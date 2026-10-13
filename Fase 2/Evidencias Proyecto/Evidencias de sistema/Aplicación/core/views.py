import re
import time
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, F, IntegerField, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import Http404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from transbank.webpay.webpay_plus.transaction import Transaction
from transbank.common.integration_type import IntegrationType
from .webpay import obtener_transaccion_webpay, TIPOS_PAGO_WEBPAY
from .models import (
    Categoria, Cliente, Cajero, DetallePedido, Insumo, Pago, Pedido, Producto,
    ProveedorInsumo, PuntosFidelizacion, Turno, Usuario, Administrador
)
from .templatetags.tienda import TIENDA
from django.http import JsonResponse
from .templatetags.formato import clp
from .disponibilidad import esta_disponible, resumen as resumen_de_disponibilidad
from .retiro import ahora as ahora_en_chile, dias_de_retiro, texto_retiro, validar_retiro
from .zona_despacho import leer_coordenadas, punto_en_zona

# ==========================================
# FUNCIONES DE CLIENTE: CATÁLOGO, CARRITO Y COMPRA
# ==========================================
# Todo sale de la base de datos (modelo Producto). El archivo productos_prueba.json
# solo sirve para cargar datos iniciales:  python manage.py cargar_productos

PRODUCTOS_DESTACADOS = 4


