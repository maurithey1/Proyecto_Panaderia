@echo off
rem Script para aplicar migraciones y cargar productos iniciales en el contenedor Docker

echo ====================================================
echo  Iniciando configuracion y carga de base de datos
echo ====================================================

echo [1/3] Creando migraciones pendientes...
docker exec -it panaderia_web python manage.py makemigrations

echo [2/3] Aplicando migraciones a la base de datos...
docker exec -it panaderia_web python manage.py migrate

echo [3/4] Cargando catálogo de productos iniciales...
docker exec -it panaderia_web python manage.py cargar_productos

echo [4/4] Configurando usuario administrador...
docker exec -it panaderia_web python manage.py crear_admin

echo ====================================================
echo  Proceso completado exitosamente.
echo ====================================================
pause
