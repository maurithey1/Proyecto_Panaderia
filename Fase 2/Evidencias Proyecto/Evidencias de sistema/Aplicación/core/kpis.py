# Módulo de cálculo y análisis de Indicadores Clave de Rendimiento (KPIs)
# Proyecto Panadería Los Tres Spa
import json
from datetime import timedelta
from decimal import Decimal
from django.db.models import Sum, Count, Avg, F, Q
from django.utils import timezone

from .models import (
    Pedido, DetallePedido, Producto, Categoria, Insumo,
    CierreCaja, PuntosFidelizacion, Receta, IngredienteReceta,
    ProduccionDiaria, Proveedor, ProveedorInsumo, OrdenCompra
)


def _obtener_rango_fechas(periodo='mes', desde_str=None, hasta_str=None):
    """
    Calcula el rango de fechas actual y el período anterior comparable.
    Periodos admitidos: 'hoy', '7dias', 'mes' (últimos 30 días), 'mes_calendario', 'anio', 'todo'.
    """
    ahora = timezone.now()
    inicio_hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_hoy = ahora.replace(hour=23, minute=59, second=59, microsecond=999999)

    if periodo == 'hoy':
        inicio_actual = inicio_hoy
        fin_actual = ahora
        duracion = fin_actual - inicio_actual
        fin_previo = inicio_actual - timedelta(microseconds=1)
        inicio_previo = fin_previo - duracion
        nombre_periodo = 'Hoy'
    elif periodo == '7dias':
        inicio_actual = inicio_hoy - timedelta(days=6)
        fin_actual = ahora
        duracion = fin_actual - inicio_actual
        fin_previo = inicio_actual - timedelta(microseconds=1)
        inicio_previo = fin_previo - duracion
        nombre_periodo = 'Últimos 7 días'
    elif periodo == 'mes_calendario':
        inicio_actual = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fin_actual = ahora
        # Mes anterior
        ultimo_dia_mes_anterior = inicio_actual - timedelta(days=1)
        inicio_previo = ultimo_dia_mes_anterior.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fin_previo = ultimo_dia_mes_anterior.replace(hour=23, minute=59, second=59, microsecond=999999)
        nombre_periodo = 'Mes actual'
    elif periodo == 'anio':
        inicio_actual = ahora.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        fin_actual = ahora
        inicio_previo = inicio_actual.replace(year=inicio_actual.year - 1)
        fin_previo = fin_actual.replace(year=fin_actual.year - 1)
        nombre_periodo = 'Este año'
    elif periodo == 'personalizado' and desde_str and hasta_str:
        try:
            inicio_actual = timezone.datetime.strptime(desde_str, '%Y-%m-%d').replace(
                tzinfo=timezone.get_current_timezone()
            )
            fin_actual = timezone.datetime.strptime(hasta_str, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, microsecond=999999,
                tzinfo=timezone.get_current_timezone()
            )
            duracion = fin_actual - inicio_actual
            fin_previo = inicio_actual - timedelta(microseconds=1)
            inicio_previo = fin_previo - duracion
            nombre_periodo = f"{desde_str} al {hasta_str}"
        except Exception:
            inicio_actual = inicio_hoy - timedelta(days=29)
            fin_actual = ahora
            duracion = fin_actual - inicio_actual
            fin_previo = inicio_actual - timedelta(microseconds=1)
            inicio_previo = fin_previo - duracion
            nombre_periodo = 'Últimos 30 días'
    elif periodo == 'todo':
        inicio_actual = None
        fin_actual = ahora
        inicio_previo = None
        fin_previo = None
        nombre_periodo = 'Histórico completo'
    else:  # por defecto: últimos 30 días
        inicio_actual = inicio_hoy - timedelta(days=29)
        fin_actual = ahora
        duracion = fin_actual - inicio_actual
        fin_previo = inicio_actual - timedelta(microseconds=1)
        inicio_previo = fin_previo - duracion
        nombre_periodo = 'Últimos 30 días'

    return {
        'inicio_actual': inicio_actual,
        'fin_actual': fin_actual,
        'inicio_previo': inicio_previo,
        'fin_previo': fin_previo,
        'nombre_periodo': nombre_periodo,
        'clave_periodo': periodo,
    }


