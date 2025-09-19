# app.py
import math
import io
import json
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

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
    if not rows:
        return ""
    headers = list(rows[0].keys())
    lines = [",".join(headers)]
    for r in rows:
        lines.append(",".join(str(r.get(h, "")) for h in headers))
    return "\n".join(lines)

def calc_disabled_parking(total_cars):
    if total_cars <= 0: return 0
    if total_cars <= 50: return 2
    if total_cars <= 100: return 3
    extra_hundreds = math.ceil((total_cars - 100) / 100)
    return 3 + max(0, extra_hundreds)

def compute_far_counted(mainAG, mainBG, pcAG, pcBG, paAG, paBG, countParking, countBasement):
    far = 0
    far += mainAG + (mainBG if countBasement else 0)
    if countParking:
        far += pcAG + (pcBG if countBasement else 0)
        far += paAG + (paBG if countBasement else 0)
    return far

# =============================
# Rules / Defaults
# =============================
BUILDING_TYPES = ["Housing", "Hi-Rise", "Low-Rise", "Public Building", "Office Building", "Hotel"]
RULES = {
    "base": { "farRange": [1, 10] },
    "building": {
        "Housing": {"minOSR": 30, "greenPctOfOSR": None},
        "Hi-Rise": {"minOSR": 10, "greenPctOfOSR": 50},
        "Low-Rise": {"minOSR": 10, "greenPctOfOSR": 50},
        "Public Building": {"minOSR": None, "greenPctOfOSR": None},
        "Office Building": {"minOSR": None, "greenPctOfOSR": None},
        "Hotel": {"minOSR": 10, "greenPctOfOSR": 40},
    }
}

DEFAULT = dict(
    # Core site & zoning
    siteArea=8000.0,
    far=5.0,
    bType="Housing",
    osr=30.0,
    greenPctOfOSR=40.0,

    # Geometry
    mainFloorsAG=20, mainFloorsBG=0,
    parkingConFloorsAG=3, parkingConFloorsBG=0,
    parkingAutoFloorsAG=0, parkingAutoFloorsBG=0,
    ftf=3.2, maxHeight=120.0,

    # Plates (m²)
    mainFloorPlate=1500.0,
    parkingConPlate=1200.0,
    parkingAutoPlate=800.0,

    # Parking efficiency (structured)
    bayConv=25.0,    circConvPct=0.0,
    bayAuto=16.0,    circAutoPct=0.0,

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

    # Custom cost table (editable)
    customCosts=[],

    # Budget
    budget=500_000_000.0,

    # --- New: Site dims & setbacks (for diagram; siteArea is authoritative) ---
    siteWidth=80.0,    # m
    siteDepth=100.0,   # m
    setbackFront=6.0,  # m
    setbackRear=6.0,   # m
    setbackSideL=3.0,  # m
    setbackSideR=3.0,  # m
)

