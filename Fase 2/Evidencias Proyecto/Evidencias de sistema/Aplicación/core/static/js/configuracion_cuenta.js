// Formateo automático para números de teléfono chilenos (+56 9 XXXX XXXX)
function formatearTelefono(val) {
  let digitos = val.replace(/\D/g, '');

  if (digitos.startsWith('56')) {
    digitos = digitos.slice(2);
  }

  digitos = digitos.slice(0, 9);

  if (digitos.length === 0) return '';
  if (digitos.length <= 1) return `+56 ${digitos}`;
  if (digitos.length <= 5) return `+56 ${digitos.slice(0, 1)} ${digitos.slice(1)}`;

  return `+56 ${digitos.slice(0, 1)} ${digitos.slice(1, 5)} ${digitos.slice(5)}`;
}

document.addEventListener('DOMContentLoaded', () => {
  // 1. Formateo automático de teléfono al cargar y al escribir
  const inputsTel = document.querySelectorAll('.input-telefono');
  inputsTel.forEach((input) => {
    if (input.value) {
      input.value = formatearTelefono(input.value);
    }
    input.addEventListener('input', (e) => {
      e.target.value = formatearTelefono(e.target.value);
    });
  });

  // 2. Navegación por pestañas laterales
  const botonesTab = document.querySelectorAll('.cuenta-sidebar__item');
  const secciones = document.querySelectorAll('.cuenta-seccion');

  botonesTab.forEach((btn) => {
    btn.addEventListener('click', () => {
      botonesTab.forEach((b) => b.classList.remove('activa'));
      secciones.forEach((s) => s.classList.remove('activa'));

      btn.classList.add('activa');
      const target = document.getElementById(btn.dataset.tabTarget);
      if (target) {
        target.classList.add('activa');
      }
    });
  });

  // 3. Cerrar modal de eliminar cuenta al hacer clic fuera de la caja
  const modalEliminar = document.getElementById('modalEliminarCuenta');
  if (modalEliminar) {
    modalEliminar.addEventListener('click', (e) => {
      if (e.target === modalEliminar) {
        modalEliminar.close();
      }
    });
  }
});