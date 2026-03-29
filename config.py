APP_NAME = "OptiCut"
VERSION = "1.0.0"

KERF_MM = 3  # rez žage (mm) - informativno
OVERMEASURE_MM = 10  # nadmera za prirez (mm)

# App updates (Windows .exe only)
UPDATE_MANIFEST_URL = "https://github.com/lutalica773/OptiCut"
UPDATE_REQUIRE_SAME_HOST = True
UPDATE_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # 200MB safety limit

# Realistične minimalne mere (mm)
MIN_DEPTH_MM = 100
MIN_WIDTH_MM = 300

# Konstrukcija (mm)
BACK_THICKNESS_MM = 4
BACK_CLEARANCE_MM = 2  # skupna zračnost (mm) za hrbtišče (v odprtini)
SHELF_BACK_CLEARANCE_MM = 2  # zračnost police do hrbta (mm)

# Material (privzeto)
CARCASS_MATERIAL_DEFAULT = "Iveral"
BACK_MATERIAL_DEFAULT = "HDF"
CARCASS_MATERIAL_OPTIONS = ["Iveral", "Vezana plošča", "Masiven les"]
BACK_MATERIAL_OPTIONS = ["HDF", "Vezana plošča", "MDF"]

# Mozniki (ocena)
DOWELS_PER_JOINT_MIN = 3
DOWELS_PER_JOINT_MAX = 7
DOWELS_DEPTH_STEP_MM = 200
DOWELS_DEPTH_BASE = 2

# GUI
MAX_SHELVES = 20
