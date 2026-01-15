from flask import Blueprint, request, render_template, jsonify
from database import conectar_bd
from datetime import datetime, time

ver_citas_bp = Blueprint("ver_citas", __name__)


# Página que muestra el calendario
@ver_citas_bp.route("/admin/ver_citas")
def ver_citas_page():
    return render_template("ver_citas.html")


# API: devuelve eventos entre start y end (FullCalendar usa estos params)
# GET /admin/api/citas?start=2025-11-01&end=2025-12-01
@ver_citas_bp.route("/admin/api/citas")
def api_citas_rango():
    start = request.args.get("start")
    end = request.args.get("end")

    # Validación mínima
    if not start or not end:
        return jsonify({"error": "start y end requeridos"}), 400

    try:
        start_date = datetime.fromisoformat(start).date()
        end_date = datetime.fromisoformat(end).date()
    except Exception:
        return jsonify({"error": "formato de fecha inválido"}), 400

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    # Obtener citas en rango; traer nombre del paciente si existe
    cursor.execute("""
        SELECT c.idCita, c.FechaCita, c.HoraCita, c.Estatus, c.idPaciente,
               p.NombrePaciente AS nombre_paciente
        FROM citas c
        LEFT JOIN paciente p ON c.idPaciente = p.IdPaciente
        WHERE c.FechaCita BETWEEN %s AND %s
    """, (start_date, end_date))
    filas = cursor.fetchall()
    cursor.close()
    conn.close()

    # Mapeo de colores por Estatus
    color_map = {
        "disponible": "#66bb6a",   # verde
        "programada": "#2196f3",   # azul
        "confirmada": "#00bcd4",   # turquesa
        "cancelada": "#9e9e9e",    # gris
        "realizada": "#8e24aa",    # morado
        "cerrada": "#212121"       # negro
    }

    eventos = []
    for f in filas:
        fecha = f["FechaCita"]
        hora = f["HoraCita"]
        # HoraCita puede venir como time o string; normalizamos
        if isinstance(hora, str):
            hora_str = hora
        else:
            try:
                hora_str = hora.strftime("%H:%M:%S")
            except Exception:
                hora_str = str(hora)

        # construir ISO datetime para FullCalendar (sin zona)
        start_iso = f"{fecha.isoformat()}T{hora_str}"

        # Título: hora + estatus + (nombre si existe)
        titulo = f"{hora_str[:5]} — {f['Estatus']}"
        if f.get("idPaciente"):
            nombre = f.get("nombre_paciente") or "Paciente"
            titulo += f" — {nombre}"

        eventos.append({
            "id": f["idCita"],
            "title": titulo,
            "start": start_iso,
            "allDay": False,
            "color": color_map.get(f["Estatus"].lower(), "#757575"),
            "extendedProps": {
                "estatus": f["Estatus"],
                "idPaciente": f["idPaciente"],
                "nombrePaciente": f.get("nombre_paciente")
            }
        })

    return jsonify(eventos)


# API: devuelve lista de citas de un día (YYYY-MM-DD)
# GET /admin/api/citas_dia?date=2025-11-21
@ver_citas_bp.route("/admin/api/citas_dia")
def api_citas_dia():
    fecha_s = request.args.get("date")
    if not fecha_s:
        return jsonify({"error": "date requerido"}), 400

    try:
        fecha = datetime.fromisoformat(fecha_s).date()
    except Exception:
        return jsonify({"error": "formato de fecha inválido, usar YYYY-MM-DD"}), 400

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT c.idCita, c.FechaCita, c.HoraCita, c.Estatus, c.idPaciente, c.Notas,
               p.NombrePaciente AS nombre_paciente
        FROM citas c
        LEFT JOIN paciente p ON c.idPaciente = p.IdPaciente
        WHERE c.FechaCita = %s
        ORDER BY c.HoraCita
    """, (fecha,))
    filas = cursor.fetchall()
    cursor.close()
    conn.close()

    resultado = []
    for f in filas:
        hora = f["HoraCita"]
        hora_str = hora.strftime("%H:%M") if not isinstance(hora, str) else hora[:5]
        resultado.append({
            "idCita": f["idCita"],
            "hora": hora_str,
            "estatus": f["Estatus"],
            "idPaciente": f["idPaciente"],
            "nombrePaciente": f.get("nombre_paciente"),
            "notas": f.get("Notas") or ""
        })

    return jsonify(resultado)
