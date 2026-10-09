#from charset_normalizer.api import logger

from flask                  import Blueprint, redirect, request, render_template, jsonify, session, url_for, flash
from datetime               import date, datetime, timedelta
from routes.citas_cliente   import avisar_fila_espera, notificar_cambio_estatus
from sqlalchemy.orm         import joinedload
from modelos                import Cliente, CitaCliente, CitaProducto, ClienteEmpresa, HistorialCita, db, Cita, ColorEstatusCitaEmpresa, EstatusCita, Usuario, Producto, ProductoUsuario, PreguntaServicio, CitaPregunta, movCuenta
from constantes             import const
from whatsapp                import enviar_whatsapp

import config
import logging

logger = logging.getLogger(__name__)

citas_admin_bp = Blueprint("citas_admin", __name__)

# ==========================================
# SEGURIDAD: Middleware Staff
# ==========================================
def login_staff_required():
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        return False
    return True


def _cita_es_espacio_libre(cita):
    estatus = EstatusCita.nombre_estatus(cita.idEstatus)
    if estatus not in ('Creada', 'Disponible', 'Cancelada') or cita.idProducto:
        return False
    return not any(reserva.ocupa_lugar for reserva in cita.reservas)


def _agrupar_asistentes(reservas):
    """
    Agrupa por nombre para no repetirlo: [{'nombre': 'Ana', 'cantidad': 2}, ...]
    Respeta el orden de aparición. La comparación ignora mayúsculas y espacios.
    """
    grupos = {}
    for reserva in reservas:
        nombre = (reserva.nombre_asistente or '').strip() or 'Sin nombre'
        clave = nombre.lower()
        if clave in grupos:
            grupos[clave]['cantidad'] += 1
        else:
            grupos[clave] = {'nombre': nombre, 'cantidad': 1}
    return list(grupos.values())


def _cambiar_estatus_reservas_en_cascada(cita, id_estatus_nuevo):
    """
    Cambia a Realizada o Bloqueada todos los lugares en Reservada/Confirmada.
    Las filas con otros estatus conservan su estatus.
    Devuelve las filas que cambiaron (para enviar los mensajes).
    """
    id_reservada = EstatusCita.id_estatus('Reservada')
    id_confirmada = EstatusCita.id_estatus('Confirmada')
    cambiadas = []
    for reserva in cita.reservas:
        if reserva.idEstatus in (id_reservada, id_confirmada):
            estatus_anterior = reserva.idEstatus
            reserva.idEstatus = id_estatus_nuevo
            db.session.add(HistorialCita(
                idCita=cita.idCita,
                idCitaCliente=reserva.idCitaCliente,
                idUsuario=session.get('idUsuario') or const.ID_USUARIO_SISTEMA,
                idCliente=reserva.idCliente,
                comentario=(
                    f'Cambio de estatus: '
                    f'{EstatusCita.nombre_estatus(estatus_anterior)} -> '
                    f'{EstatusCita.nombre_estatus(id_estatus_nuevo)}'
                ),
                idEstatusAnt=estatus_anterior,
                idEstatusNew=id_estatus_nuevo
            ))
            cambiadas.append(reserva)
    return cambiadas


@citas_admin_bp.route('/admin/agenda_servicios')
def agenda_servicios():
    if not login_staff_required():
        return redirect(config.URL_BASE)

    id_empresa = session.get('idEmpresa')
    tipo_usuario = session.get('tipoUsuario')
    id_sesion = session.get('idUsuario')
    staff = Usuario.query.filter_by(
        idEmpresa=id_empresa,
        tipoUsuario='staff'
    ).order_by(Usuario.nombreUsuario).all()

    if tipo_usuario == 'staff':
        staff_seleccionado = str(id_sesion)
    else:
        solicitado = request.args.get('idUsuario', '')
        staff_seleccionado = solicitado if any(str(s.idUsuario) == solicitado for s in staff) else ''

    return render_template(
        'agenda_servicios.html',
        staff=staff,
        staff_seleccionado=staff_seleccionado,
        tipo_usuario=tipo_usuario
    )


@citas_admin_bp.route('/admin/agenda_servicios/catalogo')
def agenda_servicios_catalogo():
    if not login_staff_required():
        return jsonify({'error': 'No autorizado'}), 401

    id_empresa = session.get('idEmpresa')
    id_staff = request.args.get('staff', type=int)
    if session.get('tipoUsuario') == 'staff':
        id_staff = session.get('idUsuario')

    staff = Usuario.query.filter_by(
        idUsuario=id_staff,
        idEmpresa=id_empresa,
        tipoUsuario='staff'
    ).first()
    if not staff:
        return jsonify({'error': 'Selecciona un especialista válido.'}), 400

    try:
        productos = db.session.query(Producto).join(
            ProductoUsuario, ProductoUsuario.idProducto == Producto.idProducto
        ).filter(
            ProductoUsuario.idUsuario == staff.idUsuario,
            Producto.idEmpresa == id_empresa,
            Producto.tipo == 'servicio',
            Producto.activo.is_(True)
        ).order_by(Producto.nombre).all()

        return jsonify([{
            'id': producto.idProducto,
            'nombre': producto.nombre,
            'duracion': producto.tiempoEstimado or 0,
            'cupoMaximo': producto.cupoMaximo or 1,
            'costo': float(producto.costo or 0)
        } for producto in productos])
    except Exception:
        db.session.rollback()
        logger.exception('Error cargando servicios para la agenda semanal')
        return jsonify({'error': 'No se pudieron cargar los servicios. Revisa el log del servidor QA.'}), 500


