/* static/js/ui_menus.js */

// Desvanecimiento automático de mensajes de Django al cargar la vista
document.addEventListener('DOMContentLoaded', () => {
  const toasts = document.querySelectorAll('.notificacion-toast');
  toasts.forEach((toast) => {
    setTimeout(() => {
      toast.classList.add('notificacion-toast--ocultando');
      toast.addEventListener('transitionend', () => toast.remove());
    }, 3500);
  });
});

// Función global para disparar Toasts dinámicos desde JS cuando se necesite
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

  setTimeout(() => {
    toast.classList.add('notificacion-toast--ocultando');
    toast.addEventListener('transitionend', () => toast.remove());
  }, 3500);
}

/* ==========================================
   INTERFAZ GENERAL: MENÚS DESPLEGABLES (DROPDOWNS)
   ========================================== */

// Menú de usuario en base.html
function toggleUsuarioMenu() {
  const dropdown = document.getElementById('usuarioDropdown');
  if (dropdown) {
    dropdown.classList.toggle('activo');
  }
}

// Menú de administrador en base_admin.html
function toggleAdminMenu() {
  const dropdown = document.getElementById('adminDropdown');
  if (dropdown) {
    dropdown.classList.toggle('activo');
  }
}

// Menú de cajero en base_cajero.html
function toggleCajeroMenu() {
  const dropdown = document.getElementById('cajeroDropdown');
  if (dropdown) {
    dropdown.classList.toggle('activo');
  }
}

// Cerrar cualquier menú al hacer clic fuera de él
window.addEventListener('click', function (e) {
  const usuarioDropdown = document.getElementById('usuarioDropdown');
  if (usuarioDropdown && !usuarioDropdown.contains(e.target)) {
    usuarioDropdown.classList.remove('activo');
  }

  const adminDropdown = document.getElementById('adminDropdown');
  if (adminDropdown && !adminDropdown.contains(e.target)) {
    adminDropdown.classList.remove('activo');
  }

  const cajeroDropdown = document.getElementById('cajeroDropdown');
  if (cajeroDropdown && !cajeroDropdown.contains(e.target)) {
    cajeroDropdown.classList.remove('activo');
  }
});