def _entero_o_none(valor):
    """Convierte a int sin lanzar error: devuelve None si no es un número válido o es enorme."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero.bit_length() <= 63 else None


def _turnos_activos():
    """Precarga los turnos activos de cada producto (para mostrar cuándo se vende)."""
    return Prefetch('turnos', queryset=Turno.objects.filter(activo=True))


def inicio(request):
    """Los 4 productos más vendidos (pedidos no cancelados), leídos de la BD."""
    _expirar_pedidos_webpay_vencidos()  # el stock que se muestra no debe incluir pagos abandonados
    estados_validos = [estado for estado, _ in Pedido.ESTADOS if estado != 'CANCELADO']

    productos = (
        Producto.objects.filter(activo=True)
        .prefetch_related(_turnos_activos())
        .annotate(
            vendidos=Coalesce(
                Sum(
                    'detallepedido__cantidad',
                    filter=Q(detallepedido__pedido__estado__in=estados_validos),
                ),
                0,
            )
        )
        .order_by('-vendidos', 'nombre')[:PRODUCTOS_DESTACADOS]
    )

    return render(request, 'core/inicio.html', {'productos': productos})


BUSQUEDA_MAX_LARGO = 80
BUSQUEDA_MAX_PALABRAS = 6


def _sin_tildes(texto):
    """Minúsculas y sin tildes ('Berlinés' -> 'berlines'), para buscar como escribe la gente."""
    descompuesto = unicodedata.normalize('NFD', texto)
    return ''.join(c for c in descompuesto if unicodedata.category(c) != 'Mn').casefold()


def _palabras(texto):
    """Palabras de un texto sin tildes ni mayúsculas: 'Pan de Molde' -> ['pan', 'de', 'molde']."""
    return re.findall(r'[a-z0-9]+', _sin_tildes(texto))


def _posicion_de(palabra_buscada, palabras):
    """Índice de la primera palabra que EMPIEZA con lo buscado, o None.

    Se compara por inicio de palabra: 'pan' calza con 'pan' y 'panadería', pero no con
    'empanada'. También acepta el plural sencillo ('panes' -> 'pan').
    """
    formas = {palabra_buscada}
    for sufijo in ('es', 's'):
        if palabra_buscada.endswith(sufijo) and len(palabra_buscada) - len(sufijo) >= 3:
            formas.add(palabra_buscada[:-len(sufijo)])
    for indice, palabra in enumerate(palabras):
        if any(palabra.startswith(forma) for forma in formas):
            return indice
    return None


def _buscar_productos(productos, busqueda):
    """Productos que calzan con la búsqueda, del más al menos relevante.

    Una palabra buscada calza si es el inicio de una palabra del nombre o de la categoría.
    Orden: los agotados al final; luego los de la categoría que calza (buscar "pan" muestra toda
    la categoría de panes); luego los que tienen la palabra antes en el nombre; luego por nombre.
    """
    terminos = _palabras(busqueda)[:BUSQUEDA_MAX_PALABRAS]
    if not terminos:
        return []

    encontrados = []
    for producto in productos.select_related('categoria'):
        en_nombre = _palabras(producto.nombre)
        en_categoria = _palabras(producto.categoria.nombre)
        if not all(_posicion_de(t, en_nombre + en_categoria) is not None for t in terminos):
            continue
        calza_categoria = all(_posicion_de(t, en_categoria) is not None for t in terminos)
        posiciones = [_posicion_de(t, en_nombre) for t in terminos]
        mejor_posicion = min((p for p in posiciones if p is not None), default=99)
        encontrados.append((
            (producto.stock <= 0, 0 if calza_categoria else 1, mejor_posicion, producto.nombre.casefold()),
            producto,
        ))
    return [producto for _, producto in sorted(encontrados, key=lambda par: par[0])]


def pedir(request):
    """Catálogo completo, público. Filtros combinables: ?categoria=<id>, ?turno=<id> y búsqueda ?q=."""
    _expirar_pedidos_webpay_vencidos()  # el stock que se muestra no debe incluir pagos abandonados
    categorias = Categoria.objects.filter(productos__activo=True).distinct().order_by('nombre')

    productos = Producto.objects.filter(activo=True).prefetch_related(_turnos_activos()).order_by(
        # Los agotados van al final
        Case(When(stock__gt=0, then=Value(0)), default=Value(1), output_field=IntegerField()),
        'nombre',
    )

    # Turnos de venta (los administra el admin). "Ahora" se calcula con la hora de Chile.
    turnos = list(Turno.objects.filter(activo=True, productos__activo=True).distinct())
    ahora_cl = ahora_en_chile()
    turnos_ahora = [t.pk for t in turnos if t.rige_en(ahora_cl)]  # pueden regir varios a la vez
    turno_actual = None
    turno_id = _entero_o_none(request.GET.get('turno', ''))
    if turno_id is not None:
        turno_actual = next((t for t in turnos if t.pk == turno_id), None)
    if turno_actual:
        # Lo que se vende en ese turno, más lo que no tiene turnos activos (se vende todo el día).
        sin_turnos = Producto.objects.exclude(turnos__activo=True).values('pk')
        en_el_turno = Producto.objects.filter(turnos=turno_actual).values('pk')
        productos = productos.filter(Q(pk__in=sin_turnos) | Q(pk__in=en_el_turno))

    categoria_actual = None
    categoria_id = _entero_o_none(request.GET.get('categoria', ''))
    if categoria_id is not None:
        categoria_actual = categorias.filter(pk=categoria_id).first()
        if categoria_actual:
            productos = productos.filter(categoria=categoria_actual)

    # Los filtros activos como query string, para que los enlaces y "Limpiar" los conserven.
    parametros = []
    if categoria_actual:
        parametros.append(f'categoria={categoria_actual.pk}')
    if turno_actual:
        parametros.append(f'turno={turno_actual.pk}')
    filtros_qs = ('?' + '&'.join(parametros)) if parametros else ''

    # Búsqueda por nombre o categoría: sin importar mayúsculas ni tildes (ver _buscar_productos).
    busqueda = request.GET.get('q', '').strip()[:BUSQUEDA_MAX_LARGO]
    if busqueda:
        productos = _buscar_productos(productos, busqueda)

    # La búsqueda en vivo (static/js/busqueda_catalogo.js) pide solo la zona de resultados. Va en
    # una URL distinta (?parcial=1) para que el navegador no guarde el fragmento como si fuera la página.
    plantilla = 'core/_resultados_busqueda.html' if request.GET.get('parcial') == '1' else 'core/pedir.html'
    return render(request, plantilla, {
        'productos': productos,
        'categorias': categorias,
        'categoria_actual': categoria_actual,
        'turnos': turnos,
        'turno_actual': turno_actual,
        'turnos_ahora': turnos_ahora,
        'filtros_qs': filtros_qs,
        'busqueda': busqueda,
    })

@login_required
def mis_pedidos(request):
    """
    Muestra el historial de compras y pedidos realizados por el cliente autenticado.
    """
    _expirar_pedidos_webpay_vencidos()  # Libera pedidos Webpay abandonados

    cliente = getattr(request.user, 'perfil_cliente', None)
    
    if not cliente:
        pedidos = Pedido.objects.none()
    else:
        pedidos = (
            Pedido.objects.filter(cliente=cliente)
            .prefetch_related('detalles__producto')
            .select_related('pago')
            .order_by('-fecha')
        )

    return render(request, 'core/mis_pedidos.html', {'pedidos': pedidos})


def _resumen_carrito_json(request, producto_id, mensaje="", tipo_mensaje="success"):
    """Helper para calcular totales y devolver respuesta JSON estandarizada."""
    carrito = request.session.get('carrito', {})
    if not isinstance(carrito, dict):
        carrito = {}

    cantidades = {}
    for p_id, cant in carrito.items():
        try:
            cantidades[int(p_id)] = int(cant)
        except (TypeError, ValueError):
            continue

    cant_unidades_item = cantidades.get(int(producto_id), 0)

    # Calcular total del carrito
    productos = Producto.objects.filter(pk__in=cantidades.keys(), activo=True)
    total_monto = sum(p.precio * cantidades[p.pk] for p in productos if p.pk in cantidades)
    
    # Subtotal del producto modificado
    producto_obj = next((p for p in productos if p.pk == int(producto_id)), None)
    subtotal_item = (producto_obj.precio * cant_unidades_item) if producto_obj else 0

    return JsonResponse({
        'ok': True,
        'producto_id': int(producto_id),
        'cantidad_item': cant_unidades_item,
        'cant_carrito': len(carrito), # O sum(cantidades.values()) según tu preferencia
        'subtotal_item_clp': clp(subtotal_item),
        'total_carrito_clp': clp(total_monto),
        'mensaje': mensaje,
        'tipo_mensaje': tipo_mensaje,
    })


@require_POST
def agregar_al_carrito(request):
    _expirar_pedidos_webpay_vencidos()  # el límite de stock no debe incluir pagos abandonados
    es_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    producto_id = _entero_o_none(request.POST.get('producto_id', ''))
    
    if producto_id is None:
        if es_ajax:
            return JsonResponse({'ok': False, 'error': 'Producto no identificado.'}, status=400)
        messages.error(request, 'No se pudo identificar el producto.')
        return redirect('pedir')

    producto = get_object_or_404(Producto, pk=producto_id, activo=True)
    carrito = request.session.get('carrito', {})
    if not isinstance(carrito, dict):
        carrito = {}

    clave = str(producto.pk)
    cantidad = carrito.get(clave, 0)
    if not isinstance(cantidad, int) or cantidad < 0:
        cantidad = 0

    if producto.stock <= cantidad:
        msg = f'No hay más stock disponible de {producto.nombre}.'
        if es_ajax:
            return _resumen_carrito_json(request, producto.pk, mensaje=msg, tipo_mensaje='error')
        messages.error(request, msg)
        return redirect(request.META.get('HTTP_REFERER') or 'pedir')

    carrito[clave] = cantidad + 1
    request.session['carrito'] = carrito
    msg = f'{producto.nombre} se agregó al carrito.'

    if es_ajax:
        return _resumen_carrito_json(request, producto.pk, mensaje=msg, tipo_mensaje='success')

    messages.success(request, msg)
    return redirect(request.META.get('HTTP_REFERER') or 'pedir')


def carrito(request):
    """Muestra el carrito de la sesión con los datos reales de cada producto."""
    _expirar_pedidos_webpay_vencidos()  # libera el stock de pagos Webpay abandonados
    carrito_sesion = request.session.get('carrito', {})
    if not isinstance(carrito_sesion, dict):
        carrito_sesion = {}

    cantidades = {}
    for producto_id, cantidad in carrito_sesion.items():
        try:
            producto_id = int(producto_id)
            cantidad = int(cantidad)
        except (TypeError, ValueError):
            continue
        if producto_id > 0 and cantidad > 0:
            cantidades[producto_id] = cantidad

    productos = Producto.objects.filter(
        pk__in=cantidades,
        activo=True,
    ).prefetch_related(_turnos_activos()).order_by('nombre')
    items = []
    ids_validos = set()
    total = Decimal('0.00')
    for producto in productos:
        cantidad = cantidades[producto.pk]
        subtotal = producto.precio * cantidad
        total += subtotal
        ids_validos.add(producto.pk)
        items.append({
            'producto': producto,
            'cantidad': cantidad,
            'subtotal': subtotal,
        })

    carrito_normalizado = {
        str(producto_id): cantidad
        for producto_id, cantidad in cantidades.items()
        if producto_id in ids_validos
    }
    if carrito_sesion != carrito_normalizado:
        request.session['carrito'] = carrito_normalizado
        if len(carrito_normalizado) < len(cantidades):
            messages.warning(request, 'Se quitaron del carrito productos que ya no están disponibles.')

    # Cliente registrado: se le ofrece la dirección que dejó al crear su cuenta.
    direccion_guardada = ''
    if request.user.is_authenticated:
        direccion_guardada = (
            Cliente.objects.filter(user=request.user)
            .values_list('direccion', flat=True)
            .first()
        ) or ''

    # Los productos con turnos solo se venden dentro de ellos: la agenda ofrece únicamente las horas
    # (de retiro o de entrega) que sirven para todos los productos del carrito.
    turnos_por_producto = []
    restricciones = []
    for item in items:
        turnos = list(item['producto'].turnos.all())
        if turnos:
            turnos_por_producto.append(turnos)
            restricciones.append({
                'nombre': item['producto'].nombre,
                'turnos': '; '.join(turno.descripcion for turno in turnos),
            })
    agenda = dias_de_retiro(turnos_por_producto=turnos_por_producto)
    # ¿No queda ninguna hora por culpa de los productos (y no porque la tienda esté cerrada)?
    sin_horas_por_productos = bool(turnos_por_producto) and not agenda and bool(dias_de_retiro())

    return render(request, 'core/carrito.html', {
        'items': items,
        'total': total,
        'direccion_guardada': direccion_guardada,
        'retiro_dias': agenda,
        'restricciones': restricciones,
        'sin_horas_por_productos': sin_horas_por_productos,
        'carrito_tiene_stock': all(
            item['cantidad'] <= item['producto'].stock for item in items
        ),
    })

@require_POST
def disminuir_del_carrito(request, producto_id):
    es_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    carrito_sesion = request.session.get('carrito', {})
    if isinstance(carrito_sesion, dict):
        clave = str(producto_id)
        cantidad = carrito_sesion.get(clave, 0)
        if isinstance(cantidad, int) and cantidad > 1:
            carrito_sesion[clave] = cantidad - 1
        else:
            carrito_sesion.pop(clave, None)
        request.session['carrito'] = carrito_sesion

    if es_ajax:
        return _resumen_carrito_json(request, producto_id, mensaje="Cantidad actualizada.")

    return redirect(request.META.get('HTTP_REFERER') or 'carrito')


@require_POST
def quitar_del_carrito(request, producto_id):
    es_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    carrito_sesion = request.session.get('carrito', {})
    if isinstance(carrito_sesion, dict):
        carrito_sesion.pop(str(producto_id), None)
        request.session['carrito'] = carrito_sesion

    msg = 'Producto quitado del carrito.'
    if es_ajax:
        return _resumen_carrito_json(request, producto_id, mensaje=msg, tipo_mensaje='info')

    messages.success(request, msg)
    return redirect(request.META.get('HTTP_REFERER') or 'carrito')

@require_POST
def finalizar_compra(request):
    """Compra de demostración: crea pedido, detalle y pago simulado, y descuenta el stock."""
    _expirar_pedidos_webpay_vencidos()  # un pago abandonado no debe dejar sin stock a quien reintenta
    carrito_sesion = request.session.get('carrito', {})
    if not isinstance(carrito_sesion, dict) or not carrito_sesion:
        messages.error(request, 'Tu carrito está vacío.')
        return redirect('carrito')

    tipo_entrega = request.POST.get('tipo_entrega', 'RETIRO')
    if tipo_entrega not in {'RETIRO', 'DESPACHO'}:
        messages.error(request, 'Selecciona una opción de entrega válida.')
        return redirect('carrito')

    direccion = request.POST.get('direccion_despacho', '').strip()
    if tipo_entrega == 'DESPACHO' and not direccion:
        messages.error(request, 'Ingresa la dirección para el despacho.')
        return redirect('carrito')

    if tipo_entrega == 'DESPACHO':
        # La dirección debe traer número (o S/N si no tiene): el repartidor lo necesita.
        if not re.search(r'\d|\bs\s*/?\s*n\b|\bsin\s+n[uú]mero\b', direccion, re.IGNORECASE):
            messages.error(request, 'Agrega el número de tu dirección (o S/N si no tiene).')
            return redirect('carrito')

        # Depto, casa o block van en un campo aparte; se guardan junto a la dirección.
        detalles = request.POST.get('detalles_entrega', '').strip()
        if detalles:
            direccion = f'{direccion} ({detalles})'
        if len(direccion) > 255:
            messages.error(request, 'La dirección y los detalles son demasiado largos (máximo 255 caracteres).')
            return redirect('carrito')

        # Solo se despacha dentro de la zona marcada en el mapa (core/zona_despacho.py).
        coordenadas = leer_coordenadas(request.POST.get('latitud'), request.POST.get('longitud'))
        if coordenadas is None:
            messages.error(
                request,
                'No pudimos confirmar tu ubicación en el mapa. Busca tu dirección y confirma '
                'el punto, o elige retiro en tienda.',
            )
            return redirect('carrito')
        if not punto_en_zona(*coordenadas):
            messages.error(
                request,
                'Tu dirección está fuera de la zona de despacho marcada en el mapa. '
                f"Puedes retirar tu pedido en la tienda ({TIENDA['direccion']}).",
            )
            return redirect('carrito')

    cantidades = {}
    for producto_id, cantidad in carrito_sesion.items():
        try:
            producto_id = int(producto_id)
            cantidad = int(cantidad)
        except (TypeError, ValueError):
            messages.error(request, 'El carrito contiene un producto inválido.')
            return redirect('carrito')
        if producto_id <= 0 or cantidad <= 0:
            messages.error(request, 'El carrito contiene una cantidad inválida.')
            return redirect('carrito')
        cantidades[producto_id] = cantidad

    # Agenda: día y hora de retiro o de entrega (core/retiro.py). Cada producto con turnos solo se vende
    # dentro de ellos, así que la hora elegida debe caber en los turnos de todos los del carrito.
    productos_del_carrito = list(
        Producto.objects.filter(pk__in=cantidades, activo=True).prefetch_related(_turnos_activos())
    )
    turnos_por_producto = [turnos for turnos in (list(p.turnos.all()) for p in productos_del_carrito) if turnos]
    etiqueta_agenda = 'Entrega programada' if tipo_entrega == 'DESPACHO' else 'Retiro programado'
    texto_agenda = ''
    fecha_elegida = request.POST.get('fecha_retiro', '').strip()
    hora_elegida = request.POST.get('hora_retiro', '').strip()
    if fecha_elegida or hora_elegida:
        fecha, hora, error = validar_retiro(fecha_elegida, hora_elegida, turnos_por_producto=turnos_por_producto)
        if error:
            messages.error(request, error)
            return redirect('carrito')
        texto_agenda = f'{etiqueta_agenda}: {texto_retiro(fecha, hora)}'
    else:
        # Sin agenda (otro cliente HTTP): los productos con turnos deben poder venderse ahora.
        momento = ahora_en_chile()
        fuera_de_turno = [p for p in productos_del_carrito if not esta_disponible(list(p.turnos.all()), momento)]
        if fuera_de_turno:
            nombres = ', '.join(p.nombre for p in fuera_de_turno)
            messages.error(request, f'Ahora no se vende: {nombres}. Elige un día y una hora de la agenda.')
            return redirect('carrito')

    if tipo_entrega == 'DESPACHO':
        direccion_final = f'{direccion} · {texto_agenda}' if texto_agenda else direccion
        if len(direccion_final) > 255:
            messages.error(
                request,
                'La dirección y los detalles son demasiado largos para sumarles la hora de entrega '
                '(máximo 255 caracteres). Acórtalos.',
            )
            return redirect('carrito')
    else:
        direccion_final = texto_agenda

    with transaction.atomic():
        productos = list(
            Producto.objects.select_for_update()
            .filter(pk__in=cantidades, activo=True)
            .order_by('pk')
        )
        if len(productos) != len(cantidades):
            messages.error(request, 'Uno o más productos ya no están disponibles.')
            return redirect('carrito')

        faltantes = [
            producto.nombre
            for producto in productos
            if producto.stock < cantidades[producto.pk]
        ]
        if faltantes:
            messages.error(
                request,
                'Stock insuficiente para: ' + ', '.join(faltantes) + '. Revisa tu carrito.',
            )
            return redirect('carrito')

        total = sum(
            (producto.precio * cantidades[producto.pk] for producto in productos),
            Decimal('0.00'),
        )
        cliente = None
        if request.user.is_authenticated:
            cliente = Cliente.objects.filter(user=request.user).first()

        metodo_pago = request.POST.get('metodo_pago', 'SIMULADO')
        es_webpay = (metodo_pago == 'WEBPAY')

        pedido = Pedido.objects.create(
            cliente=cliente,
            estado='PENDIENTE' if es_webpay else 'PAGADO',
            canal='WEB',
            tipo_entrega=tipo_entrega,
            direccion_despacho=direccion_final,
            total=total,
        )
        for producto in productos:
            cantidad = cantidades[producto.pk]
            subtotal = producto.precio * cantidad
            DetallePedido.objects.create(
                pedido=pedido,
                producto=producto,
                cantidad=cantidad,
                precio_unitario=producto.precio,
                subtotal=subtotal,
            )
            producto.stock -= cantidad
            producto.save(update_fields=['stock'])

        if not es_webpay:
            # Flujo de Demostración Simulado (sin pasarela real)
            Pago.objects.create(
                pedido=pedido,
                monto=total,
                metodo='Simulación (sin cobro real)',
                estado='SIMULADO',
                codigo_autorizacion=f'DEMO-{pedido.pk:08d}',
            )
            request.session['carrito'] = {}
            boletas = request.session.get('boletas_simuladas', [])
            if not isinstance(boletas, list):
                boletas = []
            boletas.append(pedido.pk)
            request.session['boletas_simuladas'] = boletas
            messages.success(request, 'Compra de demostración completada correctamente.')
            return redirect('boleta_simulada', pedido_id=pedido.pk)

        # Flujo Oficial Transbank Webpay Plus
        pago = Pago.objects.create(
            pedido=pedido,
            monto=total,
            metodo='Webpay Plus',
            estado='PENDIENTE',
            codigo_autorizacion='',
        )

    # Iniciar transacción con Webpay Plus fuera de la transacción atómica
    buy_order = f"ORD-{pedido.pk}"
    if not request.session.session_key:
        request.session.save()
    session_id = request.session.session_key
    amount = int(round(float(total)))
    return_url = request.build_absolute_uri('/carrito/webpay-confirmar/')

    tx = obtener_transaccion_webpay()
    try:
        response = tx.create(buy_order, session_id, amount, return_url)
    except Exception as e:
        # Si falla la comunicación inicial con Transbank, revertir stock y cancelar pedido
        with transaction.atomic():
            for detalle in pedido.detalles.select_related('producto'):
                detalle.producto.stock += detalle.cantidad
                detalle.producto.save(update_fields=['stock'])
            pedido.estado = 'CANCELADO'
            pedido.save(update_fields=['estado'])
            pago.estado = 'FALLIDO'
            pago.save(update_fields=['estado'])
        messages.error(request, f'No se pudo conectar con Transbank Webpay: {str(e)}')
        return redirect('carrito')

    token_ws = response.get('token')
    pago.codigo_autorizacion = token_ws
    pago.save(update_fields=['codigo_autorizacion'])
    request.session['webpay_pedido_id'] = pedido.pk
    request.session['webpay_token'] = token_ws

    # Redirigir al formulario de Webpay Plus
    return redirect(f"{response['url']}?token_ws={token_ws}")


# Un pedido con Webpay que sigue PENDIENTE pasado este tiempo se da por abandonado. Transbank da
# 5 min para abrir el formulario y 10 min para pagar en él (ambiente de integración): 15 min como
# máximo, y se deja margen para que un pago que llega justo no encuentre el pedido ya cancelado.
WEBPAY_VIGENCIA_MIN = 20


def _cancelar_pedido_pendiente(pedido_id, estado_pago):
    """Cancela un pedido PENDIENTE y devuelve su stock una sola vez.

    Se puede llamar de nuevo con el mismo pedido: si ya no está PENDIENTE no hace nada.
    Devuelve True si canceló el pedido.
    """
    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().filter(pk=pedido_id, estado='PENDIENTE').first()
        if pedido is None:
            return False
        for detalle in pedido.detalles.all():
            Producto.objects.filter(pk=detalle.producto_id).update(stock=F('stock') + detalle.cantidad)
        pedido.estado = 'CANCELADO'
        pedido.save(update_fields=['estado'])
        Pago.objects.filter(pedido=pedido).update(estado=estado_pago)
    return True


def _expirar_pedidos_webpay_vencidos():
    """Libera el stock de los pedidos Webpay abandonados (el cliente cerró la ventana de pago).

    Si cierra la ventana, Transbank no devuelve al cliente al sitio y nadie más los cancelaría.
    """
    limite = timezone.now() - timedelta(minutes=WEBPAY_VIGENCIA_MIN)
    vencidos = Pedido.objects.filter(
        estado='PENDIENTE', fecha__lt=limite, pago__metodo__startswith='Webpay',
    ).values_list('pk', flat=True)
    for pedido_id in list(vencidos):
        _cancelar_pedido_pendiente(pedido_id, 'EXPIRADO')


def _respuesta_resuelta_webpay(tx, token_ws, intentos=3, espera=1.0):
    """Consulta el estado real de una transacción cuando el commit dio error.

    Devuelve la respuesta si Transbank ya la resolvió (aprobada o no) y None si sigue en
    proceso o no se pudo consultar. En ese caso el pedido no se toca: si el pago nunca llega,
    _expirar_pedidos_webpay_vencidos lo libera pasado el plazo.
    """
    for intento in range(intentos):
        try:
            respuesta = tx.status(token_ws)
        except Exception:
            respuesta = None
        if respuesta and respuesta.get('status') not in (None, 'INITIALIZED'):
            return respuesta
        if intento < intentos - 1:
            time.sleep(espera)
    return None


def iniciar_pago_webpay(request, pedido_id=None):
    """
    Inicia una transacción en Transbank Webpay Plus para un pedido existente o pendiente.
    Redirige al cliente al portal de pago seguro de Transbank.
    """
    if pedido_id is None:
        pedido_id = request.POST.get('pedido_id') or request.session.get('webpay_pedido_id')

    pedido = get_object_or_404(Pedido, pk=pedido_id)

    if pedido.estado == 'PAGADO':
        messages.info(request, 'Este pedido ya se encuentra pagado.')
        return redirect('boleta_simulada', pedido_id=pedido.pk)

    buy_order = f"ORD-{pedido.pk}"
    if not request.session.session_key:
        request.session.save()
    session_id = request.session.session_key
    amount = int(round(float(pedido.total)))
    return_url = request.build_absolute_uri('/carrito/webpay-confirmar/')

    tx = obtener_transaccion_webpay()
    try:
        response = tx.create(buy_order, session_id, amount, return_url)
    except Exception as e:
        messages.error(request, f'No se pudo conectar con Transbank Webpay: {str(e)}')
        return redirect('carrito')

    token_ws = response.get('token')
    request.session['webpay_pedido_id'] = pedido.pk
    request.session['webpay_token'] = token_ws

    pago, _ = Pago.objects.get_or_create(
        pedido=pedido,
        defaults={
            'monto': pedido.total,
            'metodo': 'Webpay Plus',
            'estado': 'PENDIENTE',
            'codigo_autorizacion': token_ws,
        }
    )
    pago.codigo_autorizacion = token_ws
    pago.save(update_fields=['codigo_autorizacion'])

    return redirect(f"{response['url']}?token_ws={token_ws}")


@csrf_exempt
def webpay_confirmar(request):
    """
    Punto de retorno (return_url) invocado tras el paso por la pasarela de Webpay Plus.
    Procesa el resultado:
    - TBK_TOKEN presente (con o sin token_ws): pago anulado o formulario fallido -> se cancela
    - solo token_ws: Transacción completada -> commit()
    - Solo TBK_ID_SESION y TBK_ORDEN_COMPRA: venció el tiempo del formulario de Webpay
    """
    token_ws = request.POST.get('token_ws') or request.GET.get('token_ws')
    tbk_token = request.POST.get('TBK_TOKEN') or request.GET.get('TBK_TOKEN')
    tbk_orden_compra = request.POST.get('TBK_ORDEN_COMPRA') or request.GET.get('TBK_ORDEN_COMPRA')

    # Caso 1: el pago no se completó y el cliente volvió al sitio, ya sea porque lo anuló o porque
    # el formulario de Webpay falló y pulsó "Intentar nuevamente". Llega TBK_TOKEN (con o sin
    # token_ws): el pago NO se autorizó, así que no se confirma. Solo se cancela el pedido cuyo
    # token de Transbank coincide con el recibido. La sesión no sirve de prueba: este retorno suele
    # llegar por POST desde otro dominio y el navegador no envía la cookie de sesión.
    if tbk_token:
        tokens = [t for t in (tbk_token, token_ws) if t]
        pedido_id = (
            Pedido.objects.filter(estado='PENDIENTE', pago__codigo_autorizacion__in=tokens)
            .values_list('pk', flat=True)
            .first()
        )
        if pedido_id is not None:
            _cancelar_pedido_pendiente(pedido_id, 'CANCELADO')
        request.session.pop('webpay_pedido_id', None)
        messages.warning(
            request,
            'El pago no se completó en Webpay. No se realizó ningún cobro y tus productos '
            'se mantienen en el carrito: puedes intentarlo de nuevo.',
        )
        return redirect('carrito')

    # Caso 3: el cliente dejó vencer el formulario de Webpay. Transbank devuelve TBK_ID_SESION y
    # TBK_ORDEN_COMPRA, sin token. Solo se cancela el pedido que esta misma sesión inició; si la
    # sesión no coincide, el pedido lo libera _expirar_pedidos_webpay_vencidos pasado el plazo.
    if not token_ws and not tbk_token and tbk_orden_compra:
        pedido_id = None
        if tbk_orden_compra.startswith('ORD-'):
            pedido_id = _entero_o_none(tbk_orden_compra[len('ORD-'):])
        if pedido_id is not None and pedido_id == request.session.get('webpay_pedido_id'):
            _cancelar_pedido_pendiente(pedido_id, 'EXPIRADO')
        request.session.pop('webpay_pedido_id', None)
        messages.warning(
            request,
            'Se agotó el tiempo para pagar en Webpay. No se realizó ningún cobro '
            'y tus productos se mantienen en el carrito.',
        )
        return redirect('carrito')

    if not token_ws:
        messages.error(request, 'No se recibió el token de confirmación de Transbank.')
        return redirect('carrito')

    # Caso 2: Confirmar transacción con Transbank (commit)
    tx = obtener_transaccion_webpay()
    try:
        response = tx.commit(token_ws)
    except Exception:
        # Un error al confirmar NO significa que el pago falló. Por ejemplo, el 422 "Invalid status
        # '10' ... while authorizing" quiere decir que Transbank todavía está autorizando y va a
        # cobrar: cancelar el pedido ahí dejaría un pago cobrado sin pedido. Antes de decidir algo
        # se consulta el estado real; si sigue en proceso, el pedido queda como está.
        response = _respuesta_resuelta_webpay(tx, token_ws)
        if response is None:
            messages.warning(
                request,
                'Estamos confirmando tu pago con Transbank. Espera unos segundos y revisa tu '
                'pedido; no lo pagues de nuevo.',
            )
            return redirect('carrito')

    buy_order = response.get('buy_order', '')
    pedido_id = None
    if buy_order.startswith('ORD-'):
        try:
            pedido_id = int(buy_order.replace('ORD-', ''))
        except ValueError:
            pass
    if not pedido_id:
        pedido_id = request.session.get('webpay_pedido_id')

    pedido = get_object_or_404(Pedido, pk=pedido_id)

    response_code = response.get('response_code')
    status = response.get('status')

    # Transbank aprueba cuando response_code == 0 y status == 'AUTHORIZED'
    if response_code == 0 and status == 'AUTHORIZED':
        tipo_codigo = response.get('payment_type_code', '')
        tipo_texto = TIPOS_PAGO_WEBPAY.get(tipo_codigo, 'Tarjeta')
        cod_autorizacion = response.get('authorization_code', '')

        with transaction.atomic():
            pedido.estado = 'PAGADO'
            pedido.save(update_fields=['estado'])

            pago, _ = Pago.objects.get_or_create(
                pedido=pedido,
                defaults={
                    'monto': Decimal(str(response.get('amount', pedido.total))),
                    'metodo': f'Webpay Plus ({tipo_texto})',
                    'estado': 'APROBADO',
                    'codigo_autorizacion': cod_autorizacion,
                }
            )
            pago.monto = Decimal(str(response.get('amount', pedido.total)))
            pago.metodo = f'Webpay Plus ({tipo_texto})'
            pago.estado = 'APROBADO'
            pago.codigo_autorizacion = cod_autorizacion
            pago.save()

        # Limpiar carrito tras confirmación de pago
        request.session['carrito'] = {}
        request.session.pop('webpay_pedido_id', None)

        # Autorizar acceso al comprobante
        boletas = request.session.get('boletas_simuladas', [])
        if not isinstance(boletas, list):
            boletas = []
        boletas.append(pedido.pk)
        request.session['boletas_simuladas'] = boletas

        messages.success(request, f'¡Pago aprobado con éxito! Código de autorización: {cod_autorizacion}')
        return redirect('boleta_simulada', pedido_id=pedido.pk)
    else:
        # Pago rechazado por Transbank o por el banco emisor
        with transaction.atomic():
            for detalle in pedido.detalles.select_related('producto'):
                detalle.producto.stock += detalle.cantidad
                detalle.producto.save(update_fields=['stock'])
            pedido.estado = 'CANCELADO'
            pedido.save(update_fields=['estado'])
            if hasattr(pedido, 'pago'):
                pedido.pago.estado = 'RECHAZADO'
                pedido.pago.save(update_fields=['estado'])

        request.session.pop('webpay_pedido_id', None)
        messages.error(request, 'El pago fue rechazado por Webpay o tu banco. Por favor intenta nuevamente.')
        return redirect('carrito')



def boleta_simulada(request, pedido_id):
    """Comprobante de la compra de demostración (solo su sesión o su dueño)."""
    boletas = request.session.get('boletas_simuladas', [])
    autorizada = isinstance(boletas, list) and pedido_id in boletas
    if not autorizada and request.user.is_authenticated:
        autorizada = Pedido.objects.filter(
            pk=pedido_id,
            cliente__user=request.user,
        ).exists()
    if not autorizada:
        raise Http404

    pedido = get_object_or_404(
        Pedido.objects.prefetch_related('detalles__producto').select_related('pago'),
        pk=pedido_id,
    )
    return render(request, 'core/boleta_simulada.html', {'pedido': pedido})


def producto_detalle(request, pk):
    """Información del producto y cuándo se vende. Con ?parcial=1 devuelve solo el contenido del modal
    del catálogo (static/js/producto_modal.js); sin él, la página completa (para quien no usa JavaScript)."""
    producto = get_object_or_404(
        Producto.objects.select_related('categoria').prefetch_related(_turnos_activos()),
        pk=pk, activo=True,
    )
    turnos = list(producto.turnos.all())  # solo los activos (ver _turnos_activos)
    disponible_ahora, vuelve = resumen_de_disponibilidad(turnos, ahora_en_chile())
    plantilla = 'core/_producto_detalle.html' if request.GET.get('parcial') == '1' else 'core/producto.html'
    return render(request, plantilla, {
        'p': producto,
        'turnos_del_producto': turnos,
        'disponible_ahora': disponible_ahora,
        'vuelve': vuelve,
    })


def local(request):
    """Información de la tienda: dirección, horarios, despacho y mapa de cobertura.
    Los datos salen de core/templatetags/tienda.py."""
    return render(request, 'core/local.html')


# ==========================================
# FUNCIONES DE CARRITO Y VISTAS DE CLIENTE
# ==========================================


def redireccionar_por_rol(user):
    """
    Redirige al usuario según su rol en el sistema:
    - ADMINISTRADOR -> 'inicio_admin'
    - CAJERO -> 'inicio_cajero'
    - CLIENTE -> 'inicio'
    """
    if getattr(user, 'es_administrador', False):
        return redirect('inicio_admin')
    elif getattr(user, 'es_cajero', False):
        return redirect('inicio_cajero')
    return redirect('inicio')


# ==========================================
# FUNCIONES DE ADMINISTRADOR
# ==========================================

# --------------------------------------------
# DECORADOR Y CONTROL DE ACCESO ADMINISTRADOR
# --------------------------------------------

def admin_required(view_func):
    """
    Decorador que verifica que el usuario esté autenticado y sea Administrador.
    Si no cumple, lo redirige al inicio con un mensaje de error.
    """
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Debe iniciar sesión para acceder a esta sección.')
            return redirect('login')
        if not request.user.es_administrador:
            messages.error(request, 'No tiene permisos de administrador para acceder a esta página.')
            return redirect('inicio')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@admin_required
def inicio_admin(request):
    """
    Vista principal del Panel de Administración.
    Muestra la gestión de productos/insumos en la parte superior,
    seguido de indicadores de stock, proyecciones de ventas y precios de materias primas.
    """
    # Consulta de insumos de materia prima para la tabla CRUD
    insumos = Insumo.objects.all().order_by('codigo', 'nombre')

    # Calcular próximo ID sugerido (ej: NI007)
    ultimo = Insumo.objects.exclude(codigo='').order_by('-codigo').first()
    siguiente_id = 'NI001'
    if ultimo and ultimo.codigo.startswith('NI'):
        try:
            num = int(ultimo.codigo.replace('NI', '')) + 1
            siguiente_id = f'NI{num:03d}'
        except ValueError:
            siguiente_id = f'NI{insumos.count() + 1:03d}'

    # Consulta de productos de venta al público para la tabla CRUD
    todos_los_productos = (
        Producto.objects.select_related('categoria').prefetch_related('turnos')
        .order_by('categoria__nombre', 'nombre')
    )
    categorias_productos = Categoria.objects.all().order_by('nombre')

    # Consulta de productos con stock actual
    productos_stock = Producto.objects.filter(activo=True).order_by('nombre')
    
    # Consulta de insumos/materias primas y sus precios de proveedores
    tarifas_proveedores = ProveedorInsumo.objects.select_related('proveedor', 'insumo').all()

    contexto = {
        'insumos': insumos,
        'siguiente_id': siguiente_id,
        'todos_los_productos': todos_los_productos,
        'categorias_productos': categorias_productos,
        'turnos_disponibles': Turno.objects.filter(activo=True),
        'dias_semana': list(zip('LMXJVSD', [d.capitalize() for d in Turno.NOMBRES_DIAS])),
        'productos_stock': productos_stock,
        'tarifas_proveedores': tarifas_proveedores,
    }
    return render(request, 'core/inicio_admin.html', contexto)

@admin_required
def gestion_usuarios(request):
    """
    Vista principal de gestión de cuentas.
    Separa los usuarios en Clientes (Solo Lectura) y Personal del Sistema (Administradores y Cajeros).
    """
    clientes = Cliente.objects.select_related('user', 'puntos').all().order_by('-user__date_joined')
    personal = Usuario.objects.filter(
        rol__in=['ADMINISTRADOR', 'CAJERO']
    ).select_related('perfil_cajero', 'perfil_admin').order_by('rol', 'username')

    contexto = {
        'clientes': clientes,
        'personal': personal,
    }
    return render(request, 'core/gestion_usuarios.html', contexto)

@admin_required
def crear_personal(request):
    """Crea un nuevo usuario del personal (ADMINISTRADOR o CAJERO) con su perfil correspondiente."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        rol = request.POST.get('rol', 'CAJERO')
        num_caja = request.POST.get('num_caja_asignada', 1)

        if Usuario.objects.filter(username__iexact=username).exists():
            messages.error(request, 'El nombre de usuario ya está registrado.')
            return redirect('gestion_usuarios')

        try:
            with transaction.atomic():
                user = Usuario.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    rol=rol,
                    is_staff=True
                )
                if rol == 'CAJERO':
                    Cajero.objects.create(user=user, num_caja_asignada=num_caja)
                elif rol == 'ADMINISTRADOR':
                    Administrador.objects.create(user=user, nivel_acceso='TOTAL')

                messages.success(request, f'Usuario "{username}" ({rol}) registrado con éxito.')
        except Exception as e:
            messages.error(request, f'Error al crear el usuario: {str(e)}')

    return redirect('gestion_usuarios')


