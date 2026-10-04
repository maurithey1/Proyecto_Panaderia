from django.db import models
from django.contrib.auth.models import AbstractUser

# ==========================================
# 1. USUARIOS Y ROLES (AbstractUser + Perfiles)
# ==========================================
class Usuario(AbstractUser):
    ROLES = (
        ('ADMINISTRADOR', 'Administrador'),
        ('CAJERO', 'Cajero'),
        ('CLIENTE', 'Cliente'),
    )
    rol = models.CharField(max_length=20, choices=ROLES, default='CLIENTE')

    @property
    def es_administrador(self):
        return self.rol == 'ADMINISTRADOR' or self.is_superuser

    @property
    def es_cajero(self):
        return self.rol == 'CAJERO'

    @property
    def es_cliente(self):
        return self.rol == 'CLIENTE'

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"


class Cliente(models.Model):
    user = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='perfil_cliente')
    direccion = models.CharField(max_length=255)
    telefono = models.CharField(max_length=20)

    class Meta:
        verbose_name = "Perfil Cliente"
        verbose_name_plural = "Perfiles Clientes"

    def __str__(self):
        return f"Cliente: {self.user.get_full_name() or self.user.username}"


class PuntosFidelizacion(models.Model):
    cliente = models.OneToOneField(Cliente, on_delete=models.CASCADE, related_name='puntos')
    puntos_acumulados = models.IntegerField(default=0)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Puntos de Fidelización"
        verbose_name_plural = "Puntos de Fidelización"

    def __str__(self):
        return f"{self.cliente} - {self.puntos_acumulados} pts"


class Administrador(models.Model):
    user = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='perfil_admin')
    nivel_acceso = models.CharField(max_length=50, default='TOTAL')

    class Meta:
        verbose_name = "Perfil Administrador"
        verbose_name_plural = "Perfiles Administradores"

    def __str__(self):
        return f"Admin: {self.user.username}"


class Cajero(models.Model):
    user = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='perfil_cajero')
    num_caja_asignada = models.IntegerField(default=1)

    class Meta:
        verbose_name = "Perfil Cajero"
        verbose_name_plural = "Perfiles Cajeros"

    def __str__(self):
        return f"Cajero: {self.user.get_full_name() or self.user.username} (Caja {self.num_caja_asignada})"


# ==========================================
# 2. CATÁLOGOS Y PRODUCTOS
# ==========================================
class Categoria(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='productos')
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, null=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)
    stock_critico = models.IntegerField(default=10)
    imagen_url = models.URLField(max_length=500, blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"

    def __str__(self):
        return f"{self.nombre} (${self.precio})"


# ==========================================
# 3. INSUMOS, PROVEEDORES Y RECETAS
# ==========================================
class Proveedor(models.Model):
    rut = models.CharField(max_length=12, unique=True)
    nombre_proveedor = models.CharField(max_length=150)
    email = models.EmailField()
    telefono = models.CharField(max_length=20)
    direccion = models.CharField(max_length=255, blank=True, null=True)
    costo_flete = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Proveedor"
        verbose_name_plural = "Proveedores"

    def __str__(self):
        return self.nombre_proveedor


class Insumo(models.Model):
    nombre = models.CharField(max_length=100)
    tipo_insumo = models.CharField(max_length=50)
    unidad_medida = models.CharField(max_length=20)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    stock_actual = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_minimo = models.DecimalField(max_digits=10, decimal_places=2, default=5)
    proveedores = models.ManyToManyField(Proveedor, through='ProveedorInsumo', related_name='insumos')

    class Meta:
        verbose_name = "Insumo"
        verbose_name_plural = "Insumos"

    def __str__(self):
        return f"{self.nombre} ({self.stock_actual} {self.unidad_medida})"


class ProveedorInsumo(models.Model):
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE)
    precio_ofrecido = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = ('proveedor', 'insumo')
        verbose_name = "Tarifa Insumo Proveedor"
        verbose_name_plural = "Comparador Tarifas Proveedores"

    def __str__(self):
        return f"{self.insumo.nombre} en {self.proveedor.nombre_proveedor}: ${self.precio_ofrecido}"


class Receta(models.Model):
    producto = models.OneToOneField(Producto, on_delete=models.CASCADE, related_name='receta')
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Receta"
        verbose_name_plural = "Recetas"

    def __str__(self):
        return f"Receta de {self.producto.nombre}"


