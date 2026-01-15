from flask import Blueprint, render_template, request, redirect
from database import conectar_bd

empresas_bp = Blueprint("empresas", __name__)

@empresas_bp.route("/admin/empresas", methods=["GET", "POST"])
def empresas():
    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)

    empresa_edit = None

    # Eliminar
    if "delete" in request.args:
        cursor.execute("DELETE FROM Empresa WHERE idEmpresa=%s",
                       (request.args["delete"],))
        conn.commit()
        return redirect("/admin/empresas")

    # Editar
    if "edit" in request.args:
        cursor.execute("SELECT * FROM Empresa WHERE idEmpresa=%s",
                       (request.args["edit"],))
        empresa_edit = cursor.fetchone()

    # Guardar / Actualizar
    if request.method == "POST":
        datos = (
            request.form["RazonSocial"],
            request.form["RFC"],
            request.form["FisicaMoral"],
            request.form["RegimenFiscal"],
            request.form["Direccion"],
            request.form["CodigoPostal"],
            request.form["Telefono"],
            request.form["Contacto"]
        )

        if request.form.get("idEmpresa"):
            cursor.execute("""
                UPDATE Empresa SET
                RazonSocial=%s, RFC=%s, FisicaMoral=%s, RegimenFiscal=%s, Direccion=%s,
                CodigoPostal=%s, Telefono=%s, Contacto=%s
                WHERE idEmpresa=%s
            """, datos + (request.form["idEmpresa"],))
        else:
            cursor.execute("""
                INSERT INTO Empresa
                (RazonSocial, RFC, FisicaMoral, RegimenFiscal, Direccion, CodigoPostal, Telefono, Contacto)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, datos)

        conn.commit()
        return redirect("/admin/empresas")

    cursor.execute("SELECT * FROM Empresa ORDER BY RazonSocial")
    empresas = cursor.fetchall()

    return render_template("empresas.html",
                           empresas=empresas,
                           empresa_edit=empresa_edit)
