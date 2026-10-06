from django import template

register = template.Library()


@register.filter
def clp(valor):
    """Formatea un monto como pesos chilenos: 3190 -> $3.190"""
    try:
        entero = int(round(float(valor)))
    except (TypeError, ValueError):
        return valor
    return '${:,}'.format(entero).replace(',', '.')
