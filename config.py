# config.py

import os

if os.getenv("FLASK_ENV") != "production":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv no instalado (normal en producción)

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT")) if os.getenv("SMTP_PORT") else None
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_URL = (
    f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_ID}/messages"
    if WHATSAPP_PHONE_ID
    else None
)

#TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
#TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
#TWILIO_PHONE       = os.getenv("TWILIO_PHONE")

# 360nrs SMS (MX)
LOGIN_360nrs = os.getenv("LOGIN_360nrs")
PASSWORD_360nrs = os.getenv("PASSWORD_360nrs")
SENDER_ID360nrs = os.getenv("SENDER_ID360nrs")
URL_360nrs = "https://dashboard.360nrs.com/api/rest/sms"

URL_BASE = os.getenv("URL_BASE")
