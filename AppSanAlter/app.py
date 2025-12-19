from flask                      import Flask, render_template, request, jsonify, session, redirect
from database                   import conectar_bd
from werkzeug.security          import generate_password_hash, check_password_hash
from datetime                   import date

from routes.codigos_whatsapp    import codigos_whatsapp_bp
from routes.paciente            import paciente_bp
from routes.verificar           import verificar_bp
from routes.citas_admin         import citas_admin_bp
from routes.ver_citas           import ver_citas_bp
from routes.citas_paciente      import citas_paciente_bp

import re
import hashlib

# ----------------------------------------
# CONFIGURACIÓN DE FLASK
# ----------------------------------------

app = Flask(__name__, template_folder="templates")
app.secret_key = "QWERTY12345!@#$"

# ----------------------------------------
# RUTAS PRINCIPALES
# ----------------------------------------

@app.route('/login/sistema')
def login_sistema():
    return render_template('login_sistema.html')

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



# ============================================================
#   LOGIN DE USUARIOS DEL SISTEMA 
# ============================================================

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    usuario = data.get('usuario', '').strip().upper()
    password = data.get('password', '')

    if not usuario or not password:
        return jsonify({"error": "Falta usuario o contraseña"}), 400

    try:
        conn = conectar_bd()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM usuarios WHERE Usuario=%s", (usuario,))
        resultado = cursor.fetchone()

        cursor.close()
        conn.close()

        # Usuario NO existe
        if not resultado:
            return jsonify({"error": "Usuario no encontrado"}), 401

        # Contraseña incorrecta
        if not check_password_hash(resultado["Password"], password):
            return jsonify({"error": "Contraseña incorrecta"}), 401

        # Login correcto
        session["idUsuario"] = resultado["IdUsuario"]
        session["tipoUsuario"] = resultado["TipoUsuario"]
        session['Usuario'] = resultado['Usuario']      # username
        session['NombreUsuario'] = resultado['NombreUsuario']  # nombre completo        
        
        return jsonify({
            "mensaje": "Login correcto",
            "usuario": resultado["Usuario"],
            "tipo": resultado["TipoUsuario"]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500




# ============================================================
#          RUTAS DE MENÚ
# ============================================================

@app.route('/menu/admin')
def menu_admin():
    return render_template('menu_admin.html')


@app.route('/menu/terapeuta')
def menu_terapeuta():
    return render_template('menu_terapeuta.html', nombre=session.get('nombre'))

@app.route('/menu/asistente')
def menu_asistente():
    return render_template('menu_asistente.html', nombre=session.get('nombre'))

@app.route('/menu/paciente')
def menu_paciente():
    return render_template('menu_paciente.html', nombre=session.get('nombre'))


from flask import render_template, request, redirect
from database import conectar_bd
from datetime import date


# ---- LISTAR FRASES ----
@app.route('/frases')
def frases_listado():

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM frases ORDER BY fecha DESC")
    frases = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("frases_listar.html", frases=frases)


@app.route('/frases/nueva')
def frases_nueva():
    return render_template("nueva_frase.html")


# ---- GUARDAR NUEVA FRASE ----
@app.route('/frases/guardar', methods=['POST'])
def frases_guardar():

    frase = request.form.get("frase").strip()

    if not frase:
        return "La frase no puede estar vacía", 400

    hoy = date.today()   # <-- genera fecha tipo DATE

    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("INSERT INTO frases (frase, fecha) VALUES (%s, %s)", (frase, hoy))
    conn.commit()

    cursor.close()
    conn.close()

    return redirect("/frases")


# ---- EDITAR FRASE ----
@app.route('/frases/editar')
def frases_editar():

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

    frase = request.form.get("frase").strip()
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


@citas_admin_bp.route("/admin/cambiar_password")
def cambiar_password_form():
    return render_template("cambiar_password.html")


@citas_admin_bp.route("/admin/cambiar_password", methods=["GET", "POST"])
def cambiar_password():
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





# ============================================================
#   REGISTRO DE BLUEPRINTS (LOS DEMÁS MÓDULOS)
# ============================================================

app.register_blueprint(codigos_whatsapp_bp)
app.register_blueprint(paciente_bp)
app.register_blueprint(verificar_bp)
app.register_blueprint(citas_admin_bp)
app.register_blueprint(ver_citas_bp)
app.register_blueprint(citas_paciente_bp)



# ============================================================
#   EJECUCIÓN DE LA APP
# ============================================================

#print("\n📌 RUTAS REGISTRADAS EN FLASK:")
#for rule in app.url_map.iter_rules():
#    print(rule)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)


