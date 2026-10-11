"""Zona de despacho: decide si un punto del mapa cae dentro de la zona donde se despacha.

Usa el mismo archivo que dibuja el mapa de la página Local
(core/static/data/la_florida.geojson), así lo que el cliente ve en el mapa es
exactamente lo que se exige al comprar. Si el local amplía la zona, se cambia
ese archivo y el mapa y la validación quedan al día.

No necesita librerías externas: es una prueba de "punto dentro de polígono".
"""
import json
import math
from functools import lru_cache
from pathlib import Path

RUTA_ZONA = Path(__file__).resolve().parent / 'static' / 'data' / 'la_florida.geojson'


@lru_cache(maxsize=1)
def _poligonos():
    """Lee la zona una sola vez.

    Devuelve una lista de polígonos. Cada polígono es una lista de anillos: el primero
    es el contorno y los demás son huecos. Cada punto es (longitud, latitud).
    """
    datos = json.loads(RUTA_ZONA.read_text(encoding='utf-8'))
    poligonos = []

    def recoger(geo):
        tipo = geo.get('type')
        if tipo == 'FeatureCollection':
            for elemento in geo.get('features', []):
                recoger(elemento)
        elif tipo == 'Feature':
            recoger(geo.get('geometry') or {})
        elif tipo == 'Polygon':
            poligonos.append(geo['coordinates'])
        elif tipo == 'MultiPolygon':
            poligonos.extend(geo['coordinates'])

    recoger(datos)
    if not poligonos:
        raise ValueError(f'La zona de despacho {RUTA_ZONA.name} no tiene polígonos.')
    return poligonos


def _punto_en_anillo(x, y, anillo):
    """Prueba del rayo: cuenta cuántas veces un rayo horizontal cruza el contorno."""
    dentro = False
    j = len(anillo) - 1
    for i in range(len(anillo)):
        xi, yi = anillo[i][0], anillo[i][1]
        xj, yj = anillo[j][0], anillo[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def leer_coordenadas(latitud, longitud):
    """Convierte lo que llega del formulario en (latitud, longitud) o None si no sirve."""
    try:
        lat = float(str(latitud).strip())
        lng = float(str(longitud).strip())
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def punto_en_zona(latitud, longitud):
    """True si el punto está dentro de la zona de despacho."""
    for anillos in _poligonos():
        contorno, huecos = anillos[0], anillos[1:]
        if _punto_en_anillo(longitud, latitud, contorno) and not any(
            _punto_en_anillo(longitud, latitud, hueco) for hueco in huecos
        ):
            return True
    return False
