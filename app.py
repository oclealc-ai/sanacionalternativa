from flask                      import Flask, render_template, request, jsonify, session, redirect
from werkzeug.security          import generate_password_hash, check_password_hash
from datetime                   import date

from database                   import conectar_bd

from routes.codigos_telefono    import codigos_telefono_bp
from routes.paciente            import paciente_bp
from routes.verificar           import verificar_bp
from routes.citas_admin         import citas_admin_bp
from routes.ver_citas           import ver_citas_bp
from routes.citas_paciente      import citas_paciente_bp
from routes.empresas            import empresas_bp

import re
import logging
import os

logger = logging.getLogger("appsanalter")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    file_handler = logging.FileHandler("/home/appuser/apps/AppSanAlter/logs/app.log")
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

def log(msg):
    logger.debug(msg)


# ----------------------------------------
# CONFIGURACIÓN DE FLASK
# ----------------------------------------

app = Flask(__name__, template_folder="templates")
app.secret_key = "QWERTY12345!@#$"

# ----------------------------------------
# RUTAS PRINCIPALES
# ----------------------------------------

@app.route("/")
def home():
    return redirect("/index")

@app.route('/index')
def index():
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("SELECT frase FROM frases ORDER BY fecha DESC LIMIT 1")
    resultado = cursor.fetchone()

    cursor.close()
    conn.close()

    # Si no hay frase o viene vacía → mensaje por defecto
    frase = resultado[0] if (resultado and resultado[0].strip()) else "Bienvenido al sistema"

    return render_template("index.html", frase=frase)

@app.route('/login/sistema')
def login_sistema():
    return render_template('login_sistema.html')
    #return render_template('login_sistema.html')

@app.route('/logout/sistema')
def logout_sistema():
    session.clear()
    return render_template('logout_sistema.html')

@app.route('/login/admin')
def login_admin():
    return render_template('login_admin.html')

@app.route('/logout/admin')
def logout_admin():
    session.clear()
    return render_template('logout_admin.html')

@app.route('/login/paciente')
def login_paciente():
    return render_template('login_paciente.html')

@app.route('/logout/paciente')
def logout_paciente():
    session.clear()
    return render_template('logout_paciente.html')

@app.route('/paciente/alta')
def alta_paciente():
    telefono = request.args.get("telefono", "")
    return render_template("alta_paciente.html", telefono=telefono)


# ============================================================
#   LOGIN DE USUARIOS DEL SISTEMA 
# ============================================================

