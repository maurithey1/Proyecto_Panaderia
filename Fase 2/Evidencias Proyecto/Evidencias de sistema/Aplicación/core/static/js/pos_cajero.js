/* ==========================================
   SISTEMA POS / CAJERO: RELOJ EN TIEMPO REAL
   ========================================== */

document.addEventListener('DOMContentLoaded', () => {
  function actualizarReloj() {
    const ahora = new Date();

    // Formato Fecha: DD/MM/YYYY
    const dia = String(ahora.getDate()).padStart(2, '0');
    const mes = String(ahora.getMonth() + 1).padStart(2, '0');
    const anio = ahora.getFullYear();

    // Formato Hora: HH:MM
    const horas = String(ahora.getHours()).padStart(2, '0');
    const minutos = String(ahora.getMinutes()).padStart(2, '0');

    const elementoFecha = document.getElementById('fechaActual');
    const elementoHora = document.getElementById('horaActual');

    if (elementoFecha) {
      elementoFecha.textContent = `${dia}/${mes}/${anio}`;
    }
    if (elementoHora) {
      elementoHora.textContent = `${horas}:${minutos}`;
    }
  }

  // Ejecutar al cargar la página
  actualizarReloj();

  // Actualizar cada 10 segundos
  setInterval(actualizarReloj, 10000);
});

// Desvanecimiento automático de mensajes cargados por Django al iniciar la vista
document.addEventListener('DOMContentLoaded', () => {
  const toasts = document.querySelectorAll('.notificacion-toast');
  toasts.forEach((toast) => {
    setTimeout(() => {
      toast.classList.add('notificacion-toast--ocultando');
      toast.addEventListener('transitionend', () => toast.remove());
    }, 3500);
  });
});

// Función global para crear Toasts dinámicos en pantalla (AJAX / Fetch)
function mostrarToast(mensaje, tipo = 'success') {
  let contenedor = document.getElementById('notificaciones-contenedor');
  if (!contenedor) {
    contenedor = document.createElement('div');
    contenedor.id = 'notificaciones-contenedor';
    contenedor.className = 'notificaciones-flotantes';
    contenedor.setAttribute('aria-live', 'polite');
    contenedor.setAttribute('aria-atomic', 'true');
    document.body.appendChild(contenedor);
  }

  const toast = document.createElement('div');
  toast.className = `notificacion-toast notificacion-toast--${tipo}`;

  const icono = tipo === 'success' ? '✓' : (tipo === 'error' ? '✕' : 'ℹ');
  toast.innerHTML = `
    <div class="notificacion-toast__contenido">
      <span class="notificacion-toast__icono">${icono}</span>
      <span class="notificacion-toast__texto">${mensaje}</span>
    </div>
    <button type="button" class="notificacion-toast__cerrar" onclick="this.parentElement.remove()" aria-label="Cerrar notificación">&times;</button>
  `;

  contenedor.appendChild(toast);

  // Transición y remoción automática tras 3.5 segundos
  setTimeout(() => {
    toast.classList.add('notificacion-toast--ocultando');
    toast.addEventListener('transitionend', () => toast.remove());
  }, 3500);
}

document.addEventListener('DOMContentLoaded', function () {
    const inputBuscar = document.getElementById('inputBuscar');
    const chipsCategoria = document.querySelectorAll('#contenedorCategorias .cajero-chip');
    const tarjetasProductos = document.querySelectorAll('#gridProductosCajero .cajero-prod-card');
    const msgSinResultados = document.getElementById('msgSinResultados');

    let categoriaSeleccionada = 'todas';
    let textoBusqueda = '';

    // Función normalizadora: elimina tildes y convierte a minúsculas
    function normalizarTexto(texto) {
        return (texto || '')
            .toLowerCase()
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .trim();
    }

    // Función principal de filtrado en tiempo real
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

        // Mostrar u ocultar mensaje de "sin resultados"
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

    // Evento Búsqueda por Texto (instantáneo)
    if (inputBuscar) {
        inputBuscar.addEventListener('input', function (e) {
            textoBusqueda = normalizarTexto(e.target.value);
            filtrarProductos();
        });
    }

    // Evento Filtro por Botón de Categoría (Chips)
    chipsCategoria.forEach(chip => {
        chip.addEventListener('click', function () {
            // Remover clase activa de todos y asignarla al seleccionado
            chipsCategoria.forEach(c => c.classList.remove('activo'));
            this.classList.add('activo');

            // Actualizar categoría seleccionada
            categoriaSeleccionada = this.getAttribute('data-categoria') || 'todas';
            filtrarProductos();
        });
    });
});

