# app.py
import math
import io
import json
import pandas as pd
import streamlit as st
import plotly.express as px

# =============================
# Helpers (เทียบเคียง logic เดิม)
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
    # 0 → 0; ≤50 → 2; 51–100 → 3; >100 → +1 per 100 cars thereafter
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
# Rules / Defaults (ยกมาจากแอป)
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
    siteArea=8000,
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

    # Open-lot (ไม่นับ FAR แต่มีจำนวนคัน+ต้นทุน)
    openLotArea=0.0, openLotBay=25.0, openLotCircPct=0.0,

    # Efficiency ratios
    nlaPctOfCFA=70.0,
    nsaPctOfCFA=80.0,
    gfaOverCfaPct=95.0,

    # FAR toggles
    countParkingInFAR=True,
    countBasementInFAR=False,

    # Costs
    costArchPerSqm=16000.0,
    costStructPerSqm=22000.0,
    costMEPPerSqm=20000.0,
    costGreenPerSqm=4500.0,
    costConventionalPerCar=125000.0,
    costAutoPerCar=432000.0,
    costOpenLotPerCar=60000.0,

    # Budget
    budget=500_000_000.0,
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

    # FAR-counted (ไม่รวม open-lot)
    farCounted = compute_far_counted(
        mainCFA_AG, mainCFA_BG,
        parkConCFA_AG, parkConCFA_BG,
        parkAutoCFA_AG, parkAutoCFA_BG,
        state["countParkingInFAR"], state["countBasementInFAR"]
    )
    farOk = farCounted <= maxGFA

    # Efficiency
    nla = (state["nlaPctOfCFA"] / 100.0) * totalCFA
    nsa = (state["nsaPctOfCFA"] / 100.0) * totalCFA
    gfa = (state["gfaOverCfaPct"] / 100.0) * totalCFA

    # Costs
    baseCostPerSqm = state["costArchPerSqm"] + state["costStructPerSqm"] + state["costMEPPerSqm"]
    constructionCost = totalCFA * baseCostPerSqm
    greenCost = greenArea * state["costGreenPerSqm"]
    parkingCost = (
        totalConvCars * state["costConventionalPerCar"] +
        totalAutoCars * state["costAutoPerCar"] +
        openLotCars   * state["costOpenLotPerCar"]
    )
    capexTotal = constructionCost + greenCost + parkingCost
    budgetOk = (capexTotal <= state["budget"]) if state["budget"] > 0 else True

    # Legal
    rule = RULES["building"].get(state["bType"], {})
    osrOk = (state["osr"] >= rule.get("minOSR")) if (rule.get("minOSR") is not None) else True
    greenRule = rule.get("greenPctOfOSR")
    greenPctOk = (state["greenPctOfOSR"] >= greenRule) if (greenRule is not None) else True

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
        "baseCostPerSqm": baseCostPerSqm,
        "constructionCost": constructionCost,
        "greenCost": greenCost,
        "parkingCost": parkingCost,
        "capexTotal": capexTotal,
        "budgetOk": budgetOk,

        "osrOk": osrOk, "greenPctOk": greenPctOk,

        "effAreaConCar": effAreaConCar,
        "effAreaAutoCar": effAreaAutoCar,
        "effAreaOpenCar": effAreaOpenCar,
    }

# =============================
# UI
# =============================
st.set_page_config(page_title="Feasibility App (TH) — Streamlit", layout="wide")
st.title("🏗️ Feasibility App (TH) — Streamlit")

