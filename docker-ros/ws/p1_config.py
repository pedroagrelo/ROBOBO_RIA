"""
Carga del archivo de configuración (.yaml) del entorno.

cargar_config(ruta) devuelve el diccionario de la config indicada; sin ruta
carga config_v2.yaml de esta carpeta. Los scripts lo usan con su opción
--config (p. ej. --config config_v1.yaml para los modelos de la v1).
"""

import os
import yaml

CONFIG_POR_DEFECTO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_v2.yaml')


def cargar_config(ruta=None):
    ruta = ruta or CONFIG_POR_DEFECTO
    with open(ruta, encoding='utf-8') as f:
        return yaml.safe_load(f)

