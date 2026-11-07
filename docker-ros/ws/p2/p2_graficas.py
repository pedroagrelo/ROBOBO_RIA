#!/usr/bin/env python3
"""
Práctica 2 — Figuras a partir de lo que escribe la evolución.

  python3 p2_graficas.py curvas resultados/C3_s42/evolucion.csv [más CSV de otras semillas]
                         [--ref 60] [--salida curvas.png]
  python3 p2_graficas.py red resultados/C3_s42/mejor_genoma.pkl
                         --config resultados/C3_s42/config-p2.ini [--salida red.png]

curvas: calidad del mejor y media de la población (banda = desviación típica
        de la población) frente a la generación; abajo, nº de especies y
        complejidad del mejor (nodos y conexiones). Con varios CSV (semillas)
        dibuja la media entre semillas con banda mín-máx.
        --ref: línea horizontal con la calidad del controlador a mano.
red:    topología del genoma (grosor = |peso|, verde = positivo, rojo = negativo).

Sólo necesita numpy, matplotlib y neat-python (no usa ROS).
"""

import argparse
import csv
import os
import pickle
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

NOMBRES_ENTRADA = ['x_blob', 'size_blob', 'visible', 'ir_frontal', 'frames_perdido', 'v_ant', 'w_ant']
NOMBRES_SALIDA = ['a_v', 'a_w']


def leer(ruta):
    with open(ruta) as f:
        filas = list(csv.DictReader(f))
    return {k: np.array([float(r[k]) for r in filas]) for k in filas[0]}


def curvas(rutas, ref, salida):
    datos = [leer(r) for r in rutas]
    n = min(len(d['generacion']) for d in datos)
    g = datos[0]['generacion'][:n]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True,
                                 gridspec_kw={'height_ratios': [2, 1]})

    def media_banda(clave):
        m = np.array([d[clave][:n] for d in datos])
        return m.mean(0), m.min(0), m.max(0)

    mb, mb_lo, mb_hi = media_banda('cal_mejor')
    a1.plot(g, mb, color='tab:blue', label='mejor individuo')
    if len(datos) > 1:
        a1.fill_between(g, mb_lo, mb_hi, color='tab:blue', alpha=0.2,
                        label='mín–máx entre {} semillas'.format(len(datos)))
    mm = np.mean([d['cal_media'][:n] for d in datos], axis=0)
    sd = np.mean([d['cal_desv'][:n] for d in datos], axis=0)
    a1.plot(g, mm, color='tab:orange', label='media de la población')
    a1.fill_between(g, mm - sd, mm + sd, color='tab:orange', alpha=0.2, label='± desv. típica población')
    if ref is not None:
        a1.axhline(ref, color='k', ls='--', lw=1, label='controlador a mano')
    a1.set_ylabel('Calidad (adimensional)')
    a1.legend(fontsize=8, loc='lower right')
    a1.grid(alpha=0.3)

    esp = np.mean([d['especies'][:n] for d in datos], axis=0)
    a2.plot(g, esp, color='tab:green', label='nº de especies')
    a2.set_ylabel('Especies')
    a3 = a2.twinx()
    a3.plot(g, np.mean([d['nodos_mejor'][:n] for d in datos], axis=0), color='tab:purple', ls=':', label='nodos (mejor)')
    a3.plot(g, np.mean([d['conexiones_mejor'][:n] for d in datos], axis=0), color='tab:red', ls=':', label='conexiones (mejor)')
    a3.set_ylabel('Complejidad del mejor')
    h1, l1 = a2.get_legend_handles_labels()
    h2, l2 = a3.get_legend_handles_labels()
    a2.legend(h1 + h2, l1 + l2, fontsize=8, loc='upper left')
    a2.set_xlabel('Generación')
    a2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(salida, dpi=200)
    print('Figura guardada en', salida)


def dibujar_red(genoma, config, nombres_entrada, nombres_salida, ruta):
    gc = config.genome_config
    entradas, salidas = list(gc.input_keys), list(gc.output_keys)
    activas = [c.key for c in genoma.connections.values() if c.enabled]
    # Profundidad de cada nodo: camino más largo desde las entradas
    prof = {n: 0 for n in entradas}
    for _ in range(len(genoma.nodes) + 1):
        for (a, b) in activas:
            nueva = prof[a] + 1 if a in prof and a != b else -1
            if prof.get(b, -1) < nueva <= len(genoma.nodes):
                prof[b] = nueva
    ocultas = [n for n in prof if n not in entradas and n not in salidas]
    capas = [entradas]
    for p in sorted({prof[n] for n in ocultas}):
        capas.append(sorted(n for n in ocultas if prof[n] == p))
    capas.append(salidas)
    pos = {n: (i, j - (len(c) - 1) / 2)
           for i, c in enumerate(capas) for j, n in enumerate(c)}
    fig, ax = plt.subplots(figsize=(7, 5))
    for (a, b) in activas:
        if a in pos and b in pos:
            w = genoma.connections[(a, b)].weight
            ax.annotate("", xy=pos[b], xytext=pos[a], arrowprops=dict(
                arrowstyle="->", lw=0.5 + 1.5 * min(abs(w), 3) / 3,
                color="tab:green" if w > 0 else "tab:red"))
    nombres = dict(zip(entradas, nombres_entrada))
    nombres.update(zip(salidas, nombres_salida))
    for n, (x, y) in pos.items():
        ax.scatter(x, y, s=300, color="lightgrey", edgecolor="black", zorder=3)
        ax.text(x, y + 0.25, nombres.get(n, str(n)), ha="center", fontsize=8)
    ax.axis("off")
    fig.savefig(ruta, dpi=200, bbox_inches="tight")
    print('Figura guardada en', ruta)


def main():
    p = argparse.ArgumentParser(description='Figuras de la P2')
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('curvas')
    c.add_argument('csv', nargs='+')
    c.add_argument('--ref', type=float, default=None)
    c.add_argument('--salida', default='curvas.png')
    r = sub.add_parser('red')
    r.add_argument('genoma')
    r.add_argument('--config', required=True)
    r.add_argument('--salida', default='red.png')
    a = p.parse_args()

    if a.cmd == 'curvas':
        curvas(a.csv, a.ref, a.salida)
    else:
        import neat
        config = neat.Config(neat.DefaultGenome, neat.DefaultReproduction,
                             neat.DefaultSpeciesSet, neat.DefaultStagnation, a.config)
        with open(a.genoma, 'rb') as f:
            genoma = pickle.load(f)
        dibujar_red(genoma, config, NOMBRES_ENTRADA, NOMBRES_SALIDA, a.salida)


if __name__ == '__main__':
    main()
