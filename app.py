import math
import io
import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Any

import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

# ============================================================
# Helpers
# ============================================================

def nf(x, digits=2):
    try:
        return f"{float(x):,.{digits}f}"
    except Exception:
        return "–"


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def create_csv_from_dict(d: Dict[str, Any]) -> bytes:
    rows = [(k, json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in d.items()]
    df = pd.DataFrame(rows, columns=["Field", "Value"])
    return df.to_csv(index=False).encode("utf-8")


def parse_csv_to_state(file_bytes: bytes) -> Dict[str, Any]:
    text = file_bytes.decode("utf-8")
    df = pd.read_csv(io.StringIO(text))
    state = {}
    for _, row in df.iterrows():
        k = str(row["Field"]).strip()
        v_raw = str(row["Value"]).strip()
        # JSON first
        if (v_raw.startswith("{") and v_raw.endswith("}")) or (v_raw.startswith("[") and v_raw.endswith("]")):
            try:
                state[k] = json.loads(v_raw)
                continue
            except Exception:
                pass
        # booleans
        if v_raw.lower() == "true":
            state[k] = True
            continue
        if v_raw.lower() == "false":
            state[k] = False
            continue
        # numbers
        try:
            if v_raw.replace(".", "", 1).lstrip("-+").isdigit():
                state[k] = float(v_raw)
                continue
        except Exception:
            pass
        # fallback as string
        state[k] = v_raw
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
    return v if v is not None else 15


def suggested_green_pct(btype: str) -> float:
    v = RULES["building"].get(btype, {}).get("greenPctOfOSR")
    return v if v is not None else 40


# ============================================================
# Default Scenario
# ============================================================
DEFAULT_SCENARIO = {
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
        costMain=costMain, costParkConv=costParkConv, costParkAuto=costParkAuto, greenCost=greenCost,
        costConvPerCar=costConvPerCar, costAutoPerCar=costAutoPerCar, costOpenLotPerCar=costOpenLotPerCar,
        customCostTotal=customCostTotal, capexTotal=capexTotal, budgetOk=budgetOk,
        openSpaceArea=openSpaceArea, greenArea=greenArea, effAreaOpenCar=effAreaOpenCar,
    )


# ============================================================
# UI Components
# ============================================================

def site_viz(site_area: float, osr: float, green_area: float):
    W, H, P = 6, 3.6, 0.2  # inches for compact figure
    fig, ax = plt.subplots(figsize=(W, H))
    ax.set_axis_off()

    # draw site box
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, fill=False, lw=2, edgecolor="#94a3b8"))

    osr_ratio = clamp(osr / 100.0, 0.0, 1.0)
    green_ratio = 0.0
    if site_area * osr_ratio > 0:
        green_ratio = clamp(green_area / (site_area * osr_ratio), 0.0, 1.0)

    # scale as squares inside square for visual proportion
    osr_w = osr_h = math.sqrt(osr_ratio)
    green_w = green_h = math.sqrt(green_ratio) * osr_w

    # center them
    cx, cy = 0.5, 0.5
    ax.add_patch(plt.Rectangle((cx - osr_w/2, cy - osr_h/2), osr_w, osr_h, facecolor="#dcfce7", edgecolor="#86efac"))
    ax.add_patch(plt.Rectangle((cx - green_w/2, cy - green_h/2), green_w, green_h, facecolor="#86efac", edgecolor="#059669"))

    ax.text(0.02, 0.98, "Site", ha="left", va="top", fontsize=9)
    ax.text(cx - osr_w/2 + 0.01, cy + osr_h/2 - 0.02, "Open Space", ha="left", va="top", fontsize=8)
    ax.text(cx - green_w/2 + 0.01, cy + green_h/2 - 0.02, "Green", ha="left", va="top", fontsize=8)

    st.pyplot(fig, clear_figure=True)


# ============================================================
# Streamlit App
# ============================================================
st.set_page_config(
    page_title="Feasibility Calculator (Streamlit)", page_icon="🏗️", layout="wide"
)

st.title("🏗️ Feasibility Calculator — Compact Streamlit Edition")

