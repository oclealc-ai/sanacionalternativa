# config.py

from dotenv import load_dotenv
import os

# Carga variables de .env
load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_URL = f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_ID}/messages"

URL_BASE = os.getenv("URL_BASE")


TWILIO_SID   = "AC04cdab72efeef8ead3cc091055de9139"
TWILIO_TOKEN = "33a7183ef59eba6ab52f3e7ad5a489c5"
TWILIO_PHONE = "+12185036702"
