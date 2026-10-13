// ==========================================
// 1. CAMBIO DE PESTAÑAS (INSUMOS VS PRODUCTOS)
// ==========================================
function cambiarPestanaCrud(pestana) {
  const panelInsumos = document.getElementById('panelInsumos');
  const panelProductos = document.getElementById('panelProductos');
  const tabBtnInsumos = document.getElementById('tabBtnInsumos');
  const tabBtnProductos = document.getElementById('tabBtnProductos');
  const btnAccionAgregarInsumo = document.getElementById('btnAccionAgregarInsumo');
  const btnAccionAgregarProducto = document.getElementById('btnAccionAgregarProducto');
  const crudTituloPrincipal = document.getElementById('crudTituloPrincipal');

  if (pestana === 'insumos') {
    if (panelInsumos) panelInsumos.style.display = 'block';
    if (panelProductos) panelProductos.style.display = 'none';

    if (tabBtnInsumos) tabBtnInsumos.classList.add('activa');
    if (tabBtnProductos) tabBtnProductos.classList.remove('activa');

    if (btnAccionAgregarInsumo) btnAccionAgregarInsumo.style.display = 'inline-block';
    if (btnAccionAgregarProducto) btnAccionAgregarProducto.style.display = 'none';

    if (crudTituloPrincipal) crudTituloPrincipal.textContent = 'Gestión de insumos y materias primas';
  } else if (pestana === 'productos') {
    if (panelInsumos) panelInsumos.style.display = 'none';
    if (panelProductos) panelProductos.style.display = 'block';

    if (tabBtnInsumos) tabBtnInsumos.classList.remove('activa');
    if (tabBtnProductos) tabBtnProductos.classList.add('activa');

    if (btnAccionAgregarInsumo) btnAccionAgregarInsumo.style.display = 'none';
    if (btnAccionAgregarProducto) btnAccionAgregarProducto.style.display = 'inline-block';

    if (crudTituloPrincipal) crudTituloPrincipal.textContent = 'Gestión de productos de la panadería';
  }
}

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
  if (form) form.action = `/panel-admin/insumos/editar/${pk}/`;

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
  if (form) form.action = `/panel-admin/insumos/eliminar/${pk}/`;

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
  if (modal) modal.style.display = 'flex';
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
    cargarDisponibilidad(document.getElementById('edit_prod_disponibilidad'), dispObj);
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