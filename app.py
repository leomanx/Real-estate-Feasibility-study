# app.py — Feasibility Core (Streamlit)
# Run: streamlit run app.py

import json
import math
import streamlit as st

# =============================
# Helpers
# =============================
def nf(n, digits=2):
    try:
        x = float(n)
        return f"{x:,.{digits}f}" if digits > 0 else f"{int(round(x)):,}"
    except Exception:
        return "–"

def clamp(v, lo, hi):
    return min(hi, max(lo, v))

def create_csv(rows):
    if not rows:
        return ""
    headers = list(rows[0].keys())
    lines = [",".join(headers)]
    for r in rows:
        lines.append(",".join(str(r[h]) for h in headers))
    return "\n".join(lines)

# Disabled parking rule (TH typical)
def calc_disabled_parking(total_cars: float) -> int:
    tc = int(math.floor(max(0.0, total_cars)))
    if tc <= 0: return 0
    if tc <= 50: return 2
    if tc <= 100: return 3
    extra_hund = math.ceil((tc - 100) / 100)
    return 3 + max(0, extra_hund)

# FAR counting helper (kept for tests/back-compat)
def compute_far_counted(mainAG, mainBG, pcAG, pcBG, paAG, paBG, countParking, countBasement):
    far_counted = 0.0
    far_counted += mainAG + (mainBG if countBasement else 0.0)
    if countParking:
        far_counted += pcAG + (pcBG if countBasement else 0.0)
        far_counted += paAG + (paBG if countBasement else 0.0)
    return far_counted

# =============================
# Defaults
# =============================
RULES = {"base": {"farRange": (1.0, 10.0)}}

DEFAULT = dict(
    name="Scenario A",
    # Site & FAR
    siteArea=8000.0,
    far=5.0,
    # Geometry
    mainFloorsAG=20.0,
    mainFloorsBG=0.0,
    parkingConFloorsAG=3.0,
    parkingConFloorsBG=0.0,
    parkingAutoFloorsAG=0.0,
    parkingAutoFloorsBG=0.0,
    ftf=3.2,
    maxHeight=120.0,
    # Plates (m²)
    mainFloorPlate=1500.0,
    parkingConPlate=1200.0,
    parkingAutoPlate=800.0,
    # Parking efficiency
    bayConv=25.0,
    circConvPct=0.0,   # 0..1
    bayAuto=16.0,
    circAutoPct=0.0,   # 0..1
    # Open-lot (optional at-grade)
    openLotArea=0.0,
    openLotBay=25.0,
    openLotCircPct=0.0,  # 0..1
    # Efficiency core (from GFA)
    gfaOverCfaPct=95.0,
    publicPctOfGFA=10.0,
    bohPctOfGFA=8.0,
    servicePctOfGFA=2.0,
    # FAR toggles (kept for tests)
    countParkingInFAR=True,
    countBasementInFAR=False,
    # Costs core (฿/m²)
    costMainPerSqm=30000.0,
    costParkConvPerSqm=18000.0,
    costParkAutoPerSqm=25000.0,
    # Budget
    budget=500_000_000.0,
)

# =============================
# Session state
# =============================
if "scenario" not in st.session_state:
    st.session_state.scenario = DEFAULT.copy()
if "custom_costs" not in st.session_state:
    # {id, name, kind: "per_sqm"|"lump_sum", rate: float}
    st.session_state.custom_costs = []

s = st.session_state.scenario

st.set_page_config(page_title="Feasibility Core", layout="wide")

