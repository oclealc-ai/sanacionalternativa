from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from modelos import db, Version
import os

versiones_bp = Blueprint('versiones', __name__)

# --- LISTADO DE VERSIONES ---
@versiones_bp.route('/versiones')
def lista_versiones():
    if session.get('tipoUsuario') != 'superuser':
        flash("Acceso denegado", "danger")
        return redirect(url_for('cliente.login'))
    
    versiones = Version.query.order_by(Version.fechaLanzamiento.desc()).all()
    return render_template('versiones_lista.html', versiones=versiones)

# --- GESTIÓN (CREAR/EDITAR) ---
@versiones_bp.route('/versiones/gestion', defaults={'idVersion': None}, methods=['GET', 'POST'])
@versiones_bp.route('/versiones/gestion/<int:idVersion>', methods=['GET', 'POST'])
def gestion_version(idVersion):
    if session.get('tipoUsuario') != 'superuser':
        return redirect(url_for('cliente.login'))

    version = Version.query.get(idVersion) if idVersion else None

    if request.method == 'POST':
        num = request.form.get('numVersion')
        nombre = request.form.get('nombreVersion')
        desc = request.form.get('descripcion')
        cambios = request.form.get('cambios')
        critica = True if request.form.get('esCritica') == 'on' else False
        estatus = request.form.get('estatusVersion')
        
        archivo_apk = request.files.get('archivo_apk')

        if not version:
            version = Version()
            db.session.add(version)

        version.numVersion = num
        version.nombreVersion = nombre
        version.descripcion = desc
        version.cambios = cambios
        version.esCritica = critica
        version.estatusVersion = estatus

        try:
            db.session.commit() # Flush para obtener el idVersion si es nuevo
            
            # Manejo del archivo APK
            if archivo_apk and archivo_apk.filename != '':
                # Carpeta de destino
                upload_folder = os.path.join('static', 'uploads', 'apks')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                
                # Nombre de archivo solicitado: citanet_apk_v + clave + .apk
                nombre_archivo = f"citanet_apk_v{version.idVersion}.apk"
                ruta_completa = os.path.join(upload_folder, nombre_archivo)
                
                # Guardar (sobreescribe si existe)
                archivo_apk.save(ruta_completa)
                
                # Actualizar el modelo con el nombre del archivo
                version.archivo_apk = nombre_archivo
                db.session.commit()

            flash(f"Versión {num} guardada correctamente", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error al guardar versión: {str(e)}", "danger")

        return redirect(url_for('versiones.lista_versiones'))

    return render_template('version_form.html', version=version)

# --- ELIMINAR VERSIÓN ---
@versiones_bp.route('/versiones/eliminar/<int:idVersion>')
def eliminar_version(idVersion):
    if session.get('tipoUsuario') != 'superuser':
        return redirect(url_for('cliente.login'))

    version = Version.query.get_or_404(idVersion)
    
    # Opcional: Eliminar el archivo físico si existe
    if version.archivo_apk:
        ruta = os.path.join('static', 'uploads', 'apks', version.archivo_apk)
        if os.path.exists(ruta):
            os.remove(ruta)
            
    db.session.delete(version)
    db.session.commit()
    flash("Versión eliminada del historial", "success")
    return redirect(url_for('versiones.lista_versiones'))