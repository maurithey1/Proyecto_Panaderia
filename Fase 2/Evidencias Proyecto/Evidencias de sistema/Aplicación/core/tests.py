import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escapejs
from django.utils import timezone

from .disponibilidad import esta_disponible, proxima_disponibilidad, texto_proxima
from .disponibilidad import resumen as resumen_de_disponibilidad
from .models import Categoria, DetallePedido, Pago, Pedido, Producto, Turno, Usuario
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

    def test_el_despacho_tambien_se_programa_con_la_agenda(self):
        self.client.post(reverse('finalizar_compra'), {
            'tipo_entrega': 'DESPACHO',
            'direccion_despacho': 'Marigen 9795, La Florida',
            'latitud': '-33.54589',
            'longitud': '-70.59603',
            'fecha_retiro': '2026-10-10',
            'hora_retiro': '12:00',
        })

        self.assertEqual(
            Pedido.objects.get().direccion_despacho,
            'Marigen 9795, La Florida · Entrega programada: sábado 10 de octubre, de 12:00 a 12:30',
        )


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


class BusquedaDeProductosTests(TestCase):
    """Buscar productos por nombre o categoría en el catálogo (/pedir/?q=)."""

    def setUp(self):
        panaderia = Categoria.objects.create(nombre='Panadería')
        empanadas = Categoria.objects.create(nombre='Empanadas')
        self.dulces = Categoria.objects.create(nombre='Dulces')
        pasteleria = Categoria.objects.create(nombre='Pastelería')

        def crear(nombre, categoria, stock=5, activo=True):
            return Producto.objects.create(
                categoria=categoria, nombre=nombre, precio=Decimal('1000.00'), stock=stock, activo=activo,
            )

        crear('Marraqueta (Pan Batido)', panaderia)
        crear('Hallulla Especial', panaderia)
        crear('Pan Amasado Tradicional', panaderia)
        crear('Pan Antiguo', panaderia, activo=False)
        crear('Empanada de Pino', empanadas)
        crear('Berlinés con Manjar', self.dulces)
        crear('Berlinés Crema Pastelera', self.dulces, stock=0)
        crear('Pan de Pascua', pasteleria)

    def _buscar(self, **parametros):
        respuesta = self.client.get(reverse('pedir'), parametros)
        self.assertEqual(respuesta.status_code, 200)
        return [p.nombre for p in respuesta.context['productos']], respuesta

    def test_busca_por_parte_del_nombre_sin_importar_las_mayusculas(self):
        nombres, respuesta = self._buscar(q='MARRAQ')

        self.assertEqual(nombres, ['Marraqueta (Pan Batido)'])
        self.assertContains(respuesta, '1 resultado para «MARRAQ»')

    def test_pan_no_trae_empanadas(self):
        nombres, _ = self._buscar(q='pan')

        self.assertNotIn('Empanada de Pino', nombres)

    def test_pan_muestra_toda_la_categoria_y_luego_los_parecidos_en_el_nombre(self):
        nombres, respuesta = self._buscar(q='pan')

        # Primero la categoría "Panadería" completa (con el nombre más parecido arriba) y después
        # el "Pan de Pascua", que solo calza por su nombre. El producto inactivo no aparece.
        self.assertEqual(nombres, [
            'Pan Amasado Tradicional',
            'Marraqueta (Pan Batido)',
            'Hallulla Especial',
            'Pan de Pascua',
        ])
        self.assertContains(respuesta, '4 resultados para «pan»')

    def test_acepta_el_plural(self):
        panes, _ = self._buscar(q='panes')
        empanadas, _ = self._buscar(q='empanadas')

        self.assertIn('Hallulla Especial', panes)
        self.assertEqual(empanadas, ['Empanada de Pino'])

    def test_ignora_las_tildes_en_ambos_sentidos(self):
        sin_tilde, _ = self._buscar(q='berlines')
        con_tilde, _ = self._buscar(q='amásado')
        categoria, _ = self._buscar(q='panaderia')

        self.assertEqual(len(sin_tilde), 2)
        self.assertEqual(con_tilde, ['Pan Amasado Tradicional'])
        self.assertIn('Hallulla Especial', categoria)

    def test_varias_palabras_en_cualquier_orden(self):
        nombres, _ = self._buscar(q='tradicional  amasado')

        self.assertEqual(nombres, ['Pan Amasado Tradicional'])

    def test_no_muestra_productos_inactivos(self):
        nombres, respuesta = self._buscar(q='antiguo')

        self.assertEqual(nombres, [])
        self.assertContains(respuesta, 'No encontramos productos que coincidan con «antiguo»')

    def test_los_agotados_van_al_final_de_los_resultados(self):
        nombres, _ = self._buscar(q='berlines')

        self.assertEqual(nombres, ['Berlinés con Manjar', 'Berlinés Crema Pastelera'])

    def test_sin_resultados_ofrece_volver_al_catalogo(self):
        _, respuesta = self._buscar(q='pizza')

        self.assertContains(respuesta, 'No encontramos productos')
        self.assertContains(respuesta, 'Ver todos los productos')

    def test_la_busqueda_se_combina_con_la_categoria(self):
        dentro, _ = self._buscar(q='berlines', categoria=self.dulces.pk)
        fuera, _ = self._buscar(q='pan', categoria=self.dulces.pk)

        self.assertEqual(len(dentro), 2)
        self.assertEqual(fuera, [])

    def test_texto_en_blanco_equivale_a_no_buscar(self):
        nombres, respuesta = self._buscar(q='   ')

        self.assertEqual(len(nombres), 7)
        self.assertNotContains(respuesta, 'para «')  # no muestra "N resultados para …"

    def test_solo_simbolos_no_trae_nada(self):
        nombres, _ = self._buscar(q='%%__')

        self.assertEqual(nombres, [])

    def test_caracteres_especiales_no_rompen_la_pagina_ni_se_ejecutan(self):
        nombres, respuesta = self._buscar(q="%_'\"<script>alert(1)</script>")

        self.assertEqual(nombres, [])
        self.assertNotContains(respuesta, '<script>alert(1)')
        self.assertContains(respuesta, '&lt;script&gt;')

    def test_una_busqueda_enorme_se_recorta(self):
        nombres, respuesta = self._buscar(q='a ' * 500)

        self.assertEqual(respuesta.status_code, 200)
        self.assertLessEqual(len(respuesta.context['busqueda']), 80)


