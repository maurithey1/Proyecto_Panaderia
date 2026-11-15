/* Mantiene al día la página del carrito cuando cambian sus productos sin recargarla.

   Al agregar, quitar o cambiar una cantidad, carrito_ajax.js avisa con el evento "carrito:cambio". Aquí se
   pide al servidor el carrito actual y se reemplaza SOLO lo que depende de él: la tabla de productos, la
   sección de puntos de fidelización, la agenda y si se puede comprar. La dirección, el mapa y lo que el
   cliente ya escribió no se tocan. */
(function () {
  var form = document.querySelector('form.compra__confirmar');
  if (!form) { return; }

  var peticion = null;
  var ultima = 0;

  function formatoCLP(n) {
    return '$' + Math.max(0, Math.round(n)).toLocaleString('es-CL');
  }

  function obtenerSubtotalActual() {
    var celdaTotal = document.querySelector('.compra__tabla tfoot td strong');
    if (celdaTotal) {
      var limpio = celdaTotal.textContent.replace(/\D/g, '');
      if (limpio) { return parseInt(limpio, 10); }
    }
    var elTotalFinal = document.getElementById('resumen-total-final');
    return parseInt((elTotalFinal && elTotalFinal.dataset.subtotalInicial) || '0', 10);
  }

  function recalcularFidelizacion() {
    var inputPuntos = document.getElementById('puntos-a-canjear');
    var elDesc = document.getElementById('resumen-descuento-puntos');
    var elTotalFinal = document.getElementById('resumen-total-final');
    var elGanar = document.getElementById('resumen-puntos-ganar');

    if (!elTotalFinal) { return; }

    var subtotal = obtenerSubtotalActual();
    var canje = 0;

    if (inputPuntos) {
      var maxPermitido = Math.min(
        parseInt(inputPuntos.max || '0', 10),
        Math.floor(subtotal * 0.80),
        Math.max(0, subtotal - 100)
      );
      canje = Math.max(0, Math.min(maxPermitido, parseInt(inputPuntos.value || '0', 10) || 0));
      inputPuntos.value = canje;
    }

    var totalPagar = Math.max(0, subtotal - canje);
    var ptsGanar = Math.floor(totalPagar * 0.10);

    if (elDesc) { elDesc.textContent = '-' + formatoCLP(canje); }
    elTotalFinal.textContent = formatoCLP(totalPagar);
    if (elGanar) { elGanar.textContent = '+' + ptsGanar + ' pts'; }
  }

  form.addEventListener('input', function (e) {
    if (e.target && e.target.id === 'puntos-a-canjear') {
      recalcularFidelizacion();
    }
  });

  form.addEventListener('click', function (e) {
    var btnMax = e.target.closest('#btn-max-puntos');
    if (!btnMax) { return; }

    var inputPuntos = document.getElementById('puntos-a-canjear');
    if (!inputPuntos) { return; }

    var subtotal = obtenerSubtotalActual();
    var maxPermitido = Math.min(
      parseInt(btnMax.dataset.max || '0', 10),
      Math.floor(subtotal * 0.80),
      Math.max(0, subtotal - 100)
    );
    inputPuntos.value = Math.max(0, maxPermitido);
    recalcularFidelizacion();
  });

  function reemplazar(selector, documentoNuevo) {
    var viejo = document.querySelector(selector);
    var nuevo = documentoNuevo.querySelector(selector);
    if (viejo && nuevo) { viejo.replaceWith(document.importNode(nuevo, true)); }
  }

  function eleccionActual() {
    var fecha = document.getElementById('retiro-fecha');
    var hora = document.getElementById('retiro-hora');
    return { fecha: fecha ? fecha.value : '', hora: hora ? hora.value : '' };
  }

  function refrescar() {
    if (peticion) { peticion.abort(); }   // un cambio nuevo descarta la consulta anterior
    var control = new AbortController();
    peticion = control;
    var numero = ++ultima;

    fetch('/carrito/', { signal: control.signal, credentials: 'same-origin' })
      .then(function (respuesta) {
        if (!respuesta.ok) { throw new Error('HTTP ' + respuesta.status); }
        return respuesta.text();
      })
      .then(function (html) {
        if (numero !== ultima) { return; }
        var nuevo = new DOMParser().parseFromString(html, 'text/html');
        var formNuevo = nuevo.querySelector('form.compra__confirmar');
        if (!formNuevo) { window.location.reload(); return; }   // el carrito quedó vacío

        var inputPuntosAntes = document.getElementById('puntos-a-canjear');
        var canjePrevio = inputPuntosAntes ? (parseInt(inputPuntosAntes.value, 10) || 0) : 0;

        var elegido = eleccionActual();
        reemplazar('.compra__tabla-contenedor', nuevo);
        reemplazar('.compra__seccion-fidelizacion', nuevo);
        reemplazar('#agenda-panel', nuevo);

        var inputPuntosDespues = document.getElementById('puntos-a-canjear');
        if (inputPuntosDespues && canjePrevio > 0) {
          inputPuntosDespues.value = canjePrevio;
        }
        recalcularFidelizacion();

        // El botón de pagar: lo que dice el servidor (stock y horarios). zona_despacho.js le suma, si
        // corresponde, la exigencia de confirmar la dirección.
        var boton = form.querySelector('button[type="submit"]');
        var botonNuevo = formNuevo.querySelector('button[type="submit"]');
        if (boton && botonNuevo) {
          boton.disabled = botonNuevo.disabled;
          if (botonNuevo.dataset.bloqueoServidor === '1') { boton.dataset.bloqueoServidor = '1'; }
          else { delete boton.dataset.bloqueoServidor; }
        }
        if (window.reiniciarAgenda) { window.reiniciarAgenda(elegido); }
        form.dispatchEvent(new CustomEvent('carrito:actualizado'));
      })
      .catch(function (error) {
        // Sin conexión: se deja lo que hay. Al comprar, el servidor valida todo de nuevo.
        if (error.name === 'AbortError') { return; }
      });
  }

  document.addEventListener('carrito:cambio', refrescar);
})();
