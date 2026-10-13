/* Búsqueda en vivo del catálogo (/pedir/): al escribir se actualizan los resultados sin recargar.
   El servidor devuelve solo la zona de resultados cuando recibe ?parcial=1 (core/views.py, pedir).
   Sin JavaScript el formulario funciona igual, con el botón "Buscar".

   Si una búsqueda falla, los resultados que quedan en pantalla son los de la búsqueda anterior: se avisa
   con un mensaje visible, se marcan como desactualizados y se ofrece reintentar (también se reintenta sola
   cuando vuelve la conexión). */
(function () {
  var form = document.querySelector('form.buscador');
  var campo = document.getElementById('buscar-producto');
  var zona = document.getElementById('resultados');
  var estado = document.getElementById('buscador-estado');
  var aviso = document.getElementById('buscador-aviso');
  var avisoTexto = aviso ? aviso.querySelector('[data-texto]') : null;
  var reintentar = aviso ? aviso.querySelector('[data-reintentar]') : null;
  var limpiar = form ? form.querySelector('.buscador__limpiar') : null;
  if (!form || !campo || !zona || !window.fetch || !window.AbortController) { return; }

  // "Limpiar" solo se muestra si hay algo escrito.
  function mostrarLimpiar() {
    if (limpiar) { limpiar.hidden = campo.value === ''; }
  }

  var ESPERA_MS = 250;      // tiempo sin teclear antes de buscar
  var temporizador = null;
  // La petición vigente. Una respuesta solo se aplica si sigue siendo esta: si el cliente cambió el texto
  // mientras tanto (o volvió al que ya se ve), lo que llegue después es de una búsqueda vieja y se descarta.
  var peticion = null;
  // La búsqueda a la que corresponden los resultados que hay en pantalla. No es "la última que se intentó":
  // si una búsqueda falla, esto no cambia, y por eso se sabe que lo que se ve está desactualizado.
  var mostrada = campo.value.trim();

  // Arma la dirección con lo que lleva el formulario: la búsqueda más los filtros activos
  // (campos ocultos "turno" y "categoria"), para buscar dentro del turno y la categoría elegidos.
  function direccion(texto, parcial) {
    var parametros = new URLSearchParams();
    new FormData(form).forEach(function (valor, nombre) {
      if (nombre !== 'q' && valor !== '') { parametros.append(nombre, valor); }
    });
    if (texto) { parametros.set('q', texto); }
    if (parcial) { parametros.set('parcial', '1'); }
    var consulta = parametros.toString();
    return form.getAttribute('action') + (consulta ? '?' + consulta : '');
  }

  function anunciar() {
    var resumen = zona.querySelector('[data-resumen]');
    estado.textContent = resumen ? resumen.getAttribute('data-resumen') : '';
  }

  function ocultarAviso() {
    if (aviso) { aviso.hidden = true; }
    zona.removeAttribute('data-desactualizado');
  }

  function mostrarAviso(texto, causa) {
    zona.setAttribute('data-desactualizado', 'true');
    if (!aviso || !avisoTexto) { return; }
    var buscado = texto ? '«' + texto + '»' : 'todo el catálogo';
    var viendo = mostrada ? '«' + mostrada + '»' : 'todo el catálogo';
    var motivo = causa === 'servidor' ? 'El servidor no respondió.' : 'No hay conexión.';
    avisoTexto.textContent = motivo + ' No pudimos buscar ' + buscado +
      '; estás viendo los resultados de ' + viendo + ', que no están actualizados.';
    aviso.hidden = false;
  }

  // Cancela la búsqueda en vuelo y deja de esperarla: lo que responda ya no se aplica.
  function descartarPeticion() {
    if (peticion) {
      var vieja = peticion;
      peticion = null;
      vieja.abort();
    }
  }

  // `forzar` repite la búsqueda aunque el texto sea el mismo que el de la última que se mostró.
  function buscar(forzar) {
    var texto = campo.value.trim();
    if (forzar !== true && texto === mostrada) {
      // Volvió al texto de lo que ya se ve: no hay nada nuevo que buscar ni desactualizado que avisar. Y si
      // había una búsqueda en vuelo (p. ej. escribió «pan» y lo borró antes de la respuesta), ya no sirve:
      // se descarta, o llegaría después y dejaría el campo vacío con los resultados de «pan».
      descartarPeticion();
      zona.setAttribute('aria-busy', 'false');
      ocultarAviso();
      return;
    }

    descartarPeticion();   // una búsqueda nueva descarta la anterior
    var actual = new AbortController();
    peticion = actual;
    zona.setAttribute('aria-busy', 'true');

    fetch(direccion(texto, true), { signal: actual.signal, credentials: 'same-origin' })
      .then(function (respuesta) {
        if (!respuesta.ok) { throw new Error('HTTP ' + respuesta.status); }
        return respuesta.text();
      })
      .then(function (html) {
        if (peticion !== actual) { return; }   // llegó tarde: el cliente ya cambió la búsqueda
        // El fragmento lo genera nuestro servidor (con el texto buscado ya escapado). Se analiza como
        // documento y se mueven los nodos, sin asignar HTML directamente ni ejecutar scripts.
        var nodos = new DOMParser().parseFromString(html, 'text/html').body.childNodes;
        zona.replaceChildren.apply(zona, Array.prototype.slice.call(nodos));
        zona.setAttribute('aria-busy', 'false');
        mostrada = texto;
        ocultarAviso();
        peticion = null;
        history.replaceState(null, '', direccion(texto, false));  // recargar o compartir conserva la búsqueda
        anunciar();
      })
      .catch(function (error) {
        if (error.name === 'AbortError' || peticion !== actual) { return; }  // la reemplazó otra búsqueda
        peticion = null;
        zona.setAttribute('aria-busy', 'false');
        mostrarAviso(texto, /^HTTP/.test(error.message || '') ? 'servidor' : 'red');
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

  if (reintentar) {
    reintentar.addEventListener('click', function () {
      clearTimeout(temporizador);
      buscar(true);
    });
  }

  // Si estaba desactualizado por falta de conexión, al volver la conexión se vuelve a intentar sola.
  window.addEventListener('online', function () {
    if (aviso && !aviso.hidden) { buscar(true); }
  });

  mostrarLimpiar();
})();
