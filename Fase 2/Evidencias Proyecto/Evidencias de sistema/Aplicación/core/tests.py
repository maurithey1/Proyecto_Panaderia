import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models import F
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escapejs
from django.utils import timezone

from . import pedidos
from .views import DisponibilidadInvalida
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

        self.assertIn('Indica la hora', self._mensajes(sin_horas))
        self.assertIn('no pueden ser iguales', self._mensajes(misma_hora))
        self.assertIn('al menos un día', self._mensajes(sin_dias))
        self.assertIn('Indica la hora', self._mensajes(hora_rara))
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

    def test_agotado_no_dice_disponible_ahora_aunque_este_en_su_horario(self):
        Producto.objects.filter(pk=self.producto.pk).update(stock=0)

        dentro = self._detalle(momento=SABADO_10H_TURNOS)    # sábado 10:00, dentro del turno
        fuera = self._detalle(momento=LUNES_16H_TURNOS)      # lunes 16:00, fuera del turno

        for respuesta in (dentro, fuera):
            self.assertContains(respuesta, 'Agotado')
            self.assertNotContains(respuesta, 'Disponible ahora')
            self.assertNotContains(respuesta, 'No disponible ahora')
            self.assertContains(respuesta, 'Cuando vuelva a haber stock, se vende en estos horarios')
            self.assertContains(respuesta, '10:00 a 19:30 · jueves a sábado')

    def test_agotado_sin_turnos_tampoco_afirma_que_se_vende(self):
        Producto.objects.filter(pk=self.producto.pk).update(stock=0)
        self.producto.turnos.clear()

        respuesta = self._detalle()

        self.assertContains(respuesta, 'Cuando vuelva a haber stock, se vende todos los días')
        self.assertNotContains(respuesta, 'Disponible ahora')

    def test_con_stock_sigue_diciendo_disponible_ahora(self):
        respuesta = self._detalle(momento=SABADO_10H_TURNOS)

        self.assertContains(respuesta, 'Disponible ahora')
        self.assertNotContains(respuesta, 'Cuando vuelva a haber stock')

    def test_la_pagina_tiene_un_h1_y_el_modal_no(self):
        pagina = self._detalle(parcial=False).content.decode()
        modal = self._detalle(parcial=True).content.decode()

        self.assertEqual(pagina.count('<h1'), 1)
        self.assertRegex(pagina, r'<h1 class="detalle__titulo"[^>]*>Torta Selva Negra</h1>')
        self.assertIn('<h2 id="detalle-disponibilidad-', pagina)   # los niveles bajan en uno
        self.assertEqual(modal.count('<h1'), 0)                   # en el modal el h1 es el de /pedir/
        self.assertRegex(modal, r'<h2 class="detalle__titulo"[^>]*>Torta Selva Negra</h2>')
        self.assertIn('<h3 id="detalle-disponibilidad-', modal)

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


TOKEN_REAL = 'a1' * 32    # los tokens reales de Transbank tienen 64 caracteres


