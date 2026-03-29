from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from config import KERF_MM, OVERMEASURE_MM
from logic import Cabinet, Element, MaterialSummary


def _autosize_columns(ws, max_width: int = 60) -> None:
    for col in range(1, ws.max_column + 1):
        max_len = 0
        for row in range(1, ws.max_row + 1):
            value = ws.cell(row=row, column=col).value
            if value is None:
                continue
            max_len = max(max_len, len(str(value)))
        ws.column_dimensions[get_column_letter(col)].width = min(max_width, max(10, max_len + 2))


def _header_style(ws, row: int, fill_color: str) -> None:
    for cell in ws[row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=fill_color)
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _raw_dimensions(el: Element) -> str:
    return f"{el.width + OVERMEASURE_MM} x {el.height + OVERMEASURE_MM} x {el.thickness}"


def _final_dimensions(el: Element) -> str:
    return f"{el.width} x {el.height} x {el.thickness}"


def _material_for_element(el: Element, carcass_material: str, back_material: str) -> str:
    if el.name == "Hrbtišče":
        return back_material
    return carcass_material


def export_excel(
    cabinet: Cabinet,
    elements: list[Element],
    summary: MaterialSummary,
    file_path: str,
    carcass_material: str,
    back_material: str,
) -> None:
    wb = Workbook()

    # =========================
    # PRIREZOVALNA LISTA
    # =========================
    ws = wb.active
    ws.title = "Prirezovalna lista"

    ws.append(
        [
            "poz",
            "qty",
            "name",
            "material",
            f"raw dimensions (+{OVERMEASURE_MM}mm)",
            "final dimensions",
        ]
    )
    _header_style(ws, 1, "1F4E79")

    pos = 1
    for el in elements:
        ws.append(
            [
                pos,
                el.quantity,
                el.name,
                _material_for_element(el, carcass_material, back_material),
                _raw_dimensions(el),
                _final_dimensions(el),
            ]
        )
        pos += 1

    ws.freeze_panes = "A2"
    _autosize_columns(ws)

    ws[f"A{ws.max_row + 2}"] = f"Kerf (rez žage): {KERF_MM} mm (informativno)"
    ws[f"A{ws.max_row}"].font = Font(italic=True, color="666666")

    # =========================
    # MATERIALNA LISTA
    # =========================
    ws2 = wb.create_sheet("Materialna lista")
    ws2.append(["Postavka", "Količina", "Enota"])
    _header_style(ws2, 1, "385723")

    ws2.append(["Skupna površina", summary.surface_m2, "m²"])
    ws2.append(["Skupni volumen", summary.volume_m3, "m³"])
    ws2.append(["Robni trak", summary.edge_banding_m, "m"])
    ws2.append(["Mozniki (ocena)", summary.dowels_count, "kos"])

    ws2.freeze_panes = "A2"
    _autosize_columns(ws2)

    wb.save(file_path)

