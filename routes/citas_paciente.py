from flask    import Blueprint, request, render_template, redirect, url_for, session
from database import conectar_bd
from flask    import make_response
from datetime import datetime
from modelos  import EstatusCita

citas_paciente_bp = Blueprint("citas_paciente", __name__)


# ✅ NUEVA RUTA: con empresa en la URL
@citas_paciente_bp.route("/empresa/<int:idEmpresa>/paciente/menu")
def menu_principal_paciente_empresa(idEmpresa):
    """Menú principal del paciente con empresa en la URL"""
    # Validar que la sesión tenga el paciente y que la empresa coincida
    if "idPaciente" not in session or session.get("idEmpresa") != idEmpresa:
        return redirect(f"/empresa/{idEmpresa}/paciente/login")
    
    # Obtener el nombre de la empresa y saldo del paciente de la BD
    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT RazonSocial FROM Empresa WHERE idEmpresa=%s", (idEmpresa,))
    empresa_row = cursor.fetchone()
    
    cursor.execute("SELECT Saldo FROM paciente WHERE idPaciente=%s", (session.get("idPaciente"),))
    paciente_row = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    empresa_nombre = empresa_row["RazonSocial"] if empresa_row else "Empresa"
    saldo = paciente_row["Saldo"] if paciente_row else 0.00
    
    return render_template(
        "menu_paciente.html",
        NombrePaciente=session.get("NombrePaciente", "Paciente"),
        idPaciente=session.get("idPaciente"),
        idEmpresa=idEmpresa,
        empresa=empresa_nombre,
        saldo=saldo)

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
    idEmpresa = session.get("idEmpresa")
    
    # Obtener el nombre de la empresa de la BD
    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT RazonSocial FROM Empresa WHERE idEmpresa=%s", (idEmpresa,))
    empresa_row = cursor.fetchone()
    
    empresa_nombre = empresa_row["RazonSocial"] if empresa_row else "Empresa"
    
    # Obtener lista de terapeutas disponibles
    cursor.execute("""
        SELECT IdUsuario, NombreUsuario 
        FROM usuarios 
        WHERE idEmpresa = %s AND TipoUsuario = 'terapeuta'
        ORDER BY NombreUsuario
    """, (idEmpresa,))
    terapeutas = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template(
        "seleccionar_terapeuta.html",
        empresa=empresa_nombre,
        terapeutas=terapeutas,
        NombrePaciente=session.get("NombrePaciente", "Paciente")
    )

@citas_paciente_bp.route("/paciente/calendario_terapeuta")
def calendario_terapeuta():
    idEmpresa = session.get("idEmpresa")
    idTerapeuta = request.args.get("idTerapeuta")

    if not idTerapeuta:
        return redirect("/paciente/menu_citas")

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT RazonSocial FROM Empresa WHERE idEmpresa=%s", (idEmpresa,))
    empresa_row = cursor.fetchone()

    cursor.execute(
        "SELECT Usuario, NombreUsuario FROM usuarios WHERE idUsuario=%s AND idEmpresa=%s",
        (idTerapeuta, idEmpresa)
    )
    terapeuta_row = cursor.fetchone()

    cursor.close()
    conn.close()

    if not empresa_row or not terapeuta_row:
        return redirect("/paciente/menu_citas")

    # 🔒 GUARDAR EN SESIÓN DESPUÉS de obtenerlo
    session["idTerapeuta"] = idTerapeuta
    session["usuarioTerapeuta"] = terapeuta_row["Usuario"]
    session["nombreTerapeuta"] = terapeuta_row["NombreUsuario"]

    return render_template(
        "calendario_terapeuta.html",
        empresa=empresa_row["RazonSocial"],
        terapeuta=terapeuta_row["NombreUsuario"],
        usuarioTerapeuta=terapeuta_row["Usuario"],
        idTerapeuta=idTerapeuta,
        NombrePaciente=session.get("NombrePaciente", "Paciente")
    )


