from flask                  import Blueprint, redirect, request, render_template, jsonify, session, url_for
from datetime               import datetime, timedelta
from decimal                import Decimal
from sqlalchemy.orm         import joinedload
from modelos                import CitaPregunta, PreguntaServicio, Producto, ProductoUsuario, Usuario, db, EstatusCita, Cita, CitaCliente, Cliente, ClienteEmpresa, ColorEstatusCitaEmpresa, HistorialCita, CitaProducto, movAplica, movCuenta, metodoPago
from constantes             import const
from routes.cliente         import generar_movCuenta_Cliente
from routes.citas_cliente   import avisar_fila_espera, notificar_cambio_estatus
from routes.pagos           import procesar_pagos_con_puntos, sincronizar_pagado_productos_cita
from whatsapp               import enviar_whatsapp

import config
import logging
logger = logging.getLogger(__name__)

ver_citas_bp = Blueprint("ver_citas", __name__)

# ==========================================
# SEGURIDAD: Middleware para Admin/Staff
# ==========================================
def login_sistema_required():
    """Verifica que sea un usuario del sistema"""
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        return False
    return True

# ==========================================
# VISTAS 
# ==========================================

@ver_citas_bp.route("/admin/ver_citas")
def ver_citas_page():
    if not login_sistema_required():
        return redirect(config.URL_BASE)
    return render_template("ver_citas.html")

@ver_citas_bp.route('/admin/ver_citas_semanal')
def ver_citas_semanal():
    if not login_sistema_required():
        return redirect(config.URL_BASE)

    id_empresa        = session.get('idEmpresa')
    tipo              = session.get('tipoUsuario')
    id_usuario_sesion = session.get('idUsuario')
    
    staff = []
    id_staff_seleccionado = None

    clientes = db.session.query(Cliente).join(
        ClienteEmpresa, Cliente.idCliente == ClienteEmpresa.idCliente
    ).filter(
        ClienteEmpresa.idEmpresa == id_empresa
    ).order_by(Cliente.nombreCliente).all()

    estatus_lista = EstatusCita.query.filter_by(activo=True).all()

    if tipo == 'staff':
        id_staff_seleccionado = id_usuario_sesion
    else:
        staff = Usuario.query.filter_by(
            idEmpresa=id_empresa, 
            tipoUsuario='staff'
        ).order_by(Usuario.nombreUsuario).all()
        
        id_staff_seleccionado = request.args.get('idUsuario')

    return render_template(
        'calendario_semanal.html', 
        staff=staff, 
        clientes=clientes, 
        estatus_lista=estatus_lista,
        staff_id=id_staff_seleccionado
    )

@ver_citas_bp.route('/admin/obtener_citas')
def obtener_citas():
    if not login_sistema_required():
        return jsonify({"error": "No autorizado"}), 401

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    staff_input = request.args.get('staff') # Este recibe el 'usuario' (string) del select
    
    id_empresa = session.get('idEmpresa')

    query = Cita.query.filter(Cita.idEmpresa == id_empresa)
    
    if staff_input:
        query = query.filter(Cita.idUsuario == staff_input)

    if start_str:
        query = query.filter(Cita.fechaCita >= start_str.split('T')[0])
    if end_str:
        query = query.filter(Cita.fechaCita <= end_str.split('T')[0])

    # Excluimos los slots que quedaron bloqueados como continuación de una
    # cita cuyo servicio requirió más de un slot: ya se representan como
    # parte del bloque de su cita maestra (ver duracion_total() abajo), no
    # deben pintarse como eventos aparte en la agenda.
    query = query.filter(Cita.idCitaMaestra.is_(None))

    citas = query.all()
    eventos = []

    for c in citas:
        try:
            color_hex = ColorEstatusCitaEmpresa.color_cita_estatus(id_empresa, c.idEstatus)
            if not color_hex or color_hex.lower() == '#ffffff':
                color_hex = '#28a745' if c.idEstatus == 1 else "#EC0E0E"
                    
            hora_formatted = c.horaCita.strftime("%H:%M:%S") if hasattr(c.horaCita, 'strftime') else c.horaCita

            reservas = sorted(c.reservas, key=lambda reserva: reserva.idCitaCliente)
            reservas_activas = [reserva for reserva in reservas if reserva.ocupa_lugar]
            reservas_mostrar = reservas_activas or reservas
            nombres_clientes = list(dict.fromkeys(
                reserva.cliente.nombreCliente
                for reserva in reservas_mostrar
                if reserva.cliente and reserva.cliente.nombreCliente
            ))
            nombre_c = ', '.join(nombres_clientes)
            if not nombre_c:
                nombre_c = c.producto.nombre if c.producto else c.estatus.nombre if c.estatus else 'Cita sin cliente'
            nombres_para = list(dict.fromkeys(
                reserva.para.strip()
                for reserva in reservas_activas
                if reserva.para and reserva.para.strip()
                and not (reserva.cliente and reserva.para.strip().lower() == (reserva.cliente.nombreCliente or '').strip().lower())
            ))
            para = ', '.join(nombres_para) or None
            reserva_principal = reservas_activas[0] if reservas_activas else (reservas[0] if reservas else None)
            nombre_u = c.usuario.nombreUsuario if c.usuario else "Sin asignar"
            duracion_m = c.duracion_total() if c.duracion_total() else 30
            
            inicio_dt = datetime.combine(c.fechaCita, c.horaCita)
            fin_dt = inicio_dt + timedelta(minutes=duracion_m)
                    
            eventos.append({
                'id': c.idCita,
                'title': f"{nombre_c} ({duracion_m} min) | ({nombre_u})",
                'start': f"{c.fechaCita}T{hora_formatted}",
                'end': fin_dt.isoformat(),
                'color': color_hex,
                'extendedProps': {
                    'idCliente': reserva_principal.idCliente if reserva_principal else None,
                    'idCitaCliente': reserva_principal.idCitaCliente if reserva_principal else None,
                    'idEstatusId': c.idEstatus,
                    'notas': c.notas,
                    'notasStaff': c.notasStaff,
                    'nombreCliente': nombre_c,
                    'nombreUsuario': nombre_u,
                    'para': para,
                    'estatus': c.estatus.nombre if c.estatus else 'Desconocido',
                    'duracion': duracion_m
                }
            })
        except Exception as e:
            print(f"Error procesando cita {c.idCita}: {e}")
    
    return jsonify(eventos)


