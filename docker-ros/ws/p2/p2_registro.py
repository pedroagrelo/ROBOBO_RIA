#!/usr/bin/env python3
"""
Práctica 2 — Registro por generación (reporter propio de NEAT-Python).

Escribe una fila por generación en evolucion.csv y guarda el mejor genoma de
cada generación en genomas/mejor_genNNN.pkl. Continúa los contadores si la
evolución se reanuda desde un punto de control.

IMPORTANTE: el Checkpointer serializa los registros con pickle, así que este
objeto sólo guarda rutas y números (nunca el entorno, un archivo abierto ni
el nodo de ROS 2).
"""

import csv
import os
import pickle
import statistics
import time

import neat

# Lo actualiza evaluar_genoma() (p2_evolucionar.py) tras cada episodio.
CONTADOR = {"pasos": 0, "evaluaciones": 0}
# Generación en curso (la fija SeguimientoGeneracion; la lee la evaluación).
ESTADO = {"gen": 0}


class SeguimientoGeneracion(neat.reporting.BaseReporter):
    """Anota en ESTADO la generación en curso. Se define a nivel de módulo
    (no dentro de una función) para que el Checkpointer pueda serializarlo."""

    def start_generation(self, generation):
        ESTADO["gen"] = generation


class RegistroGeneracion(neat.reporting.BaseReporter):
    CAMPOS = ["generacion", "cal_mejor", "cal_media", "cal_desv", "especies",
              "nodos_mejor", "conexiones_mejor", "evaluaciones", "pasos", "segundos"]

    def __init__(self, ruta_csv, carpeta_genomas):
        self.ruta, self.carpeta = ruta_csv, carpeta_genomas
        os.makedirs(carpeta_genomas, exist_ok=True)
        self.base = {"evaluaciones": 0, "pasos": 0, "segundos": 0.0}
        if os.path.exists(ruta_csv):                 # se reanuda una evolución
            with open(ruta_csv) as f:
                filas = list(csv.DictReader(f))
            if filas:
                self.base = {k: float(filas[-1][k]) for k in self.base}
        else:
            with open(ruta_csv, "w", newline="") as f:
                csv.writer(f).writerow(self.CAMPOS)
        self.inicio = dict(CONTADOR)                 # por si el proceso ya había evaluado
        self.t0, self.gen = time.time(), 0

    def start_generation(self, generation):
        self.gen = generation

    def post_evaluate(self, config, population, species, best_genome):
        cal = [g.fitness for g in population.values()]
        nodos, conexiones = best_genome.size()
        fila = [self.gen, best_genome.fitness,
                statistics.mean(cal), statistics.pstdev(cal),
                len(species.species), nodos, conexiones,
                int(self.base["evaluaciones"] + CONTADOR["evaluaciones"]
                    - self.inicio["evaluaciones"]),
                int(self.base["pasos"] + CONTADOR["pasos"] - self.inicio["pasos"]),
                round(self.base["segundos"] + time.time() - self.t0, 1)]
        with open(self.ruta, "a", newline="") as f:
            csv.writer(f).writerow(fila)
        ruta = os.path.join(self.carpeta, f"mejor_gen{self.gen:03d}.pkl")
        with open(ruta, "wb") as f:
            pickle.dump(best_genome, f)
