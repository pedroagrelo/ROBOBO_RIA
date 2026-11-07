#!/usr/bin/env python3
"""
Práctica 1 — Entorno Gymnasium: seguir al Robobo guía en Follow City.

No se ejecuta directamente: lo crean p1_entrenar.py (entrenamiento) y
p1_evaluar.py (evaluación). Los parámetros se leen de la config
(config_v2.yaml por defecto, o config_v1.yaml).

La observación, la recompensa y la terminación salen SÓLO de lo que mide
el propio seguidor (blob verde de la cámara e infrarrojos). Del módulo
sim sólo se usa reset_simulation para reiniciar la escena entre
episodios; no se lee ninguna posición.

Observación (Box float32, dim 7, normalizada):
  [0] x_blob         posición horizontal de la pelota escalada a [-1, 1]
                     (si deja de verse, se mantiene el último valor)
  [1] size_blob      tamaño del blob / size_max, limitado a [0, 1] (0 si no se ve)
  [2] visible        1 si se ve la pelota en esta lectura, 0 si no
  [3] ir_frontal     máximo IR frontal / saturacion, limitado a [0, 1]
  [4] frames_perdido lecturas seguidas sin verla / frames_perdido_norm, limitado a [0, 1]
  [5] v_ant, [6] w_ant   acción anterior, [-1, 1]

Acción (Box float32, dim 2) en [-1, 1] -> cmd_vel:
  v = v_min + (a0 + 1)/2 · (v_max − v_min)   m/s
  w = a1 · w_max                            rad/s

Recompensa por paso (bloque "recompensa" de la config; v1 = config_v1.yaml,
v2 = config_v2.yaml). size_banda = [60, 200] ≈ 0,37–0,60 m según la
calibración; centro 130 ≈ 0,45 m, semiancho 70.
  distancia   k_size · (1 − clip(|size − centro| / semiancho, 0, clip_distancia))
              si se ve. clip_distancia = 2 (v1): fuera de la banda puede
              restar hasta −k_size; = 1 (v2): nunca resta
  banda       +bonus_banda si se ve y size está dentro de size_banda (sólo v2)
  centrado    −k_centro · x_blob²            (si se ve)
  no visible  −k_no_visible                  (cada paso sin verla)
  giro        −k_giro · a1²
  terminales  pen_colision / pen_perdido / bonus_completado

Terminación (bloque "terminacion"):
  colisión    IR frontal ≥ ir_colision
  perdido     frames_perdido ≥ max_frames_perdido
  completado  duracion_s sin fallos (truncamiento)

Sincronización (apartado 5.2): en step() se aplica la acción durante
periodo_s reenviando cmd_vel cada keepalive_s (el watchdog del puente
para el robot si no recibe órdenes en 0,5 s), se vacía la cola y se
ESPERA a un BlobArray nuevo, posterior a la acción.
"""

import time

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from p1_config import cargar_config


