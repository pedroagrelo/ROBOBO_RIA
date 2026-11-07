#!/usr/bin/env python3
"""
Práctica 1 — Evaluación según el protocolo del ANEXO B.

Para cada configuración del guía (C1, C2, C3) se hacen 3 ejecuciones de
120 s con la política en modo determinista. Cada ejecución empieza con un
reinicio de la simulación (el reset del entorno). En cada paso se mide con
las posiciones reales del simulador (no con los sensores del robot):

  pelota      0,08 m por detrás del centro del guía (sentido de avance)
  separación  distancia del centro del seguidor a la pelota (m)
  desviación  ángulo entre el rumbo del seguidor y la dirección a la pelota (°)

Fallos (se comprueban en cada paso):
  colisión     separación < 0,12 m
  perdido      separación > 0,90 m, o pelota sin detectar más de 3 s seguidos
Completado: 120 s sin fallos. Las terminaciones propias del entorno se
desactivan durante la evaluación (sólo cuentan los criterios del protocolo).

Métricas por configuración: completados, desenlaces, % de pasos en la
banda 0,20–0,45 m, separación media, desviación media (|°|) y % de pasos
con |desviación| < 15°. También el % en una banda propia (--banda-propia,
por defecto 0,27–0,45 m, justificada con la calibración del sensor).

Requisitos:
  - Puente lanzado (un solo puente):
      ros2 run robobo_ros2 robobo_container --ros-args -p ip:=host.docker.internal -p modules:="['blob','sim']"
  - RoboboSim abierto en Follow City y la librería robobosim instalada
    (pip install robobosim --break-system-packages). Con ella se lee la
    pose del guía, que es el objeto 'PATHFOLLOWROBOBO'.
  - La configuración del guía se cambia A MANO en RoboboSim: el script se
    para antes de cada configuración de --configs y espera a que pulses
    Enter (--sin-pausa no espera).
  - Cada modelo se evalúa con el archivo de configuración con el que se
    entrenó: los de modelos/v1/ con --config config_v1.yaml y los de
    modelos/ sin --config (config_v2.yaml, por defecto).

Uso:
  python3 p1_evaluar.py --modelo modelos/sac_s40.zip --etiqueta SAC_v2_s40 --configs C1 C2 C3
  python3 p1_evaluar.py --modelo modelos/v1/sac_s1.zip --etiqueta SAC_v1_s1 --configs C1 --config config_v1.yaml
  python3 p1_evaluar.py --aleatorio --etiqueta aleatoria --configs C2 --sin-pausa

Opciones:
  --modelo RUTA | --aleatorio   política a evaluar (el .zip puede ser SAC o PPO)
  --etiqueta NOMBRE             nombre de los archivos de salida (obligatorio)
  --configs C1 C2 C3            configuraciones del guía a evaluar
  --ejecuciones N               ejecuciones por configuración (3)
  --banda-propia MIN MAX        banda adicional en m (0.27 0.45)
  --sin-pausa                   no esperar a Enter antes de cada configuración
  --config ARCHIVO              config del entorno (config_v2.yaml)
  --objeto / --robot-id / --ip  objeto del guía, id del seguidor e IP de RoboboSim

Salida (carpeta eval_anexoB/):
  <etiqueta>_<C>_pasos.csv     una fila por paso (se sobrescribe si se repite la etiqueta)
  episodios.csv                una fila por ejecución (se va ampliando)
  y un resumen por pantalla. Las tablas para la memoria: p1_graficas.py tabla
"""

import argparse
import copy
import csv
import math
import os
import time

import numpy as np

from p1_config import cargar_config

PELOTA_DETRAS = 0.08
BANDA = (0.20, 0.45)
D_COLISION = 0.12
D_PERDIDO = 0.90
T_SIN_VER = 3.0
DESV_OK = 15.0
DURACION = 120.0
DIR_EVAL = 'eval_anexoB'

CONFIGS = {'C1': 'Crucero 10/10 (lenta constante)',
           'C2': 'Crucero 10/40 (contraste)',
           'C3': 'Variable 10/40 (fluctuante)'}


# =====================================================================
# Verdad del terreno (robobosim)
# =====================================================================

