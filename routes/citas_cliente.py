from venv           import logger
from flask          import Blueprint, request, render_template, redirect, url_for, session, current_app, jsonify
from datetime       import datetime, date as dt_date, timedelta
from modelos        import EstatusCita, db, Empresa, Cita, Usuario, HistorialCita, Producto, ProductoUsuario, CitaProducto, CitaCliente, movCuenta, Cliente, FilaEspera, ClienteEmpresa
from sqlalchemy.orm import joinedload, aliased
from whatsapp       import enviar_whatsapp
from constantes     import const
from itsdangerous   import URLSafeSerializer
from sqlalchemy     import or_, not_, func, cast, String, and_, select

import config

citas_cliente_bp = Blueprint("citas_cliente", __name__)

# ==========================================
# MIDDLEWARE DE SEGURIDAD
# ==========================================
def validar_acceso():
    id_c = session.get("idCliente")
    id_e = session.get("idEmpresa")
    if not id_c or not id_e:
        return False
    return True

def registrar_historial(id_cita, comentario, id_ant, id_new, id_cita_cliente=None):
    try:
        nuevo_h = HistorialCita(
            idCita=id_cita,
            idCitaCliente=id_cita_cliente,
            idUsuario=session.get("idUsuario") or const.ID_USUARIO_SISTEMA,
            idCliente=session.get("idCliente") if session.get("idCliente") else None,
            fechaMovimiento=datetime.now(),
            comentario=comentario,
            idEstatusAnt=id_ant,
            idEstatusNew=id_new
        )
        db.session.add(nuevo_h)
    except Exception as e:
        logger.info(f"Error en bitácora: {e}")


def _crear_o_recuperar_reserva(cita, id_cliente, para=None, id_estatus=None, costo=0.00):
    reserva = CitaCliente.query.filter_by(idCita=cita.idCita, idCliente=id_cliente).order_by(CitaCliente.idCitaCliente.asc()).first()
    if reserva is None:
        reserva = CitaCliente(
            idCita=cita.idCita,
            idCliente=id_cliente,
            idEstatus=id_estatus or EstatusCita.id_estatus("Reservada") or 1,
            para=para,
            costo=costo,
            fechaSolicitud=datetime.now(),
            notas=(cita.notas if getattr(cita, 'notas', None) else None),
        )
        db.session.add(reserva)
        db.session.flush()
    else:
        reserva.para = para if para is not None else reserva.para
        reserva.costo = costo if costo is not None else reserva.costo
        if id_estatus is not None:
            reserva.idEstatus = id_estatus
        if reserva.fechaSolicitud is None:
            reserva.fechaSolicitud = datetime.now()
    cita.recalcular_estatus_cita()
    return reserva

def _encontrar_cadena_de_citas(cita_inicial, minutos_requeridos):
    """
    A partir de cita_inicial, intenta juntar los siguientes slots del mismo
    staff/día hasta cubrir minutos_requeridos (la duración del/los
    servicio(s) elegidos).

    Los slots adicionales deben estar libres (Disponible o Cancelada) y ser
    contiguos en el tiempo -sin huecos- respecto al anterior. Devuelve la
    lista de citas en orden (incluyendo cita_inicial) si se logró cubrir el
    tiempo necesario, o None si no hay suficiente disponibilidad consecutiva
    (en cuyo caso ese horario no se puede reservar con esos servicios).
    """
    id_disponible = EstatusCita.id_estatus("Disponible")
    libres = [id_disponible, const.CANCELADA]

    cadena = [cita_inicial]
    acumulado = cita_inicial.duracion or 0
    fin_actual = datetime.combine(cita_inicial.fechaCita, cita_inicial.horaCita) + timedelta(minutes=acumulado)

    if acumulado >= minutos_requeridos:
        return cadena

    siguientes = Cita.query.filter(
        Cita.idEmpresa == cita_inicial.idEmpresa,
        Cita.idUsuario == cita_inicial.idUsuario,
        Cita.fechaCita == cita_inicial.fechaCita,
        Cita.horaCita > cita_inicial.horaCita,
        Cita.idEstatus.in_(libres)
    ).order_by(Cita.horaCita).all()

    for sig in siguientes:
        inicio_sig = datetime.combine(sig.fechaCita, sig.horaCita)
        if inicio_sig != fin_actual:
            break  # hueco entre slots: ya no son consecutivas, se detiene la cadena

        cadena.append(sig)
        acumulado += (sig.duracion or 0)
        fin_actual = inicio_sig + timedelta(minutes=sig.duracion or 0)

        if acumulado >= minutos_requeridos:
            return cadena

    return None

# ==========================================
# RUTAS DE NAVEGACIÓN 
# ==========================================

@citas_cliente_bp.route("/cliente/menu_citas")
def menu_citas():
    if not validar_acceso(): return redirect(config.URL_BASE)

    id_empresa = session.get("idEmpresa")
    empresa = Empresa.query.get(id_empresa)
    
    staff = Usuario.query.filter_by(
        idEmpresa=id_empresa, 
        tipoUsuario='staff'
    ).order_by(Usuario.nombreUsuario).all()
    
    return render_template(
        "seleccionar_staff.html",
        empresa=empresa.razonSocial if empresa else "Empresa",
        staff=staff,
        nombreCliente=session.get("nombreCliente", "Cliente")
    )

@citas_cliente_bp.route("/cliente/calendario_staff")
def calendario_staff():
    # 1. Cachamos el parámetro 'slug' si es que viene en la URL (ej: /cliente/calendario_staff?slug=xyz123)
    #slug_cliente = request.args.get('c')
    #slug_empresa = request.args.get('e')
    #date_param = request.args.get('date')  # Formato esperado: YYYY-MM-DD
    
    #if slug_cliente:
    #    cliente_autenticado = Cliente.query.filter_by(slug=slug_cliente).first()
    #    
    #    if cliente_autenticado:
    #        session['idCliente'] = cliente_autenticado.idCliente
    #        session['nombreCliente'] = cliente_autenticado.nombreCliente
    #    else:
    #        return redirect(config.URL_BASE)

    #if slug_empresa:
    #    empresa_autenticada = Empresa.query.filter_by(slug=slug_empresa).first()
    #    
    #    if empresa_autenticada:
    #        session['idEmpresa'] = empresa_autenticada.idEmpresa
    #    else:
    #        return redirect(config.URL_BASE)

    if not validar_acceso():
      return redirect(config.URL_BASE)

    id_empresa = session.get("idEmpresa")
    id_staff = request.args.get("idStaff")
    
    if not id_staff:
        return redirect(url_for("citas_cliente.menu_citas"))

    empresa = Empresa.query.get(id_empresa)
    staff = Usuario.query.filter_by(idUsuario=id_staff, idEmpresa=id_empresa).first()

    if not empresa or not staff:
        return redirect(url_for("citas_cliente.menu_citas"))

    session["idUsuario"] = id_staff
    session["nombreUsuario"] = staff.nombreUsuario

    servicios = (Producto.query
        .join(ProductoUsuario, ProductoUsuario.idProducto == Producto.idProducto)
        .filter(
            ProductoUsuario.idUsuario == staff.idUsuario,
            Producto.idEmpresa == id_empresa,
            Producto.activo.is_(True),
            Producto.tipo == 'servicio'
        )
        .order_by(Producto.nombre)
        .all())
    id_producto_param = request.args.get("idProducto")
    try:
        id_producto_seleccionado = int(id_producto_param) if id_producto_param else None
    except ValueError:
        id_producto_seleccionado = None
    if id_producto_seleccionado is not None and not any(
        servicio.idProducto == id_producto_seleccionado for servicio in servicios
    ):
        id_producto_seleccionado = None

    return render_template(
        "calendario_staff.html",
        empresa=empresa.razonSocial,
        staff=staff.nombreUsuario,
        idUsuario=id_staff,
        servicios=servicios,
        idProductoSeleccionado=id_producto_seleccionado,
        nombreCliente=session.get("nombreCliente", "Cliente")
    )

