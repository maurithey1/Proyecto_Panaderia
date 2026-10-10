# Proyecto Panadería

## Clonar solo el código del sistema

Para descargar únicamente la aplicación, sin las fases ni sus evidencias, ejecuta
estos comandos en PowerShell desde la carpeta donde quieras guardar el proyecto:

```powershell
git clone --filter=blob:none --sparse https://github.com/maurithey1/Proyecto_Panaderia.git Proyecto_Panaderia-codigo
git -C Proyecto_Panaderia-codigo sparse-checkout set --no-cone "/Fase 2/Evidencias Proyecto/Evidencias de sistema/Aplicación/**"
```

El clon incluirá la carpeta `Aplicación` completa (código, plantillas, archivos
estáticos, recursos y configuración necesaria) y excluirá el resto del repositorio,
incluidas las otras fases y evidencias.
