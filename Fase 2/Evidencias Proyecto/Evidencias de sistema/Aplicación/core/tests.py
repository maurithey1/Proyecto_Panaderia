from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Categoria, DetallePedido, Pago, Pedido, Producto
from .retiro import ZONA_HORARIA, dias_de_retiro, franjas_del_dia, texto_retiro, validar_retiro
from .views import WEBPAY_VIGENCIA_MIN
from .zona_despacho import leer_coordenadas, punto_en_zona


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


class ZonaDespachoTests(TestCase):
    """El despacho solo se acepta si el punto confirmado en el mapa está dentro de la zona de despacho."""

    DENTRO = ('-33.54589', '-70.59603')  # el local, Marigen 9795
    FUERA_PUENTE_ALTO = ('-33.6117', '-70.5758')
    FUERA_SANTIAGO = ('-33.4489', '-70.6693')
    # Dentro del rectángulo que encierra la zona, pero fuera de su contorno (precordillera)
    FUERA_PRECORDILLERA = ('-33.5300', '-70.5150')

    def setUp(self):
        categoria = Categoria.objects.create(nombre='Panes')
        self.producto = Producto.objects.create(
            categoria=categoria, nombre='Pan de prueba',
            precio=Decimal('1000.00'), stock=5, activo=True,
        )
        self.client.post(reverse('carrito_agregar'), {'producto_id': self.producto.pk})

    def comprar_con_despacho(self, coordenadas, direccion='Marigen 9795, La Florida'):
        datos = {'tipo_entrega': 'DESPACHO', 'direccion_despacho': direccion}
        if coordenadas is not None:
            datos['latitud'], datos['longitud'] = coordenadas
        return self.client.post(reverse('finalizar_compra'), datos)

    def comprobar_rechazo(self, respuesta):
        # fetch_redirect_response=False: si se abriera el carrito aquí, el mensaje de error se consumiría.
        self.assertRedirects(respuesta, reverse('carrito'), fetch_redirect_response=False)
        self.assertFalse(Pedido.objects.exists())
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 5)

    def test_punto_dentro_de_la_zona_crea_el_pedido_con_despacho(self):
        respuesta = self.comprar_con_despacho(self.DENTRO)

        pedido = Pedido.objects.get()
        self.assertRedirects(respuesta, reverse('boleta_simulada', args=[pedido.pk]))
        self.assertEqual(pedido.tipo_entrega, 'DESPACHO')
        self.assertEqual(pedido.direccion_despacho, 'Marigen 9795, La Florida')

    def test_punto_fuera_de_la_zona_se_rechaza(self):
        for coordenadas in (self.FUERA_PUENTE_ALTO, self.FUERA_SANTIAGO, self.FUERA_PRECORDILLERA):
            self.comprobar_rechazo(self.comprar_con_despacho(coordenadas))

        carrito = self.client.get(reverse('carrito'))
        self.assertContains(carrito, 'fuera de la zona de despacho')
        self.assertContains(carrito, 'Marigen 9795')  # indica dónde puede retirar

    def test_despacho_sin_coordenadas_validas_se_rechaza(self):
        for coordenadas in (None, ('', ''), ('abc', 'xyz'), ('nan', 'nan'), ('95', '0'), ('-33.5', '500')):
            self.comprobar_rechazo(self.comprar_con_despacho(coordenadas))

    def test_retiro_no_necesita_coordenadas(self):
        self.client.post(reverse('finalizar_compra'), {'tipo_entrega': 'RETIRO'})

        self.assertEqual(Pedido.objects.get().tipo_entrega, 'RETIRO')

    def test_direccion_demasiado_larga_se_rechaza(self):
        self.comprobar_rechazo(self.comprar_con_despacho(self.DENTRO, direccion='1' + 'a' * 255))

    def test_funciones_de_la_zona(self):
        self.assertTrue(punto_en_zona(-33.54589, -70.59603))
        self.assertFalse(punto_en_zona(-33.6117, -70.5758))
        self.assertFalse(punto_en_zona(-33.5300, -70.5150))
        self.assertEqual(leer_coordenadas('-33.5', '-70.6'), (-33.5, -70.6))
        self.assertIsNone(leer_coordenadas('abc', '1'))
        self.assertIsNone(leer_coordenadas('inf', '1'))

    def test_el_carrito_ofrece_la_direccion_guardada_del_cliente_registrado(self):
        from .models import Cliente, Usuario

        usuario = Usuario.objects.create_user(username='11111111-1', password='abcdef', rol='CLIENTE')
        Cliente.objects.create(user=usuario, direccion='Av. Walker Martínez 1234, La Florida', telefono='+56 9 1')
        self.client.force_login(usuario)
        self.client.post(reverse('carrito_agregar'), {'producto_id': self.producto.pk})

        carrito = self.client.get(reverse('carrito'))

        self.assertContains(carrito, 'value="Av. Walker Martínez 1234, La Florida"')

    def test_los_detalles_de_entrega_se_guardan_junto_a_la_direccion(self):
        self.client.post(reverse('finalizar_compra'), {
            'tipo_entrega': 'DESPACHO',
            'direccion_despacho': 'Marigen 9795, La Florida',
            'detalles_entrega': 'Depto 402, Block B',
            'latitud': self.DENTRO[0],
            'longitud': self.DENTRO[1],
        })

        self.assertEqual(
            Pedido.objects.get().direccion_despacho,
            'Marigen 9795, La Florida (Depto 402, Block B)',
        )

    def test_direccion_con_detalles_demasiado_larga_se_rechaza(self):
        respuesta = self.client.post(reverse('finalizar_compra'), {
            'tipo_entrega': 'DESPACHO',
            'direccion_despacho': 'a' * 200 + ' 12',
            'detalles_entrega': 'b' * 100,
            'latitud': self.DENTRO[0],
            'longitud': self.DENTRO[1],
        })

        self.comprobar_rechazo(respuesta)

    def test_despacho_sin_numero_se_rechaza(self):
        respuesta = self.comprar_con_despacho(self.DENTRO, direccion='Duoc UC Sede Melipilla, Los Carreras, Melipilla')

        self.comprobar_rechazo(respuesta)
        self.assertContains(self.client.get(reverse('carrito')), 'Agrega el número de tu dirección')

    def test_despacho_acepta_sn_cuando_la_direccion_no_tiene_numero(self):
        self.comprar_con_despacho(self.DENTRO, direccion='Los Carreras S/N, La Florida')

        self.assertEqual(Pedido.objects.get().direccion_despacho, 'Los Carreras S/N, La Florida')


