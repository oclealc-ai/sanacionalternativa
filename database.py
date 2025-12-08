from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
import mysql.connector

def conectar_bd():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