@citas_cliente_bp.route("/cliente/disponibilidades_mes")
def disponibilidades_mes():
    """
    Retorna un JSON con las fechas que tienen citas disponibles para un staff/empresa
    Ej: { "2026-07-15": 3, "2026-07-16": 5 } significa 3 y 5 citas disponibles respectivamente
    """
    id_empresa = session.get("idEmpresa")
    id_usuario = request.args.get("idUsuario", type=int)
    mes = request.args.get("mes")  # Formato: 2026-07 (YYYY-MM)
    id_producto_param = request.args.get("idProducto")
    try:
        id_producto = int(id_producto_param) if id_producto_param else None
    except ValueError:
        return jsonify({"error": "Servicio inválido"}), 400
    
    if not id_empresa or not id_usuario or not mes:
        return jsonify({"error": "Parámetros inválidos"}), 400
    if id_producto is not None and not ProductoUsuario.query.join(
        Producto, Producto.idProducto == ProductoUsuario.idProducto
    ).filter(
        ProductoUsuario.idUsuario == id_usuario,
        ProductoUsuario.idProducto == id_producto,
        Producto.idEmpresa == id_empresa,
        Producto.activo.is_(True),
        Producto.tipo == 'servicio'
    ).first():
        return jsonify({"error": "El servicio no pertenece al especialista seleccionado"}), 400
    
    try:
        # Parsear mes (ej: 2026-07)
        anio, mes_num = mes.split("-")
        anio = int(anio)
        mes_num = int(mes_num)
        
        # Primer día del mes
        primer_dia = dt_date(anio, mes_num, 1)
        # Último día del mes
        if mes_num == 12:
            ultimo_dia = dt_date(anio + 1, 1, 1) - timedelta(days=1)
        else:
            ultimo_dia = dt_date(anio, mes_num + 1, 1) - timedelta(days=1)
        
        # Publicar espacios disponibles o cancelados, tengan o no servicio fijo.
        id_disponible = EstatusCita.id_estatus("Disponible")
        id_cancelada = EstatusCita.id_estatus("Cancelada")
        estados_publicables = [id for id in (id_disponible, id_cancelada) if id is not None]
        estatus_ocupan = [const.RESERVADA, const.CONFIRMADA, const.REALIZADA]
        estatus_ocupan = [id_est for id_est in estatus_ocupan if id_est is not None]
        ocupacion = db.session.query(func.count(CitaCliente.idCitaCliente)).filter(
            CitaCliente.idCita == Cita.idCita,
            CitaCliente.idEstatus.in_(estatus_ocupan)
        ).correlate(Cita).scalar_subquery()
        filtros_citas = [
            Cita.idEmpresa == id_empresa,
            Cita.idUsuario == id_usuario,
            Cita.idEstatus.in_(estados_publicables),
            ocupacion < Cita.cupoMaximo,
            Cita.fechaCita >= primer_dia,
            Cita.fechaCita <= ultimo_dia
        ]
        if id_producto is not None:
            filtros_citas.append(Cita.idProducto == id_producto)
        citas_disponibles = Cita.query.filter(*filtros_citas).all()
        
        # Agrupar por fecha
        disponibilidades = {}
        for cita in citas_disponibles:
            fecha_str = cita.fechaCita.strftime('%Y-%m-%d')
            disponibilidades[fecha_str] = disponibilidades.get(fecha_str, 0) + 1
        
        return jsonify(disponibilidades)
    except Exception as e:
        logger.error(f"Error al obtener disponibilidades: {e}")
        return jsonify({"error": "Error al procesar disponibilidades"}), 500

@citas_cliente_bp.route("/cliente/mis_citas")
def mis_citas():
    if not validar_acceso(): return redirect(config.URL_BASE)
    
    id_cliente = session.get("idCliente")
    id_empresa = session.get("idEmpresa")
    
    ids_validos = [
        const.CONFIRMADA,
        const.CANCELADA,
        const.REALIZADA,
        const.RESERVADA,
        const.NO_ASISTENCIA
    ]
    ids_validos = [id_est for id_est in ids_validos if id_est is not None]

    reservas = CitaCliente.query.join(Cita).options(
        joinedload(CitaCliente.cita).joinedload(Cita.usuario),
        joinedload(CitaCliente.cita).joinedload(Cita.producto),
        joinedload(CitaCliente.cita_productos).joinedload(CitaProducto.producto),
        joinedload(CitaCliente.estatus)
    ).filter(
        CitaCliente.idCliente == id_cliente,
        Cita.idEmpresa == id_empresa,
        CitaCliente.idEstatus.in_(ids_validos)
    ).order_by(Cita.fechaCita.desc(), Cita.horaCita.desc()).all()

    for reserva in reservas:
        reserva.movimientos_cita = movCuenta.query.filter_by(
            idMovReferencia=reserva.idCitaCliente,
            idCliente=reserva.idCliente,
            idtipoMovimiento=const.MOV_CITA
        ).order_by(movCuenta.fecha.desc(), movCuenta.hora.desc()).all()
    
    #logger.info(f"Cliente {id_cliente} tiene {len(reservas)} citas para mostrar.")

    # Si la petición viene desde la app móvil, devolvemos JSON para evitar parsear HTML
    if request.args.get('app') == '1' or request.headers.get('Accept') == 'application/json':
        def _serialize_cita(c):
            servicios = []
            try:
                for cp in c.cita_productos:
                    servicios.append({
                        'cantidad': cp.cantidad,
                        'nombre': cp.producto.nombre if cp.producto else None,
                        'precio': float(cp.precioCobrado or 0)
                    })
            except Exception:
                servicios = []

            return {
                'id': c.cita.idCita,
                'fecha': c.cita.fechaCita.strftime('%d/%m/%Y') if c.cita.fechaCita else '',
                'hora': c.cita.horaCita.strftime('%I:%M %p') if c.cita.horaCita else '',
                'staff': c.cita.usuario.nombreUsuario if c.cita.usuario else None,
                'para': c.para,
                'servicios': servicios,
                'estado': c.estatus.nombre if c.estatus else '',
                'estado_id': c.idEstatus,
                'costo': float(c.costo or 0)
            }

        try:
            return jsonify([_serialize_cita(reserva) for reserva in reservas])
        except Exception as e:
            logger.exception(f"Error serializando citas para app: {e}")
            return jsonify({'success': False, 'msg': 'Error interno al serializar citas'}), 500

    return render_template("mis_citas.html", citas=reservas)

@citas_cliente_bp.route("/cliente/citas_disponibles")
def citas_disponibles():
    if not validar_acceso(): return redirect(config.URL_BASE)

    id_empresa = session.get("idEmpresa")
    id_usuario = session.get("idUsuario")
    fecha = request.args.get("fecha")
    id_producto_param = request.args.get("idProducto")
    try:
        id_producto = int(id_producto_param) if id_producto_param else None
    except ValueError:
        return redirect(url_for("citas_cliente.calendario_staff", idStaff=id_usuario))
    
    if not fecha or not id_usuario:
        return redirect(url_for("citas_cliente.menu_citas"))
    if id_producto is not None and not ProductoUsuario.query.join(
        Producto, Producto.idProducto == ProductoUsuario.idProducto
    ).filter(
        ProductoUsuario.idUsuario == id_usuario,
        ProductoUsuario.idProducto == id_producto,
        Producto.idEmpresa == id_empresa,
        Producto.activo.is_(True),
        Producto.tipo == 'servicio'
    ).first():
        return redirect(url_for("citas_cliente.calendario_staff", idStaff=id_usuario))

    id_disponible = EstatusCita.id_estatus("Disponible")
    id_cancelada = EstatusCita.id_estatus("Cancelada")
    estados_publicables = [id for id in (id_disponible, id_cancelada) if id is not None]
    
    estatus_ocupan = [const.RESERVADA, const.CONFIRMADA, const.REALIZADA]
    estatus_ocupan = [id_est for id_est in estatus_ocupan if id_est is not None]
    ocupacion = db.session.query(func.count(CitaCliente.idCitaCliente)).filter(
        CitaCliente.idCita == Cita.idCita,
        CitaCliente.idEstatus.in_(estatus_ocupan)
    ).correlate(Cita).scalar_subquery()
    filtros_citas = [
        Cita.fechaCita == fecha,
        Cita.idEmpresa == id_empresa,
        Cita.idUsuario == id_usuario,
        Cita.idEstatus.in_(estados_publicables),
        ocupacion < Cita.cupoMaximo
    ]
    if id_producto is not None:
        filtros_citas.append(Cita.idProducto == id_producto)
    citas = Cita.query.filter(*filtros_citas).order_by(Cita.horaCita).all()
    for cita in citas:
        cita.cupoOcupado = cita.asientos_ocupados()

    # Día de la semana en español (sin depender del idioma del servidor)
    dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    try:
        dia_semana = dias_semana[datetime.strptime(fecha, '%Y-%m-%d').weekday()]
    except ValueError:
        dia_semana = ''

    return render_template(
        "lista_citas_servicio.html",
        fecha=fecha,
        diaSemana=dia_semana,
        citas=citas,
        nombreUsuario=session.get("nombreUsuario"),
        idCliente=session.get("idCliente"),
        idProducto=id_producto
    )
    
    

