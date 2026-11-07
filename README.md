# pc-robobo en Windows

Entorno Docker de la asignatura: Ubuntu 24.04 + ROS 2 Jazzy + paquetes del robot Robobo. Esta carpeta es la versión con Windows como sistema anfitrión; equivale a las carpetas `macOS` y `Ubuntu`.

## Requisitos en el host

- Windows 10 (22H2 o posterior) o Windows 11 con **WSL2** instalado y actualizado (`wsl --update` desde PowerShell).
- **Docker Desktop** con el *backend* WSL2 activado (Settings → General → *Use the WSL 2 based engine*). Con el backend Hyper-V no hay visualización gráfica.
- Opcional: GPU NVIDIA con el driver **de Windows** que da soporte a WSL2. No hay que instalar ningún driver ni `nvidia-container-toolkit` dentro de WSL; Docker Desktop se encarga.
- **Simulador de Robobo**. Se descarga de <https://github.com/mintforpeople/robobo-programming/wiki/Unity>; basta con descomprimir y ejecutar `Robobo Simulator Win64.exe`.

## Uso

Desde PowerShell, en esta carpeta:

```powershell
.\build.ps1      # construye la imagen
.\start.ps1      # levanta el contenedor y prepara el entorno
.\terminal.ps1   # abre un shell bash dentro del contenedor
```

`build.ps1` admite `-Robobo` y `-Pip` para rehacer la capa de `robobo_ros2` o la de los paquetes de Python, y `-All` para las dos. Hace falta porque Docker no comprueba si hay versiones nuevas: reutiliza la capa mientras no cambie el texto del `Dockerfile`, de modo que sin esas opciones se seguiría usando el código y los paquetes de la primera construcción.

Si Windows se niega a ejecutar los scripts (*"la ejecución de scripts está deshabilitada en este sistema"*), hay dos salidas: usar el menú contextual del Explorador → **Ejecutar con PowerShell**, o permitirlo solo en esa ventana:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Para conectar con el simulador desde ROS 2, en un shell del contenedor:

```bash
ros2 run robobo_ros2 robobo_container --ros-args -p ip:=host.docker.internal
```

`host.docker.internal` es el nombre con el que el contenedor alcanza al equipo anfitrión, que es donde corre el simulador.

El `source` de `/opt/ros/robobo/setup.bash` está en `/root/.bashrc`, así que el entorno de ROS 2 y de los paquetes del Robobo ya está cargado en el shell que abre `terminal.ps1`. Las aplicaciones gráficas (rviz2, Gazebo) se lanzan desde ese mismo shell y aparecen como ventanas de Windows.

El directorio `docker-ros` de esta carpeta se monta dentro del contenedor en `/docker-ros`; es donde conviene tener el workspace (`docker-ros/ws`).

Para parar el contenedor: `docker compose down`.

### Autenticación del servidor X

Aquí no hace falta el `XAUTHORITY` que sí prepara la versión de Ubuntu: el servidor X de WSLg es uno dedicado que vive en la máquina virtual de WSL y cuyo socket solo es alcanzable desde dentro de WSL (y desde los contenedores a los que Docker Desktop se lo monta). No hay otros procesos del sistema de los que protegerse, así que no exige cookie y tampoco hay nada equivalente al riesgo de un `xhost +local:`.

En Ubuntu el caso es el contrario: el servidor X es el de la sesión de escritorio real, compartido con todo lo que corre en la máquina, y por eso ahí se genera una cookie en vez de abrirlo.

## Visualización: WSLg

WSL2 incluye **WSLg**, que ya proporciona un servidor X (Xwayland) y un compositor Wayland integrados con el escritorio de Windows. Docker Desktop expone sus sockets en `/run/desktop/mnt/host/wslg`, y `docker-compose.yml` los monta en el contenedor junto con las variables correspondientes:

```yaml
- /run/desktop/mnt/host/wslg/.X11-unix:/tmp/.X11-unix
- /run/desktop/mnt/host/wslg:/mnt/wslg
...
- DISPLAY=:0
- WAYLAND_DISPLAY=wayland-0
- XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir
- PULSE_SERVER=/mnt/wslg/PulseServer
```

