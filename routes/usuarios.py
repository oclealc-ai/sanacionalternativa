from datetime           import datetime, timedelta
from flask              import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash, make_response
from werkzeug.security  import generate_password_hash, check_password_hash
from modelos            import db, Usuario, Empresa, EmpresaPlan
from correo             import enviar_correo_base
from whatsapp           import enviar_whatsapp
import secrets
import string
import config
import logging

logger = logging.getLogger(__name__)
usuarios_bp = Blueprint("usuarios", __name__)


def _sin_cache(response):
    """Evita que el navegador sirva esta página desde el caché (bfcache)
    al usar el botón 'atrás', lo cual podría mostrar datos de sesión obsoletos."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response



@usuarios_bp.route("/usuarios/login", methods=["GET"])
def login():
    
    if not session.get("url_origen"):
        session["url_origen"] = request.referrer
    
    id_empresa = session.get("idEmpresa")
    if not id_empresa:
        id_empresa = request.args.get("idEmpresa")
        if id_empresa:
            session["idEmpresa"] = id_empresa

    # Si no hay empresa, lo mandamos a seleccionar una
    if not id_empresa:
        return redirect(url_for('seleccionar_empresa', destino='usuario'))
        
    if session.get("idUsuario"):
        tipo = (session.get('tipoUsuario') or '').lower()
        if tipo == 'cliente':
            # El menú del cliente vive en el blueprint 'cliente', no en 'usuarios'
            return redirect(url_for('cliente.menu_cliente'))
        if tipo in ('admin', 'superuser', 'staff', 'asistente'):
            return redirect(url_for(f"usuarios.menu_{tipo}"))
        # Tipo desconocido: se muestra el login en lugar de tronar con error 500
    
    empresa_obj = Empresa.query.get(id_empresa)

    if not empresa_obj:
        session.pop("idEmpresa", None)
        flash("La empresa seleccionada no es válida.", "danger")
        return redirect(url_for('seleccionar_empresa', destino='usuario'))

    nombre_empresa = empresa_obj.razonSocial
    return render_template("login_usuario.html", 
                           idEmpresa=id_empresa, 
                           empresa=nombre_empresa)


@usuarios_bp.route('/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Datos inválidos"}), 400

    usuario_input = data.get('usuario', '').strip().upper()
    password = data.get('password', '')
    empresa_id = data.get('empresa')

    try:
        usuario_db = Usuario.query.filter_by(usuario=usuario_input, idEmpresa=int(empresa_id)).first()

        # 1. Validar Credenciales
        if not usuario_db or not check_password_hash(usuario_db.password, password):
            return jsonify({"error": "Credenciales inválidas"}), 401

        empresa = Empresa.query.get(usuario_db.idEmpresa)
        if not empresa:
            return jsonify({"error": "Empresa no encontrada"}), 404

        # Obtener el plan vigente (el más reciente)
        empresa_plan = EmpresaPlan.query.filter_by(idEmpresa=usuario_db.idEmpresa).order_by(EmpresaPlan.fechaRegistro.desc()).first()

        rol_usuario = usuario_db.tipoUsuario.lower()

        hoy = datetime.now().date()
        fecha_limite_plan = empresa_plan.fechaVencimiento if empresa_plan else None
        if (empresa_plan and empresa_plan.estatusPlan == 'demo'
            and empresa_plan.fechaInicio):
            fecha_limite_plan = empresa_plan.fechaInicio + timedelta(days=15)
        demo_expirado = (
            empresa_plan is not None
            and empresa_plan.estatusPlan == 'demo'
            and fecha_limite_plan is not None
            and hoy > fecha_limite_plan
        )

        # Staff y asistentes solo tienen acceso al demo durante sus 15 días.
        # El admin conserva el acceso para poder realizar el pago.
        if demo_expirado and rol_usuario != 'admin':
            return jsonify({
                "error": "El periodo de demo de 15 días ha expirado. Realiza el pago para activar el plan."
            }), 403

        # 2. Validar el estatus del plan para los usuarios operativos.
        # Demo permite entrar mientras esté dentro de sus 15 días; suspendida/vencida no.
        if empresa_plan and empresa_plan.estatusPlan not in ('activa', 'demo') and rol_usuario != 'admin':
            return jsonify({"error": "La licencia de esta empresa no está activa. Contacta al administrador de CitaNet."}), 403

        # 3. Validar Fecha de Vencimiento con Periodo de Gracia para ADMIN
        advertencia_admin = None
        advertencia_vencimiento = None

        if demo_expirado and rol_usuario == 'admin':
            advertencia_admin = (
                f"El periodo de demo venció el {fecha_limite_plan.strftime('%d/%m/%Y')}. "
                "Puedes entrar para realizar el pago y activar el plan."
            )
        elif empresa_plan and fecha_limite_plan and fecha_limite_plan < hoy:
            # Si es ADMIN, revisamos si está dentro de los 15 días de gracia
            if rol_usuario == 'admin':
                fecha_limite_gracia = fecha_limite_plan + timedelta(days=15)
                
                if hoy <= fecha_limite_gracia:
                    # PERMITIR ENTRAR, pero preparamos un mensaje de advertencia
                    advertencia_admin = f"Tu licencia venció el {fecha_limite_plan.strftime('%d/%m/%Y')}. Se te otorga un acceso de gracia de 15 días para regularizar el pago."
                else:
                    # Ya pasaron los 15 días de gracia
                    return jsonify({"error": "El periodo de gracia de 15 días ha expirado. Contacta al administrador de CitaNet para renovar."}), 403
            else:
                # No es admin y está vencido
                return jsonify({"error": "La licencia de esta empresa ha vencido. Contacta al administrador de su empresa."}), 403
        elif empresa_plan and fecha_limite_plan:
            dias_restantes = (fecha_limite_plan - hoy).days
            if dias_restantes <= 5:
                advertencia_vencimiento = (
                    f"Tu licencia vence el {fecha_limite_plan.strftime('%d/%m/%Y')}. "
                    f"Quedan {dias_restantes} días para renovarla."
                )
            
        # 4. Preparar Sesión
        origen_previo = session.get("url_origen")
        session.clear() 

        session.update({
            "idUsuario": usuario_db.idUsuario,
            "Usuario": usuario_db.usuario,
            "nombreUsuario": usuario_db.nombreUsuario,
            "tipoUsuario": usuario_db.tipoUsuario.lower(),
            "idEmpresa": usuario_db.idEmpresa,
            "razonSocial": empresa.razonSocial if empresa else "",
            "url_origen": origen_previo
        })

        # Si hay advertencia, la guardamos en flash para que se vea en la siguiente pantalla (el menú)
        if advertencia_admin:
            flash(advertencia_admin, "warning")
                
        # 5. Respuesta Exitosa
        return jsonify({
            "mensaje": "Login correcto", 
            "tipo": session["tipoUsuario"],
            "advertencia": advertencia_admin, # También lo mandamos por si el JS quiere hacer algo
            "advertencia_vencimiento": advertencia_vencimiento,
            "redirect": url_for(f"usuarios.menu_{session['tipoUsuario']}")
        }), 200

    except Exception as e:
        logger.exception("ERROR LOGIN: %s", e)
        return jsonify({"error": "Error interno del servidor"}), 500

@usuarios_bp.route('/logout/sistema')
def logout_sistema():
    
    url_retorno = session.get("url_origen")
    
    logger.info("Intentando logout. url_retorno: %s", url_retorno)
    
    if url_retorno and "citanet" not in url_retorno:
        session.clear()
        return redirect(url_retorno)
    
    session.clear()
    return redirect(config.URL_BASE)


# ==========================================
# MENÚS POR ROL
# ==========================================

@usuarios_bp.route('/menu/admin')
def menu_admin():
    if 'idUsuario' not in session or session.get('tipoUsuario') != 'admin': 
        return redirect(config.URL_BASE)
    resp = render_template('menu_admin.html', nombre=session.get('nombreUsuario'), empresa=session.get('razonSocial'))
    return _sin_cache(make_response(resp))

@usuarios_bp.route('/menu/superuser')
def menu_superuser():
    if 'idUsuario' not in session or session.get('tipoUsuario') != 'superuser': 
        return redirect(config.URL_BASE)
    resp = render_template('menu_superuser.html', nombre=session.get('nombreUsuario'), empresa=session.get('razonSocial'))
    return _sin_cache(make_response(resp))

@usuarios_bp.route('/menu/staff')
def menu_staff():
    if 'idUsuario' not in session or session.get('tipoUsuario') != 'staff': 
        return redirect(config.URL_BASE)
    resp = render_template('menu_staff.html', nombre=session.get('nombreUsuario'), empresa=session.get('razonSocial'))
    return _sin_cache(make_response(resp))

@usuarios_bp.route('/menu/asistente')
def menu_asistente():
    if 'idUsuario' not in session or session.get('tipoUsuario') != 'asistente': 
        return redirect(config.URL_BASE)
    resp = render_template('menu_asistente.html', nombre=session.get('nombreUsuario'), empresa=session.get('razonSocial'))
    return _sin_cache(make_response(resp))

# ==========================================
# GESTIÓN DE USUARIOS (STAFF)
# ==========================================
@usuarios_bp.route('/admin/cambiar_password', methods=['GET', 'POST'])
def cambiar_password():
    if 'idUsuario' not in session:
        session.clear()
        return redirect(config.URL_BASE)

    mensaje = None
    tipo = None

    if request.method == 'POST':
        pw_actual = request.form.get('actual')
        pw_nueva = request.form.get('nueva')
        pw_confirmar = request.form.get('confirmar')

        user = Usuario.query.get(session['idUsuario'])

        if not check_password_hash(user.password, pw_actual):
            mensaje = "La contraseña actual es incorrecta."
            tipo = "error"
        elif pw_nueva != pw_confirmar:
            mensaje = "La nueva contraseña y la confirmación no coinciden."
            tipo = "error"
        elif len(pw_nueva) < 6:
            mensaje = "La nueva contraseña debe tener al menos 6 caracteres."
            tipo = "error"
        else:
            try:
                user.password = generate_password_hash(pw_nueva)
                db.session.commit()
                mensaje = "Contraseña actualizada exitosamente."
                tipo = "exito"
            except Exception as e:
                db.session.rollback()
                mensaje = f"Error al guardar en la base de datos: {str(e)}"
                tipo = "error"

    return render_template("cambiar_password.html", 
                           mensaje=mensaje, 
                           tipo=tipo)
    



@usuarios_bp.route('/admin/usuarios/resetear/<int:id>')
def resetear_password(id):
    if 'idEmpresa' not in session or session.get('tipoUsuario') not in ['admin', 'superuser']:
        return redirect(url_for('login'))
    
    usuario = Usuario.query.get(id)
    if usuario and usuario.idEmpresa == session['idEmpresa']:
        
        caracteres = string.ascii_letters + string.digits
        temp_pass = ''.join(secrets.choice(caracteres) for i in range(8))
        temp_pass = 'citanet'
        
        usuario.password = generate_password_hash(temp_pass)
        
        cuerpo_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 10px;">
                    <h2 style="color: #002b50; text-align: center;">CitaNet - Seguridad</h2>
                    <p>Hola, <strong>{usuario.nombreUsuario}</strong>:</p>
                    <p>Se ha generado una solicitud para restablecer tu acceso al sistema.</p>
                    
                    <div style="background-color: #f4f7f6; padding: 15px; border-radius: 8px; text-align: center; margin: 20px 0;">
                        <p style="margin: 0; font-size: 0.9rem; color: #666;">Tu nueva contraseña de uso temporal es:</p>
                        <h3 style="margin: 10px 0; color: #5bbfa6; font-size: 1.5rem; letter-spacing: 2px;">{temp_pass}</h3>
                    </div>

                    <p style="font-size: 0.9rem; color: #555;">
                        <strong>Nota importante:</strong> Por seguridad, te recomendamos cambiar esta contraseña 
                        inmediatamente después de iniciar sesión desde tu perfil de usuario.
                    </p>
                    
                    <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="font-size: 0.8rem; color: #999; text-align: center;">
                        Este es un correo automático, por favor no respondas a este mensaje.<br>
                        &copy; 2026 CitaNet System
                    </p>
                </div>
            </body>
            </html>
            """

        try:
            db.session.commit()
            
            exito = enviar_correo_base(usuario.correo, 'Cambio de contraseña', cuerpo_html)
            
            flash(f'Contraseña reseteada para {usuario.nombreUsuario}. Se envió a: {usuario.correo}', 'success')
            # Opcional: Mostrarla en un flash si no tienes configurado el correo aún
            # flash(f'Temporal: {temp_pass}', 'info') 
            
        except Exception as e:
            db.session.rollback()
            flash('Error al resetear la contraseña', 'danger')
            
    return redirect('/admin/usuarios')


