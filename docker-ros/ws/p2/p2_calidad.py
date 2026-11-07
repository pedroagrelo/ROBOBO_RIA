#!/usr/bin/env python3
"""
Práctica 2 — Función de calidad (fitness) de un individuo.

calcular(registro, causa, cal, duracion_s) -> (F, detalle)

  registro   lista con un dict por paso del episodio, con las claves:
               t            segundos desde el inicio del episodio
               sep          separación real a la pelota (m)
               desv         desviación real (grados, con signo)
               a_w          acción de giro normalizada, en [-1, 1]
               guia_parado  True si el guía está parado (lo calcula el entorno)
  causa      cómo acabó: 'tiempo' (completado), 'colision', 'perdido_distancia',
             'perdido_sin_ver' u otra ('entorno_...')
  cal        diccionario 'calidad' de config_p2.yaml
  duracion_s duración máxima del episodio (T)

La calidad se calcula UNA vez al acabar el episodio (parte incremental:
suma de lo que ocurrió en cada paso; parte final: según el desenlace).

Ejecutado como programa, prueba la función con episodios sintéticos y
comprueba que ordena como se espera (python3 p2_calidad.py).
"""

import math
import os
import sys

import numpy as np


# ---------------------------------------------------------------------
# Paradas del guía
# ---------------------------------------------------------------------

def contar_paradas(registro, causa, cal):
    """Devuelve (paradas, superadas).

    Una parada es un tramo consecutivo con guia_parado. Se da por superada
    si el guía reanuda y el seguidor sigue sin fallo t_tras_parada segundos
    después (anexo B: se detiene sin colisión y sigue sin fallo 10 s tras
    la reanudación). Si el episodio acaba antes de cumplirse ese plazo, la
    parada cuenta pero no como superada.
    """
    if not registro:
        return 0, 0
    t_fin = registro[-1]['t']
    paradas = superadas = 0
    i, n = 0, len(registro)
    while i < n:
        if registro[i].get('guia_parado'):
            j = i
            while j < n and registro[j].get('guia_parado'):
                j += 1
            paradas += 1
            if j < n:                                   # el guía reanuda en el paso j
                t_reanuda = registro[j]['t']
                plazo = t_reanuda + cal['t_tras_parada']
                # superada: el episodio llega vivo hasta el plazo (si acaba en fallo,
                # el fallo ocurre después del plazo, así que no le afecta)
                if t_fin >= plazo:
                    superadas += 1
            i = j
        else:
            i += 1
    return paradas, superadas


# ---------------------------------------------------------------------
# Términos por paso
# ---------------------------------------------------------------------

def termino_separacion(sep, cal):
    """s_t: 1 en el centro de la banda, baja suavemente al alejarse."""
    return math.exp(-((sep - cal['d0']) / cal['sigma']) ** 2)


def termino_alineacion(desv, cal):
    """a_t: 1 si el seguidor apunta a la pelota, 0 a theta_max grados o más."""
    return 1.0 - min(abs(desv) / cal['theta_max'], 1.0)


def bonus_final(causa, cal):
    if causa == 'tiempo':
        return cal['bonus_completado']
    if causa == 'colision':
        return cal['pen_colision']
    if causa.startswith('perdido'):
        return cal['pen_perdido']
    return 0.0


# ---------------------------------------------------------------------
# Calidad
# ---------------------------------------------------------------------

