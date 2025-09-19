import math, json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# =============================
# Page / Theme-ish (minimal mono)
# =============================
st.set_page_config(page_title="Feasibility (TH) — Minimal Mono", layout="wide")
st.markdown("""
<style>
.block-container { padding-top: 0.75rem; padding-bottom: 2rem; }
.stApp header { background: transparent; }
.card { background: var(--secondary-background-color);
  border: 1px solid rgba(0,0,0,.08); border-radius: 16px; padding: 16px; box-shadow: 0 6px 16px rgba(0,0,0,.06); }
.stButton>button { border-radius: 12px !important; padding: .5rem .9rem !important; font-weight: 600 !important; }
.small { font-size: 0.825rem }
.kpi .stMetric { background: #fff; border:1px solid rgba(0,0,0,.05); border-radius: 12px; padding:.6rem .8rem}
</style>
""", unsafe_allow_html=True)

# =============================
# Helpers
# =============================
def nf(n, digits=2):
    try:
        x = float(n); return f"{x:,.{digits}f}"
    except: return "–"

def clamp(v, lo, hi): return min(hi, max(lo, v))

def create_csv(rows):
    if not rows: return ""
    headers = list(rows[0].keys()); out = [",".join(headers)]
    for r in rows: out.append(",".join(str(r.get(h,"")) for h in headers))
    return "\n".join(out)

def calc_disabled_parking(total_cars:int)->int:
    if total_cars <= 0: return 0
    if total_cars <= 50: return 2
    if total_cars <= 100: return 3
    extra = math.ceil((total_cars-100)/100)
    return 3 + max(0, extra)

def compute_far_counted(mainAG, mainBG, pcAG, pcBG, paAG, paBG, countParking, countBasement):
    far = float(mainAG) + (float(mainBG) if countBasement else 0.0)
    if countParking:
        far += float(pcAG) + (float(pcBG) if countBasement else 0.0)
        far += float(paAG) + (float(paBG) if countBasement else 0.0)
    return far

# =============================
# Rules / Defaults
# =============================
BUILDING_TYPES = ["Housing","Hi-Rise","Low-Rise","Public Building","Office Building","Hotel"]
RULES = {
    "base": {"farRange":[1.0,10.0]},
    "building":{
        "Housing":{"minOSR":30.0,"greenPctOfOSR":None},
        "Hi-Rise":{"minOSR":10.0,"greenPctOfOSR":50.0},
        "Low-Rise":{"minOSR":10.0,"greenPctOfOSR":50.0},
        "Public Building":{"minOSR":None,"greenPctOfOSR":None},
        "Office Building":{"minOSR":None,"greenPctOfOSR":None},
        "Hotel":{"minOSR":10.0,"greenPctOfOSR":40.0},
    }
}

DEFAULT = dict(
    # Site & zoning
    siteArea=8000.0, far=5.0, bType="Housing", osr=30.0, greenPctOfOSR=40.0,
    # Dimensions & setbacks (for diagram)
    siteWidth=80.0, siteDepth=100.0,
    setbackFront=6.0, setbackRear=6.0, setbackSideL=3.0, setbackSideR=3.0,
    # Plate mode
    plateMode="Auto (coverage)", plateCoveragePct=80.0,  # % of buildable
    # Geometry
    mainFloorsAG=20, mainFloorsBG=0,
    parkingConFloorsAG=3, parkingConFloorsBG=0,
    parkingAutoFloorsAG=0, parkingAutoFloorsBG=0,
    ftf=3.2, maxHeight=120.0,
    # Plates (m²) — used if Manual
    mainFloorPlate=1500.0, parkingConPlate=1200.0, parkingAutoPlate=800.0,
    # Parking efficiency
    bayConv=25.0, circConvPct=0.0, bayAuto=16.0, circAutoPct=0.0,
    # Open-lot (not FAR)
    openLotArea=0.0, openLotBay=25.0, openLotCircPct=0.0,
    # Efficiency ratios
    nlaPctOfCFA=70.0, nsaPctOfCFA=80.0, gfaOverCfaPct=95.0,
    # FAR toggles
    countParkingInFAR=True, countBasementInFAR=False,
    # Costs (THB)
    costArchPerSqm=16000.0, costStructPerSqm=22000.0, costMEPPerSqm=20000.0, costGreenPerSqm=4500.0,
    interiorPctOfArch=0.0,  # NEW: interior % of Architecture total
    costConventionalPerCar=125000.0, costAutoPerCar=432000.0, costOpenLotPerCar=60000.0,
    # Additional cost items (list-style, not table)
    customCosts=[{"name":"FF&E","kind":"lump_sum","rate":0.0}],
    budget=500_000_000.0,
    # Unit program (condo quick calc)
    unitEffPct=85.0, unit1BRSize=32.0, unit2BRSize=55.0, unit1BRMixPct=70.0  # % of units being 1BR
)

