import logging
import calendar

from flask       import Blueprint, render_template, request, redirect, url_for, flash, session, abort, jsonify
from modelos     import db, Pais, Plan, Empresa, ConfiguracionWhatsapp, metodoPago, tipoMovimiento, Cita, CitaCliente, movCuenta, Usuario, Cliente, Producto, movAplica, Config, Version, VisitaIndex, EstatusCita, ColorEstatusCitaEmpresa, CitaProducto, Vendedor, NivelComisionVendedor, Comunicado, ComunicadoLeido
from datetime    import datetime, timedelta, date
from decimal     import Decimal, InvalidOperation
from sqlalchemy  import func, extract, or_
from sqlalchemy.orm import aliased
from collections import defaultdict
from functools   import wraps
from constantes  import const
from whatsapp    import enviar_whatsapp

logger = logging.getLogger(__name__)

# Definimos el Blueprint
admin_bp = Blueprint('admin', __name__)

def superuser_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Verificar si hay sesión activa
        if 'idUsuario' not in session:
            flash('Por favor, inicia sesión primero.', 'danger')
            return redirect(url_for('login')) # Ajusta a tu ruta de login
        
        # 2. Verificar en la base de datos el tipo de usuario
        usuario = Usuario.query.get(session['idUsuario'])
        if not usuario or usuario.tipoUsuario != 'superuser':
            flash('Acceso denegado. Solo el superuser puede gestionar los países.', 'danger')
            return redirect(url_for('admin.dashboard')) # Ajusta a tu panel principal
            
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/paises', methods=['GET', 'POST'])
@superuser_required
def mantener_paises():
    if request.method == 'POST':
        # Detectar si es una edición o una nueva inserción
        id_pais = request.form.get('idPais')
        
        clave = request.form.get('clave').upper().strip()
        iso3 = request.form.get('iso3').upper().strip()
        nombre = request.form.get('nombre').strip()
        codigoArea = request.form.get('codigoArea').strip()
        idioma = request.form.get('idioma').lower().strip()
        longitudMin = int(request.form.get('longitudMin', 10))
        longitudMax = int(request.form.get('longitudMax', 10))
        activo = True if request.form.get('activo') else False

        # Si el código de área no trae el '+', se lo ponemos automáticamente
        if not codigoArea.startswith('+'):
            codigoArea = f'+{codigoArea}'

        if id_pais:
            # --- Modo Edición ---
            pais = Pais.query.get(id_pais)
            if pais:
                pais.clave = clave
                pais.iso3 = iso3
                pais.nombre = nombre
                pais.codigoArea = codigoArea
                pais.idioma = idioma
                pais.longitudMin = longitudMin
                pais.longitudMax = longitudMax
                pais.activo = activo
                flash(f'País "{nombre}" actualizado correctamente.', 'success')
        else:
            # --- Modo Creación ---
            nuevo_pais = Pais(
                clave=clave,
                iso3=iso3,
                nombre=nombre,
                codigoArea=codigoArea,
                idioma=idioma,
                longitudMin=longitudMin,
                longitudMax=longitudMax,
                activo=activo
            )
            db.session.add(nuevo_pais)
            flash(f'País "{nombre}" registrado con éxito.', 'success')
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'Error al guardar en la base de datos: {str(e)}', 'danger')
            
        return redirect(url_for('admin.mantener_paises'))

    # Método GET: Listar todos los países ordenados por nombre
    paises = Pais.query.order_by(Pais.nombre.asc()).all()
    return render_template('admin/paises.html', paises=paises)


@admin_bp.route('/paises/toggle/<int:id_pais>', methods=['POST'])
@superuser_required
def toggle_pais(id_pais):
    """Endpoint rápido AJAX para activar/desactivar un país desde la tabla sin recargar toda la página"""
    pais = Pais.query.get_or_4000(id_pais)
    if pais:
        pais.activo = not pais.activo
        db.session.commit()
        return jsonify({'status': 'success', 'nuevo_estado': pais.activo})
    return jsonify({'status': 'error', 'message': 'País no encontrado'}), 404


@admin_bp.route('/admin/importar-contactos', methods=['GET', 'POST'])
@superuser_required
def importar_contactos():
    if request.method == 'POST':
        archivo = request.files.get('archivo')
        if not archivo or not archivo.filename:
            flash('Selecciona un archivo de texto para importar.', 'danger')
            return redirect(url_for('admin.importar_contactos'))

        nombre_archivo = (archivo.filename or '').lower()
        if not nombre_archivo.endswith('.txt'):
            flash('Solo se permiten archivos .txt.', 'danger')
            return redirect(url_for('admin.importar_contactos'))

        try:
            from crea_cte import crear_clientes_desde_texto
            contenido = archivo.read()
            texto = contenido.decode('utf-8', errors='ignore')
            clientes = crear_clientes_desde_texto(texto)
            flash(f'Se importaron {len(clientes)} clientes correctamente.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al importar el archivo: {str(e)}', 'danger')

        return redirect(url_for('admin.importar_contactos'))

    return render_template('admin_importar_contactos.html')


