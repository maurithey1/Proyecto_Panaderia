document.addEventListener('DOMContentLoaded', function () {
  const elem = document.getElementById('datos-inicio-admin-json');
  if (!elem) return;

  let datos = {};
  try {
    datos = JSON.parse(elem.textContent);
  } catch (e) {
    console.error('Error al parsear datos de gráficos:', e);
    return;
  }

  const fmtDinero = (v) => '$' + Math.round(v || 0).toLocaleString('es-CL');

  // 1. Gráfico de Barras: Comparativa Mes Anterior vs Actual  
  const ctxBarras = document.getElementById('graficoBarrasInicio');
  if (ctxBarras && datos.semanas_labels) {
    new Chart(ctxBarras, {
      type: 'bar',
      data: {
        labels: datos.semanas_labels,
        datasets: [
          {
            label: datos.nombre_mes_anterior || 'Mes anterior',
            data: datos.ventas_mes_anterior || [0, 0, 0, 0],
            backgroundColor: '#c8a27a',
            borderRadius: 4,
          },
          {
            label: datos.nombre_mes_actual || 'Mes actual',
            data: datos.ventas_mes_actual || [0, 0, 0, 0],
            backgroundColor: '#b4532a',
            borderRadius: 4,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { boxWidth: 10, padding: 8, font: { size: 11 } }
          },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${ctx.dataset.label}: ${fmtDinero(ctx.raw)}`
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              font: { size: 10 },
              callback: (v) => '$' + (v >= 1000 ? (v / 1000) + 'k' : v)
            },
            grid: { color: '#f0e3ce' }
          },
          x: {
            ticks: { font: { size: 10 } },
            grid: { display: false }
          }
        }
      }
    });
  }

  // 2. Gráfico de Líneas: Tendencia Últimos 14 días (POS vs Web)  
  const ctxLineas = document.getElementById('graficoLineasInicio');
  if (ctxLineas && datos.dias_labels) {
    new Chart(ctxLineas, {
      type: 'line',
      data: {
        labels: datos.dias_labels,
        datasets: [
          {
            label: 'POS',
            data: datos.tendencia_pos || [],
            borderColor: '#7b4b2a',
            backgroundColor: 'rgba(123, 75, 42, 0.12)',
            fill: true,
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2.5,
            pointHoverRadius: 5,
          },
          {
            label: 'Webpay',
            data: datos.tendencia_web || [],
            borderColor: '#e3b25b',
            backgroundColor: 'rgba(227, 178, 91, 0.12)',
            fill: true,
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2.5,
            pointHoverRadius: 5,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { boxWidth: 10, padding: 8, font: { size: 11 } }
          },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${ctx.dataset.label}: ${fmtDinero(ctx.raw)}`
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              font: { size: 10 },
              callback: (v) => '$' + (v >= 1000 ? (v / 1000) + 'k' : v)
            },
            grid: { color: '#f0e3ce' }
          },
          x: {
            ticks: { font: { size: 10 } },
            grid: { display: false }
          }
        }
      }
    });
  }
});