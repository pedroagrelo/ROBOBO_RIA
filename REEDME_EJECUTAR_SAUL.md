# REEDME_EJECUTAR_SAUL — Cómo ejecutar la P2 (NEAT con Robobo)

Guía paso a paso para lanzar el contenedor, evolucionar, probar controladores y
generar las gráficas. Todo el código de la P2 está en `docker-ros/ws/p2/`; reutiliza
los módulos de la P1 que hay en `docker-ros/ws/` (`p1_follow_env.py`, `p1_ros.py`,
`p1_config.py`, `p1_evaluar.py`, `config_v2.yaml`). No muevas ninguna de estas
carpetas: `p2/` busca los módulos de la P1 en la carpeta de arriba y lee
`../config_v2.yaml`.

---

## 0. Qué hay en el repo

| Ruta | Para qué sirve |
|---|---|
| `Dockerfile`, `docker-compose*.yml` | Imagen `pc-robobo` (ROS 2 Jazzy, robobo_ros2, neat-python, stable-baselines3, gymnasium...) |
| `build.ps1`, `start.ps1`, `terminal.ps1` | Construir la imagen, levantar el contenedor y abrir un shell dentro |
| `docker-ros/ws/config_v2.yaml`, `p1_*.py` | Entorno de la P1 reutilizado por la P2 |
| `docker-ros/ws/p2/config-p2.ini` | Parámetros de NEAT (población, mutaciones, especiación...) |
| `docker-ros/ws/p2/config_p2.yaml` | Duración del episodio, fallos del anexo B, arranque y **coeficientes de la función de calidad** |
| `docker-ros/ws/p2/p2_calidad.py` | La función de calidad (formulaciones A, B y C) |
| `docker-ros/ws/p2/p2_entorno.py` | Entorno de evaluación (real con RoboboSim, o `--falso` sin simulador) |
| `docker-ros/ws/p2/p2_controladores.py` | Controladores: red NEAT, PD de referencia y aleatorio |
| `docker-ros/ws/p2/p2_evolucionar.py` | **Evolución** (programa principal) |
| `docker-ros/ws/p2/p2_probar.py` | **Probar** un controlador o genoma y ver su calidad |
| `docker-ros/ws/p2/p2_graficas.py` | **Gráficas**: curvas de evolución y topología de la red |
| `docker-ros/ws/p2/p2_registro.py` | Escribe `evolucion.csv` y el mejor genoma de cada generación |
| `docker-ros/ws/p2/resultados/<etiqueta>/` | Resultados de cada entrenamiento (ver sección 7) |
| `docker-ros/ws/p2/curvas_*.png`, `red_*.png`, `candidatos_*.txt` | Figuras y reevaluaciones ya generadas |

---

## 1. Requisitos en el PC (Windows)

