import uuid

from flask_sqlalchemy   import SQLAlchemy
from sqlalchemy         import UniqueConstraint, func
from datetime           import date, datetime, timedelta

db = SQLAlchemy()

# ==========================================
# MODELO: Empresa
# ==========================================

class Config(db.Model):
    __tablename__ = 'config'

    idConfig = db.Column(db.Integer, primary_key=True, autoincrement=True)
    versionApk = db.Column(db.String(50), nullable=False, default='1')

    # Producto (paquete de publicidad, idEmpresa=1) que se otorga como bonificación
    # gratuita al dar de alta un cliente / una empresa nueva en CitaNet.
    idProductoBonifCliente = db.Column(db.Integer, db.ForeignKey('producto.idProducto'), nullable=True)
    idProductoBonifEmpresa = db.Column(db.Integer, db.ForeignKey('producto.idProducto'), nullable=True)

    productoBonifCliente = db.relationship("Producto", foreign_keys=[idProductoBonifCliente])
    productoBonifEmpresa = db.relationship("Producto", foreign_keys=[idProductoBonifEmpresa])

    def __repr__(self):
        return f"<Config idConfig={self.idConfig}, versionApk='{self.versionApk}'>"

class Empresa(db.Model):
    __tablename__ = "empresa" 

    idEmpresa      = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idtipoEmpresa  = db.Column(db.Integer, db.ForeignKey("tipo_empresa.idtipoEmpresa"))
    idPais         = db.Column(db.Integer, db.ForeignKey('pais.idPais'), nullable=True)
    idVendedor     = db.Column(db.Integer, db.ForeignKey("vendedor.idVendedor"), nullable=True)
    razonSocial    = db.Column(db.String(80))
    mision         = db.Column(db.Text, nullable=True)
    vision         = db.Column(db.Text, nullable=True)
    rfc            = db.Column(db.String(13))
    fisicaMoral    = db.Column(db.Enum('F', 'M'))
    direccion      = db.Column(db.String(45))
    codigoPostal   = db.Column(db.Integer)
    regimenFiscal  = db.Column(db.Integer)
    telefono       = db.Column(db.String(20))
    contacto       = db.Column(db.String(150))
    slug           = db.Column(db.String(100), unique=True, nullable=True, index=True)
    correoContacto = db.Column(db.String(50))
    url_empresa    = db.Column(db.String(100))
    logo           = db.Column(db.String(255))
    googleMapsUrl  = db.Column(db.String(500))
    idEstatus      = db.Column(db.Integer, db.ForeignKey("estatus_empresa.idEstatus"), default=1)
    etiquetaColaborador = db.Column(db.String(30), default="Colaborador")
    etiquetaCliente     = db.Column(db.String(30), default="Cliente")
    saldo               = db.Column(db.Numeric(10, 2), default=0.00)
    
    aceptaPagosEnLinea_MP = db.Column(db.Boolean, default=False)
    
    # Campos para la integración de Mercado Pago (OAuth)
    mp_access_token = db.Column(db.String(255), nullable=True)
    mp_public_key = db.Column(db.String(255), nullable=True)
    mp_refresh_token = db.Column(db.String(255), nullable=True)
    mp_user_id = db.Column(db.String(100), nullable=True)
    mp_vinculado = db.Column(db.Boolean, default=False)
    
    # Campos para la integración de Stripe (Agregados)
    stripe_secret_key      = db.Column(db.String(255), nullable=True)
    stripe_publishable_key = db.Column(db.String(255), nullable=True)
    stripe_webhook_secret  = db.Column(db.String(255), nullable=True)
    stripe_account_id      = db.Column(db.String(100), nullable=True)

    comisionVarPct = db.Column(db.DECIMAL(5, 2), default=0)
    comisionFija = db.Column(db.DECIMAL(10, 2), default=0)

    # Configuración de Puntos de Lealtad
    aceptaPuntosLealtad = db.Column(db.Boolean, default=False, nullable=False)
    # 'fijo'       -> valorPuntosLealtad = puntos otorgados por cada cita pagada
    # 'porcentaje' -> valorPuntosLealtad = % de lo pagado que se otorga en puntos
    tipoPuntosLealtad  = db.Column(db.Enum('fijo', 'porcentaje', name='tipo_puntos_lealtad'), nullable=True)
    valorPuntosLealtad = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    # 'empresa' -> los puntos se acumulan en una sola bolsa por cliente (cliente_empresa),
    #              usando aceptaPuntosLealtad/tipoPuntosLealtad/valorPuntosLealtad de arriba.
    # 'staff'   -> cada especialista (Usuario) decide si otorga puntos y bajo qué regla;
    #              se acumulan por separado en cliente_staff, uno por cada especialista.
    modoAcumulacionPuntos = db.Column(db.Enum('empresa', 'staff', name='modo_acumulacion_puntos'), default='empresa', nullable=False)

    # Relaciones
    tipo    = db.relationship("tipoEmpresa", backref="empresas")
    usuario = db.relationship("Usuario",     backref="empresa_rel", lazy=True)
    citas   = db.relationship('Cita',        back_populates='empresa')
    pais    = db.relationship('Pais', backref='empresas')
    vendedor = db.relationship('Vendedor', backref=db.backref('empresas_directas', lazy=True))

    
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