def calcular_metricas_kpi(periodo='mes', desde=None, hasta=None):
    """
    Calcula todos los indicadores clave de rendimiento (KPIs) agrupados por área.
    """
    rango = _obtener_rango_fechas(periodo, desde, hasta)
    inicio = rango['inicio_actual']
    fin = rango['fin_actual']
    inicio_prev = rango['inicio_previo']
    fin_prev = rango['fin_previo']

    # Filtro base para pedidos válidos (confirmados o en proceso)
    estados_validos = ['PAGADO', 'PREPARACION', 'LISTO', 'ENTREGADO']
    pedidos_qs = Pedido.objects.filter(estado__in=estados_validos)

    if inicio:
        pedidos_periodo = pedidos_qs.filter(fecha__gte=inicio, fecha__lte=fin)
    else:
        pedidos_periodo = pedidos_qs

    # ==========================================================
    # 1. KPIs DE VENTAS Y CANAL COMERCIAL
    # ==========================================================

    # A) Ingresos por ventas totales ($)
    total_ingresos = pedidos_periodo.aggregate(total=Sum('total'))['total'] or Decimal('0')

    # Período previo para calcular variación porcentual
    total_ingresos_prev = Decimal('0')
    if inicio_prev and fin_prev:
        total_ingresos_prev = pedidos_qs.filter(
            fecha__gte=inicio_prev, fecha__lte=fin_prev
        ).aggregate(total=Sum('total'))['total'] or Decimal('0')

    if total_ingresos_prev > 0:
        variacion_ingresos_pct = float(((total_ingresos - total_ingresos_prev) / total_ingresos_prev) * 100)
    elif total_ingresos > 0:
        variacion_ingresos_pct = 100.0
    else:
        variacion_ingresos_pct = 0.0

    # B) Volumen de transacciones (N°)
    volumen_transacciones = pedidos_periodo.count()
    volumen_prev = 0
    if inicio_prev and fin_prev:
        volumen_prev = pedidos_qs.filter(fecha__gte=inicio_prev, fecha__lte=fin_prev).count()

    if volumen_prev > 0:
        variacion_volumen_pct = round(((volumen_transacciones - volumen_prev) / volumen_prev) * 100, 1)
    else:
        variacion_volumen_pct = 0.0

    # C) Ticket promedio ($)
    if volumen_transacciones > 0:
        ticket_promedio = float(total_ingresos) / volumen_transacciones
    else:
        ticket_promedio = 0.0

    # D) Participación de ventas por canal (%): POS vs Web
    ventas_pos = pedidos_periodo.filter(canal='PRESENCIAL').aggregate(
        monto=Sum('total'), cantidad=Count('id')
    )
    monto_pos = float(ventas_pos['monto'] or 0)
    cant_pos = ventas_pos['cantidad'] or 0

    ventas_web = pedidos_periodo.filter(canal='WEB').aggregate(
        monto=Sum('total'), cantidad=Count('id')
    )
    monto_web = float(ventas_web['monto'] or 0)
    cant_web = ventas_web['cantidad'] or 0

    monto_total_canales = monto_pos + monto_web
    pct_pos = round((monto_pos / monto_total_canales * 100), 1) if monto_total_canales > 0 else 0.0
    pct_web = round((monto_web / monto_total_canales * 100), 1) if monto_total_canales > 0 else 0.0

    # E) Top 5 productos más vendidos ($ y cantidad)
    detalles_periodo = DetallePedido.objects.filter(pedido__in=pedidos_periodo)
    top_productos_query = detalles_periodo.values(
        'producto__nombre', 'producto__categoria__nombre'
    ).annotate(
        recaudacion=Sum('subtotal'),
        unidades=Sum('cantidad')
    ).order_by('-recaudacion')[:5]

    top_5_nombres = []
    top_5_montos = []
    top_5_unidades = []
    top_5_lista = []
    for item in top_productos_query:
        nombre = item['producto__nombre']
        monto = float(item['recaudacion'] or 0)
        unidades = int(item['unidades'] or 0)
        top_5_nombres.append(nombre)
        top_5_montos.append(monto)
        top_5_unidades.append(unidades)
        top_5_lista.append({
            'nombre': nombre,
            'categoria': item['producto__categoria__nombre'] or 'Sin categoría',
            'recaudacion': monto,
            'unidades': unidades,
        })

    # F) Ventas por categoría (%)
    ventas_categoria_query = detalles_periodo.values(
        'producto__categoria__nombre'
    ).annotate(
        recaudacion=Sum('subtotal')
    ).order_by('-recaudacion')

    categorias_nombres = []
    categorias_montos = []
    categorias_pct = []
    total_recaudacion_cat = sum(float(item['recaudacion'] or 0) for item in ventas_categoria_query)

    for item in ventas_categoria_query:
        cat_nom = item['producto__categoria__nombre'] or 'Otras categorías'
        monto = float(item['recaudacion'] or 0)
        pct = round((monto / total_recaudacion_cat * 100), 1) if total_recaudacion_cat > 0 else 0.0
        categorias_nombres.append(cat_nom)
        categorias_montos.append(monto)
        categorias_pct.append(pct)

    # G) Preferencia de entrega web (%): Retiro en local vs Despacho a domicilio (La Florida)
    pedidos_web_periodo = pedidos_periodo.filter(canal='WEB')
    cant_retiro = pedidos_web_periodo.filter(tipo_entrega='RETIRO').count()
    cant_despacho = pedidos_web_periodo.filter(tipo_entrega='DESPACHO').count()
    total_entregas_web = cant_retiro + cant_despacho

    pct_retiro = round((cant_retiro / total_entregas_web * 100), 1) if total_entregas_web > 0 else 0.0
    pct_despacho = round((cant_despacho / total_entregas_web * 100), 1) if total_entregas_web > 0 else 0.0

    # H) Evolución temporal de ingresos diarios (para gráfico de tendencia)
    # Genera serie cronológica de los últimos días del rango
    evolucion_dias_labels = []
    evolucion_dias_pos = []
    evolucion_dias_web = []

    # Agrupar por fecha si el rango tiene límites definidos
    dias_a_graficar = 14 if rango['clave_periodo'] == '7dias' else 30
    if inicio:
        fecha_cursor = inicio.date()
        fecha_tope = fin.date()
    else:
        fecha_cursor = (timezone.now() - timedelta(days=29)).date()
        fecha_tope = timezone.now().date()

    # Si el rango es mayor a 60 días, agrupamos semanalmente; si no, diario
    dias_totales = (fecha_tope - fecha_cursor).days + 1
    if dias_totales <= 31:
        cursor = fecha_cursor
        while cursor <= fecha_tope:
            label_dia = cursor.strftime('%d/%m')
            pedidos_dia = pedidos_periodo.filter(fecha__date=cursor)
            monto_pos_dia = float(pedidos_dia.filter(canal='PRESENCIAL').aggregate(s=Sum('total'))['s'] or 0)
            monto_web_dia = float(pedidos_dia.filter(canal='WEB').aggregate(s=Sum('total'))['s'] or 0)

            evolucion_dias_labels.append(label_dia)
            evolucion_dias_pos.append(monto_pos_dia)
            evolucion_dias_web.append(monto_web_dia)
            cursor += timedelta(days=1)
    else:
        # Muestra los últimos 15 días activos para mantener el gráfico legible
        cursor = fecha_tope - timedelta(days=14)
        while cursor <= fecha_tope:
            label_dia = cursor.strftime('%d/%m')
            pedidos_dia = pedidos_periodo.filter(fecha__date=cursor)
            monto_pos_dia = float(pedidos_dia.filter(canal='PRESENCIAL').aggregate(s=Sum('total'))['s'] or 0)
            monto_web_dia = float(pedidos_dia.filter(canal='WEB').aggregate(s=Sum('total'))['s'] or 0)

            evolucion_dias_labels.append(label_dia)
            evolucion_dias_pos.append(monto_pos_dia)
            evolucion_dias_web.append(monto_web_dia)
            cursor += timedelta(days=1)

    # ==========================================================
    # 2. KPIs DE CAJA Y FIDELIZACIÓN
    # ==========================================================

    # A) Exactitud de cuadratura de caja (%)
    cierres_qs = CierreCaja.objects.all()
    if inicio:
        cierres_periodo = cierres_qs.filter(fecha_cierre__gte=inicio, fecha_cierre__lte=fin)
    else:
        cierres_periodo = cierres_qs

    total_cierres = cierres_periodo.count()
    cierres_cuadrados = cierres_periodo.filter(diferencia=0).count()
    cierres_con_sobrante = cierres_periodo.filter(diferencia__gt=0).count()
    cierres_con_faltante = cierres_periodo.filter(diferencia__lt=0).count()

    diferencia_neta_acumulada = cierres_periodo.aggregate(d=Sum('diferencia'))['d'] or Decimal('0')
    porcentaje_cuadratura = round((cierres_cuadrados / total_cierres * 100), 1) if total_cierres > 0 else 100.0

    # B) Puntos de fidelización acumulados (pts)
    puntos_resumen = PuntosFidelizacion.objects.aggregate(
        total_puntos=Sum('puntos_acumulados'),
        promedio_puntos=Avg('puntos_acumulados'),
        total_cuentas=Count('id')
    )
    total_puntos_vigentes = puntos_resumen['total_puntos'] or 0
    promedio_puntos_cliente = round(puntos_resumen['promedio_puntos'] or 0, 1)
    clientes_con_puntos = puntos_resumen['total_cuentas'] or 0

    # ==========================================================
    # 3. KPIs DE INVENTARIO, PRODUCCIÓN Y COSTOS
    # ==========================================================

    # A) Alertas de stock crítico (N°)
    productos_criticos = Producto.objects.filter(activo=True, stock__lte=F('stock_critico'))
    insumos_criticos = Insumo.objects.filter(stock_actual__lte=F('stock_minimo'))
    total_alertas_stock = productos_criticos.count() + insumos_criticos.count()

    # B) Margen bruto por producto (%)
    # Calculamos el costo por receta de cada producto que tenga receta asociada
    recetas = Receta.objects.select_related('producto').prefetch_related('ingredientes__insumo').all()
    lista_margenes = []
    margenes_nombres = []
    margenes_porcentajes = []
    margenes_precios = []
    margenes_costos = []

    for rec in recetas:
        prod = rec.producto
        if not prod.activo or prod.precio <= 0:
            continue

        costo_receta = Decimal('0')
        for ing in rec.ingredientes.all():
            costo_ingrediente = ing.cantidad * (ing.insumo.precio_unitario or Decimal('0'))
            costo_receta += costo_ingrediente

        ganancia_bruta = prod.precio - costo_receta
        margen_pct = round(((ganancia_bruta / prod.precio) * 100), 1) if prod.precio > 0 else Decimal('0')

        item_margen = {
            'producto': prod.nombre,
            'precio_venta': float(prod.precio),
            'costo_elaboracion': float(costo_receta),
            'ganancia_bruta': float(ganancia_bruta),
            'margen_porcentaje': float(margen_pct),
        }
        lista_margenes.append(item_margen)

    # Ordenar por mayor margen porcentual y tomar los más representativos
    lista_margenes.sort(key=lambda x: x['margen_porcentaje'], reverse=True)
    for m in lista_margenes[:8]:
        margenes_nombres.append(m['producto'])
        margenes_porcentajes.append(m['margen_porcentaje'])
        margenes_precios.append(m['precio_venta'])
        margenes_costos.append(m['costo_elaboracion'])

    # C) Costo total de adquisición por molinera ($)
    # Suma de precio del saco de harina / insumo más costo de flete por cada proveedor/molinera
    proveedores_qs = Proveedor.objects.all().prefetch_related('insumos')
    molineras_nombres = []
    molineras_costo_saco = []
    molineras_costo_flete = []
    molineras_costo_total = []
    tabla_molineras = []

    for prov in proveedores_qs:
        flete = float(prov.costo_flete or 0)
        tarifas = ProveedorInsumo.objects.filter(proveedor=prov)
        if tarifas.exists():
            promedio_saco = float(tarifas.aggregate(avg=Avg('precio_ofrecido'))['avg'] or 0)
        else:
            promedio_saco = 0.0

        costo_adquisicion = promedio_saco + flete
        molineras_nombres.append(prov.nombre_proveedor)
        molineras_costo_saco.append(promedio_saco)
        molineras_costo_flete.append(flete)
        molineras_costo_total.append(costo_adquisicion)
        tabla_molineras.append({
            'proveedor': prov.nombre_proveedor,
            'rut': prov.rut,
            'costo_flete': flete,
            'promedio_saco': promedio_saco,
            'costo_total_adquisicion': costo_adquisicion,
        })

    # D) Producción diaria horneada (kg / unid)
    produccion_qs = ProduccionDiaria.objects.all()
    if inicio:
        produccion_periodo = produccion_qs.filter(
            fecha_produccion__gte=inicio, fecha_produccion__lte=fin
        )
    else:
        produccion_periodo = produccion_qs

    total_unidades_horneadas = produccion_periodo.aggregate(t=Sum('cantidad'))['t'] or 0

    # Agrupación de producción por fecha
    produccion_dias_labels = []
    produccion_dias_cantidades = []

    dias_prod_cursor = fecha_tope - timedelta(days=13)
    while dias_prod_cursor <= fecha_tope:
        label = dias_prod_cursor.strftime('%d/%m')
        cant = produccion_qs.filter(fecha_produccion__date=dias_prod_cursor).aggregate(
            t=Sum('cantidad')
        )['t'] or 0
        produccion_dias_labels.append(label)
        produccion_dias_cantidades.append(int(cant))
        dias_prod_cursor += timedelta(days=1)

    # ==========================================================
    # SERIALIZACIÓN JSON PARA CHART.JS
    # ==========================================================
    datos_graficos_json = json.dumps({
        # 1. Ventas e ingresos temporales
        'evolucion_labels': evolucion_dias_labels,
        'evolucion_pos': evolucion_dias_pos,
        'evolucion_web': evolucion_dias_web,

        # 2. Canales
        'canales_labels': ['POS (Presencial)', 'E-commerce (Webpay)'],
        'canales_montos': [monto_pos, monto_web],
        'canales_pct': [pct_pos, pct_web],

        # 3. Top 5 productos
        'top5_nombres': top_5_nombres,
        'top5_montos': top_5_montos,
        'top5_unidades': top_5_unidades,

        # 4. Categorías
        'categorias_nombres': categorias_nombres,
        'categorias_montos': categorias_montos,
        'categorias_pct': categorias_pct,

        # 5. Entrega web
        'entrega_labels': ['Retiro en Local', 'Despacho a Domicilio'],
        'entrega_cantidades': [cant_retiro, cant_despacho],
        'entrega_pct': [pct_retiro, pct_despacho],

        # 6. Margen bruto
        'margenes_nombres': margenes_nombres,
        'margenes_pct': margenes_porcentajes,
        'margenes_precios': margenes_precios,
        'margenes_costos': margenes_costos,

        # 7. Molineras
        'molineras_nombres': molineras_nombres,
        'molineras_saco': molineras_costo_saco,
        'molineras_flete': molineras_costo_flete,
        'molineras_total': molineras_costo_total,

        # 8. Producción
        'produccion_labels': produccion_dias_labels,
        'produccion_cantidades': produccion_dias_cantidades,
    })

    return {
        # Rango
        'rango': rango,

        # Ventas y Canal Comercial
        'total_ingresos': float(total_ingresos),
        'total_ingresos_prev': float(total_ingresos_prev),
        'variacion_ingresos_pct': round(variacion_ingresos_pct, 1),
        'volumen_transacciones': volumen_transacciones,
        'variacion_volumen_pct': variacion_volumen_pct,
        'ticket_promedio': round(ticket_promedio, 0),
        'monto_pos': monto_pos,
        'cant_pos': cant_pos,
        'pct_pos': pct_pos,
        'monto_web': monto_web,
        'cant_web': cant_web,
        'pct_web': pct_web,
        'top_5_lista': top_5_lista,
        'cant_retiro': cant_retiro,
        'cant_despacho': cant_despacho,
        'pct_retiro': pct_retiro,
        'pct_despacho': pct_despacho,

        # Caja y Fidelización
        'total_cierres': total_cierres,
        'cierres_cuadrados': cierres_cuadrados,
        'cierres_con_sobrante': cierres_con_sobrante,
        'cierres_con_faltante': cierres_con_faltante,
        'porcentaje_cuadratura': porcentaje_cuadratura,
        'diferencia_neta_acumulada': float(diferencia_neta_acumulada),
        'total_puntos_vigentes': total_puntos_vigentes,
        'promedio_puntos_cliente': promedio_puntos_cliente,
        'clientes_con_puntos': clientes_con_puntos,

        # Inventario, Producción y Costos
        'total_alertas_stock': total_alertas_stock,
        'productos_criticos': list(productos_criticos[:6]),
        'insumos_criticos': list(insumos_criticos[:6]),
        'total_unidades_horneadas': total_unidades_horneadas,
        'lista_margenes': lista_margenes,
        'tabla_molineras': tabla_molineras,

        # Datos JSON para JavaScript
        'datos_graficos_json': datos_graficos_json,
    }


