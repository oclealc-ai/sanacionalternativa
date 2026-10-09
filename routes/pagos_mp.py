"""
Pagos en línea con Mercado Pago (Checkout Pro).

Ubicación sugerida: routes/pagos_mp.py  (junto a routes/pagos.py)

Flujo:
  1. pagos.py decide la pasarela (selector) y llama a crear_pago_cliente_mp()
     o crear_pago_empresa_mp(), que crean una "preferencia" en Mercado Pago
     con el access_token de la empresa que cobra y regresan la URL de pago.
  2. El usuario paga en Mercado Pago y vuelve a pago_exitoso_* / pago_fallido /
     pago_pendiente.
  3. Mercado Pago avisa a /webhook/pago_mp. Ahí NO se confía en lo que llega:
     se consulta el pago directo a la API de MP con el access_token de la
     empresa y solo si está 'approved' se registra con los mismos motores que
     usa Stripe (registrar_pago_cliente / registrar_pago_empresa).

Registrar el blueprint donde ya registras pagos_bp:
    from routes.pagos_mp import pagos_mp_bp
    app.register_blueprint(pagos_mp_bp)
"""
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

import requests
from flask import Blueprint, flash, jsonify, redirect, request, url_for
from sqlalchemy import text

from constantes import const
from modelos import Cliente, Empresa, db, movCuenta
from routes.pagos import (
    _notificar_vendedor_pago_empresa,
    _url_regreso_valida,
    registrar_pago_cliente,
    registrar_pago_empresa,
)
from whatsapp import enviar_whatsapp

logger = logging.getLogger(__name__)
pagos_mp_bp = Blueprint("pagos_mp", __name__)

MP_API = "https://api.mercadopago.com"
MP_TIMEOUT = 10  # segundos
ID_EMPRESA_CITANET = 1


# ==========================================================
# UTILERÍAS
# ==========================================================
def mp_disponible(empresa):
    """True si la empresa tiene Mercado Pago activado y con credenciales."""
    return bool(empresa and empresa.aceptaPagosEnLinea_MP and empresa.mp_access_token)


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _a_dos_decimales(monto):
    return Decimal(str(monto)).quantize(Decimal("0.01"))


def _referencia(payment_id):
    return f"Mercado Pago (Ref: {payment_id})"


def _serializar_por_empresa(id_empresa):
    """Candado por empresa para el webhook. Mercado Pago manda varias notificaciones
    del mismo pago casi al mismo tiempo (payment.created / payment.updated) y, en
    paralelo, las dos pasaban la revisión de duplicados. Aquí la segunda espera a que
    la primera haga commit; con READ COMMITTED la revisión posterior ya ve ese commit.
    Debe llamarse como PRIMERA sentencia de una transacción nueva (ver webhook)."""
    db.session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
    db.session.execute(
        text("SELECT idEmpresa FROM empresa WHERE idEmpresa = :i FOR UPDATE"),
        {"i": int(id_empresa)},
    )


def _pago_ya_registrado(id_empresa, payment_id):
    """Idempotencia: MP suele mandar varias notificaciones del mismo pago
    (payment.created / payment.updated) y reintenta si no recibe 200.
    El id del pago de MP queda guardado en movCuenta.notas, así que basta con
    buscarlo ahí (sin cambios de esquema)."""
    return movCuenta.query.filter(
        movCuenta.idEmpresa == id_empresa,
        movCuenta.notas.like(f"%{_referencia(payment_id)}%"),
    ).first() is not None


