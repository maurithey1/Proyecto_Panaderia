/* Despacho a domicilio: sugiere direcciones mientras se escribe, ubica el punto en el mapa, pide el número
   si falta y comprueba que esté dentro de la zona de despacho.
   El servidor repite la comprobación de la zona al confirmar la compra (core/zona_despacho.py);
   esto sirve para avisarle al cliente a tiempo, no para reemplazar esa validación. */
(function () {
  var panel = document.getElementById('zona-despacho');
  if (!panel) { return; }

  var form = panel.closest('form');
  var campoDireccion = document.getElementById('direccion-despacho');
  var botonBuscar = document.getElementById('zona-buscar');
  var lista = document.getElementById('zona-resultados');
  var estado = document.getElementById('zona-estado');
  var bloqueNumero = document.getElementById('zona-numero-bloque');
  var campoNumero = document.getElementById('zona-numero');
  var campoLat = document.getElementById('zona-latitud');
  var campoLng = document.getElementById('zona-longitud');
  var contenedorMapa = document.getElementById('zona-mapa');
  var botonEnviar = form.querySelector('button[type="submit"]');
  var avisoEnvio = document.getElementById('zona-aviso-envio');

  var tiendaLat = parseFloat(panel.dataset.lat);
  var tiendaLng = parseFloat(panel.dataset.lng);
  var direccionTienda = panel.dataset.direccionTienda || 'la tienda';
  // El servidor bloquea el botón por falta de stock o de horarios y lo marca con data-bloqueo-servidor. Se lee
  // cada vez (no solo al cargar) porque el carrito puede cambiar sin recargar la página (carrito_estado.js).
  function bloqueadoPorServidor() {
    return botonEnviar ? botonEnviar.dataset.bloqueoServidor === '1' : false;
  }

  var ATRIBUCION = '&copy; <a href="https://www.openstreetmap.org/copyright">Colaboradores de OpenStreetMap</a>';
  var URL_TESELAS = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  // Sugerencias mientras se escribe: Photon (datos de OpenStreetMap), que sí permite autocompletar.
  var URL_PHOTON = 'https://photon.komoot.io/api/';
  // Respaldo y dirección de un punto del mapa: Nominatim (OpenStreetMap), solo por consulta puntual.
  var URL_BUSQUEDA = 'https://nominatim.openstreetmap.org/search';
  var URL_INVERSA = 'https://nominatim.openstreetmap.org/reverse';
  var BBOX_CHILE = '-75.7,-56.0,-66.4,-17.5'; // oeste,sur,este,norte
  // Django envía "Referrer-Policy: same-origin" y OpenStreetMap exige un Referer válido.
  var POLITICA_REFERER = 'strict-origin-when-cross-origin';
  var MIN_CARACTERES = 3;
  var ESPERA_ESCRIBIENDO_MS = 350;
  var TEXTO_INICIAL = 'Empieza a escribir tu dirección y elige una sugerencia de la lista. ' +
    'También puedes hacer clic en el mapa para marcar el punto exacto.';

  // Un número de casa es un número al final de la calle (o seguido de depto, casa, block...), no el que
  // forma parte del nombre ("Avenida 5 de Abril"). "S/N" y "sin número" también valen.
  var RE_NUMERO = /\b\d+[a-z]?\b(?=\s*$|\s+[a-z]\s*$|\s+(?:dp?to\.?|departamento|casa|block|blk|of\.?|oficina|local|piso)\b|\s*[-\/]\s*\w+\s*$)/i;
  var RE_SIN_NUMERO = /\bs\s*\/?\s*n\b|\bsin\s+n[uú]mero\b/i;

  var zonaGeo = null;     // GeoJSON tal como viene del archivo
  var poligonos = null;   // [[contorno, hueco, ...], ...] con puntos [lng, lat]
  var limites = null;     // [minLng, minLat, maxLng, maxLat]
  var promesaZona = null;
  var mapa = null;
  var pin = null;
  var origen = '';        // 'busqueda' o 'mapa': de dónde salió el punto actual
  var callesElegidas = []; // nombre del lugar y calle de la sugerencia elegida (para saber si los cambiaron)
  var comunaElegida = '';  // comuna de la sugerencia elegida, en minúsculas
  var motivoBloqueo = '';  // por qué no se puede comprar: 'fuera', 'numero' o 'direccion'

  var MENSAJES_BLOQUEO = {
    fuera: 'No despachamos a esa dirección porque está fuera de la zona de despacho. ' +
      'Cambia la dirección o elige retiro en tienda para poder comprar.',
    numero: 'Falta el número de la dirección (o S/N si no tiene) para poder comprar con despacho.',
    direccion: 'Para comprar con despacho, primero confirma una dirección dentro de la zona de despacho.'
  };
  var base = null;        // partes de la dirección elegida: {nombre, calle, numero, comuna, region, cp}
  var ultimoGenerado = ''; // último texto que escribió el programa en el campo (para saber si lo editaron)
  var confirmado = false; // hay un punto aceptable para despachar
  var busquedaAutomaticaHecha = false;

  var sugerencias = [];   // [{etiqueta, direccion, partes, sinNumero, lat, lng}]
  var indiceActivo = -1;
  var temporizadorEscribiendo = null;
  var controlSugerencias = null; // AbortController de la consulta en curso
  var numeroConsulta = 0;        // numera las consultas para ignorar respuestas viejas
  var temporizadorDireccion = null;
  var consultaDireccion = 0;

  function esDespacho() {
    var elegido = form.querySelector('input[name="tipo_entrega"]:checked');
    return !!elegido && elegido.value === 'DESPACHO';
  }

  // ---------- zona de despacho (mismo archivo que usa el servidor)
  function cargarZona() {
    if (!promesaZona) {
      promesaZona = fetch(panel.dataset.geojson)
        .then(function (r) {
          if (!r.ok) { throw new Error('zona'); }
          return r.json();
        })
        .then(function (geo) {
          zonaGeo = geo;
          poligonos = [];
          (function recoger(g) {
            if (!g) { return; }
            if (g.type === 'FeatureCollection') { g.features.forEach(recoger); }
            else if (g.type === 'Feature') { recoger(g.geometry); }
            else if (g.type === 'Polygon') { poligonos.push(g.coordinates); }
            else if (g.type === 'MultiPolygon') { g.coordinates.forEach(function (p) { poligonos.push(p); }); }
          })(geo);
          var xs = [], ys = [];
          poligonos.forEach(function (anillos) {
            anillos[0].forEach(function (p) { xs.push(p[0]); ys.push(p[1]); });
          });
          limites = [Math.min.apply(null, xs), Math.min.apply(null, ys), Math.max.apply(null, xs), Math.max.apply(null, ys)];
        })
        .catch(function () {
          poligonos = null; // sin la zona en el navegador, la comprobación la hace el servidor
        });
    }
    return promesaZona;
  }

  function enAnillo(x, y, anillo) {
    var dentro = false;
    for (var i = 0, j = anillo.length - 1; i < anillo.length; j = i++) {
      var xi = anillo[i][0], yi = anillo[i][1], xj = anillo[j][0], yj = anillo[j][1];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) { dentro = !dentro; }
    }
    return dentro;
  }

  // true / false, o null si la zona no se pudo leer en el navegador
  function enZona(lat, lng) {
    if (!poligonos) { return null; }
    return poligonos.some(function (anillos) {
      return enAnillo(lng, lat, anillos[0]) &&
        !anillos.slice(1).some(function (hueco) { return enAnillo(lng, lat, hueco); });
    });
  }

  // ---------- mensajes y estado del botón
  function mostrar(texto, tipo, conRetiro) {
    estado.className = 'zona__estado' + (tipo ? ' zona__estado--' + tipo : '');
    estado.textContent = texto;
    if (conRetiro) {
      var boton = document.createElement('button');
      boton.type = 'button';
      boton.className = 'boton boton--contorno zona__retiro';
      boton.textContent = 'Elegir retiro en tienda';
      boton.addEventListener('click', function () {
        var retiro = form.querySelector('input[name="tipo_entrega"][value="RETIRO"]');
        retiro.checked = true;
        retiro.dispatchEvent(new Event('change', { bubbles: true }));
        retiro.focus();
      });
      estado.appendChild(document.createTextNode(' '));
      estado.appendChild(boton);
    }
  }

  // El botón de comprar solo está habilitado si la entrega es retiro o si la dirección está confirmada
  // dentro de la zona. Cuando se bloquea por la dirección, se dice el motivo junto al botón.
  function actualizarEnvio() {
    if (!botonEnviar) { return; }
    var porDireccion = esDespacho() && !confirmado;
    var porServidor = bloqueadoPorServidor();
    botonEnviar.disabled = porServidor || porDireccion;
    if (!avisoEnvio) { return; }
    var mostrarAviso = porDireccion && !porServidor;
    avisoEnvio.hidden = !mostrarAviso;
    if (mostrarAviso) {
      avisoEnvio.textContent = MENSAJES_BLOQUEO[motivoBloqueo] || MENSAJES_BLOQUEO.direccion;
      botonEnviar.setAttribute('aria-describedby', avisoEnvio.id);
    } else {
      botonEnviar.removeAttribute('aria-describedby');
    }
  }

  // ---------- número de la dirección
  // Se miran solo las dos primeras partes (nombre del lugar y calle): el código postal también tiene dígitos.
  function tieneNumero() {
    return campoDireccion.value.split(',').slice(0, 2).some(function (parte) {
      return RE_NUMERO.test(parte) || RE_SIN_NUMERO.test(parte);
    });
  }

  // La calle y el número se agregan solos solo si el campo sigue como lo escribió el programa.
  function puedeAgregarNumero() {
    return !!(base && base.calle && campoDireccion.value === ultimoGenerado);
  }

  // El campo "Número" aparece cuando hay un punto dentro de la zona y a la dirección le falta el número.
  function actualizarNumero() {
    var lat = parseFloat(campoLat.value);
    var lng = parseFloat(campoLng.value);
    var hayPunto = !isNaN(lat) && !isNaN(lng);
    var afuera = hayPunto && enZona(lat, lng) === false;
    var falta = hayPunto && !afuera && !tieneNumero();
    var conValor = campoNumero.value.trim() !== '';
    bloqueNumero.hidden = !(puedeAgregarNumero() && (falta || conValor));
  }

  // `prefijo` (opcional) se antepone al mensaje; sirve para anunciar la dirección que se acaba de elegir.
  function evaluar(prefijo) {
    var pre = prefijo ? prefijo + ' ' : '';
    var lat = parseFloat(campoLat.value);
    var lng = parseFloat(campoLng.value);
    motivoBloqueo = 'direccion';
    if (isNaN(lat) || isNaN(lng)) {
      confirmado = false;
      mostrar(TEXTO_INICIAL, 'info');
      actualizarNumero();
      actualizarEnvio();
      return;
    }
    var dentro = enZona(lat, lng);
    if (dentro === false) {
      confirmado = false;
      motivoBloqueo = 'fuera';
      mostrar(pre + 'Esta ubicación está fuera de la zona de despacho marcada en el mapa. ' +
        'Puedes retirar tu pedido en la tienda (' + direccionTienda + ').', 'error', true);
    } else if (!campoDireccion.value.trim()) {
      confirmado = false;
      mostrar(pre + 'La ubicación está dentro de la zona. Escribe tu dirección (calle y número) ' +
        'para que el repartidor la encuentre.', 'info');
    } else if (!tieneNumero()) {
      // Sin número no se despacha: el repartidor lo necesita (S/N si la dirección no tiene).
      confirmado = false;
      motivoBloqueo = 'numero';
      if (puedeAgregarNumero()) {
        mostrar(pre + 'Dentro de la zona. Falta el número de tu casa o edificio: escríbelo en el campo ' +
          '«Número» (o S/N si no tiene).', 'info');
      } else {
        mostrar(pre + 'Dentro de la zona. Agrega el número a tu dirección (o S/N si no tiene).', 'info');
      }
    } else if (dentro === null) {
      confirmado = true;
      mostrar(pre + 'No pudimos comprobar la zona en tu navegador; la confirmaremos al finalizar la compra.', 'info');
    } else {
      confirmado = true;
      mostrar(pre + 'Dentro de la zona: despachamos a esta dirección.', 'ok');
    }
    actualizarNumero();
    actualizarEnvio();
  }

  // ---------- armado de direcciones a partir de lo que entrega OpenStreetMap
  // "Región de Valparaíso" -> "Valparaíso"; "Región Metropolitana de Santiago" -> "Región Metropolitana"
  function regionCorta(estadoRegion) {
    var r = estadoRegion || '';
    if (/metropolitana/i.test(r)) { return 'Región Metropolitana'; }
    return r.replace(/^Regi[oó]n (del? )?/i, '');
  }

  // Une las partes sin vacíos ni repetidos: "Marigen 9795, La Florida, Región Metropolitana, 8320000"
  function unir(partes) {
    var salida = [];
    partes.forEach(function (p) {
      if (p && salida.indexOf(p) === -1) { salida.push(p); }
    });
    return salida.join(', ');
  }

  // Primera parte de la dirección: "Marigen 9795" o, si es un lugar, "Duoc UC Sede Melipilla, Los Carreras 360".
  function via(p, numeroExtra) {
    var numero = p.numero || numeroExtra || '';
    var calleNumero = p.calle ? p.calle + (numero ? ' ' + numero : '') : '';
    if (calleNumero) {
      return (p.nombre && p.nombre !== p.calle) ? p.nombre + ', ' + calleNumero : calleNumero;
    }
    return p.nombre || '';
  }

  function componer(p, numeroExtra) {
    return unir([via(p, numeroExtra), p.comuna, p.region, p.cp]);
  }

  // Nominatim (búsqueda y búsqueda inversa con addressdetails=1)
  function partesNominatim(r, conNombre) {
    var a = (r && r.address) || {};
    var calle = a.road || a.pedestrian || a.footway || a.path || '';
    // En el Gran Santiago OpenStreetMap entrega "Santiago" como ciudad y la comuna en "suburb".
    var comuna = (a.city === 'Santiago' && a.suburb) ? a.suburb
      : (a.city || a.town || a.village || a.municipality || a.city_district || a.suburb || '');
    return {
      nombre: (conNombre && r.name && r.name !== calle) ? r.name : '',
      calle: calle,
      numero: a.house_number || '',
      comuna: comuna,
      region: regionCorta(a.state),
      cp: a.postcode || ''
    };
  }

  function desdeNominatim(r) {
    var partes = partesNominatim(r, true);
    var lat = parseFloat(r.lat), lng = parseFloat(r.lon);
    if ((!partes.calle && !partes.nombre) || isNaN(lat) || isNaN(lng)) { return null; }
    return {
      etiqueta: unir([via(partes), partes.comuna]),
      direccion: componer(partes),
      partes: partes,
      sinNumero: !partes.numero,
      lat: lat,
      lng: lng
    };
  }

  // Photon (sugerencias mientras se escribe)
  function desdePhoton(f) {
    var p = f.properties || {};
    var c = f.geometry && f.geometry.coordinates;
    if (!c || (p.countrycode && p.countrycode !== 'CL')) { return null; }
    var esLugar = p.osm_key === 'place' && !p.street; // ciudad, barrio o comuna: no es una dirección
    var calle = p.street || ((!esLugar && p.osm_key === 'highway') ? (p.name || '') : '');
    var partes = {
      nombre: (p.name && p.name !== calle) ? p.name : '',
      calle: calle,
      numero: p.housenumber || '',
      // En el Gran Santiago la comuna viene en "district"; una ciudad o localidad no lleva comuna aparte.
      comuna: esLugar ? '' : (p.district || p.city || p.county || ''),
      region: regionCorta(p.state),
      cp: p.postcode || ''
    };
    if (!partes.calle && !partes.nombre) { return null; }
    return {
      etiqueta: unir([via(partes), partes.comuna]),
      direccion: componer(partes),
      partes: partes,
      sinNumero: !partes.numero,
      lat: c[1],
      lng: c[0]
    };
  }

  function sinRepetidos(lista_) {
    var vistos = {};
    return lista_.filter(function (s) {
      if (!s || vistos[s.direccion]) { return false; }
      vistos[s.direccion] = true;
      return true;
    });
  }

  function consultarPhoton(texto, senal) {
    var url = URL_PHOTON + '?limit=6&bbox=' + BBOX_CHILE + '&lat=' + tiendaLat + '&lon=' + tiendaLng +
      '&q=' + encodeURIComponent(texto);
    return fetch(url, { signal: senal, headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        if (!r.ok) { throw new Error('photon'); }
        return r.json();
      })
      .then(function (geo) { return sinRepetidos((geo.features || []).map(desdePhoton)); });
  }

  function consultarNominatim(texto) {
    var url = URL_BUSQUEDA + '?format=jsonv2&limit=6&countrycodes=cl&accept-language=es&addressdetails=1&q=' +
      encodeURIComponent(texto);
    if (limites) {
      // Prioriza resultados dentro de La Florida sin descartar los de afuera (para poder avisar "fuera de zona").
      url += '&viewbox=' + [limites[0] - 0.02, limites[3] + 0.02, limites[2] + 0.02, limites[1] - 0.02].join(',');
    }
    return fetch(url, { referrerPolicy: POLITICA_REFERER, headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        if (!r.ok) { throw new Error('nominatim'); }
        return r.json();
      })
      .then(function (datos) { return sinRepetidos(datos.map(desdeNominatim)); });
  }

  // ---------- lista de sugerencias (patrón "combobox")
  function cerrarSugerencias() {
    lista.hidden = true;
    lista.textContent = '';
    sugerencias = [];
    indiceActivo = -1;
    campoDireccion.setAttribute('aria-expanded', 'false');
    campoDireccion.removeAttribute('aria-activedescendant');
  }

  function marcarActiva(indice) {
    var opciones = lista.querySelectorAll('[role="option"]');
    indiceActivo = indice;
    opciones.forEach(function (op, i) {
      op.setAttribute('aria-selected', i === indice ? 'true' : 'false');
    });
    if (indice >= 0 && opciones[indice]) {
      campoDireccion.setAttribute('aria-activedescendant', opciones[indice].id);
      opciones[indice].scrollIntoView({ block: 'nearest' });
    } else {
      campoDireccion.removeAttribute('aria-activedescendant');
    }
  }

  function mostrarSugerencias(resultados) {
    sugerencias = resultados;
    lista.textContent = '';
    resultados.forEach(function (s, i) {
      var opcion = document.createElement('li');
      opcion.id = 'zona-opcion-' + i;
      opcion.setAttribute('role', 'option');
      opcion.setAttribute('aria-selected', 'false');
      var texto = document.createElement('span');
      texto.className = 'zona__opcion-texto';
      texto.textContent = s.etiqueta;
      opcion.appendChild(texto);
      if (s.sinNumero) {
        var aviso = document.createElement('span');
        aviso.className = 'zona__opcion-detalle';
        aviso.textContent = 'sin número en el mapa';
        opcion.appendChild(aviso);
      }
      // mousedown y no click: así se elige antes de que el campo pierda el foco
      opcion.addEventListener('mousedown', function (e) {
        e.preventDefault();
        elegirSugerencia(i);
      });
      lista.appendChild(opcion);
    });
    lista.hidden = !resultados.length;
    campoDireccion.setAttribute('aria-expanded', resultados.length ? 'true' : 'false');
    indiceActivo = -1;
  }

  // La calle sin el número ("Marigen 9795" -> "marigen"): sirve para saber si cambiaron de calle.
  function normalizarCalle(segmento) {
    var m = RE_NUMERO.exec(segmento);
    if (m) { segmento = segmento.slice(0, m.index); }
    return segmento.toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function parteCalle(texto) {
    return normalizarCalle(texto.split(',')[0]);
  }

  // Las dos primeras partes (el nombre del lugar y la calle) de una dirección ya normalizadas.
  function callesDe(texto) {
    return texto.split(',').slice(0, 2).map(normalizarCalle).filter(Boolean);
  }

  function elegirSugerencia(indice) {
    var s = sugerencias[indice];
    if (!s) { return; }
    clearTimeout(temporizadorEscribiendo);
    numeroConsulta++; // descarta cualquier consulta que siga en camino
    campoDireccion.value = s.direccion;
    ultimoGenerado = s.direccion;
    base = s.partes;
    campoNumero.value = '';
    callesElegidas = callesDe(s.direccion);
    comunaElegida = (s.partes.comuna || '').toLowerCase();
    cerrarSugerencias();
    ponerPunto(s.lat, s.lng, 'busqueda');
    if (!bloqueNumero.hidden) { campoNumero.focus(); } // falta el número: se pide enseguida
  }

  function pedirSugerencias(texto) {
    if (controlSugerencias) { controlSugerencias.abort(); }
    controlSugerencias = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    var consulta = ++numeroConsulta;

    consultarPhoton(texto, controlSugerencias ? controlSugerencias.signal : undefined)
      .then(function (resultados) {
        if (consulta !== numeroConsulta) { return; }
        if (resultados.length) {
          mostrarSugerencias(resultados);
        } else {
          cerrarSugerencias();
          mostrar('No encontramos coincidencias todavía. Prueba con calle, número y comuna, ' +
            'o haz clic en el mapa para marcar tu ubicación.', 'info');
        }
      })
      .catch(function (error) {
        if (consulta !== numeroConsulta || (error && error.name === 'AbortError')) { return; }
        cerrarSugerencias();
        mostrar('No pudimos cargar sugerencias ahora. Toca «Buscar dirección» o haz clic en el mapa.', 'info');
      });
  }

  // ---------- mapa (opcional: sin Leaflet igual se puede buscar y validar)
  function iniciarMapa() {
    if (mapa || typeof L === 'undefined') { return; }

    contenedorMapa.hidden = false;
    mapa = L.map(contenedorMapa, { scrollWheelZoom: false });
    mapa.setView([tiendaLat, tiendaLng], 13);

    var capaBase = L.tileLayer(URL_TESELAS, {
      maxZoom: 19,
      attribution: ATRIBUCION,
      referrerPolicy: POLITICA_REFERER
    }).addTo(mapa);

    // Si OpenStreetMap bloquea las teselas, se quita el fondo de calles y se sigue con el contorno.
    var punto = mapa.project([tiendaLat, tiendaLng], 13).divideBy(256).floor();
    var urlPrueba = URL_TESELAS.replace('{z}', 13).replace('{x}', punto.x).replace('{y}', punto.y);
    fetch(urlPrueba, { referrerPolicy: POLITICA_REFERER })
      .then(function (r) { if (!r.ok) { throw new Error('teselas'); } })
      .catch(function () { mapa.removeLayer(capaBase); });

    var iconoTienda = L.divIcon({ className: 'mapa-pin', html: '<span></span>', iconSize: [28, 28], iconAnchor: [14, 14] });
    L.marker([tiendaLat, tiendaLng], {
      icon: iconoTienda, title: 'Nuestro local', alt: 'Nuestro local', interactive: false, keyboard: false
    }).addTo(mapa);

    mapa.on('click', function (e) { ponerPunto(e.latlng.lat, e.latlng.lng, 'mapa'); });

    cargarZona().then(function () {
      if (!zonaGeo || !mapa) { return; }
      var contorno = L.geoJSON(zonaGeo, {
        interactive: false,
        style: { color: '#b4532a', weight: 2.5, fillColor: '#b4532a', fillOpacity: 0.14 },
        attribution: ATRIBUCION
      }).addTo(mapa);
      mapa.invalidateSize();
      if (!pin) { mapa.fitBounds(contorno.getBounds(), { padding: [16, 16], animate: false }); }
      evaluar(); // por si el punto llegó antes de tener la zona
    });

    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(function () { mapa.invalidateSize({ pan: false }); }).observe(contenedorMapa);
    }
  }

  // Al mover el pin o hacer clic en el mapa, se escribe en el campo la dirección de ese punto.
  function direccionDelPunto(lat, lng) {
    clearTimeout(temporizadorDireccion);
    var consulta = ++consultaDireccion;
    // Espera medio segundo: si se sigue moviendo el pin, no se consulta en cada clic (Nominatim pide poco uso).
    temporizadorDireccion = setTimeout(function () {
      var textoAntes = campoDireccion.value;
      mostrar('Buscando la dirección de este punto…', 'info');
      var url = URL_INVERSA + '?format=jsonv2&zoom=18&addressdetails=1&accept-language=es' +
        '&lat=' + encodeURIComponent(lat.toFixed(6)) + '&lon=' + encodeURIComponent(lng.toFixed(6));

      fetch(url, { referrerPolicy: POLITICA_REFERER, headers: { 'Accept': 'application/json' } })
        .then(function (r) {
          if (!r.ok) { throw new Error('inversa'); }
          return r.json();
        })
        .then(function (datos) {
          if (consulta !== consultaDireccion) { return; } // el pin ya se movió a otro punto
          var partes = partesNominatim(datos, false);
          var texto = partes.calle ? componer(partes) : '';
          if (campoDireccion.value !== textoAntes) {
            evaluar(); // mientras tanto el cliente escribió algo: se respeta
          } else if (texto) {
            campoDireccion.value = texto;
            ultimoGenerado = texto;
            base = partes;
            campoNumero.value = '';
            evaluar('Dirección de este punto: ' + texto + '.');
          } else {
            evaluar('No encontramos una calle cerca de este punto: escribe tu dirección en el campo.');
          }
        })
        .catch(function () {
          if (consulta !== consultaDireccion) { return; }
          evaluar('No pudimos leer la dirección de este punto: escríbela en el campo.');
        });
    }, 500);
  }

  function ponerPunto(lat, lng, desde, sinMover) {
    campoLat.value = lat.toFixed(6);
    campoLng.value = lng.toFixed(6);
    origen = desde;

    if (mapa) {
      var iconoCliente = L.divIcon({ className: 'mapa-pin mapa-pin--cliente', html: '<span></span>', iconSize: [28, 28], iconAnchor: [14, 14] });
      if (!pin) {
        pin = L.marker([lat, lng], { icon: iconoCliente, draggable: true, title: 'Tu ubicación', alt: 'Tu ubicación' }).addTo(mapa);
        pin.on('dragend', function () {
          var p = pin.getLatLng();
          ponerPunto(p.lat, p.lng, 'mapa', true);
        });
      } else if (!sinMover) {
        pin.setLatLng([lat, lng]);
      }
      if (!sinMover) { mapa.setView([lat, lng], Math.max(mapa.getZoom(), 16), { animate: false }); }
    }
    cerrarSugerencias();
    evaluar();
    if (desde === 'mapa') { direccionDelPunto(lat, lng); }
  }

  function quitarPunto() {
    clearTimeout(temporizadorDireccion);
    consultaDireccion++; // cancela cualquier consulta de dirección que siga en camino
    campoLat.value = '';
    campoLng.value = '';
    origen = '';
    callesElegidas = [];
    comunaElegida = '';
    motivoBloqueo = 'direccion';
    base = null;
    ultimoGenerado = '';
    campoNumero.value = '';
    bloqueNumero.hidden = true;
    if (pin && mapa) { mapa.removeLayer(pin); }
    pin = null;
  }

  // ---------- botón "Buscar dirección" (también al presionar Enter sin sugerencias)
  function buscar() {
    var texto = campoDireccion.value.trim();
    if (!texto) {
      mostrar('Escribe tu dirección (calle y número) para buscarla.', 'error');
      campoDireccion.focus();
      return;
    }
    clearTimeout(temporizadorEscribiendo);
    var consulta = ++numeroConsulta;
    botonBuscar.disabled = true;
    cerrarSugerencias();
    mostrar('Buscando tu dirección…', 'info');

    // Primero Photon; si falla o no encuentra nada, Nominatim.
    consultarPhoton(texto)
      .then(function (resultados) {
        return resultados.length ? resultados : consultarNominatim(texto);
      })
      .catch(function () { return consultarNominatim(texto); })
      .then(function (resultados) {
        if (consulta !== numeroConsulta) { return; }
        if (!resultados.length) {
          quitarPunto();
          confirmado = false;
          mostrar('No encontramos esa dirección. Revisa la calle y el número, o haz clic en el mapa para marcar tu ubicación.', 'error');
          actualizarEnvio();
        } else if (resultados.length === 1) {
          sugerencias = resultados;
          elegirSugerencia(0);
        } else {
          quitarPunto();
          confirmado = false;
          mostrar('Encontramos varias coincidencias. Elige la tuya:', 'info');
          mostrarSugerencias(resultados);
          actualizarEnvio();
        }
      })
      .catch(function () {
        mostrar('No pudimos buscar la dirección ahora. Haz clic en el mapa para marcar tu ubicación, o elige retiro en tienda.', 'error');
      })
      .then(function () { botonBuscar.disabled = false; });
  }

  // ---------- eventos
  function alternar() {
    var despacho = esDespacho();
    panel.hidden = !despacho;
    if (despacho) {
      cargarZona().then(evaluar);
      iniciarMapa();
      if (mapa) { mapa.invalidateSize(); }
      if (!campoLat.value && campoDireccion.value.trim() && !busquedaAutomaticaHecha) {
        // Cliente registrado: se ubica la dirección que dejó al crear su cuenta.
        busquedaAutomaticaHecha = true;
        buscar();
      } else if (!campoLat.value) {
        mostrar(TEXTO_INICIAL, 'info');
      }
    }
    actualizarEnvio();
  }

  form.querySelectorAll('input[name="tipo_entrega"]').forEach(function (radio) {
    radio.addEventListener('change', alternar);
  });
  botonBuscar.addEventListener('click', buscar);

  // El campo de dirección se comporta como un cuadro de búsqueda con lista de sugerencias.
  campoDireccion.setAttribute('role', 'combobox');
  campoDireccion.setAttribute('aria-autocomplete', 'list');
  campoDireccion.setAttribute('aria-haspopup', 'listbox');
  campoDireccion.setAttribute('aria-expanded', 'false');
  campoDireccion.setAttribute('aria-controls', lista.id);
  campoDireccion.setAttribute('autocomplete', 'off'); // para que no tape las sugerencias propias

  campoDireccion.addEventListener('input', function () {
    var texto = campoDireccion.value;

    // Si el cliente editó el texto a mano, el número se agrega ahí mismo y no desde el campo "Número".
    if (texto !== ultimoGenerado) { campoNumero.value = ''; }

    // Si el punto vino de una sugerencia y cambiaron la calle o la comuna, ya no corresponde. Agregar el
    // número o el departamento no cambia nada de eso, así que el punto se mantiene.
    if (origen === 'busqueda' && (callesElegidas.indexOf(parteCalle(texto)) === -1 ||
        (comunaElegida && texto.toLowerCase().indexOf(comunaElegida) === -1))) {
      quitarPunto();
      confirmado = false;
      mostrar('Cambiaste la calle o la comuna: elige una sugerencia de la lista para ubicarla.', 'info');
      actualizarEnvio();
    } else if (campoLat.value) {
      evaluar();
    }

    clearTimeout(temporizadorEscribiendo);
    if (texto.trim().length < MIN_CARACTERES) {
      numeroConsulta++;
      cerrarSugerencias();
      return;
    }
    temporizadorEscribiendo = setTimeout(function () { pedirSugerencias(texto.trim()); }, ESPERA_ESCRIBIENDO_MS);
  });

  // Campo "Número": se inserta solo en la dirección completa, justo después de la calle.
  campoNumero.addEventListener('input', function () {
    var limpio = campoNumero.value.replace(/[^0-9A-Za-z\/\-]/g, '').slice(0, 10);
    if (campoNumero.value !== limpio) { campoNumero.value = limpio; }
    if (puedeAgregarNumero()) {
      campoDireccion.value = componer(base, limpio);
      ultimoGenerado = campoDireccion.value;
    }
    evaluar();
  });
  campoNumero.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); }
  });

  campoDireccion.addEventListener('keydown', function (e) {
    var hay = !lista.hidden && sugerencias.length > 0;
    if (e.key === 'ArrowDown' && hay) {
      e.preventDefault();
      marcarActiva((indiceActivo + 1) % sugerencias.length);
    } else if (e.key === 'ArrowUp' && hay) {
      e.preventDefault();
      marcarActiva(indiceActivo <= 0 ? sugerencias.length - 1 : indiceActivo - 1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (hay) {
        elegirSugerencia(indiceActivo >= 0 ? indiceActivo : 0);
      } else {
        buscar();
      }
    } else if (e.key === 'Escape' && hay) {
      e.preventDefault();
      cerrarSugerencias();
    }
  });

  // Al salir del campo se cierra la lista (con un respiro para poder hacer clic en una opción).
  campoDireccion.addEventListener('blur', function () {
    setTimeout(function () {
      if (document.activeElement !== campoDireccion) { cerrarSugerencias(); }
    }, 150);
  });

  form.addEventListener('submit', function (e) {
    if (esDespacho() && !confirmado) {
      e.preventDefault();
      campoDireccion.focus();
      if (!campoLat.value) { mostrar(TEXTO_INICIAL, 'error'); }
    }
  });

  // El carrito cambió sin recargar la página (static/js/carrito_estado.js): el servidor pudo habilitar o
  // bloquear la compra, así que se vuelve a calcular el botón sin tocar la dirección ni el mapa.
  form.addEventListener('carrito:actualizado', actualizarEnvio);

  alternar();
})();
