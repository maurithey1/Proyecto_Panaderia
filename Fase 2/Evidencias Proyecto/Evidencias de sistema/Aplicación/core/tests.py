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