class BusquedaEnVivoTests(TestCase):
    """La búsqueda en vivo pide solo la zona de resultados (?parcial=1)."""

    def setUp(self):
        categoria = Categoria.objects.create(nombre='Panadería')
        for nombre in ('Marraqueta (Pan Batido)', 'Hallulla Especial'):
            Producto.objects.create(
                categoria=categoria, nombre=nombre, precio=Decimal('1000.00'), stock=5, activo=True,
            )

    def test_la_respuesta_parcial_trae_solo_los_resultados(self):
        respuesta = self.client.get(reverse('pedir'), {'q': 'marraq', 'parcial': '1'})

        self.assertContains(respuesta, 'Marraqueta (Pan Batido)')
        self.assertContains(respuesta, '1 resultado para «marraq»')
        self.assertNotContains(respuesta, '<html')
        self.assertNotContains(respuesta, 'Buscar productos por nombre')  # el formulario no se repite
        self.assertNotContains(respuesta, 'Hallulla Especial')

    def test_la_pagina_completa_incluye_buscador_script_y_resultados(self):
        respuesta = self.client.get(reverse('pedir'), {'q': 'marraq'})

        self.assertContains(respuesta, '<html')
        self.assertContains(respuesta, 'id="buscar-producto"')
        self.assertContains(respuesta, 'busqueda_catalogo.js')
        self.assertContains(respuesta, 'id="resultados"')
        self.assertContains(respuesta, 'Marraqueta (Pan Batido)')

    def test_la_respuesta_parcial_escapa_el_texto_buscado(self):
        respuesta = self.client.get(reverse('pedir'), {'q': '<img src=x onerror=alert(1)>', 'parcial': '1'})

        self.assertNotContains(respuesta, '<img src=x')
        self.assertContains(respuesta, '&lt;img')

    def test_la_respuesta_parcial_sin_busqueda_trae_el_catalogo(self):
        respuesta = self.client.get(reverse('pedir'), {'parcial': '1'})

        self.assertContains(respuesta, 'Hallulla Especial')
        self.assertContains(respuesta, 'Marraqueta (Pan Batido)')
        self.assertNotContains(respuesta, '<html')


class PlantillasSinRestosTests(TestCase):
    """Ninguna página pública debe mostrar código de plantilla sin interpretar.

    Un comentario {# ... #} partido en dos líneas, por ejemplo, Django lo imprime como texto.
    """

    def setUp(self):
        categoria = Categoria.objects.create(nombre='Panadería')
        self.producto = Producto.objects.create(
            categoria=categoria, nombre='Marraqueta', precio=Decimal('1000.00'), stock=5, activo=True,
        )

    def test_las_paginas_publicas_no_muestran_etiquetas_de_plantilla(self):
        self.client.post(reverse('carrito_agregar'), {'producto_id': self.producto.pk})
        direcciones = [
            reverse('inicio'),
            reverse('pedir'),
            reverse('pedir') + '?q=marraq',
            reverse('pedir') + '?q=marraq&parcial=1',
            reverse('carrito'),
            reverse('local'),
            reverse('login'),
            reverse('registro'),
            reverse('terminos_condiciones'),
            reverse('politicas_privacidad'),
        ]
        for direccion in direcciones:
            with self.subTest(direccion=direccion):
                contenido = self.client.get(direccion).content.decode()
                for resto in ('{#', '#}', '{%', '%}', '{{', '}}'):
                    self.assertNotIn(resto, contenido)


class LimpiarBusquedaTests(TestCase):
    """El enlace "Limpiar" reemplaza a la "x" nativa y al botón Buscar."""

    def setUp(self):
        categoria = Categoria.objects.create(nombre='Panadería')
        Producto.objects.create(
            categoria=categoria, nombre='Marraqueta', precio=Decimal('1000.00'), stock=5, activo=True,
        )

    def test_con_busqueda_muestra_limpiar_hacia_el_catalogo_completo(self):
        respuesta = self.client.get(reverse('pedir'), {'q': 'marraq'})
        contenido = respuesta.content.decode()

        enlace = contenido[contenido.index('class="buscador__limpiar"'):]
        enlace = enlace[:enlace.index('</a>')]
        self.assertIn(f'href="{reverse("pedir")}"', enlace)
        self.assertIn('data-limpiar', enlace)
        self.assertNotIn('hidden', enlace)
        self.assertIn('>Limpiar', enlace)

    def test_sin_busqueda_limpiar_va_oculto(self):
        contenido = self.client.get(reverse('pedir')).content.decode()

        enlace = contenido[contenido.index('class="buscador__limpiar"'):]
        enlace = enlace[:enlace.index('</a>')]
        self.assertIn('hidden', enlace)

    def test_el_boton_buscar_solo_existe_sin_javascript(self):
        contenido = self.client.get(reverse('pedir')).content.decode()

        formulario = contenido[contenido.index('<form class="buscador"'):]
        formulario = formulario[:formulario.index('</form>')]
        self.assertIn('<noscript><button', formulario)
        self.assertEqual(formulario.count('<button'), 1)  # el único botón está dentro de <noscript>


SABADO_10H_TURNOS = datetime(2026, 10, 10, 10, 0, tzinfo=ZONA_HORARIA)   # sábado por la mañana
LUNES_16H_TURNOS = datetime(2026, 10, 12, 16, 0, tzinfo=ZONA_HORARIA)    # lunes por la tarde


class TurnoModeloTests(TestCase):
    """Un turno es una franja horaria con los días de la semana en que rige."""

    def _turno(self, **campos):
        datos = dict(nombre='T', hora_inicio=time(9, 0), hora_fin=time(14, 0))
        datos.update(campos)
        return Turno(**datos)

    def test_texto_de_los_dias(self):
        todos = self._turno()
        lun_sab = self._turno(domingo=False)
        fin_de_semana = self._turno(lunes=False, martes=False, miercoles=False, jueves=False, viernes=False)
        alternados = self._turno(martes=False, jueves=False, sabado=False, domingo=False)
        un_dia = self._turno(lunes=False, martes=False, miercoles=False, jueves=False, viernes=False, domingo=False)

        self.assertEqual(todos.dias_texto, 'todos los días')
        self.assertEqual(lun_sab.dias_texto, 'lunes a sábado')
        self.assertEqual(fin_de_semana.dias_texto, 'sábado y domingo')
        self.assertEqual(alternados.dias_texto, 'lunes, miércoles, viernes')
        self.assertEqual(un_dia.dias_texto, 'sábado')

    def test_descripcion_para_el_cliente(self):
        turno = self._turno(nombre='Tarde', hora_inicio=time(14, 0), hora_fin=time(19, 30), domingo=False)

        self.assertEqual(turno.descripcion, 'Tarde, 14:00 a 19:30, lunes a sábado')

    def test_rige_segun_dia_y_hora(self):
        turno = self._turno(domingo=False)  # 09:00 a 14:00, lunes a sábado

        self.assertTrue(turno.rige_en(SABADO_10H_TURNOS))
        self.assertFalse(turno.rige_en(LUNES_16H_TURNOS))                                    # fuera de hora
        self.assertFalse(turno.rige_en(datetime(2026, 10, 11, 10, 0, tzinfo=ZONA_HORARIA)))  # domingo
        self.assertFalse(turno.rige_en(datetime(2026, 10, 10, 14, 0, tzinfo=ZONA_HORARIA)))  # el fin no cuenta

    def test_un_turno_puede_cruzar_la_medianoche(self):
        noche = self._turno(hora_inicio=time(20, 0), hora_fin=time(2, 0))

        self.assertTrue(noche.rige_en(datetime(2026, 10, 10, 23, 0, tzinfo=ZONA_HORARIA)))
        self.assertTrue(noche.rige_en(datetime(2026, 10, 10, 1, 0, tzinfo=ZONA_HORARIA)))
        self.assertFalse(noche.rige_en(datetime(2026, 10, 10, 12, 0, tzinfo=ZONA_HORARIA)))

    def test_validaciones(self):
        sin_dias = self._turno(lunes=False, martes=False, miercoles=False, jueves=False, viernes=False,
                               sabado=False, domingo=False)
        misma_hora = self._turno(hora_fin=time(9, 0))

        with self.assertRaises(ValidationError):
            sin_dias.clean()
        with self.assertRaises(ValidationError):
            misma_hora.clean()
        self._turno().clean()  # uno válido no falla