@citas_admin_bp.route('/admin/agenda_servicios/eventos')
def agenda_servicios_eventos():
    if not login_staff_required():
        return jsonify({'error': 'No autorizado'}), 401

    id_empresa = session.get('idEmpresa')
    id_staff = request.args.get('staff', type=int)
    if session.get('tipoUsuario') == 'staff':
        id_staff = session.get('idUsuario')
    if not id_staff:
        return jsonify([])

    try:
        fecha_inicio = date.fromisoformat(request.args['start'][:10])
        fecha_fin = date.fromisoformat(request.args['end'][:10])
    except (KeyError, ValueError):
        return jsonify({'error': 'Rango de fechas inválido.'}), 400

    citas = Cita.query.options(
        joinedload(Cita.reservas).joinedload(CitaCliente.cliente),
        joinedload(Cita.producto),
        joinedload(Cita.estatus)
    ).filter(
        Cita.idEmpresa == id_empresa,
        Cita.idUsuario == id_staff,
        Cita.fechaCita >= fecha_inicio,
        Cita.fechaCita < fecha_fin,
        Cita.idCitaMaestra.is_(None)
    ).order_by(Cita.fechaCita, Cita.horaCita).all()

    # Se consultan una sola vez por request (baja latencia)
    id_reservada = EstatusCita.id_estatus('Reservada')
    id_confirmada = EstatusCita.id_estatus('Confirmada')
    id_realizada = EstatusCita.id_estatus('Realizada')
    ids_ocupan_lugar = (id_reservada, id_confirmada, id_realizada)

    eventos = []
    for cita in citas:
        reservas_activas = [r for r in cita.reservas if r.idEstatus in ids_ocupan_lugar]
        if not cita.idProducto and not reservas_activas and cita.idEstatus != const.REALIZADA:
            continue

        reservados = [r for r in reservas_activas if r.idEstatus == id_reservada]
        confirmados = [r for r in reservas_activas if r.idEstatus == id_confirmada]
        realizados = [r for r in reservas_activas if r.idEstatus == id_realizada]

        cupo_maximo = cita.cupoMaximo or 1
        es_realizada = cita.idEstatus == const.REALIZADA
        por_solicitar = 0 if es_realizada else max(cupo_maximo - len(reservas_activas), 0)

        inicio = datetime.combine(cita.fechaCita, cita.horaCita)
        fin = inicio + timedelta(minutes=cita.duracion_total() or 30)
        nombre_servicio = cita.producto.nombre if cita.producto else 'Cita'
        eventos.append({
            'id': cita.idCita,
            'title': nombre_servicio,
            'start': inicio.isoformat(),
            'end': fin.isoformat(),
            'backgroundColor': ColorEstatusCitaEmpresa.color_cita_estatus(id_empresa, cita.idEstatus),
            'extendedProps': {
                'estatus': cita.estatus.nombre if cita.estatus else '',
                'realizada': es_realizada,
                'cupoMaximo': cupo_maximo,
                'cupoOcupado': len(reservas_activas),
                'totales': {
                    'reservados': len(reservados),
                    'confirmados': len(confirmados),
                    'realizados': len(realizados),
                    'porSolicitar': por_solicitar
                },
                'reservados': _agrupar_asistentes(reservados),
                'confirmados': _agrupar_asistentes(confirmados),
                'realizados': _agrupar_asistentes(realizados)
            }
        })

    return jsonify(eventos)


@citas_admin_bp.route('/admin/agenda_servicios/crear', methods=['POST'])
def agenda_servicios_crear():
    if not login_staff_required():
        return jsonify({'success': False, 'message': 'No autorizado.'}), 401

    data = request.get_json(silent=True) or {}
    id_empresa = session.get('idEmpresa')
    id_sesion = session.get('idUsuario')
    tipo_usuario = session.get('tipoUsuario')

    try:
        id_staff = int(data.get('idUsuario'))
        id_producto = int(data.get('idProducto'))
        inicio = datetime.fromisoformat(str(data.get('inicio', '')).replace('Z', '+00:00'))
        if inicio.tzinfo:
            inicio = inicio.replace(tzinfo=None)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Especialista, servicio o fecha inválidos.'}), 400

    if tipo_usuario == 'staff' and id_staff != id_sesion:
        return jsonify({'success': False, 'message': 'Solo puedes agendar en tu propia agenda.'}), 403

    try:
        staff = Usuario.query.filter_by(
            idUsuario=id_staff,
            idEmpresa=id_empresa,
            tipoUsuario='staff'
        ).with_for_update().first()
        if not staff:
            return jsonify({'success': False, 'message': 'El especialista no pertenece a esta empresa.'}), 403

        producto = db.session.query(Producto).join(
            ProductoUsuario, ProductoUsuario.idProducto == Producto.idProducto
        ).filter(
            Producto.idProducto == id_producto,
            Producto.idEmpresa == id_empresa,
            Producto.tipo == 'servicio',
            Producto.activo.is_(True),
            ProductoUsuario.idUsuario == id_staff
        ).first()
        if not producto:
            return jsonify({'success': False, 'message': 'El servicio no está activo o no está asignado a este especialista.'}), 400

        duracion = int(producto.tiempoEstimado or 0)
        cupo_maximo = max(int(producto.cupoMaximo or 1), 1)
        if duracion <= 0:
            return jsonify({'success': False, 'message': 'El servicio debe tener una duración mayor a cero.'}), 400

        id_disponible = EstatusCita.id_estatus('Disponible')
        id_bloqueada = EstatusCita.id_estatus('Bloqueada')
        if not id_disponible or not id_bloqueada:
            return jsonify({'success': False, 'message': 'Falta configurar el estatus Disponible o Bloqueada.'}), 500

        fin = inicio + timedelta(minutes=duracion)
        citas_dia = Cita.query.filter_by(
            idEmpresa=id_empresa,
            idUsuario=id_staff,
            fechaCita=inicio.date()
        ).with_for_update().all()

        espacios_libres = []
        for existente in citas_dia:
            if existente.idCitaMaestra is not None:
                continue
            inicio_existente = datetime.combine(existente.fechaCita, existente.horaCita)
            fin_existente = inicio_existente + timedelta(minutes=existente.duracion_total() or 30)
            if inicio >= fin_existente or fin <= inicio_existente:
                continue
            if _cita_es_espacio_libre(existente):
                espacios_libres.append(existente)
            else:
                return jsonify({
                    'success': False,
                    'message': 'El horario se empalma con otra cita de este especialista.'
                }), 409

        id_creada = EstatusCita.id_estatus('Creada')
        espacio_inicio = next((c for c in espacios_libres if c.horaCita == inicio.time()), None)
        cita = espacio_inicio or Cita(
            idEmpresa=id_empresa,
            idUsuario=id_staff,
            fechaCita=inicio.date(),
            horaCita=inicio.time(),
            idEstatus=id_creada or id_disponible,
            duracion=duracion,
            cupoMaximo=cupo_maximo,
            cupoOcupado=0
        )
        if espacio_inicio is None:
            db.session.add(cita)
            db.session.flush()

        cita.idEstatus = id_disponible
        cita.idProducto = producto.idProducto
        cita.duracion = duracion
        cita.cupoMaximo = cupo_maximo
        cita.cupoOcupado = 0

        for espacio in espacios_libres:
            if espacio.idCita == cita.idCita:
                continue
            espacio.idEstatus = id_bloqueada
            espacio.idCitaMaestra = cita.idCita

        db.session.add(HistorialCita(
            idCita=cita.idCita,
            idUsuario=id_sesion,
            fechaMovimiento=datetime.now(),
            comentario=f'Cita creada para el servicio {producto.nombre}',
            idEstatusAnt=0,
            idEstatusNew=id_disponible
        ))
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Cita creada en la agenda del especialista.',
            'idCita': cita.idCita
        })
    except Exception as error:
        db.session.rollback()
        logger.exception('Error al crear cita con servicio')
        return jsonify({'success': False, 'message': 'No se pudo crear la cita.'}), 500

