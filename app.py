# app.py — Feasibility High-rise Condominium (Streamlit v1 compact + charts)
# pip install streamlit pandas numpy plotly

import math
from typing import Dict, List

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------- UI setup / theme (black/gray/white) ----------------
st.set_page_config(page_title="Feasibility High-rise Condominium", page_icon="🏗️", layout="wide")
st.markdown("""
<style>
  .stApp { background:#0f1115; }
  .block-container { padding-top: 0.8rem; padding-bottom: 1.2rem; }
  h1,h2,h3,h4,h5,h6, p, label, span, div, code, .stMarkdown { color:#e6e6e6; }
  .card { background:#141821; border:1px solid #2a2f3a; border-radius:14px; padding:14px; }
  .stNumberInput>div>div, div[data-baseweb="select"]>div { background:#171a21; }
  .stButton>button, .stDownloadButton>button { background:#171a21; color:#e6e6e6; border:1px solid #2a2f3a; border-radius:10px; }
  .tight .stHorizontalBlock { gap:.6rem; }
  .tight .st-emotion-cache-1r6slb0 { padding: 0.25rem 0; } /* compact labels */
</style>
""", unsafe_allow_html=True)

# ---------------- Helpers ----------------
def nf(x, d=2):
    try: return f"{float(x):,.{d}f}"
    except: return "–"

def create_csv_rows(d: Dict) -> str:
    lines = ["Field,Value"]
    for k, v in d.items(): lines.append(f"{k},{v}")
    return "\n".join(lines)

def parse_csv_to_dict(text: str) -> Dict:
    out = {}
    for line in [r for r in text.splitlines()[1:] if r.strip()]:
        k, v = line.split(",", 1)
        v = v.strip()
        try:
            vv = float(v) if v.replace(".","",1).replace("-","",1).isdigit() else v
        except:
            vv = v
        out[k.strip()] = vv
    return out

def calc_disabled_parking(total_cars: int) -> int:
    if total_cars <= 0: return 0
    if total_cars <= 50: return 2
    if total_cars <= 100: return 3
    extra_hundreds = math.ceil((total_cars - 100)/100)
    return 3 + max(0, extra_hundreds)

def compute_far_counted(mainAG, mainBG, pcAG, pcBG, paAG, paBG, count_parking, count_basement):
    far = 0.0
    far += mainAG + (mainBG if count_basement else 0.0)
    if count_parking:
        far += pcAG + (pcBG if count_basement else 0.0)
    # auto (paAG/paBG) excluded by policy
    return far

# ---------------- Defaults ----------------
DEFAULT = {
    "siteArea": 8000.0, "far": 5.0, "bType": "Hi-Rise", "osr": 30.0, "greenPctOfOSR": 40.0,
    "mainFloorsAG": 20.0, "mainFloorsBG": 0.0, "parkingConFloorsAG": 3.0, "parkingConFloorsBG": 0.0,
    "parkingAutoFloorsAG": 0.0, "parkingAutoFloorsBG": 0.0, "ftf": 3.2, "maxHeight": 120.0,
    "mainFloorPlate": 1500.0, "parkingConPlate": 1200.0, "parkingAutoPlate": 800.0,
    "bayConv": 25.0, "circConvPct": 0.0, "bayAuto": 16.0, "circAutoPct": 0.0,
    "openLotArea": 0.0, "openLotBay": 25.0, "openLotCircPct": 0.0,
    # Program (based on GFA)
    "publicPctOfGFA": 10.0, "nlaPctOfPublic": 40.0, "bohPctOfGFA": 8.0, "servicePctOfGFA": 2.0,
    "countParkingInFAR": True, "countBasementInFAR": False,
    # costs (coarse)
    "costMainPerSqm": 30000.0, "costParkConvPerSqm": 18000.0, "costParkAutoPerSqm": 25000.0, "costGreenPerSqm": 4500.0,
    "costConventionalPerCar": 125000.0, "costAutoPerCar": 432000.0, "costOpenLotPerCar": 60000.0,
    "budget": 500_000_000.0,
}

BUILDING_TYPES = ["Housing", "Hi-Rise", "Low-Rise", "Public Building", "Office Building", "Hotel"]