@citas_paciente_bp.route("/paciente/mis_citas")
def mis_citas():
    idPaciente = session.get("idPaciente")
    id_empresa = session.get("idEmpresa")
    
    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            c.idCita,
            c.FechaCita,
            c.HoraCita,
            c.idEstatus,
            c.Para,
            u.NombreUsuario AS NombreTerapeuta
        FROM citas c
        JOIN usuarios u ON u.Usuario = c.Terapeuta
        WHERE c.idPaciente = %s
          AND c.idEmpresa = %s
          AND c.FechaCita >= CURDATE()
          AND c.idEstatus IN (7, 3, 5)  -- Reservada, Confirmada, Cancelada
        ORDER BY c.FechaCita, c.HoraCita
    """, (idPaciente, id_empresa))

    citas = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("mis_citas.html", citas=citas)


@citas_paciente_bp.route("/paciente/citas_disponibles")
def citas_disponibles():
    
    id_empresa        = session.get("idEmpresa")
    usuario_terapeuta = session.get("usuarioTerapeuta")
    nombre_terapeuta  = session.get("nombreTerapeuta")

    fecha             = request.args.get("fecha")
    
    if not usuario_terapeuta:
        return redirect("/paciente/menu_citas")

    idDisponible = EstatusCita.id_estatus("Disponible")
    
    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    sql = """
        SELECT idCita, HoraCita, Terapeuta
        FROM citas
        WHERE FechaCita = %s
          AND idEmpresa = %s
          AND idEstatus = %s
          AND Terapeuta = %s
        ORDER BY HoraCita
    """

    cursor.execute(sql, (fecha, id_empresa, idDisponible, usuario_terapeuta))
    citas = cursor.fetchall()

    cursor.close()
    conn.close()

    resp = make_response(render_template(
        "lista_citas_paciente.html",
        fecha=fecha,
        citas=citas,
        nombreTerapeuta=nombre_terapeuta,
        usuarioTerapeuta=usuario_terapeuta,
        idTerapeuta=session.get("idTerapeuta"),
        idPaciente=session.get("idPaciente")
    ))

    return resp


# -------------------------------------------------------
# Reservar Cita
# -------------------------------------------------------
@citas_paciente_bp.route("/paciente/reservar")
def reservar_fecha_cita():
    id_cita = request.args.get("idCita")
    id_paciente = session.get("idPaciente")
    id_empresa = session.get("idEmpresa")
    
    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT FechaCita, HoraCita 
        FROM citas 
        WHERE idCita = %s AND idEmpresa = %s
    """, (id_cita, id_empresa))

    cita = cursor.fetchone()

    cursor.close()
    conn.close()

    resp = make_response(render_template("reservar_cita.html",
                         cita=cita,
                         id_cita=id_cita,
                         id_paciente=id_paciente,
                         id_empresa=id_empresa))
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
    id_empresa = session.get("idEmpresa")
    
    tipo = request.form.get("tipo", "")  # <-- aquí recuperamos “confirmar / cancelar / reagendar”
    
    idReservada = EstatusCita.id_estatus("Reservada")
    
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE citas
        SET idEstatus = %s, idPaciente = %s, FechaSolicitud = NOW(), Para = %s   
        WHERE idCita = %s AND idEmpresa = %s 
    """, (idReservada, id_paciente, para, id_cita, id_empresa))

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
    
    idConfirmada = EstatusCita.id_estatus("Confirmada")
    
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE citas
        SET idEstatus = %s
        WHERE idCita = %s
    """, (idConfirmada, idCita))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("citas_paciente.mis_citas"))

# CANCELAR CITA. DESDE EL LISTADO DE MIS CITAS 
@citas_paciente_bp.route("/paciente/cancelar")
def cancelar_cita():
    idCita = request.args.get("idCita")
    
    idCancelada = EstatusCita.id_estatus("Cancelada")
    
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE citas
        SET idEstatus = %s
        WHERE idCita = %s
    """, (idCancelada, idCita))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("citas_paciente.mis_citas"))

# RE-AGENDAR CITA. DESDE EL LISTADO DE MIS CITAS 
@citas_paciente_bp.route("/paciente/reagendar")
def reagendar_cita():
    
    idCita = request.args.get("idCita")
    
    idDisponible = EstatusCita.id_estatus("Disponible")
    
    # Primero deja disponible la cita actual
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE citas
        SET idEstatus = %s, idPaciente = NULL, FechaSolicitud = NULL
        WHERE idCita = %s
    """, (idDisponible, idCita,))

    conn.commit()
    cursor.close()
    conn.close()

    # Luego mandar al calendario para elegir nueva
    return redirect(url_for("citas_paciente.menu_citas"))
    