@admin_bp.route('/admin/config', methods=['GET', 'POST'])
@superuser_required
def configurar():
    config = Config.query.first()
    
    if not config:
        config = Config(versionApk='1')
        db.session.add(config)
        db.session.commit()

    # Paquetes de publicidad disponibles (mismos que se ofrecen en la compra normal:
    # productos de la empresa 1, activos, tipo 'producto') para los combos de bonificación.
    paquetes_publicidad = Producto.query.filter_by(
        idEmpresa=1,
        activo=True,
        tipo='producto'
    ).order_by(Producto.nombre).all()

    if request.method == 'POST':

        nuevo_build = request.form.get('versionApk')
        # Campo presente en el POST solo cuando se envía el formulario de bonificación
        # (se usa como bandera para distinguir de los otros guardados de esta misma pantalla)
        bonificacion_enviada = 'idProductoBonifCliente' in request.form or 'idProductoBonifEmpresa' in request.form

        if nuevo_build:
            config.versionApk = nuevo_build.strip()

        if bonificacion_enviada:
            id_prod_cliente = request.form.get('idProductoBonifCliente')
            id_prod_empresa = request.form.get('idProductoBonifEmpresa')

            ids_validos = {p.idProducto for p in paquetes_publicidad}

            if id_prod_cliente and int(id_prod_cliente) not in ids_validos:
                flash('El paquete seleccionado para bonificación de cliente no es válido.', 'danger')
                return redirect(url_for('admin.configurar'))
            if id_prod_empresa and int(id_prod_empresa) not in ids_validos:
                flash('El paquete seleccionado para bonificación de empresa no es válido.', 'danger')
                return redirect(url_for('admin.configurar'))

            config.idProductoBonifCliente = int(id_prod_cliente) if id_prod_cliente else None
            config.idProductoBonifEmpresa = int(id_prod_empresa) if id_prod_empresa else None

        if nuevo_build or bonificacion_enviada:
            try:
                db.session.commit()
                flash('Configuración actualizada correctamente.', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Error al guardar en la base de datos: {str(e)}', 'danger')
            return redirect(url_for('admin.configurar'))

    versiones = Version.query.order_by(Version.fechaLanzamiento.desc(), Version.idVersion.desc()).all()
    
    return render_template('config.html', config=config, versiones=versiones, paquetes_publicidad=paquetes_publicidad)

@admin_bp.route('/admin/planes')
def planes():
    if session.get('tipoUsuario') != 'superuser':
        flash("Acceso no autorizado", "danger")
        return redirect(url_for('login'))
        
    planes = Plan.query.all()
    return render_template('planes_lista.html', planes=planes)


@admin_bp.route('/admin/planes/gestion', defaults={'idPlan': None}, methods=['GET', 'POST'])
@admin_bp.route('/admin/planes/gestion/<int:idPlan>', methods=['GET', 'POST'])
def gestion_plan(idPlan):
    if session.get('tipoUsuario') != 'superuser':
        return redirect(url_for('login'))

    plan = Plan.query.get(idPlan) if idPlan else None

    if request.method == 'POST':
        nombre = request.form.get('nombrePlan')
        desc = request.form.get('descripcion')
        clientes = request.form.get('maxCantClientes')
        usuarios = request.form.get('maxCantUsuarios')
        c_mensual = request.form.get('costoMensual')
        c_anual = request.form.get('costoAnual')
        estatus = request.form.get('estatusPlan')

        if not plan:
            plan = Plan()
            db.session.add(plan)

        plan.nombrePlan = nombre
        plan.descripcion = desc
        plan.maxCantClientes = clientes
        plan.maxCantUsuarios = usuarios
        plan.costoMensual = c_mensual
        plan.costoAnual = c_anual
        plan.estatusPlan = estatus

        try:
            db.session.commit()
            flash(f"Plan '{nombre}' actualizado correctamente", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error al guardar: {str(e)}", "danger")
            
        return redirect(url_for('admin.planes'))

    return render_template('plan_form.html', plan=plan)

# --- ELIMINAR (DESACTIVAR) PLAN ---
@admin_bp.route('/admin/planes/eliminar/<int:idPlan>')
def eliminar_plan(idPlan):
    if session.get('tipoUsuario') != 'superuser':
        return redirect(url_for('login'))
        
    plan = Plan.query.get_or_404(idPlan)
    empresas_usando = Empresa.query.filter_by(idPlan=idPlan).count()
    
    if empresas_usando > 0:
        plan.estatusPlan = 'inactivo'
        flash(f"El plan tiene {empresas_usando} empresas ligadas. Se marcó como 'inactivo'.", "warning")
    else:
        db.session.delete(plan)
        flash("Plan eliminado físicamente.", "success")
        
    db.session.commit()
    return redirect(url_for('admin.planes'))


@admin_bp.route('/admin/vendedores')
@superuser_required
def catalogo_vendedores():
    vendedores = Vendedor.query.order_by(Vendedor.nombre.asc()).all()
    return render_template('vendedores_lista.html', vendedores=vendedores)


@admin_bp.route('/admin/niveles-vendedores')
@superuser_required
def catalogo_niveles_vendedores():
    niveles = NivelComisionVendedor.query.order_by(NivelComisionVendedor.idNivelComision.asc()).all()
    return render_template('niveles_vendedores_lista.html', niveles=niveles)


@admin_bp.route('/admin/niveles-vendedores/gestion', defaults={'idNivelComision': None}, methods=['GET', 'POST'])
@admin_bp.route('/admin/niveles-vendedores/gestion/<int:idNivelComision>', methods=['GET', 'POST'])
@superuser_required
def gestion_nivel_vendedor(idNivelComision):
    nivel = NivelComisionVendedor.query.get(idNivelComision) if idNivelComision else None

    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        if not nombre:
            flash('El nombre del nivel es obligatorio.', 'danger')
            return redirect(url_for('admin.gestion_nivel_vendedor', idNivelComision=idNivelComision))

        porc_comision = request.form.get('porcComision', type=float)
        periodo_meses = request.form.get('periodoComisionMeses', type=int)
        empresas_activas = request.form.get('empresasActivas', type=int)
        comision_pagada = request.form.get('comisionPagada', type=int)

        if porc_comision is None or not 0 <= porc_comision <= 100 or periodo_meses is None or periodo_meses < 1:
            flash('La comisión debe estar entre 0 y 100, y el periodo debe ser de al menos un mes.', 'danger')
            return redirect(url_for('admin.gestion_nivel_vendedor', idNivelComision=idNivelComision))

        if not nivel:
            nivel = NivelComisionVendedor()
            db.session.add(nivel)

        nivel.nombre = nombre
        nivel.porcComision = porc_comision
        nivel.periodoComisionMeses = periodo_meses
        nivel.empresasActivas = empresas_activas
        nivel.comisionPagada = comision_pagada
        nivel.activo = request.form.get('activo') == 'on'

        try:
            db.session.commit()
            flash(f"Nivel '{nombre}' guardado correctamente.", 'success')
        except Exception as error:
            db.session.rollback()
            flash(f'Error al guardar el nivel: {error}', 'danger')
        return redirect(url_for('admin.catalogo_niveles_vendedores'))

    return render_template('nivel_vendedor_form.html', nivel=nivel)

# --- WHATSAPP ---
@admin_bp.route("/admin/vincular_whatsapp")
def vincular_whatsapp():
    if session.get('tipoUsuario') not in ['admin', 'superuser']:
        return redirect(url_for('login'))
    
    id_empresa = session.get("idEmpresa")
    config_wa = ConfiguracionWhatsapp.query.filter_by(idEmpresa=id_empresa).first()
    
    if not config_wa:
        config_wa = ConfiguracionWhatsapp(
            idEmpresa=id_empresa,
            instancia=f"CN_Empresa_{id_empresa}",
            status_conexion="DISCONNECTED"
        )
        db.session.add(config_wa)
        db.session.commit()
    
    return render_template("vincular_whatsapp.html", config=config_wa)

# ==========================================
# MÉTODOS DE PAGO 
# ==========================================

@admin_bp.route('/admin/metodos_pago')
def metodos_pago():
    if session.get('tipoUsuario') != 'superuser':
        flash("Acceso no autorizado", "danger")
        return redirect(url_for('login'))
    metodos = metodoPago.query.all()
    return render_template('metodos_pago_lista.html', metodos=metodos)

@admin_bp.route('/admin/metodos_pago/guardar', methods=['POST'])
def guardar_metodo_pago():
    if session.get('tipoUsuario') != 'superuser':
        return redirect(url_for('login'))

    id_metodo = request.form.get('idmetodoPago')
    nombre = request.form.get('nombre')
    activo = True if request.form.get('activo') == 'on' else False
    acumula_puntos = True if request.form.get('acumulaPuntos') == 'on' else False

    try:
        if id_metodo:
            metodo = metodoPago.query.get(id_metodo)
            if metodo:
                metodo.nombre = nombre
                metodo.activo = activo
                metodo.acumulaPuntos = acumula_puntos
                flash(f"Método '{nombre}' actualizado", "success")
        else:
            nuevo = metodoPago(nombre=nombre, activo=activo, acumulaPuntos=acumula_puntos)
            db.session.add(nuevo)
            flash(f"Método '{nombre}' creado", "success")
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for('admin.metodos_pago'))

@admin_bp.route('/admin/metodos_pago/eliminar/<int:idMetodo>')
def eliminar_metodo_pago(idMetodo):
    if session.get('tipoUsuario') != 'superuser':
        return redirect(url_for('login'))
    metodo = metodoPago.query.get_or_404(idMetodo)
    try:
        db.session.delete(metodo)
        db.session.commit()
        flash("Eliminado", "success")
    except:
        db.session.rollback()
        metodo.activo = False
        db.session.commit()
        flash("Inactivado por historial existente", "warning")
    return redirect(url_for('admin.metodos_pago'))


# ==========================================
# TIPOS DE MOVIMIENTO
# ==========================================

@admin_bp.route('/admin/tipos_movimiento')
def tipos_movimiento():
    if session.get('tipoUsuario') != 'superuser':
        flash("Acceso no autorizado", "danger")
        return redirect(url_for('login'))
    tipos = tipoMovimiento.query.all()
    return render_template('tipos_movimiento_lista.html', tipos=tipos)

@admin_bp.route('/admin/tipos_movimiento/guardar', methods=['POST'])
def guardar_tipo_movimiento():
    if session.get('tipoUsuario') != 'superuser':
        return redirect(url_for('login'))

    id_tipo = request.form.get('idtipoMovimiento')
    nombre = request.form.get('nombre')
    desc = request.form.get('descripcion')
    # Si el switch está ON, es Abono ('A'), si no, es Cargo ('C')
    naturaleza = 'A' if request.form.get('naturaleza') == 'on' else 'C'

    try:
        if id_tipo:
            tipo = tipoMovimiento.query.get(id_tipo)
            if tipo:
                tipo.nombre = nombre
                tipo.descripcion = desc
                tipo.naturaleza = naturaleza
                flash(f"Tipo '{nombre}' actualizado", "success")
        else:
            nuevo = tipoMovimiento(nombre=nombre, descripcion=desc, naturaleza=naturaleza)
            db.session.add(nuevo)
            flash(f"Tipo '{nombre}' creado", "success")
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for('admin.tipos_movimiento'))

