# sms_twilio.py
import random
import logging
from twilio.rest import Client
import config

# Configuramos el logger para que coincida con el estándar del proyecto
logger = logging.getLogger("sms_twilio")

def enviar_codigo_sms(telefono):
    """
    Genera un código de 6 dígitos y lo envía vía Twilio.
    Retorna el código si el envío es exitoso, de lo contrario None.
    """
    codigo = str(random.randint(100000, 999999))
    
    # Extraemos las variables desde config (usando getattr por si están comentadas)
    sid = getattr(config, 'TWILIO_ACCOUNT_SID', None)
    token = getattr(config, 'TWILIO_AUTH_TOKEN', None)
    phone_from = getattr(config, 'TWILIO_PHONE', None)

    if not all([sid, token, phone_from]):
        logger.error("❌ Configuración de Twilio incompleta en config.py")
        return None
    
    try:
        client = Client(sid, token)
        
        # Formatear teléfono destino
        tel_destino = str(telefono).strip()
        if not tel_destino.startswith("+"):
            # Asumimos México si no tiene el signo +
            tel_destino = f"+52{tel_destino}"

        client.messages.create(
            body=f"Sanacion Alternativa: Tu codigo de verificacion es {codigo}",
            from_=phone_from,
            to=tel_destino
        )
        
        logger.info(f"✅ SMS Twilio enviado exitosamente a {tel_destino}")
        return codigo
    
    except Exception as e:
        logger.error(f"❌ Error crítico en Twilio: {str(e)}")
        return None