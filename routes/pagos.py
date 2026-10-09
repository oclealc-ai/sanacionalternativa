from flask           import Blueprint, render_template, request, redirect, url_for, session, flash, current_app, jsonify
from datetime        import datetime
from decimal         import Decimal, ROUND_HALF_UP, InvalidOperation
from modelos         import Empresa, EmpresaPlan, movCuenta, movAplica, Cliente, ClienteEmpresa, ClienteStaff, Usuario, Cita, CitaCliente, CitaProducto, db, metodoPago, tipoMovimiento, MovimientoPuntos, Vendedor, VendedorEmpresa
from routes.empresas import remanente_plan
from constantes      import const
from sqlalchemy.orm  import joinedload
from whatsapp        import enviar_whatsapp

import logging
import stripe

from urllib.parse import urlencode, urlparse

logger = logging.getLogger(__name__)
pagos_bp = Blueprint("pagos", __name__)

# ==========================================
# LISTAR MOVIMIENTOS Y ESTADO DE CUENTA
# ==========================================
@pagos_bp.route("/cliente/movimientos")
def listar_movimientos_cliente():
    id_cliente = session.get('idCliente')
    id_empresa = session.get('idEmpresa')
    
    if id_cliente:
        es_cliente = True 
    else:
        id_cliente = session.get('idClientegestionado') if session.get('idClientegestionado') else None
        es_cliente = False
    
    if not id_cliente or not id_empresa:
        return redirect(url_for('cliente.login'))
    
    cliente = Cliente.query.get(id_cliente)
    if not cliente:
        return "Cliente no encontrado", 404
    
    #logger.info(f"es_cliente: {es_cliente}, id_cliente: {id_cliente}, id_empresa: {id_empresa}")

    empresa = Empresa.query.get(id_empresa)
    if not empresa: 
        return "Empresa no encontrada", 404 

    saldo_CtexEmp = ClienteEmpresa.query.filter_by(idCliente=id_cliente, idEmpresa=id_empresa).first()
    if not saldo_CtexEmp:
        saldo_CtexEmp = ClienteEmpresa(
            idCliente=id_cliente,
            idEmpresa=id_empresa,
            saldo=0.0
        )
        db.session.add(saldo_CtexEmp)
        db.session.commit()

    # Movimientos ordenados por fecha descendente
    movimientos = movCuenta.query.filter_by(idCliente=id_cliente, idEmpresa=id_empresa)\
        .order_by(movCuenta.fecha.desc(), movCuenta.hora.desc()).all()
    
    # Para cada movimiento, traer sus aplicaciones y enriquecer con citas
    for mov in movimientos:
        # Aplicaciones donde este movimiento es CARGO
        apps_cargo_raw = movAplica.query.filter_by(idmovCargo=mov.idMovimiento).all()
        mov.aplicaciones_como_cargo = []
        for app in apps_cargo_raw:
            abono = movCuenta.query.get(app.idmovAbono)
            app_dict = {
                'idAplicacion'     : app.idAplicacion,
                'idmovCargo'       : app.idmovCargo,
                'idmovAbono'       : app.idmovAbono,
                'montoAplicado'    : float(app.montoAplicado),
                'idUsuario'        : app.idUsuario if app.idUsuario else const.ID_USUARIO_SISTEMA,
                'fechaAplicado'    : app.fechaAplicado,
                'idMovRelacionado' : abono.idMovReferencia if abono else None
            }
            mov.aplicaciones_como_cargo.append(app_dict)
        
        # Aplicaciones donde este movimiento es ABONO
        apps_abono_raw = movAplica.query.filter_by(idmovAbono=mov.idMovimiento).all()
        mov.aplicaciones_como_abono = []
        for app in apps_abono_raw:
            cargo = movCuenta.query.get(app.idmovCargo)
            app_dict = {
                'idAplicacion'     : app.idAplicacion,
                'idmovCargo'       : app.idmovCargo,
                'idmovAbono'       : app.idmovAbono,
                'montoAplicado'    : float(app.montoAplicado),
                'idUsuario'        : app.idUsuario if app.idUsuario else const.ID_USUARIO_SISTEMA,
                'fechaAplicado'    : app.fechaAplicado,
                'idMovRelacionado' : cargo.idMovReferencia if cargo else None
            }
            mov.aplicaciones_como_abono.append(app_dict)
    
    # Métodos de pago activos
    metodos_pago = metodoPago.query.filter_by(activo=True).all()
    
    if es_cliente:
        metodos_pago = [m for m in metodos_pago if m.idmetodoPago == const.PAGO_TRANSFERENCIA and m.activo]
    else:
        metodos_pago = [m for m in metodos_pago if m.idmetodoPago != const.PAGO_TRANSFERENCIA and m.activo]

    # Cargos pendientes (para el formulario de pago)
    cargos_pendientes = movCuenta.query.filter(
        movCuenta.idCliente == id_cliente,
        movCuenta.idEmpresa == id_empresa,
        movCuenta.saldo > 0
    ).join(movCuenta.tipo).filter_by(naturaleza='C')\
     .order_by(movCuenta.fecha.asc()).all()
    
    total_adeudado = Decimal(str(sum(c.saldo for c in cargos_pendientes)))
    
    return render_template('movimientos_cliente.html', 
                          movimientos=movimientos,
                          cliente=cliente,
                          empresa=empresa,
                          saldo_CtexEmp=saldo_CtexEmp,
                          metodos_pago=metodos_pago,
                          cargos_pendientes=cargos_pendientes,
                          total_adeudado=total_adeudado,
                          es_cliente=es_cliente,
                          PAGO_EN_LINEA=const.PAGO_EN_LINEA,
                          PAGO_PUNTOS=const.PAGO_PUNTOS,
                          saldo_puntos=saldo_CtexEmp.puntosLealtad or 0,
                          comisionVarPct=empresa.comisionVarPct,
                          comisionFija=empresa.comisionFija,
                          PctIVA=16)

# ==============================================
# MOTOR COMPARTIDO: aplica pagos contra cargos y
# calcula/registra puntos de lealtad (ganados o canjeados).
# Usado por registrar_pago_cliente() y por procesar_cobro_cita()
# (ver_citas.py) para que AMBOS flujos de cobro se comporten igual.
# No hace commit ni flash: eso queda a cargo de quien la invoque.
# ==============================================
def _resolver_staff_de_cargo(cargo, cache):
    """Si un cargo (movCuenta) viene de una cita, regresa el Usuario (staff)
    asignado a esa cita. None si el cargo no viene de una cita (ej. cargo
    directo) o si la cita no tiene especialista asignado."""
    if cargo.idMovimiento in cache:
        return cache[cargo.idMovimiento]

    staff = None
    if cargo.idMovReferencia and cargo.idtipoMovimiento == const.MOV_CITA:
        reserva_rel = db.session.get(CitaCliente, cargo.idMovReferencia)
        cita_rel = reserva_rel.cita if reserva_rel else None
        if cita_rel and cita_rel.idUsuario:
            staff = Usuario.query.get(cita_rel.idUsuario)

    cache[cargo.idMovimiento] = staff
    return staff


