(function () {
  const urlParams = new URLSearchParams(window.location.search);
  const tabUrl = urlParams.get('tab');
  const tabsValidas = ['insumos', 'productos', 'proveedores'];

  let referrerPath = '';
  if (document.referrer) {
    try {
      referrerPath = new URL(document.referrer).pathname;
    } catch (e) {}
  }

  const subrutasHijas = [
    '/panel-admin/inventario/historial-precios/',
    '/panel-admin/inventario/deficit/',
    '/panel-admin/inventario/mermas/'
  ];
  const vieneDeSubrutaHija =
    subrutasHijas.includes(referrerPath) ||
    /^\/panel-admin\/productos\/\d+\/receta\/$/.test(referrerPath);

  let tabInicial = 'insumos';
  if (tabUrl && tabsValidas.includes(tabUrl)) {
    tabInicial = tabUrl;
  } else if (vieneDeSubrutaHija) {
    const tabGuardada = sessionStorage.getItem('inventario_tab_activa');
    if (tabGuardada && tabsValidas.includes(tabGuardada)) {
      tabInicial = tabGuardada;
    }
  } else {
    sessionStorage.removeItem('inventario_tab_activa');
  }

  sessionStorage.setItem('inventario_tab_activa', tabInicial);
  document.documentElement.dataset.inventarioTab = tabInicial;

  if (tabInicial === 'productos' || tabInicial === 'proveedores') {
    const tabInsumos = document.getElementById('tabBtnInsumos');
    const tabActiva = document.getElementById(
      tabInicial === 'productos' ? 'tabBtnProductos' : 'tabBtnProveedores'
    );
    const titulo = document.getElementById('crudTituloPrincipal');

    if (tabInsumos) tabInsumos.classList.remove('activa');
    if (tabActiva) tabActiva.classList.add('activa');
    if (titulo) {
      titulo.textContent =
        tabInicial === 'productos'
          ? 'Gestión de productos de la panadería'
          : 'Gestión de proveedores de materias primas';
    }
  }
})();