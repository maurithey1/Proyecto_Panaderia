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
        self.assertContains(boleta, 'Comprobante')
        self.assertContains(boleta, 'Compra completada con éxito')
        self.assertContains(boleta, reverse('descargar_comprobante_pdf', args=[pedido.pk]))

        # Verifica la descarga del comprobante en formato PDF
        url_pdf = reverse('descargar_comprobante_pdf', args=[pedido.pk])
        resp_pdf = self.client.get(url_pdf)
        self.assertEqual(resp_pdf.status_code, 200)
        self.assertEqual(resp_pdf['Content-Type'], 'application/pdf')
        self.assertTrue(resp_pdf.content.startswith(b'%PDF-'))

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

        resp_pdf = self.client.get(
            reverse('descargar_comprobante_pdf', args=[pedido.pk])
        )
        self.assertEqual(resp_pdf.status_code, 404)



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


class HistorialVentasPosTests(TestCase):
    """El historial del POS es la libreta del cajero: solo las ventas presenciales cobradas que él registró hoy."""

    AHORA = datetime(2026, 8, 19, 11, 34, tzinfo=ZONA_HORARIA)   # miércoles; en agosto Chile está en UTC-4

    def setUp(self):
        # Reloj fijo: "hoy" no depende de la hora en que se corran las pruebas (y fecha, que es
        # auto_now_add, queda en la hora fijada).
        parche = mock.patch('django.utils.timezone.now')
        self.reloj = parche.start()
        self.addCleanup(parche.stop)
        self._fijar_hora(self.AHORA)

        categoria = Categoria.objects.create(nombre='Panes POS')
        self.amasado = Producto.objects.create(
            categoria=categoria, nombre='Pan amasado', precio=Decimal('500.00'), stock=500, activo=True,
        )
        self.marraqueta = Producto.objects.create(
            categoria=categoria, nombre='Marraqueta', precio=Decimal('1900.00'), stock=500,
            unidad_medida='kg', activo=True,
        )
        self.cajero = self._cajero('cajero-ana')
        self.otro_cajero = self._cajero('cajero-beto')
        self.client.force_login(self.cajero.user)

    def _fijar_hora(self, momento):
        self.reloj.return_value = momento

    def _cajero(self, nombre):
        from .models import Cajero

        usuario = Usuario.objects.create_user(nombre, password='clave-larga-123', rol='CAJERO')
        return Cajero.objects.create(user=usuario, num_caja_asignada=1)

    def _venta(self, cajero, momento=None, canal='POS', estado='PAGADO', estado_pago='PAGADO',
               metodo='Efectivo', lineas=None):
        """Una venta como la deja la Terminal POS (con su pago). momento: hora de la venta (por omisión, ahora)."""
        lineas = lineas or [(self.amasado, 2)]
        total = sum((producto.precio * cantidad for producto, cantidad in lineas), Decimal('0'))
        pedido = Pedido.objects.create(
            cliente=None, cajero=cajero, estado=estado, canal=canal, tipo_entrega='RETIRO',
            direccion_despacho='Venta presencial en Caja', total=total,
        )
        for producto, cantidad in lineas:
            DetallePedido.objects.create(
                pedido=pedido, producto=producto, cantidad=cantidad,
                precio_unitario=producto.precio, subtotal=producto.precio * cantidad,
            )
        Pago.objects.create(
            pedido=pedido, monto=total, metodo=metodo, estado=estado_pago,
            codigo_autorizacion=f'POS-{pedido.pk:08d}',
        )
        if momento is not None:
            Pedido.objects.filter(pk=pedido.pk).update(fecha=momento)
        return pedido

    def _hora(self, dia, hora, minuto=0):
        return datetime(2026, 8, dia, hora, minuto, tzinfo=ZONA_HORARIA)

    def _historial(self, **params):
        respuesta = self.client.get(reverse('historial_ventas_pos'), params)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def _ids(self, respuesta):
        return [venta.pk for venta in respuesta.context['page_obj']]

    def _detalle(self, pedido_id):
        return self.client.get(reverse('detalle_venta_pos', args=[pedido_id]))

    def _assert_no_encontrada(self, respuesta):
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(respuesta.json(), {'ok': False, 'error': 'Venta no encontrada.'})

    # --- La venta guarda quién la registró ---

    def test_la_venta_en_efectivo_del_pos_guarda_al_cajero_que_la_registro(self):
        from .models import Caja

        Caja.objects.create(cajero=self.cajero, numero=1, monto_inicial=Decimal('0'))   # sin caja abierta no se vende
        respuesta = self.client.post(
            reverse('finalizar_venta_pos'),
            data=json.dumps({
                'items': [{'id': self.amasado.pk, 'cantidad': 6}],
                'metodo_pago': 'EFECTIVO',
                'monto_efectivo': 5000,
            }),
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.json()['ok'])
        pedido = Pedido.objects.get(pk=respuesta.json()['pedido_id'])
        self.assertEqual(pedido.cajero, self.cajero)
        self.assertEqual(self._ids(self._historial()), [pedido.pk])
        self.assertTrue(self._detalle(pedido.pk).json()['ok'])

    def test_un_admin_sin_perfil_de_cajero_no_vende_en_el_pos(self):
        # Vender exige abrir una caja, y solo un cajero con caja asignada puede abrirla
        admin = Usuario.objects.create_user('admin-pos', password='clave-larga-123', rol='ADMINISTRADOR')
        self.client.force_login(admin)

        respuesta = self.client.post(
            reverse('finalizar_venta_pos'),
            data=json.dumps({
                'items': [{'id': self.amasado.pk, 'cantidad': 1}],
                'metodo_pago': 'EFECTIVO',
                'monto_efectivo': 500,
            }),
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 409)
        self.assertFalse(respuesta.json()['ok'])
        self.assertFalse(Pedido.objects.exists())

    # --- Acceso ---

    def test_anonimo_va_al_login_y_un_cliente_no_entra(self):
        venta = self._venta(self.cajero)
        urls = [reverse('historial_ventas_pos'), reverse('detalle_venta_pos', args=[venta.pk])]

        self.client.logout()
        for url in urls:
            self.assertRedirects(self.client.get(url), reverse('login'), fetch_redirect_response=False)

        cliente = Usuario.objects.create_user('cliente-pos', password='clave-larga-123', rol='CLIENTE')
        self.client.force_login(cliente)
        for url in urls:
            self.assertRedirects(self.client.get(url), reverse('inicio'), fetch_redirect_response=False)

    def test_solo_acepta_get(self):
        venta = self._venta(self.cajero)

        self.assertEqual(self.client.post(reverse('historial_ventas_pos')).status_code, 405)
        self.assertEqual(self.client.post(reverse('detalle_venta_pos', args=[venta.pk])).status_code, 405)

    def test_un_admin_sin_perfil_de_cajero_ve_la_lista_vacia(self):
        self._venta(self.cajero)
        admin = Usuario.objects.create_user('admin-historial', password='clave-larga-123', rol='ADMINISTRADOR')
        self.client.force_login(admin)

        respuesta = self._historial()

        self.assertEqual(self._ids(respuesta), [])
        self.assertEqual(respuesta.context['cantidad_ventas'], 0)
        self.assertEqual(respuesta.context['total_ventas'], Decimal('0'))

    # --- Qué ventas aparecen ---

    def test_muestra_solo_las_ventas_cobradas_que_el_cajero_registro_hoy(self):
        efectivo = self._venta(self.cajero, self._hora(19, 9, 0))
        tarjeta = self._venta(
            self.cajero, self._hora(19, 10, 0), estado_pago='APROBADO', metodo='Webpay Plus',
            lineas=[(self.marraqueta, 1)],
        )
        presencial_entregada = self._venta(
            self.cajero, self._hora(19, 10, 30), canal='PRESENCIAL', estado='ENTREGADO',
        )
        # No son de su libreta de hoy
        self._venta(self.otro_cajero, self._hora(19, 9, 30))
        self._venta(None, self._hora(19, 9, 45))
        self._venta(self.cajero, self._hora(19, 9, 50), canal='WEB')
        self._venta(self.cajero, self._hora(19, 11, 0), estado='PENDIENTE', estado_pago='PENDIENTE',
                    metodo='Webpay Plus')
        self._venta(self.cajero, self._hora(19, 11, 5), estado='CANCELADO', estado_pago='RECHAZADO',
                    metodo='Webpay Plus')
        self._venta(self.cajero, self.AHORA - timedelta(days=1))

        respuesta = self._historial()

        self.assertEqual(self._ids(respuesta), [presencial_entregada.pk, tarjeta.pk, efectivo.pk])
        self.assertEqual(respuesta.context['fecha'], self.AHORA.date())
        self.assertEqual(respuesta.context['cantidad_ventas'], 3)
        self.assertEqual(respuesta.context['total_ventas'], Decimal('3900.00'))   # 1000 + 1900 + 1000
        self.assertContains(respuesta, '19/08/2026')
        self.assertContains(respuesta, '$3.900')

    def test_resumen_del_dia_completo_y_paginacion_de_15(self):
        ventas = [self._venta(self.cajero, self._hora(19, 8, minuto)) for minuto in range(17)]
        self._venta(self.otro_cajero, self._hora(19, 8, 30))

        pagina_1 = self._historial()
        pagina_2 = self._historial(page=2)

        for respuesta in (pagina_1, pagina_2):
            self.assertEqual(respuesta.context['cantidad_ventas'], 17)
            self.assertEqual(respuesta.context['total_ventas'], Decimal('17000.00'))
            self.assertEqual(respuesta.context['page_obj'].paginator.num_pages, 2)
        recientes_primero = [venta.pk for venta in reversed(ventas)]
        self.assertEqual(self._ids(pagina_1), recientes_primero[:15])
        self.assertEqual(self._ids(pagina_2), recientes_primero[15:])
        # Una página que no existe muestra la última, como Paginator.get_page
        self.assertEqual(self._ids(self._historial(page=99)), recientes_primero[15:])

    def test_cada_venta_trae_numero_resumen_de_productos_y_medio_de_pago(self):
        mixta = self._venta(
            self.cajero, self._hora(19, 9, 0), lineas=[(self.amasado, 6), (self.marraqueta, 2)],
        )
        con_tarjeta = self._venta(self.cajero, self._hora(19, 9, 10), estado_pago='APROBADO', metodo='Webpay Plus')
        en_mayusculas = self._venta(self.cajero, self._hora(19, 9, 20), metodo='EFECTIVO')

        ventas = {venta.pk: venta for venta in self._historial().context['page_obj']}

        self.assertEqual(ventas[mixta.pk].numero, f'#{mixta.pk:06d}')
        self.assertEqual(ventas[mixta.pk].productos_resumen, 'Pan amasado (6 un), Marraqueta (2 kg)')
        self.assertEqual(ventas[mixta.pk].medio_pago, 'Efectivo')
        self.assertEqual(ventas[con_tarjeta.pk].productos_resumen, 'Pan amasado (2 un)')
        self.assertEqual(ventas[con_tarjeta.pk].medio_pago, 'Tarjeta')
        self.assertEqual(ventas[en_mayusculas.pk].medio_pago, 'Efectivo')

    # --- Detalle (JSON del modal) ---

    def test_detalle_de_una_venta_propia_de_hoy(self):
        venta = self._venta(self.cajero, self.AHORA, lineas=[(self.amasado, 6), (self.marraqueta, 2)])

        respuesta = self._detalle(venta.pk)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {
            'ok': True,
            'venta': {
                'id': venta.pk,
                'numero': f'#{venta.pk:06d}',
                'fecha': '19/08/2026',
                'hora': '11:34',
                'medio_pago': 'Efectivo',
                'estado': 'Pagado',
                'total': 6800,
                'total_clp': '$6.800',
                'items': [
                    {'producto': 'Pan amasado', 'cantidad': 6, 'unidad': 'un',
                     'precio_unitario_clp': '$500', 'subtotal_clp': '$3.000'},
                    {'producto': 'Marraqueta', 'cantidad': 2, 'unidad': 'kg',
                     'precio_unitario_clp': '$1.900', 'subtotal_clp': '$3.800'},
                ],
            },
        })

    def test_detalle_con_tarjeta_aprobada_por_webpay(self):
        venta = self._venta(self.cajero, estado_pago='APROBADO', metodo='Webpay Plus')

        datos = self._detalle(venta.pk).json()['venta']

        self.assertEqual(datos['medio_pago'], 'Tarjeta')
        self.assertEqual(datos['total'], 1000)

    def test_detalle_da_404_si_la_venta_no_es_suya_de_hoy(self):
        de_otro = self._venta(self.otro_cajero)
        web = self._venta(self.cajero, canal='WEB')
        de_ayer = self._venta(self.cajero, self.AHORA - timedelta(days=1))
        pendiente = self._venta(self.cajero, estado='PENDIENTE', estado_pago='PENDIENTE', metodo='Webpay Plus')

        for venta_id in (de_otro.pk, web.pk, de_ayer.pk, pendiente.pk, 999999):
            with self.subTest(venta_id=venta_id):
                self._assert_no_encontrada(self._detalle(venta_id))

        # El otro cajero sí ve la suya
        self.client.force_login(self.otro_cajero.user)
        self.assertTrue(self._detalle(de_otro.pk).json()['ok'])

    # --- El día se cuenta en hora de Chile ---

    def test_el_dia_va_de_medianoche_a_medianoche_en_hora_de_chile(self):
        # 23:30 del 19 en Chile son las 03:30 UTC del 20; 23:59 del 18 son las 03:59 UTC del 19
        a_las_2330 = self._venta(self.cajero, self._hora(19, 23, 30))
        a_las_0010_del_20 = self._venta(self.cajero, self._hora(20, 0, 10))
        a_las_0005 = self._venta(self.cajero, self._hora(19, 0, 5))
        a_las_2359_del_18 = self._venta(self.cajero, self._hora(18, 23, 59))

        self._fijar_hora(self._hora(19, 23, 45))
        respuesta = self._historial()
        self.assertEqual(self._ids(respuesta), [a_las_2330.pk, a_las_0005.pk])
        self.assertEqual(respuesta.context['cantidad_ventas'], 2)
        self.assertEqual(self._detalle(a_las_2330.pk).json()['venta']['hora'], '23:30')
        self._assert_no_encontrada(self._detalle(a_las_0010_del_20.pk))
        self._assert_no_encontrada(self._detalle(a_las_2359_del_18.pk))

        self._fijar_hora(self._hora(20, 0, 20))
        respuesta = self._historial()
        self.assertEqual(self._ids(respuesta), [a_las_0010_del_20.pk])
        self.assertEqual(respuesta.context['fecha'], self._hora(20, 0).date())
        detalle = self._detalle(a_las_0010_del_20.pk).json()['venta']
        self.assertEqual((detalle['fecha'], detalle['hora']), ('20/08/2026', '00:10'))
        self._assert_no_encontrada(self._detalle(a_las_2330.pk))


