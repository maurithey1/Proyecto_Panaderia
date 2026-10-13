from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_alter_insumo_options_insumo_codigo_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Turno',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=50, unique=True)),
                ('hora_inicio', models.TimeField(verbose_name='Desde')),
                ('hora_fin', models.TimeField(verbose_name='Hasta')),
                ('lunes', models.BooleanField(default=True)),
                ('martes', models.BooleanField(default=True)),
                ('miercoles', models.BooleanField(default=True, verbose_name='Miércoles')),
                ('jueves', models.BooleanField(default=True)),
                ('viernes', models.BooleanField(default=True)),
                ('sabado', models.BooleanField(default=True, verbose_name='Sábado')),
                ('domingo', models.BooleanField(default=True)),
                ('activo', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Turno de venta',
                'verbose_name_plural': 'Turnos de venta',
                'ordering': ['hora_inicio', 'nombre'],
            },
        ),
        migrations.AddField(
            model_name='producto',
            name='turnos',
            field=models.ManyToManyField(
                blank=True,
                help_text='Sin turnos, el producto se vende todo el día.',
                related_name='productos',
                to='core.turno',
                verbose_name='Turnos de venta',
            ),
        ),
    ]
