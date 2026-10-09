import uuid
import logging
import random
import os

from datetime           import date, datetime, timedelta
from flask              import flash, Blueprint, current_app, render_template, request, redirect, session, url_for, jsonify
from werkzeug.security  import generate_password_hash
from werkzeug.utils     import secure_filename
from modelos            import (Publicidad, Cita, CitaCliente, CitaPregunta, CitaProducto,
                                 ConfiguracionPaquetePublicidad, ConfiguracionWhatsapp,
                                 EstatusEmpresa, FilaEspera, Frase, HistorialCita,
                                 ClienteEmpresa, ClienteStaff, PreguntaServicio, Producto,
                                 ProductoUsuario, db, Empresa, CodigoTelefono, Usuario,
                                 tipoEmpresa, ColorEstatusCitaEmpresa, Plan, EmpresaPlan,
                                 movCuenta, movAplica, MovimientoPuntos, Vendedor,
                                 VendedorEmpresa, PagoComisionVendedor, Config,
                                 CompraPublicidad, Comunicado, ComunicadoLeido)
from correo             import enviar_correo, enviar_correo_base
#from sms_mx             import enviar_codigo_sms
from decimal            import Decimal
from constantes         import const

logger = logging.getLogger(__name__)

# Configuración del Blueprint
empresas_bp = Blueprint("empresas", __name__)

# Diccionario para validar tokens en memoria antes del registro final
tokens_verificacion = {}


def _aplicar_mp_desde_form(empresa, form):
    """Copia al objeto Empresa la configuración de Mercado Pago del formulario.
    mp_vinculado queda en True solo si hay access token y public key.
    mp_refresh_token no se toca: era del flujo OAuth anterior y aquí no se captura."""
    token  = (form.get("mp_access_token") or "").strip() or None
    public = (form.get("mp_public_key") or "").strip() or None
    uid    = (form.get("mp_user_id") or "").strip() or None

    empresa.aceptaPagosEnLinea_MP = True if form.get("aceptaPagosEnLinea_MP") else False
    empresa.mp_access_token = token
    empresa.mp_public_key   = public
    empresa.mp_user_id      = uid
    empresa.mp_vinculado    = bool(token and public)


def _sumar_meses(fecha_base, meses):
    if meses <= 0:
        return None
    anio = fecha_base.year + (fecha_base.month - 1 + meses) // 12
    mes = (fecha_base.month - 1 + meses) % 12 + 1
    dia = min(fecha_base.day, 28)
    return date(anio, mes, dia)


def _resolver_vendedor_referente(ref=None, id_vendedor=None):
    ref = (ref or '').strip()
    if id_vendedor:
        try:
            return Vendedor.query.get(int(id_vendedor))
        except (TypeError, ValueError):
            pass

    if not ref:
        return None

    return Vendedor.query.filter_by(codigoReferido=ref).filter_by(activo=True).first()


@empresas_bp.route("/registrar_empresa")
def registrar_empresa():
    plan_seleccionado = request.args.get('plan', type=int)
    ref = request.args.get('ref') or request.args.get('codigo') or request.args.get('codigoReferido') or request.args.get('codigoVendedor')
    id_vendedor = request.args.get('idVendedor', type=int) or session.get('idVendedor')
    vendedor = _resolver_vendedor_referente(ref=ref, id_vendedor=id_vendedor)
    
    tipos_lista = tipoEmpresa.query.all()
    planes_activos = Plan.query.filter_by(estatusPlan='activo').all()
    return render_template(
        "registrar_empresa.html",
        tipos=tipos_lista,
        planes=planes_activos,
        plan_id=plan_seleccionado,
        idVendedor=vendedor.idVendedor if vendedor else None,
        vendedor=vendedor,
        ref=ref,
        empresa=None,
    )

@empresas_bp.route("/enviar_token_email", methods=["POST"])
def enviar_token_email():
    try:
        data = request.get_json()
        correo = data.get('valor')
        
        if not correo:
            return jsonify({"success": False, "message": "Correo requerido"}), 400

        # Generamos código de 4 dígitos para el correo
        codigo = str(random.randint(1000, 9999))
        
        # Enviamos el correo
        enviar_correo(correo, f"Tu código de validación CitaNet es: {codigo}")
        
        # Guardamos en sesión para validar en el siguiente paso
        session[f"token_email_{correo}"] = codigo
        
        logger.info(f"Token Email enviado a {correo}: {codigo}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error en enviar_token_email: {e}")
        return jsonify({"success": False, "message": "Error al enviar correo"}), 500

@empresas_bp.route("/verificar_token", methods=["POST"])
def verificar_token():
    try:
        data = request.get_json()
        tipo = data.get('tipo')
        valor = data.get('valor')
        codigo_ingresado = data.get('codigo')

        if not all([tipo, valor, codigo_ingresado]):
            return jsonify({"success": False, "message": "Datos incompletos"}), 400

        if tipo == 'sms':
            # Verificación de 6 dígitos usando tabla CodigoTelefono
            registro = CodigoTelefono.query.filter(
                CodigoTelefono.telefono == valor,
                CodigoTelefono.codigo == codigo_ingresado,
                CodigoTelefono.expiracion > datetime.now()
            ).first()

            if registro:
                return jsonify({"success": True})
            else:
                return jsonify({"success": False, "message": "Código de SMS incorrecto o expirado"})

        elif tipo == 'email':
            # Verificación de 4 dígitos usando la sesión
            codigo_guardado = session.get(f"token_email_{valor}")
            
            if codigo_guardado and codigo_guardado == codigo_ingresado:
                return jsonify({"success": True})
            else:
                return jsonify({"success": False, "message": "Código de correo incorrecto"})

        return jsonify({"success": False, "message": "Tipo de validación no reconocido"}), 400

    except Exception as e:
        logger.error(f"Error en verificar_token: {e}")
        return jsonify({"success": False, "message": "Error interno al verificar"}), 500

