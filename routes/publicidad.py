from flask           import Blueprint, render_template, session, redirect, url_for, abort, request, flash, jsonify
from modelos         import db, Publicidad, Empresa, movCuenta, Producto, CompraPublicidad
from datetime        import datetime, timedelta
from decimal         import Decimal
from werkzeug.utils  import secure_filename
from correo          import enviar_correo_base
from whatsapp        import enviar_whatsapp
from constantes      import const
from routes.cliente  import generar_movCuenta_Cliente
from routes.empresas import generar_movCuenta_Empresa

import os
import config
import logging

logger = logging.getLogger(__name__)

publicidad_bp = Blueprint("publicidad", __name__)

# ==========================================
# SEGURIDAD: Validación por tipoUsuario / idCliente
# ==========================================
def es_cliente():
    return session.get("idCliente") is not None

def puede_acceder():
    tipo = session.get("tipoUsuario")
    return tipo in ["superuser", "admin"] or es_cliente()

# ==========================================
# RUTAS DE MANTENIMIENTO
# ==========================================

@publicidad_bp.route("/publicidad")
def listar_publicidad():     
    if not puede_acceder():
        return redirect(config.URL_BASE)

    tipo_usuario = session.get("tipoUsuario", "").lower()
    id_empresa_actual = session.get("idEmpresa")
    id_cliente_actual = session.get("idCliente")

    if tipo_usuario == "superuser":
        publicidad = Publicidad.query.all()
    elif es_cliente():
        publicidad = Publicidad.query.filter_by(idCliente=id_cliente_actual).all()
    else:
        publicidad = Publicidad.query.filter(Publicidad.idEmpresa == id_empresa_actual, Publicidad.idCliente == None).all()
    
    return render_template("publicidad_listar.html", publicidad=publicidad)

@publicidad_bp.route("/publicidad/pagar/<int:idPublicidad>", methods=["GET", "POST"])
def pagar_publicidad(idPublicidad):
    """Manda al cliente directo a la pasarela de pago (Stripe o Mercado Pago;
    si CitaNet tiene ambas, primero elige) a pagar únicamente
    el movCuenta ligado a esta publicidad puntual (sin pasar por el estado
    de cuenta ni por 'Mis Empresas'). La comisión de pago en línea la
    absorbe CitaNet en este flujo: el cliente solo paga el costo del paquete."""
    if not es_cliente():
        abort(403)

    id_cliente = session.get("idCliente")

    publicidad = Publicidad.query.get_or_404(idPublicidad)
    if publicidad.idCliente != id_cliente:
        abort(403)

    if not publicidad.idMovimiento:
        flash("Esta publicidad no tiene un cargo generado.", "info")
        return redirect(url_for('publicidad.listar_publicidad'))

    cargo = movCuenta.query.get(publicidad.idMovimiento)
    if not cargo or cargo.saldo <= 0:
        flash("Esta publicidad ya no tiene saldo pendiente.", "info")
        return redirect(url_for('publicidad.listar_publicidad'))

    # Import local para evitar import circular entre publicidad.py y pagos.py
    from routes.pagos import (_crear_sesion_pago_cliente, _pasarelas_disponibles,
                              _resolver_pasarela, _render_selector_pasarela)

    url_listado   = url_for('publicidad.listar_publicidad')
    empresa_cobro = Empresa.query.get(cargo.idEmpresa)   # el de CitaNet, tomado del propio cargo

    pasarelas = _pasarelas_disponibles(empresa_cobro)
    if not pasarelas:
        flash("No hay una pasarela de pago configurada para recibir este pago.", "danger")
        return redirect(url_listado)

    pasarela = _resolver_pasarela(pasarelas)
    if pasarela is None:
        # Hay más de una: el cliente elige (el botón elegido hace POST a esta misma ruta).
        return _render_selector_pasarela(
            pasarelas=pasarelas,
            action_url=url_for('publicidad.pagar_publicidad', idPublicidad=idPublicidad),
            monto=Decimal(str(cargo.saldo)),
            nombre_destino=empresa_cobro.razonSocial,
            url_cancelar=url_listado,
        )

    datos_pago = dict(
        id_cliente=id_cliente,
        id_empresa=cargo.idEmpresa,
        monto=Decimal(str(cargo.saldo)),
        cargos=[str(cargo.idMovimiento)],
        comision=Decimal('0.00'),
        comisionIVA=Decimal('0.00'),
        conceptos_texto=f"Publicidad: {publicidad.descripcion}"[:200],
        url_regreso=url_listado,
    )

    if pasarela == 'mercadopago':
        from routes.pagos_mp import crear_pago_cliente_mp
        url_pago, error = crear_pago_cliente_mp(**datos_pago)
        if error:
            flash(error, "danger")
            return redirect(url_listado)
        return redirect(url_pago, code=303)

    checkout_session, error = _crear_sesion_pago_cliente(**datos_pago)

    if error:
        flash(error, "danger")
        return redirect(url_listado)

    return redirect(checkout_session.url, code=303)