class ConciliacionWebpayTests(TestCase):
    """Un pago Webpay y el stock del pedido deben quedar consistentes, llegue cuando llegue la respuesta."""

    def setUp(self):
        cache.clear()   # la limpieza recuerda las consultas fallidas por un minuto
        categoria = Categoria.objects.create(nombre='Panes')
        self.producto = Producto.objects.create(
            categoria=categoria, nombre='Hogaza', precio=Decimal('1000.00'), stock=10, activo=True,
        )

    # --- ayudas -------------------------------------------------------------------------------
    def _reservar(self, cantidad=3, token=TOKEN_REAL):
        """Lo que deja finalizar_compra al enviar al cliente a Webpay: pedido PENDIENTE y stock reservado."""
        Producto.objects.filter(pk=self.producto.pk).update(stock=F('stock') - cantidad)
        pedido = Pedido.objects.create(
            estado='PENDIENTE', canal='WEB', tipo_entrega='RETIRO', total=Decimal('1000.00') * cantidad,
        )
        DetallePedido.objects.create(
            pedido=pedido, producto=self.producto, cantidad=cantidad,
            precio_unitario=self.producto.precio, subtotal=Decimal('1000.00') * cantidad,
        )
        Pago.objects.create(
            pedido=pedido, monto=pedido.total, metodo='Webpay Plus', estado='PENDIENTE', codigo_autorizacion=token,
        )
        return pedido

    def _envejecer(self, pedido, minutos=25):
        Pedido.objects.filter(pk=pedido.pk).update(fecha=timezone.now() - timedelta(minutes=minutos))

    def _stock(self):
        return Producto.objects.get(pk=self.producto.pk).stock

    def _autorizada(self, pedido, monto=None):
        return {
            'buy_order': f'ORD-{pedido.pk}', 'response_code': 0, 'status': 'AUTHORIZED',
            'amount': monto if monto is not None else int(pedido.total),
            'payment_type_code': 'VD', 'authorization_code': '1415',
        }

    REEMBOLSO_ACEPTADO = {
        'type': 'NULLIFIED', 'authorization_code': '123456', 'authorization_date': '2026-10-13T12:00:00.000Z',
        'nullified_amount': 3000, 'balance': 0, 'response_code': 0,
    }

    def _transbank(self, status=None, commit=None, status_error=None, refund_error=None, refund=None):
        """Un Transbank simulado. Devuelve el mock para poder revisar qué se le pidió.

        Por defecto acepta los reembolsos, como el real; `refund` fija otra respuesta (p. ej. un rechazo)."""
        tx = mock.MagicMock()
        tx.status.return_value = status if status is not None else {'status': 'INITIALIZED'}
        if status_error:
            tx.status.side_effect = status_error
        if commit is not None:
            tx.commit.return_value = commit
        tx.refund.return_value = refund if refund is not None else dict(self.REEMBOLSO_ACEPTADO)
        if refund_error:
            tx.refund.side_effect = refund_error
        parche = mock.patch('core.views.obtener_transaccion_webpay', return_value=tx)
        parche.start()
        self.addCleanup(parche.stop)
        return tx

    def _expirar(self):
        """Lo que pasa cuando alguien entra al sitio después del plazo."""
        return self.client.get(reverse('carrito'))

    def _retorno(self, token=TOKEN_REAL):
        return self.client.get(reverse('webpay_confirmar'), {'token_ws': token})

    def _mensajes(self, respuesta):
        return ' '.join(str(m) for m in get_messages(respuesta.wsgi_request))

    # --- el caso reportado ------------------------------------------------------------------------
    def test_una_autorizacion_tardia_vuelve_a_reservar_el_stock(self):
        pedido = self._reservar(3)
        self.assertEqual(self._stock(), 7)
        tx = self._transbank(status={'status': 'INITIALIZED'})
        self._envejecer(pedido)
        self._expirar()
        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, self._stock()), ('CANCELADO', 10))   # expiró y devolvió el stock

        tx.commit.return_value = self._autorizada(pedido)
        respuesta = self._retorno()

        pedido.refresh_from_db()
        self.assertRedirects(respuesta, reverse('boleta_simulada', args=[pedido.pk]), fetch_redirect_response=False)
        self.assertEqual(pedido.estado, 'PAGADO')
        self.assertEqual(self._stock(), 7)                  # el stock vuelve a quedar reservado
        self.assertEqual(pedido.pago.estado, 'APROBADO')
        self.assertEqual(pedido.pago.codigo_autorizacion, '1415')

    def test_una_autorizacion_tardia_sin_stock_se_reembolsa(self):
        pedido = self._reservar(3)
        tx = self._transbank(status={'status': 'INITIALIZED'})
        self._envejecer(pedido)
        self._expirar()
        Producto.objects.filter(pk=self.producto.pk).update(stock=1)   # otra persona compró lo que quedaba
        tx.commit.return_value = self._autorizada(pedido)

        respuesta = self._retorno()

        pedido.refresh_from_db()
        self.assertRedirects(respuesta, reverse('carrito'), fetch_redirect_response=False)
        tx.refund.assert_called_once_with(TOKEN_REAL, 3000)
        self.assertEqual(pedido.estado, 'CANCELADO')
        self.assertEqual(self._stock(), 1)                  # no se descuenta lo que no hay
        self.assertEqual(pedido.pago.estado, 'REEMBOLSADO')
        self.assertIn('Te devolvimos el pago', self._mensajes(respuesta))

    def test_si_el_reembolso_falla_queda_pendiente_y_se_avisa(self):
        pedido = self._reservar(3)
        tx = self._transbank(status={'status': 'INITIALIZED'}, refund_error=Exception('sin conexión'))
        self._envejecer(pedido)
        self._expirar()
        Producto.objects.filter(pk=self.producto.pk).update(stock=0)
        tx.commit.return_value = self._autorizada(pedido)

        respuesta = self._retorno()

        pedido.refresh_from_db()
        self.assertEqual(pedido.pago.estado, 'REEMBOLSO_PENDIENTE')
        self.assertEqual(pedido.pago.codigo_autorizacion, TOKEN_REAL)   # para resolverlo a mano
        self.assertIn(f'N° {pedido.pk}', self._mensajes(respuesta))

    def _pago_sin_stock_con_reembolso(self, refund):
        """Un pago que llega tarde y ya no hay stock: hay que devolverlo. Devuelve (pedido, respuesta)."""
        pedido = self._reservar(3)
        tx = self._transbank(status={'status': 'INITIALIZED'}, refund=refund)
        self._envejecer(pedido)
        self._expirar()
        Producto.objects.filter(pk=self.producto.pk).update(stock=0)
        tx.commit.return_value = self._autorizada(pedido)
        respuesta = self._retorno()
        pedido.refresh_from_db()
        return pedido, respuesta

    def test_un_reembolso_rechazado_por_transbank_no_se_registra_como_exitoso(self):
        rechazo = {'type': 'NULLIFIED', 'response_code': -1}

        pedido, respuesta = self._pago_sin_stock_con_reembolso(rechazo)

        self.assertEqual(pedido.pago.estado, 'REEMBOLSO_PENDIENTE')
        self.assertEqual(pedido.pago.codigo_autorizacion, TOKEN_REAL)   # para resolverlo a mano
        mensajes = self._mensajes(respuesta)
        self.assertNotIn('Te devolvimos el pago', mensajes)
        self.assertIn(f'N° {pedido.pk}', mensajes)

    def test_una_reversa_se_toma_como_devolucion_exitosa(self):
        pedido, respuesta = self._pago_sin_stock_con_reembolso({'type': 'REVERSED'})

        self.assertEqual(pedido.pago.estado, 'REEMBOLSADO')
        self.assertIn('Te devolvimos el pago', self._mensajes(respuesta))

    def test_una_respuesta_que_no_confirma_la_devolucion_no_cuenta_como_exitosa(self):
        inesperadas = {
            'sin tipo': {'response_code': 0},
            'tipo desconocido': {'type': 'OTRA_COSA', 'response_code': 0},
            'anulacion sin codigo': {'type': 'NULLIFIED'},
            'reversa con codigo de rechazo': {'type': 'REVERSED', 'response_code': -1},
            'solo un numero (cuerpo vacio)': 204,
        }
        for nombre, respuesta_tbk in inesperadas.items():
            with self.subTest(nombre):
                Pedido.objects.all().delete()
                Producto.objects.filter(pk=self.producto.pk).update(stock=10)

                pedido, _ = self._pago_sin_stock_con_reembolso(respuesta_tbk)

                self.assertEqual(pedido.pago.estado, 'REEMBOLSO_PENDIENTE')

    def test_la_conciliacion_tampoco_da_por_devuelto_un_reembolso_rechazado(self):
        pedido = self._reservar(3)
        autorizada = {'status': 'AUTHORIZED', 'response_code': 0, 'amount': 1000, 'authorization_code': '1415'}
        tx = self._transbank(status=autorizada, refund={'type': 'NULLIFIED', 'response_code': -1})
        self._envejecer(pedido)

        self._expirar()

        pedido.refresh_from_db()
        tx.refund.assert_called_once_with(TOKEN_REAL, 1000)
        self.assertEqual(pedido.pago.estado, 'REEMBOLSO_PENDIENTE')

    # --- el retorno -------------------------------------------------------------------------------
    def test_un_pago_normal_deja_el_pedido_pagado_con_el_stock_reservado(self):
        pedido = self._reservar(3)
        self._transbank(commit=self._autorizada(pedido))

        respuesta = self._retorno()

        pedido.refresh_from_db()
        self.assertRedirects(respuesta, reverse('boleta_simulada', args=[pedido.pk]), fetch_redirect_response=False)
        self.assertEqual((pedido.estado, self._stock()), ('PAGADO', 7))

    def test_repetir_el_retorno_no_repite_sus_efectos(self):
        pedido = self._reservar(3)
        self._transbank(commit=self._autorizada(pedido))

        self._retorno()
        self._retorno()
        self._retorno()

        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, self._stock()), ('PAGADO', 7))

    def test_un_monto_distinto_al_del_pedido_no_se_acepta(self):
        pedido = self._reservar(3)
        tx = self._transbank(commit=self._autorizada(pedido, monto=1000))

        self._retorno()

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'CANCELADO')
        self.assertEqual(self._stock(), 10)                 # el stock reservado se libera
        tx.refund.assert_called_once_with(TOKEN_REAL, 1000)
        self.assertEqual(pedido.pago.estado, 'REEMBOLSADO')

    def test_un_rechazo_repetido_no_devuelve_el_stock_dos_veces(self):
        pedido = self._reservar(3)
        self._transbank(commit={'buy_order': f'ORD-{pedido.pk}', 'response_code': -1, 'status': 'FAILED'})

        self._retorno()
        self._retorno()

        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, self._stock()), ('CANCELADO', 10))
        self.assertEqual(pedido.pago.estado, 'RECHAZADO')

    # --- la limpieza consulta antes de cancelar ----------------------------------------------------
    def test_la_limpieza_consulta_el_estado_real_en_transbank(self):
        pedido = self._reservar(3)
        tx = self._transbank(status={'status': 'INITIALIZED'})
        self._envejecer(pedido)

        self._expirar()

        tx.status.assert_called_once_with(TOKEN_REAL)
        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, self._stock(), pedido.pago.estado), ('CANCELADO', 10, 'EXPIRADO'))

    def test_si_el_pago_se_autorizo_la_limpieza_lo_concilia_en_vez_de_cancelarlo(self):
        pedido = self._reservar(3)
        self._transbank(status=self._autorizada(pedido))   # pagó y cerró la ventana sin volver al sitio
        self._envejecer(pedido)

        self._expirar()

        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, self._stock()), ('PAGADO', 7))   # el stock no se devuelve
        self.assertEqual(pedido.pago.estado, 'APROBADO')

    def test_si_transbank_dice_que_fallo_se_cancela(self):
        pedido = self._reservar(3)
        self._transbank(status={'status': 'FAILED', 'response_code': -1})
        self._envejecer(pedido)

        self._expirar()

        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, self._stock()), ('CANCELADO', 10))

    def test_si_no_se_puede_consultar_el_pedido_no_se_cancela(self):
        pedido = self._reservar(3)
        tx = self._transbank(status_error=Exception('sin conexión'))
        self._envejecer(pedido)

        self._expirar()
        self._expirar()   # dentro del minuto: no se vuelve a insistir

        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, self._stock()), ('PENDIENTE', 7))
        self.assertEqual(tx.status.call_count, 1)

    def test_si_transbank_no_responde_en_un_dia_se_libera_igual(self):
        pedido = self._reservar(3)
        self._transbank(status_error=Exception('sin conexión'))
        self._envejecer(pedido, minutos=25 * 60)

        self._expirar()

        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, self._stock()), ('CANCELADO', 10))

    def test_un_pedido_reciente_no_se_consulta(self):
        pedido = self._reservar(3)
        tx = self._transbank()
        self._envejecer(pedido, minutos=5)

        self._expirar()

        tx.status.assert_not_called()
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'PENDIENTE')

    def test_sin_token_de_transbank_se_cancela_sin_consultar(self):
        pedido = self._reservar(3, token='')
        tx = self._transbank()
        self._envejecer(pedido)

        self._expirar()

        tx.status.assert_not_called()
        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, self._stock()), ('CANCELADO', 10))

    def test_una_visita_no_consulta_mas_de_tres_pedidos(self):
        pedidos_pendientes = [self._reservar(1, token=f'{i:02d}' * 32) for i in range(5)]
        tx = self._transbank(status={'status': 'INITIALIZED'})
        for pedido in pedidos_pendientes:
            self._envejecer(pedido)

        self._expirar()

        self.assertEqual(tx.status.call_count, 3)
        self.assertEqual(Pedido.objects.filter(estado='PENDIENTE').count(), 2)

    # --- otras transiciones -----------------------------------------------------------------------
    def test_no_se_puede_iniciar_el_pago_de_un_pedido_cancelado(self):
        pedido = self._reservar(3)
        tx = self._transbank()
        pedidos.cancelar_pendiente(pedido.pk, 'EXPIRADO')
        sesion = self.client.session   # el pedido es de esta sesión: se llega hasta la comprobación del estado
        sesion['webpay_pedido_id'] = pedido.pk
        sesion.save()

        respuesta = self.client.post(reverse('iniciar_pago_webpay', args=[pedido.pk]))

        self.assertRedirects(respuesta, reverse('carrito'), fetch_redirect_response=False)
        tx.create.assert_not_called()

    def test_si_falla_crear_el_pago_se_libera_el_stock_sin_mostrar_el_error_tecnico(self):
        tx = self._transbank()
        tx.create.side_effect = Exception('detalle interno secreto')
        self.client.post(reverse('carrito_agregar'), {'producto_id': self.producto.pk})

        respuesta = self.client.post(
            reverse('finalizar_compra'), {'tipo_entrega': 'RETIRO', 'metodo_pago': 'WEBPAY'},
        )

        pedido = Pedido.objects.get()
        self.assertEqual((pedido.estado, self._stock()), ('CANCELADO', 10))
        self.assertEqual(pedido.pago.estado, 'FALLIDO')
        mensajes = self._mensajes(respuesta)
        self.assertIn('No pudimos conectar con Transbank', mensajes)
        self.assertNotIn('secreto', mensajes)

    def test_cancelar_un_pedido_no_pendiente_no_hace_nada(self):
        pedido = self._reservar(3)
        pedidos.aprobar_pago(pedido.pk, 3000, 'Webpay Plus (Débito)', '1415')

        cancelado = pedidos.cancelar_pendiente(pedido.pk, 'EXPIRADO')

        pedido.refresh_from_db()
        self.assertFalse(cancelado)
        self.assertEqual((pedido.estado, self._stock()), ('PAGADO', 7))


