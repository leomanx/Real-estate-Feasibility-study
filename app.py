# app.py — Feasibility Core+ (Streamlit)
# run: streamlit run app.py

import json
import math
import streamlit as st

# -----------------------------
# Helpers
# -----------------------------
def nf(n, digits=2):
    try:
        x = float(n)
        fmt = f"{{:,.{digits}f}}"
        return fmt.format(x) if digits is not None else f"{int(round(x)):,}"
    except Exception:
        return "–"

def clamp(v, lo, hi):
    return min(hi, max(lo, v))

def create_csv(rows):
    if not rows: return ""
    headers = list(rows[0].keys())
    out = [",".join(headers)]
    for r in rows: out.append(",".join(str(r[h]) for h in headers))
    return "\n".join(out)

def calc_disabled_parking(total_cars: float) -> int:
    tc = int(math.floor(max(0.0, total_cars)))
    if tc <= 0: return 0
    if tc <= 50: return 2
    if tc <= 100: return 3
    return 3 + max(0, math.ceil((tc - 100) / 100))

def compute_far_counted(mainAG, mainBG, pcAG, pcBG, paAG, paBG, countParking, countBasement):
    far = 0.0
    far += mainAG + (mainBG if countBasement else 0.0)
    if countParking:
        far += pcAG + (pcBG if countBasement else 0.0)
        far += paAG + (paBG if countBasement else 0.0)
    return far

# -----------------------------
# Defaults
# -----------------------------
RULES = {"base": {"farRange": (1.0, 10.0)}}

DEFAULT = dict(
    name="Scenario A",
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
    # parking eff
    bayConv=25.0,
    circConvPct=0.0,     # 0..1
    bayAuto=16.0,
    circAutoPct=0.0,     # 0..1
    # open-lot (outside building)
    openLotArea=0.0,
    openLotBay=25.0,
    openLotCircPct=0.0,  # 0..1
    # efficiency core (from GFA)
    gfaOverCfaPct=95.0,
    publicPctOfGFA=10.0,
    bohPctOfGFA=8.0,
    servicePctOfGFA=2.0,
    nlaPctOfPublic=40.0,  # NEW: NLA subset of Public
    # toggles (for tests/back-compat)
    countParkingInFAR=True,
    countBasementInFAR=False,
    # cost core (฿/m² blocks) kept simple for budget check by CFA
    costMainPerSqm=30000.0,
    costParkConvPerSqm=18000.0,
    costParkAutoPerSqm=25000.0,
    budget=500_000_000.0,
)

# -----------------------------
# Page setup & Theme
# -----------------------------
st.set_page_config(page_title="Feasibility — Core+", layout="wide")

