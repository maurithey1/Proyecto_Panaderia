# ==============================================================================
# Módulo de Generación de Reportes en Microsoft Excel (.xlsx)
# Proyecto Panadería Los Tres SpA
# ==============================================================================
import io
from datetime import datetime
from decimal import Decimal
from django.utils import timezone
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .models import Pedido, DetallePedido, OrdenCompra
from . import kpis as metricas_kpi


# Paleta de colores oficial de Panadería Los Tres SpA para Excel
COLORES = {
    'banner_bg': '7B4B2A',         # Café artesanal profundo
    'banner_sub_bg': 'F5EFE6',     # Crema institucional
    'encabezado_ventas': '107C41', # Verde esmeralda Excel / ejecutivo
    'encabezado_items': 'B4532A',  # Terracota artesanal
    'encabezado_kpis': '3E2A1D',   # Café oscuro
    'fila_par': 'FAF6F0',          # Crema muy sutil
    'fila_impar': 'FFFFFF',        # Blanco puro
    'totales_bg': 'EBD9C1',        # Trigo suave contable
    'texto_blanco': 'FFFFFF',
    'texto_oscuro': '2A1C12',
    'texto_suave': '6E5848',
    'borde_gris': 'D6C6B2',
    'borde_oscuro': '8D5B4C',
    # Estados de pedidos
    'estado_pagado_bg': 'E8F5E9',
    'estado_pagado_txt': '1E6B37',
    'estado_pendiente_bg': 'FFF8E1',
    'estado_pendiente_txt': '8A5300',
    'estado_cancelado_bg': 'FFEBEE',
    'estado_cancelado_txt': 'B71C1C',
}


def _crear_bordes(estilo_sup='thin', estilo_inf='thin', color='D6C6B2'):
    """Genera una estructura de bordes estándar para celdas."""
    lado_sup = Side(style=estilo_sup, color=color) if estilo_sup else Side(style=None)
    lado_inf = Side(style=estilo_inf, color=color) if estilo_inf else Side(style=None)
    lado_lat = Side(style='thin', color=color)
    return Border(top=lado_sup, bottom=lado_inf, left=lado_lat, right=lado_lat)


def _ajustar_anchos(ws, max_ancho=50, min_ancho=12):
    """Calcula y aplica el ancho óptimo para cada columna según el largo de sus celdas."""
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            # Omitimos filas combinadas del banner superior (filas 1 a 3) para no descalibrar el ancho
            if cell.row in [1, 2, 3]:
                continue
            val = str(cell.value or '')
            if '\n' in val:
                val = max(val.split('\n'), key=len)
            max_len = max(max_len, len(val))
        ancho = max(min(max_len + 4, max_ancho), min_ancho)
        ws.column_dimensions[col_letter].width = ancho


