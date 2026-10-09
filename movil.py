from flask                      import Blueprint, request, jsonify
from flask_jwt_extended         import create_access_token
from modelos                    import db, Cliente, Usuario, ClienteEmpresa, Empresa, Config, Version
from routes.codigos_telefono    import enviar_OTP
from routes.cliente             import validar_codigo_global, registrar_cliente_json

movil_bp = Blueprint('movil', __name__)

@movil_bp.route('/movil/login/solicitar', methods=['POST'])
def solicitar_codigo():
    """Paso 1: Solicitar código (Usa request.json internamente)"""
    return enviar_OTP()

@movil_bp.route('/movil/verificar_version', methods=['POST'])
def verificar_version():
    data = request.get_json() or {}
    build_cliente = data.get('build') # Recibe ej: "1" o "2" desde el Application.nativeBuildVersion de la app
    
    try:
        build_usuario = int(build_cliente)
    except (ValueError, TypeError):
        # Si por alguna razón la app no manda un build válido, le ponemos 1 por defecto para no romper el flujo
        build_usuario = 1

    try:
        # 1. Consultamos la base de datos para obtener la última versión activa/estable
        # Ordenamos por idVersion descendente para tener el registro más nuevo arriba
        ultima_version = Version.query.filter_by(estatusVersion='estable').order_by(Version.idVersion.desc()).first()
        
        # Fallback por si la tabla está vacía en algún momento
        if not ultima_version:
            return jsonify({"bloquear_por_actualizacion": False, "url_descarga": ""}), 200

        # El idVersion de tu tabla (1, 2...) actúa perfectamente como el BUILD_MINIMO_REQUERIDO
        build_minimo_requerido = ultima_version.idVersion
        nombre_apk = ultima_version.archivo_apk

        # 2. Evaluamos si el usuario se quedó en una versión vieja
        # Si deseas que SOLO se bloquee si marcaste 'esCritica = 1', puedes añadir esa condición aquí.
        # En este caso, si su build es menor al idVersion estable más nuevo, se le invita/obliga a actualizar.
        if build_usuario < build_minimo_requerido:
            
            # Puedes decidir si el bloqueo es opcional u obligatorio dependiendo de 'esCritica'
            # Si esCritica es 1, bloquear_por_actualizacion será True (Bloqueo Total)
            # Si esCritica es 0, puedes poner False si prefieres que solo sea un aviso (o dejarlo siempre True si toda actualización es obligatoria)
            bloquear = True if ultima_version.esCritica == 1 else True # Modifica aquí según tu preferencia empresarial

            return jsonify({
                "bloquear_por_actualizacion": bloquear,
                "url_descarga": f"https://www.citanet.com.mx/static/uploads/apks/{nombre_apk}"
            }), 200

    except Exception as e:
        print(f"Error en verificar_version base de datos: {e}")
        # Ante cualquier error de base de datos, no bloqueamos al usuario para mantener la app operativa
        return jsonify({"bloquear_por_actualizacion": False, "url_descarga": ""}), 200
        
    # Si su versión está al día (build_usuario >= build_minimo_requerido)
    return jsonify({
        "bloquear_por_actualizacion": False,
        "url_descarga": ""
    }), 200



@movil_bp.route('/movil/login/verificar', methods=['POST'])
def verificar_codigo():
    """Paso 2: Validación del código y generación de Token para el Cliente"""
    try:
        response_wrap = validar_codigo_global()
        
        data = response_wrap[0].get_json()
        status = response_wrap[1]

        if status == 200 and data.get('ok'):
            # Si el código es válido, buscamos al Cliente para generar su sesión
            telefono = request.get_json().get('telefono')
            # Buscamos usando el campo correcto de tu modelo 'Cliente'
            cliente = Cliente.query.filter_by(telefono=telefono).first()
            
            if not cliente:
                return jsonify({"ok": False, "msg": "Cliente no encontrado"}), 404
            
            # Generamos el token de acceso con el ID del cliente
            token = create_access_token(identity=str(cliente.idCliente))
            
            # Obtenemos las empresas del cliente (excluyendo CitaNet = idEmpresa 1)
            relaciones = ClienteEmpresa.query.filter_by(idCliente=cliente.idCliente).all()
            empresas = [
                {
                    "id": r.idEmpresa,
                    "nombre": r.empresa.razonSocial if r.empresa else "Desconocida"
                }
                for r in relaciones if r.idEmpresa != 1
            ]
            
            # Si no tiene empresas, devolvemos todas las disponibles (excepto CitaNet)
            if not empresas:
                todas = Empresa.query.filter(Empresa.idEmpresa != 1).all()
                empresas = [{"id": e.idEmpresa, "nombre": e.razonSocial} for e in todas]
            
            # Retornamos la información del cliente y sus empresas
            return jsonify({
                "ok": True,
                "token": token,
                "cliente": {
                    "nombre": cliente.nombreCliente,
                    "id": cliente.idCliente,
                    "empresas": empresas,
                    "empresaId": empresas[0]["id"] if len(empresas) == 1 else None
                }
            }), 200
        
        # Si falla la validación, devolvemos el error tal cual
        return response_wrap
        
    except Exception as e:
        print(f"Error en validación: {str(e)}")
        return jsonify({"ok": False, "msg": "Error al validar el código"}), 500


@movil_bp.route('/movil/login/registrar', methods=['POST'])
def registrar_cliente():
    data = request.get_json() or {}
    result, status = registrar_cliente_json(data)
    return jsonify(result), status


@movil_bp.route('/movil/staff/<int:id_empresa>', methods=['GET'])
def get_staff(id_empresa):
    # Obtenemos los usuarios tipo 'staff' de la empresa
    staff = Usuario.query.filter_by(idEmpresa=id_empresa, tipoUsuario='staff').all()
    return jsonify([{
        "id": s.idUsuario,
        "nombre": s.nombreUsuario
    } for s in staff])

@movil_bp.route('/movil/check_build', methods=['GET'])
def check_build():
    build_cliente = request.args.get('build', '1')
    
    config_global = Config.query.order_by(Config.idConfig.desc()).first()
    build_minimo_obligatorio = config_global.versionApk if config_global else '1'
    
    try:
        bloquear = int(build_cliente) < int(build_minimo_obligatorio)
    except ValueError:
        bloquear = False

    ultima_version = Version.query.order_by(Version.fechaLanzamiento.desc(), Version.idVersion.desc()).first()
    ultimaVersion  = ultima_version.numeroVersion if ultima_version else "1"
    
    return jsonify({
        "bloquear_por_actualizacion": bloquear,
        "url_descarga": "https://www.citanet.com.mx/descargar-app/" + ultimaVersion
    }), 200



@movil_bp.route('/movil/guardar_token', methods=['POST'])
def guardar_token_push():
    data = request.get_json()
    
    # Extraemos los datos que mandará el fetch desde React Native
    id_cliente = data.get('idCliente')
    token_push = data.get('tokenPush')
    
    if not id_cliente or not token_push:
        return jsonify({
            'success': False, 
            'message': 'Faltan parámetros obligatorios (idCliente o tokenPush).'
        }), 400
        
    try:
        # Buscamos al cliente en la base de datos
        cliente = Cliente.query.get(id_cliente)
        
        if not cliente:
            return jsonify({
                'success': False, 
                'message': 'El cliente especificado no existe.'
            }), 404
            
        # Actualizamos el campo nuevo con el token limpio
        cliente.tokenPush = token_push.strip()
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Token Push almacenado correctamente.'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False, 
            'message': f'Error al guardar en el servidor: {str(e)}'
        }), 500