# Sábado 10 de octubre de 2026, 10:00 (hora de Chile): el horario de retiro de ese día es de 9:00 a 19:30
SABADO_10H = datetime(2026, 10, 10, 10, 0, tzinfo=ZONA_HORARIA)


class FranjasDeRetiroTests(TestCase):
    """El retiro se agenda en franjas de 30 minutos dentro del horario de retiro."""

    def test_hoy_parte_una_hora_despues_de_ahora(self):
        horas = franjas_del_dia(SABADO_10H.date(), SABADO_10H)

        self.assertEqual(horas[0], '11:00')   # 10:00 + 60 minutos de preparación
        self.assertEqual(horas[-1], '19:00')  # la última franja termina a las 19:30, cuando cierra

    def test_antes_de_abrir_parte_a_la_hora_de_apertura(self):
        temprano = datetime(2026, 10, 10, 7, 0, tzinfo=ZONA_HORARIA)

        self.assertEqual(franjas_del_dia(temprano.date(), temprano)[0], '09:00')

    def test_el_domingo_tiene_su_propio_horario(self):
        horas = franjas_del_dia(datetime(2026, 10, 11).date(), SABADO_10H)

        self.assertEqual((horas[0], horas[-1]), ('10:00', '13:00'))

    def test_pasada_la_hora_de_cierre_hoy_no_quedan_franjas(self):
        tarde = datetime(2026, 10, 10, 18, 45, tzinfo=ZONA_HORARIA)

        dias = dias_de_retiro(tarde)

        self.assertEqual(dias[0]['fecha'], '2026-10-11')
        self.assertEqual(dias[0]['etiqueta'], 'Mañana, domingo 11 de octubre')

    def test_dias_de_retiro_incluye_hoy_y_los_dias_siguientes(self):
        dias = dias_de_retiro(SABADO_10H)

        self.assertEqual(len(dias), 5)
        self.assertEqual(dias[0]['etiqueta'], 'Hoy, sábado 10 de octubre')
        self.assertEqual(dias[0]['horas'][0], {'valor': '11:00', 'texto': '11:00 a 11:30'})

    def test_validar_retiro(self):
        fecha, hora, error = validar_retiro('2026-10-10', '12:30', SABADO_10H)

        self.assertIsNone(error)
        self.assertEqual(texto_retiro(fecha, hora), 'sábado 10 de octubre, de 12:30 a 13:00')
        casos_invalidos = [
            ('2026-10-10', '10:30'),  # no alcanza a prepararse
            ('2026-10-10', '19:30'),  # a esa hora ya cerró
            ('2026-10-10', '12:15'),  # no es una franja
            ('2026-10-09', '12:00'),  # ayer
            ('2026-10-20', '12:00'),  # demasiado lejos
            ('2026-10-11', '09:00'),  # el domingo abre a las 10:00
            ('hoy', 'mediodía'),
        ]
        for fecha_texto, hora_texto in casos_invalidos:
            _, _, error = validar_retiro(fecha_texto, hora_texto, SABADO_10H)
            self.assertIsNotNone(error, (fecha_texto, hora_texto))