# Sidebar inputs
with st.sidebar:
    st.header("Scenario")
    s = {**DEFAULT}

    colA, colB = st.columns(2)
    s["siteArea"] = colA.number_input(
        "Site Area (m²)",
        min_value=0.0,
        value=float(DEFAULT["siteArea"]),
        step=100.0
    )
    s["far"] = colB.number_input(
        "FAR (1–10)",
        min_value=1.0, max_value=10.0,
        value=float(DEFAULT["far"]),
        step=0.1
    )

    s["bType"] = st.selectbox("Building Type", BUILDING_TYPES, index=BUILDING_TYPES.index(DEFAULT["bType"]))
    s["osr"] = st.number_input(
        "OSR (%)",
        min_value=0.0, max_value=100.0,
        value=float(DEFAULT["osr"]),
        step=1.0
    )
    s["greenPctOfOSR"] = st.number_input(
        "Green (% of OSR)",
        min_value=0.0, max_value=100.0,
        value=float(DEFAULT["greenPctOfOSR"]),
        step=1.0
    )

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
    s["mainFloorPlate"]   = f1.number_input("Main Plate",          min_value=0.0, value=float(DEFAULT["mainFloorPlate"]),   step=10.0)
    s["parkingConPlate"]  = f2.number_input("Park Plate (Conv)",   min_value=0.0, value=float(DEFAULT["parkingConPlate"]),  step=10.0)
    s["parkingAutoPlate"] = f3.number_input("Park Plate (Auto)",   min_value=0.0, value=float(DEFAULT["parkingAutoPlate"]), step=10.0)

    st.caption("FAR flags")
    s["countParkingInFAR"]   = st.selectbox("Count Parking in FAR?",   ["Yes", "No"], index=0) == "Yes"
    s["countBasementInFAR"]  = st.selectbox("Count Basement in FAR?",  ["Yes", "No"], index=0) == "Yes"

    st.divider()
    st.subheader("Parking Efficiency")
    e1, e2, e3 = st.columns(3)
    s["bayConv"] = e1.number_input("Conv Bay (m²) — net", min_value=1.0, value=float(DEFAULT["bayConv"]), step=0.5)
    s["circConvPct"] = e2.number_input("Conv Circ (%)",   min_value=0.0, max_value=100.0, value=float(DEFAULT["circConvPct"])*100, step=1.0) / 100.0
    st.caption(f"eff Conv = {nf(s['bayConv']*(1+s['circConvPct']))} m²/คัน")

    s["bayAuto"] = e1.number_input("Auto Bay (m²) — net", min_value=1.0, value=float(DEFAULT["bayAuto"]), step=0.5, key="autobay")
    s["circAutoPct"] = e2.number_input("Auto Circ (%)",   min_value=0.0, max_value=100.0, value=float(DEFAULT["circAutoPct"])*100, step=1.0, key="autocirc") / 100.0
    st.caption(f"eff Auto = {nf(s['bayAuto']*(1+s['circAutoPct']))} m²/คัน")

    st.caption("Open-lot (ไม่นับ FAR)")
    o1, o2, o3 = st.columns(3)
    s["openLotArea"]    = o1.number_input("Open-lot Area (m²)",   min_value=0.0, value=float(DEFAULT["openLotArea"]), step=10.0)
    s["openLotBay"]     = o2.number_input("Open-lot Bay (m²/คัน)",min_value=1.0, value=float(DEFAULT["openLotBay"]),  step=0.5)
    s["openLotCircPct"] = o3.number_input("Open-lot Circ (%)",    min_value=0.0, max_value=100.0, value=float(DEFAULT["openLotCircPct"])*100, step=1.0) / 100.0
    st.caption(f"eff Open-lot = {nf(s['openLotBay']*(1+s['openLotCircPct']))} m²/คัน")

    st.divider()
    st.subheader("Costs & Budget (THB)")
    c1, c2 = st.columns(2)
    s["costArchPerSqm"] = c1.number_input("Architecture (฿/m²)",  min_value=0.0, value=float(DEFAULT["costArchPerSqm"]), step=100.0)
    s["costStructPerSqm"] = c2.number_input("Structure (฿/m²)",   min_value=0.0, value=float(DEFAULT["costStructPerSqm"]), step=100.0)
    s["costMEPPerSqm"]   = c1.number_input("MEP (฿/m²)",          min_value=0.0, value=float(DEFAULT["costMEPPerSqm"]),   step=100.0)
    s["costGreenPerSqm"] = c2.number_input("Green (฿/m²)",        min_value=0.0, value=float(DEFAULT["costGreenPerSqm"]), step=100.0)

    s["costConventionalPerCar"] = c1.number_input("Parking (Conv) (฿/car)",   min_value=0.0, value=float(DEFAULT["costConventionalPerCar"]), step=1000.0)
    s["costAutoPerCar"]         = c2.number_input("Parking (Auto) (฿/car)",   min_value=0.0, value=float(DEFAULT["costAutoPerCar"]),         step=1000.0)
    s["costOpenLotPerCar"]      = c1.number_input("Parking (Open-lot) (฿/car)",min_value=0.0, value=float(DEFAULT["costOpenLotPerCar"]),     step=1000.0)

    s["budget"] = st.number_input("Budget (฿)", min_value=0.0, value=float(DEFAULT["budget"]), step=1_000_000.0)
    
# Compute
d = compute(s)

# =============================
# Summary blocks
# =============================
m1, m2, m3, m4 = st.columns(4)
m1.metric("Max GFA (m²)", nf(d["maxGFA"]))
m2.metric("FAR-counted (m²)", nf(d["farCounted"]), help="ไม่นับ open-lot")
m3.metric("Estimated Height (m)", nf(d["estHeight"]), delta="OK" if d["heightOk"] else "Exceeds")
m4.metric("CAPEX (฿)", nf(d["capexTotal"]), delta="OK" if d["budgetOk"] else "Over Budget")

st.markdown("### Zoning / Areas / Parking")
c1, c2, c3 = st.columns(3)

