from datetime import datetime, timedelta

from flask import flash, Flask, render_template, redirect, request, session, url_for
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from sqlalchemy import text
from sqlalchemy.orm import joinedload
from modelos import db, Frase, Empresa, Anuncio
from correo import enviar_correo_base
import logging
import config

# Configuración de Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")
CORS(app, supports_credentials=True)

app.secret_key = "QWERTY12345!@#$"
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["JWT_SECRET_KEY"] = "Citanet_Seguridad_2026_Movel" 

jwt = JWTManager(app)
db.init_app(app)

# ----------------------------------------
# RUTAS PRINCIPALES
# ----------------------------------------

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

@app.route('/')
@app.route('/index')
def index():
    session.clear()
    
    frase_texto = "Tu bienestar es nuestra prioridad"
    anuncios_limpios = [] # Usaremos una lista nueva
    horarios_por_dia = []
    error_horarios = False

    try:
        # Frase
        ultima_frase = Frase.query.order_by(Frase.fecha.desc()).first()
        if ultima_frase and ultima_frase.frase:
            frase_texto = ultima_frase.frase
        
        # Anuncios: Los convertimos a diccionarios simples para evitar errores de Jinja2
        anuncios_db = Anuncio.query.filter_by(activo=True)\
            .order_by(Anuncio.fechaCreacion.desc()).all()
            
        for a in anuncios_db:
            anuncios_limpios.append({
                'imagen': a.imagen if a.imagen else '/static/anuncios/default.jpg',
                'descripcion': a.descripcion if a.descripcion else 'Sanación Alternativa',
                'url': a.urlAnuncio if a.urlAnuncio else '#'
            })
            
    except Exception as e:
        logger.error(f"Error cargando datos de la DB: {e}")

    try:
        empresa = Empresa.query.filter_by(slug="ac3785dd").first()
        if not empresa:
            logger.error("No se encontró la empresa Sanación Alternativa (slug ac3785dd).")
            error_horarios = True
        else:
            ahora = datetime.now()
            fecha_fin = ahora.date() + timedelta(days=14)
            citas = db.session.execute(
                text("""
                    SELECT c.fechaCita, c.horaCita
                    FROM cita AS c
                    JOIN estatus_cita AS estado_cita
                      ON estado_cita.idEstatus = c.idEstatus
                    WHERE c.idEmpresa = :id_empresa
                      AND c.idUsuario = :id_usuario
                      AND c.idEstatus IS NOT NULL
                      AND estado_cita.nombre IN ('Disponible', 'Cancelada')
                      AND c.idCitaMaestra IS NULL
                      AND c.fechaCita >= :fecha_inicio
                      AND c.fechaCita <= :fecha_fin
                      AND (
                          c.fechaCita > :fecha_hoy
                          OR (c.fechaCita = :fecha_hoy AND c.horaCita >= :hora_actual)
                      )
                      AND (
                          SELECT COUNT(*)
                          FROM cita_cliente AS cc
                          JOIN estatus_cita AS estado_reserva
                            ON estado_reserva.idEstatus = cc.idEstatus
                          WHERE cc.idCita = c.idCita
                            AND estado_reserva.nombre IN ('Reservada', 'Confirmada', 'Realizada')
                      ) < GREATEST(COALESCE(c.cupoMaximo, 1), 1)
                    ORDER BY c.fechaCita, c.horaCita
                """),
                {
                    "id_empresa": empresa.idEmpresa,
                    "id_usuario": 4,
                    "fecha_inicio": ahora.date(),
                    "fecha_hoy": ahora.date(),
                    "fecha_fin": fecha_fin,
                    "hora_actual": ahora.time(),
                },
            ).all()

            nombres_dias = (
                "lunes", "martes", "miércoles", "jueves",
                "viernes", "sábado", "domingo",
            )
            nombres_meses = (
                "enero", "febrero", "marzo", "abril", "mayo", "junio",
                "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
            )
            grupos = {}
            for cita in citas:
                fecha = cita.fechaCita
                if fecha not in grupos:
                    if fecha == ahora.date():
                        titulo = "Hoy"
                    elif fecha == ahora.date() + timedelta(days=1):
                        titulo = "Mañana"
                    else:
                        titulo = nombres_dias[fecha.weekday()].capitalize()
                    grupos[fecha] = {
                        "fecha": fecha,
                        "titulo": titulo,
                        "fecha_larga": f"{nombres_dias[fecha.weekday()]}, {fecha.day} de {nombres_meses[fecha.month - 1]}",
                        "horarios": [],
                    }
                grupos[fecha]["horarios"].append({
                    "hora": cita.horaCita.strftime("%H:%M"),
                })
            horarios_por_dia = list(grupos.values())
    except Exception:
        logger.exception("Error consultando horarios de Sanación Alternativa para el usuario 4.")
        error_horarios = True

    return render_template('index.html', 
                           frase=frase_texto, 
                           anuncios=anuncios_limpios,
                           horarios_por_dia=horarios_por_dia,
                           error_horarios=error_horarios) # Enviamos la lista limpia
    
    

@app.route('/contacto/publico', methods=['POST'])
def contacto_publico():
    datos = {
        'asunto-correo': request.form.get('asunto-correo'),
        'nombre': request.form.get('nombre'),
        'correo': request.form.get('correo'),
        'asunto': request.form.get('asunto'),
        'mensaje': request.form.get('mensaje')
    }
    
    empresa_principal = Empresa.query.get(1)
    if not empresa_principal or not empresa_principal.correoContacto:
        flash("No se encontró configuración de correo.", "danger")
        return redirect(url_for('index'))

    cuerpo = f"""
    <html>
    <body>
        <p><strong>Nombre:</strong> {datos['nombre']}</p>
        <p><strong>Correo:</strong> {datos['correo']}</p>
        <p><strong>Asunto:</strong> {datos['asunto']}</p>
        <hr>
        <p><strong>Mensaje:</strong><br>{datos['mensaje']}</p>
    </body>
    </html>
    """
    
    exito = enviar_correo_base(empresa_principal.correoContacto, datos['asunto-correo'], cuerpo, datos['correo'])
    
    if exito:
        flash("¡Gracias! Tu mensaje ha sido enviado.", "success")
    else:
        flash("Hubo un problema técnico al enviar el correo.", "danger")

    return redirect(url_for('index'))

@app.route('/seleccionar-empresa')
def seleccionar_empresa():
    destino_solicitado = request.args.get('destino', 'cliente')
    try:
        empresas = Empresa.query.filter(Empresa.slug.isnot(None)).all()
    except:
        empresas = []
    return render_template("seleccionar_empresa.html", empresas=empresas, destino=destino_solicitado)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)