from email.mime.text import MIMEText
import smtplib
import config

def enviar_correo(destino, token):
    url_verificacion = f"{config.URL_BASE}/verificar/{token}"
    mensaje = f"Hola!\n\nHaz clic en este enlace para verificar tu correo:\n{url_verificacion}"

    msg = MIMEText(mensaje)
    msg['Subject'] = 'Verifica tu correo para citas de Sanacion Alternativa'
    msg['From'] = config.SMTP_USER
    msg['To'] = destino

    server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
    server.starttls()
    server.login(config.SMTP_USER, config.SMTP_PASSWORD)
    server.send_message(msg)
    server.quit()
