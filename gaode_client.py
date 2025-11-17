from __future__ import annotations

from typing import Any, Dict

from geometry_utils import convert_gcj02_polygon, gcj02_to_wgs84, parse_shape_string
from models import MiningShape, PlaceDetail


class GaodeClient:
    def build_place_from_payload(self, payload: Dict[str, Any], poiid: str) -> PlaceDetail:
        if str(payload.get("status")) != "1":
            raise ValueError(f"Gaode response returned status={payload.get('status')}")
        data = payload.get("data") or {}
        base = data.get("base") or {}
        spec = data.get("spec") or {}
        mining_shape_raw = (spec.get("mining_shape") or {}) if spec else {}
        gcj_coords = parse_shape_string(mining_shape_raw.get("shape"))
        coordinates = convert_gcj02_polygon(gcj_coords)
        mining_shape = None
        if coordinates:
            center = mining_shape_raw.get("center")
            center_tuple = coordinates[0] if coordinates else (0.0, 0.0)
            if center:
                try:
                    lon_str, lat_str = center.split(",")
                    center_tuple = gcj02_to_wgs84(float(lon_str), float(lat_str))
                except ValueError:
                    pass
            level_value = mining_shape_raw.get("level")
            try:
                level = int(level_value) if level_value is not None else 0
            except (TypeError, ValueError):
                level = 0
            mining_shape = MiningShape(
                coordinates=coordinates,
                level=level,
                center=center_tuple,
                raw=mining_shape_raw,
            )
        return PlaceDetail(
            poiid=base.get("poiid") or poiid,
            name=base.get("name") or "",
            address=base.get("address") or "",
            telephone=base.get("telephone") or "",
            city_name=base.get("city_name") or "",
            tag=base.get("tag") or base.get("new_keytype") or "",
            mining_shape=mining_shape,
            metadata={
                "classify": base.get("classify"),
                "title": base.get("title"),
                "business": base.get("business"),
            },
            raw=data,
        )
