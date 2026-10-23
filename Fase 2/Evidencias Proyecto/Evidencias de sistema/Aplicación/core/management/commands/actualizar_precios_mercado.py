from django.core.management.base import BaseCommand

from core import mercado
from core.models import Insumo


class Command(BaseCommand):
    help = 'Actualiza desde ODEPA los precios de mercado de los insumos con un producto asociado.'

    def handle(self, *args, **options):
        insumos = Insumo.objects.exclude(producto_odepa='')
        if not insumos:
            self.stdout.write('Ningún insumo tiene un producto de ODEPA asociado.')
            return

        for insumo in insumos:
            try:
                cantidad = mercado.actualizar_precios(insumo)
            except mercado.ErrorMercado as exc:
                self.stderr.write(self.style.ERROR(f'{insumo.nombre}: {exc}'))
                continue
            self.stdout.write(self.style.SUCCESS(
                f'{insumo.nombre}: {cantidad} registros de "{insumo.producto_odepa}" actualizados.'
            ))
