# Construye la imagen. Sin opciones, Docker reutiliza la caché: ni vuelve a clonar
# robobo_ros2 ni reinstala los paquetes de pip, aunque haya versiones nuevas.
#   -Pip      rehace la capa de pip (scipy, robobopy, PyTorch...). Arrastra
#             también la de robobo_ros2.
#   -Robobo   rehace la capa de robobo_ros2
#   -All      rehace las dos
#   -TorchVariant cpu|cuda   fuerza la variante de PyTorch en vez de detectar la GPU
param(
    [switch]$Robobo,
    [switch]$Pip,
    [switch]$All,
    [ValidateSet("cpu", "cuda")][string]$TorchVariant
)

$ahora = [int][double]::Parse((Get-Date -UFormat %s))
$roboboCachebust = 0
$pipCachebust = 0
if ($Robobo -or $All) { $roboboCachebust = $ahora }
if ($Pip -or $All)    { $pipCachebust = $ahora }

if (-not $TorchVariant) {
    $nvidiaSmi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
    if (-not $nvidiaSmi -and (Test-Path "$env:SystemRoot\System32\nvidia-smi.exe")) {
        $nvidiaSmi = "$env:SystemRoot\System32\nvidia-smi.exe"
    }
    $tieneGpu = $false
    if ($nvidiaSmi) {
        & $nvidiaSmi -L > $null 2>&1
        if ($LASTEXITCODE -eq 0) { $tieneGpu = $true }
    }
    if ($tieneGpu) { $TorchVariant = "cuda" } else { $TorchVariant = "cpu" }
}

if ($TorchVariant -eq "cuda") {
    Write-Host "GPU NVIDIA detectada: PyTorch con CUDA (la imagen crecerá varios GB)."
    Write-Host "Si el contenedor no llegara a usar la GPU, PyTorch funcionaría en CPU."
} else {
    Write-Host "PyTorch para CPU: no se instalará ningún paquete de NVIDIA."
}

if ($roboboCachebust -ne 0) { Write-Host "Se rehará la capa de robobo_ros2 (clonado y compilación)." }
if ($pipCachebust -ne 0)    { Write-Host "Se reinstalarán los paquetes de pip." }

docker build --progress=plain `
    --build-arg ROBOBO_CACHEBUST=$roboboCachebust `
    --build-arg PIP_CACHEBUST=$pipCachebust `
    --build-arg TORCH_VARIANT=$TorchVariant `
    -t pc-robobo .