# ==========================================
# ACCIONES DE RESERVA Y CAMBIO DE ESTATUS
# ==========================================

@citas_cliente_bp.route("/cliente/reservar_cita", methods=["POST"])
def reservar_cita():
    """
    Reserva en DOS pasos:
      1) Sin 'paso=confirmar'  -> muestra reservar_para.html (cuántos lugares y para quién).
      2) Con 'paso=confirmar'  -> valida y graba un CitaCliente por cada lugar.
    """
    if not validar_acceso(): return redirect(config.URL_BASE)

    id_cita = request.form.get('idCita', type=int)
    tipo = request.form.get('tipo', '')
    paso = request.form.get('paso', '')
    id_empresa = session.get('idEmpresa')
    id_cliente = session.get('idCliente')
    nombre_cliente = (session.get('nombreCliente') or '').strip()
    id_disponible = EstatusCita.id_estatus('Disponible')
    id_cancelada = EstatusCita.id_estatus('Cancelada')
    estados_reservables = [id for id in (id_disponible, id_cancelada) if id is not None]
    id_reservada = EstatusCita.id_estatus('Reservada')

    cita = Cita.query.filter_by(idCita=id_cita, idEmpresa=id_empresa).with_for_update().first()
    if not cita or cita.idEstatus not in estados_reservables:
        return "<script>alert('Esta cita ya no está disponible.'); window.location.href='/cliente/menu_citas';</script>"

    producto = Producto.query.filter_by(
        idProducto=cita.idProducto,
        idEmpresa=id_empresa,
        tipo='servicio'
    ).first() if cita.idProducto else None
    if cita.idProducto and not producto:
        return "<script>alert('El servicio de esta cita ya no está disponible.'); window.history.back();</script>"

    reserva_activa = CitaCliente.query.filter(
        CitaCliente.idCita == cita.idCita,
        CitaCliente.idCliente == id_cliente,
        CitaCliente.idEstatus.in_([const.RESERVADA, const.CONFIRMADA])
    ).first()
    if reserva_activa and not cita.es_grupal and int(cita.cupoMaximo or 1) <= 1:
        return redirect(url_for('citas_cliente.mis_citas'))

    ocupados = cita.asientos_ocupados()
    cita.cupoOcupado = ocupados
    cupo_maximo = max(int(cita.cupoMaximo or 1), 1)
    if ocupados >= cupo_maximo:
        cita.idEstatus = const.COMPLETA
        db.session.commit()
        return "<script>alert('El cupo de esta cita ya está completo.'); window.location.href='/cliente/menu_citas';</script>"
    lugares_disponibles = cupo_maximo - ocupados

    # ---------- PASO 1: preguntar lugares y "para" ----------
    if paso != 'confirmar':
        db.session.rollback()  # libera el with_for_update; aquí no se modifica nada
        return render_template(
            'reservar_para.html',
            cita=cita,
            producto=producto,
            lugaresDisponibles=lugares_disponibles,
            nombreCliente=nombre_cliente,
            tipo=tipo,
            maxPara=CitaCliente.__table__.c.para.type.length
        )

    # ---------- PASO 2: validar y grabar ----------
    cantidad = request.form.get('cantidad', default=1, type=int) or 1
    if cantidad < 1 or cantidad > lugares_disponibles:
        db.session.rollback()
        return (f"<script>alert('Solo hay {lugares_disponibles} lugar(es) disponible(s).'); "
                "window.history.back();</script>")

    # Un "para" por lugar. Vacío => nombre del cliente. El largo sale de la columna real.
    max_para = CitaCliente.__table__.c.para.type.length
    paras_form = request.form.getlist('para')
    paras = []
    for i in range(cantidad):
        valor = (paras_form[i] if i < len(paras_form) else '').strip()[:max_para]
        paras.append(valor or nombre_cliente)

    estatus_anterior = cita.idEstatus
    # Cita individual sin servicio fijo (idProducto NULL): costo inicial 0.
    costo_reserva = float(producto.costo or 0) if producto else 0.00

    reservas = []
    for para in paras:
        if cita.es_grupal or cantidad > 1:
            reserva = CitaCliente(
                idCita=cita.idCita,
                idCliente=id_cliente,
                idEstatus=id_reservada,
                para=para,
                costo=costo_reserva,
                fechaSolicitud=datetime.now(),
                notas=cita.notas
            )
            db.session.add(reserva)
            db.session.flush()
        else:
            reserva = _crear_o_recuperar_reserva(
                cita,
                id_cliente,
                para=para,
                id_estatus=id_reservada,
                costo=costo_reserva
            )
        reserva.fechaSolicitud = datetime.now()

        if producto:
            servicio_reserva = CitaProducto.query.filter_by(
                idCitaCliente=reserva.idCitaCliente,
                idProducto=producto.idProducto
            ).first()
            if not servicio_reserva:
                db.session.add(CitaProducto(
                    idCitaCliente=reserva.idCitaCliente,
                    idProducto=producto.idProducto,
                    cantidad=1,
                    precioCobrado=producto.costo
                ))

        registrar_historial(
            cita.idCita,
            f'Cliente reservó cita con servicio asignado (para: {para})',
            estatus_anterior,
            id_reservada,
            id_cita_cliente=reserva.idCitaCliente
        )
        reservas.append(reserva)

    cita.recalcular_estatus_cita()

    fila = FilaEspera.query.filter_by(
        idCliente=id_cliente,
        idEmpresa=cita.idEmpresa,
        idUsuario=cita.idUsuario,
        activo=True
    ).first()
    if fila:
        fila.fechaUltimoAviso = None
        fila.cantidadAvisos = 0

    db.session.commit()

    empresa_obj = Empresa.query.get(cita.idEmpresa)
    empresa_nombre = empresa_obj.razonSocial if empresa_obj else 'CitaNet'
    empresa_dir = empresa_obj.direccion if empresa_obj else 'Ver en sucursal'
    staff_nombre = cita.usuario.nombreUsuario if cita.usuario else 'Personal asignado'
    f_cita = cita.fechaCita.strftime('%d/%m/%Y')
    h_cita = cita.horaCita.strftime('%I:%M %p')
    total = sum(float(r.costo or 0) for r in reservas)
    # Un solo mensaje por cliente, con los nombres de todos los "para"
    lista_para = "\n".join(f"   • {p}" for p in paras)
    cuerpo_mensaje = (
        f"✅ *¡Cita Reservada!*\n\n"
        f"Hola *{nombre_cliente}*,\n"
        f"Hemos agendado tu cita en *{empresa_nombre}* con éxito:\n\n"
        f"📅 *Fecha:* {f_cita}\n"
        f"⏰ *Hora:* {h_cita}\n"
        f"👤 *Atiende:* {staff_nombre}\n"
        f"🛠 *Servicio:* {producto.nombre if producto else 'Por definir'}\n"
        f"🎟 *Lugares ({cantidad}) para:*\n{lista_para}\n"
        f"💰 *Total:* ${total:.2f}\n\n"
        f"📍 *Ubicación:* {empresa_dir}\n\n"
        '_Por favor, llega 10 minutos antes._\n¡Te esperamos!'
    )
    telefono_cliente = session.get('telefono')
    if telefono_cliente:
        enviar_whatsapp(telefono_cliente, cuerpo_mensaje, empresa_obj.idEmpresa if empresa_obj else 1)

    if tipo == 'reagendar':
        return redirect(url_for('citas_cliente.mis_citas'))
    return render_template('reserva_exitosa.html', empresa_nombre=empresa_nombre)


