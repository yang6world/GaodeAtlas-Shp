from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Iterable, List, Sequence, Tuple

Coordinate = Tuple[float, float]


def parse_shape_string(shape: str | None) -> List[Coordinate]:
    rings = parse_shape_rings(shape)
    return rings[0] if rings else []


def parse_shape_rings(shape: str | None) -> List[List[Coordinate]]:
    if not shape:
        return []
    rings: List[List[Coordinate]] = []
    for raw_ring in shape.split("@"):
        ring_coords: List[Coordinate] = []
        for pair in raw_ring.split(";"):
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
            ring_coords.append((lon, lat))
        if not ring_coords:
            continue
        if ring_coords[0] != ring_coords[-1]:
            ring_coords.append(ring_coords[0])
        rings.append(ring_coords)
    return rings


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


def coordinates_to_shape_string(
    coords: Sequence[Coordinate], *, precision: int = 6, close_ring: bool = True
) -> str:
    if not coords:
        return ""
    points = list(coords)
    if points[0] == points[-1] and not close_ring:
        points = points[:-1]
    elif close_ring and points[0] != points[-1]:
        points = points + [points[0]]
    fmt = f"{{:.{precision}f}}"
    return ";".join(f"{fmt.format(lon)},{fmt.format(lat)}" for lon, lat in points)


def rings_to_shape_string(
    rings: Sequence[Sequence[Coordinate]], *, precision: int = 6, close_rings: bool = True
) -> str:
    parts = []
    for ring in rings:
        text = coordinates_to_shape_string(ring, precision=precision, close_ring=close_rings)
        if text:
            parts.append(text)
    return "@".join(parts)


def feature_to_shape_string(feature: dict, *, precision: int = 6, close_rings: bool = True) -> str:
    geometry = feature.get("geometry") or {}
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    rings: List[List[Coordinate]] = []
    if gtype == "Polygon":
        rings = [[(float(lon), float(lat)) for lon, lat in ring] for ring in coords]
    elif gtype == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                rings.append([(float(lon), float(lat)) for lon, lat in ring])
    else:
        raise ValueError("Only Polygon or MultiPolygon geometries can be converted to shape strings")
    return rings_to_shape_string(rings, precision=precision, close_rings=close_rings)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Convert GeoJSON polygons to Gaode shape strings")
    parser.add_argument("geojson", help="Path to the GeoJSON file to convert")
    parser.add_argument(
        "--feature-index",
        type=int,
        default=0,
        help="Zero-based index of the feature to convert (default: 0)",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=6,
        help="Decimal places to keep for each coordinate (default: 6)",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Do not append the starting point at the end of each ring",
    )
    args = parser.parse_args()
    with open(args.geojson, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    features = data.get("features") or []
    if not features:
        raise SystemExit("GeoJSON 文件中没有任何 Feature")
    index = max(0, min(args.feature_index, len(features) - 1))
    shape_text = feature_to_shape_string(
        features[index],
        precision=max(0, args.precision),
        close_rings=not args.keep_open,
    )
    print(shape_text)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("用法: python geometry_utils.py <geojson> [--feature-index N] [--precision P]")
        sys.exit(0)
    _cli()
