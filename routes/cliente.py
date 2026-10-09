from flask      import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from correo     import enviar_correo
from routes.pagos import calcular_saldo
from sms_mx     import enviar_codigo_sms
from datetime   import datetime
from modelos    import Empresa, Cliente, ClienteEmpresa, ClienteStaff, Usuario, db, CodigoTelefono, movCuenta, movAplica, tipoMovimiento, Cita, CitaCliente, CitaProducto, EstatusCita, ColorEstatusCitaEmpresa, Pais, Config, Producto, CompraPublicidad
from constantes import const
from decimal    import Decimal

from sqlalchemy.orm import joinedload
import uuid
import logging
import config
import re


logger = logging.getLogger(__name__)

cliente_bp = Blueprint("cliente", __name__)

@cliente_bp.route('/cliente_session/<int:id_cliente>')
def cliente_session(id_cliente):
    id_empresa = session.get('idEmpresa')

    if id_empresa:
        relacion = ClienteEmpresa.query.filter_by(idCliente=id_cliente, idEmpresa=id_empresa).first()
        if not relacion:
            return jsonify({"status": "error", "msg": "Cliente no encontrado en esta empresa"}), 404

    session.pop('idCliente', None)
    session['idClientegestionado'] = id_cliente
    return "OK", 200

@cliente_bp.route("/cliente/login", methods=["GET"])
def login():
    
    if not session.get("url_origen"):
        session["url_origen"] = request.referrer
        
    if session.get("idCliente"):
        if session.get("idEmpresa"):
            return redirect(url_for('cliente.menu_cliente'))
        return redirect(url_for('cliente.mis_empresas'))

    id_empresa = session.get("idEmpresa")
    empresa_nombre = "CitaNet"
    
    if id_empresa:
        empresa = Empresa.query.get(id_empresa)
        if empresa:
            empresa_nombre = empresa.razonSocial
            
    return render_template("login_cliente.html", 
                           idEmpresa=id_empresa, 
                           empresa=empresa_nombre,
                           paises=Pais.query.filter_by(activo=True).order_by(Pais.nombre).all())
    
    
@cliente_bp.route('/logout/cliente')
def logout_cliente():
    
    url_retorno = session.get("url_origen")
    
    if url_retorno and "citanet" not in url_retorno:
        session.clear()
        return redirect(url_retorno)
        
    id_empresa = session.get("idEmpresa")
    if not id_empresa:
         return redirect(config.URL_BASE)
    
    empresa = Empresa.query.get(id_empresa) if id_empresa else None
    session.clear()
    
    return render_template('logout_cliente.html', 
                           idEmpresa=id_empresa, 
                           empresa=empresa.razonSocial)
    
# ============================================================
# VALIDAR CÓDIGO
# ============================================================
@cliente_bp.route("/validar_codigo_global", methods=["POST"])
def validar_codigo_global():
    data             = request.get_json()
    telefono         = data.get("telefono")
    codigo_ingresado = data.get("codigo")
    id_pais          = data.get("idPais")
    
    #logger.info(f"Validando código para teléfono: {telefono}, codigo_ingresado = {codigo_ingresado}")
    
    if not all([telefono, codigo_ingresado]):
        return jsonify({"error": "Datos incompletos"}), 400

    registro_codigo = CodigoTelefono.query.filter(
        CodigoTelefono.telefono == telefono,
        CodigoTelefono.expiracion > datetime.now()
    ).order_by(CodigoTelefono.expiracion.desc()).first()
    
    if not registro_codigo or registro_codigo.codigo != codigo_ingresado:
        return jsonify({"error": "Código incorrecto o expirado"}), 401

    cliente_query = Cliente.query.filter_by(telefono=telefono)
    if str(id_pais or "").isdigit():
        cliente_query = cliente_query.filter_by(idPais=int(id_pais))
    cliente = cliente_query.first()

    if not cliente:
        return jsonify({"error": "Cliente no encontrado"}), 401

    # Guardamos en sesión como ENTEROS
    session["idCliente"]     = cliente.idCliente
    session["nombreCliente"] = cliente.nombreCliente
    session["telefono"]      = cliente.telefono
    
    # Limpieza de código usado
    db.session.delete(registro_codigo)
    db.session.commit()

    # --- LÓGICA DE REDIRECCIÓN ---
    # Si ya existe idEmpresa en la sesión, mandamos al menú directo.
    # Si no, mandamos a 'mis_empresas' para que elija una.
    if session.get("idEmpresa"):
        url_destino = url_for('cliente.menu_cliente')
    else:
        url_destino = url_for('cliente.mis_empresas')

    return jsonify({
        "ok": True, 
        "redirect": url_destino
    }), 200