class IngredienteReceta(models.Model):
    receta = models.ForeignKey(Receta, on_delete=models.CASCADE, related_name='ingredientes')
    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE)
    cantidad = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        verbose_name = "Ingrediente de Receta"
        verbose_name_plural = "Ingredientes de Receta"

    def __str__(self):
        return f"{self.cantidad} {self.insumo.unidad_medida} de {self.insumo.nombre}"


class ProduccionDiaria(models.Model):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='producciones')
    cantidad = models.IntegerField()
    fecha_produccion = models.DateTimeField(auto_now_add=True)
    responsable = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Producción Diaria"
        verbose_name_plural = "Registro de Producción"

    def __str__(self):
        return f"Producción: {self.cantidad} un. de {self.producto.nombre} ({self.fecha_produccion.strftime('%d/%m/%Y')})"


# ==========================================
# 4. CARRITO Y PEDIDOS
# ==========================================
class Carrito(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='carritos', null=True, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Carrito #{self.id} ({self.cliente})"


class ItemCarrito(models.Model):
    carrito = models.ForeignKey(Carrito, on_delete=models.CASCADE, related_name='items')
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.IntegerField(default=1)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.cantidad}x {self.producto.nombre}"


class Pedido(models.Model):
    ESTADOS = [
        ('PENDIENTE', 'Pendiente'),
        ('PAGADO', 'Pagado'),
        ('PREPARACION', 'En Preparación'),
        ('LISTO', 'Listo para Entrega/Retiro'),
        ('ENTREGADO', 'Entregado'),
        ('CANCELADO', 'Cancelado'),
    ]
    CANALES = [
        ('WEB', 'Web / E-commerce'),
        ('PRESENCIAL', 'Presencial / POS'),
    ]
    ENTREGAS = [
        ('RETIRO', 'Retiro en Tienda'),
        ('DESPACHO', 'Despacho a Domicilio'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos')
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=50, choices=ESTADOS, default='PENDIENTE')
    canal = models.CharField(max_length=50, choices=CANALES, default='WEB')
    tipo_entrega = models.CharField(max_length=50, choices=ENTREGAS, default='RETIRO')
    direccion_despacho = models.CharField(max_length=255, blank=True, null=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Pedido"
        verbose_name_plural = "Pedidos"
        ordering = ['-fecha']

    def __str__(self):
        return f"Pedido #{self.id} - {self.canal} (${self.total})"


class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.IntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Detalle de Pedido"
        verbose_name_plural = "Detalles de Pedido"

    def __str__(self):
        return f"{self.cantidad} x {self.producto.nombre}"


class Pago(models.Model):
    pedido = models.OneToOneField(Pedido, on_delete=models.CASCADE, related_name='pago')
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    metodo = models.CharField(max_length=50)
    estado = models.CharField(max_length=50, default='PENDIENTE')
    codigo_autorizacion = models.CharField(max_length=100, blank=True, null=True)
    fecha_pago = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def __str__(self):
        return f"Pago #{self.id} (${self.monto}) - {self.metodo}"


# ==========================================
# 5. CAJA Y OPERACIONES (POS)
# ==========================================
class Caja(models.Model):
    cajero = models.ForeignKey(Cajero, on_delete=models.SET_NULL, null=True, related_name='cajas')
    fecha_apertura = models.DateTimeField(auto_now_add=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    monto_inicial = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=20, default='ABIERTA')

    class Meta:
        verbose_name = "Caja"
        verbose_name_plural = "Cajas"

    def __str__(self):
        return f"Caja #{self.id} - {self.cajero} ({self.estado})"


class CierreCaja(models.Model):
    caja = models.ForeignKey(Caja, on_delete=models.CASCADE, related_name='cierres')
    monto_inicial = models.DecimalField(max_digits=10, decimal_places=2)
    monto_ventas_sistema = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monto_contado = models.DecimalField(max_digits=10, decimal_places=2)
    diferencia = models.DecimalField(max_digits=10, decimal_places=2)
    estado_cuadratura = models.CharField(max_length=50)
    fecha_cierre = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cierre de Caja"
        verbose_name_plural = "Cierres de Caja"

    def __str__(self):
        return f"Cierre Caja #{self.caja.id} - {self.estado_cuadratura} (Dif: ${self.diferencia})"
