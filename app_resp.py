"""
Sanación Alternativa - sitio público conectado a la base de datos de CitaNet.

Solo sirve el index.html con los horarios disponibles de la agenda.
La reservación se hace en CitaNet (los enlaces del index apuntan allá),
por eso aquí NO se registran los blueprints de routes/.

Requiere en la misma carpeta:
  - config.py            (con SQLALCHEMY_DATABASE_URI apuntando a la BD de CitaNet)
  - modelos.py           (el de CitaNet, el vigente)
  - templates/index.html
  - static/img/...       (imagen01.jpeg a imagen04.jpeg)
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, render_template
from sqlalchemy import and_, or_

import config
from modelos import db, Empresa, Cita, EstatusCita

# ----------------------------------------
# AJUSTES DEL SITIO
# ----------------------------------------
SLUG_EMPRESA     = "ac3785dd"             # Empresa "Sanación Alternativa" en CitaNet
ID_USUARIO_STAFF = 4                      # Staff cuya agenda se muestra
DIAS_ADELANTE    = 14                     # Cuántos días hacia adelante se consultan
ZONA_HORARIA     = "America/Mexico_City"  # Las citas se guardan en hora local

NOMBRES_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
NOMBRES_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

# Configuración de Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")
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
    """Agrupa [(fecha, hora), ...] por día con el formato que espera index.html."""
    hoy = ahora.date()
    manana = hoy + timedelta(days=1)
    grupos = {}

    for fecha, hora in citas:
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
        grupos[fecha]["horarios"].append({"hora": hora.strftime("%H:%M")})

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
            db.session.query(Cita.fechaCita, Cita.horaCita)
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
    return render_template(
        "index.html",
        horarios_por_dia=horarios_por_dia,
        error_horarios=error_horarios,
    )


if __name__ == "__main__":
    # Solo para pruebas locales; en el servidor lo ejecuta Gunicorn (app:app)
    app.run(host="0.0.0.0", port=5000)
