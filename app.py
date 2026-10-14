"""
Sanación Alternativa - sitio público conectado a la base de datos de CitaNet.

Sirve el index.html con los horarios disponibles de la agenda.
El cliente inicia sesión (o se registra) con el mismo flujo de CitaNet y reserva
llamando a la ruta de reserva de CitaNet (/cliente/reservar_cita), por eso aquí
NO se registran los blueprints de routes/.

Requiere en la misma carpeta:
  - config.py            (con SQLALCHEMY_DATABASE_URI apuntando a la BD de CitaNet
                          y SECRET_KEY propio de este sitio)
  - modelos.py           (el de CitaNet, el vigente)
  - templates/index.html
  - static/img/...       (imagen01.jpeg a imagen04.jpeg)
"""
import logging
import re
from datetime import datetime, timedelta
from html import unescape
from zoneinfo import ZoneInfo

import requests
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from sqlalchemy import and_, or_

import config
from modelos import db, Empresa, Cita, EstatusCita, Cliente, ClienteEmpresa, CitaCliente, Pais, Publicidad, movCuenta

# ----------------------------------------
# AJUSTES DEL SITIO
# ----------------------------------------
SLUG_EMPRESA     = "ac3785dd"             # Empresa "Sanación Alternativa" en CitaNet
ID_USUARIO_STAFF = 4                      # Staff cuya agenda se muestra
DIAS_ADELANTE    = 14                     # Cuántos días hacia adelante se consultan
ZONA_HORARIA     = "America/Mexico_City"  # Las citas se guardan en hora local

# CitaNet corre en el mismo servidor (gunicorn en 127.0.0.1:5001). Este sitio le pide
# el código por WhatsApp, el alta y la reserva, así no se duplica nada de esa lógica.
CITANET_INTERNAL_URL = getattr(config, "CITANET_INTERNAL_URL", "http://127.0.0.1:5001")

# Publicidad (carrusel vertical): la misma que CitaNet muestra en su página.
# Las imágenes viven en CitaNet; si config.py define PUBLICIDAD_IMG_BASE se usa esa URL base
# (debe terminar en "/"), por ejemplo "https://www.citanet.com.mx/static/".
PUBLICIDAD_IMG_BASE = getattr(config, "PUBLICIDAD_IMG_BASE", "https://www.citanet.com.mx/static/")
PUBLICIDAD_MAX      = 20                  # Máximo de anuncios en el carrusel
ID_EMPRESA_CITANET  = 1                   # Empresa maestra: sus anuncios no requieren pago

NOMBRES_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
NOMBRES_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

# Configuración de Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")

# Sesión del cliente: cookie firmada que dura 1 año y se renueva en cada visita; solo
# termina al pulsar "Cerrar sesión". config.SECRET_KEY debe ser fijo y distinto al de CitaNet.
app.config.update(
    SECRET_KEY=config.SECRET_KEY,
    SESSION_COOKIE_NAME="sanacion_session",
    PERMANENT_SESSION_LIFETIME=timedelta(days=365),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=getattr(config, "COOKIE_SEGURA", True),  # False solo para probar en http local
)
app.config["SQLALCHEMY_DATABASE_URI"] = config.SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Evita "MySQL server has gone away" cuando el sitio pasa un rato sin visitas
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 280}

db.init_app(app)


# ----------------------------------------
# FUNCIONES AUXILIARES
# ----------------------------------------
def ahora_local():
    """Fecha y hora actual en la zona horaria del negocio (sin tzinfo)."""
    try:
        return datetime.now(ZoneInfo(ZONA_HORARIA)).replace(tzinfo=None)
    except Exception:
        # Si el servidor no tiene la base de zonas horarias, usamos la hora del sistema
        return datetime.now()


def agrupar_horarios(citas, ahora):
    """Agrupa [(idCita, fecha, hora), ...] por día con el formato que espera index.html."""
    hoy = ahora.date()
    manana = hoy + timedelta(days=1)
    grupos = {}

    for id_cita, fecha, hora in citas:
        if fecha not in grupos:
            if fecha == hoy:
                titulo = "Hoy"
            elif fecha == manana:
                titulo = "Mañana"
            else:
                titulo = NOMBRES_DIAS[fecha.weekday()].capitalize()
            grupos[fecha] = {
                "fecha": fecha,
                "titulo": titulo,
                "fecha_larga": f"{NOMBRES_DIAS[fecha.weekday()]}, {fecha.day} de {NOMBRES_MESES[fecha.month - 1]}",
                "horarios": [],
            }
        grupos[fecha]["horarios"].append({"idCita": id_cita, "hora": hora.strftime("%H:%M")})

    return list(grupos.values())


