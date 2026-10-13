"""Transiciones de estado de un pedido con pago Webpay: un solo lugar, con bloqueo y guardias.

El pedido nace PENDIENTE con su stock ya reservado (finalizar_compra) y termina PAGADO o CANCELADO:

    PENDIENTE --aprobar_pago--> PAGADO
    PENDIENTE --cancelar_pendiente--> CANCELADO (el stock se devuelve)
    CANCELADO --aprobar_pago--> PAGADO si todavía alcanza el stock (el pago llegó tarde); si no, SIN_STOCK

Toda transición:
  * toma el pedido con select_for_update: dos peticiones simultáneas (el retorno de Transbank y la
    limpieza de pagos abandonados, por ejemplo) se turnan y no se pisan;
  * revisa el estado actual: repetir una operación no repite sus efectos (no devuelve el stock dos
    veces ni lo descuenta dos veces);
  * ajusta el stock en la misma transacción que el estado.

Aquí no se habla con Transbank: las vistas consultan o reembolsan y llaman a estas funciones.
"""
from django.db import transaction
from django.db.models import F

from .models import Pago, Pedido, Producto

# Resultados de aprobar_pago
PAGADO = 'PAGADO'                  # estaba PENDIENTE y quedó pagado
YA_PAGADO = 'YA_PAGADO'            # ya estaba pagado (se repitió el retorno): no se cambia nada
REACTIVADO = 'REACTIVADO'          # estaba CANCELADO, el pago llegó tarde y se volvió a reservar el stock
SIN_STOCK = 'SIN_STOCK'            # estaba CANCELADO y el stock ya no alcanza: hay que reembolsar
MONTO_DISTINTO = 'MONTO_DISTINTO'  # Transbank cobró un monto distinto al del pedido: hay que reembolsar
NO_ENCONTRADO = 'NO_ENCONTRADO'


def _devolver_stock(pedido):
    for detalle in pedido.detalles.all():
        Producto.objects.filter(pk=detalle.producto_id).update(stock=F('stock') + detalle.cantidad)


def _reservar_stock(pedido):
    """Descuenta el stock de todos los productos del pedido, o de ninguno. True si alcanzaba."""
    detalles = list(pedido.detalles.all())
    # Se bloquean en orden de pk (igual que finalizar_compra) para no cruzarse con otra compra.
    productos = {
        p.pk: p
        for p in Producto.objects.select_for_update().filter(pk__in=[d.producto_id for d in detalles]).order_by('pk')
    }
    if any(d.producto_id not in productos or productos[d.producto_id].stock < d.cantidad for d in detalles):
        return False
    for detalle in detalles:
        Producto.objects.filter(pk=detalle.producto_id).update(stock=F('stock') - detalle.cantidad)
    return True


def _cancelar_bloqueado(pedido, estado_pago):
    """Cancela un pedido PENDIENTE ya bloqueado: devuelve el stock y marca el pago."""
    _devolver_stock(pedido)
    pedido.estado = 'CANCELADO'
    pedido.save(update_fields=['estado'])
    Pago.objects.filter(pedido=pedido).update(estado=estado_pago)


def cancelar_pendiente(pedido_id, estado_pago):
    """Cancela un pedido PENDIENTE y devuelve su stock una sola vez.

    Se puede llamar de nuevo con el mismo pedido: si ya no está PENDIENTE no hace nada.
    Devuelve True si lo canceló.
    """
    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().filter(pk=pedido_id, estado='PENDIENTE').first()
        if pedido is None:
            return False
        _cancelar_bloqueado(pedido, estado_pago)
    return True


def aprobar_pago(pedido_id, monto, metodo, codigo_autorizacion):
    """Registra un pago autorizado por Transbank. Devuelve (resultado, pedido).

    El pago ya se cobró: lo que importa es dejar el pedido consistente con eso.
      * PENDIENTE -> PAGADO (el stock ya estaba reservado).
      * CANCELADO (el pago llegó después de que el pedido expiró o se canceló) -> se intenta volver
        a reservar el stock: si alcanza queda PAGADO; si no, SIN_STOCK y la vista reembolsa.
      * Ya pagado (o más adelantado) -> no cambia nada.
      * Monto distinto al del pedido -> MONTO_DISTINTO: no se acepta, la vista reembolsa.
    """
    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().filter(pk=pedido_id).first()
        if pedido is None:
            return NO_ENCONTRADO, None

        if int(monto) != int(pedido.total):
            if pedido.estado == 'PENDIENTE':
                _cancelar_bloqueado(pedido, 'MONTO_DISTINTO')   # libera el stock reservado
            return MONTO_DISTINTO, pedido

        if pedido.estado == 'CANCELADO':
            if not _reservar_stock(pedido):
                return SIN_STOCK, pedido
            resultado = REACTIVADO
        elif pedido.estado == 'PENDIENTE':
            resultado = PAGADO
        else:
            return YA_PAGADO, pedido    # PAGADO, PREPARACION, LISTO o ENTREGADO

        pedido.estado = 'PAGADO'
        pedido.save(update_fields=['estado'])
        Pago.objects.update_or_create(
            pedido=pedido,
            defaults={
                'monto': pedido.total,
                'metodo': metodo,
                'estado': 'APROBADO',
                'codigo_autorizacion': codigo_autorizacion,
            },
        )
        return resultado, pedido


def marcar_pago(pedido_id, estado, codigo_autorizacion=None):
    """Actualiza el estado del pago (p. ej. REEMBOLSADO). Con `codigo_autorizacion` también lo guarda."""
    campos = {'estado': estado}
    if codigo_autorizacion is not None:
        campos['codigo_autorizacion'] = codigo_autorizacion
    Pago.objects.filter(pedido_id=pedido_id).update(**campos)
