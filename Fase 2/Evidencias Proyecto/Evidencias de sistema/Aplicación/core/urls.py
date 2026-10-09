from django.urls import path
from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('pedir/', views.pedir, name='pedir'),
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
