import json
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone

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


class Turno(models.Model):
    """Franja de venta (p. ej. "Mañana, 09:00 a 14:00") y los días de la semana en que rige.

    Un producto sin turnos se vende todo el día; con turnos, solo en esas franjas.
    """
    # El índice coincide con date.weekday(): lunes = 0 ... domingo = 6.
    CAMPOS_DIAS = ('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo')
    NOMBRES_DIAS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')

    nombre = models.CharField(max_length=50, unique=True)
    hora_inicio = models.TimeField(verbose_name='Desde')
    hora_fin = models.TimeField(verbose_name='Hasta')
    lunes = models.BooleanField(default=True)
    martes = models.BooleanField(default=True)
    miercoles = models.BooleanField('Miércoles', default=True)
    jueves = models.BooleanField(default=True)
    viernes = models.BooleanField(default=True)
    sabado = models.BooleanField('Sábado', default=True)
    domingo = models.BooleanField(default=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Turno de venta"
        verbose_name_plural = "Turnos de venta"
        ordering = ['hora_inicio', 'nombre']

    def __str__(self):
        if self.nombre_es_horario:
            return self.nombre
        return f"{self.nombre} ({self.horario_texto})"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.hora_inicio is not None and self.hora_inicio == self.hora_fin:
            raise ValidationError('La hora de inicio y la de término no pueden ser iguales.')
        if not any(getattr(self, campo) for campo in self.CAMPOS_DIAS):
            raise ValidationError('Marca al menos un día de la semana.')

    def dias_activos(self):
        """Índices de los días en que rige (lunes = 0)."""
        return [i for i, campo in enumerate(self.CAMPOS_DIAS) if getattr(self, campo)]

    @property
    def cruza_medianoche(self):
        """True si termina al día siguiente (p. ej. de 20:00 a 02:00)."""
        return self.hora_fin < self.hora_inicio

    def rige_en(self, momento):
        """True si un datetime (en hora de Chile) cae dentro del turno: día y hora.

        Los días marcados son los días en que el turno EMPIEZA. Un turno de lunes de 18:00 a 12:00
        cubre el lunes desde las 18:00 y el martes hasta las 12:00 (la madrugada es del día anterior).
        """
        dia = momento.weekday()
        hora = momento.time().replace(tzinfo=None)
        activos = self.dias_activos()
        if not self.cruza_medianoche:
            return dia in activos and self.hora_inicio <= hora < self.hora_fin
        en_la_noche = dia in activos and hora >= self.hora_inicio
        en_la_madrugada = (dia - 1) % 7 in activos and hora < self.hora_fin
        return en_la_noche or en_la_madrugada

    def cubre_tramo(self, dia_semana, inicio_min, fin_min):
        """True si el tramo [inicio_min, fin_min] (minutos desde las 00:00 de ese día) cae entero dentro
        del turno. Mismo criterio de días que rige_en: la madrugada pertenece al día anterior."""
        activos = self.dias_activos()
        turno_desde = self.hora_inicio.hour * 60 + self.hora_inicio.minute
        turno_hasta = self.hora_fin.hour * 60 + self.hora_fin.minute
        if not self.cruza_medianoche:
            return dia_semana in activos and turno_desde <= inicio_min and fin_min <= turno_hasta
        en_la_noche = dia_semana in activos and inicio_min >= turno_desde
        en_la_madrugada = (dia_semana - 1) % 7 in activos and fin_min <= turno_hasta
        return en_la_noche or en_la_madrugada

    @property
    def dias_formulario(self):
        """Los siete días con su letra y si rigen, para dibujar las casillas del formulario."""
        letras = ('L', 'M', 'X', 'J', 'V', 'S', 'D')
        return [
            {
                'indice': i,
                'letra': letras[i],
                'nombre': self.NOMBRES_DIAS[i].capitalize(),
                'marcado': bool(getattr(self, campo)),
            }
            for i, campo in enumerate(self.CAMPOS_DIAS)
        ]

    @property
    def horario_texto(self):
        return f"{self.hora_inicio:%H:%M} a {self.hora_fin:%H:%M}"

    @property
    def dias_texto(self):
        """'lunes a sábado', 'sábado y domingo', 'todos los días'..."""
        dias = self.dias_activos()
        if len(dias) == 7:
            return 'todos los días'
        tramos, actual = [], []
        for dia in dias:
            if actual and dia == actual[-1] + 1:
                actual.append(dia)
            else:
                if actual:
                    tramos.append(actual)
                actual = [dia]
        if actual:
            tramos.append(actual)
        nombres = self.NOMBRES_DIAS
        partes = []
        for tramo in tramos:
            if len(tramo) == 1:
                partes.append(nombres[tramo[0]])
            elif len(tramo) == 2:
                partes.append(f"{nombres[tramo[0]]} y {nombres[tramo[1]]}")
            else:
                partes.append(f"{nombres[tramo[0]]} a {nombres[tramo[-1]]}")
        return ', '.join(partes)

    @property
    def nombre_es_horario(self):
        """True si el nombre es el propio horario (los turnos creados desde el formulario de producto
        sin ponerles nombre), para no repetir las horas al mostrarlo."""
        return self.nombre.startswith(self.horario_texto)

    @property
    def descripcion(self):
        """Texto para mostrar al cliente: 'Tarde, 14:00 a 19:30, lunes a sábado'."""
        if self.nombre_es_horario:
            return self.nombre
        return f"{self.nombre}, {self.horario_texto}, {self.dias_texto}"


class Producto(models.Model):
    UNIDADES = (
        ('unid', 'Unidad'),
        ('kg', 'Kilogramo'),
    )

    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='productos')
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, null=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)
    stock_critico = models.IntegerField(default=10)
    unidad_medida = models.CharField(max_length=10, choices=UNIDADES, default='unid')
    unidades_por_kg = models.CharField(max_length=100, blank=True, null=True)
    imagen_url = models.CharField(max_length=500, blank=True, null=True, verbose_name="URL o Ruta de Imagen")
    activo = models.BooleanField(default=True)
    turnos = models.ManyToManyField(
        Turno, blank=True, related_name='productos', verbose_name='Turnos de venta',
        help_text='Sin turnos, el producto se vende todo el día.',
    )

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"

    def __str__(self):
        return f"{self.nombre} (${self.precio})"

    @property
    def disponibilidad_formulario(self):
        """JSON con la disponibilidad del producto, para rellenar el formulario de edición del panel.

        Sin turnos: todo el día (cadena vacía). Con un turno: sus horas y días. Con varios (cargados
        desde /admin/), el formulario los respeta y no los edita.
        """
        turnos = list(self.turnos.all())
        if not turnos:
            return ''
        if len(turnos) > 1:
            return json.dumps({'varios': True, 'lista': '; '.join(t.descripcion for t in turnos)})
        turno = turnos[0]
        return json.dumps({
            'varios': False,
            'nombre': '' if turno.nombre_es_horario else turno.nombre,
            'desde': f"{turno.hora_inicio:%H:%M}",
            'hasta': f"{turno.hora_fin:%H:%M}",
            'dias': turno.dias_activos(),
        })


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
    # Unidad en que se mide la cantidad total y el contenido de cada saco, caja o bidón
    UNIDADES_MEDIDA = (
        ('kg', 'Kilos (kg)'),
        ('L', 'Litros (L)'),
        ('un.', 'Unidades (un.)'),
    )

    codigo = models.CharField(max_length=20, unique=True, default='', blank=True, verbose_name="ID / Código")
    nombre = models.CharField(max_length=100, verbose_name="Nombre producto")
    tipo_insumo = models.CharField(max_length=50, default='Materia Prima', blank=True)
    unidad_medida = models.CharField(max_length=20, default='Kg', blank=True)
    stock_sacos = models.IntegerField(default=0, verbose_name="Stock (Bolsa/saco)")
    kilos_por_saco = models.DecimalField(max_digits=8, decimal_places=2, default=25.00, verbose_name="Kg por saco")
    total_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total Kg")
    proveedor_nombre = models.CharField(max_length=150, default='', blank=True, verbose_name="Nombre Proveedor")
    precio_saco = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Precio por saco")
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_actual = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_minimo = models.DecimalField(max_digits=10, decimal_places=2, default=5)
    producto_odepa = models.CharField(
        max_length=100, default='', blank=True, verbose_name="Producto equivalente en ODEPA",
        help_text="Nombre del producto en ODEPA con el que se compara el precio de mercado.",
    )
    proveedores = models.ManyToManyField(Proveedor, through='ProveedorInsumo', related_name='insumos', blank=True)

    class Meta:
        verbose_name = "Insumo"
        verbose_name_plural = "Insumos"
        ordering = ['codigo', 'nombre']

    @property
    def unidad(self):
        """Unidad de la cantidad total y del contenido: 'kg', 'L' o 'un.' (los antiguos 'Kg' son kg)."""
        texto = (self.unidad_medida or '').strip().lower().rstrip('.')
        if texto in ('l', 'lt', 'lts', 'litro', 'litros'):
            return 'L'
        if texto in ('u', 'un', 'unid', 'unidad', 'unidades'):
            return 'un.'
        return 'kg'

    def save(self, *args, **kwargs):
        # El stock real es lo que queda en sus envases (EnvaseInsumo) y se guarda sumado en total_kg
        # (en kg, L o un.); las unidades completas (stock_sacos) se calculan desde ahí: 436 huevos en
        # cajas de 180 son 2 cajas completas. kilos_por_saco y precio_saco son los del envase de
        # referencia (el último que llegó), que usan el comparador y las órdenes de compra.
        # Un insumo nuevo que solo trae unidades completas (código antiguo) toma el total de ellas.
        contenido = Decimal(str(self.kilos_por_saco or 0))
        total = Decimal(str(self.total_kg or 0))
        creando = self._state.adding
        if creando and not total and self.stock_sacos:
            total = self.stock_sacos * contenido
        if contenido > 0:
            self.stock_sacos = int(total // contenido)
            precio = Decimal(str(self.precio_saco or 0))
            if precio > 0:
                self.precio_unitario = precio / contenido
        self.total_kg = total
        self.stock_actual = total
        super().save(*args, **kwargs)
        # Creado con stock y sin envases: el stock se reparte en envases llenos y uno en uso
        if creando and total > 0 and contenido > 0 and not self.envases.exists():
            llenos, resto = divmod(total, contenido)
            for _ in range(int(llenos)):
                self.envases.create(tipo='envase', contenido=contenido, restante=contenido, precio=self.precio_saco or 0)
            if resto:
                self.envases.create(tipo='envase', contenido=contenido, restante=resto, precio=self.precio_saco or 0)

    def actualizar_stock(self):
        """Vuelve a sumar lo que queda en los envases (después de un ingreso o una merma)."""
        self.total_kg = self.envases.aggregate(total=models.Sum('restante'))['total'] or Decimal('0')
        self.save(update_fields=['total_kg', 'stock_sacos', 'stock_actual'])

    def __str__(self):
        return f"{self.codigo} - {self.nombre} ({self.total_kg} {self.unidad})"


class EnvaseInsumo(models.Model):
    """
    Un saco, caja, bandeja o bidón de un insumo, con lo que le queda. El stock del insumo es la suma
    de sus envases (Insumo.actualizar_stock). Una merma se descuenta de un envase específico: de la
    caja en uso que tiene 76 huevos, no de las que siguen cerradas.
    """
    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE, related_name='envases')
    tipo = models.CharField(max_length=60, verbose_name="Tipo de envase")    # lo escribe el admin: "caja", "bandeja de 12"
    contenido = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Cantidad del envase")
    restante = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Le queda")
    precio = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Precio del envase")
    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.SET_NULL, null=True, blank=True, related_name='envases_insumo',
    )
    fecha_ingreso = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['insumo', 'fecha_ingreso', 'pk']
        verbose_name = 'Envase de insumo'
        verbose_name_plural = 'Envases de insumos'

    @property
    def en_uso(self):
        """Abierto: ya se sacó algo, pero le queda."""
        return 0 < self.restante < self.contenido

    @property
    def precio_por_unidad(self):
        """Lo que cuesta cada kg, L o un. de este envase ($36.990 / 180 = $205,50 por huevo)."""
        return self.precio / self.contenido if self.contenido else Decimal('0')

    def __str__(self):
        return f"{self.insumo.nombre}, {self.tipo}: quedan {self.restante} de {self.contenido} {self.insumo.unidad}"


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


