let TARIFAS = {};

function formatearMonto(monto) {
  return '$' + Math.round(monto).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

function actualizarDatosProveedor() {
  const provSelect = document.getElementById('id_proveedor');
  if (!provSelect) return;

  const opt = provSelect.options[provSelect.selectedIndex];
  if (!opt || !opt.value) return;

  if (opt.dataset.email) {
    document.getElementById('id_contacto_email').value = opt.dataset.email;
  }
  if (opt.dataset.telefono) {
    document.getElementById('id_contacto_telefono').value = opt.dataset.telefono;
  }
  if (opt.dataset.flete) {
    document.getElementById('id_costo_flete').value = Math.round(parseFloat(opt.dataset.flete));
  }

  // Actualizar precios de insumos según tarifas del proveedor
  const filas = document.querySelectorAll('.fila-insumo');
  filas.forEach(fila => {
    const selectInsumo = fila.querySelector('select[name="insumo_id[]"]');
    actualizarPrecioFila(selectInsumo);
  });

  calcularTotales();
}

function actualizarPrecioFila(selectElem) {
  const fila = selectElem.closest('.fila-insumo');
  const optInsumo = selectElem.options[selectElem.selectedIndex];
  const lblEnvase = fila.querySelector('.etiqueta-envase-fila');
  const lblUnidad = fila.querySelector('.etiqueta-unidad-fila');

  if (!optInsumo || !optInsumo.value) {
    if (lblEnvase) lblEnvase.textContent = 'env.';
    if (lblUnidad) lblUnidad.textContent = 'kg';
    return;
  }

  const insumoId = optInsumo.value;
  const kilos = optInsumo.dataset.kilos || 25;
  fila.querySelector('input[name="kilos_por_saco[]"]').value = kilos;

  if (lblEnvase) lblEnvase.textContent = (optInsumo.dataset.envase || 'envase') + '(s)';
  if (lblUnidad) lblUnidad.textContent = optInsumo.dataset.unidad || 'kg';

  const provId = document.getElementById('id_proveedor').value;
  let precio = optInsumo.dataset.precio || 0;

  // Si existe una tarifa específica cotizada con ese proveedor, usarla
  if (provId && TARIFAS[provId + '_' + insumoId]) {
    precio = TARIFAS[provId + '_' + insumoId];
  }

  fila.querySelector('input[name="precio_unitario[]"]').value = Math.round(parseFloat(precio));
  calcularTotales();
}

function calcularTotales() {
  let subtotal = 0;
  const filas = document.querySelectorAll('.fila-insumo');

  filas.forEach(fila => {
    const cant = parseFloat(fila.querySelector('input[name="cantidad_sacos[]"]').value) || 0;
    const precio = parseFloat(fila.querySelector('input[name="precio_unitario[]"]').value) || 0;
    const sub = cant * precio;
    subtotal += sub;
    fila.querySelector('.subtotal-fila').textContent = formatearMonto(sub);
  });

  const flete = parseFloat(document.getElementById('id_costo_flete').value) || 0;
  const total = subtotal + flete;

  document.getElementById('displaySubtotal').textContent = formatearMonto(subtotal);
  document.getElementById('displayTotal').textContent = formatearMonto(total);
}

function agregarFilaInsumo() {
  const cuerpo = document.getElementById('cuerpoTablaItems');
  const primeraFila = cuerpo.querySelector('.fila-insumo');
  const nuevaFila = primeraFila.cloneNode(true);

  // Resetear valores en la nueva fila
  nuevaFila.querySelector('select').selectedIndex = 0;
  nuevaFila.querySelector('input[name="cantidad_sacos[]"]').value = 5;
  nuevaFila.querySelector('input[name="kilos_por_saco[]"]').value = 25.0;
  nuevaFila.querySelector('input[name="precio_unitario[]"]').value = 0;
  nuevaFila.querySelector('.subtotal-fila').textContent = '$0';

  const lblEnvase = nuevaFila.querySelector('.etiqueta-envase-fila');
  const lblUnidad = nuevaFila.querySelector('.etiqueta-unidad-fila');
  if (lblEnvase) lblEnvase.textContent = 'env.';
  if (lblUnidad) lblUnidad.textContent = 'kg';

  cuerpo.appendChild(nuevaFila);
}

function eliminarFila(btn) {
  const filas = document.querySelectorAll('.fila-insumo');
  if (filas.length > 1) {
    btn.closest('.fila-insumo').remove();
    calcularTotales();
  } else {
    alert('La orden de compra debe contener al menos una materia prima.');
  }
}

document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('formOrdenCompra');
  if (form && form.dataset.tarifas) {
    try {
      TARIFAS = JSON.parse(form.dataset.tarifas);
    } catch (e) {
      console.error('Error al leer tarifas JSON:', e);
      TARIFAS = {};
    }
  }

  actualizarDatosProveedor();
  calcularTotales();
});