// Estado global de la orden en POS
let carritoPos = []; // Array de { id, nombre, precio, cantidad, stock }
let metodoPagoSeleccionado = 'efectivo';

// Formateador CLP
function formatoCLP(monto) {
    return '$' + Math.round(monto).toLocaleString('es-CL');
}

// Obtener token CSRF de Django (soporta tanto input hidden como cookie)
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

// Sistema de Notificaciones Toast Flotantes
function mostrarToast(mensaje, tipo = 'success') {
    let contenedor = document.getElementById('notificaciones-contenedor');
    if (!contenedor) {
        contenedor = document.createElement('div');
        contenedor.id = 'notificaciones-contenedor';
        contenedor.className = 'notificaciones-flotantes';
        document.body.appendChild(contenedor);
    }

    const toast = document.createElement('div');
    toast.className = `notificacion-toast notificacion-toast--${tipo}`;

    const icono = tipo === 'success' ? '✓' : (tipo === 'error' ? '✕' : 'ℹ');
    toast.innerHTML = `
        <div class="notificacion-toast__contenido">
            <span class="notificacion-toast__icono">${icono}</span>
            <span class="notificacion-toast__texto">${mensaje}</span>
        </div>
        <button type="button" class="notificacion-toast__cerrar" onclick="this.parentElement.remove()">&times;</button>
    `;

    contenedor.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('notificacion-toast--ocultando');
        toast.addEventListener('transitionend', () => toast.remove());
    }, 3200);
}

// Generador del HTML de la cápsula de control de cantidad
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

// Operaciones del Carrito POS
function agregarUnidadPos(id) {
    const tarjeta = document.querySelector(`.cajero-prod-card[data-id="${id}"]`);
    if (!tarjeta) return;

    const nombre = tarjeta.getAttribute('data-nombre');
    const precio = parseFloat(tarjeta.getAttribute('data-precio'));
    const stock = parseInt(tarjeta.getAttribute('data-stock'));

    const item = carritoPos.find(p => p.id === id);

    if (item) {
        if (item.cantidad < stock) {
            item.cantidad += 1;
        } else {
            mostrarToast(`Límite de stock alcanzado (${stock} un.)`, 'warning');
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

// Renderizado Sincronizado para el Ticket de Venta POS
function renderizarSincronizado() {
    // 1. Actualizar Tarjetas del Catálogo (Izquierda)
    const tarjetas = document.querySelectorAll('.cajero-prod-card');
    tarjetas.forEach(tarjeta => {
        const id = parseInt(tarjeta.getAttribute('data-id'));
        const stock = parseInt(tarjeta.getAttribute('data-stock'));
        const contenedorAcciones = tarjeta.querySelector('.cajero-prod-acciones');
        
        if (contenedorAcciones && stock > 0) {
            const itemInCart = carritoPos.find(p => p.id === id);
            const cant = itemInCart ? itemInCart.cantidad : 0;
            contenedorAcciones.innerHTML = generarControlCantidadHTML(id, cant, stock);
        }
    });

    // 2. Actualizar Tabla Derecha del Carrito (Diseño Limpio POS)
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
                        <strong>${item.nombre}</strong>
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
                tbody.appendChild(tr);
            });
        }
    }

    // 3. Recalcular Totales y Vuelto
    calcularTotalesPos();
}

function calcularTotalesPos() {
    const elTotal = document.getElementById('posMontoTotal');
    const elVuelto = document.getElementById('posMontoVuelto');
    const inputPagaCon = document.getElementById('inputPagaCon');

    const totalGral = carritoPos.reduce((acc, item) => acc + (item.precio * item.cantidad), 0);

    if (elTotal) elTotal.textContent = formatoCLP(totalGral);

    if (metodoPagoSeleccionado === 'tarjeta') {
        if (elVuelto) elVuelto.textContent = '$0';
        return;
    }

    const pagaCon = parseFloat(inputPagaCon ? inputPagaCon.value : 0) || 0;
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
}