def calcular(registro, causa, cal, duracion_s):
    if not registro:
        return 0.0, {'F': 0.0}
    T = float(duracion_s)
    t = np.array([p['t'] for p in registro], dtype=float)
    dt = np.diff(np.concatenate(([0.0], t)))
    dt = np.clip(dt, 0.0, None)
    sep = np.array([p['sep'] for p in registro], dtype=float)
    desv = np.array([p['desv'] for p in registro], dtype=float)
    a_w = np.array([p.get('a_w', 0.0) for p in registro], dtype=float)
    vis = np.array([1.0 if p.get('visible', True) else 0.0 for p in registro], dtype=float)
    x_blob = np.array([p.get('x_blob', 0.0) for p in registro], dtype=float)
    size_blob = np.array([p.get('size_blob', 0.0) for p in registro], dtype=float)
    # avance: a_v en [-1, 1] -> 0 (parado) .. 1 (velocidad máxima); sube la recompensa por paso
    a_v = np.array([p.get('a_v', -1.0) for p in registro], dtype=float)
    avance = (np.clip(a_v, -1.0, 1.0) + 1.0) / 2.0
    av_gate = vis if cal.get('avance_con_puerta', True) else 1.0
    termino_avance = cal.get('k_avance', 0.0) * avance * av_gate
    # distancia estimada SOLO con el tamaño del blob: size ~ 26/d^2, size_blob = size/600
    d_est = np.sqrt(cal.get('k_dist_blob', 0.0433) / np.maximum(size_blob, 1e-3))

    s = np.exp(-((sep - cal['d0']) / cal['sigma']) ** 2)
    a = 1.0 - np.minimum(np.abs(desv) / cal['theta_max'], 1.0)
    en_banda = (sep >= cal['banda'][0]) & (sep <= cal['banda'][1])
    frac_banda = float(np.sum(dt * en_banda) / max(np.sum(dt), 1e-9))

    if cal['formulacion'] == 'A':
        ws, wa = cal['w_sep'], cal['w_ali']
        base = (ws * s + wa * a) / (ws + wa)
        # puerta de visibilidad: sin ver la pelota no se suma S ni A (solo queda la penalización de giro)
        puerta = vis if cal.get('puerta_visible', False) else 1.0
        r = puerta * base - cal['k_giro'] * a_w ** 2 + termino_avance
        incremental = cal['escala'] * float(np.sum(r * dt)) / T
    elif cal['formulacion'] == 'C':
        # Formulación C: A sale de lo que VE el robot (x_blob). S sale de la separación REAL si
        # sep_real=true (gaussiana original) o del tamaño del blob si false. Con puerta de visibilidad.
        ws, wa = cal['w_sep'], cal['w_ali']
        if cal.get('sep_real', False):
            # separación REAL (poses del simulador), campana gaussiana original
            s_blob = np.exp(-((sep - cal['d0']) / cal['sigma']) ** 2)
        else:
            s_blob = np.exp(-np.abs(d_est - cal['d0']) / cal['lambda_sep'])
        a_blob = 1.0 - np.minimum(np.abs(x_blob), 1.0)
        base = (ws * s_blob + wa * a_blob) / (ws + wa)
        puerta = vis if cal.get('puerta_visible', True) else 1.0
        r = puerta * base - cal['k_giro'] * a_w ** 2 + termino_avance
        incremental = cal['escala'] * float(np.sum(r * dt)) / T
    elif cal['formulacion'] == 'B':
        t_vivo = min(float(t[-1]), T)
        incremental = cal['escala'] * (t_vivo / T) * (0.5 + 0.5 * frac_banda)
    else:
        raise ValueError("formulacion debe ser 'A', 'B' o 'C'")

    vv = vis > 0
    x_abs_media = float(np.abs(x_blob[vv]).mean()) if vv.any() else 1.0
    sep_est_media = float(d_est[vv].mean()) if vv.any() else float('nan')
    final = bonus_final(causa, cal)
    paradas, superadas = contar_paradas(registro, causa, cal)
    bonus_par = cal['bonus_parada'] * superadas
    F = float(incremental + final + bonus_par)
    if not math.isfinite(F):
        F = -100.0                                   # NEAT exige un número finito

    detalle = {'F': F, 'incremental': float(incremental), 'final': float(final),
               'paradas': paradas, 'paradas_superadas': superadas,
               'bonus_paradas': float(bonus_par), 'pct_banda': 100 * frac_banda,
               'pct_visible': 100 * float(np.sum(dt * vis) / max(np.sum(dt), 1e-9)),
               'x_abs_media': x_abs_media, 'sep_est_media': sep_est_media,
               'sep_media': float(sep.mean()), 'desv_media': float(np.abs(desv).mean()),
               'duracion_s': float(t[-1]), 'pasos': len(registro), 'causa': causa}
    return F, detalle


