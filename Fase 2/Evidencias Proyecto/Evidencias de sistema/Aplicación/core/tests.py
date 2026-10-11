from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import Categoria, DetallePedido, Pago, Pedido, Producto


class CarritoCompraTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre='Panes de prueba')
        self.producto = Producto.objects.create(
            categoria=self.categoria,
            nombre='Hogaza de prueba',
            descripcion='Pan artesanal para pruebas.',
            precio=Decimal('3500.00'),
            stock=3,
            activo=True,
        )

    def test_agregar_y_quitar_producto_del_carrito(self):
        url_agregar = reverse('carrito_agregar')
        self.client.post(url_agregar, {'producto_id': self.producto.pk})
        self.client.post(url_agregar, {'producto_id': self.producto.pk})

        self.assertEqual(
            self.client.session['carrito'][str(self.producto.pk)],
            2,
        )

        respuesta = self.client.post(
            reverse('carrito_quitar', args=[self.producto.pk])
        )

        self.assertRedirects(respuesta, reverse('carrito'))
        self.assertNotIn(str(self.producto.pk), self.client.session['carrito'])

    def test_compra_de_demostracion_crea_pedido_pago_simulado_y_boleta(self):
        self.client.post(
            reverse('carrito_agregar'),
            {'producto_id': self.producto.pk},
        )

        respuesta = self.client.post(
            reverse('finalizar_compra'),
            {'tipo_entrega': 'RETIRO'},
        )

        pedido = Pedido.objects.get()
        self.assertRedirects(
            respuesta,
            reverse('boleta_simulada', args=[pedido.pk]),
        )
        self.assertEqual(pedido.estado, 'PAGADO')
        self.assertEqual(pedido.total, Decimal('3500.00'))
        self.assertEqual(pedido.detalles.get().cantidad, 1)
        self.assertEqual(pedido.pago.estado, 'SIMULADO')
        self.assertIn('sin cobro real', pedido.pago.metodo)
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 2)
        self.assertEqual(self.client.session['carrito'], {})

        boleta = self.client.get(respuesta.url)
        self.assertContains(boleta, 'Comprobante simulado')
        self.assertContains(boleta, 'no acredita un pago real')

    def test_no_finaliza_si_no_hay_stock_suficiente(self):
        sesion = self.client.session
        sesion['carrito'] = {str(self.producto.pk): 4}
        sesion.save()

        respuesta = self.client.post(
            reverse('finalizar_compra'),
            {'tipo_entrega': 'RETIRO'},
        )

        self.assertRedirects(respuesta, reverse('carrito'))
        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(DetallePedido.objects.exists())
        self.assertFalse(Pago.objects.exists())
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 3)

    def test_boleta_no_es_visible_en_otra_sesion(self):
        pedido = Pedido.objects.create(total=Decimal('100.00'))

        respuesta = self.client.get(
            reverse('boleta_simulada', args=[pedido.pk])
        )

        self.assertEqual(respuesta.status_code, 404)


class CatalogoDesdeBaseDeDatosTests(TestCase):
    """El catálogo, el carrito y la compra deben hablar de los mismos productos: los de la BD."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre='Panes')
        self.otra_categoria = Categoria.objects.create(nombre='Tortas')
        self.pan = Producto.objects.create(
            categoria=self.categoria, nombre='Marraqueta de prueba',
            precio=Decimal('2190.00'), stock=10, activo=True,
        )
        self.torta = Producto.objects.create(
            categoria=self.otra_categoria, nombre='Torta de prueba',
            precio=Decimal('18990.00'), stock=5, activo=True,
        )

    def test_catalogo_muestra_los_productos_de_la_bd(self):
        respuesta = self.client.get(reverse('pedir'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            {p.pk for p in respuesta.context['productos']},
            {self.pan.pk, self.torta.pk},
        )

    def test_lo_que_se_agrega_es_lo_que_se_eligio(self):
        # Regresión: el catálogo llegó a numerar los productos por su posición en un JSON
        # y el carrito agregaba otro producto distinto.
        respuesta = self.client.get(reverse('pedir'))

        for producto in respuesta.context['productos']:
            visitante = self.client_class()
            visitante.post(reverse('carrito_agregar'), {'producto_id': producto.pk})
            carrito = visitante.get(reverse('carrito'))

            self.assertContains(carrito, producto.nombre)
            self.assertEqual(
                [item['producto'].pk for item in carrito.context['items']],
                [producto.pk],
            )

    def test_producto_inactivo_no_aparece(self):
        self.torta.activo = False
        self.torta.save()

        respuesta = self.client.get(reverse('pedir'))

        self.assertEqual([p.pk for p in respuesta.context['productos']], [self.pan.pk])

    def test_filtro_por_categoria_y_valores_invalidos(self):
        filtrado = self.client.get(reverse('pedir'), {'categoria': self.categoria.pk})
        self.assertEqual([p.pk for p in filtrado.context['productos']], [self.pan.pk])

        for valor in ('\u00b2', '999', 'abc', '9' * 30, '9' * 5000):
            respuesta = self.client.get(reverse('pedir'), {'categoria': valor})
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(len(respuesta.context['productos']), 2)

    def test_agregar_con_valor_invalido_no_da_error(self):
        for valor in ('\u00b2', 'abc', '', '9' * 30, '9' * 5000):
            respuesta = self.client.post(reverse('carrito_agregar'), {'producto_id': valor})
            self.assertRedirects(respuesta, reverse('pedir'))

    def test_stock_del_catalogo_baja_despues_de_comprar(self):
        self.client.post(reverse('carrito_agregar'), {'producto_id': self.pan.pk})
        self.client.post(reverse('finalizar_compra'), {'tipo_entrega': 'RETIRO'})

        respuesta = self.client.get(reverse('pedir'))
        pan = next(p for p in respuesta.context['productos'] if p.pk == self.pan.pk)

        self.assertEqual(pan.stock, 9)

    def test_inicio_ordena_por_ventas_sin_contar_cancelados(self):
        vendido = Pedido.objects.create(total=Decimal('56970.00'), estado='PAGADO')
        DetallePedido.objects.create(
            pedido=vendido, producto=self.torta, cantidad=3,
            precio_unitario=self.torta.precio, subtotal=self.torta.precio * 3,
        )
        cancelado = Pedido.objects.create(total=Decimal('109500.00'), estado='CANCELADO')
        DetallePedido.objects.create(
            pedido=cancelado, producto=self.pan, cantidad=50,
            precio_unitario=self.pan.precio, subtotal=self.pan.precio * 50,
        )

        respuesta = self.client.get(reverse('inicio'))

        self.assertEqual(respuesta.context['productos'][0].pk, self.torta.pk)