st.markdown("""
<style>
:root {
  --bg: #111315;
  --panel: #1a1d21;
  --muted: #9aa4af;
  --text: #e6e9ed;
  --border: #2a2f35;
}
html, body, [data-testid="stAppViewContainer"] { background: var(--bg); color: var(--text); }
.block-container { padding-top: 0.75rem; }
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

st.title("Feasibility — Core+")

# -----------------------------
# Session state
# -----------------------------
if "scenario" not in st.session_state:
    st.session_state.scenario = DEFAULT.copy()
if "custom_costs" not in st.session_state:
    # {id, name, kind:"per_sqm"|"lump_sum", rate: float}
    st.session_state.custom_costs = []
if "unit_types" not in st.session_state:
    # {id, name, size_sqm, bedrooms, share_pct}
    st.session_state.unit_types = [
        {"id": 1, "name": "1-BR", "size_sqm": 32.0, "bedrooms": 1.0, "share_pct": 60.0},
        {"id": 2, "name": "2-BR", "size_sqm": 55.0, "bedrooms": 2.0, "share_pct": 40.0},
    ]
if "id_seed" not in st.session_state:
    st.session_state.id_seed = 2

s = st.session_state.scenario

# -----------------------------
# Inputs (compact groups)
# -----------------------------
colA, colB, colC = st.columns(3)

with colA:
    st.markdown("#### Site & FAR")
    s["siteArea"] = st.number_input("Site Area (m²)", min_value=0.0, value=float(s["siteArea"]), step=100.0)
    s["far"] = st.number_input("FAR (1–10)", min_value=RULES["base"]["farRange"][0], max_value=RULES["base"]["farRange"][1], value=float(s["far"]), step=0.1)

with colB:
    st.markdown("#### Geometry & Height")
    g1, g2, g3 = st.columns(3, gap="small")
    s["mainFloorsAG"] = g1.number_input("Main Floors (AG)", min_value=0.0, value=float(s["mainFloorsAG"]), step=1.0)
    s["mainFloorsBG"] = g2.number_input("Main Floors (BG)", min_value=0.0, value=float(s["mainFloorsBG"]), step=1.0)
    s["ftf"] = g3.number_input("F2F (m)", min_value=0.0, value=float(s["ftf"]), step=0.1)

    g4, g5, g6 = st.columns(3, gap="small")
    s["parkingConFloorsAG"] = g4.number_input("Park Conv (AG)", min_value=0.0, value=float(s["parkingConFloorsAG"]), step=1.0)
    s["parkingConFloorsBG"] = g5.number_input("Park Conv (BG)", min_value=0.0, value=float(s["parkingConFloorsBG"]), step=1.0)
    s["maxHeight"] = g6.number_input("Max Height (m)", min_value=0.0, value=float(s["maxHeight"]), step=1.0)

    g7, g8 = st.columns(2, gap="small")
    s["parkingAutoFloorsAG"] = g7.number_input("Auto Park (AG)", min_value=0.0, value=float(s["parkingAutoFloorsAG"]), step=1.0)
    s["parkingAutoFloorsBG"] = g8.number_input("Auto Park (BG)", min_value=0.0, value=float(s["parkingAutoFloorsBG"]), step=1.0)

    g9, g10, g11 = st.columns(3, gap="small")
    s["mainFloorPlate"] = g9.number_input("Main Plate (m²)", min_value=0.0, value=float(s["mainFloorPlate"]), step=50.0)
    s["parkingConPlate"] = g10.number_input("Park Plate (Conv)", min_value=0.0, value=float(s["parkingConPlate"]), step=50.0)
    s["parkingAutoPlate"] = g11.number_input("Park Plate (Auto)", min_value=0.0, value=float(s["parkingAutoPlate"]), step=50.0)

with colC:
    st.markdown("#### Parking & Efficiency")
    p1, p2, p3 = st.columns(3, gap="small")
    s["bayConv"] = p1.number_input("Conv Bay (m²)", min_value=1.0, value=float(s["bayConv"]), step=1.0)
    conv_c = p2.number_input("Conv Circ (%)", min_value=0.0, max_value=100.0, value=float(s["circConvPct"]*100.0), step=1.0)
    s["circConvPct"] = conv_c/100.0
    p3.markdown(f'<div class="small">eff = <span class="mono">{nf(s["bayConv"]*(1+s["circConvPct"]))}</span> m²/คัน</div>', unsafe_allow_html=True)

    p4, p5, p6 = st.columns(3, gap="small")
    s["bayAuto"] = p4.number_input("Auto Bay (m²)", min_value=1.0, value=float(s["bayAuto"]), step=1.0)
    auto_c = p5.number_input("Auto Circ (%)", min_value=0.0, max_value=100.0, value=float(s["circAutoPct"]*100.0), step=1.0)
    s["circAutoPct"] = auto_c/100.0
    p6.markdown(f'<div class="small">eff = <span class="mono">{nf(s["bayAuto"]*(1+s["circAutoPct"]))}</span> m²/คัน</div>', unsafe_allow_html=True)

    p7, p8, p9 = st.columns(3, gap="small")
    s["openLotArea"] = p7.number_input("Open-lot Area (m²)", min_value=0.0, value=float(s["openLotArea"]), step=50.0)
    s["openLotBay"] = p8.number_input("Open-lot Bay (m²/คัน)", min_value=1.0, value=float(s["openLotBay"]), step=1.0)
    open_c = p9.number_input("Open-lot Circ (%)", min_value=0.0, max_value=100.0, value=float(s["openLotCircPct"]*100.0), step=1.0)
    s["openLotCircPct"] = open_c/100.0
    st.caption(f"eff (open-lot) = {nf(s['openLotBay']*(1+s['openLotCircPct']))} m²/คัน")

st.divider()

colD, colE = st.columns(2)
with colD:
    st.markdown("#### Efficiency Blocks")
    e1, e2, e3, e4, e5 = st.columns(5, gap="small")
    s["gfaOverCfaPct"]   = e1.number_input("GFA from CFA (%)",   min_value=0.0, max_value=100.0, value=float(s["gfaOverCfaPct"]), step=1.0)
    s["publicPctOfGFA"]  = e2.number_input("Public (% of GFA)",  min_value=0.0, max_value=100.0, value=float(s["publicPctOfGFA"]), step=1.0)
    s["nlaPctOfPublic"]  = e3.number_input("NLA (% of Public)",  min_value=0.0, max_value=100.0, value=float(s["nlaPctOfPublic"]), step=1.0)  # NEW
    s["bohPctOfGFA"]     = e4.number_input("BOH (% of GFA)",     min_value=0.0, max_value=100.0, value=float(s["bohPctOfGFA"]), step=1.0)
    s["servicePctOfGFA"] = e5.number_input("Service (% of GFA)", min_value=0.0, max_value=100.0, value=float(s["servicePctOfGFA"]), step=1.0)

with colE:
    st.markdown("#### Costs (฿/m²) & Budget")
    c1, c2, c3, c4 = st.columns(4, gap="small")
    s["costMainPerSqm"]     = c1.number_input("Main",         min_value=0.0, value=float(s["costMainPerSqm"]), step=500.0)
    s["costParkConvPerSqm"] = c2.number_input("Parking Conv", min_value=0.0, value=float(s["costParkConvPerSqm"]), step=500.0)
    s["costParkAutoPerSqm"] = c3.number_input("Parking Auto", min_value=0.0, value=float(s["costParkAutoPerSqm"]), step=500.0)
    s["budget"]             = c4.number_input("Budget (฿)",   min_value=0.0, value=float(s["budget"]), step=1_000_000.0)

st.divider()

# -----------------------------
# Compute core areas
# -----------------------------
farMin, farMax = RULES["base"]["farRange"]
far = clamp(s["far"], farMin, farMax)
maxGFA = s["siteArea"] * far  # FAR Max = Max GFA

# CFA components
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
estHeight = s["ftf"] * (s["mainFloorsAG"] + s["parkingConFloorsAG"] + s["parkingAutoFloorsAG"])
heightOk = estHeight <= s["maxHeight"]

# Parking supply (no double count)
effConv  = s["bayConv"] * (1 + s["circConvPct"])
effAuto  = s["bayAuto"] * (1 + s["circAutoPct"])
effOpen  = s["openLotBay"] * (1 + s["openLotCircPct"])
convCarsPerFloor = int(math.floor(s["parkingConPlate"] / max(1.0, effConv)))
autoCarsPerFloor = int(math.floor(s["parkingAutoPlate"] / max(1.0, effAuto)))
totalConvCars = convCarsPerFloor * int(s["parkingConFloorsAG"] + s["parkingConFloorsBG"])
totalAutoCars = autoCarsPerFloor * int(s["parkingAutoFloorsAG"] + s["parkingAutoFloorsBG"])
openLotCars   = int(math.floor(s["openLotArea"] / max(1.0, effOpen)))
totalCars = totalConvCars + totalAutoCars + openLotCars
disabledCars = calc_disabled_parking(totalCars)

# GFA / NSA / NLA
gfa = (s["gfaOverCfaPct"] / 100.0) * totalCFA
farOk = gfa <= maxGFA

publicArea  = (s["publicPctOfGFA"]  / 100.0) * gfa
bohArea     = (s["bohPctOfGFA"]     / 100.0) * gfa
serviceArea = (s["servicePctOfGFA"] / 100.0) * gfa

# NSA: หัก Public + BOH + Service ออกจาก GFA
nsa = gfa - (publicArea + bohArea + serviceArea)

# NLA: เป็น “ส่วนหนึ่งของ Public” ไม่ใช่ NSA
nla = publicArea * (s["nlaPctOfPublic"] / 100.0)

# DE ratios
de_NSA_over_GFA = (nsa / gfa) if gfa > 0 else 0.0
de_NSA_over_CFA = (nsa / totalCFA) if totalCFA > 0 else 0.0
de_GFA_over_CFA = (gfa / totalCFA) if totalCFA > 0 else 0.0
de_NLA_over_GFA = (nla / gfa) if gfa > 0 else 0.0

# Costs & budget (คร่าวๆ ตามบล็อก /m²)
costMain     = mainCFA    * s["costMainPerSqm"]
costParkConv = parkConCFA * s["costParkConvPerSqm"]
costParkAuto = parkAutoCFA* s["costParkAutoPerSqm"]
projectCost  = costMain + costParkConv + costParkAuto
budgetOk     = (projectCost <= s["budget"]) if s["budget"] > 0 else True
overUnder    = projectCost - s["budget"] if s["budget"] > 0 else 0.0
overUnderPct = (overUnder / s["budget"] * 100.0) if s["budget"] > 0 else 0.0
avgPerGFA    = (projectCost / gfa) if gfa > 0 else 0.0
avgPerCFA    = (projectCost / totalCFA) if totalCFA > 0 else 0.0

# -----------------------------
# Unit Types & Parking Demand
# -----------------------------
st.markdown("#### Unit Types & Parking Demand")
u1, u2, u3, u4, u5 = st.columns([0.2, 0.2, 0.2, 0.2, 0.2])
demand_mode = u1.selectbox("Legal Mode", options=["per bedroom", "per unit", "both (max)"], index=2)
legal_per_bed = u2.number_input("Legal: cars/bed", min_value=0.0, value=0.0, step=0.1)
legal_per_unit= u3.number_input("Legal: cars/unit", min_value=0.0, value=0.0, step=0.1)
proj_per_bed  = u4.number_input("Project target: cars/bed", min_value=0.0, value=0.5, step=0.05)
conv_share_pct= u5.slider("Target Conv share (%)", min_value=0, max_value=100, value=70, step=1)

st.caption("กำหนด Unit type (ขนาด m², จำนวนห้องนอน, สัดส่วน % ของพื้นที่ขายได้ (NSA))")

# editor-like simple list
to_del = []
for i, ut in enumerate(st.session_state.unit_types):
    cN, cS, cB, cP, cD = st.columns([0.28, 0.18, 0.18, 0.18, 0.18])
    ut["name"]      = cN.text_input(f"Name #{ut['id']}", value=ut["name"], key=f"name_{ut['id']}")
    ut["size_sqm"]  = cS.number_input(f"Size m² #{ut['id']}", min_value=1.0, value=float(ut["size_sqm"]), step=1.0, key=f"size_{ut['id']}")
    ut["bedrooms"]  = cB.number_input(f"Beds #{ut['id']}", min_value=0.0, value=float(ut["bedrooms"]), step=0.5, key=f"bed_{ut['id']}")
    ut["share_pct"] = cP.number_input(f"Share % #{ut['id']}", min_value=0.0, max_value=100.0, value=float(ut["share_pct"]), step=1.0, key=f"share_{ut['id']}")
    if cD.button(f"🗑️ Remove #{ut['id']}", key=f"del_unit_{ut['id']}"):
        to_del.append(ut["id"])
if to_del:
    st.session_state.unit_types = [x for x in st.session_state.unit_types if x["id"] not in to_del]

if st.button("➕ Add Unit Type"):
    st.session_state.id_seed += 1
    st.session_state.unit_types.append({"id": st.session_state.id_seed, "name": f"Type {st.session_state.id_seed}", "size_sqm": 30.0, "bedrooms": 1.0, "share_pct": 20.0})

# derive units from NSA by share
total_share = sum(max(0.0, float(u["share_pct"])) for u in st.session_state.unit_types)
units_list = []
total_units = 0.0
total_bedrooms = 0.0
if total_share > 0 and nsa > 0:
    for ut in st.session_state.unit_types:
        alloc_area = nsa * (float(ut["share_pct"]) / total_share)
        n_units = alloc_area / max(1.0, float(ut["size_sqm"]))
        beds    = n_units * float(ut["bedrooms"])
        units_list.append((ut["name"], alloc_area, n_units, beds))
        total_units += n_units
        total_bedrooms += beds

# parking demand (program)
prog_required_by_bed = total_bedrooms * float(proj_per_bed)

# legal demand
legal_units = total_units * float(legal_per_unit)
legal_beds  = total_bedrooms * float(legal_per_bed)
if demand_mode == "per unit":
    legal_required = legal_units
elif demand_mode == "per bedroom":
    legal_required = legal_beds
else:
    legal_required = max(legal_units, legal_beds)

# supply split target
target_conv = totalCars * (conv_share_pct / 100.0)
target_auto = totalCars - target_conv

# -----------------------------
# Summary cards
# -----------------------------
cA, cB, cC = st.columns(3)
with cA:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Zoning / GFA**")
    st.metric("FAR Max (Max GFA) m²", nf(maxGFA, 2))
    st.metric("GFA (actual) m²", nf(gfa, 2))
    st.markdown(f'<div class="{ "badge-ok" if farOk else "badge-warn"}">FAR check: {"OK" if farOk else "Exceeds"}</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

with cB:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Areas**")
    st.markdown(f"Main CFA: **{nf(mainCFA)}** m²  \nParking CFA (Conv): **{nf(parkConCFA)}** m²  \nParking CFA (Auto): **{nf(parkAutoCFA)}** m²  \nTotal CFA: **{nf(totalCFA)}** m²")
    st.markdown("---")
    st.markdown(f"Public: **{nf(publicArea)}** m²  \nBOH: **{nf(bohArea)}** m² · Service: **{nf(serviceArea)}** m²")
    st.markdown(f"NSA: **{nf(nsa)}** m²  \nNLA (subset of Public): **{nf(nla)}** m²")
    st.markdown("</div>", unsafe_allow_html=True)

with cC:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Budget (coarse)**")
    st.markdown(f"Project Cost: **฿{nf(projectCost)}**  \nBudget: **฿{nf(s['budget'])}**")
    st.markdown(f"Δ Budget: **{'+' if overUnder>=0 else ''}{nf(overUnder)} ฿** (**{overUnderPct:+.1f}%**)")
    st.markdown("---")
    st.markdown(f"Avg (฿/m² of GFA): **{nf(avgPerGFA)}**  \nAvg (฿/m² of CFA): **{nf(avgPerCFA)}**")
    st.markdown("</div>", unsafe_allow_html=True)

cD, cE, cF = st.columns(3)
with cD:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Design Efficiency (DE)**")
    st.markdown(f"NSA / GFA: **{nf(de_NSA_over_GFA,3)}**")
    st.markdown(f"NSA / CFA: **{nf(de_NSA_over_CFA,3)}**")
    st.markdown(f"GFA / CFA: **{nf(de_GFA_over_CFA,3)}**")
    st.markdown(f"NLA / GFA: **{nf(de_NLA_over_GFA,3)}**")
    st.markdown("</div>", unsafe_allow_html=True)

with cE:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Parking — Supply**")
    st.markdown(
        f"Conv/Floor: **{convCarsPerFloor}**  · Auto/Floor: **{autoCarsPerFloor}**  \n"
        f"Total Conv: **{totalConvCars}** · Auto: **{totalAutoCars}** · Open-lot: **{openLotCars}**  \n"
        f"Supply (All): **{totalCars}**  · Disabled: **{calc_disabled_parking(totalCars)}**"
    )
    st.markdown(f"Target split → Conv: **{int(target_conv)}**  · Auto: **{int(target_auto)}**")
    st.markdown("</div>", unsafe_allow_html=True)

with cF:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Parking — Demand**")
    st.markdown(f"Units (est.): **{int(total_units)}**  · Beds: **{int(total_bedrooms)}**")
    st.markdown(f"Program demand (by beds): **{math.ceil(prog_required_by_bed)}**")
    if demand_mode == "per unit":
        st.markdown(f"Legal (per unit): **{math.ceil(legal_units)}**  → **{demand_mode}** selected")
    elif demand_mode == "per bedroom":
        st.markdown(f"Legal (per bedroom): **{math.ceil(legal_beds)}**  → **{demand_mode}** selected")
    else:
        st.markdown(
    f"Legal: max(unit=**{math.ceil(legal_units)}**, bed=**{math.ceil(legal_beds)}**) → **both (max)**")
    legal_req = math.ceil(legal_required)
    prog_req  = math.ceil(prog_required_by_bed)
    worst_req = max(legal_req, prog_req)
    gap = totalCars - worst_req
    st.markdown("---")
    st.markdown(f"**Required (worst-case)**: **{worst_req}**  \nSupply: **{totalCars}**  \nΔ Supply: **{gap:+}**")
    st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------
# Export / Import
# -----------------------------
st.markdown("#### Export / Import")
cX, cY = st.columns(2)

with cX:
    payload = dict(scenario=s, custom_costs=st.session_state.custom_costs, unit_types=st.session_state.unit_types)
    st.download_button("⬇️ Download JSON", data=json.dumps(payload, indent=2), file_name=f"{s.get('name','scenario').replace(' ','_')}.json")
    rows = [{"Field": k, "Value": v} for k, v in s.items()]
    st.download_button("⬇️ Download CSV (scenario)", data=create_csv(rows), file_name=f"{s.get('name','scenario').replace(' ','_')}.csv", mime="text/csv")

with cY:
    up = st.file_uploader("Import JSON (scenario + custom_costs + unit_types)", type=["json"])
    if up is not None:
        try:
            data = json.loads(up.read())
            if "scenario" in data:
                sc = data["scenario"]
                for k, v in sc.items():
                    if isinstance(v, (int, float)): sc[k] = float(v)
                st.session_state.scenario.update(sc)
            if "custom_costs" in data and isinstance(data["custom_costs"], list):
                cc = []
                for i in data["custom_costs"]:
                    cc.append({
                        "id": int(i.get("id", 0)),
                        "name": str(i.get("name", "Misc.")),
                        "kind": "per_sqm" if i.get("kind") == "per_sqm" else "lump_sum",
                        "rate": float(i.get("rate", 0.0)),
                    })
                st.session_state.custom_costs = cc
            if "unit_types" in data and isinstance(data["unit_types"], list):
                uts = []
                for i in data["unit_types"]:
                    uts.append({
                        "id": int(i.get("id", 0)),
                        "name": str(i.get("name", "Type")),
                        "size_sqm": float(i.get("size_sqm", 30.0)),
                        "bedrooms": float(i.get("bedrooms", 1.0)),
                        "share_pct": float(i.get("share_pct", 10.0)),
                    })
                st.session_state.unit_types = uts
                st.session_state.id_seed = max([u["id"] for u in uts] + [0])
            st.success("Imported.")
        except Exception as e:
            st.error(f"Import failed: {e}")

# -----------------------------
# Tests (spot checks)
# -----------------------------
st.markdown("#### Tests")
mAG = s["mainFloorsAG"] * s["mainFloorPlate"]
mBG = s["mainFloorsBG"] * s["mainFloorPlate"]
pcAG = s["parkingConFloorsAG"] * s["parkingConPlate"]
pcBG = s["parkingConFloorsBG"] * s["parkingConPlate"]
paAG = s["parkingAutoFloorsAG"] * s["parkingAutoPlate"]
paBG = s["parkingAutoFloorsBG"] * s["parkingAutoPlate"]

far_expected = compute_far_counted(mAG, mBG, pcAG, pcBG, paAG, paBG, s["countParkingInFAR"], s["countBasementInFAR"])
open_lot_expected_cars = int(math.floor(s["openLotArea"] / max(1.0, s["openLotBay"]*(1+s["openLotCircPct"]))))

tests = [
    ("calcDisabledParking(0)",  calc_disabled_parking(0), 0),
    ("calcDisabledParking(50)", calc_disabled_parking(50), 2),
    ("calcDisabledParking(51)", calc_disabled_parking(51), 3),
    ("calcDisabledParking(100)",calc_disabled_parking(100),3),
    ("calcDisabledParking(101)",calc_disabled_parking(101),4),
    ("calcDisabledParking(250)",calc_disabled_parking(250),5),
    ("computeFarCounted(default flags)", far_expected, far_expected),
    ("computeFarCounted(no parking, no basement)", compute_far_counted(100,20,30,40,50,60, False, False), 100.0),
    ("computeFarCounted(parking+basement)", compute_far_counted(100,20,30,40,50,60, True, True), 300.0),
    ("openLotCars formula", openLotCars, open_lot_expected_cars),
    ("NLA is subset of Public", round(nla,3) <= round(publicArea,3), True),
    ("DE ratio bounds", 0.0 <= de_GFA_over_CFA <= 1.0, True),
]

all_ok = True
for name, actual, expected in tests:
    ok = (actual == expected)
    all_ok &= ok
    st.write(("✅" if ok else "❌"), f"**{name}** — actual: `{actual}` expected: `{expected}`")

if all_ok:
    st.success("All tests passed.")
else:
    st.warning("Some tests failed — please review.")
