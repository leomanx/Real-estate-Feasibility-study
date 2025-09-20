# -*- coding: utf-8 -*-
import io
import math
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
import matplotlib.pyplot as plt

# =========================
# Helpers
# =========================
def nf(n, digits=2):
    try:
        x = float(n)
    except Exception:
        return "–"
    return f"{x:,.{digits}f}"

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def currency_symbol(c: str):
    return "฿" if c == "THB" else "$"

def create_csv_from_kv(d: Dict[str, Any]) -> str:
    rows = [{"Field": k, "Value": v} for k, v in d.items()]
    df = pd.DataFrame(rows)
    return df.to_csv(index=False)

def parse_csv_to_patch(file_bytes: bytes) -> Dict[str, Any]:
    df = pd.read_csv(io.BytesIO(file_bytes))
    # expect columns: Field, Value
    out: Dict[str, Any] = {}
    for _, r in df.iterrows():
        k = str(r["Field"]).strip()
        v = r["Value"]
        # numeric coercion if possible
        try:
            if isinstance(v, str) and v.strip() == "":
                out[k] = v
            else:
                num = float(v)
                # keep as int if integer-like
                out[k] = int(num) if abs(num - int(num)) < 1e-12 else num
        except Exception:
            out[k] = v
    return out

# Disabled parking rule (exactly as spec)
def calc_disabled_parking(total_cars: int) -> int:
    if total_cars <= 0:
        return 0
    if total_cars <= 50:
        return 2
    if total_cars <= 100:
        return 3
    extra_hundreds = math.ceil((total_cars - 100) / 100)
    return 3 + max(0, extra_hundreds)

# =========================
# Presets / Rules
# =========================
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
        "None": dict(lockOSR=False, lockGreenPct=False, bType="Housing", osr=15, greenPct=40,
                     countParkingInFAR=True, countBasementInFAR=False),
        "TH Condo": dict(lockOSR=True, lockGreenPct=True, bType="Hi-Rise", osr=10, greenPct=50,
                         countParkingInFAR=True, countBasementInFAR=False),
        "TH Hotel": dict(lockOSR=True, lockGreenPct=False, bType="Hotel", osr=10, greenPct=40,
                         countParkingInFAR=True, countBasementInFAR=False),
    }
}

def suggested_osr(btype: str) -> float:
    val = RULES["building"].get(btype, {}).get("minOSR")
    return 15 if val is None else float(val)

def suggested_green_pct(btype: str) -> float:
    val = RULES["building"].get(btype, {}).get("greenPctOfOSR")
    return 40 if val is None else float(val)

# =========================
# Scenario model
# =========================
@dataclass
class CustomCost:
    id: int
    name: str = "Misc."
    kind: str = "lump_sum"   # per_sqm | per_car_conv | per_car_auto | lump_sum
    rate: float = 0.0

@dataclass
class Scenario:
    # Core site & zoning
    siteArea: float = 8000
    far: float = 5
    bType: str = "Housing"
    osr: float = 30
    greenPctOfOSR: float = 40

    # Geometry
    mainFloorsAG: int = 20
    mainFloorsBG: int = 0
    parkingConFloorsAG: int = 3
    parkingConFloorsBG: int = 0
    parkingAutoFloorsAG: int = 0
    parkingAutoFloorsBG: int = 0
    ftf: float = 3.2
    maxHeight: float = 120

    # Plates
    mainFloorPlate: float = 1500
    parkingConPlate: float = 1200
    parkingAutoPlate: float = 800

    # Parking efficiency
    bayConv: float = 25
    circConvPct: float = 0.0  # 0–1
    bayAuto: float = 16
    circAutoPct: float = 0.0  # 0–1

    # Open-lot (not GFA)
    openLotArea: float = 0
    openLotBay: float = 25
    openLotCircPct: float = 0.0  # 0–1

    # Efficiency from GFA
    publicPctOfGFA: float = 10
    nlaPctOfPublic: float = 40
    bohPctOfGFA: float = 8
    servicePctOfGFA: float = 2

    # FAR toggles
    countParkingInFAR: bool = True
    countBasementInFAR: bool = False

    # Cost (coarse)
    costMainPerSqm: float = 30000
    costParkConvPerSqm: float = 18000
    costParkAutoPerSqm: float = 25000
    costGreenPerSqm: float = 4500

    # Budget / currency
    budget: float = 500_000_000
    currency: str = "THB"

    # Add-ons
    customCosts: List[CustomCost] = field(default_factory=list)

