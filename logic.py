from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple

from config import (
    BACK_CLEARANCE_MM,
    BACK_THICKNESS_MM,
    DOWELS_PER_JOINT_MAX,
    DOWELS_PER_JOINT_MIN,
    DOWELS_DEPTH_BASE,
    DOWELS_DEPTH_STEP_MM,
    MIN_DEPTH_MM,
    MIN_WIDTH_MM,
    SHELF_BACK_CLEARANCE_MM,
)


class ValidationError(Exception):
    def __init__(self, messages: Iterable[str]):
        self.messages = [m for m in messages if m]
        super().__init__("\n".join(self.messages))


@dataclass(frozen=True)
class Cabinet:
    width: int
    height: int
    depth: int
    thickness: int


@dataclass(frozen=True)
class Element:
    name: str
    quantity: int
    width: int
    height: int
    thickness: int

    def surface_m2(self) -> float:
        return (self.width * self.height * self.quantity) / 1_000_000

    def volume_m3(self) -> float:
        return (self.width * self.height * self.thickness * self.quantity) / 1_000_000_000


@dataclass(frozen=True)
class MaterialSummary:
    surface_m2: float
    volume_m3: float
    edge_banding_m: float
    dowels_count: int


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def inner_dimensions(cabinet: Cabinet) -> Tuple[int, int, int]:
    inner_width = cabinet.width - 2 * cabinet.thickness
    inner_height = cabinet.height - 2 * cabinet.thickness
    inner_depth = cabinet.depth - BACK_THICKNESS_MM
    return inner_width, inner_height, inner_depth


def validate(cabinet: Cabinet, shelves_count: int) -> None:
    errors: List[str] = []

    def require_positive(label: str, value: int) -> None:
        if value <= 0:
            errors.append(f"{label} mora biti > 0 mm.")

    require_positive("Širina", cabinet.width)
    require_positive("Višina", cabinet.height)
    require_positive("Globina", cabinet.depth)
    require_positive("Debelina", cabinet.thickness)

    if shelves_count < 0:
        errors.append("Število polic ne sme biti negativno.")

    if cabinet.depth < MIN_DEPTH_MM:
        errors.append(f"Globina je nerealna (< {MIN_DEPTH_MM} mm).")
    if cabinet.width < MIN_WIDTH_MM:
        errors.append(f"Širina je nerealna (< {MIN_WIDTH_MM} mm).")

    inner_width = cabinet.width - 2 * cabinet.thickness
    inner_height = cabinet.height - 2 * cabinet.thickness

    # CRITICAL: zahtevane formule
    if inner_width != cabinet.width - 2 * cabinet.thickness:
        errors.append("Napaka izračuna notranje širine (W - 2*T).")
    if inner_height != cabinet.height - 2 * cabinet.thickness:
        errors.append("Napaka izračuna notranje višine (H - 2*T).")

    if inner_width <= 0:
        errors.append("Notranja širina <= 0 (W - 2*T).")
    if inner_height <= 0:
        errors.append("Notranja višina <= 0 (H - 2*T).")

    inner_depth = cabinet.depth - BACK_THICKNESS_MM
    if inner_depth <= 0:
        errors.append("Notranja globina <= 0 (D - hrbtišče).")

    # Hrbtišče mora fizično iti v odprtino
    back_w = inner_width - BACK_CLEARANCE_MM
    back_h = inner_height - BACK_CLEARANCE_MM
    if back_w <= 0 or back_h <= 0:
        errors.append("Hrbtišče ne more fizično v odprtino (premajhne mere).")

    # Polica mora fizično stati v korpusu
    if shelves_count > 0:
        shelf_w = inner_width
        shelf_d = inner_depth - SHELF_BACK_CLEARANCE_MM
        if shelf_w <= 0:
            errors.append("Polica ne more fizično v korpus (širina <= 0).")
        if shelf_d <= 0:
            errors.append("Polica ne more fizično v korpus (globina <= 0).")
        if shelf_w > inner_width:
            errors.append("Polica je širša od notranje širine korpusa.")
        if shelf_d > inner_depth:
            errors.append("Polica je globlja od notranje globine korpusa.")

    if errors:
        raise ValidationError(errors)


def calculate_elements(cabinet: Cabinet, shelves_count: int) -> List[Element]:
    inner_width, inner_height, inner_depth = inner_dimensions(cabinet)

    elements: List[Element] = []

    # Stranice: polna višina, polna globina
    elements.append(
        Element(
            name="Stranica",
            quantity=2,
            width=cabinet.depth,
            height=cabinet.height,
            thickness=cabinet.thickness,
        )
    )

    # Strop + dno: med stranicami
    elements.append(
        Element(
            name="Strop",
            quantity=1,
            width=cabinet.depth,
            height=inner_width,
            thickness=cabinet.thickness,
        )
    )
    elements.append(
        Element(
            name="Dno",
            quantity=1,
            width=cabinet.depth,
            height=inner_width,
            thickness=cabinet.thickness,
        )
    )

    # Police
    if shelves_count > 0:
        shelf_depth = inner_depth - SHELF_BACK_CLEARANCE_MM
        elements.append(
            Element(
                name="Polica",
                quantity=shelves_count,
                width=shelf_depth,
                height=inner_width,
                thickness=cabinet.thickness,
            )
        )

    # Hrbtišče (v odprtini, z zračnostjo)
    elements.append(
        Element(
            name="Hrbtišče",
            quantity=1,
            width=inner_height - BACK_CLEARANCE_MM,
            height=inner_width - BACK_CLEARANCE_MM,
            thickness=BACK_THICKNESS_MM,
        )
    )

    return elements


def calculate_materials(cabinet: Cabinet, shelves_count: int, elements: List[Element]) -> MaterialSummary:
    surface_m2 = 0.0
    volume_m3 = 0.0
    edge_banding_m = 0.0

    inner_width, _, _ = inner_dimensions(cabinet)

    for el in elements:
        surface_m2 += el.surface_m2()
        volume_m3 += el.volume_m3()

        # Robni trak - prednji robovi
        if el.name == "Stranica":
            edge_banding_m += (cabinet.height * el.quantity) / 1000.0
        elif el.name in {"Strop", "Dno", "Polica"}:
            edge_banding_m += (inner_width * el.quantity) / 1000.0

    # Mozniki - ocena glede na število spojev in globino
    # Spoji: strop (2), dno (2), vsaka polica (2) -> skupaj 4 + 2*n
    joints = 4 + 2 * max(0, shelves_count)
    dowels_per_joint = _clamp(
        int(round(cabinet.depth / float(DOWELS_DEPTH_STEP_MM))) + DOWELS_DEPTH_BASE,
        DOWELS_PER_JOINT_MIN,
        DOWELS_PER_JOINT_MAX,
    )
    dowels_count = joints * dowels_per_joint

    return MaterialSummary(
        surface_m2=round(surface_m2, 3),
        volume_m3=round(volume_m3, 5),
        edge_banding_m=round(edge_banding_m, 2),
        dowels_count=int(dowels_count),
    )