@publicidad_bp.route('/publicidad_app')
def publicidad_app():
    """Devuelve las publicaciones del cliente para la aplicación móvil."""
    id_cliente = session.get('idCliente')
    if not id_cliente:
        return jsonify({'ok': False, 'msg': 'No autorizado'}), 401

    publicidad = Publicidad.query.filter_by(idCliente=id_cliente).order_by(Publicidad.fechaCreacion.desc()).all()
    return jsonify({
        'ok': True,
        'publicidad': [{
            'idPublicidad': publicidad.idPublicidad,
            'descripcion': publicidad.descripcion,
            'imagen': (
                f"https://www.citanet.com.mx{publicidad.imagen}"
                if publicidad.imagen and publicidad.imagen.startswith('/')
                else publicidad.imagen
            ),
            'urlPublicidad': publicidad.urlPublicidad or '',
            'activo': bool(publicidad.activo),
            'validoPorCitanet': bool(publicidad.valido_por_citanet),
            'fechaInicioVigencia': publicidad.fechaInicioVigencia.isoformat() if publicidad.fechaInicioVigencia else '',
            'fechaFinVigencia': publicidad.fechaFinVigencia.isoformat() if publicidad.fechaFinVigencia else '',
            'pagado': bool(publicidad.movCuenta and publicidad.movCuenta.saldo <= 0),
        } for publicidad in publicidad]
    })

@publicidad_bp.route('/publicidad/nuevo_app', methods=['GET'])
def nueva_publicidad_app():
    if not es_cliente():
        return jsonify({'ok': False, 'msg': 'No autorizado'}), 401

    id_cliente = session.get('idCliente')
    id_empresa = session.get('idEmpresa')
    compra = CompraPublicidad.query.filter(
        CompraPublicidad.idCliente == id_cliente,
        CompraPublicidad.cantidadUsada < CompraPublicidad.cantidadPermitida
    ).order_by(CompraPublicidad.fechaCompra.desc()).first()

    paquetes = Producto.query.filter_by(idEmpresa=1, activo=True, tipo='producto').all()
    return jsonify({
        'ok': True,
        'compraDisponible': {
            'idCompraPublicidad': compra.idCompraPublicidad,
            'publicidadRestantes': compra.cantidadPermitida - compra.cantidadUsada,
        } if compra else None,
        'paquetes': [{
            'idProducto': producto.idProducto,
            'nombre': producto.nombre,
            'descripcion': producto.descripcion or '',
            'costo': float(producto.costo),
            'cantidadPublicidad': producto.configuracion_publicidad.cantidadPublicidad if producto.configuracion_publicidad else 1,
            'diasVigencia': producto.configuracion_publicidad.diasVigencia if producto.configuracion_publicidad else 30,
        } for producto in paquetes],
        'idEmpresa': id_empresa,
    })

@publicidad_bp.route('/publicidad/comprar_app', methods=['POST'])
def comprar_publicidad_app():
    if not es_cliente():
        return jsonify({'ok': False, 'msg': 'No autorizado'}), 401

    data = request.get_json(silent=True) or {}
    producto = Producto.query.filter_by(
        idProducto=data.get('idProducto'), idEmpresa=1, activo=True, tipo='producto'
    ).first()
    id_cliente = session.get('idCliente')
    id_empresa = session.get('idEmpresa')
    if not producto or not id_cliente or not id_empresa:
        return jsonify({'ok': False, 'msg': 'El paquete seleccionado no es válido.'}), 400

    config_paquete = producto.configuracion_publicidad
    try:
        movimiento = generar_movCuenta_Cliente(
            idEmpresa=1,
            idCliente=id_cliente,
            idtipoMovimiento=const.MOV_COMPRA,
            idMovReferencia=producto.idProducto,
            monto=float(producto.costo),
            idUsuario=session.get('idUsuario'),
            notas=f"Cargo por compra de publicidad: {producto.nombre}"
        )
        db.session.flush()
        compra = CompraPublicidad(
            idMovimiento=movimiento.idMovimiento,
            idProducto=producto.idProducto,
            idEmpresa=id_empresa,
            idCliente=id_cliente,
            cantidadPermitida=config_paquete.cantidadPublicidad if config_paquete else 1,
            cantidadUsada=0,
            diasVigencia=config_paquete.diasVigencia if config_paquete else 30,
        )
        db.session.add(compra)
        db.session.commit()
        return jsonify({'ok': True, 'idCompraPublicidad': compra.idCompraPublicidad})
    except Exception as error:
        db.session.rollback()
        logger.error(f"Error al generar compra de publicidad móvil: {error}")
        return jsonify({'ok': False, 'msg': 'No se pudo generar el cargo del paquete.'}), 500

