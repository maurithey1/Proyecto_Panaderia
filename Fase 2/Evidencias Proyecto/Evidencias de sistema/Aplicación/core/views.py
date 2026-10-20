import re
import time
import unicodedata
import json
from datetime import datetime, timedelta
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.validators import validate_email
from django.conf import settings
from django.core.cache import cache

from .webpay import obtener_transaccion_webpay, TIPOS_PAGO_WEBPAY
from .models import (
    Categoria, Cliente, Cajero, DetallePedido, Insumo, Pago, Pedido, Producto,
    ProveedorInsumo, PuntosFidelizacion, Turno, Usuario, Administrador, ProduccionDiaria
)
from .templatetags.tienda import TIENDA
from .templatetags.formato import clp
from . import pedidos
from . import caja as caja_pos
from .disponibilidad import esta_disponible, resumen as resumen_de_disponibilidad
from .retiro import ahora as ahora_en_chile, dias_de_retiro, texto_retiro, validar_retiro
from .zona_despacho import leer_coordenadas, punto_en_zona

# ==========================================
# FUNCIONES DE CLIENTE: CATÁLOGO, CARRITO Y COMPRA
# ==========================================

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
    _expirar_pedidos_webpay_vencidos()
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
    """Índice de la primera palabra que EMPIEZA con lo buscado, o None."""
    formas = {palabra_buscada}
    for sufijo in ('es', 's'):
        if palabra_buscada.endswith(sufijo) and len(palabra_buscada) - len(sufijo) >= 3:
            formas.add(palabra_buscada[:-len(sufijo)])
    for indice, palabra in enumerate(palabras):
        if any(palabra.startswith(forma) for forma in formas):
            return indice
    return None


def _buscar_productos(productos, busqueda):
    """Productos que calzan con la búsqueda, del más al menos relevante."""
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
    _expirar_pedidos_webpay_vencidos()
    categorias = Categoria.objects.filter(productos__activo=True).distinct().order_by('nombre')

    productos = Producto.objects.filter(activo=True).prefetch_related(_turnos_activos()).order_by(
        Case(When(stock__gt=0, then=Value(0)), default=Value(1), output_field=IntegerField()),
        'nombre',
    )

    turnos = list(Turno.objects.filter(activo=True, productos__activo=True).distinct())
    ahora_cl = ahora_en_chile()
    turnos_ahora = [t.pk for t in turnos if t.rige_en(ahora_cl)]
    turno_actual = None
    turno_id = _entero_o_none(request.GET.get('turno', ''))
    if turno_id is not None:
        turno_actual = next((t for t in turnos if t.pk == turno_id), None)
    if turno_actual:
        sin_turnos = Producto.objects.exclude(turnos__activo=True).values('pk')
        en_el_turno = Producto.objects.filter(turnos=turno_actual).values('pk')
        productos = productos.filter(Q(pk__in=sin_turnos) | Q(pk__in=en_el_turno))

    categoria_actual = None
    categoria_id = _entero_o_none(request.GET.get('categoria', ''))
    if categoria_id is not None:
        categoria_actual = categorias.filter(pk=categoria_id).first()
        if categoria_actual:
            productos = productos.filter(categoria=categoria_actual)

    parametros = []
    if categoria_actual:
        parametros.append(f'categoria={categoria_actual.pk}')
    if turno_actual:
        parametros.append(f'turno={turno_actual.pk}')
    filtros_qs = ('?' + '&'.join(parametros)) if parametros else ''

    busqueda = request.GET.get('q', '').strip()[:BUSQUEDA_MAX_LARGO]
    if busqueda:
        productos = _buscar_productos(productos, busqueda)

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
    """Muestra el historial de compras y pedidos realizados por el cliente autenticado."""
    _expirar_pedidos_webpay_vencidos()

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

    productos = Producto.objects.filter(pk__in=cantidades.keys(), activo=True)
    total_monto = sum(p.precio * cantidades[p.pk] for p in productos if p.pk in cantidades)
    
    producto_obj = next((p for p in productos if p.pk == int(producto_id)), None)
    subtotal_item = (producto_obj.precio * cant_unidades_item) if producto_obj else 0

    return JsonResponse({
        'ok': True,
        'producto_id': int(producto_id),
        'cantidad_item': cant_unidades_item,
        'cant_carrito': len(carrito),
        'subtotal_item_clp': clp(subtotal_item),
        'total_carrito_clp': clp(total_monto),
        'mensaje': mensaje,
        'tipo_mensaje': tipo_mensaje,
    })


@require_POST
def agregar_al_carrito(request):
    _expirar_pedidos_webpay_vencidos()
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
    _expirar_pedidos_webpay_vencidos()
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

    direccion_guardada = ''
    if request.user.is_authenticated:
        direccion_guardada = (
            Cliente.objects.filter(user=request.user)
            .values_list('direccion', flat=True)
            .first()
        ) or ''

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
    _expirar_pedidos_webpay_vencidos()
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
        if not re.search(r'\d|\bs\s*/?\s*n\b|\bsin\s+n[uú]mero\b', direccion, re.IGNORECASE):
            messages.error(request, 'Agrega el número de tu dirección (o S/N si no tiene).')
            return redirect('carrito')

        detalles = request.POST.get('detalles_entrega', '').strip()
        if detalles:
            direccion = f'{direccion} ({detalles})'
        if len(direccion) > 255:
            messages.error(request, 'La dirección y los detalles son demasiado largos (máximo 255 caracteres).')
            return redirect('carrito')

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

        pago = Pago.objects.create(
            pedido=pedido,
            monto=total,
            metodo='Webpay Plus',
            estado='PENDIENTE',
            codigo_autorizacion='',
        )

    buy_order = f"ORD-{pedido.pk}"
    if not request.session.session_key:
        request.session.save()
    session_id = request.session.session_key
    amount = int(round(float(total)))
    return_url = request.build_absolute_uri('/carrito/webpay-confirmar/')

    tx = obtener_transaccion_webpay()
    try:
        response = tx.create(buy_order, session_id, amount, return_url)
    except Exception:
        pedidos.cancelar_pendiente(pedido.pk, 'FALLIDO')
        messages.error(
            request,
            'No pudimos conectar con Transbank. No se realizó ningún cobro: intenta de nuevo en unos minutos.',
        )
        return redirect('carrito')

    token_ws = response.get('token')
    pago.codigo_autorizacion = token_ws
    pago.save(update_fields=['codigo_autorizacion'])
    request.session['webpay_pedido_id'] = pedido.pk
    request.session['webpay_token'] = token_ws

    return redirect(f"{response['url']}?token_ws={token_ws}")


