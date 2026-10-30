"""Mermas: inventario que se pierde sin venderse (HU-EP002-008).

Pan que sobró y se botó, una bandeja quemada, un saco de harina con humedad... Mientras nadie lo
registre, el sistema sigue ofreciendo en la tienda y en el POS lo que ya no existe, y las pérdidas
no se ven. Registrar una merma descuenta el stock y deja constancia de qué se perdió, cuánto, por
qué, quién lo registró y cuándo, con su valor estimado en pesos.

Reglas:
  * el motivo es obligatorio (criterio 3); con "Otro", también el detalle;
  * la cantidad es mayor a 0 y no puede superar lo disponible (criterio 2):
      - productos: en su unidad de venta y entera (unidades o kg; Producto.stock es entero);
      - insumos: se elige el envase (el saco, la caja o el bidón) y la cantidad va en la unidad del
        insumo, aunque sea parcial: 10 huevos de la caja en uso que tiene 76, o 2,5 kg de un saco
        (kg y L admiten 2 decimales; un., enteros). No puede superar lo que le queda a ese envase;
  * el stock se descuenta y la merma se guarda en una sola transacción, con las filas bloqueadas
    (el producto, o el insumo y su envase): una venta o una segunda merma esperan su turno (criterio 1);
  * la pérdida se valoriza al precio de venta (productos) o a lo que costó el envase dividido por lo
    que trae (insumos: $36.990 / 180 = $205,50 por huevo).
"""
import re
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Prefetch, Sum
from django.utils import timezone

from .models import EnvaseInsumo, Insumo, Merma, Producto
from .templatetags.formato import clp

PRODUCTO = 'PRODUCTO'
INSUMO = 'INSUMO'
LARGO_MAXIMO_DETALLE = 255
DIAS_HISTORIAL = 30               # período que muestra el historial si no se filtra por fecha

_ENTERO = re.compile(r'^\d{1,6}$')
_DECIMAL = re.compile(r'^\d{1,7}([.,]\d{1,2})?$')
_ITEM = re.compile(r'^(producto|insumo|envase)-(\d+)$')


class MermaInvalida(Exception):
    """La merma no se puede registrar; el mensaje es para el administrador."""


def unidad(item):
    """Unidad en que se descuenta: la del insumo (kg, L o un.); en productos, 'kg' o 'unid.'."""
    if isinstance(item, Insumo):
        return item.unidad
    return 'kg' if item.unidad_medida == 'kg' else 'unid.'


def _numero(valor):
    """Decimal('25.00') -> '25'; Decimal('0.50') -> '0.5' (sin notación científica)."""
    return format(Decimal(valor).normalize(), 'f') if valor else '0'


def con_unidad(cantidad, nombre_unidad):
    """12 unid., 2,5 kg, 76 un. ('sacos' y 'envases' son como se guardaron las primeras mermas de insumos.)"""
    if nombre_unidad in ('sacos', 'envases'):
        nombre_unidad = 'unid.'
    return f"{_numero(cantidad).replace('.', ',')} {nombre_unidad}"


def envase_por_defecto(insumo):
    """El envase del que se descuenta si no se elige uno: el que está en uso; si no, el más antiguo."""
    con_stock = list(insumo.envases.filter(restante__gt=0))
    return next((envase for envase in con_stock if envase.en_uso), None) or (con_stock[0] if con_stock else None)


def item_preseleccionado(valor):
    """Desde Gestión de inventario llega "insumo-<id>": se elige su envase por defecto."""
    coincide = _ITEM.match(str(valor or ''))
    if coincide and coincide.group(1) == 'insumo':
        insumo = Insumo.objects.filter(pk=coincide.group(2)).first()
        envase = envase_por_defecto(insumo) if insumo else None
        if envase:
            return f'envase-{envase.pk}'
    return valor