# ==========================================================
# CREAR PREFERENCIA (lo que hace "ir a pagar")
# ==========================================================
def _crear_preferencia(empresa_cobro, titulo, descripcion, monto, metadata,
                       tipo_entidad, url_exito, url_pendiente):
    """Crea la preferencia de Checkout Pro con el token de la empresa que cobra.
    Regresa (url_de_pago, None) o (None, mensaje_error)."""
    if not mp_disponible(empresa_cobro):
        return None, "Esta empresa no tiene configurado Mercado Pago para recibir pagos."

    monto = _a_dos_decimales(monto)
    if monto <= 0:
        return None, "El monto debe ser mayor a cero."

    notificacion = url_for("pagos_mp.webhook_pago_mp", _external=True) + "?" + urlencode({
        "tipo_entidad": tipo_entidad,
        "id_empresa_cobro": empresa_cobro.idEmpresa,
    })

    body = {
        "items": [{
            "id": "cargos",
            "title": titulo[:250],
            "description": (descripcion or titulo)[:250],
            "quantity": 1,
            "currency_id": "MXN",
            "unit_price": float(monto),
        }],
        "back_urls": {
            "success": url_exito,
            "failure": url_for("pagos.pago_fallido", _external=True),
            "pending": url_pendiente,
        },
        "notification_url": notificacion,
        "external_reference": f"{tipo_entidad}-{metadata.get('id_empresa')}-{metadata.get('id_cliente', '0')}",
        "metadata": metadata,
    }
    # MP solo acepta auto_return cuando las back_urls son https públicas.
    if url_exito.startswith("https://"):
        body["auto_return"] = "approved"

    try:
        resp = requests.post(
            f"{MP_API}/checkout/preferences",
            json=body,
            headers=_headers(empresa_cobro.mp_access_token),
            timeout=MP_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.error(f"Mercado Pago: no se pudo conectar para crear la preferencia: {e}")
        return None, "No fue posible conectar con Mercado Pago. Intenta de nuevo."

    if resp.status_code not in (200, 201):
        logger.error(f"Mercado Pago: error creando preferencia ({resp.status_code}): {resp.text[:500]}")
        return None, "Mercado Pago rechazó la solicitud de pago. Revisa la configuración de la empresa."

    url_pago = resp.json().get("init_point")
    if not url_pago:
        logger.error(f"Mercado Pago: la preferencia no regresó init_point: {resp.text[:500]}")
        return None, "Mercado Pago no regresó la liga de pago."
    return url_pago, None


def crear_pago_cliente_mp(id_cliente, id_empresa, monto, cargos, comision, comisionIVA,
                          conceptos_texto, url_regreso=None):
    """Equivalente MP de _crear_sesion_pago_cliente() (Stripe).
    Regresa (url_de_pago, None) o (None, mensaje_error)."""
    empresa_destino = Empresa.query.get(id_empresa)
    if not empresa_destino:
        return None, "Empresa no encontrada."

    if not conceptos_texto:
        conceptos_texto = "Pago de cargos pendientes"

    url_exito = url_for("pagos.pago_exitoso_cliente", _external=True)
    url_regreso = _url_regreso_valida(url_regreso)
    if url_regreso:
        url_exito += "?" + urlencode({"url_regreso": url_regreso})

    metadata = {
        "tipo_entidad": "cliente",
        "id_cliente": str(id_cliente),
        "id_empresa": str(id_empresa),
        "cargos": ",".join(cargos),
        "comision": str(comision),
        "comision_iva": str(comisionIVA),
        "monto_bruto": str(monto),
    }
    return _crear_preferencia(
        empresa_cobro=empresa_destino,
        titulo=f"Pago de Servicios para {empresa_destino.razonSocial} ({conceptos_texto})",
        descripcion=f"Cargos: {', '.join(cargos)}",
        monto=monto,
        metadata=metadata,
        tipo_entidad="cliente",
        url_exito=url_exito,
        url_pendiente=url_for("pagos_mp.pago_pendiente", _external=True, tipo="cliente"),
    )


def crear_pago_empresa_mp(id_empresa, monto, cargos):
    """Una empresa le paga a CitaNet (empresa 1): se cobra con el token de CitaNet.
    Regresa (url_de_pago, None) o (None, mensaje_error)."""
    empresa_citanet = Empresa.query.get(ID_EMPRESA_CITANET)
    if not empresa_citanet:
        return None, "Empresa CitaNet no encontrada."

    metadata = {
        "tipo_entidad": "empresa",
        "id_empresa": str(id_empresa),
        "cargos": ",".join(cargos),
        "monto_bruto": str(monto),
    }
    return _crear_preferencia(
        empresa_cobro=empresa_citanet,
        titulo="Pago de Plan CitaNet",
        descripcion=f"Cargos: {', '.join(cargos)}",
        monto=monto,
        metadata=metadata,
        tipo_entidad="empresa",
        url_exito=url_for("pagos.pago_exitoso_empresa", _external=True),
        url_pendiente=url_for("pagos_mp.pago_pendiente", _external=True, tipo="empresa"),
    )


# ==========================================================
# RETORNO "PAGO PENDIENTE" (OXXO, transferencia, etc.)
# ==========================================================
@pagos_mp_bp.route("/pago_mp/pendiente")
def pago_pendiente():
    flash("Tu pago quedó pendiente de confirmación. Se reflejará en tu cuenta en cuanto Mercado Pago lo apruebe.", "info")
    if request.args.get("tipo") == "empresa":
        return redirect(url_for("pagos.listar_movimientos_empresa"))
    return redirect(url_for("pagos.listar_movimientos_cliente"))


# ==========================================================
# WEBHOOK
# ==========================================================
def _crear_cargos_comision(id_empresa, id_cliente, comision, comisionIVA):
    """Mismos dos cargos (comisión + IVA) que crea el webhook de Stripe.
    Regresa (idMov_comision, idMov_iva). Solo hace flush; el commit lo hace
    registrar_pago_cliente() junto con el pago."""
    ahora = datetime.now()
    cargo_comision = movCuenta(
        idEmpresa=id_empresa, idCliente=id_cliente,
        idtipoMovimiento=const.MOV_COMISIONPL, idmetodoPago=None,
        fecha=ahora.date(), hora=ahora.time(),
        monto=comision, saldoAnterior=comision, saldo=comision,
        notas="Pago Comision por Pago en Linea",
        idUsuario=const.ID_USUARIO_SISTEMA,
    )
    cargo_iva = movCuenta(
        idEmpresa=id_empresa, idCliente=id_cliente,
        idtipoMovimiento=const.MOV_IVA, idmetodoPago=None,
        fecha=ahora.date(), hora=ahora.time(),
        monto=comisionIVA, saldoAnterior=comisionIVA, saldo=comisionIVA,
        notas="Pago de IVA de Comision por Pago en Linea",
        idUsuario=const.ID_USUARIO_SISTEMA,
    )
    db.session.add(cargo_comision)
    db.session.add(cargo_iva)
    db.session.flush()
    return cargo_comision.idMovimiento, cargo_iva.idMovimiento


@pagos_mp_bp.route("/webhook/pago_mp", methods=["POST"])
def webhook_pago_mp():
    # --- 1. ¿Qué nos avisan? MP manda JSON (type + data.id) o, en el formato
    #        viejo (IPN), query string (topic + id). Solo nos interesan pagos.
    body = request.get_json(silent=True) or {}
    tipo_notif = body.get("type") or request.args.get("type") or request.args.get("topic")
    payment_id = (body.get("data") or {}).get("id") or request.args.get("data.id") or request.args.get("id")

    if tipo_notif != "payment" or not payment_id:
        return jsonify(success=True), 200  # merchant_order, etc.: se ignoran
    payment_id = str(payment_id)

    tipo_entidad = request.args.get("tipo_entidad", "cliente")
    try:
        id_empresa_cobro = int(request.args.get("id_empresa_cobro"))
    except (TypeError, ValueError):
        logger.error("Webhook MP sin id_empresa_cobro válido")
        return jsonify(success=False), 400

    empresa_cobro = Empresa.query.get(id_empresa_cobro)
    token_mp = empresa_cobro.mp_access_token if empresa_cobro else None
    if not token_mp:
        logger.error(f"Webhook MP: la empresa {id_empresa_cobro} no tiene access_token de Mercado Pago.")
        return jsonify(success=False), 400
    # Se cierra la transacción de lectura: más abajo se abre una nueva con el candado.
    db.session.commit()

    # --- 2. Validación: se consulta el pago a MP con el token de la empresa.
    #        Así no depende de que la notificación venga firmada ni intacta.
    try:
        resp = requests.get(
            f"{MP_API}/v1/payments/{payment_id}",
            headers=_headers(token_mp),
            timeout=MP_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.error(f"Webhook MP: no se pudo consultar el pago {payment_id}: {e}")
        return jsonify(success=False), 500  # MP reintenta

    if resp.status_code == 404:
        # Ej. el botón "Simular notificación" del panel de MP manda ids falsos.
        logger.warning(f"Webhook MP: el pago {payment_id} no existe en la cuenta de la empresa {id_empresa_cobro}.")
        return jsonify(success=True), 200
    if resp.status_code != 200:
        logger.error(f"Webhook MP: consulta del pago {payment_id} falló ({resp.status_code}): {resp.text[:300]}")
        return jsonify(success=False), 500

    pago = resp.json()
    estatus = pago.get("status")
    if estatus != "approved":
        logger.info(f"Webhook MP: pago {payment_id} con estatus '{estatus}', no se registra (aún).")
        return jsonify(success=True), 200

    meta = pago.get("metadata") or {}
    id_empresa = meta.get("id_empresa")
    id_cliente = meta.get("id_cliente")
    if not id_empresa or meta.get("tipo_entidad", tipo_entidad) != tipo_entidad:
        logger.error(f"Webhook MP: metadata inconsistente en pago {payment_id}: {meta}")
        return jsonify(success=False), 400
    if tipo_entidad == "cliente" and (not id_cliente or str(id_empresa) != str(id_empresa_cobro)):
        logger.error(f"Webhook MP: el pago {payment_id} no corresponde a la empresa que cobra.")
        return jsonify(success=False), 400

    if pago.get("currency_id") != "MXN":
        logger.error(f"Webhook MP: moneda inesperada en pago {payment_id}: {pago.get('currency_id')}")
        return jsonify(success=True), 200

    # El monto sale de lo que MP realmente cobró, no de la metadata.
    monto = _a_dos_decimales(pago.get("transaction_amount") or 0)
    if monto <= 0:
        return jsonify(success=True), 200

    # --- 3. Candado + idempotencia
    try:
        _serializar_por_empresa(id_empresa)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Webhook MP: no se pudo obtener el candado para el pago {payment_id}: {e}")
        return jsonify(success=False), 500

    if _pago_ya_registrado(id_empresa, payment_id):
        db.session.rollback()  # suelta el candado
        logger.info(f"Webhook MP: el pago {payment_id} ya estaba registrado.")
        return jsonify(success=True), 200

    cargos_ids = meta.get("cargos", "") or ""
    ref = _referencia(payment_id)

    # --- 4. Registro con los motores existentes
    try:
        if tipo_entidad == "cliente":
            try:
                comision = Decimal(meta.get("comision", "0") or "0")
                # MP normaliza las llaves de metadata a snake_case (comisionIVA -> comision_iva)
                comisionIVA = Decimal(meta.get("comision_iva") or meta.get("comisionIVA") or "0")
            except InvalidOperation:
                comision = comisionIVA = Decimal("0")

            cargos_completos = cargos_ids
            if comision > 0:
                id_com, id_iva = _crear_cargos_comision(id_empresa, id_cliente, comision, comisionIVA)
                extra = f"{id_com},{id_iva}"
                cargos_completos = f"{cargos_ids},{extra}" if cargos_ids else extra

            registrar_pago_cliente(
                id_cliente_ext=id_cliente,
                id_empresa_ext=id_empresa,
                monto_ext=str(monto),
                cargos_ext=cargos_completos,
                notas_ext=f"Pago en línea {ref}",
            )
        else:
            registrar_pago_empresa(
                id_empresa_ext=id_empresa,
                monto_ext=str(monto),
                cargos_ext=cargos_ids,
                notas_ext=ref,
            )
            _notificar_vendedor_pago_empresa(id_empresa, monto)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Webhook MP: error registrando el pago {payment_id}: {e}")
        return jsonify(success=False), 500

    # registrar_pago_* atrapan sus propias excepciones (hacen rollback y flash),
    # así que se confirma que el pago de verdad quedó guardado; si no, se regresa
    # 500 para que Mercado Pago reintente la notificación.
    if not _pago_ya_registrado(id_empresa, payment_id):
        db.session.rollback()
        logger.error(f"Webhook MP: el pago {payment_id} no quedó registrado; se pedirá reintento.")
        return jsonify(success=False), 500

    # --- 5. Notificaciones por WhatsApp (best effort: si fallan, el pago ya está registrado)
    try:
        empresa_citanet = Empresa.query.get(ID_EMPRESA_CITANET)
        tel_citanet = empresa_citanet.telefono if empresa_citanet else None

        if tipo_entidad == "cliente":
            cliente = Cliente.query.get(id_cliente)
            empresa_destino = Empresa.query.get(id_empresa)
            nombre = cliente.nombreCliente if cliente else "Cliente Desconocido"
            tel_entidad = cliente.telefono if cliente else None
            msg_exito = f"CitaNet: Su pago a {empresa_destino.razonSocial} por ${monto} se registró correctamente."
            msg_admin = f"CitaNet: El cliente {nombre} pagó ${monto} a la empresa {empresa_destino.razonSocial}."
        else:
            empresa_paga = Empresa.query.get(id_empresa)
            nombre = empresa_paga.razonSocial if empresa_paga else "Empresa Desconocida"
            tel_entidad = empresa_paga.telefono if empresa_paga else None
            msg_exito = f"Su pago por ${monto} MXN se registró correctamente."
            msg_admin = f"CitaNet: Se registró un pago de la empresa {nombre} por ${monto} MXN"

        if tel_citanet:
            enviar_whatsapp(tel_citanet, msg_admin)
        if tel_entidad:
            enviar_whatsapp(tel_entidad, msg_exito)
    except Exception as e:
        logger.error(f"Webhook MP: pago {payment_id} registrado, pero falló la notificación: {e}")

    return jsonify(success=True), 200