def registrar_cliente_json(data):
    telefono = str(data.get("telefono", "")).strip()
    nombre = str(data.get("nombreCliente", "")).strip()
    fechanac = str(data.get("fechanac", "")).strip()
    correo = str(data.get("correo", "")).strip()
    codigo = str(data.get("codigo", "")).strip()
    id_pais = data.get("idPais")
    id_empresa = data.get("idEmpresa") or session.get("idEmpresa")

    if not telefono or not nombre or not codigo or not str(id_pais or "").isdigit():
        return {"ok": False, "msg": "Completa el nombre, teléfono, país y código."}, 400

    pais = Pais.query.get(int(id_pais))
    if not pais or not pais.activo:
        return {"ok": False, "msg": "Selecciona un país válido."}, 400

    # Validar que el nombre incluya al menos nombre y apellido (2 palabras),
    # y que solo contenga letras (con acentos/ñ) para evitar números o basura.
    nombre = " ".join(nombre.split())  # normaliza espacios múltiples
    partes_nombre = nombre.split(" ")
    patron_nombre = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿÑñ]+$")
    if len(partes_nombre) < 2 or not all(len(p) >= 2 and patron_nombre.match(p) for p in partes_nombre):
        return {"ok": False, "msg": "Ingresa tu nombre completo (nombre y apellido)."}, 400

    registro_codigo = CodigoTelefono.query.filter_by(telefono=telefono).first()
    if not registro_codigo or registro_codigo.codigo != codigo or datetime.now() > registro_codigo.expiracion:
        return {"ok": False, "msg": "Código inválido o expirado."}, 401

    try:
        cliente = Cliente.query.filter_by(telefono=telefono).first()
        token = str(uuid.uuid4())

        if not cliente:
            cliente = Cliente(
                nombreCliente=nombre,
                fechaNac=fechanac or None,
                telefono=telefono,
                idPais=pais.idPais,
                correo=correo,
                correoValido=False,
                tokenCorreoVerificacion=token,
                fechaRegistro=datetime.now()
            )
            db.session.add(cliente)
            db.session.flush()
            otorgar_bonificacion_publicidad_cliente(cliente)
        else:
            cliente.idPais = pais.idPais
            if correo and correo != cliente.correo:
                cliente.correo = correo
                cliente.correoValido = False
                cliente.tokenCorreoVerificacion = token

        if id_empresa:
            relacion_existente = ClienteEmpresa.query.filter_by(
                idCliente=cliente.idCliente,
                idEmpresa=int(id_empresa)
            ).first()
            if not relacion_existente:
                nueva_relacion = ClienteEmpresa(
                    idCliente=cliente.idCliente,
                    idEmpresa=int(id_empresa)
                )
                db.session.add(nueva_relacion)

        db.session.delete(registro_codigo)
        db.session.commit()

        if correo and not cliente.correoValido:
            enviar_correo(correo, token)

        session["idCliente"] = cliente.idCliente
        session["nombreCliente"] = cliente.nombreCliente
        session["telefono"] = cliente.telefono
        if id_empresa:
            session["idEmpresa"] = int(id_empresa)

        redirect_url = url_for('cliente.menu_cliente') if id_empresa else url_for('cliente.mis_empresas')
        return {
            "ok": True,
            "redirect": redirect_url,
            "cliente": {
                "id": cliente.idCliente,
                "nombreCliente": cliente.nombreCliente,
                "empresaId": int(id_empresa) if id_empresa else None
            }
        }, 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error en registro JSON: {e}")
        return {"ok": False, "msg": "Error en el registro."}, 500


# ============================================================
# ALTA: Registro de nuevo usuario
# ============================================================
@cliente_bp.route("/cliente/alta", methods=["GET", "POST"])
def alta_cliente():
    id_empresa = session.get("idEmpresa") or request.args.get("idEmpresa")
    
    empresa_obj = None
    if id_empresa:
        empresa_obj   = Empresa.query.get(id_empresa)
        etiquetaCliente = empresa_obj.etiquetaCliente if empresa_obj and empresa_obj.etiquetaCliente else 'Cliente'
    else:
        etiquetaCliente = "Cliente"
        
    if request.method == "POST":
        nombre   = request.form.get("nombreCliente")
        fechanac = request.form.get("fechanac")
        telefono = request.form.get("telefono")
        correo   = request.form.get("correo")
        codigo   = request.form.get("codigo")
        id_pais  = request.form.get("idPais")

        result, status = registrar_cliente_json({
            "telefono": telefono,
            "nombreCliente": nombre,
            "fechanac": fechanac,
            "correo": correo,
            "codigo": codigo,
            "idPais": id_pais,
            "idEmpresa": id_empresa
        })

        if result.get("ok"):
            return redirect(result["redirect"])

        return render_template("alta_cliente.html", 
                               mensaje=result.get("msg", "Error en el registro"), 
                               tipo_mensaje="error", 
                               idEmpresa=id_empresa, 
                               empresa=empresa_obj.razonSocial if empresa_obj else "CitaNet", 
                               telefono=telefono,
                               idPais=id_pais,
                               paises=Pais.query.filter_by(activo=True).order_by(Pais.nombre).all(),
                               etiqueta=etiquetaCliente)

    return render_template("alta_cliente.html", 
                           idEmpresa=id_empresa, 
                           empresa=empresa_obj.razonSocial if empresa_obj else "CitaNet", 
                           telefono=request.args.get("telefono", ""),
                           idPais=request.args.get("idPais", ""),
                           paises=Pais.query.filter_by(activo=True).order_by(Pais.nombre).all(),
                           etiqueta=etiquetaCliente)



