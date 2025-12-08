from flask import Blueprint, request, render_template, redirect, url_for, session
from database import conectar_bd
from flask import make_response
from datetime import datetime

citas_paciente_bp = Blueprint("citas_paciente", __name__)


@citas_paciente_bp.route("/paciente/menu")
def menu_principal_paciente():
    return render_template(
        "menu_paciente.html",
        nombre=session.get("nombrePaciente", "Paciente")
    )    
    
@citas_paciente_bp.route("/paciente/menu_citas")
def menu_citas():
    return render_template("calendario_paciente.html")


@citas_paciente_bp.route("/paciente/citas_disponibles")
def citas_disponibles():
    fecha = request.args.get("fecha")

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT idCita, HoraCita 
        FROM citas 
        WHERE FechaCita = %s AND Estatus = 'Disponible'
        ORDER BY HoraCita
    """, (fecha,))

    citas = cursor.fetchall()

    cursor.close()
    conn.close()

    resp = make_response(render_template("lista_citas_paciente.html",
                                         fecha=fecha,
                                         citas=citas,
                                         idPaciente=session.get("idPaciente")))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

# -------------------------------------------------------
# Reservar Cita
# -------------------------------------------------------
@citas_paciente_bp.route("/paciente/reservar")
def reservar_fecha_cita():
    id_cita = request.args.get("idCita")
    #id_paciente = request.args.get("idPaciente")   # Lo pasarás desde el login
    id_paciente = session.get("idPaciente")

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT FechaCita, HoraCita 
        FROM citas 
        WHERE idCita = %s
    """, (id_cita,))

    cita = cursor.fetchone()

    cursor.close()
    conn.close()

    #print("Reservar cita:", cita, id_cita, id_paciente)

    resp = make_response(render_template("reservar_cita.html",
                         cita=cita,
                         id_cita=id_cita,
                         id_paciente=id_paciente))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

  
# -------------------------------------------------------
# RESERVAR CITA → Actualiza BD
# -------------------------------------------------------
@citas_paciente_bp.route("/paciente/reservar_cita", methods=["POST"])
def reservar_cita():
    id_cita = request.form.get("idCita")
    id_paciente = session.get("idPaciente")
    tipo = request.form.get("tipo", "")  # <-- aquí recuperamos “confirmar / cancelar / reagendar”

    print("Reservando cita:", id_cita, id_paciente, tipo) 
    
    conn = conectar_bd()
    cursor = conn.cursor()

    print("FORM DATA:", request.form)
    print("idPaciente:", id_paciente)
    

    cursor.execute("""
        UPDATE citas
        SET Estatus = 'Reservada', idPaciente = %s, FechaSolicitud = NOW()
        WHERE idCita = %s AND Estatus IN ('Disponible', 'Reservada')
    """, (id_paciente, id_cita))

    conn.commit()
    cursor.close()
    conn.close()

    # 🔥 SI ESTA ACCIÓN VIENE DE "REAGENDAR", REGRESAR A MIS CITAS
    if tipo == "reagendar":
        return redirect(url_for("citas_paciente.mis_citas"))

    # Si es reserva normal
    return render_template("reserva_exitosa.html")



@citas_paciente_bp.route("/paciente/mis_citas")
def mis_citas():
    idPaciente = session.get("idPaciente")

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT idCita, FechaCita, HoraCita, Estatus
        FROM citas
        WHERE idPaciente = %s
          AND FechaCita >= CURDATE()
          AND Estatus IN ('Reservada', 'Confirmada')
        ORDER BY FechaCita, HoraCita
    """, (idPaciente,))

    citas = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("mis_citas.html", citas=citas)

# CONFIRMAR CITA. DESDE EL LISTADO DE MIS CITAS 
@citas_paciente_bp.route("/paciente/confirmar")
def confirmar_cita():
    idCita = request.args.get("idCita")

    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE citas
        SET Estatus = 'Confirmada'
        WHERE idCita = %s
    """, (idCita,))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("citas_paciente.mis_citas"))

# CANCELAR CITA. DESDE EL LISTADO DE MIS CITAS 
@citas_paciente_bp.route("/paciente/cancelar")
def cancelar_cita():
    idCita = request.args.get("idCita")

    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE citas
        SET Estatus = 'Cancelada'
        WHERE idCita = %s
    """, (idCita,))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("citas_paciente.mis_citas"))

# RE-AGENDAR CITA. DESDE EL LISTADO DE MIS CITAS 
@citas_paciente_bp.route("/paciente/reagendar")
def reagendar_cita():
    idCita = request.args.get("idCita")

    # Primero deja disponible la cita actual
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE citas
        SET Estatus = 'Disponible', idPaciente = NULL, FechaSolicitud = NULL
        WHERE idCita = %s
    """, (idCita,))

    conn.commit()
    cursor.close()
    conn.close()

    # Luego mandar al calendario para elegir nueva
    return redirect(url_for("citas_paciente.menu_citas"))

# Registra un cambio en la bitácora de la cita.
def registrar_historial(IdCita, Usuario, Estatus, Comentario=""):
    """"Registra un cambio en la bitácora de la cita."""
    db = conectar_bd()
    cursor = db.cursor()
    
    now = datetime.now()
    fecha = now.date()
    hora = now.time().replace(microsecond=0)  # sin microsegundos
    
    cursor.execute("""
        INSERT INTO historial_citas (IdCita, Fecha, Hora, Usuario, Estatus, Comentario)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (IdCita, fecha, hora, Usuario, Estatus, Comentario))
    
    db.commit()
    cursor.close()
    db.close()
    