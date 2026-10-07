import json
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import Categoria, Producto


class Command(BaseCommand):
    help = 'Carga categorías y productos desde un archivo JSON respetando la integridad referencial.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--archivo',
            type=str,
            default='productos_prueba.json',
            help='Nombre o ruta del archivo JSON a cargar (por defecto: productos_prueba.json)'
        )
        parser.add_argument(
            '--limpiar',
            action='store_true',
            help='Elimina los productos y categorías existentes antes de cargar para evitar duplicados o contradicciones.'
        )

    def handle(self, *args, **options):
        archivo = options['archivo']
        limpiar = options['limpiar']

        ruta_archivo = os.path.join(settings.BASE_DIR, archivo)
        if not os.path.exists(ruta_archivo):
            self.stderr.write(self.style.ERROR(f'El archivo no existe: {ruta_archivo}'))
            return

        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            try:
                datos = json.load(f)
            except json.JSONDecodeError as e:
                self.stderr.write(self.style.ERROR(f'Error al parsear JSON: {e}'))
                return

        if limpiar:
            self.stdout.write(self.style.WARNING('Limpiando productos y categorías anteriores...'))
            Producto.objects.all().delete()
            Categoria.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Limpieza completada con éxito.'))

        total_categorias = 0
        total_productos = 0

        for item in datos:
            nombre_cat = item.get('categoria')
            desc_cat = item.get('descripcion', '')
            productos = item.get('productos', [])

            # 1. Crear o recuperar la categoría primero (Integridad referencial)
            categoria_obj, cat_creada = Categoria.objects.get_or_create(
                nombre=nombre_cat,
                defaults={'descripcion': desc_cat}
            )
            if cat_creada:
                total_categorias += 1
                self.stdout.write(f'  [+] Categoría creada: {nombre_cat}')
            else:
                self.stdout.write(f'  [=] Categoría existente: {nombre_cat}')

            # 2. Crear o actualizar los productos vinculados a esa categoría
            for prod in productos:
                prod_obj, prod_creado = Producto.objects.update_or_create(
                    nombre=prod['nombre'],
                    defaults={
                        'categoria': categoria_obj,
                        'descripcion': prod.get('descripcion', ''),
                        'precio': prod.get('precio', 0),
                        'stock': prod.get('stock', 0),
                        'stock_critico': prod.get('stock_critico', 5),
                        'imagen_url': prod.get('imagen_url', ''),
                        'activo': prod.get('activo', True)
                    }
                )
                if prod_creado:
                    total_productos += 1
                    self.stdout.write(f'      -> Producto cargado: {prod_obj.nombre} (${prod_obj.precio})')
                else:
                    self.stdout.write(f'      -> Producto actualizado: {prod_obj.nombre}')

        self.stdout.write(
            self.style.SUCCESS(
                f'\nCarga finalizada con éxito: {total_categorias} categorías creadas, {total_productos} productos cargados.'
            )
        )
