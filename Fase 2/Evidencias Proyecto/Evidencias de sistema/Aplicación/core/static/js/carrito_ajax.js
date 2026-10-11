/* ==========================================
   MOTOR AJAX DEL CARRITO Y NOTIFICACIONES TOAST
   ========================================== */

document.addEventListener('DOMContentLoaded', () => {
  // Desvanecimiento de alertas iniciales cargadas por Django
  const toasts = document.querySelectorAll('.notificacion-toast');
  toasts.forEach((toast) => {
    setTimeout(() => {
      toast.classList.add('notificacion-toast--ocultando');
      toast.addEventListener('transitionend', () => toast.remove());
    }, 3500);
  });
});

// Función para actualizar dinámicamente la insignia roja del header
function actualizarInsigniaHeader(cantidadTotal) {
  let badge = document.querySelector('.carrito__insignia, #contador-carrito');
  const enlaceCarrito = document.querySelector('.carrito');

  if (cantidadTotal > 0) {
    if (!badge && enlaceCarrito) {
      badge = document.createElement('span');
      badge.className = 'carrito__insignia';
      badge.id = 'contador-carrito';
      enlaceCarrito.appendChild(badge);
    }
    if (badge) {
      badge.textContent = cantidadTotal;
      badge.style.display = 'inline-flex';
    }
  } else {
    if (badge) {
      badge.style.display = 'none';
    }
  }
}

// Función global para crear Toasts dinámicos en pantalla
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

// Interceptor de formularios del Carrito (Fetch / AJAX)
document.addEventListener('submit', async (e) => {
  const form = e.target;
  if (!form.action || (!form.action.includes('/carrito/agregar/') &&
                       !form.action.includes('/carrito/disminuir/') &&
                       !form.action.includes('/carrito/quitar/'))) {
    return;
  }

  e.preventDefault();

  try {
    const response = await fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    });

    if (!response.ok) throw new Error('Error en la solicitud.');

    const data = await response.json();

    if (data.ok) {
      actualizarInsigniaHeader(data.cant_carrito);

      const contenedores = document.querySelectorAll(`[data-producto-id="${data.producto_id}"]`);
      contenedores.forEach(contenedor => {
        actualizarControlCantidadHTML(contenedor, data.producto_id, data.cantidad_item);
      });

      const fila = document.querySelector(`tr[data-producto-fila="${data.producto_id}"]`);
      if (fila) {
        if (data.cantidad_item <= 0) {
          fila.remove();
        } else {
          const tdCantidad = fila.querySelector('.item-cantidad');
          if (tdCantidad) tdCantidad.childNodes[0].nodeValue = `${data.cantidad_item} `;

          const tdSubtotal = fila.querySelector('.item-subtotal');
          if (tdSubtotal) tdSubtotal.textContent = data.subtotal_item_clp;
        }
      }

      const totalGeneralElem = document.querySelector('.compra__tabla tfoot strong, #carrito-total');
      if (totalGeneralElem) {
        totalGeneralElem.textContent = data.total_carrito_clp;
      }

      if (data.mensaje) {
        mostrarToast(data.mensaje, data.tipo_mensaje || 'success');
      }
    }
  } catch (err) {
    console.error('Error procesando carrito:', err);
  }
});

// Renderizador dinámico del control cápsula en el cliente
function actualizarControlCantidadHTML(contenedor, productoId, cantidad) {
  if (cantidad <= 0) {
    contenedor.innerHTML = `
      <form action="/carrito/agregar/" method="post">
        <input type="hidden" name="csrfmiddlewaretoken" value="${getCsrfToken()}">
        <input type="hidden" name="producto_id" value="${productoId}">
        <button class="agregar" type="submit" aria-label="Agregar al carrito">
          <svg class="icono" aria-hidden="true"><use href="#i-mas"/></svg>
        </button>
      </form>
    `;
  } else {
    const botonIzquierdo = cantidad === 1 ? `
      <form action="/carrito/quitar/${productoId}/" method="post">
        <input type="hidden" name="csrfmiddlewaretoken" value="${getCsrfToken()}">
        <button class="control-cantidad__btn control-cantidad__btn--basura" type="submit" title="Eliminar del carrito">
          <svg class="icono" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
        </button>
      </form>
    ` : `
      <form action="/carrito/disminuir/${productoId}/" method="post">
        <input type="hidden" name="csrfmiddlewaretoken" value="${getCsrfToken()}">
        <button class="control-cantidad__btn control-cantidad__btn--menos" type="submit" title="Disminuir cantidad">
          <svg class="icono" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
        </button>
      </form>
    `;

    contenedor.innerHTML = `
      <div class="control-cantidad">
        ${botonIzquierdo}
        <span class="control-cantidad__numero">${cantidad}</span>
        <form action="/carrito/agregar/" method="post">
          <input type="hidden" name="csrfmiddlewaretoken" value="${getCsrfToken()}">
          <input type="hidden" name="producto_id" value="${productoId}">
          <button class="control-cantidad__btn control-cantidad__btn--mas" type="submit" title="Aumentar cantidad">
            <svg class="icono" aria-hidden="true"><use href="#i-mas"/></svg>
          </button>
        </form>
      </div>
    `;
  }
}

function getCsrfToken() {
  return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
}