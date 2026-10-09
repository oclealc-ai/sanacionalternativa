from flask import Blueprint
from modelos import db, Cliente

verificar_bp = Blueprint("verificar", __name__)

@verificar_bp.route("/verificar/<token>")
def verificar_correo(token):
    
    cliente = Cliente.query.filter_by(tokenCorreoVerificacion=token).first()
    
    if cliente:
        cliente.correoValido = True
        cliente.tokenCorreoVerificacion = None 
        db.session.commit()
        return "<h2>Correo verificado correctamente ✔</h2><p>Ya puedes cerrar esta ventana.</p>"
    else:
        return "<h2>Enlace no válido</h2><p>El código de verificación ha expirado o ya ha sido utilizado.</p>", 400