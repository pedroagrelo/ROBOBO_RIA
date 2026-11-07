# P2 RIA — Seguimiento del guía con neuroevolución (NEAT)

Esta carpeta (`p2/`) vive dentro de la de la P1 y **reutiliza** su software:
`p1_follow_env.py` (entorno), `p1_ros.py`, `p1_config.py`, `config_v2.yaml` y la
clase `Verdad` de `p1_evaluar.py` (posiciones reales del simulador). En el
contenedor: `/docker-ros/scripts/p1/p2`.

## Qué hay

| Archivo | Qué hace |
|---|---|
| `config-p2.ini` | Parámetros de NEAT-Python (población, mutaciones, especiación...). 7 entradas, 2 salidas, `tanh`. |
| `config_p2.yaml` | Duración del episodio, fallos del anexo B y **coeficientes de la función de calidad**. |
| `p2_calidad.py` | **La función de calidad** (formulaciones A y B). `python3 p2_calidad.py` la prueba con episodios sintéticos. |
| `p2_entorno.py` | `EntornoNEAT` (real: entorno de la P1 + verdad del simulador + fallos del anexo B) y `EntornoFalso` (sin simulador). |
| `p2_controladores.py` | `controlador_neat`, un PD de referencia y uno aleatorio (obs -> acción). |
| `p2_evolucionar.py` | Programa principal: población, evaluación de individuos, checkpoints, registros, reanudar. |
| `p2_registro.py` | Reporter propio: una fila por generación en CSV + mejor genoma de cada generación. |
| `p2_probar.py` | Ejecuta un controlador k episodios y da su calidad (referencia, línea base, reevaluar candidatos). |
| `p2_graficas.py` | Curvas de evolución (con varias semillas) y topología de la red. |

## Cómo funciona (resumen)

Cada generación, NEAT da una lista de genomas. Para cada uno se construye su red,
que controla al seguidor `k` episodios (30 s por defecto). Con lo registrado en
cada paso (separación y desviación **reales**, giro, si el guía está parado...)
se calcula **un número** (la calidad, ~0–100) y se asigna a `genoma.fitness`.
NEAT agrupa en especies, selecciona, cruza y muta.

El episodio se corta con los umbrales del anexo B medidos con la verdad del
simulador: colisión (< 0,12 m), guía perdido (> 0,90 m o pelota sin verse > 3 s)
o tiempo. Las terminaciones propias del entorno de la P1 (IR, 5 pasos sin ver)
se desactivan.

## Función de calidad (formulación A, mixta)

```
r_t = (w_sep·s_t + w_ali·a_t)/(w_sep + w_ali) − k_giro·a_w²
s_t = exp(−((sep − d0)/σ)²)            a_t = 1 − clip(|desv|/θ_max, 0, 1)
F   = escala · (1/T)·Σ r_t·Δt  +  B_final  +  bonus_parada · paradas_superadas
```

Valores en `config_p2.yaml`: escala 90, d0 0,325 m, σ 0,15 m, θ_max 45°, w_sep 1,
w_ali 0,5, k_giro 0,02, B_final = +10 completado / −10 colisión / −5 guía perdido,
bonus_parada 2 (sólo C4). Se integra con el tiempo real de cada paso y se divide
entre T = duración máxima: quien falla pronto pierde lo que no vive.
La formulación B (`--formulacion B`) es casi final: `escala·(t_vivo/T)·(0,5 + 0,5·frac_en_banda)`.

## Probar sin simulador (en cualquier sitio con `neat-python`, `numpy`, `pyyaml`)

```bash
cd /docker-ros/scripts/p1/p2
python3 p2_calidad.py                                           # la calidad ordena como se espera
python3 p2_probar.py --controlador pd --falso C3 --episodios 3  # calidad de referencia (PD)
python3 p2_probar.py --controlador aleatorio --falso C3         # línea base
python3 p2_evolucionar.py --falso C4 --etiqueta prueba --generaciones 10
python3 p2_graficas.py curvas resultados/prueba/evolucion.csv --salida curvas.png
python3 p2_graficas.py red resultados/prueba/mejor_genoma.pkl --config resultados/prueba/config-p2.ini
```

`--falso` usa una cinemática 2D mínima (guía en círculo, paso de 0,4 s): sirve
para comprobar el programa, no para sustituir a RoboboSim.

## Con RoboboSim

Igual que en la P1: RoboboSim en *Follow City*, el puente lanzado (un solo puente)
y `pip install robobosim` si no está.

```bash
ros2 run robobo_ros2 robobo_container --ros-args -p ip:=host.docker.internal -p modules:="['blob','sim']"
```

```bash
cd /docker-ros/scripts/p1/p2
# 1) Referencia: la calidad del controlador a mano y de uno aleatorio, con la MISMA función
python3 p2_probar.py --controlador pd --episodios 3
python3 p2_probar.py --controlador aleatorio --episodios 3
# 2) Dos o tres generaciones para medir cuánto dura una (columna "segundos" del CSV)
python3 p2_evolucionar.py --etiqueta test --generaciones 2
# 3) Evolución (configura antes el guía en RoboboSim; pide Enter para empezar)
python3 p2_evolucionar.py --etiqueta C3_s42 --generaciones 30 --seed 42
# 4) Si se cae la comunicación: Ctrl-C, relanzar el puente y
python3 p2_evolucionar.py --etiqueta C3_s42 --generaciones 30 --reanudar
# 5) Reevaluar los mejores antes de elegir el final
python3 p2_probar.py --genoma 'resultados/C3_s42/genomas/mejor_gen02*.pkl' --config-neat resultados/C3_s42/config-p2.ini --episodios 3
```

Antes de lanzar una evolución larga (indicaciones técnicas, apartado 10): un genoma
aleatorio completa un episodio y recibe calidad; el controlador a mano da un valor
razonable; dos generaciones se guardan y se reanudan; la duración de una generación
está medida (≈ P·k·(T_r + T)); la semilla está fijada y el `config-p2.ini` copiado
con los resultados (lo hace el programa); el guía y el multiplicador de velocidad
del simulador están anotados.

## Salidas (`resultados/<etiqueta>/`)

`evolucion.csv` (una fila por generación: mejor, media, desviación, especies,
nodos/conexiones del mejor, evaluaciones, pasos, segundos), `evaluaciones.csv`
(una fila por episodio con sus términos), `chk/` (un punto de control por
generación), `genomas/` (mejor de cada generación), `mejor_genoma.pkl` y copias de
las configuraciones usadas.

## Cosas a vigilar

* La calidad es ruidosa: la mejor de una generación puede bajar (los de élite se reevalúan).
* Comprobar en vídeo que no hay atajos (girar sobre sí mismo, pararse siempre...).
* Nunca se asigna calidad 0 si falla la comunicación: se para y se reanuda.
* El PD de `p2_controladores.py` es sólo una referencia: sustituidlo por el controlador del reto.
* Con una población pequeña, `compatibility_threshold` decide el nº de especies (apuntar a 3–6).
* El multiplicador de velocidad de RoboboSim debe ser el mismo en la evolución y en la evaluación.

## Pendiente (siguiente paso)

`p2_evaluar.py`: evaluador del anexo B con C4 (120 s, 2 ejecuciones, métrica de
paradas), reutilizando `p1_evaluar.ejecucion` con `controlador_neat`.
