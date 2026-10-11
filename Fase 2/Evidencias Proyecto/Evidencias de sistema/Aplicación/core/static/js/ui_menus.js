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