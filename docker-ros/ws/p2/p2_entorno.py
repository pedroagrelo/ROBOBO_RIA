#!/usr/bin/env python3
"""
Práctica 2 — Entornos para evaluar individuos de NEAT.

Los dos tienen la misma interfaz:

    obs = entorno.reset()
    obs, info = entorno.step(accion)      # accion: array de 2 en [-1, 1]
    entorno.detener()  /  entorno.close()

y devuelven en 'info' todo lo que necesita la calidad (verdad del terreno):
t, sep, desv, a_w, v, w, visible, sin_ver_s, guia_parado, en_banda y
'causa' ('' mientras el episodio sigue; al acabar: 'tiempo', 'colision',
'perdido_distancia' o 'perdido_sin_ver').

  EntornoNEAT    el real: RoboboFollowEnv de la P1 + posiciones reales del
                 simulador (clase Verdad de p1_evaluar.py). La terminación
                 NO la decide el entorno de la P1 (se desactiva) sino los
                 umbrales del anexo B de la P2, medidos con la verdad.
  EntornoFalso   cinemática 2D mínima, SIN simulador ni ROS. Sirve para
                 probar el programa de evolución, la calidad y NEAT en
                 cualquier ordenador (aproxima, no sustituye, a RoboboSim).
"""

import copy
import math
import os
import random
import sys
import time

import numpy as np

# Esta carpeta (p2/) está dentro de la de la P1: se importan sus módulos.
CARPETA_P1 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CARPETA_P1 not in sys.path:
    sys.path.insert(0, CARPETA_P1)

OBS_DIM = 7        # x_blob, size_blob, visible, ir_frontal, frames_perdido, v_ant, w_ant
ACC_DIM = 2        # a_v, a_w


# =====================================================================
# Lógica común: causa de fin y detección de parada del guía
# =====================================================================

class Arbitro:
    """Aplica los fallos del anexo B y detecta las paradas del guía."""

    def __init__(self, fallos, cal, duracion_s):
        self.f, self.cal, self.T = fallos, cal, duracion_s
        self.reiniciar()

    def reiniciar(self):
        self.ult_visto = 0.0
        self.t_prev = 0.0
        self.pg_prev = None
        self.t_quieto = 0.0
        self.parado = False

    def evaluar(self, t, sep, visible, pos_guia):
        """Devuelve (causa, sin_ver_s, guia_parado)."""
        if visible:
            self.ult_visto = t
        sin_ver = t - self.ult_visto

        dt = t - self.t_prev
        if self.pg_prev is not None and dt > 1e-3:
            v_g = math.hypot(pos_guia[0] - self.pg_prev[0], pos_guia[1] - self.pg_prev[1]) / dt
            if v_g < self.cal['v_parada']:
                self.t_quieto += dt
            else:
                self.t_quieto = 0.0
            self.parado = self.t_quieto > self.cal['t_parada']
        self.pg_prev, self.t_prev = pos_guia, t

        if sep < self.f['d_colision']:
            causa = 'colision'
        elif sep > self.f['d_perdido']:
            causa = 'perdido_distancia'
        elif sin_ver > self.f['t_sin_ver']:
            causa = 'perdido_sin_ver'
        elif t >= self.T:
            causa = 'tiempo'
        else:
            causa = ''
        return causa, sin_ver, self.parado


# =====================================================================
# Entorno real (RoboboSim)
# =====================================================================

