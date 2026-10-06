from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import render

from .models import Pedido, Producto

PRODUCTOS_DESTACADOS = 4


def inicio(request):
    """Menú principal de la tienda: muestra los productos más pedidos."""
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