class PrecioMercado(models.Model):
    """Precio de referencia de un insumo en el mercado, consultado a una fuente externa (ODEPA).

    Hay una fila por semana, región, sector y tipo de punto de venta, de modo que cada
    actualización suma historial en vez de pisar los datos anteriores.
    """
    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE, related_name='precios_mercado')
    fuente = models.CharField(max_length=30, default='ODEPA')
    producto_fuente = models.CharField(max_length=100)
    region = models.CharField(max_length=100)
    sector = models.CharField(max_length=100)
    tipo_punto = models.CharField(max_length=60, blank=True, default='')
    fecha = models.DateField(help_text="Primer día de la semana a la que corresponde el precio.")
    unidad = models.CharField(max_length=60, blank=True, default='')
    precio_minimo = models.DecimalField(max_digits=12, decimal_places=2)
    precio_maximo = models.DecimalField(max_digits=12, decimal_places=2)
    precio_promedio = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        unique_together = ('insumo', 'fuente', 'region', 'sector', 'tipo_punto', 'fecha')
        ordering = ['-fecha', 'precio_promedio']
        verbose_name = "Precio de mercado"
        verbose_name_plural = "Precios de mercado"

    def __str__(self):
        return f"{self.insumo.nombre} · {self.sector} ({self.fecha}): ${self.precio_promedio} {self.unidad}"


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