class ProductoYDisponibilidadAtomicosTests(TestCase):
    """Un producto y su disponibilidad se guardan juntos o no se guarda nada."""

    def setUp(self):
        self.admin = Usuario.objects.create_user('admin-atomico', password='clave-larga-123', rol='ADMINISTRADOR')
        self.client.force_login(self.admin)
        self.categoria = Categoria.objects.create(nombre='Panadería')

    def _crear(self, **disponibilidad):
        datos = {'nombre': 'Quiche nueva', 'categoria_id': self.categoria.pk, 'precio': '3500', 'stock': '5'}
        datos.update(disponibilidad)
        return self.client.post(reverse('crear_producto'), datos)

    def _producto(self):
        return Producto.objects.create(
            categoria=self.categoria, nombre='Pan', precio=Decimal('1000.00'), stock=5, activo=True,
        )

    def _editar(self, producto, **extra):
        datos = {'nombre': 'Pan renombrado', 'categoria_id': self.categoria.pk, 'precio': '9999', 'stock': '77',
                 'activo': ''}
        datos.update(extra)
        return self.client.post(reverse('editar_producto', args=[producto.pk]), datos)

    def _mensajes(self, respuesta):
        return [str(m) for m in get_messages(respuesta.wsgi_request)]

    # --- crear ------------------------------------------------------------------------------------
    def test_un_horario_invalido_no_crea_el_producto(self):
        casos = {
            'misma hora': dict(turno_desde='10:00', turno_hasta='10:00', turno_dias=['0']),
            'sin horas': dict(turno_dias=['0']),
            'hora inexistente': dict(turno_desde='25:99', turno_hasta='11:00', turno_dias=['0']),
            'sin días': dict(turno_desde='10:00', turno_hasta='11:00'),
        }
        for nombre, datos in casos.items():
            with self.subTest(caso=nombre):
                self.client.logout()                       # sesión nueva: los avisos no se acumulan
                self.client.force_login(self.admin)
                respuesta = self._crear(disponibilidad='horario', **datos)

                mensajes = self._mensajes(respuesta)
                self.assertFalse(Producto.objects.exists())
                self.assertFalse(Turno.objects.exists())
                self.assertEqual(len(mensajes), 1)                      # solo el error, no un "agregado"
                self.assertIn('No se creó el producto', mensajes[0])

    def test_un_nombre_de_turno_repetido_con_otro_horario_no_crea_el_producto(self):
        Turno.objects.create(nombre='Tarde', hora_inicio=time(14, 0), hora_fin=time(19, 0))

        respuesta = self._crear(disponibilidad='horario', turno_nombre='tarde', turno_desde='10:00',
                                turno_hasta='11:00', turno_dias=['0'])

        self.assertFalse(Producto.objects.exists())
        self.assertEqual(Turno.objects.count(), 1)
        self.assertIn('Ya existe un turno llamado', self._mensajes(respuesta)[0])

    def test_un_horario_valido_crea_el_producto_con_su_turno(self):
        respuesta = self._crear(disponibilidad='horario', turno_desde='10:00', turno_hasta='13:00',
                                turno_dias=['5', '6'])

        producto = Producto.objects.get(nombre='Quiche nueva')
        self.assertEqual(producto.turnos.get().dias_texto, 'sábado y domingo')
        self.assertIn('agregado exitosamente', self._mensajes(respuesta)[0])

    def test_todo_el_dia_crea_el_producto_sin_turnos(self):
        respuesta = self._crear(disponibilidad='todo_el_dia')

        self.assertEqual(Producto.objects.get(nombre='Quiche nueva').turnos.count(), 0)
        self.assertEqual(len(self._mensajes(respuesta)), 1)

    def test_si_algo_falla_al_aplicar_la_disponibilidad_no_queda_el_producto(self):
        with mock.patch('core.views._aplicar_disponibilidad', side_effect=DisponibilidadInvalida('falló')):
            respuesta = self._crear(disponibilidad='horario', turno_desde='10:00', turno_hasta='13:00',
                                    turno_dias=['0'])

        self.assertFalse(Producto.objects.exists())         # la transacción deshizo la creación
        self.assertIn('No se creó el producto', self._mensajes(respuesta)[0])

    # --- editar -----------------------------------------------------------------------------------
    def test_un_horario_invalido_no_cambia_nada_del_producto(self):
        producto = self._producto()
        turno = Turno.objects.create(nombre='Tarde', hora_inicio=time(14, 0), hora_fin=time(19, 0))
        producto.turnos.set([turno])

        respuesta = self._editar(producto, disponibilidad='horario', turno_desde='10:00', turno_hasta='10:00',
                                 turno_dias=['0'])

        producto.refresh_from_db()
        self.assertEqual((producto.nombre, producto.precio, producto.stock, producto.activo),
                         ('Pan', Decimal('1000.00'), 5, True))   # ni el nombre, ni el precio, ni el estado
        self.assertEqual(list(producto.turnos.all()), [turno])
        mensajes = self._mensajes(respuesta)
        self.assertEqual(len(mensajes), 1)
        self.assertIn('No se guardó ningún cambio', mensajes[0])

    def test_si_algo_falla_al_aplicar_al_editar_se_deshace_todo(self):
        producto = self._producto()

        with mock.patch('core.views._aplicar_disponibilidad', side_effect=DisponibilidadInvalida('falló')):
            self._editar(producto, disponibilidad='horario', turno_desde='10:00', turno_hasta='13:00',
                         turno_dias=['0'])

        producto.refresh_from_db()
        self.assertEqual((producto.nombre, producto.precio, producto.stock), ('Pan', Decimal('1000.00'), 5))

    def test_editar_con_un_horario_valido_cambia_todo_junto(self):
        producto = self._producto()

        self._editar(producto, activo='true', disponibilidad='horario', turno_desde='10:00', turno_hasta='13:00',
                     turno_dias=['5', '6'])

        producto.refresh_from_db()
        self.assertEqual((producto.nombre, producto.precio, producto.stock), ('Pan renombrado', Decimal('9999'), 77))
        self.assertEqual(producto.turnos.get().horario_texto, '10:00 a 13:00')


