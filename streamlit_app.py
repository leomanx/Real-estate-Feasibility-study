# streamlit_app.py
# -*- coding: utf-8 -*-
import io, math
from dataclasses import dataclass, asdict, field, is_dataclass
from typing import List, Dict, Any

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

# (plotly optional)
try:
    import plotly.express as px
    HAS_PLOTLY = True
except Exception:
    HAS_PLOTLY = False

# ---------------- Helpers ----------------
def nf(n, digits=2):
    try:
        x = float(n)
    except Exception:
        return "–"
    return f"{x:,.{digits}f}"

def clamp(v, lo, hi): return max(lo, min(hi, v))
def currency_symbol(c): return "฿" if c == "THB" else "$"

def create_csv_from_kv(d: Dict[str, Any]) -> str:
    # flatten dataclasses in lists (e.g., customCosts) so export/round-tripง่าย
    flat = {}
    for k, v in d.items():
        if isinstance(v, list) and v and is_dataclass(v[0]):
            flat[k] = pd.DataFrame([asdict(x) for x in v]).to_json(orient="records")
        else:
            flat[k] = v
    rows = [{"Field": k, "Value": v} for k, v in flat.items()]
    return pd.DataFrame(rows).to_csv(index=False)

def parse_csv_to_patch(file_bytes: bytes) -> Dict[str, Any]:
    df = pd.read_csv(io.BytesIO(file_bytes))
    out: Dict[str, Any] = {}
    for _, r in df.iterrows():
        k = str(r["Field"]).strip()
        v = r["Value"]
        # try numeric
        if isinstance(v, str):
            v_str = v.strip()
            if v_str == "":
                out[k] = v_str
                continue
            # try JSON list (customCosts)
            if (v_str.startswith("[") and v_str.endswith("]")):
                try:
                    out[k] = pd.read_json(io.StringIO(v_str)).to_dict(orient="records")
                    continue
                except Exception:
                    pass
            try:
                num = float(v_str.replace(",", ""))
                out[k] = int(num) if abs(num - int(num)) < 1e-12 else num
                continue
            except Exception:
                out[k] = v_str
        else:
            try:
                num = float(v)
                out[k] = int(num) if abs(num - int(num)) < 1e-12 else num
            except Exception:
                out[k] = v
    return out

def calc_disabled_parking(total_cars: int) -> int:
    if total_cars <= 0: return 0
    if total_cars <= 50: return 2
    if total_cars <= 100: return 3
    extra_hundreds = math.ceil((total_cars - 100) / 100)
    return 3 + max(0, extra_hundreds)

# ---------------- Rules / Presets ----------------
BUILDING_TYPES = ["Housing","Hi-Rise","Low-Rise","Public Building","Office Building","Hotel"]
RULES = {
    "base": {"farRange": (1.0, 10.0)},
    "building": {
        "Housing": {"minOSR": 30, "greenPctOfOSR": None},
        "Hi-Rise": {"minOSR": 10, "greenPctOfOSR": 50},
        "Low-Rise": {"minOSR": 10, "greenPctOfOSR": 50},
        "Public Building": {"minOSR": None, "greenPctOfOSR": None},
        "Office Building": {"minOSR": None, "greenPctOfOSR": None},
        "Hotel": {"minOSR": 10, "greenPctOfOSR": 40},
    }
}
def suggested_osr(btype): return 15 if RULES["building"].get(btype,{}).get("minOSR") is None else float(RULES["building"][btype]["minOSR"])
def suggested_green_pct(btype): 
    v = RULES["building"].get(btype,{}).get("greenPctOfOSR")
    return 40 if v is None else float(v)

# ---------------- Model ----------------
@dataclass
class CustomCost:
    id: int
    name: str = "Misc."
    kind: str = "lump_sum"   # per_sqm | per_car_conv | per_car_auto | lump_sum
    rate: float = 0.0

