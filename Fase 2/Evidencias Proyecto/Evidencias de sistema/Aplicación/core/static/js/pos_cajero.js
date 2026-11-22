/* ==========================================
   SISTEMA POS / CAJERO: RELOJ EN TIEMPO REAL
   ========================================== */

function notificarPos(mensaje, tipo = 'info') {
  if (typeof window.mostrarToast === 'function') {
    window.mostrarToast(mensaje, tipo);
  } else {
    console.warn(`[POS ${tipo}]`, mensaje);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  function actualizarReloj() {
    const ahora = new Date();

    const dia = String(ahora.getDate()).padStart(2, '0');
    const mes = String(ahora.getMonth() + 1).padStart(2, '0');
    const anio = ahora.getFullYear();

    const horas = String(ahora.getHours()).padStart(2, '0');
    const minutos = String(ahora.getMinutes()).padStart(2, '0');

    const elementoFecha = document.getElementById('fechaActual');
    const elementoHora = document.getElementById('horaActual');

    if (elementoFecha) elementoFecha.textContent = `${dia}/${mes}/${anio}`;
    if (elementoHora) elementoHora.textContent = `${horas}:${minutos}`;
  }

  actualizarReloj();
  setInterval(actualizarReloj, 10000);
});

document.addEventListener('DOMContentLoaded', function () {
  const inputBuscar = document.getElementById('inputBuscar');
  const chipsCategoria = document.querySelectorAll('#contenedorCategorias .cajero-chip');
  const tarjetasProductos = document.querySelectorAll('#gridProductosCajero .cajero-prod-card');
  const msgSinResultados = document.getElementById('msgSinResultados');

  let categoriaSeleccionada = 'todas';
  let textoBusqueda = '';

  function normalizarTexto(texto) {
    return (texto || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .trim();
  }

  function filtrarProductos() {
    let visibles = 0;

    tarjetasProductos.forEach(tarjeta => {
      const catProd = tarjeta.getAttribute('data-categoria');
      const nombreProd = normalizarTexto(tarjeta.getAttribute('data-nombre'));

      const coincideCategoria = (categoriaSeleccionada === 'todas' || catProd === categoriaSeleccionada);
      const coincideBusqueda = textoBusqueda === '' || nombreProd.includes(textoBusqueda);

      if (coincideCategoria && coincideBusqueda) {
        tarjeta.style.display = '';
        visibles++;
      } else {
        tarjeta.style.display = 'none';
      }
    });

    if (msgSinResultados) {
      if (visibles === 0 && tarjetasProductos.length > 0) {
        msgSinResultados.classList.remove('d-none');
        msgSinResultados.style.display = 'block';
      } else {
        msgSinResultados.classList.add('d-none');
        msgSinResultados.style.display = 'none';
      }
    }
  }

  if (inputBuscar) {
    inputBuscar.addEventListener('input', function (e) {
      textoBusqueda = normalizarTexto(e.target.value);
      filtrarProductos();
    });
  }

  chipsCategoria.forEach(chip => {
    chip.addEventListener('click', function () {
      chipsCategoria.forEach(c => c.classList.remove('activo'));
      this.classList.add('activo');
      categoriaSeleccionada = this.getAttribute('data-categoria') || 'todas';
      filtrarProductos();
    });
  });

  filtrarProductos();
});

// Estado global de la orden en POS
let carritoPos = []; // Array de { id, nombre, precio, cantidad, stock }
let metodoPagoSeleccionado = 'efectivo';

function formatoCLP(monto) {
  return '$' + Math.round(monto).toLocaleString('es-CL');
}

function formatearPrecio(val) {
  const limpio = String(val || '').replace(/\D/g, '');
  if (!limpio) return '';
  const formatoMiles = parseInt(limpio, 10).toLocaleString('es-CL');
  return `$ ${formatoMiles}`;
}

function normalizarPrecioPos(val) {
  const limpio = String(val || '').replace(/\D/g, '');
  return limpio ? parseInt(limpio, 10) : 0;
}

function getCsrfToken() {
  const input = document.querySelector('[name=csrfmiddlewaretoken]');
  if (input && input.value) return input.value;

  const name = 'csrftoken';
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue || '';
}

function generarControlCantidadHTML(id, cantidad, stock) {
  if (cantidad <= 0) {
    return `
      <button type="button" class="agregar" onclick="agregarUnidadPos(${id})" aria-label="Agregar">
        <svg class="icono" aria-hidden="true"><use href="#i-mas"/></svg>
      </button>`;
  }

  const btnDeshabilitadoMas = cantidad >= stock ? 'disabled' : '';

  const btnIzquierdo = cantidad === 1 ? `
    <button type="button" class="control-cantidad__btn control-cantidad__btn--basura" onclick="quitarDelCarritoPos(${id})" title="Eliminar del ticket">
      <svg class="icono" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="3 6 5 6 21 6"></polyline>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
      </svg>
    </button>` : `
    <button type="button" class="control-cantidad__btn control-cantidad__btn--menos" onclick="disminuirUnidadPos(${id})" title="Disminuir cantidad">
      <svg class="icono" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="5" y1="12" x2="19" y2="12"></line>
      </svg>
    </button>`;

  return `
    <div class="control-cantidad">
      ${btnIzquierdo}
      <span class="control-cantidad__numero">${cantidad}</span>
      <button type="button" class="control-cantidad__btn control-cantidad__btn--mas" onclick="agregarUnidadPos(${id})" title="Aumentar cantidad" ${btnDeshabilitadoMas}>
        <svg class="icono" aria-hidden="true"><use href="#i-mas"/></svg>
      </button>
    </div>`;
}

function agregarUnidadPos(id) {
  const tarjeta = document.querySelector(`.cajero-prod-card[data-id="${id}"]`);
  if (!tarjeta) return;

  const nombre = tarjeta.getAttribute('data-nombre');
  const precio = parseFloat(tarjeta.getAttribute('data-precio'));
  const stock = parseInt(tarjeta.getAttribute('data-stock'), 10);

  const item = carritoPos.find(p => p.id === id);

  if (item) {
    if (item.cantidad < stock) {
      item.cantidad += 1;
    } else {
      notificarPos(`Límite de stock alcanzado (${stock} un.)`, 'warning');
      return;
    }
  } else {
    carritoPos.push({ id, nombre, precio, stock, cantidad: 1 });
  }

  renderizarSincronizado();
}

function disminuirUnidadPos(id) {
  const item = carritoPos.find(p => p.id === id);
  if (item) {
    if (item.cantidad > 1) {
      item.cantidad -= 1;
    } else {
      quitarDelCarritoPos(id);
      return;
    }
  }
  renderizarSincronizado();
}

function quitarDelCarritoPos(id) {
  carritoPos = carritoPos.filter(p => p.id !== id);
  renderizarSincronizado();
}

function renderizarSincronizado() {
  const tarjetas = document.querySelectorAll('.cajero-prod-card');
  tarjetas.forEach(tarjeta => {
    const id = parseInt(tarjeta.getAttribute('data-id'), 10);
    const stock = parseInt(tarjeta.getAttribute('data-stock'), 10);
    const contenedorAcciones = tarjeta.querySelector('.cajero-prod-acciones');

    if (contenedorAcciones && stock > 0) {
      const itemInCart = carritoPos.find(p => p.id === id);
      const cant = itemInCart ? itemInCart.cantidad : 0;
      contenedorAcciones.innerHTML = generarControlCantidadHTML(id, cant, stock);
    }
  });

  const tbody = document.getElementById('carritoPosBody');
  if (tbody) {
    if (carritoPos.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" class="cajero-vacio-tabla">Sin productos seleccionados</td></tr>`;
    } else {
      tbody.innerHTML = '';
      carritoPos.forEach(item => {
        const totalItem = item.precio * item.cantidad;
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="pos-item-info">
            <strong></strong>
            <small>${formatoCLP(item.precio)} c/u</small>
          </td>
          <td>
            <div class="pos-ticket-qty">
              <button type="button" class="pos-qty-btn" onclick="disminuirUnidadPos(${item.id})">-</button>
              <span class="pos-qty-num">${item.cantidad}</span>
              <button type="button" class="pos-qty-btn" onclick="agregarUnidadPos(${item.id})" ${item.cantidad >= item.stock ? 'disabled' : ''}>+</button>
            </div>
          </td>
          <td class="text-right"><strong>${formatoCLP(totalItem)}</strong></td>
          <td class="text-center">
            <button type="button" class="cajero-btn-remove" onclick="quitarDelCarritoPos(${item.id})" title="Eliminar">&times;</button>
          </td>
        `;
        tr.querySelector('.pos-item-info strong').textContent = String(item.nombre ?? '');
        tbody.appendChild(tr);
      });
    }
  }

  calcularTotalesPos();
}

let clientePosSeleccionado = null; // { id, nombre, puntos_disponibles }

function calcularMaxPuntosPos(subtotal) {
  if (!clientePosSeleccionado || subtotal <= 100 || clientePosSeleccionado.puntos_disponibles <= 0) {
    return 0;
  }
  const maxPorcentaje = Math.floor(subtotal * 0.80);
  const maxPiso = Math.max(0, subtotal - 100);
  return Math.min(clientePosSeleccionado.puntos_disponibles, maxPorcentaje, maxPiso);
}

function calcularTotalesPos() {
  const elTotal = document.getElementById('posMontoTotal');
  const elVuelto = document.getElementById('posMontoVuelto');
  const inputPagaCon = document.getElementById('inputPagaCon');

  const subtotal = carritoPos.reduce((acc, item) => acc + (item.precio * item.cantidad), 0);

  let puntosCanje = 0;
  const maxPts = calcularMaxPuntosPos(subtotal);
  const maxLabel = document.getElementById('posMaxPuntosLabel');
  const canjeBox = document.getElementById('posCanjeBox');
  const inputCanje = document.getElementById('posInputPuntosCanje');

  if (clientePosSeleccionado && maxPts > 0 && canjeBox && inputCanje) {
    canjeBox.style.display = 'block';
    if (maxLabel) maxLabel.textContent = maxPts;
    inputCanje.max = maxPts;
    puntosCanje = Math.max(0, Math.min(maxPts, parseInt(inputCanje.value, 10) || 0));
    inputCanje.value = puntosCanje;
  } else {
    if (canjeBox) canjeBox.style.display = 'none';
    if (inputCanje) inputCanje.value = 0;
  }

  const totalGral = Math.max(0, subtotal - puntosCanje);

  const filaDesc = document.getElementById('posFilaDescuento');
  const txtDesc = document.getElementById('posDescuentoPuntos');
  if (filaDesc && txtDesc) {
    if (puntosCanje > 0) {
      filaDesc.style.display = 'flex';
      txtDesc.textContent = '-' + formatoCLP(puntosCanje);
    } else {
      filaDesc.style.display = 'none';
    }
  }

  const infoGanar = document.getElementById('posPuntosGanarInfo');
  const valGanar = document.getElementById('posPuntosGanarValor');
  if (infoGanar && valGanar) {
    if (clientePosSeleccionado && totalGral > 0) {
      infoGanar.style.display = 'block';
      valGanar.textContent = '+' + Math.floor(totalGral * 0.10) + ' pts';
    } else {
      infoGanar.style.display = 'none';
    }
  }

  if (elTotal) elTotal.textContent = formatoCLP(totalGral);

  if (metodoPagoSeleccionado === 'tarjeta') {
    if (elVuelto) elVuelto.textContent = '$0';
    return totalGral;
  }

  const pagaCon = normalizarPrecioPos(inputPagaCon ? inputPagaCon.value : '');
  const vuelto = pagaCon - totalGral;

  if (elVuelto) {
    if (totalGral > 0 && pagaCon >= totalGral) {
      elVuelto.textContent = formatoCLP(vuelto);
      elVuelto.style.color = '#000';
    } else if (totalGral > 0 && pagaCon > 0 && pagaCon < totalGral) {
      elVuelto.textContent = 'Falta ' + formatoCLP(totalGral - pagaCon);
      elVuelto.style.color = '#cc0000';
    } else {
      elVuelto.textContent = '$0';
      elVuelto.style.color = '#000';
    }
  }
  return totalGral;
}

document.addEventListener('DOMContentLoaded', function () {
  const btnEfectivo = document.getElementById('btnPagoEfectivo');
  const btnTarjeta = document.getElementById('btnPagoTarjeta');
  const inputPagaCon = document.getElementById('inputPagaCon');
  const seccionPagaCon = document.getElementById('seccionPagaCon');
  const seccionVuelto = document.getElementById('seccionVuelto');
  const btnFinalizar = document.getElementById('btnFinalizarVenta');
  const btnCancelar = document.getElementById('btnCancelarVenta');
  const inputBuscarCliente = document.getElementById('posBuscarCliente');
  const resultadosClienteBox = document.getElementById('posResultadosCliente');
  const clienteActivoBox = document.getElementById('posClienteActivoBox');
  let timerBusquedaCliente = null;

  function renderizarResultadosClientes(clientes) {
    resultadosClienteBox.replaceChildren();

    if (!Array.isArray(clientes) || clientes.length === 0) {
      const vacio = document.createElement('div');
      vacio.style.cssText = 'padding: 8px 10px; font-size: 0.84rem; color: var(--texto-suave);';
      vacio.textContent = 'Sin clientes encontrados';
      resultadosClienteBox.appendChild(vacio);
      resultadosClienteBox.style.display = 'block';
      return;
    }

    clientes.forEach(c => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'pos-cliente-opcion';
      btn.style.cssText = 'display: block; width: 100%; text-align: left; padding: 8px 10px; border: none; border-bottom: 1px solid #eee; background: #fff; cursor: pointer; font-size: 0.85rem;';

      const strongNombre = document.createElement('strong');
      strongNombre.textContent = String(c.nombre ?? '');

      const spanPuntos = document.createTextNode(` (${Number(c.puntos_disponibles) || 0} pts)`);
      const salto = document.createElement('br');

      const smallContacto = document.createElement('small');
      smallContacto.style.color = '#666';
      smallContacto.textContent = String(c.email || c.username || '');

      btn.append(strongNombre, spanPuntos, salto, smallContacto);

      btn.addEventListener('click', () => {
        clientePosSeleccionado = c;
        document.getElementById('posClienteNombre').textContent = String(c.nombre ?? '');
        document.getElementById('posClienteSaldo').textContent = String(Number(c.puntos_disponibles) || 0);
        document.getElementById('posBuscadorClienteBox').style.display = 'none';
        clienteActivoBox.style.display = 'block';
        resultadosClienteBox.style.display = 'none';
        calcularTotalesPos();
      });

      resultadosClienteBox.appendChild(btn);
    });

    resultadosClienteBox.style.display = 'block';
  }

  if (inputBuscarCliente && resultadosClienteBox) {
    inputBuscarCliente.addEventListener('input', () => {
      clearTimeout(timerBusquedaCliente);
      const q = inputBuscarCliente.value.trim();
      if (q.length < 2) {
        resultadosClienteBox.style.display = 'none';
        return;
      }
      timerBusquedaCliente = setTimeout(async () => {
        try {
          const resp = await fetch(`/pos/buscar-cliente/?q=${encodeURIComponent(q)}`, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
          });
          if (!resp.ok) {
            resultadosClienteBox.style.display = 'none';
            return;
          }
          const data = await resp.json();
          if (!data.ok) {
            renderizarResultadosClientes([]);
            return;
          }
          renderizarResultadosClientes(data.clientes);
        } catch (err) {
          console.error('Error buscando cliente en POS:', err);
          resultadosClienteBox.style.display = 'none';
        }
      }, 250);
    });
  }

  document.getElementById('btnQuitarClientePos')?.addEventListener('click', () => {
    clientePosSeleccionado = null;
    document.getElementById('posBuscadorClienteBox').style.display = 'block';
    clienteActivoBox.style.display = 'none';
    if (inputBuscarCliente) inputBuscarCliente.value = '';
    calcularTotalesPos();
  });

  document.getElementById('posInputPuntosCanje')?.addEventListener('input', calcularTotalesPos);
  document.getElementById('btnMaxPuntosPos')?.addEventListener('click', () => {
    const subtotal = carritoPos.reduce((acc, item) => acc + (item.precio * item.cantidad), 0);
    const inputCanje = document.getElementById('posInputPuntosCanje');
    if (inputCanje) inputCanje.value = calcularMaxPuntosPos(subtotal);
    calcularTotalesPos();
  });

  if (btnEfectivo) {
    btnEfectivo.addEventListener('click', function () {
      metodoPagoSeleccionado = 'efectivo';
      btnEfectivo.classList.add('activo');
      if (btnTarjeta) btnTarjeta.classList.remove('activo');
      if (seccionPagaCon) seccionPagaCon.style.display = 'flex';
      if (seccionVuelto) seccionVuelto.style.display = '';
      calcularTotalesPos();
    });
  }

  if (btnTarjeta) {
    btnTarjeta.addEventListener('click', function () {
      metodoPagoSeleccionado = 'tarjeta';
      btnTarjeta.classList.add('activo');
      if (btnEfectivo) btnEfectivo.classList.remove('activo');
      if (seccionPagaCon) seccionPagaCon.style.display = 'none';
      if (seccionVuelto) seccionVuelto.style.display = 'none';
      if (inputPagaCon) inputPagaCon.value = '';
      calcularTotalesPos();
    });
  }

  if (inputPagaCon) {
    inputPagaCon.addEventListener('input', function (e) {
      e.target.value = formatearPrecio(e.target.value);
      calcularTotalesPos();
    });
  }

  if (btnCancelar) {
    btnCancelar.addEventListener('click', function () {
      if (carritoPos.length === 0) {
        notificarPos('El ticket de venta ya está vacío.', 'info');
        return;
      }
      carritoPos = [];
      if (inputPagaCon) inputPagaCon.value = '';
      renderizarSincronizado();
      notificarPos('Venta cancelada. Se ha limpiado el ticket.', 'warning');
    });
  }

  if (btnFinalizar) {
    btnFinalizar.addEventListener('click', async function () {
      if (carritoPos.length === 0) {
        notificarPos('Debe agregar al menos un producto al ticket.', 'error');
        return;
      }

      const totalGral = calcularTotalesPos();
      const pagaCon = normalizarPrecioPos(inputPagaCon ? inputPagaCon.value : '');

      if (metodoPagoSeleccionado === 'efectivo' && pagaCon < totalGral) {
        notificarPos(`El efectivo ingresado (${formatoCLP(pagaCon)}) es menor al total (${formatoCLP(totalGral)}).`, 'error');
        return;
      }

      btnFinalizar.disabled = true;

      try {
        const response = await fetch('/pos/finalizar-venta/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            'X-Requested-With': 'XMLHttpRequest'
          },
          body: JSON.stringify({
            items: carritoPos,
            metodo_pago: metodoPagoSeleccionado,
            monto_efectivo: pagaCon,
            cliente_id: clientePosSeleccionado ? clientePosSeleccionado.id : null,
            puntos_a_canjear: parseInt(document.getElementById('posInputPuntosCanje')?.value, 10) || 0
          })
        });

        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          const textError = await response.text();
          console.error('Respuesta no-JSON del servidor:', response.status, textError);
          notificarPos(`Error en el servidor (${response.status}). Revisa la consola.`, 'error');
          btnFinalizar.disabled = false;
          return;
        }

        const data = await response.json();

        if (!response.ok || !data.ok) {
          notificarPos(data.error || 'Ocurrió un error al procesar la venta.', 'error');
          btnFinalizar.disabled = false;
          return;
        }

        notificarPos(data.mensaje || 'Venta registrada exitosamente.', 'success');

        carritoPos.forEach(item => {
          const card = document.querySelector(`.cajero-prod-card[data-id="${item.id}"]`);
          if (card) {
            const nuevoStock = Math.max(0, parseInt(card.getAttribute('data-stock'), 10) - item.cantidad);
            card.setAttribute('data-stock', nuevoStock);
            const badge = card.querySelector('.cajero-badge-stock');
            if (badge) {
              if (nuevoStock > 0) {
                badge.textContent = `Stock: ${nuevoStock}`;
              } else {
                badge.textContent = 'Agotado';
                badge.className = 'cajero-badge-stock sin-stock';
                card.classList.add('agotado');
                const acciones = card.querySelector('.cajero-prod-acciones');
                if (acciones) {
                  acciones.innerHTML = '<button type="button" class="cajero-btn-agregar agotado" disabled>Sin Stock</button>';
                }
              }
            }
          }
        });

        carritoPos = [];
        clientePosSeleccionado = null;
        const buscadorClienteBox = document.getElementById('posBuscadorClienteBox');
        const clienteActivoBoxReset = document.getElementById('posClienteActivoBox');
        const inputBuscarClienteReset = document.getElementById('posBuscarCliente');
        const inputCanjeReset = document.getElementById('posInputPuntosCanje');
        if (buscadorClienteBox) buscadorClienteBox.style.display = 'block';
        if (clienteActivoBoxReset) clienteActivoBoxReset.style.display = 'none';
        if (inputBuscarClienteReset) inputBuscarClienteReset.value = '';
        if (inputCanjeReset) inputCanjeReset.value = 0;
        if (inputPagaCon) inputPagaCon.value = '';
        renderizarSincronizado();
        btnFinalizar.disabled = false;

      } catch (err) {
        console.error('Error finalizando venta:', err);
        notificarPos('Error de comunicación con el servidor.', 'error');
        btnFinalizar.disabled = false;
      }
    });
  }
});