# app.py — Feasibility (TH) — Streamlit complete version
# run: streamlit run app.py
# app.py — Real Estate Feasibility v1 (Streamlit)
# Requirements:
#   pip install streamlit pandas numpy

import json
import math
import json
from dataclasses import dataclass, asdict
from typing import List, Dict

import streamlit as st

# ---------------------------------
# Helpers
# ---------------------------------
def nf(n, digits=2):
# =============== Page setup & minimalist dark theme ===============
st.set_page_config(page_title="Feasibility v1", page_icon="🏗️", layout="wide")
st.markdown(
    """
    <style>
      /* Minimal black/gray/white look */
      .stApp { background: #0f1115; }
      .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
      .stMarkdown, .stText, .stNumberInput, .stSelectbox, .stMetric, .stDataFrame { color: #e6e6e6; }
      .stMetric { background:#171a21; border:1px solid #2a2f3a; border-radius:14px; padding:12px 16px; }
      [data-testid="stMetricDelta"] { font-weight:600; }
      div[data-baseweb="select"] > div { background:#171a21; }
      .stNumberInput > div > div { background:#171a21; }
      .stButton>button, .stDownloadButton>button { background:#171a21; color:#e6e6e6; border:1px solid #2a2f3a; border-radius:10px; }
      .stTabs [data-baseweb="tab-list"] { gap:.5rem; }
      .stTabs [data-baseweb="tab"] { background:#171a21; color:#cbd5e1; border:1px solid #2a2f3a; border-radius:10px; padding:.4rem .8rem; }
      .stTabs [aria-selected="true"] { color:#fff; border-color:#3b82f6; }
      .card { background:#141821; border:1px solid #2a2f3a; border-radius:16px; padding:16px; }
      .muted { color:#9aa4b2; font-size:.82rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ====================== Helpers ======================
def nf(num, digits=2):
try:
        x = float(n)
        if digits is None:
            return f"{int(round(x)):,}"
        return f"{x:,.{digits}f}"
        n = float(num)
        return f"{n:,.{digits}f}"
except Exception:
return "–"

def clamp(v, lo, hi):
return min(hi, max(lo, v))

def create_csv(rows):
    if not rows: return ""
    headers = list(rows[0].keys())
    out = [",".join(headers)]
    for r in rows:
        out.append(",".join(str(r.get(h, "")) for h in headers))
    return "\n".join(out)

def calc_disabled_parking(total_cars: float) -> int:
    tc = int(math.floor(max(0.0, total_cars)))
    if tc <= 0: return 0
    if tc <= 50: return 2
    if tc <= 100: return 3
    return 3 + max(0, math.ceil((tc - 100) / 100))

def compute_far_counted(mainAG, mainBG, pcAG, pcBG, paAG, paBG, countParking, countBasement):
def create_csv_rows(d: Dict) -> str:
    if not d:
        return ""
    lines = ["Field,Value"]
    for k, v in d.items():
        lines.append(f"{k},{v}")
    return "\n".join(lines)

def parse_csv_to_dict(text: str) -> Dict:
    rows = [r for r in text.splitlines() if r.strip()]
    if not rows:
        return {}
    out = {}
    for line in rows[1:]:
        if "," not in line:
            continue
        k, v = line.split(",", 1)
        k = k.strip()
        v = v.strip()
        try:
            vv = float(v) if v.replace(".","",1).replace("-","",1).isdigit() else v
        except Exception:
            vv = v
        out[k] = vv
    return out

# Disabled-parking rule (worst-case guideline)
def calc_disabled_parking(total_cars: int) -> int:
    if total_cars <= 0: return 0
    if total_cars <= 50: return 2
    if total_cars <= 100: return 3
    extra_hundreds = math.ceil((total_cars - 100) / 100)
    return 3 + max(0, extra_hundreds)

# FAR counted helper (LEGAL area):
# - Auto parking is NEVER counted in FAR (policy)
# - Conventional parking counted if count_parking == True
# - Basement counted if count_basement == True
def compute_far_counted(
    mainAG, mainBG, pcAG, pcBG, paAG, paBG,
    count_parking: bool, count_basement: bool
):
far = 0.0
    far += mainAG + (mainBG if countBasement else 0.0)
    if countParking:
        far += pcAG + (pcBG if countBasement else 0.0)
        far += paAG + (paBG if countBasement else 0.0)
    far += mainAG + (mainBG if count_basement else 0.0)
    if count_parking:
        far += pcAG + (pcBG if count_basement else 0.0)
    # auto (paAG/paBG) excluded from FAR by policy
return far

# ---- Legal parking (TH) ----
def legal_parking_th(location: str, units: list, gfa: float):
    """
    location: "BKK" | "OUTSIDE"
    units: [{'count': int, 'size_sqm': float, 'bedrooms': float}]
    กทม.: ห้อง >=60 m² → 1 คัน/ห้อง,   พื้นที่ก่อสร้าง: 1 คัน/120 m²
    นอกกทม.: ห้อง >=60 m² → 1 คัน/2 ห้อง, พื้นที่ก่อสร้าง: 1 คัน/240 m²
    ใช้ค่ามากสุดของทั้งสองวิธี
    """
    is_bkk = (location.upper() == "BKK")
    rooms_ge60 = sum(int(u["count"]) for u in units if float(u["size_sqm"]) >= 60.0)
    size_based = rooms_ge60 * (1.0 if is_bkk else 0.5)

    area_quota = 120.0 if is_bkk else 240.0
    area_based = math.ceil((gfa or 0.0) / area_quota)

    legal_required = max(size_based, area_based)
    total_units = sum(int(u["count"]) for u in units)
    parking_pct = (legal_required * 100.0 / total_units) if total_units > 0 else 0.0
    return dict(
        size_based=size_based,
        area_based=area_based,
        legal_required=legal_required,
        parking_pct=parking_pct,
        total_units=total_units,
    )

# ---- Green area (population-based + on-ground constraints) ----
def green_per_unit(u):
    # ตามแนวทางในภาพ/ข้อความ: เลือกค่าที่ "เข้มข้นกว่า"
    by_size = 3.0 if float(u["size_sqm"]) < 35.0 else 5.0
    br = float(u.get("bedrooms", 1.0))
    if br >= 4: by_bed = 8.0
    elif br >= 3: by_bed = 6.0
    else: by_bed = by_size   # 1–2 ห้องนอน ให้คิดตามขนาดห้อง
    return max(by_size, by_bed)

def green_th(units: list, site_area: float, green_on_ground: float, green_on_structure: float):
    green_by_population = sum(green_per_unit(u) * float(u["count"]) for u in units)
    sustainable_ground_min = max(0.15 * site_area, 0.25 * green_by_population)
    general_ground_min = 0.5 * green_by_population
    total_provided = (green_on_ground or 0.0) + (green_on_structure or 0.0)
    return dict(
        green_by_population=green_by_population,
        sustainable_ground_min=sustainable_ground_min,
        general_ground_min=general_ground_min,
        total_green_provided=total_provided,
        pass_total= total_provided >= green_by_population,
        pass_sustainable_ground= (green_on_ground or 0.0) >= sustainable_ground_min,
        pass_general_ground= (green_on_ground or 0.0) >= general_ground_min,
        need_on_ground_min=max(sustainable_ground_min, general_ground_min),
        green_on_ground=green_on_ground or 0.0,
        green_on_structure=green_on_structure or 0.0,
    )

# ---------------------------------
# Defaults & state
# ---------------------------------
RULES = {"base": {"farRange": (1.0, 10.0)}}

DEFAULT = dict(
    name="Scenario A",
    # site & far
    siteArea=8000.0,
    far=5.0,
    # geometry
    mainFloorsAG=20.0,
    mainFloorsBG=0.0,
    parkingConFloorsAG=3.0,
    parkingConFloorsBG=0.0,
    parkingAutoFloorsAG=0.0,
    parkingAutoFloorsBG=0.0,
    ftf=3.2,
    maxHeight=120.0,
    # plates
    mainFloorPlate=1500.0,
    parkingConPlate=1200.0,
    parkingAutoPlate=800.0,
    # parking efficiency
    bayConv=25.0,
    circConvPct=0.0,  # 0..1
    bayAuto=16.0,
    circAutoPct=0.0,  # 0..1
    # open-lot (outside building)
    openLotArea=0.0,
    openLotBay=25.0,
    openLotCircPct=0.0,  # 0..1
    # efficiency blocks
    gfaOverCfaPct=95.0,
    publicPctOfGFA=10.0,
    nlaPctOfPublic=40.0,  # NLA ⊂ Public
    bohPctOfGFA=8.0,
    servicePctOfGFA=2.0,
    # toggles FAR
    countParkingInFAR=True,
    countBasementInFAR=False,
    # budget (coarse by CFA)
    costMainPerSqm=30000.0,
    costParkConvPerSqm=18000.0,
    costParkAutoPerSqm=25000.0,
    budget=500_000_000.0,
    # green provision inputs
    greenOnGround=0.0,
    greenOnStructure=0.0,
    # legal location
    location="BKK",  # "BKK" | "OUTSIDE"
)
# ====================== Default scenario ======================
DEFAULT = {
    "siteArea": 8000.0,
    "far": 5.0,
    "bType": "Housing",
    "osr": 30.0,
    "greenPctOfOSR": 40.0,

    "mainFloorsAG": 20.0,
    "mainFloorsBG": 0.0,
    "parkingConFloorsAG": 3.0,
    "parkingConFloorsBG": 0.0,
    "parkingAutoFloorsAG": 0.0,
    "parkingAutoFloorsBG": 0.0,
    "ftf": 3.2,
    "maxHeight": 120.0,

    "mainFloorPlate": 1500.0,
    "parkingConPlate": 1200.0,
    "parkingAutoPlate": 800.0,

    "bayConv": 25.0,
    "circConvPct": 0.0,
    "bayAuto": 16.0,
    "circAutoPct": 0.0,

    "openLotArea": 0.0,
    "openLotBay": 25.0,
    "openLotCircPct": 0.0,

    # Program/Efficiency based on GFA
    "publicPctOfGFA": 10.0,
    "nlaPctOfPublic": 40.0,  # NLA is a fraction of Public
    "bohPctOfGFA": 8.0,
    "servicePctOfGFA": 2.0,

    "countParkingInFAR": True,     # conventional parking only
    "countBasementInFAR": False,

    # coarse costs (฿/m²) & (฿/car)
    "costMainPerSqm": 30000.0,
    "costParkConvPerSqm": 18000.0,
    "costParkAutoPerSqm": 25000.0,
    "costGreenPerSqm": 4500.0,
    "costConventionalPerCar": 125000.0,
    "costAutoPerCar": 432000.0,
    "costOpenLotPerCar": 60000.0,

    "budget": 500_000_000.0,
    "customCosts": [],  # list of dicts: {name, kind: per_sqm|per_car_conv|per_car_auto|lump_sum, rate}
}

def ensure_defaults(s: dict) -> dict:
    out = dict(s)
    for k, v in DEFAULT.items():
        if k not in out:
            out[k] = float(v) if isinstance(v, (int, float)) else v
    return out
BUILDING_TYPES = ["Housing", "Hi-Rise", "Low-Rise", "Public Building", "Office Building", "Hotel"]
RULES = {
    "Housing": {"minOSR": 30, "greenPctOfOSR": None},
    "Hi-Rise": {"minOSR": 10, "greenPctOfOSR": 50},
    "Low-Rise": {"minOSR": 10, "greenPctOfOSR": 50},
    "Public Building": {"minOSR": None, "greenPctOfOSR": None},
    "Office Building": {"minOSR": None, "greenPctOfOSR": None},
    "Hotel": {"minOSR": 10, "greenPctOfOSR": 40},
}

# ---------------------------------
# Page chrome
# ---------------------------------
st.set_page_config(page_title="Feasibility (TH) — Streamlit", layout="wide")
def suggested_osr(bt): 
    return RULES.get(bt, {}).get("minOSR", 15)
def suggested_green(bt):
    g = RULES.get(bt, {}).get("greenPctOfOSR")
    return 40 if g is None else g

# ====================== Sidebar (Import/Export) ======================
with st.sidebar:
    st.title("⚙️ Settings")
    st.markdown("**Scenario Import/Export**")
    dl = st.download_button(
        "⬇️ Export CSV",
        data=create_csv_rows(DEFAULT),
        file_name="scenario_template.csv",
        mime="text/csv",
    )
    up = st.file_uploader("⬆️ Import CSV", type=["csv"], accept_multiple_files=False)
    scenario = DEFAULT.copy()
    if up is not None:
        try:
            parsed = parse_csv_to_dict(up.read().decode("utf-8"))
            scenario.update(parsed)
            st.success("Imported.")
        except Exception as e:
            st.error(f"Import failed: {e}")

st.markdown("""
<style>
:root {
  --bg:#111315; --panel:#1a1d21; --muted:#9aa4af; --text:#e6e9ed; --border:#2a2f35;
}
html, body, [data-testid="stAppViewContainer"] { background: var(--bg); color: var(--text); }
.block-container { padding-top: 0.8rem; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 14px; }
.small { color: var(--muted); font-size: 12px; }
.badge-ok { color: #22c55e; font-weight: 600; }
.badge-warn { color: #ef4444; font-weight: 600; }
.mono { font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
div[data-testid="stNumberInput"] input, select, textarea {
  background: var(--panel) !important; color: var(--text) !important; border: 1px solid var(--border) !important; border-radius: 10px !important;
}
div[data-testid="stMetric"] { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 10px; }
hr { border-color: var(--border) }
</style>
""", unsafe_allow_html=True)

st.title("Feasibility (TH) — Streamlit")

# ---------------------------------
# Session state
# ---------------------------------
if "scenario" not in st.session_state:
    st.session_state.scenario = DEFAULT.copy()
if "unit_types" not in st.session_state:
    # initial unit mix (editable)
    st.session_state.unit_types = [
        {"id": 1, "name": "1-BR", "size_sqm": 32.0, "bedrooms": 1.0, "count": 200},
        {"id": 2, "name": "2-BR", "size_sqm": 55.0, "bedrooms": 2.0, "count": 120},
        {"id": 3, "name": "2-BR Large", "size_sqm": 72.0, "bedrooms": 2.0, "count": 40},
    ]
if "id_seed" not in st.session_state:
    st.session_state.id_seed = 3

st.session_state.scenario = ensure_defaults(st.session_state.scenario)
s = st.session_state.scenario

# ---------------------------------
# Inputs
# ---------------------------------
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("#### Site & FAR")
    s["siteArea"] = st.number_input("Site Area (m²)", min_value=0.0, value=float(s.get("siteArea", DEFAULT["siteArea"])), step=100.0)
    s["far"]      = st.number_input("FAR (1–10)", min_value=RULES["base"]["farRange"][0], max_value=RULES["base"]["farRange"][1], value=float(s.get("far", DEFAULT["far"])), step=0.1)
    s["location"] = st.selectbox("Location (legal)", options=["BKK", "OUTSIDE"], index=0 if s.get("location","BKK")=="BKK" else 1)

with c2:
    st.markdown("#### Geometry & Height")
    g1, g2, g3 = st.columns(3)
    s["mainFloorsAG"] = g1.number_input("Main Floors (AG)", min_value=0.0, value=float(s.get("mainFloorsAG", DEFAULT["mainFloorsAG"])), step=1.0)
    s["mainFloorsBG"] = g2.number_input("Main Floors (BG)", min_value=0.0, value=float(s.get("mainFloorsBG", DEFAULT["mainFloorsBG"])), step=1.0)
    s["ftf"]          = g3.number_input("F2F (m)",          min_value=0.0, value=float(s.get("ftf", DEFAULT["ftf"])), step=0.1)

    g4, g5, g6 = st.columns(3)
    s["parkingConFloorsAG"] = g4.number_input("Park Conv (AG)", min_value=0.0, value=float(s.get("parkingConFloorsAG", DEFAULT["parkingConFloorsAG"])), step=1.0)
    s["parkingConFloorsBG"] = g5.number_input("Park Conv (BG)", min_value=0.0, value=float(s.get("parkingConFloorsBG", DEFAULT["parkingConFloorsBG"])), step=1.0)
    s["maxHeight"]          = g6.number_input("Max Height (m)", min_value=0.0, value=float(s.get("maxHeight", DEFAULT["maxHeight"])), step=1.0)

    g7, g8 = st.columns(2)
    s["parkingAutoFloorsAG"] = g7.number_input("Auto Park (AG)", min_value=0.0, value=float(s.get("parkingAutoFloorsAG", DEFAULT["parkingAutoFloorsAG"])), step=1.0)
    s["parkingAutoFloorsBG"] = g8.number_input("Auto Park (BG)", min_value=0.0, value=float(s.get("parkingAutoFloorsBG", DEFAULT["parkingAutoFloorsBG"])), step=1.0)

with c3:
    st.markdown("#### Parking & Efficiency")
    p1, p2, p3 = st.columns(3)
    s["bayConv"]     = p1.number_input("Conv Bay (m²)", min_value=1.0, value=float(s.get("bayConv", DEFAULT["bayConv"])), step=1.0)
    conv_circ_pct    = p2.number_input("Conv Circ (%)", min_value=0.0, max_value=100.0, value=float(s.get("circConvPct", DEFAULT["circConvPct"])) * 100.0, step=1.0)
    s["circConvPct"] = conv_circ_pct / 100.0
    p3.markdown(f'<div class="small">eff = <span class="mono">{nf(s["bayConv"]*(1+s["circConvPct"]))}</span> m²/คัน</div>', unsafe_allow_html=True)

    p4, p5, p6 = st.columns(3)
    s["bayAuto"]     = p4.number_input("Auto Bay (m²)", min_value=1.0, value=float(s.get("bayAuto", DEFAULT["bayAuto"])), step=1.0)
    auto_circ_pct    = p5.number_input("Auto Circ (%)", min_value=0.0, max_value=100.0, value=float(s.get("circAutoPct", DEFAULT["circAutoPct"])) * 100.0, step=1.0)
    s["circAutoPct"] = auto_circ_pct / 100.0
    p6.markdown(f'<div class="small">eff = <span class="mono">{nf(s["bayAuto"]*(1+s["circAutoPct"]))}</span> m²/คัน</div>', unsafe_allow_html=True)

    p7, p8, p9 = st.columns(3)
    s["openLotArea"]    = p7.number_input("Open-lot Area (m²)",   min_value=0.0, value=float(s.get("openLotArea", DEFAULT["openLotArea"])), step=50.0)
    s["openLotBay"]     = p8.number_input("Open-lot Bay (m²/คัน)",min_value=1.0, value=float(s.get("openLotBay", DEFAULT["openLotBay"])), step=1.0)
    open_circ_pct       = p9.number_input("Open-lot Circ (%)",    min_value=0.0, max_value=100.0, value=float(s.get("openLotCircPct", DEFAULT["openLotCircPct"])) * 100.0, step=1.0)
    s["openLotCircPct"] = open_circ_pct / 100.0
    st.caption(f"eff (open-lot) = {nf(s['openLotBay']*(1+s['openLotCircPct']))} m²/คัน")

st.divider()

cE1, cE2 = st.columns(2)
with cE1:
    st.markdown("#### Efficiency Blocks")
    e1, e2, e3, e4, e5 = st.columns(5)
    s["gfaOverCfaPct"]   = e1.number_input("GFA from CFA (%)",   min_value=0.0, max_value=100.0, value=float(s.get("gfaOverCfaPct", DEFAULT["gfaOverCfaPct"])), step=1.0)
    s["publicPctOfGFA"]  = e2.number_input("Public (% of GFA)",  min_value=0.0, max_value=100.0, value=float(s.get("publicPctOfGFA", DEFAULT["publicPctOfGFA"])), step=1.0)
    s["nlaPctOfPublic"]  = e3.number_input("NLA (% of Public)",  min_value=0.0, max_value=100.0, value=float(s.get("nlaPctOfPublic", DEFAULT["nlaPctOfPublic"])), step=1.0)
    s["bohPctOfGFA"]     = e4.number_input("BOH (% of GFA)",     min_value=0.0, max_value=100.0, value=float(s.get("bohPctOfGFA", DEFAULT["bohPctOfGFA"])), step=1.0)
    s["servicePctOfGFA"] = e5.number_input("Service (% of GFA)", min_value=0.0, max_value=100.0, value=float(s.get("servicePctOfGFA", DEFAULT["servicePctOfGFA"])), step=1.0)

with cE2:
    st.markdown("#### Costs (฿/m²) & Budget (coarse)")
    c1a, c1b, c1c, c1d = st.columns(4)
    s["costMainPerSqm"]     = c1a.number_input("Main",         min_value=0.0, value=float(s.get("costMainPerSqm", DEFAULT["costMainPerSqm"])), step=500.0)
    s["costParkConvPerSqm"] = c1b.number_input("Park Conv",    min_value=0.0, value=float(s.get("costParkConvPerSqm", DEFAULT["costParkConvPerSqm"])), step=500.0)
    s["costParkAutoPerSqm"] = c1c.number_input("Park Auto",    min_value=0.0, value=float(s.get("costParkAutoPerSqm", DEFAULT["costParkAutoPerSqm"])), step=500.0)
    s["budget"]             = c1d.number_input("Budget (฿)",   min_value=0.0, value=float(s.get("budget", DEFAULT["budget"])), step=1_000_000.0)

st.divider()

# ---------------------------------
# Derive core areas & parking supply
# ---------------------------------
far = clamp(s["far"], *RULES["base"]["farRange"])
maxGFA = s["siteArea"] * far

# CFA
mainCFA_AG    = s["mainFloorsAG"]    * s["mainFloorPlate"]
mainCFA_BG    = s["mainFloorsBG"]    * s["mainFloorPlate"]
parkConCFA_AG = s["parkingConFloorsAG"] * s["parkingConPlate"]
parkConCFA_BG = s["parkingConFloorsBG"] * s["parkingConPlate"]
parkAutoCFA_AG= s["parkingAutoFloorsAG"]* s["parkingAutoPlate"]
parkAutoCFA_BG= s["parkingAutoFloorsBG"]* s["parkingAutoPlate"]

mainCFA    = mainCFA_AG + mainCFA_BG
parkConCFA = parkConCFA_AG + parkConCFA_BG
parkAutoCFA= parkAutoCFA_AG + parkAutoCFA_BG
totalCFA   = mainCFA + parkConCFA + parkAutoCFA

# Height
    st.divider()
    st.caption("Theme: minimalist black/gray/white for architects 😉")

# ====================== Inputs ======================
st.title("🏗️ Feasibility — v1")

colA, colB = st.columns(2)
with colA:
    st.subheader("Site & Zoning")
    s = scenario
    s["siteArea"] = st.number_input("Site Area (m²)", min_value=0.0, value=float(s["siteArea"]), step=100.0)
    s["far"] = st.number_input("FAR (1–10)", min_value=1.0, max_value=10.0, value=float(s["far"]), step=0.1)
    s["bType"] = st.selectbox("Building Type", BUILDING_TYPES, index=max(0, BUILDING_TYPES.index(str(s["bType"])) if s.get("bType") in BUILDING_TYPES else 0))
    s["osr"] = st.number_input("OSR (%)", min_value=0.0, max_value=100.0, value=float(s["osr"]), step=1.0)
    s["greenPctOfOSR"] = st.number_input("Green (% of OSR)", min_value=0.0, max_value=100.0, value=float(s["greenPctOfOSR"]), step=1.0)

with colB:
    st.subheader("Geometry & Height")
    s["mainFloorsAG"] = st.number_input("Main Floors (AG)", min_value=0.0, value=float(s["mainFloorsAG"]), step=1.0)
    s["mainFloorsBG"] = st.number_input("Main Floors (BG)", min_value=0.0, value=float(s["mainFloorsBG"]), step=1.0)
    s["parkingConFloorsAG"] = st.number_input("Park Conv (AG)", min_value=0.0, value=float(s["parkingConFloorsAG"]), step=1.0)
    s["parkingConFloorsBG"] = st.number_input("Park Conv (BG)", min_value=0.0, value=float(s["parkingConFloorsBG"]), step=1.0)
    s["parkingAutoFloorsAG"] = st.number_input("Auto Park (AG)", min_value=0.0, value=float(s["parkingAutoFloorsAG"]), step=1.0)
    s["parkingAutoFloorsBG"] = st.number_input("Auto Park (BG)", min_value=0.0, value=float(s["parkingAutoFloorsBG"]), step=1.0)
    s["ftf"] = st.number_input("Floor-to-Floor (m)", min_value=0.0, value=float(s["ftf"]), step=0.1)
    s["maxHeight"] = st.number_input("Max Height (m)", min_value=0.0, value=float(s["maxHeight"]), step=1.0)

colC, colD = st.columns(2)
with colC:
    st.subheader("Plates & Parking Eff.")
    s["mainFloorPlate"] = st.number_input("Main Plate (m²)", min_value=0.0, value=float(s["mainFloorPlate"]), step=10.0)
    s["parkingConPlate"] = st.number_input("Park Plate (Conv) (m²)", min_value=0.0, value=float(s["parkingConPlate"]), step=10.0)
    s["parkingAutoPlate"] = st.number_input("Park Plate (Auto) (m²)", min_value=0.0, value=float(s["parkingAutoPlate"]), step=10.0)
    s["bayConv"] = st.number_input("Conv Bay (m²/car net)", min_value=1.0, value=float(s["bayConv"]), step=1.0)
    s["circConvPct"] = st.number_input("Conv Circ (%)", min_value=0.0, max_value=100.0, value=float(s["circConvPct"])*100.0, step=1.0)/100.0
    s["bayAuto"] = st.number_input("Auto Bay (m²/car net)", min_value=1.0, value=float(s["bayAuto"]), step=1.0)
    s["circAutoPct"] = st.number_input("Auto Circ (%)", min_value=0.0, max_value=100.0, value=float(s["circAutoPct"])*100.0, step=1.0)/100.0

with colD:
    st.subheader("Open-lot (at-grade)")
    s["openLotArea"] = st.number_input("Open-lot Area (m²)", min_value=0.0, value=float(s["openLotArea"]), step=50.0)
    s["openLotBay"] = st.number_input("Open-lot Bay (m²/car net)", min_value=1.0, value=float(s["openLotBay"]), step=1.0)
    s["openLotCircPct"] = st.number_input("Open-lot Circ (%)", min_value=0.0, max_value=100.0, value=float(s["openLotCircPct"])*100.0, step=1.0)/100.0

st.subheader("Program / Efficiency (based on GFA)")
e1, e2, e3, e4 = st.columns(4)
s["publicPctOfGFA"]  = e1.number_input("Public (% of GFA)",  min_value=0.0, max_value=100.0, value=float(s.get("publicPctOfGFA", 10.0)), step=1.0)
s["nlaPctOfPublic"]  = e2.number_input("NLA (% of Public)",  min_value=0.0, max_value=100.0, value=float(s.get("nlaPctOfPublic", 40.0)), step=1.0)
s["bohPctOfGFA"]     = e3.number_input("BOH (% of GFA)",     min_value=0.0, max_value=100.0, value=float(s.get("bohPctOfGFA", 8.0)), step=1.0)
s["servicePctOfGFA"] = e4.number_input("Service (% of GFA)", min_value=0.0, max_value=100.0, value=float(s.get("servicePctOfGFA", 2.0)), step=1.0)

st.subheader("FAR Rules")
f1, f2 = st.columns(2)
s["countParkingInFAR"]  = f1.selectbox("Count **Conventional** Parking in FAR?", ["Yes","No"], index=0 if bool(s["countParkingInFAR"]) else 1) == "Yes"
s["countBasementInFAR"] = f2.selectbox("Count Basement in FAR?", ["No","Yes"], index=1 if bool(s["countBasementInFAR"]) else 0) == "Yes"

st.subheader("Costs & Budget (THB)")
c1, c2, c3, c4 = st.columns(4)
s["costMainPerSqm"]       = c1.number_input("Architecture (฿/m²)", min_value=0.0, value=float(s["costMainPerSqm"]), step=100.0)
s["costParkConvPerSqm"]   = c2.number_input("Park Conv (฿/m²)",    min_value=0.0, value=float(s["costParkConvPerSqm"]), step=100.0)
s["costParkAutoPerSqm"]   = c3.number_input("Park Auto (฿/m²)",    min_value=0.0, value=float(s["costParkAutoPerSqm"]), step=100.0)
s["costGreenPerSqm"]      = c4.number_input("Green (฿/m²)",        min_value=0.0, value=float(s["costGreenPerSqm"]), step=50.0)

c5, c6, c7, c8 = st.columns(4)
s["costConventionalPerCar"] = c5.number_input("Conv (฿/car)", min_value=0.0, value=float(s["costConventionalPerCar"]), step=1000.0)
s["costAutoPerCar"]         = c6.number_input("Auto (฿/car)", min_value=0.0, value=float(s["costAutoPerCar"]), step=1000.0)
s["costOpenLotPerCar"]      = c7.number_input("Open-lot (฿/car)", min_value=0.0, value=float(s["costOpenLotPerCar"]), step=1000.0)
s["budget"]                 = c8.number_input("Budget (฿)", min_value=0.0, value=float(s["budget"]), step=100000.0)

# ====================== Compute ======================
# effective areas per car
eff_con = s["bayConv"] * (1.0 + s["circConvPct"])
eff_auto = s["bayAuto"] * (1.0 + s["circAutoPct"])
eff_open = s["openLotBay"] * (1.0 + s["openLotCircPct"])

# areas
mainCFA_AG = s["mainFloorsAG"] * s["mainFloorPlate"]
mainCFA_BG = s["mainFloorsBG"] * s["mainFloorPlate"]
pcCFA_AG   = s["parkingConFloorsAG"] * s["parkingConPlate"]
pcCFA_BG   = s["parkingConFloorsBG"] * s["parkingConPlate"]
paCFA_AG   = s["parkingAutoFloorsAG"] * s["parkingAutoPlate"]
paCFA_BG   = s["parkingAutoFloorsBG"] * s["parkingAutoPlate"]

mainCFA = mainCFA_AG + mainCFA_BG
parkConCFA = pcCFA_AG + pcCFA_BG
parkAutoCFA = paCFA_AG + paCFA_BG
totalCFA = mainCFA + parkConCFA + parkAutoCFA

# height
estHeight = s["ftf"] * (s["mainFloorsAG"] + s["parkingConFloorsAG"] + s["parkingAutoFloorsAG"])
heightOk = estHeight <= s["maxHeight"]

# Parking supply
effConv  = s["bayConv"] * (1 + s["circConvPct"])
effAuto  = s["bayAuto"] * (1 + s["circAutoPct"])
effOpen  = s["openLotBay"] * (1 + s["openLotCircPct"])
convCarsPerFloor = int(math.floor(s["parkingConPlate"] / max(1.0, effConv)))
autoCarsPerFloor = int(math.floor(s["parkingAutoPlate"] / max(1.0, effAuto)))
# parking supply
convCarsPerFloor = int(math.floor(s["parkingConPlate"] / max(1.0, eff_con))) if s["parkingConPlate"] > 0 else 0
autoCarsPerFloor = int(math.floor(s["parkingAutoPlate"] / max(1.0, eff_auto))) if s["parkingAutoPlate"] > 0 else 0
totalConvCars = convCarsPerFloor * int(s["parkingConFloorsAG"] + s["parkingConFloorsBG"])
totalAutoCars = autoCarsPerFloor * int(s["parkingAutoFloorsAG"] + s["parkingAutoFloorsBG"])
openLotCars   = int(math.floor(s["openLotArea"] / max(1.0, effOpen)))
openLotCars = int(math.floor(s["openLotArea"] / max(1.0, eff_open)))
totalCars = totalConvCars + totalAutoCars + openLotCars
disabledCars = calc_disabled_parking(totalCars)

# FAR counted (no open-lot)
# GFA (actual) policy:
#   mainCFA + parkConCFA (auto excluded; open-lot excluded)
gfa = mainCFA + parkConCFA

# Max GFA
maxGFA = s["siteArea"] * s["far"]

# FAR-counted (legal)
farCounted = compute_far_counted(
    mainCFA_AG, mainCFA_BG, parkConCFA_AG, parkConCFA_BG, parkAutoCFA_AG, parkAutoCFA_BG,
    s["countParkingInFAR"], s["countBasementInFAR"]
)
farOk = farCounted <= maxGFA

# Efficiency blocks to GFA/NSA/NLA
gfa = (s["gfaOverCfaPct"] / 100.0) * totalCFA
publicArea  = (s["publicPctOfGFA"]  / 100.0) * gfa
bohArea     = (s["bohPctOfGFA"]     / 100.0) * gfa
serviceArea = (s["servicePctOfGFA"] / 100.0) * gfa
nsa = gfa - (publicArea + bohArea + serviceArea)          # NSA excludes public/boh/service
nla = publicArea * (s["nlaPctOfPublic"] / 100.0)          # NLA is subset of Public

# DE ratios
de_NSA_over_GFA = (nsa / gfa) if gfa > 0 else 0.0
de_NSA_over_CFA = (nsa / totalCFA) if totalCFA > 0 else 0.0
de_GFA_over_CFA = (gfa / totalCFA) if totalCFA > 0 else 0.0
de_NLA_over_GFA = (nla / gfa) if gfa > 0 else 0.0

# Budget (coarse)
costMain     = mainCFA    * s["costMainPerSqm"]
costParkConv = parkConCFA * s["costParkConvPerSqm"]
costParkAuto = parkAutoCFA* s["costParkAutoPerSqm"]
projectCost  = costMain + costParkConv + costParkAuto
budgetOk     = (projectCost <= s["budget"]) if s["budget"] > 0 else True
overUnder    = projectCost - s["budget"] if s["budget"] > 0 else 0.0
overUnderPct = (overUnder / s["budget"] * 100.0) if s["budget"] > 0 else 0.0
avgPerGFA    = (projectCost / gfa) if gfa > 0 else 0.0
avgPerCFA    = (projectCost / totalCFA) if totalCFA > 0 else 0.0

# ---------------------------------
# Unit types (editable list: count/size/bedrooms)
# ---------------------------------
st.markdown("#### Unit Types")
to_del = []
for ut in st.session_state.unit_types:
    cN, cS, cB, cC, cD = st.columns([0.30, 0.18, 0.18, 0.18, 0.16])
    ut["name"]      = cN.text_input(f"Name #{ut['id']}", value=ut.get("name","Type"), key=f"name_{ut['id']}")
    ut["size_sqm"]  = cS.number_input(f"Size m² #{ut['id']}", min_value=1.0, value=float(ut.get("size_sqm", 30.0)), step=1.0, key=f"size_{ut['id']}")
    ut["bedrooms"]  = cB.number_input(f"Beds #{ut['id']}",    min_value=0.0, value=float(ut.get("bedrooms", 1.0)), step=0.5, key=f"bed_{ut['id']}")
    ut["count"]     = cC.number_input(f"Units #{ut['id']}",   min_value=0,   value=int(ut.get("count", 0)), step=1, key=f"cnt_{ut['id']}")
    if cD.button(f"🗑️ Remove #{ut['id']}", key=f"del_{ut['id']}"):
        to_del.append(ut["id"])
if to_del:
    st.session_state.unit_types = [x for x in st.session_state.unit_types if x["id"] not in to_del]
if st.button("➕ Add Unit Type"):
    st.session_state.id_seed += 1
    st.session_state.unit_types.append({"id": st.session_state.id_seed, "name": f"Type {st.session_state.id_seed}", "size_sqm": 30.0, "bedrooms": 1.0, "count": 0})

total_units = sum(int(u["count"]) for u in st.session_state.unit_types)
total_beds  = sum(float(u["bedrooms"]) * float(u["count"]) for u in st.session_state.unit_types)

# ---------------------------------
# Parking — Legal TH (max of two methods) + %Parking
# ---------------------------------
legal = legal_parking_th(s["location"], st.session_state.unit_types, gfa)
# (ถ้าต้องการเทียบ “เป้าตามเตียง” เพิ่มเองได้ เช่น prog_required_by_bed = total_beds * proj_per_bed)

# ---------------------------------
# Green area — TH
# ---------------------------------
g = green_th(
    units=st.session_state.unit_types,
    site_area=s["siteArea"],
    green_on_ground=float(s.get("greenOnGround", 0.0)),
    green_on_structure=float(s.get("greenOnStructure", 0.0)),
    mainCFA_AG, mainCFA_BG, pcCFA_AG, pcCFA_BG, paCFA_AG, paCFA_BG,
    bool(s["countParkingInFAR"]), bool(s["countBasementInFAR"])
)

# ---------------------------------
# Summary Cards
# ---------------------------------
cA, cB, cC = st.columns(3)

with cA:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Zoning / GFA**")
    st.metric("FAR Max (Max GFA) m²", nf(maxGFA, 2))
    st.metric("FAR-counted Area m²", nf(farCounted, 2))
    st.metric("GFA (actual) m²", nf(gfa, 2))
    st.markdown(f'<div class="{ "badge-ok" if farOk else "badge-warn"}">FAR check: {"OK" if farOk else "Exceeds"}</div>', unsafe_allow_html=True)