@dataclass
class Scenario:
    siteArea: float = 8000
    far: float = 5
    bType: str = "Housing"
    osr: float = 30
    greenPctOfOSR: float = 40
    mainFloorsAG: int = 20
    mainFloorsBG: int = 0
    parkingConFloorsAG: int = 3
    parkingConFloorsBG: int = 0
    parkingAutoFloorsAG: int = 0
    parkingAutoFloorsBG: int = 0
    ftf: float = 3.2
    maxHeight: float = 120
    mainFloorPlate: float = 1500
    parkingConPlate: float = 1200
    parkingAutoPlate: float = 800
    bayConv: float = 25
    circConvPct: float = 0.0
    bayAuto: float = 16
    circAutoPct: float = 0.0
    openLotArea: float = 0
    openLotBay: float = 25
    openLotCircPct: float = 0.0
    publicPctOfGFA: float = 10
    nlaPctOfPublic: float = 40
    bohPctOfGFA: float = 8
    servicePctOfGFA: float = 2
    countParkingInFAR: bool = True
    countBasementInFAR: bool = False
    costMainPerSqm: float = 30000
    costParkConvPerSqm: float = 18000
    costParkAutoPerSqm: float = 25000
    costGreenPerSqm: float = 4500
    budget: float = 500_000_000
    currency: str = "THB"
    customCosts: List[CustomCost] = field(default_factory=list)

def compute(s: Scenario) -> Dict[str, Any]:
    far_min, far_max = RULES["base"]["farRange"]
    far = clamp(float(s.far), far_min, far_max)
    maxGFA = float(s.siteArea) * far

    openSpaceArea = (float(s.osr)/100.0) * float(s.siteArea)
    greenArea = (float(s.greenPctOfOSR)/100.0) * openSpaceArea

    mainCFA_AG = int(s.mainFloorsAG) * float(s.mainFloorPlate)
    mainCFA_BG = int(s.mainFloorsBG) * float(s.mainFloorPlate)
    parkConCFA_AG = int(s.parkingConFloorsAG) * float(s.parkingConPlate)
    parkConCFA_BG = int(s.parkingConFloorsBG) * float(s.parkingConPlate)
    parkAutoCFA_AG = int(s.parkingAutoFloorsAG) * float(s.parkingAutoPlate)
    parkAutoCFA_BG = int(s.parkingAutoFloorsBG) * float(s.parkingAutoPlate)

    mainCFA = mainCFA_AG + mainCFA_BG
    parkConCFA = parkConCFA_AG + parkConCFA_BG
    parkAutoCFA = parkAutoCFA_AG + parkAutoCFA_BG
    totalCFA = mainCFA + parkConCFA + parkAutoCFA

    estHeight = float(s.ftf) * (int(s.mainFloorsAG) + int(s.parkingConFloorsAG) + int(s.parkingAutoFloorsAG))
    heightOk = estHeight <= float(s.maxHeight)

    effAreaConCar = float(s.bayConv) * (1.0 + float(s.circConvPct))
    effAreaAutoCar = float(s.bayAuto) * (1.0 + float(s.circAutoPct))
    effAreaOpenCar = float(s.openLotBay) * (1.0 + float(s.openLotCircPct))

    convCarsPerFloor = math.floor((float(s.parkingConPlate) or 1) / max(1, effAreaConCar))
    autoCarsPerFloor = math.floor((float(s.parkingAutoPlate) or 1) / max(1, effAreaAutoCar))
    totalConvCars = convCarsPerFloor * (int(s.parkingConFloorsAG) + int(s.parkingConFloorsBG))
    totalAutoCars = autoCarsPerFloor * (int(s.parkingAutoFloorsAG) + int(s.parkingAutoFloorsBG))
    openLotCars = math.floor(float(s.openLotArea) / max(1, effAreaOpenCar))
    totalCars = totalConvCars + totalAutoCars + openLotCars
    disabledCars = calc_disabled_parking(totalCars)

    gfa = mainCFA + parkConCFA
    farCounted = (mainCFA_AG + (mainCFA_BG if s.countBasementInFAR else 0)) + \
                 ((parkConCFA_AG + (parkConCFA_BG if s.countBasementInFAR else 0)) if s.countParkingInFAR else 0)
    farOk = gfa <= maxGFA

    publicArea = (float(s.publicPctOfGFA)/100.0) * gfa
    bohArea = (float(s.bohPctOfGFA)/100.0) * gfa
    serviceArea = (float(s.servicePctOfGFA)/100.0) * gfa
    nsa = max(0.0, gfa - (publicArea + bohArea + serviceArea))
    nla = (float(s.nlaPctOfPublic)/100.0) * publicArea

    costMain = mainCFA * float(s.costMainPerSqm)
    costParkConv = parkConCFA * float(s.costParkConvPerSqm)
    costParkAuto = parkAutoCFA * float(s.costParkAutoPerSqm)
    greenCost = greenArea * float(s.costGreenPerSqm)

    customCostTotal = 0.0
    for i in s.customCosts:
        if isinstance(i, dict):  # เผื่อกรณี load ผสม
            kind = str(i.get("kind","lump_sum"))
            rate = float(i.get("rate",0))
        else:
            kind = i.kind; rate = float(i.rate)
        if kind == "per_sqm":
            customCostTotal += rate * totalCFA
        elif kind == "per_car_conv":
            customCostTotal += rate * totalConvCars
        elif kind == "per_car_auto":
            customCostTotal += rate * totalAutoCars
        else:
            customCostTotal += rate

    capexTotal = costMain + costParkConv + costParkAuto + greenCost + customCostTotal
    budgetOk = capexTotal <= float(s.budget) if float(s.budget) > 0 else True

    def safe_ratio(a,b): return (a/b) if b>0 else 0.0
    deNSA_GFA = safe_ratio(nsa, gfa)
    deNSA_CFA = safe_ratio(nsa, totalCFA)
    deGFA_CFA = safe_ratio(gfa, totalCFA)
    deNLA_GFA = safe_ratio(nla, gfa)

    return dict(
        maxGFA=maxGFA, farCounted=farCounted, farOk=farOk,
        mainCFA_AG=mainCFA_AG, mainCFA_BG=mainCFA_BG,
        parkConCFA_AG=parkConCFA_AG, parkConCFA_BG=parkConCFA_BG,
        parkAutoCFA_AG=parkAutoCFA_AG, parkAutoCFA_BG=parkAutoCFA_BG,
        mainCFA=mainCFA, parkConCFA=parkConCFA, parkAutoCFA=parkAutoCFA,
        totalCFA=totalCFA, gfa=gfa,
        estHeight=estHeight, heightOk=heightOk,
        convCarsPerFloor=convCarsPerFloor, autoCarsPerFloor=autoCarsPerFloor,
        totalConvCars=totalConvCars, totalAutoCars=totalAutoCars,
        openLotCars=openLotCars, totalCars=totalCars, disabledCars=disabledCars,
        effAreaConCar=effAreaConCar, effAreaAutoCar=effAreaAutoCar, effAreaOpenCar=effAreaOpenCar,
        publicArea=publicArea, bohArea=bohArea, serviceArea=serviceArea, nsa=nsa, nla=nla,
        deNSA_GFA=deNSA_GFA, deNSA_CFA=deNSA_CFA, deGFA_CFA=deGFA_CFA, deNLA_GFA=deNLA_GFA,
        costMain=costMain, costParkConv=costParkConv, costParkAuto=costParkAuto,
        greenCost=greenCost, customCostTotal=customCostTotal, capexTotal=capexTotal, budgetOk=budgetOk,
        openSpaceArea=openSpaceArea, greenArea=greenArea
    )