class CatalogoPorTurnoTests(TestCase):
    """Navegar el catálogo por turno de venta, combinado con categoría y búsqueda."""

    def setUp(self):
        self.panaderia = Categoria.objects.create(nombre='Panadería')
        self.pasteleria = Categoria.objects.create(nombre='Pastelería')
        self.manana = Turno.objects.create(nombre='Mañana', hora_inicio=time(9, 0), hora_fin=time(14, 0))
        self.tarde = Turno.objects.create(
            nombre='Tarde', hora_inicio=time(14, 0), hora_fin=time(19, 30), domingo=False,
        )

        def crear(nombre, categoria, turnos=()):
            producto = Producto.objects.create(
                categoria=categoria, nombre=nombre, precio=Decimal('1000.00'), stock=5, activo=True,
            )
            producto.turnos.set(turnos)
            return producto

        self.marraqueta = crear('Marraqueta', self.panaderia)                              # todo el día
        self.empanada = crear('Empanada de Pino', self.panaderia, [self.manana])
        self.torta = crear('Torta de Mil Hojas', self.pasteleria, [self.tarde])
        self.kuchen = crear('Kuchen de Nuez', self.pasteleria, [self.manana, self.tarde])

    def _nombres(self, **parametros):
        respuesta = self.client.get(reverse('pedir'), parametros)
        self.assertEqual(respuesta.status_code, 200)
        return sorted(p.nombre for p in respuesta.context['productos']), respuesta

    def test_sin_filtro_muestra_todo_el_catalogo(self):
        nombres, _ = self._nombres()

        self.assertEqual(len(nombres), 4)

    def test_turno_manana_incluye_lo_del_turno_y_lo_de_todo_el_dia(self):
        nombres, _ = self._nombres(turno=self.manana.pk)

        self.assertEqual(nombres, ['Empanada de Pino', 'Kuchen de Nuez', 'Marraqueta'])

    def test_turno_tarde_no_incluye_lo_de_la_manana(self):
        nombres, _ = self._nombres(turno=self.tarde.pk)

        self.assertEqual(nombres, ['Kuchen de Nuez', 'Marraqueta', 'Torta de Mil Hojas'])

    def test_turno_y_categoria_se_combinan(self):
        nombres, _ = self._nombres(turno=self.tarde.pk, categoria=self.pasteleria.pk)

        self.assertEqual(nombres, ['Kuchen de Nuez', 'Torta de Mil Hojas'])

    def test_la_busqueda_respeta_el_turno(self):
        en_manana, _ = self._nombres(q='empanada', turno=self.manana.pk)
        en_tarde, respuesta = self._nombres(q='empanada', turno=self.tarde.pk)

        self.assertEqual(en_manana, ['Empanada de Pino'])
        self.assertEqual(en_tarde, [])
        self.assertContains(respuesta, 'No encontramos productos que coincidan con «empanada»')

    def test_un_turno_invalido_o_desactivado_se_ignora(self):
        self.tarde.activo = False
        self.tarde.save()

        desactivado, _ = self._nombres(turno=self.tarde.pk)
        inexistente, _ = self._nombres(turno=9999)
        basura, _ = self._nombres(turno='abc')

        self.assertEqual(len(desactivado), 4)
        self.assertEqual(len(inexistente), 4)
        self.assertEqual(len(basura), 4)

    def test_un_producto_con_solo_turnos_desactivados_se_vende_todo_el_dia(self):
        self.tarde.activo = False
        self.tarde.save()

        nombres, _ = self._nombres(turno=self.manana.pk)

        self.assertIn('Torta de Mil Hojas', nombres)   # su único turno quedó desactivado


    def test_sin_productos_en_el_turno_y_categoria_avisa(self):
        Producto.objects.filter(pk=self.marraqueta.pk).update(activo=False)

        nombres, respuesta = self._nombres(turno=self.tarde.pk, categoria=self.panaderia.pk)

        self.assertEqual(nombres, [])
        self.assertContains(respuesta, 'Por ahora no hay productos en el turno Tarde de esta categoría')


    def test_limpiar_la_busqueda_conserva_los_filtros(self):
        respuesta = self.client.get(reverse('pedir'), {'q': 'kuchen', 'turno': self.tarde.pk})
        html = respuesta.content.decode()

        enlace = html[html.index('class="buscador__limpiar"'):]
        enlace = enlace[:enlace.index('</a>')]
        self.assertIn(f'href="{reverse("pedir")}?turno={self.tarde.pk}"', enlace)







    def test_las_categorias_conservan_el_turno_de_la_url(self):
        respuesta = self.client.get(reverse('pedir'), {'turno': self.tarde.pk, 'categoria': self.pasteleria.pk})
        html = respuesta.content.decode()

        self.assertIn(f'?categoria={self.panaderia.pk}&amp;turno={self.tarde.pk}', html)
        self.assertIn(f'name="turno" value="{self.tarde.pk}"', html)
        self.assertIn(f'name="categoria" value="{self.pasteleria.pk}"', html)

    def test_no_hay_fila_de_turnos_en_el_catalogo(self):
        respuesta = self.client.get(reverse('pedir'))

        self.assertNotContains(respuesta, 'aria-label="Turnos de venta"')
        self.assertNotContains(respuesta, 'Todos los turnos')

    def test_informa_los_turnos_vigentes_con_la_hora_de_chile(self):
        almuerzo = Turno.objects.create(nombre='Almuerzo', hora_inicio=time(12, 0), hora_fin=time(15, 0))
        self.marraqueta.turnos.set([almuerzo])   # el catálogo solo considera turnos que algún producto usa
        a_las_13 = datetime(2026, 10, 10, 13, 0, tzinfo=ZONA_HORARIA)   # sábado: rigen Mañana y Almuerzo
        de_noche = datetime(2026, 10, 10, 23, 0, tzinfo=ZONA_HORARIA)

        with mock.patch('core.views.ahora_en_chile', return_value=a_las_13):
            a_mediodia = self.client.get(reverse('pedir'))
        with mock.patch('core.views.ahora_en_chile', return_value=de_noche):
            de_madrugada = self.client.get(reverse('pedir'))

        self.assertEqual(set(a_mediodia.context['turnos_ahora']), {self.manana.pk, almuerzo.pk})
        self.assertEqual(de_madrugada.context['turnos_ahora'], [])