@usuarios_bp.route('/admin/usuarios')
def admin_usuarios():
    if "idUsuario" not in session:
        return redirect("/login/sistema")
    
    tipo_usuario = session.get('tipoUsuario')
    
    id_empresa_sesion = session.get("idEmpresa")
    id_usuario        = session.get("idUsuario")
    usuarios          = Usuario.query.get(id_usuario)
    
    usuarios = Usuario.query.filter_by(idEmpresa=id_empresa_sesion).with_entities(
        Usuario.idUsuario, 
        Usuario.usuario,
        Usuario.nombreUsuario,
        Usuario.alias,
        Usuario.tipoUsuario
    ).order_by(Usuario.idUsuario.asc()).all()

    return render_template("admin_usuarios.html", usuarios=usuarios, tipo_usuario=tipo_usuario)

@usuarios_bp.route("/admin/usuarios/editar/<int:id>")
def usuario_editar(id):
    if "idUsuario" not in session:
        return redirect(config.URL_BASE)

    usuario = Usuario.query.get(id)
    if not usuario:
        return redirect(url_for("usuarios.admin_usuarios"))

    usuario_obj = Usuario.query.filter_by(idUsuario=id, idEmpresa=session.get("idEmpresa")).first()

    if not usuario_obj:
        flash("Acceso no autorizado al usuario solicitado.", "danger")
        return redirect(url_for("usuarios.admin_usuarios"))
    
    cantMaxStaff = session.get("cantMaxStaff", 2)
    usuariosStaff = Usuario.query.filter_by(idEmpresa=session.get("idEmpresa"), tipoUsuario='staff').count()

    return render_template(
        "usuario_form.html",
        modo="editar",
        usuario=usuario,
        puede_agregar_staff = (usuariosStaff < cantMaxStaff), # Permitir editar siempre; límite solo se verifica al guardar
        url=url_for('usuarios.guardar_usuario', id=id) # Es mejor usar url_for que strings manuales
    )
    