# Minimal white/gray/black theme
st.markdown("""
<style>
/* Minimal monochrome look */
:root {
  --bg: #111315;
  --panel: #1a1d21;
  --muted: #9aa4af;
  --text: #e6e9ed;
  --accent: #e5e7eb; /* neutral gray */
  --border: #2a2f35;
}
html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg);
  color: var(--text);
}
section.main > div { padding-top: 1rem; }
.block-container { padding-top: 1.2rem; }
div.stButton > button, button[kind="primary"] {
  border-radius: 10px;
}
div[data-testid="stNumberInput"] input, select, textarea {
  background: var(--panel) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
}
div[data-testid="stNumberInput"] label, label, .stMarkdown, .stText {
  color: var(--text) !important;
}
div[data-testid="stMetric"] {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 10px;
}
hr { border-color: var(--border) }
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 14px 14px 6px 14px;
}
.badge-ok   { color: #22c55e; font-weight: 600; }
.badge-warn { color: #ef4444; font-weight: 600; }
.small { color: var(--muted); font-size: 12px; }
.mono { font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
""", unsafe_allow_html=True)

st.title("Feasibility — Core (Streamlit)")

# =============================
# Layout — compact groups
# =============================
colA, colB, colC = st.columns([1.2, 1.2, 1.2])

with colA:
    st.markdown("#### Site & FAR")
    s["siteArea"] = st.number_input("Site Area (m²)", min_value=0.0, value=float(s["siteArea"]), step=100.0)
    s["far"] = st.number_input("FAR (1–10)", min_value=RULES["base"]["farRange"][0], max_value=RULES["base"]["farRange"][1], value=float(s["far"]), step=0.1)

with colB:
    st.markdown("#### Geometry & Height")
    g1, g2, g3 = st.columns(3, gap="small")
    s["mainFloorsAG"] = g1.number_input("Main Floors (AG)", min_value=0.0, value=float(s["mainFloorsAG"]), step=1.0)
    s["mainFloorsBG"] = g2.number_input("Main Floors (BG)", min_value=0.0, value=float(s["mainFloorsBG"]), step=1.0)
    s["ftf"]          = g3.number_input("F2F (m)",        min_value=0.0, value=float(s["ftf"]), step=0.1)

    g4, g5, g6 = st.columns(3, gap="small")
    s["parkingConFloorsAG"] = g4.number_input("Park Conv (AG)", min_value=0.0, value=float(s["parkingConFloorsAG"]), step=1.0)
    s["parkingConFloorsBG"] = g5.number_input("Park Conv (BG)", min_value=0.0, value=float(s["parkingConFloorsBG"]), step=1.0)
    s["maxHeight"]          = g6.number_input("Max Height (m)", min_value=0.0, value=float(s["maxHeight"]), step=1.0)

    g7, g8, g9 = st.columns(3, gap="small")
    s["parkingAutoFloorsAG"] = g7.number_input("Auto Park (AG)", min_value=0.0, value=float(s["parkingAutoFloorsAG"]), step=1.0)
    s["parkingAutoFloorsBG"] = g8.number_input("Auto Park (BG)", min_value=0.0, value=float(s["parkingAutoFloorsBG"]), step=1.0)
    st.write("")  # spacer

    g10, g11, g12 = st.columns(3, gap="small")
    s["mainFloorPlate"]    = g10.number_input("Main Plate (m²)",      min_value=0.0, value=float(s["mainFloorPlate"]), step=50.0)
    s["parkingConPlate"]   = g11.number_input("Park Plate (Conv)",    min_value=0.0, value=float(s["parkingConPlate"]), step=50.0)
    s["parkingAutoPlate"]  = g12.number_input("Park Plate (Auto)",    min_value=0.0, value=float(s["parkingAutoPlate"]), step=50.0)

    g13, g14, _ = st.columns(3, gap="small")
    s["countParkingInFAR"] = g13.selectbox("Count Parking in FAR?", options=[True, False], index=0 if s["countParkingInFAR"] else 1)
    s["countBasementInFAR"]= g14.selectbox("Count Basement in FAR?", options=[True, False], index=0 if s["countBasementInFAR"] else 1)

