"""Mermas: inventario que se pierde sin venderse (HU-EP002-008).

Pan que sobró y se botó, una bandeja quemada, un saco de harina con humedad... Mientras nadie lo
registre, el sistema sigue ofreciendo en la tienda y en el POS lo que ya no existe, y las pérdidas
no se ven. Registrar una merma descuenta el stock y deja constancia de qué se perdió, cuánto, por
qué, quién lo registró y cuándo, con su valor estimado en pesos.

Reglas:
  * el motivo es obligatorio (criterio 3); con "Otro", también el detalle;
  * la cantidad es un entero mayor a 0 y no puede superar el stock disponible (criterio 2);
  * productos: en su unidad de venta (unidades o kg, Producto.stock es entero);
    insumos: en unidades enteras. El modelo las llama "sacos" (Insumo.stock_sacos, kilos_por_saco),
    pero un insumo puede venir en saco, caja o bidón, así que aquí se habla de unidades con su
    contenido (1 unidad = 25 kg). Insumo.save() recalcula los kg desde las unidades: las mermas
    parciales (2 kg, 3 L) quedan para cuando el stock de insumos se lleve en su unidad de medida;
  * el stock se descuenta y la merma se guarda en una sola transacción, con la fila del producto o
    insumo bloqueada: una venta o una segunda merma al mismo tiempo esperan su turno (criterio 1);
  * la pérdida se valoriza al precio de venta (productos) o al precio por unidad vigente (insumos).
"""
import re
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from .models import Insumo, Merma, Producto
from .templatetags.formato import clp

PRODUCTO = 'PRODUCTO'
INSUMO = 'INSUMO'
LARGO_MAXIMO_DETALLE = 255
DIAS_HISTORIAL = 30               # período que muestra el historial si no se filtra por fecha

_CANTIDAD = re.compile(r'^\d{1,6}$')
_ITEM = re.compile(r'^(producto|insumo)-(\d+)$')


class MermaInvalida(Exception):
    """La merma no se puede registrar; el mensaje es para el administrador."""


def unidad(item):
    """Unidad en que se descuenta el stock: 'kg' para productos que se venden por kilo; si no, 'unid.'."""
    if isinstance(item, Producto) and item.unidad_medida == 'kg':
        return 'kg'
    return 'unid.'


def con_unidad(cantidad, nombre_unidad):
    """12 unid., 5 kg. ('sacos' y 'envases' son como se guardaron las primeras mermas de insumos.)"""
    if nombre_unidad in ('sacos', 'envases'):
        nombre_unidad = 'unid.'
    return f'{cantidad} {nombre_unidad}'


def unidad_contenido(insumo):
    """Unidad del contenido de cada unidad, según Insumo.unidad_medida: kg (lo habitual), L o unid."""
    texto = (insumo.unidad_medida or '').strip().lower().rstrip('.')
    if texto in ('l', 'lt', 'lts', 'litro', 'litros'):
        return 'L'
    if texto in ('u', 'un', 'unid', 'unidad', 'unidades'):
        return 'unid.'
    return 'kg'


def _numero(valor):
    """Decimal('25.00') -> '25'; Decimal('0.50') -> '0.5' (sin notación científica)."""
    return format(valor.normalize(), 'f') if valor else '0'


def stock_de(item):
    return item.stock_sacos if isinstance(item, Insumo) else item.stock


def valor_unitario(item):
    return item.precio_saco if isinstance(item, Insumo) else item.precio


def opciones_items():
    """Productos e insumos para el selector del formulario, con su stock y su valor por unidad.

    Los insumos llevan además el contenido de cada unidad (25 kg, 20 L), para mostrar el equivalente.
    """
    def opcion(prefijo, item):
        datos = {
            'valor': f'{prefijo}-{item.pk}',
            'nombre': item.nombre,
            'stock': stock_de(item),
            'unidad': unidad(item),
            'precio': int(valor_unitario(item) or 0),
            'contenido': '',
            'unidad_contenido': '',
        }
        if isinstance(item, Insumo):
            datos['contenido'] = _numero(item.kilos_por_saco)
            datos['unidad_contenido'] = unidad_contenido(item)
        return datos

    return {
        'productos': [opcion('producto', p) for p in Producto.objects.order_by('nombre')],
        'insumos': [opcion('insumo', i) for i in Insumo.objects.order_by('nombre')],
    }


def _leer_item(valor):
    coincide = _ITEM.match(str(valor or '').strip())
    if not coincide:
        raise MermaInvalida('Selecciona el producto o insumo que se perdió.')
    tipo, pk = coincide.groups()
    return (Producto if tipo == 'producto' else Insumo), int(pk)


def _leer_cantidad(texto):
    limpio = str(texto or '').replace(' ', '')
    if not limpio:
        raise MermaInvalida('Ingresa la cantidad que se perdió.')
    if not _CANTIDAD.match(limpio) or int(limpio) == 0:
        raise MermaInvalida('La cantidad debe ser un número entero mayor a 0, sin decimales.')
    return int(limpio)


