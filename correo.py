from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import config
import logging

logger = logging.getLogger(__name__)

def enviar_correo(destino, token):
    url_verificacion = f"{config.URL_BASE}/verificar/{token}"
    
    # Podrías incluso usar HTML en el futuro para que se vea más profesional
    mensaje = (
        f"Hola!\n\n"
        f"Gracias por registrarte en nuestro sistema de citas.\n"
        f"Haz clic en el siguiente enlace para verificar tu correo:\n"
        f"{url_verificacion}\n\n"
        f"Si no solicitaste este registro, puedes ignorar este mensaje."
    )

    msg = MIMEText(mensaje)
    msg['Subject'] = 'Verifica tu correo - CitaNet'
    msg['From'] = config.SMTP_USER
    msg['To'] = destino

    try:
        # El uso de 'with' asegura que el servidor haga .quit() automáticamente
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()  # Cifrado de la conexión
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
            logger.info(f"✅ Correo de verificación enviado con éxito a: {destino}")
            return True
    except Exception as e:
        logger.error(f"❌ Error al enviar correo a {destino}: {str(e)}")
        return False
    
def enviar_correo_base(destino, asunto, cuerpo, correo_cliente=None, es_html=True):
    
    msg = MIMEMultipart()
    msg['Subject'] = asunto
    msg['From'] = config.SMTP_USER
    msg['To'] = destino
    
    if correo_cliente:
        msg['Reply-To'] = correo_cliente

    tipo = 'html' if es_html else 'plain'
    msg.attach(MIMEText(cuerpo, tipo))

    try:
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
            #logger.info(f"✅ Correo enviado a: {destino} | Asunto: {asunto}")
            return True
    except Exception as e:
        logger.error(f"❌ Error SMTP: {str(e)}")
        return False



def enviar_token_bienvenida(destino, token):
    asunto = f"{token} es tu código de activación - CitaNet"
    cuerpo = f"""
    <body style="font-family: sans-serif; color: #1e2a44;">
        <h2 style="color: #5bbfa6;">¡Bienvenido a CitaNet!</h2>
        <p>Tu código de verificación es: <strong style="font-size: 1.2rem;">{token}</strong></p>
    </body>
    """
    return enviar_correo_base(destino, asunto, cuerpo)