@admin_required
def editar_personal(request, pk):
    """Edita la información y rol de un usuario del personal (Administrador o Cajero)."""
    user = get_object_or_404(Usuario, pk=pk)

    if request.method == 'POST':
        user.first_name = request.POST.get('first_name', '').strip()
        user.last_name = request.POST.get('last_name', '').strip()
        user.email = request.POST.get('email', '').strip().lower()
        nuevo_rol = request.POST.get('rol', user.rol)
        num_caja = request.POST.get('num_caja_asignada', 1)

        # Si cambió el rol, actualizamos los perfiles asociados
        if nuevo_rol != user.rol:
            user.rol = nuevo_rol
            if nuevo_rol == 'ADMINISTRADOR':
                Cajero.objects.filter(user=user).delete()
                Administrador.objects.get_or_create(user=user, defaults={'nivel_acceso': 'TOTAL'})
            elif nuevo_rol == 'CAJERO':
                Administrador.objects.filter(user=user).delete()
                Cajero.objects.get_or_create(user=user, defaults={'num_caja_asignada': num_caja})

        # Si es o sigue siendo Cajero, actualizamos el N° de caja
        if user.rol == 'CAJERO':
            cajero, _ = Cajero.objects.get_or_create(user=user)
            try:
                cajero.num_caja_asignada = int(num_caja)
                cajero.save()
            except (ValueError, TypeError):
                pass

        # Cambio de contraseña opcional
        nueva_pass = request.POST.get('password', '').strip()
        if nueva_pass:
            user.set_password(nueva_pass)

        user.save()
        messages.success(request, f'Datos del usuario "{user.username}" actualizados correctamente.')
        return redirect('gestion_usuarios')

    return redirect('gestion_usuarios')


