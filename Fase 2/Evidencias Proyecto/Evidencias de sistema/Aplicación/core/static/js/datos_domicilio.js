/* ==========================================
   FORMULARIO MULTI-PASO DE REGISTRO (STEPPER)
   ========================================== */

document.addEventListener('DOMContentLoaded', () => {
  const paso1 = document.getElementById('paso-1');
  const paso2 = document.getElementById('paso-2');
  const ind1 = document.getElementById('indicador-paso-1');
  const ind2 = document.getElementById('indicador-paso-2');
  const linea = document.getElementById('linea-paso');
  const btnContinuar = document.getElementById('btn-continuar');
  const btnVolver = document.getElementById('btn-volver');
  const form = document.getElementById('form-registro');
  const alerta = document.getElementById('js-alerta');

  if (!form || !btnContinuar) return; // Si no estamos en la página de registro, no ejecuta nada

  function mostrarError(mensaje) {
    alerta.textContent = mensaje;
    alerta.style.display = 'block';
    alerta.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function ocultarError() {
    alerta.style.display = 'none';
    alerta.textContent = '';
  }

  // Botón Continuar (Paso 1 -> Paso 2)
  btnContinuar.addEventListener('click', function() {
    ocultarError();

    const rut = document.getElementById('id_rut').value.trim();
    const nombre = document.getElementById('id_first_name').value.trim();
    const apellidos = document.getElementById('id_last_name').value.trim();
    const email = document.getElementById('id_email').value.trim();
    const telefono = document.getElementById('id_telefono').value.trim();
    const pass = document.getElementById('id_password').value;
    const passConf = document.getElementById('id_password_confirm').value;

    if (!rut || !nombre || !apellidos || !email || !telefono || !pass || !passConf) {
      mostrarError('Por favor completa todos los campos del Paso 1.');
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      mostrarError('Por favor ingresa un correo electrónico válido.');
      return;
    }

    if (pass.length < 6) {
      mostrarError('La contraseña debe tener al menos 6 caracteres.');
      return;
    }

    if (pass !== passConf) {
      mostrarError('Las contraseñas ingresadas no coinciden.');
      return;
    }

    paso1.classList.add('oculto');
    paso2.classList.remove('oculto');

    ind1.classList.remove('activo');
    ind1.classList.add('completado');
    linea.classList.add('completada');
    ind2.classList.add('activo');

    window.scrollTo({ top: paso2.offsetTop - 80, behavior: 'smooth' });
  });

  // Botón Volver (Paso 2 -> Paso 1)
  btnVolver.addEventListener('click', function() {
    ocultarError();

    paso2.classList.add('oculto');
    paso1.classList.remove('oculto');

    ind2.classList.remove('activo');
    linea.classList.remove('completada');
    ind1.classList.remove('completado');
    ind1.classList.add('activo');

    window.scrollTo({ top: paso1.offsetTop - 80, behavior: 'smooth' });
  });

  // Validación final al enviar
  form.addEventListener('submit', function(e) {
    ocultarError();

    const region = document.getElementById('id_region').value.trim();
    const comuna = document.getElementById('id_comuna').value.trim();
    const dir1 = document.getElementById('id_direccion1').value.trim();

    if (!region || !comuna || !dir1) {
      e.preventDefault();
      mostrarError('Por favor completa los campos de Región, Comuna y Dirección 1.');
    }
  });
});