from functools import wraps
from flask import Blueprint, jsonify, session, redirect, url_for, render_template, request
from modelos import db, ConfiguracionWhatsapp, Cliente  # Importamos db para poder hacer commit
from sms_mx import enviar_codigo_sms

import requests
import json
import logging
import time
import qrcode
import io
import base64
import re

logger = logging.getLogger(__name__)

# Configuración Global para Evolution API
#URL_BASE = "http://72.62.83.15:8080"
URL_BASE = "http://localhost:8080"
API_KEY_GLOBAL = "Secret0sXYZ" # Tu apikey principal de la instancia CitaNet o Global

# Definición del Blueprint
whatsapp_bp = Blueprint('whatsapp', __name__)

# --- DECORADOR DE SEGURIDAD ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # LOG DE DIAGNÓSTICO
        usuario_actual = session.get('tipoUsuario')
                
        if usuario_actual not in ['admin', 'superuser']:
            return redirect(url_for('cliente.login'))
            
        return f(*args, **kwargs)
    return decorated_function

# --- RUTA DEL WEBHOOK (PARA ACTUALIZACIÓN AUTOMÁTICA) ---
@whatsapp_bp.route("/webhook/whatsapp", methods=['POST'])
def webhook_whatsapp():
    try:
        data = request.json
        event = data.get("event")
        instance = data.get("instance")
        payload = data.get("data", {})

        # Log para ver qué llega exactamente
        logger.info(f"📩 Webhook: Evento {event} para {instance}")

        if event == "connection.update":
            status = payload.get("state") # 'open'
            
            if status == "open":
                config = ConfiguracionWhatsapp.query.filter_by(instancia=instance).first()
                if config:
                    # Extraer teléfono del ownerJid
                    owner_jid = payload.get("ownerJid", "")
                    num_limpio = owner_jid.split('@')[0] if owner_jid else config.telefono
                    
                    config.status_conexion = 'CONNECTED'
                    config.telefono = num_limpio
                    config.fecha_vinculacion = db.func.current_timestamp()
                    
                    db.session.commit()
                    logger.info(f"✅ DB Actualizada vía Webhook para {instance}: {num_limpio}")

        return jsonify({"status": "received"}), 200
    except Exception as e:
        logger.error(f"❌ Error en Webhook: {e}")
        return jsonify({"status": "error"}), 500


# --- RUTAS PARA LA VINCULACIÓN (USADAS POR EL HTML) ---

@whatsapp_bp.route("/vincular_whatsapp")
@admin_required
def vincular_whatsapp():
    id_empresa = session.get("idEmpresa")
    config = ConfiguracionWhatsapp.query.filter_by(idEmpresa=id_empresa).first()
    
    if not config:
        # Si no existe, creamos el registro base
        config = ConfiguracionWhatsapp(
            idEmpresa=id_empresa,
            instancia=f"CN_Empresa_{id_empresa}",
            status_conexion="DISCONNECTED"
        )
        db.session.add(config)
        db.session.commit()
        
    return render_template("vincular_whatsapp.html", config=config)

        
