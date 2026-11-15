function cambiarPestanaComparador(nombre) {
  // Desactivar todos los botones y ocultar paneles
  const botones = document.querySelectorAll('.crud-pestana-btn');
  botones.forEach(b => b.classList.remove('activa'));

  const paneles = document.querySelectorAll('.comparador-panel-seccion');
  paneles.forEach(p => p.style.display = 'none');

  // Activar botón y panel correspondiente
  const btn = document.getElementById('tabBtn_' + nombre);
  const panel = document.getElementById('panel_' + nombre);
  if (btn) btn.classList.add('activa');
  if (panel) panel.style.display = 'block';

  // Actualizar parámetro en la URL sin recargar
  const url = new URL(window.location);
  url.searchParams.set('tab', nombre);
  window.history.replaceState({}, '', url);
}

document.addEventListener('DOMContentLoaded', function () {
  const dialog = document.getElementById('modalConfirmacionCotizacion');
  const msg = document.getElementById('confirmCotizMensaje');
  const btnCancelar = document.getElementById('confirmCotizCancelar');
  const btnAceptar = document.getElementById('confirmCotizAceptar');
  let formPendiente = null;

  document.querySelectorAll('.form-eliminar-cotizacion').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!dialog || typeof dialog.showModal !== 'function') return;
      e.preventDefault();
      formPendiente = form;
      msg.textContent = `¿Eliminar la cotización de "${form.dataset.proveedor}"?`;
      dialog.showModal();
    });
  });

  if (btnCancelar) {
    btnCancelar.addEventListener('click', function () {
      formPendiente = null;
      dialog.close();
    });
  }
  if (btnAceptar) {
    btnAceptar.addEventListener('click', function () {
      if (formPendiente) {
        const f = formPendiente;
        formPendiente = null;
        dialog.close();
        f.submit();
      }
    });
  }
});