@citas_cliente_bp.route("/cliente/confirmar")
def confirmar_cita():
    if not validar_acceso(): return redirect(config.URL_BASE)
    id_cita = request.args.get("idCita")
    cita = Cita.query.get(id_cita)
    reserva = CitaCliente.query.filter_by(idCita=id_cita, idCliente=session.get("idCliente")).order_by(CitaCliente.idCitaCliente.asc()).first() if id_cita else None
    
    if cita and reserva and reserva.idCliente == session.get("idCliente"):
        ant = reserva.idEstatus

        filas = CitaCliente.query.filter(
            CitaCliente.idCita == id_cita,
            CitaCliente.idCliente == session.get("idCliente"),
            CitaCliente.idEstatus == const.RESERVADA
        ).update({"idEstatus": const.CONFIRMADA})

        if filas:
            registrar_historial(id_cita, "Cliente confirmó cita vía Web", ant, const.CONFIRMADA, id_cita_cliente=reserva.idCitaCliente)

        cita.recalcular_estatus_cita()
        db.session.commit()

        if filas:
            notificar_cambio_estatus(cita, "Confirmada", reserva)
            
    return redirect(url_for("citas_cliente.mis_citas"))

@citas_cliente_bp.route('/cliente/confirmar_app', methods=['GET'])
def confirmar_cita_app():
    id_cita = request.args.get('idCita')
    cita = Cita.query.get(id_cita)
    if not cita:
        return jsonify({"success": False, "msg": "Cita no encontrada"}), 404

    reserva = CitaCliente.query.filter_by(idCita=id_cita, idCliente=session.get("idCliente")).order_by(CitaCliente.idCitaCliente.asc()).first()
    if not reserva:
        return jsonify({"success": False, "msg": "No existe una reserva activa para este cliente."}), 404

    ant = reserva.idEstatus

    if ant == const.CONFIRMADA:
        return jsonify({"success": True, "status": "Confirmada"})

    filas = CitaCliente.query.filter(
        CitaCliente.idCita == id_cita,
        CitaCliente.idCliente == session.get("idCliente"),
        CitaCliente.idEstatus == const.RESERVADA
    ).update({"idEstatus": const.CONFIRMADA})

    if filas:
        registrar_historial(cita.idCita, "Confirmada desde App Móvil", ant, const.CONFIRMADA, id_cita_cliente=reserva.idCitaCliente)

    cita.recalcular_estatus_cita()
    db.session.commit()

    if filas:
        notificar_cambio_estatus(cita, "Confirmada", reserva)
        return jsonify({"success": True, "status": "Confirmada"})

    return jsonify({"success": False, "msg": "Esta cita ya no está disponible para confirmar."}), 409


@citas_cliente_bp.route("/cliente/cancelar", methods=['GET'])
def cancelar_cita():
    id_cita = request.args.get("idCita")
    origen = request.args.get("origen") # 'app' o None (web)
    
    if origen != "app" and not validar_acceso(): 
        return redirect(config.URL_BASE)
    
    cita = Cita.query.get(id_cita)
    if not cita:
        if origen == "app":
            return jsonify({"success": False, "message": "Cita no encontrada"}), 404
        return redirect(url_for("citas_cliente.mis_citas"))

    reserva = CitaCliente.query.filter_by(idCita=id_cita, idCliente=session.get("idCliente")).order_by(CitaCliente.idCitaCliente.asc()).first() if session.get("idCliente") else None
    if not reserva:
        return redirect(url_for("citas_cliente.mis_citas")) if origen != "app" else jsonify({"success": False, "message": "No existe una reserva activa para este cliente."}), 404
    
    ant = reserva.idEstatus
    reserva.idEstatus = const.CANCELADA
    cita.recalcular_estatus_cita()

    if not cita.idProducto:
        for hija in cita.citas_bloqueadas:
            hija.idEstatus = const.CANCELADA
            hija.idCitaMaestra = None
    
    motivo = "Cancelada desde App Móvil" if origen == "app" else "Cliente canceló cita vía Web"
    registrar_historial(cita.idCita, motivo, ant, const.CANCELADA, id_cita_cliente=reserva.idCitaCliente)
    db.session.commit()

    notificar_cambio_estatus(cita, "Cancelada", reserva)
    
    if origen == "app":
        return jsonify({"success": True, "status": "Cancelada"})
    
    return redirect(url_for("citas_cliente.mis_citas"))

@citas_cliente_bp.route('/cliente/reagendar')
def reagendar_cita():
    if not validar_acceso(): return redirect(config.URL_BASE)

    id_cita = request.args.get('idCita', type=int)
    cita = Cita.query.filter_by(idCita=id_cita, idEmpresa=session.get('idEmpresa')).first()
    reserva = CitaCliente.query.filter_by(
        idCita=id_cita,
        idCliente=session.get('idCliente')
    ).order_by(CitaCliente.idCitaCliente.asc()).first() if cita else None

    if not cita or not reserva or not reserva.ocupa_lugar:
        return redirect(url_for('citas_cliente.mis_citas'))

    estatus_anterior = reserva.idEstatus
    reserva.idEstatus = const.CANCELADA
    cita.recalcular_estatus_cita()
    registrar_historial(
        cita.idCita,
        'Cliente liberó su lugar para reagendar',
        estatus_anterior,
        const.CANCELADA,
        id_cita_cliente=reserva.idCitaCliente
    )
    db.session.commit()
    notificar_cambio_estatus(cita, 'Cancelada', reserva)
    session['reagendar_proceso'] = True
    return redirect(url_for('citas_cliente.calendario_staff', idStaff=cita.idUsuario))

@citas_cliente_bp.route('/cliente/reagendar_app') # Ruta nueva para la App
def reagendar_cita_app():
    if not validar_acceso(): 
        return jsonify({"success": False, "msg": "Sesión no válida"}), 401

    id_cita = request.args.get('idCita', type=int)
    cita = Cita.query.filter_by(idCita=id_cita, idEmpresa=session.get('idEmpresa')).first()
    reserva = CitaCliente.query.filter_by(
        idCita=id_cita,
        idCliente=session.get('idCliente')
    ).order_by(CitaCliente.idCitaCliente.asc()).first() if cita else None
    if not cita or not reserva or not reserva.ocupa_lugar:
        return jsonify({"success": False, "msg": "La reserva no existe o ya no está activa."}), 404

    estatus_anterior = reserva.idEstatus
    reserva.idEstatus = const.CANCELADA
    cita.recalcular_estatus_cita()
    registrar_historial(
        cita.idCita,
        'Cliente liberó su lugar para reagendar desde App',
        estatus_anterior,
        const.CANCELADA,
        id_cita_cliente=reserva.idCitaCliente
    )
    db.session.commit()
    notificar_cambio_estatus(cita, 'Cancelada', reserva)
    return jsonify({
        "success": True,
        "msg": "Lugar liberado; elige una nueva cita.",
        "idStaff": cita.idUsuario
    })