class EmpresaPlan(db.Model):
    __tablename__ = "empresa_plan"

    idEmpresaPlan           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa               = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    idPlan                  = db.Column(db.Integer, db.ForeignKey("plan.idPlan"), nullable=False)
    fechaInicio             = db.Column(db.Date, nullable=False, default=date.today)
    fechaVencimiento        = db.Column(db.Date, nullable=False)
    costo                   = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    remanente_plan_anterior = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    costo_plan              = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    estatusPlan             = db.Column(db.Enum('activa', 'suspendida', 'vencida', 'demo'), default='activa')
    fechaRegistro           = db.Column(db.DateTime, default=datetime.now)
    
    # Relaciones para facilitar consultas
    empresa = db.relationship("Empresa", backref=db.backref("historial_planes", lazy=True))
    plan    = db.relationship("Plan", backref=db.backref("empresas_asignadas", lazy=True))
    

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
    archivo_apk = db.Column(db.String(255)) # Ruta al archivo APK para esta versión

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
# MODELO: tipoEmpresa
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
    slug = db.Column(db.String(8), unique=True, nullable=False, index=True, default=lambda: str(uuid.uuid4())[:8])
    password = db.Column(db.String(45))
    nombreCliente = db.Column(db.String(80))
    fechaNac = db.Column(db.Date)
    telefono = db.Column(db.String(20))
    correo = db.Column(db.String(45), nullable=False)
    direccion = db.Column(db.String(100))
    ciudad = db.Column(db.String(15))
    estado = db.Column(db.String(15))
    idPais = db.Column(db.Integer, db.ForeignKey('pais.idPais'), nullable=True)
    referencia = db.Column(db.Integer)
    fallecido = db.Column(db.Boolean, default=False, nullable=False)
    fechaFall = db.Column(db.Date)
    correoValido = db.Column(db.Boolean, default=False)
    tokenCorreoVerificacion = db.Column(db.String(255))
    tokenPush = db.Column(db.String(255), nullable=True)
    estatus = db.Column(db.Enum('Activo', 'Inactivo', 'Bloqueado', 'Baja'), default='Activo')
    faltas = db.Column(db.Integer, default=0)
    ultima_falta = db.Column(db.DateTime, nullable=True, default=None)
    fechaRegistro = db.Column(db.DateTime, nullable=False, default=datetime.now)

    pais  = db.relationship('Pais', backref='clientes')

class ClienteEmpresa(db.Model):
    __tablename__ = "cliente_empresa"

    # Llave primaria compuesta según tu DB física
    idCliente = db.Column(db.Integer, db.ForeignKey("cliente.idCliente"), primary_key=True)
    idEmpresa  = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), primary_key=True)
    saldo = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    puntosLealtad = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    faltas = db.Column(db.Integer, default=0)
    ultima_falta = db.Column(db.DateTime, nullable=True, default=None)

    # Campos para el control de avisos de citas disponibles
    avisoEnviado = db.Column(db.Boolean, default=False, nullable=False)
    fechaUltimoAviso = db.Column(db.DateTime, nullable=True, default=None)

    # Relaciones para acceder fácil desde el objeto
    cliente = db.relationship("Cliente", backref=db.backref("membresias", lazy=True))
    empresa  = db.relationship("Empresa", backref=db.backref("clientes", lazy=True))


class ClienteStaff(db.Model):
    __tablename__ = "cliente_staff"

    # Llave primaria compuesta: un renglón por cada par cliente-especialista.
    idCliente = db.Column(db.Integer, db.ForeignKey("cliente.idCliente"), primary_key=True)
    idUsuario = db.Column(db.Integer, db.ForeignKey("usuario.idUsuario"), primary_key=True)

    # Se guarda también aunque se pueda inferir vía Usuario.idEmpresa, para poder
    # filtrar/reportar por empresa sin necesidad de hacer join contra usuario.
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)

    puntosLealtad = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)

    # Relaciones para acceder fácil desde el objeto
    cliente = db.relationship("Cliente", backref=db.backref("membresias_staff", lazy=True))
    staff   = db.relationship("Usuario", backref=db.backref("clientes_puntos", lazy=True))
    empresa = db.relationship("Empresa")

    def __repr__(self):
        return f'<ClienteStaff Cliente={self.idCliente} Usuario={self.idUsuario} Puntos={self.puntosLealtad}>'


class Producto(db.Model):
    __tablename__ = "producto"

    idProducto = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.String(500))
    imagen = db.Column(db.String(255), nullable=True)
    costo = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    
    # 'servicio' (se agenda tiempo) o 'producto' (se vende stock)
    tipo = db.Column(db.Enum('servicio', 'producto', name='tipo_producto'), nullable=False, default='servicio')
    
    # Solo se llena si tipo == 'servicio' (en minutos)
    tiempoEstimado = db.Column(db.Integer, nullable=True) 
    cupoMaximo = db.Column(db.Integer, nullable=False, default=1)
    
    activo = db.Column(db.Boolean, default=True)
    fechaCreacion = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    # Relación para acceder a la empresa desde el producto
    empresa = db.relationship('Empresa', backref='productos')

    def __repr__(self):
        return f'<Producto {self.nombre}>'


class ConfiguracionPaquetePublicidad(db.Model):
    __tablename__ = "configuracion_paquete_publicidad"

    idConfiguracion    = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idProducto         = db.Column(db.Integer, db.ForeignKey("producto.idProducto"), nullable=False, unique=True)
    cantidadPublicidad = db.Column(db.Integer, nullable=False, default=1)
    diasVigencia       = db.Column(db.Integer, nullable=False, default=30)

    producto = db.relationship("Producto", backref=db.backref("configuracion_publicidad", uselist=False))

    def __repr__(self):
        return f'<ConfiguracionPaquetePublicidad Producto:{self.idProducto} Cant:{self.cantidadPublicidad} Dias:{self.diasVigencia}>'

# ==========================================
# MODELO: Cita
# ==========================================