@admin_bp.route('/admin/tipos_movimiento/eliminar/<int:idTipo>')
def eliminar_tipo_movimiento(idTipo):
    if session.get('tipoUsuario') != 'superuser':
        return redirect(url_for('login'))
    tipo = tipoMovimiento.query.get_or_404(idTipo)
    try:
        db.session.delete(tipo)
        db.session.commit()
        flash("Eliminado correctamente", "success")
    except:
        db.session.rollback()
        flash("No se puede eliminar porque tiene historial, pero puedes desactivarlo manualmente si agregas campo activo.", "warning")
    return redirect(url_for('admin.tipos_movimiento'))


@admin_bp.route("/admin/log_accesos")
def ver_log_accesos():
    if 'idUsuario' not in session:
        return redirect("/")
    
    if session.get('tipoUsuario') != 'superuser':
        flash("Acceso no autorizado", "danger")
        return redirect(url_for('login'))
        
    logs_db = VisitaIndex.query.order_by(VisitaIndex.fecha.desc()).all()

    BOT_KEYWORDS = [
        # Bots e Indexadores estándar
        'bot', 'crawler', 'spider', 'google', 'facebook', 'tencent', 
        'digitalocean', 'selectel', 'akamai',
        
        # Servidores de ráfagas internacionales anteriores
        'level 3', 'digital llc', 'glide student', 'wirels connect',
        
        # NUEVOS: Servidores de hosting detectados en este reporte
        'cherry servers', 'ovh sas', 'oculus networks', 'hostroyale'
    ]
    logs_reales = []
    for log in logs_db:
        # Forzamos TODO a minúsculas (.strip() elimina espacios en blanco fantasmas)
        navegador = (log.navegador or '').lower().strip()
        sistema_op = (log.sistema_op or '').lower().strip()
        isp = (log.isp or '').lower().strip()
        
        if navegador == 'desconocido' or sistema_op == 'desconocido':
            continue
            
        es_bot = any(kw in isp or kw in navegador or kw in sistema_op for kw in BOT_KEYWORDS)
        
        if not es_bot:
            logs_reales.append(log)

    return render_template("admin_logs.html", logs=logs_reales)

# ==========================================
# DASHBOARD DIARIO POR STAFF
# ==========================================
# Reemplaza al viejo dashboard mensual (eliminado). Muestra, para un día y un
# especialista (staff) seleccionados, el detalle de citas del día (con su
# costo desglosado) y los conteos por estatus para la gráfica. Si quien entra
# es 'staff', solo ve su propia información; si es 'admin' o 'asistente',
# puede elegir cualquier staff de la empresa, igual que en la agenda semanal.
@admin_bp.route('/admin/dashboard')
def dashboard():
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        flash('Por favor, inicia sesión primero.', 'danger')
        return redirect(url_for('login'))

    tipo = session.get('tipoUsuario')
    if tipo not in ('admin', 'staff', 'asistente', 'superuser'):
        abort(403)

    id_empresa = session.get('idEmpresa')
    id_usuario_sesion = session.get('idUsuario')

    empresa = Empresa.query.get_or_404(id_empresa)
    usuario_sesion = Usuario.query.get(id_usuario_sesion)
    nombre_usuario_sesion = (usuario_sesion.alias or usuario_sesion.nombreUsuario) if usuario_sesion else ''

    staff_lista = []
    if tipo == 'staff':
        id_staff_seleccionado = id_usuario_sesion
    else:
        staff_lista = Usuario.query.filter_by(
            idEmpresa=id_empresa,
            tipoUsuario='staff'
        ).order_by(Usuario.nombreUsuario).all()

        id_staff_seleccionado = request.args.get('idUsuario', type=int) or id_usuario_sesion

    return render_template(
        'dashboard.html',
        empresa=empresa,
        tipo_usuario=tipo,
        staff_lista=staff_lista,
        id_staff_seleccionado=id_staff_seleccionado,
        nombre_usuario_sesion=nombre_usuario_sesion,
        fecha_hoy=datetime.now().strftime('%Y-%m-%d')
    )


PERIODOS_DASHBOARD = ('dia', 'semana', 'mes')

_ETIQUETAS_PERIODO = {
    'dia':    {'titulo': 'Resumen del día',    'ingreso': 'Ingresado en el día',    'vacio': 'este día'},
    'semana': {'titulo': 'Resumen de la semana', 'ingreso': 'Ingresado en la semana', 'vacio': 'esta semana'},
    'mes':    {'titulo': 'Resumen del mes',    'ingreso': 'Ingresado en el mes',    'vacio': 'este mes'},
}


def _normalizar_periodo(valor):
    """Devuelve 'dia', 'semana' o 'mes'; cualquier otro valor cae en 'dia'."""
    valor = (valor or '').strip().lower()
    return valor if valor in PERIODOS_DASHBOARD else 'dia'


def _rango_periodo(fecha, periodo):
    """Rango (inicio, fin) inclusivo del periodo que contiene a `fecha`.
    - dia:    solo ese día.
    - semana: lunes a domingo de la semana de `fecha`.
    - mes:    del día 1 al último día del mes de `fecha`."""
    if periodo == 'semana':
        inicio = fecha - timedelta(days=fecha.weekday())
        return inicio, inicio + timedelta(days=6)
    if periodo == 'mes':
        ultimo_dia = calendar.monthrange(fecha.year, fecha.month)[1]
        return fecha.replace(day=1), fecha.replace(day=ultimo_dia)
    return fecha, fecha


SIN_DESGLOSE_PRODUCTO = 'Sin desglose por producto'


def _atribuir_por_producto(items, solicitado_reserva, pagado_reserva, producto_respaldo=None):
    """Reparte lo cobrado de UNA reserva entre sus productos/servicios.

    `items` son los CitaProducto de la reserva, como dicts con nombre,
    cantidad, subtotal (precioCobrado x cantidad) y pagado (montoPagado).
    Lo que cada CitaProducto ya trae registrado se respeta; lo que falte para
    llegar a lo realmente cargado (`solicitado_reserva`) y lo realmente pagado
    (`pagado_reserva`, pagos aplicados al cargo) se reparte entre sus
    productos en proporción a su subtotal (o a su cantidad si el precio es 0).
    Si la reserva no tiene productos, se atribuye al producto de la cita
    (`producto_respaldo`) y, si tampoco lo hay, a "Sin desglose por producto".

    Así el desglose por producto siempre cuadra con el "Ingresado" y el
    desglose por forma de pago, que salen de los pagos aplicados.
    Devuelve {nombre: {'solicitado': x, 'pagado': y}}."""
    resultado = defaultdict(lambda: {'solicitado': 0.0, 'pagado': 0.0})
    for it in items:
        resultado[it['nombre']]['solicitado'] += it['subtotal']
        resultado[it['nombre']]['pagado'] += it['pagado']

    restos = {
        'solicitado': round(solicitado_reserva - sum(it['subtotal'] for it in items), 2),
        'pagado': round(pagado_reserva - sum(it['pagado'] for it in items), 2),
    }
    if all(resto <= 0.004 for resto in restos.values()):
        return resultado

    if items:
        destinos = [it['nombre'] for it in items]
        pesos_base = [it['subtotal'] for it in items]
        if sum(pesos_base) <= 0:
            pesos_base = [float(it['cantidad'] or 1) for it in items]
        # Lo pagado que falta repartir va primero a lo que aún no está cubierto
        # de cada producto (subtotal - pagado); si todo está cubierto, en
        # proporción a su subtotal.
        pesos_pagado = [max(it['subtotal'] - it['pagado'], 0.0) for it in items]
        if sum(pesos_pagado) <= 0:
            pesos_pagado = pesos_base
    else:
        destinos = [producto_respaldo or SIN_DESGLOSE_PRODUCTO]
        pesos_base = pesos_pagado = [1.0]

    for clave, resto in restos.items():
        if resto <= 0.004:
            continue
        pesos = pesos_pagado if clave == 'pagado' else pesos_base
        total_pesos = sum(pesos)
        acumulado = 0.0
        for k, (nombre, peso) in enumerate(zip(destinos, pesos)):
            if k == len(destinos) - 1:
                parte = round(resto - acumulado, 2)
            else:
                parte = round(resto * peso / total_pesos, 2)
                acumulado += parte
            resultado[nombre][clave] += parte
    return resultado