class TurnosDesactivadosTests(TestCase):
    """Configurar un producto no debe cambiar la disponibilidad de otro por reactivar un turno compartido."""

    LUNES_16H = datetime(2026, 10, 12, 16, 0, tzinfo=ZONA_HORARIA)
    TODOS_LOS_DIAS = [str(i) for i in range(7)]

    def setUp(self):
        self.admin = Usuario.objects.create_user('admin-turnos-4', password='clave-larga-123', rol='ADMINISTRADOR')
        self.client.force_login(self.admin)
        self.categoria = Categoria.objects.create(nombre='Panadería')
        self.a = self._producto('A')
        self.b = self._producto('B')

    def _producto(self, nombre):
        return Producto.objects.create(
            categoria=self.categoria, nombre=nombre, precio=Decimal('1000.00'), stock=5, activo=True,
        )

    def _turno_desactivado(self, nombre='Viejo', **campos):
        datos = dict(nombre=nombre, hora_inicio=time(10, 0), hora_fin=time(13, 0), activo=False)
        datos.update(campos)
        return Turno.objects.create(**datos)

    def _configurar_a(self, **extra):
        datos = {'nombre': 'A', 'categoria_id': self.categoria.pk, 'precio': '1000', 'stock': '5',
                 'activo': 'true', 'disponibilidad': 'horario', 'turno_desde': '10:00', 'turno_hasta': '13:00',
                 'turno_dias': self.TODOS_LOS_DIAS}
        datos.update(extra)
        return self.client.post(reverse('editar_producto', args=[self.a.pk]), datos)

    def _b_disponible_el_lunes_16h(self):
        # Como el catálogo: solo cuentan los turnos activos.
        return esta_disponible(list(self.b.turnos.filter(activo=True)), self.LUNES_16H)

    def _mensajes(self, respuesta):
        return [str(m) for m in get_messages(respuesta.wsgi_request)]

    def test_configurar_a_no_cambia_la_disponibilidad_de_b(self):
        """El caso reportado: B estaba disponible y dejaba de estarlo sin haberlo editado."""
        viejo = self._turno_desactivado()
        self.b.turnos.set([viejo])
        self.assertTrue(self._b_disponible_el_lunes_16h())

        self._configurar_a()

        viejo.refresh_from_db()
        self.assertFalse(viejo.activo)                       # el turno de B sigue desactivado
        self.assertTrue(self._b_disponible_el_lunes_16h())   # y B sigue vendiéndose todo el día

    def test_a_recibe_un_turno_propio_cuando_el_igual_esta_desactivado_y_en_uso(self):
        viejo = self._turno_desactivado(nombre='10:00 a 13:00 (todos los días)')
        self.b.turnos.set([viejo])

        self._configurar_a()

        nuevo = self.a.turnos.get()
        self.assertNotEqual(nuevo.pk, viejo.pk)
        self.assertTrue(nuevo.activo)
        self.assertEqual(nuevo.nombre, '10:00 a 13:00 (todos los días) #2')   # no choca con el nombre existente
        self.assertEqual(list(self.b.turnos.all()), [viejo])

    def test_un_turno_desactivado_y_sin_uso_se_reutiliza(self):
        viejo = self._turno_desactivado()

        self._configurar_a(turno_nombre='Viejo')

        viejo.refresh_from_db()
        self.assertTrue(viejo.activo)
        self.assertEqual(self.a.turnos.get(), viejo)
        self.assertEqual(Turno.objects.count(), 1)           # no se duplicó

    def test_con_el_nombre_de_un_turno_desactivado_en_uso_avisa_y_no_cambia_nada(self):
        viejo = self._turno_desactivado()
        self.b.turnos.set([viejo])

        respuesta = self._configurar_a(turno_nombre='Viejo')

        viejo.refresh_from_db()
        self.assertFalse(viejo.activo)
        self.assertEqual(self.a.turnos.count(), 0)
        self.assertEqual(Turno.objects.count(), 1)
        mensaje = self._mensajes(respuesta)[0]
        self.assertIn('turno desactivado llamado "Viejo" que usan otros productos', mensaje)
        self.assertIn('No se guardó ningún cambio', mensaje)

    def test_un_turno_activo_igual_se_sigue_compartiendo(self):
        activo = Turno.objects.create(nombre='Mañanas', hora_inicio=time(10, 0), hora_fin=time(13, 0))
        self.b.turnos.set([activo])

        self._configurar_a()

        self.assertEqual(self.a.turnos.get(), activo)
        self.assertEqual(Turno.objects.count(), 1)

    def test_si_hay_uno_activo_y_otro_desactivado_se_elige_el_activo(self):
        self._turno_desactivado(nombre='Viejo')
        activo = Turno.objects.create(nombre='Vigente', hora_inicio=time(10, 0), hora_fin=time(13, 0))
        self.b.turnos.set([Turno.objects.get(nombre='Viejo')])

        self._configurar_a()

        self.assertEqual(self.a.turnos.get(), activo)
        self.assertFalse(Turno.objects.get(nombre='Viejo').activo)


