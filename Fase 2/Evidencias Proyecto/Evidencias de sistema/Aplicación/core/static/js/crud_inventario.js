// ==========================================
// 1. CAMBIO DE PESTAÑAS (3 PESTAÑAS)
// ==========================================
function cambiarPestanaCrud(pestana) {
  sessionStorage.setItem('inventario_tab_activa', pestana);
  document.documentElement.dataset.inventarioTab = pestana;

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

// Sincronizar estado inicial calculado por inventario_tab_init.js
document.addEventListener('DOMContentLoaded', function() {
  const tabInicial = document.documentElement.dataset.inventarioTab || 'insumos';
  cambiarPestanaCrud(tabInicial);
});

// ==========================================
// 2. MODALES DE INSUMOS
// ==========================================
function abrirModalAgregarInsumo() {
  const modal = document.getElementById('modalAgregarInsumo');
  if (modal) {
    modal.style.display = 'flex';
    actualizarResumenInsumo(document.getElementById('formAgregarInsumo'));
  }
}

function cerrarModalAgregarInsumo() {
  const modal = document.getElementById('modalAgregarInsumo');
  if (modal) modal.style.display = 'none';
}

function seleccionarProveedor(select, nombre) {
  if (!select) return;
  Array.from(select.options).filter(o => o.value === '__mantener__').forEach(o => o.remove());
  const buscado = (nombre || '').trim().toLowerCase();
  if (!buscado) {
    select.value = '';
    return;
  }

  const opcion = Array.from(select.options).find(
    o => o.value && o.text.trim().toLowerCase() === buscado
  );

  if (opcion) {
    select.value = opcion.value;
  } else {
    // Si el proveedor actual del insumo fue inactivado o no está en el select, lo mostramos igual para no perderlo al guardar
    const optActual = new Option(`${nombre.trim()} (actual)`, '__mantener__');
    select.add(optActual);
    select.value = '__mantener__';
  }
}

function abrirModalEditarInsumo(pk, codigo, nombre, unidad, contenido, tipoEnvase, proveedorNombre, precioSaco, tipoInsumo) {
  const form = document.getElementById('formEditarInsumo');
  if (form) {
    form.action = `/panel-admin/inventario/editar/${pk}/`;
    form.querySelector('[data-insumo-unidad]').value = unidad || 'kg';
    form.querySelector('[data-insumo-contenido]').value = contenido || '';
  }

  if (document.getElementById('edit_insumo_codigo')) document.getElementById('edit_insumo_codigo').value = codigo || '';
  if (document.getElementById('edit_insumo_nombre')) document.getElementById('edit_insumo_nombre').value = nombre || '';
  if (document.getElementById('edit_insumo_envase')) document.getElementById('edit_insumo_envase').value = `${tipoEnvase || 'envase'} de ${formatearCantidad(contenido)} ${unidad}`;
  if (document.getElementById('edit_insumo_precio_saco')) document.getElementById('edit_insumo_precio_saco').value = formatearPrecio(String(precioSaco || ''));
  if (document.getElementById('edit_insumo_tipo')) document.getElementById('edit_insumo_tipo').value = tipoInsumo || 'otro';
  seleccionarProveedor(document.getElementById('edit_insumo_proveedor'), proveedorNombre);

  actualizarResumenInsumo(form);

  const modal = document.getElementById('modalEditarInsumo');
  if (modal) modal.style.display = 'flex';
}

// "+ Envase": solo se indica cuántos llegaron. El tipo, lo que trae cada uno, el precio y el proveedor
// son los del insumo (si cambiaron, se actualizan en "Editar"; otra presentación es otro insumo).
function abrirModalAgregarEnvase(pk, nombre, unidad, tipo, contenido, precio, proveedorNombre) {
  const form = document.getElementById('formAgregarEnvase');
  if (form) {
    form.action = `/panel-admin/inventario/${pk}/envase/`;
    form.querySelector('[data-insumo-unidad]').value = unidad || 'kg';
    form.querySelector('[data-insumo-contenido]').value = contenido || '';
    form.querySelector('[data-insumo-tipo]').value = tipo || 'envase';
  }
  const titulo = document.getElementById('envase_titulo');
  if (titulo) titulo.textContent = `Agregar envases de ${nombre}`;

  const presentacion = document.getElementById('envase_presentacion');
  if (presentacion) {
    const monto = Number(precio) > 0 ? ` a ${formatearPesos(Number(precio))}` : '';
    const deProveedor = proveedorNombre ? `, de ${proveedorNombre}` : '';
    presentacion.textContent = `Cada uno: ${tipo || 'envase'} de ${formatearCantidad(contenido)} ${unidad}${monto}${deProveedor}`;
  }
  if (document.getElementById('envase_cuantos')) document.getElementById('envase_cuantos').value = 1;

  actualizarResumenInsumo(form);

  const modal = document.getElementById('modalAgregarEnvase');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalAgregarEnvase() {
  const modal = document.getElementById('modalAgregarEnvase');
  if (modal) modal.style.display = 'none';
}

// Formularios de insumo (agregar, editar y "+ Envase"): la unidad va pegada a la cantidad del envase,
// el precio estimado por unidad se calcula solo ($36.990 / 180 = $205,50 por un.) y debajo se resume
// qué queda en stock. En "un." la cantidad va entera (no hay medio huevo).
function formatearCantidad(numero) {
  return Number(numero).toLocaleString('es-CL', { maximumFractionDigits: 2 });
}

function formatearPesos(monto) {
  const decimales = Number.isInteger(monto) ? 0 : 2;
  return '$' + monto.toLocaleString('es-CL', { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
}

function actualizarResumenInsumo(form) {
  if (!form) return;
  const campoUnidad = form.querySelector('[data-insumo-unidad]');
  const inputContenido = form.querySelector('[data-insumo-contenido]');
  if (!campoUnidad || !inputContenido) return;
  const inputTipo = form.querySelector('[data-insumo-tipo]');
  const inputCuantos = form.querySelector('[data-insumo-cuantos]');
  const inputPrecio = form.querySelector('[data-insumo-precio]');
  const precioUnidad = form.querySelector('[data-insumo-precio-unidad]');
  const resumen = form.querySelector('[data-insumo-resumen]');

  const unidad = campoUnidad.value;
  const enteras = unidad === 'un.';
  form.querySelectorAll('[data-insumo-sufijo]').forEach(sufijo => { sufijo.textContent = unidad; });
  if (inputContenido.type === 'number') {
    inputContenido.step = enteras ? '1' : '0.01';
    inputContenido.min = enteras ? '1' : '0.01';
  }

  const contenido = parseFloat(inputContenido.value);
  const precio = parseInt((inputPrecio ? inputPrecio.value : '').replace(/\D/g, ''), 10);
  if (precioUnidad) {
    precioUnidad.value = contenido > 0 && precio > 0
      ? `${formatearPesos(Math.round(precio / contenido * 100) / 100)} por ${unidad}`
      : '';
  }
  if (!resumen) return;
  if (!(contenido > 0)) {
    resumen.textContent = '';
    return;
  }

  const tipo = (inputTipo && inputTipo.value.trim()) || 'envase';
  const envase = `${tipo} de ${formatearCantidad(contenido)} ${unidad}`;
  if (form.dataset.insumoModo === 'envase') {
    const cuantos = parseInt(inputCuantos ? inputCuantos.value : '1', 10) || 0;
    resumen.textContent = cuantos > 0
      ? `Se suman ${cuantos} × ${envase} = ${formatearCantidad(cuantos * contenido)} ${unidad}.`.replace(/\.\.$/, '.')
      : '';
  } else {
    resumen.textContent = `El insumo queda con 1 ${envase} en stock. Cuando lleguen más, usa "+ Envase" en la tabla.`;
  }
}

['input', 'change'].forEach(tipo => {
  document.addEventListener(tipo, function (evento) {
    const form = evento.target.closest ? evento.target.closest('.insumo-form') : null;
    if (form) actualizarResumenInsumo(form);
  });
});

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

function _actualizarVistaPreviaImagenEditar(url, nombreArchivo = '') {
  const wrap = document.getElementById('edit_prod_imagen_preview_wrap');
  const img = document.getElementById('edit_prod_imagen_preview');
  const labelNombre = document.getElementById('edit_prod_imagen_nombre');
  const sinFoto = document.getElementById('edit_prod_imagen_sin_foto');
  if (!wrap || !img) return;

  const valor = (url || '').trim();
  if (valor) {
    img.src = valor;
    if (labelNombre) labelNombre.textContent = nombreArchivo || valor;
    wrap.style.display = 'flex';
    if (sinFoto) sinFoto.style.display = 'none';
  } else {
    img.removeAttribute('src');
    if (labelNombre) labelNombre.textContent = '';
    wrap.style.display = 'none';
    if (sinFoto) sinFoto.style.display = 'block';
  }
}

function quitarImagenEditarProducto() {
  const inputUrl = document.getElementById('edit_prod_imagen');
  const inputFile = document.getElementById('edit_prod_imagen_archivo');
  if (inputUrl) inputUrl.value = '';
  if (inputFile) inputFile.value = '';
  _actualizarVistaPreviaImagenEditar('');
}

function abrirModalAgregarProducto() {
  const modal = document.getElementById('modalAgregarProducto');
  if (modal) {
    // Limpia todo el formulario (incluyendo el archivo seleccionado) antes de abrir
    const form = modal.querySelector('form');
    if (form) form.reset();

    // Sincroniza el estado del botón eliminar categoría (deshabilitado porque está vacío)
    actualizarEstadoBtnEliminarCat('prod_categoria', 'btnEliminarCatProd');

    modal.style.display = 'flex';
    if (typeof cargarDisponibilidad === 'function') {
      cargarDisponibilidad(modal, null);
    }
  }
}

function cerrarModalAgregarProducto() {
  const modal = document.getElementById('modalAgregarProducto');
  if (modal) {
    const inputArchivo = modal.querySelector('input[type="file"]');
    if (inputArchivo) inputArchivo.value = '';
    modal.style.display = 'none';
  }
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
  const imagenUrl = btn.dataset.imagen;
  const disponibilidadRaw = btn.dataset.disponibilidad;

  const form = document.getElementById('formEditarProducto');
  if (form) form.action = `/panel-admin/productos/editar/${pk}/`;

  if (document.getElementById('edit_prod_nombre')) document.getElementById('edit_prod_nombre').value = nombre || '';
  if (document.getElementById('edit_prod_categoria')) {
    document.getElementById('edit_prod_categoria').value = categoriaId || '';
    actualizarEstadoBtnEliminarCat('edit_prod_categoria', 'btnEliminarCatEditProd');
  }
  if (document.getElementById('edit_prod_precio')) {
    document.getElementById('edit_prod_precio').value = formatearPrecio(String(precio || '0')) || '$ 0';
  }
  if (document.getElementById('edit_prod_stock')) document.getElementById('edit_prod_stock').value = stock || 0;
  const accionStock = document.getElementById('edit_prod_stock_accion');
  if (accionStock) {
    const esHorno = btn.dataset.esHorno === 'true';
    accionStock.textContent = esHorno ? '+ Horneada' : '+ Stock';
  }
  if (document.getElementById('edit_prod_stock_critico')) document.getElementById('edit_prod_stock_critico').value = stockCritico || 10;
  if (document.getElementById('edit_prod_unidad')) document.getElementById('edit_prod_unidad').value = unidad || 'unid';
  if (document.getElementById('edit_prod_desc')) document.getElementById('edit_prod_desc').value = desc || '';
  if (document.getElementById('edit_prod_imagen')) document.getElementById('edit_prod_imagen').value = imagenUrl || '';

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
  if (modal) {
    // Limpia cualquier archivo residual que haya quedado seleccionado antes
    const inputArchivo = modal.querySelector('input[type="file"]');
    if (inputArchivo) inputArchivo.value = '';

    _actualizarVistaPreviaImagenEditar(imagenUrl || '');

    modal.style.display = 'flex';
  }
}

function cerrarModalEditarProducto() {
  const modal = document.getElementById('modalEditarProducto');
  if (modal) {
    const inputArchivo = modal.querySelector('input[type="file"]');
    if (inputArchivo) inputArchivo.value = '';
    modal.style.display = 'none';
  }
}

document.addEventListener('DOMContentLoaded', function () {
  const inputFileEdit = document.getElementById('edit_prod_imagen_archivo');
  const inputUrlEdit = document.getElementById('edit_prod_imagen');

  if (inputFileEdit) {
    inputFileEdit.addEventListener('change', function () {
      const archivo = inputFileEdit.files && inputFileEdit.files[0];
      if (!archivo) {
        _actualizarVistaPreviaImagenEditar(inputUrlEdit ? inputUrlEdit.value : '');
        return;
      }
      const lector = new FileReader();
      lector.onload = function (ev) {
        _actualizarVistaPreviaImagenEditar(ev.target.result, archivo.name);
      };
      lector.readAsDataURL(archivo);
    });
  }

  if (inputUrlEdit) {
    inputUrlEdit.addEventListener('input', function () {
      if (!inputFileEdit || !inputFileEdit.files || inputFileEdit.files.length === 0) {
        _actualizarVistaPreviaImagenEditar(inputUrlEdit.value);
      }
    });
  }
});

function abrirModalRegistrarProduccion(pk, nombre, esHorno = true) {
  const form = document.getElementById('formRegistrarProduccion');
  if (form) form.action = `/panel-admin/productos/produccion/${pk}/`;

  const txt = document.getElementById('produccion_producto_nombre');
  if (txt) txt.textContent = `Producto: ${nombre}`;

  const titulo = document.getElementById('produccion_modal_titulo');
  const label = document.getElementById('produccion_label_cantidad');
  const ayuda = document.getElementById('produccion_ayuda_texto');
  const btnSubmit = document.getElementById('produccion_btn_submit');

  if (esHorno) {
    if (titulo) titulo.textContent = 'Registrar Producción Diaria (Horneada)';
    if (label) label.textContent = 'Cantidad Horneada / Producida hoy:';
    if (ayuda) ayuda.textContent = 'Esta cantidad se sumará al stock del producto y quedará guardada en el registro diario con la fecha y tu usuario. Si el producto tiene receta, se descuentan sus insumos (primero del envase en uso).';
    if (btnSubmit) {
      btnSubmit.textContent = '+ Registrar Horneada';
      btnSubmit.style.backgroundColor = '#7b4b2a';
    }
  } else {
    if (titulo) titulo.textContent = 'Registrar Ingreso de Stock';
    if (label) label.textContent = 'Cantidad a ingresar al stock:';
    if (ayuda) ayuda.textContent = 'Esta cantidad se sumará al stock disponible del producto y quedará registrada con la fecha y tu usuario.';
    if (btnSubmit) {
      btnSubmit.textContent = '+ Agregar Stock';
      btnSubmit.style.backgroundColor = '#7b4b2a';
    }
  }

  const modal = document.getElementById('modalRegistrarProduccion');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalRegistrarProduccion() {
  const modal = document.getElementById('modalRegistrarProduccion');
  if (modal) modal.style.display = 'none';
}

function abrirModalInactivarProducto(pk, nombre) {
  const form = document.getElementById('formInactivarProducto');
  if (form) form.action = `/panel-admin/productos/inactivar/${pk}/`;

  const txt = document.getElementById('inactivar_prod_texto');
  if (txt) txt.textContent = nombre;

  const modal = document.getElementById('modalInactivarProducto');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalInactivarProducto() {
  const modal = document.getElementById('modalInactivarProducto');
  if (modal) modal.style.display = 'none';
}

function abrirModalActivarProducto(pk, nombre) {
  const form = document.getElementById('formActivarProducto');
  if (form) form.action = `/panel-admin/productos/activar/${pk}/`;

  const txt = document.getElementById('activar_prod_texto');
  if (txt) txt.textContent = nombre;

  const modal = document.getElementById('modalActivarProducto');
  if (modal) modal.style.display = 'flex';
}

function cerrarModalActivarProducto() {
  const modal = document.getElementById('modalActivarProducto');
  if (modal) modal.style.display = 'none';
}

// Variable para recordar qué modal padre estaba abierto antes de abrir un modal secundario
let modalPadreTemporal = null;

function _ocultarModalPadreActivo() {
  const padres = [
    'modalAgregarProducto',
    'modalEditarProducto',
    'modalAgregarInsumo',
    'modalEditarInsumo'
  ];
  for (const id of padres) {
    const el = document.getElementById(id);
    if (el && el.style.display === 'flex') {
      el.style.display = 'none';
      modalPadreTemporal = el;
      return;
    }
  }
  modalPadreTemporal = null;
}

function _restaurarModalPadreActivo() {
  if (modalPadreTemporal) {
    modalPadreTemporal.style.display = 'flex';
    modalPadreTemporal = null;
  }
}

// Modales de Categoría Rápida
function abrirModalAgregarCategoria() {
  _ocultarModalPadreActivo();
  const modal = document.getElementById('modalAgregarCategoria');
  if (modal) {
    const form = modal.querySelector('form');
    if (form) form.reset();
    modal.style.display = 'flex';
  }
}

function cerrarModalAgregarCategoria() {
  const modal = document.getElementById('modalAgregarCategoria');
  if (modal) modal.style.display = 'none';
  _restaurarModalPadreActivo();
}

function actualizarEstadoBtnEliminarCat(selectId, btnId) {
  const select = document.getElementById(selectId);
  const btn = document.getElementById(btnId);
  if (select && btn) {
    btn.disabled = !select.value;
  }
}

async function eliminarCategoriaSeleccionada(selectId) {
  const select = document.getElementById(selectId);
  if (!select || !select.value) return;

  const categoriaId = select.value;
  const categoriaNombre = select.options[select.selectedIndex].text.trim();

  const confirmado = await confirmarAccionCrud({
    titulo: 'Eliminar categoría',
    mensaje: `¿Estás seguro de eliminar la categoría "${categoriaNombre}"?`,
    nota: 'Solo se eliminará si no tiene productos asociados en el catálogo.',
    textoAceptar: 'Sí, eliminar'
  });
  if (!confirmado) return;

  const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
  const csrfToken = csrfInput ? csrfInput.value : '';

  try {
    const resp = await fetch(`/panel-admin/categorias/eliminar/${categoriaId}/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken,
        'X-Requested-With': 'XMLHttpRequest'
      }
    });
    const data = await resp.json();

    if (resp.ok && data.ok) {
      ['prod_categoria', 'edit_prod_categoria'].forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        const opt = Array.from(sel.options).find(o => String(o.value) === String(categoriaId));
        if (opt) opt.remove();
        if (sel.value === String(categoriaId)) sel.value = '';
      });

      actualizarEstadoBtnEliminarCat('prod_categoria', 'btnEliminarCatProd');
      actualizarEstadoBtnEliminarCat('edit_prod_categoria', 'btnEliminarCatEditProd');

      if (typeof mostrarToast === 'function') {
        mostrarToast(`Categoría "${categoriaNombre}" eliminada correctamente.`, 'success');
      }
    } else {
      const msg = data.error || 'No se pudo eliminar la categoría.';
      if (typeof mostrarToast === 'function') mostrarToast(msg, 'error');
    }
  } catch (err) {
    console.error('Error al eliminar categoría:', err);
    if (typeof mostrarToast === 'function') {
      mostrarToast('Error de conexión al intentar eliminar la categoría.', 'error');
    }
  }
}

// Helper de confirmación artesanal (reemplaza window.confirm)
function confirmarAccionCrud({ titulo, mensaje, nota = '', textoAceptar = 'Confirmar' }) {
  const dialog = document.getElementById('modalConfirmacionCrud');
  if (!dialog || typeof dialog.showModal !== 'function') {
    return Promise.resolve(window.confirm(`${mensaje}\n${nota}`));
  }

  document.getElementById('confirmCrudTitulo').textContent = titulo;
  document.getElementById('confirmCrudMensaje').textContent = mensaje;
  document.getElementById('confirmCrudNota').textContent = nota;
  const btnAceptar = document.getElementById('confirmCrudAceptar');
  const btnCancelar = document.getElementById('confirmCrudCancelar');
  btnAceptar.textContent = textoAceptar;

  return new Promise((resolve) => {
    const limpiar = (resultado) => {
      dialog.close();
      btnAceptar.removeEventListener('click', onAceptar);
      btnCancelar.removeEventListener('click', onCancelar);
      dialog.removeEventListener('cancel', onCancelar);
      resolve(resultado);
    };
    const onAceptar = () => limpiar(true);
    const onCancelar = () => limpiar(false);

    btnAceptar.addEventListener('click', onAceptar);
    btnCancelar.addEventListener('click', onCancelar);
    dialog.addEventListener('cancel', onCancelar);
    dialog.showModal();
  });
}

document.addEventListener('DOMContentLoaded', function () {
  const selectEditCat = document.getElementById('edit_prod_categoria');
  const accionStock = document.getElementById('edit_prod_stock_accion');
  if (!selectEditCat || !accionStock) return;

  const categoriasHorno = ['salados', 'pastelería', 'pasteleria', 'panadería', 'panaderia', 'empanadas', 'dulces'];
  selectEditCat.addEventListener('change', function () {
    const textoCat = (selectEditCat.options[selectEditCat.selectedIndex]?.text || '').trim().toLowerCase();
    accionStock.textContent = categoriasHorno.includes(textoCat) ? '+ Horneada' : '+ Stock';
  });
});

// ==========================================
// GUARDADO RÁPIDO POR AJAX DESDE MODAL PADRE
// ==========================================
function _agregarOpcionYSeleccionar(selectIds, valor, texto) {
  selectIds.forEach(id => {
    const select = document.getElementById(id);
    if (!select) return;

    // Evita duplicar si ya existía
    let opcion = Array.from(select.options).find(o => String(o.value) === String(valor));
    if (!opcion) {
      opcion = new Option(texto, valor);
      select.add(opcion);
    }
    // Solo la selecciona en el modal padre que estaba activo
    if (modalPadreTemporal && modalPadreTemporal.contains(select)) {
      select.value = valor;
    }
  });
  actualizarEstadoBtnEliminarCat('prod_categoria', 'btnEliminarCatProd');
  actualizarEstadoBtnEliminarCat('edit_prod_categoria', 'btnEliminarCatEditProd');
}

document.addEventListener('DOMContentLoaded', function () {
  // 1. Interceptar envío de "Nueva Categoría" cuando viene desde Agregar/Editar Producto
  const formCategoria = document.querySelector('#modalAgregarCategoria form');
  if (formCategoria) {
    formCategoria.addEventListener('submit', async function (e) {
      if (!modalPadreTemporal) return; // Si no hay modal padre, envío normal
      e.preventDefault();

      const btnSubmit = formCategoria.querySelector('button[type="submit"]');
      if (btnSubmit) btnSubmit.disabled = true;

      try {
        const resp = await fetch(formCategoria.action, {
          method: 'POST',
          body: new FormData(formCategoria),
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const data = await resp.json();

        if (resp.ok && data.ok) {
          _agregarOpcionYSeleccionar(['prod_categoria', 'edit_prod_categoria'], data.id, data.nombre);
          cerrarModalAgregarCategoria();
          if (typeof mostrarToast === 'function') {
            const msg = data.creada === false
              ? `Categoría "${data.nombre}" seleccionada.`
              : `Categoría "${data.nombre}" creada y seleccionada.`;
            mostrarToast(msg, 'success');
          }
        } else {
          const errorMsg = data.error || 'No se pudo crear la categoría.';
          if (typeof mostrarToast === 'function') mostrarToast(errorMsg, 'error');
        }
      } catch (err) {
        console.error('Error al crear categoría:', err);
        if (typeof mostrarToast === 'function') {
          mostrarToast('Error de conexión al guardar la categoría.', 'error');
        }
      } finally {
        if (btnSubmit) btnSubmit.disabled = false;
      }
    });
  }

  // 2. Interceptar envío de "Nuevo Proveedor" solo cuando viene desde Agregar Insumo
  const formProveedor = document.querySelector('#modalAgregarProveedor form');
  if (formProveedor) {
    formProveedor.addEventListener('submit', async function (e) {
      if (!modalPadreTemporal) return; // Desde la pestaña Proveedores, recarga normal para ver la tabla
      e.preventDefault();

      const btnSubmit = formProveedor.querySelector('button[type="submit"]');
      if (btnSubmit) btnSubmit.disabled = true;

      try {
        const resp = await fetch(formProveedor.action, {
          method: 'POST',
          body: new FormData(formProveedor),
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const data = await resp.json();

        if (resp.ok && data.ok) {
          _agregarOpcionYSeleccionar(['insumo_proveedor', 'edit_insumo_proveedor'], data.id, data.nombre);
          _insertarProveedorEnTabla(data);
          cerrarModalAgregarProveedor();
          if (typeof mostrarToast === 'function') {
            mostrarToast(`Proveedor "${data.nombre}" registrado y seleccionado.`, 'success');
          }
        } else {
          const errorMsg = data.error || 'No se pudo registrar el proveedor.';
          if (typeof mostrarToast === 'function') mostrarToast(errorMsg, 'error');
        }
      } catch (err) {
        console.error('Error al crear proveedor:', err);
        if (typeof mostrarToast === 'function') {
          mostrarToast('Error de conexión al guardar el proveedor.', 'error');
        }
      } finally {
        if (btnSubmit) btnSubmit.disabled = false;
      }
    });
  }
});

// ==========================================
// 4. MODALES DE PROVEEDORES
// ==========================================

function _escapeHtml(valor) {
  return String(valor ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function _insertarProveedorEnTabla(data) {
  // 1. Actualizar contador en la pestaña "Proveedores (N)"
  const tabBtn = document.getElementById('tabBtnProveedores');
  if (tabBtn) {
    tabBtn.textContent = tabBtn.textContent.replace(/\((\d+)\)/, (_, n) => `(${parseInt(n, 10) + 1})`);
  }

  // 2. Insertar la fila en la tabla de proveedores
  const tbody = document.querySelector('#panelProveedores tbody');
  if (!tbody) return;

  // Eliminar fila de estado vacío ("No hay proveedores registrados...") si existía
  const filaVacia = tbody.querySelector('td[colspan]');
  if (filaVacia) filaVacia.closest('tr').remove();

  // Normalizar valores vacíos ('—' viene del backend cuando el campo es nulo/vacío)
  const rutLimpio = data.rut && data.rut !== '—' ? data.rut : '';
  const emailLimpio = data.email && data.email !== '—' ? data.email : '';
  const telLimpio = data.telefono && data.telefono !== '—' ? data.telefono : '';

  const rutTabla = rutLimpio || data.id;
  const emailTabla = emailLimpio || '-';
  const telTabla = telLimpio || '-';

  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td class="crud-col-id">${_escapeHtml(rutTabla)}</td>
    <td class="crud-col-nombre">
      <strong>${_escapeHtml(data.nombre)}</strong>
      ${data.direccion ? `<small style="display: block; color: var(--texto-suave); font-weight: normal; margin-top: 2px;">${_escapeHtml(data.direccion)}</small>` : ''}
    </td>
    <td class="crud-col-centro">
      <span class="crud-badge-cat">${_escapeHtml(data.tipo_proveedor_label || 'General / Varios')}</span>
    </td>
    <td class="crud-col-centro">${_escapeHtml(emailTabla)}</td>
    <td class="crud-col-centro">${_escapeHtml(telTabla)}</td>
    <td class="crud-col-precio">${_escapeHtml(data.costo_flete)}</td>
    <td class="crud-col-centro">
      <span class="crud-badge crud-badge--exito">Activo</span>
    </td>
    <td class="crud-col-acciones">
      <button type="button" class="crud-btn-accion crud-btn-editar"
              data-pk="${_escapeHtml(data.id)}"
              data-rut="${_escapeHtml(rutLimpio)}"
              data-nombre="${_escapeHtml(data.nombre)}"
              data-tipo="${_escapeHtml(data.tipo_proveedor || 'general')}"
              data-email="${_escapeHtml(emailLimpio)}"
              data-telefono="${_escapeHtml(telLimpio)}"
              data-direccion="${_escapeHtml(data.direccion || '')}"
              data-flete="${_escapeHtml(data.costo_flete_raw ?? 0)}"
              onclick="abrirModalEditarProveedorBtn(this)">
        Editar
      </button>
      <button type="button" class="crud-btn-accion crud-btn-eliminar"
              data-pk="${_escapeHtml(data.id)}"
              data-nombre="${_escapeHtml(data.nombre)}"
              onclick="abrirModalInactivarProveedorBtn(this)">
        Inactivar
      </button>
    </td>
  `;
  tbody.appendChild(tr);
}

function abrirModalAgregarProveedor() {
  _ocultarModalPadreActivo();
  const modal = document.getElementById('modalAgregarProveedor');
  if (modal) {
    const form = modal.querySelector('form');
    if (form) form.reset();
    modal.style.display = 'flex';
  }
}

function cerrarModalAgregarProveedor() {
  const modal = document.getElementById('modalAgregarProveedor');
  if (modal) modal.style.display = 'none';
  _restaurarModalPadreActivo();
}

function abrirModalEditarProveedorBtn(btn) {
  const { pk, rut, nombre, tipo, email, telefono, direccion, flete } = btn.dataset;
  abrirModalEditarProveedor(pk, rut, nombre, tipo, email, telefono, direccion, flete);
}

function abrirModalEditarProveedor(pk, rut, nombre, tipo, email, telefono, direccion, costoFlete) {
  const modal = document.getElementById('modalEditarProveedor');
  const form = document.getElementById('formEditarProveedor');
  if (!modal || !form) return;

  form.action = `/panel-admin/proveedores/editar/${pk}/`;

  const inputRut = document.getElementById('edit_prov_rut');
  const inputNombre = document.getElementById('edit_prov_nombre');
  const inputTipo = document.getElementById('edit_prov_tipo');
  const inputEmail = document.getElementById('edit_prov_email');
  const inputTelefono = document.getElementById('edit_prov_telefono');
  const inputDir = document.getElementById('edit_prov_dir');
  const inputFlete = document.getElementById('edit_prov_flete');

  if (inputRut) inputRut.value = formatearRut(rut || '');
  if (inputNombre) inputNombre.value = nombre || '';
  if (inputTipo) inputTipo.value = tipo || 'general';
  if (inputEmail) inputEmail.value = email || '';
  if (inputTelefono) inputTelefono.value = telefono ? formatearTelefono(telefono) : '';
  if (inputDir) inputDir.value = direccion || '';
  if (inputFlete) inputFlete.value = formatearPrecio(String(costoFlete || '0')) || '$ 0';

  modal.style.display = 'flex';
}

function cerrarModalEditarProveedor() {
  const modal = document.getElementById('modalEditarProveedor');
  if (modal) modal.style.display = 'none';
}

function abrirModalInactivarProveedorBtn(btn) {
  const { pk, nombre } = btn.dataset;
  const modal = document.getElementById('modalInactivarProveedor');
  const form = document.getElementById('formInactivarProveedor');
  if (!modal || !form) return;

  form.action = `/panel-admin/proveedores/inactivar/${pk}/`;
  const texto = document.getElementById('inactivar_prov_texto');
  if (texto) texto.textContent = nombre || '-';
  modal.style.display = 'flex';
}

function cerrarModalInactivarProveedor() {
  const modal = document.getElementById('modalInactivarProveedor');
  if (modal) modal.style.display = 'none';
}

function abrirModalActivarProveedorBtn(btn) {
  const { pk, nombre } = btn.dataset;
  const modal = document.getElementById('modalActivarProveedor');
  const form = document.getElementById('formActivarProveedor');
  if (!modal || !form) return;

  form.action = `/panel-admin/proveedores/activar/${pk}/`;
  const texto = document.getElementById('activar_prov_texto');
  if (texto) texto.textContent = nombre || '-';
  modal.style.display = 'flex';
}

function cerrarModalActivarProveedor() {
  const modal = document.getElementById('modalActivarProveedor');
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

// ==========================================
// 6. CIERRE ACCESIBLE CON ESCAPE Y CLIC EN FONDO
// ==========================================
const CIERRES_MODALES_CRUD = {
  modalAgregarCategoria: cerrarModalAgregarCategoria,
  modalAgregarProveedor: cerrarModalAgregarProveedor,
  modalAgregarInsumo: cerrarModalAgregarInsumo,
  modalEditarInsumo: cerrarModalEditarInsumo,
  modalAgregarEnvase: cerrarModalAgregarEnvase,
  modalEliminarInsumo: cerrarModalEliminarInsumo,
  modalAgregarProducto: cerrarModalAgregarProducto,
  modalEditarProducto: cerrarModalEditarProducto,
  modalRegistrarProduccion: cerrarModalRegistrarProduccion,
  modalInactivarProducto: cerrarModalInactivarProducto,
  modalActivarProducto: cerrarModalActivarProducto,
  modalEditarProveedor: cerrarModalEditarProveedor,
  modalInactivarProveedor: cerrarModalInactivarProveedor,
  modalActivarProveedor: cerrarModalActivarProveedor,
};

function _obtenerModalCrudAbierto() {
  for (const id of Object.keys(CIERRES_MODALES_CRUD)) {
    const el = document.getElementById(id);
    if (el && el.style.display === 'flex') {
      return { id, cerrar: CIERRES_MODALES_CRUD[id] };
    }
  }
  return null;
}

document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  const dialogConfirm = document.getElementById('modalConfirmacionCrud');
  if (dialogConfirm && dialogConfirm.open) return;

  const activo = _obtenerModalCrudAbierto();
  if (activo) {
    e.preventDefault();
    activo.cerrar();
  }
});

document.addEventListener('click', function (e) {
  if (!e.target.classList || !e.target.classList.contains('crud-modal-backdrop')) return;
  const cerrarFn = CIERRES_MODALES_CRUD[e.target.id];
  if (typeof cerrarFn === 'function') {
    cerrarFn();
  }
});

// ==========================================
// 7. VALIDACIÓN DE PRECIOS MAYORES A $ 0
// ==========================================
document.addEventListener('DOMContentLoaded', function () {
  const camposPrecioObligatorios = [
    { formId: 'formAgregarInsumo', inputId: 'insumo_precio_saco', mensaje: 'El precio total del envase debe ser mayor a $ 0.' },
    { formId: 'formEditarInsumo', inputId: 'edit_insumo_precio_saco', mensaje: 'El precio total del envase debe ser mayor a $ 0.' },
    { formId: 'formAgregarProducto', inputId: 'prod_precio', mensaje: 'El precio de venta debe ser mayor a $ 0.' },
    { formId: 'formEditarProducto', inputId: 'edit_prod_precio', mensaje: 'El precio de venta debe ser mayor a $ 0.' },
  ];

  camposPrecioObligatorios.forEach(({ formId, inputId, mensaje }) => {
    const form = document.getElementById(formId);
    const input = document.getElementById(inputId);
    if (!form || !input) return;

    input.addEventListener('input', function () {
      input.setCustomValidity('');
    });

    form.addEventListener('submit', function (e) {
      const monto = parseInt(input.value.replace(/\D/g, ''), 10) || 0;
      if (monto <= 0) {
        e.preventDefault();
        input.setCustomValidity(mensaje);
        input.reportValidity();
        input.focus();
      } else {
        input.setCustomValidity('');
      }
    });
  });
});