def _obtener_datos_dashboard(id_empresa, id_staff, fecha, periodo='dia'):
    """Recolecta las citas del periodo (día, semana o mes que contiene a
    `fecha`) para un staff, su detalle de costos y el conteo por estatus.
    La usan tanto /admin/dashboard_data como el envío por WhatsApp, para no
    duplicar la consulta ni el cálculo. Con periodo 'dia' se comporta igual
    que siempre; con 'semana' o 'mes' acumula toda la información estadística
    del rango."""
    periodo = _normalizar_periodo(periodo)
    fecha_inicio, fecha_fin = _rango_periodo(fecha, periodo)

    citas = Cita.query.join(EstatusCita, Cita.idEstatus == EstatusCita.idEstatus).filter(
        Cita.idEmpresa == id_empresa,
        Cita.idUsuario == id_staff,
        Cita.fechaCita >= fecha_inicio,
        Cita.fechaCita <= fecha_fin,
        func.lower(EstatusCita.nombre) != 'creada',
        or_(
            func.lower(EstatusCita.nombre) != 'vencida',
            Cita.reservas.any()
        ),
        # Excluye los slots absorbidos por una cita cuyo servicio duró más
        # de un espacio: ya se representan dentro de su cita maestra, no
        # deben contarse ni listarse aparte (se verían como "Espacio
        # disponible" fantasma aunque en realidad ya están ocupados).
        Cita.idCitaMaestra.is_(None)
    ).order_by(Cita.fechaCita.asc(), Cita.horaCita.asc()).all()

    conteo_estatus = defaultdict(int)
    colores_estatus = {}
    detalle_citas = []
    total_ingresado_dia = Decimal('0.00')
    desglose_pagos = defaultdict(float)
    desglose_productos = defaultdict(lambda: {'solicitado': 0.0, 'pagado': 0.0})
    total_pendientes_cerrar = 0

    for c in citas:
        nombre_estatus = c.estatus.nombre if c.estatus else 'Sin estatus'
        conteo_estatus[nombre_estatus] += 1

        # Mismo color que ya usa el badge de esta cita en la tabla de
        # detalle -lo real y configurado por la empresa-, para que la
        # gráfica de estatus use exactamente la misma paleta y no una
        # aparte que se desincroniza (como pasaba con "Reservada").
        color_estatus = ColorEstatusCitaEmpresa.color_cita_estatus(id_empresa, c.idEstatus) if c.idEstatus else '#5bbfa6'
        colores_estatus.setdefault(nombre_estatus, color_estatus)

        reservas = [reserva for reserva in c.reservas if reserva.ocupa_lugar]
        ids_reservas = [reserva.idCitaCliente for reserva in reservas]
        cargos = movCuenta.query.join(tipoMovimiento).filter(
            movCuenta.idEmpresa == id_empresa,
            movCuenta.idMovReferencia.in_(ids_reservas) if ids_reservas else False,
            movCuenta.idtipoMovimiento == const.MOV_CITA,
            tipoMovimiento.naturaleza == 'C'
        ).all()
        cargos_por_reserva = {cargo.idMovReferencia: cargo for cargo in cargos}

        productos_detalle = []
        nombre_producto_cita = c.producto.nombre if c.producto else None
        for reserva in reservas:
            items_reserva = []
            for cp in reserva.cita_productos:
                nombre_producto = cp.producto.nombre if cp.producto else 'Servicio'
                subtotal_producto = float(cp.precioCobrado or 0) * cp.cantidad
                productos_detalle.append({
                    'nombre': nombre_producto,
                    'cantidad': cp.cantidad,
                    'precioCobrado': float(cp.precioCobrado or 0),
                    'subtotal': subtotal_producto
                })
                items_reserva.append({
                    'nombre': nombre_producto,
                    'cantidad': cp.cantidad,
                    'subtotal': subtotal_producto,
                    'pagado': float(cp.montoPagado or 0)
                })

            # Lo cargado y lo pagado de esta reserva (mismos datos que usan el
            # KPI "Ingresado" y el desglose por forma de pago) se reparte entre
            # sus productos, para que este desglose también cuadre con ellos.
            cargos_reserva = [cg for cg in cargos if cg.idMovReferencia == reserva.idCitaCliente]
            solicitado_reserva = (
                sum(float(cg.monto or 0) for cg in cargos_reserva)
                if cargos_reserva else float(reserva.costo or 0)
            )
            pagado_reserva = sum(
                float(ap.montoAplicado or 0)
                for cg in cargos_reserva
                for ap in (cg.aplicaciones_recibidas or [])
            )
            reparto = _atribuir_por_producto(items_reserva, solicitado_reserva, pagado_reserva, nombre_producto_cita)
            for nombre_producto, montos in reparto.items():
                desglose_productos[nombre_producto]['solicitado'] += montos['solicitado']
                desglose_productos[nombre_producto]['pagado'] += montos['pagado']

        total_cita = sum(float(cargo.monto or 0) for cargo in cargos) if cargos else sum(float(r.costo or 0) for r in reservas)
        saldo_pendiente = sum(float(cargo.saldo or 0) for cargo in cargos) if cargos else total_cita
        pagado_cita = round(sum(
            float(aplicacion.montoAplicado or 0)
            for cargo in cargos
            for aplicacion in (cargo.aplicaciones_recibidas or [])
        ), 2)

        es_realizada = bool(c.idEstatus and c.idEstatus == const.REALIZADA)

        # Cita que ya pasó de horario pero aún tiene clientes en Reservada/Confirmada:
        # el staff debe cerrarla (Realizada / No Asistencia).
        pendiente_cerrar = bool(c.pendiente_de_cerrar)
        if pendiente_cerrar:
            total_pendientes_cerrar += 1

        # El ingreso y el desglose por forma de pago se cuentan en cuanto el
        # pago se aplica (movAplica), sin importar si la cita ya se marcó
        # como Realizada: si el cliente ya pagó, ese dinero ya entró.
        if pagado_cita:
            total_ingresado_dia += Decimal(str(pagado_cita))

        for cargo in cargos:
            for aplicacion in (cargo.aplicaciones_recibidas or []):
                abono = aplicacion.abono
                metodo_nombre = abono.metodo.nombre if (abono and abono.metodo) else 'Sin especificar'
                desglose_pagos[metodo_nombre] += float(aplicacion.montoAplicado)

        nombres_clientes = list(dict.fromkeys(
            reserva.cliente.nombreCliente
            for reserva in reservas
            if reserva.cliente and reserva.cliente.nombreCliente
        ))
        nombres_para = list(dict.fromkeys(
            reserva.para.strip()
            for reserva in reservas
            if reserva.para and reserva.para.strip()
        ))
        reservas_vencida = [
            {
                'para': reserva.nombre_asistente or 'Sin nombre',
                'estatus': reserva.estatus.nombre if reserva.estatus else 'Sin estatus'
            }
            for reserva in c.reservas
        ] if nombre_estatus.lower() == 'vencida' else []
        detalle_citas.append({
            'idCita': c.idCita,
            'fecha': c.fechaCita.strftime('%d/%m/%Y') if c.fechaCita else '',
            'hora': c.horaCita.strftime('%H:%M') if c.horaCita else '',
            'cliente': ', '.join(nombres_clientes) or (
                'Sin clientes' if nombre_estatus == 'Vencida'
                else (c.producto.nombre if c.producto else 'Espacio disponible')
            ),
            'para': ', '.join(nombres_para) or None,
            'reservasVencida': reservas_vencida,
            'estatus': nombre_estatus,
            'color': color_estatus,
            'esRealizada': es_realizada,
            'pendienteCerrar': pendiente_cerrar,
            'productos': productos_detalle,
            'total': total_cita,
            'saldo': saldo_pendiente,
            'pagado': pagado_cita
        })

    return {
        'fecha': fecha,
        'periodo': periodo,
        'fechaInicio': fecha_inicio,
        'fechaFin': fecha_fin,
        'totalCitas': len(citas),
        'conteoEstatus': dict(conteo_estatus),
        'coloresEstatus': colores_estatus,
        'totalPendientesCerrar': total_pendientes_cerrar,
        'totalIngresadoDia': float(round(total_ingresado_dia, 2)),
        'desglosePagos': {k: round(v, 2) for k, v in desglose_pagos.items()},
        'desgloseProductos': {
            k: {
                'solicitado': round(v['solicitado'], 2),
                'pagado': round(v['pagado'], 2)
            }
            for k, v in desglose_productos.items()
        },
        'citas': detalle_citas
    }