class ConsumoProduccion(models.Model):
    """
    Lo que gastó una hornada de cada insumo de la receta (HU-EP003-003): lo que pedía la receta, lo que
    se descontó de los envases y lo que faltó. Si quedaba menos de lo que pedía, el panadero lo hace
    rendir y la hornada se registra igual: la diferencia queda como déficit. Reglas en core/recetas.py.
    """
    produccion = models.ForeignKey(ProduccionDiaria, on_delete=models.CASCADE, related_name='consumos')
    insumo = models.ForeignKey(Insumo, on_delete=models.SET_NULL, null=True, blank=True, related_name='consumos')
    # Nombre y unidad se copian: el registro se conserva aunque el insumo se elimine
    nombre_insumo = models.CharField(max_length=100)
    unidad = models.CharField(max_length=10)
    cantidad_receta = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Pedía la receta")
    cantidad_usada = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Se descontó")
    faltante = models.DecimalField(max_digits=12, decimal_places=3, default=0, verbose_name="Faltó")
    costo = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Costo de lo usado")

    class Meta:
        ordering = ['-produccion__fecha_produccion', 'pk']
        verbose_name = 'Consumo de producción'
        verbose_name_plural = 'Consumos de producción'

    def __str__(self):
        return f"{self.produccion}: {self.cantidad_usada} {self.unidad} de {self.nombre_insumo}"