class Cita(db.Model):
    """
    Una cita es un ESPACIO en la agenda de un staff (fecha, hora, duración).
    Puede tener uno o varios lugares (cupoMaximo):
      - cupoMaximo = 1  -> cita individual (clínicas, spa). Es el valor por defecto.
      - cupoMaximo > 1  -> cita grupal (yoga, natación, inglés...).

    Quién tomó la cita NO vive aquí: vive en CitaCliente (una fila por lugar
    ocupado). El estatus de la cita describe el espacio:
    Creada / Disponible / Completa / Bloqueada / Cancelada / Realizada.
    El estatus de cada asistente vive en CitaCliente.idEstatus.
    """
    __tablename__ = "cita"

    idCita             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa          = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"))
    idEstatus          = db.Column(db.Integer, db.ForeignKey("estatus_cita.idEstatus"))
    idUsuario          = db.Column(db.Integer, db.ForeignKey("usuario.idUsuario"))
    fechaCita          = db.Column(db.Date, nullable=False)
    horaCita           = db.Column(db.Time, nullable=False)
    duracion           = db.Column(db.Integer)

    # --- Capacidad -----------------------------------------------------
    # cupoOcupado cuenta las CitaCliente en Reservada/Confirmada/Realizada.
    # Se mantiene con UPDATE atómico al reservar/cancelar (nunca con un
    # "if" previo en Python) para que dos clientes no tomen el último lugar.
    cupoMaximo         = db.Column(db.Integer, nullable=False, default=1)
    cupoOcupado        = db.Column(db.Integer, nullable=False, default=0)

    # Servicio fijo de la clase (solo citas grupales). NULL en citas
    # individuales, donde el cliente elige sus servicios al reservar.
    idProducto         = db.Column(db.Integer, db.ForeignKey("producto.idProducto"), nullable=True)

    # Notas de la cita como espacio (p. ej. "traer tapete"). Las notas de
    # cada asistente están en CitaCliente.
    notas              = db.Column(db.String(255))
    notasStaff         = db.Column(db.String(255))

    # Slot "maestro" al que pertenece esta cita cuando fue absorbida como
    # continuación de una reserva cuyo servicio requería más tiempo del que
    # dura un solo slot. NULL = cita normal / cita maestra.
    # SOLO aplica a citas con cupoMaximo = 1; las grupales tienen duración fija.
    idCitaMaestra      = db.Column(db.Integer, db.ForeignKey("cita.idCita"), nullable=True)

    estatus       = db.relationship("EstatusCita")
    usuario       = db.relationship("Usuario", backref="cita")
    empresa       = db.relationship('Empresa', back_populates='citas')
    producto      = db.relationship("Producto")

    # Relación reflexiva: desde la cita maestra, cita_maestra.citas_bloqueadas
    # da la lista de slots subsecuentes que quedaron bloqueados por ella.
    citas_bloqueadas = db.relationship(
        "Cita",
        backref=db.backref("cita_maestra", remote_side=[idCita]),
        foreign_keys=[idCitaMaestra]
    )

    @property
    def es_grupal(self):
        return (self.cupoMaximo or 1) > 1

    @property
    def lugares_libres(self):
        return max((self.cupoMaximo or 1) - (self.cupoOcupado or 0), 0)

    @property
    def fin_programado(self):
        """Fecha y hora en que termina la cita (inicio + duración total del bloque)."""
        if not self.fechaCita or self.horaCita is None:
            return None
        return datetime.combine(self.fechaCita, self.horaCita) + timedelta(minutes=int(self.duracion_total() or 0))

    @property
    def ya_paso(self):
        fin = self.fin_programado
        return bool(fin and fin <= datetime.now())

    @property
    def pendiente_de_cerrar(self):
        """
        La cita ya pasó de horario pero todavía tiene clientes en Reservada o Confirmada:
        el staff debe marcarlos Realizada o No Asistencia (o marcar la cita como realizada).
        """
        if not self.ya_paso:
            return False
        if self.estatus and self.estatus.nombre in ('Realizada', 'Bloqueada', 'Vencida', 'Cancelada'):
            return False
        return any(r.estatus and r.estatus.nombre in ('Reservada', 'Confirmada') for r in self.reservas)

    def asientos_ocupados(self):
        ids_ocupan_lugar = [
            EstatusCita.id_estatus("Reservada"),
            EstatusCita.id_estatus("Confirmada"),
            EstatusCita.id_estatus("Realizada"),
        ]
        ids_ocupan_lugar = [id_est for id_est in ids_ocupan_lugar if id_est is not None]
        if not ids_ocupan_lugar:
            return 0
        return int(db.session.query(func.count(CitaCliente.idCitaCliente))
            .filter(CitaCliente.idCita == self.idCita,
                    CitaCliente.idEstatus.in_(ids_ocupan_lugar))
            .scalar() or 0)

    def recalcular_estatus_cita(self):
        if self.idCita is None:
            return None

        id_creada = EstatusCita.id_estatus("Creada")
        id_disponible = EstatusCita.id_estatus("Disponible")
        id_completa = EstatusCita.id_estatus("Completa")
        id_realizada = EstatusCita.id_estatus("Realizada")
        id_bloqueada = EstatusCita.id_estatus("Bloqueada")
        id_cancelada = EstatusCita.id_estatus("Cancelada")
        id_vencida = EstatusCita.id_estatus("Vencida")

        if self.idEstatus == id_realizada or self.idEstatus == id_bloqueada:
            return self.idEstatus

        cupo = max(int(self.cupoMaximo or 1), 1)
        self.cupoMaximo = cupo
        self.cupoOcupado = self.asientos_ocupados()

        sin_clientes_y_ya_paso = (self.cupoOcupado == 0 and self.ya_paso and not self.idCitaMaestra)

        if self.cupoOcupado >= cupo:
            self.idEstatus = id_completa
        elif sin_clientes_y_ya_paso and self.idEstatus == id_cancelada:
            pass  # cita cancelada que ya pasó de horario: se queda cancelada
        elif sin_clientes_y_ya_paso and id_vencida:
            # Ya pasó el horario y no queda ningún cliente activo: la cita se vence.
            self.idEstatus = id_vencida
        elif self.idEstatus in (id_completa, id_creada, id_cancelada, id_vencida, None):
            self.idEstatus = id_disponible

        return self.idEstatus

    def duracion_total(self):
        """
        Duración real del bloque que ocupa esta cita en la agenda: su propia
        duración más la de todos los slots que haya absorbido por bloqueo
        (servicio más largo que un slot). Para una cita normal (sin slots
        bloqueados) es simplemente su propia duración.
        """
        propia = self.duracion or 0
        if self.idProducto:
            return propia
        extra = sum((h.duracion or 0) for h in self.citas_bloqueadas) if self.citas_bloqueadas else 0
        return propia + extra


