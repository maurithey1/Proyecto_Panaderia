from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    Usuario, Cliente, Cajero, Administrador, PuntosFidelizacion,
    Categoria, Producto, Proveedor, Insumo, ProveedorInsumo,
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

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria', 'precio', 'stock', 'stock_critico', 'activo')
    list_filter = ('categoria', 'activo')
    search_fields = ('nombre', 'descripcion')
    list_editable = ('precio', 'stock', 'activo')


# ==========================================
# 3. INSUMOS, PROVEEDORES Y RECETAS
# ==========================================
class ProveedorInsumoInline(admin.TabularInline):
    model = ProveedorInsumo
    extra = 1

@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ('rut', 'nombre_proveedor', 'telefono', 'email', 'costo_flete')
    search_fields = ('rut', 'nombre_proveedor')

@admin.register(Insumo)
class InsumoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo_insumo', 'unidad_medida', 'precio_unitario', 'stock_actual', 'stock_minimo')
    list_filter = ('tipo_insumo', 'unidad_medida')
    search_fields = ('nombre',)
    inlines = [ProveedorInsumoInline]

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
class DetallePedidoInline(admin.TabularInline):
    model = DetallePedido
    extra = 0
    readonly_fields = ('producto', 'cantidad', 'precio_unitario', 'subtotal')

@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'cliente', 'canal', 'estado', 'tipo_entrega', 'total', 'fecha')
    list_filter = ('estado', 'canal', 'tipo_entrega', 'fecha')
    search_fields = ('id', 'cliente__user__username', 'direccion_despacho')
    ordering = ('-fecha',)
    inlines = [DetallePedidoInline]

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
    list_display = ('id', 'cajero', 'monto_inicial', 'estado', 'fecha_apertura', 'fecha_cierre')
    list_filter = ('estado', 'fecha_apertura')

@admin.register(CierreCaja)
class CierreCajaAdmin(admin.ModelAdmin):
    list_display = ('caja', 'monto_inicial', 'monto_ventas_sistema', 'monto_contado', 'diferencia', 'estado_cuadratura', 'fecha_cierre')
    list_filter = ('estado_cuadratura', 'fecha_cierre')