class Notificacion(models.Model):
    TIPOS = (
        ('INSUMO', 'Materia Prima / Insumo'),
        ('PRODUCTO', 'Producto de Catálogo'),
        ('MERCADO', 'Oportunidad de Mercado'),  # Escalabilidad futura
    )

    tipo = models.CharField(max_length=20, choices=TIPOS, default='INSUMO')
    titulo = models.CharField(max_length=150)
    mensaje = models.TextField()
    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE, null=True, blank=True)
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, null=True, blank=True)
    fecha_creacion = models.DateTimeField(default=timezone.now)
    leida = models.BooleanField(default=False)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Notificación'
        verbose_name_plural = 'Notificaciones'

    def __str__(self):
        return f"[{self.get_tipo_display()}] {self.titulo} - {'Leída' if self.leida else 'No leída'}"


class HistorialPrecioInsumo(models.Model):
    """
    Registra el historial y auditoría de fluctuaciones de precios de materias primas.
    """
    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE, related_name='historial_precios', verbose_name="Materia Prima")
    proveedor = models.ForeignKey(Proveedor, on_delete=models.SET_NULL, null=True, blank=True, related_name='historial_precios_insumos', verbose_name="Proveedor / Molinera")
    precio_saco = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio por Saco")
    precio_anterior = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Precio Anterior")
    variacion_porcentaje = models.DecimalField(max_digits=6, decimal_places=2, default=0.00, verbose_name="Variación %")
    origen_cambio = models.CharField(max_length=120, default='Actualización de Inventario', verbose_name="Origen / Nota")
    fecha_registro = models.DateTimeField(default=timezone.now, verbose_name="Fecha de Registro")

    class Meta:
        verbose_name = "Historial de Precio de Insumo"
        verbose_name_plural = "Historiales de Precios de Insumos"
        ordering = ['-fecha_registro']

    def __str__(self):
        return f"{self.insumo.nombre} - ${self.precio_saco:,.0f} ({self.fecha_registro.strftime('%d/%m/%Y')})"


