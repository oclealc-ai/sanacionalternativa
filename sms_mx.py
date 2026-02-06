# sms_mx.py
from logging import config
import random
import logging
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

    logger.error("login: %s password: %s senderId: %s", ALTIRIA_LOGIN,ALTIRIA_PASSWORD,ALTIRIA_SENDER_ID)
    
    if not all([ALTIRIA_LOGIN, ALTIRIA_PASSWORD, ALTIRIA_SENDER_ID]):
        logger.error("Credenciales Altiria incompletas")
        return None

    mensaje = (
        f"{ALTIRIA_SENDER_ID}\n"
        f"Tu código de acceso es: {codigo}\n"
        "Válido por 5 minutos."
    )

    payload = {
        "cmd": "sendSMS",
        "login": ALTIRIA_LOGIN,
        "passwd": ALTIRIA_PASSWORD,
        "dest": f"52{telefono}",
        "msg": mensaje,
        "senderId": ALTIRIA_SENDER_ID
    }

    try:
        response = requests.post(
            ALTIRIA_URL,
            data=payload,
            timeout=10
        )

        response.raise_for_status()

        if not response.text.startswith("OK"):
            logger.error("Altiria error: %s", response.text)
            return None

    except Exception as e:
        logger.exception("Error enviando SMS MX: %s", str(e))
        return None

    return codigo
