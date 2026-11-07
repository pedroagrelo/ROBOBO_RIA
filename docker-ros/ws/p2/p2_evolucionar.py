#!/usr/bin/env python3
"""
Práctica 2 — Evolución de controladores con NEAT-Python.

Cada individuo (genoma -> red) controla al seguidor durante k episodios; con lo
registrado se calcula su calidad (p2_calidad.py) y se asigna a genoma.fitness.

Uso (desde esta carpeta; el puente y RoboboSim ya lanzados, como en la P1):

  python3 p2_evolucionar.py --falso --generaciones 5 --etiqueta prueba    # sin simulador
  python3 p2_evolucionar.py --etiqueta C3_s42 --generaciones 30 --seed 42
  python3 p2_evolucionar.py --etiqueta C3_s42 --generaciones 30 --reanudar # tras una caída

Opciones:
  --etiqueta NOMBRE      carpeta de resultados: resultados/<etiqueta>/
  --generaciones N       generaciones TOTALES (con --reanudar sólo se hacen las que faltan)
  --seed S               semilla de NEAT (por defecto la de config-p2.ini)
  --formulacion A|B      formulación de la calidad (sobrescribe config_p2.yaml)
  --episodios K          episodios por individuo (sobrescribe config_p2.yaml)
  --duracion S           duración máxima del episodio en s (sobrescribe config_p2.yaml)
  --pop N                tamaño de la población (sobrescribe config-p2.ini)
  --falso [C1..C4]       entorno sin simulador (cinemática 2D) para probar el programa
  --reanudar             continúa desde el último punto de control de la carpeta
  --sin-pausa            no esperar a Enter antes de empezar

La configuración del guía (C1..C4) se pone a mano en RoboboSim antes de empezar
y se anota en la etiqueta. Se guarda en resultados/<etiqueta>/:
  evolucion.csv (una fila por generación), evaluaciones.csv (una fila por episodio),
  chk/ (puntos de control), genomas/ (mejor de cada generación), mejor_genoma.pkl
  y copias de config-p2.ini y config_p2.yaml.
Si la comunicación se cuelga: Ctrl-C, relanzar el puente y repetir con --reanudar
(no se asigna calidad 0 al individuo afectado).
"""

import argparse
import csv
import glob
import os
import pickle
import re
import shutil
import sys
import time

import numpy as np
import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import neat

import p2_calidad
from p2_entorno import crear_entorno, correr_episodio
from p2_registro import CONTADOR, ESTADO, RegistroGeneracion, SeguimientoGeneracion


def ultimo_checkpoint(carpeta):
    ficheros = glob.glob(os.path.join(carpeta, 'p2-*'))
    nums = [(int(re.search(r'p2-(\d+)$', f).group(1)), f) for f in ficheros
            if re.search(r'p2-(\d+)$', f)]
    return max(nums)[1] if nums else None