# ---------------- UI ----------------
st.set_page_config(page_title="Feasibility Calculator (Streamlit)", layout="wide")
st.title("Feasibility Calculator — Streamlit Edition (Fixed)")

if "scenario" not in st.session_state: st.session_state.scenario = Scenario()
if "scenario_name" not in st.session_state: st.session_state.scenario_name = "Scenario A"
s: Scenario = st.session_state.scenario
cur_symbol = currency_symbol(s.currency)

c1, c2, c3 = st.columns([1,1,2])
with c1:
    st.text_input("Scenario name", value=st.session_state.scenario_name, key="scenario_name")
with c2:
    if st.button("Reset Scenario"):
        st.session_state.scenario = Scenario()
        s = st.session_state.scenario
with c3:
    up = st.file_uploader("Import Scenario CSV", type=["csv"], label_visibility="collapsed")
    if up is not None:
        patch = parse_csv_to_patch(up.read())
        d = asdict(s)
        d.update(patch)
        # rebuild customCosts safely
        cc_raw = d.get("customCosts", [])
        cc_list: List[CustomCost] = []
        if isinstance(cc_raw, list):
            for row in cc_raw:
                try:
                    cc_list.append(CustomCost(
                        id = int(row.get("id", 0)) if isinstance(row, dict) else int(getattr(row,"id",0)),
                        name = str(row.get("name","Misc.")) if isinstance(row, dict) else str(getattr(row,"name","Misc.")),
                        kind = str(row.get("kind","lump_sum")) if isinstance(row, dict) else str(getattr(row,"kind","lump_sum")),
                        rate = float(row.get("rate",0.0)) if isinstance(row, dict) else float(getattr(row,"rate",0.0)),
                    ))
                except Exception:
                    pass
        d["customCosts"] = cc_list
        # construct Scenario with only valid fields
        valid = {k: d[k] for k in Scenario().__dict__.keys() if k in d}
        st.session_state.scenario = Scenario(**valid)
        s = st.session_state.scenario
        st.success("Imported!")

