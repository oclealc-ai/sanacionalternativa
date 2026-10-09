from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# ==========================================
# MODELO: Empresa
# ==========================================
class Empresa(db.Model):
    __tablename__ = "empresa" 

    idEmpresa      = db.Column(db.Integer, primary_key=True, autoincrement=True)
    razonSocial    = db.Column(db.String(80))
    slug           = db.Column(db.String(10), unique=True, nullable=True, index=True)
    rfc            = db.Column(db.String(13))
    fisicaMoral    = db.Column(db.Enum('F', 'M'))
    direccion      = db.Column(db.String(45))
    codigoPostal   = db.Column(db.Integer)
    regimenFiscal  = db.Column(db.Integer)
    telefono       = db.Column(db.String(20))
    contacto       = db.Column(db.String(45))
    correoContacto = db.Column(db.String(50))

    # Relaciones
    pacientes = db.relationship("Paciente", backref="empresa_rel", lazy=True)
    usuarios = db.relationship("Usuario", backref="empresa_rel", lazy=True)


# ==========================================
# MODELO: Paciente
# ==========================================
class Paciente(db.Model):
    __tablename__ = "paciente"

    idPaciente = db.Column(db.Integer, primary_key=True, autoincrement=True)
    password = db.Column(db.String(45))
    nombrePaciente = db.Column(db.String(80))
    fechaNac = db.Column(db.Date)
    telefono = db.Column(db.String(20))
    correo = db.Column(db.String(45), nullable=False)
    direccion = db.Column(db.String(100))
    ciudad = db.Column(db.String(15))
    estado = db.Column(db.String(15))
    pais = db.Column(db.String(15))
    referencia = db.Column(db.Integer)
    fallecido = db.Column(db.Boolean, default=False, nullable=False)
    fechaFall = db.Column(db.Date)
    correoValido = db.Column(db.Boolean, default=False)
    tokenCorreoVerificacion = db.Column(db.String(255))
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    estatus = db.Column(db.Enum('Activo', 'Inactivo', 'Bloqueado', 'Baja'), default='Activo')
    saldo = db.Column(db.Numeric(10, 2), default=0.00)


# ==========================================
# MODELO: Cita
# ==========================================

class Cita(db.Model):
    __tablename__ = "citas"

    idCita = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"))
    idEstatus = db.Column(db.Integer, db.ForeignKey("estatus_cita.idEstatus"))
    idUsuario = db.Column(db.Integer, db.ForeignKey("usuarios.idUsuario"))
    idPaciente = db.Column(db.Integer, db.ForeignKey("paciente.idPaciente"))
    para = db.Column(db.String(45))
    fechaSolicitud = db.Column(db.DateTime, nullable=True) 
    fechaCita = db.Column(db.Date, nullable=False)
    horaCita = db.Column(db.Time, nullable=False)
    duracion = db.Column(db.Integer)
    notas = db.Column(db.String(255))

    # Relaciones para facilitar el acceso desde el Calendario
    
    # Usamos overlaps para silenciar las advertencias del log
    
    paciente      = db.relationship("Paciente", backref="citas")
    estatus       = db.relationship("EstatusCita")
    usuario       = db.relationship("Usuario", backref="citas") # El terapeuta/usuario
            
# ==========================================
# MODELOS DE ESTATUS
# ==========================================
class EstatusCita(db.Model):
    __tablename__ = "estatus_cita"

    idEstatus = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(30), unique=True, nullable=False)
    descripcion = db.Column(db.String(100))
    activo = db.Column(db.Boolean, default=True)

    empresas = db.relationship("EstatusEmpresa", backref="estatus_rel", lazy=True)

    @staticmethod
    def nombre_estatus(id_est):
        res = EstatusCita.query.get(id_est)
        return res.nombre if res else None

    @staticmethod
    def id_estatus(nom_est):
        res = EstatusCita.query.filter_by(nombre=nom_est).first()
        return res.idEstatus if res else None
    
class EstatusEmpresa(db.Model):
    __tablename__ = "estatus_empresa"

    idEstatusEmpresa = db.Column(db.Integer, primary_key=True)
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    idEstatus = db.Column(db.Integer, db.ForeignKey("estatus_cita.idEstatus"), nullable=False)
    color = db.Column(db.String(7), nullable=False)

    @staticmethod
    def color_estatus(id_est, id_emp):
        res = EstatusEmpresa.query.filter_by(idEstatus=id_est, idEmpresa=id_emp).first()
        return res.color if res else "#757575"


# ==========================================
# MODELO: Usuario
# ==========================================
class Usuario(db.Model):
    __tablename__ = "usuarios"

    idUsuario = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    usuario = db.Column(db.String(10), nullable=False, index=True)
    alias = db.Column(db.String(15))
    nombreUsuario = db.Column(db.String(45))
    password = db.Column(db.String(255), nullable=False)
    tipoUsuario = db.Column(db.Enum('admin', 'terapeuta', 'asistente', 'super'), default='asistente')


# ==========================================
# MODELOS AUXILIARES
# ==========================================
class Anuncio(db.Model):
    __tablename__ = "anuncios"

    idAnuncio = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    idPaciente = db.Column(db.Integer, db.ForeignKey("paciente.idPaciente"), nullable=False)
    imagen = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.String(500), nullable=False)
    urlAnuncio = db.Column(db.String(500), nullable=False)
    fechaInicioVigencia = db.Column(db.Date)
    fechaFinVigencia = db.Column(db.Date)
    activo = db.Column(db.Boolean, default=False)
    fechaCreacion = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    paciente = db.relationship("Paciente", backref="anuncios")

class CodigoTelefono(db.Model):
    __tablename__ = "codigos_telefono"
    telefono = db.Column(db.String(20), primary_key=True)
    codigo = db.Column(db.String(6))
    expiracion = db.Column(db.DateTime)

class Frase(db.Model):
    __tablename__ = "frases"
    idFrase = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    frase = db.Column(db.String(200))

class HistorialCita(db.Model):
    __tablename__ = "historial_cita"
    idHistorial = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idCita = db.Column(db.Integer, db.ForeignKey("citas.idCita"), nullable=False)
    idUsuario = db.Column(db.Integer, db.ForeignKey("usuarios.idUsuario"), nullable=False)
    fechaMovimiento = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    comentario = db.Column(db.String(255))
    idEstatusAnt = db.Column(db.Integer, nullable=False)
    idEstatusNew = db.Column(db.Integer, nullable=False)