def obtener_graficos_inicio_admin():
    """
    Calcula los datos para los dos gráficos interactivos de la pantalla principal de administración:
    1. Comparativa de ventas por semana (Mes anterior vs Mes actual).
    2. Evolución y tendencia de ventas diarias (Últimos 14 días).
    """
    ahora = timezone.now()
    nombres_meses = [
        'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
    ]

    # Mes actual
    inicio_mes_actual = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nombre_mes_actual = nombres_meses[ahora.month - 1]

    # Mes anterior
    fin_mes_anterior = inicio_mes_actual - timedelta(microseconds=1)
    inicio_mes_anterior = fin_mes_anterior.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nombre_mes_anterior = nombres_meses[fin_mes_anterior.month - 1]

    estados_validos = ['PAGADO', 'PREPARACION', 'LISTO', 'ENTREGADO']
    pedidos_qs = Pedido.objects.filter(estado__in=estados_validos)

    # 1. Gráfico de Barras: Comparativa en 4 semanas
    semanas_labels = ['Semana 1', 'Semana 2', 'Semana 3', 'Semana 4']
    ventas_mes_anterior_semanas = [0, 0, 0, 0]
    ventas_mes_actual_semanas = [0, 0, 0, 0]

    # Agrupar mes anterior por 4 semanas de 7 días
    for i in range(4):
        d_ini = inicio_mes_anterior + timedelta(days=i * 7)
        d_fin = min(inicio_mes_anterior + timedelta(days=(i + 1) * 7 - 1, hours=23, minutes=59), fin_mes_anterior)
        total = pedidos_qs.filter(fecha__gte=d_ini, fecha__lte=d_fin).aggregate(s=Sum('total'))['s'] or 0
        ventas_mes_anterior_semanas[i] = float(total)

    # Agrupar mes actual por 4 semanas de 7 días
    for i in range(4):
        d_ini = inicio_mes_actual + timedelta(days=i * 7)
        if d_ini > ahora:
            ventas_mes_actual_semanas[i] = 0
            continue
        d_fin = min(inicio_mes_actual + timedelta(days=(i + 1) * 7 - 1, hours=23, minutes=59), ahora)
        total = pedidos_qs.filter(fecha__gte=d_ini, fecha__lte=d_fin).aggregate(s=Sum('total'))['s'] or 0
        ventas_mes_actual_semanas[i] = float(total)

    # 2. Gráfico de Líneas: Evolución de los últimos 14 días
    dias_labels = []
    tendencia_pos = []
    tendencia_web = []

    cursor = (ahora - timedelta(days=13)).date()
    hoy = ahora.date()
    while cursor <= hoy:
        label = cursor.strftime('%d/%m')
        pedidos_dia = pedidos_qs.filter(fecha__date=cursor)
        monto_pos = float(pedidos_dia.filter(canal='PRESENCIAL').aggregate(s=Sum('total'))['s'] or 0)
        monto_web = float(pedidos_dia.filter(canal='WEB').aggregate(s=Sum('total'))['s'] or 0)

        dias_labels.append(label)
        tendencia_pos.append(monto_pos)
        tendencia_web.append(monto_web)
        cursor += timedelta(days=1)

    json_graficos_inicio = json.dumps({
        'nombre_mes_anterior': nombre_mes_anterior,
        'nombre_mes_actual': nombre_mes_actual,
        'semanas_labels': semanas_labels,
        'ventas_mes_anterior': ventas_mes_anterior_semanas,
        'ventas_mes_actual': ventas_mes_actual_semanas,
        'dias_labels': dias_labels,
        'tendencia_pos': tendencia_pos,
        'tendencia_web': tendencia_web,
    })

    return {
        'nombre_mes_anterior': nombre_mes_anterior,
        'nombre_mes_actual': nombre_mes_actual,
        'json_graficos_inicio': json_graficos_inicio,
    }


