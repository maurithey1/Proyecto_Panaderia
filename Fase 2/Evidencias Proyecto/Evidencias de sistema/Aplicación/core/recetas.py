
import re
from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from .models import (
    ConsumoProduccion, EnvaseInsumo, IngredienteReceta, Insumo, Notificacion, ProduccionDiaria, Producto, Receta,
)

IVA = Decimal('1.19')
CENTESIMA = Decimal('0.01')     # los envases guardan lo que les queda con 2 decimales
TOPE_GRAMOS = 100000            # 100 kg o 100 L de un insumo para una sola unidad: es un error de tipeo
TOPE_UNIDADES = Decimal('10000')

_ENTERO = re.compile(r'^\d{1,6}$')
_DECIMAL = re.compile(r'^\d{1,5}([.,]\d{1,3})?$')


class RecetaInvalida(Exception):
    """La receta no se puede guardar así; el mensaje es para el administrador."""


class ProduccionInvalida(Exception):
    """La hornada no se puede registrar; el mensaje es para el administrador."""


def numero(valor):
    """Decimal('4.960') -> '4,96' (sin ceros de sobra ni notación científica)."""
    return format(Decimal(valor).normalize(), 'f').replace('.', ',') if valor else '0'


def base(producto):
    """Por cuánto producto va la receta: 'kg' si se vende por kilo; si no, 'unid.'."""
    return 'kg' if producto.unidad_medida == 'kg' else 'unid.'


def texto_base(producto):
    return 'por 1 kg' if base(producto) == 'kg' else 'por 1 unidad'


def unidad_de_ingreso(insumo):
    """En qué se escribe la cantidad: g si el insumo va en kg, mL si va en L, un. si se cuenta."""
    return {'kg': 'g', 'L': 'mL'}.get(insumo.unidad, 'un.')


def a_ingreso(insumo, cantidad):
    """Cantidad guardada (0,062 kg) -> como se escribe (62 g)."""
    return cantidad * 1000 if insumo.unidad in ('kg', 'L') else cantidad


def precio_por_unidad(insumo):
    """Lo que cuesta 1 kg, 1 L o 1 un. del insumo: su envase de referencia dividido por lo que trae."""
    if insumo.kilos_por_saco and insumo.kilos_por_saco > 0:
        return Decimal(insumo.precio_saco or 0) / Decimal(insumo.kilos_por_saco)
    return Decimal('0')


def leer_cantidad(texto, insumo):
    """'62' (g) -> Decimal('0.062') kg; '0,5' (un.) -> Decimal('0.5'). Lanza RecetaInvalida (criterio 4)."""
    limpio = str(texto or '').strip().replace(' ', '')
    u = unidad_de_ingreso(insumo)
    if not limpio:
        raise RecetaInvalida(f'Ingresa la cantidad de {insumo.nombre} ({u}).')
    if u == 'un.':
        if not _DECIMAL.match(limpio):
            raise RecetaInvalida('La cantidad debe ser un número mayor a cero, con hasta 3 decimales.')
        cantidad = Decimal(limpio.replace(',', '.'))
        demasiado = cantidad > TOPE_UNIDADES
    else:
        if not _ENTERO.match(limpio):
            raise RecetaInvalida(f'La cantidad debe ser un número entero de {u} mayor a cero.')
        demasiado = int(limpio) > TOPE_GRAMOS
        cantidad = Decimal(int(limpio)) / 1000
    if cantidad <= 0:
        raise RecetaInvalida('La cantidad debe ser mayor a cero.')
    if demasiado:
        raise RecetaInvalida('La cantidad es demasiado grande para una sola unidad: revisa que esté bien escrita.')
    return cantidad


# ---------------------------------------------------------------------------
# La receta
# ---------------------------------------------------------------------------

def agregar_ingrediente(producto, insumo_pk, texto):
    """Agrega un insumo a la receta (la crea si no existe). Lanza RecetaInvalida (criterios 3 y 4)."""
    insumo = Insumo.objects.filter(pk=insumo_pk).first()
    if insumo is None:
        raise RecetaInvalida('Selecciona el insumo que lleva el producto.')
    cantidad = leer_cantidad(texto, insumo)
    with transaction.atomic():
        # El producto bloqueado: dos administradores agregando a la vez quedan en fila
        Producto.objects.select_for_update().filter(pk=producto.pk).first()
        receta, _ = Receta.objects.get_or_create(producto=producto, defaults={'nombre': producto.nombre})
        if receta.ingredientes.filter(insumo=insumo).exists():
            raise RecetaInvalida(f'{insumo.nombre} ya está en la receta: modifica la cantidad del que ya existe.')
        return receta.ingredientes.create(insumo=insumo, cantidad=cantidad)


def cambiar_cantidad(ingrediente, texto):
    """Cambia la cantidad de un insumo de la receta (criterio 2: el costo y el margen se recalculan)."""
    ingrediente.cantidad = leer_cantidad(texto, ingrediente.insumo)
    ingrediente.save(update_fields=['cantidad'])
    return ingrediente


