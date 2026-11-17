from django import forms
from django.contrib.auth.forms import PasswordResetForm
from .models import Usuario


class CustomPasswordResetForm(PasswordResetForm):
    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not Usuario.objects.filter(email__iexact=email, is_active=True).exists():
            raise forms.ValidationError(
                'No existe ninguna cuenta activa registrada con este correo electrónico.'
            )
        return email