@admin_bp.route('/admin/dashboard_data')
def dashboard_data():
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        return jsonify({'success': False, 'message': 'No autenticado'}), 401

    tipo = session.get('tipoUsuario')
    if tipo not in ('admin', 'staff', 'asistente', 'superuser'):
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403

    id_empresa = session.get('idEmpresa')
    id_usuario_sesion = session.get('idUsuario')

    fecha_str = request.args.get('fecha')
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else datetime.now().date()
    except ValueError:
        fecha = datetime.now().date()

    # Un 'staff' nunca puede consultar la información de otro staff, sin importar
    # qué idUsuario venga en la URL.
    if tipo == 'staff':
        id_staff = id_usuario_sesion
    else:
        id_staff = request.args.get('idUsuario', type=int) or id_usuario_sesion

    periodo = _normalizar_periodo(request.args.get('periodo'))

    datos = _obtener_datos_dashboard(id_empresa, id_staff, fecha, periodo)

    return jsonify({
        'success': True,
        'fecha': datos['fecha'].strftime('%Y-%m-%d'),
        'periodo': datos['periodo'],
        'fechaInicio': datos['fechaInicio'].strftime('%Y-%m-%d'),
        'fechaFin': datos['fechaFin'].strftime('%Y-%m-%d'),
        'totalCitas': datos['totalCitas'],
        'conteoEstatus': datos['conteoEstatus'],
        'coloresEstatus': datos['coloresEstatus'],
        'totalPendientesCerrar': datos['totalPendientesCerrar'],
        'totalIngresadoDia': datos['totalIngresadoDia'],
        'desglosePagos': datos['desglosePagos'],
        'desgloseProductos': datos['desgloseProductos'],
        'citas': datos['citas']
    })


@admin_bp.route('/admin/dashboard_enviar_whatsapp', methods=['POST'])
def dashboard_enviar_whatsapp():
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        return jsonify({'success': False, 'message': 'No autenticado'}), 401

    tipo = session.get('tipoUsuario')
    if tipo not in ('admin', 'staff', 'asistente', 'superuser'):
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403

    id_empresa = session.get('idEmpresa')
    id_usuario_sesion = session.get('idUsuario')

    payload = request.get_json(silent=True) or request.form

    fecha_str = payload.get('fecha')
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else datetime.now().date()
    except ValueError:
        fecha = datetime.now().date()

    if tipo == 'staff':
        id_staff = id_usuario_sesion
    else:
        id_staff_raw = payload.get('idUsuario')
        try:
            id_staff = int(id_staff_raw) if id_staff_raw else id_usuario_sesion
        except (TypeError, ValueError):
            id_staff = id_usuario_sesion

    staff = Usuario.query.get(id_staff)
    if not staff:
        return jsonify({'success': False, 'message': 'Especialista no encontrado'}), 404

    if not staff.telefono:
        return jsonify({'success': False, 'message': f'{staff.alias or staff.nombreUsuario} no tiene un teléfono registrado para WhatsApp.'}), 400

    periodo = _normalizar_periodo(payload.get('periodo'))
    etiquetas = _ETIQUETAS_PERIODO[periodo]

    datos = _obtener_datos_dashboard(id_empresa, id_staff, fecha, periodo)

    fecha_legible = datos['fecha'].strftime('%d/%m/%Y')
    staff_nombre = staff.alias or staff.nombreUsuario

    if periodo == 'dia':
        linea_fecha = f"Fecha: {fecha_legible}"
    else:
        linea_fecha = (
            f"Periodo: {datos['fechaInicio'].strftime('%d/%m/%Y')} "
            f"al {datos['fechaFin'].strftime('%d/%m/%Y')}"
        )

    lineas = [
        f"*{etiquetas['titulo']} - CitaNet*",
        "",
        f"Especialista: {staff_nombre}",
        linea_fecha,
        "",
        f"Total de citas: {datos['totalCitas']}",
    ]

    for nombre_estatus, cantidad in datos['conteoEstatus'].items():
        lineas.append(f"  - {nombre_estatus}: {cantidad}")
    if datos['totalPendientesCerrar']:
        lineas.append(f"  ⚠ Pendientes de cerrar: {datos['totalPendientesCerrar']}")

    lineas.append("")
    lineas.append(f"*{etiquetas['ingreso']}: ${datos['totalIngresadoDia']:,.2f}*")

    if datos['desglosePagos']:
        lineas.append("")
        lineas.append("*Desglose por forma de pago:*")
        for metodo_nombre, monto in datos['desglosePagos'].items():
            lineas.append(f"  - {metodo_nombre}: ${monto:,.2f}")

    if not datos['citas']:
        lineas.append("")
        lineas.append(f"No hay citas registradas para {etiquetas['vacio']}.")
    elif periodo == 'dia':
        # El detalle cita por cita solo se envía en el resumen diario: en una
        # semana o un mes el mensaje excedería el límite de WhatsApp.
        lineas.append("")
        lineas.append("*Detalle de citas:*")
        for c in datos['citas']:
            lineas.append("")
            lineas.append(f"{c['hora']} - {c['cliente']} ({c['estatus']})")
            for p in c['productos']:
                lineas.append(f"   • {p['nombre']} x{p['cantidad']}: ${p['subtotal']:,.2f}")
            lineas.append(f"   Total: ${c['total']:,.2f} | Pagado: ${c['pagado']:,.2f}")

    mensaje = "\n".join(lineas)

    enviado = enviar_whatsapp(
        numero=staff.telefono,
        mensaje=mensaje,
        idEmpresaEnvia=id_empresa
    )

    if enviado:
        return jsonify({'success': True, 'message': f'Resumen enviado por WhatsApp a {staff_nombre}.'})
    else:
        return jsonify({'success': False, 'message': 'No se pudo enviar el mensaje de WhatsApp.'}), 500


# ==========================================
# GRÁFICA ANUAL DE INGRESOS POR PRODUCTO / SERVICIO
# ==========================================
# Se abre desde el botón "Gráfica anual" del desglose por producto del
# dashboard. Muestra, mes a mes, lo cobrado por cada producto/servicio del
# especialista en el año elegido, agrupado por la fecha de la cita. El total
# mensual es el mismo "Ingresado" del dashboard (pagos aplicados a los cargos
# de las citas); lo que no quedó ligado a un producto se muestra aparte como
# "Sin desglose por producto".
@admin_bp.route('/admin/dashboard_ingresos')
def dashboard_ingresos():
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        flash('Por favor, inicia sesión primero.', 'danger')
        return redirect(url_for('login'))

    tipo = session.get('tipoUsuario')
    if tipo not in ('admin', 'staff', 'asistente', 'superuser'):
        abort(403)

    id_empresa = session.get('idEmpresa')
    id_usuario_sesion = session.get('idUsuario')

    empresa = Empresa.query.get_or_404(id_empresa)
    usuario_sesion = Usuario.query.get(id_usuario_sesion)
    nombre_usuario_sesion = (usuario_sesion.alias or usuario_sesion.nombreUsuario) if usuario_sesion else ''

    staff_lista = []
    if tipo == 'staff':
        id_staff_seleccionado = id_usuario_sesion
    else:
        staff_lista = Usuario.query.filter_by(
            idEmpresa=id_empresa,
            tipoUsuario='staff'
        ).order_by(Usuario.nombreUsuario).all()

        id_staff_seleccionado = request.args.get('idUsuario', type=int) or id_usuario_sesion

    anio = request.args.get('anio', type=int) or datetime.now().year

    return render_template(
        'dashboard_ingresos.html',
        empresa=empresa,
        tipo_usuario=tipo,
        staff_lista=staff_lista,
        id_staff_seleccionado=id_staff_seleccionado,
        nombre_usuario_sesion=nombre_usuario_sesion,
        anio_inicial=anio
    )