def detalle_costo(producto):
    """Ingredientes con su costo, costo de elaboración por unidad (o por kg) y margen sin IVA."""
    receta = Receta.objects.filter(producto=producto).first()
    lineas = []
    costo = Decimal('0')
    if receta:
        for ingrediente in receta.ingredientes.select_related('insumo').order_by('insumo__nombre'):
            insumo = ingrediente.insumo
            precio = precio_por_unidad(insumo)
            subtotal = ingrediente.cantidad * precio
            costo += subtotal
            lineas.append({
                'ingrediente': ingrediente,
                'insumo': insumo,
                'cantidad': numero(a_ingreso(insumo, ingrediente.cantidad)),
                'unidad_ingreso': unidad_de_ingreso(insumo),
                'precio_unidad': precio,
                'subtotal': subtotal,
            })
    precio_venta = Decimal(producto.precio or 0)
    neto = precio_venta / IVA
    margen = (neto - costo) / neto * 100 if neto and lineas else None
    return {
        'receta': receta,
        'lineas': lineas,
        'costo': costo,
        'precio': precio_venta,
        'precio_neto': neto,
        'iva': precio_venta - neto,
        'margen': margen,
        'ganancia': neto - costo,
        # Para el medidor: qué parte del precio sin IVA es costo (el resto es ganancia)
        'parte_costo': int(min(costo / neto * 100, 100)) if neto else 0,
    }


# ---------------------------------------------------------------------------
# La hornada
# ---------------------------------------------------------------------------

def _descontar_de_envases(insumo, pedido):
    """Saca `pedido` de los envases del insumo (el que está en uso primero, después los cerrados del más
    antiguo al más nuevo) hasta donde alcance. Devuelve (lo usado, lo que costó lo usado)."""
    envases = sorted(
        EnvaseInsumo.objects.select_for_update().filter(insumo=insumo, restante__gt=0),
        key=lambda envase: (not envase.en_uso, envase.fecha_ingreso, envase.pk),
    )
    falta = pedido
    usado = Decimal('0')
    costo = Decimal('0')
    for envase in envases:
        if falta <= 0:
            break
        toma = min(envase.restante, falta)
        envase.restante -= toma
        envase.save(update_fields=['restante'])
        usado += toma
        costo += toma * envase.precio_por_unidad
        falta -= toma
    return usado, costo


def registrar_hornada(producto_pk, cantidad, responsable):
    """Registra la hornada: suma el stock del producto y, si tiene receta, descuenta sus insumos.

    Devuelve (producción, consumos). Lanza ProduccionInvalida si la cantidad no sirve o si a algún
    insumo de la receta no le queda nada.
    """
    if not cantidad or cantidad <= 0:
        raise ProduccionInvalida('Por favor, ingresa una cantidad horneada válida mayor a 0.')

    with transaction.atomic():
        producto = Producto.objects.select_for_update().filter(pk=producto_pk).first()
        if producto is None:
            raise ProduccionInvalida('El producto ya no existe.')
        ingredientes = list(
            IngredienteReceta.objects.filter(receta__producto=producto).select_related('insumo').order_by('insumo_id')
        )
        # Los insumos bloqueados, siempre en el mismo orden: otra hornada o una merma espera su turno
        insumos = {
            insumo.pk: insumo
            for insumo in Insumo.objects.select_for_update().filter(pk__in=[i.insumo_id for i in ingredientes]).order_by('pk')
        }
        en_cero = [insumos[i.insumo_id].nombre for i in ingredientes if insumos[i.insumo_id].total_kg <= 0]
        if en_cero:
            raise ProduccionInvalida(
                f'No queda {", ".join(en_cero)}: registra lo que llegó con "+ Envase" antes de hornear.'
            )

        produccion = ProduccionDiaria.objects.create(producto=producto, cantidad=cantidad, responsable=responsable)
        consumos = []
        for ingrediente in ingredientes:
            insumo = insumos[ingrediente.insumo_id]
            pedido = (ingrediente.cantidad * cantidad).quantize(CENTESIMA, ROUND_HALF_UP)
            usado, costo = _descontar_de_envases(insumo, pedido)
            insumo.actualizar_stock()
            consumos.append(ConsumoProduccion.objects.create(
                produccion=produccion, insumo=insumo, nombre_insumo=insumo.nombre, unidad=insumo.unidad,
                cantidad_receta=pedido, cantidad_usada=usado, faltante=pedido - usado,
                costo=costo.quantize(CENTESIMA, ROUND_HALF_UP),
            ))

        producto.stock += cantidad
        producto.save(update_fields=['stock'])

        # Cada faltante avisa en la campana del panel (sin insumo asociado, para que la limpieza
        # automática de alertas de stock no la borre)
        for consumo in consumos:
            if consumo.faltante > 0:
                Notificacion.objects.create(
                    tipo='INSUMO',
                    titulo=f'Faltó {consumo.nombre_insumo} en una hornada',
                    mensaje=(
                        f'La hornada de {cantidad} {base(producto)} de {producto.nombre} pedía '
                        f'{numero(consumo.cantidad_receta)} {consumo.unidad} de {consumo.nombre_insumo} y quedaban '
                        f'{numero(consumo.cantidad_usada)}: faltaron {numero(consumo.faltante)} {consumo.unidad}. '
                        f'Revisa el stock o la receta.'
                    ),
                )
    return produccion, consumos


# ---------------------------------------------------------------------------
# Déficit de insumos
# ---------------------------------------------------------------------------

def deficit(registros):
    """Resumen por insumo de los faltantes del período: cuánto faltó en total y en cuántas hornadas."""
    por_insumo = OrderedDict()
    for consumo in registros:
        clave = (consumo.nombre_insumo, consumo.unidad)
        fila = por_insumo.setdefault(clave, {'insumo': consumo.nombre_insumo, 'unidad': consumo.unidad,
                                            'faltante': Decimal('0'), 'veces': 0})
        fila['faltante'] += consumo.faltante
        fila['veces'] += 1
    return sorted(por_insumo.values(), key=lambda fila: fila['veces'], reverse=True)
