from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('pedir/', views.pedir, name='pedir'),
    path('mis-pedidos/', views.mis_pedidos, name='mis_pedidos'),
    path('carrito/', views.carrito, name='carrito'),
    path('carrito/agregar/', views.agregar_al_carrito, name='carrito_agregar'),
    path('carrito/quitar/<int:producto_id>/', views.quitar_del_carrito, name='carrito_quitar'),
    path('carrito/disminuir/<int:producto_id>/', views.disminuir_del_carrito, name='carrito_disminuir'),
    path('carrito/finalizar/', views.finalizar_compra, name='finalizar_compra'),
    path('comprobante/<int:pedido_id>/', views.comprobante_pedido, name='comprobante_pedido'),
    path('comprobante/<int:pedido_id>/', views.comprobante_pedido, name='boleta_simulada'),
    path('comprobante/<int:pedido_id>/pdf/', views.descargar_comprobante_pdf, name='descargar_comprobante_pdf'),
    path('boleta-demo/<int:pedido_id>/', views.comprobante_pedido),
    path('boleta-demo/<int:pedido_id>/pdf/', views.descargar_comprobante_pdf),
    path('producto/<int:pk>/', views.producto_detalle, name='producto_detalle'),
    path('local/', views.local, name='local'),
    path('panel-admin/', views.inicio_admin, name='inicio_admin'),
    path('panel-admin/usuarios/', views.gestion_usuarios, name='gestion_usuarios'),
    path('panel-admin/usuarios/personal/crear/', views.crear_personal, name='crear_personal'),
    path('panel-admin/usuarios/personal/editar/<int:pk>/', views.editar_personal, name='editar_personal'),
    path('panel-admin/usuarios/personal/eliminar/<int:pk>/', views.eliminar_personal, name='eliminar_personal'),
    path('panel-admin/inventario/', views.gestion_inventario, name='gestion_inventario'),
    path('panel-admin/inventario/crear/', views.crear_insumo, name='crear_insumo'),
    path('panel-admin/inventario/editar/<int:pk>/', views.editar_insumo, name='editar_insumo'),
    path('panel-admin/inventario/eliminar/<int:pk>/', views.eliminar_insumo, name='eliminar_insumo'),
    path('panel-admin/productos/crear/', views.crear_producto, name='crear_producto'),
    path('panel-admin/productos/editar/<int:pk>/', views.editar_producto, name='editar_producto'),
    path('panel-admin/productos/eliminar/<int:pk>/', views.eliminar_producto, name='eliminar_producto'),
    path('panel-admin/productos/produccion/<int:pk>/', views.registrar_produccion, name='registrar_produccion'),
    path('panel-admin/categorias/crear/', views.crear_categoria, name='crear_categoria'),
    path('panel-admin/proveedores/crear/', views.crear_proveedor, name='crear_proveedor'),
    path('panel-admin/proveedores/editar/<int:pk>/', views.editar_proveedor, name='editar_proveedor'),
    path('panel-admin/proveedores/eliminar/<int:pk>/', views.eliminar_proveedor, name='eliminar_proveedor'),
    path('panel-admin/cotizaciones/', views.comparar_cotizaciones, name='comparar_cotizaciones'),
    path('panel-admin/cotizaciones/guardar/', views.guardar_cotizacion, name='guardar_cotizacion'),
    path('panel-admin/cotizaciones/mercado/', views.actualizar_precios_mercado, name='actualizar_precios_mercado'),
    path('panel-admin/cotizaciones/eliminar/<int:pk>/', views.eliminar_cotizacion, name='eliminar_cotizacion'),
    path('pos/', views.inicio_cajero, name='inicio_cajero'),
    path('pos/finalizar-venta/', views.finalizar_venta_pos, name='finalizar_venta_pos'),
    path('pos/historial/', views.historial_ventas_pos, name='historial_ventas_pos'),
    path('pos/historial/<int:pedido_id>/detalle/', views.detalle_venta_pos, name='detalle_venta_pos'),
    path('pos/apertura/', views.apertura_caja, name='apertura_caja'),
    path('pos/cierre/', views.cierre_caja, name='cierre_caja'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('registro/', views.registro_view, name='registro'),
    path('terminos-y-condiciones/', views.terminos_condiciones, name='terminos_condiciones'),
    path('politicas-de-privacidad/', views.politicas_privacidad, name='politicas_privacidad'),
    path(
        'recuperar-password/', 
        auth_views.PasswordResetView.as_view(
            template_name='core/registration/password_reset_form.html',
            email_template_name='core/registration/password_reset_email.html',
            subject_template_name='core/registration/password_reset_subject.txt',
            success_url='/recuperar-password/enviado/'
        ), 
        name='password_reset'
    ),
    path(
        'recuperar-password/enviado/', 
        auth_views.PasswordResetDoneView.as_view(
            template_name='core/registration/password_reset_done.html'
        ), 
        name='password_reset_done'
    ),
    path(
        'recuperar-password/confirmar/<uidb64>/<token>/', 
        auth_views.PasswordResetConfirmView.as_view(
            template_name='core/registration/password_reset_confirm.html',
            success_url='/recuperar-password/completado/'
        ), 
        name='password_reset_confirm'
    ),
    path(
        'recuperar-password/completado/', 
        auth_views.PasswordResetCompleteView.as_view(
            template_name='core/registration/password_reset_complete.html'
        ), 
        name='password_reset_complete'
    ),
]
