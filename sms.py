# sms.py
import random
import logging

from twilio.rest import Client

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_API_KEY,
    TWILIO_API_SECRET,
    TWILIO_PHONE
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sms")

print("🔥 SMS FUNCTION EJECUTADA 🔥")

def enviar_codigo_sms(telefono):
    codigo = str(random.randint(100000, 999999))

    logger.info("Entrando a enviar_codigo_sms")
    logger.warning(f"TWILIO_API_KEY: {TWILIO_API_KEY}")
    logger.warning(f"TWILIO_API_SECRET: {TWILIO_API_SECRET}")   
    logger.warning(f"TWILIO_ACCOUNT_SID: {TWILIO_ACCOUNT_SID}")
    logger.warning(f"TWILIO_PHONE: {TWILIO_PHONE}")
    
    if not all([TWILIO_ACCOUNT_SID, TWILIO_API_KEY, TWILIO_API_SECRET, TWILIO_PHONE]):
        logger.error("Variables de Twilio incompletas")
        return None
    
    client = Client(
        TWILIO_API_KEY,
        TWILIO_API_SECRET,
        TWILIO_ACCOUNT_SID
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