def obtener_horarios():
    """
    Devuelve (horarios_por_dia, error_horarios).
    Un horario disponible es una cita en estatus 'Disponible' del staff indicado,
    con lugar libre, dentro de los próximos DIAS_ADELANTE días y que no haya pasado.
    """
    try:
        # Se piden solo las columnas necesarias (no el objeto completo) para que el sitio
        # no dependa de columnas que no se usan aquí.
        id_empresa = db.session.query(Empresa.idEmpresa).filter(Empresa.slug == SLUG_EMPRESA).scalar()
        if id_empresa is None:
            logger.error("No se encontró la empresa con slug %s.", SLUG_EMPRESA)
            return [], True

        id_disponible = db.session.query(EstatusCita.idEstatus).filter(EstatusCita.nombre == "Disponible").scalar()
        if id_disponible is None:
            logger.error("No se encontró el estatus 'Disponible' para consultar horarios.")
            return [], True

        ahora = ahora_local()
        hoy = ahora.date()

        citas = (
            db.session.query(Cita.idCita, Cita.fechaCita, Cita.horaCita)
            .filter(
                Cita.idEmpresa == id_empresa,
                Cita.idUsuario == ID_USUARIO_STAFF,
                Cita.idEstatus == id_disponible,
                Cita.cupoOcupado < Cita.cupoMaximo,   # todavía hay lugar
                Cita.idCitaMaestra.is_(None),         # no es continuación de otra reserva
                Cita.fechaCita >= hoy,
                Cita.fechaCita <= hoy + timedelta(days=DIAS_ADELANTE),
                or_(
                    Cita.fechaCita > hoy,
                    and_(Cita.fechaCita == hoy, Cita.horaCita >= ahora.time()),
                ),
            )
            .order_by(Cita.fechaCita, Cita.horaCita)
            .all()
        )
        return agrupar_horarios(citas, ahora), False

    except Exception:
        db.session.rollback()
        logger.exception("Error consultando horarios de Sanación Alternativa (usuario %s).", ID_USUARIO_STAFF)
        return [], True


def _url_imagen_publicidad(imagen):
    """URL absoluta de la imagen de un anuncio (viene de CitaNet)."""
    imagen = (imagen or "").strip()
    if imagen.startswith(("http://", "https://")):
        return imagen
    imagen = imagen.lstrip("/")
    if imagen.startswith("static/"):
        imagen = imagen[len("static/"):]
    return PUBLICIDAD_IMG_BASE + imagen


def obtener_publicidad():
    """
    Anuncios vigentes que CitaNet muestra en su página: activos, validados por CitaNet,
    dentro de su vigencia y, o son de la empresa 1 (sin cargo), o su cargo ya está pagado
    (movCuenta ligado con saldo <= 0). Devuelve [] si algo falla para no tumbar el sitio.
    """
    try:
        hoy = ahora_local().date()
        filas = (
            db.session.query(Publicidad.idPublicidad, Publicidad.imagen,
                             Publicidad.descripcion, Publicidad.urlPublicidad)
            .outerjoin(movCuenta, Publicidad.idMovimiento == movCuenta.idMovimiento)
            .filter(
                Publicidad.activo.is_(True),
                Publicidad.valido_por_citanet.is_(True),
                or_(Publicidad.fechaInicioVigencia.is_(None), Publicidad.fechaInicioVigencia <= hoy),
                or_(Publicidad.fechaFinVigencia.is_(None), Publicidad.fechaFinVigencia >= hoy),
                or_(Publicidad.idEmpresa == ID_EMPRESA_CITANET, movCuenta.saldo <= 0),
            )
            .order_by(Publicidad.idPublicidad.desc())
            .limit(PUBLICIDAD_MAX)
            .all()
        )
        return [
            {
                "imagen": _url_imagen_publicidad(f.imagen),
                "descripcion": f.descripcion or "",
                "url": f.urlPublicidad or "",
            }
            for f in filas if f.imagen
        ]
    except Exception:
        db.session.rollback()
        logger.exception("Error consultando la publicidad.")
        return []


# ----------------------------------------
# ACCESO DE CLIENTES (reutiliza las rutas de CitaNet)
# ----------------------------------------
_id_empresa_cache = None


