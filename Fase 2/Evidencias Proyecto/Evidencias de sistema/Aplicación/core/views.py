from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import Usuario

def home(request):
    return render(request, 'core/index.html')

def login_view(request):
    # Si ya está autenticado, redirigir según su rol
    if request.user.is_authenticated:
        if getattr(request.user, 'rol', None) == 'ADMINISTRADOR' or request.user.is_superuser:
            return redirect('/admin/')
        elif getattr(request.user, 'rol', None) == 'CAJERO':
            return redirect('/pos/')
        return redirect('/')

    if request.method == 'POST':
        identificador = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        # Permitir inicio de sesión tanto con Correo Electrónico como con Nombre de Usuario
        user_obj = Usuario.objects.filter(email__iexact=identificador).first()
        username = user_obj.username if user_obj else identificador

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            # Redirección basada en roles (Sprint 1)
            if user.rol == 'ADMINISTRADOR' or user.is_superuser:
                return redirect('/admin/')
            elif user.rol == 'CAJERO':
                return redirect('/pos/')
            else:
                return redirect('/')
        else:
            messages.error(request, 'Correo o contraseña incorrectos. Por favor, intente nuevamente.')

    return render(request, 'core/login.html')

def logout_view(request):
    logout(request)
    return redirect('/')