@admin_required
def eliminar_personal(request, pk):
    """Desactiva la cuenta de un usuario del personal (Administrador o Cajero)."""
    user = get_object_or_404(Usuario, pk=pk)

    if user == request.user:
        messages.error(request, 'No puedes desactivar tu propia cuenta de administrador en uso.')
        return redirect('gestion_usuarios')

    user.is_active = False
    user.save()
    messages.warning(request, f'El usuario "{user.username}" ha sido desactivado del sistema.')
    return redirect('gestion_usuarios')


# --------------------------------------------
# CRUD DE GESTIÓN DE PRODUCTOS / INSUMOS
# --------------------------------------------

@admin_required
def gestion_inventario(request):
    """
    Redirige al inicio del panel de administración (inicio_admin),
    donde el CRUD de gestión de productos e insumos se encuentra centralizado.
    """
    return redirect('inicio_admin')


@admin_required
@require_POST
def crear_insumo(request):
    """Crea un nuevo insumo de materia prima."""
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'inicio_admin'
    codigo = request.POST.get('codigo', '').strip().upper()
    nombre = request.POST.get('nombre', '').strip()
    stock_sacos = request.POST.get('stock_sacos', 0)
    kilos_por_saco = request.POST.get('kilos_por_saco', 25)
    total_kg = request.POST.get('total_kg', None)
    proveedor_nombre = request.POST.get('proveedor_nombre', '').strip()
    precio_saco = request.POST.get('precio_saco', 0)

    if not nombre:
        messages.error(request, 'El nombre del producto es obligatorio.')
        return redirect(next_url)

    try:
        stock_sacos = int(stock_sacos)
    except (ValueError, TypeError):
        stock_sacos = 0

    try:
        kilos_por_saco = Decimal(str(kilos_por_saco).replace(',', '.'))
    except Exception:
        kilos_por_saco = Decimal('25.00')

    try:
        if total_kg:
            total_kg = Decimal(str(total_kg).replace(',', '.'))
        else:
            total_kg = stock_sacos * kilos_por_saco
    except Exception:
        total_kg = stock_sacos * kilos_por_saco

    try:
        precio_saco = Decimal(str(precio_saco).replace(',', '.').replace('$', '').strip())
    except Exception:
        precio_saco = Decimal('0.00')

    # Generar código si no se especificó
    if not codigo:
        ultimo = Insumo.objects.exclude(codigo='').order_by('-codigo').first()
        if ultimo and ultimo.codigo.startswith('NI'):
            try:
                num = int(ultimo.codigo.replace('NI', '')) + 1
                codigo = f'NI{num:03d}'
            except ValueError:
                codigo = f'NI{Insumo.objects.count() + 1:03d}'
        else:
            codigo = f'NI{Insumo.objects.count() + 1:03d}'

    if Insumo.objects.filter(codigo=codigo).exists():
        messages.error(request, f'Ya existe un producto con el ID {codigo}.')
        return redirect(next_url)

    Insumo.objects.create(
        codigo=codigo,
        nombre=nombre,
        stock_sacos=stock_sacos,
        kilos_por_saco=kilos_por_saco,
        total_kg=total_kg,
        proveedor_nombre=proveedor_nombre,
        precio_saco=precio_saco,
        tipo_insumo='Materia Prima',
        unidad_medida='Kg'
    )
    messages.success(request, f'Insumo "{nombre}" ({codigo}) agregado exitosamente.')
    return redirect(next_url)