def suggested_osr(btype:str)->float:
    r = RULES["building"].get(btype, {}); return r["minOSR"] if r.get("minOSR") is not None else 15.0

def suggested_green_pct(btype:str)->float:
    r = RULES["building"].get(btype, {}); return r["greenPctOfOSR"] if r.get("greenPctOfOSR") is not None else 40.0

# =============================
# Compute
# =============================
def compute(state:dict):
    # Buildable (for coverage & diagram)
    w = float(max(0.0, state["siteWidth"])); d = float(max(0.0, state["siteDepth"]))
    bw = max(0.0, w - (state["setbackSideL"] + state["setbackSideR"]))
    bd = max(0.0, d - (state["setbackFront"] + state["setbackRear"]))
    buildable_area = bw * bd

    # Main plate
    mainPlate = (buildable_area * (state["plateCoveragePct"]/100.0)) if state["plateMode"].startswith("Auto") else float(state["mainFloorPlate"])

    far = clamp(float(state["far"]), *RULES["base"]["farRange"])
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
    totalCFA = (mainCFA_AG+mainCFA_BG) + (parkConCFA_AG+parkConCFA_BG) + (parkAutoCFA_AG+parkAutoCFA_BG)

    # Height
    estHeight = state["ftf"] * (state["mainFloorsAG"] + state["parkingConFloorsAG"] + state["parkingAutoFloorsAG"])
    heightOk = estHeight <= state["maxHeight"]

    # Parking (effective areas)
    effConv = state["bayConv"]*(1+state["circConvPct"])
    effAuto = state["bayAuto"]*(1+state["circAutoPct"])
    effOpen = state["openLotBay"]*(1+state["openLotCircPct"])
    convCarsPerFloor = math.floor(state["parkingConPlate"]/max(1,effConv))
    autoCarsPerFloor = math.floor(state["parkingAutoPlate"]/max(1,effAuto))
    totalConvCars = convCarsPerFloor * (state["parkingConFloorsAG"]+state["parkingConFloorsBG"])
    totalAutoCars = autoCarsPerFloor * (state["parkingAutoFloorsAG"]+state["parkingAutoFloorsBG"])
    openLotCars = math.floor(state["openLotArea"]/max(1,effOpen))
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
    archTotal = totalCFA * state["costArchPerSqm"]
    interiorCost = archTotal * (state["interiorPctOfArch"]/100.0)  # NEW
    structCost = totalCFA * state["costStructPerSqm"]
    mepCost = totalCFA * state["costMEPPerSqm"]
    greenCost = greenArea * state["costGreenPerSqm"]
    parkingCost = (
        totalConvCars * state["costConventionalPerCar"] +
        totalAutoCars * state["costAutoPerCar"] +
        openLotCars   * state["costOpenLotPerCar"]
    )
    # base construction = Arch + Structure + MEP (+ Interior separate line)
    constructionCost = archTotal + structCost + mepCost

    customCostTotal = 0.0
    for i in state.get("customCosts", []):
        kind = i.get("kind","lump_sum"); rate = float(i.get("rate",0) or 0.0)
        if kind == "per_sqm": customCostTotal += rate * totalCFA
        elif kind == "per_car_conv": customCostTotal += rate * totalConvCars
        elif kind == "per_car_auto": customCostTotal += rate * totalAutoCars
        else: customCostTotal += rate

    capexTotal = constructionCost + interiorCost + greenCost + parkingCost + customCostTotal
    budgetOk = (capexTotal <= state["budget"]) if state["budget"]>0 else True

    # Condo quick program (85% of main plate × AG floors)
    unitEff = state["unitEffPct"]/100.0
    resNFA_per_floor = mainPlate * unitEff
    resNFA_total = resNFA_per_floor * state["mainFloorsAG"]
    # unit split by mix (% of unit count)
    mix1 = clamp(state["unit1BRMixPct"]/100.0, 0.0, 1.0)
    # Solve units by count with two sizes: assume target NFA is fully used, split by unit counts proportionally by mix
    # Let n1 = mix1 * N, n2 = (1-mix1)*N;  n1*s1 + n2*s2 = resNFA_total  => N = resNFA_total / (mix1*s1 + (1-mix1)*s2)
    s1 = max(1.0, float(state["unit1BRSize"])); s2 = max(1.0, float(state["unit2BRSize"]))
    denom = mix1*s1 + (1.0-mix1)*s2
    totalUnits = math.floor(resNFA_total/denom) if denom>0 else 0
    units1 = math.floor(totalUnits*mix1)
    units2 = totalUnits - units1

    # Legal
    rule = RULES["building"].get(state["bType"], {})
    osrOk = (state["osr"] >= rule.get("minOSR")) if (rule.get("minOSR") is not None) else True
    greenPctOk = (state["greenPctOfOSR"] >= rule.get("greenPctOfOSR")) if (rule.get("greenPctOfOSR") is not None) else True

    return {
        "w":w,"d":d,"bw":bw,"bd":bd,"buildable_area":buildable_area,"mainPlate":mainPlate,
        "maxGFA":maxGFA,"openSpaceArea":openSpaceArea,"greenArea":greenArea,
        "mainCFA_AG":mainCFA_AG,"mainCFA_BG":mainCFA_BG,"parkConCFA":(parkConCFA_AG+parkConCFA_BG),"parkAutoCFA":(parkAutoCFA_AG+parkAutoCFA_BG),
        "totalCFA":totalCFA,"estHeight":estHeight,"heightOk":heightOk,
        "convCarsPerFloor":convCarsPerFloor,"autoCarsPerFloor":autoCarsPerFloor,
        "totalConvCars":totalConvCars,"totalAutoCars":totalAutoCars,"openLotCars":openLotCars,
        "totalCars":totalCars,"disabledCars":disabledCars,
        "farCounted":farCounted,"farOk":farOk,
        "nla":(state["nlaPctOfCFA"]/100.0)*totalCFA, "nsa":(state["nsaPctOfCFA"]/100.0)*totalCFA, "gfa":(state["gfaOverCfaPct"]/100.0)*totalCFA,
        "ratio":ratio,
        # costs broken down
        "archTotal":archTotal,"interiorCost":interiorCost,"structCost":structCost,"mepCost":mepCost,
        "greenCost":greenCost,"parkingCost":parkingCost,"customCostTotal":customCostTotal,
        "constructionCost":constructionCost,"capexTotal":capexTotal,"budgetOk":budgetOk,
        # program
        "resNFA_per_floor":resNFA_per_floor,"resNFA_total":resNFA_total,"units1":units1,"units2":units2,"totalUnits":totalUnits,
        # legal
        "osrOk":osrOk,"greenPctOk":greenPctOk
    }