def detalle_kpi(tipo, valor, periodo='mes', desde=None, hasta=None):
    """
    Detalle de ventas para un elemento marcado en los gráficos del dashboard.

    `tipo` puede ser 'canal' (PRESENCIAL o WEB), 'producto' (nombre) o 'categoria' (nombre).
    Usa los detalles de venta (DetallePedido) de los pedidos válidos del período seleccionado.
    Devuelve None si el tipo no es válido.
    """
    rango = _obtener_rango_fechas(periodo, desde, hasta)
    inicio, fin = rango['inicio_actual'], rango['fin_actual']

    estados_validos = ['PAGADO', 'PREPARACION', 'LISTO', 'ENTREGADO']
    pedidos = Pedido.objects.filter(estado__in=estados_validos)
    if inicio:
        pedidos = pedidos.filter(fecha__gte=inicio, fecha__lte=fin)

    detalles = DetallePedido.objects.filter(pedido__in=pedidos)
    if tipo == 'canal':
        if valor not in ('PRESENCIAL', 'WEB'):
            return None
        detalles = detalles.filter(pedido__canal=valor)
        titulo = 'POS (Presencial)' if valor == 'PRESENCIAL' else 'E-commerce (Webpay)'
        agrupar, etiqueta = 'producto__nombre', 'Producto'
    elif tipo == 'categoria':
        if valor == 'Sin categoría':
            detalles = detalles.filter(producto__categoria__isnull=True)
        else:
            detalles = detalles.filter(producto__categoria__nombre=valor)
        titulo = valor
        agrupar, etiqueta = 'producto__nombre', 'Producto'
    elif tipo == 'producto':
        detalles = detalles.filter(producto__nombre=valor)
        titulo = valor
        agrupar, etiqueta = 'pedido__canal', 'Canal'
    else:
        return None

    total = detalles.aggregate(monto=Sum('subtotal'), unidades=Sum('cantidad'))
    nombres_canal = {'PRESENCIAL': 'POS (Presencial)', 'WEB': 'E-commerce (Webpay)'}
    filas = []
    for fila in detalles.values(agrupar).annotate(
        monto=Sum('subtotal'), unidades=Sum('cantidad')
    ).order_by('-monto')[:15]:
        nombre = fila[agrupar] or 'Sin nombre'
        filas.append({
            'nombre': nombres_canal.get(nombre, nombre),
            'unidades': int(fila['unidades'] or 0),
            'monto': float(fila['monto'] or 0),
        })

    ids_pedidos = detalles.values_list('pedido_id', flat=True).distinct()
    recientes = []
    for pedido in Pedido.objects.filter(id__in=ids_pedidos).order_by('-fecha')[:8]:
        recientes.append({
            'id': pedido.id,
            'fecha': timezone.localtime(pedido.fecha).strftime('%d/%m/%Y %H:%M'),
            'canal': nombres_canal.get(pedido.canal, pedido.canal),
            'total': float(pedido.total),
        })

    return {
        'tipo': tipo,
        'titulo': titulo,
        'etiqueta_filas': etiqueta,
        'periodo': rango['nombre_periodo'],
        'total_monto': float(total['monto'] or 0),
        'total_unidades': int(total['unidades'] or 0),
        'total_pedidos': len(ids_pedidos),
        'filas': filas,
        'pedidos_recientes': recientes,
    }