@admin_required
@require_POST
def editar_insumo(request, pk):
    """Actualiza los datos de un insumo existente."""
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'inicio_admin'
    insumo = get_object_or_404(Insumo, pk=pk)

    codigo = request.POST.get('codigo', '').strip().upper()
    nombre = request.POST.get('nombre', '').strip()
    stock_sacos = request.POST.get('stock_sacos', 0)
    kilos_por_saco = request.POST.get('kilos_por_saco', insumo.kilos_por_saco)
    total_kg = request.POST.get('total_kg', None)
    proveedor_nombre = request.POST.get('proveedor_nombre', '').strip()
    precio_saco = request.POST.get('precio_saco', insumo.precio_saco)

    if not nombre:
        messages.error(request, 'El nombre del producto no puede estar vacío.')
        return redirect(next_url)

    if codigo and codigo != insumo.codigo:
        if Insumo.objects.filter(codigo=codigo).exclude(pk=pk).exists():
            messages.error(request, f'El código {codigo} ya está en uso por otro producto.')
            return redirect(next_url)
        insumo.codigo = codigo

    try:
        insumo.stock_sacos = int(stock_sacos)
    except (ValueError, TypeError):
        pass

    try:
        insumo.kilos_por_saco = Decimal(str(kilos_por_saco).replace(',', '.'))
    except Exception:
        pass

    try:
        if total_kg:
            insumo.total_kg = Decimal(str(total_kg).replace(',', '.'))
        else:
            insumo.total_kg = insumo.stock_sacos * insumo.kilos_por_saco
    except Exception:
        insumo.total_kg = insumo.stock_sacos * insumo.kilos_por_saco

    try:
        insumo.precio_saco = Decimal(str(precio_saco).replace(',', '.').replace('$', '').strip())
    except Exception:
        pass

    insumo.nombre = nombre
    insumo.proveedor_nombre = proveedor_nombre
    insumo.save()

    messages.success(request, f'Insumo "{insumo.nombre}" ({insumo.codigo}) actualizado correctamente.')
    return redirect(next_url)


