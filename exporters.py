from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterable, List

import shapefile  # type: ignore

from geometry_utils import coordinates_to_feature, feature_collection
from models import PlaceDetail


class ExportError(RuntimeError):
    pass


WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
)


def _require_geometry(place: PlaceDetail) -> None:
    if not place.mining_shape or not place.mining_shape.coordinates:
        raise ExportError("当前POI缺少多边形坐标，无法导出")


def _place_properties(place: PlaceDetail) -> Dict[str, str]:
    return {
        "name": place.name,
        "address": place.address,
        "telephone": place.telephone,
        "poiid": place.poiid,
        "tag": place.tag,
    }


class GeoJSONExporter:
    def export(self, place: PlaceDetail, file_path: str) -> str:
        _require_geometry(place)
        feature = coordinates_to_feature(place.mining_shape.coordinates, _place_properties(place))
        fc = feature_collection(feature)
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(fc, fh, ensure_ascii=False, indent=2)
        return str(path)

    def export_batch(self, places: Iterable[PlaceDetail], file_path: str) -> tuple[str, List[str]]:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        features = []
        skipped: List[str] = []
        for place in places:
            if not place.has_geometry:
                skipped.append(place.poiid)
                continue
            feature = coordinates_to_feature(place.mining_shape.coordinates, _place_properties(place))
            features.append(feature)
        if not features:
            raise ExportError("选定的POI均缺少可用多边形，无法导出")
        fc = {"type": "FeatureCollection", "features": features}
        with path.open("w", encoding="utf-8") as fh:
            json.dump(fc, fh, ensure_ascii=False, indent=2)
        return str(path), skipped


class ShapefileExporter:
    def export(self, place: PlaceDetail, shp_path: str) -> str:
        _require_geometry(place)
        if not shp_path.lower().endswith(".shp"):
            shp_path = f"{shp_path}.shp"
        base = os.path.splitext(shp_path)[0]
        writer = _create_writer(base)
        writer.poly([place.mining_shape.coordinates])
        writer.record(place.name, place.address, place.telephone, place.poiid)
        writer.close()
        prj_path = f"{base}.prj"
        with open(prj_path, "w", encoding="utf-8") as fh:
            fh.write(WGS84_WKT)
        return shp_path

    def export_batch(self, places: Iterable[PlaceDetail], shp_path: str) -> tuple[str, List[str]]:
        if not shp_path.lower().endswith(".shp"):
            shp_path = f"{shp_path}.shp"
        base = os.path.splitext(shp_path)[0]
        writer = _create_writer(base)
        skipped: List[str] = []
        count = 0
        for place in places:
            if not place.has_geometry:
                skipped.append(place.poiid)
                continue
            writer.poly([place.mining_shape.coordinates])
            writer.record(place.name, place.address, place.telephone, place.poiid)
            count += 1
        if count == 0:
            writer.close()
            raise ExportError("选定的POI均缺少可用多边形，无法导出")
        writer.close()
        prj_path = f"{base}.prj"
        with open(prj_path, "w", encoding="utf-8") as fh:
            fh.write(WGS84_WKT)
        return shp_path, skipped


def _create_writer(base: str) -> shapefile.Writer:
    writer = shapefile.Writer(base, shapeType=shapefile.POLYGON)
    writer.field("name", "C", size=80)
    writer.field("address", "C", size=120)
    writer.field("telephone", "C", size=40)
    writer.field("poiid", "C", size=32)
    return writer
