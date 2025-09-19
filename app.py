import math
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# =============================
# Theme-ish CSS (mono minimal)
# =============================
st.set_page_config(page_title="Feasibility (TH) — Minimal Mono", layout="wide")
st.markdown("""
<style>
.block-container { padding-top: 1.0rem; padding-bottom: 2rem; }
.stApp header { background: transparent; }
.card {
  background: var(--secondary-background-color);
  border: 1px solid rgba(0,0,0,.08);
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 6px 16px rgba(0,0,0,.06);
}
.stButton>button { border-radius: 12px !important; padding: .55rem 1rem !important; font-weight: 600 !important; }
[data-testid="stMetricValue"] { font-weight: 700; }
.mono-muted { color: #4b5563; }
</style>
""", unsafe_allow_html=True)

# =============================
# Helpers
# =============================
def nf(n, digits=2):
    try:
        x = float(n)
        return f"{x:,.{digits}f}"
    except:
        return "–"

def clamp(v, lo, hi):
    return min(hi, max(lo, v))

def create_csv(rows):
    if not rows: return ""
    headers = list(rows[0].keys())
    lines = [",".join(headers)]
    for r in rows:
        lines.append(",".join(str(r.get(h, "")) for h in headers))
    return "\n".join(lines)

def calc_disabled_parking(total_cars:int)->int:
    if total_cars <= 0: return 0
    if total_cars <= 50: return 2
    if total_cars <= 100: return 3
    extra_hundreds = math.ceil((total_cars - 100)/100)
    return 3 + max(0, extra_hundreds)

def compute_far_counted(mainAG, mainBG, pcAG, pcBG, paAG, paBG, countParking, countBasement):
    far = 0.0
    far += mainAG + (mainBG if countBasement else 0.0)
    if countParking:
        far += pcAG + (pcBG if countBasement else 0.0)
        far += paAG + (paBG if countBasement else 0.0)
    return far

# =============================
# Rules / Defaults
# =============================
BUILDING_TYPES = ["Housing", "Hi-Rise", "Low-Rise", "Public Building", "Office Building", "Hotel"]
RULES = {
    "base": {"farRange": [1.0, 10.0]},
    "building": {
        "Housing": {"minOSR": 30.0, "greenPctOfOSR": None},
        "Hi-Rise": {"minOSR": 10.0, "greenPctOfOSR": 50.0},
        "Low-Rise": {"minOSR": 10.0, "greenPctOfOSR": 50.0},
        "Public Building": {"minOSR": None, "greenPctOfOSR": None},
        "Office Building": {"minOSR": None, "greenPctOfOSR": None},
        "Hotel": {"minOSR": 10.0, "greenPctOfOSR": 40.0},
    }
}

DEFAULT = dict(
    # Site & zoning
    siteArea=8000.0,
    far=5.0,
    bType="Housing",
    osr=30.0,
    greenPctOfOSR=40.0,

    # Dimensions & setbacks (for diagram + plate coverage mode)
    siteWidth=80.0, siteDepth=100.0,
    setbackFront=6.0, setbackRear=6.0, setbackSideL=3.0, setbackSideR=3.0,

    # Plate mode
    plateMode="Auto (coverage)",   # or "Manual"
    plateCoveragePct=80.0,         # % of buildable area

    # Geometry
    mainFloorsAG=20, mainFloorsBG=0,
    parkingConFloorsAG=3, parkingConFloorsBG=0,
    parkingAutoFloorsAG=0, parkingAutoFloorsBG=0,
    ftf=3.2, maxHeight=120.0,

    # Plates (m²) — used only if plateMode == "Manual"
    mainFloorPlate=1500.0,
    parkingConPlate=1200.0,
    parkingAutoPlate=800.0,

    # Parking efficiency (structured)
    bayConv=25.0,  circConvPct=0.0,
    bayAuto=16.0,  circAutoPct=0.0,

    # Open-lot (not FAR)
    openLotArea=0.0, openLotBay=25.0, openLotCircPct=0.0,

    # Efficiency ratios
    nlaPctOfCFA=70.0,
    nsaPctOfCFA=80.0,
    gfaOverCfaPct=95.0,

    # FAR toggles
    countParkingInFAR=True,
    countBasementInFAR=False,

    # Costs (THB)
    costArchPerSqm=16000.0,
    costStructPerSqm=22000.0,
    costMEPPerSqm=20000.0,
    costGreenPerSqm=4500.0,
    costConventionalPerCar=125000.0,
    costAutoPerCar=432000.0,
    costOpenLotPerCar=60000.0,

    customCosts=[{"name":"FF&E","kind":"lump_sum","rate":0.0}],  # editable
    budget=500_000_000.0,
)

