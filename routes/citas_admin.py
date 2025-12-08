from flask import Blueprint, request, render_template, jsonify, session
from database import conectar_bd
from datetime import datetime, timedelta

import calendar

citas_admin_bp = Blueprint("citas_admin", __name__)

# ------------------------------------------------------------
# FUNCION AUXILIAR: REGISTRAR HISTORIAL DE CITAS
# ------------------------------------------------------------
def registrar_historial(IdCita, Usuario, Estatus, Comentario="", db=None, cursor=None):
    close_conn = False
    if db is None or cursor is None:
        db = conectar_bd()
        cursor = db.cursor()
        close_conn = True

    now = datetime.now()
    fecha = now.date()
    hora = now.time().replace(microsecond=0)

    cursor.execute("""
        INSERT INTO historial_citas (IdCita, Fecha, Hora, Usuario, Estatus, Comentario)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (IdCita, fecha, hora, Usuario, Estatus, Comentario))

    if close_conn:
        db.commit()
        cursor.close()
        db.close()
    
    
# ------------------------------------------------------------
# GENERAR CITAS
# ------------------------------------------------------------
@citas_admin_bp.route("/admin/generar_citas", methods=["GET", "POST"])
def generar_citas():
    mensaje = ""
    tipo = ""

    usuario = session.get("idUsuario", None)  # Id del usuario que generó la cita
    tipo_usuario = session.get("tipoUsuario", "Asistente")  # Opcional, para historial

    if request.method == "POST":
        mes = request.form.get("mes")
        hora_inicio = request.form.get("hora_inicio")
        hora_fin = request.form.get("hora_fin")

        hoy = datetime.now()
        anio, mes_num = map(int, mes.split("-"))

        if anio < hoy.year or (anio == hoy.year and mes_num <= hoy.month):
            return render_template("generar_citas.html",
                                   mensaje="❌ Debes seleccionar un mes futuro.",
                                   tipo="error")

        primer_dia = datetime(anio, mes_num, 1)
        ultimo_dia = datetime(anio, mes_num, calendar.monthrange(anio, mes_num)[1])

        total_creadas = 0

        h_inicio = datetime.strptime(hora_inicio, "%H:%M")
        h_fin = datetime.strptime(hora_fin, "%H:%M")

        conn = conectar_bd()
        cursor = conn.cursor()

        dia = primer_dia
        while dia <= ultimo_dia:
            if dia.weekday() < 5:
                hora_actual = h_inicio
                while hora_actual < h_fin:

                    # *** VALIDAR EMPALME ***
                    cursor.execute("""
                        SELECT COUNT(*) FROM citas
                        WHERE FechaCita = %s
                        AND TIMESTAMP(FechaCita, HoraCita)
                            BETWEEN TIMESTAMP(%s, %s)
                            AND TIMESTAMP(%s, %s + INTERVAL 40 MINUTE)
                    """, (dia.date(), dia.date(), hora_actual.time(),
                          dia.date(), hora_actual.time()))

                    existe = cursor.fetchone()[0]
                    if existe:
                        hora_actual += timedelta(minutes=40)
                        continue

                    cursor.execute("""
                        INSERT INTO citas (FechaCita, HoraCita, Estatus, FechaSolicitud, idPaciente, Notas)
                        VALUES (%s, %s, 'Disponible', NULL, NULL, '')
                    """, (dia.date(), hora_actual.time()))
                    IdCita = cursor.lastrowid  # Capturamos el ID recién insertado

                    # Registrar historial
                    #registrar_historial(
                    #    IdCita=IdCita,
                    #    Usuario=usuario,
                    #    Estatus="Disponible",
                    #    Comentario="Cita generada automáticamente")
                        
                    total_creadas += 1
                    hora_actual += timedelta(minutes=40)

            dia += timedelta(days=1)

        conn.commit()
        cursor.close()
        conn.close()

        return render_template("generar_citas.html",
                               mensaje=f"✔ Se generaron {total_creadas} citas.",
                               tipo="success")

    return render_template("generar_citas.html")
    

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

    return render_template("lista_citas.html", fecha=fecha, citas=citas)

# Página HTML para seleccionar fecha
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
    
    # Registrar historial para cada cita bloqueada
    for IdCita in ids:
        registrar_historial(IdCita, usuario, "Bloqueada", "Bloqueada desde pantalla asistente")
   
    
    afectadas = cursor.rowcount
    cursor.close()
    db.close()

    return jsonify({"mensaje": f"{afectadas} cita(s) bloqueada(s) exitosamente"})