class EntornoNEAT:
    def __init__(self, cfg_p1, p2cfg):
        from p1_follow_env import RoboboFollowEnv
        from p1_evaluar import Verdad

        self.p2 = p2cfg
        self.T = p2cfg['entorno']['duracion_s']
        cfg = copy.deepcopy(cfg_p1)
        # Las terminaciones propias del entorno de la P1 se desactivan: aquí
        # sólo cuentan los criterios del anexo B (poses reales).
        cfg['episodio']['duracion_s'] = self.T + 1000.0
        cfg['terminacion']['max_frames_perdido'] = 10 ** 9
        cfg['terminacion']['ir_colision'] = float('inf')

        self.env = RoboboFollowEnv(cfg)
        self.verdad = Verdad(p2cfg['entorno']['ip_sim'], p2cfg['entorno']['objeto_guia'],
                             p2cfg['entorno']['robot_id'])
        self.arbitro = Arbitro(p2cfg['fallos'], p2cfg['calidad'], self.T)
        self.banda = p2cfg['calidad']['banda']
        self.t0 = time.time()

    def reset(self):
        obs, _ = self.env.reset()
        self.verdad.reiniciar()
        obs = self._arranque(obs)
        self.arbitro.reiniciar()
        self.t0 = time.time()
        return obs

    def _arranque(self, obs):
        """Maniobra fija de arranque tras el reinicio de la escena y ANTES de
        empezar a evaluar: el seguidor avanza recto a velocidad constante unos
        segundos (el anexo B admite acciones de arranque predeterminadas).
        Se corta antes si la separación real baja de 'parar_si_sep_menor_m'.
        El reloj del episodio y el árbitro empiezan después. Parámetros en el
        bloque 'arranque' de config_p2.yaml (sin bloque o activo=false: no hace nada)."""
        ar = self.p2.get('arranque') or {}
        if not ar.get('activo', False):
            return obs
        ros = self.env.ros
        v = float(ar['velocidad_cm_s']) / 100.0          # m/s
        t_total = float(ar['duracion_s'])
        sep_min = float(ar.get('parar_si_sep_menor_m', 0.20))
        t_ini = time.time()
        try:
            while time.time() - t_ini < t_total:
                ros.aplicar_durante(v, 0.0, min(0.5, t_total - (time.time() - t_ini)))
                m = self.verdad.medir()
                if m is not None and m['sep'] < sep_min:
                    break
        finally:
            ros.detener()
        # Pausa con el seguidor PARADO entre el avance y el inicio de la evaluación
        espera = float(ar.get('espera_parado_s', 0.0))
        if espera > 0:
            ros.detener()
            ros.spin(espera)
        # Estado limpio para el primer paso del episodio
        self.verdad.reiniciar()
        self.env.frames_perdido = 0
        self.env.ultima_accion = np.zeros(2, dtype=np.float32)
        ros.vaciar_cola()
        ros.esperar_blob_nuevo(timeout=self.env.cfg['episodio']['espera_max_lectura_s'])
        return self.env._observacion()

    def _medir(self):
        for _ in range(30):
            m = self.verdad.medir()
            if m is not None:
                return m
            time.sleep(0.05)
        raise RuntimeError('No llegan las poses de RoboboSim (¿está abierto y con robobosim conectado?)')

    def step(self, accion):
        a = np.clip(np.asarray(accion, dtype=np.float32), -1.0, 1.0)
        obs, _, _, _, info1 = self.env.step(a)
        t = time.time() - self.t0
        m = self._medir()
        causa, sin_ver, parado = self.arbitro.evaluar(
            t, m['sep'], bool(info1.get('visible')), (m['xg'], m['zg']))
        info = {'t': t, 'sep': m['sep'], 'desv': m['desv'], 'a_w': float(a[1]), 'a_v': float(a[0]),
                'v': info1.get('v', 0.0), 'w': info1.get('w', 0.0),
                'visible': bool(info1.get('visible')), 'sin_ver_s': sin_ver,
                'guia_parado': parado, 'causa': causa,
                'x_blob': float(obs[0]), 'size_blob': float(obs[1]),
                'en_banda': self.banda[0] <= m['sep'] <= self.banda[1]}
        return obs, info

    def detener(self):
        self.env.ros.detener()

    def close(self):
        try:
            self.env.close()
        finally:
            self.verdad.close()


# =====================================================================
# Entorno falso (sin simulador)
# =====================================================================

