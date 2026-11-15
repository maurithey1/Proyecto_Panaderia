from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.db.models import Q
from .models import (
    Usuario, Cliente, Cajero, Administrador, PuntosFidelizacion,
    Categoria, Producto, Turno, Proveedor, Insumo, ProveedorInsumo, EnvaseInsumo,
    Receta, IngredienteReceta, ProduccionDiaria,
    Carrito, ItemCarrito, Pedido, DetallePedido, Pago,
    Caja, CierreCaja
)

# ==========================================
# 1. USUARIOS Y ROLES (Inlines)
# ==========================================
class CajeroInline(admin.StackedInline):
    model = Cajero
    can_delete = False
    extra = 0
    verbose_name = 'Perfil de Cajero'
    verbose_name_plural = 'Datos de Cajero (Completar si el rol es Cajero)'

class ClienteInline(admin.StackedInline):
    model = Cliente
    can_delete = False
    extra = 0
    verbose_name = 'Perfil de Cliente'
    verbose_name_plural = 'Datos de Cliente (Completar si el rol es Cliente)'

class AdministradorInline(admin.StackedInline):
    model = Administrador
    can_delete = False
    extra = 0
    verbose_name = 'Perfil de Administrador'
    verbose_name_plural = 'Datos de Administrador (Completar si el rol es Administrador)'

@admin.register(Usuario)
class CustomUsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Asignación de Rol', {'fields': ('rol',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Asignación de Rol', {'fields': ('rol',)}),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'rol', 'is_staff', 'is_active')
    list_filter = ('rol', 'is_staff', 'is_active')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('username',)
    inlines = [CajeroInline, ClienteInline, AdministradorInline]

@admin.register(PuntosFidelizacion)
class PuntosFidelizacionAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'puntos_acumulados', 'fecha_actualizacion')
    search_fields = ('cliente__user__username', 'cliente__user__first_name', 'cliente__user__last_name')


# ==========================================
# 2. CATÁLOGO Y PRODUCTOS
# ==========================================
@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'descripcion')
    search_fields = ('nombre',)

@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'hora_inicio', 'hora_fin', 'dias_texto', 'activo')
    list_editable = ('activo',)
    list_filter = ('activo',)
    fieldsets = (
        (None, {'fields': ('nombre', ('hora_inicio', 'hora_fin'), 'activo')}),
        ('Días en que rige', {
            'fields': (('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo'),),
        }),
    )

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria', 'precio', 'stock', 'stock_critico', 'activo')
    list_filter = ('categoria', 'activo', 'turnos')
    search_fields = ('nombre', 'descripcion')
    list_editable = ('precio', 'stock', 'activo')
    filter_horizontal = ('turnos',)


# ==========================================
# 3. INSUMOS, PROVEEDORES Y RECETAS
# ==========================================
class ProveedorInsumoInline(admin.TabularInline):
    model = ProveedorInsumo
    extra = 1

# Envases del insumo (cada saco, caja o bidón con lo que le queda): aquí se puede corregir uno mal ingresado
class EnvaseInsumoInline(admin.TabularInline):
    model = EnvaseInsumo
    extra = 0

@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ('rut', 'nombre_proveedor', 'telefono', 'email', 'costo_flete')
    search_fields = ('rut', 'nombre_proveedor')

@admin.register(Insumo)
class InsumoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo_insumo', 'unidad_medida', 'precio_unitario', 'stock_actual', 'stock_minimo')
    list_filter = ('tipo_insumo', 'unidad_medida')
    search_fields = ('nombre',)
    inlines = [EnvaseInsumoInline, ProveedorInsumoInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.actualizar_stock()    # el stock es la suma de lo que queda en los envases

class IngredienteRecetaInline(admin.TabularInline):
    model = IngredienteReceta
    extra = 1

@admin.register(Receta)
class RecetaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'producto')
    search_fields = ('nombre', 'producto__nombre')
    inlines = [IngredienteRecetaInline]

@admin.register(ProduccionDiaria)
class ProduccionDiariaAdmin(admin.ModelAdmin):
    list_display = ('producto', 'cantidad', 'fecha_produccion', 'responsable')
    list_filter = ('fecha_produccion', 'producto')
    search_fields = ('producto__nombre', 'responsable__username')


