from flask    import Blueprint, render_template, request, jsonify, session, redirect
from database import conectar_bd
from correo   import enviar_correo
from whatsapp import enviar_codigo_whatsapp
from sms      import enviar_codigo_sms
from datetime import datetime
import uuid

paciente_bp = Blueprint("paciente", __name__, url_prefix="/paciente")

# ============================================================
# 1️⃣ PANTALLA INICIAL DE LOGIN DEL PACIENTE (solo muestra HTML)
# ============================================================
#@paciente_bp.route("/login", methods=["GET"])
#def login_paciente_form():
#    return render_template("login_paciente.html")


# ============================================================
# 2️⃣ RECIBE TELEFONO, VERIFICA SI EXISTE Y ENVÍA CÓDIGO
# ============================================================
@paciente_bp.route("/auth/login_paciente", methods=["POST"])
def login_paciente():
    data = request.get_json()
    telefono = data.get("telefono")
    canal = data.get("canal", "sms")  # canal puede ser: "whatsapp" o "sms"

    codigo = 0
    
    if not telefono:
        return jsonify({"error": "Teléfono requerido (en pacuente.py)"}), 400

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True) 

    cursor.execute("SELECT idPaciente FROM paciente WHERE telefono=%s", (telefono,))
    paciente = cursor.fetchone()

    if not paciente:
        return jsonify({"error": "Telefono no registrado"}), 404   # FRONT ya redirige a alta

    #print(f"Teléfono {telefono} encontrado. Enviando código WhatsApp...  (paciente.py)")
    
    # ENVIAR CÓDIGO WHATSAPP/SMS
    # codigo = enviar_codigo_whatsapp(telefono)
    
    print("Canal seleccionado en paciente.py:", canal)
    
    if canal == "whatsapp":
        codigo = enviar_codigo_whatsapp(telefono)
    else:
        codigo = enviar_codigo_sms(telefono)

    
    # Guardamos el teléfono temporal en sesión
    session['telefono_temp'] = telefono

    return jsonify({"message": "Código enviado"}), 200


# ============================================================
# 3️⃣ VALIDAR CÓDIGO QUE EL PACIENTE RECIBE POR WHATSAPP
# ============================================================
@paciente_bp.route("/validar_codigo", methods=["POST"])
def validar_codigo():
    data = request.get_json()
    telefono = data.get("telefono")
    codigo_ingresado = data.get("codigo")

    if not telefono or not codigo_ingresado:
        return jsonify({"error": "Datos incompletos"}), 400

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT codigo FROM codigos_telefono
        WHERE telefono=%s
        ORDER BY expiracion DESC
        LIMIT 1
    """, (telefono,))
    
    fila = cursor.fetchone()
    
    if not fila or fila["codigo"] != codigo_ingresado:
        return jsonify({"error": "Código incorrecto"}), 401

    cursor.execute("""
        SELECT idPaciente, NombrePaciente
        FROM paciente
        WHERE telefono=%s
    """, (telefono,))
    paciente = cursor.fetchone()

    session["idPaciente"]     = paciente["idPaciente"]
    session["NombrePaciente"] = paciente["NombrePaciente"]

    cursor.close()
    conn.close()

    return jsonify({"ok": True})


# ============================================================
# ALTA DEL PACIENTE
# ============================================================
@paciente_bp.route("/alta", methods=["GET", "POST"])
def alta_paciente():
    mensaje = ""
    tipo_mensaje = ""

    if request.method == "POST":
        nombre = request.form.get("NombrePaciente")
        fechanac = request.form.get("fechanac")
        telefono = request.form.get("telefono")
        correo = request.form.get("correo")
        codigo = request.form.get("codigo")
        token = str(uuid.uuid4())

        if not codigo.isdigit() or len(codigo) != 6:
            mensaje = "❌ El código debe tener exactamente 6 dígitos numéricos."
            tipo_mensaje = "error"
            return render_template("alta_paciente.html", mensaje=mensaje, tipo_mensaje=tipo_mensaje)

        # VALIDAR CÓDIGO WHATSAPP/SMS
        conn = conectar_bd()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT codigo, expiracion FROM codigos_telefono WHERE telefono=%s", (telefono,))
        fila = cursor.fetchone()

        if not fila or fila["codigo"] != codigo or datetime.now() > fila["expiracion"]:
            mensaje = "❌ Código inválido o expirado."
            tipo_mensaje = "error"
            return render_template("alta_paciente.html", mensaje=mensaje, tipo_mensaje=tipo_mensaje)

        cursor.close()
        conn.close()

        # INSERTAR AL PACIENTE
        try:
            conn = conectar_bd()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO paciente (nombrepaciente, fechanac, telefono, correo, CorreoValido, TokenCorreoVerificacion)
                VALUES (%s, %s, %s, %s, FALSE, %s)
            """, (nombre, fechanac, telefono, correo, token))

            conn.commit()

            # OBTENEMOS EL ID INSERTADO
            nuevo_id = cursor.lastrowid

            cursor.close()
            conn.close()

            enviar_correo(correo, token)

            # --- ⬇️ INICIAR SESIÓN DEL PACIENTE (IMPORTANTE)
            session["idPaciente"] = nuevo_id
            session["nombrePaciente"] = nombre

            # --- ⬇️ REDIRECCIONAR AL MENÚ DEL PACIENTE
            return redirect("/menu/paciente")

        except Exception as e:
            mensaje = f"Error: {str(e)}"
            tipo_mensaje = "error"

    return render_template("alta_paciente.html", mensaje=mensaje, tipo_mensaje=tipo_mensaje)