def opciones_items():
    """Opciones del selector: los productos y, de cada insumo, sus envases con lo que les queda.

    Los envases en uso van uno por uno ("Huevo blanco, caja: quedan 76 de 180 un. (en uso)"); los que
    siguen cerrados e iguales se juntan en una opción ("caja de 180 un. (sin abrir, 2)"): da lo mismo
    cuál de ellos se elija.
    """
    productos = [
        {
            'valor': f'producto-{p.pk}',
            'nombre': p.nombre,
            'etiqueta': f'{p.nombre}: {con_unidad(p.stock, unidad(p))}' if p.stock > 0 else f'{p.nombre}: sin stock',
            'stock': p.stock,
            'unidad': unidad(p),
            'precio': _numero(p.precio),
            'decimales': '',
            'sin_stock': p.stock <= 0,
        }
        for p in Producto.objects.order_by('nombre')
    ]

    insumos = []
    envases_con_stock = Prefetch('envases', queryset=EnvaseInsumo.objects.filter(restante__gt=0))
    for insumo in Insumo.objects.prefetch_related(envases_con_stock).order_by('nombre'):
        u = insumo.unidad
        comun = {
            'nombre': insumo.nombre,
            'unidad': u,
            'decimales': '' if u == 'un.' else '1',
            'total': _numero(insumo.total_kg),
        }
        envases = sorted(insumo.envases.all(), key=lambda envase: not envase.en_uso)    # el que está en uso, primero
        if not envases:
            insumos.append({**comun, 'valor': f'insumo-{insumo.pk}', 'etiqueta': f'{insumo.nombre}: sin stock',
                            'stock': '0', 'precio': '0', 'tipo': '', 'sin_stock': True})
            continue
        cerrados = {}
        for envase in envases:
            datos = {
                **comun, 'valor': f'envase-{envase.pk}', 'stock': _numero(envase.restante),
                'precio': _numero(round(envase.precio_por_unidad, 2)), 'tipo': envase.tipo, 'sin_stock': False,
            }
            if envase.en_uso:
                datos['etiqueta'] = (f'{insumo.nombre}, {envase.tipo}: quedan {_numero(envase.restante).replace(".", ",")} '
                                     f'de {con_unidad(envase.contenido, u)} (en uso)')
                insumos.append(datos)
            else:
                clave = (envase.tipo, envase.contenido, envase.precio)
                if clave in cerrados:
                    cerrados[clave]['iguales'] += 1
                else:
                    datos['iguales'] = 1
                    cerrados[clave] = datos
                    insumos.append(datos)
        for datos in cerrados.values():
            extra = f', {datos["iguales"]}' if datos['iguales'] > 1 else ''
            datos['etiqueta'] = f'{insumo.nombre}, {datos["tipo"]} de {con_unidad(datos["stock"], u)} (sin abrir{extra})'
    return {'productos': productos, 'insumos': insumos}


def _leer_item(valor):
    coincide = _ITEM.match(str(valor or '').strip())
    if not coincide:
        raise MermaInvalida('Selecciona el producto o insumo que se perdió.')
    tipo, pk = coincide.groups()
    return tipo, int(pk)


def _leer_cantidad(texto, decimales=False):
    """Cantidad perdida: entera, o con hasta 2 decimales en insumos que se miden en kg o L."""
    limpio = str(texto or '').replace(' ', '')
    if not limpio:
        raise MermaInvalida('Ingresa la cantidad que se perdió.')
    if decimales:
        if not _DECIMAL.match(limpio) or not Decimal(limpio.replace(',', '.')):
            raise MermaInvalida('La cantidad debe ser un número mayor a 0, con hasta 2 decimales.')
        return Decimal(limpio.replace(',', '.'))
    if not _ENTERO.match(limpio) or int(limpio) == 0:
        raise MermaInvalida('La cantidad debe ser un número entero mayor a 0, sin decimales.')
    return Decimal(int(limpio))