class TurnosQueCruzanLaMedianocheTests(TestCase):
    """Un turno que cruza la medianoche pertenece al día en que EMPIEZA: su madrugada es del día anterior.

    Estas pruebas usan turnos de UN solo día; con los siete días activos el error no se nota.
    """

    LUNES, MARTES, DOMINGO = 12, 13, 11   # octubre de 2026

    def _momento(self, dia, hora, minuto=0):
        return datetime(2026, 10, dia, hora, minuto, tzinfo=ZONA_HORARIA)

    def _solo_lunes(self):
        return _turno_sin_guardar('Lunes noche', time(18, 0), time(12, 0), dias=(0,))     # 18:00 a 12:00

    def _solo_domingo(self):
        return _turno_sin_guardar('Domingo noche', time(22, 0), time(2, 0), dias=(6,))    # 22:00 a 02:00

    # --- el modelo --------------------------------------------------------------------------------
    def test_el_caso_reportado_turno_solo_lunes_de_18_a_12(self):
        turno = self._solo_lunes()

        self.assertFalse(turno.rige_en(self._momento(self.LUNES, 10)))    # lunes por la mañana: NO (es del domingo)
        self.assertTrue(turno.rige_en(self._momento(self.LUNES, 18)))     # empieza el lunes a las 18:00
        self.assertTrue(turno.rige_en(self._momento(self.LUNES, 23, 59)))
        self.assertTrue(turno.rige_en(self._momento(self.MARTES, 0, 0)))  # sigue de madrugada
        self.assertTrue(turno.rige_en(self._momento(self.MARTES, 10)))    # martes por la mañana: SÍ (viene del lunes)
        self.assertFalse(turno.rige_en(self._momento(self.MARTES, 12)))   # el término no cuenta
        self.assertFalse(turno.rige_en(self._momento(self.MARTES, 20)))   # martes por la noche: NO (no empieza ese día)

    def test_la_madrugada_del_lunes_pertenece_al_turno_del_domingo(self):
        turno = self._solo_domingo()

        self.assertTrue(turno.rige_en(self._momento(self.DOMINGO, 23)))
        self.assertFalse(turno.rige_en(self._momento(self.DOMINGO, 1)))   # domingo de madrugada: viene del sábado
        self.assertTrue(turno.rige_en(self._momento(self.LUNES, 1)))      # la semana da la vuelta: domingo -> lunes
        self.assertFalse(turno.rige_en(self._momento(self.LUNES, 3)))

    def test_un_turno_que_no_cruza_la_medianoche_no_cambia(self):
        turno = _turno_sin_guardar('Mañana', time(9, 0), time(14, 0), dias=(0,))

        self.assertTrue(turno.rige_en(self._momento(self.LUNES, 10)))
        self.assertFalse(turno.rige_en(self._momento(self.MARTES, 10)))
        self.assertFalse(turno.rige_en(self._momento(self.LUNES, 14)))
        self.assertFalse(turno.cruza_medianoche)
        self.assertTrue(self._solo_lunes().cruza_medianoche)

    def test_con_los_siete_dias_el_resultado_es_el_de_siempre(self):
        todos = _turno_sin_guardar('Noche', time(18, 0), time(12, 0))

        for dia, hora in ((self.LUNES, 10), (self.LUNES, 20), (self.MARTES, 3), (self.MARTES, 14)):
            with self.subTest(dia=dia, hora=hora):
                self.assertEqual(todos.rige_en(self._momento(dia, hora)), hora < 12 or hora >= 18)

    # --- la agenda --------------------------------------------------------------------------------
    def test_la_agenda_ofrece_la_madrugada_en_el_dia_siguiente(self):
        turno = self._solo_lunes()
        ahora_ = datetime(2026, 10, 5, 8, 0, tzinfo=ZONA_HORARIA)   # una semana antes: no cuenta la anticipación

        lunes = franjas_del_dia(datetime(2026, 10, 12).date(), ahora_, [[turno]])
        martes = franjas_del_dia(datetime(2026, 10, 13).date(), ahora_, [[turno]])

        self.assertEqual(lunes, ['18:00', '18:30', '19:00'])                  # la tarde, hasta que cierra la tienda
        self.assertEqual(martes[0], '09:00')                                   # la mañana del martes SÍ
        self.assertEqual(martes[-1], '11:30')                                  # y termina a las 12:00
        self.assertNotIn('18:00', martes)                                      # la tarde del martes NO

    def test_la_mañana_del_lunes_no_se_ofrece(self):
        turno = self._solo_lunes()
        ahora_ = datetime(2026, 10, 5, 8, 0, tzinfo=ZONA_HORARIA)

        lunes = franjas_del_dia(datetime(2026, 10, 12).date(), ahora_, [[turno]])

        self.assertNotIn('10:00', lunes)
        self.assertNotIn('09:00', lunes)

    def test_los_dias_ofrecidos_incluyen_el_dia_de_la_madrugada(self):
        turno = self._solo_lunes()
        ahora_ = datetime(2026, 10, 12, 8, 0, tzinfo=ZONA_HORARIA)   # lunes temprano

        dias = dias_de_retiro(ahora_, [[turno]])

        self.assertEqual([d['fecha'] for d in dias][:3], ['2026-10-12', '2026-10-13', '2026-10-19'])

    def test_validar_acepta_la_madrugada_del_dia_siguiente_y_rechaza_la_del_mismo_dia(self):
        turno = self._solo_lunes()
        ahora_ = datetime(2026, 10, 12, 8, 0, tzinfo=ZONA_HORARIA)   # lunes temprano: ambos días están en la ventana

        _, _, martes = validar_retiro('2026-10-13', '10:00', ahora_, [[turno]])
        _, _, lunes = validar_retiro('2026-10-12', '10:00', ahora_, [[turno]])

        self.assertIsNone(martes)
        self.assertIn('no está disponible para todos los productos', lunes)

    # --- la disponibilidad que ve el cliente ----------------------------------------------------------
    def test_el_producto_esta_disponible_el_martes_por_la_mañana_con_un_turno_de_lunes(self):
        turno = self._solo_lunes()

        self.assertTrue(esta_disponible([turno], self._momento(self.MARTES, 10)))
        self.assertFalse(esta_disponible([turno], self._momento(self.LUNES, 10)))
        # y la próxima apertura desde el martes por la tarde es el lunes siguiente a las 18:00
        proxima = proxima_disponibilidad([turno], self._momento(self.MARTES, 15))
        self.assertEqual(proxima, self._momento(19, 18))

    def test_el_modal_avisa_que_termina_al_dia_siguiente(self):
        categoria = Categoria.objects.create(nombre='Panadería')
        producto = Producto.objects.create(
            categoria=categoria, nombre='Pan de noche', precio=Decimal('1000.00'), stock=5, activo=True,
        )
        turno = Turno.objects.create(
            nombre='Noche', hora_inicio=time(18, 0), hora_fin=time(12, 0),
            martes=False, miercoles=False, jueves=False, viernes=False, sabado=False, domingo=False,
        )
        producto.turnos.set([turno])

        respuesta = self.client.get(reverse('producto_detalle', args=[producto.pk]), {'parcial': '1'})

        self.assertContains(respuesta, 'termina a las 12:00 del día siguiente')


