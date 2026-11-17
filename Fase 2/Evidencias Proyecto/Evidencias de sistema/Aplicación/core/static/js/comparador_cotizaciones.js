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

document.addEventListener('DOMContentLoaded', function () {
  const ETIQUETAS_PROVEEDOR = {
    'HARINA': 'Molinera',
    'LACTEO': 'Proveedor de Lácteos',
    'HUEVO': 'Avícola / Proveedor',
    'LEVADURA': 'Proveedor de Insumos',
    'AZUCAR': 'Proveedor / Distribuidor',
    'SEMILLAS': 'Proveedor / Distribuidor',
    'OTRO': 'Proveedor'
  };

  function pluralizarEnvase(envase) {
  const limpio = (envase || 'saco').trim().toLowerCase();
  const [primera, ...resto] = limpio.split(/\s+/);
  const sinTilde = primera.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const capitalizada = primera.charAt(0).toUpperCase() + primera.slice(1);

  let primeraPlural;
  if (/[aeiou]$/.test(sinTilde)) {
    primeraPlural = capitalizada + 's';
  } else if (primera.endsWith('ón')) {
    primeraPlural = capitalizada.slice(0, -2) + 'ones';
  } else {
    primeraPlural = capitalizada + 'es';
  }

  return resto.length ? `${primeraPlural} ${resto.join(' ')}` : primeraPlural;
}

  // 1. Cuadro superior (Comparación)
  const selComp = document.getElementById('selectInsumoComparar');
  const lblCantComp = document.getElementById('labelCantidadComparar');

  function actualizarLabelsComparar() {
    if (!selComp || !lblCantComp) return;
    const opt = selComp.options[selComp.selectedIndex];
    const envase = (opt && opt.dataset.envase) ? opt.dataset.envase : 'saco';
    lblCantComp.textContent = `${pluralizarEnvase(envase)} a comprar`;
  }

  if (selComp) {
    selComp.addEventListener('change', actualizarLabelsComparar);
    actualizarLabelsComparar();
  }

  // 2. Cuadro inferior (Registrar / Actualizar cotización)
  const selGuard = document.getElementById('selectInsumoGuardar');
  const lblProvGuard = document.getElementById('labelProveedorGuardar');
  const lblPrecioGuard = document.getElementById('labelPrecioGuardar');
  const tituloGuard = document.getElementById('tituloGuardarCotizacion');

  function actualizarLabelsGuardar() {
    if (!selGuard) return;
    const opt = selGuard.options[selGuard.selectedIndex];
    const envase = (opt && opt.dataset.envase) ? opt.dataset.envase.toLowerCase() : 'saco';
    const tipo = (opt && opt.dataset.tipo) ? opt.dataset.tipo : 'HARINA';
    const nombreProv = ETIQUETAS_PROVEEDOR[tipo] || 'Proveedor';

    if (lblProvGuard) lblProvGuard.textContent = nombreProv;
    if (lblPrecioGuard) lblPrecioGuard.textContent = `Precio por ${envase} ($)`;
    if (tituloGuard) {
      tituloGuard.textContent = opt && opt.value
        ? `Registrar o actualizar cotización (${nombreProv})`
        : 'Registrar o actualizar cotización de proveedor';
    }
  }

  if (selGuard) {
    selGuard.addEventListener('change', actualizarLabelsGuardar);
    actualizarLabelsGuardar();
  }
});

// Formateo y validación de precio (> $ 0) en Guardar Cotización
document.addEventListener('DOMContentLoaded', function () {
  const formGuardar = document.getElementById('formGuardarCotizacion');
  const inputPrecio = document.getElementById('inputPrecioGuardar');
  if (!inputPrecio) return;

  inputPrecio.addEventListener('input', function (e) {
    const limpio = e.target.value.replace(/\D/g, '');
    e.target.value = limpio ? `$ ${parseInt(limpio, 10).toLocaleString('es-CL')}` : '';
    inputPrecio.setCustomValidity('');
  });

  if (formGuardar) {
    formGuardar.addEventListener('submit', function (e) {
      const monto = parseInt(inputPrecio.value.replace(/\D/g, ''), 10) || 0;
      if (monto <= 0) {
        e.preventDefault();
        inputPrecio.setCustomValidity('El precio debe ser mayor a $ 0.');
        inputPrecio.reportValidity();
        inputPrecio.focus();
      } else {
        inputPrecio.setCustomValidity('');
      }
    });
  }
});

// Bloquear negativos, 0 y caracteres no numéricos en "Cantidad a comprar"
document.addEventListener('DOMContentLoaded', function () {
  const inputCantidad = document.querySelector('input[name="sacos"]');
  if (!inputCantidad) return;

  inputCantidad.addEventListener('keydown', function (e) {
    if (['-', '+', 'e', 'E', '.', ','].includes(e.key)) {
      e.preventDefault();
    }
  });

  inputCantidad.addEventListener('input', function () {
    const soloDigitos = inputCantidad.value.replace(/\D/g, '');
    if (!soloDigitos) {
      inputCantidad.value = '';
      return;
    }
    const numero = parseInt(soloDigitos, 10);
    inputCantidad.value = numero > 0 ? String(numero) : '';
  });

  inputCantidad.addEventListener('blur', function () {
    const numero = parseInt(inputCantidad.value, 10);
    if (!numero || numero < 1) {
      inputCantidad.value = '1';
    }
  });
});