#!/usr/bin/env python3
"""
Práctica 2 — Probar un controlador y ver su calidad.

Ejecuta k episodios con un controlador y muestra, para cada uno, la calidad y
sus partes. Sirve para:
  - conseguir la calidad de REFERENCIA del controlador programado a mano
    (aquí hay un PD sencillo; sustitúyelo por el del reto en p2_controladores.py),
  - comparar con una red aleatoria (línea base),
  - REEVALUAR los mejores candidatos de una evolución antes de elegir el final.

Uso:
  python3 p2_probar.py --controlador pd --falso C3 --episodios 5
  python3 p2_probar.py --controlador aleatorio --episodios 5
  python3 p2_probar.py --genoma resultados/C3_s42/mejor_genoma.pkl --config-neat resultados/C3_s42/config-p2.ini --episodios 5
  python3 p2_probar.py --genoma 'resultados/C3_s42/genomas/mejor_gen0*.pkl' --config-neat resultados/C3_s42/config-p2.ini --episodios 3

Opciones: --duracion S (por defecto la de config_p2.yaml; 120 reproduce el anexo B),
--formulacion A|B, --falso [C1..C4] (sin simulador), --guardar-pasos CARPETA
(una fila por paso de cada episodio, para las figuras).
"""

import argparse
import csv
import glob
import os
import sys

import numpy as np
import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import p2_calidad
from p2_controladores import controlador_aleatorio, controlador_neat, controlador_pd
from p2_entorno import crear_entorno, correr_episodio


def main():
    p = argparse.ArgumentParser(description='Probar un controlador con la calidad de la P2')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--controlador', choices=['pd', 'aleatorio'])
    g.add_argument('--genoma', help='archivo .pkl (admite comodín entre comillas)')
    p.add_argument('--config-neat', default=os.path.join(AQUI, 'config-p2.ini'))
    p.add_argument('--config-p2', default=os.path.join(AQUI, 'config_p2.yaml'))
    p.add_argument('--episodios', type=int, default=3)
    p.add_argument('--duracion', type=float, default=None)
    p.add_argument('--formulacion', choices=['A', 'B', 'C'], default=None)
    p.add_argument('--falso', nargs='?', const='C3', default=None, choices=['C1', 'C2', 'C3', 'C4'])
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--guardar-pasos', default=None)
    a = p.parse_args()

    with open(a.config_p2, encoding='utf-8') as f:
        p2 = yaml.safe_load(f)
    if a.duracion:
        p2['entorno']['duracion_s'] = a.duracion
    if a.formulacion:
        p2['calidad']['formulacion'] = a.formulacion
    ruta_p1 = os.path.normpath(os.path.join(os.path.dirname(a.config_p2), p2['entorno']['config_p1']))
    with open(ruta_p1, encoding='utf-8') as f:
        cfg_p1 = yaml.safe_load(f)
    cal, T = p2['calidad'], p2['entorno']['duracion_s']

    candidatos = []
    if a.controlador == 'pd':
        candidatos = [('pd', controlador_pd())]
    elif a.controlador == 'aleatorio':
        candidatos = [('aleatorio', controlador_aleatorio(a.seed))]
    else:
        for ruta in sorted(glob.glob(a.genoma)) or [a.genoma]:
            candidatos.append((os.path.basename(ruta), controlador_neat(ruta, a.config_neat)))

    entorno = crear_entorno(cfg_p1, p2, falso=a.falso is not None, modo_falso=a.falso or 'C3', seed=a.seed)
    if a.guardar_pasos:
        os.makedirs(a.guardar_pasos, exist_ok=True)
    try:
        resumen = []
        for nombre, ctrl in candidatos:
            Fs = []
            print('\n== {}  (formulación {}, T={:.0f} s)'.format(nombre, cal['formulacion'], T))
            for k in range(a.episodios):
                registro, causa = correr_episodio(entorno, ctrl)
                F, d = p2_calidad.calcular(registro, causa, cal, T)
                Fs.append(F)
                print('  ep.{}: F={:7.2f}  {:18s} {:5.1f} s  en banda {:5.1f} %  sep {:.3f} m  |desv| {:4.1f}°  '
                      'incr {:6.2f} final {:+5.1f}  paradas {}/{}'.format(
                          k + 1, F, causa, d['duracion_s'], d['pct_banda'], d['sep_media'],
                          d['desv_media'], d['incremental'], d['final'],
                          d['paradas_superadas'], d['paradas']))
                if a.guardar_pasos:
                    ruta = os.path.join(a.guardar_pasos, '{}_ep{}.csv'.format(nombre, k + 1))
                    with open(ruta, 'w', newline='') as f:
                        w = csv.DictWriter(f, fieldnames=list(registro[0].keys()))
                        w.writeheader()
                        w.writerows(registro)
            print('  -> media {:.2f}  mínimo {:.2f}  máximo {:.2f}'.format(np.mean(Fs), np.min(Fs), np.max(Fs)))
            resumen.append((nombre, float(np.mean(Fs)), float(np.min(Fs))))
        if len(resumen) > 1:
            print('\nRanking por calidad media:')
            for nombre, m, mn in sorted(resumen, key=lambda x: -x[1]):
                print('  {:28s} media {:7.2f}   mínimo {:7.2f}'.format(nombre, m, mn))
    finally:
        entorno.close()


if __name__ == '__main__':
    main()