def _actualizar_pagado_productos_cita(cargo, monto_aplicado):
    if cargo.idtipoMovimiento != const.MOV_CITA or not cargo.idMovReferencia:
        return

    monto_restante = Decimal(str(monto_aplicado))
    productos_cita = CitaProducto.query.filter_by(
        idCitaCliente=cargo.idMovReferencia
    ).order_by(CitaProducto.idCitaProducto.asc()).all()
    total_productos = sum(
        (Decimal(str(producto.precioCobrado or 0)) * Decimal(str(producto.cantidad or 0))
         for producto in productos_cita),
        Decimal('0.00')
    )
    cargo_variable = max(Decimal(str(cargo.monto or 0)) - total_productos, Decimal('0.00'))
    producto_variable_id = next((
        producto.idCitaProducto
        for producto in productos_cita
        if Decimal(str(producto.precioCobrado or 0)) <= 0
    ), None) if cargo_variable > 0 else None

    for producto_cita in productos_cita:
        if monto_restante <= 0:
            break

        precio_unitario = Decimal(str(producto_cita.precioCobrado or 0))
        cantidad = Decimal(str(producto_cita.cantidad or 0))
        total_producto = precio_unitario * cantidad
        if producto_cita.idCitaProducto == producto_variable_id:
            total_producto += cargo_variable
        monto_pagado_actual = Decimal(str(producto_cita.montoPagado or 0))
        saldo_producto = max(total_producto - monto_pagado_actual, Decimal('0.00'))
        monto_producto = min(saldo_producto, monto_restante)

        if monto_producto > 0:
            producto_cita.montoPagado = monto_pagado_actual + monto_producto
            monto_restante -= monto_producto


def sincronizar_pagado_productos_cita(cargo):
    if cargo.idtipoMovimiento != const.MOV_CITA or not cargo.idMovReferencia:
        return

    monto_aplicado = sum(
        (Decimal(str(aplicacion.montoAplicado or 0))
         for aplicacion in cargo.aplicaciones_recibidas),
        Decimal('0.00')
    )
    productos_cita = CitaProducto.query.filter_by(
        idCitaCliente=cargo.idMovReferencia
    ).order_by(CitaProducto.idCitaProducto.asc()).all()

    for producto_cita in productos_cita:
        producto_cita.montoPagado = Decimal('0.00')

    _actualizar_pagado_productos_cita(cargo, monto_aplicado)