@citas_cliente_bp.route("/confirmacion-directa/<token>", methods=["GET", "POST"])
def confirmacion_directa(token):
    s = URLSafeSerializer(current_app.config["SECRET_KEY"])
    try:
        datos_token = s.loads(token)
        ids_reservas = [int(id) for id in datos_token['idCitaCliente']]
    except Exception:
        return "El enlace de confirmación es inválido o ha expirado.", 400

    if not ids_reservas:
        return "El enlace no contiene reservas válidas.", 400

    reservas = CitaCliente.query.filter(
        CitaCliente.idCitaCliente.in_(ids_reservas)
    ).order_by(CitaCliente.idCitaCliente).with_for_update().all()
    if len(reservas) != len(set(ids_reservas)):
        return "No se encontraron todas las reservas del enlace.", 404

    cita = reservas[0].cita
    if any(r.idCita != cita.idCita or r.idCliente != reservas[0].idCliente for r in reservas):
        return "El enlace no corresponde a una sola reserva de cliente.", 400

    id_confirmada = EstatusCita.id_estatus('Confirmada')
    id_reservada = EstatusCita.id_estatus('Reservada')
    if all(r.idEstatus == id_confirmada for r in reservas):
        return "Estas reservas ya fueron confirmadas."
    if any(r.idEstatus != id_reservada for r in reservas):
        return "Una o más reservas ya no están pendientes de confirmación.", 409

    if request.method == 'POST':
        for reserva in reservas:
            reserva.idEstatus = id_confirmada
            registrar_historial(
                cita.idCita,
                'Cliente confirmó cita vía enlace de recordatorio',
                id_reservada,
                id_confirmada,
                id_cita_cliente=reserva.idCitaCliente
            )
        cita.recalcular_estatus_cita()
        db.session.commit()
        for reserva in reservas:
            notificar_cambio_estatus(cita, 'Confirmada', reserva)
        return "¡Gracias! Tu reserva ha sido confirmada con éxito."

    return render_template('confirmar_asistencia.html', cita=cita, reservas=reservas)


def notificar_cambio_estatus(cita, nuevo_estatus_nombre, reserva=None):
    if reserva is None:
        reservas_activas = [r for r in cita.reservas if r.ocupa_lugar]
        if reservas_activas:
            for reserva_activa in reservas_activas:
                notificar_cambio_estatus(cita, nuevo_estatus_nombre, reserva_activa)
            return
        return

    cliente = reserva.cliente
    telefono_cliente = cliente.telefono if cliente else None

    f_cita = cita.fechaCita.strftime('%d/%m/%Y')
    h_cita = cita.horaCita.strftime('%I:%M %p')
    nombreCliente = reserva.nombre_asistente or (cliente.nombreCliente if cliente else "Cliente")
    empresa = cita.empresa if cita else None
    empresa_nombre = empresa.razonSocial if cita else "la sucursal"

    # Validación dinámica de la URL de Google Maps
    if empresa and empresa.googleMapsUrl:
        texto_ubicacion = f"\n\n📍 *Ubicación en Google Maps:*\n{empresa.googleMapsUrl}"
    else:
        texto_ubicacion = ""

    mensajes = {
        "Confirmada": (
            f"✅ *¡Cita Confirmada!*\n\n"
            f"Hola *{nombreCliente}*,\n"
            f"Tu cita para el día *{f_cita}* a las *{h_cita}* en *{empresa_nombre}* ha sido confirmada con éxito. ¡Te esperamos!{texto_ubicacion}"
        ),
        "Cancelada": (
            f"❌ *Cita Cancelada*\n\n"
            f"Hola *{nombreCliente}*,\n"
            f"Te informamos que tu cita programada para el *{f_cita}* a las *{h_cita}* ha sido cancelada."
        ),
        "Disponible": (  # Caso para cuando se libera al reagendar
            f"🔄 *Cita Liberada/Reagendada*\n\n"
            f"Hola *{nombreCliente}*,\n"
            f"Tu cita anterior del *{f_cita}* ha sido liberada. Recuerda completar tu nueva reserva."
        ),
        "Realizada": (  # Caso para cuando se realiza la cita
            f"✅ *Cita Realizada*\n\n"
            f"Hola *{nombreCliente}*,\n"
            f"Tu cita en *{empresa_nombre}* ha sido realizada con éxito. ¡Gracias por tu preferencia! Te esperamos en tu próxima visita."
        ),
        "Bloqueada": (
            f"🔒 *Cita bloqueada*\n\n"
            f"Hola *{nombreCliente}*,\n"
            f"Tu cita del *{f_cita}* a las *{h_cita}* en *{empresa_nombre}* fue cancelada. Por favor comunícate con el establecimiento para más información."
        ),
        "Reservada": (  # Caso para cuando se Reserva la cita pero no se ha confirmado
            f"✅ *Cita Reservada*\n\n"
            f"Hola *{nombreCliente}*,\n"
            f"Tu cita para el día *{f_cita}* a las *{h_cita}* en *{empresa_nombre}* ha sido reservada con éxito. ¡No olvides confirmarla antes de la fecha para no perderla!{texto_ubicacion}"
        ),
        "No Asistencia": (  # Caso para cuando el cliente no asistió a la cita
            f"⚠️ *No Asistencia Registrada*\n\n"
            f"Hola *{nombreCliente}*,\n"
            f"Tu cita en *{empresa_nombre}* el día *{f_cita}* a las *{h_cita}* se perdió por no haber asistido. Si deseas reagendar, por favor hazlo con anticipación para asegurar tu espacio. ¡Te esperamos en tu próxima visita!"
        )
    }

    mensajes_especialista = {
        "Confirmada": (
            f"✅ *Cita confirmada*\n\n"
            f"El cliente *{nombreCliente}* confirmó su cita para el *{f_cita}* a las *{h_cita}* en *{empresa_nombre}*."
        ),
        "Cancelada": (
            f"❌ *Cita cancelada*\n\n"
            f"El cliente *{nombreCliente}* canceló su cita del *{f_cita}* a las *{h_cita}* en *{empresa_nombre}*."
        ),
        "Disponible": (
            f"🔄 *Cita liberada*\n\n"
            f"La cita del cliente *{nombreCliente}* del *{f_cita}* a las *{h_cita}* quedó disponible para reagendar."
        ),
        "Realizada": (
            f"✅ *Cita realizada*\n\n"
            f"La cita del cliente *{nombreCliente}* del *{f_cita}* a las *{h_cita}* en *{empresa_nombre}* fue marcada como realizada."
        ),
        "Bloqueada": (
            f"🔒 *Cita bloqueada*\n\n"
            f"La cita del cliente *{nombreCliente}* del *{f_cita}* a las *{h_cita}* en *{empresa_nombre}* fue cancelada por bloqueo de cita principal."
        ),
        "Reservada": (
            f"📌 *Nueva reserva*\n\n"
            f"El cliente *{nombreCliente}* reservó una cita para el *{f_cita}* a las *{h_cita}* en *{empresa_nombre}*."
        ),
        "No Asistencia": (
            f"⚠️ *No asistencia registrada*\n\n"
            f"El cliente *{nombreCliente}* no asistió a la cita del *{f_cita}* a las *{h_cita}* en *{empresa_nombre}*."
        )
    }

    cuerpo = mensajes.get(nuevo_estatus_nombre)
    if cuerpo and telefono_cliente:
        enviar_whatsapp(telefono_cliente, cuerpo, cita.idEmpresa if cita else 1)

    especialista = cita.usuario if cita else None
    if especialista and especialista.telefono:
        cuerpo_especialista = mensajes_especialista.get(nuevo_estatus_nombre)
        if cuerpo_especialista:
            enviar_whatsapp(especialista.telefono, cuerpo_especialista, cita.idEmpresa if cita else 1)

    if nuevo_estatus_nombre == "Disponible":
        avisar_fila_espera(cita)
    

# ==========================================
# ACCESO DIRECTO POR TOKEN (para links de WhatsApp)
# ==========================================

