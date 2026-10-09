# sms_mx.py
import random
import logging
import requests
import base64

from config import (LOGIN_360nrs, PASSWORD_360nrs, SENDER_ID360nrs, URL_360nrs)

logger = logging.getLogger("sms_mx")

def enviar_codigo_sms(telefono):
    """
    Genera un código de 6 dígitos y lo envía vía SMS usando la API de 360nrs.
    Retorna el código generado si el envío fue exitoso, de lo contrario None.
    """
    codigo = str(random.randint(100000, 999999))

    if not all([LOGIN_360nrs, PASSWORD_360nrs, URL_360nrs]):
        logger.error("Configuración de SMS (360nrs) incompleta en variables de entorno.")
        return None

    # Preparar autenticación Basic
    auth_raw = f"{LOGIN_360nrs}:{PASSWORD_360nrs}"
    auth_token = base64.b64encode(auth_raw.encode()).decode()

    # Formatear teléfono (asegurando prefijo de país 52 para MX)
    # Si el teléfono ya trae el 52, evitamos duplicarlo
    tel_destino = str(telefono).strip()
    if not tel_destino.startswith("52"):
        tel_destino = f"52{tel_destino}"

    payload = {
        "to": [tel_destino],
        "message": (
            f"Tu cita en CitaNet: Tu codigo de acceso es {codigo}. "
            f"Valido por 5 minutos."
        ),
        "from": SENDER_ID360nrs if SENDER_ID360nrs else "CitaNet"
    }

    headers = {
        "Authorization": f"Basic {auth_token}"
    }

    try:
        # Usamos el parámetro json= de requests para mayor limpieza
        response = requests.post(
            URL_360nrs,
            headers=headers,
            json=payload,
            timeout=10
        )

        if response.ok:
            logger.info(f"✅ SMS enviado exitosamente a {tel_destino}")
            return codigo
        else:
            logger.error(f"❌ Error de API 360nrs: {response.status_code} - {response.text}")
            return None
    
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error de red al conectar con 360nrs: {str(e)}")
        return None
    except Exception as e:
        logger.exception("❌ Error inesperado en enviar_codigo_sms")
        return None