# ==========================================
# GENERAR AGENDA (POST/GET)
# ==========================================
@citas_admin_bp.route("/admin/generar_citas", methods=["GET", "POST"])
def generar_citas():
    if not login_staff_required(): return redirect(config.URL_BASE)

    id_empresa = session.get("idEmpresa")
    tipo_usuario = session.get("tipoUsuario")
    id_usuario_sesion = session.get("idUsuario")

    if tipo_usuario == "staff":
        staff_list = Usuario.query.filter_by(idUsuario=id_usuario_sesion).all()
    else:
        staff_list = Usuario.query.filter_by(idEmpresa=id_empresa, tipoUsuario='staff').order_by(Usuario.nombreUsuario).all()

    if request.method == "POST":
        if tipo_usuario == "staff":
            id_usuario_staff = id_usuario_sesion
        else:
            id_usuario_staff = request.form.get("staff") 

        mes_str = request.form.get("mes")
        h_inicio_str = request.form.get("hora_inicio")
        h_fin_str = request.form.get("hora_fin")
        intervalo = int(request.form.get("intervalo"))
        estatus_nombre = request.form.get("estatus_inicial")
        
        # Nuevos campos de días y descanso
        dias_seleccionados = request.form.getlist("dias") # Lista de strings ['0','1'...]
        dias_seleccionados = [int(d) for d in dias_seleccionados]
        
        # LÓGICA DE DETECCIÓN DEL SUTCH DE DESCANSO
        maneja_descanso = request.form.get("maneja_descanso") == "si"
        h_descanso_ini_str = request.form.get("descanso_inicio") if maneja_descanso else None
        h_descanso_fin_str = request.form.get("descanso_fin") if maneja_descanso else None

        id_estatus_final = EstatusCita.id_estatus(estatus_nombre)
        
        if not id_estatus_final:
            return render_template("generar_citas.html", mensaje=f"❌ Error: Estatus '{estatus_nombre}' no configurado.", tipo="error", staff=staff_list)

        hoy = datetime.now()
        try:
            anio, mes_num = map(int, mes_str.split("-"))
        except:
            return render_template("generar_citas.html", mensaje="❌ Formato de mes inválido.", tipo="error", staff=staff_list)

        h_inicio_dt = datetime.strptime(h_inicio_str, "%H:%M")
        h_fin_dt = datetime.strptime(h_fin_str, "%H:%M")
        
        # Parseo de descanso
        h_desc_ini_dt = datetime.strptime(h_descanso_ini_str, "%H:%M").time() if h_descanso_ini_str else None
        h_desc_fin_dt = datetime.strptime(h_descanso_fin_str, "%H:%M").time() if h_descanso_fin_str else None

        fecha_cursor = date(anio, mes_num, 1)
        if fecha_cursor < hoy.date(): 
            fecha_cursor = hoy.date()
        
        total_creadas = 0
        while fecha_cursor.month == mes_num:
            # Validar si el día de la semana está en la selección del usuario
            if fecha_cursor.weekday() in dias_seleccionados:
                
                citas_del_dia = Cita.query.filter_by(
                    idEmpresa=id_empresa,
                    idUsuario=id_usuario_staff,
                    fechaCita=fecha_cursor
                ).all()

                hora_actual_dt = h_inicio_dt
                while (hora_actual_dt + timedelta(minutes=intervalo)).time() <= h_fin_dt.time():
                    h_inicio_nueva = hora_actual_dt.time()
                    h_fin_nueva = (hora_actual_dt + timedelta(minutes=intervalo)).time()
                    
                    # 1. Validar si cae en horario de descanso
                    en_descanso = False
                    if h_desc_ini_dt and h_desc_fin_dt:
                        # Si el inicio de la cita o el fin de la cita tocan el rango de descanso
                        if h_inicio_nueva < h_desc_fin_dt and h_fin_nueva > h_desc_ini_dt:
                            en_descanso = True

                    if en_descanso:
                        # Si el check está activo y cae en descanso, salta limpiamente al fin del descanso
                        hora_actual_dt = datetime.combine(date.today(), h_desc_fin_dt)
                        continue

                    # 2. Validar traslape con citas existentes
                    empalmada = False
                    for cita in citas_del_dia:
                        cita_fin = (datetime.combine(date.today(), cita.horaCita) + timedelta(minutes=cita.duracion)).time()
                        if h_inicio_nueva < cita_fin and h_fin_nueva > cita.horaCita:
                            empalmada = True
                            break
                    
                    if not empalmada:
                        nueva = Cita(
                            idUsuario=id_usuario_staff,
                            fechaCita=fecha_cursor,
                            horaCita=h_inicio_nueva,
                            idEstatus=id_estatus_final,
                            duracion=intervalo,
                            idEmpresa=id_empresa,
                            notas=''
                        )
                        db.session.add(nueva)
                        db.session.flush() 

                        if id_estatus_final == EstatusCita.id_estatus("Disponible"):
                            avisar_fila_espera(nueva)


                        db.session.add(HistorialCita(
                            idCita=nueva.idCita,
                            idUsuario=id_usuario_sesion,
                            fechaMovimiento=datetime.now(),
                            comentario=f"Generación automática como {estatus_nombre}",
                            idEstatusAnt=0,
                            idEstatusNew=id_estatus_final
                        ))
                        total_creadas += 1
                        
                        hora_actual_dt += timedelta(minutes=intervalo)
                    else:
                        hora_actual_dt += timedelta(minutes=1)
                    
            fecha_cursor += timedelta(days=1)

        db.session.commit() 
        return render_template("generar_citas.html", mensaje=f"✔ Éxito: Se generaron {total_creadas} citas.", tipo="success", staff=staff_list)

    return render_template("generar_citas.html", staff=staff_list)