@citas_cliente_bp.route("/cliente/acceso-directo/<token>")
def acceso_directo(token):
    """
    Ruta que autentica al cliente directamente desde un link de WhatsApp.
    El token contiene { idCliente, idEmpresa, idUsuario, fecha }.
    Redirige al calendario del staff posicionado en la fecha indicada.
    """
    s = URLSafeSerializer(current_app.config["SECRET_KEY"])
    try:
        datos = s.loads(token)
    except Exception:
        return "El enlace es inválido o ha expirado.", 400

    id_cliente = datos.get("idCliente")
    id_empresa = datos.get("idEmpresa")
    id_usuario = datos.get("idUsuario")
    fecha      = datos.get("fecha")  # YYYY-MM-DDra

    cliente = Cliente.query.get(id_cliente)
    empresa = Empresa.query.get(id_empresa)
    staff   = Usuario.query.get(id_usuario)

    if not cliente or not empresa or not staff:
        return "Enlace inválido.", 400

    # Establecer sesión del cliente
    session["idCliente"]     = cliente.idCliente
    session["nombreCliente"] = cliente.nombreCliente
    session["idEmpresa"]     = empresa.idEmpresa
    session["nombreEmpresa"] = empresa.razonSocial
    session["idUsuario"]     = staff.idUsuario
    session["nombreUsuario"] = staff.nombreUsuario
    session["tipoUsuario"]   = "cliente"

    # Si el aviso trae una fecha específica (ej. una cita cancelada puntual),
    # llevamos al cliente directo a los horarios de ese día. Si no hay fecha
    # (ej. avisos de reactivación, donde no se ofrece un horario puntual),
    # lo mandamos al calendario del especialista para que elija el día.
    if fecha:
        url = url_for("citas_cliente.citas_disponibles", fecha=fecha)
    else:
        url = url_for("citas_cliente.calendario_staff", idStaff=staff.idUsuario)
    return redirect(url)


# ==========================================
# FILA DE ESPERA
# ==========================================

def _generar_token_acceso(id_cliente, id_empresa, id_usuario, fecha=None):
    """Genera un token firmado para el link directo al calendario.
    'fecha' es opcional: si no se manda (o se manda vacía), acceso_directo()
    lleva al cliente al calendario del especialista para que elija el día
    él mismo, en vez de a un día fijo."""
    s = URLSafeSerializer(current_app.config["SECRET_KEY"])
    return s.dumps({
        "idCliente": id_cliente,
        "idEmpresa": id_empresa,
        "idUsuario": id_usuario,
        "fecha":     fecha,
    })


def avisar_fila_espera(cita):
    id_empresa = cita.idEmpresa
    id_usuario = cita.idUsuario # El terapeuta
    fecha_cita = cita.fechaCita # Tipo date o string (ej. 2026-06-10)
    hora_cita  = cita.horaCita  # Tipo time (ej. 16:00:00)
    
    dia_semana_cita = str(fecha_cita.isoweekday()) 
    
    candidatos = FilaEspera.query.filter_by(
        idEmpresa=id_empresa,
        idUsuario=id_usuario,
        activo=True
    ).order_by(FilaEspera.fechaSolicitud.asc()).all()
    
    primer_cliente_elegible = None
    
    for fila in candidatos:

        if any(reserva.idCliente == fila.idCliente for reserva in cita.reservas):
            continue # No notificamos al cliente que acaba de cancelar/reagendar
        
        if fila.fechaUltimoAviso and fila.fechaUltimoAviso.date() >= (dt_date.today() - timedelta(days=6)):
            # logger.info(f"Cliente {fila.idCliente} ya recibió aviso hace menos de 7 días, se omite.")
            continue
        
        # Obtener la fecha y la hora actual del servidor
        ahora = datetime.now()
        fecha_hoy = ahora.date()
        hora_actual = ahora.time()

        cita_activa = CitaCliente.query.join(Cita).filter(
            CitaCliente.idCliente == fila.idCliente,
            CitaCliente.idEstatus.in_([const.RESERVADA, const.CONFIRMADA]),
            Cita.idEmpresa == id_empresa,
            Cita.idUsuario == id_usuario,
            or_(
                Cita.fechaCita > fecha_hoy,
                and_(
                    Cita.fechaCita == fecha_hoy,
                    Cita.horaCita > hora_actual
                )
            )
        ).first()

        if cita_activa:
            continue
                
        if fila.diasSemana:
            dias_permitidos = [d.strip() for d in fila.diasSemana.split(',')]
            if dia_semana_cita not in dias_permitidos:
                continue # No coincide el día, pasamos al siguiente candidato
        
        if fila.horaDesde and hora_cita < fila.horaDesde:
            continue
            
        if fila.horaHasta and hora_cita > fila.horaHasta:
            continue
        
        primer_cliente_elegible = fila
        break # Rompemos el ciclo porque solo queremos al primero de la lista
        
    if primer_cliente_elegible:
        fecha_cita = cita.fechaCita
        hora_cita  = cita.horaCita
        fecha_str  = fecha_cita.strftime('%d/%m/%Y') if fecha_cita else '---'
        hora_str   = hora_cita.strftime('%H:%M')     if hora_cita  else '---'
        staff      = (cita.usuario.alias or cita.usuario.nombreUsuario) if cita.usuario else 'tu terapeuta'
        empresa    = cita.empresa.razonSocial if cita.empresa else 'la empresa'

        cliente = primer_cliente_elegible.cliente

        token   = _generar_token_acceso(
            id_cliente=cliente.idCliente,
            id_empresa=cita.idEmpresa,
            id_usuario=cita.idUsuario,
            fecha=fecha_cita.strftime('%Y-%m-%d') if fecha_cita else ''
        )
        url_base = current_app.config.get("URL_BASE", "https://www.citanet.com.mx")
        link = f"{url_base}/cliente/acceso-directo/{token}"

        mensaje = (
            f"📅 *{empresa}* — Cita disponible\n\n"
            f"Hola *{cliente.nombreCliente}*, hay una cita disponible que podría interesarte:\n\n"
            f"🗓 Fecha: {fecha_str}\n"
            f"⏰ Hora: {hora_str}\n"
            f"👤 Con: {staff}\n\n"
            f"👉 Entra aquí para reservarla:\n{link}\n\n"
            f"_Si ya tienes cita o no te interesa, ignora este mensaje._"
        )
        
        enviar_whatsapp(cliente.telefono, mensaje, id_empresa)
        
        primer_cliente_elegible.cantidadAvisos += 1
        primer_cliente_elegible.fechaUltimoAviso = datetime.now()
        
        db.session.commit()
        #logger.info(f"Notificación enviada al primer cliente elegible en fila: {cliente.nombreCliente} (ID: {cliente.idCliente})")
        return True
        
    else:
        #logger.info("No se encontró ningún cliente en la fila que coincida con el horario de esta cita.")
        return False


@citas_cliente_bp.route('/cliente/fila_espera', methods=['GET'])
def ver_fila_espera():
    if 'idCliente' not in session:
        return redirect(url_for('cliente.login'))

    id_cliente = session['idCliente']
    id_empresa = session.get('idEmpresa')

    staff_list = Usuario.query.filter_by(
        idEmpresa=id_empresa,
        tipoUsuario='staff'
    ).order_by(Usuario.nombreUsuario).all() if id_empresa else []

    filas = FilaEspera.query.filter_by(
        idCliente=id_cliente,
        idEmpresa=id_empresa
    ).order_by(FilaEspera.fechaSolicitud.desc()).all()

    staff_usados = [f.idUsuario for f in filas]

    return render_template('fila_espera_cliente.html',
                           staff_list=staff_list,
                           filas=filas,
                           staff_usados=staff_usados)


@citas_cliente_bp.route('/cliente/fila_espera/datos', methods=['GET'])
def fila_espera_datos():
    """Endpoint JSON para la app móvil: devuelve staff y filas activas del cliente."""
    if 'idCliente' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    id_cliente = session['idCliente']
    id_empresa = session.get('idEmpresa')

    staff_list = Usuario.query.filter_by(
        idEmpresa=id_empresa,
        tipoUsuario='staff'
    ).order_by(Usuario.nombreUsuario).all() if id_empresa else []

    filas = FilaEspera.query.filter_by(
        idCliente=id_cliente,
        idEmpresa=id_empresa
    ).order_by(FilaEspera.fechaSolicitud.desc()).all()

    return jsonify({
        'staff': [{'id': s.idUsuario, 'nombre': s.alias or s.nombreUsuario} for s in staff_list],
        'filas': [{
            'idFilaEspera':     f.idFilaEspera,
            'idUsuario':        f.idUsuario,
            'nombreStaff':      f.usuario.alias or f.usuario.nombreUsuario if f.usuario else '',
            'idProducto':       f.idProducto,
            'nombreProducto':   f.producto.nombre if f.producto else None,
            'activo':           f.activo,
            'fechaSolicitud':   f.fechaSolicitud.strftime('%d/%m/%Y') if f.fechaSolicitud else None,
            'fechaVencimiento': f.fechaVencimiento.strftime('%d/%m/%Y') if f.fechaVencimiento else None,
            'fechaUltimoAviso': f.fechaUltimoAviso.strftime('%d/%m/%Y %H:%M') if f.fechaUltimoAviso else None,
            'cantidadAvisos':   f.cantidadAvisos or 0,
            'diasDesdeCita':    f.diasDesdeCita,
            'diasSemana':       f.diasSemana,
            'horaDesde':        f.horaDesde.strftime('%H:%M') if f.horaDesde else None,
            'horaHasta':        f.horaHasta.strftime('%H:%M') if f.horaHasta else None,
        } for f in filas]
    })


