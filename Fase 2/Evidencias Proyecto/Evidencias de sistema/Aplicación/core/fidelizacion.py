"""Reglas de negocio del programa de puntos de fidelidad (HU-EP006-003).

- Acumulación: 10% sobre el monto efectivamente pagado en dinero (1 punto = $1 CLP).
- Canje: hasta el 80% del subtotal de la compra, dejando al menos $100 CLP a pagar
  para respetar el mínimo operativo de Transbank Webpay Plus.
"""
from decimal import Decimal, ROUND_FLOOR
from django.db import transaction

from .models import MovimientoPuntos, PuntosFidelizacion

TASA_ACUMULACION = Decimal('0.10')       # 10% del monto pagado
PORCENTAJE_MAX_CANJE = Decimal('0.80')   # Máximo 80% de cobertura con puntos
VALOR_PUNTO_CLP = Decimal('1')           # 1 punto = $1 CLP
MINIMO_PAGO_CLP = 100                    # Resguardo mínimo para Webpay Plus


def obtener_cuenta_puntos(cliente, bloquear=False):
    """Obtiene (o crea si no existe) el registro PuntosFidelizacion del cliente."""
    qs = PuntosFidelizacion.objects.select_for_update() if bloquear else PuntosFidelizacion.objects
    cuenta = qs.filter(cliente=cliente).first()
    if cuenta is None:
        cuenta, _ = PuntosFidelizacion.objects.get_or_create(
            cliente=cliente, defaults={'puntos_acumulados': 0}
        )
        if bloquear:
            cuenta = PuntosFidelizacion.objects.select_for_update().get(pk=cuenta.pk)
    return cuenta


def calcular_maximo_canje(subtotal_bruto, puntos_disponibles):
    """Calcula el máximo de puntos y descuento aplicables a un subtotal dado."""
    subtotal_int = max(0, int(Decimal(str(subtotal_bruto or 0))))
    saldo_int = max(0, int(puntos_disponibles or 0))

    if subtotal_int <= MINIMO_PAGO_CLP or saldo_int <= 0:
        return {
            'max_puntos': 0,
            'max_descuento': 0,
            'porcentaje_maximo': 80,
            'minimo_pago': MINIMO_PAGO_CLP,
        }

    max_por_porcentaje = int(
        (Decimal(subtotal_int) * PORCENTAJE_MAX_CANJE).to_integral_value(rounding=ROUND_FLOOR)
    )
    max_por_piso = max(0, subtotal_int - MINIMO_PAGO_CLP)
    max_puntos = min(saldo_int, max_por_porcentaje, max_por_piso)

    return {
        'max_puntos': max_puntos,
        'max_descuento': max_puntos,  # 1 pt = $1 CLP
        'porcentaje_maximo': 80,
        'minimo_pago': MINIMO_PAGO_CLP,
    }


def calcular_puntos_ganados(monto_pagado):
    """Calcula los puntos a acumular (10% del dinero pagado, redondeado hacia abajo)."""
    monto = Decimal(str(monto_pagado or 0))
    if monto <= 0:
        return 0
    return int((monto * TASA_ACUMULACION).to_integral_value(rounding=ROUND_FLOOR))


def aplicar_canje_en_pedido(pedido, puntos_solicitados):
    """Valida y descuenta los puntos canjeados al crear el pedido (dentro de transaction.atomic)."""
    puntos = int(puntos_solicitados or 0)
    subtotal_bruto = Decimal(str(pedido.subtotal_bruto or pedido.total or 0))

    if puntos <= 0:
        pedido.subtotal_bruto = subtotal_bruto
        pedido.puntos_canjeados = 0
        pedido.descuento_puntos = Decimal('0.00')
        pedido.total = subtotal_bruto
        pedido.save(update_fields=['subtotal_bruto', 'puntos_canjeados', 'descuento_puntos', 'total'])
        return 0

    if not pedido.cliente_id:
        raise ValueError("Debes asociar una cuenta de cliente registrada para canjear puntos.")

    cuenta = obtener_cuenta_puntos(pedido.cliente, bloquear=True)
    limites = calcular_maximo_canje(subtotal_bruto, cuenta.puntos_acumulados)

    if puntos > cuenta.puntos_acumulados:
        raise ValueError(
            f"Saldo insuficiente: tienes {cuenta.puntos_acumulados} pts disponibles."
        )
    if puntos > limites['max_puntos']:
        raise ValueError(
            f"El máximo canjeable para esta compra es de {limites['max_puntos']} pts "
            f"(hasta 80% del total, dejando mínimo ${MINIMO_PAGO_CLP} CLP a pagar)."
        )

    descuento = Decimal(puntos) * VALOR_PUNTO_CLP
    nuevo_total = subtotal_bruto - descuento

    cuenta.puntos_acumulados -= puntos
    cuenta.save(update_fields=['puntos_acumulados', 'fecha_actualizacion'])

    pedido.subtotal_bruto = subtotal_bruto
    pedido.puntos_canjeados = puntos
    pedido.descuento_puntos = descuento
    pedido.total = nuevo_total
    pedido.save(update_fields=['subtotal_bruto', 'puntos_canjeados', 'descuento_puntos', 'total'])

    MovimientoPuntos.objects.create(
        cliente=pedido.cliente,
        pedido=pedido,
        tipo='CANJE',
        puntos=-puntos,
        saldo_resultante=cuenta.puntos_acumulados,
        descripcion=f"Canje de {puntos} pts (-${puntos:,}) en Pedido #{pedido.pk}".replace(',', '.'),
    )
    return puntos