def graficos_adquisicion():
    """
    Datos de los gráficos de adquisición (órdenes de compra a molineras):
    gasto por molinera, órdenes por estado y gasto por materia prima.
    Las órdenes canceladas no cuentan como gasto.
    """
    from .models import OrdenCompra, DetalleOrdenCompra

    validas = OrdenCompra.objects.exclude(estado='CANCELADA')

    por_proveedor = list(
        validas.values('proveedor__nombre_proveedor')
        .annotate(monto=Sum('total'), ordenes=Count('id')).order_by('-monto')
    )
    nombres_estado = dict(OrdenCompra.ESTADOS)
    por_estado = list(OrdenCompra.objects.values('estado').annotate(ordenes=Count('id')).order_by('-ordenes'))
    por_insumo = list(
        DetalleOrdenCompra.objects.filter(orden__in=validas)
        .values('insumo__nombre').annotate(monto=Sum('subtotal'), kilos=Sum('total_kilos'))
        .order_by('-monto')[:8]
    )

    return {
        'proveedores_nombres': [f['proveedor__nombre_proveedor'] for f in por_proveedor],
        'proveedores_montos': [float(f['monto'] or 0) for f in por_proveedor],
        'estados_claves': [f['estado'] for f in por_estado],
        'estados_nombres': [nombres_estado.get(f['estado'], f['estado']) for f in por_estado],
        'estados_cantidades': [f['ordenes'] for f in por_estado],
        'insumos_nombres': [f['insumo__nombre'] for f in por_insumo],
        'insumos_montos': [float(f['monto'] or 0) for f in por_insumo],
        'total_gastado': float(validas.aggregate(t=Sum('total'))['t'] or 0),
        'total_ordenes': OrdenCompra.objects.count(),
    }


