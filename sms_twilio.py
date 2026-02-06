# sms.py
import random
import logging

from twilio.rest import Client

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sms")

#print("🔥 SMS FUNCTION EJECUTADA 🔥")

def enviar_codigo_sms(telefono):
    codigo = str(random.randint(100000, 999999))
    
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE]):
        #logger.error("Variables de Twilio incompletas")
        return None
    
    client = Client(
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN
    )
    

    try:
        client.messages.create(
            body=f"Tu código de verificación es: {codigo}",
            from_=TWILIO_PHONE,
            to=f"+52{telefono}"
        )
    
    except Exception as e:
        logger.exception("Error SMS: %s", str(e))
        return None

    return codigo