@publicidad_bp.route('/publicidad/guardar_app', methods=['POST'])
def guardar_publicidad_app():
    if not es_cliente():
        return jsonify({'ok': False, 'msg': 'No autorizado'}), 401

    id_cliente = session.get('idCliente')
    id_empresa = session.get('idEmpresa')
    id_compra = request.form.get('idCompraPublicidad', type=int)
    compra = CompraPublicidad.query.filter_by(
        idCompraPublicidad=id_compra, idCliente=id_cliente, idEmpresa=id_empresa
    ).first()
    if not compra or compra.cantidadUsada >= compra.cantidadPermitida:
        return jsonify({'ok': False, 'msg': 'No tienes publicaciones disponibles. Compra un paquete.'}), 400

    descripcion = (request.form.get('descripcion') or '').strip()
    if not descripcion:
        return jsonify({'ok': False, 'msg': 'Escribe una descripción para la publicidad.'}), 400

    imagen = request.files.get('imagen')
    if not imagen or not imagen.filename:
        return jsonify({'ok': False, 'msg': 'Selecciona una imagen para la publicidad.'}), 400

    try:
        ruta_dir = 'static/publicidad/global'
        os.makedirs(ruta_dir, exist_ok=True)
        nombre_archivo = secure_filename(imagen.filename)
        ruta_full = os.path.join(ruta_dir, nombre_archivo)
        imagen.save(ruta_full)

        publicidad = Publicidad(
            idEmpresa=id_empresa,
            idCliente=id_cliente,
            imagen=f'/{ruta_full}',
            descripcion=descripcion,
            urlPublicidad=(request.form.get('url') or '').strip(),
            activo=True,
            valido_por_citanet=False,
            fechaCreacion=datetime.now(),
            fechaInicioVigencia=datetime.now().date(),
            fechaFinVigencia=datetime.now().date() + timedelta(days=compra.diasVigencia),
            idCompraPublicidad=compra.idCompraPublicidad,
            idMovimiento=compra.idMovimiento,
        )
        db.session.add(publicidad)
        compra.cantidadUsada += 1
        db.session.commit()
        return jsonify({'ok': True, 'msg': 'Publicidad enviada a revisión.'})
    except Exception as error:
        db.session.rollback()
        logger.error(f"Error al guardar publicidad móvil: {error}")
        return jsonify({'ok': False, 'msg': 'No se pudo guardar la publicidad.'}), 500

@publicidad_bp.route("/publicidad/nueva")
def nueva_publicidad():
    if not puede_acceder():
        abort(403)

    es_super = session.get("tipoUsuario") == "superuser"
    id_compra_pendiente = session.get('idCompraPublicidadPendiente')
    compra = CompraPublicidad.query.get(id_compra_pendiente) if id_compra_pendiente else None

    # Si la compra en sesión ya agotó su cupo, la sesión quedó desactualizada: la limpiamos.
    if compra and compra.cantidadUsada >= compra.cantidadPermitida:
        session.pop('idCompraPublicidadPendiente', None)
        session.pop('metodoPagoPublicidadPendiente', None)
        compra = None

    # Si no hay nada en sesión (p.ej. cerraron el navegador a medias), buscamos si les queda
    # una compra propia con cupo sin usar antes de pedirles comprar otra vez.
    if not compra and not es_super:
        id_cliente_sesion_busqueda = session.get('idCliente')
        id_empresa_sesion_busqueda = session.get('idEmpresa')
        query_compra = CompraPublicidad.query.filter(CompraPublicidad.cantidadUsada < CompraPublicidad.cantidadPermitida)
        if id_cliente_sesion_busqueda:
            query_compra = query_compra.filter_by(idCliente=id_cliente_sesion_busqueda)
        else:
            query_compra = query_compra.filter_by(idEmpresa=id_empresa_sesion_busqueda, idCliente=None)
        compra = query_compra.order_by(CompraPublicidad.fechaCompra.desc()).first()
        if compra:
            session['idCompraPublicidadPendiente'] = compra.idCompraPublicidad

    if not es_super and not compra:
        flash("Primero debes comprar un paquete de publicaciones.", "info")
        return redirect(url_for('publicidad.solicitar_compra'))

    publicidad_restantes = (compra.cantidadPermitida - compra.cantidadUsada) if compra else None

    return render_template(
        "publicidad_form.html",
        modo="nuevo",
        id_compra_pendiente=compra.idCompraPublicidad if compra else None,
        publicidad_restantes=publicidad_restantes
    )