with c1:
    st.subheader("Zoning")
    st.write(f"**Open Space**: {nf(d['openSpaceArea'])} m² ({s['osr']}%)")
    st.write(f"**Green**: {nf(d['greenArea'])} m² ({s['greenPctOfOSR']}% of OSR)")
    st.write(f"**FAR check**: {'✅ OK' if d['farOk'] else '❌ Exceeds Max GFA'}")

with c2:
    st.subheader("Areas")
    st.write(f"Main CFA (AG): **{nf(d['mainCFA_AG'])}** m²")
    st.write(f"Main CFA (BG): **{nf(d['mainCFA_BG'])}** m²")
    st.write(f"Parking CFA (Conv): **{nf(d['parkConCFA'])}** m²")
    st.write(f"Parking CFA (Auto): **{nf(d['parkAutoCFA'])}** m²")
    st.write(f"Total CFA: **{nf(d['totalCFA'])}** m²")

with c3:
    st.subheader("Parking")
    st.write(f"Cars/Floor (Conv): **{d['convCarsPerFloor']}** (eff {nf(d['effAreaConCar'])} m²/car)")
    st.write(f"Cars/Floor (Auto): **{d['autoCarsPerFloor']}** (eff {nf(d['effAreaAutoCar'])} m²/car)")
    st.write(f"Open-lot Cars: **{d['openLotCars']}** (eff {nf(d['effAreaOpenCar'])} m²/car)")
    st.write(f"Total Cars: **{d['totalCars']}**  · Disabled: **{d['disabledCars']}**")

# CAPEX Pie
st.markdown("### CAPEX Breakdown")
pie_df = pd.DataFrame([
    {"name": "Construction", "value": max(0, d["constructionCost"])},
    {"name": "Green",        "value": max(0, d["greenCost"])},
    {"name": "Parking",      "value": max(0, d["parkingCost"])},
])
fig = px.pie(
    pie_df, values="value", names="name", hole=0.45,
    color="name",
    color_discrete_map={
        "Construction": "#3b82f6",
        "Green": "#22c55e",
        "Parking": "#f59e0b",
        "Custom": "#a855f7",
    }
)
st.plotly_chart(fig, use_container_width=True)

# Download / Upload CSV of scenario
st.markdown("### Export / Import Scenario")
export_rows = [{"Field": k, "Value": v} for k, v in s.items()]
csv_str = create_csv(export_rows)
st.download_button("⬇️ Export CSV", data=csv_str, file_name="scenario.csv", mime="text/csv")

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
        st.info("นำเข้าค่าจาก CSV สำเร็จ (แสดงตัวอย่าง):")
        st.json({k: imported.get(k, s[k]) for k in s.keys()})
        st.caption("**Tip**: นำค่าที่ import มาใส่เป็น default ได้โดยแก้ `DEFAULT` ในโค้ด")
    except Exception as e:
        st.error(f"Import failed: {e}")

# =============================
# Self-check Tests (เทียบกับเดิม)
# =============================
st.markdown("### Self-check Tests")
def trow(name, actual, expected):
    ok = (actual == expected)
    st.write(("✅" if ok else "❌") + f" **{name}** — actual: `{actual}`  expected: `{expected}`")

trow("calcDisabledParking(0)",   calc_disabled_parking(0),   0)
trow("calcDisabledParking(50)",  calc_disabled_parking(50),  2)
trow("calcDisabledParking(51)",  calc_disabled_parking(51),  3)
trow("calcDisabledParking(100)", calc_disabled_parking(100), 3)
trow("calcDisabledParking(101)", calc_disabled_parking(101), 4)
trow("calcDisabledParking(250)", calc_disabled_parking(250), 5)

# recompute expected FAR with current toggles
mAG = s["mainFloorsAG"] * s["mainFloorPlate"]
mBG = s["mainFloorsBG"] * s["mainFloorPlate"]
pcAG = s["parkingConFloorsAG"] * s["parkingConPlate"]
pcBG = s["parkingConFloorsBG"] * s["parkingConPlate"]
paAG = s["parkingAutoFloorsAG"] * s["parkingAutoPlate"]
paBG = s["parkingAutoFloorsBG"] * s["parkingAutoPlate"]
far_expected = compute_far_counted(mAG, mBG, pcAG, pcBG, paAG, paBG, s["countParkingInFAR"], s["countBasementInFAR"])
trow("computeFarCounted(default flags)", d["farCounted"], far_expected)

trow("computeFarCounted(no parking, no basement)",
     compute_far_counted(100, 20, 30, 40, 50, 60, False, False), 100)
trow("computeFarCounted(parking+basement)",
     compute_far_counted(100, 20, 30, 40, 50, 60, True, True), 300)

open_lot_expected = math.floor(s["openLotArea"] / max(1, s["openLotBay"] * (1 + s["openLotCircPct"])))
trow("openLotCars formula", d["openLotCars"], open_lot_expected)
trow("open-lot NOT in FAR (identity check)", d["farCounted"], far_expected)
