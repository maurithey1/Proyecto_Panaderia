# Proyecto Panadería
Proyecto de título.

## Ejecución con Docker

Para iniciar el entorno de desarrollo y los servicios de base de datos y aplicación:

```bash
cd "Fase 2/Evidencias Proyecto/Evidencias de sistema/Aplicación"
docker compose up --build
```

El servicio `web` está configurado para ejecutar automáticamente al iniciar:
1. `python manage.py makemigrations` (generación de migraciones pendientes)
2. `python manage.py migrate` (aplicación de cambios en la base de datos)
3. `python manage.py cargar_productos` (carga de productos y categorías iniciales desde `productos_prueba.json`)
4. `python manage.py crear_admin` (asegura el usuario administrador `admin` con contraseña `admin123456`)
5. `python manage.py runserver 0.0.0.0:8000` (inicio del servidor web)

### Credenciales de acceso

- **Rol Administrador**:
  - **Usuario**: `admin`
  - **Contraseña**: `admin123456`
  - **Acceso Web**: [http://localhost:8000/login/](http://localhost:8000/login/) (redirige al panel de administración `/admin-panel/`)
  - **Panel Django**: [http://localhost:8000/admin/](http://localhost:8000/admin/)

### Ejecución manual de comandos

Si necesitas volver a ejecutar estos pasos de forma manual mientras los contenedores están activos:

- **Windows**: Ejecuta el archivo `inicializar_datos.bat` o:
  ```bash
  docker exec -it panaderia_web python manage.py makemigrations
  docker exec -it panaderia_web python manage.py migrate
  docker exec -it panaderia_web python manage.py cargar_productos
  docker exec -it panaderia_web python manage.py crear_admin
  ```
- **Linux / macOS**: Ejecuta `./inicializar_datos.sh`