WEBPAY_VIGENCIA_MIN = 20
WEBPAY_TOPE_SIN_RESPUESTA_HORAS = 24
WEBPAY_CONCILIAR_POR_VUELTA = 3
WEBPAY_REINTENTO_SEG = 60
WEBPAY_TOKEN_MIN = 40


def _reembolso_aceptado(respuesta):
    if not isinstance(respuesta, dict):
        return False
    tipo = respuesta.get('type')
    if tipo == 'REVERSED':
        return respuesta.get('response_code', 0) == 0
    if tipo == 'NULLIFIED':
        return respuesta.get('response_code') == 0
    return False


def _reembolsar_pago(tx, pedido_id, token, monto):
    try:
        respuesta = tx.refund(token, int(monto))
    except Exception:
        respuesta = None
    if not _reembolso_aceptado(respuesta):
        pedidos.marcar_pago(pedido_id, 'REEMBOLSO_PENDIENTE', codigo_autorizacion=token)
        return False
    pedidos.marcar_pago(pedido_id, 'REEMBOLSADO', codigo_autorizacion=token)
    return True


def _datos_de_pago(respuesta):
    tipo = TIPOS_PAGO_WEBPAY.get(respuesta.get('payment_type_code', ''), 'Tarjeta')
    return f'Webpay Plus ({tipo})', respuesta.get('authorization_code', '')


def _conciliar_pedido_vencido(tx, pedido):
    token = pedido.pago.codigo_autorizacion or ''
    if len(token) < WEBPAY_TOKEN_MIN:
        pedidos.cancelar_pendiente(pedido.pk, 'EXPIRADO')
        return

    try:
        respuesta = tx.status(token)
    except Exception:
        edad = timezone.now() - pedido.fecha
        if edad > timedelta(hours=WEBPAY_TOPE_SIN_RESPUESTA_HORAS):
            pedidos.cancelar_pendiente(pedido.pk, 'EXPIRADO')
        else:
            cache.set(f'webpay-conciliar-{pedido.pk}', 1, WEBPAY_REINTENTO_SEG)
        return

    if respuesta.get('status') == 'AUTHORIZED' and respuesta.get('response_code') == 0:
        metodo, codigo = _datos_de_pago(respuesta)
        resultado, _ = pedidos.aprobar_pago(pedido.pk, respuesta.get('amount', 0), metodo, codigo)
        if resultado == pedidos.MONTO_DISTINTO:
            _reembolsar_pago(tx, pedido.pk, token, respuesta.get('amount', 0))
        return

    pedidos.cancelar_pendiente(pedido.pk, 'EXPIRADO')


def _expirar_pedidos_webpay_vencidos():
    limite = timezone.now() - timedelta(minutes=WEBPAY_VIGENCIA_MIN)
    vencidos = list(
        Pedido.objects.filter(estado='PENDIENTE', fecha__lt=limite, pago__metodo__startswith='Webpay')
        .select_related('pago').order_by('pk')
    )
    if not vencidos:
        return
    tx = obtener_transaccion_webpay()
    consultados = 0
    for pedido in vencidos:
        if cache.get(f'webpay-conciliar-{pedido.pk}'):
            continue
        if consultados >= WEBPAY_CONCILIAR_POR_VUELTA:
            break
        consultados += 1
        _conciliar_pedido_vencido(tx, pedido)


def _respuesta_resuelta_webpay(tx, token_ws, intentos=3, espera=1.0):
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


def _es_su_pedido(request, pedido):
    if request.session.get('webpay_pedido_id') == pedido.pk:
        return True
    return (
        request.user.is_authenticated
        and Pedido.objects.filter(pk=pedido.pk, cliente__user=request.user).exists()
    )