def _envase_elegido(tipo, pk):
    """El envase de la merma: el elegido ("envase-<id>") o el por defecto del insumo ("insumo-<id>")."""
    if tipo == 'envase':
        envase = EnvaseInsumo.objects.select_related('insumo').filter(pk=pk).first()
        if envase is None:
            raise MermaInvalida('El envase seleccionado ya no existe.')
        return envase
    insumo = Insumo.objects.filter(pk=pk).first()
    if insumo is None:
        raise MermaInvalida('El producto o insumo seleccionado ya no existe.')
    envase = envase_por_defecto(insumo)
    if envase is None:
        raise MermaInvalida(f'No quedan envases con stock de {insumo.nombre}.')
    return envase


def registrar_merma(responsable, item, cantidad, motivo, detalle=''):
    """Descuenta el stock y guarda la merma. Devuelve la Merma o lanza MermaInvalida."""
    tipo, pk = _leer_item(item)
    envase = None if tipo == 'producto' else _envase_elegido(tipo, pk)
    cantidad = _leer_cantidad(cantidad, decimales=envase is not None and envase.insumo.unidad != 'un.')

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
        if envase is None:
            return _merma_de_producto(responsable, pk, cantidad, motivo, detalle)
        return _merma_de_envase(responsable, envase, cantidad, motivo, detalle)


def _merma_de_producto(responsable, pk, cantidad, motivo, detalle):
    # Fila bloqueada hasta el final: el stock que se compara es el que se descuenta
    producto = Producto.objects.select_for_update().filter(pk=pk).first()
    if producto is None:
        raise MermaInvalida('El producto o insumo seleccionado ya no existe.')
    u = unidad(producto)
    disponible = producto.stock
    if cantidad > disponible:
        raise MermaInvalida(
            f'Solo hay {con_unidad(disponible, u)} de {producto.nombre}: '
            f'la cantidad ({con_unidad(cantidad, u)}) excede el stock disponible.'
        )
    producto.stock = disponible - int(cantidad)
    producto.save(update_fields=['stock'])
    return Merma.objects.create(
        tipo=PRODUCTO, producto=producto, nombre_item=producto.nombre, unidad=u, cantidad=cantidad,
        motivo=motivo, detalle=detalle, stock_anterior=disponible, stock_resultante=producto.stock,
        valor_estimado=(producto.precio or 0) * cantidad, responsable=responsable,
    )


def _merma_de_envase(responsable, envase, cantidad, motivo, detalle):
    # Se bloquean el insumo y el envase (en ese orden, siempre): lo que se compara es lo que se descuenta
    insumo = Insumo.objects.select_for_update().filter(pk=envase.insumo_id).first()
    envase = EnvaseInsumo.objects.select_for_update().filter(pk=envase.pk).first()
    if insumo is None or envase is None:
        raise MermaInvalida('El envase seleccionado ya no existe.')
    u = insumo.unidad
    if cantidad > envase.restante:
        raise MermaInvalida(
            f'Solo quedan {con_unidad(envase.restante, u)} en ese envase ({envase.tipo}) de {insumo.nombre}: '
            f'la cantidad ({con_unidad(cantidad, u)}) excede el stock disponible.'
        )
    stock_anterior = insumo.total_kg
    envase.restante -= cantidad
    envase.save(update_fields=['restante'])
    insumo.actualizar_stock()
    return Merma.objects.create(
        tipo=INSUMO, insumo=insumo, envase=envase, nombre_item=f'{insumo.nombre} ({envase.tipo})',
        unidad=u, cantidad=cantidad, motivo=motivo, detalle=detalle,
        stock_anterior=stock_anterior, stock_resultante=insumo.total_kg,
        valor_estimado=(cantidad * envase.precio_por_unidad).quantize(Decimal('0.01')), responsable=responsable,
    )


def texto_registrada(merma):
    """Mensaje de éxito: qué se descontó, cuánto se perdió y cómo quedó el stock."""
    quedan = con_unidad(merma.stock_resultante, merma.unidad)
    return (
        f'Merma registrada: {con_unidad(merma.cantidad, merma.unidad)} de {merma.nombre_item} '
        f'por {merma.get_motivo_display().lower()}, pérdida estimada de {clp(merma.valor_estimado)}. '
        f'Quedan {quedan}' + ('' if quedan.endswith('.') else '.')      # "un." y "unid." ya traen su punto
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
