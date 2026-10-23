// ==========================================
// 1. CAMBIO DE PESTAÑAS (3 PESTAÑAS)
// ==========================================
function cambiarPestanaCrud(pestana) {
  const panelInsumos = document.getElementById('panelInsumos');
  const panelProductos = document.getElementById('panelProductos');
  const panelProveedores = document.getElementById('panelProveedores');

  const tabInsumos = document.getElementById('tabBtnInsumos');
  const tabProductos = document.getElementById('tabBtnProductos');
  const tabProveedores = document.getElementById('tabBtnProveedores');

  const btnInsumo = document.getElementById('btnAccionAgregarInsumo');
  const btnProducto = document.getElementById('btnAccionAgregarProducto');
  const btnProveedor = document.getElementById('btnAccionAgregarProveedor');

  const titulo = document.getElementById('crudTituloPrincipal');

  // Ocultar todos los paneles
  if (panelInsumos) panelInsumos.style.display = 'none';
  if (panelProductos) panelProductos.style.display = 'none';
  if (panelProveedores) panelProveedores.style.display = 'none';

  // Desactivar botones de pestañas
  if (tabInsumos) tabInsumos.classList.remove('activa');
  if (tabProductos) tabProductos.classList.remove('activa');
  if (tabProveedores) tabProveedores.classList.remove('activa');

  // Ocultar botones superiores de acción
  if (btnInsumo) btnInsumo.style.display = 'none';
  if (btnProducto) btnProducto.style.display = 'none';
  if (btnProveedor) btnProveedor.style.display = 'none';

  // Activar vista según pestaña seleccionada
  if (pestana === 'insumos') {
    if (panelInsumos) panelInsumos.style.display = 'block';
    if (tabInsumos) tabInsumos.classList.add('activa');
    if (btnInsumo) btnInsumo.style.display = 'inline-block';
    if (titulo) titulo.textContent = 'Gestión de insumos y materias primas';
  } else if (pestana === 'productos') {
    if (panelProductos) panelProductos.style.display = 'block';
    if (tabProductos) tabProductos.classList.add('activa');
    if (btnProducto) btnProducto.style.display = 'inline-block';
    if (titulo) titulo.textContent = 'Gestión de productos de la panadería';
  } else if (pestana === 'proveedores') {
    if (panelProveedores) panelProveedores.style.display = 'block';
    if (tabProveedores) tabProveedores.classList.add('activa');
    if (btnProveedor) btnProveedor.style.display = 'inline-block';
    if (titulo) titulo.textContent = 'Gestión de proveedores de materias primas';
  }
}

// Activar pestaña según el parámetro ?tab= de la URL
document.addEventListener('DOMContentLoaded', function() {
  const urlParams = new URLSearchParams(window.location.search);
  const tab = urlParams.get('tab');
  
  if (tab && ['insumos', 'productos', 'proveedores'].includes(tab)) {
    cambiarPestanaCrud(tab);
  }
});

