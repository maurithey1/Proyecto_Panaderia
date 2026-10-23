"""Estudio de mercado de materias primas con datos abiertos de ODEPA.

Fuente: https://datos.odepa.gob.cl (API CKAN, pública y sin clave). Se usa el conjunto
"Precios al Consumidor", que recoge cada semana el precio de productos de la canasta
(harina, azúcar, huevos, margarina, etc.) por región y sector.

Los precios son de venta al público (supermercados), no mayoristas: sirven como referencia
de mercado, no reemplazan una cotización de molinera.
"""
import json
import re
from decimal import Decimal, InvalidOperation
from urllib import error, parse, request

from django.db import connection, transaction
from django.db.models import Avg, Max, Min

from .models import PrecioMercado

FUENTE = 'ODEPA'
URL_API = 'https://datos.odepa.gob.cl/es/api/action'
PAQUETE = 'precios-consumidor'
TIMEOUT_SEGUNDOS = 20
SEMANAS_A_GUARDAR = 4
LIMITE_REGISTROS = 5000
MAS_BARATOS = 10
UNIDAD_POR_KILO = '$/kilo'

# Productos de ODEPA útiles para una panadería (nombres exactos tal como los publica ODEPA).
PRODUCTOS_ODEPA = [
    'Harina sin polvos de hornear',
    'Harina con polvos de hornear',
    'Azúcar',
    'Margarina',
    'Mantequilla con sal',
    'Huevo blanco grande (primera)',
    'Huevo color grande (primera)',
    'Leche en Polvo Entera',
    'Leche Fluida Entera',
    'Aceite vegetal',
    'Aceite maravilla',
]


class ErrorMercado(Exception):
    """No se pudo consultar o interpretar la respuesta de la fuente externa."""