def generar_libro_excel_kpis(periodo='todo', desde=None, hasta=None):
    """
    Genera un archivo Excel (.xlsx) estructurado, con diseño profesional,
    múltiples hojas de trabajo, autofiltros y formato de moneda nativo.
    """
    wb = openpyxl.Workbook()

    # Rango y filtros
    rango = metricas_kpi._obtener_rango_fechas(periodo, desde, hasta)
    inicio = rango.get('inicio_actual')
    fin = rango.get('fin_actual')

    pedidos_qs = Pedido.objects.all()
    if inicio and fin:
        pedidos_qs = pedidos_qs.filter(fecha__gte=inicio, fecha__lte=fin)
    pedidos_qs = pedidos_qs.order_by('id')

    pedidos_lista = list(
        pedidos_qs
        .select_related('cliente', 'cliente__user', 'cajero', 'cajero__user', 'pago')
        .prefetch_related('detalles', 'detalles__producto', 'detalles__producto__categoria')
    )

    fecha_emision = timezone.now().astimezone(timezone.get_current_timezone()).strftime('%d/%m/%Y %H:%M')

    # ==========================================================================
    # HOJA 1: RESUMEN DE VENTAS Y TRANSACCIONES
    # ==========================================================================
    ws1 = wb.active
    ws1.title = "Ventas y Pedidos"
    ws1.views.sheetView[0].showGridLines = True

    # 1. Banner Institucional
    ws1.merge_cells('A1:Q1')
    celda_titulo = ws1['A1']
    celda_titulo.value = "PANADERÍA LOS TRES SPA — REPORTE DE VENTAS Y TRANSACCIONES"
    celda_titulo.font = Font(name='Segoe UI', size=13, bold=True, color=COLORES['texto_blanco'])
    celda_titulo.fill = PatternFill(start_color=COLORES['banner_bg'], end_color=COLORES['banner_bg'], fill_type='solid')
    celda_titulo.alignment = Alignment(horizontal='center', vertical='center')
    ws1.row_dimensions[1].height = 34

    ws1.merge_cells('A2:Q2')
    celda_sub = ws1['A2']
    celda_sub.value = f"Período evaluado: {rango.get('nombre_periodo', 'Histórico completo')}   |   Fecha de emisión: {fecha_emision}   |   Sistema de Control Gerencial"
    celda_sub.font = Font(name='Segoe UI', size=9.5, italic=True, color=COLORES['texto_suave'])
    celda_sub.fill = PatternFill(start_color=COLORES['banner_sub_bg'], end_color=COLORES['banner_sub_bg'], fill_type='solid')
    celda_sub.alignment = Alignment(horizontal='center', vertical='center')
    ws1.row_dimensions[2].height = 22

    ws1.row_dimensions[3].height = 8

    # 2. Encabezados de Tabla
    encabezados_ws1 = [
        ('N° Pedido', 11, 'center'),
        ('Fecha y Hora', 19, 'center'),
        ('Canal de Venta', 18, 'center'),
        ('Estado Pedido', 16, 'center'),
        ('Modalidad Entrega', 18, 'center'),
        ('Dirección / Franja', 28, 'left'),
        ('Cliente', 24, 'left'),
        ('RUT Cliente', 14, 'center'),
        ('Correo Electrónico', 24, 'left'),
        ('Teléfono', 14, 'center'),
        ('Cajero Responsable', 20, 'left'),
        ('Medio de Pago', 18, 'center'),
        ('Estado Pago', 14, 'center'),
        ('Código Comprobante', 24, 'center'),
        ('Unidades', 12, 'center'),
        ('Productos Comprados', 36, 'left'),
        ('Total Venta ($ CLP)', 20, 'right'),
    ]

    fila_encabezado = 4
    ws1.row_dimensions[fila_encabezado].height = 26

    for col_idx, (titulo, ancho_sugerido, alig) in enumerate(encabezados_ws1, start=1):
        c = ws1.cell(row=fila_encabezado, column=col_idx, value=titulo)
        c.font = Font(name='Segoe UI', size=10, bold=True, color=COLORES['texto_blanco'])
        c.fill = PatternFill(start_color=COLORES['encabezado_ventas'], end_color=COLORES['encabezado_ventas'], fill_type='solid')
        c.alignment = Alignment(horizontal=alig, vertical='center', wrap_text=False)
        c.border = _crear_bordes(estilo_sup='medium', estilo_inf='medium', color='0B4F28')

    # 3. Filas de Datos
    fila_actual = 5
    borde_datos = _crear_bordes(estilo_sup='thin', estilo_inf='thin', color=COLORES['borde_gris'])

    for p in pedidos_lista:
        pago = getattr(p, 'pago', None)

        cliente_nombre = 'Venta Mostrador (Público General)'
        cliente_rut = 'Sin RUT'
        cliente_email = 'N/A'
        cliente_telefono = 'N/A'
        if p.cliente:
            if p.cliente.user:
                cliente_nombre = p.cliente.user.get_full_name() or p.cliente.user.username
                cliente_email = p.cliente.user.email or 'N/A'
                cliente_rut = getattr(p.cliente.user, 'rut', None) or getattr(p.cliente, 'rut', 'Sin RUT')
            cliente_telefono = getattr(p.cliente, 'telefono', None) or 'N/A'

        cajero_nombre = 'Sistema Web'
        if p.cajero and p.cajero.user:
            cajero_nombre = p.cajero.user.get_full_name() or p.cajero.user.username

        metodo_pago = pago.metodo if pago else 'Sin registro'
        estado_pago = pago.estado if pago else 'N/A'
        codigo_auth = (pago.codigo_autorizacion if pago and pago.codigo_autorizacion else 'N/A')

        detalles_list = list(p.detalles.all())
        unidades_pedido = sum(d.cantidad for d in detalles_list)
        desglose_items = ' | '.join(
            [f"{d.producto.nombre} ({d.cantidad} un. - ${int(d.subtotal):,} CLP)".replace(',', '.') for d in detalles_list]
        ) if detalles_list else 'Sin ítems'

        fecha_str = p.fecha.astimezone(timezone.get_current_timezone()).strftime('%Y-%m-%d %H:%M:%S')

        # Color alterno cebra
        color_fila = COLORES['fila_par'] if fila_actual % 2 == 0 else COLORES['fila_impar']
        fill_fila = PatternFill(start_color=color_fila, end_color=color_fila, fill_type='solid')

        valores_fila = [
            (p.id, 'center', None),
            (fecha_str, 'center', None),
            (p.get_canal_display(), 'center', None),
            (p.get_estado_display(), 'center', None),
            (p.get_tipo_entrega_display(), 'center', None),
            (p.direccion_despacho or 'Retiro en local', 'left', None),
            (cliente_nombre, 'left', None),
            (cliente_rut, 'center', None),
            (cliente_email, 'left', None),
            (cliente_telefono, 'center', None),
            (cajero_nombre, 'left', None),
            (metodo_pago, 'center', None),
            (estado_pago, 'center', None),
            (codigo_auth, 'center', None),
            (unidades_pedido, 'center', '#,##0'),
            (desglose_items, 'left', None),
            (int(p.total), 'right', '"$"#,##0'),
        ]

        ws1.row_dimensions[fila_actual].height = 20

        for col_idx, (val, alig, fmt) in enumerate(valores_fila, start=1):
            celda = ws1.cell(row=fila_actual, column=col_idx, value=val)
            celda.font = Font(name='Segoe UI', size=9.5, color=COLORES['texto_oscuro'])
            celda.fill = fill_fila
            celda.alignment = Alignment(horizontal=alig, vertical='center')
            celda.border = borde_datos
            if fmt:
                celda.number_format = fmt

        # Estilo de badge condicional en la celda de estado
        celda_estado = ws1.cell(row=fila_actual, column=4)
        if p.estado in ['PAGADO', 'LISTO', 'ENTREGADO']:
            celda_estado.fill = PatternFill(start_color=COLORES['estado_pagado_bg'], end_color=COLORES['estado_pagado_bg'], fill_type='solid')
            celda_estado.font = Font(name='Segoe UI', size=9.5, bold=True, color=COLORES['estado_pagado_txt'])
        elif p.estado in ['CANCELADO']:
            celda_estado.fill = PatternFill(start_color=COLORES['estado_cancelado_bg'], end_color=COLORES['estado_cancelado_bg'], fill_type='solid')
            celda_estado.font = Font(name='Segoe UI', size=9.5, bold=True, color=COLORES['estado_cancelado_txt'])
        else:
            celda_estado.fill = PatternFill(start_color=COLORES['estado_pendiente_bg'], end_color=COLORES['estado_pendiente_bg'], fill_type='solid')
            celda_estado.font = Font(name='Segoe UI', size=9.5, bold=True, color=COLORES['estado_pendiente_txt'])

        fila_actual += 1

    # 4. Fila Final de Totales Contables
    fila_totales = fila_actual
    ws1.row_dimensions[fila_totales].height = 24
    borde_totales = Border(
        top=Side(style='thin', color='7B4B2A'),
        bottom=Side(style='double', color='7B4B2A'),
        left=Side(style='thin', color=COLORES['borde_gris']),
        right=Side(style='thin', color=COLORES['borde_gris'])
    )
    fill_totales = PatternFill(start_color=COLORES['totales_bg'], end_color=COLORES['totales_bg'], fill_type='solid')

    for c_idx in range(1, 18):
        cel = ws1.cell(row=fila_totales, column=c_idx)
        cel.fill = fill_totales
        cel.border = borde_totales
        cel.font = Font(name='Segoe UI', size=10, bold=True, color=COLORES['texto_oscuro'])

    ws1.cell(row=fila_totales, column=1, value="TOTALES")
    ws1.cell(row=fila_totales, column=1).alignment = Alignment(horizontal='center', vertical='center')

    ws1.cell(row=fila_totales, column=2, value=f"{len(pedidos_lista)} transacciones")
    ws1.cell(row=fila_totales, column=2).alignment = Alignment(horizontal='center', vertical='center')

    # Suma de Unidades
    if pedidos_lista:
        cel_uds = ws1.cell(row=fila_totales, column=15)
        cel_uds.value = f"=SUM(O5:O{fila_totales - 1})"
        cel_uds.alignment = Alignment(horizontal='center', vertical='center')
        cel_uds.number_format = '#,##0'

        # Suma de Facturación
        cel_tot = ws1.cell(row=fila_totales, column=17)
        cel_tot.value = f"=SUM(Q5:Q{fila_totales - 1})"
        cel_tot.alignment = Alignment(horizontal='right', vertical='center')
        cel_tot.number_format = '"$"#,##0'

    # Activar Autofiltro de Excel en toda la tabla
    ws1.auto_filter.ref = f"A4:Q{fila_totales - 1}"

    # Aplicar anchos óptimos
    _ajustar_anchos(ws1)


    # ==========================================================================
    # HOJA 2: DETALLE ÍTEM POR ÍTEM (TABLA RELACIONAL)
    # ==========================================================================
    ws2 = wb.create_sheet(title="Detalle por Ítem")
    ws2.views.sheetView[0].showGridLines = True

    ws2.merge_cells('A1:N1')
    celda_tit2 = ws2['A1']
    celda_tit2.value = "PANADERÍA LOS TRES SPA — DETALLE NORMALIZADO POR PRODUCTO"
    celda_tit2.font = Font(name='Segoe UI', size=13, bold=True, color=COLORES['texto_blanco'])
    celda_tit2.fill = PatternFill(start_color=COLORES['encabezado_items'], end_color=COLORES['encabezado_items'], fill_type='solid')
    celda_tit2.alignment = Alignment(horizontal='center', vertical='center')
    ws2.row_dimensions[1].height = 34

    ws2.merge_cells('A2:N2')
    celda_sub2 = ws2['A2']
    celda_sub2.value = f"Desglose ítem por ítem   |   Período: {rango.get('nombre_periodo', 'Histórico completo')}   |   Emisión: {fecha_emision}"
    celda_sub2.font = Font(name='Segoe UI', size=9.5, italic=True, color=COLORES['texto_suave'])
    celda_sub2.fill = PatternFill(start_color=COLORES['banner_sub_bg'], end_color=COLORES['banner_sub_bg'], fill_type='solid')
    celda_sub2.alignment = Alignment(horizontal='center', vertical='center')
    ws2.row_dimensions[2].height = 22

    ws2.row_dimensions[3].height = 8

    encabezados_ws2 = [
        ('N° Detalle', 'center'),
        ('N° Pedido', 'center'),
        ('Fecha y Hora', 'center'),
        ('Canal de Venta', 'center'),
        ('Estado Pedido', 'center'),
        ('Cód. Producto', 'center'),
        ('Nombre del Producto', 'left'),
        ('Categoría', 'center'),
        ('Unidades', 'center'),
        ('Precio Unitario ($ CLP)', 'right'),
        ('Subtotal Ítem ($ CLP)', 'right'),
        ('Total Pedido ($ CLP)', 'right'),
        ('Modalidad Entrega', 'center'),
        ('Cliente', 'left'),
    ]

    ws2.row_dimensions[4].height = 26
    for c_idx, (tit, alig) in enumerate(encabezados_ws2, start=1):
        cel = ws2.cell(row=4, column=c_idx, value=tit)
        cel.font = Font(name='Segoe UI', size=10, bold=True, color=COLORES['texto_blanco'])
        cel.fill = PatternFill(start_color=COLORES['encabezado_items'], end_color=COLORES['encabezado_items'], fill_type='solid')
        cel.alignment = Alignment(horizontal=alig, vertical='center')
        cel.border = _crear_bordes(estilo_sup='medium', estilo_inf='medium', color='8D3613')

    detalles_qs = (
        DetallePedido.objects.filter(pedido__in=pedidos_qs)
        .select_related(
            'pedido', 'pedido__cliente', 'pedido__cliente__user',
            'producto', 'producto__categoria'
        )
        .order_by('pedido__id', 'id')
    )

    fila_d = 5
    for det in detalles_qs:
        ped = det.pedido
        cliente_nom = 'Venta Mostrador'
        if ped.cliente and ped.cliente.user:
            cliente_nom = ped.cliente.user.get_full_name() or ped.cliente.user.username

        cat_nom = det.producto.categoria.nombre if det.producto.categoria else 'Sin Categoría'
        f_str = ped.fecha.astimezone(timezone.get_current_timezone()).strftime('%Y-%m-%d %H:%M:%S')

        c_fondo = COLORES['fila_par'] if fila_d % 2 == 0 else COLORES['fila_impar']
        p_fill = PatternFill(start_color=c_fondo, end_color=c_fondo, fill_type='solid')

        ws2.row_dimensions[fila_d].height = 20

        valores_d = [
            (det.id, 'center', None),
            (ped.id, 'center', None),
            (f_str, 'center', None),
            (ped.get_canal_display(), 'center', None),
            (ped.get_estado_display(), 'center', None),
            (det.producto.id, 'center', None),
            (det.producto.nombre, 'left', None),
            (cat_nom, 'center', None),
            (det.cantidad, 'center', '#,##0'),
            (int(det.precio_unitario), 'right', '"$"#,##0'),
            (int(det.subtotal), 'right', '"$"#,##0'),
            (int(ped.total), 'right', '"$"#,##0'),
            (ped.get_tipo_entrega_display(), 'center', None),
            (cliente_nom, 'left', None),
        ]

        for col_idx, (v, al, f_num) in enumerate(valores_d, start=1):
            c_d = ws2.cell(row=fila_d, column=col_idx, value=v)
            c_d.font = Font(name='Segoe UI', size=9.5, color=COLORES['texto_oscuro'])
            c_d.fill = p_fill
            c_d.alignment = Alignment(horizontal=al, vertical='center')
            c_d.border = borde_datos
            if f_num:
                c_d.number_format = f_num

        fila_d += 1

    # Totales hoja 2
    ws2.row_dimensions[fila_d].height = 24
    for c_idx in range(1, 15):
        c_tot2 = ws2.cell(row=fila_d, column=c_idx)
        c_tot2.fill = fill_totales
        c_tot2.border = borde_totales
        c_tot2.font = Font(name='Segoe UI', size=10, bold=True, color=COLORES['texto_oscuro'])

    ws2.cell(row=fila_d, column=1, value="TOTALES")
    ws2.cell(row=fila_d, column=1).alignment = Alignment(horizontal='center', vertical='center')
    ws2.cell(row=fila_d, column=2, value=f"{detalles_qs.count()} ítems")
    ws2.cell(row=fila_d, column=2).alignment = Alignment(horizontal='center', vertical='center')

    if detalles_qs.exists():
        c_uds2 = ws2.cell(row=fila_d, column=9)
        c_uds2.value = f"=SUM(I5:I{fila_d - 1})"
        c_uds2.alignment = Alignment(horizontal='center', vertical='center')
        c_uds2.number_format = '#,##0'

        c_sub2 = ws2.cell(row=fila_d, column=11)
        c_sub2.value = f"=SUM(K5:K{fila_d - 1})"
        c_sub2.alignment = Alignment(horizontal='right', vertical='center')
        c_sub2.number_format = '"$"#,##0'

    ws2.auto_filter.ref = f"A4:N{fila_d - 1}"
    _ajustar_anchos(ws2)


    # ==========================================================================
    # HOJA 3: TABLERO GERENCIAL Y KPIS
    # ==========================================================================
    ws3 = wb.create_sheet(title="Métricas y KPIs")
    ws3.views.sheetView[0].showGridLines = True

    ws3.merge_cells('A1:G1')
    c_kpi_tit = ws3['A1']
    c_kpi_tit.value = "PANADERÍA LOS TRES SPA — RESUMEN EJECUTIVO DE KPIS"
    c_kpi_tit.font = Font(name='Segoe UI', size=13, bold=True, color=COLORES['texto_blanco'])
    c_kpi_tit.fill = PatternFill(start_color=COLORES['encabezado_kpis'], end_color=COLORES['encabezado_kpis'], fill_type='solid')
    c_kpi_tit.alignment = Alignment(horizontal='center', vertical='center')
    ws3.row_dimensions[1].height = 34

    ws3.merge_cells('A2:G2')
    c_kpi_sub = ws3['A2']
    c_kpi_sub.value = f"Indicadores Clave de Rendimiento   |   Período: {rango.get('nombre_periodo', 'Histórico completo')}"
    c_kpi_sub.font = Font(name='Segoe UI', size=9.5, italic=True, color=COLORES['texto_suave'])
    c_kpi_sub.fill = PatternFill(start_color=COLORES['banner_sub_bg'], end_color=COLORES['banner_sub_bg'], fill_type='solid')
    c_kpi_sub.alignment = Alignment(horizontal='center', vertical='center')
    ws3.row_dimensions[2].height = 22

    # Cálculos KPIs
    datos_kpi = metricas_kpi.calcular_metricas_kpi(periodo, desde, hasta)

    # Tabla 1: Indicadores Globales
    ws3.cell(row=4, column=1, value="1. Indicadores Globales de Ventas").font = Font(name='Segoe UI', size=11, bold=True, color='7B4B2A')
    ws3.cell(row=5, column=1, value="Métrica").font = Font(name='Segoe UI', size=9.5, bold=True, color='FFFFFF')
    ws3.cell(row=5, column=1).fill = PatternFill(start_color='7B4B2A', end_color='7B4B2A', fill_type='solid')
    ws3.cell(row=5, column=2, value="Valor").font = Font(name='Segoe UI', size=9.5, bold=True, color='FFFFFF')
    ws3.cell(row=5, column=2).fill = PatternFill(start_color='7B4B2A', end_color='7B4B2A', fill_type='solid')

    metricas_globales = [
        ("Ingresos Totales por Ventas", int(datos_kpi.get('total_ingresos', 0)), '"$"#,##0'),
        ("Volumen de Transacciones", datos_kpi.get('volumen_transacciones', 0), '#,##0'),
        ("Ticket Promedio por Pedido", int(datos_kpi.get('ticket_promedio', 0)), '"$"#,##0'),
        ("Ventas Canal POS (Presencial)", int(datos_kpi.get('monto_pos', 0)), '"$"#,##0'),
        ("Participación POS (%)", f"{datos_kpi.get('pct_pos', 0)}%", None),
        ("Ventas Canal Web (E-commerce)", int(datos_kpi.get('monto_web', 0)), '"$"#,##0'),
        ("Participación Web (%)", f"{datos_kpi.get('pct_web', 0)}%", None),
        ("Exactitud Cuadratura de Caja", f"{datos_kpi.get('porcentaje_cuadratura', 0)}%", None),
        ("Diferencia Neta en Caja", int(datos_kpi.get('diferencia_neta_acumulada', 0)), '"$"#,##0'),
    ]

    r_idx = 6
    for nom_m, val_m, fmt_m in metricas_globales:
        c1 = ws3.cell(row=r_idx, column=1, value=nom_m)
        c2 = ws3.cell(row=r_idx, column=2, value=val_m)
        c1.font = Font(name='Segoe UI', size=9.5)
        c2.font = Font(name='Segoe UI', size=9.5, bold=True)
        c1.border = borde_datos
        c2.border = borde_datos
        if fmt_m:
            c2.number_format = fmt_m
        c2.alignment = Alignment(horizontal='right' if fmt_m else 'center')
        r_idx += 1

    # Tabla 2: Top 5 Productos más Vendidos
    ws3.cell(row=4, column=4, value="2. Ranking Top 5 Productos Más Vendidos").font = Font(name='Segoe UI', size=11, bold=True, color='B4532A')
    encab_top = [('Ranking', 'center'), ('Producto', 'left'), ('Categoría', 'center'), ('Recaudación ($)', 'right')]
    for idx_t, (t_nom, t_al) in enumerate(encab_top, start=4):
        c_th = ws3.cell(row=5, column=idx_t, value=t_nom)
        c_th.font = Font(name='Segoe UI', size=9.5, bold=True, color='FFFFFF')
        c_th.fill = PatternFill(start_color='B4532A', end_color='B4532A', fill_type='solid')
        c_th.alignment = Alignment(horizontal=t_al, vertical='center')

    top_lista = datos_kpi.get('top_5_lista', [])
    r_top = 6
    for idx_p, prod in enumerate(top_lista, start=1):
        ws3.cell(row=r_top, column=4, value=f"#{idx_p}").alignment = Alignment(horizontal='center')
        ws3.cell(row=r_top, column=5, value=prod.get('nombre', ''))
        ws3.cell(row=r_top, column=6, value=prod.get('categoria', '')).alignment = Alignment(horizontal='center')
        c_dinero = ws3.cell(row=r_top, column=7, value=int(prod.get('recaudacion', 0)))
        c_dinero.number_format = '"$"#,##0'
        c_dinero.alignment = Alignment(horizontal='right')

        for c_t in range(4, 8):
            ws3.cell(row=r_top, column=c_t).border = borde_datos
            ws3.cell(row=r_top, column=c_t).font = Font(name='Segoe UI', size=9.5)
        r_top += 1

    _ajustar_anchos(ws3)

    # Retornar los bytes en memoria
    salida = io.BytesIO()
    wb.save(salida)
    salida.seek(0)
    return salida.getvalue()
