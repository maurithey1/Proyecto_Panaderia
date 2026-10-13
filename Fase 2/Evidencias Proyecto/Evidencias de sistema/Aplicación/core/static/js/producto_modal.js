/* Modal de producto: al tocar una tarjeta (catálogo e inicio) se abre una ventana con la información
   del producto y su disponibilidad. El contenido lo arma el servidor: /producto/<id>/?parcial=1.
   Sin JavaScript, el nombre del producto es un enlace a la página /producto/<id>/. */
(function () {
  var modal = document.getElementById('producto-modal');
  var contenido = document.getElementById('producto-modal-contenido');
  if (!modal || !contenido || typeof modal.showModal !== 'function' || !window.fetch) { return; }

  var peticion = null;

  function poner(html) {
    // El fragmento lo genera nuestro servidor. Se analiza como documento y se mueven los nodos,
    // sin asignar HTML directamente ni ejecutar scripts.
    var nodos = new DOMParser().parseFromString(html, 'text/html').body.childNodes;
    contenido.replaceChildren.apply(contenido, Array.prototype.slice.call(nodos));
    var titulo = contenido.querySelector('.detalle__titulo');
    if (titulo && titulo.id) {
      modal.setAttribute('aria-labelledby', titulo.id);
      modal.removeAttribute('aria-label');
    }
  }

  function mensaje(texto) {
    var p = document.createElement('p');
    p.className = 'modal-producto__cargando';
    p.textContent = texto;
    contenido.replaceChildren(p);
  }

  function abrir(url) {
    if (peticion) { peticion.abort(); }
    var actual = new AbortController();
    peticion = actual;

    mensaje('Cargando…');
    modal.removeAttribute('aria-labelledby');
    modal.setAttribute('aria-label', 'Información del producto');
    if (!modal.open) { modal.showModal(); }

    fetch(url + (url.indexOf('?') === -1 ? '?' : '&') + 'parcial=1', { signal: actual.signal, credentials: 'same-origin' })
      .then(function (respuesta) {
        if (!respuesta.ok) { throw new Error('HTTP ' + respuesta.status); }
        return respuesta.text();
      })
      .then(poner)
      .catch(function (error) {
        if (error.name === 'AbortError') { return; }
        mensaje('No pudimos cargar el producto. Intenta de nuevo.');
      });
  }

  // El nombre (enlace) y cualquier parte de la tarjeta que no sea un control abren el modal.
  document.addEventListener('click', function (evento) {
    if (evento.defaultPrevented || evento.button !== 0 || evento.metaKey || evento.ctrlKey || evento.shiftKey) { return; }
    var destino = evento.target.closest ? evento.target : null;
    if (!destino) { return; }

    var tarjeta = destino.closest('.tarjeta');
    if (!tarjeta || tarjeta.closest('dialog')) { return; }
    // Agregar, quitar y cambiar cantidad siguen funcionando sin abrir el modal.
    if (destino.closest('.tarjeta__acciones, button, form, input, select, textarea')) { return; }

    var enlace = tarjeta.querySelector('a.tarjeta__abrir');
    if (!enlace) { return; }
    evento.preventDefault();
    abrir(enlace.getAttribute('href'));
  });

  // Cerrar: botón, clic fuera de la ventana (en el fondo) o Esc (nativo).
  modal.addEventListener('click', function (evento) {
    if (evento.target === modal || (evento.target.closest && evento.target.closest('[data-cerrar]'))) {
      modal.close();
    }
  });
  modal.addEventListener('close', function () {
    if (peticion) { peticion.abort(); }
  });
})();