@empresas_bp.route("/registrar_negocio_publico", methods=["POST"])
def registrar_negocio_publico():
    
    #logger.info("Iniciando proceso de registro público de negocio")
    #logger.error(f"request.form: {request.form}")

    # 1. Datos Generales (Asegúrate que coincidan con el 'name' de tus inputs en el HTML)
    razon_social = request.form.get("razonSocial")
    url_empresa  = request.form.get("url_empresa")
    id_tipo      = request.form.get("idtipoEmpresa")
    correo       = request.form.get("correoContacto")
    tel          = request.form.get("telefono")
    contacto_nombre = request.form.get("contacto")
    
    # 2. Acceso (Usuario Administrador)
    nombre_admin = request.form.get("nombreUsuario")
    user_login   = request.form.get("usuario")
    password     = request.form.get("password")

    # 3. Fiscal
    rfc          = request.form.get("rfc")
    fisica_moral = request.form.get("fisicaMoral")
    direccion    = request.form.get("direccion")
    
    cp = request.form.get("codigoPostal")
    cp = int(cp) if cp and cp.strip() else None
    regimen = request.form.get("regimenFiscal")
    regimen = int(regimen) if regimen and regimen.strip() else None

    # 4. Etiquetas Personalizadas
    etiqueta_colaborador = request.form.get("etiquetaColaborador")
    etiqueta_cliente = request.form.get("etiquetaCliente")
    
    # 5. Misión, Visión y PLAN SELECCIONADO
    mision  = request.form.get("mision")
    vision  = request.form.get("vision")
    id_plan = request.form.get("idPlan") 
    
    stripe_secret      = request.form.get('stripe_secret_key')
    stripe_publishable = request.form.get('stripe_publishable_key')
    stripe_webhook     = request.form.get('stripe_webhook_secret')
    stripe_account     = request.form.get('stripe_account_id')
    comisionVarPct     = request.form.get('comisionVarPct')
    comisionFija       = request.form.get('comisionFija')

    if not id_plan:
        logger.error(f"No se seleccionó un plan para la nueva empresa {razon_social}")
        return f"Seleccione un plan arriba", 500
    
    frecuenciaPago_new = request.form.get("frecuenciaPago") or 'mensual'

    try:
        empresa = Empresa()
        empresa.slug = str(uuid.uuid4())[:8]
        empresa.razonSocial = razon_social
        empresa.url_empresa = url_empresa
        
        empresa.idtipoEmpresa = id_tipo
        empresa.correoContacto = correo
        empresa.telefono = tel
        empresa.contacto = contacto_nombre
        empresa.rfc = rfc
        empresa.fisicaMoral = fisica_moral
        empresa.direccion = direccion
        empresa.googleMapsUrl = request.form.get("googleMapsUrl")
        empresa.codigoPostal = cp
        empresa.regimenFiscal = regimen
        empresa.idEstatus = 1  # 1 suele ser Activo o Pendiente
        empresa.etiquetaColaborador = etiqueta_colaborador
        empresa.etiquetaCliente = etiqueta_cliente
        empresa.mision = mision
        empresa.vision = vision
        
        empresa.stripe_secret_key = stripe_secret
        empresa.stripe_publishable_key = stripe_publishable
        empresa.stripe_webhook_secret = stripe_webhook
        empresa.stripe_account_id = stripe_account
        empresa.comisionVarPct = comisionVarPct
        empresa.comisionFija = comisionFija
        _aplicar_mp_desde_form(empresa, request.form)

        # Procesamiento de Logo
        logo_file = request.files.get("Logo")
        if logo_file and logo_file.filename:
            filename = secure_filename(logo_file.filename)
            unique_filename = f"{empresa.slug}_{filename}"
            upload_folder = os.path.join(current_app.root_path, 'static', 'img', 'empresas')
            os.makedirs(upload_folder, exist_ok=True)
            logo_file.save(os.path.join(upload_folder, unique_filename))
            empresa.logo = f"img/empresas/{unique_filename}"

        db.session.add(empresa)
        db.session.flush() # Para obtener el idEmpresa generado

        # Vincular la empresa con el vendedor invitador si usó una liga o código válido.
        ref_usado = (
            request.form.get('ref')
            or request.form.get('codigoReferido')
            or request.form.get('codigoVendedor')
            or request.args.get('ref')
            or request.args.get('codigoReferido')
            or request.args.get('codigoVendedor')
            or ''
        ).strip()
        id_vendedor_ref = request.form.get('idVendedor') or session.get('idVendedor')
        if id_vendedor_ref:
            try:
                id_vendedor_ref = int(id_vendedor_ref)
            except (TypeError, ValueError):
                id_vendedor_ref = None

        vendedor_ref = _resolver_vendedor_referente(ref=ref_usado, id_vendedor=id_vendedor_ref)

        if ref_usado and not vendedor_ref:
            flash('El código de vendedor no es válido o no existe en el sistema.', 'danger')
            return redirect(url_for('empresas.registrar_empresa', ref=ref_usado, idVendedor=id_vendedor_ref))

        if vendedor_ref:
            empresa.idVendedor = vendedor_ref.idVendedor
            relacion_existente = VendedorEmpresa.query.filter_by(idVendedor=vendedor_ref.idVendedor, idEmpresa=empresa.idEmpresa).first()
            if not relacion_existente:
                nivel = vendedor_ref.nivel_comision
                porc = float(nivel.porcComision) if nivel and nivel.porcComision is not None else 0.0
                fecha_inicio = date.today()
                fecha_fin = None
                if nivel and getattr(nivel, 'periodoComisionMeses', None):
                    fecha_fin = _sumar_meses(fecha_inicio, int(nivel.periodoComisionMeses))

                relacion = VendedorEmpresa(
                    idVendedor=vendedor_ref.idVendedor,
                    idEmpresa=empresa.idEmpresa,
                    fechaInicioPeriodo=fecha_inicio,
                    fechaFinPeriodo=fecha_fin,
                    porcComision=porc,
                    comisionPagada=0.00,
                    activo=True,
                    estatus='activo',
                )
                db.session.add(relacion)
        elif ref_usado:
            flash('El código o liga de referido no es válido; la empresa quedará registrada como directa.', 'warning')

        # Crear Usuario Administrador
        usuario_admin = Usuario(
            idEmpresa=empresa.idEmpresa,
            usuario=user_login.upper() if user_login else 'ADMIN',
            nombreUsuario=nombre_admin,
            alias='Admin',
            password=generate_password_hash(password) if password else generate_password_hash('citanet'),
            tipoUsuario='admin',
            correo=correo, 
            telefono=tel)
        db.session.add(usuario_admin)
        db.session.flush()
        
        
        if frecuenciaPago_new == 'anual':
            costo_nuevo = Plan.query.get(int(id_plan)).costoAnual
            dias_vigencia = 365
        else:
            costo_nuevo = Plan.query.get(int(id_plan)).costoMensual
            dias_vigencia = 30
        
        # Crear registro en EmpresaPlan con el plan seleccionado
        if id_plan:
            empresa_plan = EmpresaPlan(
                idEmpresa=empresa.idEmpresa,
                idPlan=int(id_plan),
                fechaInicio=date.today(),
                fechaVencimiento=date.today() + timedelta(days=dias_vigencia),
                costo=costo_nuevo,
                remanente_plan_anterior=0.00,
                costo_plan=costo_nuevo,
                estatusPlan='demo',  # Inicia como demo hasta que se confirme el pago
                fechaRegistro=datetime.now()
            )
            db.session.add(empresa_plan)
            db.session.flush()  # Para obtener el idPlan generado
            
            if costo_nuevo != 0:
                notas = f"Registro inicial con plan {Plan.query.get(int(id_plan)).nombrePlan} ({frecuenciaPago_new}), costo ${costo_nuevo:,.2f}"    
                generar_movCuenta_Empresa(empresa.idEmpresa, const.MOV_PLAN, costo_nuevo, idMovReferencia=empresa_plan.idEmpresaPlan, idUsuario=usuario_admin.idUsuario, notas=notas, idmetodoPago=None)

        # Clonar colores base (ID 1 es la maestra)
        colores_base = ColorEstatusCitaEmpresa.query.filter_by(idEmpresa=1).all()
        for cb in colores_base:
            db.session.add(ColorEstatusCitaEmpresa(
                idEmpresa=empresa.idEmpresa,
                idEstatus=cb.idEstatus,
                color=cb.color
            ))

        # Bonificación de publicidad gratis por alta de empresa (si está configurada)
        otorgar_bonificacion_publicidad_empresa(empresa, idUsuario=usuario_admin.idUsuario)

        db.session.commit()
        
        # Limpiar tokens de sesión
        session.pop(f"token_email_{correo}", None)
        
        # Guardar en sesión para login automático o referencia
        session['idEmpresa']    = empresa.idEmpresa
        session['razonSocial']  = empresa.razonSocial
        session['slug']         = empresa.slug
        
        # Mandar correo de bienvenida al nuevo cliente
        # Definición del cuerpo en HTML
        cuerpo = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0;">
            <div style="max-width: 600px; margin: 20px auto; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
                <div style="background-color: #2c3e50; padding: 20px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0;">¡Bienvenido a CitaNet!</h1>
                </div>
                
                <div style="padding: 30px;">
                    <p style="font-size: 18px;">Hola <strong>{empresa.razonSocial}</strong>,</p>
                    <p>Es un gusto saludarte. Tu cuenta ha sido creada exitosamente. A continuación, te proporcionamos los accesos directos personalizados para tu empresa.</p>
                    
                    <div style="background-color: #f9f9f9; padding: 20px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #3498db;">
                        <p style="margin: 0; font-weight: bold; color: #2c3e50;">Credenciales de Administrador:</p>
                        <p style="margin: 10px 0 0 0;"><strong>Usuario:</strong> <span style="color: #3498db;">{usuario_admin.usuario}</span></p>
                    </div>

                    <h3 style="color: #2c3e50; border-bottom: 2px solid #f1f1f1; padding-bottom: 10px; margin-top: 25px;">Enlaces de Acceso Directo</h3>
                    <p style="font-size: 13px; color: #666;">Utiliza estos enlaces para entrar directamente a tu sistema. Puedes incorporarlos en tu sitio web o compartirlos con tu equipo de trabajo.</p>
                    
                    <div style="margin: 20px 0;">
                        <div style="margin-bottom: 15px; padding: 15px; border: 1px solid #d1d9e6; border-radius: 8px; background-color: #f8fbff;">
                            <p style="margin: 0 0 8px 0; font-size: 14px; color: #2c3e50;"><strong>💻 Portal para el Staff:</strong></p>
                            <a href="https://www.citanet.com.mx/e/{empresa.slug}?destino=usuario" style="color: #3498db; text-decoration: none; word-break: break-all; font-weight: bold; font-family: monospace;">
                                https://www.citanet.com.mx/e/{empresa.slug}?destino=usuario
                            </a>
                        </div>

                        <div style="padding: 15px; border: 1px solid #d1e6d9; border-radius: 8px; background-color: #f8fffb;">
                            <p style="margin: 0 0 8px 0; font-size: 14px; color: #2c3e50;"><strong>📱 Portal para Clientes:</strong></p>
                            <a href="https://www.citanet.com.mx/e/{empresa.slug}" style="color: #27ae60; text-decoration: none; word-break: break-all; font-weight: bold; font-family: monospace;">
                                https://www.citanet.com.mx/e/{empresa.slug}
                            </a>
                        </div>
                    </div>
                    
                    <p style="font-size: 14px;">Con estos enlaces, tú y tus clientes podrán ingresar directamente sin necesidad de seleccionar la empresa manualmente.</p>
                    
                    <div style="text-align: center; margin-top: 30px;">
                        <a href="https://www.citanet.com.mx/usuarios/login" style="background-color: #3498db; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                            Configurar Panel de Control
                        </a>
                    </div>
                </div>
                
                <div style="background-color: #f1f1f1; padding: 15px; text-align: center; font-size: 11px; color: #777;">
                    <p style="margin: 0;">&copy; 2026 CitaNet - Soluciones de Gestión Empresarial</p>
                    <p style="margin: 5px 0 0 0;">Este correo contiene información confidencial de acceso.</p>
                </div>
            </div>
        </body>
        </html>
        """

        # Envío del correo
        enviar_correo_base(correo, "¡Bienvenido a CitaNet!", cuerpo, correo_cliente=None, es_html=True)
                
        return redirect(url_for("usuarios.login", registro="exito"))

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error en registro público de negocio: {e}")
        return f"Error al procesar el registro: {str(e)}", 500


@empresas_bp.route("/admin/mi_empresa", methods=["GET", "POST"])
def mi_empresa():
    id_empresa = session.get("idEmpresa")
    
    if not id_empresa:
        return redirect(url_for('usuarios.login'))
    
    #hoy = datetime.now().date()
    plan_actual = EmpresaPlan.query.filter(
        EmpresaPlan.idEmpresa == id_empresa,
        #EmpresaPlan.fechaInicio <= hoy,
        #EmpresaPlan.fechaVencimiento >= hoy,
        EmpresaPlan.estatusPlan.in_(['activa', 'demo'])
    ).order_by(EmpresaPlan.idPlan.desc()).first()
    
    if not plan_actual:
        logger.warning(f"Empresa {id_empresa} sin plan activo. Verificando planes demo o vencidos.")
        return f"Sin Plan", 500
    if plan_actual.fechaVencimiento - plan_actual.fechaInicio > timedelta(days=31):
        frecuenciaPago_actual = 'anual'
    else:
        frecuenciaPago_actual = 'mensual'
    
    planes_elegibles = Plan.query.filter(Plan.idPlan >= plan_actual.idPlan, Plan.estatusPlan == 'activo').all()
    empresa          = Empresa.query.get_or_404(id_empresa)
    tipos_lista      = tipoEmpresa.query.all()
    
    if request.method == "POST":
        try:
            empresa.razonSocial = request.form.get("razonSocial")
            empresa.idtipoEmpresa = request.form.get("idtipoEmpresa")
            empresa.correoContacto = request.form.get("correoContacto")
            empresa.telefono = request.form.get("telefono")
            empresa.contacto = request.form.get("contacto")
            empresa.rfc = request.form.get("rfc")
            empresa.fisicaMoral = request.form.get("fisicaMoral")
            empresa.direccion = request.form.get("direccion")
            empresa.googleMapsUrl = request.form.get("googleMapsUrl")
            
            cp = request.form.get("codigoPostal")
            empresa.codigoPostal = int(cp) if cp and cp.strip() else None
            
            regimen = request.form.get("regimenFiscal")
            empresa.regimenFiscal = int(regimen) if regimen and regimen.strip() else None
            
            empresa.mision = request.form.get("mision")
            empresa.vision = request.form.get("vision")

            empresa.stripe_secret_key      = request.form.get('stripe_secret_key')
            empresa.stripe_publishable_key = request.form.get('stripe_publishable_key')
            empresa.stripe_webhook_secret  = request.form.get('stripe_webhook_secret')
            empresa.stripe_account_id      = request.form.get('stripe_account_id')
            empresa.comisionVarPct         = request.form.get('comisionVarPct')
            empresa.comisionFija           = request.form.get('comisionFija')
            _aplicar_mp_desde_form(empresa, request.form)

            logo_file = request.files.get("Logo")
            if logo_file and logo_file.filename:
                filename = secure_filename(logo_file.filename)
                unique_filename = f"{empresa.slug}_{filename}"
                upload_folder = os.path.join(current_app.root_path, 'static', 'img', 'empresas')
                os.makedirs(upload_folder, exist_ok=True)
                logo_file.save(os.path.join(upload_folder, unique_filename))
                empresa.logo = f"img/empresas/{unique_filename}"
            
            db.session.commit()  # Guardamos cambios en EmpresaPlan y Empresa antes de recargar la página para mostrar el nuevo plan
            return redirect(url_for("empresas.mi_empresa")) 

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error actualizando mi_empresa: {e}")
            return f"Error al actualizar: {str(e)}", 500
    
    return render_template("registrar_empresa.html",
                           tipos=tipos_lista, 
                           planes=planes_elegibles,
                           empresa=empresa,
                           modo="edicion",
                           plan_actual=plan_actual,
                           frecuenciaPago_actual=frecuenciaPago_actual)

# ==========================================
# RUTA PARA AUTO-GESTIÓN DE PLAN (ADMIN)
# ==========================================

@empresas_bp.route("/admin/config_empresa", methods=["GET"])
def config_empresa():
    """Muestra la vista de configuración general de la empresa."""
    # Validamos que sea un usuario administrador
    if session.get("tipoUsuario") != "admin":
        return "<script>alert('Acceso denegado'); window.location.href='/';</script>"

    id_empresa = session.get("idEmpresa")
    if not id_empresa:
        return "<script>alert('Sesión empresarial no válida'); window.location.href='/';</script>"

    # Cargar la entidad de la empresa actual
    empresa = Empresa.query.get_or_404(id_empresa)

    return render_template("config_empresa.html", empresa=empresa)


@empresas_bp.route("/admin/config_empresa/guardar", methods=["POST"])
def guardar_config_empresa():
    """Endpoint AJAX/Fetch para guardar las opciones de la empresa."""
    if session.get("tipoUsuario") != "admin":
        return jsonify({"success": False, "message": "Acceso denegado"}), 403

    id_empresa = session.get("idEmpresa")
    if not id_empresa:
        return jsonify({"success": False, "message": "Sesión expirada"}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No se recibieron datos válidos"}), 400

        empresa = Empresa.query.get_or_404(id_empresa)

        # Asignación de variables de configuración
        empresa.aceptaPuntosLealtad = bool(data.get("aceptaPuntosLealtad", False))
        empresa.tipoPuntosLealtad = data.get("tipoPuntosLealtad", "fijo")
        empresa.valorPuntosLealtad = Decimal(str(data.get("valorPuntosLealtad", 0)))

        modo_puntos = data.get("modoAcumulacionPuntos", "empresa")
        if modo_puntos not in ("empresa", "staff"):
            modo_puntos = "empresa"
        empresa.modoAcumulacionPuntos = modo_puntos

        # Guardar en base de datos
        db.session.commit()

        return jsonify({"success": True, "message": "Configuración guardada correctamente."})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al guardar la configuración de la empresa {id_empresa}: {e}")
        return jsonify({"success": False, "message": f"Error interno: {str(e)}"}), 500



@empresas_bp.route("/admin/plan_empresa", methods=["GET", "POST"])
def plan_empresa():
    # Validamos que sea el administrador de la empresa
    if session.get("tipoUsuario") != "admin":
        return "<script>alert('Acceso denegado'); window.location.href='/';</script>"

    # Seguridad estricta: Tomamos el ID directo de su sesión activa
    id_empresa = session.get("idEmpresa")
    if not id_empresa:
        return "<script>alert('Sesión empresarial no válida'); window.location.href='/';</script>"

    empresa = Empresa.query.get_or_404(id_empresa)
    id_usuario = session.get("idUsuario")

    # Obtener el plan activo o demo más reciente de la empresa
    plan_actual = EmpresaPlan.query.filter(
        EmpresaPlan.idEmpresa == id_empresa,
        EmpresaPlan.estatusPlan.in_(['activa', 'demo'])
    ).order_by(EmpresaPlan.idEmpresaPlan.desc()).first()

    frecuenciaPago_actual = 'mensual'
    if plan_actual and (plan_actual.fechaVencimiento - plan_actual.fechaInicio > timedelta(days=31)):
        frecuenciaPago_actual = 'anual'

    # REGLA DE NEGOCIO: Si tiene plan activo, solo puede ir hacia arriba o igual (Upgrade)
    # Si no tiene plan activo, puede seleccionar cualquiera disponible.
    if plan_actual:
        planes_disponibles = Plan.query.filter(Plan.idPlan >= plan_actual.idPlan, Plan.estatusPlan == 'activo').all()
    else:
        planes_disponibles = Plan.query.filter_by(estatusPlan='activo').all()

    saldo_remanente = remanente_plan(id_empresa)

    if request.method == "POST":
        try:
            id_plan_new = request.form.get("idPlan")
            if not id_plan_new:
                return "Seleccione un plan válido", 500
            
            frecuenciaPago_new = request.form.get("frecuenciaPago") or 'mensual'
            
            # Un cambio de plan requiere pago; se activa cuando el cargo queda liquidado.
            estado_plan_new = 'demo'

            if plan_actual:
                if plan_actual.idPlan == 1 and frecuenciaPago_new == 'anual':
                    return "No puede cambiar a una frecuencia de pago anual si el plan actual es demo", 500

                if plan_actual.idPlan == int(id_plan_new) and frecuenciaPago_new == 'mensual' and frecuenciaPago_actual == 'anual':
                    return "No puede cambiar a una frecuencia de pago mensual si el plan actual es anual", 500

            plan_nuevo = Plan.query.get(int(id_plan_new))
            if not plan_nuevo:
                return "El plan seleccionado no existe", 500

            if plan_actual.idPlan == plan_nuevo.idPlan and frecuenciaPago_actual == frecuenciaPago_new:
                return "El plan y la frecuencia seleccionados son los mismos que los actuales", 500
            

            # Calcular el costo base inicial según la frecuencia
            costo_plan_base = plan_nuevo.costoAnual if frecuenciaPago_new == 'anual' else plan_nuevo.costoMensual
            dias_vigencia = 365 if frecuenciaPago_new == 'anual' else 30
            fecha_vencimiento_final = date.today() + timedelta(days=dias_vigencia)

            deuda_pendiente_anterior = Decimal('0.00')
            detalles_notas_deuda = ""

            if plan_actual:
                mov_cuenta_anterior = movCuenta.query.filter_by(
                    idEmpresa=id_empresa,
                    idtipoMovimiento=const.MOV_PLAN,
                    idMovReferencia=plan_actual.idEmpresaPlan
                ).first()

                if mov_cuenta_anterior and mov_cuenta_anterior.saldo > 0:
                    deuda_pendiente_anterior = Decimal(str(mov_cuenta_anterior.saldo))
                    detalles_notas_deuda = f", traspaso de deuda anterior: ${deuda_pendiente_anterior:,.2f}"
                    
                    mov_cuenta_anterior.saldo = Decimal('0.00')

                # Desactivar el plan anterior
                plan_actual.estatusPlan = 'suspendida'
                plan_actual.fechaVencimiento = date.today()
            
            # =========================================================================
            # Calcular el costo neto del nuevo plan aplicando el remanente a favor y sumando la deuda vieja
            costo_final_calculado = (Decimal(str(costo_plan_base)) - Decimal(str(saldo_remanente))) + deuda_pendiente_anterior

            # Crear el nuevo registro EmpresaPlan
            nuevo_empresa_plan = EmpresaPlan(
                idEmpresa=id_empresa,
                idPlan=int(id_plan_new),
                fechaInicio=date.today(),
                fechaVencimiento=fecha_vencimiento_final,
                costo=Decimal(str(costo_plan_base)),
                remanente_plan_anterior=Decimal(str(saldo_remanente)),
                costo_plan=costo_final_calculado, # Incluye (Costo - Remanente) + Deuda Vieja
                estatusPlan=estado_plan_new,
                fechaRegistro=datetime.now()
            )
            db.session.add(nuevo_empresa_plan)
            db.session.flush()

            # Generar el movimiento contable de cargo de la cuenta
            notas = f"Cambio de plan solicitado por Admin: {plan_nuevo.nombrePlan} ({frecuenciaPago_new}), costo base ${costo_plan_base:,.2f}, remanente aplicado ${saldo_remanente:,.2f}{detalles_notas_deuda}, total a pagar asignado: ${nuevo_empresa_plan.costo_plan:,.2f}"
            generar_movCuenta_Empresa(id_empresa, const.MOV_PLAN, nuevo_empresa_plan.costo_plan, idMovReferencia=nuevo_empresa_plan.idEmpresaPlan, idUsuario=id_usuario, notas=notas, idmetodoPago=None)

            db.session.commit()
            
            # Redireccionamos al Menú de Administración o a su Estado de Cuenta
            return redirect(url_for("usuarios.menu_admin"))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error actualizando plan desde vista de admin: {e}")
            return f"Error al actualizar el plan: {str(e)}", 500

    return render_template("plan_empresa.html",
                           empresa=empresa,
                           plan_actual=plan_actual,
                           planes=planes_disponibles,
                           frecuenciaPago_actual=frecuenciaPago_actual,
                           saldo_remanente=saldo_remanente)

                           
@empresas_bp.route("/e/<string:alias>")
def entrada_empresa(alias):
    empresa = Empresa.query.filter_by(slug=alias).first()
    if not empresa:
        return redirect("/") 

    # Siempre que se llega aquí (link directo, QR, o el usuario dio "atrás"
    # desde un menú y volvió a seleccionar empresa), se considera el inicio
    # de un flujo de acceso nuevo. Limpiamos toda la sesión previa para no
    # arrastrar idUsuario/tipoUsuario/nombreUsuario de una empresa distinta.
    session.clear()

    session["idEmpresa"] = empresa.idEmpresa
    session["nombreEmpresa"] = empresa.razonSocial
    
    destino = request.args.get("destino", "cliente")
    if destino == 'usuario':
        return redirect(url_for('usuarios.login'))
        
    return redirect(url_for('cliente.login'))


@empresas_bp.route("/admin/empresas", methods=["GET", "POST"])
def empresas():
    #Esto solo es para el superusuario, los administradores de empresas no pueden ver la lista de empresas
    empresa_edit = None
    if session.get("tipoUsuario") != "superuser":
        return "<script>alert('Acceso denegado'); window.location.href='/';</script>"
    
    id_delete = request.args.get("delete")
    if id_delete:
        id_a_borrar = int(id_delete)
        if id_a_borrar == 1:
            return "<script>alert('No se puede borrar la empresa.'); window.location.href='/admin/empresas';</script>"

        try:
            empresa_obj = Empresa.query.get(id_a_borrar)
            if empresa_obj:
                archivos_a_eliminar = []
                if empresa_obj.logo:
                    logo_path = empresa_obj.logo.replace('img/empresas/', '')
                    archivos_a_eliminar.append(os.path.join(current_app.root_path, 'static', 'img', 'empresas', logo_path))

                # Recopilar IDs antes de borrar padres para conservar todas las
                # dependencias y ejecutar todo dentro de la misma transaccion.
                movimiento_ids = [mov.idMovimiento for mov in movCuenta.query.filter_by(idEmpresa=id_a_borrar).all()]
                cita_ids = [cita.idCita for cita in Cita.query.filter_by(idEmpresa=id_a_borrar).all()]
                reserva_ids = [reserva.idCitaCliente for reserva in CitaCliente.query.filter(CitaCliente.idCita.in_(cita_ids)).all()] if cita_ids else []
                producto_ids = [producto.idProducto for producto in Producto.query.filter_by(idEmpresa=id_a_borrar).all()]
                usuario_ids = [usuario.idUsuario for usuario in Usuario.query.filter_by(idEmpresa=id_a_borrar).all()]
                vendedor_empresa_ids = [rel.idVendedorEmpresa for rel in VendedorEmpresa.query.filter_by(idEmpresa=id_a_borrar).all()]
                comunicado_ids = [comunicado.idComunicado for comunicado in Comunicado.query.filter_by(idEmpresa=id_a_borrar).all()]
                pregunta_ids = [pregunta.idPregunta for pregunta in PreguntaServicio.query.filter_by(idEmpresa=id_a_borrar).all()]
                compra_ids = [compra.idCompraPublicidad for compra in CompraPublicidad.query.filter(
                    CompraPublicidad.idMovimiento.in_(movimiento_ids)
                ).all()] if movimiento_ids else []
                if usuario_ids:
                    comunicados_de_usuarios = Comunicado.query.filter(
                        Comunicado.idUsuario.in_(usuario_ids)
                    ).all()
                    comunicado_ids = list({
                        *comunicado_ids,
                        *(comunicado.idComunicado for comunicado in comunicados_de_usuarios)
                    })

                if cita_ids:
                    Cita.query.filter(Cita.idCitaMaestra.in_(cita_ids)).update(
                        {Cita.idCitaMaestra: None}, synchronize_session=False
                    )
                if producto_ids:
                    Config.query.filter(Config.idProductoBonifCliente.in_(producto_ids)).update(
                        {Config.idProductoBonifCliente: None}, synchronize_session=False
                    )
                    Config.query.filter(Config.idProductoBonifEmpresa.in_(producto_ids)).update(
                        {Config.idProductoBonifEmpresa: None}, synchronize_session=False
                    )

                # Eliminar dependencias antes de sus registros padre.
                if movimiento_ids:
                    movAplica.query.filter(movAplica.idmovCargo.in_(movimiento_ids)).delete(synchronize_session=False)
                    movAplica.query.filter(movAplica.idmovAbono.in_(movimiento_ids)).delete(synchronize_session=False)
                    CompraPublicidad.query.filter(CompraPublicidad.idMovimiento.in_(movimiento_ids)).delete(synchronize_session=False)
                    Publicidad.query.filter(Publicidad.idMovimiento.in_(movimiento_ids)).delete(synchronize_session=False)
                    Publicidad.query.filter(Publicidad.idCompraPublicidad.in_(compra_ids)).delete(synchronize_session=False)
                    MovimientoPuntos.query.filter(MovimientoPuntos.idMovimientoOrigen.in_(movimiento_ids)).delete(synchronize_session=False)
                if usuario_ids:
                    movAplica.query.filter(movAplica.idUsuario.in_(usuario_ids)).delete(synchronize_session=False)
                    MovimientoPuntos.query.filter(MovimientoPuntos.idUsuario.in_(usuario_ids)).delete(synchronize_session=False)
                    MovimientoPuntos.query.filter(MovimientoPuntos.idUsuarioStaff.in_(usuario_ids)).delete(synchronize_session=False)
                MovimientoPuntos.query.filter_by(idEmpresa=id_a_borrar).delete(synchronize_session=False)

                Publicidad.query.filter_by(idEmpresa=id_a_borrar).delete(synchronize_session=False)
                if compra_ids:
                    Publicidad.query.filter(Publicidad.idCompraPublicidad.in_(compra_ids)).delete(synchronize_session=False)
                    CompraPublicidad.query.filter(CompraPublicidad.idCompraPublicidad.in_(compra_ids)).delete(synchronize_session=False)
                if cita_ids:
                    if reserva_ids:
                        CitaPregunta.query.filter(CitaPregunta.idCitaCliente.in_(reserva_ids)).delete(synchronize_session=False)
                        CitaProducto.query.filter(CitaProducto.idCitaCliente.in_(reserva_ids)).delete(synchronize_session=False)
                        CitaCliente.query.filter(CitaCliente.idCitaCliente.in_(reserva_ids)).delete(synchronize_session=False)
                    HistorialCita.query.filter(HistorialCita.idCita.in_(cita_ids)).delete(synchronize_session=False)
                if pregunta_ids:
                    CitaPregunta.query.filter(CitaPregunta.idPregunta.in_(pregunta_ids)).delete(synchronize_session=False)
                FilaEspera.query.filter_by(idEmpresa=id_a_borrar).delete(synchronize_session=False)

                if comunicado_ids:
                    ComunicadoLeido.query.filter(ComunicadoLeido.idComunicado.in_(comunicado_ids)).delete(synchronize_session=False)
                if usuario_ids:
                    ComunicadoLeido.query.filter(ComunicadoLeido.idUsuario.in_(usuario_ids)).delete(synchronize_session=False)
                    ProductoUsuario.query.filter(ProductoUsuario.idUsuario.in_(usuario_ids)).delete(synchronize_session=False)
                if producto_ids:
                    ProductoUsuario.query.filter(ProductoUsuario.idProducto.in_(producto_ids)).delete(synchronize_session=False)
                    ConfiguracionPaquetePublicidad.query.filter(
                        ConfiguracionPaquetePublicidad.idProducto.in_(producto_ids)
                    ).delete(synchronize_session=False)
                if vendedor_empresa_ids:
                    PagoComisionVendedor.query.filter(
                        PagoComisionVendedor.idVendedorEmpresa.in_(vendedor_empresa_ids)
                    ).delete(synchronize_session=False)

                # Ultima barrera: elimina aplicaciones que apunten a cualquier
                # movimiento de la empresa, incluso si no estaban en la lista
                # recopilada al inicio.
                movimientos_empresa = db.session.query(movCuenta.idMovimiento).filter(
                    movCuenta.idEmpresa == id_a_borrar
                )
                movAplica.query.filter(movAplica.idmovCargo.in_(movimientos_empresa)).delete(
                    synchronize_session=False
                )
                movimientos_empresa = db.session.query(movCuenta.idMovimiento).filter(
                    movCuenta.idEmpresa == id_a_borrar
                )
                movAplica.query.filter(movAplica.idmovAbono.in_(movimientos_empresa)).delete(
                    synchronize_session=False
                )

                if movimiento_ids:
                    movCuenta.query.filter(movCuenta.idMovimiento.in_(movimiento_ids)).delete(synchronize_session=False)
                if cita_ids:
                    Cita.query.filter(Cita.idCita.in_(cita_ids)).delete(synchronize_session=False)
                if comunicado_ids:
                    Comunicado.query.filter(Comunicado.idComunicado.in_(comunicado_ids)).delete(synchronize_session=False)
                if pregunta_ids:
                    PreguntaServicio.query.filter(PreguntaServicio.idPregunta.in_(pregunta_ids)).delete(synchronize_session=False)
                if producto_ids:
                    Producto.query.filter(Producto.idProducto.in_(producto_ids)).delete(synchronize_session=False)
                if vendedor_empresa_ids:
                    VendedorEmpresa.query.filter(VendedorEmpresa.idVendedorEmpresa.in_(vendedor_empresa_ids)).delete(synchronize_session=False)

                ClienteStaff.query.filter_by(idEmpresa=id_a_borrar).delete(synchronize_session=False)
                ClienteEmpresa.query.filter_by(idEmpresa=id_a_borrar).delete(synchronize_session=False)
                ColorEstatusCitaEmpresa.query.filter_by(idEmpresa=id_a_borrar).delete(synchronize_session=False)
                ConfiguracionWhatsapp.query.filter_by(idEmpresa=id_a_borrar).delete(synchronize_session=False)
                Frase.query.filter_by(idEmpresa=id_a_borrar).delete(synchronize_session=False)
                EmpresaPlan.query.filter_by(idEmpresa=id_a_borrar).delete(synchronize_session=False)
                if usuario_ids:
                    Usuario.query.filter(Usuario.idUsuario.in_(usuario_ids)).delete(synchronize_session=False)
                
                db.session.delete(empresa_obj)

                for ruta in archivos_a_eliminar:
                    if os.path.exists(ruta):
                        try: os.remove(ruta)
                        except: pass

                db.session.commit()
            return redirect(url_for("empresas.empresas"))
        except Exception as e:
            db.session.rollback()
            return f"Error al borrar: {str(e)}", 500

    id_edit = request.args.get("edit")
    if id_edit:
        empresa_edit = Empresa.query.get(id_edit)
        plan_actual = EmpresaPlan.query.filter_by(idEmpresa=id_edit).order_by(EmpresaPlan.idEmpresaPlan.desc()).first()
        plan_nombre = Plan.query.get(plan_actual.idPlan).nombrePlan if plan_actual else "Sin Plan"

    if request.method == "POST":
        id_empresa = request.form.get("idEmpresa")
        es_nueva = False
        if id_empresa:
            empresa = Empresa.query.get(id_empresa)
        else:
            empresa = Empresa()
            empresa.slug = request.form.get("slug") or str(uuid.uuid4())[:8]
            es_nueva = True

        # Mapeo de campos del formulario administrativo
        empresa.idtipoEmpresa = request.form.get("idtipoEmpresa")
        empresa.idEstatus     = request.form.get("idEstatus")
        empresa.razonSocial   = request.form.get("RazonSocial")
        empresa.rfc            = request.form.get("RFC")
        empresa.fisicaMoral   = request.form.get("FisicaMoral")
        
        reg_adm = request.form.get("RegimenFiscal")
        empresa.regimenFiscal = int(reg_adm) if reg_adm and reg_adm.strip() not in ['', 'None'] else None
        empresa.direccion     = request.form.get("Direccion")
        empresa.googleMapsUrl = request.form.get("googleMapsUrl")
        cp_adm = request.form.get("CodigoPostal")
        empresa.codigoPostal  = int(cp_adm) if cp_adm and cp_adm.strip() not in ['', 'None'] else None
        
        empresa.telefono       = request.form.get("Telefono")
        empresa.contacto       = request.form.get("contacto")
        empresa.correoContacto = request.form.get("correoContacto")
        empresa.url_empresa    = request.form.get("url_empresa")
        empresa.mision         = request.form.get("mision")
        empresa.vision         = request.form.get("vision")
        
        # Etiquetas personalizadas
        empresa.etiquetaColaborador = request.form.get("etiquetaColaborador") or 'Colaborador'
        empresa.etiquetaCliente     = request.form.get("etiquetaCliente") or 'Cliente'

        # NUEVOS CAMPOS: Configuración Mercado Pago
        _aplicar_mp_desde_form(empresa, request.form)

        empresa.stripe_secret_key      = request.form.get('stripe_secret_key')
        empresa.stripe_publishable_key = request.form.get('stripe_publishable_key')
        empresa.stripe_webhook_secret  = request.form.get('stripe_webhook_secret')
        empresa.stripe_account_id      = request.form.get('stripe_account_id')
        empresa.comisionVarPct         = request.form.get('comisionVarPct')
        empresa.comisionFija           = request.form.get('comisionFija')


        id_plan_new = request.form.get("idPlan")
        estado_plan_new = request.form.get("estatusPlan") or 'demo'
        fecha_venc_form = request.form.get("fechaVencimiento")
        
        try:
            if es_nueva:
                db.session.add(empresa)
                db.session.flush()
                
                # Crear registro en EmpresaPlan
                if id_plan_new:
                    fecha_venc = date.today() + timedelta(days=15)
                    if fecha_venc_form:
                        try:
                            fecha_venc = datetime.strptime(fecha_venc_form, '%Y-%m-%d').date()
                        except:
                            pass
                    
                    empresa_plan = EmpresaPlan(
                        idEmpresa=empresa.idEmpresa,
                        idPlan=int(id_plan_new),
                        fechaInicio=date.today(),
                        fechaVencimiento=fecha_venc,
                        costo=0.00,
                        estatusPlan=estado_plan_new,
                        fechaRegistro=datetime.now()
                    )
                    db.session.add(empresa_plan)
                
                # Usuario Admin por defecto
                u_admin = Usuario(
                    idEmpresa=empresa.idEmpresa,
                    usuario='ADMIN',
                    nombreUsuario='Admin Sistema',
                    alias='Admin',
                    password=generate_password_hash('citanet'),
                    tipoUsuario='admin'
                )
                db.session.add(u_admin)
                # Colores base
                colores_base = ColorEstatusCitaEmpresa.query.filter_by(idEmpresa=1).all()
                for cb in colores_base:
                    db.session.add(ColorEstatusCitaEmpresa(idEmpresa=empresa.idEmpresa, idEstatus=cb.idEstatus, color=cb.color))
            else:
                # Si es edición, actualizar EmpresaPlan
                if id_plan_new:
                    empresa_plan = EmpresaPlan.query.filter_by(idEmpresa=empresa.idEmpresa).order_by(EmpresaPlan.idEmpresaPlan.desc()).first()
                    if empresa_plan:
                        empresa_plan.idPlan = int(id_plan_new)
                        empresa_plan.estatusPlan = estado_plan_new
                        if fecha_venc_form:
                            try:
                                empresa_plan.fechaVencimiento = datetime.strptime(fecha_venc_form, '%Y-%m-%d').date()
                            except:
                                pass
                    else:
                        fecha_venc = date.today() + timedelta(days=30)
                        if fecha_venc_form:
                            try:
                                fecha_venc = datetime.strptime(fecha_venc_form, '%Y-%m-%d').date()
                            except:
                                pass
                        empresa_plan = EmpresaPlan(
                            idEmpresa=empresa.idEmpresa,
                            idPlan=int(id_plan_new),
                            fechaInicio=date.today(),
                            fechaVencimiento=fecha_venc,
                            costo=0.00,
                            estatusPlan=estado_plan_new,
                            fechaRegistro=datetime.now()
                        )
                        db.session.add(empresa_plan)

            db.session.commit()
            return redirect(url_for("empresas.empresas"))
        except Exception as e:
            db.session.rollback()
            return f"Error al guardar: {str(e)}", 500

    empresas_lista = Empresa.query.order_by(Empresa.razonSocial).all()
    tipos_lista = tipoEmpresa.query.all()
    estatus_opciones = EstatusEmpresa.query.all()
    planes_lista = Plan.query.all()

    plan_actual = plan_actual if 'plan_actual' in dir() and plan_actual else None
    plan_nombre = plan_nombre if 'plan_nombre' in dir() and plan_nombre else "Sin Plan"

    return render_template("lista_empresas.html", 
                            empresas=empresas_lista, 
                            tipos=tipos_lista, 
                            estatus_opciones=estatus_opciones, 
                            planes=planes_lista,
                            empresa_edit=empresa_edit,
                            plan_actual=plan_actual,
                            plan_nombre=plan_nombre)

@empresas_bp.route("/admin/tipos_empresa", methods=["GET", "POST"])
def tipos_empresa():
    if request.method == "POST":
        id_t = request.form.get('idtipoEmpresa')
        nombre = request.form.get('tipo')
        etiqueta = request.form.get('etiqueta')
        if id_t:
            obj = tipoEmpresa.query.get(id_t)
            obj.tipo = nombre
            obj.etiqueta = etiqueta
        else:
            db.session.add(tipoEmpresa(tipo=nombre, etiqueta=etiqueta))
        db.session.commit()
        return redirect(url_for('empresas.tipos_empresa'))

    tipos = tipoEmpresa.query.all()
    return render_template("tipos_empresa.html", tipos=tipos)

@empresas_bp.route("/admin/tipo_empresa/delete/<int:id>")
def eliminar_tipo_empresa(id):
    obj = tipoEmpresa.query.get_or_404(id)
    db.session.delete(obj)
    db.session.commit()
    return redirect(url_for('empresas.tipos_empresa'))

@empresas_bp.route('/api/v1/empresa/info')
def ping_api_empresa():
    id_empresa = session.get('idEmpresa')
    if not id_empresa:
        return jsonify({"status": "error", "mensaje": "Sesión no encontrada"}), 401
    empresa = Empresa.query.get(id_empresa)
    return jsonify({
        "status": "online",
        "servidor": "Ubuntu 24.04 - Citanet",
        "puerto": 5001,
        "datos_empresa": {"id": empresa.idEmpresa, "nombre": empresa.razonSocial, "rfc": empresa.rfc, "telefono": empresa.telefono}
    })

@empresas_bp.route('/api/v1/empresa/staff')
def obtener_staff_api():
    id_empresa = session.get('idEmpresa')
    if not id_empresa:
        return jsonify({"mensaje": "No autorizado"}), 401
    staff = Usuario.query.filter_by(idEmpresa=id_empresa, tipoUsuario='staff').all()
    lista_staff = [{"id": t.idUsuario, "nombre": t.nombreUsuario, "alias": t.alias} for t in staff]
    return jsonify({"empresa": id_empresa, "total": len(lista_staff), "staff": lista_staff})

def remanente_plan(idEmpresa):
    
    hoy = datetime.now().date()
    plan_actual = EmpresaPlan.query.filter(
        EmpresaPlan.idEmpresa == idEmpresa,
        #EmpresaPlan.fechaInicio <= hoy,
        #EmpresaPlan.fechaVencimiento >= hoy,
        EmpresaPlan.estatusPlan.in_(['activa', 'demo'])
    ).order_by(EmpresaPlan.idPlan.desc()).first()
    
    
    if not plan_actual:
        return Decimal('0.00')
    
    if plan_actual.fechaVencimiento - plan_actual.fechaInicio > timedelta(days=31):
        dias_gracia = 60
    else:
        dias_gracia = 0
    
    dias_plan        = (plan_actual.fechaVencimiento - plan_actual.fechaInicio).days
    dias_restantes   = (plan_actual.fechaVencimiento - hoy).days
    
    if dias_restantes < dias_gracia:
        return Decimal('0.00')
    
    saldo_remanente = Decimal(str(plan_actual.costo)) / Decimal(str(dias_plan)) * Decimal(str(dias_restantes))
    
    return saldo_remanente.quantize(Decimal('0.01'))  # Redondear a 2 decimales

def generar_movCuenta_Empresa(idEmpresa, idtipoMovimiento, monto, idMovReferencia=None, idUsuario=None, notas=None, idmetodoPago=None):
    ahora = datetime.now()
    monto_decimal = Decimal(str(monto))

    if not idUsuario:
        idUsuario = const.ID_USUARIO_SISTEMA  # Usuario del sistema para operaciones automÃ¡ticas
    
    nuevo_movCuenta = movCuenta(
        idEmpresa=idEmpresa,
        idCliente=None,
        idtipoMovimiento=idtipoMovimiento,
        idUsuario=idUsuario,
        idMovReferencia=idMovReferencia,
        monto=monto_decimal,
        saldoAnterior=monto_decimal,
        saldo=monto_decimal,
        notas=notas,
        idmetodoPago=idmetodoPago,
        fecha=ahora.date(),
        hora=ahora.time()
    )

    db.session.add(nuevo_movCuenta)
    db.session.flush()  # Para obtener idMovimiento
    db.session.refresh(nuevo_movCuenta) # Cargamos la relación .tipo
    
    #Aplicar saldos a favor o en contra según el tipo de movimiento
    
    # Si es un CARGO, buscamos ABONOS con saldo para aplicar
    if nuevo_movCuenta.tipo.naturaleza == 'C' and nuevo_movCuenta.saldo > 0:
        abonos_con_saldo = db.session.query(movCuenta).join(movCuenta.tipo)\
            .filter(movCuenta.idEmpresa == idEmpresa)\
            .filter(movCuenta.idCliente.is_(None))\
            .filter(movCuenta.tipo.has(naturaleza='A'))\
            .filter(movCuenta.saldo > 0)\
            .order_by(movCuenta.fecha.asc(), movCuenta.hora.asc())\
            .all()

        for abono in abonos_con_saldo:
            if nuevo_movCuenta.saldo <= 0:
                break

            monto_a_aplicar = min(nuevo_movCuenta.saldo, abono.saldo)

            # 3. Creamos el registro en movAplica
            # Nota: Asegúrate de que los nombres de columnas coincidan con tu tabla movAplica
            aplicacion = movAplica(
                idmovCargo=nuevo_movCuenta.idMovimiento,
                idmovAbono=abono.idMovimiento,
                montoAplicado=monto_a_aplicar,
                fechaAplicado=ahora.date(),
                idUsuario=idUsuario
            )
            db.session.add(aplicacion)

            # 4. Actualizamos saldos en ambos movimientos
            nuevo_movCuenta.saldo -= monto_a_aplicar
            abono.saldo -= monto_a_aplicar

    return nuevo_movCuenta


def otorgar_bonificacion_publicidad_empresa(empresa, idUsuario=None):
    """
    Al dar de alta una empresa nueva en CitaNet, si hay un paquete configurado en
    Config.idProductoBonifEmpresa se le regala: se crea el abono de
    'Bonificación' y el cargo de 'Compra' (éste último autoaplica el abono
    dentro de generar_movCuenta_Empresa, generando el movAplica), más su
    CompraPublicidad con el cupo correspondiente — igual que si lo hubiera
    comprado. Se registra sobre la cuenta de la propia empresa nueva.
    """
    cfg = Config.query.first()
    if not cfg or not cfg.idProductoBonifEmpresa:
        return

    producto = Producto.query.get(cfg.idProductoBonifEmpresa)
    if not producto or not producto.activo:
        return

    monto = float(producto.costo)
    config_paquete = producto.configuracion_publicidad
    cantidad_publicidad = config_paquete.cantidadPublicidad if config_paquete else 1
    dias_vigencia = config_paquete.diasVigencia if config_paquete else 30

    # 1) Abono de bonificación
    generar_movCuenta_Empresa(
        idEmpresa=empresa.idEmpresa,
        idtipoMovimiento=const.MOV_BONIFICACION,
        monto=monto,
        idUsuario=idUsuario,
        notas=f"Bonificación de publicidad por alta de empresa: {producto.nombre}"
    )

    # 2) Cargo de compra: al crearse, generar_movCuenta_Empresa busca abonos con
    # saldo disponible (el que acabamos de crear) y lo aplica automáticamente,
    # generando el movAplica correspondiente.
    nuevo_movimiento = generar_movCuenta_Empresa(
        idEmpresa=empresa.idEmpresa,
        idtipoMovimiento=const.MOV_COMPRA,
        idMovReferencia=producto.idProducto,
        monto=monto,
        idUsuario=idUsuario,
        notas=f"Cargo por bonificación de publicidad: {producto.nombre}"
    )

    nueva_compra = CompraPublicidad(
        idMovimiento=nuevo_movimiento.idMovimiento,
        idProducto=producto.idProducto,
        idEmpresa=empresa.idEmpresa,
        idCliente=None,
        cantidadPermitida=cantidad_publicidad,
        cantidadUsada=0,
        diasVigencia=dias_vigencia
    )
    db.session.add(nueva_compra)