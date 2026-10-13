/* Búsqueda en vivo del catálogo (/pedir/): al escribir se actualizan los resultados sin recargar.
   El servidor devuelve solo la zona de resultados cuando recibe ?parcial=1 (core/views.py, pedir).
   Sin JavaScript el formulario funciona igual, con el botón "Buscar". */
(function () {
  var form = document.querySelector('form.buscador');
  var campo = document.getElementById('buscar-producto');
  var zona = document.getElementById('resultados');
  var estado = document.getElementById('buscador-estado');
  var limpiar = form ? form.querySelector('.buscador__limpiar') : null;
  if (!form || !campo || !zona || !window.fetch || !window.AbortController) { return; }

  // "Limpiar" solo se muestra si hay algo escrito.
  function mostrarLimpiar() {
    if (limpiar) { limpiar.hidden = campo.value === ''; }
  }

  var ESPERA_MS = 250;      // tiempo sin teclear antes de buscar
  var temporizador = null;
  var peticion = null;
  var ultimaBusqueda = campo.value.trim();

  function direccion(texto, parcial) {
    var partes = [];
    if (texto) { partes.push('q=' + encodeURIComponent(texto)); }
    if (parcial) { partes.push('parcial=1'); }
    return form.getAttribute('action') + (partes.length ? '?' + partes.join('&') : '');
  }

  function anunciar() {
    var resumen = zona.querySelector('[data-resumen]');
    estado.textContent = resumen ? resumen.getAttribute('data-resumen') : '';
  }

  function buscar() {
    var texto = campo.value.trim();
    if (texto === ultimaBusqueda) { return; }
    ultimaBusqueda = texto;

    if (peticion) { peticion.abort(); }   // una búsqueda nueva descarta la anterior
    var actual = new AbortController();
    peticion = actual;
    zona.setAttribute('aria-busy', 'true');

    fetch(direccion(texto, true), { signal: actual.signal, credentials: 'same-origin' })
      .then(function (respuesta) {
        if (!respuesta.ok) { throw new Error('HTTP ' + respuesta.status); }
        return respuesta.text();
      })
      .then(function (html) {
        // El fragmento lo genera nuestro servidor (con el texto buscado ya escapado). Se analiza como
        // documento y se mueven los nodos, sin asignar HTML directamente ni ejecutar scripts.
        var nodos = new DOMParser().parseFromString(html, 'text/html').body.childNodes;
        zona.replaceChildren.apply(zona, Array.prototype.slice.call(nodos));
        zona.setAttribute('aria-busy', 'false');
        history.replaceState(null, '', direccion(texto, false));  // recargar o compartir conserva la búsqueda
        anunciar();
      })
      .catch(function (error) {
        if (error.name === 'AbortError') { return; }  // la reemplazó otra búsqueda
        zona.setAttribute('aria-busy', 'false');       // sin conexión: quedan los resultados anteriores
        ultimaBusqueda = null;                         // y se podrá reintentar con el mismo texto
      });
  }

  campo.addEventListener('input', function () {
    mostrarLimpiar();
    clearTimeout(temporizador);
    temporizador = setTimeout(buscar, ESPERA_MS);
  });

  // Enter busca de inmediato, sin recargar la página.
  form.addEventListener('submit', function (evento) {
    evento.preventDefault();
    clearTimeout(temporizador);
    buscar();
  });

  // "Limpiar" (junto al campo) y "Ver todos los productos" (sin resultados) vacían el campo y
  // buscan, en vez de recargar la página. Un solo oyente: la zona de resultados se reemplaza.
  document.addEventListener('click', function (evento) {
    var enlace = evento.target.closest ? evento.target.closest('a[data-limpiar]') : null;
    if (!enlace) { return; }
    evento.preventDefault();
    campo.value = '';
    mostrarLimpiar();
    clearTimeout(temporizador);
    buscar();
    campo.focus();
  });

  mostrarLimpiar();
})();