class DisponibilidadDelProductoTests(TestCase):
    """El modelo expone la disponibilidad de un producto: todo el día o su turno."""

    def setUp(self):
        categoria = Categoria.objects.create(nombre='Panadería')
        self.producto = Producto.objects.create(
            categoria=categoria, nombre='Pan', precio=Decimal('1000.00'), stock=5, activo=True,
        )

    def test_sin_turnos_es_todo_el_dia(self):
        self.assertEqual(self.producto.disponibilidad_formulario, '')

    def test_con_un_turno_entrega_sus_horas_y_dias(self):
        turno = Turno.objects.create(
            nombre='Fin de semana', hora_inicio=time(10, 0), hora_fin=time(13, 0),
            lunes=False, martes=False, miercoles=False, jueves=False, viernes=False,
        )
        self.producto.turnos.set([turno])

        datos = json.loads(self.producto.disponibilidad_formulario)

        self.assertEqual(datos, {
            'varios': False, 'nombre': 'Fin de semana', 'desde': '10:00', 'hasta': '13:00', 'dias': [5, 6],
        })

    def test_con_varios_turnos_los_marca_para_conservarlos(self):
        a = Turno.objects.create(nombre='A', hora_inicio=time(8, 0), hora_fin=time(9, 0))
        b = Turno.objects.create(nombre='B', hora_inicio=time(10, 0), hora_fin=time(11, 0))
        self.producto.turnos.set([a, b])

        datos = json.loads(self.producto.disponibilidad_formulario)

        self.assertTrue(datos['varios'])
        self.assertIn('A, 08:00 a 09:00', datos['lista'])

    def test_un_turno_sin_nombre_propio_se_muestra_como_su_horario(self):
        turno = Turno.objects.create(
            nombre='10:00 a 13:00 (sábado y domingo)', hora_inicio=time(10, 0), hora_fin=time(13, 0),
            lunes=False, martes=False, miercoles=False, jueves=False, viernes=False,
        )

        self.assertTrue(turno.nombre_es_horario)
        self.assertEqual(turno.descripcion, '10:00 a 13:00 (sábado y domingo)')
        self.assertEqual(str(turno), '10:00 a 13:00 (sábado y domingo)')


