from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Paciente(db.Model):
    __tablename__ = "paciente"

    idPaciente = db.Column(db.Integer, primary_key=True, autoincrement=True)

    Password = db.Column(db.String(45))
    NombrePaciente = db.Column(db.String(80))
    FechaNac = db.Column(db.Date)
    Telefono = db.Column(db.String(20))
    Correo = db.Column(db.String(45), nullable=False)
    Direccion = db.Column(db.String(100))
    Ciudad = db.Column(db.String(15))
    Estado = db.Column(db.String(15))
    Pais = db.Column(db.String(15))
    Referencia = db.Column(db.Integer)
    Fallecido = db.Column(db.Boolean, default=False)
    FechaFall = db.Column(db.Date)
    CorreoValido = db.Column(db.Boolean, default=False)
    TokenCorreoVerificacion = db.Column(db.String(255))
    idEmpresa = db.Column(db.Integer, nullable=False)
    Estatus = db.Column(db.Enum("Activo","Inactivo","Bloqueado","Baja"))
    Saldo = db.Column(db.Numeric(10,2), default=0.00)



class Cita(db.Model):
    __tablename__ = "citas"

    idCita = db.Column(db.Integer, primary_key=True, autoincrement=True)

    idEmpresa = db.Column(db.Integer)
    idEstatus = db.Column(db.Integer)

    Terapeuta = db.Column(db.String(10))
    idPaciente = db.Column(db.Integer, db.ForeignKey("paciente.idPaciente"))

    Para = db.Column(db.String(45))

    FechaSolicitud = db.Column(db.DateTime)
    FechaCita = db.Column(db.Date, nullable=False)
    HoraCita = db.Column(db.Time, nullable=False)

    Duracion = db.Column(db.Integer)
    Notas = db.Column(db.String(255))

    # Relación opcional
    paciente = db.relationship("Paciente", backref="citas")
    
    
    
    
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