@whatsapp_bp.route("/api/generar_qr_whatsapp")
@admin_required
def api_generar_qr():
    id_empresa = session.get("idEmpresa")
    nombre_instancia = f"CN_Empresa_{id_empresa}"
    token_manual = f"TK_{id_empresa}_{int(time.time())}"
    
    headers = {"Content-Type": "application/json", "apikey": API_KEY_GLOBAL}

    try:
        # 1. Limpieza (Igual que antes)
        requests.delete(f"{URL_BASE}/instance/delete/{nombre_instancia}", headers=headers)
        time.sleep(1)

        # 2. Crear instancia (QUITAMOS EL WEBHOOK PARA QUE NO DE ERROR)
        url_create = f"{URL_BASE}/instance/create"
        payload = {
            "instanceName": nombre_instancia, 
            "token": token_manual, 
            "integration": "WHATSAPP-BAILEYS"
        }
        requests.post(url_create, json=payload, headers=headers)
        time.sleep(2)

        # 3. Obtener el código
        url_connect = f"{URL_BASE}/instance/connect/{nombre_instancia}"
        res_connect = requests.get(url_connect, headers=headers)
        
        if res_connect.status_code == 200:
            data = res_connect.json()
            raw_data = data.get("base64") or data.get("code") or (data.get("qrcode") if isinstance(data.get("qrcode"), str) else data.get("qrcode", {}).get("base64"))

            if raw_data:
                # Generación de QR (Igual que tu código original)
                if str(raw_data).startswith("2@"):
                    qr = qrcode.QRCode(version=1, box_size=10, border=5)
                    qr.add_data(raw_data)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    buffered = io.BytesIO()
                    img.save(buffered, format="PNG")
                    qr_final = "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode()
                else:
                    qr_final = raw_data if str(raw_data).startswith("data:image") else f"data:image/png;base64,{raw_data}"

                # ACTUALIZAMOS LA DB CON LA NUEVA INSTANCIA Y TOKEN
                config = ConfiguracionWhatsapp.query.filter_by(idEmpresa=id_empresa).first()
                if config:
                    config.instancia = nombre_instancia
                    config.token_instancia = token_manual
                    config.status_conexion = "DISCONNECTED" # Se resetea al generar nuevo QR
                    db.session.commit()

                return jsonify({"status": "ok", "qr_base64": qr_final})
        
        return jsonify({"status": "error", "msg": "No se pudo generar el QR."})

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return jsonify({"status": "error", "msg": str(e)})

@whatsapp_bp.route("/api/estado_whatsapp")
@admin_required
def api_estado_whatsapp():
    from datetime import datetime  # Aseguramos que use la hora del sistema
    
    id_empresa = session.get("idEmpresa")
    config = ConfiguracionWhatsapp.query.filter_by(idEmpresa=id_empresa).first()
    
    # Valores por defecto para la respuesta JSON
    res_status = "DISCONNECTED"
    res_tel = "No disponible"
    res_fecha = "---"

    if config:
        headers = {"apikey": API_KEY_GLOBAL}
        try:
            # 1. Consultar estado a la Evolution API
            res = requests.get(f"{URL_BASE}/instance/connectionState/{config.instancia}", headers=headers)
            
            if res.status_code == 200:
                data = res.json()
                inst_data = data.get("instance", {})
                estado_api = inst_data.get("state")
                
                if estado_api == 'open':
                    res_status = "CONNECTED"
                    
                    # Intentar obtener el número del ownerJid
                    owner_jid = inst_data.get("ownerJid")
                    
                    # Si no viene en el primer endpoint, lo buscamos en el fetchInstances (respaldo)
                    if not owner_jid:
                        res_fetch = requests.get(f"{URL_BASE}/instance/fetchInstances?instanceName={config.instancia}", headers=headers)
                        if res_fetch.status_code == 200:
                            instances = res_fetch.json()
                            if isinstance(instances, list) and len(instances) > 0:
                                owner_jid = instances[0].get("ownerJid")

                    # Procesar el número (quitar el @s.whatsapp.net)
                    num_extraido = None
                    if owner_jid and '@' in owner_jid:
                        num_extraido = owner_jid.split('@')[0].strip()

                    # --- ACTUALIZACIÓN FORZADA EN DB ---
                    config.status_conexion = "CONNECTED"
                    
                    # SIEMPRE actualizamos el teléfono si lo encontramos (sin el 'if not')
                    if num_extraido:
                        config.telefono = num_extraido
                    
                    # SIEMPRE actualizamos la fecha al momento actual (Hora Local)
                    config.fecha_vinculacion = datetime.now()
                    
                    db.session.commit()
                    
                    # Preparar respuesta para el HTML
                    res_tel = config.telefono
                    res_fecha = config.fecha_vinculacion.strftime('%d/%m/%Y %H:%M')
                else:
                    # Si la API responde pero no es 'open', informamos desconexión
                    res_status = "DISCONNECTED"
            else:
                # Si la instancia no existe (404), sincronizamos la DB
                if config.status_conexion != "DISCONNECTED":
                    config.status_conexion = "DISCONNECTED"
                    db.session.commit()
                res_status = "DISCONNECTED"

        except Exception as e:
            logger.error(f"Error en api_estado_whatsapp: {e}")
            res_status = "ERROR_RED"

    return jsonify({
        "status": res_status,
        "telefono": res_tel,
        "fecha": res_fecha
    })

