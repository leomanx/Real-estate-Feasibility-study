import math
import io
import json
import csv
import sys
import argparse
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple

# Optional deps (no hard fail): Streamlit / Pandas
try:
    import streamlit as st  # type: ignore
except Exception:
    st = None  # CLI-only fallback

try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None

# ============================================================
# Helpers (no matplotlib; render with SVG or tables)
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
    convCarsPerFloor = int((parkConPlate // max(1.0, effAreaConCar)))
    autoCarsPerFloor = int((parkAutoPlate // max(1.0, effAreaAutoCar)))
    totalConvCars = convCarsPerFloor * int(parkingConAG + parkingConBG)
    totalAutoCars = autoCarsPerFloor * int(parkingAutoAG + parkingAutoBG)

    openLotArea = float(state["openLotArea"]) ; openLotCars = int((openLotArea // max(1.0, effAreaOpenCar)))

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
        costMain=costMain, costParkConv=costParkConv, costParkAuto=costParkAuto, greenCost=greenCost,
        costConvPerCar=costConvPerCar, costAutoPerCar=costAutoPerCar, costOpenLotPerCar=costOpenLotPerCar,
        customCostTotal=customCostTotal, capexTotal=capexTotal, budgetOk=budgetOk,
        openSpaceArea=openSpaceArea, greenArea=greenArea, effAreaOpenCar=effAreaOpenCar,
    )


# ============================================================
# CLI Printing Utilities (no Streamlit)
# ============================================================

def print_summary(state: Dict[str, Any], D: Derived) -> None:
    print("\n==== SUMMARY (Compact) ====")
    print(f"Max GFA:        {nf(D.maxGFA)} m²")
    print(f"GFA (actual):   {nf(D.gfa)} m²   [{'OK' if D.farOk else 'EXCEEDS'}]")
    print(f"Total CFA:      {nf(D.totalCFA)} m²")
    print(f"NSA/GFA:        {D.deNSA_GFA:.3f}   NLA/GFA: {D.deNLA_GFA:.3f}")
    print(f"Height (m):     {nf(D.estHeight)}   [{'OK' if D.heightOk else 'OVER'}]")
    print(f"Budget (฿):     {nf(state['budget'])}   Total CAPEX: {nf(D.capexTotal)}   [{'OK' if D.budgetOk else 'OVER'}]")

    print("\n-- Zoning --")
    if abs(D.farCounted - D.gfa) > 1e-6:
        print(f"FAR-counted (legal): {nf(D.farCounted)} m²")
    print(f"Open Space: {nf(D.openSpaceArea)} m²   Green: {nf(D.greenArea)} m²")

    print("\n-- Areas --")
    print(f"Main CFA (AG/BG): {nf(D.mainCFA_AG)} / {nf(D.mainCFA_BG)} m²")
    print(f"Park CFA Conv/Auto: {nf(D.parkConCFA)} / {nf(D.parkAutoCFA)} m²")

    print("\n-- Parking --")
    print(f"Cars/Floor Conv/Auto: {D.convCarsPerFloor} / {D.autoCarsPerFloor}")
    print(f"Totals Conv/Auto/Open-lot/All: {D.totalConvCars} / {D.totalAutoCars} / {D.openLotCars} / {D.totalCars}")
    print(f"Disabled Spaces (calc): {D.disabledCars}")

    print("\n-- CAPEX (฿) --")
    print(f"Main: {nf(D.costMain)}  | Park Conv: {nf(D.costParkConv)}  | Park Auto: {nf(D.costParkAuto)}")
    print(f"Open-lot (/car): {nf(D.costOpenLotPerCar)}  | Conv Equip (/car): {nf(D.costConvPerCar)}  | Auto Mech (/car): {nf(D.costAutoPerCar)}")
    print(f"Green: {nf(D.greenCost)}  | Custom: {nf(D.customCostTotal)}")
    print(f"TOTAL CAPEX: {nf(D.capexTotal)}  -->  {'OK' if D.budgetOk else 'OVER BUDGET'}")


def export_csv(state: Dict[str, Any], path: str) -> None:
    with open(path, "wb") as f:
        f.write(create_csv_from_dict(state))


def import_csv(path: str) -> Dict[str, Any]:
    with open(path, "rb") as f:
        return parse_csv_to_state(f.read())


# ============================================================
# Tests (ported)
# ============================================================

def run_tests() -> Tuple[int, int]:
    """Return (passed, total). Print each case."""
    print("\n==== TESTS ====")
    passed = 0
    total = 0

    def check(name: str, actual, expected) -> None:
        nonlocal passed, total
        total += 1
        ok = (actual is True) if isinstance(expected, bool) else (actual == expected)
        mark = "✅" if ok else "❌"
        print(f"{mark} {name} — actual: {actual} expected: {expected}")
        if ok:
            passed += 1

    # Base scenario derived
    s = DEFAULT_SCENARIO.copy()
    D = compute(s)

    # Original cases
    check("calcDisabledParking(0)", calc_disabled_parking(0), 0)
    check("calcDisabledParking(50)", calc_disabled_parking(50), 2)
    check("calcDisabledParking(51)", calc_disabled_parking(51), 3)
    check("calcDisabledParking(100)", calc_disabled_parking(100), 3)
    check("calcDisabledParking(101)", calc_disabled_parking(101), 4)
    check("calcDisabledParking(250)", calc_disabled_parking(250), 5)

    far_expected = (
        (D.mainCFA_AG + (D.mainCFA_BG if s["countBasementInFAR"] else 0.0)) +
        ((D.parkConCFA_AG + (D.parkConCFA_BG if s["countBasementInFAR"] else 0.0)) if s["countParkingInFAR"] else 0.0)
    )
    check("FAR-counted (expected)", D.farCounted, far_expected)
    gfa_expected = ((D.mainCFA_AG + D.mainCFA_BG) + (D.parkConCFA_AG + D.parkConCFA_BG))
    check("GFA excludes auto parking", abs(D.gfa - gfa_expected) < 1e-6, True)
    check("0 ≤ GFA/CFA ≤ 1", 0.0 <= D.deGFA_CFA <= 1.0, True)
    check("0 ≤ NSA/GFA ≤ 1", 0.0 <= D.deNSA_GFA <= 1.0, True)
    check("0 ≤ NSA/CFA ≤ 1", 0.0 <= D.deNSA_CFA <= 1.0, True)
    check("0 ≤ NLA/GFA ≤ 1", 0.0 <= D.deNLA_GFA <= 1.0, True)

    # Additional tests
    # 1) FAR OK when GFA <= maxGFA, force exceed by lowering FAR
    s2 = DEFAULT_SCENARIO.copy()
    s2["far"] = 1.0  # lower FAR -> lower maxGFA, likely exceed
    D2 = compute(s2)
    check("FAR check uses GFA (could exceed)", D2.farOk, D2.gfa <= D2.maxGFA)

    # 2) Height check: if maxHeight very low, should fail
    s3 = DEFAULT_SCENARIO.copy()
    s3["maxHeight"] = 10.0
    D3 = compute(s3)
    check("Height check", D3.heightOk, D3.estHeight <= s3["maxHeight"])

    # 3) Budget check: set very small budget -> over
    s4 = DEFAULT_SCENARIO.copy()
    s4["budget"] = 1.0
    D4 = compute(s4)
    check("Budget check", D4.budgetOk, False)

    # 4) Open-lot cars rounding floor
    s5 = DEFAULT_SCENARIO.copy()
    s5["openLotArea"] = 49.9
    s5["openLotBay"] = 25.0
    s5["openLotCircPct"] = 0.0
    D5 = compute(s5)
    check("Open-lot cars floor", D5.openLotCars, 1)  # 49.9/25 -> 1 (floor)

    # 5) Per-floor car calc
    s6 = DEFAULT_SCENARIO.copy()
    s6["parkingConPlate"] = 100.0
    s6["bayConv"] = 25.0
    s6["circConvPct"] = 0.0
    D6 = compute(s6)
    check("Conv cars per floor", D6.convCarsPerFloor, 4)

    print(f"\nPassed {passed}/{total} tests.")
    return passed, total


# ============================================================
# Streamlit UI (no matplotlib) — compact
# ============================================================

def _site_viz_svg(site_area: float, osr: float, green_area: float) -> str:
    # Draw nested squares proportional to OSR and green ratio.
    osr_ratio = clamp(osr / 100.0, 0.0, 1.0)
    green_ratio = 0.0
    if site_area * osr_ratio > 0:
        green_ratio = clamp(green_area / (site_area * osr_ratio), 0.0, 1.0)
    W, H, P = 420, 260, 16
    siteW, siteH = W - 2 * P, H - 2 * P
    import math as _m
    osrW = siteW * (_m.sqrt(osr_ratio))
    osrH = siteH * (_m.sqrt(osr_ratio))
    greenW = osrW * (_m.sqrt(green_ratio))
    greenH = osrH * (_m.sqrt(green_ratio))
    cx, cy = W/2, H/2
    return f"""
    <svg viewBox='0 0 {W} {H}' width='100%'>
      <rect x='0' y='0' width='{W}' height='{H}' rx='12' fill='#f8fafc' />
      <rect x='{P}' y='{P}' width='{siteW}' height='{siteH}' fill='#fff' stroke='#CBD5E1' stroke-width='2'/>
      <rect x='{cx - osrW/2}' y='{cy - osrH/2}' width='{osrW}' height='{osrH}' fill='#dcfce7' stroke='#86efac'/>
      <rect x='{cx - greenW/2}' y='{cy - greenH/2}' width='{greenW}' height='{greenH}' fill='#86efac' stroke='#059669'/>
      <g font-size='10' fill='#334155'>
        <text x='{P + 6}' y='{P + 14}'>Site</text>
        <text x='{cx - osrW/2 + 6}' y='{cy - osrH/2 + 14}'>Open Space</text>
        <text x='{cx - greenW/2 + 6}' y='{cy - greenH/2 + 14}'>Green</text>
      </g>
    </svg>
    """


def run_streamlit_app() -> None:
    st.set_page_config(page_title="Feasibility Calculator (Streamlit)", page_icon="🏗️", layout="wide")
    st.title("🏗️ Feasibility Calculator — Compact Edition (No Matplotlib)")

    # State
    if "state" not in st.session_state:
        st.session_state.state = DEFAULT_SCENARIO.copy()
    s = st.session_state.state

    with st.sidebar:
        st.header("Scenario & Presets")
        preset = st.selectbox("Preset", PRESETS, index=0)
        if st.button("Apply Preset"):
            p = RULES["presets"][preset]
            s["bType"] = p["bType"]
            s["osr"] = float(p["osr"])
            s["greenPctOfOSR"] = float(p["greenPct"])
            s["countParkingInFAR"] = bool(p["countParkingInFAR"])
            s["countBasementInFAR"] = bool(p["countBasementInFAR"])

        st.divider()
        st.subheader("Import / Export")
        st.download_button("⬇️ Export Scenario CSV", data=create_csv_from_dict(s), file_name="scenario.csv", mime="text/csv")
        up = st.file_uploader("⬆️ Import Scenario CSV", type=["csv"], accept_multiple_files=False)
        if up is not None:
            try:
                new_state = parse_csv_to_state(up.getvalue())
                merged = DEFAULT_SCENARIO.copy()
                for k in DEFAULT_SCENARIO.keys():
                    if k in new_state:
                        merged[k] = new_state[k]
                if isinstance(new_state.get("customCosts"), list):
                    merged["customCosts"] = new_state["customCosts"]
                st.session_state.state = merged
                s = merged
                st.success("Scenario imported.")
            except Exception as e:
                st.error(f"Import failed: {e}")

        st.header("Inputs")
        bcol1, bcol2 = st.columns(2)
        with bcol1:
            s["siteArea"] = st.number_input("Site Area (m²)", min_value=0.0, value=float(s["siteArea"]))
            fmin, fmax = RULES["base"]["farRange"]
            s["far"] = st.number_input("FAR (1–10)", min_value=fmin, max_value=fmax, step=0.1, value=float(s["far"]))
            s["bType"] = st.selectbox("Building Type", BUILDING_TYPES, index=BUILDING_TYPES.index(s["bType"]))
            s["osr"] = st.number_input("OSR (%)", min_value=0.0, max_value=100.0, value=float(s["osr"]))
            s["greenPctOfOSR"] = st.number_input("Green (% of OSR)", min_value=0.0, max_value=100.0, value=float(s["greenPctOfOSR"]))
        with bcol2:
            s["mainFloorsAG"] = st.number_input("Main Floors (AG)", min_value=0.0, value=float(s["mainFloorsAG"]))
            s["mainFloorsBG"] = st.number_input("Main Floors (BG)", min_value=0.0, value=float(s["mainFloorsBG"]))
            s["parkingConFloorsAG"] = st.number_input("Park Conv (AG)", min_value=0.0, value=float(s["parkingConFloorsAG"]))
            s["parkingConFloorsBG"] = st.number_input("Park Conv (BG)", min_value=0.0, value=float(s["parkingConFloorsBG"]))
            s["parkingAutoFloorsAG"] = st.number_input("Auto Park (AG)", min_value=0.0, value=float(s["parkingAutoFloorsAG"]))
            s["parkingAutoFloorsBG"] = st.number_input("Auto Park (BG)", min_value=0.0, value=float(s["parkingAutoFloorsBG"]))
            s["ftf"] = st.number_input("F2F (m)", min_value=0.0, step=0.1, value=float(s["ftf"]))
            s["maxHeight"] = st.number_input("Max Height (m)", min_value=0.0, value=float(s["maxHeight"]))

        st.subheader("Plates & Parking Efficiency")
        s["mainFloorPlate"] = st.number_input("Main Plate (m²)", min_value=0.0, value=float(s["mainFloorPlate"]))
        s["parkingConPlate"] = st.number_input("Park Plate (Conv) (m²)", min_value=0.0, value=float(s["parkingConPlate"]))
        s["parkingAutoPlate"] = st.number_input("Park Plate (Auto) (m²)", min_value=0.0, value=float(s["parkingAutoPlate"]))

        s["bayConv"] = st.number_input("Conv Bay (m²) — net", min_value=1.0, value=float(s["bayConv"]))
        s["circConvPct"] = st.slider("Conv Circ (%)", min_value=0, max_value=100, value=int(float(s["circConvPct"]) * 100)) / 100.0

        s["bayAuto"] = st.number_input("Auto Bay (m²) — net", min_value=1.0, value=float(s["bayAuto"]))
        s["circAutoPct"] = st.slider("Auto Circ (%)", min_value=0, max_value=100, value=int(float(s["circAutoPct"]) * 100)) / 100.0

        s["openLotArea"] = st.number_input("Open-lot Area (m²)", min_value=0.0, value=float(s["openLotArea"]))
        s["openLotBay"] = st.number_input("Open-lot Bay (m²/คัน)", min_value=1.0, value=float(s["openLotBay"]))
        s["openLotCircPct"] = st.slider("Open-lot Circ (%)", min_value=0, max_value=100, value=int(float(s["openLotCircPct"]) * 100)) / 100.0

        st.subheader("FAR Toggles")
        s["countParkingInFAR"] = st.checkbox("Count Conventional Parking in FAR", value=bool(s["countParkingInFAR"]))
        s["countBasementInFAR"] = st.checkbox("Count Basement in FAR", value=bool(s["countBasementInFAR"]))

        st.subheader("Costs & Budget")
        s["costMainPerSqm"] = st.number_input("Architecture (฿/m²)", min_value=0.0, value=float(s["costMainPerSqm"]))
        s["costParkConvPerSqm"] = st.number_input("Park Conv (฿/m²)", min_value=0.0, value=float(s["costParkConvPerSqm"]))
        s["costParkAutoPerSqm"] = st.number_input("Park Auto (฿/m²)", min_value=0.0, value=float(s["costParkAutoPerSqm"]))
        s["costGreenPerSqm"] = st.number_input("Green (฿/m²)", min_value=0.0, value=float(s["costGreenPerSqm"]))
        s["costConventionalPerCar"] = st.number_input("Conventional (/car)", min_value=0.0, value=float(s["costConventionalPerCar"]))
        s["costAutoPerCar"] = st.number_input("Auto (/car)", min_value=0.0, value=float(s["costAutoPerCar"]))
        s["costOpenLotPerCar"] = st.number_input("Open-lot (/car)", min_value=0.0, value=float(s["costOpenLotPerCar"]))

        s["budget"] = st.number_input("Budget (฿)", min_value=0.0, value=float(s["budget"]))

        st.subheader("Additional Cost Items")
        if pd is not None:
            cc_df = pd.DataFrame(s.get("customCosts", []))
            if cc_df.empty:
                cc_df = pd.DataFrame([{"name": "", "kind": "lump_sum", "rate": 0.0}])
            edited = st.data_editor(
                cc_df,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
            )
            s["customCosts"] = [
                {"name": str(r.get("name", "")).strip(), "kind": r.get("kind", "lump_sum"), "rate": float(r.get("rate", 0.0))}
                for _, r in edited.iterrows() if str(r.get("name", "")).strip() != ""
            ]
        else:
            st.info("Pandas not available — custom costs table disabled.")

    # Compute
    D = compute(s)

    # KPI row
    kp1, kp2, kp3, kp4, kp5, kp6 = st.columns(6)
    kp1.metric("Max GFA", nf(D.maxGFA))
    kp2.metric("GFA (actual)", nf(D.gfa), delta=("OK" if D.farOk else "Exceeds"))
    kp3.metric("Total CFA", nf(D.totalCFA))
    kp4.metric("NSA/GFA", f"{D.deNSA_GFA:.3f}")
    kp5.metric("NLA/GFA", f"{D.deNLA_GFA:.3f}")
    kp6.metric("Height (m)", nf(D.estHeight), delta=("OK" if D.heightOk else "Over"))

    # Alerts
    a1, a2, a3 = st.columns(3)
    with a1:
        st.success("FAR: OK") if D.farOk else st.error("FAR: Exceeds Max GFA")
    with a2:
        st.success("Height: OK") if D.heightOk else st.error("Height: Over limit")
    with a3:
        st.success("Budget: OK") if D.budgetOk else st.error("Budget: Over")

    # Tabs
    summary_tab, details_tab, charts_tab, tests_tab = st.tabs(["Summary", "Details", "Charts", "Tests"])

    with summary_tab:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.subheader("Zoning")
            st.write(f"**Max GFA:** {nf(D.maxGFA)} m²")
            st.write(f"**GFA (actual):** {nf(D.gfa)} m²")
            if abs(D.farCounted - D.gfa) > 1e-6:
                st.caption(f"Area counted by law (FAR): {nf(D.farCounted)} m²")
            st.write(f"**Open Space:** {nf(D.openSpaceArea)} m²")
            st.write(f"**Green Area:** {nf(D.greenArea)} m²")
        with c2:
            st.subheader("Areas")
            st.write(f"Main CFA (AG): {nf(D.mainCFA_AG)} m²")
            st.write(f"Main CFA (BG): {nf(D.mainCFA_BG)} m²")
            st.write(f"Parking CFA (Conv): {nf(D.parkConCFA)} m²")
            st.write(f"Parking CFA (Auto): {nf(D.parkAutoCFA)} m²")
            st.write(f"**Total CFA:** {nf(D.totalCFA)} m²")
        with c3:
            st.subheader("Parking")
            st.write(f"Cars/Floor (Conv): {D.convCarsPerFloor}")
            st.write(f"Cars/Floor (Auto): {D.autoCarsPerFloor}")
            st.write(f"Open-lot Cars: {D.openLotCars}")
            st.write(f"Total Cars (Conv/Auto): {D.totalConvCars}/{D.totalAutoCars}")
            st.write(f"**Total Cars:** {D.totalCars}")
            st.caption(f"Disabled Spaces (calc): {D.disabledCars}")

        st.divider()
        c4, c5 = st.columns([1, 1])
        with c4:
            st.subheader("CAPEX (฿)")
            st.write(f"Main (m²): **{nf(D.costMain)}**")
            st.write(f"Park Conv (m²): **{nf(D.costParkConv)}**")
            st.write(f"Park Auto (m²): **{nf(D.costParkAuto)}**")
            st.write(f"Open-lot (/car): **{nf(D.costOpenLotPerCar)}**")
            st.write(f"Conv Equip (/car): **{nf(D.costConvPerCar)}**")
            st.write(f"Auto Mech (/car): **{nf(D.costAutoPerCar)}**")
            st.write(f"Green (m²): **{nf(D.greenCost)}**")
            if float(D.customCostTotal) > 0:
                st.write(f"Custom: **{nf(D.customCostTotal)}**")
            st.write(f"**Total CAPEX:** **{nf(D.capexTotal)}**")
        with c5:
            st.subheader("Site Visualization")
            svg = _site_viz_svg(float(s["siteArea"]), float(s["osr"]), D.greenArea)
            st.markdown(svg, unsafe_allow_html=True)

    with details_tab:
        if pd is not None:
            st.subheader("Design Efficiency Ratios")
            df_rat = pd.DataFrame({"Metric": ["NSA/GFA", "NSA/CFA", "GFA/CFA", "NLA/GFA"],
                                   "Value": [D.deNSA_GFA, D.deNSA_CFA, D.deGFA_CFA, D.deNLA_GFA]})
            st.dataframe(df_rat.style.format({"Value": "{:.3f}"}), use_container_width=True)

            st.subheader("Breakdown Tables")
            a1, a2 = st.columns(2)
            with a1:
                df_area = pd.DataFrame({
                    "Area": ["Main CFA (AG)", "Main CFA (BG)", "Park Conv (AG)", "Park Conv (BG)",
                              "Park Auto (AG)", "Park Auto (BG)", "GFA (actual)", "Total CFA"],
                    "m²": [D.mainCFA_AG, D.mainCFA_BG, D.parkConCFA_AG, D.parkConCFA_BG,
                            D.parkAutoCFA_AG, D.parkAutoCFA_BG, D.gfa, D.totalCFA],
                })
                st.dataframe(df_area, use_container_width=True)
            with a2:
                df_capex = pd.DataFrame({
                    "Item": ["Main (m²)", "Park Conv (m²)", "Park Auto (m²)", "Open-lot (/car)",
                             "Conv Equip (/car)", "Auto Mech (/car)", "Green (m²)", "Custom", "Total"],
                    "฿": [D.costMain, D.costParkConv, D.costParkAuto, D.costOpenLotPerCar,
                          D.costConvPerCar, D.costAutoPerCar, D.greenCost, D.customCostTotal, D.capexTotal],
                })
                st.dataframe(df_capex, use_container_width=True)
        else:
            st.info("Pandas not available — details tables disabled.")

    with charts_tab:
        st.subheader("CAPEX Breakdown (Bar)")
        if pd is not None:
            labels = [
                "Main (m²)", "Park Conv (m²)", "Park Auto (m²)",
                "Open-lot (/car)", "Conv Equip (/car)", "Auto Mech (/car)", "Green (m²)", "Custom"
            ]
            values = [
                D.costMain, D.costParkConv, D.costParkAuto,
                D.costOpenLotPerCar, D.costConvPerCar, D.costAutoPerCar, D.greenCost, D.customCostTotal
            ]
            df_bar = pd.DataFrame({"Item": labels, "฿": values}).set_index("Item")
            st.bar_chart(df_bar)
        else:
            st.info("Pandas not available — chart disabled.")

    with tests_tab:
        if pd is not None:
            tests = [
                ("calcDisabledParking(0)", calc_disabled_parking(0), 0),
                ("calcDisabledParking(50)", calc_disabled_parking(50), 2),
                ("calcDisabledParking(51)", calc_disabled_parking(51), 3),
                ("calcDisabledParking(100)", calc_disabled_parking(100), 3),
                ("calcDisabledParking(101)", calc_disabled_parking(101), 4),
                ("calcDisabledParking(250)", calc_disabled_parking(250), 5),
                ("FAR-counted (expected)",
                 D.farCounted,
                 (D.mainCFA_AG + (D.mainCFA_BG if s["countBasementInFAR"] else 0.0)) +
                 ((D.parkConCFA_AG + (D.parkConCFA_BG if s["countBasementInFAR"] else 0.0)) if s["countParkingInFAR"] else 0.0)),
                ("GFA excludes auto parking", abs(D.gfa - ((D.mainCFA_AG + D.mainCFA_BG) + (D.parkConCFA_AG + D.parkConCFA_BG))) < 1e-6, True),
                ("0 ≤ GFA/CFA ≤ 1", 0.0 <= D.deGFA_CFA <= 1.0, True),
                ("0 ≤ NSA/GFA ≤ 1", 0.0 <= D.deNSA_GFA <= 1.0, True),
                ("0 ≤ NSA/CFA ≤ 1", 0.0 <= D.deNSA_CFA <= 1.0, True),
                ("0 ≤ NLA/GFA ≤ 1", 0.0 <= D.deNLA_GFA <= 1.0, True),
            ]
            rows = []
            for name, actual, expected in tests:
                ok = (actual is True) if isinstance(expected, bool) else (actual == expected)
                rows.append({"Test": name, "Actual": actual, "Expected": expected, "Pass": "✅" if ok else "❌"})
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("Pandas not available — tests table disabled.")

    st.caption("Streamlit version uses no matplotlib — safe for minimal runtimes.")


# ============================================================
# CLI Entrypoint
# ============================================================

def apply_preset(state: Dict[str, Any], preset: str) -> Dict[str, Any]:
    if preset not in RULES["presets"]:
        return state
    p = RULES["presets"][preset]
    state = state.copy()
    state["bType"] = p["bType"]
    state["osr"] = float(p["osr"])
    state["greenPctOfOSR"] = float(p["greenPct"])
    state["countParkingInFAR"] = bool(p["countParkingInFAR"])
    state["countBasementInFAR"] = bool(p["countBasementInFAR"])
    return state


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Feasibility Calculator (CLI / Streamlit)")
    parser.add_argument("--import-csv", dest="import_csv_path", help="Path to scenario CSV to import")
    parser.add_argument("--export-csv", dest="export_csv_path", help="Path to write current scenario CSV")
    parser.add_argument("--preset", choices=PRESETS, help="Apply a preset before computing")
    parser.add_argument("--print-json", action="store_true", help="Print scenario JSON")
    parser.add_argument("--tests", action="store_true", help="Run test suite and exit")
    parser.add_argument("--streamlit", action="store_true", help="Run Streamlit UI (if available)")

    args = parser.parse_args(argv)

    if args.tests:
        passed, total = run_tests()
        return 0 if passed == total else 1

    if args.streamlit and st is not None:
        # Running inside Streamlit context: ignore CLI flow
        run_streamlit_app()
        return 0

    state = DEFAULT_SCENARIO.copy()

    if args.import_csv_path:
        try:
            loaded = import_csv(args.import_csv_path)
            merged = DEFAULT_SCENARIO.copy()
            for k in DEFAULT_SCENARIO.keys():
                if k in loaded:
                    merged[k] = loaded[k]
            if isinstance(loaded.get("customCosts"), list):
                merged["customCosts"] = loaded["customCosts"]
            state = merged
        except Exception as e:
            print(f"Failed to import CSV: {e}", file=sys.stderr)
            return 2

    if args.preset:
        state = apply_preset(state, args.preset)

    if args.export_csv_path:
        try:
            export_csv(state, args.export_csv_path)
            print(f"Exported scenario to {args.export_csv_path}")
        except Exception as e:
            print(f"Failed to export CSV: {e}", file=sys.stderr)
            return 3

    if args.print_json:
        print(json.dumps(state, indent=2, ensure_ascii=False))

    # Compute & print summary (CLI)
    D = compute(state)
    print_summary(state, D)
    return 0


if __name__ == "__main__":
    # If executed directly, prefer CLI. For Streamlit Cloud, set the entrypoint to run this file
    # and pass --streamlit or simply let Streamlit import and execute run_streamlit_app().
    if st is not None and hasattr(st, "_is_running_with_streamlit"):
        # When executed via `streamlit run app.py`, Streamlit sets runtime flags.
        run_streamlit_app()
    else:
        sys.exit(main(sys.argv[1:]))
