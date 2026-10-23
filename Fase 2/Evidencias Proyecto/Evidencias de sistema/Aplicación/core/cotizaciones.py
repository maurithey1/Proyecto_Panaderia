"""Comparación de cotizaciones de molineras (proveedores) para una materia prima.

El costo de cada opción incluye la materia prima y el flete:

    costo total = precio por saco x cantidad de sacos + flete del proveedor

El precio por saco es ProveedorInsumo.precio_ofrecido y el flete es Proveedor.costo_flete
(un único flete por pedido, sin importar la cantidad de sacos).
"""
from decimal import Decimal
from django.db.models import Prefetch

from .models import Insumo, ProveedorInsumo

SACOS_MINIMOS = 1
SACOS_MAXIMOS = 100000


def limitar_sacos(valor):
    """Devuelve una cantidad de sacos válida (entero entre el mínimo y el máximo)."""
    try:
        sacos = int(valor)
    except (TypeError, ValueError):
        return SACOS_MINIMOS
    return max(SACOS_MINIMOS, min(sacos, SACOS_MAXIMOS))


def comparar_cotizaciones(insumo, sacos):
    """Lista las cotizaciones del insumo ordenadas de menor a mayor costo total.

    Cada elemento trae el desglose (materia prima, flete, total), la diferencia contra la opción
    más barata y las marcas `es_mejor` (única, la de menor costo) y `empata_mejor` (mismo total).
    """
    sacos = limitar_sacos(sacos)
    cotizaciones = ProveedorInsumo.objects.filter(insumo=insumo).select_related('proveedor')

    opciones = []
    for cotizacion in cotizaciones:
        materia_prima = cotizacion.precio_ofrecido * sacos
        flete = cotizacion.proveedor.costo_flete
        opciones.append({
            'cotizacion': cotizacion,
            'proveedor': cotizacion.proveedor,
            'precio_saco': cotizacion.precio_ofrecido,
            'materia_prima': materia_prima,
            'flete': flete,
            'total': materia_prima + flete,
        })

    opciones.sort(key=lambda o: (o['total'], o['proveedor'].nombre_proveedor.lower()))

    if opciones:
        mejor_total = opciones[0]['total']
        kilos = insumo.kilos_por_saco * sacos
        for posicion, opcion in enumerate(opciones):
            opcion['es_mejor'] = posicion == 0
            opcion['empata_mejor'] = posicion > 0 and opcion['total'] == mejor_total
            opcion['diferencia'] = opcion['total'] - mejor_total
            # Costo por kilo puesto en la panadería, para comparar entre distintos tamaños de pedido.
            opcion['costo_kg'] = (opcion['total'] / kilos) if kilos > 0 else Decimal('0')
    return opciones


def tabla_comparativa_insumos():
    """Genera un listado de todos los insumos mostrando el mejor proveedor y precio disponible para cada uno."""
    insumos = Insumo.objects.prefetch_related(
        Prefetch('proveedorinsumo_set', queryset=ProveedorInsumo.objects.select_related('proveedor').order_by('precio_ofrecido'))
    ).order_by('codigo', 'nombre')

    resumen = []
    for insumo in insumos:
        cotizaciones = list(insumo.proveedorinsumo_set.all())
        mejor_cotizacion = cotizaciones[0] if cotizaciones else None

        precio_actual = insumo.precio_saco
        mejor_precio = mejor_cotizacion.precio_ofrecido if mejor_cotizacion else None

        ahorro = None
        porcentaje_ahorro = None
        if mejor_precio is not None and precio_actual > 0:
            diferencia = precio_actual - mejor_precio
            if diferencia > 0:
                ahorro = diferencia
                porcentaje_ahorro = (diferencia / precio_actual) * Decimal('100')

        costo_kg_mejor = None
        if mejor_precio is not None and insumo.kilos_por_saco > 0:
            costo_kg_mejor = mejor_precio / insumo.kilos_por_saco

        costo_kg_actual = None
        if precio_actual > 0 and insumo.kilos_por_saco > 0:
            costo_kg_actual = precio_actual / insumo.kilos_por_saco

        resumen.append({
            'insumo': insumo,
            'cantidad_cotizaciones': len(cotizaciones),
            'mejor_cotizacion': mejor_cotizacion,
            'mejor_proveedor': mejor_cotizacion.proveedor if mejor_cotizacion else None,
            'mejor_precio': mejor_precio,
            'precio_actual': precio_actual,
            'costo_kg_actual': costo_kg_actual,
            'costo_kg_mejor': costo_kg_mejor,
            'ahorro': ahorro,
            'porcentaje_ahorro': porcentaje_ahorro,
        })
    return resumen