def procesar_pagos_con_puntos(id_cliente, id_empresa, id_usuario, pagos_form, cargos_seleccionados, notas_final):
    """
    pagos_form: lista de dicts {'idmetodoPago': int, 'monto': Decimal}
    cargos_seleccionados: lista de movCuenta (cargos con saldo pendiente) ya ordenados
    Retorna dict: {'aplicaciones_count', 'monto_total_aplicado', 'relacion'}

    Los puntos de lealtad se acumulan de una de dos formas, según
    Empresa.modoAcumulacionPuntos:
      - 'empresa': una sola bolsa por cliente (ClienteEmpresa.puntosLealtad),
        usando la configuración de la empresa. Se calculan sobre el total de
        cada línea de pago, igual que antes (incluye anticipos sin aplicar).
      - 'staff': una bolsa independiente por cada especialista (ClienteStaff),
        usando la configuración propia de cada Usuario. Aquí los puntos SOLO
        se generan sobre la porción de cada pago que quedó aplicada a un cargo
        que viene de una cita con especialista asignado — un anticipo que no
        se aplicó a ninguna cita todavía no genera puntos hasta que se aplique.
    """
    empresa = Empresa.query.get(id_empresa)
    relacion = ClienteEmpresa.query.filter_by(idCliente=id_cliente, idEmpresa=id_empresa).first()

    modo_puntos = empresa.modoAcumulacionPuntos if empresa else 'empresa'
    staff_por_cargo_cache = {}

    for p in pagos_form:
        p.setdefault('obj', metodoPago.query.get(p['idmetodoPago']))

    puntos_saldo_actual = Decimal(str(relacion.puntosLealtad or 0)) if relacion else Decimal('0.00')
    movimientos_puntos_a_crear = []          # bolsa única por empresa
    puntos_ganados_por_staff = {}             # {idUsuario: Decimal} bolsa por especialista
    relacion_staff_activa = None
    saldo_staff_actual = Decimal('0.00')
    staff_id_requerido = None

    if any(p['idmetodoPago'] == const.PAGO_PUNTOS for p in pagos_form):
        if modo_puntos == 'staff':
            staff_ids = []
            for cargo in cargos_seleccionados:
                staff = _resolver_staff_de_cargo(cargo, staff_por_cargo_cache)
                if staff:
                    staff_ids.append(staff.idUsuario)

            staff_ids = list(dict.fromkeys(staff_ids))
            if len(staff_ids) != 1:
                raise Exception(
                    "Para usar puntos de lealtad en este modo, todos los cargos deben pertenecer al mismo especialista."
                )

            staff_id_requerido = staff_ids[0]
            relacion_staff_activa = ClienteStaff.query.filter_by(
                idCliente=id_cliente,
                idEmpresa=id_empresa,
                idUsuario=staff_id_requerido,
            ).first()
            if not relacion_staff_activa:
                raise Exception(
                    "Este cliente no tiene puntos acumulados para ese especialista."
                )
            saldo_staff_actual = Decimal(str(relacion_staff_activa.puntosLealtad or 0))
        elif not relacion:
            raise Exception("El cliente no tiene una cuenta de puntos registrada con esta empresa.")

    aplicaciones_count = 0
    monto_total_aplicado = Decimal('0.00')

    for p in pagos_form:
        monto_pago = p['monto']
        if monto_pago <= 0:
            continue

        # --- Canje de puntos: se valida y descuenta ANTES de crear el movCuenta,
        # para poder abortar toda la transacción si no hay saldo suficiente ---
        es_pago_con_puntos = (p['idmetodoPago'] == const.PAGO_PUNTOS)
        if es_pago_con_puntos:
            if modo_puntos == 'staff':
                if staff_id_requerido is None:
                    raise Exception(
                        "No se puede usar puntos de lealtad en este pago porque los cargos no corresponden a un mismo especialista."
                    )
                if monto_pago > saldo_staff_actual:
                    raise Exception(
                        f"Saldo de puntos insuficiente para el especialista. Disponible: {saldo_staff_actual:.2f}, "
                        f"solicitado: {monto_pago:.2f}"
                    )
                saldo_staff_actual -= monto_pago
                relacion_staff_activa.puntosLealtad = saldo_staff_actual
            else:
                if monto_pago > puntos_saldo_actual:
                    raise Exception(
                        f"Saldo de puntos insuficiente. Disponible: {puntos_saldo_actual:.2f}, "
                        f"solicitado: {monto_pago:.2f}"
                    )
                puntos_saldo_actual -= monto_pago

        nuevo_pago = movCuenta(
            idEmpresa=id_empresa,
            idCliente=id_cliente,
            idtipoMovimiento=const.MOV_PAGO,
            idmetodoPago=p['idmetodoPago'],
            fecha=datetime.now().date(),
            hora=datetime.now().time(),
            monto=monto_pago,
            saldoAnterior=monto_pago,
            saldo=monto_pago,
            notas=notas_final,
            idUsuario=id_usuario
        )
        db.session.add(nuevo_pago)
        db.session.flush()

        # Habilita el otorgamiento de puntos para este renglón de pago (respeta
        # aceptaPuntosLealtad y acumulaPuntos del método), evaluado una sola vez
        # aquí porque aplica igual sin importar el modo.
        metodo_acumula = bool(p['obj'] and getattr(p['obj'], 'acumulaPuntos', True))

        monto_restante = monto_pago
        for cargo in cargos_seleccionados:
            if monto_restante <= 0:
                break
            monto_aplicado = min(cargo.saldo, monto_restante)
            if monto_aplicado <= 0:
                continue

            aplicacion = movAplica(
                idmovCargo=cargo.idMovimiento,
                idmovAbono=nuevo_pago.idMovimiento,
                montoAplicado=monto_aplicado,
                idUsuario=id_usuario,
                fechaAplicado=datetime.now()
            )
            db.session.add(aplicacion)

            cargo.saldoAnterior = cargo.saldo
            cargo.saldo -= monto_aplicado
            monto_restante -= monto_aplicado
            monto_total_aplicado += monto_aplicado
            aplicaciones_count += 1
            _actualizar_pagado_productos_cita(cargo, monto_aplicado)

            # Puntos ganados por especialista: se calculan por cada cargo aplicado,
            # ya que dos cargos del mismo pago pueden pertenecer a citas de
            # especialistas distintos.
            if (not es_pago_con_puntos) and modo_puntos == 'staff' and metodo_acumula:
                staff = _resolver_staff_de_cargo(cargo, staff_por_cargo_cache)
                if staff and staff.aceptaPuntosLealtad:
                    valor_config = Decimal(str(staff.valorPuntosLealtad or 0))
                    puntos_cargo = Decimal('0.00')

                    if staff.tipoPuntosLealtad == 'fijo':
                        puntos_cargo = valor_config
                    elif staff.tipoPuntosLealtad == 'porcentaje':
                        puntos_cargo = monto_aplicado * (valor_config / Decimal('100.00'))

                    if puntos_cargo > Decimal('0.00'):
                        puntos_ganados_por_staff[staff.idUsuario] = (
                            puntos_ganados_por_staff.get(staff.idUsuario, Decimal('0.00')) + puntos_cargo
                        )

        nuevo_pago.saldo = round(monto_pago - (monto_pago - monto_restante), 2)

        if es_pago_con_puntos:
            if modo_puntos == 'staff':
                db.session.add(MovimientoPuntos(
                    idCliente=id_cliente,
                    idEmpresa=id_empresa,
                    idMovimientoOrigen=nuevo_pago.idMovimiento,
                    idUsuarioStaff=staff_id_requerido,
                    tipo='Canjeados',
                    puntos=-monto_pago,
                    saldoResultante=saldo_staff_actual,
                    fecha=datetime.now().date(),
                    hora=datetime.now().time(),
                    idUsuario=id_usuario,
                    notas=f"Canje de puntos del especialista (Mov. {nuevo_pago.idMovimiento})",
                ))
                logger.info(
                    f"Puntos lealtad (Canjeados, por especialista {staff_id_requerido}) Cliente {id_cliente} "
                    f"Empresa {id_empresa}: {-monto_pago:.2f} pts -> saldo {saldo_staff_actual:.2f}"
                )
            else:
                # Canje: esta línea YA se pagó con puntos (se validó y descontó arriba).
                movimientos_puntos_a_crear.append({
                    'tipo': 'Canjeados',
                    'puntos': -monto_pago,
                    'saldoResultante': puntos_saldo_actual,
                    'idMovimientoOrigen': nuevo_pago.idMovimiento,
                    'idUsuarioStaff': None,
                    'notas': f"Canje de puntos como forma de pago (Mov. {nuevo_pago.idMovimiento})",
                })
        elif modo_puntos == 'empresa':
            # Puntos ganados por este renglón de pago completo (comportamiento
            # histórico: incluye anticipos aunque no se hayan aplicado a un cargo).
            if empresa and relacion and empresa.aceptaPuntosLealtad and metodo_acumula:
                valor_config = Decimal(str(empresa.valorPuntosLealtad or 0))
                puntos_pago = Decimal('0.00')

                if empresa.tipoPuntosLealtad == 'fijo':
                    puntos_pago = valor_config
                elif empresa.tipoPuntosLealtad == 'porcentaje':
                    puntos_pago = monto_pago * (valor_config / Decimal('100.00'))

                if puntos_pago > Decimal('0.00'):
                    puntos_saldo_actual += puntos_pago
                    movimientos_puntos_a_crear.append({
                        'tipo': 'Ganados',
                        'puntos': puntos_pago,
                        'saldoResultante': puntos_saldo_actual,
                        'idMovimientoOrigen': nuevo_pago.idMovimiento,
                        'idUsuarioStaff': None,
                        'notas': f"Puntos generados por pago (Mov. {nuevo_pago.idMovimiento})",
                    })
        # modo_puntos == 'staff' y no es canje: ya se acumuló arriba, por cargo,
        # en puntos_ganados_por_staff.

    # --- Actualización de saldo de cuenta (siempre, sin importar el modo) ---
    if relacion:
        relacion.saldo = calcular_saldo(id_empresa, id_cliente)

    # --- Bolsa única por empresa ---
    if relacion and movimientos_puntos_a_crear:
        relacion.puntosLealtad = puntos_saldo_actual
        for mp in movimientos_puntos_a_crear:
            db.session.add(MovimientoPuntos(
                idCliente=id_cliente,
                idEmpresa=id_empresa,
                idMovimientoOrigen=mp['idMovimientoOrigen'],
                idUsuarioStaff=mp['idUsuarioStaff'],
                tipo=mp['tipo'],
                puntos=mp['puntos'],
                saldoResultante=mp['saldoResultante'],
                fecha=datetime.now().date(),
                hora=datetime.now().time(),
                idUsuario=id_usuario,
                notas=mp['notas'],
            ))
            logger.info(
                f"Puntos lealtad ({mp['tipo']}) Cliente {id_cliente} Empresa {id_empresa}: "
                f"{mp['puntos']:.2f} pts -> saldo {mp['saldoResultante']:.2f}"
            )

    # --- Bolsas independientes por especialista ---
    for id_staff, puntos_ganados in puntos_ganados_por_staff.items():
        relacion_staff = ClienteStaff.query.filter_by(idCliente=id_cliente, idUsuario=id_staff).first()
        if not relacion_staff:
            relacion_staff = ClienteStaff(
                idCliente=id_cliente,
                idUsuario=id_staff,
                idEmpresa=id_empresa,
                puntosLealtad=Decimal('0.00')
            )
            db.session.add(relacion_staff)
            db.session.flush()

        saldo_anterior_staff = Decimal(str(relacion_staff.puntosLealtad or 0))
        saldo_nuevo_staff = saldo_anterior_staff + puntos_ganados
        relacion_staff.puntosLealtad = saldo_nuevo_staff

        db.session.add(MovimientoPuntos(
            idCliente=id_cliente,
            idEmpresa=id_empresa,
            idMovimientoOrigen=None,
            idUsuarioStaff=id_staff,
            tipo='Ganados',
            puntos=puntos_ganados,
            saldoResultante=saldo_nuevo_staff,
            fecha=datetime.now().date(),
            hora=datetime.now().time(),
            idUsuario=id_usuario,
            notas=f"Puntos generados con especialista (Usuario {id_staff})",
        ))
        logger.info(
            f"Puntos lealtad (Ganados, por especialista {id_staff}) Cliente {id_cliente} "
            f"Empresa {id_empresa}: {puntos_ganados:.2f} pts -> saldo {saldo_nuevo_staff:.2f}"
        )

    return {
        'aplicaciones_count': aplicaciones_count,
        'monto_total_aplicado': monto_total_aplicado,
        'relacion': relacion,
    }


# ==============================================
# REGISTRAR NUEVO PAGO CLIENTE (MOTOR UNIVERSAL)
# ==============================================