def main():
    p = argparse.ArgumentParser(description='Evolución NEAT del seguidor')
    p.add_argument('--etiqueta', required=True)
    p.add_argument('--generaciones', type=int, default=30)
    p.add_argument('--seed', type=int, default=None)
    p.add_argument('--formulacion', choices=['A', 'B', 'C'], default=None)
    p.add_argument('--episodios', type=int, default=None)
    p.add_argument('--duracion', type=float, default=None)
    p.add_argument('--pop', type=int, default=None)
    p.add_argument('--falso', nargs='?', const='C3', default=None, choices=['C1', 'C2', 'C3', 'C4'])
    p.add_argument('--reanudar', action='store_true')
    p.add_argument('--sin-pausa', action='store_true')
    p.add_argument('--config-neat', default=os.path.join(AQUI, 'config-p2.ini'))
    p.add_argument('--config-p2', default=os.path.join(AQUI, 'config_p2.yaml'))
    a = p.parse_args()

    # ---------------- configuración
    with open(a.config_p2, encoding='utf-8') as f:
        p2 = yaml.safe_load(f)
    if a.formulacion:
        p2['calidad']['formulacion'] = a.formulacion
    if a.episodios:
        p2['evolucion']['episodios_por_individuo'] = a.episodios
    if a.duracion:
        p2['entorno']['duracion_s'] = a.duracion
    ruta_p1 = os.path.normpath(os.path.join(os.path.dirname(a.config_p2), p2['entorno']['config_p1']))
    with open(ruta_p1, encoding='utf-8') as f:
        cfg_p1 = yaml.safe_load(f)

    cal, T = p2['calidad'], p2['entorno']['duracion_s']
    K = p2['evolucion']['episodios_por_individuo']
    agreg = np.mean if p2['evolucion']['agregacion'] == 'media' else np.min

    config = neat.Config(neat.DefaultGenome, neat.DefaultReproduction,
                         neat.DefaultSpeciesSet, neat.DefaultStagnation, a.config_neat)
    if a.pop:
        config.pop_size = a.pop
    semilla = a.seed if a.seed is not None else getattr(config, 'seed', None)

    # ---------------- carpeta de resultados (y copia de las configuraciones)
    out = os.path.join(AQUI, 'resultados', a.etiqueta)
    os.makedirs(os.path.join(out, 'chk'), exist_ok=True)
    shutil.copy(a.config_neat, os.path.join(out, 'config-p2.ini'))
    with open(os.path.join(out, 'config_p2.yaml'), 'w', encoding='utf-8') as f:
        yaml.safe_dump(p2, f, allow_unicode=True, sort_keys=False)
    ruta_eval = os.path.join(out, 'evaluaciones.csv')
    if not os.path.exists(ruta_eval):
        with open(ruta_eval, 'w', newline='') as f:
            csv.writer(f).writerow(['generacion', 'genoma', 'episodio', 'F', 'causa', 'duracion_s',
                                    'pasos', 'pct_banda', 'sep_media', 'desv_media',
                                    'incremental', 'final', 'paradas', 'paradas_superadas',
                                    'pct_visible', 'x_abs_media', 'sep_est_media'])

    # ---------------- entorno (uno solo, fuera de la función de evaluación)
    entorno = crear_entorno(cfg_p1, p2, falso=a.falso is not None,
                            modo_falso=a.falso or 'C3', seed=semilla)

    def evaluar_genoma(gid, genoma):
        red = neat.nn.FeedForwardNetwork.create(genoma, config)
        controlador = lambda obs: np.array(red.activate(obs), dtype=np.float32)
        Fs = []
        for k in range(K):
            registro, causa = correr_episodio(entorno, controlador)
            F, d = p2_calidad.calcular(registro, causa, cal, T)
            Fs.append(F)
            CONTADOR['pasos'] += len(registro)
            CONTADOR['evaluaciones'] += 1
            with open(ruta_eval, 'a', newline='') as f:
                csv.writer(f).writerow([ESTADO['gen'], gid, k, round(F, 3), causa,
                                        round(d['duracion_s'], 1), d['pasos'], round(d['pct_banda'], 1),
                                        round(d['sep_media'], 3), round(d['desv_media'], 1),
                                        round(d['incremental'], 3), round(d['final'], 1),
                                        d['paradas'], d['paradas_superadas'],
                                        round(d['pct_visible'], 1), round(d['x_abs_media'], 3),
                                        round(d['sep_est_media'], 3)])
        return float(agreg(Fs))

    def eval_genomes(genomas, config_):
        for gid, genoma in genomas:
            genoma.fitness = evaluar_genoma(gid, genoma)

    # ---------------- población
    chk = ultimo_checkpoint(os.path.join(out, 'chk')) if a.reanudar else None
    if chk:
        print('Reanudando desde', chk)
        poblacion = neat.Checkpointer.restore_checkpoint(chk)
        faltan = max(0, a.generaciones - poblacion.generation)
    else:
        poblacion = neat.Population(config, seed=semilla)
        faltan = a.generaciones
    if faltan == 0:
        print('La evolución ya tiene las {} generaciones pedidas; sube --generaciones para continuar.'.format(a.generaciones))
        entorno.close()
        return
    print('Etiqueta {} · formulación {} · pop {} · k={} · T={:.0f} s · semilla {} · {} generaciones'.format(
        a.etiqueta, cal['formulacion'], config.pop_size, K, T, semilla, faltan))

    poblacion.add_reporter(SeguimientoGeneracion())
    poblacion.add_reporter(neat.StdOutReporter(True))
    estadisticas = neat.StatisticsReporter()
    poblacion.add_reporter(estadisticas)
    poblacion.add_reporter(neat.Checkpointer(generation_interval=1,
                                             filename_prefix=os.path.join(out, 'chk', 'p2-')))
    poblacion.add_reporter(RegistroGeneracion(os.path.join(out, 'evolucion.csv'),
                                              os.path.join(out, 'genomas')))

    if not a.falso and not a.sin_pausa:
        input('\n>>> Configura el guía en RoboboSim (C1..C4) y pulsa Enter para empezar...')

    t0 = time.time()
    mejor = None
    salida = 0
    try:
        mejor = poblacion.run(eval_genomes, faltan)
    except KeyboardInterrupt:
        print('\nInterrumpido. Se puede reanudar con --reanudar desde el último punto de control.')
        salida = 130
    except RuntimeError as err:
        # Normalmente: el puente o el simulador han dejado de responder. No se asigna
        # calidad 0 al individuo afectado: se para y se reanuda desde el último punto
        # de control (p2_lanzar.sh lo hace solo).
        print('\nFALLO DE COMUNICACIÓN: {}\nRelanza el puente y reanuda con --reanudar '
              '(se perderá sólo la generación en curso).'.format(err))
        salida = 3
    finally:
        try:
            entorno.close()
        except Exception:
            pass

    if mejor is not None:
        with open(os.path.join(out, 'mejor_genoma.pkl'), 'wb') as f:
            pickle.dump(mejor, f)
        print('\nMejor genoma (calidad {:.2f}, nodos/conexiones {}) -> {}'.format(
            mejor.fitness, mejor.size(), os.path.join(out, 'mejor_genoma.pkl')))
    print('Coste de esta sesión: {} evaluaciones, {} pasos, {:.2f} h'.format(
        CONTADOR['evaluaciones'], CONTADOR['pasos'], (time.time() - t0) / 3600))
    if salida:
        sys.exit(salida)
    print('El mejor de una evolución puede deber su calidad a un episodio afortunado: '
          'reevalúa los mejores candidatos con p2_probar.py antes de elegir el final.')


if __name__ == '__main__':
    main()