def compute(s: Scenario) -> Dict[str, Any]:
    far_min, far_max = RULES["base"]["farRange"]
    far = clamp(s.far, far_min, far_max)
    maxGFA = s.siteArea * far

    # OSR & Green
    openSpaceArea = (s.osr / 100.0) * s.siteArea
    greenArea = (s.greenPctOfOSR / 100.0) * openSpaceArea

    # CFA (structured)
    mainCFA_AG = s.mainFloorsAG * s.mainFloorPlate
    mainCFA_BG = s.mainFloorsBG * s.mainFloorPlate
    parkConCFA_AG = s.parkingConFloorsAG * s.parkingConPlate
    parkConCFA_BG = s.parkingConFloorsBG * s.parkingConPlate
    parkAutoCFA_AG = s.parkingAutoFloorsAG * s.parkingAutoPlate
    parkAutoCFA_BG = s.parkingAutoFloorsBG * s.parkingAutoPlate

    mainCFA = mainCFA_AG + mainCFA_BG
    parkConCFA = parkConCFA_AG + parkConCFA_BG
    parkAutoCFA = parkAutoCFA_AG + parkAutoCFA_BG
    totalCFA = mainCFA + parkConCFA + parkAutoCFA

    # Height check (AG only)
    estHeight = s.ftf * (s.mainFloorsAG + s.parkingConFloorsAG + s.parkingAutoFloorsAG)
    heightOk = estHeight <= s.maxHeight

    # Parking supply
    effAreaConCar = s.bayConv * (1.0 + s.circConvPct)
    effAreaAutoCar = s.bayAuto * (1.0 + s.circAutoPct)
    effAreaOpenCar = s.openLotBay * (1.0 + s.openLotCircPct)

    convCarsPerFloor = math.floor(s.parkingConPlate / max(1, effAreaConCar))
    autoCarsPerFloor = math.floor(s.parkingAutoPlate / max(1, effAreaAutoCar))
    totalConvCars = convCarsPerFloor * (s.parkingConFloorsAG + s.parkingConFloorsBG)
    totalAutoCars = autoCarsPerFloor * (s.parkingAutoFloorsAG + s.parkingAutoFloorsBG)

    openLotCars = math.floor(s.openLotArea / max(1, effAreaOpenCar))
    totalCars = totalConvCars + totalAutoCars + openLotCars
    disabledCars = calc_disabled_parking(totalCars)

    # GFA (actual): main + conventional parking (auto excluded)
    gfa = mainCFA + parkConCFA

    # FAR-counted by law
    farCounted = (mainCFA_AG + (mainCFA_BG if s.countBasementInFAR else 0)) + \
                 ( (parkConCFA_AG + (parkConCFA_BG if s.countBasementInFAR else 0)) if s.countParkingInFAR else 0 )

    # FAR check (ตามข้อตกลง: เช็คด้วย GFA อย่างเรียบง่าย)
    farOk = gfa <= maxGFA

    # Efficiency breakdown (from GFA)
    publicArea = (s.publicPctOfGFA / 100.0) * gfa
    bohArea = (s.bohPctOfGFA / 100.0) * gfa
    serviceArea = (s.servicePctOfGFA / 100.0) * gfa
    nsa = max(0.0, gfa - (publicArea + bohArea + serviceArea))
    nla = (s.nlaPctOfPublic / 100.0) * publicArea

    # Costs
    costMain = mainCFA * s.costMainPerSqm
    costParkConv = parkConCFA * s.costParkConvPerSqm
    costParkAuto = parkAutoCFA * s.costParkAutoPerSqm
    greenCost = greenArea * s.costGreenPerSqm

    customCostTotal = 0.0
    for i in s.customCosts:
        if i.kind == "per_sqm":
            customCostTotal += i.rate * totalCFA
        elif i.kind == "per_car_conv":
            customCostTotal += i.rate * totalConvCars
        elif i.kind == "per_car_auto":
            customCostTotal += i.rate * totalAutoCars
        else:  # lump_sum
            customCostTotal += i.rate

    capexTotal = costMain + costParkConv + costParkAuto + greenCost + customCostTotal
    budgetOk = capexTotal <= s.budget if s.budget > 0 else True

    # DE ratios
    deNSA_GFA = nsa / gfa if gfa > 0 else 0
    deNSA_CFA = nsa / totalCFA if totalCFA > 0 else 0
    deGFA_CFA = gfa / totalCFA if totalCFA > 0 else 0
    deNLA_GFA = nla / gfa if gfa > 0 else 0

    return dict(
        # zoning
        maxGFA=maxGFA, farCounted=farCounted, farOk=farOk,
        # areas
        mainCFA_AG=mainCFA_AG, mainCFA_BG=mainCFA_BG,
        parkConCFA_AG=parkConCFA_AG, parkConCFA_BG=parkConCFA_BG,
        parkAutoCFA_AG=parkAutoCFA_AG, parkAutoCFA_BG=parkAutoCFA_BG,
        mainCFA=mainCFA, parkConCFA=parkConCFA, parkAutoCFA=parkAutoCFA,
        totalCFA=totalCFA, gfa=gfa,
        # height
        estHeight=estHeight, heightOk=heightOk,
        # parking
        convCarsPerFloor=convCarsPerFloor, autoCarsPerFloor=autoCarsPerFloor,
        totalConvCars=totalConvCars, totalAutoCars=totalAutoCars,
        openLotCars=openLotCars, totalCars=totalCars, disabledCars=disabledCars,
        effAreaConCar=effAreaConCar, effAreaAutoCar=effAreaAutoCar, effAreaOpenCar=effAreaOpenCar,
        # efficiency
        publicArea=publicArea, bohArea=bohArea, serviceArea=serviceArea, nsa=nsa, nla=nla,
        # ratios
        deNSA_GFA=deNSA_GFA, deNSA_CFA=deNSA_CFA, deGFA_CFA=deGFA_CFA, deNLA_GFA=deNLA_GFA,
        # costs
        costMain=costMain, costParkConv=costParkConv, costParkAuto=costParkAuto,
        greenCost=greenCost, customCostTotal=customCostTotal, capexTotal=capexTotal, budgetOk=budgetOk,
        # display helpers
        openSpaceArea=openSpaceArea, greenArea=greenArea
    )