# ==========================================
# LISTADO Y GESTIÓN DE CITAS
# ==========================================

@citas_admin_bp.route('/admin/ver_citas_dia')
def ver_citas_dia():
    if not login_staff_required(): return redirect(config.URL_BASE)
    
    tipo_usuario = session.get('tipoUsuario')
    id_usuario_sesion = session.get('idUsuario')
    id_empresa = session.get('idEmpresa')
    hoy = datetime.now().date()
    
    # Consulta base: citas de hoy para esta empresa
    # Excluye los slots bloqueados como continuación de un servicio más
    # largo que un slot: ya se ven representados en su cita maestra
    # (Cita.duracion_total()), no deben listarse aparte.
    query = Cita.query.options(
        joinedload(Cita.estatus),
        joinedload(Cita.reservas).joinedload(CitaCliente.cliente)
    ).filter(
        Cita.idEmpresa == id_empresa,
        db.func.date(Cita.fechaCita) == hoy,
        Cita.idCitaMaestra.is_(None)
    )

    # SEGURIDAD: Si es staff, solo ve sus propias citas de hoy
    if tipo_usuario == 'staff':
        query = query.filter(Cita.idUsuario == id_usuario_sesion)
    
    citas_hoy = query.order_by(Cita.horaCita.asc()).all()
    staff_obj = Usuario.query.get(id_usuario_sesion)
    
    return render_template(
        'ver_citas_dia.html', 
        citas=citas_hoy, 
        hoy_texto=hoy.strftime("%d/%m/%Y"), 
        ColorEstatusCitaEmpresa=ColorEstatusCitaEmpresa,
        tipo_usuario=tipo_usuario,
        staff=staff_obj
    )

