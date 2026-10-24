from .models import Notificacion
from .alertas import verificar_y_generar_alertas_stock

def notificaciones_admin(request):
    if request.user.is_authenticated and getattr(request.user, 'es_administrador', False):
        # 1. Verifica y genera alertas de stock
        verificar_y_generar_alertas_stock(request)

        # 2. Cuenta solo las no leídas
        no_leidas_count = Notificacion.objects.filter(leida=False).count()

        # 3. Muestra únicamente las notificaciones NO LEÍDAS en el menú de la campana (máximo 5)
        recientes_no_leidas = Notificacion.objects.filter(leida=False).order_by('-fecha_creacion')[:5]

        return {
            'cant_notificaciones_no_leidas': no_leidas_count,
            'notificaciones_dropdown': recientes_no_leidas,
        }
    return {}


def contador_carrito(request):
    """
    Devuelve la cantidad de ítems/productos distintos guardados en el carrito de sesión.
    """
    carrito = request.session.get('carrito', {})
    if isinstance(carrito, dict):
        # Cuenta la cantidad de claves distintas cuyo valor sea > 0
        total_items = len([cant for cant in carrito.values() if isinstance(cant, int) and cant > 0])
    else:
        total_items = 0

    return {
        'cant_carrito': total_items
    }