# ===================================================================
# MENÚ: Pantalla principal del cliente con su información y opciones
# ===================================================================
@cliente_bp.route("/cliente/menu", methods=["GET"])
def menu_cliente():
    id_cliente = session.get("idCliente")
    id_empresa = session.get("idEmpresa")
    
    if not id_cliente or not id_empresa:
        return redirect(url_for('cliente.login'))

    cliente = Cliente.query.get(id_cliente)
    empresa = Empresa.query.get(id_empresa)
    
    if cliente is None or empresa is None:
        session.clear() # Limpiamos sesión inválida o vieja
        return redirect(url_for('cliente.login')) # Redirigir al inicio/login
    
    membresia = ClienteEmpresa.query.filter_by(
        idCliente=id_cliente, 
        idEmpresa=id_empresa
    ).first()

    saldo_actual = membresia.saldo if membresia else Decimal('0.00')
    puntos_actuales = Decimal(str(membresia.puntosLealtad)) if membresia and membresia.puntosLealtad is not None else Decimal('0.00')
    puntos_por_staff = []
    saldo_color = 'positivo' if saldo_actual >= 0 else 'negativo'

    if empresa and empresa.modoAcumulacionPuntos == 'staff':
        registros_staff = (
            db.session.query(ClienteStaff, Usuario)
            .join(Usuario, Usuario.idUsuario == ClienteStaff.idUsuario)
            .filter(
                ClienteStaff.idCliente == id_cliente,
                ClienteStaff.idEmpresa == id_empresa,
                ClienteStaff.puntosLealtad > 0
            )
            .order_by(ClienteStaff.puntosLealtad.desc())
            .all()
        )

        puntos_por_staff = []
        for cliente_staff, usuario in registros_staff:
            nombre_staff = usuario.alias or usuario.nombreUsuario or usuario.usuario or f"Staff #{usuario.idUsuario}"
            puntos = Decimal(str(cliente_staff.puntosLealtad or 0))
            if puntos > 0:
                puntos_por_staff.append({
                    'nombre': nombre_staff,
                    'puntos': puntos,
                })
                puntos_actuales += puntos

    session['razonSocial'] = empresa.razonSocial

    return render_template("menu_cliente.html", 
                           empresa=empresa.razonSocial,
                           nombreCliente=cliente.nombreCliente,
                           telefono=cliente.telefono,
                           saldo=saldo_actual,
                           saldo_color=saldo_color,
                           puntosLealtad=puntos_actuales,
                           puntos_por_staff=puntos_por_staff,
                           idEmpresa=id_empresa,
                           modoAcumulacionPuntos=empresa.modoAcumulacionPuntos if empresa else 'empresa')


@cliente_bp.route("/cliente/mis_empresas")
def mis_empresas():
    id_cliente = session.get("idCliente")
    if not id_cliente:
        return redirect(url_for('cliente.login'))

    # 1. Obtener las relaciones actuales del cliente
    relaciones = ClienteEmpresa.query.filter_by(idCliente=id_cliente).all()
    ids_vinculados = [r.idEmpresa for r in relaciones]

    # 2. Construir la consulta base para "otras empresas"
    # Siempre excluimos la empresa 1 (CITANET)
    query_otras = Empresa.query.filter(Empresa.idEmpresa != 1)

    logger.info(f"query_otras: {[e.idEmpresa for e in query_otras]} ")
    

    # 3. Si ya tiene empresas vinculadas, también las excluimos de la lista "para vincular"
    if ids_vinculados:
        query_otras = query_otras.filter(Empresa.idEmpresa.not_in(ids_vinculados))

    otras_empresas = query_otras.all()

    logger.info(f"Cliente {id_cliente} tiene {len(relaciones)} relaciones y {len(otras_empresas)} otras empresas disponibles para vincular. estas empresas son: {[e.idEmpresa for e in otras_empresas]} ")

    return render_template("empresas_cliente.html", 
                           id_empresa=session.get("idEmpresa") if session.get("idEmpresa") else None,
                           relaciones=relaciones, 
                           otras_empresas=otras_empresas)                           


@cliente_bp.route("/cliente/empresa_seleccionada/<int:id_empresa>")
def empresa_seleccionada(id_empresa):
    session["idEmpresa"] = id_empresa
    # Guardar también el nombre de la empresa para que la app móvil lo tenga en sesión
    empresa = Empresa.query.get(id_empresa)
    if empresa:
        session["nombreEmpresa"] = empresa.razonSocial
    return redirect(url_for('cliente.menu_cliente'))


@cliente_bp.route("/cliente/vincular_empresa", methods=["POST"])
def vincular_empresa():
    data = request.get_json()
    id_empresa = data.get("idEmpresa")
    id_cliente = session.get("idCliente")
    
    if not id_cliente or not id_empresa:
        return jsonify({"status": "error", "msg": "Sesión inválida"}), 400
        
    nueva_rel = ClienteEmpresa(idCliente=id_cliente, idEmpresa=id_empresa)
    db.session.add(nueva_rel)
    db.session.commit()
    
    return jsonify({"status": "ok"})

@cliente_bp.route('/buscar_cliente', methods=['GET'])
def buscar_cliente():
    # Obtenemos el término de búsqueda 'q' de la URL
    query = request.args.get('q', '').strip()
    id_empresa = session.get('idEmpresa')

    clientes = []

    if query and id_empresa:
        clientes = (
            db.session.query(Cliente)
            .join(ClienteEmpresa)
            .filter(
                ClienteEmpresa.idEmpresa == id_empresa,
                db.or_(
                    Cliente.nombreCliente.ilike(f"%{query}%"),
                    Cliente.telefono.ilike(f"%{query}%"),
                    Cliente.correo.ilike(f"%{query}%")
                )
            )
            .distinct()
            .all()
        )

    return render_template('buscar_cliente.html', clientes=clientes, query=query)


