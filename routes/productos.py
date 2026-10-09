import os
import uuid

from flask   import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from modelos import db, Producto, Empresa, ProductoUsuario, PreguntaServicio, ConfiguracionPaquetePublicidad

# Definimos el Blueprint
productos_bp = Blueprint('productos', __name__)

# ==========================================
# IMÁGENES DE PRODUCTOS (carrusel del menú del cliente)
# ==========================================
CARPETA_IMG_PRODUCTOS = os.path.join('img', 'productos')   # dentro de /static
EXTENSIONES_IMG = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
MAX_BYTES_IMG = 5 * 1024 * 1024    # 5 MB por imagen
MAX_LADO_IMG = 900                 # px; se reduce si la foto es más grande

def _ruta_carpeta_img():
    ruta = os.path.join(current_app.static_folder, CARPETA_IMG_PRODUCTOS)
    os.makedirs(ruta, exist_ok=True)
    return ruta

def _url_imagen_producto(nombre_archivo):
    if not nombre_archivo:
        return None
    return url_for('static', filename=CARPETA_IMG_PRODUCTOS.replace(os.sep, '/') + '/' + nombre_archivo)

def _guardar_imagen_producto(archivo):
    """Valida y guarda la imagen. Devuelve el nombre del archivo guardado,
    o None si no se envió archivo. Lanza ValueError si el archivo no es válido."""
    if not archivo or not archivo.filename:
        return None

    ext = archivo.filename.rsplit('.', 1)[-1].lower() if '.' in archivo.filename else ''
    if ext not in EXTENSIONES_IMG:
        raise ValueError('La imagen debe ser PNG, JPG, WEBP o GIF.')

    archivo.stream.seek(0, os.SEEK_END)
    tamano = archivo.stream.tell()
    archivo.stream.seek(0)
    if tamano > MAX_BYTES_IMG:
        raise ValueError('La imagen no puede pesar más de 5 MB.')

    carpeta = _ruta_carpeta_img()
    try:
        from PIL import Image, ImageOps
    except ImportError:
        Image = None

    if Image is not None:
        # Con Pillow: se valida que sea imagen real, se corrige la rotación de
        # fotos de celular y se reduce el tamaño para que el carrusel cargue rápido.
        try:
            img = Image.open(archivo.stream)
            img = ImageOps.exif_transpose(img)
            img.thumbnail((MAX_LADO_IMG, MAX_LADO_IMG))
            nombre = f"{uuid.uuid4().hex}.webp"
            img.save(os.path.join(carpeta, nombre), 'WEBP', quality=85)
            return nombre
        except Exception:
            raise ValueError('El archivo no es una imagen válida.')

    # Sin Pillow: se guarda tal cual (solo con extensión validada)
    nombre = f"{uuid.uuid4().hex}.{ext}"
    archivo.save(os.path.join(carpeta, nombre))
    return nombre

def _borrar_imagen_producto(nombre_archivo):
    """Borra el archivo del disco (si existe). Nunca lanza error."""
    if not nombre_archivo:
        return
    try:
        # basename evita rutas raras guardadas en BD
        ruta = os.path.join(_ruta_carpeta_img(), os.path.basename(nombre_archivo))
        if os.path.isfile(ruta):
            os.remove(ruta)
    except Exception:
        pass

@productos_bp.route('/admin/productos')
def productos_empresa():
    # Validación de sesión
    if 'idEmpresa' not in session:
        flash('Sesión expirada. Por favor, inicie sesión de nuevo.', 'danger')
        return redirect(url_for('login')) # Ajusta al nombre de tu ruta de login

    id_empresa = session['idEmpresa']
    
    # Consultamos los productos de esta empresa específica
    productos = Producto.query.filter_by(idEmpresa=id_empresa).order_by(Producto.nombre).all()
    
    # Obtenemos datos de la empresa para el encabezado
    empresa_obj = Empresa.query.get(id_empresa)
    nombre_empresa = empresa_obj.razonSocial if empresa_obj else "CitaNet System"

    return render_template('productos.html', 
                           productos=productos, 
                           empresa=nombre_empresa,
                           nombre=session.get('nombre', 'Admin'),
                           es_citanet=(id_empresa == 1))


