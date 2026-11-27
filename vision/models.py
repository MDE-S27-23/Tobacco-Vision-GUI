from dataclasses import dataclass, field
from typing import List


@dataclass
class GridInfo:
    x_lines: List[int]
    y_lines: List[int]
    pitch_x_px: float
    pitch_y_px: float
    mm_per_px_x: float
    mm_per_px_y: float
    rotation_deg: float = 0.0
    correction_mode: str = 'none'
    image_scale: float = 1.0

    @property
    def columns(self) -> int:
        return max(0, len(self.x_lines) - 1)

    @property
    def rows(self) -> int:
        return max(0, len(self.y_lines) - 1)


@dataclass
class LeafMeasurement:
    leaf_number: int
    length_mm: float
    width_mm: float
    area_mm2: float
    area_px: float
    center_x_px: float
    center_y_px: float
    mean_bgr: tuple
    mean_hex: str
    quality_flag: str = 'OK'


@dataclass
class CellResult:
    row: int
    column: int
    excel_cell: str
    bounds: tuple
    status: str
    leaves: List[LeafMeasurement] = field(default_factory=list)
    total_leaf_area_mm2: float = 0.0
    quality_flag: str = 'OK'
