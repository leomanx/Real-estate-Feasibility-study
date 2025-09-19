import math
import io
import json
import csv
import sys
import argparse
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple

# ============================================================
# Helpers (no external deps)
# ============================================================

def nf(x, digits: int = 2) -> str:
    try:
        return f"{float(x):,.{digits}f}"
    except Exception:
        return "–"


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _to_number_if_possible(s: str):
    try:
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
    except Exception:
        pass
    try:
        # allow ints/floats with optional sign and single dot
        if s.replace(".", "", 1).lstrip("-+").isdigit():
            return float(s)
    except Exception:
        pass
    return s


def create_csv_from_dict(d: Dict[str, Any]) -> bytes:
    """Return CSV bytes with columns Field,Value.
    JSON-encode complex values so they round-trip."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Field", "Value"])
    for k, v in d.items():
        if isinstance(v, (list, dict)):
            writer.writerow([k, json.dumps(v, ensure_ascii=False)])
        else:
            writer.writerow([k, v])
    return output.getvalue().encode("utf-8")


def parse_csv_to_state(file_bytes: bytes) -> Dict[str, Any]:
    text = file_bytes.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    state: Dict[str, Any] = {}
    for row in reader:
        k = str(row.get("Field", "")).strip()
        v_raw = str(row.get("Value", ""))
        if not k:
            continue
        # Try JSON first
        if (v_raw.startswith("{") and v_raw.endswith("}")) or (v_raw.startswith("[") and v_raw.endswith("]")):
            try:
                state[k] = json.loads(v_raw)
                continue
            except Exception:
                pass
        state[k] = _to_number_if_possible(v_raw)
    return state


# ============================================================
# Rules / Presets
# ============================================================
BUILDING_TYPES = ["Housing", "Hi-Rise", "Low-Rise", "Public Building", "Office Building", "Hotel"]
PRESETS = ["None", "TH Condo", "TH Hotel"]

RULES = {
    "base": {"farRange": (1.0, 10.0)},
    "building": {
        "Housing": {"minOSR": 30, "greenPctOfOSR": None},
        "Hi-Rise": {"minOSR": 10, "greenPctOfOSR": 50},
        "Low-Rise": {"minOSR": 10, "greenPctOfOSR": 50},
        "Public Building": {"minOSR": None, "greenPctOfOSR": None},
        "Office Building": {"minOSR": None, "greenPctOfOSR": None},
        "Hotel": {"minOSR": 10, "greenPctOfOSR": 40},
    },
    "presets": {
        "None": {
            "lockOSR": False,
            "lockGreenPct": False,
            "bType": "Housing",
            "osr": 15,
            "greenPct": 40,
            "countParkingInFAR": True,
            "countBasementInFAR": False,
        },
        "TH Condo": {
            "lockOSR": True,
            "lockGreenPct": True,
            "bType": "Hi-Rise",
            "osr": 10,
            "greenPct": 50,
            "countParkingInFAR": True,
            "countBasementInFAR": False,
        },
        "TH Hotel": {
            "lockOSR": True,
            "lockGreenPct": False,
            "bType": "Hotel",
            "osr": 10,
            "greenPct": 40,
            "countParkingInFAR": True,
            "countBasementInFAR": False,
        },
    },
}


def suggested_osr(btype: str) -> float:
    v = RULES["building"].get(btype, {}).get("minOSR")
    return float(v) if v is not None else 15.0


def suggested_green_pct(btype: str) -> float:
    v = RULES["building"].get(btype, {}).get("greenPctOfOSR")
    return float(v) if v is not None else 40.0


# ============================================================
# Default Scenario
# ============================================================
DEFAULT_SCENARIO: Dict[str, Any] = {
    # Core site & zoning
    "siteArea": 8000.0,
    "far": 5.0,
    "bType": "Housing",
    "osr": 30.0,
    "greenPctOfOSR": 40.0,

    # Geometry
    "mainFloorsAG": 20.0,
    "mainFloorsBG": 0.0,
    "parkingConFloorsAG": 3.0,
    "parkingConFloorsBG": 0.0,
    "parkingAutoFloorsAG": 0.0,
    "parkingAutoFloorsBG": 0.0,
    "ftf": 3.2,
    "maxHeight": 120.0,

    # Plates (m²)
    "mainFloorPlate": 1500.0,
    "parkingConPlate": 1200.0,
    "parkingAutoPlate": 800.0,

    # Parking efficiency (structured)
    "bayConv": 25.0,
    "circConvPct": 0.0,   # proportion (0-1)
    "bayAuto": 16.0,
    "circAutoPct": 0.0,

    # Open-lot (at-grade)
    "openLotArea": 0.0,
    "openLotBay": 25.0,
    "openLotCircPct": 0.0,

    # Eff ratios (based on GFA)
    "publicPctOfGFA": 10.0,
    "nlaPctOfPublic": 40.0,
    "bohPctOfGFA": 8.0,
    "servicePctOfGFA": 2.0,

    # FAR toggles
    "countParkingInFAR": True,   # conventional parking only
    "countBasementInFAR": False,

    # Costs
    "costMainPerSqm": 30000.0,
    "costParkConvPerSqm": 18000.0,
    "costParkAutoPerSqm": 25000.0,
    "costGreenPerSqm": 4500.0,
    "costConventionalPerCar": 125000.0,
    "costAutoPerCar": 432000.0,
    "costOpenLotPerCar": 60000.0,

    "customCosts": [],  # list of dicts: {name, kind: per_sqm|per_car_conv|per_car_auto|lump_sum, rate}

    # Budget
    "budget": 500_000_000.0,
}


# ============================================================
# Core Calculations
# ============================================================

def calc_disabled_parking(total_cars: int) -> int:
    if total_cars <= 0:
        return 0
    if total_cars <= 50:
        return 2
    if total_cars <= 100:
        return 3
    extra_hundreds = math.ceil((total_cars - 100) / 100)
    return 3 + max(0, extra_hundreds)


@dataclass
class Derived:
    # zoning
    maxGFA: float
    farCounted: float
    farOk: bool
    # areas
    mainCFA_AG: float
    mainCFA_BG: float
    parkConCFA_AG: float
    parkConCFA_BG: float
    parkAutoCFA_AG: float
    parkAutoCFA_BG: float
    mainCFA: float
    parkConCFA: float
    parkAutoCFA: float
    totalCFA: float
    gfa: float
    # height
    estHeight: float
    heightOk: bool
    # parking supply
    convCarsPerFloor: int
    autoCarsPerFloor: int
    totalConvCars: int
    totalAutoCars: int
    openLotCars: int
    totalCars: int
    disabledCars: int
    # efficiency
    publicArea: float
    bohArea: float
    serviceArea: float
    nsa: float
    nla: float
    # design efficiency ratios
    deNSA_GFA: float
    deNSA_CFA: float
    deGFA_CFA: float
    deNLA_GFA: float
    # costs
    costMain: float
    costParkConv: float
    costParkAuto: float
    greenCost: float
    costConvPerCar: float
    costAutoPerCar: float
    costOpenLotPerCar: float
    customCostTotal: float
    capexTotal: float
    budgetOk: bool
    # display helpers
    openSpaceArea: float
    greenArea: float
    effAreaOpenCar: float


def compute(state: Dict[str, Any]) -> Derived:
    far_min, far_max = RULES["base"]["farRange"]
    far = clamp(float(state["far"]), far_min, far_max)
    site_area = float(state["siteArea"])
    maxGFA = site_area * far

    # OSR & Green
    osr = clamp(float(state["osr"]), 0.0, 100.0)
    green_pct = clamp(float(state["greenPctOfOSR"]), 0.0, 100.0)
    openSpaceArea = (osr / 100.0) * site_area
    greenArea = (green_pct / 100.0) * openSpaceArea

    # CFA (structured)
    mainFloorsAG = float(state["mainFloorsAG"]) ; mainFloorsBG = float(state["mainFloorsBG"]) 
    parkingConAG = float(state["parkingConFloorsAG"]) ; parkingConBG = float(state["parkingConFloorsBG"]) 
    parkingAutoAG = float(state["parkingAutoFloorsAG"]) ; parkingAutoBG = float(state["parkingAutoFloorsBG"]) 

    mainPlate = float(state["mainFloorPlate"]) ; parkConPlate = float(state["parkingConPlate"]) ; parkAutoPlate = float(state["parkingAutoPlate"]) 

    mainCFA_AG = mainFloorsAG * mainPlate
    mainCFA_BG = mainFloorsBG * mainPlate
    parkConCFA_AG = parkingConAG * parkConPlate
    parkConCFA_BG = parkingConBG * parkConPlate
    parkAutoCFA_AG = parkingAutoAG * parkAutoPlate
    parkAutoCFA_BG = parkingAutoBG * parkAutoPlate

    mainCFA = mainCFA_AG + mainCFA_BG
    parkConCFA = parkConCFA_AG + parkConCFA_BG
    parkAutoCFA = parkAutoCFA_AG + parkAutoCFA_BG
    totalCFA = mainCFA + parkConCFA + parkAutoCFA

    # Height (AG only)
    estHeight = float(state["ftf"]) * (mainFloorsAG + parkingConAG + parkingAutoAG)
    heightOk = estHeight <= float(state["maxHeight"])

    # Parking efficiency
    effAreaConCar = float(state["bayConv"]) * (1.0 + float(state["circConvPct"]))
    effAreaAutoCar = float(state["bayAuto"]) * (1.0 + float(state["circAutoPct"]))
    effAreaOpenCar = float(state["openLotBay"]) * (1.0 + float(state["openLotCircPct"]))

    # Supply per floor & totals
    convCarsPerFloor = int(math.floor(parkConPlate / max(1.0, effAreaConCar)))
    autoCarsPerFloor = int(math.floor(parkAutoPlate / max(1.0, effAreaAutoCar)))
    totalConvCars = convCarsPerFloor * int(parkingConAG + parkingConBG)
    totalAutoCars = autoCarsPerFloor * int(parkingAutoAG + parkingAutoBG)

    openLotArea = float(state["openLotArea"]) ; openLotCars = int(math.floor(openLotArea / max(1.0, effAreaOpenCar)))

    totalCars = totalConvCars + totalAutoCars + openLotCars
    disabledCars = calc_disabled_parking(totalCars)

    # GFA (actual): main + conventional parking; auto & open-lot are NOT GFA
    gfa = mainCFA + parkConCFA

    # FAR-counted (legal): basement counted by flag; conventional parking counted only when flag=true; auto excluded
    countParkingInFAR = bool(state["countParkingInFAR"]) ; countBasementInFAR = bool(state["countBasementInFAR"]) 
    farCounted = (mainCFA_AG + (mainCFA_BG if countBasementInFAR else 0.0)) + (
        (parkConCFA_AG + (parkConCFA_BG if countBasementInFAR else 0.0)) if countParkingInFAR else 0.0
    )

    # FAR check uses GFA
    farOk = gfa <= maxGFA

    # Efficiency breakdown (from GFA)
    publicArea = (float(state["publicPctOfGFA"]) / 100.0) * gfa
    bohArea = (float(state["bohPctOfGFA"]) / 100.0) * gfa
    serviceArea = (float(state["servicePctOfGFA"]) / 100.0) * gfa
    nsa = max(0.0, gfa - (publicArea + bohArea + serviceArea))
    nla = (float(state["nlaPctOfPublic"]) / 100.0) * publicArea

    # Costs (coarse)
    costMain = mainCFA * float(state["costMainPerSqm"])
    costParkConv = parkConCFA * float(state["costParkConvPerSqm"])
    costParkAuto = parkAutoCFA * float(state["costParkAutoPerSqm"])
    greenCost = greenArea * float(state["costGreenPerSqm"])

    # Per-car costs
    costConvPerCar = float(state["costConventionalPerCar"]) * totalConvCars
    costAutoPerCar = float(state["costAutoPerCar"]) * totalAutoCars
    costOpenLotPerCar = float(state["costOpenLotPerCar"]) * openLotCars

    # Custom costs
    customCostTotal = 0.0
    for item in state.get("customCosts", []):
        kind = item.get("kind", "lump_sum")
        rate = float(item.get("rate", 0.0))
        if kind == "per_sqm":
            customCostTotal += rate * totalCFA
        elif kind == "per_car_conv":
            customCostTotal += rate * totalConvCars
        elif kind == "per_car_auto":
            customCostTotal += rate * totalAutoCars
        else:  # lump_sum
            customCostTotal += rate

    capexTotal = (
        costMain + costParkConv + costParkAuto + greenCost +
        costConvPerCar + costAutoPerCar + costOpenLotPerCar + customCostTotal
    )
    budgetOk = capexTotal <= float(state["budget"]) if float(state["budget"]) > 0 else True

    # DE ratios
    deNSA_GFA = (nsa / gfa) if gfa > 0 else 0.0
    deNSA_CFA = (nsa / totalCFA) if totalCFA > 0 else 0.0
    deGFA_CFA = (gfa / totalCFA) if totalCFA > 0 else 0.0
    deNLA_GFA = (nla / gfa) if gfa > 0 else 0.0

    return Derived(
        maxGFA=maxGFA, farCounted=farCounted, farOk=farOk,
        mainCFA_AG=mainCFA_AG, mainCFA_BG=mainCFA_BG, parkConCFA_AG=parkConCFA_AG, parkConCFA_BG=parkConCFA_BG,
        parkAutoCFA_AG=parkAutoCFA_AG, parkAutoCFA_BG=parkAutoCFA_BG,
        mainCFA=mainCFA, parkConCFA=parkConCFA, parkAutoCFA=parkAutoCFA, totalCFA=totalCFA, gfa=gfa,
        estHeight=estHeight, heightOk=heightOk,
        convCarsPerFloor=convCarsPerFloor, autoCarsPerFloor=autoCarsPerFloor,
        totalConvCars=totalConvCars, totalAutoCars=totalAutoCars, openLotCars=openLotCars,
        totalCars=totalCars, disabledCars=disabledCars,
        publicArea=publicArea, bohArea=bohArea, serviceArea=serviceArea, nsa=nsa, nla=nla,
        deNSA_GFA=deNSA_GFA, deNSA_CFA=deNSA_CFA, deGFA_CFA=deGFA_CFA, deNLA_GFA=deNLA_GFA,
        costMain=costMain, costParkConv=costParkConv, co
