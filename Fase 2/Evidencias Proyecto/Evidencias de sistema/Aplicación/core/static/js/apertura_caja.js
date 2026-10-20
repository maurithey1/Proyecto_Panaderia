/* ==========================================
   APERTURA DE CAJA (POS)
   ==========================================
   Ayudas del formulario; las reglas reales se validan en el servidor (core/caja.py):
   - si el monto no coincide con el del turno anterior, la observación pasa a ser obligatoria;
   - antes de abrir se pide confirmar el monto en un modal del sistema (evita errores de tipeo);
   - el botón se desactiva al enviar, para no abrir dos veces con un doble clic. */
(function () {
  var formulario = document.getElementById('formAperturaCaja');
  if (!formulario) { return; }

  var inputMonto = document.getElementById('inputMontoApertura');
  var inputObservacion = document.getElementById('inputObservacionApertura');
  var aviso = document.getElementById('avisoObservacion');
  var boton = document.getElementById('btnAbrirCaja');
  var numeroCaja = formulario.getAttribute('data-numero-caja');
  var textoAnterior = formulario.getAttribute('data-monto-anterior');
  var montoAnterior = textoAnterior === '' ? null : Number(textoAnterior);

  // "17500", "17.500" o "$17.500" -> 17500; cualquier otra cosa -> NaN
  function leerMonto(texto) {
    var limpio = String(texto || '').replace(/\s/g, '');
    if (!/^\$?(\d{1,3}(\.\d{3})+|\d+)$/.test(limpio)) { return NaN; }
    return Number(limpio.replace('$', '').replace(/\./g, ''));
  }

  function formatoCLP(monto) {
    return '$' + monto.toLocaleString('es-CL');
  }

  function actualizarObservacion() {
    var monto = leerMonto(inputMonto.value);
    var noCuadra = montoAnterior !== null && !isNaN(monto) && monto !== montoAnterior;
    inputObservacion.required = noCuadra;
    if (aviso) { aviso.hidden = !noCuadra; }
  }

  // El monto solo admite números (también al pegar): se quitan letras y símbolos y se agregan
  // los puntos de miles mientras se escribe (17500 -> 17.500)
  function soloNumeros() {
    var digitos = inputMonto.value.replace(/\D/g, '').slice(0, 7);
    inputMonto.value = digitos === '' ? '' : Number(digitos).toLocaleString('es-CL');
  }

  inputMonto.addEventListener('input', function () {
    soloNumeros();
    actualizarObservacion();
  });
  soloNumeros();
  actualizarObservacion();

  // --- Confirmación con el modal del sistema (en vez del confirm() del navegador) ---
  var modal = document.getElementById('modalConfirmarApertura');
  var usaModal = !!(modal && typeof modal.showModal === 'function');
  var confirmado = false;       // el cajero ya aceptó en el modal: el envío sigue sin volver a preguntar
  var pulsoEnFondo = false;     // el clic empezó en el fondo (para no cerrar al soltar una selección fuera)

  function enviar() {
    confirmado = true;
    if (boton) { boton.disabled = true; }
    formulario.submit();        // no vuelve a disparar 'submit': el formulario ya pasó la validación
  }

  function cerrarModal() {
    if (modal.open) { modal.close(); }
  }

  if (usaModal) {
    modal.querySelector('[data-aceptar]').addEventListener('click', function () {
      cerrarModal();
      enviar();
    });
    modal.querySelector('[data-cancelar]').addEventListener('click', cerrarModal);
    // Clic en el fondo oscuro (fuera de la caja del modal) = cancelar
    modal.addEventListener('mousedown', function (evento) { pulsoEnFondo = evento.target === modal; });
    modal.addEventListener('click', function (evento) {
      if (pulsoEnFondo && evento.target === modal) { cerrarModal(); }
      pulsoEnFondo = false;
    });
    // Al cerrar sin aceptar (Cancelar, Esc o clic fuera), el foco vuelve al monto para corregirlo
    modal.addEventListener('close', function () {
      if (!confirmado) { inputMonto.focus(); }
    });
  }

  formulario.addEventListener('submit', function (evento) {
    var monto = leerMonto(inputMonto.value);
    if (confirmado || isNaN(monto)) {         // un monto inválido lo explica el servidor
      if (boton) { boton.disabled = true; }
      return;
    }
    evento.preventDefault();
    if (!usaModal) {                           // navegador sin <dialog>: queda el confirm() nativo
      if (window.confirm('¿Abrir la Caja ' + numeroCaja + ' con ' + formatoCLP(monto) + '?')) { enviar(); }
      return;
    }
    modal.querySelector('[data-confirmar-monto]').textContent = formatoCLP(monto);
    modal.showModal();
  });

  // Al volver con "Atrás", el navegador puede restaurar la página con el botón desactivado
  window.addEventListener('pageshow', function () {
    confirmado = false;
    if (boton) { boton.disabled = false; }
  });
})();