# =========================
# Streamlit UI
# =========================
st.set_page_config(page_title="Feasibility Calculator (Streamlit)", layout="wide")

st.title("Feasibility Calculator — Streamlit Edition")
st.caption("Ported 1:1 จาก React logic (GFA/FAR/Height/Parking/CAPEX/DE ratios) พร้อม Export/Import CSV & Tests.")

# Session state
if "scenario" not in st.session_state:
    st.session_state.scenario = Scenario()
if "scenario_name" not in st.session_state:
    st.session_state.scenario_name = "Scenario A"

s: Scenario = st.session_state.scenario
cur_symbol = currency_symbol(s.currency)

# ----- Header actions
c1, c2, c3 = st.columns([1,1,2])
with c1:
    st.text_input("Scenario name", value=st.session_state.scenario_name, key="scenario_name")
with c2:
    if st.button("Reset Scenario"):
        st.session_state.scenario = Scenario()
        s = st.session_state.scenario

with c3:
    uploaded = st.file_uploader("Import Scenario CSV", type=["csv"], label_visibility="collapsed")
    if uploaded is not None:
        patch = parse_csv_to_patch(uploaded.read())
        d = asdict(s)
        d.update(patch)
        # restore customCosts if present as list-like rows (optional enhancement)
        st.session_state.scenario = Scenario(**{k: d[k] for k in d if k in Scenario().__dict__.keys()})
        s = st.session_state.scenario
        st.success("Imported!")

# ----- Layout: Inputs
st.subheader("Inputs")

# Site & Zoning
with st.expander("Site & Zoning", expanded=True):
    cz1, cz2, cz3 = st.columns(3)
    with cz1:
        s.siteArea = st.number_input("Site Area (m²)", min_value=0.0, value=float(s.siteArea), step=100.0)
        s.osr = st.number_input("OSR (%)", min_value=0.0, max_value=100.0, value=float(s.osr), step=1.0)
    with cz2:
        far_min, far_max = RULES["base"]["farRange"]
        s.far = st.number_input("FAR (1–10)", min_value=far_min, max_value=far_max, value=float(s.far), step=0.1)
        s.greenPctOfOSR = st.number_input("Green (% of OSR)", min_value=0.0, max_value=100.0, value=float(s.greenPctOfOSR), step=1.0)
    with cz3:
        old_btype = s.bType
        s.bType = st.selectbox("Building Type", BUILDING_TYPES, index=BUILDING_TYPES.index(s.bType))
        if s.bType != old_btype:
            s.osr = suggested_osr(s.bType)
            s.greenPctOfOSR = suggested_green_pct(s.bType)