@publicidad_bp.route("/publicidad/editar/<int:idPublicidad>")
def editar_publicidad(idPublicidad):
    if not puede_acceder():
        abort(403)
    
    publicidad = Publicidad.query.get_or_404(idPublicidad)

    if es_cliente() and publicidad.idCliente != session.get("idCliente"):
        abort(403)

    return render_template("publicidad_form.html", publicidad=publicidad, modo="editar")

@publicidad_bp.route("/publicidad/eliminar/<int:idPublicidad>")
def eliminar_publicidad(idPublicidad):
    if not puede_acceder():
        abort(403)
    
    publicidad = Publicidad.query.get_or_404(idPublicidad)

    if es_cliente() and publicidad.idCliente != session.get("idCliente"):
        abort(403)

    # publicidad.idMovimiento apunta al mismo cargo que CompraPublicidad.idMovimiento:
    # es el cargo del PAQUETE completo, compartido por todas las publicidades que
    # salgan de esa compra (ya creadas o futuras), así que no se toca movCuenta para
    # nada. Solo se devuelve el cupo consumido, igual que al rechazar una publicidad,
    # para que ese cupo se pueda usar de nuevo en otra publicidad más adelante.
    if publicidad.idCompraPublicidad:
        compra = CompraPublicidad.query.get(publicidad.idCompraPublicidad)
        if compra and compra.cantidadUsada > 0:
            compra.cantidadUsada -= 1

    # Borrado de imagen física en servidor
    if publicidad.imagen:
        fs_path = publicidad.imagen.lstrip('/')
        if os.path.exists(fs_path):
            try:
                os.remove(fs_path)
            except Exception as e:
                print(f"Error al borrar archivo físico: {e}")

    db.session.delete(publicidad)
    db.session.commit()
    return redirect(url_for('publicidad.listar_publicidad'))

