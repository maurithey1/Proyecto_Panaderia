/* Mantiene al día la página del carrito cuando cambian sus productos sin recargarla.

   Al agregar, quitar o cambiar una cantidad, carrito_ajax.js avisa con el evento "carrito:cambio". Aquí se
   pide al servidor el carrito actual y se reemplaza SOLO lo que depende de él: la tabla de productos, la
   agenda (los horarios y las restricciones cambian según los productos) y si se puede comprar. La
   dirección, el mapa y lo que el cliente ya escribió no se tocan. */
(function () {
  var form = document.querySelector('form.compra__confirmar');
  if (!form) { return; }

  var peticion = null;
  var ultima = 0;

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

        var elegido = eleccionActual();
        reemplazar('.compra__tabla-contenedor', nuevo);
        reemplazar('#agenda-panel', nuevo);

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
