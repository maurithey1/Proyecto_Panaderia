/* ==========================================================
   GESTIÓN DE USUARIOS: LÓGICA DE MODALES (CREAR Y EDITAR)
   ========================================================== */

// --- MODAL CREAR PERSONAL ---
function abrirModalUsuario() {
  const modal = document.getElementById('modalUsuario');
  if (modal) {
    toggleCampoCajaCrear();
    modal.showModal();
  }
}

function cerrarModalUsuario() {
  const modal = document.getElementById('modalUsuario');
  if (modal) modal.close();
}

function toggleCampoCajaCrear() {
  const selectRol = document.getElementById('crear_rol');
  const contenedorCaja = document.getElementById('contenedor_caja_crear');
  if (selectRol && contenedorCaja) {
    contenedorCaja.style.display = (selectRol.value === 'CAJERO') ? 'block' : 'none';
  }
}

// --- MODAL EDITAR PERSONAL ---
function abrirModalEditarUsuario(id, username, firstName, lastName, email, rol, numCaja) {
  const modal = document.getElementById('modalEditarUsuario');
  const form = document.getElementById('formEditarUsuario');
  if (!modal || !form) return;

  // Asigna dinámicamente la URL con la PK del usuario en Django
  form.action = `/panel-admin/usuarios/personal/editar/${id}/`;

  // Rellena los datos actuales en el formulario
  document.getElementById('edit_username').value = username;
  document.getElementById('edit_first_name').value = firstName;
  document.getElementById('edit_last_name').value = lastName;
  document.getElementById('edit_email').value = email;
  document.getElementById('edit_rol').value = rol;
  document.getElementById('edit_num_caja').value = numCaja || 1;

  toggleCampoCajaEditar();
  modal.showModal();
}

function cerrarModalEditarUsuario() {
  const modal = document.getElementById('modalEditarUsuario');
  if (modal) modal.close();
}

function toggleCampoCajaEditar() {
  const selectRol = document.getElementById('edit_rol');
  const contenedorCaja = document.getElementById('contenedor_caja_editar');
  if (selectRol && contenedorCaja) {
    contenedorCaja.style.display = (selectRol.value === 'CAJERO') ? 'block' : 'none';
  }
}

// --- MODAL DESACTIVAR PERSONAL ---
function abrirModalDesactivarUsuario(id, username) {
  const modal = document.getElementById('modalDesactivarUsuario');
  const txtUsername = document.getElementById('desactivar_username');
  const btnConfirmar = document.getElementById('btnConfirmarDesactivar');
  
  if (!modal || !btnConfirmar) return;

  if (txtUsername) txtUsername.textContent = username;
  btnConfirmar.href = `/panel-admin/usuarios/personal/eliminar/${id}/`;

  modal.showModal();
}

function cerrarModalDesactivarUsuario() {
  const modal = document.getElementById('modalDesactivarUsuario');
  if (modal) modal.close();
}