# =============================
# Compute block
# =============================
def compute(state: dict):
    far_min, far_max = RULES["base"]["farRange"]
    far = clamp(float(state["far"]), far_min, far_max)
    maxGFA = state["siteArea"] * far

    # OSR & Green
    openSpaceArea = (state["osr"] / 100.0) * state["siteArea"]
    greenArea = (state["greenPctOfOSR"] / 100.0) * openSpaceArea

    # CFA
    mainCFA_AG = state["mainFloorsAG"] * state["mainFloorPlate"]
    mainCFA_BG = state["mainFloorsBG"] * state["mainFloorPlate"]
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

    # Parking eff area / car
    effAreaConCar  = state["bayConv"] * (1 + state["circConvPct"])
    effAreaAutoCar = state["bayAuto"] * (1 + state["circAutoPct"])
    effAreaOpenCar = state["openLotBay"] * (1 + state["openLotCircPct"])

    convCarsPerFloor = math.floor(state["parkingConPlate"] / max(1, effAreaConCar))
    autoCarsPerFloor = math.floor(state["parkingAutoPlate"] / max(1, effAreaAutoCar))

    totalConvCars = convCarsPerFloor * (state["parkingConFloorsAG"] + state["parkingConFloorsBG"])
    totalAutoCars = autoCarsPerFloor * (state["parkingAutoFloorsAG"] + state["parkingAutoFloorsBG"])
    openLotCars   = math.floor(state["openLotArea"] / max(1, effAreaOpenCar))

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

    # Efficiency (areas)
    nla = (state["nlaPctOfCFA"] / 100.0) * totalCFA
    nsa = (state["nsaPctOfCFA"] / 100.0) * totalCFA
    gfa = (state["gfaOverCfaPct"] / 100.0) * totalCFA

    # Ratios (requested)
    ratio_nla_cfa = nla / totalCFA if totalCFA > 0 else 0
    ratio_nsa_gfa = nsa / gfa if gfa > 0 else 0
    ratio_nsa_cfa = nsa / totalCFA if totalCFA > 0 else 0
    ratio_nla_gfa = nla / gfa if gfa > 0 else 0

    # Costs
    baseCostPerSqm = state["costArchPerSqm"] + state["costStructPerSqm"] + state["costMEPPerSqm"]
    constructionCost = totalCFA * baseCostPerSqm
    greenCost = greenArea * state["costGreenPerSqm"]
    parkingCost = (
        totalConvCars * state["costConventionalPerCar"] +
        totalAutoCars * state["costAutoPerCar"] +
        openLotCars   * state["costOpenLotPerCar"]
    )

    # Custom costs
    customCostTotal = 0.0
    for i in state.get("customCosts", []):
        kind = i.get("kind", "lump_sum")
        rate = float(i.get("rate", 0.0) or 0.0)
        if kind == "per_sqm":
            customCostTotal += rate * totalCFA
        elif kind == "per_car_conv":
            customCostTotal += rate * totalConvCars
        elif kind == "per_car_auto":
            customCostTotal += rate * totalAutoCars
        else:
            customCostTotal += rate

    capexTotal = constructionCost + greenCost + parkingCost + customCostTotal
    budgetOk = (capexTotal <= state["budget"]) if state["budget"] > 0 else True

    # Legal
    rule = RULES["building"].get(state["bType"], {})
    osrOk = (state["osr"] >= rule.get("minOSR")) if (rule.get("minOSR") is not None) else True
    greenRule = rule.get("greenPctOfOSR")
    greenPctOk = (state["greenPctOfOSR"] >= greenRule) if (greenRule is not None) else True

    # Site dims & setbacks (diagram only; siteArea is authoritative)
    width  = max(0.0, float(state["siteWidth"]))
    depth  = max(0.0, float(state["siteDepth"]))
    area_by_dims = width * depth
    # scale factor to respect siteArea as the truth (for diagram label)
    scale_info = None
    if area_by_dims <= 0:
        buildableW = buildableD = buildableArea = 0.0
    else:
        # setbacks
        bw = max(0.0, width - (state["setbackSideL"] + state["setbackSideR"]))
        bd = max(0.0, depth - (state["setbackFront"] + state["setbackRear"]))
        buildableW, buildableD = bw, bd
        buildableArea = bw * bd
        if abs(area_by_dims - state["siteArea"]) > 1e-6:
            scale_info = dict(
                width=width, depth=depth, area_dims=area_by_dims, area_true=state["siteArea"]
            )

    return {
        "maxGFA": maxGFA,
        "openSpaceArea": openSpaceArea,
        "greenArea": greenArea,
        "mainCFA_AG": mainCFA_AG,
        "mainCFA_BG": mainCFA_BG,
        "parkConCFA": parkConCFA,
        "parkAutoCFA": parkAutoCFA,
        "totalCFA": totalCFA,
        "farCounted": farCounted,
        "farOk": farOk,
        "estHeight": estHeight,
        "heightOk": heightOk,

        "convCarsPerFloor": convCarsPerFloor,
        "autoCarsPerFloor": autoCarsPerFloor,
        "totalConvCars": totalConvCars,
        "totalAutoCars": totalAutoCars,
        "openLotCars": openLotCars,
        "totalCars": totalCars,
        "disabledCars": disabledCars,

        "nla": nla, "nsa": nsa, "gfa": gfa,
        "ratio_nla_cfa": ratio_nla_cfa,
        "ratio_nsa_gfa": ratio_nsa_gfa,
        "ratio_nsa_cfa": ratio_nsa_cfa,
        "ratio_nla_gfa": ratio_nla_gfa,

        "baseCostPerSqm": baseCostPerSqm,
        "constructionCost": constructionCost,
        "greenCost": greenCost,
        "parkingCost": parkingCost,
        "customCostTotal": customCostTotal,
        "capexTotal": capexTotal,
        "budgetOk": budgetOk,

        "osrOk": osrOk, "greenPctOk": greenPctOk,

        # for diagram
        "siteWidth": width, "siteDepth": depth,
        "buildableW": buildableW if area_by_dims>0 else 0,
        "buildableD": buildableD if area_by_dims>0 else 0,
        "buildableArea": buildableArea if area_by_dims>0 else 0,
        "scaleInfo": scale_info,
    }