# ---------------- Sidebar: import/export ----------------
with st.sidebar:
    st.title("⚙️ Feasibility High-rise Condominium")
    st.caption("Minimalist architect theme")
    st.download_button("⬇️ Export CSV", data=create_csv_rows(DEFAULT), file_name="scenario_template.csv", mime="text/csv")
    up = st.file_uploader("⬆️ Import CSV", type=["csv"])
    s = DEFAULT.copy()
    if up is not None:
        try:
            s.update(parse_csv_to_dict(up.read().decode("utf-8")))
            st.success("Imported scenario.")
        except Exception as e:
            st.error(f"Import failed: {e}")

# ---------------- Inputs (compact) ----------------
st.markdown("### Inputs")
wrap1 = st.container()
with wrap1:
    st.markdown('<div class="tight">', unsafe_allow_html=True)
    a1, a2, a3, a4, a5, a6 = st.columns(6)
    s["siteArea"] = a1.number_input("Site Area (m²)", min_value=0.0, value=float(s["siteArea"]), step=100.0)
    s["far"] = a2.number_input("FAR (1–10)", min_value=1.0, max_value=10.0, value=float(s["far"]), step=0.1)
    s["bType"] = a3.selectbox("Building Type", BUILDING_TYPES, index=1 if s.get("bType") not in BUILDING_TYPES else BUILDING_TYPES.index(s["bType"]))
    s["osr"] = a4.number_input("OSR (%)", min_value=0.0, max_value=100.0, value=float(s["osr"]), step=1.0)
    s["greenPctOfOSR"] = a5.number_input("Green (% of OSR)", min_value=0.0, max_value=100.0, value=float(s["greenPctOfOSR"]), step=1.0)
    s["maxHeight"] = a6.number_input("Max Height (m)", min_value=0.0, value=float(s["maxHeight"]), step=1.0)

    b1, b2, b3, b4, b5, b6 = st.columns(6)
    s["mainFloorsAG"] = b1.number_input("Main Floors (AG)", min_value=0.0, value=float(s["mainFloorsAG"]), step=1.0)
    s["mainFloorsBG"] = b2.number_input("Main Floors (BG)", min_value=0.0, value=float(s["mainFloorsBG"]), step=1.0)
    s["parkingConFloorsAG"] = b3.number_input("Park Conv (AG)", min_value=0.0, value=float(s["parkingConFloorsAG"]), step=1.0)
    s["parkingConFloorsBG"] = b4.number_input("Park Conv (BG)", min_value=0.0, value=float(s["parkingConFloorsBG"]), step=1.0)
    s["parkingAutoFloorsAG"] = b5.number_input("Auto Park (AG)", min_value=0.0, value=float(s["parkingAutoFloorsAG"]), step=1.0)
    s["parkingAutoFloorsBG"] = b6.number_input("Auto Park (BG)", min_value=0.0, value=float(s["parkingAutoFloorsBG"]), step=1.0)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    s["mainFloorPlate"]   = c1.number_input("Main Plate (m²)", min_value=0.0, value=float(s["mainFloorPlate"]), step=10.0)
    s["parkingConPlate"]  = c2.number_input("Conv Plate (m²)", min_value=0.0, value=float(s["parkingConPlate"]), step=10.0)
    s["parkingAutoPlate"] = c3.number_input("Auto Plate (m²)", min_value=0.0, value=float(s["parkingAutoPlate"]), step=10.0)
    s["ftf"]              = c4.number_input("Floor-to-Floor (m)", min_value=0.0, value=float(s["ftf"]), step=0.1)
    s["countParkingInFAR"]  = c5.selectbox("Count Conv Parking in FAR?", ["Yes","No"], index=0 if bool(s["countParkingInFAR"]) else 1) == "Yes"
    s["countBasementInFAR"] = c6.selectbox("Count Basement in FAR?", ["No","Yes"], index=1 if bool(s["countBasementInFAR"]) else 0) == "Yes"

    d1, d2, d3, d4, d5, d6 = st.columns(6)
    s["bayConv"] = d1.number_input("Conv Bay (m²/car)", min_value=1.0, value=float(s["bayConv"]), step=1.0)
    s["circConvPct"] = d2.number_input("Conv Circ (%)", min_value=0.0, max_value=100.0, value=float(s["circConvPct"])*100.0, step=1.0)/100.0
    s["bayAuto"] = d3.number_input("Auto Bay (m²/car)", min_value=1.0, value=float(s["bayAuto"]), step=1.0)
    s["circAutoPct"] = d4.number_input("Auto Circ (%)", min_value=0.0, max_value=100.0, value=float(s["circAutoPct"])*100.0, step=1.0)/100.0
    s["openLotArea"] = d5.number_input("Open-lot Area (m²)", min_value=0.0, value=float(s["openLotArea"]), step=50.0)
    s["openLotBay"] = d6.number_input("Open-lot Bay (m²/car)", min_value=1.0, value=float(s["openLotBay"]), step=1.0)
    st.markdown('</div>', unsafe_allow_html=True)