class AperturaCajaTests(TestCase):
    """Apertura de caja: el cajero declara el dinero físico de su caja y solo entonces puede vender."""

    AHORA = datetime(2026, 8, 19, 7, 55, tzinfo=ZONA_HORARIA)   # miércoles, comienzo del turno

    def setUp(self):
        # Reloj fijo: "hoy" y la hora de apertura no dependen de cuándo se corran las pruebas
        parche = mock.patch('django.utils.timezone.now')
        self.reloj = parche.start()
        self.addCleanup(parche.stop)
        self.reloj.return_value = self.AHORA

        categoria = Categoria.objects.create(nombre='Panes caja')
        self.pan = Producto.objects.create(
            categoria=categoria, nombre='Hallulla', precio=Decimal('500.00'), stock=50, activo=True,
        )
        self.cajero = self._cajero('cajero-patricia', caja=1, nombre='Patricia', apellido='Guzmán')
        self.client.force_login(self.cajero.user)

    def _cajero(self, usuario, caja=1, nombre='', apellido=''):
        from .models import Cajero

        user = Usuario.objects.create_user(
            usuario, password='clave-larga-123', rol='CAJERO', first_name=nombre, last_name=apellido,
        )
        return Cajero.objects.create(user=user, num_caja_asignada=caja)

    def _abrir(self, monto, observacion=''):
        return self.client.post(reverse('apertura_caja'), {'monto': monto, 'observacion': observacion})

    def _vender(self):
        return self.client.post(
            reverse('finalizar_venta_pos'),
            data=json.dumps({
                'items': [{'id': self.pan.pk, 'cantidad': 2}],
                'metodo_pago': 'EFECTIVO',
                'monto_efectivo': 1000,
            }),
            content_type='application/json',
        )

    def _caja(self, cajero, numero=1, estado='ABIERTA', abierta_hace=None):
        """Una caja de `cajero`; abierta_hace: timedelta antes de AHORA (por omisión, ahora)."""
        from .models import Caja

        caja = Caja.objects.create(cajero=cajero, numero=numero, monto_inicial=Decimal('10000'), estado=estado)
        if abierta_hace is not None:
            Caja.objects.filter(pk=caja.pk).update(fecha_apertura=self.AHORA - abierta_hace)
        return caja

    def _turno_anterior(self, monto_contado, numero=1):
        """Una caja física ya cerrada, con su cierre (lo que hará el cierre de caja, HU-EP004-002)."""
        from .models import CierreCaja

        anterior = self._cajero(f'cajero-anterior-{numero}', caja=numero)
        caja = self._caja(anterior, numero=numero, estado='CERRADA', abierta_hace=timedelta(days=1))
        CierreCaja.objects.create(
            caja=caja, monto_inicial=Decimal('10000'), monto_contado=Decimal(monto_contado),
            diferencia=Decimal('0'), estado_cuadratura='Cuadrada',
        )

    def _cajas_propias(self):
        from .models import Caja

        return Caja.objects.filter(cajero=self.cajero)

    # --- Sin caja abierta no se vende ---

    def test_sin_caja_abierta_el_pos_manda_a_la_apertura(self):
        respuesta = self.client.get(reverse('inicio_cajero'))

        self.assertRedirects(respuesta, reverse('apertura_caja'), fetch_redirect_response=False)
        mensajes = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertIn('Antes de vender, declara el monto inicial de tu caja.', mensajes)

    def test_sin_caja_abierta_la_venta_se_rechaza_y_no_descuenta_stock(self):
        respuesta = self._vender()

        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.json()['error'], 'Antes de vender, declara el monto inicial de tu caja.')
        self.assertFalse(Pedido.objects.exists())
        self.pan.refresh_from_db()
        self.assertEqual(self.pan.stock, 50)

    # --- Apertura ---

    def test_primera_apertura_sin_turno_anterior_y_luego_puede_vender(self):
        pantalla = self.client.get(reverse('apertura_caja'))
        self.assertContains(pantalla, 'Caja cerrada')
        self.assertContains(pantalla, 'Sin turno anterior (primera apertura)')
        self.assertContains(pantalla, '19/08/2026')
        self.assertContains(pantalla, '07:55')

        respuesta = self._abrir('20.000')

        self.assertRedirects(respuesta, reverse('inicio_cajero'), fetch_redirect_response=False)
        caja = self._cajas_propias().get()
        self.assertEqual(
            (caja.numero, caja.monto_inicial, caja.estado, caja.observacion_apertura),
            (1, Decimal('20000'), 'ABIERTA', ''),
        )
        self.assertEqual(self.client.get(reverse('inicio_cajero')).status_code, 200)
        venta = self._vender()
        self.assertTrue(venta.json()['ok'])
        self.assertEqual(Pedido.objects.get().cajero, self.cajero)

    def test_con_la_caja_abierta_la_apertura_muestra_el_turno_en_curso(self):
        self._abrir('$20.000')

        pantalla = self.client.get(reverse('apertura_caja'))

        self.assertContains(pantalla, 'Caja abierta')
        self.assertContains(pantalla, '$20.000')
        self.assertContains(pantalla, 'Ir a vender')
        self.assertNotContains(pantalla, 'name="monto"')

    def test_el_monto_debe_ser_un_entero_de_pesos_dentro_del_tope(self):
        for monto in ['', 'abc', '-500', '17500.5', '17,5', '1.50', '600000']:
            with self.subTest(monto=monto):
                respuesta = self._abrir(monto)
                self.assertEqual(respuesta.status_code, 400)
                self.assertFalse(self._cajas_propias().exists())

    def test_no_se_abre_dos_veces_la_misma_caja(self):
        self._abrir('20000')

        respuesta = self._abrir('20000')

        self.assertContains(respuesta, 'Ya tienes la Caja 1 abierta.', status_code=400)
        self.assertEqual(self._cajas_propias().count(), 1)

    # --- Turno anterior de la caja física ---

    def test_si_no_cuadra_con_el_ultimo_cierre_exige_observacion(self):
        self._turno_anterior('17500')
        self.assertContains(self.client.get(reverse('apertura_caja')), '$17.500')

        sin_observacion = self._abrir('17.000')
        self.assertContains(sin_observacion, 'no coincide con el del turno anterior ($17.500)', status_code=400)
        self.assertFalse(self._cajas_propias().exists())

        con_observacion = self._abrir('17.000', '  Faltan $500: se usaron para cambio  ')
        self.assertRedirects(con_observacion, reverse('inicio_cajero'), fetch_redirect_response=False)
        caja = self._cajas_propias().get()
        self.assertEqual(
            (caja.monto_inicial, caja.observacion_apertura),
            (Decimal('17000'), 'Faltan $500: se usaron para cambio'),
        )

    def test_si_cuadra_con_el_ultimo_cierre_no_pide_observacion(self):
        self._turno_anterior('17500')

        respuesta = self._abrir('$17.500')

        self.assertRedirects(respuesta, reverse('inicio_cajero'), fetch_redirect_response=False)
        self.assertEqual(self._cajas_propias().get().monto_inicial, Decimal('17500'))

    def test_el_turno_anterior_es_de_la_misma_caja_fisica(self):
        self._turno_anterior('30000', numero=2)

        self.assertContains(self.client.get(reverse('apertura_caja')), 'Sin turno anterior (primera apertura)')
        self.assertRedirects(self._abrir('5000'), reverse('inicio_cajero'), fetch_redirect_response=False)

    # --- Cajas que quedaron abiertas ---

    def test_una_caja_propia_abierta_de_ayer_bloquea_la_apertura_y_la_venta(self):
        self._caja(self.cajero, abierta_hace=timedelta(days=1))

        pantalla = self.client.get(reverse('apertura_caja'))
        self.assertContains(pantalla, 'Tu Caja 1 sigue abierta desde el 18/08/2026')
        self.assertNotContains(pantalla, 'name="monto"')
        self.assertEqual(self._abrir('20000').status_code, 400)
        self.assertRedirects(
            self.client.get(reverse('inicio_cajero')), reverse('apertura_caja'), fetch_redirect_response=False,
        )
        self.assertEqual(self._vender().status_code, 409)
        self.assertEqual(self._cajas_propias().count(), 1)

    def test_la_caja_fisica_abierta_por_otro_cajero_bloquea_la_apertura(self):
        juan = self._cajero('cajero-juan', caja=1, nombre='Juan', apellido='Pérez')
        self._caja(juan, numero=1)

        self.assertContains(self.client.get(reverse('apertura_caja')), 'La Caja 1 ya está abierta por Juan Pérez.')
        self.assertEqual(self._abrir('20000').status_code, 400)
        self.assertFalse(self._cajas_propias().exists())

    def test_otra_caja_fisica_abierta_no_bloquea(self):
        self._caja(self._cajero('cajero-juan', caja=2), numero=2)

        self.assertRedirects(self._abrir('20000'), reverse('inicio_cajero'), fetch_redirect_response=False)

    # --- Acceso ---

    def test_un_admin_sin_perfil_de_cajero_no_abre_caja_ni_vende(self):
        admin = Usuario.objects.create_user('admin-caja', password='clave-larga-123', rol='ADMINISTRADOR')
        self.client.force_login(admin)

        for nombre in ('apertura_caja', 'inicio_cajero'):
            with self.subTest(vista=nombre):
                self.assertRedirects(
                    self.client.get(reverse(nombre)), reverse('inicio_admin'), fetch_redirect_response=False,
                )
        self.assertEqual(self._vender().status_code, 409)

    def test_anonimo_y_cliente_no_entran_a_la_apertura(self):
        self.client.logout()
        self.assertRedirects(self.client.get(reverse('apertura_caja')), reverse('login'), fetch_redirect_response=False)

        cliente = Usuario.objects.create_user('cliente-caja', password='clave-larga-123', rol='CLIENTE')
        self.client.force_login(cliente)
        self.assertRedirects(self.client.get(reverse('apertura_caja')), reverse('inicio'), fetch_redirect_response=False)


