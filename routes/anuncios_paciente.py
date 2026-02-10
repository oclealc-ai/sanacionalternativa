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


@anuncios_paciente_bp.route("/paciente/anuncios/editar/<int:idAnuncio>")
def editar_anuncio(idAnuncio):
    if "idPaciente" not in session:
        return redirect("/login/paciente")

    id_paciente = session.get("idPaciente")

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT idAnuncio, imagen AS Imagen, descripcion AS Descripcion, urlAnuncio AS URLAnuncio, fechaInicioVigencia AS FechaInicioVigencia, fechaFinVigencia AS FechaFinVigencia, idPaciente
        FROM anuncios
        WHERE idAnuncio = %s
    """, (idAnuncio,))

    anuncio = cursor.fetchone()
    cursor.close()
    conn.close()

    if not anuncio or anuncio.get('idPaciente') != id_paciente:
        return "No autorizado", 403

    return render_template("paciente_anuncio_form.html", anuncio=anuncio)


@anuncios_paciente_bp.route("/paciente/anuncios/eliminar/<int:idAnuncio>")
def eliminar_anuncio(idAnuncio):
    if "idPaciente" not in session:
        return redirect("/login/paciente")

    id_paciente = session.get("idPaciente")
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute("SELECT idPaciente, imagen FROM anuncios WHERE idAnuncio=%s", (idAnuncio,))
    fila = cursor.fetchone()
    if not fila or fila[0] != id_paciente:
        cursor.close()
        conn.close()
        return "No autorizado", 403

    # eliminar archivo de imagen si existe
    imagen_path = fila[1]
    try:
        if imagen_path and imagen_path.startswith('/'):
            fs_path = imagen_path.lstrip('/')
            if os.path.exists(fs_path):
                os.remove(fs_path)
    except Exception:
        pass

    cursor.execute("DELETE FROM anuncios WHERE idAnuncio=%s", (idAnuncio,))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect('/paciente/mis_anuncios')




@anuncios_paciente_bp.route("/paciente/anuncios/guardar", methods=["POST"])
def guardar_anuncio():
    print("SESSION ACTUAL en /anuncios/guardar: anuncios_paciente.py:", dict(session))
    
    print("Datos recibidos en /anuncios/guardar:", {
        "descripcion": request.form.get("descripcion"),
        "url": request.form.get("url"),
        "imagen": request.files.get("imagen").filename if request.files.get("imagen") else None
    })

    id_paciente = session["idPaciente"]
    id_empresa = session["idEmpresa"]

    descripcion = request.form.get("descripcion", "").strip()
    url = request.form.get("url", "").strip()
    imagen = request.files.get("imagen")
    id_anuncio = request.form.get("idAnuncio")

    conn = conectar_bd()
    cursor = conn.cursor()

    # Si viene idAnuncio → editar
    if id_anuncio:
        # Obtener anuncio y validar pertenencia
        cursor.execute("SELECT idPaciente, imagen FROM anuncios WHERE idAnuncio=%s", (id_anuncio,))
        fila = cursor.fetchone()
        if not fila or fila[0] != id_paciente:
            cursor.close()
            conn.close()
            return "No autorizado", 403

        # Si se subió nueva imagen, reemplazar archivo
        if imagen and imagen.filename:
            nombre_archivo = secure_filename(imagen.filename)
            ruta_base = f"static/anuncios/Empresa{id_empresa}/Paciente{id_paciente}"
            os.makedirs(ruta_base, exist_ok=True)
            ruta_final = os.path.join(ruta_base, nombre_archivo)
            imagen.save(ruta_final)
            ruta_bd = "/" + ruta_final
            cursor.execute("UPDATE anuncios SET imagen=%s WHERE idAnuncio=%s", (ruta_bd, id_anuncio))

        # actualizar descripción y url
        cursor.execute("UPDATE anuncios SET descripcion=%s, urlAnuncio=%s WHERE idAnuncio=%s",
                       (descripcion, url, id_anuncio))

        conn.commit()
        cursor.close()
        conn.close()
        return redirect("/paciente/mis_anuncios")

    # Nuevo anuncio
    if not descripcion or not imagen:
        cursor.close()
        conn.close()
        return "Faltan datos obligatorios", 400

    # -------- RUTA DE IMAGEN --------
    nombre_archivo = secure_filename(imagen.filename)

    ruta_base = f"static/anuncios/Empresa{id_empresa}/Paciente{id_paciente}"
    os.makedirs(ruta_base, exist_ok=True)

    ruta_final = os.path.join(ruta_base, nombre_archivo)
    imagen.save(ruta_final)

    ruta_bd = "/" + ruta_final  # para usar en HTML

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
