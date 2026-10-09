from django.urls import path
from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('pedir/', views.pedir, name='pedir'),
    path('carrito/', views.carrito, name='carrito'),
    path('carrito/agregar/', views.agregar_al_carrito, name='carrito_agregar'),
    path('carrito/quitar/<int:producto_id>/', views.quitar_del_carrito, name='carrito_quitar'),
    path('carrito/finalizar/', views.finalizar_compra, name='finalizar_compra'),
    path('boleta-demo/<int:pedido_id>/', views.boleta_simulada, name='boleta_simulada'),
    path('local/', views.local, name='local'),
    path('panel-admin/', views.inicio_admin, name='inicio_admin'),
    path('panel-admin/usuarios/', views.gestion_usuarios, name='gestion_usuarios'),
    path('panel-admin/usuarios/cajero/crear/', views.crear_cajero, name='crear_cajero'),
    path('panel-admin/usuarios/cajero/editar/<int:pk>/', views.editar_cajero, name='editar_cajero'),
    path('panel-admin/usuarios/cajero/eliminar/<int:pk>/', views.eliminar_cajero, name='eliminar_cajero'),
    path('pos/', views.inicio_cajero, name='inicio_cajero'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('registro/', views.registro_view, name='registro'),
    path('terminos-y-condiciones/', views.terminos_condiciones, name='terminos_condiciones'),
    path('politicas-de-privacidad/', views.politicas_privacidad, name='politicas_privacidad'),
]