# =============================
# UI
# =============================
st.set_page_config(page_title="Feasibility App (TH) — Streamlit", layout="wide")

# --- (อ็อปชัน) CSS การ์ด ---
st.markdown("""
<style>
.block-container { padding-top: 1.25rem; padding-bottom: 2rem; }
.stApp header { background: transparent; }
.card {
  background: var(--secondary-background-color);
  border: 1px solid rgba(0,0,0,0.06);
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 6px 16px rgba(0,0,0,0.06);
}
.stButton>button { border-radius: 12px !important; padding: 0.55rem 1rem !important; font-weight: 600 !important; }
[data-testid="stMetricValue"] { font-weight: 700; }
</style>
""", unsafe_allow_html=True)

st.title("🏗️ Feasibility App (TH) — Streamlit (Minimal Mono Theme)")

# Sidebar inputs
with st.sidebar:
    st.header("Scenario")
    s = {**DEFAULT}

    colA, colB = st.columns(2)
    s["siteArea"] = colA.number_input("Site Area (m²)", min_value=0.0, value=float(DEFAULT["siteArea"]), step=100.0)
    s["far"] = colB.number_input("FAR (1–10)", min_value=1.0, max_value=10.0, value=float(DEFAULT["far"]), step=0.1)

    s["bType"] = st.selectbox("Building Type", BUILDING_TYPES, index=BUILDING_TYPES.index(DEFAULT["bType"]))
    s["osr"] = st.number_input("OSR (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["osr"]), step=1.0)
    s["greenPctOfOSR"] = st.number_input("Green (% of OSR)", min_value=0.0, max_value=100.0, value=float(DEFAULT["greenPctOfOSR"]), step=1.0)

    st.divider()
    st.subheader("Geometry & Height")
    g1, g2, g3 = st.columns(3)
    s["mainFloorsAG"] = g1.number_input("Main Floors (AG)", min_value=0, value=int(DEFAULT["mainFloorsAG"]), step=1)
    s["mainFloorsBG"] = g2.number_input("Main Floors (BG)", min_value=0, value=int(DEFAULT["mainFloorsBG"]), step=1)
    s["ftf"] = g3.number_input("F2F (m)", min_value=0.0, value=float(DEFAULT["ftf"]), step=0.1)

    p1, p2, p3 = st.columns(3)
    s["parkingConFloorsAG"] = p1.number_input("Park Conv (AG)", min_value=0, value=int(DEFAULT["parkingConFloorsAG"]), step=1)
    s["parkingConFloorsBG"] = p2.number_input("Park Conv (BG)", min_value=0, value=int(DEFAULT["parkingConFloorsBG"]), step=1)
    s["maxHeight"] = p3.number_input("Max Height (m)", min_value=0.0, value=float(DEFAULT["maxHeight"]), step=1.0)

    a1, a2 = st.columns(2)
    s["parkingAutoFloorsAG"] = a1.number_input("Auto Park (AG)", min_value=0, value=int(DEFAULT["parkingAutoFloorsAG"]), step=1)
    s["parkingAutoFloorsBG"] = a2.number_input("Auto Park (BG)", min_value=0, value=int(DEFAULT["parkingAutoFloorsBG"]), step=1)

    st.caption("Floor Plates (m²)")
    f1, f2, f3 = st.columns(3)
    s["mainFloorPlate"] = f1.number_input("Main Plate", min_value=0.0, value=float(DEFAULT["mainFloorPlate"]), step=10.0)
    s["parkingConPlate"] = f2.number_input("Park Plate (Conv)", min_value=0.0, value=float(DEFAULT["parkingConPlate"]), step=10.0)
    s["parkingAutoPlate"] = f3.number_input("Park Plate (Auto)", min_value=0.0, value=float(DEFAULT["parkingAutoPlate"]), step=10.0)

    st.caption("FAR flags")
    s["countParkingInFAR"] = st.selectbox("Count Parking in FAR?", ["Yes", "No"], index=0) == "Yes"
    s["countBasementInFAR"] = st.selectbox("Count Basement in FAR?", ["Yes", "No"], index=0) == "Yes"

    st.divider()
    st.subheader("Parking Efficiency")
    e1, e2 = st.columns(2)
    s["bayConv"] = e1.number_input("Conv Bay (m²) — net", min_value=1.0, value=float(DEFAULT["bayConv"]), step=0.5)
    s["circConvPct"] = e2.number_input("Conv Circ (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["circConvPct"])*100, step=1.0) / 100.0
    st.caption(f"eff Conv = {nf(s['bayConv']*(1+s['circConvPct']))} m²/คัน")

    s["bayAuto"] = e1.number_input("Auto Bay (m²) — net", min_value=1.0, value=float(DEFAULT["bayAuto"]), step=0.5, key="autobay")
    s["circAutoPct"] = e2.number_input("Auto Circ (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["circAutoPct"])*100, step=1.0, key="autocirc") / 100.0
    st.caption(f"eff Auto = {nf(s['bayAuto']*(1+s['circAutoPct']))} m²/คัน")

    st.caption("Open-lot (ไม่นับ FAR)")
    o1, o2, o3 = st.columns(3)
    s["openLotArea"] = o1.number_input("Open-lot Area (m²)", min_value=0.0, value=float(DEFAULT["openLotArea"]), step=10.0)
    s["openLotBay"] = o2.number_input("Open-lot Bay (m²/คัน)", min_value=1.0, value=float(DEFAULT["openLotBay"]), step=0.5)
    s["openLotCircPct"] = o3.number_input("Open-lot Circ (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["openLotCircPct"])*100, step=1.0) / 100.0
    st.caption(f"eff Open-lot = {nf(s['openLotBay']*(1+s['openLotCircPct']))} m²/คัน")

    st.divider()
    st.subheader("Site Dimensions & Setbacks (diagram)")
    d1, d2 = st.columns(2)
    s["siteWidth"]  = d1.number_input("Site Width (m)", min_value=0.0, value=float(DEFAULT["siteWidth"]), step=1.0)
    s["siteDepth"]  = d2.number_input("Site Depth (m)", min_value=0.0, value=float(DEFAULT["siteDepth"]), step=1.0)
    sb1, sb2, sb3, sb4 = st.columns(4)
    s["setbackFront"] = sb1.number_input("Front (m)", min_value=0.0, value=float(DEFAULT["setbackFront"]), step=0.5)
    s["setbackRear"]  = sb2.number_input("Rear (m)",  min_value=0.0, value=float(DEFAULT["setbackRear"]),  step=0.5)
    s["setbackSideL"] = sb3.number_input("Side-L (m)",min_value=0.0, value=float(DEFAULT["setbackSideL"]), step=0.5)
    s["setbackSideR"] = sb4.number_input("Side-R (m)",min_value=0.0, value=float(DEFAULT["setbackSideR"]), step=0.5)

    st.divider()
    st.subheader("Costs & Budget (THB)")
    c1, c2 = st.columns(2)
    s["costArchPerSqm"] = c1.number_input("Architecture (฿/m²)", min_value=0.0, value=float(DEFAULT["costArchPerSqm"]), step=100.0)
    s["costStructPerSqm"] = c2.number_input("Structure (฿/m²)",  min_value=0.0, value=float(DEFAULT["costStructPerSqm"]), step=100.0)
    s["costMEPPerSqm"]   = c1.number_input("MEP (฿/m²)",         min_value=0.0, value=float(DEFAULT["costMEPPerSqm"]),   step=100.0)
    s["costGreenPerSqm"] = c2.number_input("Green (฿/m²)",       min_value=0.0, value=float(DEFAULT["costGreenPerSqm"]), step=100.0)
    s["costConventionalPerCar"] = c1.number_input("Parking (Conv) (฿/car)", min_value=0.0, value=float(DEFAULT["costConventionalPerCar"]), step=1000.0)
    s["costAutoPerCar"]         = c2.number_input("Parking (Auto) (฿/car)", min_value=0.0, value=float(DEFAULT["costAutoPerCar"]),         step=1000.0)
    s["costOpenLotPerCar"]      = c1.number_input("Parking (Open-lot) (฿/car)", min_value=0.0, value=float(DEFAULT["costOpenLotPerCar"]),  step=1000.0)
    s["budget"] = st.number_input("Budget (฿)", min_value=0.0, value=float(DEFAULT["budget"]), step=1_000_000.0)

# Editable custom cost table
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Additional Cost Items")
st.caption("กำหนดหมวดต้นทุนเพิ่มจากหมวดหลัก (per m², per car, หรือ lump sum)")
default_rows = pd.DataFrame(s.get("customCosts") or [], columns=["name","kind","rate"])
if default_rows.empty:
    default_rows = pd.DataFrame([{"name":"FF&E","kind":"lump_sum","rate":0.0}])
edited = st.data_editor(
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
st.markdown('</div>', unsafe_allow_html=True)

# Compute
d = compute(s)

# Summary metrics
m1, m2, m3, m4 = st.columns(4)
m1.metric("Max GFA (m²)", nf(d["maxGFA"]))
m2.metric("FAR-counted (m²)", nf(d["farCounted"]))
m3.metric("Estimated Height (m)", nf(d["estHeight"]), delta="OK" if d["heightOk"] else "Exceeds")
m4.metric("CAPEX (฿)", nf(d["capexTotal"]), delta="OK" if d["budgetOk"] else "Over Budget")

# Zoning / Areas / Parking
z1, z2, z3 = st.columns(3)
with z1:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Zoning")
    st.write(f"**Open Space**: {nf(d['openSpaceArea'])} m² ({s['osr']}%)")
    st.write(f"**Green**: {nf(d['greenArea'])} m² ({s['greenPctOfOSR']}% of OSR)")
    st.write(f"**FAR check**: {'✅ OK' if d['farOk'] else '❌ Exceeds Max GFA'}")
    st.markdown('</div>', unsafe_allow_html=True)

with z2:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Areas")
    st.write(f"Main CFA (AG): **{nf(d['mainCFA_AG'])}** m²")
    st.write(f"Main CFA (BG): **{nf(d['mainCFA_BG'])}** m²")
    st.write(f"Parking CFA (Conv): **{nf(d['parkConCFA'])}** m²")
    st.write(f"Parking CFA (Auto): **{nf(d['parkAutoCFA'])}** m²")
    st.write(f"Total CFA: **{nf(d['totalCFA'])}** m²")
    st.markdown('</div>', unsafe_allow_html=True)

with z3:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Parking")
    st.write(f"Cars/Floor (Conv): **{d['convCarsPerFloor']}** (eff {nf(s['bayConv']*(1+s['circConvPct']))} m²/car)")
    st.write(f"Cars/Floor (Auto): **{d['autoCarsPerFloor']}** (eff {nf(s['bayAuto']*(1+s['circAutoPct']))} m²/car)")
    st.write(f"Open-lot Cars: **{d['openLotCars']}** (eff {nf(s['openLotBay']*(1+s['openLotCircPct']))} m²/car)")
    st.write(f"Total Cars: **{d['totalCars']}**  · Disabled: **{d['disabledCars']}**")
    st.markdown('</div>', unsafe_allow_html=True)

# Efficiency ratios (ใหม่)
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Efficiency Ratios")
r1, r2, r3, r4 = st.columns(4)
r1.metric("NLA / CFA", f"{d['ratio_nla_cfa']*100:.1f}%")
r2.metric("NSA / GFA", f"{d['ratio_nsa_gfa']*100:.1f}%")
r3.metric("NSA / CFA", f"{d['ratio_nsa_cfa']*100:.1f}%")
r4.metric("NLA / GFA", f"{d['ratio_nla_gfa']*100:.1f}%")
st.markdown('</div>', unsafe_allow_html=True)

# CAPEX Breakdown (ตามชื่อ=สีคงที่)
CAPEX_COLOR_MAP = {
    "Construction": "#111827",  # ดำเข้ม
    "Green":        "#6b7280",  # เทากลาง
    "Parking":      "#9ca3af",  # เทาอ่อน
    "Custom":       "#d1d5db",  # เทาอ่อนมาก
}
pie_df = pd.DataFrame([
    {"name": "Construction", "value": max(0, d["constructionCost"])},
    {"name": "Green",        "value": max(0, d["greenCost"])},
    {"name": "Parking",      "value": max(0, d["parkingCost"])},
    {"name": "Custom",       "value": max(0, d["customCostTotal"])},
])
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("CAPEX Breakdown")
fig = px.pie(pie_df, values="value", names="name", hole=0.45, color="name", color_discrete_map=CAPEX_COLOR_MAP)
fig.update_layout(template="plotly_white")
st.plotly_chart(fig, use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# Site setbacks diagram (ใช้ตัวเลข siteArea เป็นหลักสำหรับข้อความ; สเกลจาก width/depth ที่ใส่)
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Site & Setbacks Diagram")
if d["siteWidth"] > 0 and d["siteDepth"] > 0:
    fig2 = go.Figure()
    # Outer site rectangle
    fig2.add_shape(type="rect", x0=0, y0=0, x1=d["siteWidth"], y1=d["siteDepth"],
                   line=dict(color="#111827"), fillcolor="#ffffff")
    # Buildable rectangle
    bx0 = d["sitetWidth"]=0 + s["setbackSideL"]
    bx1 = d["siteWidth"] - s["setbackSideR"]
    by0 = 0 + s["setbackFront"]
    by1 = d["siteDepth"] - s["setbackRear"]
    bx0 = max(0,bx0); by0=max(0,by0); bx1=max(bx0,bx1); by1=max(by0,by1)
    fig2.add_shape(type="rect", x0=bx0, y0=by0, x1=bx1, y1=by1,
                   line=dict(color="#6b7280"), fillcolor="#e5e7eb")
    fig2.add_annotation(x=d["siteWidth"]/2, y=d["siteDepth"]+0.5, showarrow=False,
                        text=f"Site: {nf(s['siteArea'])} m² (diagram: {nf(d['siteWidth'])} × {nf(d['siteDepth'])} m)")
    fig2.add_annotation(x=(bx0+bx1)/2, y=(by0+by1)/2, showarrow=False,
                        text=f"Buildable ~ {nf(d['buildableArea'])} m²")
    fig2.update_xaxes(range=[-1, d["siteWidth"]+1], visible=False)
    fig2.update_yaxes(range=[-1, d["siteDepth"]+1], scaleanchor="x", scaleratio=1, visible=False)
    fig2.update_layout(height=320, margin=dict(l=10,r=10,t=10,b=10), template="plotly_white")
    st.plotly_chart(fig2, use_container_width=True)

    if d["scaleInfo"] is not None:
        st.caption("⚠️ Width×Depth ที่กรอกไม่เท่ากับ siteArea จริง—ใช้เพื่อสเกลภาพเท่านั้น (ยึด siteArea เป็นหลักในการคำนวณ)")
else:
    st.info("กรอก Site Width/Depth เพื่อดูแผนภาพ setbacks")

st.markdown('</div>', unsafe_allow_html=True)

# Export / Import Scenario + Template
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Export / Import Scenario")
export_rows = [{"Field": k, "Value": v} for k, v in s.items()]
csv_str = create_csv(export_rows)

cA, cB, cC = st.columns([1,1,2])
with cA:
    st.download_button("⬇️ Export CSV", data=csv_str, file_name="scenario.csv", mime="text/csv")
with cB:
    # Template = โครง Field,Value (ค่าว่าง/ตัวอย่าง)
    template_rows = [{"Field": k, "Value": DEFAULT[k]} for k in DEFAULT.keys()]
    template_csv = create_csv(template_rows)
    st.download_button("⬇️ Download CSV Template", data=template_csv, file_name="scenario_template.csv", mime="text/csv")
with cC:
    st.write("รูปแบบไฟล์: สองคอลัมน์ **Field,Value**. ตัวอย่างแถว:")
    st.code("Field,Value\nsiteArea,8000\nfar,5\nbType,Housing\n...", language="csv")

up = st.file_uploader("⬆️ Import CSV (Field,Value)", type=["csv"])
if up:
    df = pd.read_csv(up)
    try:
        imported = {}
        for _, row in df.iterrows():
            k = str(row["Field"])
            v = row["Value"]
            try:
                if str(v).strip() == "":
                    imported[k] = ""
                else:
                    imported[k] = float(v) if "." in str(v) or "e" in str(v).lower() else int(v)
            except:
                imported[k] = v
        st.success("นำเข้าค่าจาก CSV สำเร็จ (preview)")
        st.json({k: imported.get(k, s[k]) for k in s.keys()})
        st.caption("Tip: นำค่าที่ import ไปตั้งเป็น DEFAULT ได้โดยแก้ dict `DEFAULT` ในโค้ด")
    except Exception as e:
        st.error(f"Import failed: {e}")
st.markdown('</div>', unsafe_allow_html=True)

# Self-check Tests (เหมือนเดิม + open-lot)
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

mAG = s["mainFloorsAG"] * s["mainFloorPlate"]
mBG = s["mainFloorsBG"] * s["mainFloorPlate"]
pcAG = s["parkingConFloorsAG"] * s["parkingConPlate"]
pcBG = s["parkingConFloorsBG"] * s["parkingConPlate"]
paAG = s["parkingAutoFloorsAG"] * s["parkingAutoPlate"]
paBG = s["parkingAutoFloorsBG"] * s["parkingAutoPlate"]
far_expected = compute_far_counted(mAG, mBG, pcAG, pcBG, paAG, paBG, s["countParkingInFAR"], s["countBasementInFAR"])
trow("computeFarCounted(default flags)", compute_far_counted(mAG, mBG, pcAG, pcBG, paAG, paBG, s["countParkingInFAR"], s["countBasementInFAR"]), far_expected)
trow("openLotCars formula", d["openLotCars"], math.floor(s["openLotArea"]/max(1, s["openLotBay"]*(1+s["openLotCircPct"]))))
st.markdown('</div>', unsafe_allow_html=True)
