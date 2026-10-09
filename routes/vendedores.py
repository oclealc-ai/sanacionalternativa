from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort, send_from_directory
from datetime import datetime, timedelta
from decimal import Decimal
from werkzeug.utils import secure_filename
from sqlalchemy import func
from modelos import db, Vendedor, NivelComisionVendedor, VendedorEmpresa, Empresa, CodigoTelefono, movCuenta, PagoComisionVendedor, Pais
from constantes import const
import logging
import random
import re
import string
import os
import uuid
import config

logger = logging.getLogger(__name__)
vendedores_bp = Blueprint('vendedores', __name__)


def _formatear_porcentaje(valor):
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    if f == int(f):
        return str(int(f))
    texto = f'{f:.2f}'.rstrip('0').rstrip('.')
    return texto


def _generar_codigo_referido():
    while True:
        codigo = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        if not Vendedor.query.filter_by(codigoReferido=codigo).first():
            return codigo


def _aplicar_datos_referidos(vendedor):
    if not vendedor.codigoReferido or len((vendedor.codigoReferido or '').strip()) != 8:
        vendedor.codigoReferido = _generar_codigo_referido()

    vendedor.codigoReferido = (vendedor.codigoReferido or _generar_codigo_referido()).strip().upper()

    existente_codigo = Vendedor.query.filter_by(codigoReferido=vendedor.codigoReferido).first()
    if existente_codigo and existente_codigo.idVendedor != vendedor.idVendedor:
        vendedor.codigoReferido = _generar_codigo_referido()


def _obtener_nivel_default():
    nivel = NivelComisionVendedor.query.filter_by(activo=True).order_by(NivelComisionVendedor.idNivelComision.asc()).first()
    if nivel:
        return nivel.idNivelComision

    nivel_nuevo = NivelComisionVendedor(
        nombre='Nivel Inicial',
        porcComision=20.00,
        periodoComisionMeses=12,
        activo=True,
    )
    db.session.add(nivel_nuevo)
    db.session.commit()
    return nivel_nuevo.idNivelComision


@vendedores_bp.route('/vendedores')
def landing():
    if session.get('idVendedor'):
        return redirect(url_for('vendedores.dashboard'))

    niveles = NivelComisionVendedor.query.filter_by(
        activo=True
    ).order_by(
        NivelComisionVendedor.idNivelComision.asc()
    ).all()

    comision_min = comision_max = None
    periodo_min = periodo_max = None
    if niveles:
        comisiones = [float(n.porcComision) for n in niveles]
        periodos = [n.periodoComisionMeses for n in niveles]
        comision_min = _formatear_porcentaje(min(comisiones))
        comision_max = _formatear_porcentaje(max(comisiones))
        periodo_min = min(periodos)
        periodo_max = max(periodos)

    return render_template(
        'vendedores_landing.html',
        niveles=niveles,
        comision_min=comision_min,
        comision_max=comision_max,
        periodo_min=periodo_min,
        periodo_max=periodo_max,
    )


@vendedores_bp.route('/vendedores/login', methods=['GET'])
def login():
    if session.get('idVendedor'):
        return redirect(url_for('vendedores.dashboard'))
    return render_template('vendedores_login.html')


@vendedores_bp.route('/vendedores/validar_codigo', methods=['POST'])
def validar_codigo_login():
    telefono = (request.form.get('telefono') or '').strip().replace(' ', '')
    codigo = (request.form.get('codigo') or '').strip()

    if not telefono or not codigo:
        flash('Completa tu teléfono y el código.', 'danger')
        return redirect(url_for('vendedores.login'))

    registro_codigo = CodigoTelefono.query.filter(
        CodigoTelefono.telefono == telefono,
        CodigoTelefono.expiracion > datetime.now()
    ).order_by(CodigoTelefono.expiracion.desc()).first()

    if not registro_codigo or registro_codigo.codigo != codigo:
        flash('El código es incorrecto o ya expiró.', 'danger')
        return redirect(url_for('vendedores.login'))

    vendedor = Vendedor.query.filter_by(telefono=telefono).first()
    if not vendedor:
        db.session.delete(registro_codigo)
        db.session.commit()
        flash('Este teléfono no está registrado como vendedor.', 'danger')
        return redirect(url_for('vendedores.login'))

    if not vendedor.activo:
        db.session.delete(registro_codigo)
        db.session.commit()
        flash('Este vendedor está inactivo y no puede acceder al panel.', 'danger')
        return redirect(url_for('vendedores.landing'))

    db.session.delete(registro_codigo)
    db.session.commit()

    session['idVendedor'] = vendedor.idVendedor
    session['nombreVendedor'] = vendedor.nombre
    session['telefonoVendedor'] = vendedor.telefono

    flash('Bienvenido de nuevo.', 'success')
    return redirect(url_for('vendedores.dashboard'))


