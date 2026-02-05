from flask    import Blueprint, render_template, request, jsonify, session, redirect
from database import conectar_bd
from correo   import enviar_correo
from whatsapp import enviar_codigo_whatsapp
from sms      import enviar_codigo_sms
from datetime import datetime
import uuid

paciente_bp = Blueprint("paciente", __name__, url_prefix="/paciente")


# ============================================================
# RECIBE TELEFONO, VERIFICA SI EXISTE EN LA EMPRESA Y ENVÍA CÓDIGO
# ============================================================
@paciente_bp.route("/empresa/<int:idEmpresa>/auth/login", methods=["POST"])
def login_paciente_empresa(idEmpresa):
    """
    Login de paciente validando que el teléfono existe en ESA empresa específica.
    La empresa viene en la URL, no la elige el paciente.
    """
    data = request.get_json()
    telefono = data.get("telefono")
    canal = data.get("canal", "sms")  # canal puede ser: "whatsapp" o "sms"

    if not telefono:
        return jsonify({"error": "Teléfono requerido"}), 400

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True) 

    # ✅ Validar que la empresa existe
    cursor.execute("SELECT idEmpresa FROM Empresa WHERE idEmpresa=%s", (idEmpresa,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "Empresa no válida"}), 404

    # ✅ Buscar el paciente en esa empresa específica
    cursor.execute("""
        SELECT idPaciente, NombrePaciente 
        FROM paciente 
        WHERE Telefono=%s AND idEmpresa=%s
    """, (telefono, idEmpresa))
    paciente = cursor.fetchone()

    if not paciente:
        cursor.close()
        conn.close()
        # Si no existe en esta empresa, ofrecer registrarse
        return jsonify({"error": "no_encontrado"}), 404

    # ✅ Enviar código por el canal elegido
    if canal == "whatsapp":
        codigo = enviar_codigo_whatsapp(telefono)
    else:
        codigo = enviar_codigo_sms(telefono)

    if not codigo:
        cursor.close()
        conn.close()
        return jsonify({"error": "Error enviando código"}), 500
    
    # Guardamos en sesión: teléfono, empresa e ID de paciente (temporal)
    session['telefono_temp'] = telefono
    session['idEmpresa_temp'] = idEmpresa
    session['idPaciente_temp'] = paciente['idPaciente']

    cursor.close()
    conn.close()

    return jsonify({"message": "Código enviado"}), 200


# ============================================================
# VALIDAR CÓDIGO QUE EL PACIENTE RECIBE POR WHATSAPP/SMS
# ============================================================
@paciente_bp.route("/validar_codigo_empresa", methods=["POST"])
def validar_codigo_empresa():
    """
    Valida el código y completar el login.
    Valida que todo pertenezca a la empresa correcta.
    """
    data = request.get_json()
    telefono = data.get("telefono")
    codigo_ingresado = data.get("codigo")
    idEmpresa = data.get("idEmpresa")

    if not telefono or not codigo_ingresado or not idEmpresa:
        return jsonify({"error": "Datos incompletos"}), 400

    try:
        idEmpresa = int(idEmpresa)
    except:
        return jsonify({"error": "Empresa inválida"}), 400

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    # ✅ Validar código
    cursor.execute("""
        SELECT codigo FROM codigos_telefono
        WHERE Telefono=%s
        ORDER BY expiracion DESC
        LIMIT 1
    """, (telefono,))
    
    fila = cursor.fetchone()
    
    if not fila or fila["codigo"] != codigo_ingresado:
        cursor.close()
        conn.close()
        return jsonify({"error": "Código incorrecto o expirado"}), 401

    # ✅ Obtener paciente EN esa empresa
    cursor.execute("""
        SELECT idPaciente, NombrePaciente
        FROM paciente
        WHERE Telefono=%s AND idEmpresa=%s
    """, (telefono, idEmpresa))
    paciente = cursor.fetchone()

    if not paciente:
        cursor.close()
        conn.close()
        return jsonify({"error": "Paciente no encontrado en esta empresa"}), 401

    # ✅ Iniciar sesión correctamente
    session["idPaciente"] = paciente["idPaciente"]
    session["NombrePaciente"] = paciente["NombrePaciente"]
    session["idEmpresa"] = idEmpresa

    cursor.close()
    conn.close()

    return jsonify({"ok": True}), 200


