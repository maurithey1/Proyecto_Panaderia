param(
    [string]$Destino = (Join-Path (Get-Location) "Proyecto_Panaderia-codigo")
)

$Repositorio = "https://github.com/maurithey1/Proyecto_Panaderia.git"
$RutaAplicacion = "/Fase 2/Evidencias Proyecto/Evidencias de sistema/Aplicación/**"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git no está instalado o no está disponible en PATH."
}

if (Test-Path $Destino) {
    throw "La ruta de destino ya existe: $Destino"
}

git clone --filter=blob:none --sparse $Repositorio $Destino
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo clonar el repositorio."
}

git -C $Destino sparse-checkout set --no-cone $RutaAplicacion
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo limitar el clon a la carpeta de la aplicación."
}

Write-Host "Aplicación clonada en: $Destino"
