from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

Coordinate = Tuple[float, float]


def parse_shape_string(shape: str | None) -> List[Coordinate]:
    if not shape:
        return []
    coords: List[Coordinate] = []
    for pair in shape.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        lon_lat = pair.split(",")
        if len(lon_lat) != 2:
            continue
        try:
            lon = float(lon_lat[0])
            lat = float(lon_lat[1])
        except ValueError:
            continue
        coords.append((lon, lat))
    # ensure polygon closed for downstream consumers
    if coords and coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def coordinates_to_feature(coords: Sequence[Coordinate], properties: dict | None = None) -> dict:
    properties = properties or {}
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "Polygon",
            "coordinates": [list(coords)],
        },
    }


def feature_collection(feature: dict) -> dict:
    return {"type": "FeatureCollection", "features": [feature]}


def compute_bounds(coords: Iterable[Coordinate]) -> Tuple[float, float, float, float] | None:
    points = list(coords)
    if not points:
        return None
    xs = [pt[0] for pt in points]
    ys = [pt[1] for pt in points]
    return min(xs), min(ys), max(xs), max(ys)


def normalize_to_view(coords: Sequence[Coordinate], width: float, height: float, padding: float = 10.0) -> List[Coordinate]:
    bounds = compute_bounds(coords)
    if not bounds:
        return []
    min_x, min_y, max_x, max_y = bounds
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    scale_x = (width - 2 * padding) / span_x
    scale_y = (height - 2 * padding) / span_y
    scale = min(scale_x, scale_y)
    normalized: List[Coordinate] = []
    for x, y in coords:
        nx = padding + (x - min_x) * scale
        ny = height - (padding + (y - min_y) * scale)
        normalized.append((nx, ny))
    return normalized


# GCJ-02 to WGS84 conversion utilities
A = 6378245.0
EE = 0.00669342162296594323
PI = math.pi


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * PI) + 320 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return ret


def _out_of_china(lon: float, lat: float) -> bool:
    return not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271)


def gcj02_to_wgs84(lon: float, lat: float) -> Coordinate:
    if _out_of_china(lon, lat):
        return lon, lat
    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * PI
    magic = math.sin(rad_lat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    d_lon = (d_lon * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * PI)
    mg_lat = lat + d_lat
    mg_lon = lon + d_lon
    return lon - (mg_lon - lon), lat - (mg_lat - lat)


def convert_gcj02_polygon(coords: Sequence[Coordinate]) -> List[Coordinate]:
    return [gcj02_to_wgs84(lon, lat) for lon, lat in coords]