// ==========================================
// 2. MODALES DE INSUMOS
// ==========================================
function abrirModalAgregarInsumo() {
  const modal = document.getElementById('modalAgregarInsumo');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalAgregarInsumo() {
  const modal = document.getElementById('modalAgregarInsumo');
  if (modal) modal.style.display = 'none';
}

function abrirModalEditarInsumo(pk, codigo, nombre, stockSacos, kilosSaco, totalKg, proveedor, precioSaco) {
  const form = document.getElementById('formEditarInsumo');
  if (form) form.action = `/panel-admin/inventario/editar/${pk}/`;

  if (document.getElementById('edit_insumo_codigo')) document.getElementById('edit_insumo_codigo').value = codigo || '';
  if (document.getElementById('edit_insumo_nombre')) document.getElementById('edit_insumo_nombre').value = nombre || '';
  if (document.getElementById('edit_insumo_stock_sacos')) document.getElementById('edit_insumo_stock_sacos').value = stockSacos || 0;
  if (document.getElementById('edit_insumo_kilos_por_saco')) document.getElementById('edit_insumo_kilos_por_saco').value = kilosSaco || 25;
  if (document.getElementById('edit_insumo_proveedor')) document.getElementById('edit_insumo_proveedor').value = proveedor || '';
  if (document.getElementById('edit_insumo_precio_saco')) document.getElementById('edit_insumo_precio_saco').value = precioSaco || 0;

  const modal = document.getElementById('modalEditarInsumo');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalEditarInsumo() {
  const modal = document.getElementById('modalEditarInsumo');
  if (modal) modal.style.display = 'none';
}

function abrirModalEliminarInsumo(pk, codigo, nombre) {
  const form = document.getElementById('formEliminarInsumo');
  if (form) form.action = `/panel-admin/inventario/eliminar/${pk}/`;

  const txt = document.getElementById('eliminar_insumo_texto');
  if (txt) txt.textContent = `${codigo ? codigo + ' - ' : ''}${nombre}`;

  const modal = document.getElementById('modalEliminarInsumo');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalEliminarInsumo() {
  const modal = document.getElementById('modalEliminarInsumo');
  if (modal) modal.style.display = 'none';
}

// ==========================================
// 3. MODALES DE PRODUCTOS
// ==========================================
function abrirModalAgregarProducto() {
  const modal = document.getElementById('modalAgregarProducto');
  if (modal) {
    modal.style.display = 'flex';
    if (typeof cargarDisponibilidad === 'function') {
      cargarDisponibilidad(modal, null);
    }
  }
}

function cerrarModalAgregarProducto() {
  const modal = document.getElementById('modalAgregarProducto');
  if (modal) modal.style.display = 'none';
}

function abrirModalEditarProductoBtn(btn) {
  const pk = btn.dataset.pk;
  const nombre = btn.dataset.nombre;
  const categoriaId = btn.dataset.categoria;
  const precio = btn.dataset.precio;
  const stock = btn.dataset.stock;
  const stockCritico = btn.dataset.stockCritico;
  const unidad = btn.dataset.unidad;
  const desc = btn.dataset.descripcion;
  const activo = btn.dataset.activo;
  const imagenUrl = btn.dataset.imagen;
  const disponibilidadRaw = btn.dataset.disponibilidad;

  const form = document.getElementById('formEditarProducto');
  if (form) form.action = `/panel-admin/productos/editar/${pk}/`;

  if (document.getElementById('edit_prod_nombre')) document.getElementById('edit_prod_nombre').value = nombre || '';
  if (document.getElementById('edit_prod_categoria')) document.getElementById('edit_prod_categoria').value = categoriaId || '';
  if (document.getElementById('edit_prod_precio')) document.getElementById('edit_prod_precio').value = precio || 0;
  if (document.getElementById('edit_prod_stock')) document.getElementById('edit_prod_stock').value = stock || 0;
  if (document.getElementById('edit_prod_stock_critico')) document.getElementById('edit_prod_stock_critico').value = stockCritico || 10;
  if (document.getElementById('edit_prod_unidad')) document.getElementById('edit_prod_unidad').value = unidad || 'unid';
  if (document.getElementById('edit_prod_desc')) document.getElementById('edit_prod_desc').value = desc || '';
  if (document.getElementById('edit_prod_imagen')) document.getElementById('edit_prod_imagen').value = imagenUrl || '';
  if (document.getElementById('edit_prod_activo')) document.getElementById('edit_prod_activo').checked = (activo === 'true' || activo === true);

  if (typeof cargarDisponibilidad === 'function') {
    let dispObj = null;
    if (disponibilidadRaw) {
      try {
        dispObj = JSON.parse(disponibilidadRaw);
      } catch (e) {
        console.error("Error al parsear disponibilidad:", e);
      }
    }
    const contenedorDisp = document.getElementById('edit_prod_disponibilidad') || document.getElementById('modalEditarProducto');
    cargarDisponibilidad(contenedorDisp, dispObj);
  }

  const modal = document.getElementById('modalEditarProducto');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalEditarProducto() {
  const modal = document.getElementById('modalEditarProducto');
  if (modal) modal.style.display = 'none';
}

function abrirModalRegistrarProduccion(pk, nombre) {
  const form = document.getElementById('formRegistrarProduccion');
  if (form) form.action = `/panel-admin/productos/produccion/${pk}/`;

  const txt = document.getElementById('produccion_producto_nombre');
  if (txt) txt.textContent = `Producto: ${nombre}`;

  const modal = document.getElementById('modalRegistrarProduccion');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalRegistrarProduccion() {
  const modal = document.getElementById('modalRegistrarProduccion');
  if (modal) modal.style.display = 'none';
}

function abrirModalEliminarProducto(pk, nombre) {
  const form = document.getElementById('formEliminarProducto');
  if (form) form.action = `/panel-admin/productos/eliminar/${pk}/`;

  const txt = document.getElementById('eliminar_prod_texto');
  if (txt) txt.textContent = nombre;

  const modal = document.getElementById('modalEliminarProducto');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalEliminarProducto() {
  const modal = document.getElementById('modalEliminarProducto');
  if (modal) modal.style.display = 'none';
}

// Modales de Categoría Rápida
function abrirModalAgregarCategoria() {
  const modal = document.getElementById('modalAgregarCategoria');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalAgregarCategoria() {
  const modal = document.getElementById('modalAgregarCategoria');
  if (modal) modal.style.display = 'none';
}

// ==========================================
// 4. MODALES DE PROVEEDORES
// ==========================================
function abrirModalAgregarProveedor() {
  const modal = document.getElementById('modalAgregarProveedor');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalAgregarProveedor() {
  const modal = document.getElementById('modalAgregarProveedor');
  if (modal) modal.style.display = 'none';
}

function abrirModalEditarProveedor(pk, rut, nombre, email, telefono, direccion, costoFlete) {
  const modal = document.getElementById('modalEditarProveedor');
  const form = document.getElementById('formEditarProveedor');

  if (form) form.action = `/panel-admin/proveedores/editar/${pk}/`;

  if (document.getElementById('edit_prov_rut')) document.getElementById('edit_prov_rut').value = rut || '';
  if (document.getElementById('edit_prov_nombre')) document.getElementById('edit_prov_nombre').value = nombre || '';
  if (document.getElementById('edit_prov_email')) document.getElementById('edit_prov_email').value = email || '';
  if (document.getElementById('edit_prov_telefono')) document.getElementById('edit_prov_telefono').value = telefono || '';
  if (document.getElementById('edit_prov_dir')) document.getElementById('edit_prov_dir').value = direccion || '';
  if (document.getElementById('edit_prov_flete')) document.getElementById('edit_prov_flete').value = costoFlete || '0';

  if (modal) modal.style.display = 'flex';
}

function cerrarModalEditarProveedor() {
  const modal = document.getElementById('modalEditarProveedor');
  if (modal) modal.style.display = 'none';
}

function abrirModalEliminarProveedor(pk, nombre) {
  const modal = document.getElementById('modalEliminarProveedor');
  const form = document.getElementById('formEliminarProveedor');

  if (form) form.action = `/panel-admin/proveedores/eliminar/${pk}/`;

  const texto = document.getElementById('eliminar_prov_texto');
  if (texto) texto.textContent = nombre;

  if (modal) modal.style.display = 'flex';
}

function cerrarModalEliminarProveedor() {
  const modal = document.getElementById('modalEliminarProveedor');
  if (modal) modal.style.display = 'none';
}

// Función para dar formato al RUT (Ej: 761234567 -> 76.123.456-7)
function formatearRut(rutRaw) {
  // 1. Elimina cualquier carácter que no sea número ni 'K'/'k'
  let limpio = rutRaw.replace(/[^0-9kK]/g, '').toUpperCase();
  
  if (limpio.length <= 1) return limpio;

  // 2. Separa el cuerpo del dígito verificador
  let cuerpo = limpio.slice(0, -1);
  let dv = limpio.slice(-1);

  // 3. Agrega puntos de miles al cuerpo
  cuerpo = cuerpo.replace(/\B(?=(\d{3})+(?!\d))/g, ".");

  return `${cuerpo}-${dv}`;
}

// Aplicar evento 'input' a los campos de RUT de los modales
document.addEventListener('DOMContentLoaded', function() {
  const inputsRut = document.querySelectorAll('.input-rut');
  
  inputsRut.forEach(input => {
    input.addEventListener('input', function(e) {
      e.target.value = formatearRut(e.target.value);
    });
  });
});

// Formateo de teléfono chileno (Ej: 912345678 -> +56 9 1234 5678)
function formatearTelefono(val) {
  // Limpiar todo lo que no sea número
  let digitos = val.replace(/\D/g, '');
  
  // Si empieza con 56, se lo quitamos para no duplicar
  if (digitos.startsWith('56')) {
    digitos = digitos.slice(2);
  }
  
  // Limitamos a 9 dígitos (formato estándar móvil chileno)
  digitos = digitos.slice(0, 9);

  if (digitos.length === 0) return '';
  if (digitos.length <= 1) return `+56 ${digitos}`;
  if (digitos.length <= 5) return `+56 ${digitos.slice(0, 1)} ${digitos.slice(1)}`;
  
  return `+56 ${digitos.slice(0, 1)} ${digitos.slice(1, 5)} ${digitos.slice(5)}`;
}

// Evento para inputs de teléfono
document.addEventListener('DOMContentLoaded', function() {
  const inputsTel = document.querySelectorAll('.input-telefono');
  
  inputsTel.forEach(input => {
    input.addEventListener('input', function(e) {
      e.target.value = formatearTelefono(e.target.value);
    });
  });
});

// Formateo de precios en CLP (Ej: 15000 -> $ 15.000)
function formatearPrecio(val) {
  let limpio = val.replace(/\D/g, ''); // Solo números
  if (!limpio) return '';
  
  // Formatear con puntos de miles
  let formatoMiles = parseInt(limpio, 10).toLocaleString('es-CL');
  return `$ ${formatoMiles}`;
}

// Evento para inputs de precio
document.addEventListener('DOMContentLoaded', function() {
  const inputsPrecio = document.querySelectorAll('.input-precio');
  
  inputsPrecio.forEach(input => {
    input.addEventListener('input', function(e) {
      e.target.value = formatearPrecio(e.target.value);
    });
  });
});

// ==========================================
// 5. CONTROL DE DISPONIBILIDAD Y TURNOS
// ==========================================

// Escuchador global de cambios en radios "disponibilidad"
document.addEventListener('change', function (evento) {
  const radio = evento.target;
  if (radio.name !== 'disponibilidad') return;

  const contenedor = radio.closest('[data-disponibilidad]') || radio.closest('.modal') || document;
  if (!contenedor) return;

  const bloqueHorario = contenedor.querySelector('[data-horario]');
  const bloqueVarios = contenedor.querySelector('[data-varios]');

  if (radio.value === 'horario') {
    if (bloqueHorario) bloqueHorario.hidden = false;
    if (bloqueVarios) bloqueVarios.hidden = true;
  } else if (radio.value === 'todo_el_dia') {
    if (bloqueHorario) bloqueHorario.hidden = true;
    if (bloqueVarios) bloqueVarios.hidden = true;
  } else if (radio.value === 'mantener') {
    if (bloqueHorario) bloqueHorario.hidden = true;
    if (bloqueVarios) bloqueVarios.hidden = false;
  }
});

/**
 * Rellena o resetea los campos de disponibilidad en un modal/contenedor
 */
function cargarDisponibilidad(contenedorElemento, datosDisponibilidad) {
  let contenedor = typeof contenedorElemento === 'string'
    ? document.getElementById(contenedorElemento)
    : contenedorElemento;

  if (!contenedor) {
    contenedor = document.getElementById('modalEditarProducto') || document;
  }

  let datos = datosDisponibilidad;
  if (typeof datos === 'string' && datos.trim() !== '') {
    try {
      datos = JSON.parse(datos);
    } catch (e) {
      console.error("Error al parsear disponibilidad:", e);
      datos = null;
    }
  }

  const radioTodoElDia = contenedor.querySelector('input[name="disponibilidad"][value="todo_el_dia"]');
  const radioHorario = contenedor.querySelector('input[name="disponibilidad"][value="horario"]');
  const radioMantener = contenedor.querySelector('input[name="disponibilidad"][value="mantener"]');

  const bloqueHorario = contenedor.querySelector('[data-horario]');
  const bloqueVarios = contenedor.querySelector('[data-varios]');

  const inputNombre = contenedor.querySelector('[name="turno_nombre"]');
  const inputDesde = contenedor.querySelector('[name="turno_desde"]');
  const inputHasta = contenedor.querySelector('[name="turno_hasta"]');
  const checkboxesDias = contenedor.querySelectorAll('[name="turno_dias"]');

  // Resetear checkboxes de días
  checkboxesDias.forEach(chk => { chk.checked = false; });

  if (!datos) {
    // Caso 1: Todo el día
    if (radioTodoElDia) radioTodoElDia.checked = true;
    if (bloqueHorario) bloqueHorario.hidden = true;
    if (bloqueVarios) bloqueVarios.hidden = true;

    if (inputNombre) inputNombre.value = '';
    if (inputDesde) inputDesde.value = '';
    if (inputHasta) inputHasta.value = '';

  } else if (datos.varios) {
    // Caso 2: Varios turnos asociados
    if (radioMantener) radioMantener.checked = true;
    if (bloqueHorario) bloqueHorario.hidden = true;
    if (bloqueVarios) bloqueVarios.hidden = false;

  } else {
    // Caso 3: Horario único
    if (radioHorario) radioHorario.checked = true;
    if (bloqueHorario) bloqueHorario.hidden = false;
    if (bloqueVarios) bloqueVarios.hidden = true;

    if (inputNombre) inputNombre.value = datos.nombre || '';
    if (inputDesde) inputDesde.value = datos.desde || '';
    if (inputHasta) inputHasta.value = datos.hasta || '';

    if (Array.isArray(datos.dias)) {
      checkboxesDias.forEach(chk => {
        chk.checked = datos.dias.includes(parseInt(chk.value, 10));
      });
    }
  }
}