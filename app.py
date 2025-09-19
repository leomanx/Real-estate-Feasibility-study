# app.py — Real Estate Feasibility v1 (Streamlit)
# Requirements:
#   pip install streamlit pandas numpy

import math
import json
from dataclasses import dataclass, asdict
from typing import List, Dict

import streamlit as st

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
        n = float(num)
        return f"{n:,.{digits}f}"
    except Exception:
        return "–"

def clamp(v, lo, hi):
    return min(hi, max(lo, v))

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
    far += mainAG + (mainBG if count_basement else 0.0)
    if count_parking:
        far += pcAG + (pcBG if count_basement else 0.0)
    # auto (paAG/paBG) excluded from FAR by policy
    return far

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

BUILDING_TYPES = ["Housing", "Hi-Rise", "Low-Rise", "Public Building", "Office Building", "Hotel"]
RULES = {
    "Housing": {"minOSR": 30, "greenPctOfOSR": None},
    "Hi-Rise": {"minOSR": 10, "greenPctOfOSR": 50},
    "Low-Rise": {"minOSR": 10, "greenPctOfOSR": 50},
    "Public Building": {"minOSR": None, "greenPctOfOSR": None},
    "Office Building": {"minOSR": None, "greenPctOfOSR": None},
    "Hotel": {"minOSR": 10, "greenPctOfOSR": 40},
}

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

# parking supply
convCarsPerFloor = int(math.floor(s["parkingConPlate"] / max(1.0, eff_con))) if s["parkingConPlate"] > 0 else 0
autoCarsPerFloor = int(math.floor(s["parkingAutoPlate"] / max(1.0, eff_auto))) if s["parkingAutoPlate"] > 0 else 0
totalConvCars = convCarsPerFloor * int(s["parkingConFloorsAG"] + s["parkingConFloorsBG"])
totalAutoCars = autoCarsPerFloor * int(s["parkingAutoFloorsAG"] + s["parkingAutoFloorsBG"])
openLotCars = int(math.floor(s["openLotArea"] / max(1.0, eff_open)))
totalCars = totalConvCars + totalAutoCars + openLotCars
disabledCars = calc_disabled_parking(totalCars)

# GFA (actual) policy:
#   mainCFA + parkConCFA (auto excluded; open-lot excluded)
gfa = mainCFA + parkConCFA

# Max GFA
maxGFA = s["siteArea"] * s["far"]

# FAR-counted (legal)
farCounted = compute_far_counted(
    mainCFA_AG, mainCFA_BG, pcCFA_AG, pcCFA_BG, paCFA_AG, paCFA_BG,
    bool(s["countParkingInFAR"]), bool(s["countBasementInFAR"])
)

# FAR check uses GFA (simple rule)
farOk = gfa <= maxGFA

# OSR & green
openSpaceArea = (s["osr"]/100.0) * s["siteArea"]
greenArea = (s["greenPctOfOSR"]/100.0) * openSpaceArea

# Program/Efficiency (from GFA)
publicArea  = (s["publicPctOfGFA"]/100.0) * gfa
bohArea     = (s["bohPctOfGFA"]/100.0) * gfa
serviceArea = (s["servicePctOfGFA"]/100.0) * gfa
nsa = max(0.0, gfa - (publicArea + bohArea + serviceArea))
nla = (s["nlaPctOfPublic"]/100.0) * publicArea

# Ratios (DE)
deNSA_GFA = (nsa / gfa) if gfa > 0 else 0.0
deNSA_CFA = (nsa / totalCFA) if totalCFA > 0 else 0.0
deGFA_CFA = (gfa / totalCFA) if totalCFA > 0 else 0.0
deNLA_GFA = (nla / gfa) if gfa > 0 else 0.0

# Costs (coarse)
costMain = mainCFA * s["costMainPerSqm"]
costParkConv = parkConCFA * s["costParkConvPerSqm"]
costParkAuto = parkAutoCFA * s["costParkAutoPerSqm"]
greenCost = greenArea * s["costGreenPerSqm"]

customCosts: List[Dict] = s.get("customCosts", []) if isinstance(s.get("customCosts", []), list) else []
customTotal = 0.0
for i in customCosts:
    kind = i.get("kind", "lump_sum")
    rate = float(i.get("rate", 0.0))
    if kind == "per_sqm":       customTotal += rate * totalCFA
    elif kind == "per_car_conv": customTotal += rate * totalConvCars
    elif kind == "per_car_auto": customTotal += rate * totalAutoCars
    else:                        customTotal += rate

capexTotal = costMain + costParkConv + costParkAuto + greenCost + customTotal
budgetOk = capexTotal <= s["budget"] if s["budget"] > 0 else True

# ====================== Key Metrics ======================
m1, m2, m3 = st.columns(3)
m1.metric("FAR Max (Max GFA) m²", nf(maxGFA), None)
m2.metric("GFA (actual) m²", nf(gfa), "OK" if farOk else "Exceeds")
m3.metric("Total CFA m²", nf(totalCFA), f"GFA/CFA {nf(deGFA_CFA,3)}")

# ====================== Tabs ======================
tabs = st.tabs(["Zoning / GFA", "Areas", "Parking", "Program & DE", "Costs", "Diagnostics"])