with colC:
    st.markdown("#### Parking & Efficiency")
    p1, p2, p3 = st.columns(3, gap="small")
    s["bayConv"]     = p1.number_input("Conv Bay (m²)",   min_value=1.0, value=float(s["bayConv"]), step=1.0)
    conv_circ_pct    = p2.number_input("Conv Circ (%)",   min_value=0.0, max_value=100.0, value=float(s["circConvPct"]*100.0), step=1.0)
    s["circConvPct"] = conv_circ_pct/100.0
    p3.markdown(f'<div class="small">eff = <span class="mono">{nf(s["bayConv"]*(1+s["circConvPct"]))}</span> m²/คัน</div>', unsafe_allow_html=True)

    p4, p5, p6 = st.columns(3, gap="small")
    s["bayAuto"]     = p4.number_input("Auto Bay (m²)",   min_value=1.0, value=float(s["bayAuto"]), step=1.0)
    auto_circ_pct    = p5.number_input("Auto Circ (%)",   min_value=0.0, max_value=100.0, value=float(s["circAutoPct"]*100.0), step=1.0)
    s["circAutoPct"] = auto_circ_pct/100.0
    p6.markdown(f'<div class="small">eff = <span class="mono">{nf(s["bayAuto"]*(1+s["circAutoPct"]))}</span> m²/คัน</div>', unsafe_allow_html=True)

    p7, p8, p9 = st.columns(3, gap="small")
    s["openLotArea"]     = p7.number_input("Open-lot Area (m²)", min_value=0.0, value=float(s["openLotArea"]), step=50.0)
    s["openLotBay"]      = p8.number_input("Open-lot Bay (m²/คัน)", min_value=1.0, value=float(s["openLotBay"]), step=1.0)
    open_circ_pct        = p9.number_input("Open-lot Circ (%)", min_value=0.0, max_value=100.0, value=float(s["openLotCircPct"]*100.0), step=1.0)
    s["openLotCircPct"]  = open_circ_pct/100.0
    st.markdown(f'<div class="small">eff (open-lot) = <span class="mono">{nf(s["openLotBay"]*(1+s["openLotCircPct"]))}</span> m²/คัน</div>', unsafe_allow_html=True)

st.divider()

colD, colE = st.columns([1.5, 1.5])

with colD:
    st.markdown("#### Efficiency Core")
    e1, e2, e3, e4 = st.columns(4, gap="small")
    s["gfaOverCfaPct"]  = e1.number_input("GFA from CFA (%)", min_value=0.0, max_value=100.0, value=float(s["gfaOverCfaPct"]), step=1.0)
    s["publicPctOfGFA"] = e2.number_input("Public (% of GFA)", min_value=0.0, max_value=100.0, value=float(s["publicPctOfGFA"]), step=1.0)
    s["bohPctOfGFA"]    = e3.number_input("BOH (% of GFA)",    min_value=0.0, max_value=100.0, value=float(s["bohPctOfGFA"]), step=1.0)
    s["servicePctOfGFA"]= e4.number_input("Service (% of GFA)",min_value=0.0, max_value=100.0, value=float(s["servicePctOfGFA"]), step=1.0)

