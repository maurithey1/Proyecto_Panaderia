import os
from django.core.management.base import BaseCommand
from core.models import Usuario, Administrador


class Command(BaseCommand):
    help = 'Crea o actualiza el usuario administrador por defecto.'

    def handle(self, *args, **options):
        # Lee las variables desde el entorno con un valor por defecto si no existen
        admin_user = os.getenv('ADMIN_USERNAME', 'admin')
        admin_pass = os.getenv('ADMIN_PASSWORD', 'ClaveSegura2026!')
        usuario, creado = Usuario.objects.get_or_create(username=admin_user)
        usuario.set_password(admin_pass)
        usuario.rol = 'ADMINISTRADOR'
        usuario.is_staff = True
        usuario.is_superuser = True
        usuario.is_active = True
        usuario.save()

        perfil, _ = Administrador.objects.get_or_create(user=usuario)
        perfil.nivel_acceso = 'TOTAL'
        perfil.save()

        accion = 'creado' if creado else 'actualizado'
        self.stdout.write(
            self.style.SUCCESS(
                f'Usuario administrador {accion} con éxito (Usuario: {admin_user} | Rol: ADMINISTRADOR).'
            )
        )