def _llamar(accion, **parametros):
    """Hace una consulta GET a la API de ODEPA y devuelve el campo `result` ya decodificado."""
    url = f'{URL_API}/{accion}?{parse.urlencode(parametros)}'
    peticion = request.Request(url, headers={'User-Agent': 'PanaderiaLosTresSpa/1.0'})
    try:
        with request.urlopen(peticion, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            cuerpo = json.loads(respuesta.read().decode('utf-8'))
    except (error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise ErrorMercado(f'No se pudo conectar con ODEPA ({exc}).') from exc
    if not cuerpo.get('success'):
        raise ErrorMercado('ODEPA respondió con un error.')
    return cuerpo['result']


def _recursos_por_anio():
    """Recursos de datos del paquete, del año más reciente al más antiguo."""
    recursos = _llamar('package_show', id=PAQUETE).get('resources', [])
    con_anio = []
    for recurso in recursos:
        coincidencia = re.search(r'(\d{4})', recurso.get('name', ''))
        if coincidencia and recurso.get('datastore_active'):
            con_anio.append((int(coincidencia.group(1)), recurso['id']))
    return [id_recurso for _, id_recurso in sorted(con_anio, reverse=True)]


def _a_decimal(texto):
    """Convierte '1204,933333' (coma decimal chilena) en Decimal; devuelve None si no es válido."""
    try:
        return Decimal(str(texto).strip().replace(',', '.')).quantize(Decimal('0.01'))
    except (InvalidOperation, AttributeError):
        return None


def obtener_precios(producto, semanas=SEMANAS_A_GUARDAR):
    """Descarga de ODEPA los precios de las últimas semanas de un producto.

    Devuelve una lista de diccionarios (uno por semana, región, sector y tipo de punto).
    """
    if producto not in PRODUCTOS_ODEPA:
        raise ErrorMercado('El producto no está entre los disponibles para el estudio de mercado.')

    registros = []
    for id_recurso in _recursos_por_anio():
        resultado = _llamar(
            'datastore_search', resource_id=id_recurso, filters=json.dumps({'Producto': producto}),
            sort='Fecha inicio desc', limit=LIMITE_REGISTROS,
        )
        registros = resultado.get('records', [])
        if registros:
            break
    if not registros:
        raise ErrorMercado(f'ODEPA no tiene precios publicados para "{producto}".')

    ultimas_fechas = sorted({r['Fecha inicio'] for r in registros}, reverse=True)[:semanas]
    precios = []
    for registro in registros:
        if registro['Fecha inicio'] not in ultimas_fechas:
            continue
        minimo = _a_decimal(registro.get('Precio minimo'))
        maximo = _a_decimal(registro.get('Precio maximo'))
        promedio = _a_decimal(registro.get('Precio promedio'))
        if minimo is None or maximo is None or promedio is None:
            continue
        precios.append({
            'fecha': registro['Fecha inicio'],
            'region': registro.get('Region', '')[:100],
            'sector': registro.get('Sector', '')[:100],
            'tipo_punto': registro.get('Tipo de punto monitoreo', '')[:60],
            'unidad': registro.get('Unidad', '')[:60],
            'precio_minimo': minimo,
            'precio_maximo': maximo,
            'precio_promedio': promedio,
        })
    return precios


def actualizar_precios(insumo):
    """Consulta ODEPA para el producto vinculado al insumo y guarda los precios.

    Si ya existía una semana/sector, se actualiza; las semanas anteriores se conservan.
    Devuelve la cantidad de registros procesados.
    """
    if not insumo.producto_odepa:
        raise ErrorMercado('El insumo no tiene un producto de ODEPA asociado.')
    precios = obtener_precios(insumo.producto_odepa)

    filas = [
        PrecioMercado(insumo=insumo, fuente=FUENTE, producto_fuente=insumo.producto_odepa, **precio)
        for precio in precios
    ]
    # MySQL resuelve el conflicto con la clave única de la tabla y no admite indicar campos;
    # PostgreSQL y SQLite sí lo exigen.
    opciones_conflicto = {}
    if connection.features.supports_update_conflicts_with_target:
        opciones_conflicto['unique_fields'] = ['insumo', 'fuente', 'region', 'sector', 'tipo_punto', 'fecha']
    with transaction.atomic():
        PrecioMercado.objects.bulk_create(
            filas, batch_size=500, update_conflicts=True,
            update_fields=['producto_fuente', 'unidad', 'precio_minimo', 'precio_maximo', 'precio_promedio'],
            **opciones_conflicto,
        )
    return len(filas)


def estudio_mercado(insumo, precio_saco_mas_barato=None):
    """Resume el último estudio guardado: dónde está más barato, promedio nacional y tendencia.

    `precio_saco_mas_barato` es la cotización de molinera más económica (solo materia prima);
    si el producto de ODEPA se mide por kilo, se compara contra el promedio de mercado.
    Devuelve None si el insumo no tiene datos de mercado.
    """
    if not insumo.producto_odepa:
        return None
    precios = PrecioMercado.objects.filter(
        insumo=insumo, fuente=FUENTE, producto_fuente=insumo.producto_odepa,
    )
    ultima_fecha = precios.aggregate(f=Max('fecha'))['f']
    if ultima_fecha is None:
        return None

    semana = precios.filter(fecha=ultima_fecha)
    resumen = semana.aggregate(promedio=Avg('precio_promedio'), minimo=Min('precio_promedio'),
                               maximo=Max('precio_promedio'))
    unidad = semana.values_list('unidad', flat=True).first() or ''

    tendencia = [
        {'fecha': fila['fecha'], 'promedio': fila['promedio']}
        for fila in precios.values('fecha').annotate(promedio=Avg('precio_promedio')).order_by('-fecha')
    ]

    estudio = {
        'producto': insumo.producto_odepa,
        'fecha': ultima_fecha,
        'unidad': unidad,
        'cantidad_puntos': semana.count(),
        'promedio': resumen['promedio'],
        'minimo': resumen['minimo'],
        'maximo': resumen['maximo'],
        'mas_baratos': list(semana.order_by('precio_promedio', 'region', 'sector')[:MAS_BARATOS]),
        'tendencia': tendencia,
        'comparacion': None,
    }

    if precio_saco_mas_barato and unidad == UNIDAD_POR_KILO and insumo.kilos_por_saco > 0:
        tu_precio_kg = precio_saco_mas_barato / insumo.kilos_por_saco
        promedio = Decimal(resumen['promedio'])
        estudio['comparacion'] = {
            'tu_precio_kg': tu_precio_kg,
            'diferencia': tu_precio_kg - promedio,
            'porcentaje': ((tu_precio_kg - promedio) / promedio * 100) if promedio else Decimal('0'),
            'mas_barato_que_mercado': tu_precio_kg < promedio,
        }
    return estudio