@pagos_bp.route("/cliente/registrar_pago_cliente", methods=['POST', 'GET'])
def registrar_pago_cliente(id_cliente_ext=None, id_empresa_ext=None, monto_ext=None, cargos_ext=None, notas_ext=None):

    # pagos_form: lista de dicts {'idmetodoPago': int, 'monto': Decimal}
    # Igual que en procesar_cobro_cita, un mismo pago puede repartirse en varias formas de pago,
    # cada una genera su propio movCuenta (MOV_PAGO) aunque todas pertenezcan al mismo cobro.
    if request.method == 'POST' and request.form:
        id_cliente = request.form.get('id_cliente') or id_cliente_ext or session.get('idCliente')
        cargos = request.form.getlist('cargos_seleccionados') or cargos_ext
        ref_libre = request.form.get('referencia', '')
        notas = ref_libre.strip() if ref_libre else None

        ids_metodo = request.form.getlist('idmetodoPago[]')
        montos_pago = request.form.getlist('montoPago[]')

        pagos_form = []
        for idm, mto in zip(ids_metodo, montos_pago):
            try:
                idm_int = int(idm)
                mto_dec = Decimal(str(mto))
            except (TypeError, ValueError, InvalidOperation):
                continue
            if idm_int > 0 and mto_dec > 0:
                pagos_form.append({'idmetodoPago': idm_int, 'monto': mto_dec})

        # Compatibilidad hacia atrás por si algún caller viejo todavía manda un solo 'metodo_pago'
        if not pagos_form:
            metodo_pago_legacy = request.form.get('metodo_pago')
            monto_legacy = request.form.get('monto') or monto_ext
            if metodo_pago_legacy and str(metodo_pago_legacy).isdigit() and monto_legacy:
                try:
                    pagos_form = [{'idmetodoPago': int(metodo_pago_legacy), 'monto': Decimal(str(monto_legacy))}]
                except (ValueError, InvalidOperation):
                    pagos_form = []
    else:
        id_cliente = id_cliente_ext or session.get('idCliente')
        cargos = cargos_ext
        notas = notas_ext
        monto_dec = Decimal(str(monto_ext)) if monto_ext else Decimal('0.00')
        pagos_form = [{'idmetodoPago': const.PAGO_EN_LINEA, 'monto': monto_dec}] if monto_dec > 0 else []

    id_empresa = id_empresa_ext or session.get('idEmpresa')
    id_usuario = session.get('idUsuario') or const.ID_USUARIO_SISTEMA

    if not id_cliente or not id_empresa:
        flash("No autenticado", "danger")
        return redirect(url_for('cliente.login'))

    if not pagos_form:
        flash("Debe agregar al menos una forma de pago con un monto válido", "danger")
        return redirect(url_for('pagos.listar_movimientos_cliente'))

    try:
        if cargos:
            if isinstance(cargos, str):
                cargos_ids = [int(c) for c in cargos.split(',') if c.strip()]
            else:
                cargos_ids = [int(c) for c in cargos]
        else:
            cargos_ids = request.form.getlist('cargos_seleccionados')
            cargos_ids = [int(c) for c in cargos_ids] if cargos_ids else []

        total_pago = sum((p['monto'] for p in pagos_form), Decimal('0.00'))
        if total_pago <= 0:
            flash("El monto debe ser mayor a cero", "danger")
            return redirect(url_for('pagos.listar_movimientos_cliente'))

        total_cargos = movCuenta.query.filter(
            movCuenta.idCliente == id_cliente,
            movCuenta.idEmpresa == id_empresa,
            movCuenta.saldo > 0
        ).join(movCuenta.tipo).filter_by(naturaleza='C').order_by(movCuenta.fecha.asc(), movCuenta.hora.asc())

        if cargos_ids:
            cargos_seleccionados = total_cargos.filter(movCuenta.idMovimiento.in_(cargos_ids)).all()
        else:
            cargos_seleccionados = total_cargos.all()

        total_adeudado = sum((c.saldo for c in cargos_seleccionados), Decimal('0.00'))

        # Adjuntamos el objeto metodoPago y si es efectivo a cada renglón de pago
        for p in pagos_form:
            p['obj'] = metodoPago.query.get(p['idmetodoPago'])
            p['es_efectivo'] = bool(p['obj'] and 'efectivo' in p['obj'].nombre.lower())

        # --- Cambio físico en efectivo ---
        # Si el total pagado supera lo adeudado y parte del excedente viene de efectivo,
        # ese excedente se entrega como cambio físico y no se registra como crédito a favor
        # (igual que el comportamiento previo de esta función, ahora repartido entre métodos).
        exceso = (total_pago - total_adeudado) if (cargos_ids and total_adeudado > 0) else Decimal('0.00')
        cambio_efectivo = Decimal('0.00')
        if exceso > 0:
            restante_exceso = exceso
            for p in pagos_form:
                if restante_exceso <= 0:
                    break
                if p['es_efectivo']:
                    reduccion = min(p['monto'], restante_exceso)
                    p['monto'] -= reduccion
                    cambio_efectivo += reduccion
                    restante_exceso -= reduccion
            total_pago -= cambio_efectivo

        notas_final = notas
        if not notas_final or notas_final.strip() == '':
            if cambio_efectivo > Decimal('0.01'):
                notas_final = f"Pago con cambio de ${cambio_efectivo:,.2f}"
            elif not cargos_ids or total_adeudado <= 0:
                notas_final = "Pago adelantado / Abono libre"
            else:
                notas_final = "Pago registrado"

        # Motor compartido: crea los movCuenta de pago, los aplica contra los
        # cargos seleccionados, y calcula/registra puntos de lealtad.
        resultado = procesar_pagos_con_puntos(
            id_cliente=id_cliente,
            id_empresa=id_empresa,
            id_usuario=id_usuario,
            pagos_form=pagos_form,
            cargos_seleccionados=cargos_seleccionados,
            notas_final=notas_final,
        )
        aplicaciones_count = resultado['aplicaciones_count']

        db.session.commit()
        logger.info(f"Pago registrado y aplicado - ID Cliente: {id_cliente}, ID Empresa: {id_empresa}, Total: {total_pago:,.2f}, Formas de pago: {len(pagos_form)}, Cargos aplicados: {aplicaciones_count}")

        mensaje = f"Pago de ${total_pago:,.2f} registrado en {len(pagos_form)} forma(s) de pago y aplicado a {aplicaciones_count} cargo(s)"
        if cambio_efectivo > Decimal('0.01'):
            mensaje += f" | Cambio: ${cambio_efectivo:,.2f} - Entregado al cliente"

        flash(mensaje, "success")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error registrando pago cliente: {e}")
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for('pagos.listar_movimientos_cliente'))



# ==========================================
# LISTAR MOVIMIENTOS Y ESTADO DE CUENTA

