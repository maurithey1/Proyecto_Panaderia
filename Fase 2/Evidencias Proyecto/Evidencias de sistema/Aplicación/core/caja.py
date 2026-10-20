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
from django.db.models import Q
from django.utils import timezone

from .models import Caja, Cajero, CierreCaja
from .templatetags.formato import clp

ABIERTA = 'ABIERTA'
CERRADA = 'CERRADA'
MONTO_MAXIMO_APERTURA = 500000    # tope para atrapar errores de tipeo ($3.000.000 en vez de $30.000)
LARGO_MAXIMO_OBSERVACION = 500

# "17500", "17.500" o "$17.500": pesos enteros, con o sin puntos de miles
_MONTO = re.compile(r'^\$?(\d{1,3}(\.\d{3})+|\d+)$')


class AperturaInvalida(Exception):
    """La apertura no se puede hacer; el mensaje es para el cajero."""


def _inicio_de_hoy():
    hoy = timezone.localdate()
    return timezone.make_aware(datetime.combine(hoy, datetime.min.time()))


def _fecha(caja):
    return timezone.localtime(caja.fecha_apertura).strftime('%d/%m/%Y')


def _nombre(cajero):
    if cajero is None:
        return 'otro cajero'
    return cajero.user.get_full_name() or cajero.user.username


def leer_monto(texto):
    """Monto declarado por el cajero -> Decimal en pesos enteros. Lanza AperturaInvalida si no sirve."""
    limpio = str(texto or '').replace(' ', '')
    if not limpio:
        raise AperturaInvalida('Ingresa el monto físico que hay en la caja.')
    if not _MONTO.match(limpio):
        raise AperturaInvalida('El monto debe ser un número entero de pesos, sin decimales.')
    monto = int(limpio.lstrip('$').replace('.', ''))
    if monto > MONTO_MAXIMO_APERTURA:
        raise AperturaInvalida(
            f'El monto supera el máximo de apertura ({clp(MONTO_MAXIMO_APERTURA)}). Revisa que esté bien escrito.'
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