class Verdad:
    """Poses del seguidor (robot 0) y del guía (objeto PATHFOLLOWROBOBO) leídas
    con robobosim, en el mismo sistema de coordenadas (plano x-z, metros).

    Rumbo del guía: se toma de su DIRECCIÓN DE AVANCE (el guía nunca va
    marcha atrás), que no depende de convenciones de ángulos. Con esa misma
    dirección se deduce la convención de la rotación y, que se usa para el
    rumbo del seguidor (que puede girar sin avanzar)."""

    def __init__(self, ip, objeto, robot_id):
        from robobosim.RoboboSim import RoboboSim
        self.sim = RoboboSim(ip)
        self.sim.connect()
        self.sim.wait(1.0)
        self.objeto, self.rid = objeto, robot_id
        self.votos = {(1, 1): 0.0, (-1, 1): 0.0}
        self.reiniciar()

    def reiniciar(self):
        self.ancla = None          # última posición del guía usada para el rumbo
        self.dir_guia = None       # vector unitario de avance del guía

    @staticmethod
    def _pose(loc):
        if not isinstance(loc, dict):
            return None
        p, r = loc.get('position', {}), loc.get('rotation', {})
        try:
            return float(p['x']) / 1000.0, float(p['z']) / 1000.0, float(r.get('y', 0.0))
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _adelante(theta, conv):
        t = math.radians(theta)
        return np.array([conv[0] * math.sin(t), conv[1] * math.cos(t)])

    def conv(self):
        return max(self.votos, key=self.votos.get)

    def medir(self):
        """Devuelve dict con poses, pelota, separación y desviación, o None."""
        g = self._pose(self.sim.getObjectLocation(self.objeto))
        s = self._pose(self.sim.getRobotLocation(self.rid))
        if g is None or s is None:
            return None
        pg = np.array(g[:2])
        if self.ancla is None:
            self.ancla = pg
        d = pg - self.ancla
        n = float(np.linalg.norm(d))
        if n > 0.02:                                   # el guía ha avanzado 2 cm
            self.dir_guia = d / n
            self.ancla = pg
            for c in self.votos:                       # ¿qué convención encaja?
                self.votos[c] += float(np.dot(self.dir_guia, self._adelante(g[2], c)))
        fwd = self.dir_guia if self.dir_guia is not None else self._adelante(g[2], self.conv())
        bola = pg - PELOTA_DETRAS * fwd
        v = bola - np.array(s[:2])
        sep = float(np.linalg.norm(v))
        h = self._adelante(s[2], self.conv())
        desv = math.degrees(math.atan2(h[0] * v[1] - h[1] * v[0], h[0] * v[0] + h[1] * v[1]))
        return {'xs': s[0], 'zs': s[1], 'rot_s': s[2], 'xg': g[0], 'zg': g[1], 'rot_g': g[2],
                'xb': float(bola[0]), 'zb': float(bola[1]), 'sep': sep, 'desv': desv}

    def close(self):
        try:
            self.sim.disconnect()
        except Exception:
            pass


# =====================================================================
# Política
# =====================================================================

def cargar_politica(ruta):
    from stable_baselines3 import PPO, SAC
    for clase in (SAC, PPO):
        try:
            m = clase.load(ruta)
            print('Modelo {} cargado como {}'.format(ruta, clase.__name__))
            return lambda o: m.predict(o, deterministic=True)[0]
        except Exception:
            continue
    raise SystemExit('No se pudo cargar {} ni como SAC ni como PPO'.format(ruta))


# =====================================================================
# Una ejecución
# =====================================================================

COLS = ['t', 'xs', 'zs', 'rot_s', 'xg', 'zg', 'rot_g', 'xb', 'zb', 'sep', 'desv',
        'visible', 'size', 'x_blob', 'ir', 'v', 'w', 'en_banda', 'en_banda_propia', 'sin_ver_s']


def ejecucion(env, verdad, politica, banda_propia, wr, n_ej):
    obs, _ = env.reset()
    verdad.reiniciar()
    t0 = time.time()
    ult_visto = 0.0
    filas = []
    causa = None
    while causa is None:
        a = env.action_space.sample() if politica is None else politica(obs)
        obs, r, term, trunc, info = env.step(a)
        t = time.time() - t0
        m = verdad.medir()
        if m is None:
            continue
        vis = bool(info.get('visible'))
        if vis:
            ult_visto = t
        sin_ver = t - ult_visto
        f = dict(m, t=round(t, 3), visible=int(vis), size=info.get('size', 0.0),
                 x_blob=info.get('x', float('nan')), ir=info.get('ir', 0.0),
                 v=info.get('v', 0.0), w=info.get('w', 0.0),
                 en_banda=int(BANDA[0] <= m['sep'] <= BANDA[1]),
                 en_banda_propia=int(banda_propia[0] <= m['sep'] <= banda_propia[1]),
                 sin_ver_s=round(sin_ver, 2))
        filas.append(f)
        wr.writerow([n_ej] + [round(f[c], 4) if isinstance(f[c], float) else f[c] for c in COLS])
        if m['sep'] < D_COLISION:
            causa = 'colision'
        elif m['sep'] > D_PERDIDO:
            causa = 'perdido_distancia'
        elif sin_ver > T_SIN_VER:
            causa = 'perdido_sin_ver'
        elif t >= DURACION:
            causa = 'completado'
        elif term or trunc:
            causa = 'entorno_' + (info.get('causa') or 'otro')
    env.ros.detener()
    sep = np.array([f['sep'] for f in filas])
    desv = np.abs(np.array([f['desv'] for f in filas]))
    return {'causa': causa, 'completado': int(causa == 'completado'),
            'duracion_s': round(filas[-1]['t'], 1), 'pasos': len(filas),
            'pct_banda': round(100 * np.mean([f['en_banda'] for f in filas]), 1),
            'pct_banda_propia': round(100 * np.mean([f['en_banda_propia'] for f in filas]), 1),
            'sep_media': round(float(sep.mean()), 3),
            'desv_media': round(float(desv.mean()), 1),
            'pct_desv15': round(100 * float(np.mean(desv < DESV_OK)), 1)}


