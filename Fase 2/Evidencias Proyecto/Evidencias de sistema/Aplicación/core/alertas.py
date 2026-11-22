from django.db.models import F
from django.utils import timezone
from django.contrib import messages
from .models import Insumo, Producto, Notificacion
from .recetas import detalle_costo

# Umbral de rentabilidad mínima deseada para los productos (30%)
MARGEN_MINIMO_DESEADO = 30.0


def verificar_y_generar_alertas_stock(request=None):
    """
    Revisa todo el inventario (Insumos y Productos) y evalúa márgenes de rentabilidad
    según recetas para generar o limpiar alertas automáticamente.
    Si recibe un 'request', también emite notificaciones tipo 'toast/messages' en tiempo real.
    """
    ahora = timezone.now()

    # ------------------------------------------------------------------
    # 1. MATERIAS PRIMAS / INSUMOS (Stock Crítico)
    # ------------------------------------------------------------------
    insumos_criticos = Insumo.objects.filter(stock_actual__lte=F('stock_minimo'))
    ids_insumos_criticos = list(insumos_criticos.values_list('id', flat=True))

    # Limpia las alertas de insumos que ya fueron repuestos por encima del mínimo
    Notificacion.objects.filter(tipo='INSUMO', insumo__isnull=False).exclude(
        insumo_id__in=ids_insumos_criticos
    ).delete()

    for insumo in insumos_criticos:
        existe_alerta = Notificacion.objects.filter(insumo=insumo, tipo='INSUMO').exists()
        if not existe_alerta:
            Notificacion.objects.create(
                tipo='INSUMO',
                titulo=f"Stock Crítico: {insumo.nombre}",
                mensaje=(
                    f"El insumo {insumo.nombre} ({insumo.codigo}) ha bajado a "
                    f"{insumo.stock_actual} {insumo.unidad}. El mínimo es {insumo.stock_minimo}."
                ),
                insumo=insumo,
                fecha_creacion=ahora,
                leida=False
            )
            if request:
                messages.warning(
                    request,
                    f"Alerta de Inventario: {insumo.nombre} en nivel crítico ({insumo.stock_actual} {insumo.unidad})"
                )

    # ------------------------------------------------------------------
    # 2. PRODUCTOS DE CATÁLOGO (Stock Crítico)
    # ------------------------------------------------------------------
    productos_criticos = Producto.objects.filter(activo=True, stock__lte=F('stock_critico'))
    ids_prod_criticos = list(productos_criticos.values_list('id', flat=True))

    # Limpia alertas de productos que ya tienen stock saludable
    Notificacion.objects.filter(tipo='PRODUCTO').exclude(producto_id__in=ids_prod_criticos).delete()

    for prod in productos_criticos:
        existe_alerta = Notificacion.objects.filter(producto=prod, tipo='PRODUCTO').exists()
        if not existe_alerta:
            Notificacion.objects.create(
                tipo='PRODUCTO',
                titulo=f"Stock Bajo en Vitrina: {prod.nombre}",
                mensaje=(
                    f"Quedan solo {prod.stock} {prod.unidad_medida} de {prod.nombre} "
                    f"(Mínimo configurado: {prod.stock_critico})."
                ),
                producto=prod,
                fecha_creacion=ahora,
                leida=False
            )
            if request:
                messages.warning(
                    request,
                    f"Alerta de Producto: Queda poco stock de {prod.nombre} ({prod.stock} {prod.unidad_medida})"
                )

    # ------------------------------------------------------------------
    # 3. MARGEN DE GANANCIA Y RENTABILIDAD (HU-EP002-005 / CP-036)
    # ------------------------------------------------------------------
    productos_activos = Producto.objects.filter(activo=True)
    ids_prod_bajo_margen = []

    for prod in productos_activos:
        detalle = detalle_costo(prod)
        costo_prod = detalle['costo']
        margen_actual = detalle['margen']

        # Solo evalúa productos que tengan precio, receta con ingredientes y margen calculable
        if prod.precio > 0 and costo_prod > 0 and margen_actual is not None:
            margen_val = float(margen_actual)

            if margen_val < MARGEN_MINIMO_DESEADO:
                ids_prod_bajo_margen.append(prod.id)
                alerta_actual = Notificacion.objects.filter(producto=prod, tipo='MERCADO').first()
                costo_fmt = f"${costo_prod:,.0f}".replace(',', '.')
                mensaje_alerta = (
                    f"El margen neto de {prod.nombre} cayó a {margen_val:.1f}% "
                    f"(mínimo deseado: {MARGEN_MINIMO_DESEADO:.0f}%). "
                    f"Costo de elaboración: {costo_fmt}. Se sugiere revisar el precio de venta o costos de insumos."
                )

                if not alerta_actual:
                    Notificacion.objects.create(
                        tipo='MERCADO',
                        titulo=f"Bajo Margen de Ganancia: {prod.nombre}",
                        mensaje=mensaje_alerta,
                        producto=prod,
                        fecha_creacion=ahora,
                        leida=False
                    )
                    if request:
                        messages.warning(
                            request,
                            f"Alerta de Margen: El producto {prod.nombre} registra una rentabilidad reducida del {margen_val:.1f}%"
                        )
                elif alerta_actual.mensaje != mensaje_alerta:
                    # Solo reactiva la campana y lanza el toast si el costo o el margen realmente cambiaron
                    alerta_actual.mensaje = mensaje_alerta
                    alerta_actual.fecha_creacion = ahora
                    alerta_actual.leida = False
                    alerta_actual.save(update_fields=['mensaje', 'fecha_creacion', 'leida'])
                    if request:
                        messages.warning(
                            request,
                            f"Alerta de Margen: El producto {prod.nombre} registra una rentabilidad reducida del {margen_val:.1f}%"
                        )

    # Limpia alertas de margen de productos que recuperaron rentabilidad o quedaron sin receta/inactivos
    Notificacion.objects.filter(tipo='MERCADO').exclude(producto_id__in=ids_prod_bajo_margen).delete()