@citas_admin_bp.route("/admin/gestion_cita")
def gestion_cita():
    if not login_staff_required(): 
        return redirect(config.URL_BASE)
        
    id_empresa = session.get("idEmpresa")
    
    modo = request.args.get('modo', 'nuevo')
    id_cita = request.args.get('idCita')
    id_cita_cliente = request.args.get('idCitaCliente', type=int)
    cita = None
    fecha_inicial = request.args.get('fechaRaw', '')
    duracion_inicial = request.args.get('duracion', '30')
    id_usuario_inicial = request.args.get('idUsuario') or request.args.get('staffSelector') or ''
    nombre_usuario_inicial = request.args.get('nombreUsuario', 'Sin asignar')
    id_estatus_inicial = request.args.get('idEstatusId', '')

    if modo == 'nuevo':
        params = {}
        if fecha_inicial:
            params['inicio'] = fecha_inicial
        if id_usuario_inicial:
            params['idUsuario'] = id_usuario_inicial
        return redirect(url_for('citas_admin.agenda_servicios', **params))
    
    # Inicializamos la variable que viajará al HTML
    citas_anteriores = []
    saldo_pendiente = 0.0
    reserva_principal = None
    reservas_vista = []
    
    if modo == 'editar' and id_cita:
        cita = Cita.query.options(
            joinedload(Cita.reservas).joinedload(CitaCliente.cliente),
            joinedload(Cita.reservas).joinedload(CitaCliente.estatus),
            joinedload(Cita.producto),
            joinedload(Cita.usuario)
        ).get_or_404(id_cita)

        reservas_activas = [reserva for reserva in cita.reservas if reserva.ocupa_lugar]
        reserva_principal = next(
            (reserva for reserva in reservas_activas if reserva.idCitaCliente == id_cita_cliente),
            min(reservas_activas, key=lambda reserva: reserva.idCitaCliente, default=None)
        )

        cargo_cita = movCuenta.query.filter_by(
            idMovReferencia=reserva_principal.idCitaCliente if reserva_principal else None,
            idtipoMovimiento=const.MOV_CITA
        ).first()
        saldo_pendiente = float(cargo_cita.saldo) if cargo_cita else float(reserva_principal.costo or 0) if reserva_principal else 0.0

        for reserva in sorted(cita.reservas, key=lambda item: item.idCitaCliente):
            historial_reserva = HistorialCita.query.filter_by(
                idCitaCliente=reserva.idCitaCliente
            ).order_by(HistorialCita.fechaMovimiento.desc()).all()
            reservas_vista.append({
                'reserva': reserva,
                'historial': historial_reserva,
                'cargo': movCuenta.query.filter_by(
                    idMovReferencia=reserva.idCitaCliente,
                    idtipoMovimiento=const.MOV_CITA
                ).first()
            })

        ids_productos = [cita.idProducto] if cita.producto and cita.producto.tipo == 'servicio' and cita.producto.activo else []

        preguntas_disponibles = []
        if ids_productos:
            preguntas_disponibles = PreguntaServicio.query.filter(
                PreguntaServicio.idEmpresa == cita.idEmpresa,
                PreguntaServicio.idProducto.in_(ids_productos)
            ).all()

        respuestas_existentes = CitaPregunta.query.filter_by(
            idCitaCliente=reserva_principal.idCitaCliente
        ).all() if reserva_principal else []
        mapa_respuestas = {r.idPregunta: r.respuesta for r in respuestas_existentes}

        preguntas_formulario = []
        for preg in preguntas_disponibles:
            preguntas_formulario.append({
                "idPregunta": preg.idPregunta,
                "pregunta": preg.pregunta,
                "tipoDatoRespuesta": preg.tipoDatoRespuesta.lower().strip(), # Aseguramos minúsculas y sin espacios
                "respuesta_actual": mapa_respuestas.get(preg.idPregunta, "")
            })

        if reserva_principal:
            citas_pasadas = CitaCliente.query.join(Cita).filter(
                CitaCliente.idCliente == reserva_principal.idCliente,
                Cita.idEmpresa == id_empresa,
                CitaCliente.idEstatus == const.REALIZADA,
                Cita.idCita != cita.idCita
            ).order_by(Cita.fechaCita.asc(), Cita.horaCita.asc()).all()

            for reserva_pasada in citas_pasadas:
                cita_pasada = reserva_pasada.cita
                respuestas_viejas = CitaPregunta.query.filter_by(
                    idCitaCliente=reserva_pasada.idCitaCliente
                ).all()
                
                if not respuestas_viejas:
                    continue
                
                lista_preguntas_historial = []
                for rv in respuestas_viejas:
                    preg_original = PreguntaServicio.query.get(rv.idPregunta)
                    texto_pregunta = preg_original.pregunta if preg_original else "Pregunta Anterior"
                    
                    lista_preguntas_historial.append({
                        "pregunta": texto_pregunta,
                        "respuesta": rv.respuesta or ""
                    })

                fecha_str = cita_pasada.fechaCita.strftime('%d/%m/%Y') if cita_pasada.fechaCita else "--/--/----"
                hora_str = str(cita_pasada.horaCita)[:5] if cita_pasada.horaCita else "--:--"
                
                citas_anteriores.append({
                    "fecha": f"{fecha_str} {hora_str}",
                    "notas": reserva_pasada.notas or cita_pasada.notas or "",
                    "notasStaff": reserva_pasada.notasStaff or cita_pasada.notasStaff or "",
                    "preguntas": lista_preguntas_historial
                })
        fecha_inicial = f"{cita.fechaCita.isoformat()}T{str(cita.horaCita)[:8]}"
        duracion_inicial = str(cita.duracion or 30)
        id_usuario_inicial = str(cita.idUsuario or '')
        nombre_usuario_inicial = (cita.usuario.alias or cita.usuario.nombreUsuario or 'Sin asignar') if cita.usuario else 'Sin asignar'
        id_estatus_inicial = str(cita.idEstatus or '')

    if not id_estatus_inicial:
        id_estatus_inicial = str(EstatusCita.id_estatus('Creada') or 1)
        
    nombres_estatus_agenda = ('Creada', 'Disponible', 'Completa', 'Realizada')
    estatus_lista = EstatusCita.query.filter(EstatusCita.nombre.in_(nombres_estatus_agenda)).all()
    estatus_reserva_lista = EstatusCita.query.filter(
        EstatusCita.nombre.in_(('Reservada', 'Confirmada', 'Cancelada', 'Realizada', 'No Asistencia', 'Bloqueada'))
    ).all()
    clientes_empresa = ClienteEmpresa.query.filter_by(idEmpresa=id_empresa).all()
    clientes_lista = [cliente.cliente for cliente in clientes_empresa]
        
    return render_template(
        "gestion_cita.html", 
        estatus_lista=estatus_lista,
        id_estatus_realizada=const.REALIZADA,
        id_estatus_bloqueada=const.BLOQUEADA,
        clientes=clientes_lista,
        estatus_reserva_lista=estatus_reserva_lista,
        preguntas_servicio=preguntas_formulario if modo == 'editar' else [],
        cita=cita if modo == 'editar' else None,
        reserva_principal=reserva_principal,
        reservas_vista=reservas_vista,
        modo=modo,
        citas_anteriores=citas_anteriores,
        saldo_pendiente=saldo_pendiente,
        fecha_inicial=fecha_inicial,
        duracion_inicial=duracion_inicial,
        id_usuario_inicial=id_usuario_inicial,
        nombre_usuario_inicial=nombre_usuario_inicial,
        id_estatus_inicial=id_estatus_inicial,
        es_cita_realizada=bool(cita and cita.idEstatus == const.REALIZADA),
        puede_cobrar=(not cita or cita.idEstatus != const.REALIZADA or saldo_pendiente > 0.005)
    )
