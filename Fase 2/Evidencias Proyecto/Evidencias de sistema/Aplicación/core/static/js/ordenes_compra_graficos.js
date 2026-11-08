// ==========================================================================
// Gráficos interactivos de adquisición (órdenes de compra a molineras)
// Al pulsar el icono de gráfico se despliega el panel; al marcar un elemento se despliega su detalle.
// ==========================================================================
document.addEventListener('DOMContentLoaded', function () {
  const boton = document.getElementById('btnGraficosAdquisicion');
  const panel = document.getElementById('panelGraficosAdquisicion');
  if (!boton || !panel || !window.Chart) return;

  const paleta = ['#b4532a', '#e3b25b', '#7b4b2a', '#c8a27a', '#8d5b4c', '#2d7a4f', '#d9822b', '#6e5848'];
  const dinero = (v) => '$' + Math.round(v || 0).toLocaleString('es-CL');
  let cargado = false;

  const crear = (etiqueta, clase, texto) => {
    const el = document.createElement(etiqueta);
    if (clase) el.className = clase;
    if (texto !== undefined) el.textContent = texto;
    return el;
  };

  const tabla = (columnas, filas) => {
    const t = crear('table', 'kpi-detalle__tabla');
    const cab = crear('tr');
    columnas.forEach((c) => cab.appendChild(crear('th', '', c)));
    t.appendChild(cab);
    filas.forEach((fila) => {
      const tr = crear('tr');
      fila.forEach((celda) => tr.appendChild(crear('td', '', celda)));
      t.appendChild(tr);
    });
    return t;
  };

  const detalle = document.getElementById('detalleGraficosAdquisicion');

  function mostrarDetalle(info) {
    detalle.replaceChildren();
    const cab = crear('div', 'kpi-detalle__cabecera');
    cab.appendChild(crear('strong', '', `Detalle: ${info.titulo}`));
    const cerrar = crear('button', 'kpi-detalle__cerrar', 'Cerrar ✕');
    cerrar.type = 'button';
    cerrar.addEventListener('click', () => { detalle.hidden = true; });
    cab.appendChild(cerrar);
    detalle.appendChild(cab);

    detalle.appendChild(crear('p', 'kpi-detalle__resumen',
      `${info.total_ordenes} órdenes · ${dinero(info.total_monto)} · ${info.total_kilos.toLocaleString('es-CL')} kg`));
    if (info.materias.length) {
      detalle.appendChild(crear('p', 'kpi-detalle__subtitulo', 'Materias primas'));
      detalle.appendChild(tabla(['Materia prima', 'Kilos', 'Monto'],
        info.materias.map((m) => [m.nombre, m.kilos.toLocaleString('es-CL'), dinero(m.monto)])));
    }
    if (info.ordenes.length) {
      detalle.appendChild(crear('p', 'kpi-detalle__subtitulo', 'Órdenes de compra'));
      detalle.appendChild(tabla(['Código', 'Fecha', 'Molinera', 'Estado', 'Total'],
        info.ordenes.map((o) => [o.codigo, o.fecha, o.proveedor, o.estado, dinero(o.total)])));
    } else {
      detalle.appendChild(crear('p', 'kpi-detalle__vacio', 'Sin órdenes registradas.'));
    }
    detalle.hidden = false;
  }

  async function cargarDetalle(tipo, valor) {
    detalle.replaceChildren(crear('p', 'kpi-detalle__vacio', 'Cargando detalle…'));
    detalle.hidden = false;
    try {
      const params = new URLSearchParams({ tipo, valor });
      const r = await fetch(`${panel.dataset.urlDetalle}?${params}`, { credentials: 'same-origin' });
      if (!r.ok) throw new Error('Respuesta no válida');
      mostrarDetalle(await r.json());
    } catch (e) {
      detalle.replaceChildren(crear('p', 'kpi-detalle__vacio', 'No se pudo cargar el detalle. Intenta nuevamente.'));
    }
  }

  // Crea un gráfico que al marcar un elemento pide su detalle
  function grafico(idCanvas, tipoGrafico, etiquetas, valores, tipoDetalle, claves, formato) {
    const canvas = document.getElementById(idCanvas);
    const hay = valores.length > 0;
    const opciones = {
      responsive: true,
      maintainAspectRatio: false,
      onHover: (e, el) => { e.native.target.style.cursor = hay && el.length ? 'pointer' : 'default'; },
      onClick: (e, el) => {
        if (hay && el.length) cargarDetalle(tipoDetalle, (claves || etiquetas)[el[0].index]);
      },
      plugins: {
        legend: { display: tipoGrafico !== 'bar', position: 'bottom', labels: { boxWidth: 12 } },
        tooltip: { callbacks: { label: (c) => ` ${c.label}: ${formato(c.raw)}` } },
      },
    };
    if (tipoGrafico === 'bar') {
      opciones.indexAxis = 'y';
      opciones.scales = { x: { beginAtZero: true, ticks: { callback: (v) => dinero(v) } }, y: { grid: { display: false } } };
    }
    new Chart(canvas, {
      type: tipoGrafico,
      data: {
        labels: hay ? etiquetas : ['Sin datos'],
        datasets: [{ data: hay ? valores : [1], backgroundColor: hay ? paleta : ['#e6d5bc'], borderColor: '#ffffff', borderWidth: 2, borderRadius: tipoGrafico === 'bar' ? 6 : 0 }],
      },
      options: opciones,
    });
  }

  async function iniciar() {
    try {
      const r = await fetch(panel.dataset.urlDatos, { credentials: 'same-origin' });
      if (!r.ok) throw new Error('Respuesta no válida');
      const d = await r.json();
      document.getElementById('resumenGraficosAdquisicion').textContent =
        `${d.total_ordenes} órdenes emitidas · ${dinero(d.total_gastado)} en compras (sin canceladas). Marca un elemento para ver su detalle.`;
      grafico('graficoAdqProveedores', 'doughnut', d.proveedores_nombres, d.proveedores_montos, 'proveedor', null, dinero);
      grafico('graficoAdqEstados', 'pie', d.estados_nombres, d.estados_cantidades, 'estado', d.estados_claves, (v) => `${v} órdenes`);
      grafico('graficoAdqInsumos', 'bar', d.insumos_nombres, d.insumos_montos, 'insumo', null, dinero);
      cargado = true;
    } catch (e) {
      document.getElementById('resumenGraficosAdquisicion').textContent = 'No se pudieron cargar los gráficos. Intenta nuevamente.';
    }
  }

  boton.addEventListener('click', function () {
    panel.hidden = !panel.hidden;
    boton.setAttribute('aria-expanded', String(!panel.hidden));
    if (!panel.hidden && !cargado) iniciar();
  });
});