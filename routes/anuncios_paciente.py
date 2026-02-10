from flask          import Blueprint, render_template, session, redirect, request
from database       import conectar_bd
from datetime       import datetime
from werkzeug.utils import secure_filename

import os

anuncios_paciente_bp = Blueprint("anuncios_paciente", __name__)

@anuncios_paciente_bp.route("/paciente/mis_anuncios")
def mis_anuncios():
    if "idPaciente" not in session:
        return redirect("/login/paciente")

    id_paciente = session.get("idPaciente")

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT idAnuncio, imagen AS Imagen, descripcion AS Descripcion, urlAnuncio AS URLAnuncio, fechaInicioVigencia AS FechaInicioVigencia, fechaFinVigencia AS FechaFinVigencia
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


@anuncios_paciente_bp.route("/paciente/anuncios/nuevo")
def nuevo_anuncio():
    if "idPaciente" not in session:
        return redirect("/login/paciente")

    return render_template("paciente_anuncio_form.html", modo="nuevo")




@anuncios_paciente_bp.route("/paciente/anuncios/guardar", methods=["POST"])
def guardar_anuncio():
    print("SESSION ACTUAL en /anuncios/guardar: anuncios_paciente.py:", dict(session))
    if "idPaciente" not in session:
        return redirect("/login/paciente")

    id_paciente = session["idPaciente"]
    id_empresa = session["idEmpresa"]

    descripcion = request.form.get("descripcion", "").strip()
    url = request.form.get("url", "").strip()
    imagen = request.files.get("imagen")

    if not descripcion or not imagen:
        return "Faltan datos obligatorios", 400

    # -------- RUTA DE IMAGEN --------
    nombre_archivo = secure_filename(imagen.filename)

    ruta_base = f"static/anuncios/Empresa{id_empresa}/Paciente{id_paciente}"
    os.makedirs(ruta_base, exist_ok=True)

    ruta_final = os.path.join(ruta_base, nombre_archivo)
    imagen.save(ruta_final)

    ruta_bd = "/" + ruta_final  # para usar en HTML

    # -------- INSERT BD --------
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO anuncios
        (idEmpresa, idPaciente, imagen, descripcion, urlAnuncio, activo, fechaCreacion)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        id_empresa,
        id_paciente,
        ruta_bd,
        descripcion,
        url,
        0,  # Estado: Pendiente
        datetime.now()
    ))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect("/paciente/mis_anuncios")