# Geometry & Height
with st.expander("Geometry & Height", expanded=True):
    g1, g2, g3 = st.columns(3)
    with g1:
        s.mainFloorsAG = st.number_input("Main Floors (AG)", min_value=0, value=int(s.mainFloorsAG), step=1)
        s.parkingConFloorsAG = st.number_input("Park Conv (AG)", min_value=0, value=int(s.parkingConFloorsAG), step=1)
        s.parkingAutoFloorsAG = st.number_input("Auto Park (AG)", min_value=0, value=int(s.parkingAutoFloorsAG), step=1)
        s.mainFloorPlate = st.number_input("Main Plate (m²)", min_value=0.0, value=float(s.mainFloorPlate), step=50.0)
    with g2:
        s.mainFloorsBG = st.number_input("Main Floors (BG)", min_value=0, value=int(s.mainFloorsBG), step=1)
        s.parkingConFloorsBG = st.number_input("Park Conv (BG)", min_value=0, value=int(s.parkingConFloorsBG), step=1)
        s.parkingAutoFloorsBG = st.number_input("Auto Park (BG)", min_value=0, value=int(s.parkingAutoFloorsBG), step=1)
        s.parkingConPlate = st.number_input("Park Plate (Conv) (m²)", min_value=0.0, value=float(s.parkingConPlate), step=50.0)
    with g3:
        s.ftf = st.number_input("F2F (m)", min_value=0.0, value=float(s.ftf), step=0.1)
        s.maxHeight = st.number_input("Max Height (m)", min_value=0.0, value=float(s.maxHeight), step=1.0)
        s.parkingAutoPlate = st.number_input("Park Plate (Auto) (m²)", min_value=0.0, value=float(s.parkingAutoPlate), step=50.0)

    h1, h2 = st.columns(2)
    with h1:
        s.countParkingInFAR = st.selectbox("Count Parking in FAR? (Conventional only)", ["Yes", "No"],
                                           index=0 if s.countParkingInFAR else 1) == "Yes"
    with h2:
        s.countBasementInFAR = st.selectbox("Count Basement in FAR?", ["Yes", "No"],
                                            index=0 if s.countBasementInFAR else 1) == "Yes"

# Parking & Efficiency
with st.expander("Parking & Efficiency", expanded=True):
    p1, p2, p3 = st.columns(3)
    with p1:
        s.bayConv = st.number_input("Conv Bay (m²) — net", min_value=1.0, value=float(s.bayConv), step=1.0)
        s.circConvPct = st.number_input("Conv Circ (%)", min_value=0.0, max_value=100.0, value=float(s.circConvPct * 100), step=1.0) / 100.0
        st.caption(f"eff = {nf(s.bayConv * (1 + s.circConvPct))} m²/คัน")
    with p2:
        s.bayAuto = st.number_input("Auto Bay (m²) — net", min_value=1.0, value=float(s.bayAuto), step=1.0)
        s.circAutoPct = st.number_input("Auto Circ (%)", min_value=0.0, max_value=100.0, value=float(s.circAutoPct * 100), step=1.0) / 100.0
        st.caption(f"eff = {nf(s.bayAuto * (1 + s.circAutoPct))} m²/คัน")
    with p3:
        s.openLotArea = st.number_input("Open-lot Area (m²)", min_value=0.0, value=float(s.openLotArea), step=50.0)
        s.openLotBay = st.number_input("Open-lot Bay (m²/คัน)", min_value=1.0, value=float(s.openLotBay), step=1.0)
        s.openLotCircPct = st.number_input("Open-lot Circ (%)", min_value=0.0, max_value=100.0, value=float(s.openLotCircPct * 100), step=1.0) / 100.0
        st.caption(f"eff (open-lot) = {nf(s.openLotBay * (1 + s.openLotCircPct))} m²/คัน")