@productos_bp.route('/admin/productos/guardar', methods=['POST'])
def guardar():
    if 'idEmpresa' not in session:
        return redirect(url_for('login'))

    id_empresa = session['idEmpresa']
    id_producto = request.form.get('idProducto')
    
    # Recolección de datos del formulario
    nombre = request.form.get('nombre')
    tipo = request.form.get('tipo')
    costo = request.form.get('costo', 0)
    descripcion = request.form.get('descripcion')
    tiempo = request.form.get('tiempoEstimado')
    cupo_maximo = request.form.get('cupoMaximo', 1)
    activo = True if request.form.get('activo') else False

    # Solo aplica para el catálogo propio de CitaNet (idEmpresa=1) y productos tipo 'producto'
    es_paquete_publicidad = (id_empresa == 1 and tipo == 'producto')
    cantidad_publicidad = request.form.get('cantidadPublicidad')
    dias_vigencia = request.form.get('diasVigencia')

    def guardar_config_paquete(producto_obj):
        if not es_paquete_publicidad:
            return
        config = ConfiguracionPaquetePublicidad.query.filter_by(idProducto=producto_obj.idProducto).first()
        if not config:
            config = ConfiguracionPaquetePublicidad(idProducto=producto_obj.idProducto)
            db.session.add(config)
        config.cantidadPublicidad = int(cantidad_publicidad) if cantidad_publicidad else 1
        config.diasVigencia = int(dias_vigencia) if dias_vigencia else 30

    nueva_imagen = None       # archivo recién guardado (se borra si hay rollback)
    imagen_anterior = None    # archivo reemplazado/quitado (se borra tras el commit)
    quitar_imagen = bool(request.form.get('quitarImagen'))

    try:
        nueva_imagen = _guardar_imagen_producto(request.files.get('imagen'))

        if id_producto and id_producto != "":
            # --- ACTUALIZACIÓN ---
            p = Producto.query.get(id_producto)
            if p and p.idEmpresa == id_empresa:
                p.nombre = nombre
                p.tipo = tipo
                p.costo = costo
                p.descripcion = descripcion
                p.tiempoEstimado = tiempo if tipo == 'servicio' else None
                p.cupoMaximo = int(cupo_maximo) if tipo == 'servicio' and cupo_maximo not in (None, '') else 1
                p.activo = activo
                if nueva_imagen:
                    imagen_anterior = p.imagen
                    p.imagen = nueva_imagen
                elif quitar_imagen and p.imagen:
                    imagen_anterior = p.imagen
                    p.imagen = None
                guardar_config_paquete(p)
                flash('Registro actualizado correctamente', 'success')
        else:
            # --- ALTA NUEVA ---
            nuevo_p = Producto(
                idEmpresa=id_empresa,
                nombre=nombre,
                tipo=tipo,
                costo=costo,
                descripcion=descripcion,
                tiempoEstimado=tiempo if tipo == 'servicio' else None,
                cupoMaximo=int(cupo_maximo) if tipo == 'servicio' and cupo_maximo not in (None, '') else 1,
                activo=activo,
                imagen=nueva_imagen
            )
            db.session.add(nuevo_p)
            db.session.flush()  # para tener nuevo_p.idProducto disponible
            guardar_config_paquete(nuevo_p)
            flash('Nuevo item agregado al catálogo', 'success')
        
        # El commit se ejecuta para ambos casos de manera segura
        db.session.commit()
        _borrar_imagen_producto(imagen_anterior)
        
    except Exception as e:
        db.session.rollback()
        _borrar_imagen_producto(nueva_imagen)
        flash(f'Error en la operación: {str(e)}', 'danger')
        
        # En caso de error en la BD, se renderiza la vista de nuevo con los datos actuales
        productos = Producto.query.filter_by(idEmpresa=session['idEmpresa']).all()
        return render_template('productos.html', productos=productos, empresa=session.get('razonSocial', 'CitaNet'), es_citanet=(id_empresa == 1))

    # RETORNO GLOBAL: Si todo sale bien (Alta o Edición), redirige a la vista del catálogo
    return redirect(url_for('productos.productos_empresa'))

    

@productos_bp.route('/admin/productos/eliminar/<int:id>')
def eliminar(id):
    if 'idEmpresa' not in session:
        return redirect(url_for('login'))

    # Buscamos el producto asegurando que pertenezca a la empresa del usuario
    p = Producto.query.filter_by(idProducto=id, idEmpresa=session['idEmpresa']).first()
    
    if p:
        try:
            imagen_p = p.imagen
            db.session.delete(p)
            db.session.commit()
            _borrar_imagen_producto(imagen_p)
            flash('El registro ha sido eliminado del catálogo', 'warning')
        except Exception as e:
            db.session.rollback()
            flash('No se puede eliminar: el producto podría estar ligado a citas existentes', 'danger')
    else:
        flash('Registro no encontrado o sin permisos', 'danger')
            
    return redirect(url_for('productos.productos_empresa'))