@cliente_bp.route('/perfil_cliente')
def perfil_cliente():
    id_empresa = session.get('idEmpresa')
    id_cliente_gestionado = session.get('idClientegestionado')

    if not id_empresa:
        return redirect(config.URL_BASE)
    if not id_cliente_gestionado:
        return redirect(url_for('cliente.buscar_cliente'))

    cliente_data = db.session.query(Cliente, ClienteEmpresa).join(ClienteEmpresa).filter(
        Cliente.idCliente == id_cliente_gestionado,
        ClienteEmpresa.idEmpresa == id_empresa
    ).first()

    if not cliente_data:
        return "Cliente no encontrado", 404

    cliente, membresia = cliente_data
    empresa = Empresa.query.get(id_empresa)
    session['idClientegestionado'] = id_cliente_gestionado

    puntos_por_staff = []
    total_puntos_staff = 0.0

    if empresa and empresa.modoAcumulacionPuntos == 'staff':
        registros_staff = (
            db.session.query(ClienteStaff, Usuario)
            .join(Usuario, Usuario.idUsuario == ClienteStaff.idUsuario)
            .filter(
                ClienteStaff.idCliente == id_cliente_gestionado,
                ClienteStaff.idEmpresa == id_empresa,
                ClienteStaff.puntosLealtad > 0
            )
            .order_by(ClienteStaff.puntosLealtad.desc())
            .all()
        )

        puntos_por_staff = []
        for cliente_staff, usuario in registros_staff:
            nombre_staff = usuario.alias or usuario.nombreUsuario or usuario.usuario or f"Staff #{usuario.idUsuario}"
            puntos = float(cliente_staff.puntosLealtad or 0)
            if puntos > 0:
                puntos_por_staff.append({
                    'nombre': nombre_staff,
                    'puntos': puntos,
                })
                total_puntos_staff += puntos

    tipos_movimiento = tipoMovimiento.query.all()

    return render_template(
        'perfil_cliente.html',
        cliente=cliente,
        membresia=membresia,
        empresa=empresa,
        razonSocial=empresa.razonSocial if empresa else 'Cliente',
        tipos_movimiento=tipos_movimiento,
        puntos_por_staff=puntos_por_staff,
        total_puntos_staff=total_puntos_staff,
    )

@cliente_bp.route('/cliente/editar_datos', methods=['GET', 'POST'])
def editar_datos_cliente():

    id_empresa = session.get('idEmpresa')
    es_personal = session.get('tipoUsuario') in ('superuser', 'admin', 'staff', 'asistente')
    id_cliente = session.get('idClientegestionado') if es_personal else session.get('idCliente')

    if not id_cliente:
        return redirect(url_for('cliente.login'))

    if es_personal and not id_empresa:
        return redirect(config.URL_BASE)

    cliente = Cliente.query.get(id_cliente)
    if not cliente:
        return 'Cliente no encontrado', 404

    if es_personal:
        pertenece_empresa = ClienteEmpresa.query.filter_by(
            idCliente=id_cliente,
            idEmpresa=id_empresa
        ).first()
        if not pertenece_empresa:
            return 'Cliente no encontrado en esta empresa', 404

    paises = Pais.query.filter_by(activo=True).order_by(Pais.nombre).all()
    clientes_referencia = (
        Cliente.query
        .filter(Cliente.idCliente != id_cliente)
        .order_by(Cliente.nombreCliente.asc())
        .all()
    )

    if request.method == 'POST':
        nombre = ' '.join((request.form.get('nombreCliente') or '').split())
        correo = (request.form.get('correo') or '').strip()
        fecha_nac = (request.form.get('fechaNac') or '').strip()

        direccion = (request.form.get('direccion') or '').strip()
        ciudad = (request.form.get('ciudad') or '').strip()
        estado = (request.form.get('estado') or '').strip()
        id_pais_raw = (request.form.get('idPais') or '').strip()

        referencia_raw = (request.form.get('referencia') or '').strip()
        fallecido = request.form.get('fallecido') in ('1', 'on', 'true', 'True') if es_personal else cliente.fallecido
        fecha_fall = (request.form.get('fechaFall') or '').strip() if es_personal else ''

        if len(nombre.split()) < 2:
            flash('Escribe el nombre completo del cliente.', 'danger')
            return render_template(
                'editar_datos_cliente.html',
                cliente=cliente,
                es_personal=es_personal,
                paises=paises,
                clientes_referencia=clientes_referencia
            )

        if not correo or '@' not in correo:
            flash('Escribe un correo electrónico válido.', 'danger')
            return render_template(
                'editar_datos_cliente.html',
                cliente=cliente,
                es_personal=es_personal,
                paises=paises,
                clientes_referencia=clientes_referencia
            )

        try:
            fecha_nac_obj = datetime.strptime(fecha_nac, '%Y-%m-%d').date() if fecha_nac else None
        except ValueError:
            flash('La fecha de nacimiento no es válida.', 'danger')
            return render_template(
                'editar_datos_cliente.html',
                cliente=cliente,
                es_personal=es_personal,
                paises=paises,
                clientes_referencia=clientes_referencia
            )

        fecha_fall_obj = cliente.fechaFall
        if es_personal:
            try:
                fecha_fall_obj = datetime.strptime(fecha_fall, '%Y-%m-%d').date() if fecha_fall else None
            except ValueError:
                flash('La fecha de fallecimiento no es válida.', 'danger')
                return render_template(
                    'editar_datos_cliente.html',
                    cliente=cliente,
                    es_personal=es_personal,
                    paises=paises,
                    clientes_referencia=clientes_referencia
                )

        if fallecido and fecha_fall_obj and fecha_nac_obj and fecha_fall_obj < fecha_nac_obj:
            flash('La fecha de fallecimiento no puede ser menor a la fecha de nacimiento.', 'danger')
            return render_template(
                'editar_datos_cliente.html',
                cliente=cliente,
                es_personal=es_personal,
                paises=paises,
                clientes_referencia=clientes_referencia
            )

        cliente.nombreCliente = nombre
        cliente.correo = correo
        cliente.fechaNac = fecha_nac_obj
        cliente.direccion = direccion or None
        cliente.ciudad = ciudad or None
        cliente.estado = estado or None
        cliente.idPais = int(id_pais_raw) if id_pais_raw and id_pais_raw.isdigit() else None
        cliente.referencia = referencia_raw or None
        if es_personal:
            cliente.fallecido = fallecido
            cliente.fechaFall = fecha_fall_obj if fallecido else None
        cliente.correoValido = False
        db.session.commit()

        if not es_personal:
            session['nombreCliente'] = cliente.nombreCliente

        flash('Datos personales actualizados correctamente.', 'success')
        destino = url_for('cliente.perfil_cliente') if es_personal else url_for('cliente.menu_cliente')
        return redirect(destino)

    return render_template(
        'editar_datos_cliente.html',
        cliente=cliente,
        es_personal=es_personal,
        paises=paises,
        clientes_referencia=clientes_referencia
    )