def suggested_osr(btype:str)->float:
    r = RULES["building"].get(btype, {})
    return r["minOSR"] if r.get("minOSR") is not None else 15.0

def suggested_green_pct(btype:str)->float:
    r = RULES["building"].get(btype, {})
    return r["greenPctOfOSR"] if r.get("greenPctOfOSR") is not None else 40.0

# =============================
# Compute
# =============================
def compute(state:dict):
    # Buildable (for coverage & diagram)
    w = max(0.0, float(state["siteWidth"]))
    d = max(0.0, float(state["siteDepth"]))
    bw = max(0.0, w - (state["setbackSideL"] + state["setbackSideR"]))
    bd = max(0.0, d - (state["setbackFront"] + state["setbackRear"]))
    buildable_area = bw * bd

    # Main plate
    if state["plateMode"].startswith("Auto"):
        mainPlate = buildable_area * (state["plateCoveragePct"]/100.0)
    else:
        mainPlate = float(state["mainFloorPlate"])

    # Clamp FAR
    far = clamp(float(state["far"]), RULES["base"]["farRange"][0], RULES["base"]["farRange"][1])
    maxGFA = state["siteArea"] * far

    # OSR & Green
    openSpaceArea = (state["osr"]/100.0) * state["siteArea"]
    greenArea = (state["greenPctOfOSR"]/100.0) * openSpaceArea

    # CFA (structured)
    mainCFA_AG = state["mainFloorsAG"] * mainPlate
    mainCFA_BG = state["mainFloorsBG"] * mainPlate
    parkConCFA_AG = state["parkingConFloorsAG"] * state["parkingConPlate"]
    parkConCFA_BG = state["parkingConFloorsBG"] * state["parkingConPlate"]
    parkAutoCFA_AG = state["parkingAutoFloorsAG"] * state["parkingAutoPlate"]
    parkAutoCFA_BG = state["parkingAutoFloorsBG"] * state["parkingAutoPlate"]
    mainCFA = mainCFA_AG + mainCFA_BG
    parkConCFA = parkConCFA_AG + parkConCFA_BG
    parkAutoCFA = parkAutoCFA_AG + parkAutoCFA_BG
    totalCFA = mainCFA + parkConCFA + parkAutoCFA

    # Height
    estHeight = state["ftf"] * (state["mainFloorsAG"] + state["parkingConFloorsAG"] + state["parkingAutoFloorsAG"])
    heightOk = estHeight <= state["maxHeight"]

    # Parking (eff areas)
    effConv = state["bayConv"] * (1 + state["circConvPct"])
    effAuto = state["bayAuto"] * (1 + state["circAutoPct"])
    effOpen = state["openLotBay"] * (1 + state["openLotCircPct"])

    convCarsPerFloor = math.floor(state["parkingConPlate"] / max(1, effConv))
    autoCarsPerFloor = math.floor(state["parkingAutoPlate"] / max(1, effAuto))
    totalConvCars = convCarsPerFloor * (state["parkingConFloorsAG"] + state["parkingConFloorsBG"])
    totalAutoCars = autoCarsPerFloor * (state["parkingAutoFloorsAG"] + state["parkingAutoFloorsBG"])
    openLotCars = math.floor(state["openLotArea"] / max(1, effOpen))
    totalCars = totalConvCars + totalAutoCars + openLotCars
    disabledCars = calc_disabled_parking(totalCars)

    # FAR-counted (no open-lot)
    farCounted = compute_far_counted(
        mainCFA_AG, mainCFA_BG,
        parkConCFA_AG, parkConCFA_BG,
        parkAutoCFA_AG, parkAutoCFA_BG,
        state["countParkingInFAR"], state["countBasementInFAR"]
    )
    farOk = farCounted <= maxGFA

    # Eff areas
    nla = (state["nlaPctOfCFA"]/100.0) * totalCFA
    nsa = (state["nsaPctOfCFA"]/100.0) * totalCFA
    gfa = (state["gfaOverCfaPct"]/100.0) * totalCFA

    # Ratios
    ratio = dict(
        nla_cfa = (nla/totalCFA) if totalCFA>0 else 0.0,
        nsa_gfa = (nsa/gfa) if gfa>0 else 0.0,
        nsa_cfa = (nsa/totalCFA) if totalCFA>0 else 0.0,
        nla_gfa = (nla/gfa) if gfa>0 else 0.0
    )

    # Costs
    baseCostPerSqm = state["costArchPerSqm"] + state["costStructPerSqm"] + state["costMEPPerSqm"]
    constructionCost = totalCFA * baseCostPerSqm
    greenCost = greenArea * state["costGreenPerSqm"]
    parkingCost = (
        totalConvCars * state["costConventionalPerCar"] +
        totalAutoCars * state["costAutoPerCar"] +
        openLotCars   * state["costOpenLotPerCar"]
    )

    customCostTotal = 0.0
    for i in state.get("customCosts", []):
        kind = i.get("kind","lump_sum")
        rate = float(i.get("rate",0) or 0.0)
        if kind == "per_sqm":
            customCostTotal += rate * totalCFA
        elif kind == "per_car_conv":
            customCostTotal += rate * totalConvCars
        elif kind == "per_car_auto":
            customCostTotal += rate * totalAutoCars
        else:
            customCostTotal += rate

    capexTotal = constructionCost + greenCost + parkingCost + customCostTotal
    budgetOk = (capexTotal <= state["budget"]) if state["budget"]>0 else True

    # Legal
    rule = RULES["building"].get(state["bType"], {})
    osrOk = (state["osr"] >= rule.get("minOSR")) if (rule.get("minOSR") is not None) else True
    greenPctOk = (state["greenPctOfOSR"] >= rule.get("greenPctOfOSR")) if (rule.get("greenPctOfOSR") is not None) else True

    return {
        "buildable_area": buildable_area, "bw": bw, "bd": bd, "w": w, "d": d, "mainPlate": mainPlate,
        "maxGFA": maxGFA, "openSpaceArea": openSpaceArea, "greenArea": greenArea,
        "mainCFA_AG": mainCFA_AG, "mainCFA_BG": mainCFA_BG, "parkConCFA": parkConCFA, "parkAutoCFA": parkAutoCFA, "totalCFA": totalCFA,
        "estHeight": estHeight, "heightOk": heightOk,
        "convCarsPerFloor": convCarsPerFloor, "autoCarsPerFloor": autoCarsPerFloor,
        "totalConvCars": totalConvCars, "totalAutoCars": totalAutoCars, "openLotCars": openLotCars,
        "totalCars": totalCars, "disabledCars": disabledCars,
        "farCounted": farCounted, "farOk": farOk,
        "nla":nla, "nsa":nsa, "gfa":gfa, "ratio":ratio,
        "baseCostPerSqm": baseCostPerSqm, "constructionCost": constructionCost,
        "greenCost": greenCost, "parkingCost": parkingCost, "customCostTotal": customCostTotal,
        "capexTotal": capexTotal, "budgetOk": budgetOk, "osrOk": osrOk, "greenPctOk": greenPctOk
    }