class CarritoSeMantieneAlDiaTests(TestCase):
    """El carrito entrega al navegador lo que necesita para recalcularse tras cada cambio."""

    def setUp(self):
        categoria = Categoria.objects.create(nombre='Salados')
        self.quiche = Producto.objects.create(
            categoria=categoria, nombre='Quiche', precio=Decimal('3500.00'), stock=5, activo=True,
        )
        self.alfajor = Producto.objects.create(
            categoria=categoria, nombre='Alfajor', precio=Decimal('1100.00'), stock=5, activo=True,
        )
        # Sin ningún horario en común: la quiche es de lunes a sábado y el alfajor solo de domingo
        # después de que la tienda cierra, así que ninguna franja sirve para los dos.
        self.quiche.turnos.set([Turno.objects.create(
            nombre='Almuerzo', hora_inicio=time(12, 0), hora_fin=time(15, 0), domingo=False,
        )])
        self.alfajor.turnos.set([Turno.objects.create(
            nombre='Domingo tarde', hora_inicio=time(16, 0), hora_fin=time(18, 0),
            lunes=False, martes=False, miercoles=False, jueves=False, viernes=False, sabado=False,
        )])

    def _agregar(self, *productos):
        for producto in productos:
            self.client.post(reverse('carrito_agregar'), {'producto_id': producto.pk})

    def _boton(self, html):
        inicio = html.index('<button class="boton boton--primario" type="submit"')
        return html[inicio:html.index('</button>', inicio)]

    def test_con_productos_incompatibles_el_boton_va_bloqueado_y_marcado_por_el_servidor(self):
        self._agregar(self.quiche, self.alfajor)

        html = self.client.get(reverse('carrito')).content.decode()

        boton = self._boton(html)
        self.assertIn('disabled', boton)
        self.assertIn('data-bloqueo-servidor="1"', boton)   # lo lee zona_despacho.js cada vez
        self.assertIn('en que se vendan todos los productos de tu carrito a la vez', html)

    def test_al_quitar_el_incompatible_el_servidor_ya_no_bloquea(self):
        self._agregar(self.quiche, self.alfajor)
        self.client.post(reverse('carrito_quitar', args=[self.alfajor.pk]))

        html = self.client.get(reverse('carrito')).content.decode()

        boton = self._boton(html)
        self.assertNotIn('disabled', boton)
        self.assertNotIn('data-bloqueo-servidor', boton)
        self.assertNotIn('en que se vendan todos los productos de tu carrito a la vez', html)

    def test_la_pagina_carga_el_script_que_mantiene_el_carrito_al_dia(self):
        self._agregar(self.quiche)

        html = self.client.get(reverse('carrito')).content.decode()

        self.assertIn('carrito_estado.js', html)
        self.assertIn('id="agenda-panel"', html)              # lo que se reemplaza
        self.assertIn('compra__tabla-contenedor', html)

    def test_cada_cambio_avisa_al_navegador_con_un_evento(self):
        js = (settings.BASE_DIR / 'core/static/js/carrito_ajax.js').read_text(encoding='utf-8')

        self.assertIn("new CustomEvent('carrito:cambio'", js)