with st.sidebar:
    st.header("Scenario & Presets")
    preset = st.selectbox("Preset", PRESETS, index=0)

    # state store
    if "state" not in st.session_state:
        st.session_state.state = DEFAULT_SCENARIO.copy()

    s = st.session_state.state

    # Apply preset minimal effects (does not lock UI; just suggests defaults)
    if st.button("Apply Preset"):
        p = RULES["presets"][preset]
        s["bType"] = p["bType"]
        s["osr"] = p["osr"]
        s["greenPctOfOSR"] = p["greenPct"]
        s["countParkingInFAR"] = p["countParkingInFAR"]
        s["countBasementInFAR"] = p["countBasementInFAR"]

    st.divider()
    # Export / Import
    st.subheader("Import / Export")
    if st.download_button(
        "⬇️ Export Scenario CSV", data=create_csv_from_dict(s), file_name="scenario.csv", mime="text/csv"
    ):
        pass

    up = st.file_uploader("⬆️ Import Scenario CSV", type=["csv"], accept_multiple_files=False)
    if up is not None:
        try:
            new_state = parse_csv_to_state(up.getvalue())
            # keep only known keys; merge customCosts safely
            merged = DEFAULT_SCENARIO.copy()
            merged.update({k: new_state.get(k, v) for k, v in DEFAULT_SCENARIO.items()})
            # if uploaded has customCosts, adopt
            if isinstance(new_state.get("customCosts"), list):
                merged["customCosts"] = new_state["customCosts"]
            st.session_state.state = merged
            st.success("Scenario imported.")
        except Exception as e:
            st.error(f"Import failed: {e}")

st.write("")

# ======= Sidebar Inputs (grouped & compact) =======
with st.sidebar:
    st.header("Inputs")
    bcol1, bcol2 = st.columns(2)
    with bcol1:
        s["siteArea"] = st.number_input("Site Area (m²)", min_value=0.0, value=float(s["siteArea"]))
        far_min, far_max = RULES["base"]["farRange"]
        s["far"] = st.number_input("FAR (1–10)", min_value=far_min, max_value=far_max, step=0.1, value=float(s["far"]))
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
    # show as editable table
    cc_df = pd.DataFrame(s.get("customCosts", []))
    if cc_df.empty:
        cc_df = pd.DataFrame([
            {"name": "", "kind": "lump_sum", "rate": 0.0}
        ])
    edited = st.data_editor(
        cc_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "name": st.column_config.TextColumn("Name"),
            "kind": st.column_config.SelectboxColumn("Kind", options=["per_sqm", "per_car_conv", "per_car_auto", "lump_sum"]),
            "rate": st.column_config.NumberColumn("Rate", step=100.0, format="%f"),
        },
        hide_index=True,
    )
    # keep only valid rows
    s["customCosts"] = [
        {"name": str(r.get("name", "")).strip(), "kind": r.get("kind", "lump_sum"), "rate": float(r.get("rate", 0.0))}
        for _, r in edited.iterrows() if str(r.get("name", "")).strip() != ""
    ]

# ======= Compute =======
D = compute(st.session_state.state)

# ======= Summary KPIs (Top) =======
kp1, kp2, kp3, kp4, kp5, kp6 = st.columns(6)
kp1.metric("Max GFA", nf(D.maxGFA))
kp2.metric("GFA (actual)", nf(D.gfa), delta=("OK" if D.farOk else "Exceeds"))
kp3.metric("Total CFA", nf(D.totalCFA))
kp4.metric("NSA/GFA", f"{D.deNSA_GFA:.3f}")
kp5.metric("NLA/GFA", f"{D.deNLA_GFA:.3f}")
kp6.metric("Height (m)", nf(D.estHeight), delta=("OK" if D.heightOk else "Over"))

# Compact alerts
alert_cols = st.columns(3)
with alert_cols[0]:
    if not D.farOk:
        st.error("FAR: Exceeds Max GFA")
    else:
        st.success("FAR: OK")
with alert_cols[1]:
    if not D.heightOk:
        st.error("Height: Over limit")
    else:
        st.success("Height: OK")
with alert_cols[2]:
    if not D.budgetOk:
        st.error("Budget: Over")
    else:
        st.success("Budget: OK")

# ======= Tabs for compact layout =======
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
        st.write(f"Parking CFA (Auto): {nf(D.parkAutoCFA)} m²  ")
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
        site_viz(
            site_area=float(s["siteArea"]), osr=float(s["osr"]), green_area=D.greenArea
        )