@require_POST
def iniciar_pago_webpay(request, pedido_id=None):
    if pedido_id is None:
        pedido_id = request.session.get('webpay_pedido_id')

    pedido = get_object_or_404(Pedido, pk=pedido_id)
    if not _es_su_pedido(request, pedido):
        raise Http404

    if pedido.estado == 'PAGADO':
        messages.info(request, 'Este pedido ya se encuentra pagado.')
        return redirect('boleta_simulada', pedido_id=pedido.pk)
    if pedido.estado != 'PENDIENTE':
        messages.error(request, 'Este pedido ya no está disponible para pagar. Vuelve a armar tu carrito.')
        return redirect('carrito')

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
        print(f"Error Webpay: {str(e)}") 
        messages.error(request, "No fue posible conectar con la pasarela de pago. Por favor, intente nuevamente.")
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
    token_ws = request.POST.get('token_ws') or request.GET.get('token_ws')
    tbk_token = request.POST.get('TBK_TOKEN') or request.GET.get('TBK_TOKEN')
    tbk_orden_compra = request.POST.get('TBK_ORDEN_COMPRA') or request.GET.get('TBK_ORDEN_COMPRA')

    # Recuperar ID de pedido desde session o token
    pedido_id_session = request.session.get('webpay_pedido_id')

    # Helper interno para determinar si redirigir al Terminal POS o al Carrito Web
    def _redirigir_segun_origen(pedido_obj=None, mensaje="", tipo_msg="warning"):
        if mensaje:
            if tipo_msg == 'error':
                messages.error(request, mensaje)
            elif tipo_msg == 'info':
                messages.info(request, mensaje)
            elif tipo_msg == 'success':
                messages.success(request, mensaje)
            else:
                messages.warning(request, mensaje)

        es_pos = False
        if pedido_obj and getattr(pedido_obj, 'canal', None) == 'POS':
            es_pos = True
        elif request.user.is_authenticated and (getattr(request.user, 'es_cajero', False) or getattr(request.user, 'es_administrador', False)):
            es_pos = True

        return redirect('inicio_cajero' if es_pos else 'carrito')

    # 1. Pago cancelado voluntariamente por el usuario en Transbank
    if tbk_token:
        tokens = [t for t in (tbk_token, token_ws) if t]
        pedido = (
            Pedido.objects.filter(estado='PENDIENTE', pago__codigo_autorizacion__in=tokens)
            .first()
        )
        if not pedido and pedido_id_session:
            pedido = Pedido.objects.filter(pk=pedido_id_session, estado='PENDIENTE').first()

        if pedido:
            pedidos.cancelar_pendiente(pedido.pk, 'CANCELADO')
        
        request.session.pop('webpay_pedido_id', None)
        return _redirigir_segun_origen(
            pedido,
            'El pago no se completó en Webpay. Se canceló la operación y el stock reservado ha vuelto al inventario.',
            'warning'
        )

    # 2. Tiempo de espera agotado (Timeout en Transbank)
    if not token_ws and not tbk_token and tbk_orden_compra:
        pedido_id = None
        if tbk_orden_compra.startswith('ORD-'):
            pedido_id = _entero_o_none(tbk_orden_compra[len('ORD-'):])
        if not pedido_id:
            pedido_id = pedido_id_session

        pedido = Pedido.objects.filter(pk=pedido_id, estado='PENDIENTE').first() if pedido_id else None
        if pedido:
            pedidos.cancelar_pendiente(pedido.pk, 'EXPIRADO')
        
        request.session.pop('webpay_pedido_id', None)
        return _redirigir_segun_origen(
            pedido,
            'Se agotó el tiempo límite para pagar en Webpay. La compra fue anulada y el stock está disponible.',
            'warning'
        )

    # 3. Sin token de confirmación de Transbank (Retorno con error o expirado)
    if not token_ws:
        pedido = Pedido.objects.filter(pk=pedido_id_session, estado='PENDIENTE').first() if pedido_id_session else None
        if pedido:
            pedidos.cancelar_pendiente(pedido.pk, 'EXPIRADO')
        
        request.session.pop('webpay_pedido_id', None)
        return _redirigir_segun_origen(
            pedido,
            'No se recibió el token de confirmación de Transbank. La transacción fue anulada y el stock restaurado.',
            'error'
        )

    tx = obtener_transaccion_webpay()
    try:
        response = tx.commit(token_ws)
    except Exception:
        response = _respuesta_resuelta_webpay(tx, token_ws)
        if response is None:
            pedido = Pedido.objects.filter(pk=pedido_id_session, estado='PENDIENTE').first() if pedido_id_session else None
            return _redirigir_segun_origen(
                pedido,
                'Estamos confirmando tu pago con Transbank. Espera unos segundos y revisa el estado de tu pedido.',
                'info'
            )

    buy_order = response.get('buy_order', '')
    pedido_id = None
    if buy_order.startswith('ORD-'):
        try:
            pedido_id = int(buy_order.replace('ORD-', ''))
        except ValueError:
            pass
    if not pedido_id:
        pedido_id = pedido_id_session

    if not pedido_id or not Pedido.objects.filter(pk=pedido_id).exists():
        raise Http404

    pedido = Pedido.objects.get(pk=pedido_id)
    response_code = response.get('response_code')
    status = response.get('status')

    # 4. Pago Aprobado Exitosamente
    if response_code == 0 and status == 'AUTHORIZED':
        metodo, cod_autorizacion = _datos_de_pago(response)
        monto = response.get('amount', 0)
        resultado, pedido = pedidos.aprobar_pago(pedido_id, monto, metodo, cod_autorizacion)

        if resultado in (pedidos.PAGADO, pedidos.YA_PAGADO, pedidos.REACTIVADO):
            request.session['carrito'] = {}
            request.session.pop('webpay_pedido_id', None)

            boletas = request.session.get('boletas_simuladas', [])
            if not isinstance(boletas, list):
                boletas = []
            if pedido.pk not in boletas:
                boletas.append(pedido.pk)
            request.session['boletas_simuladas'] = boletas

            messages.success(request, f'¡Pago aprobado con éxito en Webpay! Venta N° {pedido.pk} realizada. Autorización: {cod_autorizacion}')
            
            # Si la venta se hizo desde la Terminal POS, vuelve a la Terminal del Cajero
            if pedido.canal == 'POS' or getattr(request.user, 'es_cajero', False) or getattr(request.user, 'es_administrador', False):
                return redirect('inicio_cajero')

            return redirect('boleta_simulada', pedido_id=pedido.pk)

        # Reembolso en caso de pago tardío o descalce
        reembolsado = _reembolsar_pago(tx, pedido.pk, token_ws, monto)
        request.session.pop('webpay_pedido_id', None)
        motivo = 'El tiempo del pedido venció' if resultado == pedidos.SIN_STOCK else 'El monto no coincide'
        msg_final = f'{motivo}. Se devolvió el pago automáticamente.' if reembolsado else f'{motivo}. Contacta soporte con la Orden N° {pedido.pk}.'
        return _redirigir_segun_origen(pedido, msg_final, 'warning' if reembolsado else 'error')

    # 5. Pago Rechazado por Transbank / Banco
    pedidos.cancelar_pendiente(pedido.pk, 'RECHAZADO')
    request.session.pop('webpay_pedido_id', None)
    return _redirigir_segun_origen(
        pedido,
        'El pago fue rechazado por Webpay o el banco emisor. La venta fue anulada y el stock restaurado.',
        'error'
    )


def boleta_simulada(request, pedido_id):
    boletas = request.session.get('boletas_simuladas', [])
    autorizada = isinstance(boletas, list) and pedido_id in boletas
    if not autorizada and request.user.is_authenticated:
        autorizada = Pedido.objects.filter(
            pk=pedido_id,
            cliente__user=request.user,
        ).exists()
    if not autorizada and (getattr(request.user, 'es_cajero', False) or getattr(request.user, 'es_administrador', False)):
        autorizada = True

    if not autorizada:
        raise Http404

    pedido = get_object_or_404(
        Pedido.objects.prefetch_related('detalles__producto').select_related('pago'),
        pk=pedido_id,
    )

    # Si un Cajero o Administrador intenta ver una boleta simulada, usa el layout base_cajero
    template_base = 'core/base_cajero.html' if (getattr(request.user, 'es_cajero', False) or getattr(request.user, 'es_administrador', False)) else 'core/base.html'

    return render(request, 'core/boleta_simulada.html', {
        'pedido': pedido,
        'template_base': template_base,
    })


