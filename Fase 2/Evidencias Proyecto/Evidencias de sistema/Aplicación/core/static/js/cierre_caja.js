/* ==========================================
   CIERRE DE CAJA (POS)
   ==========================================
   Ayudas del formulario; las reglas reales se validan en el servidor (core/caja.py):
   - calcula en tiempo real la diferencia (cuadrada, sobrante o faltante);
   - si la caja no cuadra, la observación es obligatoria para explicar la discrepancia;
   - antes de cerrar se pide confirmación en modal para evitar errores de tipeo;
   - el botón se deshabilita al enviar para evitar dobles envíos. */
(function () {
  var formulario = document.getElementById('formCierreCaja');
  if (!formulario) { return; }

  var inputMonto = document.getElementById('inputMontoCierre');
  var inputObservacion = document.getElementById('inputObservacionCierre');
  var ayudaObservacion = document.getElementById('ayudaObservacion');
  var avisoObservacion = document.getElementById('avisoObservacionCierre');
  var boton = document.getElementById('btnCerrarCaja');
  var numeroCaja = formulario.getAttribute('data-numero-caja') || '1';
  var montoEsperado = Number(formulario.getAttribute('data-monto-esperado') || 0);

  var contenedorCuadratura = document.getElementById('contenedorCuadratura');
  var badgeCuadratura = document.getElementById('badgeCuadratura');
  var textoDiferencia = document.getElementById('textoDiferencia');

  // Convierte "$17.500" o "17500" -> 17500
  function leerMonto(texto) {
    var limpio = String(texto || '').replace(/\s/g, '');
    if (!/^\$?(\d{1,3}(\.\d{3})+|\d+)$/.test(limpio)) { return NaN; }
    return Number(limpio.replace('$', '').replace(/\./g, ''));
  }

  function formatoCLP(monto) {
    return '$' + Math.round(monto).toLocaleString('es-CL');
  }

  function actualizarCuadratura() {
    var montoContado = leerMonto(inputMonto.value);
    if (isNaN(montoContado) || inputMonto.value.trim() === '') {
      if (contenedorCuadratura) { contenedorCuadratura.hidden = true; }
      inputObservacion.required = false;
      if (avisoObservacion) { avisoObservacion.hidden = true; }
      if (ayudaObservacion) { ayudaObservacion.textContent = '(opcional si la caja cuadra)'; }
      return { montoContado: NaN, diferencia: 0, estado: '' };
    }

    var diferencia = montoContado - montoEsperado;
    var estado = '';
    var claseBadge = '';
    var textoDif = '';

    if (contenedorCuadratura) { contenedorCuadratura.hidden = false; }

    if (diferencia === 0) {
      estado = 'Cuadrada';
      claseBadge = 'apertura-insignia--cuadrada';
      textoDif = 'Caja cuadrada (sin diferencia)';
      inputObservacion.required = false;
      if (avisoObservacion) { avisoObservacion.hidden = true; }
      if (ayudaObservacion) { ayudaObservacion.textContent = '(opcional: la caja cuadra)'; }
    } else if (diferencia > 0) {
      estado = 'Sobrante';
      claseBadge = 'apertura-insignia--sobrante';
      textoDif = 'Sobrante de +' + formatoCLP(diferencia);
      inputObservacion.required = true;
      if (avisoObservacion) { avisoObservacion.hidden = false; }
      if (ayudaObservacion) { ayudaObservacion.textContent = '(obligatorio: hay un sobrante de dinero)'; }
    } else {
      estado = 'Faltante';
      claseBadge = 'apertura-insignia--faltante';
      textoDif = 'Faltante de -' + formatoCLP(Math.abs(diferencia));
      inputObservacion.required = true;
      if (avisoObservacion) { avisoObservacion.hidden = false; }
      if (ayudaObservacion) { ayudaObservacion.textContent = '(obligatorio: hay un faltante de dinero)'; }
    }

    if (badgeCuadratura) {
      badgeCuadratura.className = 'apertura-insignia ' + claseBadge;
      badgeCuadratura.textContent = estado;
    }
    if (textoDiferencia) {
      textoDiferencia.textContent = '(' + textoDif + ')';
    }

    return { montoContado: montoContado, diferencia: diferencia, estado: estado };
  }

  // Agrega formato con puntos de miles al escribir
  function soloNumeros() {
    var digitos = inputMonto.value.replace(/\D/g, '').slice(0, 9);
    inputMonto.value = digitos === '' ? '' : Number(digitos).toLocaleString('es-CL');
  }

  inputMonto.addEventListener('input', function () {
    soloNumeros();
    actualizarCuadratura();
  });
  soloNumeros();
  actualizarCuadratura();

  // --- Confirmación con <dialog> ---
  var modal = document.getElementById('modalConfirmarCierre');
  var usaModal = !!(modal && typeof modal.showModal === 'function');
  var confirmado = false;
  var pulsoEnFondo = false;

  function enviar() {
    confirmado = true;
    if (boton) { boton.disabled = true; }
    formulario.submit();
  }

  function cerrarModal() {
    if (modal && modal.open) { modal.close(); }
  }

  if (usaModal) {
    modal.querySelector('[data-aceptar]').addEventListener('click', function () {
      cerrarModal();
      enviar();
    });
    modal.querySelector('[data-cancelar]').addEventListener('click', cerrarModal);
    modal.addEventListener('mousedown', function (evento) { pulsoEnFondo = evento.target === modal; });
    modal.addEventListener('click', function (evento) {
      if (pulsoEnFondo && evento.target === modal) { cerrarModal(); }
      pulsoEnFondo = false;
    });
    modal.addEventListener('close', function () {
      if (!confirmado) { inputMonto.focus(); }
    });
  }

  formulario.addEventListener('submit', function (evento) {
    var info = actualizarCuadratura();
    if (confirmado || isNaN(info.montoContado)) {
      if (boton) { boton.disabled = true; }
      return;
    }

    // Validación de observación si no cuadra
    if (info.diferencia !== 0 && !inputObservacion.value.trim()) {
      inputObservacion.focus();
      if (avisoObservacion) { avisoObservacion.hidden = false; }
      evento.preventDefault();
      return;
    }

    evento.preventDefault();
    if (!usaModal) {
      var msg = '¿Confirmar cierre de Caja ' + numeroCaja + ' con arqueo de ' + formatoCLP(info.montoContado) +
                ' (' + info.estado + ')?';
      if (window.confirm(msg)) { enviar(); }
      return;
    }

    modal.querySelector('[data-confirmar-monto]').textContent = formatoCLP(info.montoContado);
    var detalle = document.getElementById('modalDetalleCuadratura');
    if (detalle) {
      if (info.diferencia === 0) {
        detalle.innerHTML = '<span class="apertura-insignia apertura-insignia--cuadrada">Caja cuadrada</span> (Coincide con el sistema)';
      } else if (info.diferencia > 0) {
        detalle.innerHTML = '<span class="apertura-insignia apertura-insignia--sobrante">Sobrante: +' + formatoCLP(info.diferencia) + '</span>';
      } else {
        detalle.innerHTML = '<span class="apertura-insignia apertura-insignia--faltante">Faltante: -' + formatoCLP(Math.abs(info.diferencia)) + '</span>';
      }
    }
    modal.showModal();
  });

  window.addEventListener('pageshow', function () {
    confirmado = false;
    if (boton) { boton.disabled = false; }
  });
})();
