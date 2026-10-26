document.addEventListener('DOMContentLoaded', () => {
  // 1. Verificar si viene un insumo especificado en los parámetros URL (?insumo_id=X)
  const urlParams = new URLSearchParams(window.location.search);
  const insumoParam = urlParams.get('insumo_id');

  if (insumoParam) {
    const selectorInsumo = document.getElementById('filtroMateriaPrima');
    if (selectorInsumo) {
      selectorInsumo.value = insumoParam;
    }
  }

  // 2. Ejecutar filtro inicial
  aplicarFiltrosYOrden();
});

function aplicarFiltrosYOrden() {
  const idInsumoSel = document.getElementById('filtroMateriaPrima').value;
  const idProveedorSel = document.getElementById('filtroProveedor').value;
  const ordenSel = document.getElementById('ordenPrecio').value;

  const tbody = document.getElementById('tbodyHistorial');
  const filas = Array.from(tbody.querySelectorAll('tr[data-insumo-id]'));
  let filasVisibles = 0;

  // A. Filtrado
  filas.forEach(fila => {
    const insumoId = fila.getAttribute('data-insumo-id');
    const proveedorId = fila.getAttribute('data-proveedor-id');

    const coincideInsumo = !idInsumoSel || insumoId === idInsumoSel;
    const coincideProveedor = !idProveedorSel || proveedorId === idProveedorSel;

    if (coincideInsumo && coincideProveedor) {
      fila.style.display = '';
      filasVisibles++;
    } else {
      fila.style.display = 'none';
    }
  });

  // Mostrar / Ocultar mensaje de sin resultados
  const trSinRes = document.getElementById('trSinResultados');
  if (trSinRes) {
    trSinRes.style.display = filasVisibles === 0 ? '' : 'none';
  }

  // B. Ordenamiento de las filas visibles
  const filasFiltradas = filas.filter(f => f.style.display !== 'none');

  filasFiltradas.sort((a, b) => {
    const precioA = parseFloat(a.getAttribute('data-precio')) || 0;
    const precioB = parseFloat(b.getAttribute('data-precio')) || 0;
    const fechaA = new Date(a.getAttribute('data-fecha'));
    const fechaB = new Date(b.getAttribute('data-fecha'));

    if (ordenSel === 'precio_asc') {
      return precioA - precioB; // Menor a Mayor
    } else if (ordenSel === 'precio_desc') {
      return precioB - precioA; // Mayor a Menor
    } else {
      return fechaB - fechaA; // Por defecto: Más recientes primero
    }
  });

  // Reordenar en el DOM
  filasFiltradas.forEach(fila => tbody.appendChild(fila));
}

function limpiarFiltros() {
  document.getElementById('filtroMateriaPrima').value = '';
  document.getElementById('filtroProveedor').value = '';
  document.getElementById('ordenPrecio').value = 'fecha_desc';
  
  // Limpiar URL sin recargar la página
  window.history.replaceState({}, document.title, window.location.pathname);
  
  aplicarFiltrosYOrden();
}