@admin_required
@require_POST
def eliminar_insumo(request, pk):
    """Elimina un insumo del catálogo de productos/inventario."""
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'inicio_admin'
    insumo = get_object_or_404(Insumo, pk=pk)
    nombre = insumo.nombre
    codigo = insumo.codigo
    insumo.delete()
    messages.warning(request, f'El insumo "{nombre}" ({codigo}) ha sido eliminado.')
    return redirect(next_url)


# --------------------------------------------
# CRUD DE PRODUCTOS DE VENTA AL PÚBLICO
# --------------------------------------------

def _hora_o_none(texto):
    """'09:30' (o '09:30:00') -> time; None si no es una hora válida."""
    for formato in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime((texto or '').strip(), formato).time()
        except ValueError:
            continue
    return None


def _dias_del_formulario(request, campo):
    """Índices de día (0 = lunes ... 6 = domingo) marcados en las casillas `campo`."""
    indices = (_entero_o_none(v) for v in request.POST.getlist(campo))
    return {i for i in indices if i is not None and 0 <= i <= 6}


def _guardar_disponibilidad_del_producto(request, producto):
    """Aplica la "Disponibilidad" del formulario del panel: todo el día o un horario propio.

    - todo_el_dia: el producto no tiene turnos (se vende a cualquier hora).
    - horario: el admin define desde, hasta y los días (y un nombre, opcional). Se reutiliza un turno
      igual si ya existe; si no, se crea uno nuevo. Nunca se modifica un turno que usan otros productos.
    - mantener (o sin el campo): no se toca, p. ej. un producto con varios turnos cargados en /admin/.
    """
    modo = request.POST.get('disponibilidad', 'mantener')
    if modo == 'todo_el_dia':
        producto.turnos.clear()
        return
    if modo != 'horario':
        return

    nombre = request.POST.get('turno_nombre', '').strip()[:50]
    desde = _hora_o_none(request.POST.get('turno_desde'))
    hasta = _hora_o_none(request.POST.get('turno_hasta'))
    dias = _dias_del_formulario(request, 'turno_dias')
    if desde is None or hasta is None:
        messages.error(request, 'Disponibilidad: indica la hora desde y hasta. No se cambió.')
        return

    dias_por_campo = {campo: (i in dias) for i, campo in enumerate(Turno.CAMPOS_DIAS)}
    candidato = Turno(nombre=nombre, hora_inicio=desde, hora_fin=hasta, **dias_por_campo)
    try:
        candidato.clean()
    except ValidationError as error:
        messages.error(request, f'Disponibilidad: {error.messages[0]} No se cambió.')
        return

    # ¿Ya hay un turno con exactamente ese horario y esos días (y ese nombre, si se puso uno)?
    iguales = Turno.objects.filter(hora_inicio=desde, hora_fin=hasta, **dias_por_campo)
    if nombre:
        iguales = iguales.filter(nombre__iexact=nombre)
    turno = iguales.first()

    if turno is None:
        if nombre and Turno.objects.filter(nombre__iexact=nombre).exists():
            messages.error(
                request,
                f'Ya existe un turno llamado "{nombre}" con otro horario o días. '
                'Usa otro nombre o déjalo en blanco. No se cambió.',
            )
            return
        # Sin nombre, el turno se llama como su horario: "10:00 a 13:00 (sábado y domingo)".
        base = nombre or f'{candidato.horario_texto} ({candidato.dias_texto})'[:50]
        candidato.nombre = base
        sufijo = 2
        while Turno.objects.filter(nombre__iexact=candidato.nombre).exists():
            candidato.nombre = f'{base[:45]} #{sufijo}'
            sufijo += 1
        candidato.save()
        turno = candidato

    if not turno.activo:
        turno.activo = True
        turno.save(update_fields=['activo'])
    producto.turnos.set([turno])