class RetiroProgramadoCompraTests(TestCase):
    """La compra con retiro guarda el día y la hora elegidos, y rechaza horas que no están disponibles."""

    def setUp(self):
        categoria = Categoria.objects.create(nombre='Panes')
        self.producto = Producto.objects.create(
            categoria=categoria, nombre='Pan de prueba',
            precio=Decimal('1000.00'), stock=5, activo=True,
        )
        self.client.post(reverse('carrito_agregar'), {'producto_id': self.producto.pk})
        # Se fija "ahora" para que las pruebas no dependan del día en que se ejecutan
        parche = mock.patch('core.retiro.ahora', return_value=SABADO_10H)
        parche.start()
        self.addCleanup(parche.stop)

    def test_el_carrito_muestra_la_direccion_del_local_y_las_franjas(self):
        carrito = self.client.get(reverse('carrito'))

        self.assertContains(carrito, 'Marigen 9795, La Florida')
        self.assertContains(carrito, 'Hoy, sábado 10 de octubre')
        self.assertContains(carrito, '11:00 a 11:30')

    def test_el_retiro_programado_se_guarda_y_sale_en_el_comprobante(self):
        respuesta = self.client.post(reverse('finalizar_compra'), {
            'tipo_entrega': 'RETIRO', 'fecha_retiro': '2026-10-10', 'hora_retiro': '12:00',
        })

        pedido = Pedido.objects.get()
        self.assertRedirects(respuesta, reverse('boleta_simulada', args=[pedido.pk]))
        self.assertEqual(
            pedido.direccion_despacho,
            'Retiro programado: sábado 10 de octubre, de 12:00 a 12:30',
        )
        comprobante = self.client.get(respuesta.url)
        self.assertContains(comprobante, 'sábado 10 de octubre, de 12:00 a 12:30')
        self.assertContains(comprobante, 'Marigen 9795, La Florida')

    def test_una_hora_que_no_esta_disponible_se_rechaza(self):
        respuesta = self.client.post(reverse('finalizar_compra'), {
            'tipo_entrega': 'RETIRO', 'fecha_retiro': '2026-10-10', 'hora_retiro': '10:30',
        })

        self.assertRedirects(respuesta, reverse('carrito'), fetch_redirect_response=False)
        self.assertFalse(Pedido.objects.exists())
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 5)
        self.assertContains(self.client.get(reverse('carrito')), 'ya no está disponible')

    def test_retiro_sin_agenda_sigue_funcionando(self):
        self.client.post(reverse('finalizar_compra'), {'tipo_entrega': 'RETIRO'})

        pedido = Pedido.objects.get()
        self.assertEqual(pedido.tipo_entrega, 'RETIRO')
        self.assertEqual(pedido.direccion_despacho, '')

    def test_el_despacho_ignora_la_agenda_de_retiro(self):
        self.client.post(reverse('finalizar_compra'), {
            'tipo_entrega': 'DESPACHO',
            'direccion_despacho': 'Marigen 9795, La Florida',
            'latitud': '-33.54589',
            'longitud': '-70.59603',
            'fecha_retiro': '2026-10-10',
            'hora_retiro': '12:00',
        })

        self.assertEqual(Pedido.objects.get().direccion_despacho, 'Marigen 9795, La Florida')


