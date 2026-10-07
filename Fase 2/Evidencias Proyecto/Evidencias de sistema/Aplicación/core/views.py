from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from .models import Categoria, Pedido, Producto, Usuario, Cliente, PuntosFidelizacion

PRODUCTOS_DESTACADOS = 4


def inicio(request):
    """
    Vista principal de la panadería.
    Muestra los 4 productos más vendidos en la sección 'Los más pedidos'.
    """
    # Cuenta lo vendido en pedidos que no fueron cancelados.
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
    valor = request.GET.get('categoria', '')
    if valor.isdigit():
        categoria_actual = categorias.filter(pk=int(valor)).first()
        if categoria_actual:
            productos = productos.filter(categoria=categoria_actual)

    contexto = {
        'productos': productos,
        'categorias': categorias,
        'categoria_actual': categoria_actual,
    }
    return render(request, 'core/pedir.html', contexto)


def redireccionar_por_rol(user):
    """
    Redirige al usuario según su rol en el sistema:
    - ADMINISTRADOR -> /admin/
    - CAJERO -> /pos/
    - CLIENTE -> 'inicio'
    """
    if getattr(user, 'es_administrador', False):
        return redirect('/admin/')
    elif getattr(user, 'es_cajero', False):
        return redirect('/pos/')
    return redirect('inicio')


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

