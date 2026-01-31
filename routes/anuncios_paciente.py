from flask import Blueprint, render_template, session, redirect
from database import conectar_bd

anuncios_paciente_bp = Blueprint("anuncios_paciente", __name__)



@anuncios_paciente_bp.route("/paciente/mis_anuncios")
def mis_anuncios():
    if "idUsuario" not in session:
        return redirect("/login/paciente")

    id_paciente = session.get("idPaciente")

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT idAnuncio, Imagen, Descripcion, URLAnuncio
        FROM anuncios
        WHERE idPaciente = %s
        ORDER BY idAnuncio DESC
    """, (id_paciente,))

    anuncios = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "paciente_anuncios_listar.html",
        anuncios=anuncios
    )
