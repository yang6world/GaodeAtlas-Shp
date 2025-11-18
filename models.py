from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

Coordinate = Tuple[float, float]


@dataclass
class MiningShape:
    coordinates: List[Coordinate]
    level: int
    center: Coordinate
    raw: Dict


@dataclass
class PlaceDetail:
    poiid: str
    name: str
    classify: str
    longitude: float
    latitude: float
    address: str
    telephone: str
    city_name: str
    city_adcode: str
    code: str
    tag: str
    mining_shape: MiningShape | None
    metadata: Dict
    raw: Dict = field(default_factory=dict)

    @property
    def has_geometry(self) -> bool:
        return bool(self.mining_shape and self.mining_shape.coordinates)
