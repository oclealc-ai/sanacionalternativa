from flask import flash, Flask, render_template, redirect, request, session, url_for
from flask_cors import CORS
from flask_jwt_extended import JWTManager
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
    # Limpiamos sesión para un inicio fresco
    session.clear()
    
    # Valores por defecto por si falla la DB
    frase_texto = "Tu bienestar es nuestra prioridad"
    anuncios = []
    empresa_citanet = None

    try:
        # Intentamos obtener la frase
        ultima_frase = Frase.query.order_by(Frase.fecha.desc()).first()
        if ultima_frase:
            frase_texto = ultima_frase.frase
        
        # Intentamos obtener la info de la empresa (ID 1 por defecto)
        empresa_citanet = Empresa.query.get(1)
        
        # Intentamos cargar anuncios activos
        anuncios = Anuncio.query.filter_by(activo=True)\
            .order_by(Anuncio.fechaCreacion.desc())\
            .all()
            
    except Exception as e:
        logger.error(f"Error cargando datos de la DB: {e}")
        # Si falla, no pasa nada, ya tenemos los valores por defecto arriba

    return render_template('index.html', 
                           frase=frase_texto, 
                           anuncios=anuncios, 
                           empresa=empresa_citanet)

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