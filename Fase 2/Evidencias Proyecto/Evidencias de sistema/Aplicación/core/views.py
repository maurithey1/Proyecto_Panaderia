import re
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import Http404
from django.views.decorators.http import require_POST
from .models import (
    Categoria, Cliente, Cajero, DetallePedido, Pago, Pedido, Producto,
    ProveedorInsumo, PuntosFidelizacion, Usuario,
)
from .templatetags.tienda import TIENDA
from .retiro import dias_de_retiro, texto_retiro, validar_retiro
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


def inicio(request):
    """Los 4 productos más vendidos (pedidos no cancelados), leídos de la BD."""
    estados_validos = [estado for estado, _ in Pedido.ESTADOS if estado != 'CANCELADO']

    productos = (
        Producto.objects.filter(activo=True)
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


def pedir(request):
    """Catálogo completo, público. Se puede filtrar con ?categoria=<id>."""
    categorias = Categoria.objects.filter(productos__activo=True).distinct().order_by('nombre')

    productos = Producto.objects.filter(activo=True).order_by(
        # Los agotados van al final
        Case(When(stock__gt=0, then=Value(0)), default=Value(1), output_field=IntegerField()),
        'nombre',
    )

    categoria_actual = None
    categoria_id = _entero_o_none(request.GET.get('categoria', ''))
    if categoria_id is not None:
        categoria_actual = categorias.filter(pk=categoria_id).first()
        if categoria_actual:
            productos = productos.filter(categoria=categoria_actual)

    return render(request, 'core/pedir.html', {
        'productos': productos,
        'categorias': categorias,
        'categoria_actual': categoria_actual,
    })


@require_POST
def agregar_al_carrito(request):
    """Agrega una unidad del producto elegido en el catálogo al carrito de la sesión."""
    producto_id = _entero_o_none(request.POST.get('producto_id', ''))
    if producto_id is None:
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
        messages.error(request, f'No hay más stock disponible de {producto.nombre}.')
        return redirect('carrito')

    carrito[clave] = cantidad + 1
    request.session['carrito'] = carrito
    messages.success(request, f'{producto.nombre} se agregó al carrito.')
    return redirect('carrito')


def carrito(request):
    """Muestra el carrito de la sesión con los datos reales de cada producto."""
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
    ).order_by('nombre')
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

    return render(request, 'core/carrito.html', {
        'items': items,
        'total': total,
        'direccion_guardada': direccion_guardada,
        'retiro_dias': dias_de_retiro(),
        'carrito_tiene_stock': all(
            item['cantidad'] <= item['producto'].stock for item in items
        ),
    })


@require_POST
def quitar_del_carrito(request, producto_id):
    """Quita un producto del carrito de la sesión."""
    carrito_sesion = request.session.get('carrito', {})
    if isinstance(carrito_sesion, dict):
        carrito_sesion.pop(str(producto_id), None)
        request.session['carrito'] = carrito_sesion
    messages.success(request, 'Producto quitado del carrito.')
    return redirect('carrito')