# =====================================================================

def main():
    p = argparse.ArgumentParser(description='Evaluador del anexo B')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--modelo', help='ruta al .zip (SAC o PPO, se detecta solo)')
    g.add_argument('--aleatorio', action='store_true', help='línea base: acciones aleatorias')
    p.add_argument('--etiqueta', required=True, help='nombre para los archivos, p. ej. SAC_v2_s40')
    p.add_argument('--configs', nargs='+', default=['C1', 'C2', 'C3'], choices=list(CONFIGS))
    p.add_argument('--ejecuciones', type=int, default=3)
    p.add_argument('--banda-propia', type=float, nargs=2, default=[0.27, 0.45])
    p.add_argument('--sin-pausa', action='store_true', help='no esperar a Enter entre configuraciones')
    p.add_argument('--config', default=None, help='config a usar (por defecto config_v2.yaml)')
    p.add_argument('--objeto', default='PATHFOLLOWROBOBO')
    p.add_argument('--robot-id', type=int, default=0)
    p.add_argument('--ip', default='host.docker.internal')
    a = p.parse_args()

    cfg = copy.deepcopy(cargar_config(a.config))
    # Durante la evaluación sólo cuentan los criterios del protocolo:
    cfg['episodio']['duracion_s'] = DURACION + 30.0
    cfg['terminacion']['max_frames_perdido'] = 10 ** 9
    cfg['terminacion']['ir_colision'] = float('inf')

    from p1_follow_env import RoboboFollowEnv
    politica = None if a.aleatorio else cargar_politica(a.modelo)
    env = RoboboFollowEnv(cfg)
    verdad = Verdad(a.ip, a.objeto, a.robot_id)
    os.makedirs(DIR_EVAL, exist_ok=True)
    ruta_ep = os.path.join(DIR_EVAL, 'episodios.csv')
    nuevo = not os.path.exists(ruta_ep)
    resultados = []
    try:
        for c in a.configs:
            if not a.sin_pausa:
                input('\n>>> Configura el guía en {} ({}) en RoboboSim y pulsa Enter...'.format(c, CONFIGS[c]))
            ruta_p = os.path.join(DIR_EVAL, '{}_{}_pasos.csv'.format(a.etiqueta, c))
            with open(ruta_p, 'w', newline='') as fp:
                wr = csv.writer(fp)
                wr.writerow(['ejecucion'] + COLS)
                for k in range(1, a.ejecuciones + 1):
                    res = ejecucion(env, verdad, politica, a.banda_propia, wr, k)
                    res.update(etiqueta=a.etiqueta, config=c, ejecucion=k,
                               fecha=time.strftime('%Y-%m-%d %H:%M'))
                    resultados.append(res)
                    print('{} {} ej.{}: {:18s} {:5.1f} s  banda {:5.1f} %  propia {:5.1f} %  sep {:.3f} m  '
                          '|desv| {:4.1f}°  <15° {:5.1f} %'.format(
                              a.etiqueta, c, k, res['causa'], res['duracion_s'], res['pct_banda'],
                              res['pct_banda_propia'], res['sep_media'], res['desv_media'], res['pct_desv15']))
                    with open(ruta_ep, 'a', newline='') as fe:
                        cols = ['fecha', 'etiqueta', 'config', 'ejecucion', 'causa', 'completado',
                                'duracion_s', 'pasos', 'pct_banda', 'pct_banda_propia', 'sep_media',
                                'desv_media', 'pct_desv15']
                        we = csv.DictWriter(fe, fieldnames=cols)
                        if nuevo:
                            we.writeheader()
                            nuevo = False
                        we.writerow({k2: res[k2] for k2 in cols})
            print('Registro por paso: ' + ruta_p)
    except KeyboardInterrupt:
        print('\nInterrumpido.')
    finally:
        env.close()
        verdad.close()

    if resultados:
        print('\nConvención de ángulos detectada: {}'.format(verdad.conv()))
        print('\nResumen ({}):'.format(a.etiqueta))
        for c in a.configs:
            rs = [r for r in resultados if r['config'] == c]
            if not rs:
                continue
            comp = sum(r['completado'] for r in rs)
            print('  {}  completados {}/{} ({:.0f} %)  banda {:.1f} %  sep {:.3f} m  |desv| {:.1f}°  <15° {:.1f} %  desenlaces: {}'
                  .format(c, comp, len(rs), 100 * comp / len(rs),
                          np.mean([r['pct_banda'] for r in rs]), np.mean([r['sep_media'] for r in rs]),
                          np.mean([r['desv_media'] for r in rs]), np.mean([r['pct_desv15'] for r in rs]),
                          ', '.join('{}={}'.format(x, sum(r['causa'] == x for r in rs))
                                    for x in sorted({r['causa'] for r in rs}))))
        print('\nTablas para la memoria:  python3 p1_graficas.py tabla')


if __name__ == '__main__':
    main()