def producto_detalle(request, pk):
    producto = get_object_or_404(
        Producto.objects.select_related('categoria').prefetch_related(_turnos_activos()),
        pk=pk, activo=True,
    )
    turnos = list(producto.turnos.all())
    disponible_ahora, vuelve = resumen_de_disponibilidad(turnos, ahora_en_chile())
    plantilla = 'core/_producto_detalle.html' if request.GET.get('parcial') == '1' else 'core/producto.html'
    return render(request, plantilla, {
        'p': producto,
        'turnos_del_producto': turnos,
        'disponible_ahora': disponible_ahora,
        'vuelve': vuelve,
    })

# ==========================================
# FUNCIONES DE CLIENTE: CATÁLOGO, CARRITO Y COMPRA
# ==========================================

# Pagina informativa del local, con mapa y datos de contacto

def local(request):
    return render(request, 'core/local.html')

# Funcion de redireccionamiento según el rol del usuario autenticado

def redireccionar_por_rol(user):
    if getattr(user, 'es_administrador', False):
        return redirect('inicio_admin')
    elif getattr(user, 'es_cajero', False):
        return redirect('inicio_cajero')
    return redirect('inicio')

# ==========================================
# FUNCIONES DE ADMINISTRADOR: GESTIÓN DE USUARIOS, INVENTARIO Y REPORTES
# ==========================================

def admin_required(view_func):
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
    productos_stock = Producto.objects.filter(activo=True).order_by('nombre')
    tarifas_proveedores = ProveedorInsumo.objects.select_related('proveedor', 'insumo').all()

    contexto = {
        'productos_stock': productos_stock,
        'tarifas_proveedores': tarifas_proveedores,
    }
    return render(request, 'core/inicio_admin.html', contexto)


@admin_required
def gestion_usuarios(request):
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
@require_POST
def crear_personal(request):
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
@require_POST
def editar_personal(request, pk):
    user = get_object_or_404(Usuario, pk=pk)

    user.first_name = request.POST.get('first_name', '').strip()
    user.last_name = request.POST.get('last_name', '').strip()
    user.email = request.POST.get('email', '').strip().lower()
    nuevo_rol = request.POST.get('rol', user.rol)
    num_caja = request.POST.get('num_caja_asignada', 1)

    if nuevo_rol != user.rol:
        user.rol = nuevo_rol
        if nuevo_rol == 'ADMINISTRADOR':
            Cajero.objects.filter(user=user).delete()
            Administrador.objects.get_or_create(user=user, defaults={'nivel_acceso': 'TOTAL'})
        elif nuevo_rol == 'CAJERO':
            Administrador.objects.filter(user=user).delete()
            Cajero.objects.get_or_create(user=user, defaults={'num_caja_asignada': num_caja})

    if user.rol == 'CAJERO':
        cajero, _ = Cajero.objects.get_or_create(user=user)
        try:
            cajero.num_caja_asignada = int(num_caja)
            cajero.save()
        except (ValueError, TypeError):
            pass

    nueva_pass = request.POST.get('password', '').strip()
    if nueva_pass:
        user.set_password(nueva_pass)

    user.save()
    messages.success(request, f'Datos del usuario "{user.username}" actualizados correctamente.')
    return redirect('gestion_usuarios')


@admin_required
@require_POST
def eliminar_personal(request, pk):
    user = get_object_or_404(Usuario, pk=pk)

    if user == request.user:
        messages.error(request, 'No puedes desactivar tu propia cuenta de administrador en uso.')
        return redirect('gestion_usuarios')

    user.is_active = False
    user.save()
    messages.warning(request, f'El usuario "{user.username}" ha sido desactivado del sistema.')
    return redirect('gestion_usuarios')