def detalle_adquisicion(tipo, valor):
    """
    Detalle de las órdenes de compra de una molinera, un estado o una materia prima marcados
    en los gráficos. Devuelve None si el tipo no es válido.
    """
    from .models import OrdenCompra, DetalleOrdenCompra

    ordenes = OrdenCompra.objects.select_related('proveedor')
    nombres_estado = dict(OrdenCompra.ESTADOS)
    if tipo == 'proveedor':
        ordenes = ordenes.filter(proveedor__nombre_proveedor=valor).exclude(estado='CANCELADA')
        titulo = valor
    elif tipo == 'estado':
        if valor not in nombres_estado:
            return None
        ordenes = ordenes.filter(estado=valor)
        titulo = nombres_estado[valor]
    elif tipo == 'insumo':
        ordenes = ordenes.filter(detalles__insumo__nombre=valor).exclude(estado='CANCELADA').distinct()
        titulo = valor
    else:
        return None

    renglones = DetalleOrdenCompra.objects.filter(orden__in=ordenes)
    if tipo == 'insumo':
        renglones = renglones.filter(insumo__nombre=valor)
    totales = renglones.aggregate(monto=Sum('subtotal'), kilos=Sum('total_kilos'))

    lista = []
    for orden in ordenes.order_by('-fecha_emision')[:10]:
        lista.append({
            'codigo': orden.codigo,
            'fecha': timezone.localtime(orden.fecha_emision).strftime('%d/%m/%Y'),
            'proveedor': orden.proveedor.nombre_proveedor,
            'estado': nombres_estado.get(orden.estado, orden.estado),
            'total': float(orden.total or 0),
        })

    materias = [
        {
            'nombre': f['insumo__nombre'],
            'kilos': float(f['kilos'] or 0),
            'monto': float(f['monto'] or 0),
        }
        for f in renglones.values('insumo__nombre').annotate(
            monto=Sum('subtotal'), kilos=Sum('total_kilos')).order_by('-monto')[:10]
    ]

    return {
        'tipo': tipo,
        'titulo': titulo,
        'total_ordenes': ordenes.count(),
        'total_monto': float(totales['monto'] or 0),
        'total_kilos': float(totales['kilos'] or 0),
        'materias': materias,
        'ordenes': lista,
    }