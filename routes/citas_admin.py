from flask import Blueprint, request, render_template, jsonify, session
from database import conectar_bd
from datetime import datetime, timedelta
import logging
import calendar

logger = logging.getLogger(__name__)

citas_admin_bp = Blueprint("citas_admin", __name__)
    
# ------------------------------------------------------------
# GENERAR CITAS
# ------------------------------------------------------------
@citas_admin_bp.route("/admin/generar_citas", methods=["GET", "POST"])
def generar_citas():
    mensaje = ""
    tipo = ""

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    # -----------------------------
    # OBTENER TERAPEUTAS
    # -----------------------------
    cursor.execute("""
        SELECT idUsuario, Usuario, NombreUsuario
        FROM usuarios
        WHERE TipoUsuario='terapeuta'
        ORDER BY Usuario
    """)
    terapeutas = cursor.fetchall()  # lista de dicts con idUsuario, Usuario y NombreUsuario
    # -----------------------------
    
    usuario = session.get("Usuario", None)  # usuario que generó la cita
    id_empresa = session.get("idEmpresa", None)  # empresa del admin logueado
    
    logger.warning(f"id_empresa: {id_empresa}")
    
    if request.method == "POST":
        id_terapeuta = request.form.get("terapeuta")
        mes = request.form.get("mes")
        hora_inicio = request.form.get("hora_inicio")
        hora_fin = request.form.get("hora_fin")
        intervalo = int(request.form.get("intervalo"))
        
        hoy = datetime.now()
        anio, mes_num = map(int, mes.split("-"))

        # permitir el mes actual (solo las fechas restantes), pero bloquear meses pasados
        if anio < hoy.year or (anio == hoy.year and mes_num < hoy.month):
            return render_template("generar_citas.html",
                                   mensaje="❌ Debes seleccionar un mes futuro o el mes actual.",
                                   tipo="error",
                                   terapeutas=terapeutas)

        primer_dia = datetime(anio, mes_num, 1)
        ultimo_dia = datetime(anio, mes_num, calendar.monthrange(anio, mes_num)[1])

        total_creadas = 0

        h_inicio = datetime.strptime(hora_inicio, "%H:%M")
        h_fin = datetime.strptime(hora_fin, "%H:%M")

        # si el usuario solicita el mes actual, comenzar desde el día de hoy
        if anio == hoy.year and mes_num == hoy.month:
            dia = datetime(hoy.year, hoy.month, hoy.day)
        else:
            dia = primer_dia
        while dia <= ultimo_dia:
            if dia.weekday() < 5:
                hora_actual = h_inicio
                while hora_actual < h_fin:

                    hora_fin_nueva = (hora_actual + timedelta(minutes=intervalo)).time()

                    cursor.execute("""
                        SELECT COUNT(*) AS ValidaEmpalme
                        FROM citas
                        WHERE Terapeuta = %s
                        AND FechaCita = %s
                        AND HoraCita < %s
                        AND ADDTIME(HoraCita, SEC_TO_TIME(%s*60)) > %s
                    """, (
                        id_terapeuta,
                        dia.date(),
                        hora_fin_nueva,
                        intervalo,
                        hora_actual.time()
                    ))

                    existe = cursor.fetchone()['ValidaEmpalme']

                    
                    
                    if existe:
                        hora_actual += timedelta(minutes=intervalo)
                        continue

                    cursor.execute("""
                        INSERT INTO citas (Terapeuta, FechaCita, HoraCita, Estatus, FechaSolicitud, idPaciente, Notas, Duracion, idEmpresa, Empresa)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (id_terapeuta, dia.date(), hora_actual.time(), 'Disponible', None, None, '', intervalo, id_empresa, id_empresa))
                    
                    total_creadas += 1
                    hora_actual += timedelta(minutes=intervalo)

            dia += timedelta(days=1)

        conn.commit()
        cursor.close()
        conn.close()

        return render_template("generar_citas.html",
                               mensaje=f"✔ Se generaron {total_creadas} citas.",
                               tipo="success",
                               terapeutas=terapeutas)

    cursor.close()
    conn.close()
    return render_template("generar_citas.html", terapeutas=terapeutas)
    

# ------------------------------------------------------------
# VER CALENDARIO (solo selecciona día)
# ------------------------------------------------------------
@citas_admin_bp.route("/admin/ver_citas")
def ver_citas():
    return render_template("ver_citas.html")


# ------------------------------------------------------------
# CONSULTAR citas por día → JSON
# ------------------------------------------------------------
@citas_admin_bp.route("/admin/citas_dia")
def citas_por_dia():
    fecha = request.args.get("fecha")  # YYYY-MM-DD

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT c.*, p.NombrePaciente 
        FROM citas c
        LEFT JOIN paciente p ON c.idPaciente = p.IdPaciente
        WHERE FechaCita = %s
        ORDER BY HoraCita
    """, (fecha,))

    citas = cursor.fetchall()

    cursor.close()
    conn.close()

    # Convertir HoraCita a string
    for c in citas:
        if isinstance(c['HoraCita'], timedelta):
            total_seconds = int(c['HoraCita'].total_seconds())
            horas = total_seconds // 3600
            minutos = (total_seconds % 3600) // 60
            segundos = total_seconds % 60
            c['HoraCita'] = f"{horas:02d}:{minutos:02d}:{segundos:02d}"
            
    return jsonify(citas)
    