@admin_required
@require_POST
def crear_producto(request):
    """Crea un nuevo producto para el catálogo de venta de la panadería."""
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'inicio_admin'
    nombre = request.POST.get('nombre', '').strip()
    categoria_id = request.POST.get('categoria_id')
    precio = request.POST.get('precio', 0)
    stock = request.POST.get('stock', 0)
    stock_critico = request.POST.get('stock_critico', 10)
    unidad_medida = request.POST.get('unidad_medida', 'unid')
    descripcion = request.POST.get('descripcion', '').strip()

    if not nombre or not categoria_id:
        messages.error(request, 'El nombre y la categoría del producto son obligatorios.')
        return redirect(next_url)

    categoria = get_object_or_404(Categoria, pk=categoria_id)

    try:
        precio = Decimal(str(precio).replace(',', '.').replace('$', '').strip())
    except Exception:
        precio = Decimal('0.00')

    try:
        stock = int(stock)
    except (ValueError, TypeError):
        stock = 0

    try:
        stock_critico = int(stock_critico)
    except (ValueError, TypeError):
        stock_critico = 10

    producto = Producto.objects.create(
        nombre=nombre,
        categoria=categoria,
        precio=precio,
        stock=stock,
        stock_critico=stock_critico,
        unidad_medida=unidad_medida,
        descripcion=descripcion,
        activo=True
    )
    _guardar_disponibilidad_del_producto(request, producto)
    messages.success(request, f'Producto "{nombre}" agregado exitosamente al catálogo.')
    return redirect(next_url)


