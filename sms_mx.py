# sms_mx.py
import random
import logging
import base64
import requests

from config import (
    ALTIRIA_LOGIN,
    ALTIRIA_PASSWORD,
    ALTIRIA_SENDER_ID
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sms_mx")

ALTIRIA_URL = "https://www.altiria.net/api/http"

def enviar_codigo_sms(telefono):
    """
    telefono: string de 10 dígitos (sin +52)
    retorna: código OTP o None si falla
    """

    codigo = str(random.randint(100000, 999999))

    if not all([ALTIRIA_LOGIN, ALTIRIA_PASSWORD, ALTIRIA_SENDER_ID]):
        logger.error("Credenciales Altiria incompletas")
        return None

    # 🔐 BASIC AUTH (CLAVE DEL PROBLEMA)
    auth_raw = f"{ALTIRIA_LOGIN}:{ALTIRIA_PASSWORD}"
    auth_b64 = base64.b64encode(auth_raw.encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    mensaje = (
        f"{ALTIRIA_SENDER_ID}\n"
        f"Tu código de acceso es: {codigo}\n"
        "Válido por 5 minutos."
    )

    payload = {
        "cmd": "sendSMS",
        "dest": f"52{telefono}",
        "msg": mensaje,
        "senderId": ALTIRIA_SENDER_ID
    }

    try:
        response = requests.post(
            ALTIRIA_URL,
            headers=headers,
            data=payload,
            timeout=10
        )

        response.raise_for_status()

        if not response.text.startswith("OK"):
            logger.error("Altiria error: %s", response.text)
            return None

    except Exception as e:
        logger.exception("Error enviando SMS MX")
        return None

    return codigo