class CitaCliente(db.Model):
    """
    Un lugar tomado en una cita. Una fila por persona que asiste.

    Un mismo cliente puede tener varias filas en la misma cita, cada una con
    su propio "para" (pareja, amigo, etc.). El teléfono al que se avisa es
    siempre el del cliente (Cliente.telefono); "para" es solo el nombre de
    quien asiste.

    Aquí viven el estatus del asistente (Reservada / Confirmada / Cancelada /
    Realizada / No Asistencia), su costo, servicios (CitaProducto), respuestas
    (CitaPregunta), cargo en cuenta (movCuenta con idMovReferencia =
    idCitaCliente y tipo MOV_CITA) y los controles de recordatorio.
    """
    __tablename__ = "cita_cliente"

    # Estatus (EstatusCita.nombre) que ocupan un lugar en la cita.
    ESTATUS_OCUPAN_LUGAR = ('Reservada', 'Confirmada', 'Realizada')
    # Estatus (EstatusCita.nombre) de quien todavía debe asistir y por tanto recibe avisos/mensajes de la cita...
    ESTATUS_RECIBEN_AVISO = ('Reservada', 'Confirmada')

    idCitaCliente       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idCita              = db.Column(db.Integer, db.ForeignKey("cita.idCita"), nullable=False)
    idCliente           = db.Column(db.Integer, db.ForeignKey("cliente.idCliente"), nullable=False)
    idEstatus           = db.Column(db.Integer, db.ForeignKey("estatus_cita.idEstatus"), nullable=False)
    para                = db.Column(db.String(45))
    costo               = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    fechaSolicitud      = db.Column(db.DateTime, nullable=True)
    notas               = db.Column(db.String(255))
    notasStaff          = db.Column(db.String(255))
    ultimoRecordatorio  = db.Column(db.Date, nullable=True)
    avisoProximoEnviado = db.Column(db.Boolean, default=False)

    cita    = db.relationship("Cita",    backref=db.backref("reservas", lazy=True))
    cliente = db.relationship("Cliente", backref=db.backref("reservas", lazy=True))
    estatus = db.relationship("EstatusCita")

    @property
    def nombre_asistente(self):
        """Quien asiste: el 'para' si lo hay, si no el propio cliente."""
        if self.para and self.para.strip():
            return self.para.strip()
        return self.cliente.nombreCliente if self.cliente else ''

    @property
    def ocupa_lugar(self):
        return bool(self.estatus and self.estatus.nombre in self.ESTATUS_OCUPAN_LUGAR)

    @property
    def recibe_aviso(self):
        return bool(self.estatus and self.estatus.nombre in self.ESTATUS_RECIBEN_AVISO)

    def actualizar_cita_padre(self):
        if self.cita is not None:
            self.cita.recalcular_estatus_cita()

    def __repr__(self):
        return f'<CitaCliente {self.idCitaCliente} cita={self.idCita} cliente={self.idCliente} para={self.para!r}>'


class CitaProducto(db.Model):
    __tablename__ = "cita_producto"

    idCitaProducto = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idCitaCliente = db.Column(db.Integer, db.ForeignKey("cita_cliente.idCitaCliente"), nullable=False)
    idProducto = db.Column(db.Integer, db.ForeignKey("producto.idProducto"), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    precioCobrado = db.Column(db.Numeric(10, 2), nullable=False)
    montoPagado = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    notas = db.Column(db.String(255))

    # Relaciones para acceder fácil desde Python
    reserva = db.relationship("CitaCliente", backref="cita_productos")
    producto = db.relationship("Producto")

class ProductoUsuario(db.Model):
    __tablename__ = 'producto_usuario'
    
    idProductoUsuario = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idProducto = db.Column(db.Integer, db.ForeignKey('producto.idProducto'), nullable=False)
    idUsuario = db.Column(db.Integer, db.ForeignKey('usuario.idUsuario'), nullable=False)
    comentarios = db.Column(db.Text, nullable=True)

    # Relaciones actualizadas
    producto = db.relationship('Producto', backref=db.backref('usuarios_asignados', lazy=True))
    usuario = db.relationship('Usuario', backref=db.backref('productos_asignados', lazy=True))

    def __repr__(self):
        return f'<ProductoUsuario P:{self.idProducto} U:{self.idUsuario}>'
    
# ==========================================
# MODELOS DE ESTATUS
# ==========================================
class EstatusCita(db.Model):
    __tablename__ = "estatus_cita"

    idEstatus = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(30), unique=True, nullable=False)
    descripcion = db.Column(db.String(100))
    orden = db.Column(db.Integer, default=0)
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

    idUsuario               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa               = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    usuario                 = db.Column(db.String(10), nullable=False)
    alias                   = db.Column(db.String(15))
    nombreUsuario           = db.Column(db.String(45))
    password                = db.Column(db.String(255), nullable=False)
    telefono                = db.Column(db.String(20), nullable=True)
    correo                  = db.Column(db.String(45), nullable=False)
    correoValido            = db.Column(db.Boolean, default=False)
    tokenCorreoVerificacion = db.Column(db.String(255))
    tipoUsuario             = db.Column(db.Enum('admin', 'staff', 'asistente', 'superuser'), default='asistente')

    # Configuración de Puntos de Lealtad a nivel especialista.
    # Solo se toman en cuenta cuando Empresa.modoAcumulacionPuntos == 'staff'.
    aceptaPuntosLealtad = db.Column(db.Boolean, default=False, nullable=False)
    tipoPuntosLealtad    = db.Column(db.Enum('fijo', 'porcentaje', name='tipo_puntos_lealtad_staff'), nullable=True)
    valorPuntosLealtad   = db.Column(db.Numeric(10, 2), default=0, nullable=False)

    # Si está activo (True), al agendar una cita con este especialista se obliga
    # a seleccionar un servicio/producto; si está apagado (False), se permite
    # dejarlo en blanco. Configurable por el propio staff, admin o asistente.
    obligaSeleccionServicio = db.Column(db.Boolean, default=False, nullable=False)

    idPais = db.Column(db.Integer, db.ForeignKey('pais.idPais'), nullable=True)
    pais = db.relationship('Pais', backref='usuarios')

    __table_args__ = (
        UniqueConstraint('usuario', 'idEmpresa', name='uniq_usuario_empresa'),
        UniqueConstraint('idEmpresa', 'telefono', name='uq_empresa_telefono'),
    )

    def __repr__(self):
        return f'<Usuario {self.usuario} (Empresa ID: {self.idEmpresa})>'


