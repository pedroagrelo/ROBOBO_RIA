# Comprobación previa: Docker instalado y en marcha
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: no se encuentra el comando 'docker'. Instala Docker Desktop"
    Write-Host "       y vuelve a abrir PowerShell."
    exit 1
}

docker info > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker no responde. Arranca Docker Desktop, espera a que"
    Write-Host "       el icono deje de moverse y vuelve a ejecutar este script."
    exit 1
}

# Usuario dentro del contenedor.
# El nombre de usuario de Windows puede llevar espacios o tildes ("José Antonio"),
# que no son válidos para crear un usuario de Linux: se quitan los acentos y todo
# lo que no sea [a-z0-9_-].
$nombre = $env:USERNAME.Normalize([Text.NormalizationForm]::FormD)
$nombre = ($nombre.ToCharArray() | Where-Object {
    [Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne 'NonSpacingMark'
}) -join ''
$nombre = $nombre.ToLower() -replace '[^a-z0-9_-]', ''
if ($nombre.Length -gt 32) { $nombre = $nombre.Substring(0, 32) }
if ($nombre -notmatch '^[a-z_]') { $nombre = "u$nombre" }
if ([string]::IsNullOrWhiteSpace($nombre)) { $nombre = "alumno" }

$env:DOCKER_USER = $nombre
$env:DOCKER_UID = "1000"
$env:DOCKER_GID = "1000"
if ($nombre -ne $env:USERNAME.ToLower()) {
    Write-Host "Usuario dentro del contenedor: $nombre (adaptado de '$env:USERNAME')"
}

# GPU NVIDIA: se comprueba el driver del host con nvidia-smi, no los runtimes de
# Docker. Docker Desktop trae el runtime 'nvidia' registrado aunque no haya GPU.
$nvidiaSmi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
if (-not $nvidiaSmi -and (Test-Path "$env:SystemRoot\System32\nvidia-smi.exe")) {
    $nvidiaSmi = "$env:SystemRoot\System32\nvidia-smi.exe"
}
$tieneGpu = $false
if ($nvidiaSmi) {
    & $nvidiaSmi -L > $null 2>&1
    if ($LASTEXITCODE -eq 0) { $tieneGpu = $true }
}

$env:COMPOSE_FILE = "docker-compose.yml"
if ($tieneGpu) {
    # Comprobación funcional con la imagen ya construida: declarar la reserva sin
    # que el contenedor pueda usar la GPU hace fallar el 'docker compose up'.
    docker image inspect pc-robobo > $null 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "GPU NVIDIA detectada, pero la imagen aún no existe: construye con .\build.ps1"
    } else {
        docker run --rm --gpus all pc-robobo true > $null 2>&1
        if ($LASTEXITCODE -eq 0) {
            $env:COMPOSE_FILE = "docker-compose.yml;docker-compose.nvidia.yml"
            Write-Host "GPU NVIDIA utilizable desde el contenedor: aceleración activada."
        } else {
            Write-Host "AVISO: hay GPU NVIDIA pero el contenedor no puede usarla. Comprueba el"
            Write-Host "       driver con soporte de WSL2 y ejecuta 'wsl --update'. Se sigue sin ella."
        }
    }
} else {
    Write-Host "Sin GPU NVIDIA: se usará el renderizado de WSLg."
}

Write-Host "Levantando contenedor..."
docker compose up -d

Write-Host "Habilitando multicast en loopback dentro del contenedor..."
docker compose exec pc-robobo ip link set lo multicast on

Write-Host "Listo. Abre un shell dentro del contenedor con .\terminal.ps1"
