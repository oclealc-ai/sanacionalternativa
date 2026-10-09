from flask    import Blueprint, render_template, request, redirect, session, url_for
from modelos  import db, Frase
from datetime import date

import config

frases_bp = Blueprint("frases", __name__)

# ==========================================
# SEGURIDAD: Middleware Staff
# ==========================================
def login_staff_required():
    if 'idUsuario' not in session or 'idEmpresa' not in session or session.get("idEmpresa") != 1:
        return False    
    return True

# ==========================================
# RUTAS ADMINISTRATIVAS
# ==========================================

@frases_bp.route('/admin/frases')
def listar_frases():
    
    if not login_staff_required(): return redirect(config.URL_BASE)
    
    # Filtro estricto por idEmpresa de la sesión
    frases_lista = Frase.query.filter_by(
        idEmpresa=session.get("idEmpresa")
    ).order_by(Frase.fecha.desc()).all()
    
    return render_template("frases_listar.html", frases=frases_lista)

@frases_bp.route('/frases/nueva')
def nueva_frase():
    if not login_staff_required(): return redirect(config.URL_BASE)
    
    return render_template("frase_nueva.html")

@frases_bp.route('/frases/guardar', methods=['POST'])
def frases_guardar():
    if not login_staff_required(): return redirect(config.URL_BASE)
    
    texto = request.form.get("frase", "").strip()
    if texto:
        nueva = Frase(
            frase=texto, 
            fecha=date.today(), 
            idEmpresa=session.get("idEmpresa")
        )
        db.session.add(nueva)
        db.session.commit()
    return redirect(url_for("frases.listar_frases"))

@frases_bp.route('/frases/editar/<int:idFrase>')
def editar_frase(idFrase):
    if not login_staff_required(): return redirect(config.URL_BASE)
    
    frase_obj = Frase.query.get_or_404(idFrase)
    
    # Validar que la frase pertenezca a la empresa del usuario
    if frase_obj.idEmpresa != session.get("idEmpresa"):
        return "No autorizado", 403
        
    return render_template("frases_editar.html", registro=frase_obj)

@frases_bp.route('/frases/actualizar', methods=['POST'])
def actualizar_frase():
    if not login_staff_required(): return redirect(config.URL_BASE)
    
    id_f = request.form.get("idFrase")
    frase_obj = Frase.query.get_or_404(id_f)
    
    if frase_obj.idEmpresa != session.get("idEmpresa"):
        return "No autorizado", 403
        
    frase_obj.frase = request.form.get("frase", "").strip()
    db.session.commit()
        
    return redirect(url_for("frases.listar_frases"))

@frases_bp.route('/frases/borrar/<int:idFrase>')
def borrar_frase(idFrase):
    if not login_staff_required(): return redirect(config.URL_BASE)
    
    frase_obj = Frase.query.get_or_404(idFrase)
    
    # Seguridad de empresa
    if frase_obj.idEmpresa != session.get("idEmpresa"):
        return "No autorizado", 403
        
    db.session.delete(frase_obj)
    db.session.commit()
    return redirect(url_for("frases.listar_frases"))