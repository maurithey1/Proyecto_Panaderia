/* Agenda del carrito: elegir el día y la hora de retiro o de entrega. Las franjas las calcula el servidor
   (core/retiro.py) y ya vienen filtradas por los turnos de los productos del carrito.
   Sin JavaScript el formulario igual envía la primera franja disponible. */
(function () {
  var local = document.getElementById('retiro-panel');    // tarjeta del local: solo con retiro
  var agenda = document.getElementById('agenda-panel');   // día y hora: con retiro y con despacho
  var base = local || agenda;
  if (!base) { return; }

  var form = base.closest('form');
  var selectorDia = document.getElementById('retiro-dia');
  var selectorHora = document.getElementById('retiro-hora');
  var campoFecha = document.getElementById('retiro-fecha');
  var resumen = document.getElementById('retiro-resumen');
  var leyenda = document.getElementById('agenda-leyenda');
  var datosEl = document.getElementById('retiro-datos');
  var dias = [];

  try {
    dias = datosEl ? JSON.parse(datosEl.textContent) : [];
  } catch (e) {
    dias = [];
  }

  function esRetiro() {
    var elegido = form.querySelector('input[name="tipo_entrega"]:checked');
    return !elegido || elegido.value === 'RETIRO';
  }

  function diaActual() {
    for (var i = 0; i < dias.length; i++) {
      if (dias[i].fecha === (selectorDia ? selectorDia.value : '')) { return dias[i]; }
    }
    return dias[0] || null;
  }

  function actualizarResumen() {
    if (!resumen) { return; }
    var dia = diaActual();
    var hora = selectorHora && selectorHora.options[selectorHora.selectedIndex];
    var verbo = esRetiro() ? 'Retiras ' : 'Recibes ';
    resumen.textContent = (dia && hora) ? verbo + dia.etiqueta.charAt(0).toLowerCase() + dia.etiqueta.slice(1) +
      ', de ' + hora.textContent + '.' : '';
  }

  function llenarHoras() {
    var dia = diaActual();
    if (!dia || !selectorHora) { return; }
    var anterior = selectorHora.value;
    selectorHora.textContent = '';
    dia.horas.forEach(function (h) {
      var opcion = document.createElement('option');
      opcion.value = h.valor;
      opcion.textContent = h.texto;
      selectorHora.appendChild(opcion);
    });
    // Si la hora que estaba elegida existe ese día, se conserva.
    if (anterior) { selectorHora.value = anterior; }
    if (campoFecha) { campoFecha.value = dia.fecha; }
    actualizarResumen();
  }

  function alternar() {
    if (local) { local.hidden = !esRetiro(); }   // la tarjeta del local solo tiene sentido con retiro
    if (leyenda) { leyenda.textContent = esRetiro() ? 'Programa tu retiro' : 'Programa tu entrega'; }
    actualizarResumen();
  }

  if (selectorDia && dias.length) {
    selectorDia.disabled = false; // viene deshabilitado para que, sin JavaScript, solo se use el primer día
    selectorDia.addEventListener('change', llenarHoras);
    llenarHoras();
  }
  if (selectorHora) { selectorHora.addEventListener('change', actualizarResumen); }

  form.querySelectorAll('input[name="tipo_entrega"]').forEach(function (radio) {
    radio.addEventListener('change', alternar);
  });
  alternar();
})();