@require_POST
def finalizar_compra(request):
    """Compra de demostración: crea pedido, detalle y pago simulado, y descuenta el stock."""
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

    # Retiro programado: el día y la hora salen de core/retiro.py. Sin agenda (otros clientes HTTP) se acepta.
    texto_del_retiro = ''
    if tipo_entrega == 'RETIRO':
        fecha_retiro = request.POST.get('fecha_retiro', '').strip()
        hora_retiro = request.POST.get('hora_retiro', '').strip()
        if fecha_retiro or hora_retiro:
            fecha, hora, error = validar_retiro(fecha_retiro, hora_retiro)
            if error:
                messages.error(request, error)
                return redirect('carrito')
            texto_del_retiro = f'Retiro programado: {texto_retiro(fecha, hora)}'

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

        pedido = Pedido.objects.create(
            cliente=cliente,
            estado='PAGADO',
            canal='WEB',
            tipo_entrega=tipo_entrega,
            direccion_despacho=direccion if tipo_entrega == 'DESPACHO' else texto_del_retiro,
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
    Muestra indicadores de stock, proyecciones de ventas y precios de insumos.
    """
    # Consulta de productos con stock actual
    productos_stock = Producto.objects.filter(activo=True).order_by('nombre')
    
    # Consulta de insumos/materias primas y sus precios de proveedores
    tarifas_proveedores = ProveedorInsumo.objects.select_related('proveedor', 'insumo').all()

    contexto = {
        'productos_stock': productos_stock,
        'tarifas_proveedores': tarifas_proveedores,
    }
    return render(request, 'core/inicio_admin.html', contexto)

@admin_required
def gestion_usuarios(request):
    """
    Vista principal de gestión de cuentas.
    Separa los usuarios en Clientes (Solo Lectura) y Cajeros/Trabajadores (CRUD).
    """
    clientes = Cliente.objects.select_related('user', 'puntos').all().order_by('-user__date_joined')
    cajeros = Cajero.objects.select_related('user').all().order_by('num_caja_asignada')

    contexto = {
        'clientes': clientes,
        'cajeros': cajeros,
    }
    return render(request, 'core/gestion_usuarios.html', contexto)

@admin_required
def crear_cajero(request):
    """Crea un nuevo usuario de tipo CAJERO con su correspondiente perfil operativo."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
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
                    rol='CAJERO',
                    is_staff=True # Permite accesos operativos
                )
                Cajero.objects.create(user=user, num_caja_asignada=num_caja)
                messages.success(request, f'Cajero "{username}" registrado con éxito.')
        except Exception as e:
            messages.error(request, f'Error al crear el cajero: {str(e)}')

    return redirect('gestion_usuarios')


@admin_required
def editar_cajero(request, pk):
    """Edita la información de un cajero existente y su asignación de caja."""
    cajero = get_object_or_404(Cajero, pk=pk)
    user = cajero.user

    if request.method == 'POST':
        user.first_name = request.POST.get('first_name', '').strip()
        user.last_name = request.POST.get('last_name', '').strip()
        user.email = request.POST.get('email', '').strip().lower()
        cajero.num_caja_asignada = request.POST.get('num_caja_asignada', 1)
        
        # Cambio de contraseña opcional
        nueva_pass = request.POST.get('password', '').strip()
        if nueva_pass:
            user.set_password(nueva_pass)

        user.save()
        cajero.save()
        messages.success(request, f'Datos del cajero "{user.username}" actualizados correctamente.')
        return redirect('gestion_usuarios')

    return render(request, 'core/editar_cajero.html', {'cajero': cajero})


@admin_required
def eliminar_cajero(request, pk):
    """Desactiva o elimina la cuenta de un cajero."""
    cajero = get_object_or_404(Cajero, pk=pk)
    user = cajero.user
    
    # Desactivar en lugar de eliminar físicamente para no perder historial de cajas
    user.is_active = False
    user.save()
    messages.warning(request, f'El cajero "{user.username}" ha sido desactivado del sistema.')
    return redirect('gestion_usuarios')

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
        rut = request.POST.get('rut', '').strip()
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

        if not (rut and first_name and last_name and email and telefono and password and password_confirm and region and comuna and direccion1):
            errores.append('Por favor completa todos los campos obligatorios.')

        if password != password_confirm:
            errores.append('Las contraseñas no coinciden.')

        if len(password) < 6:
            errores.append('La contraseña debe tener al menos 6 caracteres.')

        if Usuario.objects.filter(username__iexact=rut).exists():
            errores.append('Ya existe una cuenta registrada con este RUT.')

        if email and Usuario.objects.filter(email__iexact=email).exists():
            errores.append('Ya existe una cuenta con este correo electrónico.')

        if errores:
            for err in errores:
                messages.error(request, err)
            return render(request, 'core/registro.html', {
                'datos': {
                    'rut': rut,
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
                    username=rut,
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