with tabs[0]:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Zoning / GFA")
    st.write(f"**FAR-counted (legal)** m²: {nf(farCounted)}  \n"
             f"**Open Space (OSR)** m²: {nf(openSpaceArea)} ({nf(s['osr'],0)}%)  \n"
             f"**Green Area** m²: {nf(greenArea)} ({nf(s['greenPctOfOSR'],0)}% of OSR)")
    st.markdown(f"**FAR check:** {'✅ OK' if farOk else '❌ Exceeds Max GFA'}")
    st.markdown("</div>", unsafe_allow_html=True)

with tabs[1]:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Areas")
    st.write(f"- Main CFA (AG): **{nf(mainCFA_AG)}** m²")
    st.write(f"- Main CFA (BG): **{nf(mainCFA_BG)}** m²")
    st.write(f"- Parking CFA (Conventional): **{nf(parkConCFA)}** m²")
    st.write(f"- Parking CFA (Auto): **{nf(parkAutoCFA)}** m² _(NOT GFA)_")
    st.write(f"- **Total CFA**: **{nf(totalCFA)}** m²")
    st.write(f"- **GFA (actual)**: **{nf(gfa)}** m² _(main + conventional parking; auto & open-lot excluded)_")
    st.markdown("</div>", unsafe_allow_html=True)

with tabs[2]:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Parking")
    st.write(f"- Cars/Floor (Conv): **{convCarsPerFloor}** (eff {nf(eff_con)} m²/car)")
    st.write(f"- Cars/Floor (Auto): **{autoCarsPerFloor}** (eff {nf(eff_auto)} m²/car)")
    st.write(f"- Open-lot Cars: **{openLotCars}** (eff {nf(eff_open)} m²/car)")
    st.write(f"- Total Cars (Conv): **{totalConvCars}**")
    st.write(f"- Total Cars (Auto): **{totalAutoCars}**")
    st.write(f"- **Total Cars**: **{totalCars}**")
    st.write(f"- Disabled Spaces (calc): **{disabledCars}**")
    st.markdown("</div>", unsafe_allow_html=True)

with tabs[3]:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Program & Design Efficiency")
    st.write(f"- Public area: **{nf(publicArea)}** m²  \n"
             f"- BOH: **{nf(bohArea)}** m²  \n"
             f"- Service: **{nf(serviceArea)}** m²  \n"
             f"- **NSA**: **{nf(nsa)}** m²  \n"
             f"- **NLA** (as % of Public): **{nf(nla)}** m²")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("NSA / GFA", nf(deNSA_GFA,3))
    r2.metric("NSA / CFA", nf(deNSA_CFA,3))
    r3.metric("GFA / CFA", nf(deGFA_CFA,3))
    r4.metric("NLA / GFA", nf(deNLA_GFA,3))
    st.caption("หมายเหตุ: NLA คิดเป็นสัดส่วนของพื้นที่ Public (NLA ⊂ Public)")
    st.markdown("</div>", unsafe_allow_html=True)

with tabs[4]:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Costs & Budget (coarse)")
    st.write(f"- Main: **฿{nf(costMain)}**")
    st.write(f"- Park (Conv): **฿{nf(costParkConv)}**")
    st.write(f"- Park (Auto): **฿{nf(costParkAuto)}**")
    st.write(f"- Green: **฿{nf(greenCost)}**")
    if customCosts:
        st.write(f"- Custom items: **฿{nf(customTotal)}**")
    st.write(f"**Total CAPEX: ฿{nf(capexTotal)}**")
    st.write(f"**Budget:** ฿{nf(s['budget'])} → "
             f"{'✅ ภายในงบ' if budgetOk else '❌ เกินงบ'}")
    if s["budget"] > 0:
        delta_amt = capexTotal - s["budget"]
        delta_pct = (delta_amt / s["budget"]) * 100.0
        st.write(f"Δ vs Budget: **฿{nf(delta_amt)}** ({nf(delta_pct,1)}%)")
    st.markdown("</div>", unsafe_allow_html=True)

with tabs[5]:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Diagnostics")
    # quick tests
    tests = []
    far_expected = compute_far_counted(
        mainCFA_AG, mainCFA_BG, pcCFA_AG, pcCFA_BG, paCFA_AG, paCFA_BG,
        s["countParkingInFAR"], s["countBasementInFAR"]
    )
    tests.append(("FAR-counted (expected) = computed", abs(far_expected - farCounted) < 1e-6))
    gfa_expected = (mainCFA + parkConCFA)  # auto excluded
    tests.append(("GFA excludes auto parking", abs(gfa - gfa_expected) < 1e-6))
    tests.append(("0 ≤ GFA/CFA ≤ 1", 0 - 1e-9 <= deGFA_CFA <= 1 + 1e-9))
    tests.append(("0 ≤ NSA/GFA ≤ 1", 0 - 1e-9 <= deNSA_GFA <= 1 + 1e-9))
    tests.append(("0 ≤ NSA/CFA ≤ 1", 0 - 1e-9 <= deNSA_CFA <= 1 + 1e-9))
    tests.append(("0 ≤ NLA/GFA ≤ 1", 0 - 1e-9 <= deNLA_GFA <= 1 + 1e-9))
    for name, ok in tests:
        st.write(("✅ " if ok else "❌ ") + name)
    st.markdown("</div>", unsafe_allow_html=True)
