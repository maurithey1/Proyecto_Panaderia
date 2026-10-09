/* Mapa estático de la página Local: ubicación de la tienda y zona de despacho */
(function () {
  var contenedor = document.getElementById('mapa-cobertura');
  if (!contenedor || typeof L === 'undefined') {
    return; // sin Leaflet (sin internet) queda el texto de la página
  }

  var lat = parseFloat(contenedor.dataset.lat);
  var lng = parseFloat(contenedor.dataset.lng);
  var nombre = contenedor.dataset.nombre;
  var aviso = document.getElementById('mapa-aviso');

  var ATRIBUCION = '&copy; <a href="https://www.openstreetmap.org/copyright">Colaboradores de OpenStreetMap</a>';
  var URL_TESELAS = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  var ZOOM_INICIAL = 13;
  // Django envía "Referrer-Policy: same-origin", y OpenStreetMap exige un Referer válido en sus teselas.
  // Se indica explícitamente que a otros sitios solo se envíe el origen (sin la ruta).
  var POLITICA_REFERER = 'strict-origin-when-cross-origin';

  var mapa = L.map(contenedor, {
    zoomControl: false,
    dragging: false,
    scrollWheelZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
    touchZoom: false,
    tapHold: false,
    zoomSnap: 0,
    zoomAnimation: false,
    fadeAnimation: false,
    markerZoomAnimation: false
  });
  mapa.setView([lat, lng], ZOOM_INICIAL);

  var capaBase = L.tileLayer(URL_TESELAS, {
    maxZoom: 19,
    attribution: ATRIBUCION,
    referrerPolicy: POLITICA_REFERER
  }).addTo(mapa);

  var pin = L.divIcon({ className: 'mapa-pin', html: '<span></span>', iconSize: [28, 28], iconAnchor: [14, 14] });
  L.marker([lat, lng], {
    icon: pin, title: nombre, alt: nombre, interactive: false, keyboard: false
  }).addTo(mapa);

  // Si OpenStreetMap bloquea las teselas (error 403), el navegador igual dibuja la imagen de error
  // y Leaflet no lo detecta. Se prueba una tesela: si falla, se quita el mapa de calles y se avisa.
  // La zona y el local siguen visibles sobre el fondo liso.
  var punto = mapa.project([lat, lng], ZOOM_INICIAL).divideBy(256).floor();
  var urlPrueba = URL_TESELAS.replace('{z}', ZOOM_INICIAL).replace('{x}', punto.x).replace('{y}', punto.y);
  fetch(urlPrueba, { referrerPolicy: POLITICA_REFERER })
    .then(function (respuesta) {
      if (!respuesta.ok) { throw new Error('Teselas no disponibles: ' + respuesta.status); }
    })
    .catch(function () {
      mapa.removeLayer(capaBase);
      if (aviso) { aviso.hidden = false; }
    });

  // La vista se ajusta al contorno de la zona de despacho, con un margen pequeño.
  var limites = null;

  function encuadrar() {
    if (limites) {
      mapa.fitBounds(limites, { padding: [20, 20], animate: false });
    }
  }

  fetch(contenedor.dataset.geojson)
    .then(function (respuesta) { return respuesta.json(); })
    .then(function (geo) {
      var zona = L.geoJSON(geo, {
        interactive: false,
        style: { color: '#b4532a', weight: 2.5, fillColor: '#b4532a', fillOpacity: 0.14 },
        attribution: ATRIBUCION // el contorno viene de OpenStreetMap
      }).addTo(mapa);
      limites = zona.getBounds();
      mapa.invalidateSize();
      encuadrar();
    })
    .catch(function () { /* sin el contorno, el mapa sigue mostrando el local */ });

  // Conserva el encuadre al cambiar el tamaño de la ventana o acomodarse la página.
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(function () {
      mapa.invalidateSize({ pan: false });
      encuadrar();
    }).observe(contenedor);
  }
})();
