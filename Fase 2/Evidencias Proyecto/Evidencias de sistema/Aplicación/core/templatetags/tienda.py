"""Datos de la tienda para las plantillas (pie de página y página Local).

Uso:  {% load tienda %}{% datos_tienda as tienda %}  y luego {{ tienda.direccion }}
Es una etiqueta de plantilla y no un context processor para no depender de settings.py.
Aquí se cambian los datos en un solo lugar.
"""
from urllib.parse import quote_plus

from django import template

register = template.Library()

DIRECCION = 'Marigen 9795'
ZONA = 'La Florida, Región Metropolitana'

TIENDA = {
    'nombre': 'Los Tres Spa',

    # Dirección según el documento 1.5 (Fase 1). Coordenadas obtenidas de OpenStreetMap.
    'direccion': DIRECCION,
    'zona': ZONA,
    'latitud': -33.54589,
    'longitud': -70.59603,
    'mapa_url': 'https://www.google.com/maps/search/?api=1&query='
                + quote_plus(f'{DIRECCION}, {ZONA}'),

    # Datos de "¿Quiénes somos?", según el documento 1.5 (Fase 1)
    'comuna': 'La Florida',
    'inicio_actividades': '2022-08-02',
    'inicio_actividades_texto': '2 de agosto de 2022',
    'trabajadores': 40,
    # Misión y visión entregadas por el equipo (la misión sale de los objetivos de la panadería con el proyecto).
    # Si alguna se deja vacía, la página Local no la muestra.
    'mision': (
        'Automatizar nuestros procesos manuales y dar un salto hacia lo digital. '
        'Mejorar la gestión de los pedidos, tanto en la tienda física como en la digital, '
        'administrar los insumos de nuestros productos y consolidar una base más fuerte de clientes.'
    ),
    'vision': (
        'Dar un servicio más rápido y efectivo, y mantener la calidad sin perder la esencia '
        'tradicional de la producción de nuestros productos. Adaptar un marco digital a la estructura '
        'de nuestras ventas para consolidar una relación cercana con nuestros clientes '
        'y reforzar su confianza en nosotros.'
    ),

    # TODO: los horarios, el valor del despacho, el teléfono y el correo son de ejemplo.
    # Reemplazar por los datos reales que entregue el cliente.
    'horario_atencion': [
        ('Lunes a sábado', '8:00 a 20:00'),
        ('Domingo', '9:00 a 14:00'),
    ],
    'horario_retiro': [
        ('Lunes a sábado', '9:00 a 19:30'),
        ('Domingo', '10:00 a 13:30'),
    ],

    # Valor único para toda la comuna. El Sprint 2 (despacho y zona de cobertura)
    # debe leer este mismo valor para no duplicarlo.
    'despacho_valor': 2500,
    'despacho_zona': 'La Florida',

    'telefono': '+56 9 0000 0000',
    'telefono_enlace': '+56900000000',
    'correo': 'contacto@ejemplo.cl',
}


@register.simple_tag
def datos_tienda():
    return TIENDA