st.subheader("Inputs")
with st.expander("Site & Zoning", expanded=True):
    cz1, cz2, cz3 = st.columns(3)
    with cz1:
        s.siteArea = float(st.number_input("Site Area (m²)", min_value=0.0, value=float(s.siteArea), step=100.0))
        s.osr = float(st.number_input("OSR (%)", min_value=0.0, max_value=100.0, value=float(s.osr), step=1.0))
    with cz2:
        far_min, far_max = RULES["base"]["farRange"]
        s.far = float(st.number_input("FAR (1–10)", min_value=float(far_min), max_value=float(far_max), value=float(s.far), step=0.1))
        s.greenPctOfOSR = float(st.number_input("Green (% of OSR)", min_value=0.0, max_value=100.0, value=float(s.greenPctOfOSR), step=1.0))
    with cz3:
        prev = s.bType
        s.bType = st.selectbox("Building Type", BUILDING_TYPES, index=BUILDING_TYPES.index(s.bType))
        if s.bType != prev:
            s.osr = suggested_osr(s.bType)
            s.greenPctOfOSR = suggested_green_pct(s.bType)

with st.expander("Geometry & Height", expanded=True):
    g1, g2, g3 = st.columns(3)
    with g1:
        s.mainFloorsAG = int(st.number_input("Main Floors (AG)", min_value=0, value=int(s.mainFloorsAG), step=1))
        s.parkingConFloorsAG = int(st.number_input("Park Conv (AG)", min_value=0, value=int(s.parkingConFloorsAG), step=1))
        s.parkingAutoFloorsAG = int(st.number_input("Auto Park (AG)", min_value=0, value=int(s.parkingAutoFloorsAG), step=1))
        s.mainFloorPlate = float(st.number_input("Main Plate (m²)", min_value=0.0, value=float(s.mainFloorPlate), step=50.0))
    with g2:
        s.mainFloorsBG = int(st.number_input("Main Floors (BG)", min_value=0, value=int(s.mainFloorsBG), step=1))
        s.parkingConFloorsBG = int(st.number_input("Park Conv (BG)", min_value=0, value=int(s.parkingConFloorsBG), step=1))
        s.parkingAutoFloorsBG = int(st.number_input("Auto Park (BG)", min_value=0, value=int(s.parkingAutoFloorsBG), step=1))
        s.parkingConPlate = float(st.number_input("Park Plate (Conv) (m²)", min_value=0.0, value=float(s.parkingConPlate), step=50.0))
    with g3:
        s.ftf = float(st.number_input("F2F (m)", min_value=0.0, value=float(s.ftf), step=0.1))
        s.maxHeight = float(st.number_input("Max Height (m)", min_value=0.0, value=float(s.maxHeight), step=1.0))
        s.parkingAutoPlate = float(st.number_input("Park Plate (Auto) (m²)", min_value=0.0, value=float(s.parkingAutoPlate), step=50.0))

with st.expander("Parking & Efficiency", expanded=True):
    p1, p2, p3 = st.columns(3)
    with p1:
        s.bayConv = float(st.number_input("Conv Bay (m²) — net", min_value=1.0, value=float(s.bayConv), step=1.0))
        s.circConvPct = float(st.number_input("Conv Circ (%)", min_value=0.0, max_value=100.0, value=float(s.circConvPct*100), step=1.0))/100.0
        st.caption(f"eff = {nf(s.bayConv * (1 + s.circConvPct))} m²/คัน")
    with p2:
        s.bayAuto = float(st.number_input("Auto Bay (m²) — net", min_value=1.0, value=float(s.bayAuto), step=1.0))
        s.circAutoPct = float(st.number_input("Auto Circ (%)", min_value=0.0, max_value=100.0, value=float(s.circAutoPct*100), step=1.0))/100.0
        st.caption(f"eff = {nf(s.bayAuto * (1 + s.circAutoPct))} m²/คัน")
    with p3:
        s.openLotArea = float(st.number_input("Open-lot Area (m²)", min_value=0.0, value=float(s.openLotArea), step=50.0))
        s.openLotBay = float(st.number_input("Open-lot Bay (m²/คัน)", min_value=1.0, value=float(s.openLotBay), step=1.0))
        s.openLotCircPct = float(st.number_input("Open-lot Circ (%)", min_value=0.0, max_value=100.0, value=float(s.openLotCircPct*100), step=1.0))/100.0
        st.caption(f"eff (open-lot) = {nf(s.openLotBay * (1 + s.openLotCircPct))} m²/คัน")

