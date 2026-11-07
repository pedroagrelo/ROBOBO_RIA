#!/usr/bin/env python3
"""
Práctica 2 — Controladores observación -> acción.

Todos son funciones obs (7 valores) -> acción (2 valores en [-1, 1]), así que
sirven igual para el evaluador, para la calidad y para comparar con SB3:

  controlador_neat(genoma.pkl, config-p2.ini)   red evolucionada con NEAT
  controlador_pd()      referencia sencilla programada a mano (NO es el del reto:
                        sustitúyelo por el vuestro para tener su calidad de referencia)
  controlador_aleatorio(seed)   línea base

Observación (orden de p1_follow_env.py):
  [0] x_blob   [1] size_blob   [2] visible   [3] ir_frontal   [4] frames_perdido
  [5] v_ant    [6] w_ant
Acción: a_v -> v = v_min + (a_v+1)/2·(v_max-v_min);  a_w -> w = a_w·w_max
"""

import pickle

import numpy as np


def controlador_neat(ruta_genoma, ruta_config):
    import neat
    config = neat.Config(neat.DefaultGenome, neat.DefaultReproduction,
                         neat.DefaultSpeciesSet, neat.DefaultStagnation, ruta_config)
    with open(ruta_genoma, 'rb') as f:
        genoma = pickle.load(f)
    red = neat.nn.FeedForwardNetwork.create(genoma, config)
    return lambda obs: np.array(red.activate(obs), dtype=np.float32)


def controlador_pd(size_objetivo=130.0, size_max=600.0, kp_v=6.0, kp_w=1.5):
    """Proporcional: gira hacia la pelota y regula la velocidad con su tamaño.

    size_objetivo = 130 (centro de size_banda de config_v2.yaml, ~0,45 m).
    Si no ve la pelota, para y gira hacia donde la vio por última vez.
    """
    objetivo = size_objetivo / size_max
    ultimo = {'x': 0.0}

    def ctrl(obs):
        x, size, visible = float(obs[0]), float(obs[1]), float(obs[2])
        if visible < 0.5:
            giro = 1.0 if ultimo['x'] < 0 else -1.0      # x<0: pelota a la izquierda -> w>0
            return np.array([-1.0, giro * 0.6], dtype=np.float32)
        ultimo['x'] = x
        v_norm = 0.35 + kp_v * (objetivo - size)           # 0..1
        a_v = float(np.clip(2.0 * v_norm - 1.0, -1.0, 1.0))
        a_w = float(np.clip(-kp_w * x, -1.0, 1.0))         # x>0 (derecha) -> girar a la derecha (w<0)
        return np.array([a_v, a_w], dtype=np.float32)
    return ctrl


def controlador_aleatorio(seed=None):
    rng = np.random.default_rng(seed)
    return lambda obs: rng.uniform(-1.0, 1.0, size=2).astype(np.float32)