class PanelDisponibilidadTests(TestCase):
    """El admin define, en el formulario del producto, si se vende todo el día o en un horario propio."""

    def setUp(self):
        self.admin = Usuario.objects.create_user('admin-turnos', password='clave-larga-123', rol='ADMINISTRADOR')
        self.client.force_login(self.admin)
        self.categoria = Categoria.objects.create(nombre='Panadería')

    def _producto(self, nombre='Pan'):
        return Producto.objects.create(
            categoria=self.categoria, nombre=nombre, precio=Decimal('1000.00'), stock=5, activo=True,
        )

    def _editar(self, producto, **disponibilidad):
        datos = {'nombre': producto.nombre, 'categoria_id': self.categoria.pk, 'precio': '1000', 'stock': '5',
                 'activo': 'true'}
        datos.update(disponibilidad)
        return self.client.post(reverse('editar_producto', args=[producto.pk]), datos)

    def _mensajes(self, respuesta):
        return ' '.join(str(m) for m in get_messages(respuesta.wsgi_request))

    def test_el_formulario_ofrece_todo_el_dia_o_un_horario(self):
        self._producto()

        html = self.client.get(reverse('inicio_admin')).content.decode()

        self.assertEqual(html.count('type="radio" name="disponibilidad"'), 2 * 3)  # crear y editar: 3 opciones
        self.assertIn('value="todo_el_dia" checked', html)
        self.assertIn('name="turno_desde"', html)
        self.assertIn('name="turno_hasta"', html)
        self.assertEqual(html.count('type="checkbox" name="turno_dias"'), 2 * 7)  # 7 días, en crear y en editar
        self.assertNotIn('Crear un turno nuevo', html)   # ya no hay lista de turnos preestablecidos

    def test_crear_producto_con_horario_propio(self):
        self.client.post(reverse('crear_producto'), {
            'nombre': 'Pan de pascua', 'categoria_id': self.categoria.pk, 'precio': '2500', 'stock': '10',
            'disponibilidad': 'horario', 'turno_desde': '10:00', 'turno_hasta': '13:00', 'turno_dias': ['5', '6'],
        })

        turno = Producto.objects.get(nombre='Pan de pascua').turnos.get()
        self.assertEqual(turno.nombre, '10:00 a 13:00 (sábado y domingo)')
        self.assertEqual((turno.hora_inicio, turno.hora_fin), (time(10, 0), time(13, 0)))
        self.assertEqual(turno.dias_activos(), [5, 6])

    def test_el_admin_puede_ponerle_nombre_al_turno(self):
        producto = self._producto()

        self._editar(producto, disponibilidad='horario', turno_nombre='Desayuno', turno_desde='07:00',
                     turno_hasta='10:30', turno_dias=['0', '1', '2', '3', '4'])

        turno = producto.turnos.get()
        self.assertEqual(turno.nombre, 'Desayuno')
        self.assertEqual(turno.dias_texto, 'lunes a viernes')

    def test_todo_el_dia_quita_los_turnos(self):
        producto = self._producto()
        turno = Turno.objects.create(nombre='Tarde', hora_inicio=time(14, 0), hora_fin=time(19, 0))
        producto.turnos.set([turno])

        self._editar(producto, disponibilidad='todo_el_dia')

        self.assertEqual(producto.turnos.count(), 0)
        self.assertTrue(Turno.objects.filter(pk=turno.pk).exists())   # el turno no se borra

    def test_sin_el_campo_o_con_mantener_no_se_tocan_los_turnos(self):
        producto = self._producto()
        a = Turno.objects.create(nombre='A', hora_inicio=time(8, 0), hora_fin=time(9, 0))
        b = Turno.objects.create(nombre='B', hora_inicio=time(10, 0), hora_fin=time(11, 0))
        producto.turnos.set([a, b])

        self._editar(producto)                                   # un cliente HTTP que no envía el campo
        self._editar(producto, disponibilidad='mantener')        # producto con varios turnos

        self.assertEqual(set(producto.turnos.all()), {a, b})

    def test_dos_productos_con_el_mismo_horario_comparten_el_turno(self):
        uno, dos = self._producto('Uno'), self._producto('Dos')
        horario = dict(disponibilidad='horario', turno_desde='10:00', turno_hasta='13:00', turno_dias=['5', '6'])

        self._editar(uno, **horario)
        self._editar(dos, **horario)

        self.assertEqual(Turno.objects.count(), 1)
        self.assertEqual(uno.turnos.get(), dos.turnos.get())

    def test_cambiar_el_horario_de_un_producto_no_cambia_el_de_otro(self):
        uno, dos = self._producto('Uno'), self._producto('Dos')
        compartido = Turno.objects.create(nombre='Tarde', hora_inicio=time(14, 0), hora_fin=time(19, 0))
        uno.turnos.set([compartido])
        dos.turnos.set([compartido])

        self._editar(uno, disponibilidad='horario', turno_desde='15:00', turno_hasta='17:00',
                     turno_dias=['0', '1', '2', '3', '4', '5', '6'])

        compartido.refresh_from_db()
        self.assertEqual((compartido.hora_inicio, compartido.hora_fin), (time(14, 0), time(19, 0)))
        self.assertEqual(dos.turnos.get(), compartido)
        self.assertEqual(uno.turnos.get().hora_inicio, time(15, 0))

    def test_un_nombre_repetido_con_otro_horario_avisa_y_no_cambia(self):
        producto = self._producto()
        Turno.objects.create(nombre='Tarde', hora_inicio=time(14, 0), hora_fin=time(19, 0))

        respuesta = self._editar(producto, disponibilidad='horario', turno_nombre='tarde', turno_desde='10:00',
                                 turno_hasta='11:00', turno_dias=['0'])

        self.assertIn('Ya existe un turno llamado', self._mensajes(respuesta))
        self.assertEqual(producto.turnos.count(), 0)
        self.assertEqual(Turno.objects.count(), 1)

    def test_datos_invalidos_avisan_y_no_cambian_nada(self):
        producto = self._producto()
        actual = Turno.objects.create(nombre='Tarde', hora_inicio=time(14, 0), hora_fin=time(19, 0))
        producto.turnos.set([actual])

        sin_horas = self._editar(producto, disponibilidad='horario', turno_dias=['0'])
        misma_hora = self._editar(producto, disponibilidad='horario', turno_desde='10:00', turno_hasta='10:00',
                                  turno_dias=['0'])
        sin_dias = self._editar(producto, disponibilidad='horario', turno_desde='10:00', turno_hasta='11:00')
        hora_rara = self._editar(producto, disponibilidad='horario', turno_desde='25:99', turno_hasta='11:00',
                                 turno_dias=['0'])

        self.assertIn('indica la hora', self._mensajes(sin_horas))
        self.assertIn('no pueden ser iguales', self._mensajes(misma_hora))
        self.assertIn('al menos un día', self._mensajes(sin_dias))
        self.assertIn('indica la hora', self._mensajes(hora_rara))
        self.assertEqual(list(producto.turnos.all()), [actual])
        self.assertEqual(Turno.objects.count(), 1)

    def test_si_el_turno_igual_estaba_desactivado_se_reactiva(self):
        producto = self._producto()
        viejo = Turno.objects.create(nombre='Noche', hora_inicio=time(20, 0), hora_fin=time(23, 0), activo=False)

        self._editar(producto, disponibilidad='horario', turno_nombre='Noche', turno_desde='20:00',
                     turno_hasta='23:00', turno_dias=['0', '1', '2', '3', '4', '5', '6'])

        viejo.refresh_from_db()
        self.assertTrue(viejo.activo)
        self.assertEqual(producto.turnos.get(), viejo)

    def test_el_panel_entrega_la_disponibilidad_del_producto_al_editar(self):
        producto = self._producto()
        turno = Turno.objects.create(nombre='Desayuno', hora_inicio=time(7, 0), hora_fin=time(10, 0))
        producto.turnos.set([turno])

        html = self.client.get(reverse('inicio_admin')).content.decode()

        # El botón de editar lleva la disponibilidad como JSON escapado para JavaScript.
        self.assertIn(escapejs(producto.disponibilidad_formulario), html)
        self.assertIn('Desayuno', producto.disponibilidad_formulario)

    def test_un_visitante_no_puede_cambiar_la_disponibilidad(self):
        self.client.logout()
        producto = self._producto()

        self.client.post(reverse('editar_producto', args=[producto.pk]), {
            'nombre': 'Pan', 'categoria_id': self.categoria.pk, 'disponibilidad': 'horario',
            'turno_desde': '10:00', 'turno_hasta': '11:00', 'turno_dias': ['0'],
        })

        self.assertEqual(producto.turnos.count(), 0)
        self.assertEqual(Turno.objects.count(), 0)


class DisponibilidadFuncionesTests(TestCase):
    """core/disponibilidad.py: si un producto está disponible ahora y cuándo vuelve."""

    def setUp(self):
        self.entre_semana = Turno(nombre='Tardes', hora_inicio=time(14, 0), hora_fin=time(19, 30),
                                  sabado=False, domingo=False)
        self.fin_de_semana = Turno(nombre='Finde', hora_inicio=time(9, 0), hora_fin=time(13, 0),
                                   lunes=False, martes=False, miercoles=False, jueves=False, viernes=False)

    def _momento(self, dia, hora, minuto=0):
        return datetime(2026, 10, dia, hora, minuto, tzinfo=ZONA_HORARIA)   # 12 = lunes, 10 = sábado

    def test_sin_turnos_siempre_esta_disponible(self):
        self.assertTrue(esta_disponible([], self._momento(12, 3)))

    def test_disponible_solo_cuando_rige_algun_turno(self):
        turnos = [self.entre_semana, self.fin_de_semana]

        self.assertTrue(esta_disponible(turnos, self._momento(12, 15)))    # lunes por la tarde
        self.assertTrue(esta_disponible(turnos, self._momento(10, 11)))    # sábado por la mañana
        self.assertFalse(esta_disponible(turnos, self._momento(12, 10)))   # lunes por la mañana
        self.assertFalse(esta_disponible(turnos, self._momento(10, 15)))   # sábado por la tarde

    def test_proxima_disponibilidad(self):
        turnos = [self.entre_semana, self.fin_de_semana]

        manana_lunes = proxima_disponibilidad(turnos, self._momento(12, 10))
        sabado_tarde = proxima_disponibilidad(turnos, self._momento(10, 15))

        self.assertEqual(manana_lunes, self._momento(12, 14))               # hoy a las 14:00
        self.assertEqual(sabado_tarde, self._momento(11, 9))                # mañana (domingo) a las 09:00

    def test_textos_de_cuando_vuelve(self):
        lunes_10 = self._momento(12, 10)

        self.assertEqual(texto_proxima(self._momento(12, 14), lunes_10), 'hoy a las 14:00')
        self.assertEqual(texto_proxima(self._momento(13, 14), lunes_10), 'mañana a las 14:00')
        self.assertEqual(texto_proxima(self._momento(15, 9), lunes_10), 'el jueves a las 09:00')

    def test_resumen(self):
        turnos = [self.entre_semana]

        self.assertEqual(resumen_de_disponibilidad(turnos, self._momento(12, 15)), (True, ''))
        self.assertEqual(resumen_de_disponibilidad(turnos, self._momento(12, 10)), (False, 'hoy a las 14:00'))
        self.assertEqual(resumen_de_disponibilidad([], self._momento(12, 3)), (True, ''))