# ------------------------------------------------------------
# PANTALLA 2: LISTA DE CITAS DEL DÍA
# ------------------------------------------------------------
@citas_admin_bp.route("/admin/lista_citas")
def lista_citas():
    fecha = request.args.get("fecha")

    usuario_logueado = session.get("Usuario")      # debe traer username
    tipo_usuario = session.get("TipoUsuario")      # debe traer 'terapeuta' o 'admin'

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT Usuario, NombreUsuario
    FROM usuarios
    WHERE TipoUsuario = 'terapeuta'
    ORDER BY NombreUsuario
    """)
    terapeutas = cursor.fetchall()


    cursor.execute("""
    SELECT 
        c.*,
        p.NombrePaciente,
        u.NombreUsuario AS NombreTerapeuta
    FROM citas c
    LEFT JOIN paciente p ON c.idPaciente = p.IdPaciente
    LEFT JOIN usuarios u ON c.Terapeuta = u.Usuario
    WHERE c.FechaCita = %s
    ORDER BY c.HoraCita
    """, (fecha,))

    citas = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "lista_citas.html",
        fecha=fecha,
        citas=citas,
        terapeutas=terapeutas,
        usuario_logueado=usuario_logueado if tipo_usuario == "terapeuta" else None
    )
    

@citas_admin_bp.route("/admin/bloquear_citas")
def bloquear_citas_html():
    return render_template("bloquear_citas.html")


# ------------------------------------------------------------
# LISTA DE CITAS POR DÍA PARA BLOQUEAR (JSON)
# ------------------------------------------------------------
@citas_admin_bp.route("/admin/lista_citas_bloquear")
def lista_citas_bloquear():
    fecha = request.args.get("fecha")
    if not fecha:
        return jsonify([])

    db = conectar_bd()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT c.IdCita, c.HoraCita, c.Estatus, c.idPaciente, p.NombrePaciente AS Paciente
        FROM citas c
        LEFT JOIN paciente p ON c.idPaciente = p.IdPaciente
        WHERE DATE(c.FechaCita) = %s
        ORDER BY c.HoraCita
    """, (fecha,))
    citas = cursor.fetchall()
    cursor.close()
    db.close()

    # Convertir HoraCita de timedelta a string "HH:MM:SS"
    for c in citas:
        if isinstance(c['HoraCita'], timedelta):
            total_seconds = int(c['HoraCita'].total_seconds())
            horas = total_seconds // 3600
            minutos = (total_seconds % 3600) // 60
            segundos = total_seconds % 60
            c['HoraCita'] = f"{horas:02d}:{minutos:02d}:{segundos:02d}"

    return jsonify(citas)

# ------------------------------------------------------------
# BLOQUEAR CITAS SELECCIONADAS (POST)
# ------------------------------------------------------------
@citas_admin_bp.route("/admin/bloquear_citas", methods=["POST"])
def bloquear_citas():
    data = request.get_json()
    ids = data.get("ids", [])
    usuario = data.get("usuario", "Asistente")
    
    if not ids:
        return jsonify({"mensaje": "No se recibieron citas para bloquear"}), 400

    db = conectar_bd()
    cursor = db.cursor()
    format_strings = ','.join(['%s'] * len(ids))
    query = f"UPDATE citas SET Estatus='Bloqueada' WHERE IdCita IN ({format_strings})"
    cursor.execute(query, tuple(ids))
    db.commit()
    
    afectadas = cursor.rowcount
    cursor.close()
    db.close()

    return jsonify({"mensaje": f"{afectadas} cita(s) bloqueada(s) exitosamente"})