@admin_required
@require_POST
def editar_producto(request, pk):
    """Actualiza la información de un producto de venta existente."""
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'inicio_admin'
    producto = get_object_or_404(Producto, pk=pk)

    nombre = request.POST.get('nombre', '').strip()
    categoria_id = request.POST.get('categoria_id')
    precio = request.POST.get('precio', producto.precio)
    stock = request.POST.get('stock', producto.stock)
    stock_critico = request.POST.get('stock_critico', producto.stock_critico)
    unidad_medida = request.POST.get('unidad_medida', producto.unidad_medida)
    descripcion = request.POST.get('descripcion', '').strip()
    activo = request.POST.get('activo') in ['1', 'true', 'on', True]

    if not nombre:
        messages.error(request, 'El nombre del producto no puede quedar vacío.')
        return redirect(next_url)

    if categoria_id:
        producto.categoria = get_object_or_404(Categoria, pk=categoria_id)

    try:
        producto.precio = Decimal(str(precio).replace(',', '.').replace('$', '').strip())
    except Exception:
        pass

    try:
        producto.stock = int(stock)
    except (ValueError, TypeError):
        pass

    try:
        producto.stock_critico = int(stock_critico)
    except (ValueError, TypeError):
        pass

    producto.nombre = nombre
    producto.unidad_medida = unidad_medida
    producto.descripcion = descripcion
    producto.activo = activo
    producto.save()
    _guardar_disponibilidad_del_producto(request, producto)

    messages.success(request, f'Producto "{producto.nombre}" actualizado correctamente.')
    return redirect(next_url)


@admin_required
@require_POST
def eliminar_producto(request, pk):
    """Elimina o desactiva un producto de venta."""
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'inicio_admin'
    producto = get_object_or_404(Producto, pk=pk)
    nombre = producto.nombre

    if producto.detallepedido_set.exists():
        producto.activo = False
        producto.save()
        messages.warning(request, f'El producto "{nombre}" tiene ventas asociadas y ha sido marcado como inactivo.')
    else:
        producto.delete()
        messages.warning(request, f'El producto "{nombre}" ha sido eliminado del catálogo.')
    return redirect(next_url)

# ==========================================
# FUNCIONES DE ADMINISTRADOR
# ==========================================

# ==========================================
# FUNCIONES DE CAJERO
# ==========================================

# ------------------------------------------
# DECORADOR Y CONTROL DE ACCESO CAJERO
# ------------------------------------------
def cajero_required(view_func):
    """Verifica que el usuario esté autenticado y sea Cajero o Administrador."""
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Debe iniciar sesión para acceder al sistema POS.')
            return redirect('login')
        if not (request.user.es_cajero or request.user.es_administrador):
            messages.error(request, 'No tiene permisos de cajero para acceder a esta área.')
            return redirect('inicio')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@cajero_required
def inicio_cajero(request):
    """Vista principal del Terminal POS / Punto de Venta."""
    categorias = Categoria.objects.all().order_by('nombre')
    productos = Producto.objects.filter(activo=True).order_by('nombre')

    contexto = {
        'categorias': categorias,
        'productos': productos,
    }
    return render(request, 'core/inicio_cajero.html', contexto)

# ==========================================
# FUNCIONES DE CAJERO
# ==========================================


def login_view(request):
    """
    Controlador de inicio de sesión con soporte para:
    - Autenticación por Correo Electrónico o Nombre de Usuario.
    - Redirección según rol (Administrador, Cajero, Cliente).
    - Redirección previa con parámetro ?next=/...
    """
    # Si el usuario ya está conectado, redirigir a su vista correspondiente
    if request.user.is_authenticated:
        return redireccionar_por_rol(request.user)

    next_url = request.GET.get('next') or request.POST.get('next')

    if request.method == 'POST':
        identificador = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if not identificador or not password:
            messages.error(request, 'Por favor, ingrese su correo o usuario y contraseña.')
            return render(request, 'core/login.html', {'next': next_url})

        # Buscar si el dato ingresado corresponde al email o al username
        usuario_encontrado = Usuario.objects.filter(
            Q(username__iexact=identificador) | Q(email__iexact=identificador)
        ).first()

        username_auth = usuario_encontrado.username if usuario_encontrado else identificador

        # Autenticación de Django
        user = authenticate(request, username=username_auth, password=password)

        if user is not None:
            if not user.is_active:
                messages.error(request, 'Esta cuenta se encuentra desactivada.')
                return render(request, 'core/login.html', {'next': next_url})

            login(request, user)

            # Redirección personalizada o según rol
            if next_url and next_url.startswith('/'):
                return redirect(next_url)

            return redireccionar_por_rol(user)
        else:
            messages.error(request, 'Credenciales incorrectas. Verifique sus datos e intente nuevamente.')

    return render(request, 'core/login.html', {'next': next_url})


def logout_view(request):
    """Cierra la sesión y redirige a la página de inicio."""
    logout(request)
    messages.info(request, 'Has cerrado sesión correctamente.')
    return redirect('inicio')


def registro_view(request):
    """
    Vista de registro público exclusiva para clientes (Formulario en 2 Pasos).
    - Asigna obligatoriamente rol='CLIENTE'.
    - Crea Usuario, Perfil Cliente y registro inicial de PuntosFidelizacion (0 pts).
    - Inicia sesión automáticamente tras el registro y redirige a 'inicio'.
    """
    if request.user.is_authenticated:
        return redirect('inicio')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        telefono = request.POST.get('telefono', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        # Datos de domicilio
        region = request.POST.get('region', '').strip()
        comuna = request.POST.get('comuna', '').strip()
        direccion1 = request.POST.get('direccion1', '').strip()
        direccion2 = request.POST.get('direccion2', '').strip()
        indicaciones = request.POST.get('indicaciones', '').strip()

        # Validaciones de backend
        errores = []

        if not (username and first_name and last_name and email and telefono and password and password_confirm and region and comuna and direccion1):
            errores.append('Por favor completa todos los campos obligatorios.')

        if password != password_confirm:
            errores.append('Las contraseñas no coinciden.')

        if len(password) < 6:
            errores.append('La contraseña debe tener al menos 6 caracteres.')

        if Usuario.objects.filter(username__iexact=username).exists():
            errores.append('Ya existe una cuenta registrada con este nombre de usuario.')

        if email and Usuario.objects.filter(email__iexact=email).exists():
            errores.append('Ya existe una cuenta con este correo electrónico.')

        if errores:
            for err in errores:
                messages.error(request, err)
            return render(request, 'core/registro.html', {
                'datos': {
                    'username': username,
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'telefono': telefono,
                    'region': region,
                    'comuna': comuna,
                    'direccion1': direccion1,
                    'direccion2': direccion2,
                    'indicaciones': indicaciones,
                }
            })

        try:
            with transaction.atomic():
                # 1. Crear Usuario cliente
                user = Usuario.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    rol='CLIENTE'
                )

                # 2. Formatear dirección para el perfil
                partes_dir = [direccion1]
                if direccion2:
                    partes_dir.append(direccion2)
                partes_dir.append(comuna)
                partes_dir.append(region)
                direccion_completa = ", ".join(partes_dir)
                if indicaciones:
                    direccion_completa += f" (Ref: {indicaciones})"

                # 3. Crear Perfil Cliente
                cliente = Cliente.objects.create(
                    user=user,
                    direccion=direccion_completa[:255],
                    telefono=telefono or "+56 9"
                )

                # 4. Inicializar bolsa de puntos de fidelización
                PuntosFidelizacion.objects.create(
                    cliente=cliente,
                    puntos_acumulados=0
                )

                # 5. Iniciar sesión automática
                login(request, user)
                messages.success(request, f'¡Bienvenido/a a Los Tres Spa, {first_name}! Tu cuenta ha sido creada exitosamente.')
                return redirect('inicio')

        except Exception as e:
            messages.error(request, f'Ocurrió un error al procesar el registro: {str(e)}')
            return render(request, 'core/registro.html', {'datos': request.POST})

    return render(request, 'core/registro.html')

# ---------------------------------------------------------------
# APARTADO TERMINOS Y CONDICIONES / POLÍTICAS DE PRIVACIDAD
# ---------------------------------------------------------------

def terminos_condiciones(request):
    """Muestra la página de Términos y Condiciones de Uso."""
    return render(request, 'core/terminos_condiciones.html')

def politicas_privacidad(request):
    """Muestra la página de Políticas de Privacidad y Protección de Datos."""
    return render(request, 'core/politicas_privacidad.html')
