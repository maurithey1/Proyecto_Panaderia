/* ==========================================
   MERMAS DE INVENTARIO (panel de administración)
   ==========================================
   Ayudas del formulario; las reglas reales se validan en el servidor (core/mermas.py):
   - la lista se acorta a productos o a insumos con el selector de arriba. En insumos se elige el
     envase (la caja en uso que tiene 76 huevos, o una de las que siguen cerradas);
   - la ficha muestra lo que hay, lo que quedaría y la pérdida estimada mientras se escribe la
     cantidad. En un envase la cantidad puede ser parcial (10 huevos, 2,5 kg) o "todo el envase";
   - antes de enviar se revisan los mismos casos que el servidor (motivo obligatorio, cantidad
     mayor a 0 y que no exceda lo disponible) y se avisa con el mismo mensaje;
   - se confirma en un modal del sistema, porque una merma no se deshace;
   - el botón se desactiva al enviar, para no registrar dos veces con un doble clic. */
(function () {
  var formulario = document.getElementById('formMerma');
  if (!formulario) { return; }

  var selectItem = document.getElementById('mermaItem');
  var inputCantidad = document.getElementById('mermaCantidad');
  var inputDetalle = document.getElementById('mermaDetalle');
  var grupoMotivo = formulario.querySelector('.merma-motivo');
  var selectorTipo = formulario.querySelector('[data-tipo]');
  var unidadCantidad = formulario.querySelector('[data-unidad-etiqueta]');
  var botonTodo = formulario.querySelector('[data-todo-envase]');
  var ayudaDetalle = formulario.querySelector('[data-detalle-ayuda]');
  var aviso = document.getElementById('mermaAvisoCliente');
  var boton = document.getElementById('btnRegistrarMerma');

  var ficha = document.getElementById('mermaFicha');
  var fichaVacia = ficha.querySelector('[data-ficha-vacia]');
  var fichaContenido = ficha.querySelector('[data-ficha-contenido]');
  var fichaNombre = ficha.querySelector('[data-ficha-nombre]');
  var medidorQueda = ficha.querySelector('[data-medidor-queda]');
  var medidorPierde = ficha.querySelector('[data-medidor-pierde]');
  var fichaHay = ficha.querySelector('[data-ficha-hay]');
  var fichaQuedan = ficha.querySelector('[data-ficha-quedan]');
  var fichaPerdida = ficha.querySelector('[data-ficha-perdida]');
  var fichaNota = ficha.querySelector('[data-ficha-nota]');

  function formatoNumero(numero) {
    return Number(numero).toLocaleString('es-CL', { maximumFractionDigits: 2 });
  }

  function formatoCLP(monto) {
    return '$' + Math.round(monto).toLocaleString('es-CL');
  }

  // 12 unid., 2,5 kg, 76 un. (igual que core/mermas.py)
  function conUnidad(cantidad, unidad) {
    return formatoNumero(cantidad) + ' ' + unidad;
  }

  function itemElegido() {
    var opcion = selectItem.options[selectItem.selectedIndex];
    if (!opcion || !opcion.value) { return null; }
    var envase = opcion.getAttribute('data-envase') || '';
    return {
      nombre: opcion.getAttribute('data-nombre'),
      envase: envase,                                          // tipo de envase ("caja"); vacío en productos
      esEnvase: opcion.value.indexOf('envase-') === 0,
      stock: Number(opcion.getAttribute('data-stock')),        // en un envase: lo que le queda
      unidad: opcion.getAttribute('data-unidad'),
      precio: Number(opcion.getAttribute('data-precio')),      // por unidad de venta, o por kg / L / un. del envase
      decimales: opcion.getAttribute('data-decimales') === '1',
      total: Number(opcion.getAttribute('data-total') || 0)    // stock de todo el insumo (todos sus envases)
    };
  }

  // Cantidad escrita como número (acepta "2,5"), o NaN si no es válida para ese ítem
  function cantidadEscrita(item) {
    var texto = inputCantidad.value.trim();
    var patron = item && item.decimales ? /^\d+([.,]\d{1,2})?$/ : /^\d+$/;
    return patron.test(texto) ? Number(texto.replace(',', '.')) : NaN;
  }

  function motivoElegido() {
    return formulario.querySelector('input[name="motivo"]:checked');
  }

  // --- Lista acortada a productos o insumos ---
  var grupos = {};
  Array.prototype.forEach.call(selectItem.querySelectorAll('optgroup[data-grupo]'), function (grupo) {
    grupos[grupo.getAttribute('data-grupo')] = grupo;
  });
  var opcionVacia = selectItem.options[0];

  function mostrarLista(tipo) {
    var elegido = selectItem.value;
    selectItem.textContent = '';
    selectItem.appendChild(opcionVacia);
    Array.prototype.forEach.call(grupos[tipo].children, function (opcion) {
      selectItem.appendChild(opcion.cloneNode(true));
    });
    var esDelTipo = tipo === 'producto' ? elegido.indexOf('producto-') === 0 : elegido !== '' && elegido.indexOf('producto-') !== 0;
    selectItem.value = esDelTipo ? elegido : '';
  }

  if (grupos.producto && grupos.insumo) {
    var tipoInicial = selectItem.value !== '' && selectItem.value.indexOf('producto-') !== 0 ? 'insumo' : 'producto';
    selectorTipo.querySelector('input[value="' + tipoInicial + '"]').checked = true;
    selectorTipo.hidden = false;
    mostrarLista(tipoInicial);
    selectorTipo.addEventListener('change', function (evento) {
      mostrarLista(evento.target.value);
      actualizar();
      mostrarAviso('');
    });
  }

  // --- Ficha: lo que hay, lo que quedaría y lo que se pierde ---
  function escribir(celda, principal, secundario) {
    celda.textContent = principal;
    if (secundario) {
      var detalle = document.createElement('small');
      detalle.textContent = secundario;
      celda.appendChild(detalle);
    }
  }

  function actualizar() {
    var item = itemElegido();
    unidadCantidad.hidden = !item;
    botonTodo.hidden = !(item && item.esEnvase);
    fichaVacia.hidden = !!item;          // sin ítem, la ficha explica para qué sirve
    fichaContenido.hidden = !item;
    if (!item) { return; }

    fichaNombre.textContent = item.envase ? item.nombre + ' (' + item.envase + ')' : item.nombre;
    var cantidad = cantidadEscrita(item);
    if (isNaN(cantidad)) { cantidad = 0; }
    var excede = cantidad > item.stock;
    var porcentaje = item.stock > 0 ? Math.min(cantidad, item.stock) / item.stock * 100 : 100;

    unidadCantidad.textContent = item.unidad;
    ficha.classList.toggle('merma-ficha--excede', excede);
    medidorPierde.style.width = (excede ? 100 : porcentaje) + '%';
    medidorQueda.style.width = (excede ? 0 : 100 - porcentaje) + '%';

    escribir(fichaHay, conUnidad(item.stock, item.unidad), item.esEnvase ? 'en el envase' : '');
    if (excede) {
      escribir(fichaQuedan, 'No alcanza', 'faltan ' + conUnidad(cantidad - item.stock, item.unidad));
      fichaPerdida.textContent = '—';
    } else {
      escribir(fichaQuedan, conUnidad(item.stock - cantidad, item.unidad), item.esEnvase ? 'en el envase' : '');
      fichaPerdida.textContent = formatoCLP(item.precio * cantidad);
    }
    if (item.esEnvase) {
      var quedanEnTotal = excede ? item.total : item.total - cantidad;
      fichaNota.textContent = 'Stock total de ' + item.nombre + ': ' + conUnidad(item.total, item.unidad) +
        (cantidad > 0 && !excede ? ' → ' + conUnidad(quedanEnTotal, item.unidad) : '') +
        '. Cada ' + item.unidad + ' de este envase vale ' + formatoCLP(item.precio) + '.';
    } else {
      fichaNota.textContent = 'Precio de venta: ' + formatoCLP(item.precio) + ' por ' + (item.unidad === 'kg' ? 'kg' : 'unidad') + '.';
    }
  }

  // La cantidad solo admite dígitos, coma y punto (también al pegar). Los decimales los valida
  // revisar(): si se borraran la coma o el punto, "1,5" pasaría a ser 15 sin que nadie lo note.
  function soloNumeros() {
    inputCantidad.value = inputCantidad.value.replace(/[^\d.,]/g, '').slice(0, 10);
  }

  function actualizarDetalle() {
    var motivo = motivoElegido();
    ayudaDetalle.textContent = motivo && motivo.value === 'OTRO' ? '(obligatorio con el motivo Otro)' : '(opcional)';
  }

  // --- Avisos (mismos mensajes que el servidor) ---
  function mostrarAviso(mensaje, campo) {
    [selectItem, inputCantidad, inputDetalle].forEach(function (c) { c.removeAttribute('aria-invalid'); });
    grupoMotivo.classList.remove('merma-motivo--error');
    aviso.textContent = mensaje;
    aviso.hidden = !mensaje;
    if (!campo) { return; }
    if (campo === grupoMotivo) {
      grupoMotivo.classList.add('merma-motivo--error');
      grupoMotivo.querySelector('input').focus();
      return;
    }
    campo.setAttribute('aria-invalid', 'true');
    campo.focus();
  }

  // Devuelve [mensaje, campo] del primer problema, o null si se puede registrar
  function revisar() {
    var item = itemElegido();
    var motivo = motivoElegido();
    if (!item) { return ['Selecciona el producto o insumo que se perdió.', selectItem]; }
    var cantidad = cantidadEscrita(item);
    if (inputCantidad.value.trim() === '') { return ['Ingresa la cantidad que se perdió.', inputCantidad]; }
    if (!(cantidad > 0)) {
      return [item.decimales ? 'La cantidad debe ser un número mayor a 0, con hasta 2 decimales.'
                             : 'La cantidad debe ser un número entero mayor a 0, sin decimales.', inputCantidad];
    }
    if (!motivo) { return ['El motivo es obligatorio: indica por qué se perdió.', grupoMotivo]; }
    if (motivo.value === 'OTRO' && !inputDetalle.value.trim()) {
      return ['Con el motivo "Otro", describe en el detalle qué pasó.', inputDetalle];
    }
    if (cantidad > item.stock) {
      var mensaje = item.esEnvase
        ? 'Solo quedan ' + conUnidad(item.stock, item.unidad) + ' en ese envase (' + item.envase + ') de ' + item.nombre
        : 'Solo hay ' + conUnidad(item.stock, item.unidad) + ' de ' + item.nombre;
      return [mensaje + ': la cantidad (' + conUnidad(cantidad, item.unidad) + ') excede el stock disponible.', inputCantidad];
    }
    return null;
  }

  selectItem.addEventListener('change', function () {
    actualizar();
    mostrarAviso('');
  });
  inputCantidad.addEventListener('input', function () {
    soloNumeros();
    actualizar();
    mostrarAviso('');
  });
  botonTodo.addEventListener('click', function () {
    var item = itemElegido();
    if (!item) { return; }
    inputCantidad.value = formatoNumero(item.stock).replace(/\./g, '');    // "76" o "12,5", sin puntos de miles
    actualizar();
    mostrarAviso('');
    inputCantidad.focus();
  });
  grupoMotivo.addEventListener('change', function () {
    actualizarDetalle();
    mostrarAviso('');
  });
  inputDetalle.addEventListener('input', function () { mostrarAviso(''); });
  ficha.hidden = false;                // la ficha solo existe con JavaScript
  soloNumeros();
  actualizar();
  actualizarDetalle();

  // --- Confirmación con el modal del sistema (en vez del confirm() del navegador) ---
  var modal = document.getElementById('modalConfirmarMerma');
  var usaModal = !!(modal && typeof modal.showModal === 'function');
  var confirmado = false;       // ya aceptó en el modal: el envío sigue sin volver a preguntar
  var pulsoEnFondo = false;     // el clic empezó en el fondo (para no cerrar al soltar una selección fuera)

  function enviar() {
    confirmado = true;
    boton.disabled = true;
    formulario.submit();        // no vuelve a disparar 'submit': el formulario ya se revisó
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
    // Al cerrar sin aceptar (Cancelar, Esc o clic fuera), el foco vuelve a la cantidad para corregirla
    modal.addEventListener('close', function () {
      if (!confirmado) { inputCantidad.focus(); }
    });
  }

  formulario.addEventListener('submit', function (evento) {
    if (confirmado) {
      boton.disabled = true;
      return;
    }
    evento.preventDefault();
    var problema = revisar();
    if (problema) {
      mostrarAviso(problema[0], problema[1]);
      return;
    }
    mostrarAviso('');

    var item = itemElegido();
    var cantidad = cantidadEscrita(item);
    var nombre = item.envase ? item.nombre + ' (' + item.envase + ')' : item.nombre;
    var motivo = motivoElegido().parentNode.textContent.trim().toLowerCase();
    var valor = formatoCLP(item.precio * cantidad);
    if (!usaModal) {                           // navegador sin <dialog>: queda el confirm() nativo
      if (window.confirm('¿Registrar la merma de ' + conUnidad(cantidad, item.unidad) + ' de ' + nombre + ' (' + valor + ')?')) {
        enviar();
      }
      return;
    }
    modal.querySelector('[data-confirmar-cantidad]').textContent = conUnidad(cantidad, item.unidad);
    modal.querySelector('[data-confirmar-nombre]').textContent = nombre;
    modal.querySelector('[data-confirmar-motivo]').textContent = motivo;
    modal.querySelector('[data-confirmar-valor]').textContent = valor;
    modal.querySelector('[data-confirmar-stock]').textContent =
      (item.esEnvase ? 'El envase pasa de ' : 'El stock pasa de ') +
      conUnidad(item.stock, item.unidad) + ' a ' + conUnidad(item.stock - cantidad, item.unidad) + '.';
    modal.showModal();
  });

  // Al volver con "Atrás", el navegador puede restaurar la página con el botón desactivado
  window.addEventListener('pageshow', function () {
    confirmado = false;
    boton.disabled = false;
  });
})();
