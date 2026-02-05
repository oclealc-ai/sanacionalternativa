from flask import Blueprint, request, render_template, redirect, url_for, session
from database import conectar_bd
from flask import make_response
from datetime import datetime

citas_paciente_bp = Blueprint("citas_paciente", __name__)


# ✅ NUEVA RUTA: con empresa en la URL
@citas_paciente_bp.route("/empresa/<int:idEmpresa>/paciente/menu")
def menu_principal_paciente_empresa(idEmpresa):
    """Menú principal del paciente con empresa en la URL"""
    # Validar que la sesión tenga el paciente y que la empresa coincida
    if "idPaciente" not in session or session.get("idEmpresa") != idEmpresa:
        return redirect(f"/empresa/{idEmpresa}/paciente/login")
    
    return render_template(
        "menu_paciente.html",
        NombrePaciente=session.get("NombrePaciente", "Paciente"),
        idPaciente=session.get("idPaciente"),
        idEmpresa=idEmpresa)

# 🔄 RUTA ANTIGUA: mantener por compatibilidad (redirige a la nueva)
@citas_paciente_bp.route("/paciente/menu")
def menu_principal_paciente():
    """Ruta antigua - redirige a la nueva con empresa"""
    idEmpresa = session.get("idEmpresa")
    if not idEmpresa:
        return redirect("/")  # O a una página de error
    return redirect(f"/empresa/{idEmpresa}/paciente/menu")
    
        
    
@citas_paciente_bp.route("/paciente/menu_citas")
def menu_citas():
    return render_template("calendario_paciente.html")


@citas_paciente_bp.route("/paciente/mis_citas")
def mis_citas():
    idPaciente = session.get("idPaciente")

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            c.idCita,
            c.FechaCita,
            c.HoraCita,
            c.Estatus,
            c.Para,
            u.NombreUsuario AS NombreTerapeuta
        FROM citas c
        JOIN usuarios u ON u.Usuario = c.Terapeuta
        WHERE c.idPaciente = %s
          AND c.FechaCita >= CURDATE()
          AND c.Estatus IN ('Reservada', 'Confirmada', 'Cancelada')
        ORDER BY c.FechaCita, c.HoraCita
    """, (idPaciente,))

    citas = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("mis_citas.html", citas=citas)



@citas_paciente_bp.route("/paciente/citas_disponibles")
def citas_disponibles():
    fecha = request.args.get("fecha")
    terapeuta_sel = request.args.get("terapeuta") 
    
    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT Usuario, NombreUsuario
        FROM usuarios
        WHERE TipoUsuario = 'terapeuta'
        ORDER BY NombreUsuario
    """)
    terapeutas = cursor.fetchall()
    
    sql = """
        SELECT idCita, HoraCita, Terapeuta
        FROM citas
        WHERE FechaCita = %s
          AND Estatus = 'Disponible'
    """
    params = [fecha]

    if terapeuta_sel:
        sql += " AND Terapeuta = %s"
        params.append(terapeuta_sel)

    sql += " ORDER BY HoraCita"

    cursor.execute(sql, tuple(params))

    citas = cursor.fetchall()

    cursor.close()
    conn.close()

    resp = make_response(render_template(
        "lista_citas_paciente.html",
        fecha=fecha,
        citas=citas,
        terapeutas=terapeutas,       # ← para el select
        terapeuta_sel=terapeuta_sel, # ← para dejar seleccionado
        idPaciente=session.get("idPaciente")
    ))

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
    para = request.form.get("Para")
    id_paciente = session.get("idPaciente")
    tipo = request.form.get("tipo", "")  # <-- aquí recuperamos “confirmar / cancelar / reagendar”

    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE citas
        SET Estatus = 'Reservada', idPaciente = %s, FechaSolicitud = NOW(), Para = %s   
        WHERE idCita = %s AND Estatus IN ('Disponible', 'Reservada')
    """, (id_paciente, para, id_cita))

    conn.commit()
    cursor.close()
    conn.close()

    # 🔥 SI ESTA ACCIÓN VIENE DE "REAGENDAR", REGRESAR A MIS CITAS
    if tipo == "reagendar":
        return redirect(url_for("citas_paciente.mis_citas"))

    # Si es reserva normal
    return render_template("reserva_exitosa.html")


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
    