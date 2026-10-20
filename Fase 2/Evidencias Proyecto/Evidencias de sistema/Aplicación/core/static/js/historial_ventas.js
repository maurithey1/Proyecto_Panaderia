/* ==========================================
   HISTORIAL DE VENTAS DEL CAJERO (POS): MODAL "VER DETALLE"
   ==========================================
   Cada botón "Ver detalle" trae en data-url la ruta del detalle (/pos/historial/<id>/detalle/),
   que responde JSON. El modal se arma solo con textContent y createElement: los nombres de los
   productos pueden traer HTML y nunca se interpretan. */
(function () {
  var modal = document.getElementById('historial-modal');
  var titulo = document.getElementById('historial-modal-titulo');
  var cuerpo = document.getElementById('historial-modal-cuerpo');
  if (!modal || !titulo || !cuerpo || typeof modal.showModal !== 'function' || !window.fetch) { return; }

  var TITULO_INICIAL = 'Detalle de la venta';
  var rutaLogin = new URL(modal.getAttribute('data-url-login') || '/login/', window.location.href).pathname;

  var peticion = null;      // AbortController de la petición en curso
  var disparador = null;    // Botón que abrió el modal (recupera el foco al cerrar)
  var pulsoEnFondo = false; // El clic empezó en el fondo (para no cerrar al soltar una selección de texto fuera)

  // Errores con un mensaje pensado para el cajero
  function ErrorVisible(mensaje, conLogin) {
    this.mensaje = mensaje;
    this.conLogin = !!conLogin;
  }

  function crear(etiqueta, clase, texto) {
    var nodo = document.createElement(etiqueta);
    if (clase) { nodo.className = clase; }
    if (texto !== undefined && texto !== null) { nodo.textContent = String(texto); }
    return nodo;
  }

  function mostrarMensaje(texto, tipo, conLogin) {
    var p = crear('p', 'historial-modal__mensaje' + (tipo ? ' historial-modal__mensaje--' + tipo : ''), texto);
    if (conLogin) {
      p.appendChild(document.createTextNode(' '));
      var enlace = crear('a', 'historial-modal__enlace', 'Iniciar sesión');
      enlace.href = modal.getAttribute('data-url-login') || '/login/';
      p.appendChild(enlace);
    }
    cuerpo.replaceChildren(p);
  }

  function esLogin(url) {
    try {
      return new URL(url, window.location.href).pathname === rutaLogin;
    } catch (e) {
      return false;
    }
  }

  // Cantidad con su unidad: 6 → "6 un"; 1.5 → "1,5 kg"
  function textoCantidad(item) {
    var numero = Number(item.cantidad);
    var cantidad = isNaN(numero) ? String(item.cantidad) : numero.toLocaleString('es-CL');
    return item.unidad ? cantidad + ' ' + item.unidad : cantidad;
  }

  function textoTotal(venta) {
    if (venta.total_clp) { return venta.total_clp; }
    return '$' + Math.round(Number(venta.total) || 0).toLocaleString('es-CL');
  }

  // Fecha, hora, medio de pago y estado
  function crearDatos(venta) {
    var lista = crear('dl', 'historial-modal__datos');
    var estadoClase = 'historial-estado historial-estado--' + String(venta.estado || '').toLowerCase().replace(/[^a-z]+/g, '-');
    [
      ['Fecha', venta.fecha],
      ['Hora', venta.hora],
      ['Medio de pago', venta.medio_pago],
      ['Estado', venta.estado, estadoClase]
    ].forEach(function (fila) {
      var grupo = crear('div', 'historial-modal__dato');
      grupo.appendChild(crear('dt', null, fila[0]));
      var valor = crear('dd');
      if (fila[2]) {
        valor.appendChild(crear('span', fila[2], fila[1] || '—'));
      } else {
        valor.textContent = fila[1] || '—';
      }
      grupo.appendChild(valor);
      lista.appendChild(grupo);
    });
    return lista;
  }

  // Tabla Producto | Cantidad | Precio unit. | Subtotal
  function crearTablaItems(venta) {
    var contenedor = crear('div', 'historial-modal__tabla-contenedor');
    var tabla = crear('table', 'historial-modal__tabla');
    tabla.appendChild(crear('caption', 'solo-lector', 'Productos de la venta ' + (venta.numero || '')));

    var thead = crear('thead');
    var filaEncabezado = crear('tr');
    [
      ['Producto', ''],
      ['Cantidad', 'historial-tabla__derecha'],
      ['Precio unit.', 'historial-tabla__derecha'],
      ['Subtotal', 'historial-tabla__derecha']
    ].forEach(function (col) {
      var th = crear('th', col[1], col[0]);
      th.scope = 'col';
      filaEncabezado.appendChild(th);
    });
    thead.appendChild(filaEncabezado);
    tabla.appendChild(thead);

    var tbody = crear('tbody');
    var items = Array.isArray(venta.items) ? venta.items : [];
    if (items.length === 0) {
      var filaVacia = crear('tr');
      var celda = crear('td', 'historial-modal__sin-items', 'La venta no tiene productos registrados.');
      celda.colSpan = 4;
      filaVacia.appendChild(celda);
      tbody.appendChild(filaVacia);
    }
    items.forEach(function (item) {
      var fila = crear('tr');
      fila.appendChild(crear('td', 'historial-modal__producto', item.producto));
      fila.appendChild(crear('td', 'historial-tabla__derecha', textoCantidad(item)));
      fila.appendChild(crear('td', 'historial-tabla__derecha', item.precio_unitario_clp));
      fila.appendChild(crear('td', 'historial-tabla__derecha', item.subtotal_clp));
      tbody.appendChild(fila);
    });
    tabla.appendChild(tbody);
    contenedor.appendChild(tabla);
    return contenedor;
  }

  // "Venta" en la fuente de títulos y el número aparte, con cifras rectas (.historial-cifra)
  function ponerTitulo(numero) {
    titulo.textContent = numero ? 'Venta ' : TITULO_INICIAL;
    if (numero) { titulo.appendChild(crear('span', 'historial-cifra', numero)); }
  }

  function mostrarVenta(venta) {
    ponerTitulo(venta.numero);

    var total = crear('p', 'historial-modal__total');
    total.appendChild(crear('span', null, 'Total'));
    total.appendChild(crear('strong', null, textoTotal(venta)));

    cuerpo.replaceChildren(crearDatos(venta), crearTablaItems(venta), total);
  }

  // Pide el detalle y distingue sesión vencida, venta inexistente y fallas de red
  function cargar(url) {
    if (peticion) { peticion.abort(); }
    var actual = new AbortController();
    peticion = actual;
    cuerpo.setAttribute('aria-busy', 'true');

    fetch(url, {
      signal: actual.signal,
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (respuesta) {
        // cajero_required redirige a /login/ si la sesión venció: fetch sigue la redirección
        if (esLogin(respuesta.url) || respuesta.status === 401) {
          throw new ErrorVisible('Tu sesión expiró, vuelve a iniciar sesión.', true);
        }
        var tipo = respuesta.headers.get('content-type') || '';
        if (tipo.indexOf('application/json') === -1) {
          throw new ErrorVisible(respuesta.status === 404
            ? 'Venta no encontrada.'
            : 'No pudimos cargar el detalle de la venta. Intenta de nuevo.');
        }
        return respuesta.json().then(function (datos) {
          if (!respuesta.ok || !datos || !datos.ok || !datos.venta) {
            var porDefecto = respuesta.status === 404
              ? 'Venta no encontrada.'
              : 'No pudimos cargar el detalle de la venta. Intenta de nuevo.';
            throw new ErrorVisible((datos && datos.error) || porDefecto);
          }
          return datos.venta;
        });
      })
      .then(function (venta) {
        if (peticion !== actual) { return; }
        mostrarVenta(venta);
      })
      .catch(function (error) {
        if (error && error.name === 'AbortError') { return; }
        if (peticion !== actual) { return; }
        if (error instanceof ErrorVisible) {
          mostrarMensaje(error.mensaje, 'error', error.conLogin);
        } else {
          mostrarMensaje('No se pudo conectar con el servidor. Revisa tu conexión e intenta de nuevo.', 'error');
        }
      })
      .then(function () {
        if (peticion === actual) {
          cuerpo.removeAttribute('aria-busy');
          peticion = null;
        }
      });
  }

  function abrir(boton) {
    disparador = boton;
    ponerTitulo(boton.getAttribute('data-numero'));
    mostrarMensaje('Cargando…');
    if (!modal.open) { modal.showModal(); }
    cargar(boton.getAttribute('data-url'));
  }

  // Botones "Ver detalle" de la tabla
  document.addEventListener('click', function (evento) {
    var boton = evento.target.closest ? evento.target.closest('.historial-btn-detalle') : null;
    if (!boton || !boton.getAttribute('data-url')) { return; }
    evento.preventDefault();
    abrir(boton);
  });

  // Cerrar: botón "Cerrar", clic en el fondo (fuera de la caja) o Esc (nativo del <dialog>)
  modal.addEventListener('pointerdown', function (evento) {
    pulsoEnFondo = evento.target === modal;
  });
  modal.addEventListener('click', function (evento) {
    var enFondo = evento.target === modal && pulsoEnFondo;
    pulsoEnFondo = false;
    if (enFondo || (evento.target.closest && evento.target.closest('[data-cerrar]'))) {
      modal.close();
    }
  });

  modal.addEventListener('close', function () {
    if (peticion) { peticion.abort(); peticion = null; }
    cuerpo.removeAttribute('aria-busy');
    if (disparador && document.body.contains(disparador)) { disparador.focus(); }
    disparador = null;
  });
})();
