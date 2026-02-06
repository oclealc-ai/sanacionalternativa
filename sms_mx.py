# sms_mx.py
import random
import logging
import requests
import base64
import json

from config import (
    ALTIRIA_LOGIN,
    ALTIRIA_PASSWORD,
    ALTIRIA_SENDER_ID
)

logger = logging.getLogger("sms_mx")

ALTIRIA_URL = "https://api.altiria.com/api/rest/sms"


def enviar_codigo_sms(telefono):

    codigo = str(random.randint(100000, 999999))

    if not all([ALTIRIA_LOGIN, ALTIRIA_PASSWORD]):
        logger.error("Credenciales Altiria incompletas")
        return None

    auth_raw = f"{ALTIRIA_LOGIN}:{ALTIRIA_PASSWORD}"
    auth_token = base64.b64encode(auth_raw.encode()).decode()

    payload = {
        "to": [f"52{telefono}"],
        "message": (
            f"-Sanacion Alternativa- \n"
            f"Tu codigo de acceso es: {codigo} \n"
            f"Valido por 5 minutos."
        )
    }

    # senderId solo si lo tienes aprobado
    if ALTIRIA_SENDER_ID:
        payload["from"] = ALTIRIA_SENDER_ID

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_token}"
    }

    try:
        response = requests.post(
            ALTIRIA_URL,
            headers=headers,
            data=json.dumps(payload),
            timeout=10
        )

        if not response.ok:
            logger.error("Altiria HTTP error %s: %s",
                        response.status_code, response.text)
            return None
    
    except Exception as e:
        logger.exception("Error enviando SMS MX")
        return None

    return codigo