class Pais(db.Model):
    __tablename__ = 'pais'

    idPais = db.Column(db.Integer, primary_key=True, autoincrement=True)
    clave = db.Column(db.String(2), nullable=False)  # Ej. 'MX', 'US'
    iso3 = db.Column(db.String(3), nullable=False)   # Ej. 'MEX', 'USA'
    nombre = db.Column(db.String(100), nullable=False)
    codigoArea = db.Column(db.String(10), nullable=False) # Ej. '+52', '+1'
    idioma = db.Column(db.String(10), nullable=True, default='es')
    longitudMin = db.Column(db.Integer, nullable=True, default=10)
    longitudMax = db.Column(db.Integer, nullable=True, default=10)
    activo = db.Column(db.Boolean, nullable=True, default=True)

    def __repr__(self):
        return f"<Pais {self.nombre} ({self.codigoArea})>"

    def to_dict(self):
        """Método utilitario para parsear el país a JSON fácilmente en tus rutas de Flask"""
        return {
            'idPais': self.idPais,
            'clave': self.clave,
            'iso3': self.iso3,
            'nombre': self.nombre,
            'codigoArea': self.codigoArea,
            'idioma': self.idioma,
            'longitudMin': self.longitudMin,
            'longitudMax': self.longitudMax,
            'activo': self.activo
        }
    

# ==========================================
# MODELO: Vendedor
# ==========================================
class NivelComisionVendedor(db.Model):
    __tablename__ = "nivel_comision_vendedor"
    
    idNivelComision = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column(db.String(80), nullable=False)
    porcComision = db.Column(db.Numeric(5, 2), nullable=False, default=0.00)
    periodoComisionMeses = db.Column(db.Integer, nullable=False, default=12)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    empresasActivas = db.Column(db.Integer)
    comisionPagada = db.Column(db.Integer)
    fechaCreacion = db.Column(db.DateTime, nullable=False, default=datetime.now)
    
    vendedores = db.relationship('Vendedor', backref=db.backref('nivel_comision', lazy=True))
    
    def __repr__(self):
        return f'<NivelComisionVendedor {self.nombre} - {self.porcComision}%>'

