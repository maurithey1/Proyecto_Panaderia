"""Apertura de caja del POS: el cajero solo vende con su caja abierta (HU-EP004-001, criterio 1).

Al empezar el turno, el cajero cuenta el dinero físico de su caja y lo declara como monto inicial.
La caja física se identifica por su número (Caja.numero, copiado de Cajero.num_caja_asignada al abrir),
porque el dinero del cajón es de la caja y no del cajero: si Juan cierra la Caja 1 y después la abre
Patricia, el "turno anterior" de Patricia es el de Juan.

    sin caja abierta --abrir_caja--> ABIERTA (puede vender) --cierre (HU-EP004-002)--> CERRADA

Reglas:
  * una sola caja abierta por cajero y por caja física;
  * una caja que quedó abierta de un día anterior bloquea la apertura y la venta hasta que se cierre;
  * el monto anterior es lo contado en el último cierre de esa caja física (todo lo contado queda en
    el cajón); si el monto declarado no coincide, la observación es obligatoria. En la primera apertura
    de una caja no hay con qué comparar.
"""
import re
from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Caja, Cajero, CierreCaja, Pedido, Pago
from .templatetags.formato import clp

ABIERTA = 'ABIERTA'
CERRADA = 'CERRADA'
MONTO_MAXIMO_APERTURA = 500000    # tope para atrapar errores de tipeo ($3.000.000 en vez de $30.000)
MONTO_MAXIMO_CIERRE = 10000000    # tope para cierre ($10.000.000)
LARGO_MAXIMO_OBSERVACION = 500


# "17500", "17.500" o "$17.500": pesos enteros, con o sin puntos de miles
_MONTO = re.compile(r'^\$?(\d{1,3}(\.\d{3})+|\d+)$')


class AperturaInvalida(Exception):
    """La apertura no se puede hacer; el mensaje es para el cajero."""


class CierreInvalido(Exception):
    """El cierre no se puede hacer; el mensaje es para el cajero."""



def _inicio_de_hoy():
    hoy = timezone.localdate()
    return timezone.make_aware(datetime.combine(hoy, datetime.min.time()))


def _fecha(caja):
    return timezone.localtime(caja.fecha_apertura).strftime('%d/%m/%Y')


def _nombre(cajero):
    if cajero is None:
        return 'otro cajero'
    return cajero.user.get_full_name() or cajero.user.username


def leer_monto(texto, maximo=MONTO_MAXIMO_APERTURA, tipo_error=AperturaInvalida):
    """Monto declarado por el cajero -> Decimal en pesos enteros. Lanza tipo_error si no sirve."""
    limpio = str(texto or '').replace(' ', '')
    if not limpio:
        raise tipo_error('Ingresa el monto físico que hay en la caja.')
    if not _MONTO.match(limpio):
        raise tipo_error('El monto debe ser un número entero de pesos, sin decimales.')
    monto = int(limpio.lstrip('$').replace('.', '') or '0')
    if maximo and monto > maximo:
        raise tipo_error(
            f'El monto supera el límite permitido ({clp(maximo)}). Revisa que esté bien escrito.'
        )
    return Decimal(monto)



def caja_del_cajero(cajero):
    """La caja abierta del cajero (de cualquier día), o None."""
    return Caja.objects.filter(cajero=cajero, estado=ABIERTA).order_by('-fecha_apertura').first()


def caja_fisica_abierta(numero):
    """La caja física `numero` abierta por cualquier cajero, o None."""
    return (
        Caja.objects.filter(numero=numero, estado=ABIERTA)
        .select_related('cajero__user')
        .order_by('-fecha_apertura')
        .first()
    )


def monto_turno_anterior(numero):
    """Lo contado en el último cierre de la caja física; None si nunca se ha cerrado (primera apertura)."""
    cierre = CierreCaja.objects.filter(caja__numero=numero).order_by('-fecha_cierre', '-pk').first()
    return cierre.monto_contado if cierre else None


def situacion(cajero):
    """
    Qué puede hacer el cajero ahora. Devuelve (caja, bloqueo):
      * (su caja, None): tiene la caja abierta hoy y puede vender;
      * (None, None): no tiene caja abierta y puede abrirla;
      * (None, mensaje): no puede vender ni abrir (una caja quedó abierta de otro día, o su caja
        física la tiene abierta otro cajero).
    """
    propia = caja_del_cajero(cajero)
    if propia is not None:
        if propia.fecha_apertura >= _inicio_de_hoy():
            return propia, None
        return None, (
            f'Tu Caja {propia.numero} sigue abierta desde el {_fecha(propia)}: '
            'debe cerrarse antes de abrir un nuevo turno.'
        )

    fisica = caja_fisica_abierta(cajero.num_caja_asignada)
    if fisica is not None:
        if fisica.fecha_apertura >= _inicio_de_hoy():
            return None, f'La Caja {fisica.numero} ya está abierta por {_nombre(fisica.cajero)}.'
        return None, (
            f'La Caja {fisica.numero} sigue abierta desde el {_fecha(fisica)} ({_nombre(fisica.cajero)}): '
            'debe cerrarse primero.'
        )
    return None, None