@ver_citas_bp.route('/admin/calcular_horarios_dinamicos')
def calcular_horarios_dinamicos():
    """
    Calcula dinámicamente slotMinTime, slotMaxTime y slotDuration 
    basado en las citas que se van a mostrar en el período
    """
    if not login_sistema_required():
        return jsonify({"error": "No autorizado"}), 401

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    staff_input = request.args.get('staff')
    
    id_empresa = session.get('idEmpresa')
    
    # Valores por defecto si no hay citas
    min_time = "07:00:00"
    max_time = "22:00:00"
    min_duracion = "00:10:00"  # 10 minutos por defecto

    try:
        query = Cita.query.filter(Cita.idEmpresa == id_empresa)
        
        if staff_input:
            query = query.filter(Cita.idUsuario == staff_input)

        if start_str:
            query = query.filter(Cita.fechaCita >= start_str.split('T')[0])
        if end_str:
            query = query.filter(Cita.fechaCita <= end_str.split('T')[0])

        citas = query.all()

        if citas:
            # Encontrar la hora más temprana
            horas_min = []
            for c in citas:
                if c.horaCita:
                    horas_min.append(c.horaCita)
            
            if horas_min:
                min_time_obj = min(horas_min)
                # Redondear hacia abajo a la hora cerrada más cercana (sin minutos)
                min_time_obj = min_time_obj.replace(minute=0, second=0, microsecond=0)
                min_time = min_time_obj.strftime("%H:%M:%S")
            
            # Encontrar la hora más tarde + su duración
            horas_max = []
            duraciones = []
            for c in citas:
                if c.horaCita:
                    duracion_m = c.duracion if c.duracion else 30
                    duraciones.append(duracion_m)
                    end_time = (datetime.combine(datetime.today(), c.horaCita) + timedelta(minutes=duracion_m)).time()
                    horas_max.append(end_time)
            
            if horas_max:
                max_time_obj = max(horas_max)
                # Redondear hacia arriba a la hora cerrada más cercana (sin minutos)
                if max_time_obj.minute != 0 or max_time_obj.second != 0:
                    max_time_obj = (datetime.combine(datetime.today(), max_time_obj).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).time()
                max_time = max_time_obj.strftime("%H:%M:%S")
            
            # Encontrar la duración mínima
            if duraciones:
                min_dur = min(duraciones)
                # Convertir a formato HH:MM:SS (máximo en minutos)
                if min_dur < 60:
                    min_duracion = f"00:{str(min_dur).zfill(2)}:00"
                else:
                    horas = min_dur // 60
                    mins = min_dur % 60
                    min_duracion = f"{str(horas).zfill(2)}:{str(mins).zfill(2)}:00"
        
        return jsonify({
            "slotMinTime": min_time,
            "slotMaxTime": max_time,
            "slotDuration": min_duracion
        })
    
    except Exception as e:
        logger.error(f"Error calculando horarios dinámicos: {e}")
        return jsonify({
            "slotMinTime": min_time,
            "slotMaxTime": max_time,
            "slotDuration": min_duracion
        })


@ver_citas_bp.route('/admin/historial_cita/<int:id_cita>')
def historial_cita(id_cita):
    historial = db.session.query(HistorialCita, Usuario, Cliente, EstatusCita)\
        .outerjoin(Usuario, HistorialCita.idUsuario == Usuario.idUsuario)\
        .outerjoin(Cliente, HistorialCita.idCliente == Cliente.idCliente)\
        .outerjoin(EstatusCita, HistorialCita.idEstatusNew == EstatusCita.idEstatus)\
        .filter(HistorialCita.idCita == id_cita,
                HistorialCita.idCitaCliente.is_(None))\
        .order_by(HistorialCita.fechaMovimiento.desc()).all()
    # Solo eventos de la cita como espacio (creada, disponible, completa, realizada...).
    # Los movimientos de cada cliente (estatus, para, cambio de cliente) se ven en la
    # tarjeta de su reserva, así que aquí no se repiten.

    lista_historial = []
    for h, u, c, e in historial:
        nombre_cliente = (c.nombreCliente or "") if c else ""
        if u:
            nombre_usuario = u.alias if u.alias else u.nombreUsuario
        else:
            nombre_usuario = "Usuario Sistema"

        lista_historial.append({
            "fecha": h.fechaMovimiento.strftime("%d/%m %H:%M"),
            "estatus": e.nombre if e else (h.comentario or f"Estatus {h.idEstatusNew}"),
            "accion": h.comentario,
            "usuario": nombre_usuario,
            "cliente": nombre_cliente
        })
    
    return jsonify(lista_historial)

@ver_citas_bp.route('/admin/borrar_cita/<int:id_cita>', methods=['POST'])
def borrar_cita(id_cita):
    """
    Borra permanentemente una cita y todos sus registros dependientes.
    Solo accesible para usuarios tipo 'admin' o 'superuser'.
    """
    if not login_sistema_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401

    if session.get('tipoUsuario') not in ('admin', 'superuser'):
        return jsonify({"success": False, "error": "Solo un administrador puede borrar citas"}), 403

    id_empresa = session.get('idEmpresa')

    try:
        cita = Cita.query.filter_by(idCita=id_cita, idEmpresa=id_empresa).first()

        if not cita:
            return jsonify({"success": False, "error": "La cita no existe o no pertenece a esta empresa"}), 404

        # Si esta cita había encadenado slots siguientes (servicio más largo
        # que un slot), se liberan antes de borrar: si no, la FK
        # idCitaMaestra de esos slots quedaría apuntando a una cita
        # inexistente y el borrado fallaría.
        id_disp_liberar = EstatusCita.id_estatus("Disponible")
        for hija in cita.citas_bloqueadas:
            hija.idEstatus = id_disp_liberar
            hija.idCitaMaestra = None

        # Borrar los dependientes de cada reserva antes de eliminarla.
        reservas = db.session.query(CitaCliente.idCitaCliente).filter_by(idCita=id_cita).all()
        reserva_ids = [reserva_id for (reserva_id,) in reservas]
        if reserva_ids:
            HistorialCita.query.filter(
                HistorialCita.idCitaCliente.in_(reserva_ids)
            ).delete(synchronize_session=False)
            CitaPregunta.query.filter(CitaPregunta.idCitaCliente.in_(reserva_ids)).delete(synchronize_session=False)
            CitaProducto.query.filter(CitaProducto.idCitaCliente.in_(reserva_ids)).delete(synchronize_session=False)
            CitaCliente.query.filter(CitaCliente.idCitaCliente.in_(reserva_ids)).delete(synchronize_session=False)
        HistorialCita.query.filter_by(idCita=id_cita).delete(synchronize_session=False)

        db.session.delete(cita)
        db.session.commit()

        return jsonify({"success": True, "mensaje": "Cita eliminada correctamente"})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al borrar cita {id_cita}: {e}")
        return jsonify({"success": False, "error": "Ocurrió un error al borrar la cita"}), 500

@ver_citas_bp.route('/guardar_cita', methods=['POST'])
def guardar_cita():
    data = request.get_json(silent=True) or {}
    if not data.get('idCita'):
        return jsonify({
            'success': False,
            'message': 'Las citas nuevas deben crearse desde Agenda por servicio.'
        }), 409
    return _guardar_cita_existente(data)