def id_empresa_sitio():
    """idEmpresa de este sitio, resuelto por su slug (se guarda tras la primera consulta)."""
    global _id_empresa_cache
    if _id_empresa_cache is None:
        _id_empresa_cache = db.session.query(Empresa.idEmpresa).filter(Empresa.slug == SLUG_EMPRESA).scalar()
    return _id_empresa_cache


def _es_redireccion(r):
    return r.status_code in (301, 302, 303, 307, 308)


def _cliente_por_telefono(telefono, id_pais):
    """Mismo criterio que /validar_codigo_global de CitaNet para encontrar al cliente."""
    # CitaNet acaba de escribir en la BD: se cierra la transacción de lectura de esta
    # petición para no ver una copia anterior (MySQL REPEATABLE READ).
    db.session.rollback()
    q = Cliente.query.filter_by(telefono=telefono)
    if str(id_pais or "").isdigit():
        q = q.filter_by(idPais=int(id_pais))
    return q.first()


def _abrir_sesion(cliente, sesion_citanet):
    """Abre la sesión de este sitio y conserva la de CitaNet, que la reserva necesita."""
    session.clear()  # sesión nueva (evita reutilizar una anterior)
    session.permanent = True
    session["cliente"] = {"id": cliente.idCliente, "nombre": (cliente.nombreCliente or "").strip()}
    session["cn"] = sesion_citanet.cookies.get_dict()


@app.context_processor
def inyectar_cliente():
    """Deja `cliente` ({'id', 'nombre'}) disponible en las plantillas, o None."""
    return {"cliente": session.get("cliente")}


@app.post("/acceso/enviar_codigo")
def acceso_enviar_codigo():
    """Pide a CitaNet que mande el código por WhatsApp (/enviar_codigo), para login o alta."""
    d = request.get_json(silent=True) or {}
    modo = "alta" if d.get("modo") == "alta" else "login"
    payload = {
        "telefono": str(d.get("telefono", "")).strip(),
        "modo": modo,
        "canal": "whatsapp",
    }
    if modo == "login":
        # Igual que login_cliente.html (manda la empresa) y alta_cliente.html (no la manda)
        payload["idEmpresa"] = id_empresa_sitio()
    if d.get("idPais"):
        payload["idPais"] = d["idPais"]

    try:
        r = requests.post(f"{CITANET_INTERNAL_URL}/enviar_codigo", json=payload, timeout=15)
        data = r.json()
    except (requests.RequestException, ValueError):
        return jsonify(status="error", msg="No pudimos enviar el código. Intenta de nuevo."), 502
    return jsonify(data), r.status_code


@app.post("/acceso/validar_codigo")
def acceso_validar_codigo():
    """Valida el código en CitaNet (/validar_codigo_global) y abre la sesión del sitio."""
    d = request.get_json(silent=True) or {}
    telefono = str(d.get("telefono", "")).strip()
    payload = {"telefono": telefono, "idPais": d.get("idPais"), "codigo": str(d.get("codigo", "")).strip()}
    id_emp = id_empresa_sitio()

    s = requests.Session()
    try:
        r = s.post(f"{CITANET_INTERNAL_URL}/validar_codigo_global", json=payload, timeout=15)
        data = r.json()
        if not (r.ok and data.get("ok")):
            return jsonify(ok=False, error=data.get("error") or "Código incorrecto"), 400
        # La reserva de CitaNet exige idEmpresa en su sesión: se fija con su ruta existente
        r2 = s.get(f"{CITANET_INTERNAL_URL}/cliente/empresa_seleccionada/{id_emp}",
                   allow_redirects=False, timeout=10)
        if not _es_redireccion(r2):
            raise ValueError("empresa_seleccionada no respondió como se esperaba")
    except (requests.RequestException, ValueError):
        logger.exception("Error validando código en CitaNet")
        return jsonify(ok=False, error="No pudimos validar el código. Intenta de nuevo."), 502

    cliente = _cliente_por_telefono(telefono, d.get("idPais"))
    if not cliente:
        return jsonify(ok=False, error="No pudimos identificar tu cuenta."), 502
    _abrir_sesion(cliente, s)
    return jsonify(ok=True)