class Vendedor(db.Model):
    __tablename__ = "vendedor"
    
    idVendedor = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column(db.String(150), nullable=False)
    fechaNac = db.Column(db.Date, nullable=True)
    telefono = db.Column(db.String(20), nullable=False, unique=True)
    email = db.Column(db.String(120), nullable=True, unique=True)
    codigoReferido = db.Column(db.String(20), nullable=True, unique=True, index=True)
    idNivelComision = db.Column(db.Integer, db.ForeignKey("nivel_comision_vendedor.idNivelComision"), nullable=False, default=1)
    idPais = db.Column(db.Integer, db.ForeignKey('pais.idPais'), nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    fechaRegistro = db.Column(db.DateTime, nullable=False, default=datetime.now)
    
    # Datos bancarios para pagos de comisiones
    banco = db.Column(db.String(120), nullable=True)
    nombreBanco = db.Column(db.String(120), nullable=True)
    titularCuenta = db.Column(db.String(150), nullable=True)
    tipoCuenta = db.Column(db.String(30), nullable=True)
    numeroCuenta = db.Column(db.String(40), nullable=True)
    clabe = db.Column(db.String(18), nullable=True)
    rfc = db.Column(db.String(13), nullable=True)
    
    # Relaciones
    pais = db.relationship('Pais', backref='vendedores')
    relaciones_empresas = db.relationship('VendedorEmpresa', backref=db.backref('vendedor_ref', lazy=True), cascade='all, delete-orphan')
    pagos = db.relationship('PagoComisionVendedor', backref=db.backref('vendedor_pago', lazy=True), cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Vendedor {self.nombre} ({self.telefono})>'

class VendedorEmpresa(db.Model):
    __tablename__ = "vendedor_empresa"
    
    idVendedorEmpresa = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idVendedor = db.Column(db.Integer, db.ForeignKey("vendedor.idVendedor"), nullable=False)
    idEmpresa = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    fechaInicioPeriodo = db.Column(db.Date, nullable=False)
    fechaFinPeriodo = db.Column(db.Date, nullable=True)
    porcComision = db.Column(db.Numeric(5, 2), nullable=False, default=0.00)
    comisionPagada = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    estatus = db.Column(db.Enum('activo', 'cerrado', 'pagado', 'cancelado'), nullable=False, default='activo')
    fechaRegistro = db.Column(db.DateTime, nullable=False, default=datetime.now)
    
    # Relaciones
    empresa = db.relationship('Empresa', backref=db.backref('vendedor_historial', lazy=True))
    
    __table_args__ = (
        UniqueConstraint('idVendedor', 'idEmpresa', name='uq_vendedor_empresa'),
    )
    
    def __repr__(self):
        return f'<VendedorEmpresa Vendedor={self.idVendedor} Empresa={self.idEmpresa}>'

class PagoComisionVendedor(db.Model):
    __tablename__ = "pago_comision_vendedor"
    
    idPagoComisionVendedor = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idVendedor = db.Column(db.Integer, db.ForeignKey("vendedor.idVendedor"), nullable=False)
    idVendedorEmpresa = db.Column(db.Integer, db.ForeignKey("vendedor_empresa.idVendedorEmpresa"), nullable=True)
    montoPago = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    fechaPago = db.Column(db.DateTime, nullable=False, default=datetime.now)
    aplicado = db.Column(db.Boolean, nullable=False, default=False)
    fechaAplicacion = db.Column(db.DateTime, nullable=True)
    metodoPago = db.Column(db.String(40), nullable=True)
    folioTransferencia = db.Column(db.String(100), nullable=True)
    comprobante = db.Column(db.String(255), nullable=True)
    observaciones = db.Column(db.String(255), nullable=True)
    
    # Relaciones
    vendedor_empresa_ref = db.relationship('VendedorEmpresa', backref=db.backref('pagos_comision', lazy=True))
    
    def __repr__(self):
        return f'<PagoComisionVendedor Vendedor={self.idVendedor} Monto=${self.montoPago}>'

# ==========================================
# MODELOS AUXILIARES
# ==========================================
class Publicidad(db.Model):
    __tablename__ = "publicidad"

    idPublicidad        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa           = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    idCliente           = db.Column(db.Integer, db.ForeignKey('cliente.idCliente'), nullable=True)
    imagen              = db.Column(db.String(255), nullable=False)
    descripcion         = db.Column(db.String(500), nullable=False)
    urlPublicidad       = db.Column(db.String(500), nullable=False)
    fechaInicioVigencia = db.Column(db.Date)
    fechaFinVigencia    = db.Column(db.Date)
    activo              = db.Column(db.Boolean, default=False)
    fechaCreacion       = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    valido_por_citanet  = db.Column(db.Boolean, nullable=False, default=False)
    idMovimiento        = db.Column(db.Integer, db.ForeignKey('movCuenta.idMovimiento'), nullable=True)
    idCompraPublicidad  = db.Column(db.Integer, db.ForeignKey('compra_publicidad.idCompraPublicidad'), nullable=True)
    
    # Relaciones
    cliente     = db.relationship("Cliente", backref="publicidad")
    empresa     = db.relationship('Empresa', backref='publicidad')
    movCuenta   = db.relationship("movCuenta", backref="publicidad")
    compra      = db.relationship("CompraPublicidad", backref="publicidad")
 
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

    idHistorial     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idCita          = db.Column(db.Integer, db.ForeignKey("cita.idCita"), nullable=False)
    # NULL = movimiento de la cita como espacio; con valor = movimiento de un asistente.
    idCitaCliente   = db.Column(db.Integer, db.ForeignKey("cita_cliente.idCitaCliente"), nullable=True)
    idUsuario       = db.Column(db.Integer, db.ForeignKey("usuario.idUsuario"), nullable=False)
    idCliente       = db.Column(db.Integer, db.ForeignKey("cliente.idCliente"), nullable=True) # <--- Nuevo Campo
    fechaMovimiento = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    comentario      = db.Column(db.String(255))
    idEstatusAnt    = db.Column(db.Integer, nullable=False)
    idEstatusNew    = db.Column(db.Integer, nullable=False)

    # Relaciones (opcional pero recomendado para facilitar consultas en Python)
    cita    = db.relationship("Cita", backref=db.backref("historial", lazy=True))
    reserva = db.relationship("CitaCliente", backref=db.backref("historial", lazy=True))
    usuario = db.relationship("Usuario")
    cliente = db.relationship("Cliente", backref=db.backref("historial_citas", lazy=True))


class PreguntaServicio(db.Model):
    __tablename__ = 'preguntas_servicio'
    idEmpresa         = db.Column(db.Integer, db.ForeignKey('empresa.idEmpresa'), nullable=False)
    idProducto        = db.Column(db.Integer, db.ForeignKey('producto.idProducto'), nullable=False)
    idPregunta        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    pregunta          = db.Column(db.String(255), nullable=False)
    tipoDatoRespuesta = db.Column(db.String(50), nullable=False)

    empresa           = db.relationship('Empresa', backref='preguntas', lazy=True)
    producto          = db.relationship('Producto', backref='preguntas', lazy=True)
    # Relación inversa para acceder a las respuestas desde la pregunta si lo necesitas
    respuestas        = db.relationship('CitaPregunta', backref='pregunta_origen', lazy=True)


class CitaPregunta(db.Model):
    __tablename__ = 'cita_pregunta'

    idCitaPregunta = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idPregunta     = db.Column(db.Integer, db.ForeignKey('preguntas_servicio.idPregunta', ondelete='CASCADE'), nullable=False)
    idCitaCliente  = db.Column(db.Integer, db.ForeignKey('cita_cliente.idCitaCliente'), nullable=False) # Cada asistente responde por su cuenta
    respuesta      = db.Column(db.Text, nullable=True)

    reserva        = db.relationship('CitaCliente', backref=db.backref('respuestas', lazy=True))

class ConfiguracionWhatsapp(db.Model):
    __tablename__ = 'ConfiguracionWhatsapp'
    
    idConfigWA        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa         = db.Column(db.Integer, db.ForeignKey('empresa.idEmpresa'), nullable=False)
    etiqueta          = db.Column(db.String(50), default='General')
    telefono          = db.Column(db.String(20), nullable=True)
    instancia         = db.Column(db.String(100), nullable=False)
    token_instancia   = db.Column(db.String(255), nullable=True)
    status_conexion   = db.Column(db.String(20), default='DISCONNECTED')
    fecha_vinculacion = db.Column(db.DateTime, nullable=True)
    fecha_creacion    = db.Column(db.DateTime, default=db.func.current_timestamp())

    # Relación opcional para acceder a los datos de la empresa desde aquí
    empresa = db.relationship('Empresa', backref=db.backref('configuraciones_wa', lazy=True))

    def __repr__(self):
        return f'<ConfigWA {self.etiqueta} - {self.instancia}>'
    
# ==========================================
# MODELO: tipoMovimiento
# ==========================================
class tipoMovimiento(db.Model):
    __tablename__ = "tipoMovimiento"
    idtipoMovimiento = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre           = db.Column(db.String(50), nullable=False)
    naturaleza       = db.Column(db.Enum('A', 'C'), nullable=False) # 'A'=Abono, 'C'=Cargo
    descripcion      = db.Column(db.String(100))   

# ==========================================
# MODELO: metodoPago
# ==========================================
class metodoPago(db.Model):
    __tablename__ = "metodoPago"
    idmetodoPago  = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre        = db.Column(db.String(50), nullable=False)
    activo        = db.Column(db.Boolean, default=True)
    acumulaPuntos = db.Column(db.Boolean, default=True, nullable=False)

    
# ==========================================
# MODELO: movCuenta
# ==========================================
class movCuenta(db.Model):
    __tablename__ = 'movCuenta'

    idMovimiento     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa        = db.Column(db.Integer, db.ForeignKey('empresa.idEmpresa'), nullable=False)
    idCliente        = db.Column(db.Integer, db.ForeignKey('cliente.idCliente'), nullable=True)
    idtipoMovimiento = db.Column(db.Integer, db.ForeignKey('tipoMovimiento.idtipoMovimiento'), nullable=False)
    idmetodoPago     = db.Column(db.Integer, db.ForeignKey('metodoPago.idmetodoPago'), nullable=False)
    # Según idtipoMovimiento: MOV_CITA -> CitaCliente.idCitaCliente (un cargo por
    # asistente); MOV_PLAN -> EmpresaPlan.idEmpresaPlan; etc.
    idMovReferencia  = db.Column(db.Integer, nullable=True)
    fecha            = db.Column(db.Date, nullable=False, default=date.today)
    hora             = db.Column(db.Time, nullable=False, default=lambda: datetime.now().time())
    monto            = db.Column(db.Numeric(10, 2), nullable=False)
    saldoAnterior    = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    saldo            = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    notas            = db.Column(db.String(255), nullable=True)
    idUsuario        = db.Column(db.Integer, db.ForeignKey('usuario.idUsuario'), nullable=True)

    empresa = db.relationship("Empresa", backref=db.backref("movimientos_empresa", lazy=True))
    cliente = db.relationship("Cliente", backref=db.backref("movimientos_cuenta", lazy=True))
    usuario = db.relationship("Usuario")
    tipo    = db.relationship("tipoMovimiento")
    metodo  = db.relationship("metodoPago")
    
    def __repr__(self):
        return f'<movCuenta {self.idMovimiento} - Monto: {self.monto} - Saldo: {self.saldo}>'
    
class movAplica(db.Model):
    __tablename__ = 'movAplica'

    idAplicacion  = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idmovCargo    = db.Column(db.Integer, db.ForeignKey('movCuenta.idMovimiento'), nullable=False)
    idmovAbono    = db.Column(db.Integer, db.ForeignKey('movCuenta.idMovimiento'), nullable=False)
    montoAplicado = db.Column(db.Numeric(10, 2), nullable=False)
    idUsuario     = db.Column(db.Integer, db.ForeignKey('usuario.idUsuario'), nullable=False)
    fechaAplicado = db.Column(db.DateTime, nullable=False, default=datetime.now)

    # Relaciones para que en Python hagas: aplica.cargo.monto o aplica.usuario.NombreUsuario
    cargo   = db.relationship("movCuenta", foreign_keys=[idmovCargo], backref="aplicaciones_recibidas")
    abono   = db.relationship("movCuenta", foreign_keys=[idmovAbono], backref="aplicaciones_realizadas")
    usuario = db.relationship("Usuario")

    def __repr__(self):
        return f'<MovAplica {self.idAplicacion} | Cargo: {self.idmovCargo} | Abono: {self.idmovAbono} | Monto: {self.montoAplicado}>'


class CompraPublicidad(db.Model):
    __tablename__ = "compra_publicidad"

    idCompraPublicidad = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idMovimiento       = db.Column(db.Integer, db.ForeignKey("movCuenta.idMovimiento"), nullable=False)
    idProducto         = db.Column(db.Integer, db.ForeignKey("producto.idProducto"), nullable=False)
    idEmpresa        = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=True)
    idCliente        = db.Column(db.Integer, db.ForeignKey("cliente.idCliente"), nullable=True)
    cantidadPermitida = db.Column(db.Integer, nullable=False, default=1)
    cantidadUsada    = db.Column(db.Integer, nullable=False, default=0)
    diasVigencia     = db.Column(db.Integer, nullable=False, default=30)
    fechaCompra      = db.Column(db.DateTime, nullable=False, default=datetime.now)

    movimiento = db.relationship("movCuenta", backref=db.backref("compra_publicidad", uselist=False))
    producto   = db.relationship("Producto")
    empresa    = db.relationship("Empresa")
    cliente    = db.relationship("Cliente")

    def __repr__(self):
        return f'<CompraPublicidad {self.idCompraPublicidad} Mov:{self.idMovimiento} {self.cantidadUsada}/{self.cantidadPermitida}>'


class FilaEspera(db.Model):
    __tablename__ = "fila_espera"

    idFilaEspera     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idEmpresa        = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)
    idUsuario        = db.Column(db.Integer, db.ForeignKey("usuario.idUsuario"), nullable=False)
    idCliente        = db.Column(db.Integer, db.ForeignKey("cliente.idCliente"), nullable=False)
    idProducto       = db.Column(db.Integer, db.ForeignKey("producto.idProducto"), nullable=True)  # servicio deseado
    activo           = db.Column(db.Boolean, default=True, nullable=False)
    fechaSolicitud   = db.Column(db.DateTime, server_default=db.func.current_timestamp(), nullable=False)
    fechaUltimoAviso = db.Column(db.DateTime, nullable=True)
    cantidadAvisos   = db.Column(db.Integer, default=0, nullable=False)
    fechaVencimiento = db.Column(db.Date, nullable=True)
    # Preferencias de agenda
    diasDesdeCita    = db.Column(db.Integer, nullable=True)   # días mínimos desde última cita
    diasSemana       = db.Column(db.String(20), nullable=True) # ej. "1,3,5" (lun=1 ... dom=7)
    horaDesde        = db.Column(db.Time, nullable=True)       # inicio rango horario preferido
    horaHasta        = db.Column(db.Time, nullable=True)       # fin rango horario preferido

    # Relaciones
    empresa  = db.relationship("Empresa",  backref=db.backref("fila_espera", lazy=True))
    usuario  = db.relationship("Usuario",  backref=db.backref("fila_espera", lazy=True))
    cliente  = db.relationship("Cliente",  backref=db.backref("fila_espera", lazy=True))
    producto = db.relationship("Producto", backref=db.backref("fila_espera", lazy=True))

    def __repr__(self):
        return f'<FilaEspera cliente={self.idCliente} staff={self.idUsuario} empresa={self.idEmpresa}>'