# --- FUNCIONES DE ENVÍO ---

def enviar_whatsapp(numero, mensaje, idEmpresaEnvia=None, codigoArea=None):
    id_empresa = (
        session.get("idEmpresa") if idEmpresaEnvia is None else idEmpresaEnvia
    )

    INSTANCIA_CITANET = "CN_Empresa_1"
    instancia_a_usar = (
        f"CN_Empresa_{id_empresa}" if id_empresa else INSTANCIA_CITANET
    )
    token_a_usar = API_KEY_GLOBAL

    if id_empresa:
        config = ConfiguracionWhatsapp.query.filter_by(
            idEmpresa=id_empresa
        ).first()
        if config and config.status_conexion == "CONNECTED":
            instancia_a_usar = config.instancia
            token_a_usar = config.token_instancia
        else:
            instancia_a_usar = INSTANCIA_CITANET
            token_a_usar = API_KEY_GLOBAL

    cliente = Cliente.query.filter_by(telefono=str(numero).strip()).first()
    codigo_area = codigoArea or (cliente.pais.codigoArea if cliente and cliente.pais else None)
    numero_normalizado = normalizar_numero_whatsapp(numero, codigo_area)
    logger.info(
        f"🔍 DEBUG NORMALIZACION: Original='{numero}' -> Normalizado='{numero_normalizado}'"
    )
    endpoint = f"{URL_BASE}/message/sendText/{instancia_a_usar}"

    payload = {
        "number": numero_normalizado,
        "text": mensaje,
        "options": {
            "delay": 1200,
            "presence": "composing",
            "linkPreview": False,
        },
    }

    headers = {"Content-Type": "application/json", "apikey": token_a_usar}

    try:
        response = requests.post(
            endpoint, data=json.dumps(payload), headers=headers, timeout=10
        )
        res_data = response.json() if response.text else {}

        if response.status_code in [200, 201]:
            # Log de depuración para inspeccionar la respuesta real de Evolution API
            logger.info(
                f"✅ Respuesta API ({instancia_a_usar}): {json.dumps(res_data)}"
            )

            # Verificar si la API reporta un estado de error dentro de un 200/201
            if res_data.get("status") == "PENDING" or "key" in res_data:
                return True, "Enviado correctamente"

            # Si la respuesta trae un flag de error aunque el HTTP sea 200
            if res_data.get("error"):
                logger.error(
                    f"❌ Error en respuesta interna ({instancia_a_usar}): {res_data}"
                )
                return False, f"Error API: {res_data.get('error')}"

            return True, "Enviado correctamente"

        # Manejo de códigos HTTP distintos a 200/201
        logger.error(
            f"❌ Error API ({instancia_a_usar}): {response.status_code} - {response.text}"
        )

        msg_list = res_data.get("response", {}).get("message", [])
        if (
            isinstance(msg_list, list)
            and len(msg_list) > 0
            and msg_list[0].get("exists") is False
        ):
            return False, "El número no tiene WhatsApp activo"

        return False, f"Error API {response.status_code}"

    except Exception as e:
        logger.exception(f"❌ Error de conexión en whatsapp.py: {e}")
        return False, f"Error de conexión: {str(e)}"