def _guardar_cita_existente(data):
    try:
        id_cita = int(data.get('idCita'))
        id_cita_cliente = data.get('idCitaCliente')
        id_cita_cliente = int(id_cita_cliente) if id_cita_cliente else None
        id_estatus_nuevo = int(data.get('idEstatus'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Cita, reserva o estatus inválidos.'}), 400

    id_empresa = session.get('idEmpresa')
    cita = Cita.query.filter_by(idCita=id_cita, idEmpresa=id_empresa).first()
    if not cita:
        return jsonify({'success': False, 'message': 'Cita no encontrada'}), 404
    if session.get('tipoUsuario') == 'staff' and cita.idUsuario != session.get('idUsuario'):
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    reserva = CitaCliente.query.filter_by(
        idCitaCliente=id_cita_cliente,
        idCita=id_cita
    ).first() if id_cita_cliente else None
    if id_cita_cliente and not reserva:
        return jsonify({'success': False, 'message': 'La reserva no pertenece a esta cita.'}), 404

    estatus_anterior = cita.idEstatus
    estatus_anterior_reserva = reserva.idEstatus if reserva else None
    allowed_statuses = [const.CREADA, const.DISPONIBLE, const.COMPLETA, const.REALIZADA, const.BLOQUEADA]
    estados_reserva = [
        const.RESERVADA,
        const.CONFIRMADA,
        const.CANCELADA,
        const.REALIZADA,
        const.NO_ASISTENCIA,
        const.BLOQUEADA
    ]
    # "Realizada" existe tanto como estatus de reserva como de cita. Si no viene idCitaCliente
    # (botón de acción general), Realizada o Bloqueada se aplican a toda la cita.
    es_cambio_cita_completa = (
        id_estatus_nuevo in (const.REALIZADA, const.BLOQUEADA) and not reserva
    )
    if id_estatus_nuevo in estados_reserva and not es_cambio_cita_completa:
        if not reserva:
            return jsonify({'success': False, 'message': 'Selecciona la reserva del cliente que quieres actualizar.'}), 400

        # --- Validación de cupo -------------------------------------------------
        # Si la reserva pasa de un estatus que NO ocupa lugar (Cancelada, No Asistencia)
        # a uno que SÍ lo ocupa (Reservada, Confirmada, Realizada), hay que comprobar que
        # todavía haya un lugar libre. Se bloquea la fila de la cita (FOR UPDATE) para que
        # dos cambios simultáneos no se queden con el último lugar.
        ids_ocupan_lugar = [const.RESERVADA, const.CONFIRMADA, const.REALIZADA]
        if id_estatus_nuevo in ids_ocupan_lugar and estatus_anterior_reserva not in ids_ocupan_lugar:
            db.session.query(Cita.idCita).filter(Cita.idCita == cita.idCita).with_for_update().first()
            lugares_ocupados = CitaCliente.query.filter(
                CitaCliente.idCita == cita.idCita,
                CitaCliente.idEstatus.in_(ids_ocupan_lugar),
                CitaCliente.idCitaCliente != reserva.idCitaCliente
            ).count()
            cupo_maximo = max(int(cita.cupoMaximo or 1), 1)
            if lugares_ocupados >= cupo_maximo:
                db.session.rollback()
                return jsonify({
                    'success': False,
                    'message': (f'La cita ya está completa ({lugares_ocupados} de {cupo_maximo} lugares). '
                                'No se puede reactivar esta reserva mientras no se libere un lugar.')
                }), 409

        reserva.idEstatus = id_estatus_nuevo
        if id_estatus_nuevo == const.REALIZADA:
            # Mismo cargo automático que al realizar la cita completa; solo si aún no existe.
            # (procesar_cobro_cita lo actualiza después si cambia el total.)
            cargo = movCuenta.query.filter_by(
                idMovReferencia=reserva.idCitaCliente,
                idtipoMovimiento=const.MOV_CITA
            ).first()
            if not cargo:
                generar_movCuenta_Cliente(
                    idEmpresa=id_empresa,
                    idCliente=reserva.idCliente,
                    idtipoMovimiento=const.MOV_CITA,
                    idMovReferencia=reserva.idCitaCliente,
                    monto=reserva.costo,
                    idUsuario=session.get('idUsuario'),
                    notas=f'Cargo automático por completar la cita #{id_cita}'
                )
        if id_estatus_nuevo == const.NO_ASISTENCIA and estatus_anterior_reserva != const.NO_ASISTENCIA:
            ahora = datetime.now()
            cliente = reserva.cliente
            if cliente:
                cliente.faltas = (cliente.faltas or 0) + 1
                cliente.ultima_falta = ahora
            cliente_empresa = ClienteEmpresa.query.filter_by(
                idCliente=reserva.idCliente,
                idEmpresa=id_empresa
            ).first()
            if cliente_empresa:
                cliente_empresa.faltas = (cliente_empresa.faltas or 0) + 1
                cliente_empresa.ultima_falta = ahora
        cita.recalcular_estatus_cita()
        if cita.idEstatus != estatus_anterior:
            # El espacio cambió de estatus por el movimiento de esta reserva (Completa, Disponible, Vencida...)
            db.session.add(HistorialCita(
                idCita=cita.idCita,
                idUsuario=session.get('idUsuario') or const.ID_USUARIO_SISTEMA,
                comentario=f'Cambio de estatus de la cita: {EstatusCita.nombre_estatus(estatus_anterior)} -> {EstatusCita.nombre_estatus(cita.idEstatus)}',
                idEstatusAnt=estatus_anterior,
                idEstatusNew=cita.idEstatus
            ))
        nombre_anterior_reserva = EstatusCita.nombre_estatus(estatus_anterior_reserva)
        nombre_nuevo_reserva = EstatusCita.nombre_estatus(id_estatus_nuevo)
        # Si el estatus no cambió (p. ej. solo se guardó el "para" o las preguntas) no se
        # registra historial ni se avisa al cliente por WhatsApp.
        estatus_cambio = estatus_anterior_reserva != id_estatus_nuevo
        if estatus_cambio:
            db.session.add(HistorialCita(
                idCita=cita.idCita,
                idCitaCliente=reserva.idCitaCliente,
                idUsuario=session.get('idUsuario') or const.ID_USUARIO_SISTEMA,
                idCliente=reserva.idCliente,
                comentario=f'Cambio de estatus: {nombre_anterior_reserva} -> {nombre_nuevo_reserva}',
                idEstatusAnt=estatus_anterior_reserva,
                idEstatusNew=id_estatus_nuevo
            ))
        db.session.commit()
        if estatus_cambio:
            notificar_cambio_estatus(cita, nombre_nuevo_reserva, reserva)
        return jsonify({'success': True})
    # Se acepta también el estatus actual de la cita sin cambios (p. ej. Vencida o Cancelada),
    # porque la pantalla siempre manda el estatus del espacio al guardar notas.
    if id_estatus_nuevo not in allowed_statuses and id_estatus_nuevo != cita.idEstatus:
        return jsonify({'success': False, 'message': 'Ese estatus pertenece a una reserva, no a la cita.'}), 400

    if cita.idEstatus == const.REALIZADA and id_estatus_nuevo != cita.idEstatus and session.get('tipoUsuario') not in ('admin', 'superuser'):
        return jsonify({'success': False, 'message': 'Solo un administrador puede revertir una cita realizada.'}), 403

    cita.idEstatus = id_estatus_nuevo
    reservas_estatus_cambiadas = []
    if id_estatus_nuevo in (const.REALIZADA, const.BLOQUEADA):
        reservas_estatus_cambiadas = [
            r for r in cita.reservas
            if r.idEstatus in (const.RESERVADA, const.CONFIRMADA)
        ]
        for reserva_cambiada in reservas_estatus_cambiadas:
            estatus_anterior_reserva = reserva_cambiada.idEstatus
            reserva_cambiada.idEstatus = id_estatus_nuevo
            db.session.add(HistorialCita(
                idCita=cita.idCita,
                idCitaCliente=reserva_cambiada.idCitaCliente,
                idUsuario=session.get('idUsuario') or const.ID_USUARIO_SISTEMA,
                idCliente=reserva_cambiada.idCliente,
                comentario=(
                    f'Cambio de estatus: '
                    f'{EstatusCita.nombre_estatus(estatus_anterior_reserva)} -> '
                    f'{EstatusCita.nombre_estatus(id_estatus_nuevo)}'
                ),
                idEstatusAnt=estatus_anterior_reserva,
                idEstatusNew=id_estatus_nuevo
            ))
            if id_estatus_nuevo != const.REALIZADA:
                continue
            cargo = movCuenta.query.filter_by(
                idMovReferencia=reserva_cambiada.idCitaCliente,
                idtipoMovimiento=const.MOV_CITA
            ).first()
            if not cargo:
                generar_movCuenta_Cliente(
                    idEmpresa=id_empresa,
                    idCliente=reserva_cambiada.idCliente,
                    idtipoMovimiento=const.MOV_CITA,
                    idMovReferencia=reserva_cambiada.idCitaCliente,
                    monto=reserva_cambiada.costo,
                    idUsuario=session.get('idUsuario'),
                    notas=f'Cargo automático por completar la cita #{id_cita}'
                )
    cita.recalcular_estatus_cita()

    cita.notas = data.get('notas', cita.notas)
    cita.notasStaff = data.get('notasStaff', cita.notasStaff)
    nuevo_nombre = EstatusCita.nombre_estatus(id_estatus_nuevo)
    if estatus_anterior != cita.idEstatus:
        db.session.add(HistorialCita(
            idCita=cita.idCita,
            idUsuario=session.get('idUsuario') or const.ID_USUARIO_SISTEMA,
            comentario=f'Cambio de estatus: {EstatusCita.nombre_estatus(estatus_anterior)} -> {nuevo_nombre}',
            idEstatusAnt=estatus_anterior,
            idEstatusNew=cita.idEstatus
        ))

    if reserva:
        for pregunta_data in data.get('preguntas', []):
            id_pregunta = pregunta_data.get('idPregunta')
            if not id_pregunta:
                continue
            pregunta = PreguntaServicio.query.filter_by(
                idPregunta=id_pregunta,
                idEmpresa=id_empresa,
                idProducto=cita.idProducto
            ).first()
            if not pregunta:
                continue
            respuesta = CitaPregunta.query.filter_by(
                idCitaCliente=reserva.idCitaCliente,
                idPregunta=id_pregunta
            ).first()
            if respuesta:
                respuesta.respuesta = str(pregunta_data.get('valor', '')).strip() or None
            elif str(pregunta_data.get('valor', '')).strip():
                db.session.add(CitaPregunta(
                    idCitaCliente=reserva.idCitaCliente,
                    idPregunta=id_pregunta,
                    respuesta=str(pregunta_data.get('valor', '')).strip()
                ))

    db.session.commit()
    for reserva_cambiada in reservas_estatus_cambiadas:
        notificar_cambio_estatus(cita, nuevo_nombre, reserva_cambiada)
    return jsonify({'success': True})
    

def cerrar_citas_vencidas(dias_atras=None):
    """
    Tarea programada (correr cada 15-30 min, con app context, junto a los demás crons de avisos.py).

    Revisa las citas que ya pasaron de horario y siguen en Creada / Disponible / Completa:
      - Sin ningún cliente activo (Reservada/Confirmada/Realizada) -> pasan a "Vencida".
      - Con clientes en Reservada/Confirmada NO se tocan: quedan "pendientes de cerrar" y el
        staff las marca Realizada / No Asistencia (la pantalla de gestión lo avisa).
    Usa Cita.recalcular_estatus_cita(), que ya aplica esa regla. Devuelve cuántas se vencieron.

    dias_atras: si se indica, solo revisa citas de los últimos N días (lo normal para el cron).
                None = revisa todo el histórico (útil para una limpieza única de citas viejas).
    """
    id_vencida = EstatusCita.id_estatus('Vencida')
    ids_candidatos = [i for i in (EstatusCita.id_estatus('Creada'),
                                  EstatusCita.id_estatus('Disponible'),
                                  EstatusCita.id_estatus('Completa')) if i]
    if not id_vencida or not ids_candidatos:
        return 0

    ahora = datetime.now()
    consulta = Cita.query.filter(
        Cita.idEstatus.in_(ids_candidatos),
        Cita.fechaCita <= ahora.date(),
        Cita.idCitaMaestra.is_(None)
    )
    if dias_atras is not None:
        consulta = consulta.filter(Cita.fechaCita >= ahora.date() - timedelta(days=int(dias_atras)))
    candidatas = consulta.all()

    vencidas = 0
    try:
        for cita in candidatas:
            if not cita.ya_paso:
                continue
            estatus_anterior = cita.idEstatus
            cita.recalcular_estatus_cita()
            if cita.idEstatus == id_vencida and estatus_anterior != id_vencida:
                db.session.add(HistorialCita(
                    idCita=cita.idCita,
                    idUsuario=const.ID_USUARIO_SISTEMA,
                    comentario='Cita vencida: pasó el horario sin clientes activos',
                    idEstatusAnt=estatus_anterior,
                    idEstatusNew=id_vencida
                ))
                vencidas += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Error en cerrar_citas_vencidas')
        return 0
    return vencidas


def _cambiar_cliente_reserva(cita, reserva, id_cliente_nuevo, id_empresa):
    """
    Cambia el cliente titular de una reserva (CitaCliente.idCliente).
    Devuelve None si se hizo el cambio, o un texto con el motivo si no se puede.

    Reglas:
      - El cliente nuevo debe pertenecer a la empresa.
      - Si la reserva ya tiene pagos aplicados (al cargo o a sus productos) NO se cambia:
        el dinero ya quedó a nombre del cliente original.
      - Si solo hay cargo sin pagos, el cargo (movCuenta MOV_CITA) pasa al cliente nuevo.
      - No Asistencia no se cambia: la falta ya se le contó al cliente original.
    """
    if reserva.idEstatus == const.NO_ASISTENCIA:
        return ('Esta reserva está en No Asistencia y la falta ya se le contó al cliente actual. '
                'Cambia primero el estatus y después el cliente.')

    nuevo = Cliente.query.get(id_cliente_nuevo)
    pertenece = ClienteEmpresa.query.filter_by(idCliente=id_cliente_nuevo, idEmpresa=id_empresa).first() if nuevo else None
    if not nuevo or not pertenece:
        return 'El cliente elegido no pertenece a esta empresa.'

    cargos = movCuenta.query.filter_by(
        idEmpresa=id_empresa,
        idtipoMovimiento=const.MOV_CITA,
        idMovReferencia=reserva.idCitaCliente
    ).all()
    producto_pagado = CitaProducto.query.filter(
        CitaProducto.idCitaCliente == reserva.idCitaCliente,
        CitaProducto.montoPagado > 0
    ).first()
    if producto_pagado or any(cargo.aplicaciones_recibidas for cargo in cargos):
        return ('Esta reserva ya tiene pagos aplicados a nombre del cliente actual, '
                'por eso no se puede cambiar el cliente.')

    nombre_anterior = reserva.cliente.nombreCliente if reserva.cliente else f'#{reserva.idCliente}'
    for cargo in cargos:
        cargo.idCliente = nuevo.idCliente
    reserva.idCliente = nuevo.idCliente
    reserva.cliente = nuevo
    db.session.add(HistorialCita(
        idCita=cita.idCita,
        idCitaCliente=reserva.idCitaCliente,
        idUsuario=session.get('idUsuario') or const.ID_USUARIO_SISTEMA,
        idCliente=nuevo.idCliente,
        comentario=f'Cambio de cliente: {nombre_anterior} -> {nuevo.nombreCliente}',
        idEstatusAnt=reserva.idEstatus,
        idEstatusNew=reserva.idEstatus
    ))
    return None


@ver_citas_bp.route('/admin/guardar_datos_reserva', methods=['POST'])
def guardar_datos_reserva():
    """
    Guarda, por cada reserva (asistente) de una cita:
      - 'para': nombre de quien asiste cuando NO es el cliente titular de la reserva
                (vacío o igual al nombre del cliente = es para el mismo cliente).
      - 'idCliente': (opcional) nuevo cliente titular de la reserva; ver _cambiar_cliente_reserva.
      - 'preguntas': respuestas a las preguntas de los servicios de ESA reserva
                (servicio fijo de la cita grupal + servicios agregados en CitaProducto).

    Body JSON:
      { "idCita": 123,
        "reservas": [ { "idCitaCliente": 45, "para": "Ana", "preguntas": [ {"idPregunta": 7, "valor": "..."} ] } ] }
    Cada clave es opcional por reserva: si no viene 'para' no se toca; si no vienen 'preguntas' no se tocan.
    """
    data = request.get_json(silent=True) or {}
    try:
        id_cita = int(data.get('idCita'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Cita inválida.'}), 400

    id_empresa = session.get('idEmpresa')
    cita = Cita.query.filter_by(idCita=id_cita, idEmpresa=id_empresa).first()
    if not cita:
        return jsonify({'success': False, 'message': 'Cita no encontrada'}), 404
    if session.get('tipoUsuario') == 'staff' and cita.idUsuario != session.get('idUsuario'):
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    try:
        for item in (data.get('reservas') or []):
            try:
                id_cita_cliente = int(item.get('idCitaCliente'))
            except (TypeError, ValueError):
                db.session.rollback()
                return jsonify({'success': False, 'message': 'Reserva inválida.'}), 400

            reserva = CitaCliente.query.filter_by(idCitaCliente=id_cita_cliente, idCita=id_cita).first()
            if not reserva:
                db.session.rollback()
                return jsonify({'success': False, 'message': 'La reserva no pertenece a esta cita.'}), 404

            # ---- Cambio de cliente de la reserva (antes del "para", que se compara contra el cliente) ----
            id_cliente_nuevo = item.get('idCliente')
            if id_cliente_nuevo not in (None, '', 0):
                try:
                    id_cliente_nuevo = int(id_cliente_nuevo)
                except (TypeError, ValueError):
                    db.session.rollback()
                    return jsonify({'success': False, 'message': 'Cliente inválido.'}), 400
                if id_cliente_nuevo != reserva.idCliente:
                    motivo = _cambiar_cliente_reserva(cita, reserva, id_cliente_nuevo, id_empresa)
                    if motivo:
                        db.session.rollback()
                        return jsonify({'success': False, 'message': motivo}), 409

            # ---- "Para" ----
            if 'para' in item:
                para = str(item.get('para') or '').strip()
                if len(para) > 45:
                    db.session.rollback()
                    return jsonify({'success': False, 'message': 'El nombre de "para" no puede pasar de 45 caracteres.'}), 400
                nombre_cliente = (reserva.cliente.nombreCliente or '').strip() if reserva.cliente else ''
                if para.lower() == nombre_cliente.lower():
                    para = ''
                para_nuevo = para or None
                para_anterior = (reserva.para or '').strip() or None
                if para_nuevo != para_anterior:
                    reserva.para = para_nuevo
                    db.session.add(HistorialCita(
                        idCita=cita.idCita,
                        idCitaCliente=reserva.idCitaCliente,
                        idUsuario=session.get('idUsuario') or const.ID_USUARIO_SISTEMA,
                        idCliente=reserva.idCliente,
                        comentario=f'Cambio de asistente: {para_anterior or "mismo cliente"} -> {para_nuevo or "mismo cliente"}',
                        idEstatusAnt=reserva.idEstatus,
                        idEstatusNew=reserva.idEstatus
                    ))

            # ---- Preguntas de los servicios de esta reserva ----
            if 'preguntas' in item:
                ids_productos = {cp.idProducto for cp in reserva.cita_productos}
                if cita.idProducto:
                    ids_productos.add(cita.idProducto)
                for pregunta_data in (item.get('preguntas') or []):
                    id_pregunta = pregunta_data.get('idPregunta')
                    if not id_pregunta:
                        continue
                    pregunta = PreguntaServicio.query.filter_by(
                        idPregunta=id_pregunta,
                        idEmpresa=id_empresa
                    ).first()
                    # Solo se aceptan preguntas de servicios que realmente tiene esta reserva
                    if not pregunta or pregunta.idProducto not in ids_productos:
                        continue
                    valor = str(pregunta_data.get('valor', '') or '').strip()
                    respuesta = CitaPregunta.query.filter_by(
                        idCitaCliente=reserva.idCitaCliente,
                        idPregunta=pregunta.idPregunta
                    ).first()
                    if respuesta:
                        respuesta.respuesta = valor or None
                    elif valor:
                        db.session.add(CitaPregunta(
                            idCitaCliente=reserva.idCitaCliente,
                            idPregunta=pregunta.idPregunta,
                            respuesta=valor
                        ))

        db.session.commit()
        return jsonify({'success': True})
    except Exception:
        db.session.rollback()
        logger.exception('Error en guardar_datos_reserva (cita %s)', id_cita)
        return jsonify({'success': False, 'message': 'No se pudieron guardar los datos de las reservas.'}), 500


@ver_citas_bp.route("/admin/citas_dia")
def api_citas_dia():
    if not login_sistema_required():
        return jsonify({"error": "No autorizado"}), 401

    fecha_s = request.args.get("date")
    id_empresa = session.get("idEmpresa")
    tipo_sesion = session.get('tipoUsuario')
    id_usuario_sesion = session.get('idUsuario')

    if not fecha_s:
        return jsonify({"error": "date requerido"}), 400

    try:
        fecha = datetime.fromisoformat(fecha_s.split('T')[0]).date()
    except Exception:
        return jsonify({"error": "formato de fecha inválido"}), 400

    query = Cita.query.options(
        joinedload(Cita.reservas).joinedload(CitaCliente.cliente),
        joinedload(Cita.producto),
        joinedload(Cita.estatus)
    ).filter(
        Cita.idEmpresa == id_empresa,
        Cita.fechaCita == fecha
    )

    if tipo_sesion == 'staff':
        query = query.filter(Cita.idUsuario == id_usuario_sesion)

    citas = query.order_by(Cita.horaCita).all()

    resultado = []
    for c in citas:
        reservas_activas = [reserva for reserva in c.reservas if reserva.ocupa_lugar]
        nombres_clientes = list(dict.fromkeys(
            reserva.cliente.nombreCliente
            for reserva in reservas_activas
            if reserva.cliente and reserva.cliente.nombreCliente
        ))
        color_hex = ColorEstatusCitaEmpresa.color_cita_estatus(id_empresa, c.idEstatus)
        resultado.append({
            "idCita": c.idCita,
            "hora": c.horaCita.strftime("%H:%M"),
            "estatus": c.idEstatus,
            "nombreEstatus": c.estatus.nombre if c.estatus else "N/A",
            "color": color_hex,
            "idCliente": reservas_activas[0].idCliente if reservas_activas else None,
            "nombreCliente": ', '.join(nombres_clientes) or (c.producto.nombre if c.producto else None),
            "nombreUsuario": c.usuario.nombreUsuario if c.usuario else "Sin asignar", # <--- Agregado aquí
            "notas": c.notas or "",
            "notasStaff": c.notasStaff or "",
            "duracion": c.duracion
        })

    return jsonify(resultado)

@ver_citas_bp.route('/admin/gestionar_productos_cita/<int:idCita>')
def gestionar_productos_cita(idCita):
    cita = Cita.query.get_or_404(idCita)
    id_cita_cliente = request.args.get('idCitaCliente', type=int)
    id_cliente = request.args.get('idCliente', type=int)

    reservas_query = CitaCliente.query.filter_by(idCita=idCita)
    if id_cita_cliente:
        reservas_query = reservas_query.filter_by(idCitaCliente=id_cita_cliente)
    elif id_cliente:
        reservas_query = reservas_query.filter_by(idCliente=id_cliente)
    reserva = reservas_query.order_by(CitaCliente.idCitaCliente.asc()).first()
    if not reserva:
        return "La cita no tiene una reserva de cliente que se pueda gestionar.", 404
    if session.get('tipoUsuario') == 'staff' and cita.idUsuario != session.get('idUsuario'):
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    cliente = reserva.cliente
    productos_asignados = db.session.query(CitaProducto).join(
        Producto
    ).filter(CitaProducto.idCitaCliente == reserva.idCitaCliente).all()

    cargo_cita = movCuenta.query.filter_by(
        idMovReferencia=reserva.idCitaCliente,
        idtipoMovimiento=const.MOV_CITA
    ).first()
    monto_cargo_previo = 0.0
    monto_pagado_previo = 0.0
    monto_cobro_inicial = 0.0
    if cargo_cita:
        sincronizar_pagado_productos_cita(cargo_cita)
        db.session.commit()
        monto_cargo_previo = float(cargo_cita.monto or 0)
        monto_pagado_previo = float(sum(
            (Decimal(str(aplicacion.montoAplicado or 0))
             for aplicacion in cargo_cita.aplicaciones_recibidas),
            Decimal('0.00')
        ))
    total_productos = sum(
        (Decimal(str(producto.cantidad or 0)) * Decimal(str(producto.precioCobrado or 0))
         for producto in productos_asignados),
        Decimal('0.00')
    )
    monto_cargo_variable_previo = max(
        Decimal(str(monto_cargo_previo)) - total_productos,
        Decimal('0.00')
    )
    producto_variable_previo = next((
        producto for producto in productos_asignados
        if Decimal(str(producto.precioCobrado or 0)) <= 0
    ), None)
    monto_pagado_variable_previo = (
        Decimal(str(producto_variable_previo.montoPagado or 0))
        if producto_variable_previo
        else min(Decimal(str(monto_pagado_previo)), monto_cargo_variable_previo)
    )
    if total_productos > 0:
        monto_cobro_inicial = monto_cargo_variable_previo + sum(
            (max(
                Decimal(str(producto.cantidad or 0)) * Decimal(str(producto.precioCobrado or 0))
                - Decimal(str(producto.montoPagado or 0)),
                Decimal('0.00')
            ) for producto in productos_asignados),
            Decimal('0.00')
        )
    else:
        monto_cobro_inicial = monto_cargo_variable_previo
    monto_cobro_inicial = max(monto_cobro_inicial - monto_pagado_variable_previo, Decimal('0.00'))
    
    # IMPORTANTE: Convertir precios de Decimal a Float para evitar error de sintaxis en JS
    for pa in productos_asignados:
        pa.precioCobrado = float(pa.precioCobrado) if pa.precioCobrado else 0.0
        pa.montoPagado = float(pa.montoPagado) if pa.montoPagado else 0.0
        
    productos_catalogo = db.session.query(Producto).join(
        ProductoUsuario, Producto.idProducto == ProductoUsuario.idProducto
    ).filter(
        ProductoUsuario.idUsuario == cita.idUsuario, # El staff de la cita
        Producto.idEmpresa == session.get('idEmpresa'),
        Producto.activo == True
    ).all()

    for p in productos_catalogo:
        p.costo = float(p.costo) if p.costo else 0.0
        
    notas_url = request.args.get('notas')
    notasStaff_url = request.args.get('notasStaff')
    notas_finales = notas_url if notas_url else reserva.notas or cita.notas
    notas_finales_staff = notasStaff_url if notasStaff_url else reserva.notasStaff or cita.notasStaff
    modo = request.args.get('modo', 'gestionar')
    if reserva.idEstatus == const.CANCELADA:
        modo = 'ver'  # una reserva cancelada no se gestiona ni se cobra
    readonly = modo == 'ver'

    metodos_pago_query = metodoPago.query.filter_by(activo=True)
    if const.PAGO_EN_LINEA:
        metodos_pago_query = metodos_pago_query.filter(metodoPago.idmetodoPago != const.PAGO_EN_LINEA)
    metodos_pago = metodos_pago_query.order_by(metodoPago.nombre).all()

    return render_template('gestionar_productos_cita.html', 
                           cita=cita, 
                           reserva=reserva,
                           cliente=cliente, 
                           productos_asignados=productos_asignados,
                           productos_catalogo=productos_catalogo, # Enviamos la lista de productos
                           notas_previa=notas_finales,
                           modo=modo,
                           readonly=readonly,
                           metodos_pago=metodos_pago,
                           monto_cargo_previo=monto_cargo_previo,
                           monto_pagado_previo=monto_pagado_previo,
                           monto_cargo_variable_previo=float(monto_cargo_variable_previo),
                           monto_cobro_inicial=float(monto_cobro_inicial))


@ver_citas_bp.route('/admin/guardar_productos_cita', methods=['POST'])
def guardar_productos_cita():
    if not login_sistema_required():
        return jsonify({'success': False, 'message': 'No autorizado'}), 401

    data = request.get_json(silent=True) or {}
    productos_recibidos = data.get('productos', [])
    id_cita = data.get('idCita')
    id_cita_cliente = data.get('idCitaCliente')
    try:
        id_cita = int(id_cita)
        id_cita_cliente = int(id_cita_cliente)
        ids_nuevos = [int(producto['id']) for producto in productos_recibidos]
    except (TypeError, ValueError, KeyError):
        return jsonify({'success': False, 'message': 'Cita, reserva o productos inválidos.'}), 400

    if len(ids_nuevos) != len(set(ids_nuevos)):
        return jsonify({'success': False, 'message': 'No se permiten productos duplicados en el detalle.'}), 400

    reserva = CitaCliente.query.join(Cita).filter(
        CitaCliente.idCitaCliente == id_cita_cliente,
        CitaCliente.idCita == id_cita,
        Cita.idEmpresa == session.get('idEmpresa')
    ).with_for_update().first()
    if not reserva:
        return jsonify({'success': False, 'message': 'La reserva no pertenece a esta cita.'}), 404
    cita = reserva.cita
    if session.get('tipoUsuario') == 'staff' and cita.idUsuario != session.get('idUsuario'):
        return jsonify({'success': False, 'message': 'No autorizado'}), 403
    if reserva.idEstatus == const.CANCELADA:
        return jsonify({'success': False, 'message': 'La reserva está cancelada; no se pueden modificar sus productos.'}), 409

    productos_actuales = CitaProducto.query.filter_by(idCitaCliente=id_cita_cliente).all()
    productos_actuales_por_id = {producto.idProducto: producto for producto in productos_actuales}
    ids_actuales = set(productos_actuales_por_id)
    ids_eliminados = ids_actuales - set(ids_nuevos)
    total_productos_actuales = sum(
        (Decimal(str(producto.cantidad or 0)) * Decimal(str(producto.precioCobrado or 0))
         for producto in productos_actuales),
        Decimal('0.00')
    )
    cargo_existente = movCuenta.query.filter_by(
        idMovReferencia=id_cita_cliente,
        idtipoMovimiento=const.MOV_CITA
    ).first()
    total_aplicado_existente = sum(
        (Decimal(str(aplicacion.montoAplicado or 0)
         ) for aplicacion in cargo_existente.aplicaciones_recibidas),
        Decimal('0.00')
    ) if cargo_existente else Decimal('0.00')
    cargo_variable_previo = max(
        Decimal(str(cargo_existente.monto or 0)) - total_productos_actuales,
        Decimal('0.00')
    ) if cargo_existente else Decimal('0.00')
    if ids_eliminados and total_productos_actuales <= 0 and total_aplicado_existente > 0:
        return jsonify({
            'success': False,
            'message': 'No se pueden quitar productos porque el cargo variable de la cita ya tiene pagos registrados.'
        }), 400

    if cita.idProducto and cita.idProducto not in ids_nuevos:
        return jsonify({'success': False, 'message': 'El servicio asignado a la cita no se puede quitar.'}), 400

    for producto_actual in productos_actuales:
        monto_pagado = Decimal(str(producto_actual.montoPagado or 0))
        producto_nuevo = next((p for p in productos_recibidos if int(p['id']) == producto_actual.idProducto), None)
        if monto_pagado > 0 and not producto_nuevo:
            return jsonify({'success': False, 'message': f'No se puede eliminar {producto_actual.producto.nombre}: ya tiene pagos registrados.'}), 400
        if producto_nuevo:
            cantidad_nueva = Decimal(str(producto_nuevo.get('cantidad', 0) or 0))
            precio_actual = Decimal(str(producto_actual.precioCobrado or 0))
            if cantidad_nueva * precio_actual < monto_pagado:
                return jsonify({'success': False, 'message': 'No se puede reducir el producto por debajo de lo ya pagado.'}), 400

    productos_validos = Producto.query.filter(
        Producto.idProducto.in_(ids_nuevos),
        Producto.idEmpresa == cita.idEmpresa,
        Producto.activo.is_(True)
    ).all()
    productos_por_id = {producto.idProducto: producto for producto in productos_validos}
    if set(ids_nuevos) - set(productos_por_id):
        return jsonify({'success': False, 'message': 'Uno o más productos no están activos en esta empresa.'}), 400

    if ids_eliminados:
        ids_preguntas = db.session.query(PreguntaServicio.idPregunta).filter(
            PreguntaServicio.idProducto.in_(ids_eliminados)
        ).all()
        ids_preguntas = [fila.idPregunta for fila in ids_preguntas]
        if ids_preguntas:
            CitaPregunta.query.filter(
                CitaPregunta.idCitaCliente == id_cita_cliente,
                CitaPregunta.idPregunta.in_(ids_preguntas)
            ).delete(synchronize_session=False)

    CitaProducto.query.filter_by(idCitaCliente=id_cita_cliente).delete(synchronize_session=False)
    total_cita = Decimal('0.00')
    for datos_producto in productos_recibidos:
        id_producto = int(datos_producto['id'])
        anterior = productos_actuales_por_id.get(id_producto)
        es_servicio_fijo = id_producto == cita.idProducto
        cantidad = 1 if es_servicio_fijo else int(datos_producto.get('cantidad', 1) or 1)
        producto = productos_por_id[id_producto]
        precio_catalogo = Decimal(str(producto.costo or 0))
        if precio_catalogo <= 0:
            precio_anterior = Decimal(str(anterior.precioCobrado or 0)) if anterior else Decimal('0.00')
            try:
                precio = Decimal(str(datos_producto.get('costo', precio_anterior) or 0))
            except (ArithmeticError, TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Ingresa un costo válido para el producto.'}), 400
            if not precio.is_finite() or precio < 0:
                return jsonify({'success': False, 'message': 'El costo del producto no puede ser negativo.'}), 400
            monto_pagado_anterior = Decimal(str(anterior.montoPagado or 0)) if anterior else Decimal('0.00')
            if anterior and monto_pagado_anterior > 0 and precio != precio_anterior:
                return jsonify({'success': False, 'message': 'No se puede cambiar el costo de un producto que ya tiene pagos registrados.'}), 400
        else:
            precio = Decimal(str(anterior.precioCobrado if anterior else precio_catalogo))
        monto_pagado = Decimal(str(anterior.montoPagado or 0)) if anterior else Decimal('0.00')
        if precio * cantidad < monto_pagado:
            return jsonify({'success': False, 'message': 'El costo no puede quedar por debajo de lo ya pagado.'}), 400
        total_cita += precio * cantidad
        db.session.add(CitaProducto(
            idCitaCliente=id_cita_cliente,
            idProducto=id_producto,
            cantidad=cantidad,
            precioCobrado=precio,
            montoPagado=monto_pagado,
            notas=data.get('notas', '')
        ))

    reserva.notas = data.get('notas', reserva.notas)
    reserva.notasStaff = data.get('notasStaff', reserva.notasStaff)
    cargo = movCuenta.query.filter_by(
        idMovReferencia=id_cita_cliente,
        idtipoMovimiento=const.MOV_CITA
    ).first()
    if total_cita <= 0:
        total_variable = cargo.monto if cargo and cargo.monto else reserva.costo
        total_cita = Decimal(str(total_variable or 0))
    elif cargo_variable_previo > 0:
        total_cita += cargo_variable_previo
    reserva.costo = total_cita
    if cargo:
        aplicado = sum(
            (Decimal(str(aplicacion.montoAplicado or 0)) for aplicacion in cargo.aplicaciones_recibidas),
            Decimal('0.00')
        )
        cargo.monto = total_cita
        cargo.saldoAnterior = cargo.saldo
        cargo.saldo = max(total_cita - aplicado, Decimal('0.00'))

    db.session.commit()
    return jsonify({
        'success': True,
        'message': 'Productos guardados exitosamente',
        'idEstatus': cita.idEstatus,
        'idCliente': reserva.idCliente,
        'idCita': cita.idCita,
        'idCitaCliente': reserva.idCitaCliente
    })

@ver_citas_bp.route('/admin/procesar_cobro_cita', methods=['POST'])
def procesar_cobro_cita():
    
    if not login_sistema_required():
        return jsonify({'success': False, 'message': 'No autorizado'}), 401

    id_empresa = session.get('idEmpresa')
    data = request.get_json(silent=True) or {}
    productos_recibidos = data.get('productos', [])
    pagos_recibidos = data.get('pagos', [])
    notas = data.get('notas', 'Cobro de productos/servicios en cita')
    try:
        id_cita = int(data.get('idCita'))
        id_cita_cliente = int(data.get('idCitaCliente'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Cita o reserva inválida.'}), 400

    reserva = CitaCliente.query.join(Cita).filter(
        CitaCliente.idCitaCliente == id_cita_cliente,
        CitaCliente.idCita == id_cita,
        Cita.idEmpresa == id_empresa
    ).with_for_update().first()
    if not reserva:
        return jsonify({'success': False, 'message': 'La reserva no pertenece a esta cita.'}), 404
    cita = reserva.cita
    if session.get('tipoUsuario') == 'staff' and cita.idUsuario != session.get('idUsuario'):
        return jsonify({'success': False, 'message': 'No autorizado'}), 403
    if reserva.idEstatus == const.CANCELADA:
        return jsonify({'success': False, 'message': 'La reserva está cancelada; no se puede cobrar.'}), 409

    try:
        productos_actuales = CitaProducto.query.filter_by(idCitaCliente=id_cita_cliente).all()
        productos_actuales_por_id = {producto.idProducto: producto for producto in productos_actuales}
        total_productos_actuales = sum(
            (Decimal(str(producto.precioCobrado or 0)) * Decimal(str(producto.cantidad or 0))
             for producto in productos_actuales),
            Decimal('0.00')
        )
        ids_nuevos = [int(producto['id']) for producto in productos_recibidos]
        if cita.idProducto and cita.idProducto not in ids_nuevos:
            return jsonify({'success': False, 'message': 'El servicio asignado a la cita no se puede quitar.'}), 400

        ids_nuevos = list(dict.fromkeys(ids_nuevos))
        productos_catalogo = Producto.query.filter(
            Producto.idProducto.in_(ids_nuevos),
            Producto.idEmpresa == id_empresa,
            Producto.activo.is_(True)
        ).all() if ids_nuevos else []
        productos_por_id = {producto.idProducto: producto for producto in productos_catalogo}
        if set(ids_nuevos) - set(productos_por_id):
            return jsonify({'success': False, 'message': 'Uno o más productos no están activos en esta empresa.'}), 400

        total_cita = Decimal('0.00')
        CitaProducto.query.filter_by(idCitaCliente=id_cita_cliente).delete(synchronize_session=False)
        for datos_producto in productos_recibidos:
            id_producto = int(datos_producto['id'])
            anterior = productos_actuales_por_id.get(id_producto)
            producto = productos_por_id[id_producto]
            cantidad = 1 if id_producto == cita.idProducto else int(datos_producto.get('cantidad', 1) or 1)
            precio = Decimal(str(anterior.precioCobrado if anterior else producto.costo or 0))
            monto_pagado = Decimal(str(anterior.montoPagado or 0)) if anterior else Decimal('0.00')
            if cantidad <= 0 or Decimal(cantidad) * precio < monto_pagado:
                return jsonify({'success': False, 'message': 'La cantidad no puede quedar por debajo de lo ya pagado.'}), 400
            total_cita += Decimal(cantidad) * precio
            db.session.add(CitaProducto(
                idCitaCliente=id_cita_cliente,
                idProducto=id_producto,
                cantidad=cantidad,
                precioCobrado=precio,
                montoPagado=monto_pagado,
                notas=notas
            ))

        cargo = movCuenta.query.filter_by(
            idMovReferencia=id_cita_cliente,
            idtipoMovimiento=const.MOV_CITA
        ).first()
        total_aplicado = sum(
            (Decimal(str(aplicacion.montoAplicado or 0)) for aplicacion in (cargo.aplicaciones_recibidas or [])),
            Decimal('0.00')
        ) if cargo else Decimal('0.00')
        cargo_variable_previo = max(
            Decimal(str(cargo.monto or 0)) - total_productos_actuales,
            Decimal('0.00')
        ) if cargo else Decimal('0.00')
        if total_cita <= 0:
            total_cita = (
                Decimal(str(cargo.monto or 0))
                if cargo and Decimal(str(cargo.monto or 0)) > 0
                else Decimal(str(data.get('montoTotal') or 0))
            )
        elif cargo_variable_previo > 0:
            total_cita += cargo_variable_previo
        reserva.costo = total_cita
        reserva.notas = notas or reserva.notas

        if not cargo:
            cargo = movCuenta(
                idEmpresa=id_empresa,
                idCliente=reserva.idCliente,
                idtipoMovimiento=const.MOV_CITA,
                idUsuario=session.get('idUsuario'),
                idMovReferencia=id_cita_cliente,
                monto=total_cita,
                saldoAnterior=total_cita,
                saldo=max(total_cita - total_aplicado, Decimal('0.00')),
                notas=notas,
                idmetodoPago=None,
                fecha=datetime.now().date(),
                hora=datetime.now().time()
            )
            db.session.add(cargo)
            db.session.flush()
        else:
            cargo.monto = total_cita
            cargo.saldoAnterior = cargo.saldo
            cargo.saldo = max(total_cita - total_aplicado, Decimal('0.00'))
            cargo.notas = notas

        if not pagos_recibidos and data.get('idmetodoPago'):
            pagos_recibidos = [{
                'idmetodoPago': int(data.get('idmetodoPago')),
                'monto': float(data.get('montoTotal') or total_cita)
            }]
        pagos_form = []
        for pago in pagos_recibidos:
            id_metodo = int(pago.get('idmetodoPago') or 0)
            monto_pago = Decimal(str(pago.get('monto') or 0))
            if id_metodo > 0 and monto_pago > 0:
                pagos_form.append({'idmetodoPago': id_metodo, 'monto': monto_pago})

        total_pago = sum((pago['monto'] for pago in pagos_form), Decimal('0.00'))
        saldo_cargo = Decimal(str(cargo.saldo or 0))
        if total_pago > saldo_cargo:
            return jsonify({'success': False, 'message': f'El pago excede el saldo pendiente de ${saldo_cargo:.2f}.'}), 400

        if pagos_form:
            procesar_pagos_con_puntos(
                id_cliente=reserva.idCliente,
                id_empresa=id_empresa,
                id_usuario=session.get('idUsuario') or const.ID_USUARIO_SISTEMA,
                pagos_form=pagos_form,
                cargos_seleccionados=[cargo],
                notas_final=notas,
            )

        db.session.commit()
        return jsonify({'success': True, 'message': 'Cobro procesado exitosamente'})
    except Exception as error:
        db.session.rollback()
        logger.exception('Error procesando cobro por reserva')
        return jsonify({'success': False, 'message': str(error)}), 500

def enviar_info_cita_whatsapp(cita, reserva):
    if not cita or not reserva or not reserva.cliente or not reserva.cliente.telefono:
        return False

    fecha_str    = cita.fechaCita.strftime('%d/%m/%Y') if cita.fechaCita else '---'
    hora_str     = cita.horaCita.strftime('%H:%M')     if cita.horaCita  else '---'
    staff_nombre = (cita.usuario.alias or cita.usuario.nombreUsuario) if cita.usuario else 'Sin asignar'

    lineas = [
        "*Informacion de tu cita*",
        "",
        f"Fecha: {fecha_str}",
        f"Hora: {hora_str}",
        f"Especialista: {staff_nombre}",
    ]
    
    lineas.append(f"Cliente: {reserva.cliente.nombreCliente}")
    if reserva.para and reserva.para.strip().lower() != (reserva.cliente.nombreCliente or '').strip().lower():
        lineas.append(f"Para: {reserva.para}")

    notas = reserva.notas or cita.notas
    if notas and notas.strip():
        lineas.append(f"Notas: {notas.strip()}")

    respuestas = CitaPregunta.query.filter_by(idCitaCliente=reserva.idCitaCliente).all()
    respuestas_con_valor = [r for r in respuestas if r.respuesta and str(r.respuesta).strip()]

    if respuestas_con_valor:
        bloques = {}  # { idProducto: { 'nombre': ..., 'preguntas': [ (pregunta, respuesta) ] } }
        for r in respuestas_con_valor:
            preg = PreguntaServicio.query.get(r.idPregunta)
            if preg and preg.producto:
                id_prod = preg.idProducto
                if id_prod not in bloques:
                    bloques[id_prod] = {
                        'nombre': preg.producto.nombre,
                        'preguntas': []
                    }
                bloques[id_prod]['preguntas'].append((preg.pregunta, r.respuesta))

        if bloques:
            lineas.append("")
            lineas.append("*Datos registrados:*")
            for bloque in bloques.values():
                lineas.append("")
                lineas.append(f"_{bloque['nombre']}_")
                for pregunta, respuesta in bloque['preguntas']:
                    lineas.append(f"- {pregunta}: {respuesta}")
    
    lineas.append(f"*Total de esta reserva: ${float(reserva.costo or 0):,.2f}*")
    mensaje = "\n".join(lineas)

    return enviar_whatsapp(
        numero=reserva.cliente.telefono,
        mensaje=mensaje,
        idEmpresaEnvia=cita.idEmpresa
    )


@ver_citas_bp.route('/admin/enviar_info_cita/<int:id_cita>', methods=['POST'])
def enviar_info_cita(id_cita):
    if not login_sistema_required():
        return jsonify({'success': False, 'message': 'No autorizado'}), 401

    cita = Cita.query.get_or_404(id_cita)
    if session.get('tipoUsuario') == 'staff' and cita.idUsuario != session.get('idUsuario'):
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    data = request.get_json(silent=True) or {}
    id_cita_cliente = data.get('idCitaCliente')
    try:
        id_cita_cliente = int(id_cita_cliente)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Selecciona una reserva válida.'}), 400

    reserva = CitaCliente.query.filter_by(
        idCitaCliente=id_cita_cliente,
        idCita=cita.idCita
    ).first()
    if not reserva:
        return jsonify({'success': False, 'message': 'La reserva no pertenece a esta cita.'}), 404
    if not reserva.cliente or not reserva.cliente.telefono:
        return jsonify({'success': False, 'message': 'El cliente de esta reserva no tiene teléfono registrado.'}), 400

    resultado = enviar_info_cita_whatsapp(cita, reserva)
    exito = bool(resultado[0] if isinstance(resultado, tuple) else resultado)
    if exito:
        return jsonify({'success': True, 'message': f'Información enviada a {reserva.nombre_asistente}.'})
    return jsonify({'success': False, 'message': 'No se pudo enviar el mensaje. Verifica la conexión de WhatsApp.'}), 502