# =============================
# Sidebar — Site / Setbacks first (React-like placement)
# =============================
st.sidebar.header("Site & Zoning")
s = {**DEFAULT}

# Site area & FAR (pair)
c1, c2 = st.sidebar.columns(2)
s["siteArea"] = c1.number_input("Site Area (m²)", min_value=0.0, value=float(DEFAULT["siteArea"]), step=100.0)
s["far"] = c2.number_input("FAR (1–10)", min_value=1.0, max_value=10.0, value=float(DEFAULT["far"]), step=0.1)

# Dimension & Setbacks (together)
d1, d2 = st.sidebar.columns(2)
s["siteWidth"] = d1.number_input("Width (m)", min_value=0.0, value=float(DEFAULT["siteWidth"]), step=1.0)
s["siteDepth"] = d2.number_input("Depth (m)", min_value=0.0, value=float(DEFAULT["siteDepth"]), step=1.0)
sb = st.sidebar.columns(4)
s["setbackFront"] = sb[0].number_input("Front", min_value=0.0, value=float(DEFAULT["setbackFront"]), step=0.5)
s["setbackRear"]  = sb[1].number_input("Rear",  min_value=0.0, value=float(DEFAULT["setbackRear"]),  step=0.5)
s["setbackSideL"] = sb[2].number_input("Side-L",min_value=0.0, value=float(DEFAULT["setbackSideL"]), step=0.5)
s["setbackSideR"] = sb[3].number_input("Side-R",min_value=0.0, value=float(DEFAULT["setbackSideR"]), step=0.5)

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
st.sidebar.subheader("Geometry & Height")
g = st.sidebar.columns(3)
s["mainFloorsAG"] = g[0].number_input("Main AG", min_value=0, value=int(DEFAULT["mainFloorsAG"]), step=1)
s["mainFloorsBG"] = g[1].number_input("Main BG", min_value=0, value=int(DEFAULT["mainFloorsBG"]), step=1)
s["ftf"] = g[2].number_input("F2F (m)", min_value=0.0, value=float(DEFAULT["ftf"]), step=0.1)
g2 = st.sidebar.columns(3)
s["parkingConFloorsAG"] = g2[0].number_input("Park Conv AG", min_value=0, value=int(DEFAULT["parkingConFloorsAG"]), step=1)
s["parkingConFloorsBG"] = g2[1].number_input("Park Conv BG", min_value=0, value=int(DEFAULT["parkingConFloorsBG"]), step=1)
s["maxHeight"] = g2[2].number_input("Max Height (m)", min_value=0.0, value=float(DEFAULT["maxHeight"]), step=1.0)  # <— กลับมาแล้ว
g3 = st.sidebar.columns(2)
s["parkingAutoFloorsAG"] = g3[0].number_input("Park Auto AG", min_value=0, value=int(DEFAULT["parkingAutoFloorsAG"]), step=1)
s["parkingAutoFloorsBG"] = g3[1].number_input("Park Auto BG", min_value=0, value=int(DEFAULT["parkingAutoFloorsBG"]), step=1)

