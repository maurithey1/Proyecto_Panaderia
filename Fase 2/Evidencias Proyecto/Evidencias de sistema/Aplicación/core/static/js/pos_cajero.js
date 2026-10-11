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