@admin_required
@require_POST
def desactivar_usuario(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    if usuario.pk == request.user.pk:
        messages.error(request, 'No puedes desactivar tu propia cuenta de administrador.')
        return redirect('gestion_usuarios')

    usuario.is_active = False
    usuario.save()
    messages.success(request, f'El usuario {usuario.username} ha sido desactivado.')
    return redirect('gestion_usuarios')


@admin_required
def gestion_inventario(request):
    insumos = Insumo.objects.all().order_by('codigo', 'nombre')

    ultimo = Insumo.objects.exclude(codigo='').order_by('-codigo').first()
    siguiente_id = 'NI001'
    if ultimo and ultimo.codigo.startswith('NI'):
        try:
            num = int(ultimo.codigo.replace('NI', '')) + 1
            siguiente_id = f'NI{num:03d}'
        except ValueError:
            siguiente_id = f'NI{insumos.count() + 1:03d}'

    todos_los_productos = (
        Producto.objects.select_related('categoria').prefetch_related('turnos')
        .order_by('categoria__nombre', 'nombre')
    )
    categorias_productos = Categoria.objects.all().order_by('nombre')

    dias_semana = [
        ('L', 'Lunes'),
        ('M', 'Martes'),
        ('X', 'Miércoles'),
        ('J', 'Jueves'),
        ('V', 'Viernes'),
        ('S', 'Sábado'),
        ('D', 'Domingo'),
    ]

    contexto = {
        'insumos': insumos,
        'siguiente_id': siguiente_id,
        'todos_los_productos': todos_los_productos,
        'categorias_productos': categorias_productos,
        'dias_semana': dias_semana,
    }
    return render(request, 'core/tabla_crud_insumos.html', contexto)


@admin_required
@require_POST
def crear_insumo(request):
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
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'inicio_admin'
    insumo = get_object_or_404(Insumo, pk=pk)
    nombre = insumo.nombre
    codigo = insumo.codigo
    insumo.delete()
    messages.warning(request, f'El insumo "{nombre}" ({codigo}) ha sido eliminado.')
    return redirect(next_url)


def _hora_o_none(texto):
    for formato in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime((texto or '').strip(), formato).time()
        except ValueError:
            continue
    return None


def _dias_del_formulario(request, campo):
    indices = (_entero_o_none(v) for v in request.POST.getlist(campo))
    return {i for i in indices if i is not None and 0 <= i <= 6}


class DisponibilidadInvalida(Exception):
    pass


def _disponibilidad_del_formulario(request):
    modo = request.POST.get('disponibilidad', 'mantener')
    if modo == 'todo_el_dia':
        return ('todo_el_dia',)
    if modo != 'horario':
        return ('mantener',)

    nombre = request.POST.get('turno_nombre', '').strip()[:50]
    desde = _hora_o_none(request.POST.get('turno_desde'))
    hasta = _hora_o_none(request.POST.get('turno_hasta'))
    if desde is None or hasta is None:
        raise DisponibilidadInvalida('Indica la hora desde y hasta.')

    dias = _dias_del_formulario(request, 'turno_dias')
    dias_por_campo = {campo: (i in dias) for i, campo in enumerate(Turno.CAMPOS_DIAS)}
    try:
        Turno(nombre=nombre, hora_inicio=desde, hora_fin=hasta, **dias_por_campo).clean()
    except ValidationError as error:
        raise DisponibilidadInvalida(error.messages[0])

    _turno_igual(nombre, desde, hasta, dias_por_campo)
    return ('horario', nombre, desde, hasta, dias_por_campo)


def _turno_igual(nombre, desde, hasta, dias_por_campo):
    iguales = Turno.objects.filter(hora_inicio=desde, hora_fin=hasta, **dias_por_campo)
    if nombre:
        iguales = iguales.filter(nombre__iexact=nombre)

    activo = iguales.filter(activo=True).first()
    if activo is not None:
        return activo
    sin_uso = iguales.filter(activo=False).annotate(usos=Count('productos')).filter(usos=0).first()
    if sin_uso is not None:
        return sin_uso

    if nombre:
        existente = Turno.objects.filter(nombre__iexact=nombre).first()
        if existente is not None and not existente.activo:
            raise DisponibilidadInvalida(
                f'Ya existe un turno desactivado llamado "{nombre}" que usan otros productos. '
                'Actívalo en /admin/ o usa otro nombre.'
            )
        if existente is not None:
            raise DisponibilidadInvalida(
                f'Ya existe un turno llamado "{nombre}" con otro horario o días. '
                'Usa otro nombre o déjalo en blanco.'
            )
    return None


def _aplicar_disponibilidad(producto, plan):
    modo = plan[0]
    if modo == 'todo_el_dia':
        producto.turnos.clear()
        return
    if modo != 'horario':
        return

    _, nombre, desde, hasta, dias_por_campo = plan
    turno = _turno_igual(nombre, desde, hasta, dias_por_campo)
    if turno is None:
        candidato = Turno(nombre=nombre, hora_inicio=desde, hora_fin=hasta, **dias_por_campo)
        base = nombre or f'{candidato.horario_texto} ({candidato.dias_texto})'[:50]
        candidato.nombre = base
        sufijo = 2
        while Turno.objects.filter(nombre__iexact=candidato.nombre).exists():
            candidato.nombre = f'{base[:45]} #{sufijo}'
            sufijo += 1
        try:
            with transaction.atomic():
                candidato.save()
        except IntegrityError:
            raise DisponibilidadInvalida(
                'Otro administrador creó un turno con ese nombre al mismo tiempo. Intenta de nuevo.'
            )
        turno = candidato

    if not turno.activo:
        turno.activo = True
        turno.save(update_fields=['activo'])
    producto.turnos.set([turno])


@admin_required
@require_POST
def crear_producto(request):
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'gestion_inventario'
    nombre = request.POST.get('nombre', '').strip()
    categoria_id = request.POST.get('categoria_id')
    precio = request.POST.get('precio', 0)
    stock = request.POST.get('stock', 0)
    stock_critico = request.POST.get('stock_critico', 10)
    unidad_medida = request.POST.get('unidad_medida', 'unid')
    descripcion = request.POST.get('descripcion', '').strip()
    imagen_url = request.POST.get('imagen_url', '').strip()

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

    try:
        disponibilidad = _disponibilidad_del_formulario(request)
        with transaction.atomic():
            producto = Producto.objects.create(
                nombre=nombre,
                categoria=categoria,
                precio=precio,
                stock=stock,
                stock_critico=stock_critico,
                unidad_medida=unidad_medida,
                descripcion=descripcion,
                imagen_url=imagen_url,
                activo=True
            )
            _aplicar_disponibilidad(producto, disponibilidad)
    except DisponibilidadInvalida as error:
        messages.error(request, f'Disponibilidad: {error} No se creó el producto.')
        return redirect(next_url)
    messages.success(request, f'Producto "{nombre}" agregado exitosamente al catálogo.')
    return redirect(next_url)


@admin_required
@require_POST
def editar_producto(request, pk):
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'gestion_inventario'
    producto = get_object_or_404(Producto, pk=pk)

    nombre = request.POST.get('nombre', '').strip()
    categoria_id = request.POST.get('categoria_id')
    precio = request.POST.get('precio', producto.precio)
    stock = request.POST.get('stock', producto.stock)
    stock_critico = request.POST.get('stock_critico', producto.stock_critico)
    unidad_medida = request.POST.get('unidad_medida', producto.unidad_medida)
    descripcion = request.POST.get('descripcion', '').strip()
    imagen_url = request.POST.get('imagen_url', '').strip()
    activo = request.POST.get('activo') in ['1', 'true', 'on', True]

    if not nombre:
        messages.error(request, 'El nombre del producto no puede quedar vacío.')
        return redirect(next_url)

    try:
        disponibilidad = _disponibilidad_del_formulario(request)
    except DisponibilidadInvalida as error:
        messages.error(request, f'Disponibilidad: {error} No se guardó ningún cambio.')
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
    producto.imagen_url = imagen_url
    producto.activo = activo
    try:
        with transaction.atomic():
            producto.save()
            _aplicar_disponibilidad(producto, disponibilidad)
    except DisponibilidadInvalida as error:
        messages.error(request, f'Disponibilidad: {error} No se guardó ningún cambio.')
        return redirect(next_url)

    messages.success(request, f'Producto "{producto.nombre}" actualizado correctamente.')
    return redirect(next_url)


@admin_required
@require_POST
def registrar_produccion(request, pk):
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'gestion_inventario'
    producto = get_object_or_404(Producto, pk=pk)
    cantidad = _entero_o_none(request.POST.get('cantidad', 0))

    if cantidad and cantidad > 0:
        with transaction.atomic():
            producto.stock += cantidad
            producto.save(update_fields=['stock'])

            ProduccionDiaria.objects.create(
                producto=producto,
                cantidad=cantidad,
                responsable=request.user
            )
        messages.success(request, f'¡Hornada registrada! Se sumaron +{cantidad} un. a "{producto.nombre}". Stock actualizado: {producto.stock}.')
    else:
        messages.error(request, 'Por favor, ingresa una cantidad horneada válida mayor a 0.')

    return redirect(next_url)


@admin_required
@require_POST
def eliminar_producto(request, pk):
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


@admin_required
@require_POST
def crear_categoria(request):
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'gestion_inventario'
    nombre = request.POST.get('nombre', '').strip()
    descripcion = request.POST.get('descripcion', '').strip()

    if not nombre:
        messages.error(request, 'El nombre de la categoría es obligatorio.')
        return redirect(next_url)

    categoria, creada = Categoria.objects.get_or_create(
        nombre__iexact=nombre,
        defaults={'nombre': nombre, 'descripcion': descripcion}
    )

    if creada:
        messages.success(request, f'Categoría "{categoria.nombre}" creada exitosamente.')
    else:
        messages.warning(request, f'La categoría "{nombre}" ya existía en el catálogo.')

    return redirect(next_url)

# ==========================================
# FUNCIONES DE ADMINISTRADOR: GESTIÓN DE USUARIOS, INVENTARIO Y REPORTES
# ==========================================

# ==========================================
# FUNCIONES DE CAJERO: TERMINAL POS, APERTURA Y CIERRE DE CAJA, VENTAS
# ==========================================

def cajero_required(view_func):
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Debe iniciar sesión para acceder al sistema POS.')
            return redirect('login')
        if not (request.user.es_cajero or request.user.es_administrador):
            messages.error(request, 'No tiene permisos de cajero para acceder a esta área.')
            return redirect('inicio')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def caja_abierta_required(view_func):
    """
    Solo se vende con la caja abierta: sin caja, la Terminal POS manda a la apertura de caja
    y una venta (POST) se rechaza. Va debajo de @cajero_required.
    """
    def _wrapped_view(request, *args, **kwargs):
        cajero = getattr(request.user, 'perfil_cajero', None)
        if cajero is None:
            caja, bloqueo = None, 'El punto de venta es solo para cajeros con una caja asignada.'
        else:
            caja, bloqueo = caja_pos.situacion(cajero)

        if caja is None:
            mensaje = bloqueo or 'Antes de vender, declara el monto inicial de tu caja.'
            if request.method == 'POST':
                return JsonResponse({'ok': False, 'error': mensaje}, status=409)
            if cajero is None:
                messages.error(request, mensaje)
                return redirect('inicio_admin' if request.user.es_administrador else 'inicio')
            if not bloqueo:
                messages.info(request, mensaje)    # el bloqueo ya se explica en la pantalla de apertura
            return redirect('apertura_caja')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


@cajero_required
@require_http_methods(['GET', 'POST'])
def apertura_caja(request):
    """
    Apertura de caja: al empezar el turno, el cajero declara el dinero físico que hay en su caja.
    Hasta abrirla no puede vender. El monto se compara con lo contado en el último cierre de esa
    caja física; si no coincide, la observación es obligatoria (reglas en core/caja.py).
    """
    cajero = getattr(request.user, 'perfil_cajero', None)
    if cajero is None:
        messages.error(request, 'Solo un cajero con una caja asignada puede abrir caja.')
        return redirect('inicio_admin' if request.user.es_administrador else 'inicio')

    error = None
    monto_ingresado = ''
    observacion = ''
    if request.method == 'POST':
        monto_ingresado = request.POST.get('monto', '').strip()
        observacion = request.POST.get('observacion', '')
        try:
            caja = caja_pos.abrir_caja(cajero, monto_ingresado, observacion)
        except caja_pos.AperturaInvalida as motivo:
            error = str(motivo)
        else:
            messages.success(request, f'Caja {caja.numero} abierta con {clp(caja.monto_inicial)}. ¡Buen turno!')
            return redirect('inicio_cajero')

    caja, bloqueo = caja_pos.situacion(cajero)
    monto_anterior = caja_pos.monto_turno_anterior(cajero.num_caja_asignada)
    contexto = {
        'caja': caja,                 # su caja abierta hoy (ya puede vender)
        'bloqueo': bloqueo,           # no puede abrir: una caja quedó abierta
        'numero_caja': cajero.num_caja_asignada,
        'monto_anterior': monto_anterior,
        'monto_anterior_entero': int(monto_anterior) if monto_anterior is not None else '',
        'ahora': timezone.localtime(),
        'error': error,
        'monto_ingresado': monto_ingresado,
        'observacion': observacion,
        'largo_observacion': caja_pos.LARGO_MAXIMO_OBSERVACION,
    }
    return render(request, 'core/apertura_caja.html', contexto, status=400 if error else 200)


@cajero_required
@caja_abierta_required
def inicio_cajero(request):
    """
    Vista dedicada para la Terminal POS del Cajero.
    Carga todas las categorías activas y productos disponibles
    para permitir el filtrado instantáneo en el Frontend.
    """
    # 1. Obtener categorías disponibles
    categorias = Categoria.objects.all().order_by('nombre')
    # 2. Obtener productos activos e incluir la relación con su categoría
    productos = Producto.objects.filter(activo=True).select_related('categoria').order_by('nombre')

    contexto = {
        'categorias': categorias,
        'productos': productos,
    }
    return render(request, 'core/inicio_cajero.html', contexto)

@cajero_required
@caja_abierta_required
@require_POST
def finalizar_venta_pos(request):
    """
    Procesa la venta presencial desde la Terminal POS.
    Soporta Pago en Efectivo y Pago con Tarjeta (Webpay Plus).
    """
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    carrito_items = data.get('items', [])
    metodo_pago = data.get('metodo_pago', 'EFECTIVO').upper()
    try:
        monto_efectivo = Decimal(str(data.get('monto_efectivo', 0)))
    except Exception:
        monto_efectivo = Decimal('0.00')

    if not carrito_items:
        return JsonResponse({'ok': False, 'error': 'El ticket de venta está vacío.'}, status=400)

    # Validar cantidades
    cantidades = {}
    for item in carrito_items:
        try:
            p_id = int(item.get('id'))
            cant = int(item.get('cantidad'))
            if p_id > 0 and cant > 0:
                cantidades[p_id] = cant
        except (TypeError, ValueError):
            continue

    if not cantidades:
        return JsonResponse({'ok': False, 'error': 'No hay productos válidos en la venta.'}, status=400)

    with transaction.atomic():
        productos = list(
            Producto.objects.select_for_update()
            .filter(pk__in=cantidades.keys(), activo=True)
            .order_by('pk')
        )
        if len(productos) != len(cantidades):
            return JsonResponse({'ok': False, 'error': 'Uno o más productos seleccionados ya no están disponibles.'}, status=400)

        faltantes = [p.nombre for p in productos if p.stock < cantidades[p.pk]]
        if faltantes:
            return JsonResponse({
                'ok': False, 
                'error': f'Stock insuficiente para: {", ".join(faltantes)}.'
            }, status=400)

        total = sum(p.precio * cantidades[p.pk] for p in productos)

        if metodo_pago == 'EFECTIVO' and monto_efectivo < total:
            return JsonResponse({
                'ok': False,
                'error': f'El efectivo ingresado ({clp(monto_efectivo)}) es menor al total ({clp(total)}).'
            }, status=400)

        es_webpay = (metodo_pago in ['TARJETA', 'WEBPAY', 'DEBITO'])

        pedido = Pedido.objects.create(
            cliente=None,
            estado='PENDIENTE' if es_webpay else 'PAGADO',
            canal='POS',
            cajero=getattr(request.user, 'perfil_cajero', None),
            tipo_entrega='RETIRO',
            direccion_despacho='Venta presencial en Caja',
            total=total,
        )

        for producto in productos:
            cant = cantidades[producto.pk]
            subtotal = producto.precio * cant
            DetallePedido.objects.create(
                pedido=pedido,
                producto=producto,
                cantidad=cant,
                precio_unitario=producto.precio,
                subtotal=subtotal,
            )
            producto.stock -= cant
            producto.save(update_fields=['stock'])

        # --- CASO 1: PAGO EN EFECTIVO ---
        if not es_webpay:
            vuelto = monto_efectivo - total if monto_efectivo > total else Decimal('0.00')
            Pago.objects.create(
                pedido=pedido,
                monto=total,
                metodo='Efectivo',
                estado='PAGADO',
                codigo_autorizacion=f'POS-{pedido.pk:08d}',
            )
            return JsonResponse({
                'ok': True,
                'metodo': 'efectivo',
                'pedido_id': pedido.pk,
                'total_clp': clp(total),
                'vuelto_clp': clp(vuelto),
                'mensaje': f'¡Venta N° {pedido.pk} registrada! Total: {clp(total)} | Vuelto: {clp(vuelto)}'
            })

        # --- CASO 2: PAGO CON TARJETA (WEBPAY PLUS) ---
        pago = Pago.objects.create(
            pedido=pedido,
            monto=total,
            metodo='Webpay Plus',
            estado='PENDIENTE',
            codigo_autorizacion='',
        )

        buy_order = f"ORD-{pedido.pk}"
        if not request.session.session_key:
            request.session.save()
        session_id = request.session.session_key
        amount = int(round(float(total)))
        return_url = request.build_absolute_uri('/carrito/webpay-confirmar/')

        tx = obtener_transaccion_webpay()
        try:
            response = tx.create(buy_order, session_id, amount, return_url)
        except Exception:
            pedidos.cancelar_pendiente(pedido.pk, 'FALLIDO')
            return JsonResponse({'ok': False, 'error': 'No se pudo conectar con Transbank Webpay.'}, status=500)

        token_ws = response.get('token')
        pago.codigo_autorizacion = token_ws
        pago.save(update_fields=['codigo_autorizacion'])

        request.session['webpay_pedido_id'] = pedido.pk
        request.session['webpay_token'] = token_ws

        return JsonResponse({
            'ok': True,
            'metodo': 'tarjeta',
            'pedido_id': pedido.pk,
            'url_webpay': f"{response['url']}?token_ws={token_ws}",
            'mensaje': 'Conectando con Transbank Webpay...'
        })


# --- HISTORIAL DE VENTAS DEL CAJERO (la libreta de su turno) ---

VENTAS_POR_PAGINA_POS = 15
# Estados de una venta ya cobrada (PENDIENTE espera a Webpay; CANCELADO no cuenta)
ESTADOS_VENTA_POS = ['PAGADO', 'PREPARACION', 'LISTO', 'ENTREGADO']
# 'PAGADO' lo deja la venta en efectivo; 'APROBADO', Webpay al autorizar la tarjeta
ESTADOS_PAGO_POS = ['PAGADO', 'APROBADO']


def _ventas_pos_de_hoy(request):
    """Ventas presenciales cobradas que registró hoy (hora de Chile) el cajero conectado.

    Devuelve (fecha de hoy, queryset). Un administrador sin perfil de cajero no tiene ventas propias.
    """
    hoy = timezone.localdate()
    # Rango del día y no fecha__date: en MySQL, __date con USE_TZ usa CONVERT_TZ y devuelve vacío si el
    # servidor no tiene cargadas las tablas de zonas horarias. (datetime.min.time() es las 00:00: aquí
    # `time` es el módulo que usa time.sleep.)
    inicio = timezone.make_aware(datetime.combine(hoy, datetime.min.time()))
    ventas = Pedido.objects.filter(
        cajero__user=request.user,
        canal__in=['POS', 'PRESENCIAL'],    # finalizar_venta_pos graba 'POS', que no está en CANALES
        estado__in=ESTADOS_VENTA_POS,
        pago__estado__in=ESTADOS_PAGO_POS,
        fecha__gte=inicio,
        fecha__lt=inicio + timedelta(days=1),
    )
    return hoy, ventas


def _con_detalles(ventas):
    """Precarga el pago y las líneas de cada venta (con su producto, en el orden en que se agregaron)."""
    return ventas.select_related('pago').prefetch_related(
        Prefetch('detalles', queryset=DetallePedido.objects.select_related('producto').order_by('pk'))
    )


def _unidad_venta_pos(producto):
    return 'kg' if producto.unidad_medida == 'kg' else 'un'


def _medio_de_pago_pos(pago):
    """'Efectivo' o 'Tarjeta' (Webpay Plus, débito, crédito...)."""
    return 'Efectivo' if (pago.metodo or '').strip().lower() == 'efectivo' else 'Tarjeta'


@cajero_required
@require_GET
def historial_ventas_pos(request):
    """
    Historial de ventas del cajero: solo las ventas presenciales que él registró hoy.
    El resumen (cantidad y total) es del día completo; la lista va paginada.
    """
    hoy, ventas = _ventas_pos_de_hoy(request)
    resumen = ventas.aggregate(cantidad=Count('pk'), total=Sum('total'))

    paginador = Paginator(_con_detalles(ventas).order_by('-fecha', '-pk'), VENTAS_POR_PAGINA_POS)
    page_obj = paginador.get_page(request.GET.get('page'))
    page_obj.object_list = list(page_obj.object_list)
    for venta in page_obj.object_list:
        venta.numero = f'#{venta.pk:06d}'
        venta.productos_resumen = ', '.join(
            f'{detalle.producto.nombre} ({detalle.cantidad} {_unidad_venta_pos(detalle.producto)})'
            for detalle in venta.detalles.all()
        )
        venta.medio_pago = _medio_de_pago_pos(venta.pago)

    contexto = {
        'fecha': hoy,
        'cantidad_ventas': resumen['cantidad'],
        'total_ventas': resumen['total'] or Decimal('0'),
        'page_obj': page_obj,
    }
    return render(request, 'core/historial_ventas_pos.html', contexto)


@cajero_required
@require_GET
def detalle_venta_pos(request, pedido_id):
    """
    Detalle de una venta del historial, en JSON, para el modal "Ver detalle".
    Solo responde por ventas del cajero conectado y de hoy: cualquier otra da 404.
    """
    _, ventas = _ventas_pos_de_hoy(request)
    venta = _con_detalles(ventas).filter(pk=pedido_id).first()
    if venta is None:
        return JsonResponse({'ok': False, 'error': 'Venta no encontrada.'}, status=404)

    momento = timezone.localtime(venta.fecha)
    items = [
        {
            'producto': detalle.producto.nombre,
            'cantidad': detalle.cantidad,
            'unidad': _unidad_venta_pos(detalle.producto),
            'precio_unitario_clp': clp(detalle.precio_unitario),
            'subtotal_clp': clp(detalle.subtotal),
        }
        for detalle in venta.detalles.all()
    ]
    return JsonResponse({
        'ok': True,
        'venta': {
            'id': venta.pk,
            'numero': f'#{venta.pk:06d}',
            'fecha': momento.strftime('%d/%m/%Y'),
            'hora': momento.strftime('%H:%M'),
            'medio_pago': _medio_de_pago_pos(venta.pago),
            'estado': venta.get_estado_display(),
            'total': int(round(venta.total)),
            'total_clp': clp(venta.total),
            'items': items,
        },
    })

# ==========================================
# FUNCIONES DE CAJERO: TERMINAL POS, APERTURA Y CIERRE DE CAJA, VENTAS
# ==========================================

# ==========================================
# FUNCIONES DE INICIO Y REGISTRO DE USUARIOS
# ==========================================

def login_view(request):
    if request.user.is_authenticated:
        return redireccionar_por_rol(request.user)

    next_url = request.GET.get('next') or request.POST.get('next')

    if request.method == 'POST':
        identificador = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if not identificador or not password:
            messages.error(request, 'Por favor, ingrese su correo o usuario y contraseña.')
            return render(request, 'core/login.html', {'next': next_url})

        usuario_encontrado = Usuario.objects.filter(
            Q(username__iexact=identificador) | Q(email__iexact=identificador)
        ).first()

        username_auth = usuario_encontrado.username if usuario_encontrado else identificador

        user = authenticate(request, username=username_auth, password=password)

        if user is not None:
            if not user.is_active:
                messages.error(request, 'Esta cuenta se encuentra desactivada.')
                return render(request, 'core/login.html', {'next': next_url})

            login(request, user)

            if next_url and next_url.startswith('/'):
                return redirect(next_url)

            return redireccionar_por_rol(user)
        else:
            messages.error(request, 'Credenciales incorrectas. Verifique sus datos e intente nuevamente.')

    return render(request, 'core/login.html', {'next': next_url})


def logout_view(request):
    logout(request)
    messages.info(request, 'Has cerrado sesión correctamente.')
    return redirect('inicio')


def registro_view(request):
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

        region = request.POST.get('region', '').strip()
        comuna = request.POST.get('comuna', '').strip()
        direccion1 = request.POST.get('direccion1', '').strip()
        direccion2 = request.POST.get('direccion2', '').strip()
        indicaciones = request.POST.get('indicaciones', '').strip()

        errores = []

        if not (username and first_name and last_name and email and telefono and password and password_confirm and region and comuna and direccion1):
            errores.append('Por favor completa todos los campos obligatorios.')

        if email:
            try:
                validate_email(email)
            except ValidationError:
                errores.append('Ingresa un correo electrónico válido.')
        
        if password != password_confirm:
            errores.append('Las contraseñas no coinciden.')

        if len(password) < 6:
            errores.append('La contraseña debe tener al menos 6 caracteres.')

        if Usuario.objects.filter(username__iexact=username).exists():
            errores.append('Ya existe una cuenta registrada con este nombre de usuario.')

        if Usuario.objects.filter(email=email).exists():
            errores.append('El correo electrónico ya se encuentra registrado.')

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
                user = Usuario.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    rol='CLIENTE'
                )

                partes_dir = [direccion1]
                if direccion2:
                    partes_dir.append(direccion2)
                partes_dir.append(comuna)
                partes_dir.append(region)
                direccion_completa = ", ".join(partes_dir)
                if indicaciones:
                    direccion_completa += f" (Ref: {indicaciones})"

                cliente = Cliente.objects.create(
                    user=user,
                    direccion=direccion_completa[:255],
                    telefono=telefono or "+56 9"
                )

                PuntosFidelizacion.objects.create(
                    cliente=cliente,
                    puntos_acumulados=0
                )

                login(request, user)
                messages.success(request, f'¡Bienvenido/a a Los Tres Spa, {first_name}! Tu cuenta ha sido creada exitosamente.')
                return redirect('inicio')

        except Exception as e:
            messages.error(request, f'Ocurrió un error al procesar el registro: {str(e)}')
            return render(request, 'core/registro.html', {'datos': request.POST})

    return render(request, 'core/registro.html')

# ==========================================
# FUNCIONES DE INICIO Y REGISTRO DE USUARIOS
# ==========================================

# Vistas de páginas informativas: Términos y Condiciones, Políticas de Privacidad

def terminos_condiciones(request):
    return render(request, 'core/terminos_condiciones.html')


def politicas_privacidad(request):
    return render(request, 'core/politicas_privacidad.html')