class WebpayPagoAbandonadoTests(TestCase):
    """Un pago con Webpay que no se completa no debe dejar un pedido PENDIENTE reteniendo stock."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre='Panes de prueba')
        self.producto = Producto.objects.create(
            categoria=self.categoria,
            nombre='Hogaza de prueba',
            precio=Decimal('1000.00'),
            stock=10,
            activo=True,
        )

    def _pedido_webpay(self, cantidad=3, minutos=0, estado='PENDIENTE'):
        """Un pedido como el que deja finalizar_compra al enviar al cliente a Webpay."""
        self.producto.stock -= cantidad
        self.producto.save(update_fields=['stock'])
        pedido = Pedido.objects.create(
            estado=estado, canal='WEB', tipo_entrega='RETIRO', total=Decimal('1000.00') * cantidad,
        )
        DetallePedido.objects.create(
            pedido=pedido, producto=self.producto, cantidad=cantidad,
            precio_unitario=self.producto.precio, subtotal=self.producto.precio * cantidad,
        )
        Pago.objects.create(
            pedido=pedido, monto=pedido.total, metodo='Webpay Plus', estado='PENDIENTE',
            codigo_autorizacion='TOKEN',
        )
        if minutos:
            Pedido.objects.filter(pk=pedido.pk).update(fecha=timezone.now() - timedelta(minutes=minutos))
        return pedido

    def _stock(self):
        return Producto.objects.get(pk=self.producto.pk).stock

    def _como_cliente_del_pedido(self, pedido):
        sesion = self.client.session
        sesion['webpay_pedido_id'] = pedido.pk
        sesion.save()

    def _timeout(self, pedido):
        return self.client.get(reverse('webpay_confirmar'), {
            'TBK_ID_SESION': 'sesion-de-transbank', 'TBK_ORDEN_COMPRA': f'ORD-{pedido.pk}',
        })

    def test_timeout_cancela_el_pedido_y_repone_el_stock(self):
        pedido = self._pedido_webpay(cantidad=3)
        self._como_cliente_del_pedido(pedido)
        self.assertEqual(self._stock(), 7)

        respuesta = self._timeout(pedido)

        self.assertRedirects(respuesta, reverse('carrito'), fetch_redirect_response=False)
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'CANCELADO')
        self.assertEqual(pedido.pago.estado, 'EXPIRADO')
        self.assertEqual(self._stock(), 10)
        self.assertIn('Se agotó el tiempo', ' '.join(str(m) for m in get_messages(respuesta.wsgi_request)))

    def test_timeout_repetido_no_repone_dos_veces(self):
        pedido = self._pedido_webpay(cantidad=3)
        self._como_cliente_del_pedido(pedido)

        self._timeout(pedido)
        self._como_cliente_del_pedido(pedido)
        self._timeout(pedido)

        self.assertEqual(self._stock(), 10)

    def test_timeout_no_cancela_el_pedido_de_otra_sesion(self):
        pedido = self._pedido_webpay(cantidad=3)  # esta sesión no inició ese pedido

        self._timeout(pedido)

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'PENDIENTE')
        self.assertEqual(self._stock(), 7)

    def test_retorno_sin_nada_sigue_pidiendo_el_token(self):
        respuesta = self.client.get(reverse('webpay_confirmar'))

        self.assertRedirects(respuesta, reverse('carrito'), fetch_redirect_response=False)
        self.assertIn('No se recibió el token', ' '.join(str(m) for m in get_messages(respuesta.wsgi_request)))

    def test_pedido_abandonado_se_libera_al_ver_el_carrito(self):
        pedido = self._pedido_webpay(cantidad=3, minutos=WEBPAY_VIGENCIA_MIN + 1)

        self.client.get(reverse('carrito'))

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'CANCELADO')
        self.assertEqual(pedido.pago.estado, 'EXPIRADO')
        self.assertEqual(self._stock(), 10)

    def test_el_catalogo_no_muestra_el_stock_de_un_pago_abandonado(self):
        pedido = self._pedido_webpay(cantidad=3, minutos=WEBPAY_VIGENCIA_MIN + 1)

        respuesta = self.client.get(reverse('pedir'))

        self.assertContains(respuesta, '<strong>Stock:</strong> 10')
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'CANCELADO')

    def test_pedido_reciente_no_se_libera(self):
        pedido = self._pedido_webpay(cantidad=3, minutos=WEBPAY_VIGENCIA_MIN - 5)

        self.client.get(reverse('carrito'))

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'PENDIENTE')
        self.assertEqual(self._stock(), 7)

    def test_pedidos_pagados_no_se_tocan(self):
        pedido = self._pedido_webpay(cantidad=3, minutos=WEBPAY_VIGENCIA_MIN + 60, estado='PAGADO')

        self.client.get(reverse('carrito'))

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'PAGADO')
        self.assertEqual(self._stock(), 7)

    def test_intentar_nuevamente_cancela_el_pedido_sin_confirmar_el_pago(self):
        """La página de error de Webpay vuelve con TBK_TOKEN y token_ws, por POST y sin cookie."""
        pedido = self._pedido_webpay(cantidad=3)  # su token guardado es 'TOKEN'

        with mock.patch('core.views.obtener_transaccion_webpay') as obtener:
            respuesta = self.client.post(reverse('webpay_confirmar'), {
                'token_ws': 'TOKEN', 'TBK_TOKEN': 'TOKEN',
                'TBK_ORDEN_COMPRA': f'ORD-{pedido.pk}', 'TBK_ID_SESION': 'sesion',
            })

        obtener.return_value.commit.assert_not_called()
        self.assertRedirects(respuesta, reverse('carrito'), fetch_redirect_response=False)
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'CANCELADO')
        self.assertEqual(self._stock(), 10)
        mensajes = ' '.join(str(m) for m in get_messages(respuesta.wsgi_request))
        self.assertIn('puedes intentarlo de nuevo', mensajes)

    def test_anular_cancela_solo_con_el_token_del_pedido(self):
        pedido = self._pedido_webpay(cantidad=3)

        # Quien solo conoce el número de pedido no puede cancelarlo.
        self.client.get(reverse('webpay_confirmar'), {
            'TBK_TOKEN': 'adivinado', 'TBK_ORDEN_COMPRA': f'ORD-{pedido.pk}',
        })
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'PENDIENTE')
        self.assertEqual(self._stock(), 7)

        # Con el token que entregó Transbank sí, y una sola vez.
        for _ in range(2):
            self.client.get(reverse('webpay_confirmar'), {
                'TBK_TOKEN': 'TOKEN', 'TBK_ORDEN_COMPRA': f'ORD-{pedido.pk}',
            })
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'CANCELADO')
        self.assertEqual(self._stock(), 10)

    def _retorno_con_commit_en_error(self, pedido, estado_real):
        """El retorno de Transbank cuando el commit falla con 422 (todavía autorizando)."""
        self._como_cliente_del_pedido(pedido)
        with mock.patch('core.views.obtener_transaccion_webpay') as obtener, \
                mock.patch('core.views.time.sleep'):
            tx = obtener.return_value
            tx.commit.side_effect = Exception("Invalid status '10' for transaction while authorizing (422)")
            tx.status.return_value = estado_real
            respuesta = self.client.get(reverse('webpay_confirmar'), {'token_ws': 'TOKEN'})
        return respuesta, ' '.join(str(m) for m in get_messages(respuesta.wsgi_request))

    def test_error_422_mientras_autoriza_no_cancela_el_pedido(self):
        pedido = self._pedido_webpay(cantidad=3)

        respuesta, mensajes = self._retorno_con_commit_en_error(pedido, {'status': 'INITIALIZED'})

        self.assertRedirects(respuesta, reverse('carrito'), fetch_redirect_response=False)
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'PENDIENTE')
        self.assertEqual(self._stock(), 7)
        self.assertIn('Estamos confirmando tu pago', mensajes)
        self.assertNotIn('422', mensajes)

    def test_error_en_commit_pero_pago_autorizado_deja_el_pedido_pagado(self):
        pedido = self._pedido_webpay(cantidad=3)

        respuesta, _ = self._retorno_con_commit_en_error(pedido, {
            'status': 'AUTHORIZED', 'response_code': 0, 'buy_order': f'ORD-{pedido.pk}',
            'amount': 3000, 'payment_type_code': 'VD', 'authorization_code': '1415',
        })

        self.assertRedirects(
            respuesta, reverse('boleta_simulada', args=[pedido.pk]), fetch_redirect_response=False,
        )
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'PAGADO')
        self.assertEqual(pedido.pago.estado, 'APROBADO')
        self.assertEqual(self._stock(), 7)

    def test_error_en_commit_pero_pago_rechazado_repone_el_stock(self):
        pedido = self._pedido_webpay(cantidad=3)

        respuesta, _ = self._retorno_con_commit_en_error(pedido, {
            'status': 'FAILED', 'response_code': -1, 'buy_order': f'ORD-{pedido.pk}',
        })

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'CANCELADO')
        self.assertEqual(self._stock(), 10)

    def test_quien_reintenta_no_queda_bloqueado_por_su_pago_abandonado(self):
        # Un pedido abandonado retiene 8 de 10: sin liberarlo, no alcanzaría el stock para comprar 5.
        pedido = self._pedido_webpay(cantidad=8, minutos=WEBPAY_VIGENCIA_MIN + 1)
        self.assertEqual(self._stock(), 2)
        for _ in range(5):
            self.client.post(reverse('carrito_agregar'), {'producto_id': self.producto.pk})

        self.client.post(reverse('finalizar_compra'), {'tipo_entrega': 'RETIRO'})

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'CANCELADO')
        nuevo = Pedido.objects.exclude(pk=pedido.pk).get()
        self.assertEqual(nuevo.estado, 'PAGADO')
        self.assertEqual(self._stock(), 5)