class CierreCajaTests(TestCase):
    """Cierre de caja: al terminar el turno, el cajero declara el dinero contado y realiza la cuadratura (HU-EP004-002)."""

    AHORA = datetime(2026, 8, 19, 18, 0, tzinfo=ZONA_HORARIA)   # fin de turno

    def setUp(self):
        parche = mock.patch('django.utils.timezone.now')
        self.reloj = parche.start()
        self.addCleanup(parche.stop)
        self.reloj.return_value = self.AHORA

        categoria = Categoria.objects.create(nombre='Panes caja cierre')
        self.pan = Producto.objects.create(
            categoria=categoria, nombre='Marraqueta', precio=Decimal('1000.00'), stock=100, activo=True,
        )
        self.cajero = self._cajero('cajero-cierre', caja=1, nombre='Carlos', apellido='Pérez')
        self.client.force_login(self.cajero.user)

    def _cajero(self, usuario, caja=1, nombre='', apellido=''):
        from .models import Cajero
        user = Usuario.objects.create_user(
            usuario, password='clave-larga-123', rol='CAJERO', first_name=nombre, last_name=apellido,
        )
        return Cajero.objects.create(user=user, num_caja_asignada=caja)

    def _abrir(self, monto='10000'):
        return self.client.post(reverse('apertura_caja'), {'monto': monto, 'observacion': ''})

    def _cerrar(self, monto, observacion=''):
        return self.client.post(reverse('cierre_caja'), {'monto': monto, 'observacion': observacion})

    def _vender(self, cantidad=1, metodo='EFECTIVO', monto_efectivo=1000):
        return self.client.post(
            reverse('finalizar_venta_pos'),
            data=json.dumps({
                'items': [{'id': self.pan.pk, 'cantidad': cantidad}],
                'metodo_pago': metodo,
                'monto_efectivo': monto_efectivo,
            }),
            content_type='application/json',
        )

    def test_sin_caja_abierta_pantalla_de_cierre_muestra_aviso(self):
        respuesta = self.client.get(reverse('cierre_caja'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Caja cerrada')
        self.assertContains(respuesta, 'no tienes ninguna caja abierta')

    def test_cierre_exitoso_cuadrado(self):
        self._abrir('10000')
        self._vender(cantidad=2, metodo='EFECTIVO', monto_efectivo=2000)   # $2.000 ventas
        # Monto esperado: $10.000 inicial + $2.000 ventas = $12.000
        respuesta = self._cerrar('12000')
        self.assertRedirects(respuesta, reverse('cierre_caja'), fetch_redirect_response=False)
        from .models import Caja, CierreCaja
        caja = Caja.objects.get(cajero=self.cajero)
        self.assertEqual(caja.estado, 'CERRADA')
        self.assertIsNotNone(caja.fecha_cierre)
        cierre = CierreCaja.objects.get(caja=caja)
        self.assertEqual(cierre.monto_contado, Decimal('12000'))
        self.assertEqual(cierre.diferencia, Decimal('0'))
        self.assertEqual(cierre.estado_cuadratura, 'Cuadrada')

    def test_cierre_con_diferencia_exige_observacion(self):
        self._abrir('10000')
        # Esperado: $10.000. Contado: $9.000 (faltante de $1.000) sin observación
        sin_obs = self._cerrar('9000', observacion='')
        self.assertEqual(sin_obs.status_code, 400)
        self.assertContains(sin_obs, 'La caja no cuadra', status_code=400)


        # Con observación se acepta el faltante
        con_obs = self._cerrar('9000', observacion='Falta billete de mil extraviado')
        self.assertRedirects(con_obs, reverse('cierre_caja'), fetch_redirect_response=False)
        from .models import CierreCaja
        cierre = CierreCaja.objects.get(caja__cajero=self.cajero)
        self.assertEqual(cierre.estado_cuadratura, 'Faltante')
        self.assertEqual(cierre.diferencia, Decimal('-1000'))
        self.assertEqual(cierre.observacion, 'Falta billete de mil extraviado')

    def test_cierre_con_sobrante_se_registra_correctamente(self):
        self._abrir('10000')
        # Esperado: $10.000. Contado: $15.000 (sobrante de $5.000)
        respuesta = self._cerrar('15000', observacion='Propina dejada por cliente')
        self.assertRedirects(respuesta, reverse('cierre_caja'), fetch_redirect_response=False)
        from .models import CierreCaja
        cierre = CierreCaja.objects.get(caja__cajero=self.cajero)
        self.assertEqual(cierre.estado_cuadratura, 'Sobrante')
        self.assertEqual(cierre.diferencia, Decimal('5000'))


class ComparadorCotizacionesTests(TestCase):
    """Como administrador, comparo cotizaciones de molineras (materia prima + flete) y elijo la más barata."""

    def setUp(self):
        from .models import Insumo, Proveedor, ProveedorInsumo
        self.Insumo, self.Proveedor, self.ProveedorInsumo = Insumo, Proveedor, ProveedorInsumo
        self.admin = Usuario.objects.create_user('admin-cotiz', password='clave-larga-123', rol='ADMINISTRADOR')
        self.client.force_login(self.admin)
        self.harina = Insumo.objects.create(codigo='NI001', nombre='Harina 000', kilos_por_saco=Decimal('25'))
        self.molino_a = self._molinera('11111111-1', 'Molino A', flete='20000')
        self.molino_b = self._molinera('22222222-2', 'Molino B', flete='5000')
        self.molino_c = self._molinera('33333333-3', 'Molino C', flete='0')

    def _molinera(self, rut, nombre, flete):
        return self.Proveedor.objects.create(
            rut=rut, nombre_proveedor=nombre, email=f'{nombre[-1].lower()}@mail.cl', telefono='+56911111111',
            costo_flete=Decimal(flete),
        )

    def _cotizar(self, proveedor, precio):
        return self.ProveedorInsumo.objects.create(
            proveedor=proveedor, insumo=self.harina, precio_ofrecido=Decimal(precio),
        )

    def test_el_costo_incluye_materia_prima_y_flete(self):
        from .cotizaciones import comparar_cotizaciones
        self._cotizar(self.molino_a, '28000')

        opcion = comparar_cotizaciones(self.harina, 10)[0]

        self.assertEqual(opcion['materia_prima'], Decimal('280000'))
        self.assertEqual(opcion['flete'], Decimal('20000'))
        self.assertEqual(opcion['total'], Decimal('300000'))
        self.assertEqual(opcion['costo_kg'], Decimal('1200'))  # 300.000 / 250 kg

    def test_gana_la_de_menor_costo_total_aunque_su_precio_por_saco_sea_mayor(self):
        from .cotizaciones import comparar_cotizaciones
        self._cotizar(self.molino_a, '27000')   # barato por saco, pero flete alto
        self._cotizar(self.molino_b, '27500')
        self._cotizar(self.molino_c, '29000')   # caro por saco, sin flete

        opciones = comparar_cotizaciones(self.harina, 5)

        # A: 135.000 + 20.000 = 155.000 | B: 137.500 + 5.000 = 142.500 | C: 145.000 + 0 = 145.000
        self.assertEqual([o['proveedor'] for o in opciones], [self.molino_b, self.molino_c, self.molino_a])
        self.assertTrue(opciones[0]['es_mejor'])
        self.assertFalse(opciones[1]['es_mejor'])
        self.assertEqual(opciones[1]['diferencia'], Decimal('2500'))
        self.assertEqual(opciones[2]['diferencia'], Decimal('12500'))

    def test_el_resultado_cambia_con_la_cantidad_de_sacos(self):
        from .cotizaciones import comparar_cotizaciones
        self._cotizar(self.molino_b, '30000')   # flete de $5.000
        self._cotizar(self.molino_c, '29000')   # precio menor por saco, pero flete de $60.000
        self.molino_c.costo_flete = Decimal('60000')
        self.molino_c.save()

        pocos = comparar_cotizaciones(self.harina, 1)[0]['proveedor']
        muchos = comparar_cotizaciones(self.harina, 100)[0]['proveedor']

        self.assertEqual(pocos, self.molino_b)    # 1 saco: B = 35.000 vs C = 89.000
        self.assertEqual(muchos, self.molino_c)   # 100 sacos: B = 3.005.000 vs C = 2.960.000

    def test_empate_de_costo_se_marca_sin_duplicar_el_mejor(self):
        from .cotizaciones import comparar_cotizaciones
        self._cotizar(self.molino_b, '25000')
        self._cotizar(self.molino_c, '30000')
        self.molino_c.costo_flete = Decimal('0')
        self.molino_c.save()
        self.molino_b.costo_flete = Decimal('5000')
        self.molino_b.save()
        # Con 1 saco: B = 30.000 y C = 30.000

        opciones = comparar_cotizaciones(self.harina, 1)

        self.assertEqual([o['es_mejor'] for o in opciones], [True, False])
        self.assertTrue(opciones[1]['empata_mejor'])

    def test_sacos_invalidos_se_corrigen(self):
        from .cotizaciones import limitar_sacos
        self.assertEqual(limitar_sacos('abc'), 1)
        self.assertEqual(limitar_sacos(0), 1)
        self.assertEqual(limitar_sacos(-4), 1)
        self.assertEqual(limitar_sacos(10 ** 12), 100000)
        self.assertEqual(limitar_sacos('12'), 12)

    def test_la_pagina_muestra_la_mejor_opcion(self):
        self._cotizar(self.molino_a, '27000')
        self._cotizar(self.molino_b, '27500')

        respuesta = self.client.get(reverse('comparar_cotizaciones'), {'insumo': self.harina.pk, 'sacos': 5})
        html = respuesta.content.decode()

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['mejor']['proveedor'], self.molino_b)
        self.assertIn('Menor costo: Molino B', html)
        self.assertIn('$142.500', html)

    def test_pagina_sin_seleccion_o_con_insumo_inexistente_no_falla(self):
        self.assertEqual(self.client.get(reverse('comparar_cotizaciones')).status_code, 200)
        self.assertEqual(self.client.get(reverse('comparar_cotizaciones'), {'insumo': '9999', 'sacos': 'x'}).status_code, 200)
        self.assertEqual(self.client.get(reverse('comparar_cotizaciones'), {'insumo': 'hola'}).status_code, 200)

    def test_solo_el_administrador_accede(self):
        self.client.logout()
        self.assertRedirects(self.client.get(reverse('comparar_cotizaciones')), reverse('login'))

        cajero = Usuario.objects.create_user('cajero-cotiz', password='clave-larga-123', rol='CAJERO')
        self.client.force_login(cajero)
        self.assertRedirects(self.client.get(reverse('comparar_cotizaciones')), reverse('inicio'))
        self.assertEqual(self.client.post(reverse('guardar_cotizacion'), {}).status_code, 302)
        self.assertEqual(self.ProveedorInsumo.objects.count(), 0)

    def test_guardar_cotizacion_la_crea_y_luego_la_actualiza(self):
        datos = {'insumo_id': self.harina.pk, 'proveedor_id': self.molino_a.pk, 'precio_saco': '$28.500', 'sacos': '4'}

        respuesta = self.client.post(reverse('guardar_cotizacion'), datos)

        self.assertRedirects(
            respuesta, f"{reverse('comparar_cotizaciones')}?insumo={self.harina.pk}&sacos=4",
            fetch_redirect_response=False,
        )
        self.assertEqual(self.ProveedorInsumo.objects.get().precio_ofrecido, Decimal('28500'))

        datos['precio_saco'] = '26000'
        self.client.post(reverse('guardar_cotizacion'), datos)

        self.assertEqual(self.ProveedorInsumo.objects.count(), 1)
        self.assertEqual(self.ProveedorInsumo.objects.get().precio_ofrecido, Decimal('26000'))

    def test_guardar_rechaza_precio_vacio_cero_o_exagerado(self):
        for precio in ('', '0', 'abc', '999999999999'):
            self.client.post(reverse('guardar_cotizacion'), {
                'insumo_id': self.harina.pk, 'proveedor_id': self.molino_a.pk, 'precio_saco': precio,
            })
        self.assertEqual(self.ProveedorInsumo.objects.count(), 0)

    def test_guardar_exige_materia_prima_y_molinera_validas(self):
        self.client.post(reverse('guardar_cotizacion'), {'insumo_id': '9999', 'proveedor_id': self.molino_a.pk, 'precio_saco': '1000'})
        self.client.post(reverse('guardar_cotizacion'), {'insumo_id': self.harina.pk, 'proveedor_id': '', 'precio_saco': '1000'})
        self.assertEqual(self.ProveedorInsumo.objects.count(), 0)

    def test_eliminar_cotizacion(self):
        cotizacion = self._cotizar(self.molino_a, '28000')

        respuesta = self.client.post(reverse('eliminar_cotizacion', args=[cotizacion.pk]), {'sacos': '3'})

        self.assertRedirects(
            respuesta, f"{reverse('comparar_cotizaciones')}?insumo={self.harina.pk}&sacos=3",
            fetch_redirect_response=False,
        )
        self.assertEqual(self.ProveedorInsumo.objects.count(), 0)
        # Solo por POST
        self.assertEqual(self.client.get(reverse('eliminar_cotizacion', args=[cotizacion.pk])).status_code, 405)

    def test_el_menu_del_admin_enlaza_al_comparador(self):
        html = self.client.get(reverse('inicio_admin')).content.decode()
        self.assertIn(f'href="{reverse("comparar_cotizaciones")}"', html)


def _registro_odepa(fecha, sector, promedio, minimo='1000', maximo='1700', region='Región Metropolitana de Santiago',
                    tipo='Supermercado', unidad='$/kilo'):
    return {
        'Fecha inicio': fecha, 'Region': region, 'Sector': sector, 'Tipo de punto monitoreo': tipo,
        'Unidad': unidad, 'Precio minimo': minimo, 'Precio maximo': maximo, 'Precio promedio': promedio,
    }


def _odepa_falso(registros_por_recurso):
    """Simula la API de ODEPA: `registros_por_recurso` mapea id de recurso -> lista de registros."""
    recursos = [
        {'id': 'r2026', 'name': 'Detalle de Precios Consumidor año 2026', 'datastore_active': True},
        {'id': 'r2025', 'name': 'Detalle de Precios Consumidor año 2025', 'datastore_active': True},
        {'id': 'rcsv', 'name': 'Diccionario de datos', 'datastore_active': False},
    ]

    def llamar(accion, **parametros):
        if accion == 'package_show':
            return {'resources': recursos}
        return {'records': registros_por_recurso.get(parametros['resource_id'], [])}
    return llamar


class MercadoOdepaTests(TestCase):
    """Estudio de mercado: precios de ODEPA para saber dónde está más barato cada materia prima."""

    def setUp(self):
        from .models import Insumo, Proveedor, ProveedorInsumo, PrecioMercado
        self.Insumo, self.PrecioMercado = Insumo, PrecioMercado
        self.admin = Usuario.objects.create_user('admin-mercado', password='clave-larga-123', rol='ADMINISTRADOR')
        self.client.force_login(self.admin)
        self.harina = Insumo.objects.create(codigo='NI001', nombre='Harina 000', kilos_por_saco=Decimal('25'))
        self.registros = [
            _registro_odepa('2026-10-19', 'Punilla', '1204,933333', region='Región de Ñuble'),
            _registro_odepa('2026-10-19', 'Oriente', '1312,741935'),
            _registro_odepa('2026-10-19', 'Valparaíso', '1340,000000', region='Región de Valparaíso'),
            _registro_odepa('2026-10-12', 'Punilla', '1190,5', region='Región de Ñuble'),
        ]
        self.odepa = _odepa_falso({'r2026': self.registros})

    def _vincular(self, producto='Harina sin polvos de hornear'):
        self.harina.producto_odepa = producto
        self.harina.save()

    def test_obtener_precios_lee_decimales_con_coma_y_las_ultimas_semanas(self):
        from . import mercado
        with mock.patch.object(mercado, '_llamar', self.odepa):
            todos = mercado.obtener_precios('Harina sin polvos de hornear')
            una_semana = mercado.obtener_precios('Harina sin polvos de hornear', semanas=1)

        self.assertEqual(len(todos), 4)
        self.assertEqual(len(una_semana), 3)
        punilla = next(p for p in una_semana if p['sector'] == 'Punilla')
        self.assertEqual(punilla['precio_promedio'], Decimal('1204.93'))
        self.assertEqual(punilla['unidad'], '$/kilo')

    def test_registros_con_precios_invalidos_se_omiten(self):
        from . import mercado
        malos = _odepa_falso({'r2026': [_registro_odepa('2026-10-19', 'Roto', 'sin dato'), self.registros[0]]})
        with mock.patch.object(mercado, '_llamar', malos):
            self.assertEqual(len(mercado.obtener_precios('Azúcar')), 1)

    def test_producto_fuera_de_la_lista_se_rechaza_sin_consultar(self):
        from . import mercado
        with mock.patch.object(mercado, '_llamar') as llamar:
            with self.assertRaises(mercado.ErrorMercado):
                mercado.obtener_precios('Uranio enriquecido')
        llamar.assert_not_called()

    def test_si_el_anio_actual_no_trae_datos_usa_el_anterior(self):
        from . import mercado
        odepa = _odepa_falso({'r2026': [], 'r2025': [self.registros[0]]})
        with mock.patch.object(mercado, '_llamar', odepa):
            precios = mercado.obtener_precios('Azúcar')
        self.assertEqual(len(precios), 1)

    def test_sin_datos_en_ningun_anio_informa_el_error(self):
        from . import mercado
        with mock.patch.object(mercado, '_llamar', _odepa_falso({})):
            with self.assertRaises(mercado.ErrorMercado):
                mercado.obtener_precios('Azúcar')

    def test_una_falla_de_red_se_convierte_en_error_controlado(self):
        from urllib import error
        from . import mercado
        with mock.patch.object(mercado.request, 'urlopen', side_effect=error.URLError('sin internet')):
            with self.assertRaises(mercado.ErrorMercado):
                mercado._llamar('package_show', id='x')

    def test_actualizar_precios_no_duplica_y_actualiza_los_existentes(self):
        from . import mercado
        self._vincular()
        with mock.patch.object(mercado, '_llamar', self.odepa):
            mercado.actualizar_precios(self.harina)
            self.assertEqual(self.PrecioMercado.objects.count(), 4)

            self.registros[0]['Precio promedio'] = '1100'
            mercado.actualizar_precios(self.harina)

        self.assertEqual(self.PrecioMercado.objects.count(), 4)
        actualizado = self.PrecioMercado.objects.get(sector='Punilla', fecha='2026-10-19')
        self.assertEqual(actualizado.precio_promedio, Decimal('1100.00'))

    def test_actualizar_sin_producto_asociado_falla(self):
        from . import mercado
        with self.assertRaises(mercado.ErrorMercado):
            mercado.actualizar_precios(self.harina)

    def test_estudio_ordena_por_precio_y_resume_la_ultima_semana(self):
        from . import mercado
        self._vincular()
        with mock.patch.object(mercado, '_llamar', self.odepa):
            mercado.actualizar_precios(self.harina)

        estudio = mercado.estudio_mercado(self.harina)

        self.assertEqual(str(estudio['fecha']), '2026-10-19')
        self.assertEqual([f.sector for f in estudio['mas_baratos']], ['Punilla', 'Oriente', 'Valparaíso'])
        self.assertEqual(estudio['cantidad_puntos'], 3)
        self.assertEqual(estudio['minimo'], Decimal('1204.93'))
        self.assertEqual(estudio['maximo'], Decimal('1340.00'))
        self.assertEqual(len(estudio['tendencia']), 2)   # dos semanas guardadas
        self.assertIsNone(estudio['comparacion'])        # sin cotización no se compara

    def test_estudio_compara_la_mejor_cotizacion_con_el_promedio(self):
        from . import mercado
        self._vincular()
        with mock.patch.object(mercado, '_llamar', self.odepa):
            mercado.actualizar_precios(self.harina)

        # 25 kg a $25.000 = $1.000 por kg, bajo el promedio de mercado (~$1.286)
        barato = mercado.estudio_mercado(self.harina, Decimal('25000'))['comparacion']
        self.assertTrue(barato['mas_barato_que_mercado'])
        self.assertEqual(barato['tu_precio_kg'], Decimal('1000'))
        self.assertLess(barato['porcentaje'], 0)

        caro = mercado.estudio_mercado(self.harina, Decimal('40000'))['comparacion']   # $1.600 por kg
        self.assertFalse(caro['mas_barato_que_mercado'])
        self.assertGreater(caro['porcentaje'], 0)

    def test_estudio_no_compara_si_el_producto_no_se_mide_por_kilo(self):
        from . import mercado
        self._vincular('Huevo blanco grande (primera)')
        huevos = _odepa_falso({'r2026': [_registro_odepa('2026-10-19', 'Oriente', '5000', unidad='$/bandeja 30 unidades')]})
        with mock.patch.object(mercado, '_llamar', huevos):
            mercado.actualizar_precios(self.harina)

        self.assertIsNone(mercado.estudio_mercado(self.harina, Decimal('25000'))['comparacion'])

    def test_estudio_sin_datos_o_sin_producto_devuelve_none(self):
        from . import mercado
        self.assertIsNone(mercado.estudio_mercado(self.harina))
        self._vincular()
        self.assertIsNone(mercado.estudio_mercado(self.harina))

    def test_vista_vincula_el_producto_y_descarga_los_precios(self):
        from . import mercado
        with mock.patch.object(mercado, '_llamar', self.odepa):
            respuesta = self.client.post(reverse('actualizar_precios_mercado'), {
                'insumo_id': self.harina.pk, 'producto_odepa': 'Harina sin polvos de hornear', 'sacos': '5',
            })

        self.assertRedirects(
            respuesta, f"{reverse('comparar_cotizaciones')}?insumo={self.harina.pk}&sacos=5",
            fetch_redirect_response=False,
        )
        self.harina.refresh_from_db()
        self.assertEqual(self.harina.producto_odepa, 'Harina sin polvos de hornear')
        self.assertEqual(self.PrecioMercado.objects.count(), 4)

    def test_vista_rechaza_un_producto_que_no_esta_en_la_lista(self):
        respuesta = self.client.post(reverse('actualizar_precios_mercado'), {
            'insumo_id': self.harina.pk, 'producto_odepa': 'Cualquier cosa',
        })
        self.assertEqual(respuesta.status_code, 302)
        self.harina.refresh_from_db()
        self.assertEqual(self.harina.producto_odepa, '')
        self.assertEqual(self.PrecioMercado.objects.count(), 0)

    def test_vista_informa_si_odepa_no_responde_sin_romper(self):
        from . import mercado
        with mock.patch.object(mercado, '_llamar', side_effect=mercado.ErrorMercado('sin conexión')):
            respuesta = self.client.post(reverse('actualizar_precios_mercado'), {
                'insumo_id': self.harina.pk, 'producto_odepa': 'Azúcar',
            })
        self.assertEqual(respuesta.status_code, 302)
        mensajes = ' '.join(str(m) for m in get_messages(respuesta.wsgi_request))
        self.assertIn('No se pudieron actualizar los precios de mercado', mensajes)

    def test_solo_el_administrador_puede_consultar_el_mercado(self):
        self.client.logout()
        respuesta = self.client.post(reverse('actualizar_precios_mercado'), {
            'insumo_id': self.harina.pk, 'producto_odepa': 'Azúcar',
        })
        self.assertRedirects(respuesta, reverse('login'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('actualizar_precios_mercado')).status_code, 302)

    def test_la_pagina_muestra_el_estudio_y_la_comparacion(self):
        from . import mercado
        from .models import Proveedor, ProveedorInsumo
        self._vincular()
        with mock.patch.object(mercado, '_llamar', self.odepa):
            mercado.actualizar_precios(self.harina)
        molino = Proveedor.objects.create(rut='11111111-1', nombre_proveedor='Molino A', email='a@mail.cl',
                                          telefono='+56911111111', costo_flete=Decimal('0'))
        ProveedorInsumo.objects.create(proveedor=molino, insumo=self.harina, precio_ofrecido=Decimal('25000'))

        html = self.client.get(reverse('comparar_cotizaciones'), {'insumo': self.harina.pk}).content.decode()

        self.assertIn('Estudio de mercado (ODEPA)', html)
        self.assertIn('Punilla', html)
        self.assertIn('bajo el promedio de mercado', html)
        self.assertIn('id="tablaMercado"', html)

    def test_la_pagina_ofrece_consultar_el_mercado_si_aun_no_hay_datos(self):
        html = self.client.get(reverse('comparar_cotizaciones'), {'insumo': self.harina.pk}).content.decode()
        self.assertIn('Consultar precios de mercado', html)
        self.assertNotIn('id="tablaMercado"', html)

    def test_el_comando_actualiza_solo_los_insumos_vinculados(self):
        from io import StringIO
        from django.core.management import call_command
        from . import mercado
        self._vincular()
        self.Insumo.objects.create(codigo='NI002', nombre='Sal')   # sin producto asociado
        salida = StringIO()

        with mock.patch.object(mercado, '_llamar', self.odepa):
            call_command('actualizar_precios_mercado', stdout=salida)

        self.assertEqual(self.PrecioMercado.objects.filter(insumo=self.harina).count(), 4)
        self.assertEqual(self.PrecioMercado.objects.count(), 4)
        self.assertIn('Harina 000', salida.getvalue())

    def test_tabla_comparativa_insumos_detecta_mejor_proveedor_y_ahorro(self):
        from .cotizaciones import tabla_comparativa_insumos
        from .models import Proveedor, ProveedorInsumo
        self.harina.precio_saco = Decimal('30000')
        self.harina.save()

        m1 = Proveedor.objects.create(rut='44444444-4', nombre_proveedor='Molinera Económica', email='e@mail.cl', telefono='+569111')
        m2 = Proveedor.objects.create(rut='55555555-5', nombre_proveedor='Molinera Cara', email='c@mail.cl', telefono='+569222')
        ProveedorInsumo.objects.create(proveedor=m1, insumo=self.harina, precio_ofrecido=Decimal('22000'))
        ProveedorInsumo.objects.create(proveedor=m2, insumo=self.harina, precio_ofrecido=Decimal('28000'))

        resumen = tabla_comparativa_insumos()
        item = next(r for r in resumen if r['insumo'].pk == self.harina.pk)

        self.assertEqual(item['mejor_proveedor'], m1)
        self.assertEqual(item['mejor_precio'], Decimal('22000'))
        self.assertEqual(item['ahorro'], Decimal('8000'))  # 30.000 - 22.000
        self.assertAlmostEqual(float(item['porcentaje_ahorro']), 26.66, places=1)
        self.assertEqual(item['cantidad_cotizaciones'], 2)

    def test_vista_renderiza_tabla_comparativa_de_insumos(self):
        respuesta = self.client.get(reverse('comparar_cotizaciones'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('tablaResumenInsumos', respuesta.content.decode('utf-8'))
        self.assertIn('Comparador de Insumos', respuesta.content.decode('utf-8'))
