"""
Integración con Transbank Webpay Plus (SDK Oficial de Python).
Gestiona la creación y confirmación de transacciones de pago.
"""
from django.conf import settings
from transbank.webpay.webpay_plus.transaction import Transaction

# Mapeo de códigos de tipo de pago de Transbank a descripciones legibles
TIPOS_PAGO_WEBPAY = {
    'VD': 'Débito (Redcompra)',
    'VN': 'Crédito (Venta Normal)',
    'VC': 'Crédito en Cuotas',
    'SI': '3 Cuotas sin Interés',
    'S2': '2 Cuotas sin Interés',
    'NC': 'N Cuotas sin Interés',
    'VP': 'Prepago',
}


def obtener_transaccion_webpay():
    """
    Retorna una instancia configurada de Transaction según el entorno
    (INTEGRATION o PRODUCTION). Soporta tanto la API moderna (v5/v6)
    como versiones anteriores del SDK.
    """
    ambiente = getattr(settings, 'WEBPAY_AMBIENTE', 'INTEGRATION')
    commerce_code = getattr(settings, 'WEBPAY_COMMERCE_CODE', '597055555532')
    api_key = getattr(
        settings,
        'WEBPAY_API_KEY',
        '579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C'
    )

    if hasattr(Transaction, 'build_for_integration'):
        if ambiente == 'INTEGRATION':
            return Transaction.build_for_integration(commerce_code, api_key)
        return Transaction.build_for_production(commerce_code, api_key)
    else:
        tx = Transaction()
        if hasattr(tx, 'configure_for_integration'):
            if ambiente == 'INTEGRATION':
                tx.configure_for_integration(commerce_code, api_key)
            else:
                tx.configure_for_production(commerce_code, api_key)
        return tx