@admin_bp.route('/admin/dashboard_ingresos_data')
def dashboard_ingresos_data():
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        return jsonify({'success': False, 'message': 'No autenticado'}), 401

    tipo = session.get('tipoUsuario')
    if tipo not in ('admin', 'staff', 'asistente', 'superuser'):
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403

    id_empresa = session.get('idEmpresa')
    id_usuario_sesion = session.get('idUsuario')

    # Un 'staff' nunca puede consultar la información de otro staff.
    if tipo == 'staff':
        id_staff = id_usuario_sesion
    else:
        id_staff = request.args.get('idUsuario', type=int) or id_usuario_sesion

    anio_actual = datetime.now().year
    anio = request.args.get('anio', type=int) or anio_actual
    if anio < 2000 or anio > 2100:
        anio = anio_actual

    # Misma base de citas que el desglose del dashboard: cita que no esté
    # "Creada" ni absorbida por una cita maestra, y solo reservas que ocupan
    # lugar (CitaCliente.ESTATUS_OCUPAN_LUGAR).
    estatus_reserva = aliased(EstatusCita)
    filtros_cita = (
        Cita.idEmpresa == id_empresa,
        Cita.idUsuario == id_staff,
        Cita.fechaCita >= date(anio, 1, 1),
        Cita.fechaCita <= date(anio, 12, 31),
        func.lower(EstatusCita.nombre) != 'creada',
        Cita.idCitaMaestra.is_(None),
        estatus_reserva.nombre.in_(CitaCliente.ESTATUS_OCUPAN_LUGAR)
    )

    def consulta_reservas(*columnas):
        return db.session.query(*columnas).select_from(Cita).join(
            EstatusCita, Cita.idEstatus == EstatusCita.idEstatus
        ).join(
            CitaCliente, CitaCliente.idCita == Cita.idCita
        ).join(
            estatus_reserva, CitaCliente.idEstatus == estatus_reserva.idEstatus
        )

    # 1) Reservas del año: mes de la cita y producto de la cita.
    filas_reservas = consulta_reservas(
        CitaCliente.idCitaCliente,
        extract('month', Cita.fechaCita),
        Cita.idProducto
    ).filter(*filtros_cita).all()

    # 2) Lo realmente pagado por reserva: pagos aplicados a su cargo, igual
    #    que el KPI "Ingresado" del dashboard.
    filas_pagado = consulta_reservas(
        CitaCliente.idCitaCliente,
        func.coalesce(func.sum(movAplica.montoAplicado), 0)
    ).join(
        movCuenta, movCuenta.idMovReferencia == CitaCliente.idCitaCliente
    ).join(
        tipoMovimiento, movCuenta.idtipoMovimiento == tipoMovimiento.idtipoMovimiento
    ).join(
        movAplica, movAplica.idmovCargo == movCuenta.idMovimiento
    ).filter(
        *filtros_cita,
        movCuenta.idEmpresa == id_empresa,
        movCuenta.idtipoMovimiento == const.MOV_CITA,
        tipoMovimiento.naturaleza == 'C'
    ).group_by(CitaCliente.idCitaCliente).all()

    # 3) Productos/servicios de cada reserva.
    filas_items = consulta_reservas(
        CitaProducto.idCitaCliente,
        Producto.nombre,
        CitaProducto.cantidad,
        CitaProducto.precioCobrado,
        CitaProducto.montoPagado
    ).join(
        CitaProducto, CitaProducto.idCitaCliente == CitaCliente.idCitaCliente
    ).join(
        Producto, CitaProducto.idProducto == Producto.idProducto
    ).filter(*filtros_cita).all()

    ids_producto_cita = {idp for _, _, idp in filas_reservas if idp}
    nombres_producto_cita = {}
    if ids_producto_cita:
        nombres_producto_cita = dict(
            db.session.query(Producto.idProducto, Producto.nombre)
            .filter(Producto.idProducto.in_(ids_producto_cita)).all()
        )

    pagado_por_reserva = {rid: float(monto or 0) for rid, monto in filas_pagado}
    items_por_reserva = defaultdict(list)
    for rid, nombre, cantidad, precio, monto_pagado in filas_items:
        items_por_reserva[rid].append({
            'nombre': nombre,
            'cantidad': cantidad,
            'subtotal': float(precio or 0) * (cantidad or 0),
            'pagado': float(monto_pagado or 0)
        })

    # nombre de producto -> 12 montos pagados (enero a diciembre)
    por_producto = defaultdict(lambda: [0.0] * 12)
    for rid, mes, id_producto_cita in filas_reservas:
        items = items_por_reserva.get(rid, [])
        reparto = _atribuir_por_producto(
            items,
            sum(it['subtotal'] for it in items),
            pagado_por_reserva.get(rid, 0.0),
            nombres_producto_cita.get(id_producto_cita)
        )
        for nombre, montos in reparto.items():
            por_producto[nombre][int(mes) - 1] += montos['pagado']

    productos = sorted(
        (
            {
                'nombre': nombre,
                'pagado': [round(v, 2) for v in montos],
                'total': round(sum(montos), 2),
                'sinDesglose': nombre == SIN_DESGLOSE_PRODUCTO
            }
            for nombre, montos in por_producto.items()
        ),
        key=lambda p: (p['sinDesglose'], -p['total'], p['nombre'].lower())
    )

    # Años que el selector ofrece: desde la primera cita del especialista hasta
    # el año actual (siempre incluye el año consultado).
    primera, ultima = db.session.query(
        func.min(Cita.fechaCita), func.max(Cita.fechaCita)
    ).filter(
        Cita.idEmpresa == id_empresa,
        Cita.idUsuario == id_staff
    ).one()
    primer_anio = primera.year if primera else anio_actual
    ultimo_anio = max(ultima.year if ultima else anio_actual, anio_actual)
    anios = sorted(set(range(primer_anio, ultimo_anio + 1)) | {anio}, reverse=True)

    return jsonify({
        'success': True,
        'anio': anio,
        'aniosDisponibles': anios,
        'productos': productos
    })


# ==========================================
# PUNTOS DE LEALTAD POR ESPECIALISTA
# ==========================================
# Punto de entrada único: si es admin o asistente, ve el listado de su staff y
# entra a configurar a cualquiera; si es staff, entra directo a su propia
# configuración.
@admin_bp.route('/admin/config_puntos_staff')
def config_puntos_staff():
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        flash('Por favor, inicia sesión primero.', 'danger')
        return redirect(url_for('login'))

    tipo = session.get('tipoUsuario')
    if tipo not in ('admin', 'staff', 'asistente'):
        abort(403)

    if tipo == 'staff':
        return redirect(url_for('admin.config_puntos_staff_detalle', idUsuario=session.get('idUsuario')))

    id_empresa = session.get('idEmpresa')
    empresa = Empresa.query.get_or_404(id_empresa)

    staff_lista = Usuario.query.filter_by(
        idEmpresa=id_empresa,
        tipoUsuario='staff'
    ).order_by(Usuario.nombreUsuario).all()

    return render_template(
        'config_puntos_staff_lista.html',
        empresa=empresa,
        staff_lista=staff_lista
    )


