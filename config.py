# config.py
import os

if os.getenv("FLASK_ENV") != "production":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

# --- Base de Datos (Parámetros sueltos para SQL puro) ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# --- URI para SQLAlchemy (Migración ORM) ---
# Esta variable la usaremos en app.py para db.init_app
SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"

# --- Correo (SMTP) ---
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT")) if os.getenv("SMTP_PORT") else 587
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# --- WhatsApp API ---
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_URL = (
    f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_ID}/messages"
    if WHATSAPP_PHONE_ID
    else None
)

# --- 360nrs SMS ---
LOGIN_360nrs = os.getenv("LOGIN_360nrs")
PASSWORD_360nrs = os.getenv("PASSWORD_360nrs")
SENDER_ID360nrs = os.getenv("SENDER_ID360nrs")
URL_360nrs      = os.getenv("URL_360nrs", "https://dashboard.360nrs.com/api/rest/sms") 

URL_BASE = os.getenv("URL_BASE", "http://localhost:5000")