# ==========================================
@pagos_bp.route("/empresa/movimientos")
def listar_movimientos_empresa():
    id_empresa = session.get('idEmpresa')
        
    if not id_empresa:
        return redirect(url_for('login'))
    
    empresa = Empresa.query.filter_by(idEmpresa=id_empresa).first()
    
    # Movimientos ordenados por fecha descendente
    movimientos = movCuenta.query.filter_by(idCliente=None, idEmpresa=id_empresa)\
        .order_by(movCuenta.fecha.desc(), movCuenta.hora.desc()).all()
    
    # Para cada movimiento, traer sus aplicaciones
    for mov in movimientos:
        # Aplicaciones donde este movimiento es CARGO
        apps_cargo_raw = movAplica.query.filter_by(idmovCargo=mov.idMovimiento).all()
        mov.aplicaciones_como_cargo = []
        for app in apps_cargo_raw:
            abono = movCuenta.query.get(app.idmovAbono)
            app_dict = {
                'idAplicacion'     : app.idAplicacion,
                'idmovCargo'       : app.idmovCargo,
                'idmovAbono'       : app.idmovAbono,
                'montoAplicado'    : float(app.montoAplicado),
                'idUsuario'        : app.idUsuario if app.idUsuario else const.ID_USUARIO_SISTEMA,
                'fechaAplicado'    : app.fechaAplicado,
                'idMovReferencia'  : abono.idMovReferencia if abono else None
            }
            mov.aplicaciones_como_cargo.append(app_dict)
        
        # Aplicaciones donde este movimiento es ABONO
        apps_abono_raw = movAplica.query.filter_by(idmovAbono=mov.idMovimiento).all()
        mov.aplicaciones_como_abono = []
        for app in apps_abono_raw:
            cargo = movCuenta.query.get(app.idmovCargo)
            app_dict = {
                'idAplicacion'     : app.idAplicacion,
                'idmovCargo'       : app.idmovCargo,
                'idmovAbono'       : app.idmovAbono,
                'montoAplicado'    : float(app.montoAplicado),
                'idUsuario'        : app.idUsuario if app.idUsuario else const.ID_USUARIO_SISTEMA,
                'fechaAplicado'    : app.fechaAplicado,
                'idMovReferencia'  : cargo.idMovReferencia if cargo else None
            }
            mov.aplicaciones_como_abono.append(app_dict)
    
    # Métodos de pago activos
    metodos_pago = metodoPago.query.filter_by(activo=True).all()
        
    # Cargos pendientes (para el formulario de pago)
    cargos_pendientes = movCuenta.query.filter(
        movCuenta.idCliente == None,
        movCuenta.idEmpresa == id_empresa,
        movCuenta.saldo > 0
    ).join(movCuenta.tipo).filter_by(naturaleza='C')\
     .order_by(movCuenta.fecha.asc()).all()
    
    total_adeudado = sum(c.saldo for c in cargos_pendientes)
    remanente_actual  = remanente_plan(id_empresa)
    return render_template('movimientos_empresa.html', 
                          movimientos=movimientos,
                          metodos_pago=metodos_pago,
                          cargos_pendientes=cargos_pendientes,
                          total_adeudado=total_adeudado,
                          empresa=empresa,
                          PAGO_EN_LINEA=const.PAGO_EN_LINEA,
                          remanente_plan=remanente_actual)
    
# ===============================================
# REGISTRAR NUEVO PAGO EMPRESA (MOTOR UNIVERSAL)
# ===============================================

@pagos_bp.route("/empresa/registrar_pago_empresa", methods=['POST', 'GET'])
def registrar_pago_empresa(id_empresa_ext=None, monto_ext=None, cargos_ext=None, notas_ext=None):
    
    id_empresa = id_empresa_ext or session.get('idEmpresa')
    id_usuario = session.get('idUsuario') or const.ID_USUARIO_SISTEMA 
    
    if not id_usuario or not id_empresa:
        flash("Empresa o usuario no encontrado", "danger")
        return redirect(url_for('index'))
    
    try:
        if monto_ext is not None:
            monto_pago = Decimal(str(monto_ext))
        else:
            monto_pago = Decimal(request.form.get('monto', '0'))

        id_metodo_pago = const.PAGO_EN_LINEA 
        notes = notas_ext or request.form.get('notas', 'Pago registrado en línea')
        
        # Manejo de cargos (pueden venir como lista o string separado por comas)
        if cargos_ext:
            if isinstance(cargos_ext, str):
                cargos_ids = [int(c) for c in cargos_ext.split(',') if c.strip()]
            else:
                cargos_ids = [int(c) for c in cargos_ext]
        else:
            cargos_ids = request.form.getlist('cargos')
            cargos_ids = [int(c) for c in cargos_ids] if cargos_ids else []
        
        # Validaciones básicas
        if monto_pago <= 0:
            flash("El monto debe ser mayor a cero", "danger")
            return redirect(url_for('pagos.listar_movimientos_empresa'))
        
        # Obtener cargos pendientes de la empresa
        total_cargos = movCuenta.query.filter(
            movCuenta.idCliente == None,
            movCuenta.idEmpresa == id_empresa,
            movCuenta.saldo > 0
        ).join(movCuenta.tipo).filter_by(naturaleza='C').order_by(movCuenta.fecha.asc(), movCuenta.hora.asc())

        if cargos_ids:
            cargos_seleccionados = total_cargos.filter(movCuenta.idMovimiento.in_(cargos_ids)).all()
        else:
            cargos_seleccionados = total_cargos.all()
        
        metodo_pago_obj = metodoPago.query.get(id_metodo_pago)
        es_efectivo = metodo_pago_obj and 'efectivo' in metodo_pago_obj.nombre.lower()
        
        total_adeudado = sum(c.saldo for c in cargos_seleccionados)
        cambio = monto_pago - total_adeudado
        
        if es_efectivo and cambio > 0:
            monto_pago_principal = total_adeudado
            tiene_cambio = True
        else:
            monto_pago_principal = monto_pago
            tiene_cambio = cambio > 0
        
        notas_final = notes
        if tiene_cambio and cambio > Decimal('0.01'):
            if not notes or notes.strip() == '':
                if not cargos_ids or total_adeudado <= 0:
                    notas_final = f"Pago adelantado de ${cambio:,.2f}"
                else:
                    notas_final = f"Pago con cambio de ${cambio:,.2f}"
            else:
                notas_final = f"{notes}"
        
        monto_restante = monto_pago_principal
        monto_total_aplicado = Decimal('0')
        
        for cargo in cargos_seleccionados:
            if monto_restante <= 0: break
            monto_aplicado = min(cargo.saldo, monto_restante)
            if monto_aplicado > 0:
                monto_total_aplicado += monto_aplicado
                monto_restante -= monto_aplicado
        
        saldo_final_pago = monto_pago_principal - monto_total_aplicado
        
        nuevo_pago = movCuenta(
            idEmpresa=id_empresa,
            idCliente=None,
            idtipoMovimiento=const.MOV_PAGO,
            idmetodoPago=id_metodo_pago,
            fecha=datetime.now().date(),
            hora=datetime.now().time(),
            monto=monto_pago_principal,
            saldoAnterior=monto_pago_principal,
            saldo=saldo_final_pago,
            notas=notas_final,
            idUsuario=id_usuario
        )
        db.session.add(nuevo_pago)
        db.session.flush() # Para obtener el ID del nuevo pago
        
        monto_restante = monto_pago_principal
        aplicaciones_count = 0
        
        for cargo in cargos_seleccionados:
            if monto_restante <= 0: break
            
            monto_aplicado = min(cargo.saldo, monto_restante)
            if monto_aplicado <= 0: continue
            
            aplicacion = movAplica(
                idmovCargo=cargo.idMovimiento,
                idmovAbono=nuevo_pago.idMovimiento,
                montoAplicado=monto_aplicado,
                idUsuario=id_usuario,
                fechaAplicado=datetime.now()
            )
            db.session.add(aplicacion)
            
            cargo.saldoAnterior = cargo.saldo
            cargo.saldo -= monto_aplicado
            monto_restante -= monto_aplicado
            aplicaciones_count += 1
            
            if cargo.idtipoMovimiento == const.MOV_PLAN and cargo.saldo <= 0:
                plan_a_activar = EmpresaPlan.query.filter_by(idEmpresaPlan=cargo.idMovReferencia).first()
                if plan_a_activar:
                    plan_a_activar.estatusPlan = 'activa'
                            
        
        # 5. ACTUALIZAR SALDO GLOBAL EMPRESA
        empresa = Empresa.query.get(id_empresa)
        empresa.saldo = calcular_saldo(id_empresa)
        
        db.session.commit()
        flash(f"Pago de ${monto_pago_principal:,.2f} procesado correctamente.", "success")
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error en motor de pago: {e}")
        flash(f"Error al registrar pago: {str(e)}", "danger")
    
    return redirect(url_for('pagos.listar_movimientos_empresa'))

