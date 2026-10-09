import mysql.connector
import os
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

# El puerto suele ser 3306, lo extraemos de config o env
DB_PORT = int(os.getenv("DB_PORT", 3306))

def conectar_bd():
    """
    Crea una conexión a la base de datos MySQL para SQL puro.
    Se asegura de usar utf8mb4 para compatibilidad total con caracteres especiales.
    """
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            charset='utf8mb4',
            collation='utf8mb4_general_ci',
            use_unicode=True
        )
        return conn
    except mysql.connector.Error as err:
        print(f"❌ Error de conexión: {err}")
        raise err