with colE:
    st.markdown("#### Costs (฿/m²) & Budget")
    c1, c2, c3, c4 = st.columns(4, gap="small")
    s["costMainPerSqm"]     = c1.number_input("Main",         min_value=0.0, value=float(s["costMainPerSqm"]), step=500.0)
    s["costParkConvPerSqm"] = c2.number_input("Parking Conv", min_value=0.0, value=float(s["costParkConvPerSqm"]), step=500.0)
    s["costParkAutoPerSqm"] = c3.number_input("Parking Auto", min_value=0.0, value=float(s["costParkAutoPerSqm"]), step=500.0)
    s["budget"]             = c4.number_input("Budget (฿)",   min_value=0.0, value=float(s["budget"]), step=1_000_000.0)

    # Additional cost items (simple add/edit list)
    st.markdown("**Additional Cost Items**")
    add_col, _, _ = st.columns([0.25, 0.25, 0.5])
    if add_col.button("➕ Add item"):
        st.session_state.custom_costs.append({"id": int(st.session_state.get("id_seed", 0)) + 1, "name": "Misc.", "kind": "lump_sum", "rate": 0.0})
        st.session_state.id_seed = st.session_state.get("id_seed", 0) + 1

    if not st.session_state.custom_costs:
        st.caption("(ว่าง) — เพิ่ม per m² หรือ lump sum ได้")

    # Render items
    to_delete = []
    for idx, i in enumerate(st.session_state.custom_costs):
        name = st.text_input(f"Name #{i['id']}", value=i["name"], key=f"name_{i['id']}")
        kind = st.selectbox(f"Kind #{i['id']}", options=["per_sqm", "lump_sum"], index=0 if i["kind"]=="per_sqm" else 1, key=f"kind_{i['id']}")
        rate = st.number_input(f"Rate #{i['id']}", min_value=0.0, value=float(i["rate"]), step=1000.0, key=f"rate_{i['id']}")
        i["name"], i["kind"], i["rate"] = name, kind, float(rate)
        if st.button(f"🗑️ Remove #{i['id']}", key=f"del_{i['id']}"):
            to_delete.append(i["id"])
        st.markdown("<hr/>", unsafe_allow_html=True)
    if to_delete:
        st.session_state.custom_costs = [x for x in st.session_state.custom_costs if x["id"] not in to_delete]

# =============================
# Compute
# =============================
farMin, farMax = RULES["base"]["farRange"]
far = clamp(s["far"], farMin, farMax)
maxGFA = s["siteArea"] * far

# CFA blocks
mainCFA_AG   = s["mainFloorsAG"] * s["mainFloorPlate"]
mainCFA_BG   = s["mainFloorsBG"] * s["mainFloorPlate"]
parkConCFA_AG= s["parkingConFloorsAG"] * s["parkingConPlate"]
parkConCFA_BG= s["parkingConFloorsBG"] * s["parkingConPlate"]
parkAutoCFA_AG= s["parkingAutoFloorsAG"] * s["parkingAutoPlate"]
parkAutoCFA_BG= s["parkingAutoFloorsBG"] * s["parkingAutoPlate"]

mainCFA    = mainCFA_AG + mainCFA_BG
parkConCFA = parkConCFA_AG + parkConCFA_BG
parkAutoCFA= parkAutoCFA_AG + parkAutoCFA_BG
totalCFA   = mainCFA + parkConCFA + parkAutoCFA

# Height
estHeight = s["ftf"] * (s["mainFloorsAG"] + s["parkingConFloorsAG"] + s["parkingAutoFloorsAG"])
heightOk = estHeight <= s["maxHeight"]

# Parking counts
effAreaConCar = s["bayConv"] * (1 + s["circConvPct"])
effAreaAutoCar= s["bayAuto"] * (1 + s["circAutoPct"])
effAreaOpenCar= s["openLotBay"] * (1 + s["openLotCircPct"])

convCarsPerFloor = int(math.floor(s["parkingConPlate"] / max(1.0, effAreaConCar)))
autoCarsPerFloor = int(math.floor(s["parkingAutoPlate"] / max(1.0, effAreaAutoCar)))

totalConvCars = convCarsPerFloor * int(s["parkingConFloorsAG"] + s["parkingConFloorsBG"])
totalAutoCars = autoCarsPerFloor * int(s["parkingAutoFloorsAG"] + s["parkingAutoFloorsBG"])
openLotCars   = int(math.floor(s["openLotArea"] / max(1.0, effAreaOpenCar)))

totalCars = totalConvCars + totalAutoCars + openLotCars
disabledCars = calc_disabled_parking(totalCars)

# GFA (actual)
gfa = (s["gfaOverCfaPct"] / 100.0) * totalCFA
farOk = gfa <= maxGFA

# Costs core
costMain    = mainCFA    * s["costMainPerSqm"]
costParkConv= parkConCFA * s["costParkConvPerSqm"]
costParkAuto= parkAutoCFA* s["costParkAutoPerSqm"]