# ==========================================
# SELECTOR DE PASARELA DE PAGO EN LINEA
# ==========================================
def _pasarelas_disponibles(empresa_cobro):
    """Pasarelas con las que la empresa que COBRA puede recibir un pago en línea.
    Para agregar otra (ej. PayPal) basta con sumar aquí su condición y su rama
    en pago_en_linea_cliente() / pago_en_linea_empresa()."""
    disponibles = []
    if empresa_cobro and empresa_cobro.stripe_secret_key:
        disponibles.append({
            'id': 'stripe', 'nombre': 'Stripe',
            'descripcion': 'Tarjeta de crédito o débito',
            'icono': 'fab fa-stripe',
        })
    if empresa_cobro and empresa_cobro.aceptaPagosEnLinea_MP and empresa_cobro.mp_access_token:
        disponibles.append({
            'id': 'mercadopago', 'nombre': 'Mercado Pago',
            'descripcion': 'Tarjeta, saldo en Mercado Pago, OXXO y más',
            'icono': 'fas fa-wallet',
        })
    return disponibles


def _resolver_pasarela(pasarelas):
    """Regresa el id de la pasarela a usar: la que el usuario eligió (si es válida)
    o la única disponible. Regresa None si hay que mostrar la pantalla de selección."""
    ids = [p['id'] for p in pasarelas]
    elegida = request.form.get('pasarela')
    if elegida in ids:
        return elegida
    if len(ids) == 1:
        return ids[0]
    return None


def _render_selector_pasarela(pasarelas, action_url, monto, nombre_destino, url_cancelar):
    """Pantalla "¿Cómo quieres pagar?". Reenvía como hidden TODOS los campos del
    formulario original, y el botón elegido agrega 'pasarela' al mismo endpoint."""
    campos = [(k, v) for k, valores in request.form.lists() if k != 'pasarela' for v in valores]
    return render_template(
        'elegir_pasarela.html',
        pasarelas=pasarelas, campos=campos, action_url=action_url,
        monto=monto, nombre_destino=nombre_destino, url_cancelar=url_cancelar,
    )


# ==========================================
# CREAR SESIONES DE CHECKOUT STRIPE
# ==========================================
def _url_regreso_valida(url_regreso):
    """Solo se acepta una ruta propia relativa (empieza con "/", sin dominio
    ni "//"), para no abrir la puerta a un open-redirect si algún día
    url_regreso llegara a depender de un valor externo."""
    if not url_regreso:
        return None
    partes = urlparse(url_regreso)
    if partes.netloc or partes.scheme or not url_regreso.startswith('/') or url_regreso.startswith('//'):
        return None
    return url_regreso


def _success_url_cliente(url_regreso=None):
    """success_url de Stripe para pagos de cliente: siempre pasa por
    pago_exitoso_cliente() (que hace el flash de confirmación), y le agrega
    url_regreso solo si viene y es una ruta propia válida."""
    base = url_for('pagos.pago_exitoso_cliente', _external=True) + "?session_id={CHECKOUT_SESSION_ID}"
    url_regreso = _url_regreso_valida(url_regreso)
    if url_regreso:
        base += "&" + urlencode({"url_regreso": url_regreso})
    return base


# ==============================================
# MOTOR COMPARTIDO: crea la sesión de Stripe para un pago de cliente.
# No hace redirect ni flash: eso queda a cargo de quien la invoque.
# La usan tanto pago_en_linea_cliente() (flujo normal del estado de
# cuenta) como cualquier otro flujo que necesite mandar a un cliente
# directo a Stripe a pagar uno o varios cargos puntuales (ej. el botón
# "Pendiente de pago" del listado de publicidad).
# ==============================================
def _crear_sesion_pago_cliente(id_cliente, id_empresa, monto, cargos, comision, comisionIVA, conceptos_texto, url_regreso=None):
    """Crea la sesión de Stripe para un pago de cliente.
    Regresa (checkout_session, None) si todo salió bien, o (None, mensaje_error) si no.

    url_regreso: ruta propia de CitaNet (relativa, empieza con "/") a la que se
    quiere volver después de un pago exitoso, en vez del estado de cuenta por
    defecto. Si no se manda, el comportamiento es exactamente el de siempre
    (pago_exitoso_cliente() redirige a listar_movimientos_cliente). Pensado
    para que cualquier pantalla que mande a un cliente directo a pagar un
    cargo puntual (como el listado de publicidad) pueda regresarlo a sí misma."""
    empresa_destino = Empresa.query.get(id_empresa)

    if not empresa_destino or not empresa_destino.stripe_secret_key:
        return None, "Esta empresa no tiene configurada su cuenta de Stripe para recibir pagos."

    stripe.api_key = empresa_destino.stripe_secret_key

    # Si por alguna razón viene vacío, asignamos un texto por defecto
    if not conceptos_texto:
        conceptos_texto = "Pago de cargos pendientes"

    try:
        monto_centavos = int(monto * 100)
        nombre_producto_stripe = f"Pago de Servicios para {empresa_destino.razonSocial} ({conceptos_texto})"
        if len(nombre_producto_stripe) > 250:
            nombre_producto_stripe = nombre_producto_stripe[:247] + "..."

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[
                {
                    'price_data': {
                        'currency': 'mxn',
                        'unit_amount': monto_centavos,
                        'product_data': {
                            'name': nombre_producto_stripe,
                            'description': f"Cargos: {', '.join(cargos)}",
                        },
                    },
                    'quantity': 1,
                },
            ],
            mode='payment',
            metadata={
                "tipo_entidad"  : "cliente", 
                "id_cliente"    : id_cliente,
                "id_empresa"    : id_empresa,
                "cargos"        : ",".join(cargos),
                "comision"      : str(comision),
                "comisionIVA"   : str(comisionIVA),
                "monto_bruto"   : str(monto)  # lo que realmente se le cobra al cliente en Stripe
            },
            success_url=_success_url_cliente(url_regreso),
            cancel_url=url_for('pagos.pago_fallido', _external=True),
        )

        return checkout_session, None

    except Exception as e:
        logger.error(f"Error al crear sesión de Stripe Cliente: {str(e)}")
        return None, "Ocurrió un error al conectar con el sistema de pagos."


@pagos_bp.route("/cliente/pago_en_linea_cliente", methods=['POST'])
def pago_en_linea_cliente():
    monto_str   = request.form.get('monto')
    monto       = Decimal(monto_str) if monto_str else Decimal('0.00')
    cargos      = request.form.getlist('cargos_seleccionados')
    comision    = Decimal(request.form.get('comision', '0.00'))
    comisionIVA = Decimal(request.form.get('comisionIVA', '0.00'))
    id_empresa  = session.get('idEmpresa')
    id_cliente  = session.get('idCliente')

    if not id_cliente or not id_empresa:
        flash("Sesión no válida", "danger")
        return redirect(url_for('cliente.login'))

    # Recuperamos la lista de conceptos concatenados
    descripcion_conceptos = request.form.get('conceptos_texto')

    empresa_destino = Empresa.query.get(id_empresa)
    url_estado_cuenta = url_for('pagos.listar_movimientos_cliente')

    # --- Pasarelas con las que esta empresa puede cobrar ---
    pasarelas = _pasarelas_disponibles(empresa_destino)
    if not pasarelas:
        flash("Esta empresa no tiene configurada ninguna pasarela para recibir pagos en línea.", "danger")
        return redirect(url_estado_cuenta)

    pasarela = _resolver_pasarela(pasarelas)
    if pasarela is None:
        # Hay más de una: el cliente elige.
        return _render_selector_pasarela(
            pasarelas=pasarelas,
            action_url=url_for('pagos.pago_en_linea_cliente'),
            monto=monto,
            nombre_destino=empresa_destino.razonSocial,
            url_cancelar=url_estado_cuenta,
        )

    if pasarela == 'mercadopago':
        from routes.pagos_mp import crear_pago_cliente_mp   # import local: evita import circular
        url_pago, error = crear_pago_cliente_mp(
            id_cliente=id_cliente, id_empresa=id_empresa, monto=monto, cargos=cargos,
            comision=comision, comisionIVA=comisionIVA, conceptos_texto=descripcion_conceptos,
        )
        if error:
            flash(error, "danger")
            return redirect(url_estado_cuenta)
        return redirect(url_pago, code=303)

    # --- Stripe (flujo de siempre) ---
    checkout_session, error = _crear_sesion_pago_cliente(
        id_cliente=id_cliente,
        id_empresa=id_empresa,
        monto=monto,
        cargos=cargos,
        comision=comision,
        comisionIVA=comisionIVA,
        conceptos_texto=descripcion_conceptos,
    )

    if error:
        flash(error, "danger")
        # OJO: ya no se usa request.referrer, porque si el usuario venía de la
        # pantalla de selección el referrer sería esta misma ruta (solo POST).
        return redirect(url_estado_cuenta)

    return redirect(checkout_session.url, code=303)