@admin_bp.route('/admin/config_puntos_staff/<int:idUsuario>', methods=['GET', 'POST'])
def config_puntos_staff_detalle(idUsuario):
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        flash('Por favor, inicia sesión primero.', 'danger')
        return redirect(url_for('login'))

    tipo = session.get('tipoUsuario')
    if tipo not in ('admin', 'staff', 'asistente'):
        abort(403)

    id_empresa = session.get('idEmpresa')
    id_usuario_sesion = session.get('idUsuario')

    # Un staff solo puede configurarse a sí mismo, sin importar qué idUsuario
    # venga en la URL.
    if tipo == 'staff' and idUsuario != id_usuario_sesion:
        abort(403)

    staff = Usuario.query.filter_by(idUsuario=idUsuario, idEmpresa=id_empresa, tipoUsuario='staff').first()
    if not staff:
        abort(404)

    empresa = Empresa.query.get_or_404(id_empresa)

    if request.method == 'POST':
        acepta = request.form.get('aceptaPuntosLealtad') == 'on'
        tipo_puntos = request.form.get('tipoPuntosLealtad')
        valor_raw = request.form.get('valorPuntosLealtad')

        if acepta:
            if tipo_puntos not in ('fijo', 'porcentaje'):
                flash('Selecciona si los puntos son de valor fijo o porcentaje.', 'danger')
                return redirect(url_for('admin.config_puntos_staff_detalle', idUsuario=idUsuario))
            try:
                valor = Decimal(str(valor_raw))
                if valor < 0:
                    raise InvalidOperation
                if tipo_puntos == 'porcentaje' and valor > 100:
                    flash('El porcentaje no puede ser mayor a 100.', 'danger')
                    return redirect(url_for('admin.config_puntos_staff_detalle', idUsuario=idUsuario))
            except (InvalidOperation, TypeError, ValueError):
                flash('El valor de los puntos debe ser un número válido.', 'danger')
                return redirect(url_for('admin.config_puntos_staff_detalle', idUsuario=idUsuario))

            staff.aceptaPuntosLealtad = True
            staff.tipoPuntosLealtad = tipo_puntos
            staff.valorPuntosLealtad = valor
        else:
            staff.aceptaPuntosLealtad = False
            staff.tipoPuntosLealtad = None
            staff.valorPuntosLealtad = 0

        try:
            db.session.commit()
            flash('Configuración de puntos de lealtad actualizada.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al guardar: {str(e)}', 'danger')

        return redirect(url_for('admin.config_puntos_staff_detalle', idUsuario=idUsuario))

    return render_template(
        'config_puntos_staff_detalle.html',
        empresa=empresa,
        staff=staff,
        tipo_usuario=tipo,
        modo_acumulacion_activo=(empresa.modoAcumulacionPuntos == 'staff')
    )


# ==========================================
# CONFIGURACIÓN DE ESPECIALISTAS (pantalla unificada)
# ==========================================
# Punto de entrada único para las configuraciones por especialista (puntos de
# lealtad, obligar selección de servicio, y las que se agreguen después).
# Si es admin o asistente, ve el listado completo de su staff; si es staff,
# ve únicamente su propio registro. A diferencia de config_puntos_staff, aquí
# nunca se redirige directo al detalle: siempre se muestra esta lista primero
# y desde ahí se elige el botón de configuración deseado.
@admin_bp.route('/admin/config_especialistas')
def config_especialistas():
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        flash('Por favor, inicia sesión primero.', 'danger')
        return redirect(url_for('login'))

    tipo = session.get('tipoUsuario')
    if tipo not in ('admin', 'staff', 'asistente'):
        abort(403)

    id_empresa = session.get('idEmpresa')
    empresa = Empresa.query.get_or_404(id_empresa)

    if tipo == 'staff':
        staff_lista = Usuario.query.filter_by(
            idUsuario=session.get('idUsuario'),
            idEmpresa=id_empresa,
            tipoUsuario='staff'
        ).all()
    else:
        staff_lista = Usuario.query.filter_by(
            idEmpresa=id_empresa,
            tipoUsuario='staff'
        ).order_by(Usuario.nombreUsuario).all()

    return render_template(
        'config_especialistas_lista.html',
        empresa=empresa,
        staff_lista=staff_lista,
        tipo_usuario=tipo
    )


@admin_bp.route('/admin/config_servicio_obligatorio/<int:idUsuario>', methods=['GET', 'POST'])
def config_servicio_obligatorio_detalle(idUsuario):
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        flash('Por favor, inicia sesión primero.', 'danger')
        return redirect(url_for('login'))

    tipo = session.get('tipoUsuario')
    if tipo not in ('admin', 'staff', 'asistente'):
        abort(403)

    id_empresa = session.get('idEmpresa')
    id_usuario_sesion = session.get('idUsuario')

    # Un staff solo puede configurarse a sí mismo, sin importar qué idUsuario
    # venga en la URL.
    if tipo == 'staff' and idUsuario != id_usuario_sesion:
        abort(403)

    staff = Usuario.query.filter_by(idUsuario=idUsuario, idEmpresa=id_empresa, tipoUsuario='staff').first()
    if not staff:
        abort(404)

    empresa = Empresa.query.get_or_404(id_empresa)

    if request.method == 'POST':
        staff.obligaSeleccionServicio = request.form.get('obligaSeleccionServicio') == 'on'

        try:
            db.session.commit()
            flash('Configuración actualizada.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al guardar: {str(e)}', 'danger')

        return redirect(url_for('admin.config_servicio_obligatorio_detalle', idUsuario=idUsuario))

    return render_template(
        'config_servicio_obligatorio_detalle.html',
        empresa=empresa,
        staff=staff,
        tipo_usuario=tipo
    )


# ==========================================
# COMUNICADOS (mensajes/tips/avisos/recordatorios de menú)
# ==========================================
# Solo admin (limitado a su propia empresa) o superuser (limitado a la empresa 1,
# la maestra de CitaNet) pueden crear/editar comunicados. El superuser puede
# además dejar idEmpresa en blanco para publicar un comunicado global a todo el
# SaaS. La pantalla de gestión solo se enlaza desde el menú de admin/superuser.

def _validar_acceso_comunicados():
    """Devuelve (tipo, id_empresa_sesion) si el usuario en sesión puede
    administrar comunicados, o hace abort(403)/redirect si no puede."""
    if 'idUsuario' not in session or 'idEmpresa' not in session:
        flash('Por favor, inicia sesión primero.', 'danger')
        return redirect(url_for('login'))

    tipo = session.get('tipoUsuario')
    if tipo not in ('admin', 'superuser'):
        abort(403)

    return tipo, session.get('idEmpresa')


@admin_bp.route('/admin/comunicados')
def comunicados():
    acceso = _validar_acceso_comunicados()
    if not isinstance(acceso, tuple):
        return acceso
    tipo, id_empresa = acceso

    # Siempre se administran los comunicados de la propia empresa del usuario en
    # sesión (si esa empresa es la 1, esos comunicados se ven en todo el SaaS,
    # pero se siguen gestionando/listando aquí igual).
    comunicados = Comunicado.query.filter(
        Comunicado.idEmpresa == id_empresa
    ).order_by(Comunicado.fechaCreacion.desc()).all()

    return render_template('comunicados_lista.html', comunicados=comunicados, tipo_usuario=tipo, es_empresa_global=(id_empresa == 1))


