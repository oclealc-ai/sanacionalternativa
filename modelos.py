from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# ==========================================
# MODELO: Empresa
# ==========================================

class Empresa(db.Model):
    __tablename__ = "empresa" 

    idEmpresa      = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idtipoEmpresa  = db.Column(db.Integer, db.ForeignKey("tipo_empresa.idtipoEmpresa"))
    razonSocial    = db.Column(db.String(80))
    mision         = db.Column(db.Text, nullable=True)
    vision         = db.Column(db.Text, nullable=True)
    rfc            = db.Column(db.String(13))
    fisicaMoral    = db.Column(db.Enum('F', 'M'))
    direccion      = db.Column(db.String(45))
    codigoPostal   = db.Column(db.Integer)
    regimenFiscal  = db.Column(db.Integer)
    telefono       = db.Column(db.String(20))
    contacto       = db.Column(db.String(45))
    slug           = db.Column(db.String(100), unique=True, nullable=True, index=True)
    correoContacto = db.Column(db.String(50))
    url_empresa    = db.Column(db.String(100))
    logo           = db.Column(db.String(255))
    idEstatus      = db.Column(db.Integer, db.ForeignKey("estatus_empresa.idEstatus"), default=1)
    idPlan         = db.Column(db.Integer, db.ForeignKey("plan.idPlan"))
    etiquetaColaborador = db.Column(db.String(30), default="Colaborador")
    etiquetaCliente     = db.Column(db.String(30), default="Cliente")
    fechaVencPlan       = db.Column(db.Date)
    estatusPlan         = db.Column(db.Enum('activa', 'suspendida', 'demo'), default='demo')

    # Relaciones
    tipo    = db.relationship("tipoEmpresa", backref="empresas")
    usuario = db.relationship("Usuario",     backref="empresa_rel", lazy=True)

    
class Plan(db.Model):
    __tablename__ = "plan"

    idPlan          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombrePlan      = db.Column(db.String(50), nullable=False)
    descripcion     = db.Column(db.Text, nullable=True)
    maxCantClientes = db.Column(db.Integer, nullable=False)
    maxCantUsuarios = db.Column(db.Integer, nullable=False)
    costoMensual    = db.Column(db.Numeric(10, 2), nullable=False)
    costoAnual      = db.Column(db.Numeric(10, 2), nullable=False)
    estatusPlan     = db.Column(db.Enum('activo', 'inactivo'), default='activo')

    # Relación para ver qué empresas tienen este plan
    empresas = db.relationship("Empresa", backref="plan_detalles", lazy=True)
    
    
class Version(db.Model):
    __tablename__ = 'versiones'
    idVersion = db.Column(db.Integer, primary_key=True, autoincrement=True)
    numVersion = db.Column(db.String(20), nullable=False) # Ej: 1.0.4
    nombreVersion = db.Column(db.String(100)) # Ej: "Parche de Seguridad"
    descripcion = db.Column(db.Text)
    cambios = db.Column(db.Text) # Aquí puedes guardar una lista de puntos
    fechaLanzamiento = db.Column(db.DateTime, default=db.func.now())
    esCritica = db.Column(db.Boolean, default=False)
    estatusVersion = db.Column(db.String(20), default='estable') # estable, beta, descontinuada

    def __repr__(self):
        return f'<Version {self.numVersion}>'
    
class EstatusEmpresa(db.Model):
    __tablename__ = "estatus_empresa"
    idEstatus = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column(db.String(50), nullable=False) # 'Prueba', 'Activo', 'Suspendido'
    descripcion = db.Column(db.String(100))

    # Relación inversa para saber qué empresas tienen este estatus
    empresas = db.relationship('Empresa', backref='status_negocio', lazy=True)

    def __repr__(self):
        return f'<EstatusEmpresa {self.nombre}>'
    
# ==========================================
# MODELO: TipoEmpresa
# ==========================================
class tipoEmpresa(db.Model):
    __tablename__ = "tipo_empresa"
    idtipoEmpresa = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tipo          = db.Column(db.String(45), nullable=False)
        
    
# ==========================================
# MODELO: Cliente
# ==========================================
class Cliente(db.Model):
    __tablename__ = "cliente"

    idCliente = db.Column(db.Integer, primary_key=True, autoincrement=True)
    password = db.Column(db.String(45))
    nombreCliente = db.Column(db.String(80))
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
    estatus = db.Column(db.Enum('Activo', 'Inactivo', 'Bloqueado', 'Baja'), default='Activo')
    saldo = db.Column(db.Numeric(10, 2), default=0.00)


class ClienteEmpresa(db.Model):
    __tablename__ = "cliente_empresa"

    # Llave primaria compuesta según tu DB física
    idCliente = db.Column(db.Integer, db.ForeignKey("cliente.idCliente"), primary_key=True)
    idEmpresa  = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), primary_key=True)
    fechaRegistro = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    # Relaciones para acceder fácil desde el objeto
    cliente = db.relationship("Cliente", backref=db.backref("membresias", lazy=True))
    empresa  = db.relationship("Empresa", backref=db.backref("clientes", lazy=True))


