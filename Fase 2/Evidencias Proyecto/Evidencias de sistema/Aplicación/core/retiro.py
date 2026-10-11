"""Retiro en tienda: días y horas en que se puede retirar un pedido programado.

Los horarios salen de `RETIRO_TRAMOS` (core/templatetags/tienda.py), el mismo dato que muestran
el pie de página y la página Local. La hora es la de Chile y no depende de settings.TIME_ZONE.

Cada franja es una ventana de PASO_MIN minutos dentro del horario de retiro: el cliente llega
a esa hora o poco después, y siempre antes de que cierre el local.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .templatetags.tienda import RETIRO_TRAMOS

ZONA_HORARIA = ZoneInfo('America/Santiago')
ANTICIPACION_MIN = 60  # minutos mínimos para preparar el pedido (valor de ejemplo, confirmar con el cliente)
PASO_MIN = 30          # una franja cada 30 minutos
DIAS_ADELANTE = 4      # hoy y los 4 días siguientes

DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
MESES = [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]


def ahora():
    """Fecha y hora actual en Chile (las pruebas reemplazan esta función)."""
    return datetime.now(ZONA_HORARIA)


def _a_minutos(hhmm):
    horas, minutos = hhmm.split(':')
    return int(horas) * 60 + int(minutos)


def _a_hhmm(minutos):
    return f'{minutos // 60:02d}:{minutos % 60:02d}'


def _horario_del_dia(fecha):
    """(desde, hasta) en minutos desde la medianoche, o None si ese día no hay retiro."""
    for _nombre, dias, desde, hasta in RETIRO_TRAMOS:
        if fecha.weekday() in dias:
            return _a_minutos(desde), _a_minutos(hasta)
    return None


def franjas_del_dia(fecha, ahora_=None):
    """Horas de inicio ('HH:MM') disponibles ese día, descontando el tiempo de preparación."""
    horario = _horario_del_dia(fecha)
    if horario is None:
        return []
    desde, hasta = horario
    ahora_ = ahora_ or ahora()
    minimo = desde
    if fecha == ahora_.date():
        minimo = max(desde, ahora_.hour * 60 + ahora_.minute + ANTICIPACION_MIN)

    horas = []
    inicio = desde
    while inicio + PASO_MIN <= hasta:
        if inicio >= minimo:
            horas.append(_a_hhmm(inicio))
        inicio += PASO_MIN
    return horas


def _nombre_del_dia(fecha):
    return f'{DIAS[fecha.weekday()]} {fecha.day} de {MESES[fecha.month - 1]}'


def _etiqueta(fecha, hoy):
    dias_de_diferencia = (fecha - hoy).days
    if dias_de_diferencia == 0:
        return f'Hoy, {_nombre_del_dia(fecha)}'
    if dias_de_diferencia == 1:
        return f'Mañana, {_nombre_del_dia(fecha)}'
    return _nombre_del_dia(fecha)


def _rango(hhmm):
    """'10:30' -> '10:30 a 11:00'"""
    return f'{hhmm} a {_a_hhmm(_a_minutos(hhmm) + PASO_MIN)}'


def dias_de_retiro(ahora_=None):
    """Días con horas disponibles, en el formato que usa el carrito."""
    ahora_ = ahora_ or ahora()
    dias = []
    for i in range(DIAS_ADELANTE + 1):
        fecha = (ahora_ + timedelta(days=i)).date()
        horas = franjas_del_dia(fecha, ahora_)
        if horas:
            dias.append({
                'fecha': fecha.isoformat(),
                'etiqueta': _etiqueta(fecha, ahora_.date()),
                'horas': [{'valor': h, 'texto': _rango(h)} for h in horas],
            })
    return dias


def validar_retiro(fecha_texto, hora_texto, ahora_=None):
    """Comprueba el día y la hora elegidos. Devuelve (fecha, hora, None) o (None, None, mensaje)."""
    ahora_ = ahora_ or ahora()
    try:
        fecha = datetime.strptime(fecha_texto, '%Y-%m-%d').date()
        datetime.strptime(hora_texto, '%H:%M')
    except (TypeError, ValueError):
        return None, None, 'Elige un día y una hora de retiro válidos.'

    dentro_de_los_dias = 0 <= (fecha - ahora_.date()).days <= DIAS_ADELANTE
    if not dentro_de_los_dias or hora_texto not in franjas_del_dia(fecha, ahora_):
        return None, None, 'Esa hora de retiro ya no está disponible. Elige otra.'
    return fecha, hora_texto, None


def texto_retiro(fecha, hora):
    """Texto que se guarda en el pedido y se muestra en el comprobante."""
    return f'{_nombre_del_dia(fecha)}, de {_rango(hora)}'