with details_tab:
    st.subheader("Design Efficiency Ratios")
    st.write(
        pd.DataFrame(
            {
                "Metric": ["NSA/GFA", "NSA/CFA", "GFA/CFA", "NLA/GFA"],
                "Value": [D.deNSA_GFA, D.deNSA_CFA, D.deGFA_CFA, D.deNLA_GFA],
            }
        ).style.format({"Value": "{:.3f}"})
    )

    st.subheader("Breakdown Tables")
    a1, a2 = st.columns(2)
    with a1:
        df_area = pd.DataFrame(
            {
                "Area": [
                    "Main CFA (AG)", "Main CFA (BG)", "Park Conv (AG)", "Park Conv (BG)",
                    "Park Auto (AG)", "Park Auto (BG)", "GFA (actual)", "Total CFA",
                ],
                "m²": [
                    D.mainCFA_AG, D.mainCFA_BG, D.parkConCFA_AG, D.parkConCFA_BG,
                    D.parkAutoCFA_AG, D.parkAutoCFA_BG, D.gfa, D.totalCFA,
                ],
            }
        )
        st.dataframe(df_area, use_container_width=True)

    with a2:
        df_capex = pd.DataFrame(
            {
                "Item": [
                    "Main (m²)", "Park Conv (m²)", "Park Auto (m²)", "Open-lot (/car)",
                    "Conv Equip (/car)", "Auto Mech (/car)", "Green (m²)", "Custom", "Total"
                ],
                "฿": [
                    D.costMain, D.costParkConv, D.costParkAuto, D.costOpenLotPerCar,
                    D.costConvPerCar, D.costAutoPerCar, D.greenCost, D.customCostTotal, D.capexTotal,
                ],
            }
        )
        st.dataframe(df_capex, use_container_width=True)

with charts_tab:
    st.subheader("CAPEX Breakdown Pie")
    labels = [
        "Main (m²)", "Park Conv (m²)", "Park Auto (m²)",
        "Open-lot (/car)", "Conv Equip (/car)", "Auto Mech (/car)", "Green (m²)", "Custom"
    ]

    values = [
        D.costMain, D.costParkConv, D.costParkAuto,
        D.costOpenLotPerCar, D.costConvPerCar, D.costAutoPerCar, D.greenCost, D.customCostTotal
    ]

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.pie(values, labels=labels, autopct=lambda p: f"{p:.1f}%" if p > 2 else "")
    ax.axis('equal')
    st.pyplot(fig, clear_figure=True)

with tests_tab:
    st.subheader("Sanity Checks")
    tests = [
        ("calcDisabledParking(0)", calc_disabled_parking(0), 0),
        ("calcDisabledParking(50)", calc_disabled_parking(50), 2),
        ("calcDisabledParking(51)", calc_disabled_parking(51), 3),
        ("calcDisabledParking(100)", calc_disabled_parking(100), 3),
        ("calcDisabledParking(101)", calc_disabled_parking(101), 4),
        ("calcDisabledParking(250)", calc_disabled_parking(250), 5),
        # FAR-counted expected
        (
            "FAR-counted (expected)",
            D.farCounted,
            (D.mainCFA_AG + (D.mainCFA_BG if s["countBasementInFAR"] else 0.0)) + (
                (D.parkConCFA_AG + (D.parkConCFA_BG if s["countBasementInFAR"] else 0.0)) if s["countParkingInFAR"] else 0.0
            ),
        ),
        ("GFA excludes auto parking", abs(D.gfa - ((D.mainCFA_AG + D.mainCFA_BG) + (D.parkConCFA_AG + D.parkConCFA_BG))) < 1e-6, True),
        ("0 ≤ GFA/CFA ≤ 1", 0.0 <= D.deGFA_CFA <= 1.0, True),
        ("0 ≤ NSA/GFA ≤ 1", 0.0 <= D.deNSA_GFA <= 1.0, True),
        ("0 ≤ NSA/CFA ≤ 1", 0.0 <= D.deNSA_CFA <= 1.0, True),
        ("0 ≤ NLA/GFA ≤ 1", 0.0 <= D.deNLA_GFA <= 1.0, True),
    ]

    def glyph(ok: bool) -> str:
        return "✅" if ok else "❌"

    rows = []
    for name, actual, expected in tests:
        ok = (actual is True) if isinstance(expected, bool) else (actual == expected)
        rows.append({"Test": name, "Actual": actual, "Expected": expected, "Pass": glyph(ok)})

    st.dataframe(pd.DataFrame(rows), use_container_width=True)

st.caption("Made for compact deploy on Streamlit — summary first, details in tabs, import/export ready.")