class VisitaIndex(db.Model):
    __tablename__ = "visita_index"

    idVisita     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fecha        = db.Column(db.DateTime, server_default=db.func.current_timestamp(), nullable=False)
    ip           = db.Column(db.String(45))
    pais         = db.Column(db.String(100))
    region       = db.Column(db.String(100))
    ciudad       = db.Column(db.String(100))
    isp          = db.Column(db.String(200))
    zona_horaria = db.Column(db.String(100))
    navegador    = db.Column(db.String(200))
    sistema_op   = db.Column(db.String(100))
    dispositivo  = db.Column(db.String(50))
    referrer     = db.Column(db.String(500))
    idioma       = db.Column(db.String(20))

    def __repr__(self):
        return f'<VisitaIndex {self.ip} {self.ciudad} {self.fecha}>'


class MovimientoPuntos(db.Model):
    __tablename__ = 'MovimientoPuntos'

    idMovimientoPuntos = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idCliente          = db.Column(db.Integer, db.ForeignKey('cliente.idCliente'), nullable=False)
    idEmpresa          = db.Column(db.Integer, db.ForeignKey('empresa.idEmpresa'), nullable=False)

    # Referencia opcional al pago que originó estos puntos (movCuenta.idMovimiento)
    idMovimientoOrigen = db.Column(db.Integer, db.ForeignKey('movCuenta.idMovimiento'), nullable=True)

    # Cuando Empresa.modoAcumulacionPuntos == 'staff', indica de qué especialista es esta
    # bolsa de puntos (ClienteStaff). NULL cuando el modo es 'empresa' (bolsa única).
    idUsuarioStaff = db.Column(db.Integer, db.ForeignKey('usuario.idUsuario'), nullable=True)

    tipo   = db.Column(db.Enum('Ganados', 'Canjeados', 'Ajuste', 'Expirados', name='tipoMovimientoPuntos'), nullable=False)
    puntos = db.Column(db.Numeric(10, 2), nullable=False)  # positivo en Ganados/Ajuste(+), negativo en Canjeados/Ajuste(-)

    saldoResultante = db.Column(db.Numeric(10, 2), nullable=False)  # saldo del cliente DESPUÉS de este movimiento

    fecha = db.Column(db.Date, nullable=False, default=datetime.now().date)
    hora  = db.Column(db.Time, nullable=False, default=datetime.now().time)

    idUsuario = db.Column(db.Integer, db.ForeignKey('usuario.idUsuario'), nullable=False)  # ID_USUARIO_SISTEMA si es automático
    notas     = db.Column(db.String(255), nullable=True)

    cliente = db.relationship('Cliente', backref='movimientosPuntos')
    empresa = db.relationship('Empresa', backref='movimientosPuntos')
    staff   = db.relationship('Usuario', foreign_keys=[idUsuarioStaff])


