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