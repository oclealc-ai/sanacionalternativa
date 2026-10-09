"""Actualiza diariamente el nivel de comisión de cada vendedor.

Uso manual:
    python actualizar_niveles_vendedores.py

Uso recomendado en crontab:
    15 0 * * * cd /home/appuser/apps/AppCitaNet && /usr/bin/python3 actualizar_niveles_vendedores.py >> /var/log/citanet_niveles_vendedores.log 2>&1
"""

from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
import logging
import sys

from sqlalchemy import func

from app import app
from modelos import (
    db,
    Empresa,
    EstatusEmpresa,
    NivelComisionVendedor,
    PagoComisionVendedor,
    Vendedor,
    VendedorEmpresa,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("actualizar_niveles_vendedores")


def restar_meses(fecha, meses):
    """Resta meses conservando una fecha válida para meses cortos."""
    total_meses = fecha.year * 12 + (fecha.month - 1) - meses
    anio = total_meses // 12
    mes = total_meses % 12 + 1
    dia = min(fecha.day, monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def obtener_umbral(valor):
    """Los umbrales vacíos se interpretan como cero."""
    return Decimal(str(valor or 0))


def obtener_nivel_aplicable(vendedor, niveles, empresas_activas):
    niveles_candidatos = []
    relaciones = VendedorEmpresa.query.filter_by(
        idVendedor=vendedor.idVendedor
    ).all()
    relaciones_por_id = {
        relacion.idVendedorEmpresa: relacion for relacion in relaciones
    }

    for nivel in niveles:
        umbral_empresas = int(nivel.empresasActivas or 0)
        umbral_comision = obtener_umbral(nivel.comisionPagada)
        fecha_limite = restar_meses(date.today(), nivel.periodoComisionMeses or 12)
        comision_pagada = Decimal('0.00')

        pagos = PagoComisionVendedor.query.filter(
            PagoComisionVendedor.idVendedor == vendedor.idVendedor,
            PagoComisionVendedor.aplicado.is_(True),
            #PagoComisionVendedor.fechaPago >= fecha_limite,
        ).all()
        for pago in pagos:
            if pago.idVendedorEmpresa in relaciones_por_id:
                comision_pagada += Decimal(str(pago.montoPago or 0))

        if (
            empresas_activas >= umbral_empresas
            and comision_pagada >= umbral_comision
        ):
            niveles_candidatos.append((nivel, comision_pagada))

    if niveles_candidatos:
        return max(
            niveles_candidatos,
            key=lambda item: item[0].idNivelComision,
        )

    nivel_inicial = min(niveles, key=lambda nivel: nivel.idNivelComision)
    return nivel_inicial, Decimal('0.00')


def actualizar_niveles():
    estatus_activo = EstatusEmpresa.query.filter(
        func.lower(EstatusEmpresa.nombre).in_(['activo', 'activa'])
    ).first()
    if not estatus_activo:
        raise RuntimeError(
            "No se encontró un estatus de empresa 'Activo'/'Activa'."
        )

    niveles = NivelComisionVendedor.query.filter_by(activo=True).order_by(
        NivelComisionVendedor.idNivelComision.asc()
    ).all()
    if not niveles:
        logger.warning("No hay niveles de comisión activos.")
        return

    vendedores = Vendedor.query.filter_by(activo=True).order_by(
        Vendedor.idVendedor.asc()
    ).all()
    cambios = 0

    for vendedor in vendedores:
        empresas_activas = db.session.query(func.count(Empresa.idEmpresa)).filter(
            Empresa.idVendedor == vendedor.idVendedor,
            Empresa.idEstatus == estatus_activo.idEstatus,
        ).scalar() or 0

        nivel_actual = vendedor.nivel_comision
        nivel_nuevo, comision_evaluada = obtener_nivel_aplicable(
            vendedor,
            niveles,
            int(empresas_activas),
        )

        if not nivel_actual or nivel_actual.idNivelComision != nivel_nuevo.idNivelComision:
            nivel_anterior = nivel_actual.nombre if nivel_actual else 'Sin nivel'
            vendedor.idNivelComision = nivel_nuevo.idNivelComision
            cambios += 1
            logger.info(
                "Vendedor %s (%s): %s -> %s | empresas activas=%s | comisión aplicada evaluada=$%.2f",
                vendedor.idVendedor,
                vendedor.nombre,
                nivel_anterior,
                nivel_nuevo.nombre,
                empresas_activas,
                comision_evaluada,
            )
        else:
            logger.info(
                "Vendedor %s (%s): conserva %s | empresas activas=%s | comisión aplicada evaluada=$%.2f",
                vendedor.idVendedor,
                vendedor.nombre,
                nivel_nuevo.nombre,
                empresas_activas,
                comision_evaluada,
            )

    db.session.commit()
    logger.info(
        "Actualización terminada. vendedores=%s cambios=%s",
        len(vendedores),
        cambios,
    )


if __name__ == "__main__":
    try:
        with app.app_context():
            actualizar_niveles()
    except Exception:
        db.session.rollback()
        logger.exception("Error actualizando niveles de vendedores.")
        sys.exit(1)