// Eventos del DOM
document.addEventListener('DOMContentLoaded', function () {
    const btnEfectivo = document.getElementById('btnPagoEfectivo');
    const btnTarjeta = document.getElementById('btnPagoTarjeta');
    const inputPagaCon = document.getElementById('inputPagaCon');
    const seccionPagaCon = document.getElementById('seccionPagaCon');
    const btnFinalizar = document.getElementById('btnFinalizarVenta');
    const btnCancelar = document.getElementById('btnCancelarVenta');

    if (btnEfectivo) {
        btnEfectivo.addEventListener('click', function () {
            metodoPagoSeleccionado = 'efectivo';
            btnEfectivo.classList.add('activo');
            if (btnTarjeta) btnTarjeta.classList.remove('activo');
            if (seccionPagaCon) seccionPagaCon.style.display = 'flex';
            calcularTotalesPos();
        });
    }

    if (btnTarjeta) {
        btnTarjeta.addEventListener('click', function () {
            metodoPagoSeleccionado = 'tarjeta';
            btnTarjeta.classList.add('activo');
            if (btnEfectivo) btnEfectivo.classList.remove('activo');
            if (seccionPagaCon) seccionPagaCon.style.display = 'none';
            calcularTotalesPos();
        });
    }

    if (inputPagaCon) {
        inputPagaCon.addEventListener('input', calcularTotalesPos);
    }

    // Cancelar Venta
    if (btnCancelar) {
        btnCancelar.addEventListener('click', function () {
            if (carritoPos.length === 0) {
                mostrarToast('El ticket de venta ya está vacío.', 'info');
                return;
            }
            carritoPos = [];
            if (inputPagaCon) inputPagaCon.value = '';
            renderizarSincronizado();
            mostrarToast('Venta cancelada. Se ha limpiado el ticket.', 'warning');
        });
    }

    // Finalizar Venta y Redireccionar a Webpay en Tarjeta
    if (btnFinalizar) {
        btnFinalizar.addEventListener('click', async function () {
            if (carritoPos.length === 0) {
                mostrarToast('Debe agregar al menos un producto al ticket.', 'error');
                return;
            }

            const totalGral = carritoPos.reduce((acc, item) => acc + (item.precio * item.cantidad), 0);
            const pagaCon = parseFloat(inputPagaCon ? inputPagaCon.value : 0) || 0;

            if (metodoPagoSeleccionado === 'efectivo' && pagaCon < totalGral) {
                mostrarToast(`El efectivo ingresado (${formatoCLP(pagaCon)}) es menor al total (${formatoCLP(totalGral)}).`, 'error');
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
                        monto_efectivo: pagaCon
                    })
                });

                // Verificar si el servidor devolvió JSON
                const contentType = response.headers.get('content-type');
                if (!contentType || !contentType.includes('application/json')) {
                    const textError = await response.text();
                    console.error('Respuesta no-JSON del servidor:', response.status, textError);
                    mostrarToast(`Error en el servidor (${response.status}). Revisa la consola.`, 'error');
                    btnFinalizar.disabled = false;
                    return;
                }

                const data = await response.json();

                if (!response.ok || !data.ok) {
                    mostrarToast(data.error || 'Ocurrió un error al procesar la venta.', 'error');
                    btnFinalizar.disabled = false;
                    return;
                }

                // Redirección a Webpay o Confirmación en Efectivo
                if (data.metodo === 'tarjeta' && data.url_webpay) {
                    mostrarToast('Redirigiendo a pasarela Webpay Plus...', 'info');
                    setTimeout(() => {
                        window.location.href = data.url_webpay;
                    }, 800);
                } else {
                    mostrarToast(data.mensaje, 'success');
                    carritoPos = [];
                    if (inputPagaCon) inputPagaCon.value = '';
                    renderizarSincronizado();
                    btnFinalizar.disabled = false;
                }

            } catch (err) {
                console.error('Error finalizando venta:', err);
                mostrarToast('Error de comunicación con el servidor.', 'error');
                btnFinalizar.disabled = false;
            }
        });
    }
});