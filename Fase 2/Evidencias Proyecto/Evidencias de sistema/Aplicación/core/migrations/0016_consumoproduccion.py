import django.db.models.deletion
from django.db import migrations, models
class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_envaseinsumo'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConsumoProduccion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre_insumo', models.CharField(max_length=100)),
                ('unidad', models.CharField(max_length=10)),
                ('cantidad_receta', models.DecimalField(decimal_places=3, max_digits=12, verbose_name='Pedía la receta')),
                ('cantidad_usada', models.DecimalField(decimal_places=3, max_digits=12, verbose_name='Se descontó')),
                ('faltante', models.DecimalField(decimal_places=3, default=0, max_digits=12, verbose_name='Faltó')),
                ('costo', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Costo de lo usado')),
                ('insumo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='consumos', to='core.insumo')),
                ('produccion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consumos', to='core.producciondiaria')),
            ],
            options={
                'verbose_name': 'Consumo de producción',
                'verbose_name_plural': 'Consumos de producción',
                'ordering': ['-produccion__fecha_produccion', 'pk'],
            },
        ),
    ]