# ==========================================
# AGREGAR CLIENTE A UNA CITA (captura manual del staff)
# ==========================================
@citas_admin_bp.route('/admin/agregar_cliente_cita/<int:id_cita>', methods=['POST'])
def agregar_cliente_cita(id_cita):
    """
    Crea un lugar (CitaCliente en Reservada) para un cliente de la empresa,
    con su "para" opcional, y recalcula el estatus de la cita:
    Disponible mientras queden lugares, Completa cuando se llena.
    """
    if not login_staff_required():
        return jsonify({'success': False, 'message': 'No autorizado.'}), 401

    data = request.get_json(silent=True) or {}
    id_empresa = session.get('idEmpresa')
    id_sesion = session.get('idUsuario')

    try:
        id_cliente = int(data.get('idCliente'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Selecciona un cliente válido.'}), 400

    para = (data.get('para') or '').strip()[:45] or None

    try:
        # Se bloquea la fila de la cita para que dos capturas simultáneas no tomen el último lugar.
        cita = Cita.query.filter_by(idCita=id_cita, idEmpresa=id_empresa).with_for_update().first()
        if not cita:
            return jsonify({'success': False, 'message': 'La cita no existe.'}), 404

        if session.get('tipoUsuario') == 'staff' and cita.idUsuario != id_sesion:
            return jsonify({'success': False, 'message': 'Acción no permitida.'}), 403

        if cita.idCitaMaestra is not None:
            return jsonify({'success': False, 'message': 'Este horario está bloqueado por otra cita.'}), 409

        nombre_estatus = EstatusCita.nombre_estatus(cita.idEstatus)
        if nombre_estatus not in ('Creada', 'Disponible'):
            if nombre_estatus == 'Completa':
                msg = 'La cita está completa; no se pueden agregar más clientes.'
            else:
                msg = f'Con el estatus actual de la cita ({nombre_estatus}) no se pueden agregar clientes.'
            return jsonify({'success': False, 'message': msg}), 409

        if not ClienteEmpresa.query.filter_by(idCliente=id_cliente, idEmpresa=id_empresa).first():
            return jsonify({'success': False, 'message': 'El cliente no pertenece a esta empresa.'}), 403

        # Si el lugar es para el mismo cliente, "para" se guarda con el nombre del cliente
        cliente_base = db.session.get(Cliente, id_cliente)
        nombre_cliente_base = ((cliente_base.nombreCliente if cliente_base else '') or '').strip()
        if not para:
            para = nombre_cliente_base[:45] or None

        id_reservada = EstatusCita.id_estatus('Reservada')
        if not id_reservada:
            return jsonify({'success': False, 'message': 'Falta configurar el estatus Reservada.'}), 500

        # Cupo real contado desde cita_cliente (no se confía en el valor del formulario)
        cupo_maximo = max(int(cita.cupoMaximo or 1), 1)
        if cita.asientos_ocupados() >= cupo_maximo:
            cita.recalcular_estatus_cita()
            db.session.commit()
            return jsonify({'success': False, 'message': 'La cita ya está completa.'}), 409

        # Un mismo cliente puede tomar varios lugares, pero cada uno con un "para" distinto
        nombre_nuevo = (para or '').lower()
        for existente in CitaCliente.query.filter_by(idCita=cita.idCita, idCliente=id_cliente).all():
            if existente.ocupa_lugar and (existente.nombre_asistente or '').strip().lower() == nombre_nuevo:
                quien = 'para sí mismo' if nombre_nuevo == nombre_cliente_base.lower() else f'para {para}'
                return jsonify({'success': False, 'message': f'Este cliente ya tiene un lugar {quien} en la cita.'}), 409

        producto = cita.producto
        costo = producto.costo if producto else 0

        reserva = CitaCliente(
            idCita=cita.idCita,
            idCliente=id_cliente,
            idEstatus=id_reservada,
            para=para,
            costo=costo,
            fechaSolicitud=datetime.now(),
            notas=cita.notas,
            notasStaff=cita.notasStaff
        )
        db.session.add(reserva)
        db.session.flush()

        # Cita con servicio fijo (grupal): el lugar nace con su servicio
        if producto:
            db.session.add(CitaProducto(
                idCitaCliente=reserva.idCitaCliente,
                idProducto=producto.idProducto,
                cantidad=1,
                precioCobrado=costo,
                montoPagado=0
            ))

        nombre_cliente = reserva.cliente.nombreCliente if reserva.cliente else f'Cliente {id_cliente}'
        comentario = f'Lugar agregado por el staff: {nombre_cliente}' + (f' (para {para})' if para and para.lower() != nombre_cliente_base.lower() else '')
        db.session.add(HistorialCita(
            idCita=cita.idCita,
            idCitaCliente=reserva.idCitaCliente,
            idUsuario=id_sesion,
            idCliente=id_cliente,
            fechaMovimiento=datetime.now(),
            comentario=comentario,
            idEstatusAnt=0,
            idEstatusNew=id_reservada
        ))

        # Disponible mientras haya lugares; Completa cuando se llena
        estatus_anterior = cita.idEstatus
        db.session.flush()
        cita.recalcular_estatus_cita()
        if cita.idEstatus != estatus_anterior:
            db.session.add(HistorialCita(
                idCita=cita.idCita,
                idUsuario=id_sesion,
                fechaMovimiento=datetime.now(),
                comentario='Estatus actualizado al agregar un cliente',
                idEstatusAnt=estatus_anterior or 0,
                idEstatusNew=cita.idEstatus
            ))

        db.session.commit()
        notificar_cambio_estatus(cita, 'Reservada', reserva)
        return jsonify({
            'success': True,
            'message': 'Cliente agregado a la cita.',
            'idCitaCliente': reserva.idCitaCliente,
            'estatusCita': EstatusCita.nombre_estatus(cita.idEstatus),
            'cupoOcupado': cita.cupoOcupado,
            'cupoMaximo': cita.cupoMaximo
        })
    except Exception:
        db.session.rollback()
        logger.exception('Error al agregar cliente a la cita %s', id_cita)
        return jsonify({'success': False, 'message': 'No se pudo agregar el cliente a la cita.'}), 500

@citas_admin_bp.route('/admin/mensaje_grupo_cita/<int:id_cita>', methods=['POST'])
def mensaje_grupo_cita(id_cita):
    """Envía por WhatsApp un mismo mensaje a los clientes de la cita que deben recibir avisos
    (un solo mensaje por cliente aunque tenga varios lugares)."""
    if not login_staff_required():
        return jsonify({'success': False, 'message': 'Sesión no válida'}), 401
    if session.get('tipoUsuario') not in ('admin', 'staff', 'asistente', 'superuser'):
        return jsonify({'success': False, 'message': 'Sin permisos'}), 403

    id_empresa = session.get('idEmpresa')
    data = request.get_json(silent=True) or {}
    texto = (data.get('mensaje') or '').strip()[:1000]
    if not texto:
        return jsonify({'success': False, 'message': 'Escribe un mensaje.'}), 400

    cita = Cita.query.options(
        joinedload(Cita.reservas).joinedload(CitaCliente.cliente)
    ).filter_by(idCita=id_cita, idEmpresa=id_empresa).first()
    if not cita:
        return jsonify({'success': False, 'message': 'Cita no encontrada.'}), 404

    # Reciben el mensaje las reservas cuyo estatus lo permite (CitaCliente.recibe_aviso).
    # Un cliente por teléfono: se deduplica por idCliente
    clientes = {}
    for reserva in cita.reservas:
        if reserva.recibe_aviso and reserva.cliente:
            clientes[reserva.idCliente] = reserva.cliente
    if not clientes:
        return jsonify({'success': False, 'message': 'No hay clientes pendientes de asistir en esta cita.'}), 400

    empresa_nombre = session.get('NombreEmpresa', 'CitaNet')
    f_cita = cita.fechaCita.strftime('%d/%m/%Y')
    h_cita = cita.horaCita.strftime('%I:%M %p')

    enviados, fallidos = 0, []
    for cliente in clientes.values():
        nombre = cliente.nombreCliente or ''
        if not cliente.telefono:
            fallidos.append(nombre or f'#{cliente.idCliente}')
            continue
        mensaje = (
            f"📢 *{empresa_nombre}* — Aviso sobre tu cita del *{f_cita}* a las *{h_cita}*\n\n"
            f"Hola {nombre}:\n\n{texto}"
        )
        try:
            exito, _detalle = enviar_whatsapp(cliente.telefono, mensaje, idEmpresaEnvia=id_empresa)
        except Exception as e:
            logger.exception(f"Error enviando mensaje de grupo (cita {id_cita}): {e}")
            exito = False
        if exito:
            enviados += 1
        else:
            fallidos.append(nombre or f'#{cliente.idCliente}')

    msg = f'Mensaje enviado a {enviados} de {len(clientes)} cliente(s).'
    if fallidos:
        msg += ' No se pudo enviar a: ' + ', '.join(fallidos) + '.'
    return jsonify({'success': enviados > 0, 'enviados': enviados, 'fallidos': fallidos, 'message': msg})


@citas_admin_bp.route('/admin/guardar_atencion/<int:id_cita>', methods=['POST'])
def guardar_atencion(id_cita):
    if not login_staff_required(): return redirect(config.URL_BASE)
    
    cita = Cita.query.get_or_404(id_cita)
    
    if session.get('tipoUsuario') == 'staff' and cita.idUsuario != session.get('idUsuario'):
        flash("Acción no permitida.", "danger")
        return redirect(url_for('citas_admin.ver_citas_dia'))

    try:
        reservas_estatus_cambiadas = []
        nuevo_estatus = request.form.get('id_estatus')
        if nuevo_estatus:
            if cita.idEstatus != int(nuevo_estatus):
                db.session.add(HistorialCita(
                    idCita=cita.idCita,
                    idUsuario=session.get('idUsuario'),
                    fechaMovimiento=datetime.now(),
                    comentario="Estatus actualizado en atención",
                    idEstatusAnt=cita.idEstatus,
                    idEstatusNew=int(nuevo_estatus)
                ))
            cita.idEstatus = int(nuevo_estatus)
            if int(nuevo_estatus) in (const.REALIZADA, const.BLOQUEADA):
                reservas_estatus_cambiadas = _cambiar_estatus_reservas_en_cascada(
                    cita, int(nuevo_estatus)
                )
        
        # Recorremos todas las llaves enviadas por el formulario buscando el prefijo 'pregunta_'
        id_cita_cliente = request.form.get('idCitaCliente', type=int)
        reserva_preguntas = CitaCliente.query.filter_by(
            idCitaCliente=id_cita_cliente,
            idCita=cita.idCita
        ).first() if id_cita_cliente else None
        for key, val in request.form.items():
            if key.startswith('pregunta_'):
                try:
                    id_pregunta_int = int(key.split('_')[1])
                    if not reserva_preguntas:
                        continue
                    
                    # Buscamos si ya existe registro de respuesta para actualizar, sino lo creamos
                    registro_resp = CitaPregunta.query.filter_by(
                        idCitaCliente=reserva_preguntas.idCitaCliente,
                        idPregunta=id_pregunta_int
                    ).first()

                    if registro_resp:
                        registro_resp.respuesta = val if val.strip() != "" else None
                    else:
                        # Si mandan datos vacíos en una nueva respuesta, evitamos insertar basura
                        if val.strip() != "":
                            nueva_respuesta = CitaPregunta(
                                idCitaCliente=reserva_preguntas.idCitaCliente,
                                idPregunta=id_pregunta_int,
                                respuesta=val
                            )
                            db.session.add(nueva_respuesta)
                except ValueError:
                    continue # Seguridad contra inputs malformados en el DOM

        db.session.commit()

        for reserva in reservas_estatus_cambiadas:
            nombre_estatus = EstatusCita.nombre_estatus(reserva.idEstatus)
            try:
                notificar_cambio_estatus(cita, nombre_estatus, reserva)
            except Exception:
                logger.exception(
                    'Error al enviar el mensaje de estatus %s (reserva %s)',
                    nombre_estatus,
                    reserva.idCitaCliente
                )

        flash("Registro guardado exitosamente.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error al procesar la atención: {str(e)}", "danger")
    
    return redirect(url_for('citas_admin.ver_citas_dia'))

# ==========================================
# GESTIÓN MASIVA DE ESTATUS
# ==========================================

@citas_admin_bp.route("/admin/estatus_citas", methods=["GET", "POST"])
def estatus_citas():
    if not login_staff_required(): return redirect(config.URL_BASE)
    id_empresa = session.get("idEmpresa")
    tipo_usuario = session.get("tipoUsuario")

    #logger.error(f"Accediendo a estatus_citas - Usuario: {session.get('idUsuario')}, Empresa: {id_empresa}, Tipo: {tipo_usuario}")

    if request.method == "POST":
        data = request.get_json()
        ids = data.get("ids", [])
        nuevo_estatus_nombre = data.get("nuevo_estatus")
        
        id_nuevo = EstatusCita.id_estatus(nuevo_estatus_nombre)
        
        citas = Cita.query.filter(Cita.idCita.in_(ids), Cita.idEmpresa == id_empresa).all()
        for c in citas:
            # SEGURIDAD: Si es staff, solo puede modificar sus propias citas en el proceso masivo
            if tipo_usuario == 'staff' and c.idUsuario != session.get('idUsuario'):
                continue

            ant = c.idEstatus
            c.idEstatus = id_nuevo

            if id_nuevo in (EstatusCita.id_estatus("Disponible"), EstatusCita.id_estatus("Cancelada")):
                # Si esta cita había encadenado slots siguientes (servicio
                # más largo que un slot), se liberan también.
                for hija in c.citas_bloqueadas:
                    hija.idEstatus = EstatusCita.id_estatus("Disponible")
                    hija.idCitaMaestra = None

            if id_nuevo == EstatusCita.id_estatus("Disponible"):
                avisar_fila_espera(c)

            db.session.add(HistorialCita(
                idCita=c.idCita, 
                idUsuario=session.get("idUsuario"), 
                fechaMovimiento=datetime.now(), 
                comentario=f"Cambio masivo a {nuevo_estatus_nombre}",
                idEstatusAnt=ant, 
                idEstatusNew=id_nuevo
            ))
        db.session.commit()
        return jsonify({"mensaje": "Actualización masiva completada."})

    estatus_lista = ["Disponible", "Completa", "Bloqueada", "Creada", "Cancelada"]
    
    # Filtro de staff para el combo del Front
    if tipo_usuario == 'staff':
        staff_list = Usuario.query.filter_by(idUsuario=session.get('idUsuario')).all()
    else:
        staff_list = Usuario.query.filter_by(idEmpresa=id_empresa, tipoUsuario='staff').all()
    
    return render_template("estatus_citas.html", 
                           staff=staff_list, 
                           estatus_lista=estatus_lista,
                           fecha_actual=date.today())

@citas_admin_bp.route("/admin/lista_citas_estatus")
def lista_citas_estatus():
    if not login_staff_required(): return jsonify([]), 401
    
    fecha = request.args.get("fecha")
    id_staff = request.args.get("idUsuario")
    id_empresa = session.get("idEmpresa")
    tipo_usuario = session.get('tipoUsuario')

    # SEGURIDAD: Si un staff intenta consultar el ID de otro, lo forzamos al suyo
    if tipo_usuario == 'staff':
        id_staff = session.get('idUsuario')
    
    # Excluye los slots bloqueados como continuación de otra cita: ya se
    # representan dentro de su cita maestra.
    citas = Cita.query.filter_by(
        fechaCita=fecha, idEmpresa=id_empresa, idUsuario=id_staff, idCitaMaestra=None
    ).all()
    
    resultado = []
    for cita in citas:
        reservas_activas = [reserva for reserva in cita.reservas if reserva.ocupa_lugar]
        nombres = list(dict.fromkeys(
            reserva.cliente.nombreCliente
            for reserva in reservas_activas
            if reserva.cliente and reserva.cliente.nombreCliente
        ))
        resultado.append({
            "idCita": cita.idCita,
            "horaCita": cita.horaCita.strftime("%H:%M"),
            "nombreEstatus": EstatusCita.nombre_estatus(cita.idEstatus),
            "color": ColorEstatusCitaEmpresa.color_cita_estatus(id_empresa, cita.idEstatus),
            "nombreCliente": ', '.join(nombres) or (cita.producto.nombre if cita.producto else "Disponible")
        })
    return jsonify(resultado)

# ==========================================
# CONFIGURACIÓN DE COLORES POR EMPRESA
# ==========================================

@citas_admin_bp.route("/admin/configurar_colores", methods=["GET", "POST"])
def configurar_colores():
    if not login_staff_required(): return redirect(config.URL_BASE)
    
    # Solo administradores deberían configurar colores globales
    if session.get('tipoUsuario') == 'staff':
        flash("No tienes permisos para configurar colores.", "warning")
        return redirect(url_for('citas_admin.ver_citas_dia'))

    id_empresa = session.get("idEmpresa")

    if request.method == "POST":
        colores_input = request.form.to_dict()
        for id_estatus_str, color_hex in colores_input.items():
            try:
                id_est_int = int(id_estatus_str)
                config_color = ColorEstatusCitaEmpresa.query.filter_by(
                    idEmpresa=id_empresa, idEstatus=id_est_int
                ).first()

                if config_color:
                    config_color.color = color_hex
                else:
                    db.session.add(ColorEstatusCitaEmpresa(
                        idEmpresa=id_empresa, idEstatus=id_est_int, color=color_hex
                    ))
            except: continue
        
        db.session.commit()
        flash("Colores actualizados correctamente.", "success")
        return render_template("configurar_colores.html", estatus_con_colores=obtener_estatus_colores(id_empresa))

    return render_template("configurar_colores.html", estatus_con_colores=obtener_estatus_colores(id_empresa))

def obtener_estatus_colores(id_empresa):
    todos_los_estatus = EstatusCita.query.all()
    resultado = []
    for est in todos_los_estatus:
        color_reg = ColorEstatusCitaEmpresa.query.filter_by(idEmpresa=id_empresa, idEstatus=est.idEstatus).first()
        resultado.append({
            "idEstatus": est.idEstatus,
            "nombre": est.nombre,
            "color": color_reg.color if color_reg else "#5bbfa6"
        })
    return resultado