class AvisoDeBusquedaFallidaTests(TestCase):
    """Si una búsqueda en vivo falla, la página debe poder avisarlo y ofrecer reintentar."""

    def setUp(self):
        categoria = Categoria.objects.create(nombre='Panadería')
        Producto.objects.create(
            categoria=categoria, nombre='Marraqueta', precio=Decimal('1000.00'), stock=5, activo=True,
        )

    def _js(self):
        return (settings.BASE_DIR / 'core/static/js/busqueda_catalogo.js').read_text(encoding='utf-8')

    def test_la_pagina_trae_el_aviso_oculto_con_su_boton_de_reintentar(self):
        html = self.client.get(reverse('pedir')).content.decode()

        aviso = html[html.index('id="buscador-aviso"'):]
        aviso = aviso[:aviso.index('</div>')]
        self.assertIn('role="alert"', aviso)
        self.assertIn('hidden', aviso)                     # oculto mientras todo funciona
        self.assertIn('data-reintentar', aviso)
        self.assertIn('Reintentar', aviso)

    def test_el_aviso_no_viaja_en_la_respuesta_parcial(self):
        # La zona que se reemplaza al buscar no debe duplicar el aviso, que vive fuera de ella.
        respuesta = self.client.get(reverse('pedir'), {'q': 'marraq', 'parcial': '1'})

        self.assertNotContains(respuesta, 'buscador-aviso')

    def test_el_script_distingue_lo_mostrado_de_lo_intentado(self):
        js = self._js()

        self.assertIn('var mostrada', js)                  # la búsqueda a la que corresponden los resultados
        self.assertIn("setAttribute('data-desactualizado', 'true')", js)
        self.assertIn('buscar(true)', js)                  # reintentar repite aunque el texto sea el mismo
        self.assertIn("addEventListener('online'", js)     # y reintenta solo al volver la conexión

    def test_los_resultados_desactualizados_se_ven_apagados(self):
        css = (settings.BASE_DIR / 'core/static/css/estilo.css').read_text(encoding='utf-8')

        self.assertIn('#resultados[data-desactualizado="true"]', css)
        self.assertIn('.buscador__aviso', css)


