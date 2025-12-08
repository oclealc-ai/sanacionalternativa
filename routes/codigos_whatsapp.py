from flask import Blueprint, request, jsonify
from database import conectar_bd
from whatsapp import enviar_codigo_whatsapp
from datetime import datetime, timedelta

codigos_whatsapp_bp = Blueprint("codigos_whatsapp", __name__)

@codigos_whatsapp_bp.route("/enviar_codigo", methods=["POST"])
def enviar_codigo():
    #telefono = request.json.get("telefono")
    data = request.get_json()
    telefono = data.get("telefono")
    modo = data.get("modo")  # --- "login" o "alta"
    
    print("DATOS QUE LLEGAN:", modo, telefono)
    
    if not telefono:
        return jsonify({"status": "error", "msg": "Teléfono requerido"})
    
    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    # ✔️ Verificar si el paciente existe
    cursor.execute("""
        SELECT IdPaciente 
        FROM paciente 
        WHERE Telefono = %s
    """, (telefono,))
    existe = cursor.fetchone()

    cursor.close()
    conn.close()

    print("EXISTE:", existe, "MODO:", modo)
    
    if not existe and modo == "login":
        # ERROR: Paciente NO registrado
        return jsonify({"status": "no_encontrado"})
    
    
    codigo = enviar_codigo_whatsapp(telefono)
    if not codigo:
        return jsonify({"status": "error"}), 500

    db = conectar_bd()
    cursor = db.cursor()

    cursor.execute("DELETE FROM codigos_telefono WHERE telefono=%s", (telefono,))
    cursor.execute("""
        INSERT INTO codigos_telefono (telefono, codigo, expiracion)
        VALUES (%s, %s, %s)
    """, (telefono, codigo, datetime.now() + timedelta(minutes=5)))

    db.commit()
    cursor.close()
    db.close()

    return jsonify({"status": "ok"})


@codigos_whatsapp_bp.route("/validar_codigo", methods=["POST"])
def validar_codigo():
    telefono = request.json.get("telefono")
    codigo = request.json.get("codigo")

    db = conectar_bd()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM codigos_telefono WHERE telefono=%s", (telefono,))
    fila = cursor.fetchone()

    if not fila:
        return jsonify({"validado": False})

    if fila["codigo"] != codigo:
        return jsonify({"validado": False})

    if datetime.now() > fila["expiracion"]:
        return jsonify({"validado": False})

    return jsonify({"validado": True})
