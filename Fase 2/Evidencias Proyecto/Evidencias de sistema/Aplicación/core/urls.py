from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Inicio y Catálogo
    path('', views.inicio, name='inicio'),
    path('pedir/', views.pedir, name='pedir'),
    path('mis-pedidos/', views.mis_pedidos, name='mis_pedidos'),
    path('producto/<int:pk>/', views.producto_detalle, name='producto_detalle'),
    path('local/', views.local, name='local'),

    # Carrito y Procesamiento de Pago Webpay
    path('carrito/', views.carrito, name='carrito'),
    path('carrito/agregar/', views.agregar_al_carrito, name='carrito_agregar'),
    path('carrito/quitar/<int:producto_id>/', views.quitar_del_carrito, name='carrito_quitar'),
    path('carrito/disminuir/<int:producto_id>/', views.disminuir_del_carrito, name='carrito_disminuir'),
    path('carrito/finalizar/', views.finalizar_compra, name='finalizar_compra'),
    path('carrito/webpay-confirmar/', views.webpay_confirmar, name='webpay_confirmar'),
    path('carrito/webpay-iniciar/', views.iniciar_pago_webpay, name='iniciar_pago_webpay'),
    path('carrito/webpay-iniciar/<int:pedido_id>/', views.iniciar_pago_webpay, name='iniciar_pago_webpay'),

    # Comprobantes y Boletas
    path('comprobante/<int:pedido_id>/', views.comprobante_pedido, name='comprobante_pedido'),
    path('comprobante/<int:pedido_id>/pdf/', views.descargar_comprobante_pdf, name='descargar_comprobante_pdf'),
    path('boleta-demo/<int:pedido_id>/', views.comprobante_pedido, name='boleta_simulada'),
    path('boleta-demo/<int:pedido_id>/pdf/', views.descargar_comprobante_pdf),

    # Panel Administrador
    path('panel-admin/', views.inicio_admin, name='inicio_admin'),
    path('panel-admin/usuarios/', views.gestion_usuarios, name='gestion_usuarios'),
    path('panel-admin/inventario/historial-precios/', views.historial_precios_insumos, name='historial_precios_insumos'),
    path('panel-admin/usuarios/desactivar/<int:pk>/', views.desactivar_usuario, name='desactivar_usuario'),
    path('panel-admin/usuarios/personal/crear/', views.crear_personal, name='crear_personal'),
    path('panel-admin/usuarios/personal/editar/<int:pk>/', views.editar_personal, name='editar_personal'),
    path('panel-admin/usuarios/reactivar/<int:pk>/', views.reactivar_usuario, name='reactivar_usuario'),

    # Centro de Notificaciones y Alertas
    path('panel-admin/notificaciones/', views.lista_notificaciones, name='lista_notificaciones'),
    path('panel-admin/notificaciones/marcar-leida/<int:pk>/', views.marcar_notificacion_leida, name='marcar_notificacion_leida'),
    path('panel-admin/notificaciones/marcar-todas-leidas/', views.marcar_todas_leidas, name='marcar_todas_leidas'),
    
    # Inventario y Productos
    path('panel-admin/inventario/', views.gestion_inventario, name='gestion_inventario'),
    path('panel-admin/inventario/crear/', views.crear_insumo, name='crear_insumo'),
    path('panel-admin/inventario/editar/<int:pk>/', views.editar_insumo, name='editar_insumo'),
    path('panel-admin/inventario/<int:pk>/envase/', views.agregar_envase, name='agregar_envase'),
    path('panel-admin/inventario/eliminar/<int:pk>/', views.eliminar_insumo, name='eliminar_insumo'),
    path('panel-admin/inventario/mermas/', views.gestion_mermas, name='gestion_mermas'),
    path('panel-admin/productos/crear/', views.crear_producto, name='crear_producto'),
    path('panel-admin/productos/editar/<int:pk>/', views.editar_producto, name='editar_producto'),
    path('panel-admin/productos/eliminar/<int:pk>/', views.eliminar_producto, name='eliminar_producto'),
    path('panel-admin/productos/produccion/<int:pk>/', views.registrar_produccion, name='registrar_produccion'),
    path('panel-admin/categorias/crear/', views.crear_categoria, name='crear_categoria'),

    # Proveedores y Cotizaciones
    path('panel-admin/proveedores/crear/', views.crear_proveedor, name='crear_proveedor'),
    path('panel-admin/proveedores/editar/<int:pk>/', views.editar_proveedor, name='editar_proveedor'),
    path('panel-admin/proveedores/eliminar/<int:pk>/', views.eliminar_proveedor, name='eliminar_proveedor'),
    path('panel-admin/cotizaciones/', views.comparar_cotizaciones, name='comparar_cotizaciones'),
    path('panel-admin/cotizaciones/guardar/', views.guardar_cotizacion, name='guardar_cotizacion'),
    path('panel-admin/cotizaciones/mercado/', views.actualizar_precios_mercado, name='actualizar_precios_mercado'),
    path('panel-admin/cotizaciones/eliminar/<int:pk>/', views.eliminar_cotizacion, name='eliminar_cotizacion'),

    # Órdenes de Compra a Molineras (RQF9)
    path('panel-admin/ordenes-compra/', views.lista_ordenes_compra, name='lista_ordenes_compra'),
    path('panel-admin/ordenes-compra/crear/', views.crear_orden_compra, name='crear_orden_compra'),
    path('panel-admin/ordenes-compra/<int:pk>/pdf/', views.ver_orden_compra_pdf, name='ver_orden_compra_pdf'),
    path('panel-admin/ordenes-compra/<int:pk>/descargar-pdf/', views.descargar_orden_compra_pdf, name='descargar_orden_compra_pdf'),
    path('panel-admin/ordenes-compra/<int:pk>/enviar-email/', views.enviar_orden_compra_email, name='enviar_orden_compra_email'),
    path('panel-admin/ordenes-compra/<int:pk>/enviar-mensaje/', views.enviar_orden_compra_mensaje, name='enviar_orden_compra_mensaje'),
    path('panel-admin/ordenes-compra/<int:pk>/cambiar-estado/', views.cambiar_estado_orden_compra, name='cambiar_estado_orden_compra'),

    # Punto de Venta POS (Cajero)
    path('pos/', views.inicio_cajero, name='inicio_cajero'),
    path('pos/finalizar-venta/', views.finalizar_venta_pos, name='finalizar_venta_pos'),
    path('pos/historial/', views.historial_ventas_pos, name='historial_ventas_pos'),
    path('pos/historial/<int:pedido_id>/detalle/', views.detalle_venta_pos, name='detalle_venta_pos'),
    path('pos/apertura/', views.apertura_caja, name='apertura_caja'),
    path('pos/cierre/', views.cierre_caja, name='cierre_caja'),

    # Autenticación y Cuentas
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('registro/', views.registro_view, name='registro'),
    path('terminos-y-condiciones/', views.terminos_condiciones, name='terminos_condiciones'),
    path('politicas-de-privacidad/', views.politicas_privacidad, name='politicas_privacidad'),

    # Recuperación de Contraseña
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