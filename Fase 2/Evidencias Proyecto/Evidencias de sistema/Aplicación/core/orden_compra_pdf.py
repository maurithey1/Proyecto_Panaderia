"""
Módulo para la generación de la Orden de Compra formal en formato PDF (RQF9).
Utiliza ReportLab para emitir el documento institucional dirigido a molineras
y proveedores de materias primas.
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
    """Formatea un monto como pesos chilenos: 15000 -> $15.000"""
    try:
        entero = int(round(float(valor)))
    except (TypeError, ValueError):
        return str(valor)
    return '${:,}'.format(entero).replace(',', '.')


def generar_orden_compra_pdf(orden, tienda=None):
    """
    Genera el contenido binario (bytes) de un archivo PDF correspondiente a
    una orden de compra formal emitida a una molinera o proveedor (RQF9).
    """
    if tienda is None:
        tienda = TIENDA

    buffer = io.BytesIO()
    # Tamaño de página Carta (Letter) con márgenes estándar
    documento = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    estilos = getSampleStyleSheet()

    # Colores corporativos de la panadería
    color_primario = colors.HexColor('#4A2E18')     # Café oscuro
    color_secundario = colors.HexColor('#8C4E2E')   # Café cálido
    color_texto = colors.HexColor('#2D2825')        # Carbón
    color_suave = colors.HexColor('#6D645E')        # Gris cálido
    color_borde = colors.HexColor('#D9CBBF')        # Borde cálido
    color_fondo_total = colors.HexColor('#F8EFE4')  # Crema cálido
    color_fondo_proveedor = colors.HexColor('#FDFBF7')

    # Tipografías y estilos
    estilo_nombre_empresa = ParagraphStyle(
        'NombreEmpresaOC',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=color_primario,
    )
    estilo_datos_empresa = ParagraphStyle(
        'DatosEmpresaOC',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=color_suave,
    )
    estilo_titulo_oc = ParagraphStyle(
        'TituloOC',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        alignment=TA_RIGHT,
        textColor=color_primario,
    )
    estilo_subtitulo_oc = ParagraphStyle(
        'SubtituloOC',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=13,
        alignment=TA_RIGHT,
        textColor=color_secundario,
    )
    estilo_seccion = ParagraphStyle(
        'SeccionOC',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=color_primario,
    )
    estilo_lbl = ParagraphStyle(
        'LblOC',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=color_suave,
    )
    estilo_val = ParagraphStyle(
        'ValOC',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=color_texto,
    )
    estilo_th_izq = ParagraphStyle(
        'ThIzqOC',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
        alignment=TA_LEFT,
    )
    estilo_th_centro = ParagraphStyle(
        'ThCentroOC',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    estilo_th_der = ParagraphStyle(
        'ThDerOC',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
        alignment=TA_RIGHT,
    )
    estilo_td_izq = ParagraphStyle(
        'TdIzqOC',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=color_texto,
        alignment=TA_LEFT,
    )
    estilo_td_centro = ParagraphStyle(
        'TdCentroOC',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=color_texto,
        alignment=TA_CENTER,
    )
    estilo_td_der = ParagraphStyle(
        'TdDerOC',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=color_texto,
        alignment=TA_RIGHT,
    )
    estilo_pie = ParagraphStyle(
        'PieOC',
        parent=estilos['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=11,
        alignment=TA_CENTER,
        textColor=color_suave,
    )

    elementos = []

    # ---------------------------------------------------------
    # 1. Cabecera institucional
    # ---------------------------------------------------------
    nombre_empresa = tienda.get('nombre', 'Panadería Los Tres Spa')
    direccion_empresa = tienda.get('direccion', 'Avenida Principal 1234')
    comuna_empresa = tienda.get('comuna', 'Santiago')
    telefono_empresa = tienda.get('telefono', '+56 9 1234 5678')
    correo_empresa = tienda.get('correo', 'contacto@lostresspa.cl')

    try:
        fecha_emision_dt = timezone.localtime(orden.fecha_emision)
    except Exception:
        fecha_emision_dt = orden.fecha_emision
    fecha_emision_str = fecha_emision_dt.strftime('%d/%m/%Y')

    cabecera = [
        [
            Paragraph(f"<b>{html.escape(nombre_empresa)}</b>", estilo_nombre_empresa),
            Paragraph(f"<b>ORDEN DE COMPRA</b><br/><font size='10' color='#8C4E2E'>{html.escape(orden.codigo)}</font>", estilo_titulo_oc),
        ],
        [
            Paragraph(
                f"{html.escape(direccion_empresa)}, {html.escape(comuna_empresa)}<br/>"
                f"Teléfono: {html.escape(telefono_empresa)} | Correo: {html.escape(correo_empresa)}<br/>"
                f"Giro: Elaboración de productos de panadería y pastelería",
                estilo_datos_empresa,
            ),
            Paragraph(
                f"<b>Fecha de emisión:</b> {fecha_emision_str}<br/>"
                f"<b>Estado:</b> {html.escape(orden.get_estado_display())}",
                estilo_subtitulo_oc,
            ),
        ],
    ]
    tabla_cabecera = Table(cabecera, colWidths=[330, 210])
    tabla_cabecera.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elementos.append(tabla_cabecera)
    elementos.append(Spacer(1, 8))

    elementos.append(HRFlowable(width="100%", thickness=2, color=color_primario, spaceBefore=2, spaceAfter=12))

    # ---------------------------------------------------------
    # 2. Información del Proveedor / Molinera y Condiciones
    # ---------------------------------------------------------
    prov = orden.proveedor
    fecha_entrega_str = orden.fecha_entrega_esperada.strftime('%d/%m/%Y') if orden.fecha_entrega_esperada else "A convenir con proveedor"

    datos_proveedor_tabla = [
        [
            Paragraph("<b>DATOS DEL PROVEEDOR / MOLINERA</b>", estilo_seccion),
            "",
            Paragraph("<b>CONDICIONES DE LA ORDEN</b>", estilo_seccion),
            "",
        ],
        [
            Paragraph("Razón Social:", estilo_lbl),
            Paragraph(html.escape(prov.nombre_proveedor), estilo_val),
            Paragraph("Condiciones de pago:", estilo_lbl),
            Paragraph(html.escape(orden.condiciones_pago or "Transferencia"), estilo_val),
        ],
        [
            Paragraph("RUT Proveedor:", estilo_lbl),
            Paragraph(html.escape(prov.rut), estilo_val),
            Paragraph("Fecha entrega requerida:", estilo_lbl),
            Paragraph(html.escape(fecha_entrega_str), estilo_val),
        ],
        [
            Paragraph("Correo electrónico:", estilo_lbl),
            Paragraph(html.escape(orden.contacto_email or prov.email or "Sin correo"), estilo_val),
            Paragraph("Lugar de entrega:", estilo_lbl),
            Paragraph(f"{html.escape(direccion_empresa)}, {html.escape(comuna_empresa)}", estilo_val),
        ],
        [
            Paragraph("Teléfono de contacto:", estilo_lbl),
            Paragraph(html.escape(orden.contacto_telefono or prov.telefono or "Sin teléfono"), estilo_val),
            Paragraph("Contacto en molinera:", estilo_lbl),
            Paragraph(html.escape(orden.contacto_nombre or "Ventas / Despacho"), estilo_val),
        ],
    ]

    tabla_info = Table(datos_proveedor_tabla, colWidths=[110, 160, 120, 150])
    tabla_info.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('SPAN', (2, 0), (3, 0)),
        ('BACKGROUND', (0, 0), (-1, -1), color_fondo_proveedor),
        ('BOX', (0, 0), (-1, -1), 0.8, color_borde),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, 0), 1, color_borde),
    ]))
    elementos.append(tabla_info)
    elementos.append(Spacer(1, 14))

    # ---------------------------------------------------------
    # 3. Detalle de Materias Primas Solicitadas
    # ---------------------------------------------------------
    elementos.append(Paragraph("<b>DETALLE DE MATERIAS PRIMAS Y COTIZACIÓN</b>", estilo_seccion))
    elementos.append(Spacer(1, 4))

    filas_items = [
        [
            Paragraph("<b>Cód.</b>", estilo_th_izq),
            Paragraph("<b>Materia Prima / Insumo</b>", estilo_th_izq),
            Paragraph("<b>Sacos</b>", estilo_th_centro),
            Paragraph("<b>Kg / Saco</b>", estilo_th_centro),
            Paragraph("<b>Total Kg</b>", estilo_th_centro),
            Paragraph("<b>Precio Saco</b>", estilo_th_der),
            Paragraph("<b>Subtotal</b>", estilo_th_der),
        ]
    ]

    detalles = orden.detalles.all()
    for d in detalles:
        cod = d.insumo.codigo or str(d.insumo.pk)
        nom = d.insumo.nombre
        filas_items.append([
            Paragraph(html.escape(cod), estilo_td_izq),
            Paragraph(html.escape(nom), estilo_td_izq),
            Paragraph(str(d.cantidad_sacos), estilo_td_centro),
            Paragraph(f"{d.kilos_por_saco:.1f} kg", estilo_td_centro),
            Paragraph(f"{d.total_kilos:.1f} kg", estilo_td_centro),
            Paragraph(formatear_clp(d.precio_unitario), estilo_td_der),
            Paragraph(formatear_clp(d.subtotal), estilo_td_der),
        ])

    tabla_items = Table(filas_items, colWidths=[45, 175, 45, 60, 65, 75, 75])
    estilos_tabla = [
        ('BACKGROUND', (0, 0), (-1, 0), color_primario),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('BOX', (0, 0), (-1, -1), 0.8, color_borde),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, color_borde),
    ]

    # Filas alternadas
    for i in range(1, len(filas_items)):
        if i % 2 == 0:
            estilos_tabla.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FAF7F2')))

    tabla_items.setStyle(TableStyle(estilos_tabla))
    elementos.append(tabla_items)
    elementos.append(Spacer(1, 6))

    # ---------------------------------------------------------
    # 4. Resumen de Totales y Flete
    # ---------------------------------------------------------
    datos_totales = [
        [
            Paragraph("<b>Subtotal materias primas:</b>", ParagraphStyle('SubTotLbl', parent=estilo_lbl, alignment=TA_RIGHT)),
            Paragraph(formatear_clp(orden.subtotal), ParagraphStyle('SubTotVal', parent=estilo_val, alignment=TA_RIGHT, fontName='Helvetica-Bold')),
        ],
        [
            Paragraph("<b>Costo de flete / despacho:</b>", ParagraphStyle('FleteLbl', parent=estilo_lbl, alignment=TA_RIGHT)),
            Paragraph(formatear_clp(orden.costo_flete), ParagraphStyle('FleteVal', parent=estilo_val, alignment=TA_RIGHT)),
        ],
        [
            Paragraph("<b>TOTAL ORDEN DE COMPRA (CLP):</b>", ParagraphStyle('TotFinalLbl', parent=estilos['Normal'], fontName='Helvetica-Bold', fontSize=9.5, textColor=color_primario, alignment=TA_RIGHT)),
            Paragraph(f"<b>{formatear_clp(orden.total)}</b>", ParagraphStyle('TotFinalVal', parent=estilos['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=color_primario, alignment=TA_RIGHT)),
        ],
    ]
    tabla_totales = Table(datos_totales, colWidths=[420, 120])
    tabla_totales.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 2), (-1, 2), color_fondo_total),
        ('LINEABOVE', (0, 2), (-1, 2), 1, color_primario),
    ]))
    elementos.append(tabla_totales)
    elementos.append(Spacer(1, 14))

    # ---------------------------------------------------------
    # 5. Observaciones y Cláusulas
    # ---------------------------------------------------------
    if orden.observaciones:
        elementos.append(Paragraph("<b>OBSERVACIONES / REQUERIMIENTOS ESPECIALES</b>", estilo_seccion))
        elementos.append(Spacer(1, 2))
        elementos.append(Paragraph(html.escape(orden.observaciones), estilo_val))
        elementos.append(Spacer(1, 12))

    # Firmas
    admin_nombre = orden.administrador.get_full_name() if orden.administrador else "Administración Panadería"
    firmas = [
        [
            Paragraph(
                f"<br/><br/>_____________________________________<br/>"
                f"<b>Emitido por: {html.escape(admin_nombre)}</b><br/>"
                f"Administración General - Los Tres Spa",
                ParagraphStyle('FirmaAdmin', parent=estilo_val, alignment=TA_CENTER)
            ),
            Paragraph(
                f"<br/><br/>_____________________________________<br/>"
                f"<b>Recepción Molinera / Proveedor</b><br/>"
                f"Firma, Timbre y Fecha de Recepción",
                ParagraphStyle('FirmaProv', parent=estilo_val, alignment=TA_CENTER)
            ),
        ]
    ]
    tabla_firmas = Table(firmas, colWidths=[270, 270])
    tabla_firmas.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    elementos.append(tabla_firmas)
    elementos.append(Spacer(1, 14))

    # Pie de página
    elementos.append(HRFlowable(width="100%", thickness=0.6, color=color_borde, spaceBefore=4, spaceAfter=6))
    fecha_impresion = timezone.localtime(timezone.now()).strftime('%d/%m/%Y a las %H:%M')
    elementos.append(Paragraph(
        f"Documento emitido electrónicamente por el Sistema de Gestión Los Tres Spa el {fecha_impresion}. RQF9 - Generar orden de compra.",
        estilo_pie
    ))

    documento.build(elementos)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
