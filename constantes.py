# constantes.py
from modelos import EstatusCita, tipoMovimiento, metodoPago

class CData:
    _cache = {}

    @classmethod
    def get_estatus(cls, nombre):
        key = f"estatus_{nombre}"
        if key not in cls._cache:
            cls._cache[key] = EstatusCita.id_estatus(nombre)
        return cls._cache[key]

    @classmethod
    def get_movimiento(cls, nombre):
        key = f"mov_{nombre}"
        if key not in cls._cache:
            # Buscamos en la tabla tipoMovimiento por el nombre
            mov = tipoMovimiento.query.filter_by(nombre=nombre).first()
            cls._cache[key] = mov.idtipoMovimiento if mov else None
        return cls._cache[key]

    @classmethod
    def get_metodo_pago(cls, nombre):
        key = f"pago_{nombre}"
        if key not in cls._cache:
            # Buscamos en la tabla metodoPago por el nombre
            pago = metodoPago.query.filter_by(nombre=nombre).first()
            cls._cache[key] = pago.idmetodoPago if pago else None
        return cls._cache[key]

        # --- Constantes para ID's  del Sistema ---
    ID_USUARIO_SISTEMA = 1
    ID_EMPRESA_CITANET = 1
        
    # --- Propiedades para Estatus de Cita ---
    @property
    def CREADA(self): return self.get_estatus("Creada")
    
    @property
    def DISPONIBLE(self): return self.get_estatus("Disponible")

    @property
    def COMPLETA(self): return self.get_estatus("Completa")

    @property
    def CONFIRMADA(self): return self.get_estatus("Confirmada")
    
    @property
    def BLOQUEADA(self): return self.get_estatus("Bloqueada")
    
    @property
    def CANCELADA(self): return self.get_estatus("Cancelada")
    
    @property
    def REALIZADA(self): return self.get_estatus("Realizada")
    
    @property
    def RESERVADA(self): return self.get_estatus("Reservada")
    
    @property
    def NO_ASISTENCIA(self): return self.get_estatus("No Asistencia")

    # --- Propiedades para Tipos de Movimiento ---
    @property
    def MOV_CITA(self): return self.get_movimiento("Cita")

    @property
    def MOV_PAGO(self): return self.get_movimiento("Pago")

    @property
    def MOV_COMPRA(self): return self.get_movimiento("Compra")

    @property
    def MOV_DESCUENTO(self): return self.get_movimiento("Descuento")

    @property
    def MOV_BONIFICACION(self): return self.get_movimiento("Bonificacion")
    
    @property
    def MOV_PLAN(self): return self.get_movimiento("Plan")

    @property
    def MOV_COMISIONPL(self): return self.get_movimiento("ComisionPagoLinea")

    @property
    def MOV_IVA(self): return self.get_movimiento("IVA")

    # --- Propiedades para Métodos de Pago ---
    @property
    def PAGO_EFECTIVO(self): return self.get_metodo_pago("Efectivo")

    @property
    def PAGO_TARJETA_CREDITO(self): return self.get_metodo_pago("Tarjeta Credito")

    @property
    def PAGO_TARJETA_DEBITO(self): return self.get_metodo_pago("Tarjeta Debito")

    @property
    def PAGO_TRANSFERENCIA(self): return self.get_metodo_pago("Transferencia")

    @property
    def PAGO_EN_LINEA(self): return self.get_metodo_pago("En Linea")
    
    @property
    def PAGO_PUNTOS(self): return self.get_metodo_pago("Puntos de Lealtad")

# Instancia única
const = CData()