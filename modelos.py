from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class EstatusCita(db.Model):
    __tablename__ = "estatus_cita"

    idEstatus = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(30), unique=True, nullable=False)

    # Relación con estatus_empresa
    empresas = db.relationship("EstatusEmpresa", backref="estatus", lazy=True)

    @staticmethod
    def nombre_estatus(id_estatus):
        estatus = EstatusCita.query.get(id_estatus)
        return estatus.nombre if estatus else None


class EstatusEmpresa(db.Model):
    __tablename__ = "estatus_empresa"

    idEstatusEmpresa = db.Column(db.Integer, primary_key=True)
    idEmpresa = db.Column(db.Integer, nullable=False)
    idEstatus = db.Column(
        db.Integer,
        db.ForeignKey("estatus_cita.idEstatus"),
        nullable=False
    )
    color = db.Column(db.String(7), nullable=False)

    @staticmethod
    def color_estatus(id_estatus, id_empresa):
        estatus_color = EstatusEmpresa.query.filter_by(
            idEstatus=id_estatus,
            idEmpresa=id_empresa
        ).first()

        return estatus_color.color if estatus_color else "#757575"
