from flask import Blueprint, request, jsonify
from modelos import db, Cliente, Vendedor, CodigoTelefono, Empresa, Pais
from whatsapp import enviar_whatsapp
from sms_mx import enviar_codigo_sms
from datetime import datetime, timedelta

import logging
import random

logger = logging.getLogger(__name__)

codigos_telefono_bp = Blueprint("codigos_telefono", __name__)


def _resolver_registro_y_pais(Modelo, telefono, id_pais_raw):
    """
    Busca un registro (Cliente o Vendedor) por teléfono y resuelve su país.
    - Si llega id_pais_raw, filtra por ese país (comportamiento de siempre).
    - Si no llega, busca solo por teléfono:
        * 1 coincidencia -> resuelve el país de ese registro automáticamente.
        * 2+ coincidencias (mismo teléfono en países distintos; solo puede
          pasar con Cliente, ya que Vendedor.telefono es único) -> no
          adivina: regresa una respuesta de ambigüedad lista para devolver.
    Regresa (registro_o_None, id_pais_resuelto_o_None, respuesta_ambigua_o_None).
    """
    query = Modelo.query.filter_by(telefono=telefono)

    if str(id_pais_raw or "").isdigit():
        id_pais_resuelto = int(id_pais_raw)
        registro = query.filter_by(idPais=id_pais_resuelto).first()
        return registro, id_pais_resuelto, None

    encontrados = query.all()

    if len(encontrados) > 1:
        paises_match = []
        ids_vistos = set()
        for r in encontrados:
            if r.idPais and r.idPais not in ids_vistos:
                ids_vistos.add(r.idPais)
                p = Pais.query.get(r.idPais)
                if p:
                    paises_match.append(p.to_dict())
        respuesta_ambigua = (jsonify({
            "status": "ambiguo",
            "msg": "Encontramos varias cuentas con ese teléfono. Selecciona tu país.",
            "paises": paises_match
        }), 300)
        return None, None, respuesta_ambigua

    registro = encontrados[0] if encontrados else None
    id_pais_resuelto = registro.idPais if registro else None
    return registro, id_pais_resuelto, None


@codigos_telefono_bp.route("/movil/paises", methods=["GET"])
def listar_paises_movil():
    paises = Pais.query.filter_by(activo=True).order_by(Pais.nombre).all()
    return jsonify({
        "paises": [pais.to_dict() for pais in paises]
    })

@codigos_telefono_bp.route("/enviar_codigo", methods=["POST"])
def enviar_OTP():
    try:
        data = request.get_json()
        telefono = str(data.get("telefono", "")).strip().replace(" ", "")
        id_pais = data.get("idPais")
        modo     = data.get("modo") 
        canal    = data.get("canal", "whatsapp")
        id_empresa = data.get("idEmpresa") or 1
        codigo = None 
        
        if not telefono:
            return jsonify({"status": "error", "msg": "Teléfono requerido"}), 400

        # ------------------------------------------------------------
        # Resolución de país: para clientes se resuelve contra Cliente,
        # para vendedores contra Vendedor (que además tiene teléfono único,
        # así que ahí nunca hay ambigüedad real, pero usamos la misma
        # función por consistencia).
        # ------------------------------------------------------------
        if modo in ("vendedor", "vendedor_login"):
            vendedor, id_pais_resuelto, respuesta_ambigua = _resolver_registro_y_pais(Vendedor, telefono, id_pais)
            if respuesta_ambigua:
                return respuesta_ambigua
            cliente = None
        else:
            cliente, id_pais_resuelto, respuesta_ambigua = _resolver_registro_y_pais(Cliente, telefono, id_pais)
            if respuesta_ambigua:
                return respuesta_ambigua
            vendedor = None

        if modo == "login" and not cliente:
            return jsonify({
                "status": "no_encontrado",
                "msg": "Cliente no registrado."
            }), 404

        if modo == "vendedor_login" and not vendedor:
            return jsonify({
                "status": "no_encontrado",
                "msg": "Vendedor no registrado."
            }), 404

        pais = Pais.query.get(id_pais_resuelto) if id_pais_resuelto else None

        try:
            id_empresa = int(id_empresa)
        except (TypeError, ValueError):
            id_empresa = 1

        if not Empresa.query.get(id_empresa):
            return jsonify({
                "status": "error",
                "msg": "La empresa de acceso no es válida."
            }), 400
        
        telefonos_prueba = ["1234567890", "8110646050x"]
        
        if telefono in telefonos_prueba:
            codigo = "123456"
            logger.info(f"✅ SIMULACIÓN: Código fijo para {telefono}")
        else:
            if canal == "whatsapp":
                temp_codigo = str(random.randint(100000, 999999))
                
                exito = enviar_whatsapp(
                    telefono,
                    f"Tu código de verificación es {temp_codigo}. Válido por 5 min.",
                    id_empresa,
                    pais.codigoArea if pais else None
                )
                
                if exito and (not isinstance(exito, tuple) or exito[0]):
                    codigo = temp_codigo
            else:
                codigo = enviar_codigo_sms(telefono)

        if not codigo:
            #logger.error(f"❌ Falló generación/envío para {telefono} vía {canal}")
            return jsonify({"status": "error", "msg": "No se pudo enviar el código"}), 500

        CodigoTelefono.query.filter_by(telefono=telefono).delete()
        
        nuevo_registro = CodigoTelefono(
            telefono=telefono,
            codigo=codigo,
            expiracion=datetime.now() + timedelta(minutes=5)
        )
        db.session.add(nuevo_registro)
        db.session.commit()

        return jsonify({"status": "ok", "idPais": id_pais_resuelto})

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error crítico en enviar_codigo: {str(e)}")
        return jsonify({"status": "error", "msg": "Error interno"}), 500
