// App (single file) — minimal monochrome theme, buildable-aware main plate, open-lot parking
import React, { useMemo, useRef } from "react";
import {
  Download, Ruler, Building2, Car, Calculator, Factory,
  TrendingUp, TriangleAlert, Plus, Trash2, FileUp, BarChart3, LayoutGrid
} from "lucide-react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from "recharts";

// =============================================================
// Helpers
// =============================================================
const nf = (n, digits = 2) =>
  isFinite(Number(n)) ? Number(n).toLocaleString(undefined, { maximumFractionDigits: digits }) : "–";
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const currencySymbol = (cur) => (cur === "USD" ? "$" : "฿");

function createCSV(rows) {
  if (!rows || rows.length === 0) return "";
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(","), ...rows.map((r) => headers.map((h) => r[h]).join(","))];
  return lines.join("\n");
}

// Disabled parking rule
function calcDisabledParking(totalCars) {
  if (totalCars <= 0) return 0;
  if (totalCars <= 50) return 2;
  if (totalCars <= 100) return 3;
  const extraHundreds = Math.ceil((totalCars - 100) / 100);
  return 3 + Math.max(0, extraHundreds);
}

// FAR counting helper (no open-lot)
function computeFarCounted(mainAG, mainBG, pcAG, pcBG, paAG, paBG, countParking, countBasement) {
  let farCounted = 0;
  farCounted += mainAG + (countBasement ? mainBG : 0);
  if (countParking) {
    farCounted += pcAG + (countBasement ? pcBG : 0);
    farCounted += paAG + (countBasement ? paBG : 0);
  }
  return farCounted;
}

// =============================================================
// Rules
// =============================================================
const BUILDING_TYPES = ["Housing", "Hi-Rise", "Low-Rise", "Public Building", "Office Building", "Hotel"];
const RULES = {
  base: { farRange: [1, 10] },
  building: {
    Housing: { minOSR: 30, greenPctOfOSR: null },
    "Hi-Rise": { minOSR: 10, greenPctOfOSR: 50 },
    "Low-Rise": { minOSR: 10, greenPctOfOSR: 50 },
    "Public Building": { minOSR: null, greenPctOfOSR: null },
    "Office Building": { minOSR: null, greenPctOfOSR: null },
    Hotel: { minOSR: 10, greenPctOfOSR: 40 },
  },
};
const suggestedOSR = (type) => RULES.building[type]?.minOSR ?? 15;
const suggestedGreenPct = (type) => RULES.building[type]?.greenPctOfOSR ?? 40;

// =============================================================
// Scenario (with site dims & setbacks + main plate mode)
// =============================================================
const DEFAULT_SCENARIO = {
  // Core site & zoning
  name: "Base",
  siteArea: 8000,
  far: 5,
  bType: "Housing",
  osr: 30,
  greenPctOfOSR: 40,

  // Site dims & setbacks (for diagram + buildable calc)
  siteWidth: 80,   // m
  siteDepth: 100,  // m
  setbackFront: 6, // m
  setbackRear: 6,  // m
  setbackSideL: 3, // m
  setbackSideR: 3, // m

  // Geometry
  mainFloorsAG: 20,
  mainFloorsBG: 0,
  parkingConFloorsAG: 3,
  parkingConFloorsBG: 0,
  parkingAutoFloorsAG: 0,
  parkingAutoFloorsBG: 0,
  ftf: 3.2,
  maxHeight: 120,

  // Main plate mode
  mainPlateMode: "abs", // "abs" | "pct"
  mainPlatePct: 80,     // used when mode="pct"

  // Plates (m²)
  mainFloorPlate: 1500,
  parkingConPlate: 1200,
  parkingAutoPlate: 800,

  // Parking efficiency (structured)
  bayConv: 25,
  circConvPct: 0.0,
  bayAuto: 16,
  circAutoPct: 0.0,

  // Open-lot (outside building; not FAR)
  openLotArea: 0,
  openLotBay: 25,
  openLotCircPct: 0.0,

  // Eff ratios
  nlaPctOfCFA: 70,
  nsaPctOfCFA: 80,
  gfaOverCfaPct: 95,

  // FAR flags
  countParkingInFAR: true,
  countBasementInFAR: false,

  // Costs (THB)
  costArchPerSqm: 16000,
  costStructPerSqm: 22000,
  costMEPPerSqm: 20000,
  costGreenPerSqm: 4500,
  costConventionalPerCar: 125000,
  costAutoPerCar: 432000,
  costOpenLotPerCar: 60000,

  customCosts: [],
  budget: 500000000,
};