@usuarios_bp.route('/admin/usuarios/eliminar/<int:id>', methods=['POST'])
def eliminar_usuario(id):
    if session.get("tipoUsuario") not in ['admin', 'superuser']:
        return redirect(config.URL_BASE)

    try:
        usuario_a_eliminar = Usuario.query.get(id)
        
        # Validación: No eliminarse a sí mismo
        if usuario_a_eliminar.idUsuario == session.get('idUsuario'):
            flash("¡Error! No puedes eliminar tu propia cuenta de administrador.", "danger")
            return redirect(url_for('usuarios.admin_usuarios'))

        # Validación: No eliminar al último admin
        if usuario_a_eliminar.tipoUsuario == 'admin':
            total_admins = Usuario.query.filter_by(idEmpresa=session.get("idEmpresa"), tipoUsuario='admin').count()
            if total_admins <= 1:
                flash("¡Acción bloqueada! Debe existir al menos un administrador.", "warning")
                return redirect(url_for('usuarios.admin_usuarios'))

        db.session.delete(usuario_a_eliminar)
        db.session.commit()
        flash(f"Usuario {usuario_a_eliminar.usuario} eliminado correctamente.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash("Ocurrió un error interno al intentar eliminar.", "danger")
        
    return redirect(url_for('usuarios.admin_usuarios'))

@usuarios_bp.route('/admin/usuarios/guardar', methods=['POST'])
@usuarios_bp.route('/admin/usuarios/guardar/<int:id>', methods=['POST'])
def guardar_usuario(id=None):
    if session.get("tipoUsuario") not in ['admin', 'superuser']:
        return redirect(config.URL_BASE)

    empresa_id     = session.get("idEmpresa")
    cantMaxStaff   = session.get("cantMaxStaff", 2)

    # 1. Captura de datos del formulario
    usuario_val    = request.form.get('usuario', '').strip().upper()
    nombre_val     = request.form.get('nombreUsuario', '').strip()
    alias_val      = request.form.get('alias', '').strip()
    tipo_val       = request.form.get('tipoUsuario', 'asistente').lower()
    telefono_val   = request.form.get('telefono', '').strip()
    correo_val     = request.form.get('correo', '').strip().lower()
    password_plano = request.form.get('password')

    # Objeto temporal para no perder datos en el formulario si hay error
    datos_pantalla = {
        'idUsuario': id,
        'usuario': usuario_val,
        'nombreUsuario': nombre_val,
        'alias': alias_val,
        'tipoUsuario': tipo_val,
        'telefono': telefono_val,
        'correo': correo_val
    }

    usuariosStaff = Usuario.query.filter_by(idEmpresa=empresa_id, tipoUsuario='staff').count()
    nuevos_staff = usuariosStaff

    if id:
        usuario_actual = Usuario.query.get(id)
        if not usuario_actual or usuario_actual.idEmpresa != empresa_id:
            flash("Acceso no autorizado al usuario solicitado.", "danger")
            return redirect(url_for('usuarios.admin_usuarios'))

        if usuario_actual.tipoUsuario != 'staff' and tipo_val == 'staff':
            nuevos_staff += 1
    else:
        if tipo_val == 'staff':
            nuevos_staff += 1

    if nuevos_staff > cantMaxStaff:
        flash(f"No puedes asignar más usuarios STAFF. El límite de tu plan es {cantMaxStaff}.", "warning")
        return render_template("usuario_form.html", modo="editar" if id else "nuevo", usuario=datos_pantalla, url=request.path)

    try:
        query_correo = Usuario.query.filter_by(correo=correo_val, idEmpresa=empresa_id)
        if id: query_correo = query_correo.filter(Usuario.idUsuario != id)
        if query_correo.first():
            flash("El correo ya está registrado para otro usuario.", "danger")
            return render_template("usuario_form.html", modo="editar" if id else "nuevo", usuario=datos_pantalla, url=request.path)

        if telefono_val:
            query_tel = Usuario.query.filter_by(telefono=telefono_val, idEmpresa=empresa_id)
            if id: query_tel = query_tel.filter(Usuario.idUsuario != id)
            if query_tel.first():
                flash(f"El teléfono {telefono_val} ya está registrado.", "danger")
                return render_template("usuario_form.html", modo="editar" if id else "nuevo", usuario=datos_pantalla, url=request.path)

        if id:  # --- MODO EDICIÓN ---
            u = Usuario.query.get(id)
            if u:
                u.nombreUsuario = nombre_val
                u.alias = alias_val
                u.tipoUsuario = tipo_val
                u.telefono = telefono_val
                u.correo = correo_val
            flash(f"Usuario {u.nombreUsuario} actualizado correctamente.", "success")
        
        else:   # --- MODO NUEVO ---
            u = Usuario(
                usuario=usuario_val,
                password=generate_password_hash(password_plano),
                tipoUsuario=tipo_val,
                idEmpresa=empresa_id,
                nombreUsuario=nombre_val,
                alias=alias_val,
                telefono=telefono_val,
                correo=correo_val,
                correoValido=0
            )
            db.session.add(u)
            flash(f"Usuario {nombre_val} creado exitosamente.", "success")

        db.session.commit()
        return redirect(url_for("usuarios.admin_usuarios"))

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al guardar usuario: {e}")
        flash(f"Error al procesar la solicitud: {str(e)}", "danger")
        return render_template("usuario_form.html", modo="editar" if id else "nuevo", usuario=datos_pantalla, url=request.path)

@usuarios_bp.route("/admin/usuarios/nuevo")
def usuario_nuevo():
    if "idUsuario" not in session:
        return redirect(config.URL_BASE)
        
    if session.get("tipoUsuario") not in ['admin', 'superuser']:
        return redirect(url_for('usuarios.menu_asistente'))

    return render_template(
        "usuario_form.html",
        modo="nuevo",
        usuario=None,  # Enviamos None para que el HTML sepa que no hay datos que precargar
        url=url_for('usuarios.guardar_usuario') # Apunta a la ruta de guardar (sin ID)
    )

# ==========================================
# RECUPERACIÓN DE CONTRASEÑA
# ==========================================

@usuarios_bp.route('/usuarios/recuperar_contrasena', methods=['GET'])
def recuperar_contrasena():
    """Renderiza la pantalla de recuperación de contraseña."""
    id_empresa = session.get('idEmpresa') or request.args.get('idEmpresa')
    return render_template('recuperar_contrasena.html', idEmpresa=id_empresa or '')


@usuarios_bp.route('/usuarios/validar_codigo_recuperacion', methods=['GET'])
def validar_codigo_recuperacion():
    """Renderiza la pantalla de validación de código y cambio de contraseña."""
    return render_template('validar_codigo_recuperacion.html')


@usuarios_bp.route('/usuarios/solicitar_recuperacion', methods=['POST'])
def solicitar_recuperacion():
    """Genera y envía el código de recuperación por correo o WhatsApp."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Datos inválidos'}), 400

    metodo     = data.get('metodo')       # 'email' o 'phone'
    valor      = data.get('valor', '').strip()
    usuario_input = data.get('usuario', '').strip().upper()
    id_empresa = data.get('idEmpresa')

    if not metodo or not valor:
        return jsonify({'error': 'Faltan datos'}), 400

    # Buscar el usuario
    try:
        id_empresa_int = int(id_empresa) if id_empresa else None
    except (ValueError, TypeError):
        id_empresa_int = None

    usuario = None
    if metodo == 'email':
        # Si viene el nombre de usuario, validar que coincida con el correo
        if usuario_input:
            q = Usuario.query.filter_by(usuario=usuario_input, correo=valor.lower())
        else:
            q = Usuario.query.filter_by(correo=valor.lower())
        if id_empresa_int:
            q = q.filter_by(idEmpresa=id_empresa_int)
        usuario = q.first()
        if not usuario:
            # Mensaje genérico para no revelar si el correo existe o no
            return jsonify({'error': 'No se encontró una cuenta con esos datos. Verifica tu usuario y correo.'}), 404
    elif metodo == 'phone':
        # Normalizar: quitar +52 si viene
        tel = valor.replace('+52', '').replace(' ', '').replace('-', '')
        if usuario_input:
            q = Usuario.query.filter_by(usuario=usuario_input).filter(
                Usuario.telefono.like(f'%{tel[-10:]}%'))
        else:
            q = Usuario.query.filter(Usuario.telefono.like(f'%{tel[-10:]}%'))
        if id_empresa_int:
            q = q.filter_by(idEmpresa=id_empresa_int)
        usuario = q.first()
        if not usuario:
            return jsonify({'error': 'No se encontró una cuenta con esos datos. Verifica tu usuario y teléfono.'}), 404

    # Generar código de 6 dígitos
    codigo = ''.join(secrets.choice(string.digits) for _ in range(6))
    expira = datetime.now() + timedelta(minutes=10)
    token  = secrets.token_hex(32)

    # Guardar en sesión Flask (funciona con múltiples workers de Gunicorn)
    session['recuperacion'] = {
        'idUsuario': usuario.idUsuario,
        'codigo':    codigo,
        'expira':    expira.isoformat(),
        'token':     None,
    }

    # Enviar el código
    exito = False
    if metodo == 'email':
        cuerpo = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;">
        <div style="max-width:600px;margin:0 auto;padding:20px;border:1px solid #e0e0e0;border-radius:10px;">
            <h2 style="color:#002b50;text-align:center;">CitaNet — Recuperación de Contraseña</h2>
            <p>Hola, <strong>{usuario.nombreUsuario}</strong>:</p>
            <p>Tu código de recuperación es:</p>
            <div style="text-align:center;margin:30px 0;">
                <span style="font-size:2rem;font-weight:bold;letter-spacing:8px;color:#5bbfa6;
                             background:#f4f7f6;padding:15px 30px;border-radius:10px;">{codigo}</span>
            </div>
            <p style="color:#666;font-size:0.9rem;">Este código es válido por <strong>10 minutos</strong>.</p>
            <p style="color:#999;font-size:0.8rem;">Si no solicitaste este código, ignora este mensaje.</p>
        </div>
        </body></html>
        """
        exito = enviar_correo_base(usuario.correo, 'Código de recuperación — CitaNet', cuerpo)
    elif metodo == 'phone':
        mensaje_wa = f'🔐 *CitaNet* — Código de recuperación\n\nHola *{usuario.nombreUsuario}*, tu código es:\n\n*{codigo}*\n\n_Válido por 10 minutos. Si no lo solicitaste, ignora este mensaje._'
        exito = enviar_whatsapp(numero=usuario.telefono, mensaje=mensaje_wa, idEmpresaEnvia=usuario.idEmpresa)

    if not exito:
        return jsonify({'error': 'No se pudo enviar el código. Intenta más tarde.'}), 500

    logger.info(f"Código de recuperación enviado a usuario {usuario.idUsuario} via {metodo}")
    return jsonify({
        'mensaje': f'Código enviado. Revisa tu {"correo" if metodo == "email" else "teléfono"}.',
        'idUsuario': usuario.idUsuario
    }), 200


@usuarios_bp.route('/usuarios/verificar_codigo_recuperacion', methods=['POST'])
def verificar_codigo_recuperacion():
    """Valida el código ingresado y devuelve un token para cambiar la contraseña."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Datos inválidos'}), 400

    id_usuario = data.get('idUsuario')
    codigo     = data.get('codigo', '').strip()

    try:
        id_usuario = int(id_usuario)
    except (ValueError, TypeError):
        return jsonify({'error': 'Usuario inválido'}), 400

    registro = session.get('recuperacion')
    if not registro or registro.get('idUsuario') != id_usuario:
        return jsonify({'error': 'No hay una solicitud de recuperación activa para este usuario'}), 400

    if datetime.now() > datetime.fromisoformat(registro['expira']):
        session.pop('recuperacion', None)
        return jsonify({'error': 'El código ha expirado. Solicita uno nuevo.'}), 400

    if registro['codigo'] != codigo:
        return jsonify({'error': 'Código incorrecto'}), 400

    # Generar token y guardarlo en la misma sesión
    token = secrets.token_hex(32)
    session['recuperacion']['token'] = token
    session.modified = True

    return jsonify({'token': token}), 200


@usuarios_bp.route('/usuarios/reenviar_codigo_recuperacion', methods=['POST'])
def reenviar_codigo_recuperacion():
    """Reenvía el código de recuperación."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Datos inválidos'}), 400

    id_usuario = data.get('idUsuario')
    metodo     = data.get('metodo')
    valor      = data.get('valor', '').strip()

    # Reutilizamos la misma lógica llamando al endpoint interno
    # Simplemente regeneramos y reenviamos
    try:
        id_usuario = int(id_usuario)
    except (ValueError, TypeError):
        return jsonify({'error': 'Usuario inválido'}), 400

    usuario = Usuario.query.get(id_usuario)
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    codigo = ''.join(secrets.choice(string.digits) for _ in range(6))
    expira = datetime.now() + timedelta(minutes=10)

    session['recuperacion'] = {
        'idUsuario': usuario.idUsuario,
        'codigo':    codigo,
        'expira':    expira.isoformat(),
        'token':     None,
    }

    exito = False
    if metodo == 'email':
        cuerpo = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;">
        <div style="max-width:600px;margin:0 auto;padding:20px;border:1px solid #e0e0e0;border-radius:10px;">
            <h2 style="color:#002b50;text-align:center;">CitaNet — Código Reenviado</h2>
            <p>Hola, <strong>{usuario.nombreUsuario}</strong>:</p>
            <p>Tu nuevo código de recuperación es:</p>
            <div style="text-align:center;margin:30px 0;">
                <span style="font-size:2rem;font-weight:bold;letter-spacing:8px;color:#5bbfa6;
                             background:#f4f7f6;padding:15px 30px;border-radius:10px;">{codigo}</span>
            </div>
            <p style="color:#666;font-size:0.9rem;">Este código es válido por <strong>10 minutos</strong>.</p>
        </div>
        </body></html>
        """
        exito = enviar_correo_base(usuario.correo, 'Nuevo código de recuperación — CitaNet', cuerpo)
    elif metodo == 'phone':
        mensaje_wa = f'🔐 *CitaNet* — Nuevo código de recuperación\n\nHola *{usuario.nombreUsuario}*, tu nuevo código es:\n\n*{codigo}*\n\n_Válido por 10 minutos._'
        exito = enviar_whatsapp(numero=usuario.telefono, mensaje=mensaje_wa, idEmpresaEnvia=usuario.idEmpresa)

    if not exito:
        return jsonify({'error': 'No se pudo reenviar el código'}), 500

    return jsonify({'mensaje': 'Código reenviado exitosamente'}), 200


@usuarios_bp.route('/usuarios/cambiar_contrasena_recuperacion', methods=['POST'])
def cambiar_contrasena_recuperacion():
    """Cambia la contraseña usando el token validado."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Datos inválidos'}), 400

    id_usuario       = data.get('idUsuario')
    token            = data.get('token', '').strip()
    nueva_contrasena = data.get('nueva_contrasena', '')

    try:
        id_usuario = int(id_usuario)
    except (ValueError, TypeError):
        return jsonify({'error': 'Usuario inválido'}), 400

    # Validar token desde la sesión Flask
    registro = session.get('recuperacion')
    if not registro or registro.get('idUsuario') != id_usuario:
        return jsonify({'error': 'Sesión de recuperación inválida o expirada'}), 400

    if not registro.get('token') or registro['token'] != token:
        return jsonify({'error': 'Token inválido. Verifica el código nuevamente.'}), 400

    # Validar contraseña
    if len(nueva_contrasena) < 8:
        return jsonify({'error': 'La contraseña debe tener al menos 8 caracteres'}), 400
    if not any(c.isupper() for c in nueva_contrasena):
        return jsonify({'error': 'La contraseña debe tener al menos una mayúscula'}), 400
    if not any(c.islower() for c in nueva_contrasena):
        return jsonify({'error': 'La contraseña debe tener al menos una minúscula'}), 400
    if not any(c.isdigit() for c in nueva_contrasena):
        return jsonify({'error': 'La contraseña debe tener al menos un número'}), 400

    # Cambiar contraseña
    try:
        usuario = Usuario.query.get(id_usuario)
        if not usuario:
            return jsonify({'error': 'Usuario no encontrado'}), 404

        usuario.password = generate_password_hash(nueva_contrasena)
        db.session.commit()

        # Limpiar la sesión de recuperación
        session.pop('recuperacion', None)

        logger.info(f"Contraseña cambiada exitosamente para usuario {id_usuario}")
        return jsonify({'mensaje': 'Contraseña actualizada exitosamente'}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al cambiar contraseña: {e}")
        return jsonify({'error': 'Error interno al cambiar la contraseña'}), 500