@cliente_bp.route('/cliente/datos_personales_app', methods=['GET', 'POST'])
def datos_personales_app():
    """Consulta y actualiza los datos personales desde la app móvil."""
    id_cliente = session.get('idCliente')
    if not id_cliente:
        return jsonify({'ok': False, 'msg': 'No autorizado'}), 401

    cliente = Cliente.query.get(id_cliente)
    if not cliente:
        return jsonify({'ok': False, 'msg': 'Cliente no encontrado'}), 404

    if request.method == 'GET':
        paises = Pais.query.filter_by(activo=True).order_by(Pais.nombre).all()
        clientes_referencia = Cliente.query.filter(
            Cliente.idCliente != id_cliente
        ).order_by(Cliente.nombreCliente.asc()).all()
        return jsonify({
            'ok': True,
            'cliente': {
                'nombreCliente': cliente.nombreCliente or '',
                'correo': cliente.correo or '',
                'fechaNac': cliente.fechaNac.isoformat() if cliente.fechaNac else '',
                'telefono': cliente.telefono or '',
                'idPais': cliente.idPais,
                'direccion': cliente.direccion or '',
                'ciudad': cliente.ciudad or '',
                'estado': cliente.estado or '',
                'referencia': cliente.referencia or '',
            },
            'paises': [{'idPais': pais.idPais, 'nombre': pais.nombre} for pais in paises],
            'clientesReferencia': [
                {'id': cliente_ref.idCliente, 'nombre': cliente_ref.nombreCliente or ''}
                for cliente_ref in clientes_referencia
            ],
        })

    data = request.get_json(silent=True) or {}
    nombre = ' '.join(str(data.get('nombreCliente') or '').split())
    correo = str(data.get('correo') or '').strip()
    if len(nombre.split()) < 2:
        return jsonify({'ok': False, 'msg': 'Escribe el nombre completo del cliente.'}), 400
    if not correo or '@' not in correo:
        return jsonify({'ok': False, 'msg': 'Escribe un correo electrónico válido.'}), 400

    def parse_date(value, label):
        if not value:
            return None
        try:
            return datetime.strptime(str(value), '%Y-%m-%d').date()
        except ValueError:
            raise ValueError(f'La {label} no es válida.')

    try:
        fecha_nac = parse_date(data.get('fechaNac'), 'fecha de nacimiento')
    except ValueError as error:
        return jsonify({'ok': False, 'msg': str(error)}), 400

    cliente.nombreCliente = nombre
    cliente.correo = correo
    cliente.fechaNac = fecha_nac
    cliente.direccion = str(data.get('direccion') or '').strip() or None
    cliente.ciudad = str(data.get('ciudad') or '').strip() or None
    cliente.estado = str(data.get('estado') or '').strip() or None
    cliente.idPais = int(data['idPais']) if str(data.get('idPais') or '').isdigit() else None
    cliente.referencia = str(data.get('referencia') or '').strip() or None
    cliente.correoValido = False
    db.session.commit()
    session['nombreCliente'] = cliente.nombreCliente

    return jsonify({'ok': True, 'msg': 'Datos personales actualizados correctamente.'})