@pagos_bp.route("/empresa/pago_en_linea_empresa", methods=['POST'])
def pago_en_linea_empresa():
    # 1. Recoger datos del formulario
    monto_str = request.form.get('monto')
    monto = Decimal(monto_str) if monto_str else Decimal('0.00')
    cargos = request.form.getlist('cargos-seleccionados')
    id_empresa = session.get('idEmpresa')
    id_empresa_citanet = 1
    url_estado_cuenta = url_for('pagos.listar_movimientos_empresa')

    # 2. Validaciones iniciales
    empresa = Empresa.query.get(id_empresa)
    if not empresa:
        flash("Empresa no encontrada", "danger")
        return redirect(url_for('index'))

    empresa_citanet = Empresa.query.get(id_empresa_citanet)
    if not empresa_citanet:
        flash("Empresa CitaNet no encontrada", "danger")
        return redirect(url_for('index'))

    # 3. La empresa le paga a CitaNet, así que las pasarelas son las de CitaNet
    pasarelas = _pasarelas_disponibles(empresa_citanet)
    if not pasarelas:
        flash("La plataforma CitaNet no tiene configurada ninguna pasarela de pago.", "danger")
        return redirect(url_estado_cuenta)

    pasarela = _resolver_pasarela(pasarelas)
    if pasarela is None:
        return _render_selector_pasarela(
            pasarelas=pasarelas,
            action_url=url_for('pagos.pago_en_linea_empresa'),
            monto=monto,
            nombre_destino="CitaNet",
            url_cancelar=url_estado_cuenta,
        )

    if pasarela == 'mercadopago':
        from routes.pagos_mp import crear_pago_empresa_mp   # import local: evita import circular
        url_pago, error = crear_pago_empresa_mp(id_empresa=id_empresa, monto=monto, cargos=cargos)
        if error:
            flash(error, "danger")
            return redirect(url_estado_cuenta)
        return redirect(url_pago, code=303)

    # --- Stripe (flujo de siempre) ---
    stripe.api_key = empresa_citanet.stripe_secret_key

    try:
        monto_centavos = int(monto * 100)

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[
                {
                    'price_data': {
                        'currency': 'mxn',
                        'unit_amount': monto_centavos,
                        'product_data': {
                            'name': 'Pago de Plan CitaNet',
                            'description': f"Cargos: {', '.join(cargos)}",
                        },
                    },
                    'quantity': 1,
                },
            ],
            mode='payment',

            metadata={
                "tipo_entidad": "empresa", # Identificador para el Webhook
                "id_empresa": id_empresa,
                "cargos": ",".join(cargos),
                "monto_original": str(monto),
                "monto_bruto": str(monto)
            },
            success_url=url_for('pagos.pago_exitoso_empresa', _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for('pagos.pago_fallido', _external=True),
        )

        return redirect(checkout_session.url, code=303)

    except Exception as e:
        logger.error(f"Error al crear sesión de Stripe: {str(e)}")
        flash("Ocurrió un error al conectar con el sistema de pagos.", "danger")
        return redirect(url_estado_cuenta)



@pagos_bp.route("/cliente/pago_exitoso")
def pago_exitoso_cliente():
    flash("¡Gracias! Tu pago ha sido recibido y se verá reflejado en unos momentos.", "success")
    url_regreso = _url_regreso_valida(request.args.get('url_regreso'))
    return redirect(url_regreso or url_for('pagos.listar_movimientos_cliente'))


@pagos_bp.route("/empresa/pago_exitoso")
def pago_exitoso_empresa():
    session_id = request.args.get('session_id')
    try:
        flash("¡Gracias! Tu pago ha sido recibido y se verá reflejado en unos momentos.", "success")
        return redirect(url_for('pagos.listar_movimientos_empresa'))
    except Exception as e:
        logger.error(f"Error al procesar: {e}")
        return redirect(url_for('pagos.listar_movimientos_empresa'))
    
@pagos_bp.route("/pago_fallido")
def pago_fallido():
    flash("El pago fue cancelado o no pudo completarse.", "warning")
    return redirect(url_for('index'))


def _notificar_vendedor_pago_empresa(id_empresa, monto_pago):
    if not id_empresa or monto_pago is None:
        return

    try:
        monto_pago_decimal = Decimal(str(monto_pago))
        relacion = VendedorEmpresa.query.filter_by(idEmpresa=id_empresa, activo=True).order_by(VendedorEmpresa.fechaRegistro.desc()).first()
        if not relacion:
            return

        vendedor = Vendedor.query.get(relacion.idVendedor)
        if not vendedor or not vendedor.telefono:
            return

        empresa = Empresa.query.get(id_empresa)
        nombre_empresa = empresa.razonSocial if empresa else 'la empresa'

        mensaje = (
            f"📣 La empresa {nombre_empresa} acaba de pagar ${monto_pago_decimal:,.2f} a CitaNet. "
            f"Tu comisión asociada ya quedó registrada para revisión en tu dashboard."
        )
        enviar_whatsapp(vendedor.telefono, mensaje, idEmpresaEnvia=1)
        logger.info(f"WhatsApp de pago a vendedor enviado: vendedor={vendedor.idVendedor}, empresa={id_empresa}, monto={monto_pago_decimal:,.2f}")
    except Exception as e:
        logger.error(f"Error enviando WhatsApp al vendedor por pago de empresa: {e}")