@citas_cliente_bp.route('/cliente/fila_espera/servicios/<int:id_usuario>', methods=['GET'])
def servicios_staff(id_usuario):
    """Devuelve los servicios activos de un staff en JSON para el selector dinámico."""
    id_empresa = session.get('idEmpresa')
    productos = (Producto.query
        .join(ProductoUsuario, ProductoUsuario.idProducto == Producto.idProducto)
        .filter(
            ProductoUsuario.idUsuario == id_usuario,
            Producto.idEmpresa == id_empresa,
            Producto.activo == True,
            Producto.tipo == 'servicio'
        ).order_by(Producto.nombre).all())

    return jsonify([{'id': p.idProducto, 'nombre': p.nombre} for p in productos])


@citas_cliente_bp.route('/cliente/fila_espera/registrar', methods=['POST'])
def registrar_fila_espera():
    if 'idCliente' not in session:
        return jsonify({'success': False, 'message': 'Sesión expirada'}), 401

    data       = request.get_json(silent=True) or {}
    id_cliente = session['idCliente']
    id_empresa = session.get('idEmpresa')
    id_usuario = data.get('idUsuario')
    id_producto= data.get('idProducto')
    dias_desde = data.get('diasDesdeCita')
    dias_semana= data.get('diasSemana')       # lista [1,3,5]
    hora_desde = data.get('horaDesde')        # "09:00"
    hora_hasta = data.get('horaHasta')        # "13:00"
    fecha_venc = data.get('fechaVencimiento')

    if not id_usuario:
        return jsonify({'success': False, 'message': 'Selecciona un terapeuta'}), 400

    try:
        from datetime import datetime as dt, time as dt_time

        fecha_venc_dt = None
        if fecha_venc:
            fecha_venc_dt = dt.strptime(fecha_venc, '%Y-%m-%d').date()

        hora_desde_dt = None
        hora_hasta_dt = None
        if hora_desde:
            h, m = hora_desde.split(':')
            hora_desde_dt = dt_time(int(h), int(m))
        if hora_hasta:
            h, m = hora_hasta.split(':')
            hora_hasta_dt = dt_time(int(h), int(m))

        dias_str = None
        if dias_semana and isinstance(dias_semana, list):
            dias_str = ','.join(str(d) for d in dias_semana)

        id_fila = data.get('idFilaEspera')
        if id_fila:
            registro = FilaEspera.query.filter_by(
                idFilaEspera=int(id_fila),
                idCliente=id_cliente,
                idEmpresa=id_empresa
            ).first()
            if not registro:
                return jsonify({'success': False, 'message': 'No se encontró el registro para modificar.'}), 404

            existente = FilaEspera.query.filter(
                FilaEspera.idCliente == id_cliente,
                FilaEspera.idEmpresa == id_empresa,
                FilaEspera.idUsuario == int(id_usuario),
                FilaEspera.idFilaEspera != registro.idFilaEspera
            ).first()
            if existente:
                return jsonify({'success': False, 'message': 'Ya tienes una fila de espera para este terapeuta'}), 400

            registro.idUsuario        = int(id_usuario)
            registro.idProducto       = int(id_producto) if id_producto else None
            registro.activo           = True
            registro.diasDesdeCita    = int(dias_desde) if dias_desde else None
            registro.diasSemana       = dias_str
            registro.horaDesde        = hora_desde_dt
            registro.horaHasta        = hora_hasta_dt
            registro.fechaVencimiento = fecha_venc_dt
            db.session.commit()
            message = 'Tu registro de fila de espera fue actualizado y activado.'
        else:
            existente = FilaEspera.query.filter_by(
                idCliente=id_cliente,
                idEmpresa=id_empresa,
                idUsuario=int(id_usuario)
            ).first()
            if existente:
                return jsonify({'success': False, 'message': 'Ya tienes una fila de espera para este terapeuta'}), 400

            nueva_fila = FilaEspera(
                idEmpresa        = id_empresa,
                idUsuario        = int(id_usuario),
                idCliente        = id_cliente,
                idProducto       = int(id_producto) if id_producto else None,
                activo           = True,
                diasDesdeCita    = int(dias_desde) if dias_desde else None,
                diasSemana       = dias_str,
                horaDesde        = hora_desde_dt,
                horaHasta        = hora_hasta_dt,
                fechaVencimiento = fecha_venc_dt
            )
            db.session.add(nueva_fila)
            db.session.commit()
            message = 'Te registramos en la fila de espera. Te avisaremos por WhatsApp cuando haya citas disponibles que coincidan con tus preferencias.'

        return jsonify({'success': True, 'message': message})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error al registrar: {str(e)}'}), 500


@citas_cliente_bp.route('/cliente/fila_espera/cancelar/<int:id_fila>', methods=['POST'])
def cancelar_fila_espera(id_fila):
    if 'idCliente' not in session:
        return jsonify({'success': False, 'message': 'Sesión expirada'}), 401

    id_cliente = session['idCliente']
    registro = FilaEspera.query.filter_by(
        idFilaEspera=id_fila,
        idCliente=id_cliente
    ).first()

    if not registro:
        return jsonify({'success': False, 'message': 'Registro no encontrado'}), 404

    try:
        registro.activo = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'Saliste de la fila de espera'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@citas_cliente_bp.route('/aviso_cita_disponible', methods=['GET'])