class ProductoDetalleTests(TestCase):
    """Modal (y página) con la información del producto y su disponibilidad."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre='Pastelería')
        self.producto = Producto.objects.create(
            categoria=self.categoria, nombre='Torta Selva Negra', descripcion='Bizcocho de chocolate con cerezas.',
            precio=Decimal('19990.00'), stock=4, stock_critico=5, activo=True,
        )
        self.turno = Turno.objects.create(
            nombre='Tortas de celebración', hora_inicio=time(10, 0), hora_fin=time(19, 30),
            lunes=False, martes=False, miercoles=False, domingo=False,
        )  # jueves a sábado
        self.producto.turnos.set([self.turno])

    def _detalle(self, pk=None, momento=None, parcial=True):
        direccion = reverse('producto_detalle', args=[pk or self.producto.pk])
        with mock.patch('core.views.ahora_en_chile', return_value=momento or SABADO_10H_TURNOS):
            return self.client.get(direccion, {'parcial': '1'} if parcial else {})

    def test_el_fragmento_trae_la_informacion_del_producto(self):
        respuesta = self._detalle()

        self.assertContains(respuesta, 'Torta Selva Negra')
        self.assertContains(respuesta, 'Bizcocho de chocolate con cerezas.')
        self.assertContains(respuesta, 'Pastelería')
        self.assertContains(respuesta, '$19.990')
        self.assertContains(respuesta, 'Quedan pocas')
        self.assertNotContains(respuesta, '<html')

    def test_muestra_los_horarios_y_los_dias(self):
        respuesta = self._detalle()

        self.assertContains(respuesta, 'Disponibilidad')
        self.assertContains(respuesta, 'Tortas de celebración')
        self.assertContains(respuesta, '10:00 a 19:30 · jueves a sábado')

    def test_dentro_del_turno_dice_disponible_ahora(self):
        respuesta = self._detalle(momento=SABADO_10H_TURNOS)   # sábado 10:00

        self.assertContains(respuesta, 'Disponible ahora')
        self.assertNotContains(respuesta, 'No disponible ahora')

    def test_fuera_del_turno_dice_cuando_vuelve(self):
        respuesta = self._detalle(momento=LUNES_16H_TURNOS)    # lunes 16:00

        self.assertContains(respuesta, 'No disponible ahora · vuelve el jueves a las 10:00')

    def test_un_producto_sin_turnos_se_vende_todos_los_dias(self):
        self.producto.turnos.clear()

        respuesta = self._detalle()

        self.assertContains(respuesta, 'Se vende todos los días, en el horario de la tienda.')
        self.assertNotContains(respuesta, 'Disponible ahora')

    def test_ignora_turnos_desactivados(self):
        self.turno.activo = False
        self.turno.save()

        respuesta = self._detalle()

        self.assertContains(respuesta, 'Se vende todos los días')

    def test_la_pagina_completa_funciona_sin_javascript(self):
        respuesta = self._detalle(parcial=False)

        self.assertContains(respuesta, '<html')
        self.assertContains(respuesta, 'Volver al catálogo')
        self.assertContains(respuesta, 'Torta Selva Negra')

    def test_un_producto_inactivo_o_inexistente_da_404(self):
        Producto.objects.filter(pk=self.producto.pk).update(activo=False)

        self.assertEqual(self._detalle().status_code, 404)
        self.assertEqual(self._detalle(pk=9999).status_code, 404)

    def test_se_puede_agregar_al_carrito_desde_el_detalle(self):
        sin_agregar = self._detalle()
        self.assertContains(sin_agregar, reverse('carrito_agregar'))

        self.client.post(reverse('carrito_agregar'), {'producto_id': self.producto.pk})
        agregado = self._detalle()

        self.assertContains(agregado, 'control-cantidad__numero">1<')

    def test_un_producto_agotado_lo_indica(self):
        Producto.objects.filter(pk=self.producto.pk).update(stock=0)

        respuesta = self._detalle()

        self.assertContains(respuesta, 'Agotado')

    def test_las_tarjetas_enlazan_al_detalle_y_traen_el_modal(self):
        for direccion in (reverse('pedir'), reverse('inicio')):
            with self.subTest(direccion=direccion):
                html = self.client.get(direccion).content.decode()

                self.assertIn(f'<a class="tarjeta__abrir" href="{reverse("producto_detalle", args=[self.producto.pk])}">', html)
                self.assertIn('id="producto-modal"', html)
                self.assertIn('producto_modal.js', html)

    def test_la_tarjeta_ya_no_repite_la_disponibilidad(self):
        html = self.client.get(reverse('pedir')).content.decode()

        self.assertNotIn('Se vende:', html)
        self.assertNotIn('aria-label="Turnos de venta"', html)


LUNES_10H_AGENDA = datetime(2026, 10, 12, 10, 0, tzinfo=ZONA_HORARIA)    # lunes 10:00
JUEVES_10H_AGENDA = datetime(2026, 10, 15, 10, 0, tzinfo=ZONA_HORARIA)   # jueves 10:00


def _turno_sin_guardar(nombre, desde, hasta, dias=range(7)):
    campos = {c: (i in dias) for i, c in enumerate(Turno.CAMPOS_DIAS)}
    return Turno(nombre=nombre, hora_inicio=desde, hora_fin=hasta, **campos)


class FranjasPorTurnosTests(TestCase):
    """La agenda solo ofrece horas en que se venden TODOS los productos del carrito."""

    def setUp(self):
        self.almuerzo = _turno_sin_guardar('Almuerzo', time(12, 0), time(15, 0), dias=range(0, 6))
        self.jue_a_sab = _turno_sin_guardar('Tortas', time(10, 0), time(19, 30), dias=(3, 4, 5))
        self.lunes = LUNES_10H_AGENDA.date()
        self.jueves = JUEVES_10H_AGENDA.date()

    def test_sin_productos_restringidos_todo_el_horario_de_la_tienda(self):
        horas = franjas_del_dia(self.lunes, LUNES_10H_AGENDA)

        self.assertEqual(horas[0], '11:00')     # 10:00 + 60 min de preparación
        self.assertEqual(horas[-1], '19:00')

    def test_un_producto_de_almuerzo_solo_ofrece_esas_horas(self):
        horas = franjas_del_dia(self.lunes, LUNES_10H_AGENDA, [[self.almuerzo]])

        self.assertEqual(horas[0], '12:00')
        self.assertEqual(horas[-1], '14:30')    # la franja 14:30 a 15:00 cabe justo en el turno
        self.assertNotIn('17:00', horas)

    def test_la_franja_debe_caber_entera_en_el_turno(self):
        corto = _turno_sin_guardar('Corto', time(12, 0), time(12, 45))

        horas = franjas_del_dia(self.jueves, JUEVES_10H_AGENDA, [[corto]])

        self.assertEqual(horas, ['12:00'])      # 12:30 a 13:00 se pasa de las 12:45

    def test_un_producto_de_otro_dia_no_ofrece_horas_ese_dia(self):
        self.assertEqual(franjas_del_dia(self.lunes, LUNES_10H_AGENDA, [[self.jue_a_sab]]), [])
        self.assertTrue(franjas_del_dia(self.jueves, JUEVES_10H_AGENDA, [[self.jue_a_sab]]))

    def test_con_varios_productos_se_intersectan_los_turnos(self):
        horas = franjas_del_dia(self.jueves, JUEVES_10H_AGENDA, [[self.almuerzo], [self.jue_a_sab]])

        self.assertEqual(horas[0], '12:00')
        self.assertEqual(horas[-1], '14:30')

    def test_un_producto_con_dos_turnos_acepta_cualquiera(self):
        manana = _turno_sin_guardar('Mañana', time(9, 0), time(11, 0))
        tarde = _turno_sin_guardar('Tarde', time(16, 0), time(18, 0))

        viernes = self.jueves + timedelta(days=1)   # un día futuro: así no cuenta la anticipación de hoy
        horas = franjas_del_dia(viernes, JUEVES_10H_AGENDA, [[manana, tarde]])

        self.assertEqual(horas, ['09:00', '09:30', '10:00', '10:30', '16:00', '16:30', '17:00', '17:30'])

    def test_los_dias_ofrecidos_solo_son_los_del_turno(self):
        dias = dias_de_retiro(LUNES_10H_AGENDA, [[self.jue_a_sab]])

        self.assertEqual([d['fecha'] for d in dias], ['2026-10-15', '2026-10-16', '2026-10-17'])

    def test_sin_turnos_se_miran_4_dias_y_con_turnos_una_semana(self):
        sin = dias_de_retiro(LUNES_10H_AGENDA)
        con = dias_de_retiro(LUNES_10H_AGENDA, [[_turno_sin_guardar('Todo', time(9, 0), time(19, 30))]])

        self.assertEqual(len(sin), 5)    # hoy y 4 días
        self.assertEqual(len(con), 8)    # hoy y 7 días

    def test_validar_rechaza_horas_fuera_del_turno_con_un_mensaje_claro(self):
        fecha, hora, error = validar_retiro('2026-10-12', '17:00', LUNES_10H_AGENDA, [[self.almuerzo]])
        valida, _, sin_error = validar_retiro('2026-10-12', '12:30', LUNES_10H_AGENDA, [[self.almuerzo]])

        self.assertIsNone(fecha)
        self.assertIn('no está disponible para todos los productos', error)
        self.assertIsNone(sin_error)
        self.assertEqual(valida, LUNES_10H_AGENDA.date())

    def test_validar_sigue_rechazando_horas_pasadas_o_inexistentes(self):
        _, _, ayer = validar_retiro('2026-10-11', '12:00', LUNES_10H_AGENDA)
        _, _, rara = validar_retiro('2026-10-12', '25:00', LUNES_10H_AGENDA)

        self.assertIn('ya no está disponible', ayer)
        self.assertIn('válidos', rara)


class CompraConTurnosTests(TestCase):
    """El carrito y la compra respetan los turnos de los productos, en retiro y en despacho."""

    DENTRO_DE_LA_ZONA = {'latitud': '-33.54589', 'longitud': '-70.59603'}

    def setUp(self):
        categoria = Categoria.objects.create(nombre='Salados')
        self.almuerzo = Turno.objects.create(
            nombre='Almuerzo', hora_inicio=time(12, 0), hora_fin=time(15, 0), domingo=False,
        )
        self.quiche = Producto.objects.create(
            categoria=categoria, nombre='Quiche', precio=Decimal('3500.00'), stock=5, activo=True,
        )
        self.quiche.turnos.set([self.almuerzo])
        self.pan = Producto.objects.create(
            categoria=categoria, nombre='Pan amasado', precio=Decimal('1000.00'), stock=5, activo=True,
        )

    def _agregar(self, producto):
        self.client.post(reverse('carrito_agregar'), {'producto_id': producto.pk})

    def _carrito(self, momento=LUNES_10H_AGENDA):
        with mock.patch('core.retiro.ahora', return_value=momento):
            return self.client.get(reverse('carrito'))

    def _comprar(self, momento=LUNES_10H_AGENDA, **datos):
        with mock.patch('core.retiro.ahora', return_value=momento), \
                mock.patch('core.views.ahora_en_chile', return_value=momento):
            return self.client.post(reverse('finalizar_compra'), datos)

    def _mensajes(self, respuesta):
        return ' '.join(str(m) for m in get_messages(respuesta.wsgi_request))

    # --- el carrito ---------------------------------------------------------------------------
    def test_el_carrito_solo_ofrece_las_horas_del_turno(self):
        self._agregar(self.quiche)

        respuesta = self._carrito()

        horas = [h['valor'] for h in respuesta.context['retiro_dias'][0]['horas']]
        self.assertEqual(horas[0], '12:00')
        self.assertEqual(horas[-1], '14:30')
        self.assertNotContains(respuesta, '17:00 a 17:30')

    def test_el_carrito_explica_la_restriccion(self):
        self._agregar(self.quiche)
        self._agregar(self.pan)

        respuesta = self._carrito()

        self.assertContains(respuesta, 'Algunos productos se venden solo en ciertos horarios')
        self.assertContains(respuesta, 'Quiche')
        self.assertContains(respuesta, 'Almuerzo, 12:00 a 15:00, lunes a sábado')
        self.assertEqual([r['nombre'] for r in respuesta.context['restricciones']], ['Quiche'])

    def test_sin_productos_restringidos_el_carrito_no_cambia(self):
        self._agregar(self.pan)

        respuesta = self._carrito()

        self.assertNotContains(respuesta, 'Algunos productos se venden solo')
        self.assertEqual(respuesta.context['retiro_dias'][0]['horas'][0]['valor'], '11:00')

    def test_si_ningun_horario_sirve_se_avisa_y_se_bloquea_la_compra(self):
        madrugada = Turno.objects.create(nombre='Madrugada', hora_inicio=time(2, 0), hora_fin=time(4, 0))
        self.pan.turnos.set([madrugada])    # fuera del horario de la tienda
        self._agregar(self.pan)

        respuesta = self._carrito()

        self.assertTrue(respuesta.context['sin_horas_por_productos'])
        self.assertContains(respuesta, 'en que se vendan todos los productos de tu carrito a la vez')
        self.assertRegex(respuesta.content.decode(), r'<button class="boton boton--primario" type="submit"[^>]*disabled')

    # --- retiro --------------------------------------------------------------------------------
    def test_retiro_dentro_del_turno_se_acepta(self):
        self._agregar(self.quiche)

        respuesta = self._comprar(tipo_entrega='RETIRO', fecha_retiro='2026-10-12', hora_retiro='12:30')

        pedido = Pedido.objects.get()
        self.assertRedirects(respuesta, reverse('boleta_simulada', args=[pedido.pk]), fetch_redirect_response=False)
        self.assertEqual(pedido.direccion_despacho, 'Retiro programado: lunes 12 de octubre, de 12:30 a 13:00')

    def test_retiro_a_las_17_de_un_producto_de_almuerzo_se_rechaza(self):
        self._agregar(self.quiche)

        respuesta = self._comprar(tipo_entrega='RETIRO', fecha_retiro='2026-10-12', hora_retiro='17:00')

        self.assertRedirects(respuesta, reverse('carrito'), fetch_redirect_response=False)
        self.assertFalse(Pedido.objects.exists())
        self.assertIn('no está disponible para todos los productos', self._mensajes(respuesta))
        self.assertEqual(Producto.objects.get(pk=self.quiche.pk).stock, 5)

    def test_un_producto_de_otro_dia_se_rechaza(self):
        torta = Producto.objects.create(
            categoria=self.quiche.categoria, nombre='Torta', precio=Decimal('19990.00'), stock=5, activo=True,
        )
        torta.turnos.set([Turno.objects.create(
            nombre='Jue a sáb', hora_inicio=time(10, 0), hora_fin=time(19, 30),
            lunes=False, martes=False, miercoles=False, domingo=False,
        )])
        self._agregar(torta)

        lunes = self._comprar(tipo_entrega='RETIRO', fecha_retiro='2026-10-12', hora_retiro='12:00')
        jueves = self._comprar(tipo_entrega='RETIRO', fecha_retiro='2026-10-15', hora_retiro='12:00')

        self.assertRedirects(lunes, reverse('carrito'), fetch_redirect_response=False)
        self.assertEqual(Pedido.objects.count(), 1)
        self.assertEqual(Pedido.objects.get().direccion_despacho, 'Retiro programado: jueves 15 de octubre, de 12:00 a 12:30')
        self.assertEqual(jueves.status_code, 302)

    # --- despacho ------------------------------------------------------------------------------
    def test_el_despacho_se_programa_y_respeta_el_turno(self):
        self._agregar(self.quiche)
        datos = dict(tipo_entrega='DESPACHO', direccion_despacho='Marigen 9795, La Florida', **self.DENTRO_DE_LA_ZONA)

        fuera = self._comprar(fecha_retiro='2026-10-12', hora_retiro='17:00', **datos)
        dentro = self._comprar(fecha_retiro='2026-10-12', hora_retiro='13:00', **datos)

        self.assertRedirects(fuera, reverse('carrito'), fetch_redirect_response=False)
        pedido = Pedido.objects.get()
        self.assertRedirects(dentro, reverse('boleta_simulada', args=[pedido.pk]), fetch_redirect_response=False)
        self.assertEqual(
            pedido.direccion_despacho,
            'Marigen 9795, La Florida · Entrega programada: lunes 12 de octubre, de 13:00 a 13:30',
        )

    def test_la_boleta_muestra_la_entrega_programada(self):
        self._agregar(self.pan)
        self._comprar(
            tipo_entrega='DESPACHO', direccion_despacho='Marigen 9795, La Florida',
            fecha_retiro='2026-10-12', hora_retiro='13:00', **self.DENTRO_DE_LA_ZONA,
        )

        pedido = Pedido.objects.get()
        boleta = self.client.get(reverse('boleta_simulada', args=[pedido.pk]))

        self.assertContains(boleta, 'Marigen 9795, La Florida')
        self.assertContains(boleta, 'Entrega programada: lunes 12 de octubre, de 13:00 a 13:30')

    def test_una_direccion_muy_larga_no_cabe_con_la_hora_de_entrega(self):
        self._agregar(self.pan)

        respuesta = self._comprar(
            tipo_entrega='DESPACHO', direccion_despacho='Calle ' + 'x' * 190 + ' 123', detalles_entrega='y' * 50,
            fecha_retiro='2026-10-12', hora_retiro='13:00', **self.DENTRO_DE_LA_ZONA,
        )

        self.assertFalse(Pedido.objects.exists())
        self.assertIn('demasiado largos', self._mensajes(respuesta))

    # --- sin agenda (otros clientes HTTP) ----------------------------------------------------------
    def test_sin_agenda_un_producto_fuera_de_turno_se_rechaza(self):
        self._agregar(self.quiche)
        a_las_17 = datetime(2026, 10, 12, 17, 0, tzinfo=ZONA_HORARIA)

        respuesta = self._comprar(momento=a_las_17, tipo_entrega='RETIRO')

        self.assertFalse(Pedido.objects.exists())
        self.assertIn('Ahora no se vende: Quiche', self._mensajes(respuesta))

    def test_sin_agenda_un_producto_en_turno_se_acepta(self):
        self._agregar(self.quiche)
        a_las_13 = datetime(2026, 10, 12, 13, 0, tzinfo=ZONA_HORARIA)

        self._comprar(momento=a_las_13, tipo_entrega='RETIRO')

        self.assertEqual(Pedido.objects.count(), 1)

    def test_un_producto_sin_turnos_se_compra_a_cualquier_hora(self):
        self._agregar(self.pan)
        a_las_3 = datetime(2026, 10, 12, 3, 0, tzinfo=ZONA_HORARIA)

        self._comprar(momento=a_las_3, tipo_entrega='RETIRO')

        self.assertEqual(Pedido.objects.count(), 1)