# ==========================================
# MODELO: Comunicado (mensajes/tips/avisos/recordatorios de menú)
# ==========================================

class Comunicado(db.Model):
    __tablename__ = "comunicado"

    idComunicado = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Siempre es la empresa del usuario que lo crea (nunca NULL). Por convención,
    # si idEmpresa == 1 (la empresa maestra de CitaNet), lo ven TODAS las
    # empresas; cualquier otro valor limita el comunicado solo a esa empresa.
    idEmpresa    = db.Column(db.Integer, db.ForeignKey("empresa.idEmpresa"), nullable=False)

    objetivo     = db.Column(db.Enum('cliente', 'usuario', 'empresa', name='objetivo_comunicado'), nullable=False)

    # Solo aplica cuando objetivo == 'usuario': permite dirigirlo a un tipo de
    # usuario específico (admin/staff/asistente; no aplica a superuser). NULL
    # = para todos los tipos de usuario.
    subObjetivo  = db.Column(db.Enum('admin', 'staff', 'asistente', name='subobjetivo_comunicado'), nullable=True)

    tipo         = db.Column(db.Enum('recordatorio', 'aviso', name='tipo_comunicado'), nullable=False)

    # 1=Baja, 2=Media, 3=Alta, 4=Muy Alta, 5=Crítica (ver NIVELES_PRIORIDAD)
    prioridad    = db.Column(db.Integer, nullable=False, default=1)

    mensaje      = db.Column(db.Text, nullable=False)
    fechaInicio  = db.Column(db.Date, nullable=False)
    fechaFinal   = db.Column(db.Date, nullable=False)
    activo       = db.Column(db.Boolean, default=True, nullable=False)

    # Quien crea el comunicado siempre es un Usuario (admin/staff/asistente/superuser)
    idUsuario     = db.Column(db.Integer, db.ForeignKey("usuario.idUsuario"), nullable=False)
    fechaCreacion = db.Column(db.DateTime, default=datetime.now, nullable=False)

    empresa = db.relationship("Empresa", backref=db.backref("comunicados", lazy=True))
    usuario = db.relationship("Usuario", backref=db.backref("comunicados_creados", lazy=True))

    NIVELES_PRIORIDAD = {
        1: "Baja",
        2: "Media",
        3: "Alta",
        4: "Muy Alta",
        5: "Crítica",
    }

    def nombre_prioridad(self):
        return self.NIVELES_PRIORIDAD.get(self.prioridad, "Baja")

    def __repr__(self):
        return f'<Comunicado {self.idComunicado} objetivo={self.objetivo} prioridad={self.prioridad}>'


class ComunicadoLeido(db.Model):
    __tablename__ = "comunicado_leido"

    idComunicadoLeido = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idComunicado = db.Column(db.Integer, db.ForeignKey("comunicado.idComunicado"), nullable=False)

    # Igual que en el resto del modelo (CompraPublicidad, FilaEspera): el lector
    # es un Cliente o un Usuario según tipoLector, con la otra llave en NULL.
    tipoLector   = db.Column(db.Enum('cliente', 'usuario', name='tipo_lector_comunicado'), nullable=False)
    idCliente    = db.Column(db.Integer, db.ForeignKey("cliente.idCliente"), nullable=True)
    idUsuario    = db.Column(db.Integer, db.ForeignKey("usuario.idUsuario"), nullable=True)

    fechaLectura = db.Column(db.DateTime, default=datetime.now, nullable=False)

    comunicado = db.relationship("Comunicado", backref=db.backref("lecturas", lazy=True))
    cliente    = db.relationship("Cliente")
    usuario    = db.relationship("Usuario", foreign_keys=[idUsuario])

    __table_args__ = (
        UniqueConstraint('idComunicado', 'tipoLector', 'idCliente', 'idUsuario', name='uniq_comunicado_lector'),
    )

    def __repr__(self):
        return f'<ComunicadoLeido Comunicado={self.idComunicado} tipoLector={self.tipoLector}>'