@cliente_bp.route('/cliente/historial_citas')
def historial_citas():
    id_empresa = session.get('idEmpresa')
    id_cliente_gestionado = session.get('idClientegestionado')

    if not id_empresa:
        return redirect(config.URL_BASE)
    if not id_cliente_gestionado:
        return redirect(url_for('cliente.buscar_cliente'))

    cliente = Cliente.query.get(id_cliente_gestionado)
    empresa = Empresa.query.get(id_empresa)

    if not cliente or not empresa:
        return "Cliente no encontrado", 404

    # Filtro opcional por estatus (?estatus=<idEstatus>)
    id_estatus_filtro = request.args.get('estatus', type=int)

    query = CitaCliente.query.join(Cita).options(
        joinedload(CitaCliente.cita).joinedload(Cita.usuario),
        joinedload(CitaCliente.cita).joinedload(Cita.producto),
        joinedload(CitaCliente.cita_productos).joinedload(CitaProducto.producto),
        joinedload(CitaCliente.estatus)
    ).filter(
        CitaCliente.idCliente == id_cliente_gestionado,
        Cita.idEmpresa == id_empresa
    )

    if id_estatus_filtro:
        query = query.filter(CitaCliente.idEstatus == id_estatus_filtro)

    citas = query.order_by(Cita.fechaCita.desc(), Cita.horaCita.desc()).all()

    # Colores por estatus, específicos de esta empresa (para los badges)
    colores_estatus = {
        e.idEstatus: ColorEstatusCitaEmpresa.color_cita_estatus(id_empresa, e.idEstatus)
        for e in EstatusCita.query.all()
    }

    # Solo mostramos en el filtro los estatus que aplican a citas ya agendadas
    # por un cliente (excluimos "Disponible"/"Bloqueada", que son horarios internos sin cliente)
    estatus_ocultos = {const.CREADA, const.DISPONIBLE, const.COMPLETA, const.BLOQUEADA}
    estatus_lista = [
        e for e in EstatusCita.query.filter_by(activo=True).order_by(EstatusCita.nombre).all()
        if e.idEstatus not in estatus_ocultos
    ]

    return render_template(
        'historial_citas.html',
        cliente=cliente,
        razonSocial=empresa.razonSocial,
        citas=citas,
        estatus_lista=estatus_lista,
        estatus_seleccionado=id_estatus_filtro,
        colores_estatus=colores_estatus
    )


@cliente_bp.route('/admin/cliente/cargo_directo', methods=['POST'])
def registrar_cargo_directo():
    if "idUsuario" not in session:
        return redirect(config.URL_BASE)

    id_empresa = session.get('idEmpresa')
    id_cliente = request.form.get('idCliente')
    id_tipo_mov = request.form.get('idTipoMovimiento')
    monto_str = request.form.get('monto')
    notas = request.form.get('notas')

    if not id_cliente or not id_tipo_mov or not monto_str:
        flash("Datos incompletos para registrar el movimiento.", "danger")
        return redirect(url_for('cliente.perfil_cliente'))

    try:
        monto = Decimal(monto_str)
        id_usuario = session.get('idUsuario')

        # Utilizamos directamente tu función existente de cliente.py
        generar_movCuenta_Cliente(
            idEmpresa=int(id_empresa),
            idCliente=int(id_cliente),
            idtipoMovimiento=int(id_tipo_mov),
            monto=monto,
            idUsuario=id_usuario,
            notas=notas
        )

        db.session.commit()
        flash("Movimiento directo aplicado correctamente a la cuenta.", "success")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al aplicar cargo directo: {e}")
        flash("Ocurrió un error al procesar el cargo en la base de datos.", "danger")

    return redirect(url_for('cliente.perfil_cliente'))

