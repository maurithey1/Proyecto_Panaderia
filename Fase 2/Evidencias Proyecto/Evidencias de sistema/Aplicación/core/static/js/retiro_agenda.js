/* Agenda del carrito: elegir el día y la hora de retiro o de entrega. Las franjas las calcula el servidor
   (core/retiro.py) y ya vienen filtradas por los turnos de los productos del carrito.
   Sin JavaScript el formulario igual envía la primera franja disponible.

   Cuando el carrito cambia (static/js/carrito_estado.js) el bloque de la agenda se reemplaza por el que
   calculó el servidor y se vuelve a iniciar con window.reiniciarAgenda(). */
(function () {
  var local = document.getElementById('retiro-panel');    // tarjeta del local: solo con retiro
  var base = local || document.getElementById('agenda-panel');
  if (!base) { return; }

  var form = base.closest('form');
  var selectorDia, selectorHora, campoFecha, resumen, leyenda;
  var dias = [];

  // Toma los elementos actuales (el bloque de la agenda se reemplaza cuando cambia el carrito).
  function capturar() {
    selectorDia = document.getElementById('retiro-dia');
    selectorHora = document.getElementById('retiro-hora');
    campoFecha = document.getElementById('retiro-fecha');
    resumen = document.getElementById('retiro-resumen');
    leyenda = document.getElementById('agenda-leyenda');
    var datosEl = document.getElementById('retiro-datos');
    try {
      dias = datosEl ? JSON.parse(datosEl.textContent) : [];
    } catch (e) {
      dias = [];
    }
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

  // Llena las horas del día elegido. Se conserva la hora que estaba elegida solo si ese día la ofrece;
  // si no, queda la primera (asignar un valor inexistente deja el selector vacío y el envío fallaría).
  function llenarHoras(horaPreferida) {
    var dia = diaActual();
    if (!dia || !selectorHora) { return; }
    var deseada = (typeof horaPreferida === 'string' && horaPreferida) ? horaPreferida : selectorHora.value;
    selectorHora.textContent = '';
    dia.horas.forEach(function (h) {
      var opcion = document.createElement('option');
      opcion.value = h.valor;
      opcion.textContent = h.texto;
      selectorHora.appendChild(opcion);
    });
    var existe = dia.horas.some(function (h) { return h.valor === deseada; });
    selectorHora.value = existe ? deseada : dia.horas[0].valor;
    if (campoFecha) { campoFecha.value = dia.fecha; }
    actualizarResumen();
  }

  function alternar() {
    if (local) { local.hidden = !esRetiro(); }   // la tarjeta del local solo tiene sentido con retiro
    if (leyenda) { leyenda.textContent = esRetiro() ? 'Programa tu retiro' : 'Programa tu entrega'; }
    actualizarResumen();
  }

  // `conservar` ({fecha, hora}) mantiene lo que el cliente había elegido, si todavía se ofrece.
  function iniciar(conservar) {
    capturar();
    if (selectorDia && dias.length) {
      selectorDia.disabled = false; // viene deshabilitado para que, sin JavaScript, solo se use el primer día
      selectorDia.addEventListener('change', function () { llenarHoras(); });
      if (selectorHora) { selectorHora.addEventListener('change', actualizarResumen); }
      var fecha = conservar && conservar.fecha;
      if (fecha && dias.some(function (d) { return d.fecha === fecha; })) { selectorDia.value = fecha; }
      llenarHoras(conservar && conservar.hora);
    }
    alternar();
  }

  form.querySelectorAll('input[name="tipo_entrega"]').forEach(function (radio) {
    radio.addEventListener('change', alternar);
  });

  window.reiniciarAgenda = iniciar;
  iniciar();
})();
