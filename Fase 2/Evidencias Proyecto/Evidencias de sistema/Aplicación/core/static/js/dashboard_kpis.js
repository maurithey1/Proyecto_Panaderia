// ==========================================================================
// Dashboard de Indicadores Clave (KPIs) - Panadería Los Tres Spa
// Integración de gráficos interactivos con Chart.js y paleta de diseño artesanal
// ==========================================================================

document.addEventListener('DOMContentLoaded', function () {
  const jsonElem = document.getElementById('datos-kpi-json');
  if (!jsonElem) return;

  let datos = {};
  try {
    datos = JSON.parse(jsonElem.textContent);
  } catch (e) {
    console.error('Error al procesar los datos JSON de KPIs:', e);
    return;
  }

  // Paleta de colores oficial de la panadería Los Tres Spa
  const colores = {
    terracota: '#b4532a',
    terracotaSuave: 'rgba(180, 83, 42, 0.2)',
    cafe: '#7b4b2a',
    cafeOscuro: '#3e2a1d',
    cafeClaro: '#c8a27a',
    trigo: '#e3b25b',
    trigoClaro: '#f1d596',
    trigoSuave: 'rgba(227, 178, 91, 0.2)',
    verdeExito: '#2d7a4f',
    crema: '#fbf5ea',
    grisBorde: '#e6d5bc',
    paletaMultiple: [
      '#b4532a', // Terracota
      '#e3b25b', // Trigo
      '#7b4b2a', // Café
      '#c8a27a', // Café claro
      '#8d5b4c', // Madera
      '#2d7a4f', // Verde artesanal
      '#d9822b', // Naranja miel
      '#6e5848', // Texto suave
    ]
  };

  // Función auxiliar para formatear dinero en pesos chilenos ($)
  const formatearDinero = (val) => {
    return '$' + Math.round(val || 0).toLocaleString('es-CL');
  };

  // Configuración global de fuentes para Chart.js
  if (window.Chart) {
    Chart.defaults.font.family = "'Figtree', system-ui, -apple-system, sans-serif";
    Chart.defaults.color = '#3e2a1d';
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
  }

  // ==========================================================================
  // 1. Gráfico de Evolución Temporal de Ingresos Diarios (POS vs Webpay)
  // ==========================================================================
  const ctxEvolucion = document.getElementById('graficoEvolucionVentas');
  if (ctxEvolucion && datos.evolucion_labels) {
    new Chart(ctxEvolucion, {
      type: 'line',
      data: {
        labels: datos.evolucion_labels,
        datasets: [
          {
            label: 'POS (Presencial)',
            data: datos.evolucion_pos,
            borderColor: colores.cafe,
            backgroundColor: 'rgba(123, 75, 42, 0.12)',
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointBackgroundColor: colores.cafe,
            pointRadius: 3,
            pointHoverRadius: 6,
          },
          {
            label: 'Webpay (Online)',
            data: datos.evolucion_web,
            borderColor: colores.terracota,
            backgroundColor: 'rgba(180, 83, 42, 0.12)',
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointBackgroundColor: colores.terracota,
            pointRadius: 3,
            pointHoverRadius: 6,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          legend: {
            display: false,
          },
          tooltip: {
            callbacks: {
              label: function (context) {
                return ` ${context.dataset.label}: ${formatearDinero(context.raw)}`;
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: {
              color: '#f0e3ce',
            },
            ticks: {
              callback: function (value) {
                return '$' + (value >= 1000 ? (value / 1000) + 'k' : value);
              }
            }
          },
          x: {
            grid: {
              display: false,
            }
          }
        }
      }
    });
  }

  // ==========================================================================
  // 2. Gráfico de Participación por Canal (POS vs Webpay)
  // ==========================================================================
  const ctxCanales = document.getElementById('graficoCanales');
  if (ctxCanales && datos.canales_montos) {
    const totalCanales = (datos.canales_montos[0] || 0) + (datos.canales_montos[1] || 0);
    new Chart(ctxCanales, {
      type: 'doughnut',
      data: {
        labels: datos.canales_labels,
        datasets: [{
          data: totalCanales > 0 ? datos.canales_montos : [1, 0],
          backgroundColor: [colores.cafe, colores.terracota],
          borderWidth: 2,
          borderColor: '#ffffff',
          hoverOffset: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: { boxWidth: 14, padding: 15 }
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                if (totalCanales === 0) return ' Sin registros en el período';
                const valor = ctx.raw;
                const porcentaje = ((valor / totalCanales) * 100).toFixed(1);
                return ` ${ctx.label}: ${formatearDinero(valor)} (${porcentaje}%)`;
              }
            }
          }
        }
      }
    });
  }

  // ==========================================================================
  // 3. Gráfico Top 5 Productos más Vendidos (Con Alternancia Interactiva)
  // ==========================================================================
  const ctxTop5 = document.getElementById('graficoTop5');
  if (ctxTop5 && datos.top5_nombres) {
    const hayDatosTop5 = datos.top5_montos && datos.top5_montos.length > 0;
    window.chartInstanciaTop5 = new Chart(ctxTop5, {
      type: 'bar',
      data: {
        labels: hayDatosTop5 ? datos.top5_nombres : ['Sin datos'],
        datasets: [{
          label: 'Recaudación ($)',
          data: hayDatosTop5 ? datos.top5_montos : [0],
          backgroundColor: colores.terracota,
          borderRadius: 6,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                const idx = ctx.dataIndex;
                const uds = (datos.top5_unidades && datos.top5_unidades[idx]) ? datos.top5_unidades[idx] : 0;
                if (window.metricaTop5Actual === 'unidades') {
                  const rec = (datos.top5_montos && datos.top5_montos[idx]) ? datos.top5_montos[idx] : 0;
                  return ` Vendidas: ${ctx.raw} unidades (${formatearDinero(rec)})`;
                }
                return ` Recaudado: ${formatearDinero(ctx.raw)} (${uds} unidades)`;
              }
            }
          }
        },
        scales: {
          x: {
            beginAtZero: true,
            grid: { color: '#f0e3ce' },
            ticks: {
              callback: (val) => {
                if (window.metricaTop5Actual === 'unidades') return val + ' un.';
                return '$' + (val >= 1000 ? (val / 1000) + 'k' : val);
              }
            }
          },
          y: {
            grid: { display: false }
          }
        }
      }
    });
  }

  // Función global para alternar la métrica del Top 5
  window.metricaTop5Actual = 'monto';
  window.cambiarMetricaTop5 = function (metrica) {
    if (!window.chartInstanciaTop5) return;
    window.metricaTop5Actual = metrica;

    const btnMonto = document.getElementById('btnTop5Monto');
    const btnUnidades = document.getElementById('btnTop5Unidades');
    const titulo = document.getElementById('tituloTop5');
    const bajada = document.getElementById('bajadaTop5');

    if (metrica === 'unidades') {
      window.chartInstanciaTop5.data.datasets[0].data = datos.top5_unidades || [];
      window.chartInstanciaTop5.data.datasets[0].label = 'Unidades Vendidas';
      window.chartInstanciaTop5.data.datasets[0].backgroundColor = colores.cafe;
      if (btnMonto) btnMonto.classList.remove('activo');
      if (btnUnidades) btnUnidades.classList.add('activo');
      if (titulo) titulo.textContent = 'Top 5 Productos por Unidades Vendidas';
      if (bajada) bajada.textContent = 'Ranking por volumen de unidades comercializadas';
    } else {
      window.chartInstanciaTop5.data.datasets[0].data = datos.top5_montos || [];
      window.chartInstanciaTop5.data.datasets[0].label = 'Recaudación ($)';
      window.chartInstanciaTop5.data.datasets[0].backgroundColor = colores.terracota;
      if (btnUnidades) btnUnidades.classList.remove('activo');
      if (btnMonto) btnMonto.classList.add('activo');
      if (titulo) titulo.textContent = 'Top 5 Productos más Vendidos ($)';
      if (bajada) bajada.textContent = 'Ranking por recaudación total en el período';
    }
    window.chartInstanciaTop5.update();
  };

  // ==========================================================================
  // 4. Gráfico de Ventas por Categoría
  // ==========================================================================
  const ctxCategorias = document.getElementById('graficoCategorias');
  if (ctxCategorias && datos.categorias_nombres) {
    const hayCategorias = datos.categorias_montos && datos.categorias_montos.length > 0;
    new Chart(ctxCategorias, {
      type: 'pie',
      data: {
        labels: hayCategorias ? datos.categorias_nombres : ['Sin registros'],
        datasets: [{
          data: hayCategorias ? datos.categorias_montos : [1],
          backgroundColor: colores.paletaMultiple,
          borderWidth: 2,
          borderColor: '#ffffff',
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { boxWidth: 12, padding: 12 }
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                if (!hayCategorias) return ' Sin registros';
                return ` ${ctx.label}: ${formatearDinero(ctx.raw)}`;
              }
            }
          }
        }
      }
    });
  }

  // ==========================================================================
  // 5. Gráfico de Preferencia de Entrega Web (Retiro vs Despacho)
  // ==========================================================================
  const ctxEntrega = document.getElementById('graficoEntregaWeb');
  if (ctxEntrega && datos.entrega_cantidades) {
    const totalEntregas = (datos.entrega_cantidades[0] || 0) + (datos.entrega_cantidades[1] || 0);
    new Chart(ctxEntrega, {
      type: 'doughnut',
      data: {
        labels: datos.entrega_labels,
        datasets: [{
          data: totalEntregas > 0 ? datos.entrega_cantidades : [1, 0],
          backgroundColor: [colores.trigo, colores.cafeClaro],
          borderWidth: 2,
          borderColor: '#ffffff',
          hoverOffset: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '65%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: { boxWidth: 14, padding: 15 }
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                if (totalEntregas === 0) return ' Sin pedidos online registrados';
                const cant = ctx.raw;
                const pct = ((cant / totalEntregas) * 100).toFixed(1);
                return ` ${ctx.label}: ${cant} pedidos (${pct}%)`;
              }
            }
          }
        }
      }
    });
  }

  // ==========================================================================
  // 6. Gráfico de Margen Bruto por Producto (%)
  // ==========================================================================
  const ctxMargenes = document.getElementById('graficoMargenes');
  if (ctxMargenes && datos.margenes_nombres) {
    const hayMargenes = datos.margenes_pct && datos.margenes_pct.length > 0;
    new Chart(ctxMargenes, {
      type: 'bar',
      data: {
        labels: hayMargenes ? datos.margenes_nombres : ['Sin recetas configuradas'],
        datasets: [{
          label: 'Margen de Rentabilidad (%)',
          data: hayMargenes ? datos.margenes_pct : [0],
          backgroundColor: colores.verdeExito,
          borderRadius: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                const idx = ctx.dataIndex;
                const precio = datos.margenes_precios[idx] || 0;
                const costo = datos.margenes_costos[idx] || 0;
                return [
                  ` Margen bruto: ${ctx.raw}%`,
                  ` Precio venta: ${formatearDinero(precio)}`,
                  ` Costo insumos: ${formatearDinero(costo)}`
                ];
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            max: 100,
            grid: { color: '#f0e3ce' },
            ticks: {
              callback: (val) => val + '%'
            }
          },
          x: {
            grid: { display: false }
          }
        }
      }
    });
  }

  // ==========================================================================
  // 7. Gráfico de Producción Diaria Horneada
  // ==========================================================================
  const ctxProduccion = document.getElementById('graficoProduccion');
  if (ctxProduccion && datos.produccion_labels) {
    new Chart(ctxProduccion, {
      type: 'bar',
      data: {
        labels: datos.produccion_labels,
        datasets: [{
          label: 'Unidades horneadas',
          data: datos.produccion_cantidades,
          backgroundColor: colores.trigo,
          borderColor: colores.cafeClaro,
          borderWidth: 1,
          borderRadius: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ` Horneado: ${ctx.raw} unidades`;
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: '#f0e3ce' },
            ticks: { precision: 0 }
          },
          x: {
            grid: { display: false }
          }
        }
      }
    });
  }

  // ==========================================================================
  // 8. Gráfico de Costo Total de Adquisición por Molinera (Saco + Flete)
  // ==========================================================================
  const ctxMolineras = document.getElementById('graficoMolineras');
  if (ctxMolineras && datos.molineras_nombres) {
    const hayMolineras = datos.molineras_nombres.length > 0;
    new Chart(ctxMolineras, {
      type: 'bar',
      data: {
        labels: hayMolineras ? datos.molineras_nombres : ['Sin proveedores'],
        datasets: [
          {
            label: 'Precio Saco ($)',
            data: hayMolineras ? datos.molineras_saco : [0],
            backgroundColor: colores.cafeClaro,
            stack: 'adquisicion',
            borderRadius: { topLeft: 0, topRight: 0, bottomLeft: 4, bottomRight: 4 }
          },
          {
            label: 'Costo de Flete ($)',
            data: hayMolineras ? datos.molineras_flete : [0],
            backgroundColor: colores.terracota,
            stack: 'adquisicion',
            borderRadius: { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 }
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { boxWidth: 12, padding: 10 }
          },
          tooltip: {
            callbacks: {
              footer: function (tooltipItems) {
                let total = 0;
                tooltipItems.forEach(item => { total += item.raw || 0; });
                return 'Total adquisición: ' + formatearDinero(total);
              }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false }
          },
          y: {
            beginAtZero: true,
            grid: { color: '#f0e3ce' },
            ticks: {
              callback: (val) => '$' + (val >= 1000 ? (val / 1000) + 'k' : val)
            }
          }
        }
      }
    });
  }

  // ==========================================================================
  // Interactividad: al marcar un canal, producto o categoría se despliega su detalle
  // ==========================================================================
  const urlDetalle = jsonElem.dataset.urlDetalle;
  const parametrosPeriodo = new URLSearchParams(window.location.search);

  // Crea (una sola vez) el panel de detalle debajo del gráfico
  function obtenerPanelDetalle(canvas) {
    const contenedor = canvas.closest('.kpi-panel-grafico');
    let panel = contenedor.querySelector('.kpi-detalle');
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'kpi-detalle';
      panel.setAttribute('aria-live', 'polite');
      panel.hidden = true;
      contenedor.appendChild(panel);
    }
    return panel;
  }

  function crearElemento(etiqueta, clase, texto) {
    const el = document.createElement(etiqueta);
    if (clase) el.className = clase;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function crearTabla(columnas, filas) {
    const tabla = crearElemento('table', 'kpi-detalle__tabla');
    const cabecera = crearElemento('tr');
    columnas.forEach((c) => cabecera.appendChild(crearElemento('th', '', c)));
    tabla.appendChild(cabecera);
    filas.forEach((fila) => {
      const tr = crearElemento('tr');
      fila.forEach((celda) => tr.appendChild(crearElemento('td', '', celda)));
      tabla.appendChild(tr);
    });
    return tabla;
  }

  function mostrarDetalle(canvas, info) {
    const panel = obtenerPanelDetalle(canvas);
    panel.replaceChildren();

    const cabecera = crearElemento('div', 'kpi-detalle__cabecera');
    cabecera.appendChild(crearElemento('strong', '', `Detalle: ${info.titulo}`));
    const cerrar = crearElemento('button', 'kpi-detalle__cerrar', 'Cerrar ✕');
    cerrar.type = 'button';
    cerrar.addEventListener('click', () => { panel.hidden = true; });
    cabecera.appendChild(cerrar);
    panel.appendChild(cabecera);

    panel.appendChild(crearElemento(
      'p', 'kpi-detalle__resumen',
      `${info.periodo}: ${formatearDinero(info.total_monto)} · ${info.total_unidades} unidades · ${info.total_pedidos} pedidos`
    ));

    if (info.filas.length) {
      panel.appendChild(crearTabla(
        [info.etiqueta_filas, 'Unidades', 'Monto'],
        info.filas.map((f) => [f.nombre, String(f.unidades), formatearDinero(f.monto)])
      ));
    }
    if (info.pedidos_recientes.length) {
      panel.appendChild(crearElemento('p', 'kpi-detalle__subtitulo', 'Últimos pedidos'));
      panel.appendChild(crearTabla(
        ['Pedido', 'Fecha', 'Canal', 'Total'],
        info.pedidos_recientes.map((p) => [`#${p.id}`, p.fecha, p.canal, formatearDinero(p.total)])
      ));
    }
    if (!info.filas.length && !info.pedidos_recientes.length) {
      panel.appendChild(crearElemento('p', 'kpi-detalle__vacio', 'Sin ventas registradas en el período.'));
    }
    panel.hidden = false;
  }

  async function cargarDetalle(canvas, tipo, valor) {
    const panel = obtenerPanelDetalle(canvas);
    panel.replaceChildren(crearElemento('p', 'kpi-detalle__vacio', 'Cargando detalle…'));
    panel.hidden = false;

    const params = new URLSearchParams({ tipo, valor });
    ['periodo', 'desde', 'hasta'].forEach((k) => {
      if (parametrosPeriodo.get(k)) params.set(k, parametrosPeriodo.get(k));
    });
    try {
      const respuesta = await fetch(`${urlDetalle}?${params.toString()}`, { credentials: 'same-origin' });
      if (!respuesta.ok) throw new Error('Respuesta no válida');
      mostrarDetalle(canvas, await respuesta.json());
    } catch (e) {
      panel.replaceChildren(crearElemento('p', 'kpi-detalle__vacio', 'No se pudo cargar el detalle. Intenta nuevamente.'));
    }
  }

  // Conecta un gráfico: `resolverValor(indice)` devuelve el valor a consultar (o null si no hay datos)
  function hacerInteractivo(idCanvas, tipo, resolverValor) {
    const canvas = document.getElementById(idCanvas);
    if (!canvas || !urlDetalle || !window.Chart) return;
    const grafico = Chart.getChart(canvas);
    if (!grafico) return;
    canvas.style.cursor = 'default';
    grafico.options.onHover = (evento, elementos) => {
      const activo = elementos.length > 0 && resolverValor(elementos[0].index) !== null;
      evento.native.target.style.cursor = activo ? 'pointer' : 'default';
    };
    grafico.options.onClick = (evento, elementos) => {
      if (!elementos.length) return;
      const valor = resolverValor(elementos[0].index);
      if (valor !== null) cargarDetalle(canvas, tipo, valor);
    };
    grafico.update();
  }

  const canalesClave = ['PRESENCIAL', 'WEB'];
  hacerInteractivo('graficoCanales', 'canal', (i) => {
    const hayVentas = ((datos.canales_montos || [])[0] || 0) + ((datos.canales_montos || [])[1] || 0) > 0;
    return hayVentas ? canalesClave[i] : null;
  });
  hacerInteractivo('graficoTop5', 'producto', (i) => (datos.top5_nombres || [])[i] ?? null);
  hacerInteractivo('graficoCategorias', 'categoria', (i) => {
    const hay = datos.categorias_montos && datos.categorias_montos.length > 0;
    return hay ? (datos.categorias_nombres[i] ?? null) : null;
  });});

// Función para enviar el formulario con rango de fechas personalizado
function aplicarRangoPersonalizado() {
  const desde = document.getElementById('fechaDesde').value;
  const hasta = document.getElementById('fechaHasta').value;
  if (!desde || !hasta) {
    alert('Por favor selecciona tanto la fecha de inicio (Desde) como la de término (Hasta).');
    return;
  }
  if (desde > hasta) {
    alert('La fecha Desde no puede ser posterior a la fecha Hasta.');
    return;
  }
  document.getElementById('inputPeriodoPersonalizado').value = 'personalizado';
  document.getElementById('formPeriodoKpi').submit();
}