# ==========================================
# 4. PEDIDOS Y PAGOS
# ==========================================
class TipoClienteFilter(admin.SimpleListFilter):
    title = 'Tipo de cliente'
    parameter_name = 'tipo_cliente'

    def lookups(self, request, model_admin):
        return (
            ('REGISTRADO', 'Cliente Registrado (con cuenta)'),
            ('INVITADO_WEB', 'Invitado Web (sin cuenta)'),
            ('MOSTRADOR_POS', 'Mostrador POS (presencial)'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'REGISTRADO':
            return queryset.filter(cliente__isnull=False)
        if self.value() == 'INVITADO_WEB':
            return queryset.filter(cliente__isnull=True, canal='WEB')
        if self.value() == 'MOSTRADOR_POS':
            return queryset.filter(cliente__isnull=True, canal__in=['PRESENCIAL', 'POS'])
        return queryset


class DetallePedidoInline(admin.TabularInline):
    model = DetallePedido
    extra = 0
    readonly_fields = ('producto', 'cantidad', 'precio_unitario', 'subtotal')


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'cliente_columna',
        'canal_columna',
        'cajero_columna',
        'estado',
        'tipo_entrega',
        'direccion_columna',
        'total_columna',
        'fecha',
    )
    list_filter = (
        'estado',
        'canal',
        TipoClienteFilter,
        'cajero',
        'tipo_entrega',
        'fecha',
    )
    search_fields = (
        'id',
        'cliente__user__first_name',
        'cliente__user__last_name',
        'cliente__user__username',
        'cliente__user__email',
        'cliente_nombre_respaldo',
        'direccion_despacho',
    )
    ordering = ('-fecha',)
    list_select_related = ('cliente__user', 'cajero__user')
    inlines = [DetallePedidoInline]
    actions = ['normalizar_pedidos_historicos']

    @admin.display(description='Cliente', ordering='cliente__user__first_name')
    def cliente_columna(self, obj):
        return obj.nombre_cliente_display

    @admin.display(description='Canal', ordering='canal')
    def canal_columna(self, obj):
        return obj.nombre_canal_display

    @admin.display(description='Cajero que registró la venta', ordering='cajero__user__first_name')
    def cajero_columna(self, obj):
        return obj.nombre_cajero_display

    @admin.display(description='Detalle / Dirección entrega', ordering='direccion_despacho')
    def direccion_columna(self, obj):
        return obj.direccion_entrega_display

    @admin.display(description='Total', ordering='total')
    def total_columna(self, obj):
        return f"${int(round(obj.total)):,}".replace(',', '.')

    @admin.action(description='Normalizar canal POS y completar datos vacíos en pedidos seleccionados')
    def normalizar_pedidos_historicos(self, request, queryset):
        actualizados_canal = queryset.filter(canal='POS').update(canal='PRESENCIAL')
        actualizados_dir = queryset.filter(
            canal='PRESENCIAL',
        ).filter(
            Q(direccion_despacho__isnull=True) | Q(direccion_despacho='')
        ).update(direccion_despacho='Venta presencial en Caja')

        self.message_user(
            request,
            f"Normalización completada: {actualizados_canal} pedido(s) migrados de 'POS' a 'PRESENCIAL' "
            f"y {actualizados_dir} dirección(es) completada(s).",
            level=messages.SUCCESS
        )


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ('id', 'pedido', 'monto', 'metodo', 'estado', 'codigo_autorizacion', 'fecha_pago')
    list_filter = ('metodo', 'estado', 'fecha_pago')
    search_fields = ('pedido__id', 'codigo_autorizacion')


# ==========================================
# 5. CAJA Y OPERACIONES (POS)
# ==========================================
@admin.register(Caja)
class CajaAdmin(admin.ModelAdmin):
    list_display = ('id', 'numero', 'cajero', 'monto_inicial', 'estado', 'fecha_apertura', 'fecha_cierre')
    list_filter = ('estado', 'numero', 'fecha_apertura')

@admin.register(CierreCaja)
class CierreCajaAdmin(admin.ModelAdmin):
    list_display = ('caja', 'monto_inicial', 'monto_ventas_sistema', 'monto_contado', 'diferencia', 'estado_cuadratura', 'observacion', 'fecha_cierre')
    list_filter = ('estado_cuadratura', 'fecha_cierre')
    search_fields = ('caja__numero', 'caja__cajero__user__username', 'observacion')

