import os

# -------------------------------
# CONFIGURACIÓN BASE DE DATOS
# -------------------------------
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# -------------------------------
# CONFIGURACIÓN SMTP (CORREO)
# -------------------------------
SMTP_SERVER = os.getenv("SMTP_SERVER", 'smtp.gmail.com')
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# -------------------------------
# URL BASE PARA ENLACES
# -------------------------------
URL_BASE = os.getenv("URL_BASE")

# -------------------------------
# CONFIGURACIÓN WHATSAPP
# -------------------------------
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_URL = f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_ID}/messages"