customCostTotal = 0.0
for i in st.session_state.custom_costs:
    if i["kind"] == "per_sqm":
        customCostTotal += i["rate"] * totalCFA
    else:
        customCostTotal += i["rate"]

projectCost = costMain + costParkConv + costParkAuto + customCostTotal
budgetOk = (projectCost <= s["budget"]) if s["budget"] > 0 else True
overUnder = projectCost - s["budget"] if s["budget"] > 0 else 0.0
overUnderPct = (overUnder / s["budget"] * 100.0) if s["budget"] > 0 else 0.0
avgCostPerGFA = (projectCost / gfa) if gfa > 0 else 0.0
avgCostPerCFA = (projectCost / totalCFA) if totalCFA > 0 else 0.0

# Efficiency split
publicArea  = (s["publicPctOfGFA"]  / 100.0) * gfa
bohArea     = (s["bohPctOfGFA"]     / 100.0) * gfa
serviceArea = (s["servicePctOfGFA"] / 100.0) * gfa
nsa = gfa - (bohArea + serviceArea)
nla = nsa + publicArea

# =============================
# Summary (compact cards)
# =============================
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Zoning / GFA**")
    st.metric("FAR Max (Max GFA) m²", nf(maxGFA, 2))
    st.metric("GFA (actual) m²", nf(gfa, 2))
    st.markdown(
        f'<div class="{ "badge-ok" if farOk else "badge-warn"}">'
        + ("FAR check: OK" if farOk else "FAR check: Exceeds") + "</div>",
        unsafe_allow_html=True
    )
    st.markdown("</div>", unsafe_allow_html=True)

with c2:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Areas**")
    st.markdown(f"Main CFA: **{nf(mainCFA)}** m²  \nParking CFA (Conv): **{nf(parkConCFA)}** m²  \nParking CFA (Auto): **{nf(parkAutoCFA)}** m²  \nTotal CFA: **{nf(totalCFA)}** m²")
    st.markdown("---")
    st.markdown(f"Public: **{nf(publicArea)}** m²  \nBOH: **{nf(bohArea)}** m² · Service: **{nf(serviceArea)}** m²")
    st.markdown(f"NSA: **{nf(nsa)}** m² · NLA (incl. Public): **{nf(nla)}** m²")
    st.markdown("</div>", unsafe_allow_html=True)

with c3:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Budget**")
    st.markdown(f"Project Cost: **฿{nf(projectCost)}**  \nBudget: **฿{nf(s['budget'])}**")
    st.markdown(
        f"Δ Budget: **{'+' if overUnder>=0 else ''}{nf(overUnder)} ฿** "
        f"(**{overUnderPct:+.1f}%**)"
    )
    st.markdown("---")
    st.markdown(f"Avg (฿/m² of GFA): **{nf(avgCostPerGFA)}**  \nAvg (฿/m² of CFA): **{nf(avgCostPerCFA)}**")
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown(" ")
c4, c5, c6 = st.columns(3)
with c4:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Height**")
    st.markdown(f"Estimated Height: **{nf(estHeight)}** m  \nMax Height: **{nf(s['maxHeight'])}** m")
    st.markdown(
        f'<div class="{ "badge-ok" if heightOk else "badge-warn"}">'
        + ("Height check: OK" if heightOk else "Height check: Exceeds") + "</div>",
        unsafe_allow_html=True
    )
    st.markdown("</div>", unsafe_allow_html=True)

with c5:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Parking**")
    st.markdown(
        f"Cars/Floor (Conv): **{convCarsPerFloor}**  \n"
        f"Cars/Floor (Auto): **{autoCarsPerFloor}**  \n"
        f"Open-lot Cars: **{openLotCars}**  \n"
        f"Total Cars (Conv): **{totalConvCars}**  \n"
        f"Total Cars (Auto): **{totalAutoCars}**  \n"
        f"Total Cars: **{totalCars}**  \n"
        f"Disabled Spaces: **{calc_disabled_parking(totalCars)}**"
    )
    st.markdown("</div>", unsafe_allow_html=True)