ppl = st.sidebar.columns(2)
s["parkingConPlate"]  = ppl[0].number_input("Conv Plate (m²)", min_value=0.0, value=float(DEFAULT["parkingConPlate"]), step=10.0)
s["parkingAutoPlate"] = ppl[1].number_input("Auto Plate (m²)", min_value=0.0, value=float(DEFAULT["parkingAutoPlate"]), step=10.0)

st.sidebar.caption("FAR flags")
ff = st.sidebar.columns(2)
s["countParkingInFAR"]  = (ff[0].selectbox("Count Parking?", ["Yes","No"], index=0) == "Yes")
s["countBasementInFAR"] = (ff[1].selectbox("Count Basement?", ["Yes","No"], index=0) == "Yes")

st.sidebar.divider()
st.sidebar.subheader("Parking Efficiency")
pe1, pe2 = st.sidebar.columns(2)
s["bayConv"] = pe1.number_input("Conv Bay (m²)", min_value=1.0, value=float(DEFAULT["bayConv"]), step=0.5)
s["circConvPct"] = pe2.number_input("Conv Circ (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["circConvPct"])*100, step=1.0)/100.0
s["bayAuto"] = pe1.number_input("Auto Bay (m²)", min_value=1.0, value=float(DEFAULT["bayAuto"]), step=0.5, key="autobay")
s["circAutoPct"] = pe2.number_input("Auto Circ (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["circAutoPct"])*100, step=1.0, key="autocirc")/100.0

st.sidebar.caption("Open-lot (ไม่นับ FAR)")
ol = st.sidebar.columns(3)
s["openLotArea"] = ol[0].number_input("Area (m²)", min_value=0.0, value=float(DEFAULT["openLotArea"]), step=10.0)
s["openLotBay"] = ol[1].number_input("Bay (m²/คัน)", min_value=1.0, value=float(DEFAULT["openLotBay"]), step=0.5)
s["openLotCircPct"] = ol[2].number_input("Circ (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["openLotCircPct"])*100, step=1.0)/100.0

st.sidebar.divider()
st.sidebar.subheader("Costs & Budget (THB)")
cb = st.sidebar.columns(2)
s["costArchPerSqm"] = cb[0].number_input("Architecture (฿/m²)", min_value=0.0, value=float(DEFAULT["costArchPerSqm"]), step=100.0)
s["interiorPctOfArch"] = cb[1].number_input("Interior (% of Arch total)", min_value=0.0, max_value=100.0, value=float(DEFAULT["interiorPctOfArch"]), step=1.0)  # NEW
s["costStructPerSqm"] = cb[0].number_input("Structure (฿/m²)",  min_value=0.0, value=float(DEFAULT["costStructPerSqm"]), step=100.0, key="struct")
s["costMEPPerSqm"]   = cb[1].number_input("MEP (฿/m²)",         min_value=0.0, value=float(DEFAULT["costMEPPerSqm"]),   step=100.0)
s["costGreenPerSqm"] = cb[0].number_input("Green (฿/m²)",       min_value=0.0, value=float(DEFAULT["costGreenPerSqm"]), step=100.0)
s["costConventionalPerCar"] = cb[1].number_input("Parking Conv (฿/car)", min_value=0.0, value=float(DEFAULT["costConventionalPerCar"]), step=1000.0)
s["costAutoPerCar"]         = cb[0].number_input("Parking Auto (฿/car)",  min_value=0.0, value=float(DEFAULT["costAutoPerCar"]),         step=1000.0)
s["costOpenLotPerCar"]      = cb[1].number_input("Open-lot (฿/car)",      min_value=0.0, value=float(DEFAULT["costOpenLotPerCar"]),      step=1000.0)
s["budget"] = st.sidebar.number_input("Budget (฿)", min_value=0.0, value=float(DEFAULT["budget"]), step=1_000_000.0)

# ---- Additional Costs (list style) ----
st.sidebar.caption("Additional Cost Items")
if "customCosts" not in st.session_state:
    st.session_state.customCosts = list(DEFAULT["customCosts"])
# list renderer (compact)
for idx, item in enumerate(st.session_state.customCosts):
    r = st.sidebar.columns([5,3,3,1])
    name = r[0].text_input(f"Name {idx+1}", value=item.get("name",""), key=f"cc_name_{idx}")
    kind = r[1].selectbox(f"Kind {idx+1}", options=["per_sqm","per_car_conv","per_car_auto","lump_sum"], index=["per_sqm","per_car_conv","per_car_auto","lump_sum"].index(item.get("kind","lump_sum")), key=f"cc_kind_{idx}")
    rate = r[2].number_input(f"Rate {idx+1}", value=float(item.get("rate",0.0)), step=100.0, key=f"cc_rate_{idx}")
    delcol = r[3].button("✕", key=f"cc_del_{idx}")
    if delcol:
        st.session_state.customCosts.pop(idx)
        st.rerun()
# add button
if st.sidebar.button("＋ Add Cost Item"):
    st.session_state.customCosts.append({"name":"Misc.","kind":"lump_sum","rate":0.0})
    st.rerun()
s["customCosts"] = st.session_state.customCosts

st.sidebar.divider()
st.sidebar.subheader("Condo Program (quick)")
cp = st.sidebar.columns(2)
s["unitEffPct"]  = cp[0].number_input("Net eff. of main plate (%)", min_value=50.0, max_value=95.0, value=float(DEFAULT["unitEffPct"]), step=1.0)
s["unit1BRSize"] = cp[1].number_input("1-BR size (m²)", min_value=20.0, value=float(DEFAULT["unit1BRSize"]), step=1.0)
s["unit2BRSize"] = cp[0].number_input("2-BR size (m²)", min_value=40.0, value=float(DEFAULT["unit2BRSize"]), step=1.0)
s["unit1BRMixPct"]= cp[1].number_input("Mix: 1-BR (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT["unit1BRMixPct"]), step=1.0)

# =============================
# Compute once
# =============================
d = compute(s)

# =============================
# Header KPIs
# =============================
st.title("🏗️ Feasibility (TH) — Minimal Mono")
k1,k2,k3,k4 = st.columns(4, gap="small")
with k1: st.metric("FAR Max.(m²)", nf(d["maxGFA"]))
with k2: st.metric("GFA (m²)", nf(d["farCounted"]))
with k3: st.metric("Est. Height (m)", nf(d["estHeight"]), delta=("OK" if d["heightOk"] else "Exceeds"))
with k4: st.metric("CAPEX (฿)", nf(d["capexTotal"]), delta=("OK" if d["budgetOk"] else "Over Budget"))

# =============================
# Three cards: Zoning / Areas (+ratios) / Parking
# =============================
cA,cB,cC = st.columns(3)
with cA:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Zoning")
    st.write(f"Open Space (OSR): **{nf(d['openSpaceArea'])}** m² ({s['osr']}%)")
    st.write(f"Green: **{nf(d['greenArea'])}** m² ({s['greenPctOfOSR']}% of OSR)")
    st.write(f"FAR check: {'✅ OK' if d['farOk'] else '❌ Exceeds'}")
    st.markdown('</div>', unsafe_allow_html=True)

with cB:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Areas")
    st.write(f"Main CFA (AG): **{nf(d['mainCFA_AG'])}** m²")
    st.write(f"Main CFA (BG): **{nf(d['mainCFA_BG'])}** m²")
    st.write(f"Parking CFA (Conv): **{nf(d['parkConCFA'])}** m²")
    st.write(f"Parking CFA (Auto): **{nf(d['parkAutoCFA'])}** m²")
    st.write(f"Total CFA: **{nf(d['totalCFA'])}** m²")
    st.markdown("---")
    st.caption("Efficiency Ratios")
    r1,r2,r3,r4 = st.columns(4)
    r1.metric("NLA/CFA", f"{d['ratio']['nla_cfa']*100:.1f}%")
    r2.metric("NSA/GFA", f"{d['ratio']['nsa_gfa']*100:.1f}%")
    r3.metric("NSA/CFA", f"{d['ratio']['nsa_cfa']*100:.1f}%")
    r4.metric("NLA/GFA", f"{d['ratio']['nla_gfa']*100:.1f}%")
    st.markdown('</div>', unsafe_allow_html=True)

with cC:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Parking")
    st.write(f"Cars/Floor (Conv): **{d['convCarsPerFloor']}**")
    st.write(f"Cars/Floor (Auto): **{d['autoCarsPerFloor']}**")
    st.write(f"Open-lot Cars: **{d['openLotCars']}**")
    st.write(f"Total Cars: **{d['totalCars']}** · Disabled: **{d['disabledCars']}**")
    st.markdown('</div>', unsafe_allow_html=True)

# =============================
# Site Diagram + CAPEX donut (compact)
# =============================
s1, s2 = st.columns([2,1], gap="large")

with s1:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Site & Setbacks Diagram (Green overlay)")
    if d["w"]>0 and d["d"]>0:
        fig2 = go.Figure()
        # site
        fig2.add_shape(type="rect", x0=0, y0=0, x1=d["w"], y1=d["d"], line=dict(color="#111827"), fillcolor="#ffffff")
        # buildable
        bx0,by0 = s["setbackSideL"], s["setbackFront"]
        bx1,by1 = max(bx0, d["w"]-s["setbackSideR"]), max(by0, d["d"]-s["setbackRear"])
        fig2.add_shape(type="rect", x0=bx0, y0=by0, x1=bx1, y1=by1, line=dict(color="#6b7280"), fillcolor="#e5e7eb")
        # OSR approximate (center block)
        osr_ratio = clamp(s["osr"]/100.0, 0.0, 1.0)
        osrW = d["w"] * (osr_ratio**0.5); osrD = d["d"]*(osr_ratio**0.5)
        cx,cy = d["w"]/2, d["d"]/2
        fig2.add_shape(type="rect", x0=cx-osrW/2, y0=cy-osrD/2, x1=cx+osrW/2, y1=cy+osrD/2, line=dict(color="#6b7280"), fillcolor="#d1d5db")
        # green (subset)
        green_ratio = clamp(d["greenArea"]/max(1e-9, d["openSpaceArea"]), 0.0, 1.0) if s["osr"]>0 else 0.0
        gW = osrW*(green_ratio**0.5); gD = osrD*(green_ratio**0.5)
        fig2.add_shape(type="rect", x0=cx-gW/2, y0=cy-gD/2, x1=cx+gW/2, y1=cy+gD/2, line=dict(color="#16a34a"), fillcolor="#86efac")
        # label
        fig2.add_annotation(x=d["w"]/2, y=d["d"]+0.6, showarrow=False,
            text=f"Site: {nf(s['siteArea'])} m² • Buildable: {nf(d['buildable_area'])} m² • Main Plate: {nf(d['mainPlate'])} m²")
        fig2.update_xaxes(range=[-1,d["w"]+1],visible=False); fig2.update_yaxes(range=[-1,d["d"]+1],scaleanchor="x",scaleratio=1,visible=False)
        fig2.update_layout(height=330, template="plotly_white", margin=dict(l=8,r=8,t=8,b=8))
        st.plotly_chart(fig2, use_container_width=True)
        # note
        if abs(d["w"]*d["d"] - s["siteArea"])>1e-6:
            st.caption("⚠️ Width×Depth != Site Area — ใช้เพื่อสเกลภาพ (การคำนวณยึด Site Area)")

    else:
        st.info("กรอก Width/Depth เพื่อดูแผนภาพ")

    st.markdown('</div>', unsafe_allow_html=True)

with s2:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("CAPEX Breakdown")
    capex_df = pd.DataFrame([
        {"name":"Architecture","value":max(0,d["archTotal"])},
        {"name":"Interior","value":max(0,d["interiorCost"])},
        {"name":"Structure","value":max(0,d["structCost"])},
        {"name":"MEP","value":max(0,d["mepCost"])},
        {"name":"Green","value":max(0,d["greenCost"])},
        {"name":"Parking","value":max(0,d["parkingCost"])},
        {"name":"Custom","value":max(0,d["customCostTotal"])},
    ])
    COLOR_MAP = {
        "Architecture":"#111827","Interior":"#4b5563","Structure":"#6b7280",
        "MEP":"#9ca3af","Green":"#22c55e","Parking":"#a3a3a3","Custom":"#d1d5db"
    }
    fig = px.pie(capex_df, values="value", names="name", hole=0.55, color="name", color_discrete_map=COLOR_MAP)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(template="plotly_white", height=330, margin=dict(l=4,r=4,t=4,b=4), legend=dict(orientation="h",yanchor="bottom",y=-0.1,xanchor="center",x=0.5))
    st.plotly_chart(fig, use_container_width=True)
    st.markdown('<div class="small">Total CAPEX: <b>฿{} </b>{}</div>'.format(nf(d["capexTotal"]), "✅ within budget" if d["budgetOk"] else "❌ over budget"), unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# =============================
# Condo quick program (1-BR/2-BR)
# =============================
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Condo Program — quick estimate from main plate × 85%")
colu = st.columns(4)
colu[0].metric("Net per floor (m²)", nf(d["resNFA_per_floor"]))
colu[1].metric("Total net (m²)", nf(d["resNFA_total"]))
colu[2].metric("Units (1-BR)", f"{d['units1']}")
colu[3].metric("Units (2-BR)", f"{d['units2']}")
st.caption("หมายเหตุ: ใช้ Main floor plate × {:.0f}% × ชั้นพักอาศัย (Main AG) และกระจายยูนิตตามสัดส่วน 1-BR/2-BR".format(s["unitEffPct"]))
st.markdown('</div>', unsafe_allow_html=True)

# =============================
# Export / Import (CSV Field,Value) — JSON-safe for lists/dicts
# =============================
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Export / Import")
export_rows = []
for k,v in s.items():
    if isinstance(v,(list,dict)):
        export_rows.append({"Field":k,"Value":json.dumps(v, ensure_ascii=False)})
    else:
        export_rows.append({"Field":k,"Value":v})
csv_str = create_csv(export_rows)
cA, cB = st.columns(2)
cA.download_button("⬇️ Export CSV", data=csv_str, file_name="scenario.csv", mime="text/csv")
template_rows = [{"Field":k,"Value": (DEFAULT[k] if not isinstance(DEFAULT[k],(list,dict)) else json.dumps(DEFAULT[k], ensure_ascii=False))}
                 for k in DEFAULT.keys()]
template_csv = create_csv(template_rows)
cB.download_button("⬇️ CSV Template", data=template_csv, file_name="scenario_template.csv", mime="text/csv")

up = st.file_uploader("⬆️ Import CSV (Field,Value)", type=["csv"])
if up is not None:
    try:
        df = pd.read_csv(up); imported={}
        for _,row in df.iterrows():
            k = str(row["Field"]); v = row["Value"]
            if isinstance(v,str) and v.strip().startswith(("{","[")):
                try: imported[k]=json.loads(v); continue
                except: pass
            try:
                v_str = str(v)
                if any(ch in v_str for ch in [".","e","E"]): imported[k]=float(v)
                else: imported[k]=int(v)
            except: imported[k]=v
        st.success("Imported (preview). หากต้องการตั้งเป็น DEFAULT โปรดแก้โค้ด DEFAULT")
        st.json(imported)
    except Exception as e:
        st.error(f"Import failed: {e}")
st.markdown('</div>', unsafe_allow_html=True)

# =============================
# Tests (quick sanity)
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

# recompute expected FAR with current plate/main setting
mAG = s["mainFloorsAG"] * d["mainPlate"]
mBG = s["mainFloorsBG"] * d["mainPlate"]
pcAG = s["parkingConFloorsAG"] * s["parkingConPlate"]
pcBG = s["parkingConFloorsBG"] * s["parkingConPlate"]
paAG = s["parkingAutoFloorsAG"] * s["parkingAutoPlate"]
paBG = s["parkingAutoFloorsBG"] * s["parkingAutoPlate"]
far_expected = compute_far_counted(mAG,mBG,pcAG,pcBG,paAG,paBG,s["countParkingInFAR"],s["countBasementInFAR"])
trow("computeFarCounted(default flags)", round(d["farCounted"]), round(far_expected))

openLotExpected = math.floor(s["openLotArea"]/max(1, s["openLotBay"]*(1+s["openLotCircPct"])))
trow("openLotCars formula", d["openLotCars"], openLotExpected)
st.markdown('</div>', unsafe_allow_html=True)