class InicioDePagoWebpayTests(TestCase):
    """Nadie puede iniciar (ni, con el token que recibe, cancelar) el pago de un pedido que no es suyo."""

    TOKEN_ORIGINAL = 'b2' * 32
    TOKEN_NUEVO = 'c3' * 32

    def setUp(self):
        cache.clear()
        categoria = Categoria.objects.create(nombre='Panes')
        self.producto = Producto.objects.create(
            categoria=categoria, nombre='Hogaza', precio=Decimal('1000.00'), stock=10, activo=True,
        )
        self.tx = mock.MagicMock()
        self.tx.create.return_value = {
            'token': self.TOKEN_NUEVO, 'url': 'https://webpay3gint.transbank.cl/webpayserver/initTransaction',
        }
        parche = mock.patch('core.views.obtener_transaccion_webpay', return_value=self.tx)
        parche.start()
        self.addCleanup(parche.stop)

    def _pedido(self, cliente=None):
        Producto.objects.filter(pk=self.producto.pk).update(stock=F('stock') - 2)
        pedido = Pedido.objects.create(
            cliente=cliente, estado='PENDIENTE', canal='WEB', tipo_entrega='RETIRO', total=Decimal('2000.00'),
        )
        DetallePedido.objects.create(
            pedido=pedido, producto=self.producto, cantidad=2,
            precio_unitario=self.producto.precio, subtotal=Decimal('2000.00'),
        )
        Pago.objects.create(
            pedido=pedido, monto=pedido.total, metodo='Webpay Plus', estado='PENDIENTE',
            codigo_autorizacion=self.TOKEN_ORIGINAL,
        )
        return pedido

    def _cliente(self, nombre):
        from .models import Cliente

        usuario = Usuario.objects.create_user(nombre, password='clave-larga-123', rol='CLIENTE')
        return Cliente.objects.create(user=usuario, direccion='Calle 1', telefono='+56 9 1')

    def _sesion_paga(self, cliente_http, pedido):
        """Lo que deja finalizar_compra en la sesión de quien va a pagar."""
        sesion = cliente_http.session
        sesion['webpay_pedido_id'] = pedido.pk
        sesion.save()

    def _iniciar(self, pedido, cliente_http=None):
        return (cliente_http or self.client).post(reverse('iniciar_pago_webpay', args=[pedido.pk]))

    def _intacto(self, pedido):
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'PENDIENTE')
        self.assertEqual(pedido.pago.codigo_autorizacion, self.TOKEN_ORIGINAL)
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 8)
        self.tx.create.assert_not_called()

    def test_una_sesion_anonima_no_puede_iniciar_el_pago_de_un_pedido_ajeno(self):
        pedido = self._pedido()

        respuesta = self._iniciar(pedido)

        self.assertEqual(respuesta.status_code, 404)
        self._intacto(pedido)

    def test_otro_cliente_con_sesion_iniciada_tampoco(self):
        duenio = self._cliente('duenio')
        pedido = self._pedido(cliente=duenio)
        self._cliente('intruso')
        self.client.login(username='intruso', password='clave-larga-123')

        respuesta = self._iniciar(pedido)

        self.assertEqual(respuesta.status_code, 404)
        self._intacto(pedido)

    def test_una_sesion_que_paga_otro_pedido_no_sirve_para_este(self):
        propio = self._pedido()
        ajeno = self._pedido()
        self._sesion_paga(self.client, propio)

        respuesta = self._iniciar(ajeno)

        self.assertEqual(respuesta.status_code, 404)
        ajeno.refresh_from_db()
        self.assertEqual(ajeno.pago.codigo_autorizacion, self.TOKEN_ORIGINAL)
        self.tx.create.assert_not_called()

    def test_un_pedido_inexistente_da_404(self):
        respuesta = self.client.post(reverse('iniciar_pago_webpay', args=[9999]))

        self.assertEqual(respuesta.status_code, 404)

    def test_quien_hizo_la_compra_como_invitado_puede_reintentar_el_pago(self):
        pedido = self._pedido()
        self._sesion_paga(self.client, pedido)

        respuesta = self._iniciar(pedido)

        self.assertRedirects(
            respuesta,
            f'https://webpay3gint.transbank.cl/webpayserver/initTransaction?token_ws={self.TOKEN_NUEVO}',
            fetch_redirect_response=False,
        )
        pedido.refresh_from_db()
        self.assertEqual(pedido.pago.codigo_autorizacion, self.TOKEN_NUEVO)
        self.assertEqual(self.tx.create.call_count, 1)

    def test_el_cliente_duenio_con_sesion_iniciada_puede_iniciar_el_pago(self):
        duenio = self._cliente('duenio')
        pedido = self._pedido(cliente=duenio)
        self.client.login(username='duenio', password='clave-larga-123')

        respuesta = self._iniciar(pedido)

        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(self.TOKEN_NUEVO, respuesta['Location'])
        self.assertEqual(self.tx.create.call_count, 1)

    def test_solo_acepta_post(self):
        pedido = self._pedido()
        self._sesion_paga(self.client, pedido)

        respuesta = self.client.get(reverse('iniciar_pago_webpay', args=[pedido.pk]))

        self.assertEqual(respuesta.status_code, 405)
        self._intacto(pedido)

    def test_el_pedido_ajeno_no_se_puede_cancelar_con_un_token_propio(self):
        """El ataque completo: iniciar el pago del pedido de otro para obtener un token y cancelarlo con él."""
        pedido = self._pedido()

        self._iniciar(pedido)
        self.client.get(reverse('webpay_confirmar'), {'TBK_TOKEN': self.TOKEN_NUEVO})

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'PENDIENTE')
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 8)

class ArregloRegistroTests(TestCase):
    """El registro usa el campo que existe y valida el correo en el servidor."""

    def test_el_js_usa_el_campo_de_usuario(self):
        html = self.client.get(reverse('registro')).content.decode()
        js = (settings.BASE_DIR / 'core/static/js/datos_domicilio.js').read_text(encoding='utf-8')
        self.assertIn('id="id_username"', html)
        self.assertIn('id="js-alerta"', html)
        self.assertIn("getVal('id_username')", js)
        self.assertNotIn('id_rut', js)

    def test_rechaza_un_correo_con_formato_invalido(self):
        self.client.post(reverse('registro'), {
            'username': 'nuevo', 'first_name': 'Ana', 'last_name': 'Pérez', 'email': 'esto-no-es-un-correo',
            'telefono': '912345678', 'password': 'clave-larga-123', 'password_confirm': 'clave-larga-123',
            'region': 'Metropolitana', 'comuna': 'La Florida', 'direccion1': 'Calle 1 123',
        })
        self.assertFalse(Usuario.objects.filter(username='nuevo').exists())