@app.route('/auth/login', methods=['POST'])
def login():
    
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Datos inválidos"}), 400

    usuario = data.get('usuario', '').strip().upper()
    password = data.get('password', '')
    empresa = data.get('empresa')

    if not usuario or not password or not empresa:
        return jsonify({"error": "Faltan datos"}), 400

    try:
        empresa = int(empresa)
    except:
        return jsonify({"error": "Empresa inválida"}), 400
    
    try:
        conn = conectar_bd()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT *
            FROM usuarios
            WHERE Usuario = %s
            AND idEmpresa = %s
        """, (usuario, empresa))

        resultado = cursor.fetchone()

        # Usuario NO existe
        if not resultado:
            return jsonify({"error": "Usuario no existe en esta empresa"}), 401

        # Contraseña incorrecta
        if not check_password_hash(resultado["Password"], password):
            return jsonify({"error": "Contraseña incorrecta"}), 401

        cursor.execute(
            "SELECT RazonSocial FROM Empresa WHERE idEmpresa = %s",
            (usuario["idEmpresa"],)
        )
        empresa = cursor.fetchone()

        if empresa:
            session["RazonSocial"] = empresa[0]
        else:
            session["RazonSocial"] = ""

        
        cursor.close()
        conn.close()
        
        # Login correcto
        session["idUsuario"] = resultado["IdUsuario"]
        session["tipoUsuario"] = resultado["TipoUsuario"]
        session['Usuario'] = resultado['Usuario']      # username
        session['NombreUsuario'] = resultado['NombreUsuario']  # nombre completo        
        session["idEmpresa"] = resultado["idEmpresa"]

        log("SESSION: " + str(dict(session)))
        log(f"LOGIN OK → Usuario:{usuario} Empresa:{empresa}")

        return jsonify({
            "mensaje": "Login correcto",
            "usuario": resultado["Usuario"],
            "tipo": resultado["TipoUsuario"]
        }), 200

    except Exception as e:
        log("ERROR LOGIN: " + str(e))
        return jsonify({"error": str(e)}), 500




# ============================================================
#          RUTAS DE MENÚ
# ============================================================

@app.route('/menu/admin')
def menu_admin():
    if "idUsuario" not in session:
        return redirect("/login/sistema")
    return render_template('menu_admin.html', nombre=session.get('NombreUsuario'))




@app.route('/menu/terapeuta')
def menu_terapeuta():
    if "idUsuario" not in session:
        return redirect("/login/sistema")
    return render_template('menu_terapeuta.html',
                            nombre=session.get('NombreUsuario'),
                            empresa=session.get('RazonSocial')
                          )


@app.route('/menu/asistente')
def menu_asistente():
    if "idUsuario" not in session:
        return redirect("/login/sistema")
    return render_template('menu_asistente.html', nombre=session.get('NombreUsuario'),empresa=session.get('RazonSocial'))


@app.route('/menu/paciente')
def menu_paciente():
    if "idUsuario" not in session:
        return redirect("/login/sistema")
    return render_template('menu_paciente.html', nombre=session.get('NombreUsuario'), empresa=session.get('RazonSocial'))
#luego vemos la empresa en este menu de pacientes, para ver de donde llega el valor


# ---- LISTAR FRASES ----
@app.route('/frases')
def frases_listado():
    if "idUsuario" not in session:
        return redirect("/login/sistema")

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM frases ORDER BY fecha DESC")
    frases = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("frases_listar.html", frases=frases)


@app.route('/frases/nueva')
def frases_nueva():
    if "idUsuario" not in session:
        return redirect("/login/sistema")
    return render_template("nueva_frase.html")


# ---- GUARDAR NUEVA FRASE ----
@app.route('/frases/guardar', methods=['POST'])
def frases_guardar():
    if "idUsuario" not in session:
        return redirect("/login/sistema")
    try:
        log("Formulario recibido: " + str(request.form))

        frase = request.form.get("frase", "")
        frase = frase.strip()
        empresa = session.get("idEmpresa")
        if not empresa:
            log("Empresa no definida en sesión")
            return "Empresa no definida en sesión", 403


        if not frase:
            log("Frase vacía")
            return "La frase no puede estar vacía", 400

        #hoy = date.today()
        hoy = date.today().strftime("%Y-%m-%d")


        conn = conectar_bd()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO frases (frase, fecha, idEmpresa) VALUES (%s, %s, %s)",
            (frase, hoy, empresa)
        )

        conn.commit()
        cursor.close()
        conn.close()

        log("Frase insertada correctamente")

        return redirect("/frases")

    except Exception as e:
        log("ERROR AL GUARDAR FRASE: " + str(e))
        return "Error interno al guardar la frase", 500



# ---- EDITAR FRASE ----
@app.route('/frases/editar')
def frases_editar():
    if "idUsuario" not in session:
        return redirect("/login/sistema")

    idf = request.args.get("id")

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM frases WHERE idFrase = %s", (idf,))
    registro = cursor.fetchone()

    print("Registro obtenido :", registro)
    cursor.close()
    conn.close()

    return render_template("frases_editar.html", registro=registro)


# ---- ACTUALIZAR FRASE ----
@app.route('/frases/actualizar', methods=['POST'])
def frases_actualizar():
    if "idUsuario" not in session:
        return redirect("/login/sistema")

    frase = request.form.get("frase", "").strip()

    idf = request.form.get("idFrase")
    
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE frases SET frase = %s WHERE idFrase = %s
    """, (frase, idf))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect("/frases")


# ---- BORRAR FRASE ----
@app.route('/frases/borrar')
def frases_borrar():
    if "idUsuario" not in session:
        return redirect("/login/sistema")

    idf = request.args.get("id")

    print("ID de la frase a borrar:", idf)
        
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM frases WHERE idFrase = %s", (idf,))
    conn.commit()

    cursor.close()
    conn.close()

    return redirect("/frases")