class Merma(models.Model):
    """
    Inventario que se perdió sin venderse (HU-EP002-008): descuenta el stock del producto o insumo
    y deja registro de la pérdida. Reglas en core/mermas.py.
    """
    TIPOS = (
        ('PRODUCTO', 'Producto'),
        ('INSUMO', 'Insumo'),
    )
    MOTIVOS = (
        ('VENCIMIENTO', 'Vencimiento'),
        ('DANO', 'Daño o rotura'),
        ('QUEMADO', 'Quemado o mal horneado'),
        ('HUMEDAD', 'Humedad o contaminación'),
        ('SOBRANTE', 'Sobrante no vendido'),
        ('OTRO', 'Otro'),
    )

    tipo = models.CharField(max_length=10, choices=TIPOS)
    producto = models.ForeignKey(Producto, on_delete=models.SET_NULL, null=True, blank=True, related_name='mermas')
    insumo = models.ForeignKey(Insumo, on_delete=models.SET_NULL, null=True, blank=True, related_name='mermas')
    # De qué saco, caja o bidón salió la pérdida (solo insumos)
    envase = models.ForeignKey(EnvaseInsumo, on_delete=models.SET_NULL, null=True, blank=True, related_name='mermas')
    # Nombre y unidad se copian al registrar: el historial de pérdidas se conserva aunque el ítem se elimine
    nombre_item = models.CharField(max_length=150, verbose_name="Producto o insumo")
    unidad = models.CharField(max_length=20, verbose_name="Unidad")
    # Con decimales: un insumo puede perder 2,5 kg o 0,5 L. Los stocks son los del producto o insumo.
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    motivo = models.CharField(max_length=20, choices=MOTIVOS)
    detalle = models.CharField(max_length=255, blank=True, default='')
    stock_anterior = models.DecimalField(max_digits=10, decimal_places=2)
    stock_resultante = models.DecimalField(max_digits=10, decimal_places=2)
    valor_estimado = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Pérdida estimada")
    responsable = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='mermas_registradas')
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'Merma'
        verbose_name_plural = 'Mermas'

    def __str__(self):
        return f"Merma: {self.cantidad} {self.unidad} de {self.nombre_item} ({self.get_motivo_display()})"


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
    cajero = models.ForeignKey(Cajero, on_delete=models.SET_NULL, null=True, blank=True, related_name='ventas', verbose_name='Cajero que registró la venta')
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
    numero = models.IntegerField(default=1, verbose_name='Número de caja')
    fecha_apertura = models.DateTimeField(auto_now_add=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    monto_inicial = models.DecimalField(max_digits=10, decimal_places=2)
    observacion_apertura = models.TextField(blank=True, default='', verbose_name='Observación de apertura')
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
    observacion = models.TextField(blank=True, default='', verbose_name='Observación del cierre')
    fecha_cierre = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cierre de Caja"
        verbose_name_plural = "Cierres de Caja"

    @property
    def monto_esperado(self):
        return self.monto_inicial + self.monto_ventas_sistema

    def __str__(self):
        return f"Cierre Caja #{self.caja.id} - {self.estado_cuadratura} (Dif: ${self.diferencia})"


# ==========================================
# 6. ÓRDENES DE COMPRA (RQF9)
# ==========================================
class OrdenCompra(models.Model):
    """
    Representa una orden de compra formal emitida a una molinera o proveedor
    de materias primas (RQF9).
    """
    ESTADOS = [
        ('EMITIDA', 'Emitida'),
        ('ENVIADA', 'Enviada al proveedor'),
        ('RECEPCIONADA', 'Recepcionada / En bodega'),
        ('CANCELADA', 'Cancelada'),
    ]

    codigo = models.CharField(max_length=30, unique=True, verbose_name="Código de Orden")
    proveedor = models.ForeignKey(
        Proveedor,
        on_delete=models.CASCADE,
        related_name='ordenes_compra',
        verbose_name="Molinera / Proveedor"
    )
    administrador = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ordenes_emitidas',
        verbose_name="Emitida por"
    )
    fecha_emision = models.DateTimeField(default=timezone.now, verbose_name="Fecha de emisión")
    fecha_entrega_esperada = models.DateField(null=True, blank=True, verbose_name="Fecha estimada de entrega")
    estado = models.CharField(max_length=20, choices=ESTADOS, default='EMITIDA', verbose_name="Estado")

    contacto_nombre = models.CharField(max_length=150, blank=True, default='', verbose_name="Contacto en molinera")
    contacto_email = models.EmailField(blank=True, default='', verbose_name="Correo de contacto")
    contacto_telefono = models.CharField(max_length=30, blank=True, default='', verbose_name="Teléfono / WhatsApp")

    costo_flete = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Costo de flete")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Subtotal materias primas")
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Total orden de compra")

    condiciones_pago = models.CharField(max_length=120, default='Transferencia bancaria contra entrega', blank=True, verbose_name="Condiciones de pago")
    observaciones = models.TextField(blank=True, default='', verbose_name="Observaciones / Instrucciones")

    enviada_por_email = models.BooleanField(default=False, verbose_name="Enviada por correo")
    fecha_envio_email = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de envío por correo")
    enviada_por_mensaje = models.BooleanField(default=False, verbose_name="Enviada por mensaje")
    fecha_envio_mensaje = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de envío por mensaje")

    class Meta:
        verbose_name = "Orden de Compra"
        verbose_name_plural = "Órdenes de Compra"
        ordering = ['-fecha_emision']

    def __str__(self):
        return f"{self.codigo} - {self.proveedor.nombre_proveedor} (${self.total})"

    def calcular_totales(self):
        """Calcula el subtotal sumando los detalles y suma el flete para el total general."""
        suma_detalles = sum(d.subtotal for d in self.detalles.all())
        self.subtotal = suma_detalles
        self.total = suma_detalles + (self.costo_flete or 0)
        self.save(update_fields=['subtotal', 'total'])


class DetalleOrdenCompra(models.Model):
    """
    Renglón o ítem individual de materia prima dentro de una orden de compra.
    """
    orden = models.ForeignKey(OrdenCompra, on_delete=models.CASCADE, related_name='detalles')
    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE, verbose_name="Materia Prima / Insumo")
    cantidad_sacos = models.PositiveIntegerField(default=1, verbose_name="Cantidad de sacos / bultos")
    kilos_por_saco = models.DecimalField(max_digits=8, decimal_places=2, default=25.00, verbose_name="Kg por saco")
    total_kilos = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total Kilogramos")
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio por saco")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Subtotal ítem")

    class Meta:
        verbose_name = "Detalle de Orden de Compra"
        verbose_name_plural = "Detalles de Orden de Compra"

    def __str__(self):
        return f"{self.cantidad_sacos} sacos de {self.insumo.nombre} en {self.orden.codigo}"

    def save(self, *args, **kwargs):
        self.total_kilos = float(self.cantidad_sacos) * float(self.kilos_por_saco)
        self.subtotal = float(self.cantidad_sacos) * float(self.precio_unitario)
        super().save(*args, **kwargs)


