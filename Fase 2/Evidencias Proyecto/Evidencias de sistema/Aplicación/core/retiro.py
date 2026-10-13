"""Retiro en tienda y despacho: días y horas en que se puede programar un pedido.

Los horarios salen de `RETIRO_TRAMOS` (core/templatetags/tienda.py), el mismo dato que muestran
el pie de página y la página Local. La hora es la de Chile y no depende de settings.TIME_ZONE.

Cada franja es una ventana de PASO_MIN minutos dentro del horario de la tienda: el cliente llega
a esa hora o poco después, y siempre antes de que cierre el local.

Además, cada producto puede venderse solo en ciertos turnos (días y horas). Una franja solo se
ofrece si cabe entera dentro de un turno de TODOS los productos del carrito que tengan turnos.
`turnos_por_producto` es una lista con la lista de turnos activos de cada producto restringido.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .templatetags.tienda import RETIRO_TRAMOS

ZONA_HORARIA = ZoneInfo('America/Santiago')
ANTICIPACION_MIN = 60  # minutos mínimos para preparar el pedido (valor de ejemplo, confirmar con el cliente)
PASO_MIN = 30          # una franja cada 30 minutos
DIAS_ADELANTE = 4      # hoy y los 4 días siguientes
DIAS_ADELANTE_CON_TURNOS = 7   # con productos de turno se mira una semana, para que aparezca cada día

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


def _minutos_de(hora):
    return hora.hour * 60 + hora.minute


def _horario_del_dia(fecha):
    """(desde, hasta) en minutos desde la medianoche, o None si ese día no hay retiro."""
    for _nombre, dias, desde, hasta in RETIRO_TRAMOS:
        if fecha.weekday() in dias:
            return _a_minutos(desde), _a_minutos(hasta)
    return None


def _cabe_en_turno(fecha, inicio, turno):
    """True si la franja que empieza en `inicio` (minutos) cabe entera en el turno ese día."""
    if fecha.weekday() not in turno.dias_activos():
        return False
    turno_desde, turno_hasta = _minutos_de(turno.hora_inicio), _minutos_de(turno.hora_fin)
    fin = inicio + PASO_MIN
    if turno_desde <= turno_hasta:
        return turno_desde <= inicio and fin <= turno_hasta
    return inicio >= turno_desde or fin <= turno_hasta   # el turno cruza la medianoche


def _cabe_en_los_turnos(fecha, inicio, turnos_por_producto):
    """La franja debe caber en algún turno de cada producto restringido del carrito."""
    return all(
        any(_cabe_en_turno(fecha, inicio, turno) for turno in turnos)
        for turnos in turnos_por_producto if turnos
    )


def franjas_del_dia(fecha, ahora_=None, turnos_por_producto=()):
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
        if inicio >= minimo and _cabe_en_los_turnos(fecha, inicio, turnos_por_producto):
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


def _dias_hacia_adelante(turnos_por_producto):
    return DIAS_ADELANTE_CON_TURNOS if any(turnos_por_producto) else DIAS_ADELANTE


def dias_de_retiro(ahora_=None, turnos_por_producto=()):
    """Días con horas disponibles, en el formato que usa el carrito."""
    ahora_ = ahora_ or ahora()
    dias = []
    for i in range(_dias_hacia_adelante(turnos_por_producto) + 1):
        fecha = (ahora_ + timedelta(days=i)).date()
        horas = franjas_del_dia(fecha, ahora_, turnos_por_producto)
        if horas:
            dias.append({
                'fecha': fecha.isoformat(),
                'etiqueta': _etiqueta(fecha, ahora_.date()),
                'horas': [{'valor': h, 'texto': _rango(h)} for h in horas],
            })
    return dias


def validar_retiro(fecha_texto, hora_texto, ahora_=None, turnos_por_producto=()):
    """Comprueba el día y la hora elegidos. Devuelve (fecha, hora, None) o (None, None, mensaje)."""
    ahora_ = ahora_ or ahora()
    try:
        fecha = datetime.strptime(fecha_texto, '%Y-%m-%d').date()
        datetime.strptime(hora_texto, '%H:%M')
    except (TypeError, ValueError):
        return None, None, 'Elige un día y una hora válidos.'

    dentro_de_los_dias = 0 <= (fecha - ahora_.date()).days <= _dias_hacia_adelante(turnos_por_producto)
    if not dentro_de_los_dias or hora_texto not in franjas_del_dia(fecha, ahora_):
        return None, None, 'Esa hora ya no está disponible. Elige otra.'
    if hora_texto not in franjas_del_dia(fecha, ahora_, turnos_por_producto):
        return None, None, (
            'Esa hora no está disponible para todos los productos de tu carrito. '
            'Elige una de las horas que te mostramos.'
        )
    return fecha, hora_texto, None


def texto_retiro(fecha, hora):
    """Texto que se guarda en el pedido y se muestra en el comprobante."""
    return f'{_nombre_del_dia(fecha)}, de {_rango(hora)}'