# ==========================================
# WEBHOOK CENTRALIZADO (STRIPE)
# ==========================================
@pagos_bp.route("/webhook/pago_stripe", methods=['POST'])
def webhook_pago_stripe():
    logger.info("Webhook Stripe Recibido")

    payload = request.get_data()
    sig_header = request.environ.get('HTTP_STRIPE_SIGNATURE')

    # === PASO 1: EXTRAEMOS TODO DE UNA VEZ EN EL DICT SEGURO ===
    try:
        import json
        event_data = json.loads(payload)
        stripe_session = event_data['data']['object']
        
        # Como aquí 'stripe_session' es un dict de Python, .get() nunca falla
        meta = stripe_session.get('metadata', {})
        
        # Sacamos absolutamente todas las variables que usaremos en la función
        tipo_entidad   = meta.get('tipo_entidad', 'empresa')
        id_empresa     = meta.get('id_empresa')
        id_cliente     = meta.get('id_cliente')
        monto_bruto    = meta.get('monto_bruto') or meta.get('monto_original') or '0'
        comision       = Decimal(meta.get('comision', '0') or '0')
        comisionIVA    = Decimal(meta.get('comisionIVA', '0') or '0')
        cargos_ids     = meta.get('cargos', '')
        
        # También la referencia del pago (payment_intent)
        id_transaccion = stripe_session.get('payment_intent', 'N/A')

        # Creamos los movCuenta de las 2 comisiones (solo aplica al flujo de pago
        # en línea del cliente, y solo si de verdad hubo comisión que cobrar)
        id_mov_comision = None
        id_mov_comisionIVA = None

        if tipo_entidad == 'cliente' and comision > 0:
            Comision = movCuenta(
                idEmpresa=id_empresa,
                idCliente=id_cliente,
                idtipoMovimiento=const.MOV_COMISIONPL,
                idmetodoPago=None,
                fecha=datetime.now().date(),
                hora=datetime.now().time(),
                monto=comision,
                saldoAnterior=comision,
                saldo=comision,
                notas="Pago Comision por Pago en Linea",
                idUsuario=const.ID_USUARIO_SISTEMA
            )
            db.session.add(Comision)

            ComisionIVA = movCuenta(
                idEmpresa=id_empresa,
                idCliente=id_cliente,
                idtipoMovimiento=const.MOV_IVA,
                idmetodoPago=None,
                fecha=datetime.now().date(),
                hora=datetime.now().time(),
                monto=comisionIVA,
                saldoAnterior=comisionIVA,
                saldo=comisionIVA,
                notas="Pago de IVA de Comision por Pago en Linea",
                idUsuario=const.ID_USUARIO_SISTEMA
            )
            db.session.add(ComisionIVA)

            # flush (no commit) para que ambos obtengan idMovimiento y podamos
            # incluirlos en la lista de cargos que se van a liquidar junto con
            # el pago, dentro de la misma transacción/sesión.
            db.session.flush()
            id_mov_comision = Comision.idMovimiento
            id_mov_comisionIVA = ComisionIVA.idMovimiento
        
        #logger.info(f"Metadatos extraídos con éxito de forma segura -> Empresa: {id_empresa}, Cliente: {id_cliente}")
        
    except Exception as e:
        logger.error(f"Error parseando el payload JSON inicial: {e}")
        return jsonify(success=False), 400

    if not id_empresa:
        logger.error("El webhook recibido no contiene el id_empresa en los metadatos.")
        return jsonify(success=False), 400

    # === PASO 2: VALIDACIÓN DE FIRMA ===
    id_empresa_llaves = 1 if tipo_entidad == 'empresa' else int(id_empresa)
    
    empresa_duena_cuenta = Empresa.query.get(id_empresa_llaves)
    if not empresa_duena_cuenta or not empresa_duena_cuenta.stripe_webhook_secret:
        logger.error(f"La empresa ID {id_empresa_llaves} no tiene configurado su stripe_webhook_secret.")
        return jsonify(success=False), 400
        
    endpoint_secret = empresa_duena_cuenta.stripe_webhook_secret 
    
    try:
        stripe.api_key = empresa_duena_cuenta.stripe_secret_key
        # Validamos que el webhook sí venga de Stripe y no esté alterado
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        logger.error(f"Error de firma en webhook dinámico: {e}")
        return jsonify(success=False), 400

    # === PASO 3: PROCESAMIENTO (Usando las variables del Paso 1) ===
    if event['type'] == 'checkout.session.completed':
        
        # ¡Magia! Ya no tocamos para nada el 'event['data']['object']' de Stripe
        # Usamos directo las variables que ya teníamos guardadas arriba
        logger.info(f"Evento verificado - Tipo Entidad: {tipo_entidad}, ID Empresa: {id_empresa_llaves}, ID Transacción: {id_transaccion}")

        empresa_citanet = Empresa.query.get(1)
        numerocitanet = empresa_citanet.telefono if empresa_citanet else None
        
        try:
            if tipo_entidad == 'cliente':
                cliente = Cliente.query.get(id_cliente)
                empresa_destino = Empresa.query.get(id_empresa)
                
                nombre_entidad = cliente.nombreCliente if cliente else "Cliente Desconocido"
                numero_entidad = cliente.telefono if cliente else None

                # Armamos la lista final de cargos a liquidar: los cargos originales
                # que el cliente seleccionó + los dos cargos de comisión/IVA que
                # acabamos de crear (si los hubo), para que el mismo Pago los salde a todos.
                cargos_ids_completos = cargos_ids
                if id_mov_comision and id_mov_comisionIVA:
                    extra = f"{id_mov_comision},{id_mov_comisionIVA}"
                    cargos_ids_completos = f"{cargos_ids},{extra}" if cargos_ids else extra
                
                registrar_pago_cliente(
                    id_cliente_ext=id_cliente,
                    id_empresa_ext=id_empresa,
                    monto_ext=monto_bruto,
                    cargos_ext=cargos_ids_completos,
                    notas_ext=f"Pago en línea Stripe (Ref: {id_transaccion})"
                )

                mensaje_exito = f"CitaNet: Su pago a {empresa_destino.razonSocial} por ${monto_bruto} se registró correctamente."
                mensaje_admin = f"CitaNet: El cliente {nombre_entidad} pagó ${monto_bruto} a la empresa {empresa_destino.razonSocial}."
            
            else:
                empresa_paga = Empresa.query.get(id_empresa)
                nombre_entidad = empresa_paga.razonSocial if empresa_paga else "Empresa Desconocida"
                numero_entidad = empresa_paga.telefono if empresa_paga else None
                
                registrar_pago_empresa(
                    id_empresa_ext=id_empresa,
                    monto_ext=monto_bruto,
                    cargos_ext=cargos_ids,
                    notas_ext=f"Stripe (Ref: {id_transaccion})"
                )
                _notificar_vendedor_pago_empresa(id_empresa, monto_bruto)
                mensaje_exito = f"Su pago por ${monto_bruto} MXN se registró correctamente."
                mensaje_admin = f"CitaNet: Se registró un pago de la empresa {nombre_entidad} por ${monto_bruto} MXN"
            
            # Envío de Notificaciones WhatsApp
            if numerocitanet:
                enviar_whatsapp(numerocitanet, mensaje_admin)
            
            if numero_entidad:
                enviar_whatsapp(numero_entidad, mensaje_exito)

        except Exception as e:
            logger.error(f"Error al ejecutar motores de pago en webhook ({tipo_entidad}): {str(e)}")
            return jsonify(success=False), 500

    # Si hay algun error en el procesamiento, se debe retornar un error HTTP para que Stripe reintente el webhook.
    # Pero que pasa con la información de la transacción? Se puede guardar en un log o en una tabla de errores para revisarla después.
    # Se queda registrado en la base de datos de Stripe, pero no en nuestra base de datos. Se puede crear una tabla de logs de webhooks fallidos para revisarlos después.
    # Se hace un rollback en la sesión de SQLAlchemy si hay un error en el procesamiento del pago. Si hay un error, se hace un rollback y se retorna un error HTTP para que Stripe reintente el webhook.
    
    return jsonify(success=True), 200


def calcular_saldo(id_empresa, id_cliente=None):
    try:
        movimientos = db.session.query(
            movCuenta.saldo,
            tipoMovimiento.naturaleza
        ).join(
            tipoMovimiento, 
            movCuenta.idtipoMovimiento == tipoMovimiento.idtipoMovimiento
        ).filter(
            movCuenta.idEmpresa == id_empresa,
            movCuenta.idCliente == id_cliente
        ).all()

        saldo_total = Decimal('0.00')

        for mov in movimientos:
            # Si es Cargo (C), el saldo pendiente es dinero que la empresa DEBE (resta)
            if mov.naturaleza == 'C':
                saldo_total -= Decimal(str(mov.saldo))
            # Si es Abono (A), es saldo a favor o pago no aplicado (suma)
            elif mov.naturaleza == 'A':
                saldo_total += Decimal(str(mov.saldo))

        return saldo_total

    except Exception as e:
        print(f"Error al calcular saldo: {e}")
        return Decimal('0.00')