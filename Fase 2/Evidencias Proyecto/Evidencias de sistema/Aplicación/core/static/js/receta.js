(function () {
  var selectInsumo = document.getElementById('recetaInsumo');
  var sufijo = document.querySelector('[data-receta-unidad]');
  var inputCantidad = document.getElementById('recetaCantidad');
  if (!selectInsumo || !sufijo || !inputCantidad) { return; }

  var ejemplos = { 'g': 'Ej: 62', 'mL': 'Ej: 15', 'un.': 'Ej: 0,5' };

  function actualizarUnidad() {
    var opcion = selectInsumo.options[selectInsumo.selectedIndex];
    var unidad = (opcion && opcion.getAttribute('data-unidad')) || 'g';
    sufijo.textContent = unidad;
    inputCantidad.placeholder = ejemplos[unidad] || '';
  }

  selectInsumo.addEventListener('change', actualizarUnidad);
  actualizarUnidad();
})();