class EntornoFalso:
    """Guía en un círculo (giro a la izquierda) y seguidor tipo monociclo.

    Modos del guía (aproximados, en m/s):
      C1 constante 0,10   C2 constante 0,30   C3 oscila entre 0,10 y 0,30
      C4 como C3 con paradas aleatorias de 3 a 6 s
    El paso dura 0,4 s, como el medido en el simulador real.
    """
    DT = 0.4
    R = 2.0

    def __init__(self, cfg_p1, p2cfg, modo='C3', seed=None):
        self.p2 = p2cfg
        self.T = p2cfg['entorno']['duracion_s']
        self.modo = modo
        self.v_max = cfg_p1['control']['v_max']
        self.w_max = cfg_p1['control']['w_max']
        self.rng = random.Random(seed)
        self.arbitro = Arbitro(p2cfg['fallos'], p2cfg['calidad'], self.T)
        self.banda = p2cfg['calidad']['banda']

    # -- guía --
    def _v_guia(self, t):
        if self.parada_hasta > t:
            return 0.0
        if self.modo == 'C1':
            return 0.10
        if self.modo == 'C2':
            return 0.30
        v = 0.20 + 0.10 * math.sin(2 * math.pi * t / 20.0)
        if self.modo == 'C4' and self.rng.random() < 0.04:
            self.parada_hasta = t + self.rng.uniform(3.0, 6.0)
            return 0.0
        return v

    def reset(self):
        self.t = 0.0
        self.parada_hasta = -1.0
        self.phi = self.rng.uniform(0, 2 * math.pi)
        self.v_guia = 0.0
        self.th_g = self.phi + math.pi / 2
        gx, gy = self.R * math.cos(self.phi), self.R * math.sin(self.phi)
        # seguidor 0,45 m por detrás, apuntando en la misma dirección
        ph_s = self.phi - 0.45 / self.R
        self.sx, self.sy = self.R * math.cos(ph_s), self.R * math.sin(ph_s)
        self.th = self.th_g
        self.ult = np.zeros(2, dtype=np.float32)
        self.fp = 0
        self.arbitro.reiniciar()
        return self._obs(*self._medidas())[0]

    def _medidas(self):
        gx, gy = self.R * math.cos(self.phi), self.R * math.sin(self.phi)
        bx, by = gx - 0.08 * math.cos(self.th_g), gy - 0.08 * math.sin(self.th_g)
        vx, vy = bx - self.sx, by - self.sy
        sep = math.hypot(vx, vy)
        hx, hy = math.cos(self.th), math.sin(self.th)
        desv = math.degrees(math.atan2(hx * vy - hy * vx, hx * vx + hy * vy))
        return sep, desv, (gx, gy)

    def _obs(self, sep, desv, _g):
        visible = abs(desv) < 35.0 and sep < 1.0
        if visible:
            x = float(np.clip(-desv / 30.0 + self.rng.gauss(0, 0.02), -1, 1))   # + = derecha
            size = float(np.clip(26.0 / max(sep, 0.05) ** 2 / 600.0, 0, 1))
            self.fp = 0
            self._ult_x = x
        else:
            x, size = getattr(self, '_ult_x', 0.0), 0.0
            self.fp += 1
        ir = float(np.clip((0.25 - sep) / 0.15, 0, 1))
        obs = np.array([x, size, 1.0 if visible else 0.0, ir, min(self.fp / 10.0, 1.0),
                        self.ult[0], self.ult[1]], dtype=np.float32)
        return obs, visible

    def step(self, accion):
        a = np.clip(np.asarray(accion, dtype=np.float32), -1.0, 1.0)
        self.ult = a
        v = (float(a[0]) + 1.0) * 0.5 * self.v_max
        w = float(a[1]) * self.w_max
        dt = self.DT
        # seguidor
        self.th += w * dt
        self.sx += v * math.cos(self.th) * dt
        self.sy += v * math.sin(self.th) * dt
        # guía
        self.v_guia = self._v_guia(self.t)
        self.phi += self.v_guia / self.R * dt
        self.th_g = self.phi + math.pi / 2
        self.t += dt

        sep, desv, pg = self._medidas()
        obs, visible = self._obs(sep, desv, pg)
        causa, sin_ver, parado = self.arbitro.evaluar(self.t, sep, visible, pg)
        info = {'t': self.t, 'sep': sep, 'desv': desv, 'a_w': float(a[1]), 'a_v': float(a[0]), 'v': v, 'w': w,
                'visible': visible, 'sin_ver_s': sin_ver, 'guia_parado': parado,
                'causa': causa, 'x_blob': float(obs[0]), 'size_blob': float(obs[1]),
                'en_banda': self.banda[0] <= sep <= self.banda[1]}
        return obs, info

    def detener(self):
        pass

    def close(self):
        pass


# =====================================================================
# Creación y bucle de un episodio
# =====================================================================

def crear_entorno(cfg_p1, p2cfg, falso=False, modo_falso='C3', seed=None):
    if falso:
        return EntornoFalso(cfg_p1, p2cfg, modo=modo_falso, seed=seed)
    return EntornoNEAT(cfg_p1, p2cfg)


def correr_episodio(entorno, controlador):
    """Ejecuta un episodio completo con 'controlador' (obs -> acción).

    Devuelve (registro, causa): un dict por paso y cómo terminó.
    """
    obs = entorno.reset()
    registro = []
    while True:
        accion = controlador(obs)
        obs, info = entorno.step(accion)
        registro.append(info)
        if info['causa']:
            break
    entorno.detener()
    return registro, info['causa']