// =============================================================
// Compute hook
// =============================================================
function useScenarioCompute(state) {
  const effAreaConCar = useMemo(() => state.bayConv * (1 + state.circConvPct), [state.bayConv, state.circConvPct]);
  const effAreaAutoCar = useMemo(() => state.bayAuto * (1 + state.circAutoPct), [state.bayAuto, state.circAutoPct]);
  const effAreaOpenCar = useMemo(() => state.openLotBay * (1 + state.openLotCircPct), [state.openLotBay, state.openLotCircPct]);

  const derived = useMemo(() => {
    const far = clamp(state.far, RULES.base.farRange[0], RULES.base.farRange[1]);
    const maxGFA = state.siteArea * far;

    // Buildable area from dims & setbacks
    const width = Math.max(0, Number(state.siteWidth || 0));
    const depth = Math.max(0, Number(state.siteDepth || 0));
    const sbF = Math.max(0, Number(state.setbackFront || 0));
    const sbR = Math.max(0, Number(state.setbackRear || 0));
    const sbL = Math.max(0, Number(state.setbackSideL || 0));
    const sbRR = Math.max(0, Number(state.setbackSideR || 0));
    const buildableW = Math.max(0, width - (sbL + sbRR));
    const buildableD = Math.max(0, depth - (sbF + sbR));
    const buildableArea = buildableW * buildableD;

    // OSR & Green
    const openSpaceArea = (state.osr / 100) * state.siteArea;
    const greenArea = (state.greenPctOfOSR / 100) * openSpaceArea;

    // Main plate absolute (abs or % of buildable)
    const mainPlateAbs =
      state.mainPlateMode === "pct"
        ? Math.max(0, Math.min(buildableArea, (Number(state.mainPlatePct || 0) / 100) * buildableArea))
        : Math.max(0, Number(state.mainFloorPlate || 0));

    // CFA
    const mainCFA_AG = state.mainFloorsAG * mainPlateAbs;
    const mainCFA_BG = state.mainFloorsBG * mainPlateAbs;
    const parkConCFA_AG = state.parkingConFloorsAG * state.parkingConPlate;
    const parkConCFA_BG = state.parkingConFloorsBG * state.parkingConPlate;
    const parkAutoCFA_AG = state.parkingAutoFloorsAG * state.parkingAutoPlate;
    const parkAutoCFA_BG = state.parkingAutoFloorsBG * state.parkingAutoPlate;

    const mainCFA = mainCFA_AG + mainCFA_BG;
    const parkConCFA = parkConCFA_AG + parkConCFA_BG;
    const parkAutoCFA = parkAutoCFA_AG + parkAutoCFA_BG;
    const totalCFA = mainCFA + parkConCFA + parkAutoCFA;

    // Height (AG only)
    const estHeight = state.ftf * (state.mainFloorsAG + state.parkingConFloorsAG + state.parkingAutoFloorsAG);
    const heightOk = estHeight <= state.maxHeight;

    // Parking counts
    const convCarsPerFloor = Math.floor(state.parkingConPlate / Math.max(1, effAreaConCar));
    const autoCarsPerFloor = Math.floor(state.parkingAutoPlate / Math.max(1, effAreaAutoCar));
    const totalConvCars = convCarsPerFloor * (state.parkingConFloorsAG + state.parkingConFloorsBG);
    const totalAutoCars = autoCarsPerFloor * (state.parkingAutoFloorsAG + state.parkingAutoFloorsBG);
    const openLotCars = Math.floor(state.openLotArea / Math.max(1, effAreaOpenCar));
    const totalCars = totalConvCars + totalAutoCars + openLotCars;
    const disabledCars = calcDisabledParking(totalCars);

    // FAR-counted (no open-lot)
    const farCounted = computeFarCounted(
      mainCFA_AG, mainCFA_BG, parkConCFA_AG, parkConCFA_BG, parkAutoCFA_AG, parkAutoCFA_BG,
      state.countParkingInFAR, state.countBasementInFAR
    );
    const farOk = farCounted <= maxGFA;

    // Efficiency
    const nla = (state.nlaPctOfCFA / 100) * totalCFA;
    const nsa = (state.nsaPctOfCFA / 100) * totalCFA;
    const gfa = (state.gfaOverCfaPct / 100) * totalCFA;

    // Ratios
    const ratioNLA_CFA = totalCFA > 0 ? nla / totalCFA : 0;
    const ratioNSA_GFA = gfa > 0 ? nsa / gfa : 0;
    const ratioNSA_CFA = totalCFA > 0 ? nsa / totalCFA : 0;
    const ratioNLA_GFA = gfa > 0 ? nla / gfa : 0;

    // Costs
    const baseCostPerSqm = state.costArchPerSqm + state.costStructPerSqm + state.costMEPPerSqm;
    const constructionCost = totalCFA * baseCostPerSqm;
    const greenCost = greenArea * state.costGreenPerSqm;
    const parkingCost =
      totalConvCars * state.costConventionalPerCar +
      totalAutoCars * state.costAutoPerCar +
      openLotCars * state.costOpenLotPerCar;

    const customCostTotal = (state.customCosts || []).reduce((sum, i) => {
      if (i.kind === "per_sqm") return sum + i.rate * totalCFA;
      if (i.kind === "per_car_conv") return sum + i.rate * totalConvCars;
      if (i.kind === "per_car_auto") return sum + i.rate * totalAutoCars;
      return sum + i.rate;
    }, 0);

    const capexTotal = constructionCost + greenCost + parkingCost + customCostTotal;
    const budgetOk = state.budget > 0 ? capexTotal <= state.budget : true;

    // Legal
    const rule = RULES.building[state.bType] || {};
    const osrOk = rule.minOSR != null ? state.osr >= rule.minOSR : true;
    const greenRule = rule.greenPctOfOSR;
    const greenPctOk = greenRule != null ? state.greenPctOfOSR >= greenRule : true;

    return {
      // zoning
      maxGFA, openSpaceArea, greenArea,
      // buildable
      buildableW, buildableD, buildableArea, mainPlateAbs,
      // cfa
      mainCFA_AG, mainCFA_BG, mainCFA,
      parkConCFA_AG, parkConCFA_BG, parkConCFA,
      parkAutoCFA_AG, parkAutoCFA_BG, parkAutoCFA,
      totalCFA,
      // checks
      farCounted, farOk, estHeight, heightOk, osrOk, greenPctOk,
      // parking
      convCarsPerFloor, autoCarsPerFloor, totalConvCars, totalAutoCars, openLotCars, totalCars, disabledCars,
      // eff
      nla, nsa, gfa,
      ratioNLA_CFA, ratioNSA_GFA, ratioNSA_CFA, ratioNLA_GFA,
      // costs
      baseCostPerSqm, constructionCost, greenCost, parkingCost, customCostTotal, capexTotal, budgetOk,
      // helpers
      effAreaOpenCar,
    };
  }, [state, effAreaConCar, effAreaAutoCar, effAreaOpenCar]);

  return { effAreaConCar, effAreaAutoCar, effAreaOpenCar, derived };
}