# ==========================================
# VISTA PRINCIPAL DEL CUESTIONARIO POR SERVICIO
# ==========================================
@productos_bp.route('/admin/preguntas', methods=['GET'])
def listar_preguntas():
    if 'idEmpresa' not in session:
        return redirect(url_for('login'))

    id_empresa = session['idEmpresa']
    id_producto = request.args.get('idProducto') # Cambiado de idProducto a id_producto para tu estándar
    
    if not id_producto:
        flash('No se especificó un servicio válido.', 'danger')
        return redirect(url_for('productos.productos_empresa'))

    # Buscamos el servicio en tu base de datos
    producto = Producto.query.filter_by(idProducto=id_producto, idEmpresa=id_empresa).first()
    
    if not producto:
        flash('El servicio solicitado no existe o no pertenece a tu empresa.', 'danger')
        return redirect(url_for('productos.productos_empresa'))

    # Traemos las preguntas asociadas a este servicio e idEmpresa
    preguntas = PreguntaServicio.query.filter_by(idProducto=id_producto, idEmpresa=id_empresa).all()

    # Retornamos el HTML que creamos pasando el objeto producto (para el título) y la lista de preguntas
    return render_template('preguntas.html', producto=producto, preguntas=preguntas)


# ==========================================
# ACCIÓN: GUARDAR / EDITAR PREGUNTA
# ==========================================
@productos_bp.route('/admin/preguntas/guardar', methods=['POST'])
def guardar_pregunta():
    idEmpresa = session.get('idEmpresa')
    if not idEmpresa:
        flash('Sesión expirada.', 'danger')
        return redirect(url_for('login'))

    idProducto = request.form.get('idProducto')
    idPregunta = request.form.get('idPregunta')
    texto_pregunta = request.form.get('pregunta')
    tipo_dato = request.form.get('tipoDatoRespuesta')

    try:
        if idPregunta:  # MODO EDICIÓN
            pregunta_obj = PreguntaServicio.query.filter_by(idPregunta=idPregunta, idEmpresa=idEmpresa).first()
            if pregunta_obj:
                pregunta_obj.pregunta = texto_pregunta
                pregunta_obj.tipoDatoRespuesta = tipo_dato
                flash('Pregunta actualizada exitosamente.', 'success')
            else:
                flash('No se encontró la pregunta a modificar.', 'danger')
        else:  # MODO NUEVO REGISTRO
            nueva_pregunta = PreguntaServicio(
                idEmpresa=idEmpresa,
                idProducto=idProducto, # Atributo requerido para saber de cuál servicio es
                pregunta=texto_pregunta,
                tipoDatoRespuesta=tipo_dato
            )
            db.session.add(nueva_pregunta)
            flash('Nueva pregunta agregada al servicio.', 'success')

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar la solicitud: {str(e)}', 'danger')

    return redirect(url_for('productos.listar_preguntas', idProducto=idProducto))