def aviso_cita_disponible():
    if 'idUsuario' not in session:
        return redirect(url_for('usuarios.login'))
    # acceso_directo() también guarda idUsuario en la sesión de los clientes,
    # así que además se exige que sea personal del sistema
    if session.get('tipoUsuario') not in ('admin', 'staff', 'asistente', 'superuser'):
        return redirect(url_for('usuarios.login'))

    id_empresa = session.get('idEmpresa')
    tipo_usuario = session.get('tipoUsuario')  # 'admin', 'staff', 'asistente', 'superuser'
    id_usuario_sesion = session.get('idUsuario')

    # 1. Obtener especialista(s) para el selector (solo de tipo 'staff')
    query_staff = Usuario.query.filter_by(idEmpresa=id_empresa, tipoUsuario='staff')
    
    if tipo_usuario == 'staff':
        query_staff = query_staff.filter_by(idUsuario=id_usuario_sesion)
        
    lista_especialistas = query_staff.all()

    # Parámetros desde la URL
    dias_inactivos = request.args.get('dias_inactivos', type=int, default=30)
    id_especialista = request.args.get('id_especialista', type=int)
    busqueda = request.args.get('busqueda', type=str, default='').strip()

    # Si no se especifica, tomar el ID del especialista correspondiente
    if not id_especialista:
        if tipo_usuario == 'staff':
            id_especialista = id_usuario_sesion
        elif lista_especialistas:
            id_especialista = lista_especialistas[0].idUsuario

    clientes_resultado = []

    if id_especialista:
        fecha_limite = datetime.now() - timedelta(days=dias_inactivos)
        ahora_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        logger.info(f"fecha_limite: {fecha_limite} , ahora: {ahora_str}")

        # Aliases
        CitaFutura = aliased(Cita)
        ReservaFutura = aliased(CitaCliente)
        UltimaCita = aliased(Cita)
        UltimaReserva = aliased(CitaCliente)

        # Estatus activos
        id_estatus_reservada = EstatusCita.id_estatus('Reservada')
        id_estatus_confirmada = EstatusCita.id_estatus('Confirmada')
        estatus_activos = [e for e in [id_estatus_reservada, id_estatus_confirmada] if e is not None]

        concat_futura = func.concat(cast(CitaFutura.fechaCita, String), ' ', cast(CitaFutura.horaCita, String))
        concat_ultima = func.concat(cast(UltimaCita.fechaCita, String), ' ', cast(UltimaCita.horaCita, String))

        # 1. Clientes con cita futura/activa con este especialista
        subq_cita_futura = db.session.query(ReservaFutura.idCliente).join(
            CitaFutura, CitaFutura.idCita == ReservaFutura.idCita
        ).filter(
            CitaFutura.idEmpresa == id_empresa,
            CitaFutura.idUsuario == id_especialista,
            ReservaFutura.idEstatus.in_(estatus_activos),
            concat_futura >= ahora_str
        ).distinct().subquery()

        # 2. Última cita PASADA del cliente (Filtrada por la empresa del sistema)
        subq_ultima_cita = db.session.query(
            UltimaReserva.idCliente,
            func.max(concat_ultima).label('max_fecha')
        ).join(
            UltimaCita, UltimaCita.idCita == UltimaReserva.idCita
        ).filter(
            UltimaCita.idEmpresa == id_empresa,
            UltimaCita.idUsuario == id_especialista,
            concat_ultima <= ahora_str  # solo citas que ya pasaron; las futuras activas se excluyen con subq_cita_futura
        ).group_by(UltimaReserva.idCliente).subquery()

        # 3. Consulta Principal
        # Consulta Principal: Unimos Cliente -> ClienteEmpresa -> subq_ultima_cita -> UltimaCita -> EstatusCita
        query = db.session.query(
            Cliente,
            subq_ultima_cita.c.max_fecha,
            EstatusCita.nombre.label('nombre_estatus')
        ).select_from(Cliente).join(
            ClienteEmpresa, ClienteEmpresa.idCliente == Cliente.idCliente
        ).outerjoin(
            subq_ultima_cita, subq_ultima_cita.c.idCliente == Cliente.idCliente
        ).outerjoin(
            UltimaCita, and_(
                UltimaCita.idUsuario == id_especialista,
                concat_ultima == subq_ultima_cita.c.max_fecha
            )
        ).outerjoin(
            UltimaReserva, and_(
                UltimaReserva.idCita == UltimaCita.idCita,
                UltimaReserva.idCliente == Cliente.idCliente
            )
        ).outerjoin(
            EstatusCita, EstatusCita.idEstatus == UltimaReserva.idEstatus
        ).filter(
            ClienteEmpresa.idEmpresa    == id_empresa,  # Filtro correcto de empresa mediante la tabla intermedia
            ClienteEmpresa.avisoEnviado == False,       # Excluye los ya avisados
            Cliente.fallecido == False,
            not_(Cliente.idCliente.in_(select(subq_cita_futura.c.idCliente))),
            or_(
                subq_ultima_cita.c.max_fecha <= fecha_limite.strftime('%Y-%m-%d %H:%M:%S'),
                subq_ultima_cita.c.max_fecha.is_(None)
            )
        )

        resultados = query.all()

        clientes_resultado = []
        for cliente, max_fecha, nombre_estatus in resultados:
            es_nuevo = max_fecha is None
            fecha_str = "Sin citas previas"
            ultimo_st = "Sin citas previas"
            
            if max_fecha:
                try:
                    f_obj = datetime.strptime(str(max_fecha)[:19], '%Y-%m-%d %H:%M:%S')
                    fecha_str = f_obj.strftime('%d/%m/%Y %H:%M')
                    ultimo_st = nombre_estatus or "Desconocido"
                except ValueError:
                    fecha_str = str(max_fecha)
                    ultimo_st = nombre_estatus or "Desconocido"

            clientes_resultado.append({
                'idCliente': cliente.idCliente,
                'nombre': cliente.nombreCliente,
                'telefono': cliente.telefono or '',
                'es_nuevo': es_nuevo,
                'ultima_cita': fecha_str,
                'ultimo_estatus': ultimo_st 
            })

    # IMPORTANTE: Este return debe ir fuera del 'if id_especialista:', al nivel principal de la función
    return render_template(
        'aviso_cita_disponible.html',
        especialistas=lista_especialistas,
        clientes=clientes_resultado,
        dias_inactivos=dias_inactivos,
        id_especialista_sel=id_especialista,
        busqueda=busqueda,
        tipo_usuario=tipo_usuario
    )


@citas_cliente_bp.route('/enviar_aviso_cita_disponible', methods=['POST'])
def enviar_aviso_cita_disponible():
    if 'idUsuario' not in session:
        return jsonify({'status': 'error', 'message': 'Sesión no válida'}), 401
    if session.get('tipoUsuario') not in ('admin', 'staff', 'asistente', 'superuser'):
        return jsonify({'status': 'error', 'message': 'Sin permisos'}), 403

    id_empresa = session.get('idEmpresa')
    data = request.get_json() or {}

    id_cliente = data.get('idCliente')
    id_especialista = data.get('idEspecialista')
    #dias = data.get('diasInactivos', 30)

    if not id_cliente or not id_especialista:
        return jsonify({'status': 'error', 'message': 'Datos incompletos'}), 400

    cliente = Cliente.query.filter_by(idCliente=id_cliente).first()
    especialista = Usuario.query.filter_by(idUsuario=id_especialista, idEmpresa=id_empresa).first()
    razon_social = session.get('NombreEmpresa', 'CitaNet')

    if not cliente or not cliente.telefono:
        return jsonify({'status': 'error', 'message': 'Cliente sin teléfono válido'}), 400
    
    # 1. Validar si ya se envió previamente
    cliente_empresa = ClienteEmpresa.query.filter_by(
        idCliente=id_cliente, 
        idEmpresa=id_empresa
    ).first()

    if cliente_empresa and cliente_empresa.avisoEnviado:
        return jsonify({
            'status': 'already_sent', 
            'message': 'El aviso ya fue enviado anteriormente a este cliente'
        }), 200
    
    # Generación de token y enlace con acceso directo
    token = _generar_token_acceso(
        id_cliente=cliente.idCliente,
        id_empresa=id_empresa,
        id_usuario=especialista.idUsuario,
        fecha=''
    )
    url_base = current_app.config.get("URL_BASE", "https://www.citanet.com.mx")
    link_acceso = f"{url_base}/cliente/acceso-directo/{token}"

    nombre_staff = especialista.alias or especialista.nombreUsuario

    MENSAJE_DEFAULT = (
        "📅 *{empresa}* — Aviso de Cita disponible\n\n"
        "Hola {nombre}\n\n"
        "¡Queremos saber cómo estás! Tenemos lugares disponibles para ti si deseas agendar nuevamente con *{especialista}*:\n\n"
        "👉 *Reserva tu horario preferido aquí:*\n"
        "{link}"
    )

    # Mensaje variable: viene del cuadro de diálogo; si llega vacío se usa el mensaje de siempre
    plantilla = (data.get('mensaje') or '').strip()[:1000] or MENSAJE_DEFAULT

    # Si el usuario no puso {link}, se agrega al final para no mandar un aviso sin enlace
    if '{link}' not in plantilla:
        plantilla += "\n\n👉 *Reserva aquí:*\n{link}"

    # replace() en lugar de format() para que llaves sueltas en el texto no truenen
    mensaje = (
        plantilla
        .replace('{nombre}', cliente.nombreCliente or '')
        .replace('{especialista}', nombre_staff)
        .replace('{empresa}', razon_social)
        .replace('{link}', link_acceso)
    )

    # Llamar a la función que ahora devuelve la tupla
    exito, detalle = enviar_whatsapp(cliente.telefono, mensaje, idEmpresaEnvia=id_empresa)

    if exito:
        if cliente_empresa:
            cliente_empresa.avisoEnviado = True
            cliente_empresa.fechaUltimoAviso = datetime.now()
            db.session.commit()
        return jsonify({'status': 'success', 'message': 'Aviso enviado correctamente'}), 200
    else:
        # Retornamos status error pero con código HTTP 200 para que el JS capture el JSON ordenadamente
        return jsonify({'status': 'error', 'message': detalle}), 200