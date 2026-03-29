from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, render_template, request

# Ensure project root is importable when running `python web_app/app.py`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import APP_NAME, OVERMEASURE_MM, VERSION  # noqa: E402
from logic import Cabinet, ValidationError, calculate_elements, calculate_materials, validate  # noqa: E402

app = Flask(__name__)


def _to_int(value: str, field: str) -> int:
    try:
        return int(value.strip())
    except Exception as e:
        raise ValidationError([f"{field} must be an integer (mm)."]) from e


@app.route("/", methods=["GET", "POST"])
def index():
    errors: List[str] = []
    cut_list: List[Dict[str, Any]] = []
    material: Dict[str, Any] = {}

    form = {
        "width": request.form.get("width", "600"),
        "height": request.form.get("height", "800"),
        "depth": request.form.get("depth", "350"),
        "thickness": request.form.get("thickness", "19"),
    }

    if request.method == "POST":
        try:
            cabinet = Cabinet(
                width=_to_int(form["width"], "Width"),
                height=_to_int(form["height"], "Height"),
                depth=_to_int(form["depth"], "Depth"),
                thickness=_to_int(form["thickness"], "Thickness"),
            )
            shelves_count = 1

            validate(cabinet, shelves_count)
            elements = calculate_elements(cabinet, shelves_count)
            summary = calculate_materials(cabinet, shelves_count, elements)

            pos = 1
            for el in elements:
                cut_list.append(
                    {
                        "poz": pos,
                        "qty": el.quantity,
                        "name": el.name,
                        "raw": f"{el.width + OVERMEASURE_MM} x {el.height + OVERMEASURE_MM} x {el.thickness}",
                        "final": f"{el.width} x {el.height} x {el.thickness}",
                    }
                )
                pos += 1

            material = {
                "surface_m2": summary.surface_m2,
                "volume_m3": summary.volume_m3,
                "edge_banding_m": summary.edge_banding_m,
                "dowels_count": summary.dowels_count,
            }
        except ValidationError as e:
            errors = e.messages
        except Exception as e:
            errors = [str(e)]

    return render_template(
        "index.html",
        app_name=APP_NAME,
        version=VERSION,
        overmeasure_mm=OVERMEASURE_MM,
        form=form,
        errors=errors,
        cut_list=cut_list,
        material=material,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