class RoboboFollowEnv(gym.Env):

    metadata = {'render_modes': []}

    def __init__(self, cfg=None, verbose=False, ros=None):
        super().__init__()
        self.cfg = cfg if cfg is not None else cargar_config()
        self.verbose = verbose

        c = self.cfg
        self.periodo = c['control']['periodo_s']
        self.v_min, self.v_max = c['control']['v_min'], c['control']['v_max']
        self.w_max = c['control']['w_max']
        self.xc = 0.5 * (c['blob']['x_min'] + c['blob']['x_max'])
        self.xr = 0.5 * (c['blob']['x_max'] - c['blob']['x_min'])

        if ros is None:
            from p1_ros import RoboboROS
            ros = RoboboROS(c, nombre_nodo='p1_entorno_rl')
        self.ros = ros

        self.observation_space = spaces.Box(
            low=np.array([-1, 0, 0, 0, 0, -1, -1], dtype=np.float32),
            high=np.array([1, 1, 1, 1, 1, 1, 1], dtype=np.float32),
            dtype=np.float32)
        self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(2,), dtype=np.float32)

        self.ultima_accion = np.zeros(2, dtype=np.float32)
        self.ult_x = 0.0
        self.frames_perdido = 0
        self.pasos = 0
        self.t_inicio = time.time()

        # Arranque: comprobar que llegan blobs y dejar el color configurado.
        self.ros.esperar_blob_nuevo(timeout=c['episodio']['espera_max_lectura_s'])
        self.ros.activar_color()

    # -----------------------------------------------------------------
    # Lecturas del seguidor
    # -----------------------------------------------------------------

    def _visible(self):
        b = self.ros.blob
        return b is not None and b['size'] >= self.cfg['blob']['size_min']

    def _size_crudo(self):
        return float(self.ros.blob['size']) if self._visible() else 0.0

    def _ir_crudo(self):
        return float(self.ros.ir_frontal_crudo()) if self.cfg['ir']['usar'] else 0.0

    def _observacion(self):
        c = self.cfg
        if self._visible():
            b = self.ros.blob
            self.ult_x = float(np.clip((b['x'] - self.xc) / self.xr, -1, 1))
            size = float(np.clip(b['size'] / c['blob']['size_max'], 0, 1))
            vis = 1.0
            self.frames_perdido = 0
        else:
            size, vis = 0.0, 0.0
            self.frames_perdido += 1
        ir = float(np.clip(self._ir_crudo() / c['ir']['saturacion'], 0, 1))
        fp = min(self.frames_perdido / c['control']['frames_perdido_norm'], 1.0)
        return np.array([self.ult_x, size, vis, ir, fp,
                         self.ultima_accion[0], self.ultima_accion[1]], dtype=np.float32)

    # -----------------------------------------------------------------
    # Recompensa (cada término por separado, coeficientes en config)
    # -----------------------------------------------------------------

    def _recompensa(self, visible, size, x, a1, causa):
        k = self.cfg['recompensa']
        lo, hi = k['size_banda']
        centro, semi = 0.5 * (lo + hi), 0.5 * (hi - lo)
        t = {}
        # clip_distancia: 2 (v1) -> el término llega a -k_size lejos de la banda;
        #                 1 (v2) -> el término queda en [0, k_size], nunca resta.
        tope = k.get('clip_distancia', 2.0)
        if visible:
            t['distancia'] = k['k_size'] * (1.0 - float(np.clip(abs(size - centro) / semi, 0, tope)))
            t['centrado'] = -k['k_centro'] * x ** 2
            t['no_visible'] = 0.0
            # bonus_banda (v2): premio fijo por paso con la pelota dentro de size_banda (v1: 0)
            t['banda'] = k.get('bonus_banda', 0.0) if lo <= size <= hi else 0.0
        else:
            t['banda'] = 0.0
            t['distancia'] = 0.0
            t['centrado'] = 0.0
            t['no_visible'] = -k['k_no_visible']
        t['giro'] = -k['k_giro'] * a1 ** 2
        t['terminal'] = {'colision': k['pen_colision'], 'perdido': k['pen_perdido'],
                         'tiempo': k['bonus_completado']}.get(causa, 0.0)
        return float(sum(t.values())), t

    # -----------------------------------------------------------------
    # Gymnasium
    # -----------------------------------------------------------------

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        c = self.cfg
        self.ros.detener()

        for intento in range(c['episodio']['reintentos_reset']):
            self.ros.reiniciar_escena()
            time.sleep(0.5)
            if c['camara']['tilt_angulo'] is not None:
                self.ros.mover_tilt(c['camara']['tilt_angulo'], c['camara']['tilt_velocidad'])
            if self._esperar_pelota():
                break
            print('[reset] No se ve la pelota tras {:.0f} s; reintento {}'
                  .format(c['camara']['espera_visible_s'], intento + 1))
        else:
            print('[reset] AVISO: el episodio empieza sin ver la pelota.')

        self.pasos = 0
        self.frames_perdido = 0
        self.ult_x = 0.0
        self.ultima_accion = np.zeros(2, dtype=np.float32)

        self.ros.vaciar_cola()
        self.ros.esperar_blob_nuevo(timeout=c['episodio']['espera_max_lectura_s'])
        self.t_inicio = time.time()
        return self._observacion(), {}

    def _esperar_pelota(self):
        """Espera a ver la pelota N lecturas seguidas (el TILT puede estar
        subiendo tras el reinicio). Devuelve False si no la ve a tiempo."""
        c = self.cfg['camara']
        t0 = time.time()
        seguidos = 0
        while time.time() - t0 < c['espera_visible_s']:
            self.ros.esperar_blob_nuevo()
            seguidos = seguidos + 1 if self._visible() else 0
            if seguidos >= c['frames_visible_ok']:
                return True
        return False

    def step(self, accion):
        c = self.cfg
        term = c['terminacion']
        a = np.clip(np.asarray(accion, dtype=np.float32), -1.0, 1.0)
        self.ultima_accion = a
        v = self.v_min + (float(a[0]) + 1.0) * 0.5 * (self.v_max - self.v_min)
        w = float(a[1]) * self.w_max

        # 1-2. Aplicar la acción durante el periodo de control.
        self.ros.aplicar_durante(v, w, self.periodo)
        # 3. Descartar lo antiguo y esperar una lectura POSTERIOR a la acción.
        self.ros.vaciar_cola()
        self.ros.esperar_blob_nuevo(timeout=c['episodio']['espera_max_lectura_s'],
                                    keepalive=(v, w))
        self.ros.vaciar_cola()
        self.pasos += 1
        obs = self._observacion()
        t_ep = time.time() - self.t_inicio

        # 4. Todo lo que sigue sale de los sensores del propio seguidor.
        visible = self._visible()
        size = self._size_crudo()
        ir = self._ir_crudo()

        causa = ''
        if ir >= term['ir_colision']:
            causa = 'colision'
        elif self.frames_perdido >= term['max_frames_perdido']:
            causa = 'perdido'
        elif t_ep >= c['episodio']['duracion_s']:
            causa = 'tiempo'

        terminated = causa in ('colision', 'perdido')
        truncated = causa == 'tiempo'
        r, terminos = self._recompensa(visible, size, float(obs[0]), float(a[1]), causa)

        lo, hi = c['recompensa']['size_banda']
        info = {'pasos': self.pasos, 't': t_ep, 'v': v, 'w': w, 'causa': causa,
                'visible': visible, 'size': size, 'x': float(obs[0]), 'ir': ir,
                'en_banda': visible and lo <= size <= hi,
                'terminos': terminos}

        if terminated or truncated:
            self.ros.detener()

        if self.verbose:
            print('paso {:4d} t={:5.1f} v={:+.2f} w={:+.2f} vis={:d} size={:6.1f} x={:+.2f} '
                  'ir={:5.0f} r={:+.3f} {}'.format(self.pasos, t_ep, v, w, int(visible), size,
                                                   obs[0], ir, r, causa.upper()))
        return obs, r, terminated, truncated, info

    def close(self):
        self.ros.close()
