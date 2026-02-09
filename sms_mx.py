# sms_mx.py
import random
import logging
import requests
import base64
import json

from config import (LOGIN_360nrs,PASSWORD_360nrs,SENDER_ID360nrs,URL_360nrs)

logger = logging.getLogger("sms_mx")

#ALTIRIA_URL = "https://api.altiria.com/api/rest/sms"

def enviar_codigo_sms(telefono):

    codigo = str(random.randint(100000, 999999))

    if not all([LOGIN_360nrs, PASSWORD_360nrs]):
        logger.error("Credenciales 360nrs incompletas")
        return None

    auth_raw = f"{LOGIN_360nrs}:{PASSWORD_360nrs}"
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
    if SENDER_ID360nrs:
        payload["from"] = SENDER_ID360nrs
    else:
        payload["from"] = "CitaNet"  # Valor por defecto si no se proporciona senderId  
        
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_token}"
    }

    try:
        response = requests.post(
            URL_360nrs,
            headers=headers,
            data=json.dumps(payload),
            timeout=10
        )

        if not response.ok:
            logger.error("360nrs HTTP error %s: %s",
                        response.status_code, response.text)
            return None
    
    except Exception as e:
        logger.exception("Error enviando SMS MX")
        return None

    return codigo