# ---------------------------------------------------------------------
# Prueba con episodios sintéticos
# ---------------------------------------------------------------------

def _episodio(duracion, dt, sep_fn, desv_fn, a_w=0.0, parado_fn=None, visible=True, a_v=0.0):
    reg, t = [], 0.0
    while t < duracion:
        t = round(t + dt, 6)
        reg.append({'t': t, 'sep': sep_fn(t), 'desv': desv_fn(t), 'a_w': a_w,
                    'guia_parado': bool(parado_fn(t)) if parado_fn else False,
                    'visible': visible, 'a_v': a_v,
                    'x_blob': max(-1.0, min(1.0, -desv_fn(t) / 30.0)),
                    'size_blob': min(1.0, 0.0433 / max(sep_fn(t), 0.05) ** 2)})
    return reg


def _prueba(cal):
    T, dt = 30.0, 0.4
    centro = cal['d0']
    casos = [
        ('perfecto (30 s, centrado)',       _episodio(T, dt, lambda t: centro, lambda t: 0.0), 'tiempo'),
        ('bueno (30 s, algo lejos, 10°)',   _episodio(T, dt, lambda t: 0.40, lambda t: 10.0), 'tiempo'),
        ('regular (30 s, lejos 0,7 m)',     _episodio(T, dt, lambda t: 0.70, lambda t: 25.0), 'tiempo'),
        ('choca a los 20 s',                _episodio(20, dt, lambda t: centro, lambda t: 0.0), 'colision'),
        ('pierde al guía a los 8 s',        _episodio(8, dt, lambda t: 0.3 + 0.08 * t, lambda t: 5.0), 'perdido_distancia'),
        ('pierde al guía a los 2 s',        _episodio(2, dt, lambda t: 0.3 + 0.3 * t, lambda t: 5.0), 'perdido_distancia'),
        ('choca a los 2 s',                 _episodio(2, dt, lambda t: 0.3 - 0.08 * t, lambda t: 0.0), 'colision'),
        ('en banda pero sin ver (30 s)',   _episodio(T, dt, lambda t: centro, lambda t: 0.0, visible=False), 'tiempo'),
        ('gira sin parar (30 s, no ve)',    _episodio(T, dt, lambda t: 0.85, lambda t: 80.0, a_w=1.0), 'tiempo'),
    ]
    # Parada del guía entre 8 y 14 s, el seguidor sigue bien hasta el final
    parada = _episodio(T, dt, lambda t: centro, lambda t: 0.0, parado_fn=lambda t: 8 <= t <= 14)
    casos.append(('con 1 parada superada (C4)', parada, 'tiempo'))
    return T, casos


def main():
    import yaml
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_p2.yaml')
    with open(ruta, encoding='utf-8') as f:
        cal = yaml.safe_load(f)['calidad']
    for form in ('A', 'B', 'C'):
        cal = dict(cal, formulacion=form)
        T, casos = _prueba(cal)
        print('\nFormulación {}  (T = {:.0f} s, escala {:.0f}):'.format(form, T, cal['escala']))
        for nombre, reg, causa in casos:
            F, d = calcular(reg, causa, cal, T)
            print('  {:34s} F = {:7.2f}   (incremental {:6.2f}, final {:+5.1f}, paradas {}/{})'.format(
                nombre, F, d['incremental'], d['final'], d['paradas_superadas'], d['paradas']))
    print('\nComprueba que: perfecto > bueno > regular, que el que pierde al guía a los 8 s '
          'puntúa más que a los 2 s (gradiente desde la generación 0) y que la parada superada suma.')


if __name__ == '__main__':
    main()