# Program / efficiency (based on GFA)
st.markdown('<div class="tight">', unsafe_allow_html=True)
e1, e2, e3, e4 = st.columns(4)
s["publicPctOfGFA"]  = e1.number_input("Public (% of GFA)",  min_value=0.0, max_value=100.0, value=float(s.get("publicPctOfGFA",10.0)), step=1.0)
s["nlaPctOfPublic"]  = e2.number_input("NLA (% of Public)",  min_value=0.0, max_value=100.0, value=float(s.get("nlaPctOfPublic",40.0)), step=1.0)
s["bohPctOfGFA"]     = e3.number_input("BOH (% of GFA)",     min_value=0.0, max_value=100.0, value=float(s.get("bohPctOfGFA",8.0)), step=1.0)
s["servicePctOfGFA"] = e4.number_input("Service (% of GFA)", min_value=0.0, max_value=100.0, value=float(s.get("servicePctOfGFA",2.0)), step=1.0)
st.markdown('</div>', unsafe_allow_html=True)

# Costs / Budget
st.markdown('<div class="tight">', unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
s["costMainPerSqm"]     = c1.number_input("Architecture (฿/m²)", min_value=0.0, value=float(s["costMainPerSqm"]), step=100.0)
s["costParkConvPerSqm"] = c2.number_input("Park Conv (฿/m²)",    min_value=0.0, value=float(s["costParkConvPerSqm"]), step=100.0)
s["costParkAutoPerSqm"] = c3.number_input("Park Auto (฿/m²)",    min_value=0.0, value=float(s["costParkAutoPerSqm"]), step=100.0)
s["costGreenPerSqm"]    = c4.number_input("Green (฿/m²)",        min_value=0.0, value=float(s["costGreenPerSqm"]), step=50.0)
s["budget"]             = c5.number_input("Budget (฿)",          min_value=0.0, value=float(s["budget"]), step=100000.0)
st.markdown('</div>', unsafe_allow_html=True)

# ---------------- Compute ----------------
eff_con  = s["bayConv"]    * (1 + s["circConvPct"])
eff_auto = s["bayAuto"]    * (1 + s["circAutoPct"])
eff_open = s["openLotBay"] * (1 + s["openLotCircPct"])

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

# Parking supply
convCarsPerFloor = int(math.floor(s["parkingConPlate"]/max(1.0, eff_con))) if s["parkingConPlate"]>0 else 0
autoCarsPerFloor = int(math.floor(s["parkingAutoPlate"]/max(1.0, eff_auto))) if s["parkingAutoPlate"]>0 else 0
totalConvCars = convCarsPerFloor * int(s["parkingConFloorsAG"] + s["parkingConFloorsBG"])
totalAutoCars = autoCarsPerFloor * int(s["parkingAutoFloorsAG"] + s["parkingAutoFloorsBG"])
openLotCars = int(math.floor(s["openLotArea"]/max(1.0, eff_open)))
totalCars = totalConvCars + totalAutoCars + openLotCars
disabledCars = calc_disabled_parking(totalCars)

# GFA policy (auto+openlot excluded)
gfa = mainCFA + parkConCFA
maxGFA = s["siteArea"] * s["far"]
farCounted = compute_far_counted(mainCFA_AG, mainCFA_BG, pcCFA_AG, pcCFA_BG, paCFA_AG, paCFA_BG, s["countParkingInFAR"], s["countBasementInFAR"])
farOk = gfa <= maxGFA

# Program
publicArea  = (s["publicPctOfGFA"]/100.0) * gfa
bohArea     = (s["bohPctOfGFA"]/100.0) * gfa
serviceArea = (s["servicePctOfGFA"]/100.0) * gfa
nsa = max(0.0, gfa - (publicArea + bohArea + serviceArea))
nla = (s["nlaPctOfPublic"]/100.0) * publicArea

# Ratios
deNSA_GFA = (nsa/gfa) if gfa>0 else 0.0
deNSA_CFA = (nsa/totalCFA) if totalCFA>0 else 0.0
deGFA_CFA = (gfa/totalCFA) if totalCFA>0 else 0.0
deNLA_GFA = (nla/gfa) if gfa>0 else 0.0

# ---------------- Top summary row ----------------
st.markdown("### Summary")
sm1, sm2, sm3, sm4, sm5, sm6 = st.columns(6)
sm1.metric("Max GFA (m²)", nf(maxGFA))
sm2.metric("GFA actual (m²)", nf(gfa), "OK" if farOk else "Exceeds")
sm3.metric("Total CFA (m²)", nf(totalCFA), f"GFA/CFA {nf(deGFA_CFA,3)}")
sm4.metric("NSA/GFA", nf(deNSA_GFA,3))
sm5.metric("NSA/CFA", nf(deNSA_CFA,3))
sm6.metric("NLA/GFA", nf(deNLA_GFA,3))

# ---------------- Charts (interactive, essential only) ----------------
st.markdown("### Charts")

# 1) Area composition (CFA vs GFA)
area_df = pd.DataFrame({
    "Area": ["Main CFA", "Conv Park CFA", "Auto Park CFA"],
    "m²": [mainCFA, parkConCFA, parkAutoCFA],
    "In_GFA": [True, True, False]
})
fig_area = px.bar(area_df, x="Area", y="m²", color="In_GFA",
                  color_discrete_map={True:"#3b82f6", False:"#64748b"},
                  title="Area Composition (CFA / GFA inclusion)")
fig_area.update_layout(template="plotly_dark", height=320, margin=dict(l=20,r=20,t=40,b=20), legend_title="")
st.plotly_chart(fig_area, use_container_width=True)

# 2) DE ratios donut
de_df = pd.DataFrame({"Metric":["NSA/GFA","NSA/CFA","GFA/CFA","NLA/GFA"],
                      "Value":[deNSA_GFA,deNSA_CFA,deGFA_CFA,deNLA_GFA]})
fig_de = px.pie(de_df, names="Metric", values="Value", hole=0.55, title="Design Efficiency Ratios")
fig_de.update_traces(textposition='inside', texttemplate="%{label}<br>%{percent:.1%}")
fig_de.update_layout(template="plotly_dark", height=320, margin=dict(l=20,r=20,t=40,b=20), showlegend=False)
st.plotly_chart(fig_de, use_container_width=True)

# 3) Parking mix
pk_df = pd.DataFrame({"Type":["Conv (structured)","Auto (structured)","Open-lot"],
                      "Stalls":[totalConvCars,totalAutoCars,openLotCars]})
fig_pk = px.bar(pk_df, x="Type", y="Stalls", text="Stalls", title="Parking Mix (Supply)")
fig_pk.update_traces(textposition="outside")
fig_pk.update_layout(template="plotly_dark", height=320, margin=dict(l=20,r=20,t=40,b=20))
st.plotly_chart(fig_pk, use_container_width=True)

# ---------------- Detail cards ----------------
colA, colB, colC = st.columns(3)
with colA:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Zoning / GFA")
    st.write(f"- **FAR-counted (legal)**: {nf(farCounted)} m²")
    st.write(f"- **FAR check:** {'✅ OK' if farOk else '❌ Exceeds Max GFA'}")
    st.write(f"- Open Space (OSR): {nf((s['osr']/100)*s['siteArea'])} m²  |  Green: {nf((s['greenPctOfOSR']/100)*(s['osr']/100)*s['siteArea'])} m²")
    st.markdown("</div>", unsafe_allow_html=True)

with colB:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Areas")
    st.write(f"Main CFA (AG/BG): **{nf(mainCFA)}** m²")
    st.write(f"Parking CFA (Conv): **{nf(parkConCFA)}** m²")
    st.write(f"Parking CFA (Auto): **{nf(parkAutoCFA)}** m² _(NOT in GFA)_")
    st.write(f"**GFA actual**: **{nf(gfa)}** m²")
    st.markdown("</div>", unsafe_allow_html=True)

with colC:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Parking")
    st.write(f"Cars/Floor (Conv): **{convCarsPerFloor}**  |  (eff {nf(eff_con)} m²/car)")
    st.write(f"Cars/Floor (Auto): **{autoCarsPerFloor}**  |  (eff {nf(eff_auto)} m²/car)")
    st.write(f"Open-lot cars: **{openLotCars}**  |  (eff {nf(eff_open)} m²/car)")
    st.write(f"Total: **{totalCars}**  |  Disabled: **{calc_disabled_parking(totalCars)}**")
    st.markdown("</div>", unsafe_allow_html=True)
