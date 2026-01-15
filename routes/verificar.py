from flask import Blueprint
from database import conectar_bd

verificar_bp = Blueprint("verificar", __name__)

@verificar_bp.route("/verificar/<token>")
def verificar_correo(token):
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute("UPDATE paciente SET CorreoValido = TRUE WHERE TokenCorreoVerificacion = %s", (token,))
    conn.commit()
    cursor.close()
    conn.close()
    return "<h2>Correo verificado correctamente ✔</h2>"