@app.post("/acceso/alta")
def acceso_alta():
    """Registra al cliente con la ruta de alta de CitaNet (/cliente/alta) y abre su sesión."""
    d = request.get_json(silent=True) or {}
    form = {k: str(d.get(k, "")).strip()
            for k in ("nombreCliente", "fechanac", "telefono", "correo", "codigo", "idPais")}

    s = requests.Session()
    try:
        r = s.post(f"{CITANET_INTERNAL_URL}/cliente/alta", params={"idEmpresa": id_empresa_sitio()},
                   data=form, allow_redirects=False, timeout=20)
    except requests.RequestException:
        logger.exception("Error en el alta contra CitaNet")
        return jsonify(ok=False, error="No pudimos completar el registro. Intenta de nuevo."), 502

    if not _es_redireccion(r):
        # CitaNet vuelve a pintar su formulario con el motivo en un <div class="alert ...">
        m = re.search(r'<div class="alert alert-(?:danger|success)[^"]*">\s*(.*?)\s*</div>', r.text or "", re.S)
        msg = unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
        return jsonify(ok=False, error=msg or "No pudimos completar el registro."), 400

    cliente = _cliente_por_telefono(form["telefono"], form["idPais"])
    if not cliente:
        return jsonify(ok=False, error="No pudimos identificar tu cuenta."), 502
    _abrir_sesion(cliente, s)
    return jsonify(ok=True)


@app.post("/acceso/reservar")
def acceso_reservar():
    """Reserva con la misma ruta de CitaNet (/cliente/reservar_cita), usando la sesión de CitaNet."""
    cl, cn = session.get("cliente"), session.get("cn")
    if not cl or not cn:
        return jsonify(ok=False, sesion_expirada=True, error="Inicia sesión para reservar."), 401

    d = request.get_json(silent=True) or {}
    try:
        id_cita = int(d.get("idCita"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Horario inválido."), 400

    id_emp = id_empresa_sitio()
    expirada = (jsonify(ok=False, sesion_expirada=True,
                        error="Tu sesión expiró. Inicia sesión de nuevo para reservar."), 401)

    s = requests.Session()
    s.cookies.update(cn)
    try:
        # Si el cliente aún no está vinculado a esta empresa, se vincula con la ruta de CitaNet
        if not ClienteEmpresa.query.filter_by(idCliente=cl["id"], idEmpresa=id_emp).first():
            rv = s.post(f"{CITANET_INTERNAL_URL}/cliente/vincular_empresa",
                        json={"idEmpresa": id_emp}, timeout=10)
            if rv.status_code != 200:
                return expirada

        t0 = datetime.now() - timedelta(seconds=10)   # CitaNet graba fechaSolicitud con datetime.now()
        r = s.post(f"{CITANET_INTERNAL_URL}/cliente/reservar_cita",
                   data={"idCita": id_cita, "paso": "confirmar", "cantidad": 1, "tipo": ""},
                   allow_redirects=False, timeout=30)
    except requests.RequestException:
        logger.exception("Error reservando en CitaNet")
        return jsonify(ok=False, error="No pudimos reservar. Intenta de nuevo."), 502

    if _es_redireccion(r):
        if "mis_citas" in r.headers.get("Location", ""):
            return jsonify(ok=False, error="Ya tienes una reserva en este horario."), 409
        return expirada   # CitaNet no reconoció la sesión (validar_acceso)

    # La respuesta de CitaNet es HTML; se confirma con la propia reserva en la BD
    db.session.rollback()
    reserva = CitaCliente.query.filter(
        CitaCliente.idCita == id_cita,
        CitaCliente.idCliente == cl["id"],
        CitaCliente.fechaSolicitud >= t0,
    ).first()
    if reserva:
        return jsonify(ok=True)

    m = re.search(r"alert\('([^']*)'\)", r.text or "")
    return jsonify(ok=False, error=m.group(1) if m else "No pudimos reservar este horario."), 409


@app.post("/salir")
def salir():
    session.clear()
    return redirect(url_for("index"))


# ----------------------------------------
# RUTAS
# ----------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        return "Página no encontrada", 404


@app.route("/")
@app.route("/index")
def index():
    horarios_por_dia, error_horarios = obtener_horarios()
    paises = []
    if not session.get("cliente"):
        try:   # lista de países para el alta (la misma que usa CitaNet)
            paises = Pais.query.filter_by(activo=True).order_by(Pais.nombre).all()
        except Exception:
            db.session.rollback()
            logger.exception("No se pudo cargar la lista de países.")
    return render_template(
        "index.html",
        horarios_por_dia=horarios_por_dia,
        error_horarios=error_horarios,
        paises=paises,
        publicidad=obtener_publicidad(),
    )


if __name__ == "__main__":
    # Solo para pruebas locales; en el servidor lo ejecuta Gunicorn (app:app)
    app.run(host="0.0.0.0", port=5000)