@vendedores_bp.route('/vendedores/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        fecha_nac = request.form.get('fechaNac') or None
        telefono = (request.form.get('telefono') or '').strip().replace(' ', '')
        email = (request.form.get('email') or '').strip()
        codigo = (request.form.get('codigo') or '').strip()
        id_pais = request.form.get('idPais')

        if not nombre or not telefono or not codigo or not str(id_pais or '').isdigit():
            flash('Completa nombre, teléfono, país y código.', 'danger')
            return redirect(url_for('vendedores.registro'))

        pais = Pais.query.get(int(id_pais))
        if not pais or not pais.activo:
            flash('Selecciona un país válido.', 'danger')
            return redirect(url_for('vendedores.registro'))

        registro_codigo = CodigoTelefono.query.filter(
            CodigoTelefono.telefono == telefono,
            CodigoTelefono.expiracion > datetime.now()
        ).order_by(CodigoTelefono.expiracion.desc()).first()

        if not registro_codigo or registro_codigo.codigo != codigo:
            flash('El código de verificación es incorrecto o ya expiró.', 'danger')
            return redirect(url_for('vendedores.registro'))

        vendedor = Vendedor.query.filter_by(telefono=telefono).first()

        if not vendedor:
            vendedor = Vendedor(
                nombre=nombre,
                fechaNac=fecha_nac or None,
                telefono=telefono,
                email=email or None,
                idPais=pais.idPais,
                codigoReferido=_generar_codigo_referido(),
                idNivelComision=_obtener_nivel_default(),
                activo=True,
            )
            db.session.add(vendedor)
            db.session.flush()
            _aplicar_datos_referidos(vendedor)
            flash('Tu registro como vendedor se completó con éxito.', 'success')
        else:
            vendedor.idPais = pais.idPais
            _aplicar_datos_referidos(vendedor)
            if not vendedor.activo:
                flash('Este vendedor está inactivo y no puede acceder al panel.', 'danger')
                return redirect(url_for('vendedores.landing'))
            flash('Bienvenido de nuevo, continúa con tu panel.', 'success')

        db.session.delete(registro_codigo)
        db.session.commit()

        session['idVendedor'] = vendedor.idVendedor
        session['nombreVendedor'] = vendedor.nombre
        session['telefonoVendedor'] = vendedor.telefono

        return redirect(url_for('vendedores.dashboard'))

    return render_template(
        'vendedores_registro.html',
        telefono=request.args.get('telefono', ''),
        paises=Pais.query.filter_by(activo=True).order_by(Pais.nombre).all(),
    )


@vendedores_bp.route('/vendedores/dashboard')
def dashboard():
    id_vendedor_solicitado = request.args.get('idVendedor', type=int)
    es_superuser = session.get('tipoUsuario') == 'superuser'
    if id_vendedor_solicitado and not es_superuser:
        abort(403)

    id_vendedor = id_vendedor_solicitado if es_superuser and id_vendedor_solicitado else session.get('idVendedor')
    if not id_vendedor:
        flash('Debes registrarte o iniciar sesión como vendedor.', 'warning')
        return redirect(url_for('vendedores.registro'))

    vendedor = Vendedor.query.get(id_vendedor)
    if not vendedor:
        session.clear()
        flash('No se encontró el vendedor.', 'danger')
        return redirect(url_for('vendedores.registro'))

    _aplicar_datos_referidos(vendedor)
    db.session.commit()

    relaciones = VendedorEmpresa.query.filter_by(idVendedor=vendedor.idVendedor).order_by(VendedorEmpresa.fechaRegistro.desc()).all()
    empresas = [rel.empresa for rel in relaciones if rel.empresa]

    detalle_relaciones = []
    total_pagado_a_vendedor = Decimal('0.00')
    total_pendiente = Decimal('0.00')
    total_plan_empresa = Decimal('0.00')

    for rel in relaciones:
        total_plan = db.session.query(func.coalesce(func.sum(movCuenta.monto), 0)).filter(
            movCuenta.idEmpresa == rel.idEmpresa,
            movCuenta.idCliente.is_(None),
            movCuenta.idtipoMovimiento == const.MOV_PLAN,
        ).scalar() or Decimal('0.00')

        comision_generada = (Decimal(str(total_plan)) * (Decimal(str(rel.porcComision or 0)) / Decimal('100')))
        pagos_vendedor = db.session.query(func.coalesce(func.sum(PagoComisionVendedor.montoPago), 0)).filter(
            PagoComisionVendedor.idVendedor == vendedor.idVendedor,
            PagoComisionVendedor.idVendedorEmpresa == rel.idVendedorEmpresa,
            PagoComisionVendedor.aplicado.is_(True),
        ).scalar() or Decimal('0.00')
        pagos_registrados = db.session.query(func.coalesce(func.sum(PagoComisionVendedor.montoPago), 0)).filter(
            PagoComisionVendedor.idVendedor == vendedor.idVendedor,
            PagoComisionVendedor.idVendedorEmpresa == rel.idVendedorEmpresa,
        ).scalar() or Decimal('0.00')

        saldo_pendiente = max(
            comision_generada - Decimal(str(pagos_registrados)),
            Decimal('0.00')
        )

        detalle_relaciones.append({
            'relacion': rel,
            'empresa': rel.empresa,
            'monto_plan': Decimal(str(total_plan)).quantize(Decimal('0.01')),
            'comision_generada': comision_generada.quantize(Decimal('0.01')),
            'pagos_vendedor': Decimal(str(pagos_vendedor)).quantize(Decimal('0.01')),
            'saldo_pendiente': saldo_pendiente.quantize(Decimal('0.01')),
        })

        total_plan_empresa += Decimal(str(total_plan))
        total_pagado_a_vendedor += Decimal(str(pagos_vendedor))
        total_pendiente += saldo_pendiente

    total_empresas = len(empresas)
    total_comision = sum((float(rel.porcComision or 0) * 100) for rel in relaciones)

    codigo_referido = vendedor.codigoReferido
    url_invite = url_for('empresas.registrar_empresa', _external=True, ref=codigo_referido)

    return render_template(
        'vendedores_dashboard.html',
        vendedor=vendedor,
        nivel=vendedor.nivel_comision,
        empresas=empresas,
        relaciones=relaciones,
        total_empresas=total_empresas,
        total_comision=total_comision,
        codigo_referido=codigo_referido,
        url_invite=url_invite,
        detalle_relaciones=detalle_relaciones,
        total_plan_empresa=total_plan_empresa.quantize(Decimal('0.01')),
        total_pagado_a_vendedor=total_pagado_a_vendedor.quantize(Decimal('0.01')),
        total_pendiente=total_pendiente.quantize(Decimal('0.01')),
        es_superuser=es_superuser,
    )


@vendedores_bp.route('/vendedores/codigo', methods=['POST'])
def actualizar_codigo_referido():
    id_vendedor = session.get('idVendedor')
    if not id_vendedor:
        flash('Debes iniciar sesión como vendedor.', 'warning')
        return redirect(url_for('vendedores.login'))

    vendedor = Vendedor.query.get(id_vendedor)
    if not vendedor:
        session.clear()
        flash('No se encontró el vendedor.', 'danger')
        return redirect(url_for('vendedores.registro'))

    codigo = (request.form.get('codigoReferido') or '').strip().upper()
    codigo = re.sub(r'[^A-Z0-9]', '', codigo)

    if not codigo:
        flash('El código de referido no puede quedar vacío.', 'danger')
        return redirect(url_for('vendedores.dashboard'))

    if len(codigo) != 8:
        flash('El código de referido debe tener exactamente 8 caracteres.', 'danger')
        return redirect(url_for('vendedores.dashboard'))

    existente = Vendedor.query.filter(Vendedor.codigoReferido == codigo, Vendedor.idVendedor != vendedor.idVendedor).first()
    if existente:
        flash('Ese código ya está en uso por otro vendedor.', 'danger')
        return redirect(url_for('vendedores.dashboard'))

    vendedor.codigoReferido = codigo

    db.session.commit()
    flash('Tu código de referido se actualizó correctamente.', 'success')
    return redirect(url_for('vendedores.dashboard'))


@vendedores_bp.route('/vendedores/enlace')
def enlace_referido():
    id_vendedor = session.get('idVendedor')
    if not id_vendedor:
        return jsonify({'ok': False, 'msg': 'Sesión de vendedor no activa.'}), 401

    vendedor = Vendedor.query.get(id_vendedor)
    if not vendedor:
        return jsonify({'ok': False, 'msg': 'Vendedor no encontrado.'}), 404

    codigo = vendedor.codigoReferido or 'REF-SIN-CODIGO'
    link = url_for('empresas.registrar_empresa', _external=True, ref=codigo)
    return jsonify({
        'ok': True,
        'codigo': codigo,
        'link': link,
    })


@vendedores_bp.route('/vendedores/datos_bancarios', methods=['GET', 'POST'])
def datos_bancarios():
    id_vendedor = session.get('idVendedor')
    if not id_vendedor:
        flash('Debes iniciar sesión como vendedor.', 'warning')
        return redirect(url_for('vendedores.login'))

    vendedor = Vendedor.query.get(id_vendedor)
    if not vendedor:
        flash('No se encontró el vendedor.', 'danger')
        return redirect(url_for('vendedores.registro'))

    if request.method == 'POST':
        vendedor.banco = (request.form.get('banco') or '').strip()
        vendedor.nombreBanco = (request.form.get('nombreBanco') or '').strip() or vendedor.banco
        vendedor.titularCuenta = (request.form.get('titularCuenta') or '').strip()
        vendedor.tipoCuenta = (request.form.get('tipoCuenta') or '').strip()
        vendedor.numeroCuenta = (request.form.get('numeroCuenta') or '').strip()
        vendedor.clabe = (request.form.get('clabe') or '').strip()
        vendedor.rfc = (request.form.get('rfc') or '').strip()
        db.session.commit()
        flash('Tus datos bancarios se guardaron correctamente.', 'success')
        return redirect(url_for('vendedores.dashboard'))

    return render_template('vendedores_datos_bancarios.html', vendedor=vendedor)


@vendedores_bp.route('/vendedores/empresa/<int:id_empresa>')
def empresa_detalle(id_empresa):
    id_vendedor_solicitado = request.args.get('idVendedor', type=int)
    es_superuser = session.get('tipoUsuario') == 'superuser'
    if id_vendedor_solicitado and not es_superuser:
        abort(403)

    id_vendedor = id_vendedor_solicitado if es_superuser and id_vendedor_solicitado else session.get('idVendedor')
    if not id_vendedor:
        flash('Debes iniciar sesión como vendedor.', 'warning')
        return redirect(url_for('vendedores.login'))

    vendedor = Vendedor.query.get(id_vendedor)
    if not vendedor:
        flash('No se encontró el vendedor.', 'danger')
        return redirect(url_for('vendedores.registro'))

    relacion = VendedorEmpresa.query.filter_by(idVendedor=vendedor.idVendedor, idEmpresa=id_empresa).first_or_404()
    empresa = relacion.empresa

    movimientos_plan = movCuenta.query.filter(
        movCuenta.idEmpresa == id_empresa,
        movCuenta.idCliente.is_(None),
        movCuenta.idtipoMovimiento == const.MOV_PLAN,
    ).order_by(movCuenta.fecha.desc(), movCuenta.hora.desc()).all()

    total_plan = sum((Decimal(str(m.monto)) for m in movimientos_plan), Decimal('0.00'))
    comision_generada = total_plan * (Decimal(str(relacion.porcComision or 0)) / Decimal('100'))

    pagos = PagoComisionVendedor.query.filter_by(
        idVendedor=vendedor.idVendedor,
        idVendedorEmpresa=relacion.idVendedorEmpresa,
    ).order_by(PagoComisionVendedor.fechaPago.desc()).all()
    total_pagado = sum(
        (Decimal(str(p.montoPago)) for p in pagos if p.aplicado),
        Decimal('0.00')
    )
    total_registrado = sum(
        (Decimal(str(p.montoPago)) for p in pagos),
        Decimal('0.00')
    )
    saldo_pendiente = max(
        comision_generada - total_registrado,
        Decimal('0.00')
    )

    return render_template(
        'vendedores_empresa_detalle.html',
        vendedor=vendedor,
        empresa=empresa,
        relacion=relacion,
        movimientos_plan=movimientos_plan,
        total_plan=total_plan.quantize(Decimal('0.01')),
        comision_generada=comision_generada.quantize(Decimal('0.01')),
        pagos=pagos,
        total_pagado=total_pagado.quantize(Decimal('0.01')),
        saldo_pendiente=saldo_pendiente.quantize(Decimal('0.01')),
        es_superuser=es_superuser,
    )


@vendedores_bp.route('/vendedores/empresa/<int:id_empresa>/registrar_pago', methods=['POST'])
def registrar_pago_comision(id_empresa):
    # Solo tú (superuser) puedes generar el registro de un pago hecho a un vendedor.
    if session.get('tipoUsuario') != 'superuser':
        abort(403)

    id_vendedor = request.args.get('idVendedor', type=int) or request.form.get('idVendedor', type=int)
    relacion = VendedorEmpresa.query.filter_by(idVendedor=id_vendedor, idEmpresa=id_empresa).first_or_404()

    try:
        monto = Decimal(str(request.form.get('montoPago', '0')))
    except Exception:
        monto = Decimal('0.00')

    if monto <= 0:
        flash('El monto del pago debe ser mayor a cero.', 'danger')
        return redirect(url_for('vendedores.empresa_detalle', id_empresa=id_empresa, idVendedor=id_vendedor))

    movimientos_plan = movCuenta.query.filter(
        movCuenta.idEmpresa == id_empresa,
        movCuenta.idCliente.is_(None),
        movCuenta.idtipoMovimiento == const.MOV_PLAN,
    ).all()
    comision_generada = sum(
        (Decimal(str(m.monto)) for m in movimientos_plan),
        Decimal('0.00')
    ) * (Decimal(str(relacion.porcComision or 0)) / Decimal('100'))
    pagos_registrados = db.session.query(func.coalesce(func.sum(PagoComisionVendedor.montoPago), 0)).filter(
        PagoComisionVendedor.idVendedor == id_vendedor,
        PagoComisionVendedor.idVendedorEmpresa == relacion.idVendedorEmpresa,
    ).scalar() or Decimal('0.00')
    saldo_disponible = max(
        comision_generada - Decimal(str(pagos_registrados)),
        Decimal('0.00')
    )

    if monto > saldo_disponible:
        flash(
            f'El monto excede el adeudo disponible. Máximo permitido: ${saldo_disponible:,.2f}.',
            'danger'
        )
        return redirect(url_for('vendedores.empresa_detalle', id_empresa=id_empresa, idVendedor=id_vendedor))

    observaciones = (request.form.get('observaciones') or '').strip() or None

    nuevo_pago = PagoComisionVendedor(
        idVendedor=id_vendedor,
        idVendedorEmpresa=relacion.idVendedorEmpresa,
        montoPago=monto,
        fechaPago=datetime.now(),
        aplicado=False,
        observaciones=observaciones,
    )
    db.session.add(nuevo_pago)
    db.session.commit()

    flash(f'Se registró el pago de ${monto:,.2f} al vendedor. Márcalo como "Aplicado" cuando ya lo hayas transferido.', 'success')
    return redirect(url_for('vendedores.empresa_detalle', id_empresa=id_empresa, idVendedor=id_vendedor))


@vendedores_bp.route('/vendedores/pago_comision/<int:id_pago>/comprobante')
def descargar_comprobante_pago(id_pago):
    pago = PagoComisionVendedor.query.get_or_404(id_pago)
    es_superuser = session.get('tipoUsuario') == 'superuser'
    es_vendedor_destino = session.get('idVendedor') == pago.idVendedor
    if not es_superuser and not es_vendedor_destino:
        abort(403)

    if not pago.comprobante:
        abort(404)

    carpeta_comprobantes = os.path.join(config.base_dir, 'static', 'uploads', 'pagos_vendedor')
    return send_from_directory(carpeta_comprobantes, pago.comprobante, as_attachment=False)


@vendedores_bp.route('/vendedores/pago_comision/<int:id_pago>/marcar_aplicado', methods=['POST'])
def marcar_pago_aplicado(id_pago):
    # Solo tú (superuser) puedes confirmar que un pago ya se transfirió de verdad.
    if session.get('tipoUsuario') != 'superuser':
        abort(403)

    pago = PagoComisionVendedor.query.get_or_404(id_pago)
    if pago.aplicado:
        flash('Este pago ya está marcado como aplicado.', 'info')
        return redirect(url_for('vendedores.empresa_detalle', id_empresa=request.args.get('id_empresa', type=int), idVendedor=pago.idVendedor))

    fecha_aplicacion = (request.form.get('fechaAplicacion') or '').strip()
    metodo_pago = (request.form.get('metodoPago') or '').strip()
    folio = (request.form.get('folioTransferencia') or '').strip()
    comprobante = request.files.get('comprobante')

    if not fecha_aplicacion or not metodo_pago or not folio or not comprobante or not comprobante.filename:
        flash('Fecha, método, folio y comprobante son obligatorios para aplicar el pago.', 'danger')
        return redirect(url_for('vendedores.empresa_detalle', id_empresa=request.args.get('id_empresa', type=int), idVendedor=pago.idVendedor))

    try:
        fecha_aplicacion_dt = datetime.strptime(fecha_aplicacion, '%Y-%m-%dT%H:%M')
    except ValueError:
        flash('La fecha de aplicación no tiene un formato válido.', 'danger')
        return redirect(url_for('vendedores.empresa_detalle', id_empresa=request.args.get('id_empresa', type=int), idVendedor=pago.idVendedor))

    nombre_original = secure_filename(comprobante.filename)
    extension = os.path.splitext(nombre_original)[1].lower()
    extensiones_permitidas = {'.pdf', '.jpg', '.jpeg', '.png'}
    if extension not in extensiones_permitidas:
        flash('El comprobante debe ser PDF, JPG, JPEG o PNG.', 'danger')
        return redirect(url_for('vendedores.empresa_detalle', id_empresa=request.args.get('id_empresa', type=int), idVendedor=pago.idVendedor))

    carpeta_comprobantes = os.path.join(config.base_dir, 'static', 'uploads', 'pagos_vendedor')
    os.makedirs(carpeta_comprobantes, exist_ok=True)
    nombre_archivo = f'{pago.idPagoComisionVendedor}_{uuid.uuid4().hex}{extension}'
    comprobante.save(os.path.join(carpeta_comprobantes, nombre_archivo))

    pago.aplicado = True
    pago.fechaAplicacion = fecha_aplicacion_dt
    pago.metodoPago = metodo_pago
    pago.folioTransferencia = folio
    pago.comprobante = nombre_archivo
    pago.observaciones = (request.form.get('observaciones') or '').strip() or pago.observaciones
    db.session.commit()

    flash('Pago marcado como aplicado.', 'success')

    id_empresa = request.args.get('id_empresa', type=int)
    id_vendedor = request.args.get('idVendedor', type=int) or pago.idVendedor
    if id_empresa:
        return redirect(url_for('vendedores.empresa_detalle', id_empresa=id_empresa, idVendedor=id_vendedor))
    return redirect(url_for('vendedores.dashboard', idVendedor=id_vendedor))


@vendedores_bp.route('/vendedores/logout')
def logout():
    session.pop('idVendedor', None)
    session.pop('nombreVendedor', None)
    session.pop('telefonoVendedor', None)
    flash('Sesión de vendedor cerrada.', 'success')
    return redirect(url_for('vendedores.landing'))
