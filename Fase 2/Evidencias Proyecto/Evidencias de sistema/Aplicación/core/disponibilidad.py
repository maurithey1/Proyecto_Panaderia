"""Disponibilidad de un producto según sus turnos de venta.

Un producto sin turnos se vende todo el día, todos los días. Con turnos, solo cuando rige alguno.
Las funciones reciben un datetime con zona horaria (la hora de Chile, ver core/retiro.py).
"""
from datetime import datetime, timedelta

DIAS_PROXIMOS = 8  # se busca la próxima apertura dentro de una semana y un día


def esta_disponible(turnos, momento):
    """True si el producto se puede vender en ese momento."""
    return not turnos or any(turno.rige_en(momento) for turno in turnos)


def proxima_disponibilidad(turnos, momento):
    """El primer instante posterior a `momento` en que empieza algún turno; None si no hay."""
    inicios = []
    for desplazamiento in range(DIAS_PROXIMOS):
        dia = (momento + timedelta(days=desplazamiento)).date()
        for turno in turnos:
            if dia.weekday() in turno.dias_activos():
                inicio = datetime.combine(dia, turno.hora_inicio, tzinfo=momento.tzinfo)
                if inicio > momento:
                    inicios.append(inicio)
    return min(inicios) if inicios else None


def texto_proxima(inicio, momento):
    """'hoy a las 14:00', 'mañana a las 10:00' o 'el jueves a las 10:00'."""
    dias = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
    diferencia = (inicio.date() - momento.date()).days
    if diferencia == 0:
        cuando = 'hoy'
    elif diferencia == 1:
        cuando = 'mañana'
    else:
        cuando = f'el {dias[inicio.weekday()]}'
    return f'{cuando} a las {inicio:%H:%M}'


def resumen(turnos, momento):
    """Datos para mostrar en el detalle del producto: (disponible_ahora, texto_de_proxima o '')."""
    disponible = esta_disponible(turnos, momento)
    if disponible:
        return True, ''
    inicio = proxima_disponibilidad(turnos, momento)
    return False, texto_proxima(inicio, momento) if inicio else ''