with c6:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("**Export / Import**")
    # Export JSON/CSV of current scenario + custom costs
    export_payload = dict(scenario=s, custom_costs=st.session_state.custom_costs)
    st.download_button("⬇️ Download JSON", data=json.dumps(export_payload, indent=2), file_name=f"{s.get('name','scenario').replace(' ','_')}.json")
    # CSV of scenario key-values
    rows = [{"Field": k, "Value": v} for k, v in s.items()]
    st.download_button("⬇️ Download CSV", data=create_csv(rows), file_name=f"{s.get('name','scenario').replace(' ','_')}.csv", mime="text/csv")
    st.markdown(" ")
    uploaded = st.file_uploader("Import JSON (scenario + custom_costs)", type=["json"])
    if uploaded is not None:
        try:
            data = json.loads(uploaded.read())
            if "scenario" in data:
                # keep numeric types as float
                for k, v in data["scenario"].items():
                    if isinstance(v, (int, float)):
                        data["scenario"][k] = float(v)
                st.session_state.scenario.update(data["scenario"])
            if "custom_costs" in data and isinstance(data["custom_costs"], list):
                # sanitize
                clean = []
                for i in data["custom_costs"]:
                    clean.append({
                        "id": int(i.get("id", 0)),
                        "name": str(i.get("name","Misc.")),
                        "kind": "per_sqm" if i.get("kind") == "per_sqm" else "lump_sum",
                        "rate": float(i.get("rate", 0.0))
                    })
                st.session_state.custom_costs = clean
            st.success("Imported.")
        except Exception as e:
            st.error(f"Import failed: {e}")
    st.markdown("</div>", unsafe_allow_html=True)

# =============================
# Tests
# =============================
st.markdown("#### Tests")
mAG = s["mainFloorsAG"] * s["mainFloorPlate"]
mBG = s["mainFloorsBG"] * s["mainFloorPlate"]
pcAG = s["parkingConFloorsAG"] * s["parkingConPlate"]
pcBG = s["parkingConFloorsBG"] * s["parkingConPlate"]
paAG = s["parkingAutoFloorsAG"] * s["parkingAutoPlate"]
paBG = s["parkingAutoFloorsBG"] * s["parkingAutoPlate"]

far_expected = compute_far_counted(mAG, mBG, pcAG, pcBG, paAG, paBG, s["countParkingInFAR"], s["countBasementInFAR"])
open_lot_expected_cars = int(math.floor(s["openLotArea"] / max(1.0, s["openLotBay"] * (1 + s["openLotCircPct"]))))

tests = [
    ("calcDisabledParking(0)",  calc_disabled_parking(0), 0),
    ("calcDisabledParking(50)", calc_disabled_parking(50), 2),
    ("calcDisabledParking(51)", calc_disabled_parking(51), 3),
    ("calcDisabledParking(100)",calc_disabled_parking(100),3),
    ("calcDisabledParking(101)",calc_disabled_parking(101),4),
    ("calcDisabledParking(250)",calc_disabled_parking(250),5),
    ("computeFarCounted(default flags matches compute)", far_expected, far_expected),
    ("computeFarCounted(no parking, no basement)",
        compute_far_counted(100,20,30,40,50,60, False, False), 100),
    ("computeFarCounted(parking+basement)",
        compute_far_counted(100,20,30,40,50,60, True, True), 300),
    ("openLotCars formula", openLotCars, open_lot_expected_cars),
]

ok_all = True
for name, actual, expected in tests:
    ok = actual == expected
    ok_all = ok_all and ok
    st.write(("✅" if ok else "❌"), f"**{name}** — actual: `{actual}` expected: `{expected}`")

if ok_all:
    st.success("All tests passed.")
else:
    st.warning("Some tests failed — please review formulas.")