# ==========================================
# ACCIÓN: ELIMINAR PREGUNTA
# ==========================================
@productos_bp.route('/admin/preguntas/eliminar/<int:id>', methods=['GET'])
def eliminar_pregunta(id):
    idEmpresa = session.get('idEmpresa')
    idProducto = request.args.get('idProducto') # Captura el id del query string enviado por JS
    
    if not idEmpresa:
        flash('Sesión expirada.', 'danger')
        return redirect(url_for('login'))

    pregunta_obj = PreguntaServicio.query.filter_by(idPregunta=id, idEmpresa=idEmpresa).first()
    if pregunta_obj:
        try:
            db.session.delete(pregunta_obj)
            db.session.commit()
            flash('Pregunta eliminada correctamente.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'No se pudo eliminar la pregunta: {str(e)}', 'danger')
    else:
        flash('La pregunta no existe o no cuentas con los permisos.', 'danger')

    return redirect(url_for('productos.listar_preguntas', idProducto=idProducto))


# ==========================================
# API JSON: CONSUMIDA POR EL FETCH DE EDICIÓN
# ==========================================
@productos_bp.route('/admin/api/pregunta/<int:id>', methods=['GET'])
def api_obtener_pregunta(id):
    idEmpresa = session.get('idEmpresa')
    if not idEmpresa:
        return jsonify({'error': 'No autorizado'}), 401

    pregunta_obj = PreguntaServicio.query.filter_by(idPregunta=id, idEmpresa=idEmpresa).first()
    if not pregunta_obj:
        return jsonify({'error': 'Pregunta no encontrada'}), 404

    # Retorna la estructura exacta que tu JS espera leer para rellenar los inputs
    return jsonify({
        'idPregunta': pregunta_obj.idPregunta,
        'pregunta': pregunta_obj.pregunta,
        'tipoDatoRespuesta': pregunta_obj.tipoDatoRespuesta
    })





# --- RUTA API PARA EL MODAL DE EDICIÓN ---
@productos_bp.route('/admin/api/producto/<int:id>')
def obtener_producto_api(id):
    if 'idEmpresa' not in session:
        return jsonify({"error": "No autorizado"}), 401

    p = Producto.query.filter_by(idProducto=id, idEmpresa=session['idEmpresa']).first()
    
    if p:
        config = p.configuracion_publicidad  # Relación definida en el modelo Producto
        return jsonify({
            "idProducto": p.idProducto,
            "nombre": p.nombre,
            "tipo": p.tipo,
            "costo": float(p.costo),
            "tiempoEstimado": p.tiempoEstimado,
            "cupoMaximo": p.cupoMaximo or 1,
            "descripcion": p.descripcion,
            "imagen": _url_imagen_producto(p.imagen),
            "activo": p.activo,
            "cantidadPublicidad": config.cantidadPublicidad if config else None,
            "diasVigencia": config.diasVigencia if config else None
        })
    
    return jsonify({"error": "No encontrado"}), 404


# --- API PARA EL CARRUSEL DEL MENÚ DEL CLIENTE ---
@productos_bp.route('/cliente/api/carrusel_productos')
def carrusel_productos():
    id_empresa = session.get('idEmpresa')
    if not id_empresa:
        return jsonify([]), 401

    productos = (Producto.query
                 .filter(Producto.idEmpresa == id_empresa,
                         Producto.activo == True,
                         Producto.imagen.isnot(None),
                         Producto.imagen != '')
                 .order_by(Producto.nombre)
                 .all())

    return jsonify([
        {
            "idProducto": p.idProducto,
            "nombre": p.nombre,
            "imagen": _url_imagen_producto(p.imagen)
        }
        for p in productos
    ])


@productos_bp.route("/staff/mis_servicios")
def mis_servicios():
    id_usuario = session.get('idUsuario')
    id_empresa = session.get('idEmpresa')
    
    if not id_usuario:
        return redirect(url_for('usuarios.login'))

    # Obtenemos lo que ya tiene
    mis_productos = ProductoUsuario.query.filter_by(idUsuario=id_usuario).all()
    ids_ya_asignados = [p.idProducto for p in mis_productos]

    # Obtenemos lo que NO tiene
    productos_disponibles = Producto.query.filter(
        Producto.idEmpresa == id_empresa,
        Producto.idProducto.not_in(ids_ya_asignados) if ids_ya_asignados else True,
        Producto.activo == True
    ).all()

    empresa_obj = Empresa.query.get(id_empresa)
    nombre_empresa = empresa_obj.razonSocial if empresa_obj else "CitaNet System"

    return render_template("asignar_productos_staff.html", 
                           mis_productos=mis_productos, 
                           productos_empresa=productos_disponibles,
                           empresa=nombre_empresa,
                           nombre=session.get('nombre', 'Staff'))

@productos_bp.route("/staff/guardar_producto", methods=["POST"])
def guardar_producto_staff():
    id_usuario = session.get('idUsuario')
    id_producto = request.form.get('idProducto')
    comentarios = request.form.get('comentarios')

    if id_usuario and id_producto:
        existe = ProductoUsuario.query.filter_by(idUsuario=id_usuario, idProducto=id_producto).first()
        if not existe:
            nueva_asignacion = ProductoUsuario(idProducto=id_producto, idUsuario=id_usuario, comentarios=comentarios)
            db.session.add(nueva_asignacion)
            db.session.commit()
    
    # IMPORTANTE: Redirige a la misma ruta para que HTMX refresque el contenido
    return redirect(url_for('productos.mis_servicios'))

@productos_bp.route("/staff/eliminar_producto/<int:id>", methods=["POST"])
def eliminar_producto_staff(id):
    asignacion = ProductoUsuario.query.get(id)
    if asignacion and asignacion.idUsuario == session.get('idUsuario'):
        db.session.delete(asignacion)
        db.session.commit()
        
    return redirect(url_for('productos.mis_servicios'))