# ============================================================
# ALTA DEL PACIENTE (Registro en una empresa específica)
# ============================================================
@paciente_bp.route("/empresa/<int:idEmpresa>/alta", methods=["GET", "POST"])
def alta_paciente_empresa(idEmpresa):
    """
    Registro de paciente nuevo en una empresa específica.
    La empresa viene en la URL.
    """
    mensaje = ""
    tipo_mensaje = ""

    # Validar que la empresa existe
    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT idEmpresa, RazonSocial FROM Empresa WHERE idEmpresa=%s", (idEmpresa,))
    empresa = cursor.fetchone()
    cursor.close()
    conn.close()

    if not empresa:
        return "Empresa no válida", 404

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
            return render_template("alta_paciente.html", 
                                   mensaje=mensaje, 
                                   tipo_mensaje=tipo_mensaje,
                                   empresa=empresa["RazonSocial"],
                                   telefono=telefono)

        # VALIDAR CÓDIGO WHATSAPP/SMS
        conn = conectar_bd()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT codigo, expiracion FROM codigos_telefono WHERE Telefono=%s", (telefono,))
        fila = cursor.fetchone()

        if not fila or fila["codigo"] != codigo or datetime.now() > fila["expiracion"]:
            mensaje = "❌ Código inválido o expirado."
            tipo_mensaje = "error"
            cursor.close()
            conn.close()
            return render_template("alta_paciente.html", 
                                   mensaje=mensaje, 
                                   tipo_mensaje=tipo_mensaje,
                                   empresa=empresa["RazonSocial"],
                                   telefono=telefono)

        # ✅ Verificar que el paciente no existe YA en esta empresa
        cursor.execute("""
            SELECT idPaciente FROM paciente
            WHERE Telefono=%s AND idEmpresa=%s
        """, (telefono, idEmpresa))
        
        if cursor.fetchone():
            cursor.close()
            conn.close()
            mensaje = "❌ Este teléfono ya está registrado en esta empresa."
            tipo_mensaje = "error"
            return render_template("alta_paciente.html", 
                                   mensaje=mensaje, 
                                   tipo_mensaje=tipo_mensaje,
                                   empresa=empresa["RazonSocial"],
                                   telefono=telefono)

        # ✅ INSERTAR AL PACIENTE EN LA EMPRESA
        try:
            cursor.execute("""
                INSERT INTO paciente 
                (idEmpresa, NombrePaciente, FechaNac, Telefono, Correo, CorreoValido, TokenCorreoVerificacion)
                VALUES (%s, %s, %s, %s, %s, FALSE, %s)
            """, (idEmpresa, nombre, fechanac, telefono, correo, token))

            conn.commit()
            nuevo_id = cursor.lastrowid

            cursor.close()
            conn.close()

            # Enviar correo de verificación
            enviar_correo(correo, token)

            # ✅ Iniciar sesión del paciente
            session["idPaciente"] = nuevo_id
            session["NombrePaciente"] = nombre
            session["idEmpresa"] = idEmpresa

            # Redirigir al menú del paciente
            return redirect(f"/empresa/{idEmpresa}/paciente/menu")

        except Exception as e:
            cursor.close()
            conn.close()
            mensaje = f"Error: {str(e)}"
            tipo_mensaje = "error"
            return render_template("alta_paciente.html", 
                                   mensaje=mensaje, 
                                   tipo_mensaje=tipo_mensaje,
                                   empresa=empresa["RazonSocial"],
                                   telefono=telefono)

    # GET - Mostrar formulario de alta
    telefono_param = request.args.get("telefono", "")
    return render_template("alta_paciente.html", 
                          mensaje=mensaje, 
                          tipo_mensaje=tipo_mensaje,
                          empresa=empresa["RazonSocial"],
                          telefono=telefono_param)