// =============================================================
// Scenario Card (single-scenario UI)
// =============================================================
function ScenarioCard({ scenario, onUpdate, onRemove, currency = "THB" }) {
  const { effAreaConCar, effAreaAutoCar, effAreaOpenCar, derived } = useScenarioCompute(scenario);
  const rule = RULES.building[scenario.bType] || {};
  const farMin = RULES.base.farRange[0];
  const farMax = RULES.base.farRange[1];

  const warnings = [];
  if (!derived.farOk) warnings.push("FAR เกิน Max GFA");
  if (!derived.heightOk) warnings.push("ความสูงเกิน Max Height");
  if (rule.minOSR != null && !derived.osrOk) warnings.push(`OSR ต่ำกว่าขั้นต่ำ ${rule.minOSR}%`);
  if (rule.greenPctOfOSR != null && !derived.greenPctOk) warnings.push(`Green % ต่ำกว่าขั้นต่ำ ${rule.greenPctOfOSR}% ของ OSR`);
  if (!derived.budgetOk) warnings.push("CAPEX เกินงบประมาณ");

  const curSymbol = currencySymbol(currency);
  const sqmLabel = `${curSymbol}/m²`;

  const capexData = useMemo(
    () => [
      { name: "Construction", value: Math.max(0, derived.constructionCost) },
      { name: "Green",        value: Math.max(0, derived.greenCost) },
      { name: "Parking",      value: Math.max(0, derived.parkingCost) },
      { name: "Custom",       value: Math.max(0, derived.customCostTotal) },
    ],
    [derived.constructionCost, derived.greenCost, derived.parkingCost, derived.customCostTotal]
  );

  // Monochrome palette
  const CAPEX_COLOR_BY_NAME = {
    Construction: "#111827", // black
    Green:        "#6b7280", // gray-500/600
    Parking:      "#9ca3af", // gray-400
    Custom:       "#d1d5db", // gray-300
  };
  const fileRef = useRef(null);

  const handleExportCSV = () => {
    const s = scenario;
    const rows = Object.entries(s)
      .filter(([k]) => k !== "id")
      .map(([Field, Value]) => ({
        Field,
        Value: Value && typeof Value === "object" ? JSON.stringify(Value) : Value,
      }));
    const csv = createCSV(rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `${(s.name || "scenario").replace(/\s+/g, "_")}.csv`);
    document.body.appendChild(link);
    link.click();
    link.parentNode?.removeChild(link);
  };

  const handleImportCSV = (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const text = String(reader.result || "");
        const lines = text.split(/\r?\n/).filter(Boolean);
        const entries = lines.slice(1).map((line) => {
          const idx = line.indexOf(",");
          if (idx < 0) return null;
          const k = line.slice(0, idx).trim();
          const v = line.slice(idx + 1).trim();
          let parsed = v;
          if (/^\s*[\{\[]/.test(v)) {
            try { parsed = JSON.parse(v); } catch {}
          } else {
            const num = Number(v);
            if (isFinite(num) && v.match(/^[-+]?\d+(\.\d+)?$/)) parsed = num;
          }
          return [k, parsed];
        }).filter(Boolean);
        const patch = Object.fromEntries(entries);
        onUpdate(scenario.id, patch);
      } catch (e) {
        alert("Import failed: " + e);
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="p-4 rounded-2xl bg-[#f5f5f5]">
      <div className="p-4 rounded-2xl bg-white shadow border space-y-4">
        <div className="flex items-center gap-3">
          <h2 className="font-semibold">Scenario: {scenario.name}</h2>
          <button onClick={() => onRemove?.(scenario.id)} className="ml-auto text-neutral-500 hover:text-red-600">
            <Trash2 className="w-5 h-5" />
          </button>
        </div>

        {/* Inputs */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Site & Zoning (with dims + setbacks under Site) */}
          <div className="p-3 rounded-xl border">
            <h3 className="font-medium text-sm flex items-center gap-2"><Ruler className="w-4 h-4" /> Site & Zoning</h3>
            <div className="grid grid-cols-2 gap-3 mt-2 text-sm">
              <label>
                Site Area (m²)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.siteArea}
                  onChange={(e) => onUpdate(scenario.id, { siteArea: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label>
                FAR (1–10)
                <input type="number" min={farMin} max={farMax} step={0.1} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.far}
                  onChange={(e) => onUpdate(scenario.id, { far: clamp(Number(e.target.value), farMin, farMax) })}/>
              </label>

              {/* Site dims + setbacks */}
              <div className="col-span-2 grid grid-cols-6 gap-3">
                <label className="col-span-2">
                  Site Width (m)
                  <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                    value={scenario.siteWidth}
                    onChange={(e)=>onUpdate(scenario.id,{siteWidth: Math.max(0, Number(e.target.value))})}/>
                </label>
                <label className="col-span-2">
                  Site Depth (m)
                  <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                    value={scenario.siteDepth}
                    onChange={(e)=>onUpdate(scenario.id,{siteDepth: Math.max(0, Number(e.target.value))})}/>
                </label>
                <label>
                  Setback Front (m)
                  <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                    value={scenario.setbackFront}
                    onChange={(e)=>onUpdate(scenario.id,{setbackFront: Math.max(0, Number(e.target.value))})}/>
                </label>
                <label>
                  Setback Rear (m)
                  <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                    value={scenario.setbackRear}
                    onChange={(e)=>onUpdate(scenario.id,{setbackRear: Math.max(0, Number(e.target.value))})}/>
                </label>
                <label>
                  Setback Side (L) (m)
                  <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                    value={scenario.setbackSideL}
                    onChange={(e)=>onUpdate(scenario.id,{setbackSideL: Math.max(0, Number(e.target.value))})}/>
                </label>
                <label>
                  Setback Side (R) (m)
                  <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                    value={scenario.setbackSideR}
                    onChange={(e)=>onUpdate(scenario.id,{setbackSideR: Math.max(0, Number(e.target.value))})}/>
                </label>
              </div>

              <label>
                Building Type
                <select className="mt-1 w-full border rounded-xl px-3 py-2" value={scenario.bType}
                  onChange={(e)=>onUpdate(scenario.id,{
                    bType: e.target.value,
                    osr: suggestedOSR(e.target.value),
                    greenPctOfOSR: suggestedGreenPct(e.target.value),
                  })}>
                  {BUILDING_TYPES.map((t)=> <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <label>
                OSR (%)
                <input type="number" min={0} max={100} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.osr}
                  onChange={(e)=>onUpdate(scenario.id,{ osr: clamp(Number(e.target.value), 0, 100) })}/>
                {RULES.building[scenario.bType]?.minOSR != null &&
                  <div className="text-[11px] mt-1 text-neutral-500">ขั้นต่ำ {RULES.building[scenario.bType].minOSR}%</div>}
              </label>
              <label>
                Green (% of OSR)
                <input type="number" min={0} max={100} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.greenPctOfOSR}
                  onChange={(e)=>onUpdate(scenario.id,{ greenPctOfOSR: clamp(Number(e.target.value), 0, 100) })}/>
                {RULES.building[scenario.bType]?.greenPctOfOSR != null &&
                  <div className="text-[11px] mt-1 text-neutral-500">ขั้นต่ำ {RULES.building[scenario.bType].greenPctOfOSR}%</div>}
              </label>
            </div>
          </div>

          {/* Geometry & Height */}
          <div className="p-3 rounded-xl border">
            <h3 className="font-medium text-sm flex items-center gap-2"><Building2 className="w-4 h-4" /> Geometry & Height</h3>
            <div className="grid grid-cols-3 gap-3 mt-2 text-sm">
              <label className="col-span-1">
                Main Floors (AG)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.mainFloorsAG}
                  onChange={(e)=>onUpdate(scenario.id,{ mainFloorsAG: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label className="col-span-1">
                Main Floors (BG)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.mainFloorsBG}
                  onChange={(e)=>onUpdate(scenario.id,{ mainFloorsBG: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label className="col-span-1">
                F2F (m)
                <input type="number" min={0} step={0.1} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.ftf}
                  onChange={(e)=>onUpdate(scenario.id,{ ftf: Math.max(0, Number(e.target.value)) })}/>
              </label>

              <label className="col-span-1">
                Park Conv (AG)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.parkingConFloorsAG}
                  onChange={(e)=>onUpdate(scenario.id,{ parkingConFloorsAG: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label className="col-span-1">
                Park Conv (BG)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.parkingConFloorsBG}
                  onChange={(e)=>onUpdate(scenario.id,{ parkingConFloorsBG: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label className="col-span-1">
                Max Height (m)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.maxHeight}
                  onChange={(e)=>onUpdate(scenario.id,{ maxHeight: Math.max(0, Number(e.target.value)) })}/>
              </label>

              <label className="col-span-1">
                Auto Park (AG)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.parkingAutoFloorsAG}
                  onChange={(e)=>onUpdate(scenario.id,{ parkingAutoFloorsAG: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label className="col-span-1">
                Auto Park (BG)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.parkingAutoFloorsBG}
                  onChange={(e)=>onUpdate(scenario.id,{ parkingAutoFloorsBG: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <div className="col-span-1" />

              {/* Main plate mode */}
              <div className="col-span-1">
                <label>Main Plate</label>
                <div className="grid grid-cols-2 gap-2 mt-1">
                  <select className="border rounded-xl px-3 py-2"
                    value={scenario.mainPlateMode}
                    onChange={(e)=>onUpdate(scenario.id,{ mainPlateMode: e.target.value })}>
                    <option value="abs">Abs (m²)</option>
                    <option value="pct">% of buildable</option>
                  </select>
                  {scenario.mainPlateMode === "abs" ? (
                    <input type="number" min={0} className="w-full border rounded-xl px-3 py-2"
                      value={scenario.mainFloorPlate}
                      onChange={(e)=>onUpdate(scenario.id,{ mainFloorPlate: Math.max(0, Number(e.target.value)) })}/>
                  ) : (
                    <div className="flex items-center gap-2">
                      <input type="number" min={0} max={100} className="w-full border rounded-xl px-3 py-2"
                        value={scenario.mainPlatePct}
                        onChange={(e)=>onUpdate(scenario.id,{ mainPlatePct: clamp(Number(e.target.value), 0, 100) })}/>
                      <span className="text-sm text-neutral-500">% buildable</span>
                    </div>
                  )}
                </div>
                {scenario.mainPlateMode === "pct" && (
                  <div className="text-[11px] text-neutral-500 mt-1">
                    Using {scenario.mainPlatePct}% × Buildable ≈ <b>{nf(derived.mainPlateAbs)}</b> m²
                  </div>
                )}
              </div>

              <label className="col-span-1">
                Park Plate (Conv) (m²)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.parkingConPlate}
                  onChange={(e)=>onUpdate(scenario.id,{ parkingConPlate: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label className="col-span-1">
                Park Plate (Auto) (m²)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.parkingAutoPlate}
                  onChange={(e)=>onUpdate(scenario.id,{ parkingAutoPlate: Math.max(0, Number(e.target.value)) })}/>
              </label>

              <label className="col-span-1">
                Count Parking in FAR?
                <select className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={String(scenario.countParkingInFAR)}
                  onChange={(e)=>onUpdate(scenario.id,{ countParkingInFAR: e.target.value === "true" })}>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </label>
              <label className="col-span-1">
                Count Basement in FAR?
                <select className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={String(scenario.countBasementInFAR)}
                  onChange={(e)=>onUpdate(scenario.id,{ countBasementInFAR: e.target.value === "true" })}>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </label>
              <div className="col-span-1" />
            </div>
          </div>

          {/* Parking & Efficiency */}
          <div className="p-3 rounded-xl border">
            <h3 className="font-medium text-sm flex items-center gap-2"><Car className="w-4 h-4" /> Parking & Efficiency</h3>
            <div className="grid grid-cols-3 gap-3 mt-2 text-sm">
              <label>
                Conv Bay (m²) — net
                <input type="number" min={1} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.bayConv}
                  onChange={(e)=>onUpdate(scenario.id,{ bayConv: Math.max(1, Number(e.target.value)) })}/>
              </label>
              <label>
                Conv Circ (%)
                <input type="number" min={0} max={100} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.circConvPct * 100}
                  onChange={(e)=>onUpdate(scenario.id,{ circConvPct: clamp(Number(e.target.value), 0, 100) / 100 })}/>
              </label>
              <div className="text-xs text-neutral-600 flex items-end">eff = {nf(scenario.bayConv*(1+scenario.circConvPct))} m²/คัน</div>

              <label>
                Auto Bay (m²) — net
                <input type="number" min={1} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.bayAuto}
                  onChange={(e)=>onUpdate(scenario.id,{ bayAuto: Math.max(1, Number(e.target.value)) })}/>
              </label>
              <label>
                Auto Circ (%)
                <input type="number" min={0} max={100} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.circAutoPct * 100}
                  onChange={(e)=>onUpdate(scenario.id,{ circAutoPct: clamp(Number(e.target.value), 0, 100) / 100 })}/>
              </label>
              <div className="text-xs text-neutral-600 flex items-end">eff = {nf(scenario.bayAuto*(1+scenario.circAutoPct))} m²/คัน</div>

              <label className="col-span-1">
                Open-lot Area (m²)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.openLotArea}
                  onChange={(e)=>onUpdate(scenario.id,{ openLotArea: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label className="col-span-1">
                Open-lot Bay (m²/คัน)
                <input type="number" min={1} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.openLotBay}
                  onChange={(e)=>onUpdate(scenario.id,{ openLotBay: Math.max(1, Number(e.target.value)) })}/>
              </label>
              <label className="col-span-1">
                Open-lot Circ (%)
                <input type="number" min={0} max={100} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.openLotCircPct * 100}
                  onChange={(e)=>onUpdate(scenario.id,{ openLotCircPct: clamp(Number(e.target.value), 0, 100) / 100 })}/>
              </label>
              <div className="col-span-3 text-xs text-neutral-600">eff (open-lot) = {nf(derived.effAreaOpenCar)} m²/คัน</div>
            </div>
          </div>

          {/* Costs & Budget (with Additional cost inside) */}
          <div className="p-3 rounded-xl border">
            <h3 className="font-medium text-sm flex items-center gap-2"><Factory className="w-4 h-4" /> Costs & Budget</h3>
            <div className="grid grid-cols-2 gap-3 mt-2 text-sm">
              <label>Architecture {sqmLabel}
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.costArchPerSqm}
                  onChange={(e)=>onUpdate(scenario.id,{ costArchPerSqm: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label>Structure {sqmLabel}
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.costStructPerSqm}
                  onChange={(e)=>onUpdate(scenario.id,{ costStructPerSqm: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label>MEP {sqmLabel}
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.costMEPPerSqm}
                  onChange={(e)=>onUpdate(scenario.id,{ costMEPPerSqm: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label>Green {sqmLabel}
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.costGreenPerSqm}
                  onChange={(e)=>onUpdate(scenario.id,{ costGreenPerSqm: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label>Parking (Conv) ({curSymbol}/car)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.costConventionalPerCar}
                  onChange={(e)=>onUpdate(scenario.id,{ costConventionalPerCar: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label>Parking (Auto) ({curSymbol}/car)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.costAutoPerCar}
                  onChange={(e)=>onUpdate(scenario.id,{ costAutoPerCar: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label>Parking (Open-lot) ({curSymbol}/car)
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.costOpenLotPerCar}
                  onChange={(e)=>onUpdate(scenario.id,{ costOpenLotPerCar: Math.max(0, Number(e.target.value)) })}/>
              </label>
              <label className="col-span-2">Budget ({curSymbol})
                <input type="number" min={0} className="mt-1 w-full border rounded-xl px-3 py-2"
                  value={scenario.budget}
                  onChange={(e)=>onUpdate(scenario.id,{ budget: Math.max(0, Number(e.target.value)) })}/>
              </label>
            </div>

            {/* Additional Cost Items */}
            <div className="mt-3">
              <div className="flex items-center justify-between">
                <h4 className="font-medium text-sm">Additional Cost Items</h4>
                <button
                  onClick={() => onUpdate(scenario.id, {
                    customCosts: [...(scenario.customCosts || []), { id: Date.now(), name: "FF&E", kind: "lump_sum", rate: 0 }]
                  })}
                  className="text-sm px-2 py-1 border rounded-xl flex items-center gap-1 hover:bg-neutral-100">
                  <Plus className="w-4 h-4" />Add
                </button>
              </div>
              {(scenario.customCosts || []).length === 0 &&
                <div className="text-xs text-neutral-500 mt-1">(ว่าง) — เพิ่มหมวด FF&E/Facade Premium/Consultant/Permit ฯลฯ</div>}
              {(scenario.customCosts || []).map((i) => (
                <div key={i.id} className="grid grid-cols-12 gap-2 items-center mt-2">
                  <input className="col-span-5 border rounded-xl px-3 py-2 text-sm" value={i.name}
                    onChange={(e)=>onUpdate(scenario.id,{
                      customCosts: (scenario.customCosts || []).map((x)=>x.id===i.id?{...x, name:e.target.value}:x)
                    })}/>
                  <select className="col-span-3 border rounded-xl px-3 py-2 text-sm" value={i.kind}
                    onChange={(e)=>onUpdate(scenario.id,{
                      customCosts: (scenario.customCosts || []).map((x)=>x.id===i.id?{...x, kind:e.target.value}:x)
                    })}>
                    <option value="per_sqm">per m²</option>
                    <option value="per_car_conv">per car (Conv)</option>
                    <option value="per_car_auto">per car (Auto)</option>
                    <option value="lump_sum">lump sum</option>
                  </select>
                  <input type="number" className="col-span-3 border rounded-xl px-3 py-2 text-sm" value={i.rate}
                    onChange={(e)=>onUpdate(scenario.id,{
                      customCosts: (scenario.customCosts || []).map((x)=>x.id===i.id?{...x, rate:Number(e.target.value)}:x)
                    })}/>
                  <button onClick={()=>onUpdate(scenario.id,{ customCosts: (scenario.customCosts || []).filter((x)=>x.id!==i.id) })}
                    className="col-span-1 justify-self-end text-neutral-500 hover:text-red-600">
                    <Trash2 className="w-5 h-5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Summary & Viz (neutral theme) */}
        <div className="grid md:grid-cols-3 gap-4">
          <div className="p-4 rounded-2xl bg-white border border-neutral-200 shadow-sm">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-neutral-800">
              <TrendingUp className="w-4 h-4" /> Zoning Summary
            </h3>
            <div className="mt-2 text-sm space-y-1">
              <div>Max GFA: <b>{nf(derived.maxGFA)}</b> m²</div>
              <div>FAR-counted Area: <b>{nf(derived.farCounted)}</b> m²</div>
              <div>Open Space (OSR): <b>{nf(derived.openSpaceArea)}</b> m² ({scenario.osr}%)</div>
              <div>Green Area: <b>{nf(derived.greenArea)}</b> m² ({scenario.greenPctOfOSR}% of OSR)</div>
              <div className={`text-xs ${derived.farOk ? "text-emerald-700" : "text-red-600"} flex items-center gap-1`}>
                {!derived.farOk && <TriangleAlert className="w-3 h-3" />} FAR check: {derived.farOk ? "OK" : "Exceeds Max GFA"}
              </div>
            </div>
          </div>
          <div className="p-4 rounded-2xl bg-white border border-neutral-200 shadow-sm">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-neutral-800">
              <Calculator className="w-4 h-4" /> Areas
            </h3>
            <div className="mt-2 text-sm space-y-1">
              <div>Main CFA (AG): <b>{nf(derived.mainCFA_AG)}</b> m²</div>
              <div>Main CFA (BG): <b>{nf(derived.mainCFA_BG)}</b> m²</div>
              <div>Parking CFA (Conv): <b>{nf(derived.parkConCFA)}</b> m²</div>
              <div>Parking CFA (Auto): <b>{nf(derived.parkAutoCFA)}</b> m²</div>
              <div>Total CFA: <b>{nf(derived.totalCFA)}</b> m²</div>
            </div>
          </div>
          <div className="p-4 rounded-2xl bg-white border border-neutral-200 shadow-sm">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-neutral-800">
              <Building2 className="w-4 h-4" /> Height
            </h3>
            <div className="mt-2 text-sm space-y-1">
              <div>Estimated Height (AG only): <b>{nf(derived.estHeight)}</b> m</div>
              <div>Max Height: <b>{nf(scenario.maxHeight)}</b> m</div>
              <div className={`text-xs ${derived.heightOk ? "text-emerald-700" : "text-red-600"} flex items-center gap-1`}>
                {!derived.heightOk && <TriangleAlert className="w-3 h-3" />} Height check: {derived.heightOk ? "OK" : "Exceeds Limit"}
              </div>
            </div>
          </div>
        </div>

        <div className="grid md:grid-cols-3 gap-4">
          <div className="p-4 rounded-2xl bg-white border border-neutral-200 shadow-sm">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-neutral-800">
              <Calculator className="w-4 h-4" /> Efficiency Output
            </h3>
            <div className="mt-2 text-sm space-y-1">
              <div>NLA: <b>{nf(derived.nla)}</b> m² <span className="text-xs text-neutral-500">({nf(derived.nla/derived.totalCFA,3)} × CFA)</span></div>
              <div>NSA: <b>{nf(derived.nsa)}</b> m² <span className="text-xs text-neutral-500">({nf(derived.nsa/derived.totalCFA,3)} × CFA)</span></div>
              <div>GFA: <b>{nf(derived.gfa)}</b> m² <span className="text-xs text-neutral-500">({nf(derived.gfa/derived.totalCFA,3)} × CFA)</span></div>
              <div className="border-t pt-2 text-neutral-700 space-y-0.5">
                <div>NLA / CFA: <b>{nf(derived.ratioNLA_CFA*100,1)}%</b></div>
                <div>NSA / GFA: <b>{nf(derived.ratioNSA_GFA*100,1)}%</b></div>
                <div>NSA / CFA: <b>{nf(derived.ratioNSA_CFA*100,1)}%</b></div>
                <div>NLA / GFA: <b>{nf(derived.ratioNLA_GFA*100,1)}%</b></div>
              </div>
            </div>
          </div>
          <div className="p-4 rounded-2xl bg-white border border-neutral-200 shadow-sm">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-neutral-800">
              <Car className="w-4 h-4" /> Parking
            </h3>
            <div className="mt-2 text-sm space-y-1">
              <div>Cars/Floor (Conv): <b>{derived.convCarsPerFloor}</b> <span className="text-xs text-neutral-500">(eff {nf(effAreaConCar)} m²/car)</span></div>
              <div>Cars/Floor (Auto): <b>{derived.autoCarsPerFloor}</b> <span className="text-xs text-neutral-500">(eff {nf(effAreaAutoCar)} m²/car)</span></div>
              <div>Open-lot Cars: <b>{derived.openLotCars}</b> <span className="text-xs text-neutral-500">(eff {nf(derived.effAreaOpenCar)} m²/car)</span></div>
              <div>Total Cars (Conv): <b>{derived.totalConvCars}</b></div>
              <div>Total Cars (Auto): <b>{derived.totalAutoCars}</b></div>
              <div>Total Cars: <b>{derived.totalCars}</b></div>
              <div>Disabled Spaces (calc): <b>{derived.disabledCars}</b></div>
            </div>
          </div>
          <div className="p-4 rounded-2xl bg-white border border-neutral-200 shadow-sm">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-neutral-800">
              <Factory className="w-4 h-4" /> CAPEX
            </h3>
            <div className="mt-2 text-sm space-y-1">
              <div>Base Build Cost: <b>{curSymbol}{nf(derived.constructionCost)}</b></div>
              <div>Green Cost: <b>{curSymbol}{nf(derived.greenCost)}</b></div>
              <div>Parking Cost: <b>{curSymbol}{nf(derived.parkingCost)}</b> <span className="text-xs text-neutral-500">(includes open-lot)</span></div>
              {(scenario.customCosts || []).length > 0 && <div>Additional (custom): <b>{curSymbol}{nf(derived.customCostTotal)}</b></div>}
              <div className="border-t pt-2">Total CAPEX: <b>{curSymbol}{nf(derived.capexTotal)}</b></div>
              <div className={`text-xs ${derived.budgetOk ? "text-emerald-700" : "text-red-600"} flex items-center gap-1`}>
                {!derived.budgetOk && <TriangleAlert className="w-3 h-3" />} Budget check: {derived.budgetOk ? "OK" : "Over Budget"} (Budget {curSymbol}{nf(scenario.budget)})
              </div>
            </div>
          </div>
        </div>

        {/* Viz row */}
        <div className="grid md:grid-cols-3 gap-4">
          <div className="p-3 rounded-2xl bg-white border shadow flex flex-col">
            <div className="text-sm font-semibold flex items-center gap-2 mb-2"><LayoutGrid className="w-4 h-4" /> Site Visualization</div>
            <SiteViz
              siteArea={scenario.siteArea}
              osr={scenario.osr}
              greenArea={derived.greenArea}
              siteWidth={scenario.siteWidth}
              siteDepth={scenario.siteDepth}
              setbacks={{ front: scenario.setbackFront, rear: scenario.setbackRear, sideL: scenario.setbackSideL, sideR: scenario.setbackSideR }}
              className="w-full h-auto"
            />
            <div className="text-xs text-neutral-600 mt-2">Site / Buildable / Open Space / Green (schematic)</div>
          </div>
          <div className="p-3 rounded-2xl bg-white border shadow col-span-2">
            <div className="text-sm font-semibold flex items-center gap-2 mb-2"><BarChart3 className="w-4 h-4" /> CAPEX Breakdown</div>
            <div style={{ width: "100%", height: 240 }}>
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={capexData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80}>
                    {capexData.map((entry, idx) => (
                      <Cell key={`cell-${idx}`} fill={CAPEX_COLOR_BY_NAME[entry.name] || "#9ca3af"} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v) => nf(v)} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Legal & Warning banner */}
        {warnings.length > 0 && (
          <div className="p-4 rounded-2xl bg-amber-50 border-amber-200 border text-amber-900 flex gap-3 items-start">
            <TriangleAlert className="w-4 h-4 mt-0.5" />
            <div className="text-sm"><b>Design check:</b> {warnings.join(" · ")}</div>
          </div>
        )}

        {/* Export/Import */}
        <div className="flex gap-2">
          <button onClick={handleExportCSV} className="px-3 py-2 rounded-xl border shadow-sm hover:bg-neutral-100 flex items-center gap-2">
            <Download className="w-4 h-4" /> Export CSV
          </button>
          <label className="px-3 py-2 rounded-xl border shadow-sm hover:bg-neutral-100 flex items-center gap-2 cursor-pointer">
            <FileUp className="w-4 h-4" /> Import CSV
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                handleImportCSV(f);
                e.target.value = "";
              }}
            />
          </label>
        </div>

        {/* Tests */}
        <TestsPanel scenario={scenario} derived={derived} />
      </div>
    </div>
  );
}

// Small SVG site visualizer (with true dims & buildable, plus schematic OSR/Green)
function SiteViz({ siteArea, osr, greenArea, className, siteWidth, siteDepth, setbacks }) {
  const W = 460, H = 300, P = 16;
  const cx = W / 2, cy = H / 2;
  const hasDims = Number(siteWidth) > 0 && Number(siteDepth) > 0;

  let elements = null;
  if (hasDims) {
    const scale = Math.min((W - 2 * P) / siteWidth, (H - 2 * P) / siteDepth);
    const sw = siteWidth * scale, sd = siteDepth * scale;
    const x0 = cx - sw / 2, y0 = cy - sd / 2;

    const sb = {
      front: Math.max(0, setbacks?.front || 0) * scale,
      rear: Math.max(0, setbacks?.rear || 0) * scale,
      l: Math.max(0, setbacks?.sideL || 0) * scale,
      r: Math.max(0, setbacks?.sideR || 0) * scale,
    };
    const bx0 = x0 + sb.l, bx1 = x0 + sw - sb.r;
    const by0 = y0 + sb.front, by1 = y0 + sd - sb.rear;

    // OSR & Green schematic rects centered
    const osrRatio = clamp(osr / 100, 0, 1);
    const greenRatio = clamp(greenArea / Math.max(1e-9, siteArea * osrRatio), 0, 1);
    const osrW = sw * Math.sqrt(osrRatio), osrH = sd * Math.sqrt(osrRatio);
    const greenW = osrW * Math.sqrt(greenRatio), greenH = osrH * Math.sqrt(greenRatio);

    elements = (
      <>
        {/* Site */}
        <rect x={x0} y={y0} width={sw} height={sd} fill="#fff" stroke="#D1D5DB" strokeWidth={2} />
        {/* Buildable */}
        <rect x={bx0} y={by0} width={Math.max(0, bx1 - bx0)} height={Math.max(0, by1 - by0)} fill="#F3F4F6" stroke="#9CA3AF" />
        {/* OSR & Green schematic */}
        <rect x={cx - osrW / 2} y={cy - osrH / 2} width={osrW} height={osrH} fill="#E5FBEA" stroke="#86EFAC" />
        <rect x={cx - greenW / 2} y={cy - greenH / 2} width={greenW} height={greenH} fill="#86EFAC" stroke="#059669" />
        <g fontSize={10} fill="#374151">
          <text x={x0 + 6} y={y0 + 14}>Site</text>
          <text x={bx0 + 6} y={by0 + 14}>Buildable</text>
          <text x={cx - osrW / 2 + 6} y={cy - osrH / 2 + 14}>Open Space</text>
          <text x={cx - greenW / 2 + 6} y={cy - greenH / 2 + 14}>Green</text>
        </g>
      </>
    );
  } else {
    // Fallback proportional
    const siteW = W - 2 * P, siteH = H - 2 * P;
    const osrRatio = clamp(osr / 100, 0, 1);
    const greenRatio = clamp(greenArea / Math.max(1e-9, siteArea * osrRatio), 0, 1);
    const osrW = siteW * Math.sqrt(osrRatio), osrH = siteH * Math.sqrt(osrRatio);
    const greenW = osrW * Math.sqrt(greenRatio), greenH = osrH * Math.sqrt(greenRatio);
    elements = (
      <>
        <rect x={P} y={P} width={siteW} height={siteH} fill="#fff" stroke="#CBD5E1" strokeWidth={2} />
        <rect x={cx - osrW / 2} y={cy - osrH / 2} width={osrW} height={osrH} fill="#E5FBEA" stroke="#86EFAC" />
        <rect x={cx - greenW / 2} y={cy - greenH / 2} width={greenW} height={greenH} fill="#86EFAC" stroke="#059669" />
        <g fontSize={10} fill="#334155">
          <text x={P + 6} y={P + 14}>Site</text>
          <text x={cx - osrW / 2 + 6} y={cy - osrH / 2 + 14}>Open Space</text>
          <text x={cx - greenW / 2 + 6} y={cy - greenH / 2 + 14}>Green</text>
        </g>
      </>
    );
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={className}>
      <rect x={0} y={0} width={W} height={H} rx={12} fill="#F8FAFC" />
      {elements}
    </svg>
  );
}

// =============================
// Test panel (ALWAYS add tests)
// =============================
function TestsPanel({ scenario, derived }) {
  const tests = useMemo(() => {
    // recompute expected with same rules
    const width  = Math.max(0, Number(scenario.siteWidth || 0));
    const depth  = Math.max(0, Number(scenario.siteDepth || 0));
    const sbF = Math.max(0, Number(scenario.setbackFront || 0));
    const sbR = Math.max(0, Number(scenario.setbackRear || 0));
    const sbL = Math.max(0, Number(scenario.setbackSideL || 0));
    const sbRR= Math.max(0, Number(scenario.setbackSideR || 0));
    const buildableArea = Math.max(0, width - (sbL + sbRR)) * Math.max(0, depth - (sbF + sbR));

    const mainPlateAbs =
      scenario.mainPlateMode === "pct"
        ? Math.max(0, Math.min(buildableArea, (Number(scenario.mainPlatePct || 0)/100) * buildableArea))
        : Math.max(0, Number(scenario.mainFloorPlate || 0));

    const mAG = scenario.mainFloorsAG * mainPlateAbs;
    const mBG = scenario.mainFloorsBG * mainPlateAbs;
    const pcAG = scenario.parkingConFloorsAG * scenario.parkingConPlate;
    const pcBG = scenario.parkingConFloorsBG * scenario.parkingConPlate;
    const paAG = scenario.parkingAutoFloorsAG * scenario.parkingAutoPlate;
    const paBG = scenario.parkingAutoFloorsBG * scenario.parkingAutoPlate;

    const farExpected = computeFarCounted(
      mAG, mBG, pcAG, pcBG, paAG, paBG,
      scenario.countParkingInFAR, scenario.countBasementInFAR
    );

    const openLotExpectedCars = Math.floor(
      scenario.openLotArea / Math.max(1, scenario.openLotBay * (1 + scenario.openLotCircPct))
    );

    return [
      // disabled parking rule
      { name: "calcDisabledParking(0)",   actual: calcDisabledParking(0),   expected: 0 },
      { name: "calcDisabledParking(50)",  actual: calcDisabledParking(50),  expected: 2 },
      { name: "calcDisabledParking(51)",  actual: calcDisabledParking(51),  expected: 3 },
      { name: "calcDisabledParking(100)", actual: calcDisabledParking(100), expected: 3 },
      { name: "calcDisabledParking(101)", actual: calcDisabledParking(101), expected: 4 },
      { name: "calcDisabledParking(250)", actual: calcDisabledParking(250), expected: 5 },

      // FAR counted
      { name: "computeFarCounted(default flags)", actual: derived.farCounted, expected: farExpected },
      { name: "computeFarCounted(no parking, no basement)", actual: computeFarCounted(100,20,30,40,50,60,false,false), expected: 100 },
      { name: "computeFarCounted(parking+basement)",        actual: computeFarCounted(100,20,30,40,50,60,true,true),   expected: 300 },

      // open-lot behavior
      { name: "openLot cars calc", actual: derived.openLotCars, expected: openLotExpectedCars },

      // main plate % clamp
      { name: "mainPlate pct clamp ≤ buildable", actual: scenario.mainPlateMode==="pct" ? (derived.mainPlateAbs <= buildableArea) : true, expected: true },
    ];
  }, [scenario, derived]);

  return (
    <div className="mt-4 p-3 rounded-xl border text-sm">
      <div className="font-semibold mb-2">Tests</div>
      <ul className="space-y-1">
        {tests.map((t, i) => (
          <li key={i} className={t.actual === t.expected ? "text-emerald-700" : "text-red-600"}>
            {t.actual === t.expected ? "✅" : "❌"} {t.name} — actual: <b>{String(t.actual)}</b>, expected: <b>{String(t.expected)}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Optional default export
export { ScenarioCard, SiteViz, computeFarCounted, calcDisabledParking };
export default ScenarioCard;