# ==========================================
# MODELO: Cita
# ==========================================
class Cita(db.Model):
    __tablename__ = "cita"

    idCita = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"))
    idEstatus = db.Column(db.Integer, db.ForeignKey("estatus_cita.idEstatus"))
    idUsuario = db.Column(db.Integer, db.ForeignKey("usuario.idUsuario"))
    idCliente = db.Column(db.Integer, db.ForeignKey("cliente.idCliente"))
    para = db.Column(db.String(45))
    fechaSolicitud = db.Column(db.DateTime, nullable=True) 
    fechaCita = db.Column(db.Date, nullable=False)
    horaCita = db.Column(db.Time, nullable=False)
    duracion = db.Column(db.Integer)
    
    # Medidas Antropométricas
    medidaInicial = db.Column(db.Float, nullable=True)
    medidaFinal   = db.Column(db.Float, nullable=True)
    pesoInicial   = db.Column(db.Float, nullable=True)
    pesoFinal     = db.Column(db.Float, nullable=True)

    # Signos Vitales - Presión Arterial
    sistolicaInicial  = db.Column(db.Integer, nullable=True)
    sistolicaFinal    = db.Column(db.Integer, nullable=True)
    diastolicaInicial = db.Column(db.Integer, nullable=True)
    diastolicaFinal   = db.Column(db.Integer, nullable=True)
    pulsoInicial       = db.Column(db.Integer, nullable=True)
    pulsoFinal         = db.Column(db.Integer, nullable=True)
    oxigenacionInicial = db.Column(db.Integer, nullable=True)
    oxigenacionFinal   = db.Column(db.Integer, nullable=True)
    
    notas = db.Column(db.String(255))

    cliente      = db.relationship("Cliente", backref="cita")
    estatus       = db.relationship("EstatusCita")
    usuario       = db.relationship("Usuario", backref="cita") 

# ==========================================
# MODELOS DE ESTATUS
# ==========================================
class EstatusCita(db.Model):
    __tablename__ = "estatus_cita"

    idEstatus = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(30), unique=True, nullable=False)
    descripcion = db.Column(db.String(100))
    activo = db.Column(db.Boolean, default=True)

    empresas = db.relationship("ColorEstatusCitaEmpresa", backref="estatus_rel", lazy=True)

    @staticmethod
    def nombre_estatus(id_est):
        res = EstatusCita.query.get(id_est)
        return res.nombre if res else None

    @staticmethod
    def id_estatus(nom_est):
        res = EstatusCita.query.filter_by(nombre=nom_est).first()
        return res.idEstatus if res else None
    
class ColorEstatusCitaEmpresa(db.Model):
    __tablename__ = 'color_estatus_cita_empresa'
    
    idColorEstatusCitaEmpresa = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    idEmpresa = db.Column(db.Integer, db.ForeignKey('empresa.idEmpresa'), nullable=False)
    idEstatus = db.Column(db.Integer, db.ForeignKey('estatus_cita.idEstatus'), nullable=False)
    color = db.Column(db.String(7), nullable=False)

    @staticmethod
    def color_cita_estatus(id_empresa, id_estatus):
        reg = ColorEstatusCitaEmpresa.query.filter_by(idEmpresa=id_empresa, idEstatus=id_estatus).first()
        return reg.color if reg else "#5bbfa6"


    
# ==========================================
# MODELO: Usuario
# ==========================================
class Usuario(db.Model):
    __tablename__ = "usuario"

    idUsuario     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa     = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    usuario       = db.Column(db.String(10), nullable=False, index=True)
    alias         = db.Column(db.String(15))
    nombreUsuario = db.Column(db.String(45))
    password      = db.Column(db.String(255), nullable=False)
    tipoUsuario   = db.Column(db.Enum('admin', 'staff', 'asistente', 'superuser'), default='asistente')
    
# ==========================================
# MODELOS AUXILIARES
# ==========================================
class Anuncio(db.Model):
    __tablename__ = "anuncio"

    idAnuncio = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    idCliente = db.Column(db.Integer, db.ForeignKey('cliente.idCliente'), nullable=True)
    imagen = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.String(500), nullable=False)
    urlAnuncio = db.Column(db.String(500), nullable=False)
    fechaInicioVigencia = db.Column(db.Date)
    fechaFinVigencia = db.Column(db.Date)
    activo = db.Column(db.Boolean, default=False)
    fechaCreacion = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    cliente = db.relationship("Cliente", backref="anuncio")
    empresa = db.relationship('Empresa', backref='anuncio')
    
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
    idCita = db.Column(db.Integer, db.ForeignKey("cita.idCita"), nullable=False)
    idUsuario = db.Column(db.Integer, db.ForeignKey("usuario.idUsuario"), nullable=False)
    fechaMovimiento = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    comentario = db.Column(db.String(255))
    idEstatusAnt = db.Column(db.Integer, nullable=False)
    idEstatusNew = db.Column(db.Integer, nullable=False)