WSLg habla **los dos protocolos**: un compositor Wayland (Weston), que publica `wayland-0`, y un servidor **Xwayland** para los clientes X11, en el display `:0`. De ahí que el `docker-compose.yml` exporte a la vez `DISPLAY` y `WAYLAND_DISPLAY`: cada aplicación usa el que sepa. rviz2 y Gazebo tiran de X11 vía Xwayland, igual que en Ubuntu.

## Rendimiento gráfico

`start.ps1` decide qué ficheros de compose usar según lo que encuentre:

| Situación detectada | Ficheros usados |
|---|---|
| `nvidia-smi` responde y el contenedor puede usar la GPU | `docker-compose.yml` + `docker-compose.nvidia.yml` |
| Cualquier otro caso | solo `docker-compose.yml` (renderizado de WSLg) |

La reserva de GPU vive en `docker-compose.nvidia.yml` y **no** en el fichero base a propósito: declarar `driver: nvidia` en un equipo sin GPU NVIDIA hace fallar el arranque con `could not select device driver "" with capabilities: [[gpu]]`.

La detección **no** se hace mirando los runtimes que expone `docker info`: Docker Desktop trae el runtime `nvidia` registrado aunque el equipo no tenga ninguna GPU NVIDIA, de modo que ese criterio da falsos positivos. Se comprueba el driver del host con `nvidia-smi` y, si responde, se verifica que el contenedor pueda usar la GPU de verdad con un `docker run --gpus all` sobre la imagen ya construida.

En Windows el separador de la variable `COMPOSE_FILE` es `;` (en Linux y macOS es `:`); por eso `start.ps1` la construye así y no copiando la línea de Ubuntu.

A diferencia del `docker-compose.nvidia.yml` de Ubuntu, aquí no se define `NVIDIA_DRIVER_CAPABILITIES`. Esa variable sirve para que el `nvidia-container-toolkit` inyecte en el contenedor las bibliotecas de la capacidad `graphics` (OpenGL, EGL, Vulkan), que no entran por defecto —el valor por omisión es `utility,compute`—. En Ubuntu es lo que permite que rviz2 y Gazebo rendericen con la GPU NVIDIA. En WSL2 el camino gráfico es otro: el OpenGL lo resuelve WSLg con Mesa sobre `/dev/dxg`, no las bibliotecas GLX de NVIDIA, así que la variable no cambiaría el renderizado. Lo que la reserva de GPU aporta aquí es acceso a **CUDA** desde el contenedor, no aceleración 3D.

## El nombre de usuario

`start.ps1` pasa `DOCKER_USER` al contenedor para crear allí el usuario. El nombre de cuenta de Windows puede llevar espacios o tildes (`José Antonio`), que no son válidos en Linux, así que el script quita los acentos, pasa a minúsculas, filtra todo lo que no sea `[a-z0-9_-]`, recorta a 32 caracteres y garantiza que empiece por letra (`José Antonio` → `joseantonio`). Si el nombre queda vacío usa `alumno`. Cuando lo adapta, lo dice por pantalla.

`DOCKER_UID` y `DOCKER_GID` van fijos a 1000, que es lo habitual en WSL2.

## Problemas frecuentes

- **`docker: error during connect` o el script avisa de que Docker no responde**: Docker Desktop no está arrancado o aún está iniciándose.
- **No se abre ninguna ventana gráfica**: comprobar que Docker Desktop usa el backend WSL2 y que WSL está actualizado (`wsl --update`, luego `wsl --shutdown` y reabrir Docker Desktop).
- **`could not select device driver`**: es el síntoma de haber declarado la reserva NVIDIA sin GPU; con `start.ps1` no debería ocurrir, pero sí si se lanza `docker compose up` a mano con `COMPOSE_FILE` mal puesta.
- **El contenedor no ve al Robobo**: comprobar que el móvil y el PC están en la misma red.