@publicidad_bp.route("/publicidad/guardar", methods=["POST"])
def guardar_publicidad():     
    if not puede_acceder():
        return redirect(config.URL_BASE)

    id_empresa_sesion = session.get("idEmpresa")
    id_cliente_sesion = session.get("idCliente")
    es_super          = session.get("tipoUsuario") == "superuser"
    es_cli            = es_cliente()

    descripcion       = request.form.get("descripcion")
    
    f_inicio_raw      = request.form.get("fechaInicioVigencia")
    f_fin_raw         = request.form.get("fechaFinVigencia")
    url_final         = request.form.get("url")
    
    public_activo     = True if request.form.get("activo") else False
    valido_cita       = True if request.form.get("valido_por_citanet") else False
    
    file = request.files.get("imagen")
    ruta_imagen_final = None

    if file and file.filename != '':
        nombre_archivo = secure_filename(file.filename)
        
        ruta_dir = "static/publicidad/global"
        os.makedirs(ruta_dir, exist_ok=True)
        ruta_full = os.path.join(ruta_dir, nombre_archivo)
        file.save(ruta_full)
        
        ruta_imagen_final = f"/{ruta_full}"
    else:
        ruta_imagen_final = request.form.get("imagen_actual")

    if not descripcion:
        return "Falta la descripción", 400
    
    if not ruta_imagen_final:
        return "Falta la imagen", 400


    def parse_date(date_str):
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None

    f_inicio = parse_date(f_inicio_raw) or datetime.now().date()
    f_fin    = parse_date(f_fin_raw) or (datetime.now() + timedelta(days=10)).date()

    if not url_final:
        url_final = ""

    id_publicidad = request.form.get("idPublicidad")
    publicidad_obj = None

    if id_publicidad:
        publicidad_obj = Publicidad.query.get(id_publicidad)
        if es_cli and publicidad_obj and publicidad_obj.idCliente != id_cliente_sesion:
            abort(403)

    if publicidad_obj:
        estaba_inactivo = not publicidad_obj.activo

        publicidad_obj.imagen = ruta_imagen_final
        publicidad_obj.descripcion = descripcion
        publicidad_obj.urlPublicidad = url_final
        publicidad_obj.activo = public_activo
        publicidad_obj.valido_por_citanet = valido_cita if es_super else False

        if not es_super and estaba_inactivo and public_activo and not publicidad_obj.idCompraPublicidad:
            query_compra = CompraPublicidad.query.filter(CompraPublicidad.cantidadUsada < CompraPublicidad.cantidadPermitida)
            if es_cli:
                query_compra = query_compra.filter_by(idCliente=id_cliente_sesion)
            else:
                query_compra = query_compra.filter_by(idEmpresa=id_empresa_sesion, idCliente=None)
            compra_disponible = query_compra.order_by(CompraPublicidad.fechaCompra.desc()).first()

            if compra_disponible:
                publicidad_obj.idCompraPublicidad = compra_disponible.idCompraPublicidad
                publicidad_obj.idMovimiento = compra_disponible.idMovimiento
                compra_disponible.cantidadUsada += 1
            else:
                publicidad_obj.activo = False
                flash("No tienes cupo disponible de ningún paquete para reactivar esta publicidad. Compra un paquete nuevo.", "error")
        nuevo = publicidad_obj
    else:
        id_compra_form = request.form.get("idCompraPublicidad")
        compra_obj = None

        if id_compra_form:
            compra_obj = CompraPublicidad.query.get(id_compra_form)

            if not compra_obj:
                return "La compra asociada a esta publicidad no es válida", 400

            # Verificar que la compra pertenece a la sesión actual (cliente o empresa)
            if es_cli and compra_obj.idCliente != id_cliente_sesion:
                abort(403)
            if not es_cli and compra_obj.idEmpresa != id_empresa_sesion:
                abort(403)

            if compra_obj.cantidadUsada >= compra_obj.cantidadPermitida:
                flash("Ya usaste todas las publicaciones incluidas en este paquete.", "error")
                return redirect(url_for('publicidad.listar_publicidad'))

        elif not es_super:
            # Nadie más que superuser puede crear una publicidad sin una compra ligada
            flash("Primero debes comprar un paquete de publicidad.", "error")
            return redirect(url_for('publicidad.solicitar_compra'))

        # Si viene de un paquete y no se eligió fecha fin manualmente, usamos los días de vigencia del paquete
        if compra_obj and not f_fin_raw:
            f_fin = f_inicio + timedelta(days=compra_obj.diasVigencia)

        nuevo = Publicidad(
            idEmpresa=id_empresa_sesion,
            idCliente=id_cliente_sesion if es_cli else None,
            imagen="/" + ruta_imagen_final if not ruta_imagen_final.startswith("/") else ruta_imagen_final,
            descripcion=descripcion,
            urlPublicidad=url_final,  
            activo=public_activo,
            valido_por_citanet=valido_cita if es_super else False,
            fechaCreacion=datetime.now(),
            fechaInicioVigencia=f_inicio,
            fechaFinVigencia=f_fin,
            idCompraPublicidad=compra_obj.idCompraPublicidad if compra_obj else None,
            idMovimiento=compra_obj.idMovimiento if compra_obj else None
        )
        db.session.add(nuevo)

        if compra_obj:
            compra_obj.cantidadUsada += 1
    
    db.session.flush()

    if not es_super:
        if es_cli:
            nombre_creador = session.get("nombreCliente") or "Cliente Registrado"
            texto_creador = f"El Cliente (<strong>{nombre_creador}</strong>)"
        else:
            empresa = Empresa.query.get(id_empresa_sesion)
            texto_creador = empresa.razonSocial if empresa else "Empresa Disconocida"

        url_imagen_absoluta    = f"https://www.citanet.com.mx{nuevo.imagen}"
        url_aceptar_publicidad    = f"https://www.citanet.com.mx/publicidad/procesar?idPublicidad={nuevo.idPublicidad}&accion=aceptar"
        url_no_aceptar_publicidad = f"https://www.citanet.com.mx/publicidad/procesar?idPublicidad={nuevo.idPublicidad}&accion=rechazar"

        empresa_citanet = Empresa.query.filter_by(idEmpresa=const.ID_EMPRESA_CITANET).first()
        correo_destino = empresa_citanet.correoContacto if empresa_citanet else ""
        asunto_correo = "Validación de Publicación CitaNet"

        cuerpo_html = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
        </head>
        <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 0;">
            <div style="max-width: 600px; margin: 20px auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: 1px solid #e2e8f0;">
                <div style="background-color: #0f172a; padding: 25px; text-align: center;">
                    <h2 style="color: #5bbfa6; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px;">CITANET</h2>
                </div>
                <div style="padding: 30px;">
                    <p style="margin-top: 0; font-size: 16px;">Equipo de <strong>CitaNet</strong>,</p>
                    <p style="font-size: 15px;">{texto_creador} creó una nueva publicación.</p>

                    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 15px; margin: 20px 0;">
                        <p style="margin: 0 0 10px 0; font-size: 14px; color: #64748b;"><strong>Descripción proporcionada:</strong></p>
                        <p style="margin: 0; font-size: 15px; font-style: italic; color: #1e293b;">"{descripcion}"</p>
                    </div>

                    <p style="font-size: 14px; color: #64748b; margin-bottom: 10px;"><strong>Vista previa de la imagen cargada:</strong></p>
                    <div style="text-align: center; margin-bottom: 25px; background: #0f172a; padding: 10px; border-radius: 6px;">
                        <img src="{url_imagen_absoluta}" alt="Imagen de la Publicación" style="max-width: 100%; height: auto; border-radius: 4px; max-height: 250px; object-fit: contain;">
                    </div>

                    <div style="text-align: center; margin-top: 25px; margin-bottom: 10px;">
                        <a href="{url_aceptar_publicidad}" style="background-color: #5bbfa6; color: #0f172a; padding: 12px 30px; text-decoration: none; font-size: 15px; font-weight: bold; border-radius: 6px; display: inline-block; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            Aceptar Publicidad (Publicar)
                        </a>
                    </div>
                    <div style="text-align: center; margin-top: 25px; margin-bottom: 10px;">
                        <a href="{url_no_aceptar_publicidad}" style="background-color: #5bbfa6; color: #0f172a; padding: 12px 30px; text-decoration: none; font-size: 15px; font-weight: bold; border-radius: 6px; display: inline-block; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            No Aceptar Publicidad (Rechazar)
                        </a>
                    </div>
                </div>
                <div style="background-color: #f8fafc; padding: 20px; text-align: center; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8;">
                    Atentamente,<br>
                    <strong>Equipo de Operaciones CitaNet</strong><br>
                    <span style="display: inline-block; margin-top: 5px;">Este es un mensaje automático de control del sistema.</span>
                </div>
            </div>
        </body>
        </html>
        """
        enviar_correo_base(correo_destino, asunto_correo, cuerpo_html, es_html=True)

        # Avisar por WhatsApp a CitaNet usando la instancia de la empresa 1.
        if empresa_citanet and empresa_citanet.telefono:
            mensaje_whatsapp = (
                f"Nueva publicidad pendiente de validación en CitaNet.\n"
                f"Origen: {texto_creador.replace('<strong>', '').replace('</strong>', '')}\n"
                f"Descripción: {descripcion}\n"
                f"Revisar: {url_aceptar_publicidad}"
            )
            try:
                enviado, detalle = enviar_whatsapp(
                    numero=empresa_citanet.telefono,
                    mensaje=mensaje_whatsapp,
                    idEmpresaEnvia=const.ID_EMPRESA_CITANET
                )
                if not enviado:
                    logger.warning(f"No se pudo enviar aviso WhatsApp de publicidad: {detalle}")
            except Exception as whatsapp_error:
                logger.error(f"Error enviando aviso WhatsApp de publicidad: {whatsapp_error}")
        
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al guardar publicidad: {str(e)}")
        return "Error interno al guardar en la base de datos", 500

    id_compra_pendiente = session.get('idCompraPublicidadPendiente')
    metodo_pago_pendiente = session.get('metodoPagoPublicidadPendiente')

    if id_compra_pendiente and str(id_compra_pendiente) == request.form.get("idCompraPublicidad"):
        compra_actualizada = CompraPublicidad.query.get(id_compra_pendiente)

        if compra_actualizada and compra_actualizada.cantidadUsada < compra_actualizada.cantidadPermitida:
            restantes = compra_actualizada.cantidadPermitida - compra_actualizada.cantidadUsada
            flash(f"Publicidad guardada. Te quedan {restantes} publicidad(es) por crear de este paquete.", "info")
            return redirect(url_for('publicidad.nueva_publicidad'))

        # Cuota agotada: ya se puede limpiar la sesión y avanzar al pago (si aplica) o al listado
        session.pop('idCompraPublicidadPendiente', None)
        session.pop('metodoPagoPublicidadPendiente', None)

        if metodo_pago_pendiente == "linea":
            flash("Publicidad(s) guardada(s). Completa tu pago en línea para publicarlas.", "info")
            if es_cli:
                return redirect(url_for('pagos.listar_movimientos_cliente'))
            else:
                return redirect(url_for('pagos.listar_movimientos_empresa'))

    return redirect(url_for("publicidad.listar_publicidad"))

@publicidad_bp.route("/publicidad/procesar", methods=["GET"])
def procesar_publicidad():
    id_publicidad = request.args.get("idPublicidad")
    accion = request.args.get("accion")

    if not id_publicidad:
        return "Falta el ID de la publicidad", 400

    # Buscar la publicidad en la base de datos
    publicidad = Publicidad.query.get_or_404(id_publicidad)

    if accion == "rechazar":
        publicidad.activo = False
        publicidad.valido_por_citanet = False 

        # Devolver el cupo consumido: una publicacion rechazada no debe contar contra el paquete comprado
        if publicidad.idCompraPublicidad:
            compra_rechazo = CompraPublicidad.query.get(publicidad.idCompraPublicidad)
            if compra_rechazo and compra_rechazo.cantidadUsada > 0:
                compra_rechazo.cantidadUsada -= 1
            publicidad.idCompraPublicidad = None

        # Determinar destinatario y texto de presentación dinámicamente
        if publicidad.idCliente:
            # Si no tienes correo guardado directamente en la sesión o tabla de publicidad,
            # asegúrate de usar la variable/campo de correo correspondiente al cliente.
            correo_destino = getattr(publicidad, "correoCliente", "") 
            saludo_destinatario = f"Estimado(a) <strong>{getattr(publicidad, 'nombreCliente', 'Cliente')}</strong>,"
        else:
            # Si pertenece a una empresa
            empresa = Empresa.query.get(publicidad.idEmpresa)
            correo_destino = empresa.correoContacto if empresa else ""
            razon = empresa.razonSocial if empresa else ""
            saludo_destinatario = f"Estimado administrador de <strong>{razon}</strong>,"

        asunto_correo = "Estatus de tu Publicidad en CitaNet"
        
        cuerpo_html = f"""
            <!DOCTYPE html>
            <html lang="es">
            <head>
                <meta charset="UTF-8">
            </head>
            <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 0;">
                <div style="max-width: 600px; margin: 20px auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: 1px solid #e2e8f0;">
                    <div style="background-color: #0f172a; padding: 25px; text-align: center;">
                        <h2 style="color: #ef4444; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px;">CITANET</h2>
                    </div>
                    <div style="padding: 30px;">
                        <p style="margin-top: 0; font-size: 16px;">{saludo_destinatario}</p>
                        <p style="font-size: 15px; line-height: 1.6;">Te informamos que la publicación que registraste recientemente en nuestra plataforma ha sido revisada por el equipo de operaciones y <strong>no pudo ser aprobada</strong> para su publicación.</p>
                        
                        <div style="background-color: #fef2f2; border-left: 4px solid #ef4444; border-radius: 4px; padding: 15px; margin: 20px 0;">
                            <p style="margin: 0 0 5px 0; font-size: 14px; color: #991b1b; font-weight: bold;">Motivo de la declinación:</p>
                            <p style="margin: 0; font-size: 14px; color: #7f1d1d; line-height: 1.5;">
                                La imagen cargada incumple con las políticas de contenido, dimensiones o calidad requeridas por el sistema CitaNet.
                            </p>
                        </div>

                        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 15px; margin: 20px 0;">
                            <p style="margin: 0 0 5px 0; font-size: 13px; color: #64748b;"><strong>Detalles de la publicidad rechazada:</strong></p>
                            <p style="margin: 0; font-size: 14px; color: #1e293b;"><strong>Descripción:</strong> {publicidad.descripcion}</p>
                        </div>

                        <p style="font-size: 15px; line-height: 1.6;">Te invitamos a ingresar nuevamente a tu panel de administración, verificar que la imagen cumpla con el formato adecuado y volver a enviar tu solicitud de alta.</p>
                        
                        <div style="text-align: center; margin-top: 30px; margin-bottom: 10px;">
                            <a href="https://www.citanet.com.mx" style="background-color: #0f172a; color: #ffffff; padding: 12px 30px; text-decoration: none; font-size: 14px; font-weight: bold; border-radius: 6px; display: inline-block;">
                                Ir a Mi Panel de Control
                            </a>
                        </div>
                    </div>
                    <div style="background-color: #f8fafc; padding: 20px; text-align: center; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8;">
                        Este es un mensaje automático del sistema de control de contenidos.<br>
                        Si tienes dudas sobre las dimensiones o lineamientos de imágenes, por favor contacta a soporte.<br>
                        <strong>Equipo de Operaciones CitaNet</strong>
                    </div>
                </div>
            </body>
            </html>
            """
        enviar_correo_base(correo_destino, asunto_correo, cuerpo_html, es_html=True)

    else:
        # Actualizar los campos automáticamente: la vigencia empieza a contar desde que se aprueba
        hoy = datetime.now().date()
        dias_vigencia = 30  # valor por defecto solo si la publicidad no viene de un paquete comprado

        if publicidad.idCompraPublicidad:
            compra_aceptar = CompraPublicidad.query.get(publicidad.idCompraPublicidad)
            if compra_aceptar:
                dias_vigencia = compra_aceptar.diasVigencia

        publicidad.fechaInicioVigencia = hoy
        publicidad.fechaFinVigencia    = hoy + timedelta(days=dias_vigencia)
        publicidad.activo              = True
        publicidad.valido_por_citanet  = True

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al {accion} publicidad {id_publicidad}: {str(e)}")
        return f"Error interno al procesar la {accion}", 500

    # Redirige directo a la página principal de CitaNet o confirmación
    return redirect(config.URL_BASE)

@publicidad_bp.route('/comprar-publicidad', methods=['GET'])
def solicitar_compra():
    if not puede_acceder():
        return redirect(config.URL_BASE)

    id_empresa = session.get('idEmpresa')
    paquetes = Producto.query.filter_by(
        idEmpresa=1, 
        activo=True, 
        tipo='producto'
    ).all()
    
    return render_template('comprar_publicidad.html', paquetes=paquetes)

@publicidad_bp.route('/publicidad/procesar_solicitud', methods=['POST'])
def procesar_solicitud():
    if not puede_acceder():
        return redirect(config.URL_BASE)

    metodo_pago = request.form.get('metodo_pago')
    id_producto = request.form.get('idProducto')

    # Identificar la sesión y extraer las llaves foráneas requeridas
    id_usuario = session.get('idUsuario')
    id_empresa = session.get('idEmpresa')
    id_cliente = session.get('idCliente')

    if not id_producto:
        flash("Debes seleccionar un paquete.", "error")
        return redirect(url_for('publicidad.solicitar_compra'))

    producto = Producto.query.get(id_producto)
    if not producto:
        flash("El paquete seleccionado no es válido.", "error")
        return redirect(url_for('publicidad.solicitar_compra'))

    monto = float(producto.costo)

    # Config del paquete: cuántas publicaciones incluye y cuántos días de vigencia por defecto.
    # Si el producto no tiene configuración (paquetes viejos o de otro tipo), se asume 1 publicación / 30 días.
    config_paquete = producto.configuracion_publicidad
    cantidad_publicidad = config_paquete.cantidadPublicidad if config_paquete else 1
    dias_vigencia = config_paquete.diasVigencia if config_paquete else 30

    try:
        if id_cliente:
            nuevo_movimiento = generar_movCuenta_Cliente(
                idEmpresa=1,
                idCliente=id_cliente,
                idtipoMovimiento=const.MOV_COMPRA,
                idMovReferencia=producto.idProducto,
                monto=monto,
                idUsuario=id_usuario,
                notas=f"Cargo por compra de publicidad: {producto.nombre}"
            )
        elif id_empresa:
            nuevo_movimiento = generar_movCuenta_Empresa(
                idEmpresa=id_empresa,
                idtipoMovimiento=const.MOV_COMPRA,
                idMovReferencia=producto.idProducto,
                monto=monto,
                idUsuario=id_usuario,
                notas=f"Cargo por compra de publicidad: {producto.nombre}"
            )
        else:
            flash("Error: No se pudo identificar la sesión para procesar el cargo.", "error")
            return redirect(url_for('publicidad.solicitar_compra'))

        db.session.flush()  # asegura que nuevo_movimiento.idMovimiento ya tenga valor

        nueva_compra = CompraPublicidad(
            idMovimiento=nuevo_movimiento.idMovimiento,
            idProducto=producto.idProducto,
            idEmpresa=id_empresa,
            idCliente=id_cliente,
            cantidadPermitida=cantidad_publicidad,
            cantidadUsada=0,
            diasVigencia=dias_vigencia
        )
        db.session.add(nueva_compra)

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al generar el cargo por compra de publicidad: {str(e)}")
        flash("Ocurrió un error al registrar el cargo. Intenta de nuevo.", "error")
        return redirect(url_for('publicidad.solicitar_compra'))

    # Guardamos la compra (y el método de pago elegido) en sesión para poder ligarla
    # a las publicaciones que se creen a continuación, y para saber a dónde mandar al usuario
    # cuando se agote la cuota: a pagar en línea, o directo al listado.
    session['idCompraPublicidadPendiente'] = nueva_compra.idCompraPublicidad
    session['metodoPagoPublicidadPendiente'] = metodo_pago

    if metodo_pago == "linea":
        flash(f"Cargo registrado. Completa los datos de tu(s) {cantidad_publicidad} publicacion(es); después te llevaremos a pagarlo en línea.", "info")
    else:
        flash(f"Cargo registrado en tu Estado de Cuenta. Ahora completa los datos de tu(s) {cantidad_publicidad} publicacion(es).", "info")

    return redirect(url_for('publicidad.nueva_publicidad'))