# =============================
# SIDEBAR — Site (ติดกัน) & Zoning
# =============================
st.sidebar.header("Site & Zoning")
s = {**DEFAULT}

# วาง Site Area + ขนาดแปลง + Setbacks ใกล้กัน
colA, colB = st.sidebar.columns(2)
s["siteArea"] = colA.number_input("Site Area (m²)", min_value=0.0, value=float(DEFAULT["siteArea"]), step=100.0)
s["far"] = colB.number_input("FAR (1–10)", min_value=1.0, max_value=10.0, value=float(DEFAULT["far"]), step=0.1)

dim1, dim2 = st.sidebar.columns(2)
s["siteWidth"] = dim1.number_input("Width (m)", min_value=0.0, value=float(DEFAULT["siteWidth"]), step=1.0)
s["siteDepth"] = dim2.number_input("Depth (m)", min_value=0.0, value=float(DEFAULT["siteDepth"]), step=1.0)

sb1, sb2, sb3, sb4 = st.sidebar.columns(4)
s["setbackFront"] = sb1.number_input("Front", min_value=0.0, value=float(DEFAULT["setbackFront"]), step=0.5)
s["setbackRear"]  = sb2.number_input("Rear",  min_value=0.0, value=float(DEFAULT["setbackRear"]),  step=0.5)
s["setbackSideL"] = sb3.number_input("Side-L",min_value=0.0, value=float(DEFAULT["setbackSideL"]), step=0.5)
s["setbackSideR"] = sb4.number_input("Side-R",min_value=0.0, value=float(DEFAULT["setbackSideR"]), step=0.5)

