# sms.py
import random
from twilio.rest import Client
from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_API_KEY,
    TWILIO_API_SECRET,
    TWILIO_PHONE
)


def enviar_codigo_sms(telefono):
    codigo = str(random.randint(100000, 999999))

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
        print("Error SMS:", e)
        return None

    return codigo
