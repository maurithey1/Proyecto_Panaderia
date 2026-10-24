from django.db.models import F
from django.utils import timezone
from django.contrib import messages
from .models import Insumo, Producto, Notificacion

# Umbral de rentabilidad mínima deseada para los productos (30%)
MARGEN_MINIMO_DESEADO = 30.0 


def _limpiar_duplicados_existentes():
    """Elimina notificaciones duplicadas conservando solo la más reciente por ítem."""
    # Duplicados de insumos
    for insumo_id in Notificacion.objects.filter(tipo='INSUMO', insumo__isnull=False).values_list('insumo_id', flat=True).distinct():
        notifs = Notificacion.objects.filter(tipo='INSUMO', insumo_id=insumo_id).order_by('-fecha_creacion')
        if notifs.count() > 1:
            pks_viejas = list(notifs.values_list('pk', flat=True))[1:]
            Notificacion.objects.filter(pk__in=pks_viejas).delete()

    # Duplicados de productos (Stock)
    for prod_id in Notificacion.objects.filter(tipo='PRODUCTO', producto__isnull=False).values_list('producto_id', flat=True).distinct():
        notifs = Notificacion.objects.filter(tipo='PRODUCTO', producto_id=prod_id).order_by('-fecha_creacion')
        if notifs.count() > 1:
            pks_viejas = list(notifs.values_list('pk', flat=True))[1:]
            Notificacion.objects.filter(pk__in=pks_viejas).delete()

    # Duplicados de productos (Margen de mercado)
    for prod_id in Notificacion.objects.filter(tipo='MERCADO', producto__isnull=False).values_list('producto_id', flat=True).distinct():
        notifs = Notificacion.objects.filter(tipo='MERCADO', producto_id=prod_id).order_by('-fecha_creacion')
        if notifs.count() > 1:
            pks_viejas = list(notifs.values_list('pk', flat=True))[1:]
            Notificacion.objects.filter(pk__in=pks_viejas).delete()


def verificar_y_generar_alertas_stock(request=None):
    """
    Revisa stock de insumos, productos y márgenes de rentabilidad de la panadería.
    """
    ahora = timezone.localtime()
    _limpiar_duplicados_existentes()

    # ------------------------------------------------------------------
    # 1. MATERIAS PRIMAS / INSUMOS (Stock Crítico)
    # ------------------------------------------------------------------
    insumos_criticos = Insumo.objects.filter(stock_sacos__lte=2)
    for insumo in insumos_criticos:
        existe_alerta = Notificacion.objects.filter(insumo=insumo, tipo='INSUMO').exists()
        if not existe_alerta:
            Notificacion.objects.create(
                tipo='INSUMO',
                titulo=f"Stock Crítico de Insumo: {insumo.nombre}",
                mensaje=f"Quedan solo {insumo.stock_sacos} sacos ({insumo.total_kg} kg) de {insumo.nombre}.",
                insumo=insumo,
                fecha_creacion=ahora,
                leida=False
            )
            if request:
                messages.warning(
                    request, 
                    f"Alerta, se ha detectado stock mínimo de {insumo.stock_sacos} sacos del insumo {insumo.nombre}"
                )

    insumos_sanos = Insumo.objects.filter(stock_sacos__gt=2)
    Notificacion.objects.filter(insumo__in=insumos_sanos, tipo='INSUMO').delete()

    # ------------------------------------------------------------------
    # 2. PRODUCTOS DE CATÁLOGO (Stock Mínimo)
    # ------------------------------------------------------------------
    productos_criticos = Producto.objects.filter(activo=True, stock__lte=F('stock_critico'))
    for prod in productos_criticos:
        existe_alerta = Notificacion.objects.filter(producto=prod, tipo='PRODUCTO').exists()
        if not existe_alerta:
            Notificacion.objects.create(
                tipo='PRODUCTO',
                titulo=f"Stock Mínimo en Catálogo: {prod.nombre}",
                mensaje=f"El producto {prod.nombre} ({prod.categoria.nombre}) ha alcanzado su nivel crítico con solo {prod.stock} {prod.unidad_medida} disponibles.",
                producto=prod,
                fecha_creacion=ahora,
                leida=False
            )
            if request:
                messages.warning(
                    request, 
                    f"Alerta, se ha detectado stock mínimo de {prod.stock} {prod.unidad_medida} del producto {prod.nombre}"
                )

    productos_sanos = Producto.objects.filter(activo=True, stock__gt=F('stock_critico'))
    Notificacion.objects.filter(producto__in=productos_sanos, tipo='PRODUCTO').delete()

    # ------------------------------------------------------------------
    # 3. MARGEN DE GANANCIA Y RENTABILIDAD (HU-EP002-005)
    # ------------------------------------------------------------------
    productos_activos = Producto.objects.filter(activo=True)
    for prod in productos_activos:
        # Verifica si el producto tiene costo y precio asignado para calcular el margen
        costo_prod = getattr(prod, 'costo', 0) or 0
        precio_prod = prod.precio or 0

        if precio_prod > 0 and costo_prod > 0:
            margen_actual = ((precio_prod - costo_prod) / precio_prod) * 100.0

            if margen_actual < MARGEN_MINIMO_DESEADO:
                existe_alerta = Notificacion.objects.filter(producto=prod, tipo='MERCADO').exists()
                if not existe_alerta:
                    Notificacion.objects.create(
                        tipo='MERCADO',
                        titulo=f"Bajo Margen de Ganancia: {prod.nombre}",
                        mensaje=f"El margen actual de {prod.nombre} cayó a {margen_actual:.1f}% (mínimo deseado: {MARGEN_MINIMO_DESEADO}%). Se sugiere revisar el precio de venta o costos de insumos.",
                        producto=prod,
                        fecha_creacion=ahora,
                        leida=False
                    )
                    if request:
                        messages.info(
                            request,
                            f"Alerta de Margen: El producto {prod.nombre} registra una rentabilidad reducida del {margen_actual:.1f}%"
                        )
            else:
                # Si el administrador ajustó el precio o bajó el costo de los insumos, se elimina la alerta
                Notificacion.objects.filter(producto=prod, tipo='MERCADO').delete()