with st.expander("Costs & Budget", expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        s.costMainPerSqm = float(st.number_input(f"Architecture ({cur_symbol}/m²)", min_value=0.0, value=float(s.costMainPerSqm), step=100.0))
        s.costParkConvPerSqm = float(st.number_input(f"Park Conv ({cur_symbol}/m²)", min_value=0.0, value=float(s.costParkConvPerSqm), step=100.0))
    with c2:
        s.costParkAutoPerSqm = float(st.number_input(f"Park Auto ({cur_symbol}/m²)", min_value=0.0, value=float(s.costParkAutoPerSqm), step=100.0))
        s.budget = float(st.number_input(f"Budget ({cur_symbol})", min_value=0.0, value=float(s.budget), step=1_000_000.0))

    st.markdown("**Additional Cost Items**")
    cc_df = pd.DataFrame([asdict(x) for x in s.customCosts]) if s.customCosts else pd.DataFrame(
        columns=["id","name","kind","rate"]
    )
    edited_df = st.data_editor(
        cc_df,
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True
    )
    # rehydrate customCosts
    s.customCosts = []
    for _, r in edited_df.iterrows():
        try:
            s.customCosts.append(CustomCost(
                id = int(r.get("id", 0)) if not pd.isna(r.get("id", None)) else 0,
                name = str(r.get("name","Misc.")),
                kind = str(r.get("kind","lump_sum")),
                rate = float(r.get("rate", 0.0)) if not pd.isna(r.get("rate", None)) else 0.0
            ))
        except Exception:
            pass

# -------- Compute & Output --------
d = compute(s)

st.subheader("Key Metrics")
k1, k2, k3 = st.columns(3)
with k1: st.metric("Max FAR (Max GFA)", nf(d["maxGFA"]))
with k2:
    st.metric("GFA (actual)", nf(d["gfa"]))
    st.markdown(f"**FAR:** {'✅ OK' if d['farOk'] else '❌ Exceeds'}")
with k3:
    st.metric("Total CFA", nf(d["totalCFA"]))
    st.caption(f"GFA/CFA = {nf(d['deGFA_CFA'], 3)}")

st.subheader("Summaries")
s1, s2, s3 = st.columns(3)
with s1:
    st.markdown("### Zoning")
    st.write(f"Max GFA: **{nf(d['maxGFA'])}** m²")
    st.write(f"GFA (actual): **{nf(d['gfa'])}** m²")
    st.write(f"Open Space (OSR): **{nf(d['openSpaceArea'])}** m²")
    st.write(f"Green Area: **{nf(d['greenArea'])}** m²")
with s2:
    st.markdown("### Areas")
    st.write(f"Main CFA (AG): **{nf(d['mainCFA_AG'])}** m²")
    st.write(f"Main CFA (BG): **{nf(d['mainCFA_BG'])}** m²")
    st.write(f"Parking CFA (Conv): **{nf(d['parkConCFA'])}** m²")
    st.write(f"Parking CFA (Auto): **{nf(d['parkAutoCFA'])}** m² *(NOT GFA)*")
    st.write(f"Total CFA: **{nf(d['totalCFA'])}** m²")
with s3:
    st.markdown("### Height")
    st.write(f"Estimated Height (AG): **{nf(d['estHeight'])}** m")
    st.write(f"Max Height: **{nf(s.maxHeight)}** m")
    st.info(f"Height: {'OK' if d['heightOk'] else 'Exceeds'}")

st.subheader("Parking & CAPEX")
pc1, pc2 = st.columns([1,2])
with pc1:
    st.markdown("#### Parking")
    st.write(f"Cars/Floor (Conv): **{d['convCarsPerFloor']}** (eff {nf(d['effAreaConCar'])} m²/car)")
    st.write(f"Cars/Floor (Auto): **{d['autoCarsPerFloor']}** (eff {nf(d['effAreaAutoCar'])} m²/car)")
    st.write(f"Open-lot Cars: **{d['openLotCars']}**")
    st.write(f"Total Cars (Conv/Auto/All): **{d['totalConvCars']} / {d['totalAutoCars']} / {d['totalCars']}**")
    st.write(f"Disabled Spaces: **{d['disabledCars']}**")

with pc2:
    st.markdown("#### CAPEX")
    st.write(f"Main: **{cur_symbol}{nf(d['costMain'])}**")
    st.write(f"Park (Conv): **{cur_symbol}{nf(d['costParkConv'])}**")
    st.write(f"Park (Auto): **{cur_symbol}{nf(d['costParkAuto'])}**")
    st.write(f"Green: **{cur_symbol}{nf(d['greenCost'])}**")
    if s.customCosts: st.write(f"Custom: **{cur_symbol}{nf(d['customCostTotal'])}**")
    st.write(f"**Total CAPEX: {cur_symbol}{nf(d['capexTotal'])}**")
    st.info(f"Budget: {'OK' if d['budgetOk'] else 'Over'} (Budget {cur_symbol}{nf(s.budget)})")

    if HAS_PLOTLY:
        capex_df = pd.DataFrame([
            {"name": "Main", "value": max(0, d["costMain"])},
            {"name": "Park (Conv)", "value": max(0, d["costParkConv"])},
            {"name": "Park (Auto)", "value": max(0, d["costParkAuto"])},
            {"name": "Green", "value": max(0, d["greenCost"])},
            {"name": "Custom", "value": max(0, d["customCostTotal"])},
        ])
        fig = px.pie(capex_df, values="value", names="name", hole=0.35, title="CAPEX Breakdown")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Plotly not installed — skipping CAPEX chart.")

st.subheader("Site Visualization")
W, H, P = 10, 6, 0.6
siteW, siteH = W - 2*P, H - 2*P
osr_ratio = clamp(float(s.osr)/100.0, 0.0, 1.0)
green_ratio = clamp((d["greenArea"] / (s.siteArea*osr_ratio)) if s.siteArea*osr_ratio>0 else 0, 0.0, 1.0)
osrW, osrH = siteW * math.sqrt(osr_ratio), siteH * math.sqrt(osr_ratio)
greenW, greenH = osrW * math.sqrt(green_ratio), osrH * math.sqrt(green_ratio)
cx, cy = W/2, H/2
fig2, ax = plt.subplots(figsize=(7,4))
ax.add_patch(plt.Rectangle((0,0), W, H, color="#f8fafc"))
ax.add_patch(plt.Rectangle((P,P), siteW, siteH, fill=False, edgecolor="#94a3b8", linewidth=2))
ax.add_patch(plt.Rectangle((cx - osrW/2, cy - osrH/2), osrW, osrH, facecolor="#dcfce7", edgecolor="#86efac"))
ax.add_patch(plt.Rectangle((cx - greenW/2, cy - greenH/2), greenW, greenH, facecolor="#86efac", edgecolor="#059669"))
ax.set_xlim(-0.1, W+0.1); ax.set_ylim(-0.1, H+0.1)
ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect('equal', 'box')
st.pyplot(fig2)

# Warnings
warnings = []
rule = RULES["building"].get(s.bType, {})
if not d["farOk"]: warnings.append("FAR เกิน Max GFA")
if not d["heightOk"]: warnings.append("ความสูงเกิน Max Height")
if rule.get("minOSR") is not None and s.osr < rule["minOSR"]: warnings.append(f"OSR ต่ำกว่าขั้นต่ำ {rule['minOSR']}%")
if rule.get("greenPctOfOSR") is not None and s.greenPctOfOSR < rule["greenPctOfOSR"]: warnings.append(f"Green % ต่ำกว่า {rule['greenPctOfOSR']}% ของ OSR")
if not d["budgetOk"]: warnings.append("CAPEX เกินงบประมาณ")
if warnings: st.warning("**Design check:** " + " · ".join(warnings))

# Export
st.subheader("Export / Save")
cA, cB = st.columns([1,2])
with cA:
    csv_text = create_csv_from_kv(asdict(s))
    st.download_button(
        "Export Scenario CSV",
        data=csv_text.encode("utf-8"),
        file_name=f"{st.session_state.scenario_name.replace(' ','_')}.csv",
        mime="text/csv",
        use_container_width=True
    )
with cB:
    out = {**asdict(s), **d}
    df_sum = pd.DataFrame([out])
    st.download_button(
        "Export Derived Summary CSV",
        data=df_sum.to_csv(index=False).encode("utf-8"),
        file_name=f"{st.session_state.scenario_name.replace(' ','_')}_summary.csv",
        mime="text/csv",
        use_container_width=True
    )