- Windows 10 (22H2+) o 11 con **WSL2** actualizado (`wsl --update`).
- **Docker Desktop** con el backend WSL2 activado.
- **RoboboSim** (simulador de Robobo): descomprimir y ejecutar `Robobo Simulator Win64.exe`
  (descarga: <https://github.com/mintforpeople/robobo-programming/wiki/Unity>).
- Git.

Si PowerShell no deja ejecutar los `.ps1`, en esa ventana:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

---

## 2. Obtener el código

```powershell
git clone https://github.com/pedroagrelo/ROBOBO_RIA.git
cd ROBOBO_RIA
```

Todos los comandos `.\build.ps1`, `.\start.ps1` y `.\terminal.ps1` se ejecutan desde
esa carpeta (la que contiene el `Dockerfile`).

> Si el repo tiene otra estructura al clonar, la carpeta correcta es la que tiene
> `Dockerfile`, `docker-compose.yml` y `docker-ros/` juntos.

---

## 3. Lanzar el contenedor

```powershell
.\build.ps1      # construye la imagen (solo la primera vez; tarda un rato)
.\start.ps1      # levanta el contenedor
.\terminal.ps1   # abre un shell bash DENTRO del contenedor
```

- Docker Desktop tiene que estar arrancado antes de `start.ps1`.
- `build.ps1 -Pip` rehace la capa de paquetes de Python; `-Robobo` la de `robobo_ros2`;
  `-All` las dos.
- Para parar el contenedor: `docker compose down`. Ojo: al hacer `down` el contenedor
  se elimina y se pierde lo instalado a mano con `pip` dentro de él (ver `robobosim`
  más abajo). Los ficheros de `docker-ros/` sí se conservan, porque es una carpeta
  del PC montada en el contenedor.

La carpeta `docker-ros/` del PC aparece dentro del contenedor como `/docker-ros`, así
que **la carpeta de trabajo de la P2 en el contenedor es `/docker-ros/ws/p2`**. Todo
lo que se escriba allí (resultados, gráficas) aparece también en tu PC.

---

## 4. Preparar el simulador y el puente (solo si se usa RoboboSim)

Hacen falta **dos shells** del contenedor (abre otro `.\terminal.ps1` en otra ventana).

### 4.1. RoboboSim

1. Abrir `Robobo Simulator Win64.exe` en Windows.
2. Cargar la escena **Follow City**.
3. Dejar el guía en la configuración **C1** (sin aleatoriedad en su velocidad). Las
   etiquetas `C3_*` de las carpetas de `resultados/` son solo nombres de ejecución.
4. El multiplicador de velocidad del simulador debe ser el mismo en la evolución y en
   cualquier evaluación posterior.

### 4.2. `robobosim` dentro del contenedor (una vez por contenedor)

La función de calidad lee las posiciones reales del simulador con `robobosim`. Si
`python3 -c "import robobosim"` da error:

```bash
pip install robobosim
```

(Hace falta volver a instalarlo si se recrea el contenedor con `docker compose down`.)

### 4.3. Puente ROS 2 (shell nº 1, dejarlo abierto)

```bash
ros2 run robobo_ros2 robobo_container --ros-args -p ip:=host.docker.internal -p modules:="['blob','sim']"
```

Debe aparecer algo como `Connected to RoboboSim at host.docker.internal:50505`.
Lanzar **un solo puente**. Si se cuelga: Ctrl-C y volver a lanzarlo.

---

## 5. Ejecutar la P2 (shell nº 2)

```bash
cd /docker-ros/ws/p2
```

### 5.1. Probar que todo funciona SIN simulador

Con `--falso` se usa una cinemática 2D mínima (guía en círculo). Sirve para comprobar
el programa, no sustituye a RoboboSim. No hace falta puente ni simulador.

```bash
python3 p2_calidad.py                                            # la calidad ordena como se espera
python3 p2_probar.py --controlador pd --falso C3 --episodios 3   # calidad del PD de referencia
python3 p2_probar.py --controlador aleatorio --falso C3          # línea base
python3 p2_evolucionar.py --falso C4 --etiqueta prueba --generaciones 10 --sin-pausa
```

### 5.2. Referencia: PD a mano y controlador aleatorio (con RoboboSim)

Misma función de calidad para ambos:

```bash
python3 p2_probar.py --controlador pd --episodios 3
python3 p2_probar.py --controlador aleatorio --episodios 3
```

### 5.3. Prueba corta de evolución (mide cuánto dura una generación)

```bash
python3 p2_evolucionar.py --etiqueta test --generaciones 2
```

La columna `segundos` de `resultados/test/evolucion.csv` indica la duración. Como orden
de magnitud, la ejecución `C3_s51` (50 generaciones, 70 evaluaciones por generación,
episodios de 70 s) tardó unas 9,5 horas (34 544 s en el CSV).

### 5.4. Evolución (entrenamiento)

```bash
python3 p2_evolucionar.py --etiqueta C3_s51 --generaciones 50 --seed 51 --pop 35
```

Antes de empezar pide pulsar Enter (para que dé tiempo a dejar RoboboSim listo); con
`--sin-pausa` no espera.

| Opción | Qué hace |
|---|---|
| `--etiqueta NOMBRE` | **Obligatoria.** Guarda en `resultados/<NOMBRE>/` |
| `--generaciones N` | Generaciones **totales** (con `--reanudar` solo hace las que faltan) |
| `--seed S` | Semilla de NEAT (por defecto la de `config-p2.ini`) |
| `--pop N` | Tamaño de población (sobrescribe `config-p2.ini`) |
| `--episodios K` | Episodios por individuo (sobrescribe `config_p2.yaml`) |
| `--duracion S` | Duración máxima del episodio en segundos (sobrescribe `config_p2.yaml`) |
| `--formulacion A\|B\|C` | Formulación de la calidad (sobrescribe `config_p2.yaml`) |
| `--falso [C1..C4]` | Entorno sin simulador |
| `--reanudar` | Continúa desde el último punto de control (`chk/`) de esa etiqueta |
| `--sin-pausa` | No espera a Enter |
| `--config-neat RUTA` / `--config-p2 RUTA` | Usar otros ficheros de configuración |

Con `--pop 35` y 2 episodios por individuo, cada generación hace 70 evaluaciones.

### 5.5. Si se cae la comunicación en mitad de una evolución

1. Ctrl-C en el shell de la evolución.
2. Relanzar el puente (sección 4.3).
3. Repetir **el mismo comando** añadiendo `--reanudar`:

```bash
python3 p2_evolucionar.py --etiqueta C3_s51 --generaciones 50 --seed 51 --pop 35 --reanudar
```

Nunca se asigna calidad 0 al individuo afectado por la caída.

### 5.6. Probar un genoma ya entrenado

Un solo genoma (el mejor de la ejecución):

```bash
python3 p2_probar.py --genoma resultados/C3_s51/mejor_genoma.pkl --config-neat resultados/C3_s51/config-p2.ini --episodios 5
```

Reevaluar varios candidatos (el comodín va entre comillas) y guardar la salida:

```bash
python3 p2_probar.py --genoma 'resultados/C3_s51/genomas/mejor_gen0*.pkl' --config-neat resultados/C3_s51/config-p2.ini --episodios 5 2>&1 | tee candidatos_C3_s51.txt
```

Importante: usar siempre el `config-p2.ini` **de la carpeta de resultados** del
genoma, no el de `p2/`, para que la red tenga la misma estructura con la que se evolucionó.

Otras opciones de `p2_probar.py`:

| Opción | Qué hace |
|---|---|
| `--controlador pd\|aleatorio` | Controlador de referencia (alternativa a `--genoma`) |
| `--episodios K` | Nº de episodios (por defecto 3) |
| `--duracion S` | Duración del episodio; 120 reproduce el anexo B |
| `--formulacion A\|B\|C` | Formulación de la calidad |
| `--guardar-pasos CARPETA` | Guarda una fila por paso de cada episodio (para figuras) |
| `--falso [C1..C4]` | Sin simulador |
| `--seed N` | Semilla (por defecto 0) |

---

## 6. Gráficas (no necesitan simulador ni puente)

Solo necesitan `numpy`, `matplotlib`, `neat-python` y los CSV/genomas de `resultados/`.
Se pueden generar dentro del contenedor, en `/docker-ros/ws/p2`.

### 6.1. Curvas de evolución

Calidad del mejor y media de la población (banda = desviación típica) frente a la
generación; abajo, nº de especies y complejidad del mejor. Con varios CSV (semillas)
dibuja la media entre semillas con banda mín–máx.

```bash
# una ejecución
python3 p2_graficas.py curvas resultados/C3_s51/evolucion.csv --salida curvas_C3_s51.png

# varias ejecuciones juntas
python3 p2_graficas.py curvas resultados/C3_s50/evolucion.csv resultados/C3_s51/evolucion.csv --salida curvas_comparacion.png

# con una línea horizontal de referencia (calidad del controlador a mano, valor a poner)
python3 p2_graficas.py curvas resultados/C3_s51/evolucion.csv --ref 60 --salida curvas_C3_s51.png
```

### 6.2. Topología de la red

Grosor = |peso|, verde = peso positivo, rojo = negativo.

```bash
python3 p2_graficas.py red resultados/C3_s51/mejor_genoma.pkl --config resultados/C3_s51/config-p2.ini --salida red_C3_s51.png
```

---

## 7. Resultados incluidos en el repo (`resultados/<etiqueta>/`)

Cada carpeta contiene:

| Fichero | Contenido |
|---|---|
| `evolucion.csv` | Una fila por generación: `cal_mejor`, `cal_media`, `cal_desv`, especies, nodos y conexiones del mejor, evaluaciones, pasos, segundos |
| `evaluaciones.csv` | Una fila por episodio con sus términos de calidad |
| `genomas/mejor_genNNN.pkl` | Mejor genoma de cada generación |
| `mejor_genoma.pkl` | Mejor genoma de la ejecución |
| `config-p2.ini`, `config_p2.yaml` | Copia de la configuración usada en ese entrenamiento |

Los puntos de control `chk/` **no** están en el repo (solo sirven para reanudar un
entrenamiento).

Ejecuciones incluidas, según la copia de `config_p2.yaml` guardada en cada una:

| Carpeta | Generaciones | Formulación de la calidad | Episodio |
|---|---|---|---|
| `C3_s42` | 30 | (ver su `config_p2.yaml`) | (ver su `config_p2.yaml`) |
| `C3_s45` | 40 | A | 70 s, 2 por individuo |
| `C3_s47` | 32 | A | 70 s, 2 por individuo |
| `C3_s49` | 45 | A | 70 s, 2 por individuo |
| `C3_s50` | 50 | C | 70 s, 2 por individuo |
| `C3_s51` | 50 | C | 70 s, 2 por individuo |

---

## 8. Parámetros que se tocan con más frecuencia

En `docker-ros/ws/p2/config_p2.yaml`:

- `entorno.duracion_s`: duración máxima del episodio de evaluación (el anexo B usa 120 s).
- `evolucion.episodios_por_individuo`: episodios que se promedian por individuo.
- `arranque`: maniobra fija tras reiniciar la escena, antes de evaluar.
- `fallos`: umbrales del anexo B (colisión < 0,12 m; guía perdido > 0,90 m o pelota sin verse > 3 s).
- `calidad.formulacion`: `A` (poses reales), `B` (casi final) o `C` (con el blob: `size_blob` y `x_blob`).
- `calidad.puerta_visible`: si es `true`, en un paso sin ver la pelota no se suma recompensa.
- `calidad.escala`, `d0`, `sigma`, `theta_max`, `w_sep`, `w_ali`, `k_avance`, `bonus_completado`: coeficientes de la función de calidad.

En `docker-ros/ws/p2/config-p2.ini` (NEAT): `pop_size`, `seed`, tasas de mutación y
`compatibility_threshold` (con población pequeña decide el nº de especies; apuntar a 3–6).
La red tiene 7 entradas (`x_blob`, `size_blob`, `visible`, `ir_frontal`, `frames_perdido`,
`v_ant`, `w_ant`) y 2 salidas (`a_v`, `a_w` en [-1, 1], activación `tanh`).

Cada entrenamiento guarda una copia de ambos ficheros en su carpeta de resultados, así
que se puede saber siempre con qué configuración se obtuvo cada genoma.

---

## 9. Problemas frecuentes

| Síntoma | Qué hacer |
|---|---|
| `docker: error during connect` / "Docker no responde" | Arrancar Docker Desktop y esperar a que termine de iniciar |
| No se abren ventanas gráficas | Backend WSL2 en Docker Desktop; `wsl --update`, luego `wsl --shutdown` y reabrir Docker Desktop |
| `ModuleNotFoundError: robobosim` | `pip install robobosim` dentro del contenedor |
| `ModuleNotFoundError: neat` | Reconstruir la imagen: `.\build.ps1 -Pip` |
| El script no conecta con el simulador | Comprobar que RoboboSim está abierto en *Follow City*, que el puente está lanzado (uno solo) y que `ip_sim: host.docker.internal` en `config_p2.yaml` |
| La comunicación se cuelga en mitad de la evolución | Ctrl-C, relanzar el puente y repetir el comando con `--reanudar` |
| La calidad del mejor baja de una generación a otra | Es normal: la calidad es ruidosa (los de élite se reevalúan) |
| Resultados distintos entre evolución y evaluación | El multiplicador de velocidad de RoboboSim y la configuración del guía deben coincidir |

---

## 10. Antes de lanzar una evolución larga

- Un genoma aleatorio completa un episodio y recibe calidad (`p2_probar.py --controlador aleatorio`).
- El controlador a mano da un valor razonable (`p2_probar.py --controlador pd`).
- Dos generaciones se guardan y se reanudan (`--generaciones 2`, luego `--reanudar`).
- La duración de una generación está medida (columna `segundos`).
- La semilla está fijada (`--seed`) y el `config-p2.ini` se copia con los resultados (lo hace el programa).
- El guía (C1) y el multiplicador de velocidad de RoboboSim están anotados.
- Comprobar en vídeo que no hay atajos (girar sobre sí mismo, quedarse parado...).