def acreditar_puntos_pedido(pedido):
    """Acredita el 10% del monto pagado cuando el pedido queda PAGADO (idempotente)."""
    if not pedido.cliente_id:
        return 0
    if pedido.estado not in ('PAGADO', 'PREPARACION', 'LISTO', 'ENTREGADO'):
        return 0

    with transaction.atomic():
        if MovimientoPuntos.objects.filter(pedido=pedido, tipo='ACUMULACION').exists():
            return pedido.puntos_ganados or 0

        puntos = calcular_puntos_ganados(pedido.total)
        if puntos <= 0:
            return 0

        cuenta = obtener_cuenta_puntos(pedido.cliente, bloquear=True)
        cuenta.puntos_acumulados += puntos
        cuenta.save(update_fields=['puntos_acumulados', 'fecha_actualizacion'])

        pedido.puntos_ganados = puntos
        pedido.save(update_fields=['puntos_ganados'])

        canal_txt = "POS" if pedido.canal in ('PRESENCIAL', 'POS') else "Web"
        MovimientoPuntos.objects.create(
            cliente=pedido.cliente,
            pedido=pedido,
            tipo='ACUMULACION',
            puntos=puntos,
            saldo_resultante=cuenta.puntos_acumulados,
            descripcion=f"Acumulación 10% por compra {canal_txt} (Pedido #{pedido.pk})",
        )
        return puntos


def devolver_canje_pedido(pedido):
    """Reintegra los puntos canjeados si un pedido PENDIENTE se cancela o expira (idempotente)."""
    if not pedido.cliente_id or (pedido.puntos_canjeados or 0) <= 0:
        return 0

    with transaction.atomic():
        if MovimientoPuntos.objects.filter(pedido=pedido, tipo='DEVOLUCION_CANJE').exists():
            return 0
        if not MovimientoPuntos.objects.filter(pedido=pedido, tipo='CANJE').exists():
            return 0

        puntos = int(pedido.puntos_canjeados)
        cuenta = obtener_cuenta_puntos(pedido.cliente, bloquear=True)
        cuenta.puntos_acumulados += puntos
        cuenta.save(update_fields=['puntos_acumulados', 'fecha_actualizacion'])

        MovimientoPuntos.objects.create(
            cliente=pedido.cliente,
            pedido=pedido,
            tipo='DEVOLUCION_CANJE',
            puntos=puntos,
            saldo_resultante=cuenta.puntos_acumulados,
            descripcion=f"Reintegro de {puntos} pts por cancelación de Pedido #{pedido.pk}",
        )
        return puntos


def reaplicar_canje_si_reactivado(pedido):
    """Si un pedido CANCELADO se reactiva por pago tardío de Webpay, vuelve a descontar su canje."""
    if not pedido.cliente_id or (pedido.puntos_canjeados or 0) <= 0:
        return
    with transaction.atomic():
        devolucion = MovimientoPuntos.objects.filter(pedido=pedido, tipo='DEVOLUCION_CANJE').first()
        if not devolucion:
            return
        puntos = int(pedido.puntos_canjeados)
        cuenta = obtener_cuenta_puntos(pedido.cliente, bloquear=True)
        descuento_real = min(puntos, cuenta.puntos_acumulados)
        cuenta.puntos_acumulados -= descuento_real
        cuenta.save(update_fields=['puntos_acumulados', 'fecha_actualizacion'])
        devolucion.delete()