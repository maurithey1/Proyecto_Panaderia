"""
Módulo para la generación del comprobante de venta o compra simulada en formato PDF.
Utiliza ReportLab para crear un documento con diseño formal y coherente con la identidad visual.
"""

import html
import io
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .templatetags.tienda import TIENDA


def formatear_clp(valor):
    """Formatea un monto como pesos chilenos: 1200 -> $1.200"""
    try:
        entero = int(round(float(valor)))
    except (TypeError, ValueError):
        return str(valor)
    return '${:,}'.format(entero).replace(',', '.')


def generar_comprobante_pdf(pedido, tienda=None):
    """
    Genera el contenido binario (bytes) de un archivo PDF correspondiente al
    comprobante de un pedido o compra de demostración.
    """
    if tienda is None:
        tienda = TIENDA

    buffer = io.BytesIO()
    # Configuración de márgenes y tamaño de página (Carta / Letter)
    documento = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=36,
        bottomMargin=36,
    )

    estilos = getSampleStyleSheet()

    # Colores institucionales de la panadería
    color_primario = colors.HexColor('#4A2E18')     # Café oscuro
    color_secundario = colors.HexColor('#8C4E2E')   # Café cálido
    color_texto = colors.HexColor('#2D2825')        # Carbón suave
    color_suave = colors.HexColor('#6D645E')        # Gris cálido
    color_borde = colors.HexColor('#E2D8CD')        # Borde sutil
    color_fondo_total = colors.HexColor('#F7EFE4')  # Crema suave
    color_aviso_fondo = colors.HexColor('#FEF8EE')  # Fondo advertencia
    color_aviso_borde = colors.HexColor('#E8D7BE')  # Borde advertencia
    color_aviso_texto = colors.HexColor('#7A5B28')  # Texto advertencia

    # Estilos de párrafos tipográficos
    estilo_nombre_tienda = ParagraphStyle(
        'NombreTienda',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=color_primario,
    )
    estilo_subtitulo_tienda = ParagraphStyle(
        'SubtituloTienda',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=color_suave,
    )
    estilo_titulo_boleta = ParagraphStyle(
        'TituloBoleta',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=color_primario,
    )
    estilo_estado_demostracion = ParagraphStyle(
        'EstadoDemostracion',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=color_secundario,
    )
    estilo_aviso_legal = ParagraphStyle(
        'AvisoLegal',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
        textColor=color_aviso_texto,
    )
    estilo_etiqueta_meta = ParagraphStyle(
        'EtiquetaMeta',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=color_suave,
    )
    estilo_valor_meta = ParagraphStyle(
        'ValorMeta',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=color_texto,
    )
    estilo_th_izq = ParagraphStyle(
        'ThIzq',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.white,
        alignment=TA_LEFT,
    )
    estilo_th_centro = ParagraphStyle(
        'ThCentro',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    estilo_th_der = ParagraphStyle(
        'ThDer',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.white,
        alignment=TA_RIGHT,
    )
    estilo_td_izq = ParagraphStyle(
        'TdIzq',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=color_texto,
        alignment=TA_LEFT,
    )
    estilo_td_centro = ParagraphStyle(
        'TdCentro',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=color_texto,
        alignment=TA_CENTER,
    )
    estilo_td_der = ParagraphStyle(
        'TdDer',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=color_texto,
        alignment=TA_RIGHT,
    )
    estilo_total_label = ParagraphStyle(
        'TotalLabel',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=color_primario,
        alignment=TA_LEFT,
    )
    estilo_total_monto = ParagraphStyle(
        'TotalMonto',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=color_primario,
        alignment=TA_RIGHT,
    )
    estilo_pie = ParagraphStyle(
        'PiePagina',
        parent=estilos['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=11,
        textColor=color_suave,
        alignment=TA_CENTER,
    )

    elementos = []

    # 1. Encabezado de la tienda
    nombre_tienda = tienda.get('nombre', 'Panadería Los Tres Spa')
    direccion_tienda = tienda.get('direccion', '')
    comuna_tienda = tienda.get('comuna', '')
    telefono_tienda = tienda.get('telefono', '')
    correo_tienda = tienda.get('correo', '')

    datos_cabecera = [
        [
            Paragraph(f"<b>{html.escape(nombre_tienda)}</b>", estilo_nombre_tienda),
            Paragraph(
                f"<b>Comprobante N° {pedido.pk}</b><br/>"
                f"<font size='8' color='#6D645E'>Pedido #{pedido.pk}</font>",
                ParagraphStyle('NumComp', parent=estilo_titulo_boleta, alignment=TA_RIGHT),
            ),
        ],
        [
            Paragraph(
                f"{html.escape(direccion_tienda)}, {html.escape(comuna_tienda)}<br/>"
                f"Teléfono: {html.escape(telefono_tienda)} | Correo: {html.escape(correo_tienda)}",
                estilo_subtitulo_tienda,
            ),
            Paragraph("Comprobante de compra", estilo_estado_demostracion),
        ],
    ]
    tabla_cabecera = Table(datos_cabecera, colWidths=[332, 200])
    tabla_cabecera.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('ALIGN', (1, 1), (1, 1), 'RIGHT'),
    ]))
    elementos.append(tabla_cabecera)
    elementos.append(Spacer(1, 10))

    # Línea decorativa
    elementos.append(HRFlowable(width="100%", thickness=1.5, color=color_primario, spaceBefore=4, spaceAfter=14))

    # Metadatos del pedido
    try:
        fecha_dt = timezone.localtime(pedido.fecha)
    except Exception:
        fecha_dt = pedido.fecha
    fecha_formateada = fecha_dt.strftime('%d/%m/%Y %H:%M')

    metodo_pago_texto = pedido.pago.metodo if (hasattr(pedido, 'pago') and pedido.pago and pedido.pago.metodo) else "Confirmado"

    filas_meta = [
        [
            Paragraph("Número de pedido", estilo_etiqueta_meta),
            Paragraph(f"#{pedido.pk}", estilo_valor_meta),
            Paragraph("Fecha de emisión", estilo_etiqueta_meta),
            Paragraph(fecha_formateada, estilo_valor_meta),
        ],
        [
            Paragraph("Estado del pedido", estilo_etiqueta_meta),
            Paragraph(html.escape(pedido.get_estado_display()), estilo_valor_meta),
            Paragraph("Tipo de entrega", estilo_etiqueta_meta),
            Paragraph(html.escape(pedido.get_tipo_entrega_display()), estilo_valor_meta),
        ],
    ]

    # Información de retiro o despacho
    if pedido.tipo_entrega == 'RETIRO':
        lugar_retiro = f"{direccion_tienda}, {comuna_tienda}"
        filas_meta.append([
            Paragraph("Retiro en", estilo_etiqueta_meta),
            Paragraph(html.escape(lugar_retiro), estilo_valor_meta),
            Paragraph("Método de pago", estilo_etiqueta_meta),
            Paragraph(html.escape(metodo_pago_texto), estilo_valor_meta),
        ])
        if pedido.direccion_despacho:
            horario_retiro = pedido.direccion_despacho.replace('Retiro programado: ', '')
            filas_meta.append([
                Paragraph("Retiro programado", estilo_etiqueta_meta),
                Paragraph(html.escape(horario_retiro), estilo_valor_meta),
                Paragraph("", estilo_etiqueta_meta),
                Paragraph("", estilo_valor_meta),
            ])
    else:
        filas_meta.append([
            Paragraph("Dirección de despacho", estilo_etiqueta_meta),
            Paragraph(html.escape(pedido.direccion_despacho or 'No especificada'), estilo_valor_meta),
            Paragraph("Método de pago", estilo_etiqueta_meta),
            Paragraph(html.escape(metodo_pago_texto), estilo_valor_meta),
        ])

    if pedido.cliente and getattr(pedido.cliente, 'user', None):
        nombre_cliente = pedido.cliente.user.get_full_name() or pedido.cliente.user.username
        filas_meta.append([
            Paragraph("Cliente", estilo_etiqueta_meta),
            Paragraph(html.escape(nombre_cliente), estilo_valor_meta),
            Paragraph("", estilo_etiqueta_meta),
            Paragraph("", estilo_valor_meta),
        ])

    tabla_meta = Table(filas_meta, colWidths=[120, 160, 100, 152])
    tabla_meta.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#F2ECE4')),
    ]))
    elementos.append(tabla_meta)
    elementos.append(Spacer(1, 14))

    # 4. Tabla de detalles del pedido
    filas_tabla = [
        [
            Paragraph("<b>Producto</b>", estilo_th_izq),
            Paragraph("<b>Cantidad</b>", estilo_th_centro),
            Paragraph("<b>Precio unitario</b>", estilo_th_der),
            Paragraph("<b>Subtotal</b>", estilo_th_der),
        ]
    ]

    for detalle in pedido.detalles.all():
        nombre_prod = detalle.producto.nombre if detalle.producto else "Producto"
        filas_tabla.append([
            Paragraph(html.escape(nombre_prod), estilo_td_izq),
            Paragraph(str(detalle.cantidad), estilo_td_centro),
            Paragraph(formatear_clp(detalle.precio_unitario), estilo_td_der),
            Paragraph(formatear_clp(detalle.subtotal), estilo_td_der),
        ])

    # Fila de Total
    total_idx = len(filas_tabla)
    filas_tabla.append([
        Paragraph("<b>Total</b>", estilo_total_label),
        "",
        "",
        Paragraph(f"<b>{formatear_clp(pedido.total)}</b>", estilo_total_monto),
    ])

    tabla_productos = Table(filas_tabla, colWidths=[262, 60, 105, 105])
    estilo_tabla_prod = [
        ('BACKGROUND', (0, 0), (-1, 0), color_primario),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        # Fila de total
        ('SPAN', (0, total_idx), (2, total_idx)),
        ('BACKGROUND', (0, total_idx), (-1, total_idx), color_fondo_total),
        ('LINEABOVE', (0, total_idx), (-1, total_idx), 1, color_borde),
        ('BOX', (0, 0), (-1, -1), 1, color_borde),
        ('INNERGRID', (0, 0), (-1, total_idx - 1), 0.5, color_borde),
    ]

    # Fondo alternado en filas de productos
    for i in range(1, total_idx):
        if i % 2 == 0:
            estilo_tabla_prod.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FAF7F2')))

    tabla_productos.setStyle(TableStyle(estilo_tabla_prod))
    elementos.append(tabla_productos)
    elementos.append(Spacer(1, 24))

    # 5. Pie de página y agradecimiento
    elementos.append(HRFlowable(width="100%", thickness=0.8, color=color_borde, spaceBefore=4, spaceAfter=10))
    elementos.append(Paragraph(
        f"¡Gracias por su preferencia! - {html.escape(nombre_tienda)}",
        estilo_pie
    ))
    elementos.append(Spacer(1, 4))
    fecha_generacion = timezone.localtime(timezone.now()).strftime('%d/%m/%Y a las %H:%M')
    elementos.append(Paragraph(
        f"Documento generado el {fecha_generacion} a través del sistema web.",
        ParagraphStyle('FechaGen', parent=estilo_pie, fontSize=7, textColor=colors.HexColor('#999999'))
    ))

    documento.build(elementos)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
