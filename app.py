from flask import Flask, render_template, redirect
from modelos import db, Frase

from routes.usuarios          import usuarios_bp
from routes.paciente          import paciente_bp
from routes.frases            import frases_bp
from routes.citas_admin       import citas_admin_bp
from routes.citas_paciente    import citas_paciente_bp
from routes.ver_citas         import ver_citas_bp
from routes.empresas          import empresas_bp
from routes.verificar         import verificar_bp
from routes.anuncios_paciente import anuncios_paciente_bp
from routes.codigos_telefono  import codigos_telefono_bp

import logging
import config

# Configuración de Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")
app.secret_key = "QWERTY12345!@#$"

app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# ----------------------------------------
# RUTAS PRINCIPALES
# ----------------------------------------

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

@app.route("/")
def home():
    return redirect("/index")

@app.route('/index')
def index():
    ultima_frase = Frase.query.order_by(Frase.fecha.desc()).first()
    frase_texto = ultima_frase.frase if ultima_frase else "Bienvenido al sistema"
    return render_template("index.html", frase=frase_texto)

# ----------------------------------------
# REGISTRO DE BLUEPRINTS
# ----------------------------------------
app.register_blueprint(usuarios_bp)
app.register_blueprint(paciente_bp)
app.register_blueprint(frases_bp)
app.register_blueprint(citas_admin_bp)
app.register_blueprint(citas_paciente_bp)
app.register_blueprint(ver_citas_bp)
app.register_blueprint(empresas_bp)
app.register_blueprint(verificar_bp)
app.register_blueprint(anuncios_paciente_bp)
app.register_blueprint(codigos_telefono_bp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)