def abrir_caja(cajero, monto_texto, observacion=''):
    """Abre la caja física del cajero con el monto declarado. Devuelve la Caja o lanza AperturaInvalida."""
    monto = leer_monto(monto_texto)
    observacion = (observacion or '').strip()
    if len(observacion) > LARGO_MAXIMO_OBSERVACION:
        raise AperturaInvalida(f'La observación puede tener hasta {LARGO_MAXIMO_OBSERVACION} caracteres.')

    numero = cajero.num_caja_asignada
    with transaction.atomic():
        # Bloquea al cajero y a los demás cajeros de esa caja física: un doble clic o dos cajeros
        # abriendo la misma caja a la vez quedan en fila, y el segundo ve la caja ya abierta.
        list(
            Cajero.objects.select_for_update()
            .filter(Q(pk=cajero.pk) | Q(num_caja_asignada=numero))
            .order_by('pk')
        )
        caja, bloqueo = situacion(cajero)
        if caja is not None:
            raise AperturaInvalida(f'Ya tienes la Caja {caja.numero} abierta.')
        if bloqueo:
            raise AperturaInvalida(bloqueo)

        anterior = monto_turno_anterior(numero)
        if anterior is not None and monto != anterior and not observacion:
            raise AperturaInvalida(
                f'El monto no coincide con el del turno anterior ({clp(anterior)}): '
                'escribe una observación que explique la diferencia.'
            )
        return Caja.objects.create(
            cajero=cajero,
            numero=numero,
            monto_inicial=monto,
            observacion_apertura=observacion,
            estado=ABIERTA,
        )


def resumen_ventas_turno(caja):
    """
    Calcula el resumen de ventas del turno actual de la caja.
    Retorna un diccionario con:
      - 'ventas_efectivo': total recaudado en efectivo (Decimal)
      - 'ventas_tarjeta': total recaudado con tarjeta / Webpay (Decimal)
      - 'total_ventas': suma de todas las ventas del turno (Decimal)
      - 'total_pedidos': cantidad de pedidos pagados (int)
      - 'monto_esperado': monto inicial + ventas_efectivo (Decimal)
    """
    if caja is None or not caja.cajero:
        cero = Decimal('0.00')
        return {
            'ventas_efectivo': cero,
            'ventas_tarjeta': cero,
            'total_ventas': cero,
            'total_pedidos': 0,
            'monto_esperado': cero,
        }

    pedidos_turno = Pedido.objects.filter(
        cajero=caja.cajero,
        canal='POS',
        fecha__gte=caja.fecha_apertura,
    )
    if caja.fecha_cierre:
        pedidos_turno = pedidos_turno.filter(fecha__lte=caja.fecha_cierre)

    pagos_pagados = Pago.objects.filter(
        pedido__in=pedidos_turno,
        estado='PAGADO',
    )

    ventas_efectivo = (
        pagos_pagados.filter(metodo__iexact='Efectivo')
        .aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    )
    ventas_tarjeta = (
        pagos_pagados.exclude(metodo__iexact='Efectivo')
        .aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    )
    total_ventas = ventas_efectivo + ventas_tarjeta
    total_pedidos = pedidos_turno.filter(estado='PAGADO').count()
    monto_esperado = caja.monto_inicial + ventas_efectivo

    return {
        'ventas_efectivo': ventas_efectivo,
        'ventas_tarjeta': ventas_tarjeta,
        'total_ventas': total_ventas,
        'total_pedidos': total_pedidos,
        'monto_esperado': monto_esperado,
    }


def ultimo_cierre_cajero(cajero):
    """Devuelve el último CierreCaja realizado por el cajero o en su caja física."""
    if cajero is None:
        return None
    return (
        CierreCaja.objects.filter(Q(caja__cajero=cajero) | Q(caja__numero=cajero.num_caja_asignada))
        .select_related('caja', 'caja__cajero__user')
        .order_by('-fecha_cierre', '-pk')
        .first()
    )


def cerrar_caja(cajero, monto_contado_texto, observacion=''):
    """
    Realiza el cierre de la caja abierta del cajero.
    Comprueba cuadratura y registra el CierreCaja correspondiente.
    """
    monto_contado = leer_monto(monto_contado_texto, maximo=MONTO_MAXIMO_CIERRE, tipo_error=CierreInvalido)
    observacion = (observacion or '').strip()
    if len(observacion) > LARGO_MAXIMO_OBSERVACION:
        raise CierreInvalido(f'La observación puede tener hasta {LARGO_MAXIMO_OBSERVACION} caracteres.')

    with transaction.atomic():
        # Bloquear la caja del cajero
        caja = (
            Caja.objects.select_for_update()
            .filter(cajero=cajero, estado=ABIERTA)
            .order_by('-fecha_apertura')
            .first()
        )
        if caja is None:
            raise CierreInvalido('No tienes ninguna caja abierta para cerrar.')

        ventas = resumen_ventas_turno(caja)
        monto_esperado = ventas['monto_esperado']
        diferencia = monto_contado - monto_esperado

        if diferencia == 0:
            estado_cuadratura = 'Cuadrada'
        elif diferencia > 0:
            estado_cuadratura = 'Sobrante'
        else:
            estado_cuadratura = 'Faltante'

        if diferencia != 0 and not observacion:
            tipo_dif = 'un sobrante' if diferencia > 0 else 'un faltante'
            raise CierreInvalido(
                f'La caja no cuadra ({tipo_dif} de {clp(abs(diferencia))}): '
                'escribe una observación que explique la diferencia antes de cerrar.'
            )

        caja.estado = CERRADA
        caja.fecha_cierre = timezone.now()
        caja.save(update_fields=['estado', 'fecha_cierre'])

        cierre = CierreCaja.objects.create(
            caja=caja,
            monto_inicial=caja.monto_inicial,
            monto_ventas_sistema=ventas['ventas_efectivo'],
            monto_contado=monto_contado,
            diferencia=diferencia,
            estado_cuadratura=estado_cuadratura,
            observacion=observacion,
        )
        return cierre