def registrar_merma(responsable, item, cantidad, motivo, detalle=''):
    """Descuenta el stock y guarda la merma. Devuelve la Merma o lanza MermaInvalida."""
    modelo, pk = _leer_item(item)
    cantidad = _leer_cantidad(cantidad)

    motivo = (motivo or '').strip()
    detalle = (detalle or '').strip()
    if not motivo:
        raise MermaInvalida('El motivo es obligatorio: indica por qué se perdió.')
    if motivo not in dict(Merma.MOTIVOS):
        raise MermaInvalida('Selecciona un motivo de la lista.')
    if motivo == 'OTRO' and not detalle:
        raise MermaInvalida('Con el motivo "Otro", describe en el detalle qué pasó.')
    if len(detalle) > LARGO_MAXIMO_DETALLE:
        raise MermaInvalida(f'El detalle puede tener hasta {LARGO_MAXIMO_DETALLE} caracteres.')

    with transaction.atomic():
        # Fila bloqueada hasta el final: el stock que se compara es el que se descuenta
        obj = modelo.objects.select_for_update().filter(pk=pk).first()
        if obj is None:
            raise MermaInvalida('El producto o insumo seleccionado ya no existe.')

        nombre_unidad = unidad(obj)
        disponible = stock_de(obj)
        if cantidad > disponible:
            raise MermaInvalida(
                f'Solo hay {con_unidad(disponible, nombre_unidad)} de {obj.nombre}: '
                f'la cantidad ({con_unidad(cantidad, nombre_unidad)}) excede el stock disponible.'
            )

        if modelo is Insumo:
            obj.stock_sacos = disponible - cantidad
            obj.save(update_fields=['stock_sacos', 'total_kg', 'stock_actual'])   # save() recalcula los kg
        else:
            obj.stock = disponible - cantidad
            obj.save(update_fields=['stock'])

        return Merma.objects.create(
            tipo=INSUMO if modelo is Insumo else PRODUCTO,
            producto=obj if modelo is Producto else None,
            insumo=obj if modelo is Insumo else None,
            nombre_item=obj.nombre,
            unidad=nombre_unidad,
            cantidad=cantidad,
            motivo=motivo,
            detalle=detalle,
            stock_anterior=disponible,
            stock_resultante=disponible - cantidad,
            valor_estimado=(valor_unitario(obj) or 0) * cantidad,
            responsable=responsable,
        )


def texto_registrada(merma):
    """Mensaje de éxito: qué se descontó, cuánto se perdió y cómo quedó el stock."""
    quedan = con_unidad(merma.stock_resultante, merma.unidad)
    return (
        f'Merma registrada: {con_unidad(merma.cantidad, merma.unidad)} de {merma.nombre_item} '
        f'({merma.get_motivo_display().lower()}), pérdida estimada de {clp(merma.valor_estimado)}. '
        f'Quedan {quedan}' + ('' if quedan.endswith('.') else '.')      # "unid." ya trae su punto
    )


# ---------------------------------------------------------------------------
# Historial de pérdidas
# ---------------------------------------------------------------------------

def _fecha(texto):
    try:
        return datetime.strptime(str(texto or ''), '%Y-%m-%d').date()
    except ValueError:
        return None


def leer_filtros(parametros):
    """Filtros del historial desde la URL (?desde=&hasta=&motivo=&tipo=). Sin fechas: últimos 30 días."""
    hoy = timezone.localdate()
    desde = _fecha(parametros.get('desde')) or hoy - timedelta(days=DIAS_HISTORIAL - 1)
    hasta = _fecha(parametros.get('hasta')) or hoy
    if desde > hasta:
        desde, hasta = hasta, desde
    motivo = parametros.get('motivo', '')
    tipo = parametros.get('tipo', '')
    return {
        'desde': desde,
        'hasta': hasta,
        'motivo': motivo if motivo in dict(Merma.MOTIVOS) else '',
        'tipo': tipo if tipo in dict(Merma.TIPOS) else '',
    }


def historial(filtros):
    """Mermas del período filtrado, de la más reciente a la más antigua."""
    # Por rango y no con fecha__date: MySQL sin tablas de zonas horarias no resuelve __date
    inicio = timezone.make_aware(datetime.combine(filtros['desde'], datetime.min.time()))
    fin = timezone.make_aware(datetime.combine(filtros['hasta'] + timedelta(days=1), datetime.min.time()))
    registros = Merma.objects.select_related('responsable').filter(fecha__gte=inicio, fecha__lt=fin)
    if filtros['motivo']:
        registros = registros.filter(motivo=filtros['motivo'])
    if filtros['tipo']:
        registros = registros.filter(tipo=filtros['tipo'])
    return registros.order_by('-fecha', '-pk')


def resumen(registros):
    """Total perdido, cantidad de mermas y desglose por motivo (de mayor a menor pérdida)."""
    nombres = dict(Merma.MOTIVOS)
    por_motivo = [
        {'motivo': nombres.get(fila['motivo'], fila['motivo']), 'total': fila['total'], 'veces': fila['veces']}
        for fila in registros.order_by().values('motivo').annotate(total=Sum('valor_estimado'), veces=Count('pk'))
    ]
    por_motivo.sort(key=lambda fila: fila['total'] or 0, reverse=True)
    total = sum((fila['total'] or 0) for fila in por_motivo)
    for fila in por_motivo:
        # Porcentaje del total, para el largo de la barra de cada motivo
        fila['parte'] = round((fila['total'] or 0) * 100 / total) if total else 0
    return {
        'total': total,
        'veces': sum(fila['veces'] for fila in por_motivo),
        'por_motivo': por_motivo,
    }