def enviar_whatsapp_media(numero, url_media, tipo_media="document", caption="", idEmpresaEnvia=None, filename="archivo.pdf"):
    """
    tipo_media puede ser: 'image', 'document', 'video', 'audio'
    url_media: URL pública del archivo o base64
    """
    id_empresa = session.get("idEmpresa") if idEmpresaEnvia is None else idEmpresaEnvia
    INSTANCIA_CITANET = "CN_Empresa_1"
        
    instancia_a_usar = f"CN_Empresa_{id_empresa}" if id_empresa else INSTANCIA_CITANET
    token_a_usar = API_KEY_GLOBAL
    
    if id_empresa:
        config = ConfiguracionWhatsapp.query.filter_by(idEmpresa=id_empresa).first()
        if config and config.status_conexion == 'CONNECTED':
            instancia_a_usar = config.instancia
            token_a_usar = config.token_instancia

    cliente = Cliente.query.filter_by(telefono=str(numero).strip()).first()
    codigo_area = cliente.pais.codigoArea if cliente and cliente.pais else None
    numero_normalizado = normalizar_numero_whatsapp(numero, codigo_area)
    
    # CAMBIO 1: Endpoint de media en lugar de sendText
    endpoint = f"{URL_BASE}/message/sendMedia/{instancia_a_usar}"
    
    # CAMBIO 2: Payload para archivos
    payload = {
        "number": numero_normalizado,
        "mediaMessage": {
            "mediatype": tipo_media, # 'image' o 'document'
            "caption": caption,      # Texto opcional acompañando el archivo
            "media": url_media,      # URL accesible por la red (http://...) o base64
            "fileName": filename     # Nombre con extensión para el receptor
        },
        "options": {
            "delay": 1200,
            "presence": "composing"
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "apikey": token_a_usar
    }

    try:
        response = requests.post(endpoint, data=json.dumps(payload), headers=headers)
        if response.status_code in [200, 201]:
            logger.info(f"✅ Archivo enviado a {numero_normalizado} vía {instancia_a_usar}")
            return True
        else:
            logger.error(f"❌ Error API Media ({instancia_a_usar}): {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.exception(f"❌ Error de conexión enviando media: {e}")
        return False


def normalizar_numero_whatsapp(numero, codigo_area=None):
    # 1. Limpieza total: remueve espacios, guiones, +, paréntesis y cualquier no-dígito
    n = re.sub(r"\D", "", str(numero or ""))

    # 2. Si son solo 10 dígitos locales, usa el país del cliente.
    if len(n) == 10:
        prefijo = re.sub(r"\D", "", str(codigo_area or "+52"))
        return f"{prefijo}{n}"

    # 3. Si viene con 13 dígitos y empieza con '521' (ej: 5218110646050) -> Quitar el '1'
    if len(n) == 13 and n.startswith("521"):
        return f"52{n[3:]}"

    return n

@whatsapp_bp.route("/desconectar_whatsapp")
@admin_required
def desconectar_whatsapp():
    id_empresa = session.get("idEmpresa")
    config = ConfiguracionWhatsapp.query.filter_by(idEmpresa=id_empresa).first()
    
    if config:
        nombre_instancia = config.instancia
        headers = {"apikey": API_KEY_GLOBAL}
        try:
            # 1. Intentar borrar la instancia físicamente de Evolution API
            requests.delete(f"{URL_BASE}/instance/delete/{nombre_instancia}", headers=headers)
            
            # 2. LIMPIEZA TOTAL en nuestra base de datos
            config.status_conexion = 'DISCONNECTED'
            config.telefono = None           # Borramos el número
            config.fecha_vinculacion = None  # Borramos la fecha
            
            db.session.commit()
            logger.info(f"🔌 Instancia {nombre_instancia} eliminada y DB limpia.")
        except Exception as e:
            logger.error(f"❌ Error al desconectar: {e}")
            
    return redirect(url_for('whatsapp.vincular_whatsapp'))