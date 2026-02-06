
import logging
logging.basicConfig(level=logging.WARNING)

from flask    import Blueprint, request, jsonify
from database import conectar_bd
from whatsapp import enviar_codigo_whatsapp
from sms_mx   import enviar_codigo_sms

from datetime import datetime, timedelta

codigos_telefono_bp = Blueprint("codigos_telefono", __name__)

@codigos_telefono_bp.route("/enviar_codigo", methods=["POST"])
def enviar_codigo():
    data = request.get_json()
    telefono = data.get("telefono")
    modo = data.get("modo")  # --- "login" o "alta"
    canal = data.get("canal", "sms")  # sms por defecto

    #print("Datos recibidos:", data)
    #print("Canal seleccionado en codigos_telefono.py:", canal)
    
    #logging.warning("🔥 DATA RECIBIDA: %s", data)
    #logging.warning("🔥 CANAL: %s", canal)


    if not telefono:
        return jsonify({"status": "error", "msg": "Teléfono requerido"})
    
    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT IdPaciente
        FROM paciente
        WHERE Telefono = %s
    """, (telefono,))
    existe = cursor.fetchone()

    cursor.close()
    conn.close()
    
    if not existe and modo == "login":
        return jsonify({"status": "no_encontrado"})
    
    
    #codigo = enviar_codigo_whatsapp(telefono)
    if canal == "whatsapp":
        codigo = enviar_codigo_whatsapp(telefono)
    else:
        codigo = enviar_codigo_sms(telefono)

    if not codigo:
        return jsonify({"status": "error"}), 500

    db = conectar_bd()
    cursor = db.cursor()

    cursor.execute("DELETE FROM codigos_telefono WHERE Telefono=%s", (telefono,))
    cursor.execute("""
        INSERT INTO codigos_telefono (Telefono, codigo, expiracion)
        VALUES (%s, %s, %s)
    """, (telefono, codigo, datetime.now() + timedelta(minutes=5)))

    db.commit()
    cursor.close()
    db.close()

    return jsonify({"status": "ok"})