s["bType"] = st.sidebar.selectbox("Building Type", BUILDING_TYPES, index=BUILDING_TYPES.index(DEFAULT["bType"]))
s["osr"] = st.sidebar.number_input("OSR (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["osr"]), step=1.0)
s["greenPctOfOSR"] = st.sidebar.number_input("Green (% of OSR)", min_value=0.0, max_value=100.0, value=float(DEFAULT["greenPctOfOSR"]), step=1.0)

st.sidebar.divider()
st.sidebar.subheader("Main Plate Mode")
s["plateMode"] = st.sidebar.selectbox("Mode", ["Auto (coverage)","Manual"], index=0)
if s["plateMode"].startswith("Auto"):
    s["plateCoveragePct"] = st.sidebar.slider("Coverage (% of buildable)", min_value=10, max_value=100, value=int(DEFAULT["plateCoveragePct"]), step=5)
else:
    s["mainFloorPlate"] = st.sidebar.number_input("Main Plate (m²)", min_value=0.0, value=float(DEFAULT["mainFloorPlate"]), step=10.0)

st.sidebar.divider()
st.sidebar.subheader("Geometry (floors & plates)")
g1, g2, g3 = st.sidebar.columns(3)
s["mainFloorsAG"] = g1.number_input("Main AG", min_value=0, value=int(DEFAULT["mainFloorsAG"]), step=1)
s["mainFloorsBG"] = g2.number_input("Main BG", min_value=0, value=int(DEFAULT["mainFloorsBG"]), step=1)
s["ftf"] = g3.number_input("F2F (m)", min_value=0.0, value=float(DEFAULT["ftf"]), step=0.1)

p1, p2 = st.sidebar.columns(2)
s["parkingConFloorsAG"] = p1.number_input("Park Conv AG", min_value=0, value=int(DEFAULT["parkingConFloorsAG"]), step=1)
s["parkingConFloorsBG"] = p2.number_input("Park Conv BG", min_value=0, value=int(DEFAULT["parkingConFloorsBG"]), step=1)
p3, p4 = st.sidebar.columns(2)
s["parkingAutoFloorsAG"] = p3.number_input("Park Auto AG", min_value=0, value=int(DEFAULT["parkingAutoFloorsAG"]), step=1)
s["parkingAutoFloorsBG"] = p4.number_input("Park Auto BG", min_value=0, value=int(DEFAULT["parkingAutoFloorsBG"]), step=1)

pl1, pl2 = st.sidebar.columns(2)
s["parkingConPlate"]  = pl1.number_input("Conv Plate (m²)", min_value=0.0, value=float(DEFAULT["parkingConPlate"]), step=10.0)
s["parkingAutoPlate"] = pl2.number_input("Auto Plate (m²)", min_value=0.0, value=float(DEFAULT["parkingAutoPlate"]), step=10.0)

st.sidebar.caption("FAR flags")
ff1, ff2 = st.sidebar.columns(2)
s["countParkingInFAR"]  = ff1.selectbox("Count Parking?", ["Yes","No"], index=0) == "Yes"
s["countBasementInFAR"] = ff2.selectbox("Count Basement?", ["Yes","No"], index=0) == "Yes"

st.sidebar.divider()
st.sidebar.subheader("Parking Efficiency")
e1, e2 = st.sidebar.columns(2)
s["bayConv"] = e1.number_input("Conv Bay (m²)", min_value=1.0, value=float(DEFAULT["bayConv"]), step=0.5)
s["circConvPct"] = e2.number_input("Conv Circ (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["circConvPct"])*100, step=1.0) / 100.0
s["bayAuto"] = e1.number_input("Auto Bay (m²)", min_value=1.0, value=float(DEFAULT["bayAuto"]), step=0.5, key="autobay")
s["circAutoPct"] = e2.number_input("Auto Circ (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["circAutoPct"])*100, step=1.0, key="autocirc") / 100.0

st.sidebar.caption("Open-lot (ไม่นับ FAR)")
o1, o2, o3 = st.sidebar.columns(3)
s["openLotArea"] = o1.number_input("Area (m²)", min_value=0.0, value=float(DEFAULT["openLotArea"]), step=10.0)
s["openLotBay"] = o2.number_input("Bay (m²/คัน)", min_value=1.0, value=float(DEFAULT["openLotBay"]), step=0.5)
s["openLotCircPct"] = o3.number_input("Circ (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["openLotCircPct"])*100, step=1.0) / 100.0

st.sidebar.divider()
st.sidebar.subheader("Costs & Budget (THB)")
c1, c2 = st.sidebar.columns(2)
s["costArchPerSqm"] = c1.number_input("Architecture (฿/m²)", min_value=0.0, value=float(DEFAULT["costArchPerSqm"]), step=100.0)
s["costStructPerSqm"] = c2.number_input("Structure (฿/m²)",  min_value=0.0, value=float(DEFAULT["costStructPerSqm"]), step=100.0)
s["costMEPPerSqm"]   = c1.number_input("MEP (฿/m²)",         min_value=0.0, value=float(DEFAULT["costMEPPerSqm"]),   step=100.0)
s["costGreenPerSqm"] = c2.number_input("Green (฿/m²)",       min_value=0.0, value=float(DEFAULT["costGreenPerSqm"]), step=100.0)
s["costConventionalPerCar"] = c1.number_input("Parking Conv (฿/car)", min_value=0.0, value=float(DEFAULT["costConventionalPerCar"]), step=1000.0)
s["costAutoPerCar"]         = c2.number_input("Parking Auto (฿/car)", min_value=0.0, value=float(DEFAULT["costAutoPerCar"]),         step=1000.0)
s["costOpenLotPerCar"]      = c1.number_input("Parking Open-lot (฿/car)", min_value=0.0, value=float(DEFAULT["costOpenLotPerCar"]),  step=1000.0)
s["budget"] = st.sidebar.number_input("Budget (฿)", min_value=0.0, value=float(DEFAULT["budget"]), step=1_000_000.0)

st.sidebar.caption("Additional Cost Items")
default_rows = pd.DataFrame(s.get("customCosts") or [], columns=["name","kind","rate"])
if default_rows.empty:
    default_rows = pd.DataFrame([{"name":"FF&E","kind":"lump_sum","rate":0.0}])
edited = st.sidebar.data_editor(
    default_rows,
    column_config={
        "name": st.column_config.TextColumn("Name", width="medium"),
        "kind": st.column_config.SelectboxColumn("Kind", options=["per_sqm","per_car_conv","per_car_auto","lump_sum"]),
        "rate": st.column_config.NumberColumn("Rate", step=100.0, format="%.2f"),
    },
    num_rows="dynamic",
    use_container_width=True,
    key="custom_costs_editor"
)
s["customCosts"] = edited.to_dict("records")

# =============================
# Compute
# =============================
d = compute(s)

# =============================
# Header metrics
# =============================
st.title("🏗️ Feasibility (TH) — Minimal Mono")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Max GFA (m²)", nf(d["maxGFA"]))
m2.metric("FAR-counted (m²)", nf(d["farCounted"]))
m3.metric("Est. Height (m)", nf(d["estHeight"]), delta=("OK" if d["heightOk"] else "Exceeds"))
m4.metric("CAPEX (฿)", nf(d["capexTotal"]), delta=("OK" if d["budgetOk"] else "Over Budget"))

# =============================
# Zoning / Areas / Parking
# =============================
z1, z2, z3 = st.columns(3)
with z1:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Zoning")
    st.write(f"Open Space (OSR): **{nf(d['openSpaceArea'])}** m² ({s['osr']}%)")
    st.write(f"Green: **{nf(d['greenArea'])}** m² ({s['greenPctOfOSR']}% of OSR)")
    st.write(f"FAR check: {'✅ OK' if d['farOk'] else '❌ Exceeds Max GFA'}")
    st.markdown('</div>', unsafe_allow_html=True)

with z2:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Areas")
    st.write(f"Main CFA (AG): **{nf(d['mainCFA_AG'])}** m²")
    st.write(f"Main CFA (BG): **{nf(d['mainCFA_BG'])}** m²")
    st.write(f"Parking CFA (Conv): **{nf(d['parkConCFA'])}** m²")
    st.write(f"Parking CFA (Auto): **{nf(d['parkAutoCFA'])}** m²")
    st.write(f"Total CFA: **{nf(d['totalCFA'])}** m²")
    # Efficiency ratios
    st.markdown("---")
    st.caption("Efficiency Ratios")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("NLA / CFA", f"{d['ratio']['nla_cfa']*100:.1f}%")
    r2.metric("NSA / GFA", f"{d['ratio']['nsa_gfa']*100:.1f}%")
    r3.metric("NSA / CFA", f"{d['ratio']['nsa_cfa']*100:.1f}%")
    r4.metric("NLA / GFA", f"{d['ratio']['nla_gfa']*100:.1f}%")
    st.markdown('</div>', unsafe_allow_html=True)

with z3:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Parking")
    st.write(f"Cars/Floor (Conv): **{d['convCarsPerFloor']}** (eff {nf(s['bayConv']*(1+s['circConvPct']))} m²/car)")
    st.write(f"Cars/Floor (Auto): **{d['autoCarsPerFloor']}** (eff {nf(s['bayAuto']*(1+s['circAutoPct']))} m²/car)")
    st.write(f"Open-lot Cars: **{d['openLotCars']}** (eff {nf(s['openLotBay']*(1+s['openLotCircPct']))} m²/car)")
    st.write(f"Total Cars: **{d['totalCars']}** · Disabled: **{d['disabledCars']}**")
    st.markdown('</div>', unsafe_allow_html=True)

# =============================
# CAPEX Breakdown (mono palette)
# =============================
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("CAPEX Breakdown")
capex_df = pd.DataFrame([
    {"name":"Construction","value":max(0,d["constructionCost"])},
    {"name":"Green","value":max(0,d["greenCost"])},
    {"name":"Parking","value":max(0,d["parkingCost"])},
    {"name":"Custom","value":max(0,d["customCostTotal"])},
])
COLOR_MAP = {
    "Construction":"#111827", # almost-black
    "Green":"#6b7280",       # gray 500
    "Parking":"#9ca3af",     # gray 400
    "Custom":"#d1d5db",      # gray 300
}
fig = px.pie(capex_df, values="value", names="name", hole=0.45, color="name", color_discrete_map=COLOR_MAP)
fig.update_layout(template="plotly_white", margin=dict(l=10,r=10,t=10,b=10))
st.plotly_chart(fig, use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# =============================
# Site & Setbacks Diagram (+ Green area overlay)
# =============================
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Site & Setbacks Diagram (Green overlay)")
if d["w"]>0 and d["d"]>0:
    fig2 = go.Figure()
    # Site rect
    fig2.add_shape(type="rect", x0=0, y0=0, x1=d["w"], y1=d["d"],
                   line=dict(color="#111827"), fillcolor="#ffffff")
    # Buildable rect
    bx0, by0 = s["setbackSideL"], s["setbackFront"]
    bx1, by1 = max(bx0, d["w"]-s["setbackSideR"]), max(by0, d["d"]-s["setbackRear"])
    fig2.add_shape(type="rect", x0=bx0, y0=by0, x1=bx1, y1=by1,
                   line=dict(color="#6b7280"), fillcolor="#e5e7eb")
    # OSR rect (centered proportionally to site; simple visualization)
    osr_ratio = clamp(s["osr"]/100.0, 0.0, 1.0)
    osrW = d["w"] * (osr_ratio ** 0.5)
    osrD = d["d"] * (osr_ratio ** 0.5)
    cx, cy = d["w"]/2, d["d"]/2
    ox0, oy0 = cx-osrW/2, cy-osrD/2
    ox1, oy1 = cx+osrW/2, cy+osrD/2
    fig2.add_shape(type="rect", x0=ox0, y0=oy0, x1=ox1, y1=oy1,
                   line=dict(color="#6b7280"), fillcolor="#d1d5db")
    # Green area (subset inside OSR)
    green_ratio = 0.0
    if s["osr"]>0:
        green_ratio = clamp(d["greenArea"] / max(1e-9, d["openSpaceArea"]), 0.0, 1.0)
    gW = osrW * (green_ratio ** 0.5)
    gD = osrD * (green_ratio ** 0.5)
    gx0, gy0 = cx-gW/2, cy-gD/2
    gx1, gy1 = cx+gW/2, cy+gD/2
    fig2.add_shape(type="rect", x0=gx0, y0=gy0, x1=gx1, y1=gy1,
                   line=dict(color="#16a34a"), fillcolor="#86efac")
    # Labels
    fig2.add_annotation(x=d["w"]/2, y=d["d"]+0.6, showarrow=False,
                        text=f"Site: {nf(s['siteArea'])} m²  •  Buildable: {nf(d['buildable_area'])} m²  •  Main Plate: {nf(d['mainPlate'])} m²")
    fig2.update_xaxes(range=[-1, d["w"]+1], visible=False)
    fig2.update_yaxes(range=[-1, d["d"]+1], scaleanchor="x", scaleratio=1, visible=False)
    fig2.update_layout(height=360, template="plotly_white", margin=dict(l=10,r=10,t=10,b=10))
    st.plotly_chart(fig2, use_container_width=True)

    # Note about area mismatch (width*depth vs siteArea)
    area_dims = d["w"]*d["d"]
    if abs(area_dims - s["siteArea"]) > 1e-6:
        st.caption("⚠️ Width×Depth ไม่เท่ากับ Site Area — ใช้เพื่อสเกลภาพเท่านั้น (การคำนวณยึด Site Area เป็นหลัก)")
else:
    st.info("กรอก Width/Depth เพื่อดูแผนภาพ Setbacks + Green Area overlay")
st.markdown('</div>', unsafe_allow_html=True)

# =============================
# Export / Import (CSV Field,Value) + JSON fields
# =============================
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Export / Import")
export_rows = []
for k, v in s.items():
    if isinstance(v, (list, dict)):
        export_rows.append({"Field": k, "Value": json.dumps(v, ensure_ascii=False)})
    else:
        export_rows.append({"Field": k, "Value": v})
csv_str = create_csv(export_rows)
cA, cB = st.columns(2)
cA.download_button("⬇️ Export CSV", data=csv_str, file_name="scenario.csv", mime="text/csv")

template_rows = [{"Field": k, "Value": DEFAULT[k] if not isinstance(DEFAULT[k], (list,dict)) else json.dumps(DEFAULT[k], ensure_ascii=False)} for k in DEFAULT.keys()]
template_csv = create_csv(template_rows)
cB.download_button("⬇️ Download CSV Template", data=template_csv, file_name="scenario_template.csv", mime="text/csv")

up = st.file_uploader("⬆️ Import CSV (Field,Value)", type=["csv"])
if up is not None:
    try:
        df = pd.read_csv(up)
        imported = {}
        for _, row in df.iterrows():
            k = str(row["Field"])
            v = row["Value"]
            # JSON?
            if isinstance(v, str) and v.strip().startswith(("{","[")):
                try:
                    imported[k] = json.loads(v)
                    continue
                except:
                    pass
            # numeric?
            try:
                if "." in str(v) or "e" in str(v).lower():
                    imported[k] = float(v)
                else:
                    imported[k] = int(v)
            except:
                imported[k] = v
        st.success("Imported (preview). แก้ DEFAULT เองในโค้ดถ้าต้องการตั้งเป็นค่าเริ่มต้นถาวร")
        st.json(imported)
    except Exception as e:
        st.error(f"Import failed: {e}")
st.markdown('</div>', unsafe_allow_html=True)

# =============================
# Self-check tests (essential)
# =============================
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Self-check Tests")
def trow(name, actual, expected):
    ok = (actual == expected)
    st.write(("✅" if ok else "❌") + f" **{name}** — actual: `{actual}`  expected: `{expected}`")

trow("calcDisabledParking(0)",   calc_disabled_parking(0),   0)
trow("calcDisabledParking(50)",  calc_disabled_parking(50),  2)
trow("calcDisabledParking(51)",  calc_disabled_parking(51),  3)
trow("calcDisabledParking(100)", calc_disabled_parking(100), 3)
trow("calcDisabledParking(101)", calc_disabled_parking(101), 4)
trow("calcDisabledParking(250)", calc_disabled_parking(250), 5)

mAG = s["mainFloorsAG"] * (d["mainPlate"])
mBG = s["mainFloorsBG"] * (d["mainPlate"])
pcAG = s["parkingConFloorsAG"] * s["parkingConPlate"]
pcBG = s["parkingConFloorsBG"] * s["parkingConPlate"]
paAG = s["parkingAutoFloorsAG"] * s["parkingAutoPlate"]
paBG = s["parkingAutoFloorsBG"] * s["parkingAutoPlate"]
far_expected = compute_far_counted(mAG, mBG, pcAG, pcBG, paAG, paBG, s["countParkingInFAR"], s["countBasementInFAR"])
trow("computeFarCounted(default flags)", round(d["farCounted"]), round(far_expected))
trow("openLotCars formula", d["openLotCars"], math.floor(s["openLotArea"]/max(1, s["openLotBay"]*(1+s["openLotCircPct"]))))

st.markdown('</div>', unsafe_allow_html=True)