# Costs & Budget
with st.expander("Costs & Budget", expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        s.costMainPerSqm = st.number_input(f"Architecture ({cur_symbol}/m²)", min_value=0.0, value=float(s.costMainPerSqm), step=100.0)
        s.costParkConvPerSqm = st.number_input(f"Park Conv ({cur_symbol}/m²)", min_value=0.0, value=float(s.costParkConvPerSqm), step=100.0)
    with c2:
        s.costParkAutoPerSqm = st.number_input(f"Park Auto ({cur_symbol}/m²)", min_value=0.0, value=float(s.costParkAutoPerSqm), step=100.0)
        s.budget = st.number_input(f"Budget ({cur_symbol})", min_value=0.0, value=float(s.budget), step=1_000_000.0)

    st.markdown("**Additional Cost Items** *(เพิ่ม FF&E/Facade/Consultant/Permit ฯลฯ)*")
    # Simple table-like editor for custom costs
    cc_df = pd.DataFrame([asdict(x) for x in s.customCosts]) if s.customCosts else pd.DataFrame(columns=["id","name","kind","rate"])
    edited = st.dataframe(
        cc_df,
        hide_index=True,
        use_container_width=True
    )
    st.caption("Tip: ใช้ปุ่ม ‘+ Add’ ด้านล่างเพื่อเพิ่มแถวใหม่ แล้วแก้ในตาราง")

    a1, a2 = st.columns([1,3])
    with a1:
        if st.button("+ Add"):
            new = CustomCost(id=int(pd.Timestamp.utcnow().value), name="Misc.", kind="lump_sum", rate=0.0)
            s.customCosts.append(new)
    with a2:
        if st.button("Apply Table Edits"):
            # re-pull from session state data editor
            # (Streamlit DataFrame editor here is read-only; use simple apply to keep UX compact)
            st.info("ตารางนี้เป็นตัวแสดงผลอย่างง่าย หากต้องแก้ไข ให้กด +Add และใช้ปุ่ม Apply เพื่อรีเฟรช")
    # Rehydrate customCosts from current df (best-effort)
    try:
        cc_current = edited.data if hasattr(edited, "data") else cc_df
        s.customCosts = []
        for _, r in cc_current.iterrows():
            s.customCosts.append(CustomCost(
                id=int(r.get("id", int(pd.Timestamp.utcnow().value))),
                name=str(r.get("name", "Misc.")),
                kind=str(r.get("kind", "lump_sum")),
                rate=float(r.get("rate", 0.0))
            ))
    except Exception:
        pass

# ----- Compute
d = compute(s)

# ----- Key DE Panel
st.subheader("Key Metrics")
k1, k2, k3 = st.columns(3)
with k1:
    st.metric("Max FAR (Max GFA)", nf(d["maxGFA"]))
with k2:
    st.metric("GFA (actual)", nf(d["gfa"]), help="FAR check: " + ("OK" if d["farOk"] else "Exceeds"))
    st.markdown(f"**FAR:** {'✅ OK' if d['farOk'] else '❌ Exceeds Max GFA'}")
with k3:
    st.metric("Total CFA", nf(d["totalCFA"]))
    st.caption(f"GFA/CFA = {nf(d['deGFA_CFA'], 3)}")

# ----- Summaries
st.subheader("Summaries")
s1, s2, s3 = st.columns(3)

with s1:
    st.markdown("### Zoning Summary")
    st.write(f"Max GFA: **{nf(d['maxGFA'])}** m²")
    st.write(f"GFA (actual): **{nf(d['gfa'])}** m²")
    if abs(d["farCounted"] - d["gfa"]) > 1e-9:
        st.caption(f"Area counted by law (FAR): **{nf(d['farCounted'])}** m²")
    st.write(f"Open Space (OSR): **{nf(d['openSpaceArea'])}** m² ({s.osr}%)")
    st.write(f"Green Area: **{nf(d['greenArea'])}** m² ({s.greenPctOfOSR}% of OSR)")
    st.info(f"FAR check: {'OK' if d['farOk'] else 'Exceeds Max GFA'}")

with s2:
    st.markdown("### Areas")
    st.write(f"Main CFA (AG): **{nf(d['mainCFA_AG'])}** m²")
    st.write(f"Main CFA (BG): **{nf(d['mainCFA_BG'])}** m²")
    st.write(f"Parking CFA (Conv): **{nf(d['parkConCFA'])}** m²")
    st.write(f"Parking CFA (Auto): **{nf(d['parkAutoCFA'])}** m² *(NOT GFA)*")
    st.write(f"Total CFA: **{nf(d['totalCFA'])}** m²")

with s3:
    st.markdown("### Height")
    st.write(f"Estimated Height (AG only): **{nf(d['estHeight'])}** m")
    st.write(f"Max Height: **{nf(s.maxHeight)}** m")
    st.info(f"Height check: {'OK' if d['heightOk'] else 'Exceeds Limit'}")

# ----- Parking & CAPEX
st.subheader("Parking & CAPEX")

pc1, pc2 = st.columns([1,2])
with pc1:
    st.markdown("#### Parking")
    st.write(f"Cars/Floor (Conv): **{d['convCarsPerFloor']}** (eff {nf(d['effAreaConCar'])} m²/car)")
    st.write(f"Cars/Floor (Auto): **{d['autoCarsPerFloor']}** (eff {nf(d['effAreaAutoCar'])} m²/car)")
    st.write(f"Open-lot Cars: **{d['openLotCars']}** (eff {nf(d['effAreaOpenCar'])} m²/car)")
    st.write(f"Total Cars (Conv): **{d['totalConvCars']}**")
    st.write(f"Total Cars (Auto): **{d['totalAutoCars']}**")
    st.write(f"Total Cars: **{d['totalCars']}**")
    st.write(f"Disabled Spaces (calc): **{d['disabledCars']}**")

with pc2:
    st.markdown("#### CAPEX")
    st.write(f"Main: **{cur_symbol}{nf(d['costMain'])}**")
    st.write(f"Park (Conv): **{cur_symbol}{nf(d['costParkConv'])}**")
    st.write(f"Park (Auto): **{cur_symbol}{nf(d['costParkAuto'])}**")
    st.write(f"Green: **{cur_symbol}{nf(d['greenCost'])}**")
    if s.customCosts:
        st.write(f"Custom: **{cur_symbol}{nf(d['customCostTotal'])}**")
    st.write(f"**Total CAPEX: {cur_symbol}{nf(d['capexTotal'])}**")
    st.info(f"Budget check: {'OK' if d['budgetOk'] else 'Over Budget'} (Budget {cur_symbol}{nf(s.budget)})")

    # Pie chart with plotly
    capex_df = pd.DataFrame([
        {"name": "Main", "value": max(0, d["costMain"])},
        {"name": "Park (Conv)", "value": max(0, d["costParkConv"])},
        {"name": "Park (Auto)", "value": max(0, d["costParkAuto"])},
        {"name": "Green", "value": max(0, d["greenCost"])},
        {"name": "Custom", "value": max(0, d["customCostTotal"])},
    ])
    fig = px.pie(capex_df, values="value", names="name", hole=0.35, title="CAPEX Breakdown")
    st.plotly_chart(fig, use_container_width=True)

# ----- Site Visualization (simple rectangles)
st.subheader("Site Visualization")
# Draw simple rectangles with matplotlib to mimic site / OSR / Green
W, H, P = 10, 6, 0.6  # arbitrary
siteW, siteH = W - 2*P, H - 2*P
osr_ratio = clamp(s.osr / 100.0, 0.0, 1.0)
green_ratio = 0.0
if s.siteArea * osr_ratio > 0:
    green_ratio = clamp(d["greenArea"] / (s.siteArea * osr_ratio), 0.0, 1.0)

osrW, osrH = siteW * math.sqrt(osr_ratio), siteH * math.sqrt(osr_ratio)
greenW, greenH = osrW * math.sqrt(green_ratio), osrH * math.sqrt(green_ratio)
cx, cy = W/2, H/2

fig2, ax = plt.subplots(figsize=(7, 4))
ax.add_patch(plt.Rectangle((0,0), W, H, color="#f8fafc"))
ax.add_patch(plt.Rectangle((P,P), siteW, siteH, fill=False, edgecolor="#94a3b8", linewidth=2))
ax.add_patch(plt.Rectangle((cx - osrW/2, cy - osrH/2), osrW, osrH, facecolor="#dcfce7", edgecolor="#86efac"))
ax.add_patch(plt.Rectangle((cx - greenW/2, cy - greenH/2), greenW, greenH, facecolor="#86efac", edgecolor="#059669"))
ax.set_xlim(-0.1, W+0.1); ax.set_ylim(-0.1, H+0.1)
ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect('equal', 'box')
ax.text(P+0.1, H-P-0.3, "Site", fontsize=9, color="#334155")
ax.text(cx - osrW/2 + 0.1, cy + osrH/2 - 0.3, "Open Space", fontsize=9, color="#334155")
ax.text(cx - greenW/2 + 0.1, cy - greenH/2 + 0.3, "Green", fontsize=9, color="#334155")
st.pyplot(fig2)

# ----- Warnings
warnings = []
rule = RULES["building"].get(s.bType, {})
if not d["farOk"]:
    warnings.append("FAR เกิน Max GFA")
if not d["heightOk"]:
    warnings.append("ความสูงเกิน Max Height")
if rule.get("minOSR") is not None and s.osr < rule["minOSR"]:
    warnings.append(f"OSR ต่ำกว่าขั้นต่ำ {rule['minOSR']}%")
if rule.get("greenPctOfOSR") is not None and s.greenPctOfOSR < rule["greenPctOfOSR"]:
    warnings.append(f"Green % ต่ำกว่า {rule['greenPctOfOSR']}% ของ OSR")
if not d["budgetOk"]:
    warnings.append("CAPEX เกินงบประมาณ")

if warnings:
    st.warning("**Design check:** " + " · ".join(warnings))

# ----- Export
st.subheader("Export / Save")
export_cols = st.columns([1,2])
with export_cols[0]:
    # Export scenario as CSV (Field,Value)
    csv_text = create_csv_from_kv(asdict(s))
    st.download_button(
        "Export Scenario CSV",
        data=csv_text.encode("utf-8"),
        file_name=f"{st.session_state.scenario_name.replace(' ','_')}.csv",
        mime="text/csv",
        use_container_width=True
    )
with export_cols[1]:
    # Export derived summary as CSV
    out = {**asdict(s), **d}
    df_sum = pd.DataFrame([out])
    st.download_button(
        "Export Derived Summary CSV",
        data=df_sum.to_csv(index=False).encode("utf-8"),
        file_name=f"{st.session_state.scenario_name.replace(' ','_')}_summary.csv",
        mime="text/csv",
        use_container_width=True
    )

# ----- Tests
st.subheader("Tests")
tests = []
# disabled parking
tests += [
    ("calcDisabledParking(0)", calc_disabled_parking(0), 0),
    ("calcDisabledParking(50)", calc_disabled_parking(50), 2),
    ("calcDisabledParking(51)", calc_disabled_parking(51), 3),
    ("calcDisabledParking(100)", calc_disabled_parking(100), 3),
    ("calcDisabledParking(101)", calc_disabled_parking(101), 4),
    ("calcDisabledParking(250)", calc_disabled_parking(250), 5),
]
# FAR counting & GFA rules
mAG = s.mainFloorsAG * s.mainFloorPlate
mBG = s.mainFloorsBG * s.mainFloorPlate
pcAG = s.parkingConFloorsAG * s.parkingConPlate
pcBG = s.parkingConFloorsBG * s.parkingConPlate
paAG = s.parkingAutoFloorsAG * s.parkingAutoPlate
paBG = s.parkingAutoFloorsBG * s.parkingAutoPlate

far_expected = (mAG + (mBG if s.countBasementInFAR else 0)) + \
               ((pcAG + (pcBG if s.countBasementInFAR else 0)) if s.countParkingInFAR else 0)
gfa_expected = (mAG + mBG) + (pcAG + pcBG)
open_lot_expected = math.floor(s.openLotArea / max(1, s.openLotBay * (1 + s.openLotCircPct)))

tests += [
    ("FAR-counted (expected)", d["farCounted"], far_expected),
    ("GFA excludes auto parking", abs(d["gfa"] - gfa_expected) < 1e-6, True),
    ("Open-lot cars", d["openLotCars"], open_lot_expected),
    ("0 ≤ GFA/CFA ≤ 1", 0 <= d["deGFA_CFA"] <= 1, True),
    ("0 ≤ NSA/GFA ≤ 1", 0 <= d["deNSA_GFA"] <= 1, True),
    ("0 ≤ NSA/CFA ≤ 1", 0 <= d["deNSA_CFA"] <= 1, True),
    ("0 ≤ NLA/GFA ≤ 1", 0 <= d["deNLA_GFA"] <= 1, True),
]

df_tests = pd.DataFrame([{
    "Test": name,
    "Actual": actual,
    "Expected": expected,
    "Pass": (actual == expected) if isinstance(expected, (int, float, str)) else (actual is True)
} for (name, actual, expected) in tests])

st.dataframe(df_tests, use_container_width=True, hide_index=True)