def generar_movCuenta_Cliente(idEmpresa, idCliente, idtipoMovimiento, monto, idMovReferencia=None, idUsuario=None, notas=None, idmetodoPago=None):
    ahora = datetime.now()
    monto = Decimal(str(monto))

    nuevo_movCuenta = movCuenta(
        idEmpresa=idEmpresa,
        idCliente=idCliente,
        idtipoMovimiento=idtipoMovimiento,
        idUsuario=idUsuario,
        idMovReferencia=idMovReferencia,
        monto=monto,        
        saldoAnterior=monto,
        saldo=monto,                
        notas=notas,
        idmetodoPago=idmetodoPago,
        fecha=datetime.now(),
        hora = ahora.time()    )

    db.session.add(nuevo_movCuenta)
    db.session.flush()  # Para obtener el ID del nuevo cargo
    
    # Si es un CARGO, buscar abonos disponibles y aplicarlos automáticamente
    tipo_mov = tipoMovimiento.query.get(idtipoMovimiento)
    if tipo_mov and tipo_mov.naturaleza == 'C':  # Si es CARGO
        # Buscar abonos (pagos) con saldo disponible
        abonos_disponibles = movCuenta.query.filter(
            movCuenta.idCliente == idCliente,
            movCuenta.idEmpresa == idEmpresa,
            movCuenta.saldo > 0
        ).join(movCuenta.tipo).filter_by(naturaleza='A')\
         .order_by(movCuenta.fecha.asc(), movCuenta.hora.asc()).all()
        
        # Aplicar abonos al cargo
        monto_restante = Decimal(str(nuevo_movCuenta.saldo))
        for abono in abonos_disponibles:
            if monto_restante <= 0:
                break
            
            # ¿Cuánto se aplica?
            monto_aplicado = min(Decimal(str(abono.saldo)), monto_restante)
            
            if monto_aplicado <= 0:
                continue
            
            # Crear aplicación
            aplicacion = movAplica(
                idmovCargo=nuevo_movCuenta.idMovimiento,
                idmovAbono=abono.idMovimiento,
                montoAplicado=monto_aplicado,
                idUsuario=idUsuario,
                fechaAplicado=datetime.now()
            )
            db.session.add(aplicacion)
            
            # Actualizar saldos del cargo
            nuevo_movCuenta.saldoAnterior = nuevo_movCuenta.saldo
            nuevo_movCuenta.saldo -= monto_aplicado

            if idtipoMovimiento == const.MOV_CITA and idMovReferencia:
                monto_producto_pendiente = monto_aplicado
                productos_cita = CitaProducto.query.filter_by(
                    idCitaCliente=idMovReferencia
                ).order_by(CitaProducto.idCitaProducto.asc()).all()

                for producto_cita in productos_cita:
                    if monto_producto_pendiente <= 0:
                        break

                    precio_unitario = Decimal(str(producto_cita.precioCobrado or 0))
                    cantidad = Decimal(str(producto_cita.cantidad or 0))
                    total_producto = precio_unitario * cantidad
                    monto_pagado_actual = Decimal(str(producto_cita.montoPagado or 0))
                    saldo_producto = max(total_producto - monto_pagado_actual, Decimal('0.00'))
                    monto_producto = min(saldo_producto, monto_producto_pendiente)

                    if monto_producto > 0:
                        producto_cita.montoPagado = monto_pagado_actual + monto_producto
                        monto_producto_pendiente -= monto_producto
            
            # Actualizar saldos del abono
            abono.saldoAnterior = abono.saldo
            abono.saldo -= monto_aplicado
            
            monto_restante -= monto_aplicado
    
    relacion = ClienteEmpresa.query.filter_by(idCliente=idCliente, idEmpresa=idEmpresa).first()
    relacion.saldo = calcular_saldo(idEmpresa, idCliente)
    
    """
    
    ce = ClienteEmpresa.query.filter_by(idCliente=idCliente, idEmpresa=idEmpresa).first()
    
    # Actualizar saldo según el tipo de movimiento
    # Si es CARGO (naturaleza='C'): disminuye el saldo del cliente (aumenta su adeudo)
    # Si es ABONO (naturaleza='A'): aumenta el saldo del cliente (reduce su adeudo)
    tipo_mov = tipoMovimiento.query.get(idtipoMovimiento)
    
    if ce:
        if tipo_mov and tipo_mov.naturaleza == 'C':
            ce.saldo -= monto  # Cargo: disminuye saldo
        else:
            ce.saldo += monto  # Abono: aumenta saldo
    else:
        if tipo_mov and tipo_mov.naturaleza == 'C':
            nueva_ce = ClienteEmpresa(idCliente=idCliente, idEmpresa=idEmpresa, saldo=-monto)
        else:
            nueva_ce = ClienteEmpresa(idCliente=idCliente, idEmpresa=idEmpresa, saldo=monto)
        db.session.add(nueva_ce)
    """    
    return nuevo_movCuenta


def otorgar_bonificacion_publicidad_cliente(cliente, idUsuario=None):
    """
    Cuando se crea un Cliente por primera vez en CitaNet (registro global, sin
    importar bajo qué empresa se dio de alta), si hay un paquete configurado en
    Config.idProductoBonifCliente se le regala: se crea el abono de
    'Bonificación' y el cargo de 'Compra' (éste último autoaplica el abono
    dentro de generar_movCuenta_Cliente, generando el movAplica), más su
    CompraPublicidad con el cupo correspondiente — igual que si lo hubiera
    comprado. Se registra sobre la cuenta de la empresa 1 (CitaNet), que es
    donde vive el catálogo de paquetes de publicidad.
    """
    cfg = Config.query.first()
    if not cfg or not cfg.idProductoBonifCliente:
        return

    producto = Producto.query.get(cfg.idProductoBonifCliente)
    if not producto or not producto.activo:
        return

    idUsuario = idUsuario or const.ID_USUARIO_SISTEMA
    id_empresa_citanet = const.ID_EMPRESA_CITANET

    # generar_movCuenta_Cliente actualiza el saldo de ClienteEmpresa al final;
    # como el cliente puede no tener membresía con la empresa 1 (CitaNet), nos
    # aseguramos de que exista antes de generar los movimientos.
    relacion = ClienteEmpresa.query.filter_by(idCliente=cliente.idCliente, idEmpresa=id_empresa_citanet).first()
    if not relacion:
        relacion = ClienteEmpresa(idCliente=cliente.idCliente, idEmpresa=id_empresa_citanet)
        db.session.add(relacion)
        db.session.flush()

    monto = float(producto.costo)
    config_paquete = producto.configuracion_publicidad
    cantidad_publicidad = config_paquete.cantidadPublicidad if config_paquete else 1
    dias_vigencia = config_paquete.diasVigencia if config_paquete else 30

    # 1) Abono de bonificación
    generar_movCuenta_Cliente(
        idEmpresa=id_empresa_citanet,
        idCliente=cliente.idCliente,
        idtipoMovimiento=const.MOV_BONIFICACION,
        monto=monto,
        idUsuario=idUsuario,
        notas=f"Bonificación de publicidad por alta de cliente: {producto.nombre}"
    )

    # 2) Cargo de compra: al crearse, generar_movCuenta_Cliente busca abonos con
    # saldo disponible (el que acabamos de crear) y lo aplica automáticamente,
    # generando el movAplica correspondiente.
    nuevo_movimiento = generar_movCuenta_Cliente(
        idEmpresa=id_empresa_citanet,
        idCliente=cliente.idCliente,
        idtipoMovimiento=const.MOV_COMPRA,
        idMovReferencia=producto.idProducto,
        monto=monto,
        idUsuario=idUsuario,
        notas=f"Cargo por bonificación de publicidad: {producto.nombre}"
    )

    nueva_compra = CompraPublicidad(
        idMovimiento=nuevo_movimiento.idMovimiento,
        idProducto=producto.idProducto,
        idEmpresa=None,
        idCliente=cliente.idCliente,
        cantidadPermitida=cantidad_publicidad,
        cantidadUsada=0,
        diasVigencia=dias_vigencia
    )
    db.session.add(nueva_compra)