# ---------- LISTA DE USUARIOS ----------
@app.route('/admin/usuarios')
def admin_usuarios():
    if "idUsuario" not in session:
        return redirect("/login/sistema")
    conexion = conectar_bd()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("SELECT IdUsuario, Usuario, TipoUsuario FROM usuarios ORDER BY IdUsuario ASC")
    usuarios = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template("admin_usuarios.html", usuarios=usuarios)



# ---------- FORMULARIO DE ALTA ----------
@app.route('/admin/usuarios/nuevo')
def admin_usuarios_nuevo():
    if "idUsuario" not in session:
        return redirect("/login/sistema")
    return render_template("admin_usuarios_nuevo.html")  # este HTML lo creas abajo



# ---------- GUARDAR USUARIO ----------
@app.route('/admin/usuarios/guardar', methods=['POST'])
def admin_usuarios_guardar():
    usuario = request.form.get('Usuario')
    password_plano = request.form.get('Password')
    password_encriptado = generate_password_hash(password_plano)
    tipo = request.form.get('TipoUsuario')

    if not usuario or not password_plano or not tipo:
        return "Faltan datos", 400

    # Convertir a MAYÚSCULAS
    usuario = usuario.upper()

    # Validar que no tenga símbolos raros
    # Solo permite A-Z, 0-9, guion y guion bajo
    if not re.match(r'^[A-Z0-9_-]+$', usuario):
        return "❌ El usuario contiene caracteres no permitidos.", 400
    
    # 🔐 Encriptar contraseña
    password_encriptado = generate_password_hash(password_plano)
    
    conexion = conectar_bd()
    cursor = conexion.cursor()

    sql = """INSERT INTO usuarios (Usuario, Password, TipoUsuario)
             VALUES (%s, %s, %s)"""
    cursor.execute(sql, (usuario, password_encriptado, tipo))
    conexion.commit()

    cursor.close()
    conexion.close()

    return redirect('/admin/usuarios')


@citas_admin_bp.route("/admin/cambiar_password", methods=["GET", "POST"])
def cambiar_password():
    if "idUsuario" not in session:
        return redirect("/login/sistema")
    if request.method == "POST":
        actual = request.form.get("actual")
        nueva = request.form.get("nueva")
        confirmar = request.form.get("confirmar")

        if nueva != confirmar:
            return render_template(
                "cambiar_password.html",
                mensaje="❌ Las contraseñas no coinciden",
                tipo="error"
            )

        id_usuario = session.get("idUsuario")

        conn = conectar_bd()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT Password FROM usuarios WHERE IdUsuario=%s",
            (id_usuario,)
        )
        usuario = cursor.fetchone()

        # ✅ VALIDAR PASSWORD ACTUAL
        if not usuario or not check_password_hash(usuario["Password"], actual):
            cursor.close()
            conn.close()
            return render_template(
                "cambiar_password.html",
                mensaje="❌ Contraseña actual incorrecta",
                tipo="error"
            )

        # ✅ ENCRIPTAR NUEVA CONTRASEÑA
        nueva_hash = generate_password_hash(nueva)

        cursor.execute(
            "UPDATE usuarios SET Password=%s WHERE IdUsuario=%s",
            (nueva_hash, id_usuario)
        )

        conn.commit()
        cursor.close()
        conn.close()

        return render_template(
            "cambiar_password.html",
            mensaje="✅ Contraseña actualizada correctamente",
            tipo="success"
        )

    return render_template("cambiar_password.html")



@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("EXCEPCIÓN NO CONTROLADA")
    return "Error interno", 500


# ============================================================
#   REGISTRO DE BLUEPRINTS (LOS DEMÁS MÓDULOS)
# ============================================================

app.register_blueprint(codigos_telefono_bp)
app.register_blueprint(paciente_bp)
app.register_blueprint(verificar_bp)
app.register_blueprint(citas_admin_bp)
app.register_blueprint(ver_citas_bp)
app.register_blueprint(citas_paciente_bp)
app.register_blueprint(empresas_bp)


# ============================================================
#   EJECUCIÓN DE LA APP
# ============================================================

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)