@admin_bp.route('/admin/comunicados/gestion', defaults={'idComunicado': None}, methods=['GET', 'POST'])
@admin_bp.route('/admin/comunicados/gestion/<int:idComunicado>', methods=['GET', 'POST'])
def gestion_comunicado(idComunicado):
    acceso = _validar_acceso_comunicados()
    if not isinstance(acceso, tuple):
        return acceso
    tipo, id_empresa_sesion = acceso

    comunicado = Comunicado.query.get(idComunicado) if idComunicado else None

    # Un usuario solo puede tocar comunicados de su propia empresa
    if comunicado and comunicado.idEmpresa != id_empresa_sesion:
        abort(403)

    objetivos = ['cliente', 'usuario']
    #if tipo == 'superuser':
    #    objetivos.append('empresa')

    if request.method == 'POST':
        objetivo = request.form.get('objetivo')
        sub_objetivo_raw = (request.form.get('subObjetivo') or '').strip()
        tipo_comunicado = request.form.get('tipo')
        prioridad_raw = request.form.get('prioridad')
        mensaje = (request.form.get('mensaje') or '').strip()
        fecha_inicio_raw = request.form.get('fechaInicio')
        fecha_final_raw = request.form.get('fechaFinal')
        activo = True if request.form.get('activo') else False

        if objetivo not in ('cliente', 'usuario', 'empresa'):
            flash('Selecciona a quién va dirigido el comunicado.', 'danger')
            return redirect(url_for('admin.gestion_comunicado', idComunicado=idComunicado))

        # subObjetivo solo tiene sentido cuando objetivo == 'usuario'
        sub_objetivo = None
        if objetivo == 'usuario' and sub_objetivo_raw:
            if sub_objetivo_raw not in ('admin', 'staff', 'asistente'):
                flash('El tipo de usuario específico no es válido.', 'danger')
                return redirect(url_for('admin.gestion_comunicado', idComunicado=idComunicado))
            sub_objetivo = sub_objetivo_raw

        if tipo_comunicado not in ('recordatorio', 'aviso'):
            flash('Selecciona el tipo de comunicado.', 'danger')
            return redirect(url_for('admin.gestion_comunicado', idComunicado=idComunicado))

        try:
            prioridad = int(prioridad_raw)
            if prioridad not in Comunicado.NIVELES_PRIORIDAD:
                raise ValueError
        except (TypeError, ValueError):
            flash('La prioridad debe ser un valor entre 1 y 5.', 'danger')
            return redirect(url_for('admin.gestion_comunicado', idComunicado=idComunicado))

        if not mensaje:
            flash('El mensaje no puede estar vacío.', 'danger')
            return redirect(url_for('admin.gestion_comunicado', idComunicado=idComunicado))

        try:
            fecha_inicio = datetime.strptime(fecha_inicio_raw, '%Y-%m-%d').date()
            fecha_final = datetime.strptime(fecha_final_raw, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            flash('Las fechas de vigencia no son válidas.', 'danger')
            return redirect(url_for('admin.gestion_comunicado', idComunicado=idComunicado))

        if fecha_final < fecha_inicio:
            flash('La fecha final no puede ser anterior a la fecha de inicio.', 'danger')
            return redirect(url_for('admin.gestion_comunicado', idComunicado=idComunicado))

        if comunicado:
            comunicado.objetivo = objetivo
            comunicado.subObjetivo = sub_objetivo
            comunicado.tipo = tipo_comunicado
            comunicado.prioridad = prioridad
            comunicado.mensaje = mensaje
            comunicado.fechaInicio = fecha_inicio
            comunicado.fechaFinal = fecha_final
            comunicado.activo = activo
            flash('Comunicado actualizado correctamente.', 'success')
        else:
            comunicado = Comunicado(
                idEmpresa=id_empresa_sesion,  # siempre la empresa de quien lo crea
                objetivo=objetivo,
                subObjetivo=sub_objetivo,
                tipo=tipo_comunicado,
                prioridad=prioridad,
                mensaje=mensaje,
                fechaInicio=fecha_inicio,
                fechaFinal=fecha_final,
                activo=activo,
                idUsuario=session.get('idUsuario'),
            )
            db.session.add(comunicado)
            flash('Comunicado creado correctamente.', 'success')

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'Error al guardar en la base de datos: {str(e)}', 'danger')
            return redirect(url_for('admin.gestion_comunicado', idComunicado=idComunicado))

        return redirect(url_for('admin.comunicados'))

    return render_template(
        'comunicado_gestion.html',
        comunicado=comunicado,
        objetivos=objetivos,
        tipo_usuario=tipo,
        es_empresa_global=(id_empresa_sesion == 1),
        niveles_prioridad=Comunicado.NIVELES_PRIORIDAD,
    )


@admin_bp.route('/admin/comunicados/toggle/<int:idComunicado>', methods=['POST'])
def toggle_comunicado(idComunicado):
    """Endpoint AJAX para activar/desactivar un comunicado desde la tabla sin recargar la página."""
    acceso = _validar_acceso_comunicados()
    if not isinstance(acceso, tuple):
        return jsonify({'status': 'error', 'message': 'No autorizado'}), 403
    tipo, id_empresa_sesion = acceso

    comunicado = Comunicado.query.get_or_404(idComunicado)
    if comunicado.idEmpresa != id_empresa_sesion:
        return jsonify({'status': 'error', 'message': 'No autorizado'}), 403

    comunicado.activo = not comunicado.activo
    db.session.commit()
    return jsonify({'status': 'success', 'nuevo_estado': comunicado.activo})


@admin_bp.route('/admin/comunicados/pendientes')
def comunicados_pendientes():

    # 1. Validar que exista al menos una sesión válida (sea usuario del sistema o cliente)
    id_usuario   = session.get('idUsuario')
    id_empresa   = session.get('idEmpresa')
    id_cliente   = session.get('idCliente')
    tipo_usuario = session.get('tipoUsuario')


    #logger.info(f"Comunicados pendientes: id_usuario={id_usuario}, id_empresa={id_empresa}, id_cliente={id_cliente}, tipo_usuario={tipo_usuario}")

    if not id_empresa or (not id_usuario and not id_cliente):
        return jsonify([])

    hoy = datetime.now().date()

    # 2. Definir dinámicamente el tipo de lector y el ID a consultar/filtrar
    if id_cliente:
        lector_id = id_cliente
        objetivos = ['cliente']
    else:
        lector_id = id_usuario
        objetivos = ['usuario']
        #if tipo_usuario in ('admin'):
        #    objetivos.append('empresa')

    # 3. Query de ya_leidos dependiendo de si es cliente o usuario
    if id_cliente:
        ya_leidos = db.session.query(ComunicadoLeido.idComunicado).filter(
            ComunicadoLeido.tipoLector == 'cliente',
            ComunicadoLeido.idCliente == lector_id
        )
    else:
        ya_leidos = db.session.query(ComunicadoLeido.idComunicado).filter(
            ComunicadoLeido.tipoLector == 'usuario',
            ComunicadoLeido.idUsuario == lector_id
        )

    #logger.info(f"Comunicados pendientes: objetivos={objetivos}, ya_leidos={list(ya_leidos)}")

    pendientes = Comunicado.query.filter(
        Comunicado.activo.is_(True),
        Comunicado.objetivo.in_(objetivos),
        Comunicado.fechaInicio <= hoy,
        Comunicado.fechaFinal >= hoy,
        db.or_(Comunicado.idEmpresa == id_empresa, Comunicado.idEmpresa == 1),
        db.or_(Comunicado.subObjetivo.is_(None), Comunicado.subObjetivo == tipo_usuario),
        ~Comunicado.idComunicado.in_(ya_leidos)
    ).order_by(Comunicado.prioridad.desc(), Comunicado.fechaCreacion.desc()).all()

    

    return jsonify([{
        'idComunicado': c.idComunicado,
        'tipo': c.tipo,
        'prioridad': c.prioridad,
        'nombrePrioridad': c.nombre_prioridad(),
        'mensaje': c.mensaje,
    } for c in pendientes])


@admin_bp.route('/admin/comunicados/marcar_leido/<int:idComunicado>', methods=['POST'])
def marcar_comunicado_leido(idComunicado):
    id_usuario = session.get('idUsuario')
    id_cliente = session.get('idCliente')

    if not id_usuario and not id_cliente:
        return jsonify({'status': 'error', 'message': 'No autorizado'}), 403

    # Determinar si el lector es cliente o usuario
    if id_cliente:
        tipo_lector = 'cliente'
        filtro_lector = ComunicadoLeido.idCliente == id_cliente
    else:
        tipo_lector = 'usuario'
        filtro_lector = ComunicadoLeido.idUsuario == id_usuario

    ya_existe = ComunicadoLeido.query.filter(
        ComunicadoLeido.idComunicado == idComunicado if 'idComunicado' in locals() else ComunicadoLeido.idComunicado == idComunicado,
        ComunicadoLeido.tipoLector == tipo_lector,
        filtro_lector
    ).first()

    if not ya_existe:
        lectura = ComunicadoLeido(
            idComunicado=idComunicado,
            tipoLector=tipo_lector,
            idUsuario=id_usuario,
            idCliente=id_cliente
        )
        db.session.add(lectura)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'status': 'error', 'message': str(e)}), 500

    return jsonify({'status': 'success'})