# ==========================================
# ENDPOINTS JSON PARA APP MÓVIL
# ==========================================

@cliente_bp.route("/cliente/mis_empresas_app", methods=["GET"])
def mis_empresas_app():
    """Devuelve JSON de empresas vinculadas con logo para la app móvil."""
    id_cliente = session.get("idCliente")
    if not id_cliente:
        return jsonify({"error": "No autorizado"}), 401

    cliente  = Cliente.query.get(id_cliente)
    relaciones = ClienteEmpresa.query.filter_by(idCliente=id_cliente).all()

    empresas = []
    for rel in relaciones:
        emp = Empresa.query.get(rel.idEmpresa)
        if emp and emp.slug:
            logo_url = None
            if emp.logo:
                logo_url = f"https://www.citanet.com.mx/static/{emp.logo}"
            empresas.append({
                "id":   emp.idEmpresa,
                "name": emp.razonSocial,
                "logo": logo_url,
                "slug": emp.slug,
            })

    return jsonify({
        "empresas":      empresas,
        "nombreCliente": cliente.nombreCliente if cliente else "",
        "idCliente":     id_cliente,
    })


@cliente_bp.route("/cliente/empresa_seleccionada_app/<int:id_empresa>", methods=["GET"])
def empresa_seleccionada_app(id_empresa):
    """Selecciona empresa y devuelve JSON con datos para la app móvil."""
    id_cliente = session.get("idCliente")
    if not id_cliente:
        return jsonify({"error": "No autorizado"}), 401

    cliente = Cliente.query.get(id_cliente)
    empresa = Empresa.query.get(id_empresa)

    if not empresa:
        return jsonify({"error": "Empresa no encontrada"}), 404

    # Guardar en sesión igual que el flujo web
    session["idEmpresa"]     = empresa.idEmpresa
    session["nombreEmpresa"] = empresa.razonSocial

    logo_url = None
    if empresa.logo:
        logo_url = f"https://www.citanet.com.mx/static/{empresa.logo}"

    relacion = ClienteEmpresa.query.filter_by(idCliente=id_cliente, idEmpresa=empresa.idEmpresa).first()
    puntos_lealtad = float(relacion.puntosLealtad) if relacion and relacion.puntosLealtad is not None else 0.0

    return jsonify({
        "ok":            True,
        "idEmpresa":     empresa.idEmpresa,
        "nombreEmpresa": empresa.razonSocial,
        "logo":          logo_url,
        "nombreCliente": cliente.nombreCliente if cliente else "",
        "idCliente":     id_cliente,
        "puntosLealtad": puntos_lealtad,
    })

@cliente_bp.route("/cliente/puntos_app", methods=["GET"])
def puntos_app():
    """Devuelve los puntos del cliente y, si aplica, el desglose por especialista."""
    id_cliente = session.get("idCliente")
    id_empresa = session.get("idEmpresa")
    if not id_cliente or not id_empresa:
        return jsonify({"ok": False, "msg": "No autorizado"}), 401

    empresa = Empresa.query.get(id_empresa)
    membresia = ClienteEmpresa.query.filter_by(
        idCliente=id_cliente,
        idEmpresa=id_empresa
    ).first()
    puntos_total = Decimal(str(membresia.puntosLealtad or 0)) if membresia else Decimal('0.00')
    puntos_por_staff = []

    if empresa and empresa.modoAcumulacionPuntos == 'staff':
        registros_staff = (
            db.session.query(ClienteStaff, Usuario)
            .join(Usuario, Usuario.idUsuario == ClienteStaff.idUsuario)
            .filter(
                ClienteStaff.idCliente == id_cliente,
                ClienteStaff.idEmpresa == id_empresa,
                ClienteStaff.puntosLealtad > 0
            )
            .order_by(ClienteStaff.puntosLealtad.desc())
            .all()
        )
        for cliente_staff, usuario in registros_staff:
            puntos = Decimal(str(cliente_staff.puntosLealtad or 0))
            if puntos > 0:
                puntos_por_staff.append({
                    "nombre": usuario.alias or usuario.nombreUsuario or usuario.usuario or f"Staff #{usuario.idUsuario}",
                    "puntos": float(puntos),
                })
                puntos_total += puntos

    return jsonify({
        "ok": True,
        "modoAcumulacionPuntos": empresa.modoAcumulacionPuntos if empresa else "empresa",
        "puntosLealtad": float(puntos_total),
        "puntosPorStaff": puntos_por_staff,
    })