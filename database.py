from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
import os
import mysql.connector

DB_PORT = int(os.getenv("DB_PORT", 3306))

def conectar_bd():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT
    )


