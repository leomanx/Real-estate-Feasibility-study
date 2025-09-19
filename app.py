import React, { useMemo, useRef, useState } from "react";
import {
  Download,
  Ruler,
  Building2,
  Car,
  Calculator,
  Factory,
  TrendingUp,
  TriangleAlert,
  Plus,
  Trash2,
  FileUp,
  BarChart3,
  LayoutGrid,
} from "lucide-react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from "recharts";

// =============================================================
// Helpers
// =============================================================
const nf = (n, digits = 2) =>
  isFinite(Number(n)) ? Number(n).toLocaleString(undefined, { maximumFractionDigits: digits }) : "–";
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function createCSV(rows) {
  if (!rows || rows.length === 0) return "";
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(","), ...rows.map((r) => headers.map((h) => r[h]).join(","))];
  return lines.join("\n");
}

// Disabled parking rule used in sheet: 0 → 0; ≤50 → 2; 51–100 → 3; >100 → +1 per 100 cars thereafter
function calcDisabledParking(totalCars) {
  if (totalCars <= 0) return 0;
  if (totalCars <= 50) return 2;
  if (totalCars <= 100) return 3;
  const extraHundreds = Math.ceil((totalCars - 100) / 100);
  return 3 + Math.max(0, extraHundreds);
}

// FAR counting helper
function computeFarCounted(mainAG, mainBG, pcAG, pcBG, paAG, paBG, countParking, countBasement) {
  let farCounted = 0;
  farCounted += mainAG + (countBasement ? mainBG : 0);
  if (countParking) {
    farCounted += pcAG + (countBasement ? pcBG : 0);
    farCounted += paAG + (countBasement ? paBG : 0);
  }
  return farCounted;
}

// Currency conversion (kept for future use)
const CURRENCIES = ["THB", "USD"];
function convertCurrency(value, from, to, fxTHBperUSD) {
  if (from === to) return value;
  if (from === "USD" && to === "THB") return value * fxTHBperUSD;
  if (from === "THB" && to === "USD") return value / Math.max(1e-9, fxTHBperUSD);
  return value;
}

// =============================================================
// Legal Presets (TH) — **Replace/extend with your locality rules as needed**
// =============================================================
const BUILDING_TYPES = ["Housing", "Hi-Rise", "Low-Rise", "Public Building", "Office Building", "Hotel"];
const PRESETS = ["None", "TH Condo", "TH Hotel"];

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
  presets: {
    None: {
      lockOSR: false,
      lockGreenPct: false,
      bType: "Housing",
      osr: 15,
      greenPct: 40,
      countParkingInFAR: true,
      countBasementInFAR: false,
    },
    "TH Condo": {
      lockOSR: true,
      lockGreenPct: true,
      bType: "Hi-Rise",
      osr: 10,
      greenPct: 50,
      countParkingInFAR: false,
      countBasementInFAR: false,
    },
    "TH Hotel": {
      lockOSR: true,
      lockGreenPct: false,
      bType: "Hotel",
      osr: 10,
      greenPct: 40,
      countParkingInFAR: false,
      countBasementInFAR: false,
    },
  },
};

function suggestedOSR(type) {
  const r = RULES.building[type];
  return r?.minOSR ?? 15;
}
function suggestedGreenPct(type) {
  const r = RULES.building[type];
  return r?.greenPctOfOSR ?? 40;
}

// =============================================================
// Scenario type
// =============================================================
const DEFAULT_SCENARIO = {
  // Core site & zoning
  siteArea: 8000,
  far: 5,
  bType: "Housing",
  osr: 30,
  greenPctOfOSR: 40,

  // Geometry
  mainFloorsAG: 20,
  mainFloorsBG: 0,
  parkingConFloorsAG: 3,
  parkingConFloorsBG: 0,
  parkingAutoFloorsAG: 0,
  parkingAutoFloorsBG: 0,
  ftf: 3.2,
  maxHeight: 120,

  // Plates (m²)
  mainFloorPlate: 1500,
  parkingConPlate: 1200,
  parkingAutoPlate: 800,

  // Parking efficiency (structured)
  bayConv: 25,
  circConvPct: 0.0,
  bayAuto: 16,
  circAutoPct: 0.0,

  // Open-lot parking (at-grade, outside building → NOT counted in FAR)
  openLotArea: 0, // m² of open lot used for parking
  openLotBay: 25, // m² per car, net
  openLotCircPct: 0.0, // % circulation for open lot

  // Eff ratios
  nlaPctOfCFA: 70,
  nsaPctOfCFA: 80,
  gfaOverCfaPct: 95,

  // FAR rules toggles
  countParkingInFAR: true,
  countBasementInFAR: false,

  // Cost
  costArchPerSqm: 16000,
  costStructPerSqm: 22000,
  costMEPPerSqm: 20000,
  costGreenPerSqm: 4500,
  costConventionalPerCar: 125000,
  costAutoPerCar: 432000,
  costOpenLotPerCar: 60000, // cheaper per stall assumption

  customCosts: [],

  // Budget
  budget: 500000000, // ฿500m default
};

// single scenario compute
function useScenarioCompute(state) {
  const effAreaConCar = useMemo(() => state.bayConv * (1 + state.circConvPct), [state.bayConv, state.circConvPct]);
  const effAreaAutoCar = useMemo(() => state.bayAuto * (1 + state.circAutoPct), [state.bayAuto, state.circAutoPct]);
  const effAreaOpenCar = useMemo(() => state.openLotBay * (1 + state.openLotCircPct), [state.openLotBay, state.openLotCircPct]);

  const derived = useMemo(() => {
    const far = clamp(state.far, RULES.base.farRange[0], RULES.base.farRange[1]);
    const maxGFA = state.siteArea * far;

    // OSR & Green
    const openSpaceArea = (state.osr / 100) * state.siteArea;
    const greenArea = (state.greenPctOfOSR / 100) * openSpaceArea;

    // CFA (structured)
    const mainCFA_AG = state.mainFloorsAG * state.mainFloorPlate;
    const mainCFA_BG = state.mainFloorsBG * state.mainFloorPlate;
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

    // Parking counts by effective area/car (structured)
    const convCarsPerFloor = Math.floor(state.parkingConPlate / Math.max(1, effAreaConCar));
    const autoCarsPerFloor = Math.floor(state.parkingAutoPlate / Math.max(1, effAreaAutoCar));
    const totalConvCars = convCarsPerFloor * (state.parkingConFloorsAG + state.parkingConFloorsBG);
    const totalAutoCars = autoCarsPerFloor * (state.parkingAutoFloorsAG + state.parkingAutoFloorsBG);

    // Open-lot cars (at-grade outside building) → NOT part of FAR, derived from area
    const openLotCars = Math.floor(state.openLotArea / Math.max(1, effAreaOpenCar));

    // Totals
    const totalCars = totalConvCars + totalAutoCars + openLotCars;
    const disabledCars = calcDisabledParking(totalCars);

    // FAR-counted (no open-lot)
    const farCounted = computeFarCounted(
      mainCFA_AG,
      mainCFA_BG,
      parkConCFA_AG,
      parkConCFA_BG,
      parkAutoCFA_AG,
      parkAutoCFA_BG,
      state.countParkingInFAR,
      state.countBasementInFAR
    );
    const farOk = farCounted <= maxGFA;

    // Efficiency
    const nla = (state.nlaPctOfCFA / 100) * totalCFA;
    const nsa = (state.nsaPctOfCFA / 100) * totalCFA;
    const gfa = (state.gfaOverCfaPct / 100) * totalCFA;

    const baseCostPerSqm = state.costArchPerSqm + state.costStructPerSqm + state.costMEPPerSqm;
    const constructionCost = totalCFA * baseCostPerSqm;
    const greenCost = greenArea * state.costGreenPerSqm;
    const parkingCost =
      totalConvCars * state.costConventionalPerCar + totalAutoCars * state.costAutoPerCar + openLotCars * state.costOpenLotPerCar;

    const customCostTotal = (state.customCosts || []).reduce((sum, i) => {
      if (i.kind === "per_sqm") return sum + i.rate * totalCFA;
      if (i.kind === "per_car_conv") return sum + i.rate * totalConvCars;
      if (i.kind === "per_car_auto") return sum + i.rate * totalAutoCars;
      return sum + i.rate;
    }, 0);

    const capexTotal = constructionCost + greenCost + parkingCost + customCostTotal;
    const budgetOk = state.budget > 0 ? capexTotal <= state.budget : true;

    // Legal checks (based on bType)
    const rule = RULES.building[state.bType] || {};
    const osrOk = rule.minOSR != null ? state.osr >= rule.minOSR : true;
    const greenRule = rule.greenPctOfOSR;
    const greenPctOk = greenRule != null ? state.greenPctOfOSR >= greenRule : true; // treat rule as minimum requirement

    return {
      maxGFA,
      openSpaceArea,
      greenArea,
      mainCFA_AG,
      mainCFA_BG,
      mainCFA,
      parkConCFA_AG,
      parkConCFA_BG,
      parkConCFA,
      parkAutoCFA_AG,
      parkAutoCFA_BG,
      parkAutoCFA,
      totalCFA,
      farCounted,
      farOk,
      estHeight,
      heightOk,
      convCarsPerFloor,
      autoCarsPerFloor,
      totalConvCars,
      totalAutoCars,
      openLotCars,
      totalCars,
      disabledCars,
      nla,
      nsa,
      gfa,
      baseCostPerSqm,
      constructionCost,
      greenCost,
      parkingCost,
      customCostTotal,
      capexTotal,
      budgetOk,
      osrOk,
      greenPctOk,
      // helpers
      effAreaOpenCar,
    };
  }, [state, effAreaConCar, effAreaAutoCar, effAreaOpenCar]);

  return { effAreaConCar, effAreaAutoCar, effAreaOpenCar, derived };
}

// =============================================================
// Scenario Card (no undefined components; no Chip usage)
// =============================================================
function ScenarioCard({ scenario, preset, onUpdate, onRemove, currency, fxTHBperUSD }) {
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

  const curSymbol = currency === "THB" ? "฿" : "$";
  const sqmLabel = `${curSymbol}/m²`;

  const capexData = useMemo(
    () => [
      { name: "Construction", value: Math.max(0, derived.constructionCost) },
      { name: "Green", value: Math.max(0, derived.greenCost) },
      { name: "Parking", value: Math.max(0, derived.parkingCost) },
      { name: "Custom", value: Math.max(0, derived.customCostTotal) },
    ],
    [derived.constructionCost, derived.greenCost, derived.parkingCost, derived.customCostTotal]
  );

  const COLORS = ["#3b82f6", "#22c55e", "#f97316", "#a855f7"];

  const fileRef = useRef(null);
  const handleExportCSV = () => {
    const s = scenario;
    const rows = Object.entries(s)
      .filter(([k]) => k !== "id")
      .map(([Field, Value]) => ({ Field, Value }));
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
        // Expect Field,Value header
        const entries = lines
          .slice(1)
          .map((line) => {
            const idx = line.indexOf(",");
            if (idx < 0) return null;
            const k = line.slice(0, idx).trim();
            const v = line.slice(idx + 1).trim();
            const num = Number(v);
            return [k, isFinite(num) && v.match(/^[-+]?\d+(\.\d+)?$/) ? num : v];
          })
          .filter(Boolean);
        const patch = Object.fromEntries(entries);
        onUpdate(scenario.id, patch);
      } catch (e) {
        alert("Import failed: " + e);
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="p-4 rounded-2xl bg-white shadow border space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="font-semibold">Scenario: {scenario.name}</h2>
        <button onClick={() => onRemove(scenario.id)} className="ml-auto text-neutral-500 hover:text-red-600">
          <Trash2 className="w-5 h-5" />
        </button>
      </div>

      {/* Inputs */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="p-3 rounded-xl border">
          <h3 className="font-medium text-sm flex items-center gap-2">
            <Ruler className="w-4 h-4" /> Site & Zoning
          </h3>
          <div className="grid grid-cols-2 gap-3 mt-2 text-sm">
            <label>
              Site Area (m²)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.siteArea}
                onChange={(e) => onUpdate(scenario.id, { siteArea: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label>
              FAR (1–10)
              <input
                type="number"
                min={RULES.base.farRange[0]}
                max={RULES.base.farRange[1]}
                step={0.1}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.far}
                onChange={(e) =>
                  onUpdate(scenario.id, { far: clamp(Number(e.target.value), RULES.base.farRange[0], RULES.base.farRange[1]) })
                }
              />
            </label>
            <label className="col-span-2">
              Building Type
              <select
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.bType}
                onChange={(e) =>
                  onUpdate(scenario.id, {
                    bType: e.target.value,
                    osr: suggestedOSR(e.target.value),
                    greenPctOfOSR: suggestedGreenPct(e.target.value),
                  })
                }
              >
                {BUILDING_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label>
              OSR (%)
              <input
                type="number"
                min={0}
                max={100}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.osr}
                onChange={(e) => onUpdate(scenario.id, { osr: clamp(Number(e.target.value), 0, 100) })}
              />
              {RULES.building[scenario.bType]?.minOSR != null && (
                <div className="text-[11px] mt-1 text-neutral-500">ขั้นต่ำ {RULES.building[scenario.bType].minOSR}%</div>
              )}
            </label>
            <label>
              Green (% of OSR)
              <input
                type="number"
                min={0}
                max={100}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.greenPctOfOSR}
                onChange={(e) => onUpdate(scenario.id, { greenPctOfOSR: clamp(Number(e.target.value), 0, 100) })}
              />
              {RULES.building[scenario.bType]?.greenPctOfOSR != null && (
                <div className="text-[11px] mt-1 text-neutral-500">ขั้นต่ำ {RULES.building[scenario.bType].greenPctOfOSR}%</div>
              )}
            </label>
          </div>
        </div>

        <div className="p-3 rounded-xl border">
          <h3 className="font-medium text-sm flex items-center gap-2">
            <Building2 className="w-4 h-4" /> Geometry & Height
          </h3>
          <div className="grid grid-cols-3 gap-3 mt-2 text-sm">
            <label className="col-span-1">
              Main Floors (AG)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.mainFloorsAG}
                onChange={(e) => onUpdate(scenario.id, { mainFloorsAG: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label className="col-span-1">
              Main Floors (BG)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.mainFloorsBG}
                onChange={(e) => onUpdate(scenario.id, { mainFloorsBG: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label className="col-span-1">
              F2F (m)
              <input
                type="number"
                min={0}
                step={0.1}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.ftf}
                onChange={(e) => onUpdate(scenario.id, { ftf: Math.max(0, Number(e.target.value)) })}
              />
            </label>

            <label className="col-span-1">
              Park Conv (AG)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.parkingConFloorsAG}
                onChange={(e) => onUpdate(scenario.id, { parkingConFloorsAG: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label className="col-span-1">
              Park Conv (BG)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.parkingConFloorsBG}
                onChange={(e) => onUpdate(scenario.id, { parkingConFloorsBG: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label className="col-span-1">
              Max Height (m)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.maxHeight}
                onChange={(e) => onUpdate(scenario.id, { maxHeight: Math.max(0, Number(e.target.value)) })}
              />
            </label>

            <label className="col-span-1">
              Auto Park (AG)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.parkingAutoFloorsAG}
                onChange={(e) => onUpdate(scenario.id, { parkingAutoFloorsAG: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label className="col-span-1">
              Auto Park (BG)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.parkingAutoFloorsBG}
                onChange={(e) => onUpdate(scenario.id, { parkingAutoFloorsBG: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <div className="col-span-1" />

            <label className="col-span-1">
              Main Plate (m²)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.mainFloorPlate}
                onChange={(e) => onUpdate(scenario.id, { mainFloorPlate: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label className="col-span-1">
              Park Plate (Conv) (m²)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.parkingConPlate}
                onChange={(e) => onUpdate(scenario.id, { parkingConPlate: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label className="col-span-1">
              Park Plate (Auto) (m²)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.parkingAutoPlate}
                onChange={(e) => onUpdate(scenario.id, { parkingAutoPlate: Math.max(0, Number(e.target.value)) })}
              />
            </label>

            <label className="col-span-1">
              Count Parking in FAR?
              <select
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={String(scenario.countParkingInFAR)}
                onChange={(e) => onUpdate(scenario.id, { countParkingInFAR: e.target.value === "true" })}
              >
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </label>
            <label className="col-span-1">
              Count Basement in FAR?
              <select
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={String(scenario.countBasementInFAR)}
                onChange={(e) => onUpdate(scenario.id, { countBasementInFAR: e.target.value === "true" })}
              >
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </label>
            <div className="col-span-1" />
          </div>
        </div>

        <div className="p-3 rounded-xl border">
          <h3 className="font-medium text-sm flex items-center gap-2">
            <Car className="w-4 h-4" /> Parking & Efficiency
          </h3>
          <div className="grid grid-cols-3 gap-3 mt-2 text-sm">
            <label>
              Conv Bay (m²) — net
              <input
                type="number"
                min={1}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.bayConv}
                onChange={(e) => onUpdate(scenario.id, { bayConv: Math.max(1, Number(e.target.value)) })}
              />
            </label>
            <label>
              Conv Circ (%)
              <input
                type="number"
                min={0}
                max={100}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.circConvPct * 100}
                onChange={(e) => onUpdate(scenario.id, { circConvPct: clamp(Number(e.target.value), 0, 100) / 100 })}
              />
            </label>
            <div className="text-xs text-neutral-600 flex items-end">
              eff = {nf(scenario.bayConv * (1 + scenario.circConvPct))} m²/คัน
            </div>

            <label>
              Auto Bay (m²) — net
              <input
                type="number"
                min={1}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.bayAuto}
                onChange={(e) => onUpdate(scenario.id, { bayAuto: Math.max(1, Number(e.target.value)) })}
              />
            </label>
            <label>
              Auto Circ (%)
              <input
                type="number"
                min={0}
                max={100}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.circAutoPct * 100}
                onChange={(e) => onUpdate(scenario.id, { circAutoPct: clamp(Number(e.target.value), 0, 100) / 100 })}
              />
            </label>
            <div className="text-xs text-neutral-600 flex items-end">
              eff = {nf(scenario.bayAuto * (1 + scenario.circAutoPct))} m²/คัน
            </div>

            <label className="col-span-1">
              Open-lot Area (m²)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.openLotArea}
                onChange={(e) => onUpdate(scenario.id, { openLotArea: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label className="col-span-1">
              Open-lot Bay (m²/คัน)
              <input
                type="number"
                min={1}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.openLotBay}
                onChange={(e) => onUpdate(scenario.id, { openLotBay: Math.max(1, Number(e.target.value)) })}
              />
            </label>
            <label className="col-span-1">
              Open-lot Circ (%)
              <input
                type="number"
                min={0}
                max={100}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.openLotCircPct * 100}
                onChange={(e) => onUpdate(scenario.id, { openLotCircPct: clamp(Number(e.target.value), 0, 100) / 100 })}
              />
            </label>
            <div className="col-span-3 text-xs text-neutral-600">eff (open-lot) = {nf(effAreaOpenCar)} m²/คัน</div>
          </div>
        </div>

        <div className="p-3 rounded-xl border">
          <h3 className="font-medium text-sm flex items-center gap-2">
            <Factory className="w-4 h-4" /> Costs & Budget
          </h3>
          <div className="grid grid-cols-2 gap-3 mt-2 text-sm">
            <label>
              Architecture {sqmLabel}
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.costArchPerSqm}
                onChange={(e) => onUpdate(scenario.id, { costArchPerSqm: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label>
              Structure {sqmLabel}
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.costStructPerSqm}
                onChange={(e) => onUpdate(scenario.id, { costStructPerSqm: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label>
              MEP {sqmLabel}
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.costMEPPerSqm}
                onChange={(e) => onUpdate(scenario.id, { costMEPPerSqm: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label>
              Green {sqmLabel}
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.costGreenPerSqm}
                onChange={(e) => onUpdate(scenario.id, { costGreenPerSqm: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label>
              Parking (Conv) ({curSymbol}/car)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.costConventionalPerCar}
                onChange={(e) => onUpdate(scenario.id, { costConventionalPerCar: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label>
              Parking (Auto) ({curSymbol}/car)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.costAutoPerCar}
                onChange={(e) => onUpdate(scenario.id, { costAutoPerCar: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label>
              Parking (Open-lot) ({curSymbol}/car)
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.costOpenLotPerCar}
                onChange={(e) => onUpdate(scenario.id, { costOpenLotPerCar: Math.max(0, Number(e.target.value)) })}
              />
            </label>
            <label className="col-span-2">
              Budget ({curSymbol})
              <input
                type="number"
                min={0}
                className="mt-1 w-full border rounded-xl px-3 py-2"
                value={scenario.budget}
                onChange={(e) => onUpdate(scenario.id, { budget: Math.max(0, Number(e.target.value)) })}
              />
            </label>
          </div>
          {/* custom cost items */}
          <div className="mt-3">
            <div className="flex items-center justify-between">
              <h4 className="font-medium text-sm">Additional Cost Items</h4>
              <button
                onClick={() =>
                  onUpdate(scenario.id, {
                    customCosts: [...(scenario.customCosts || []), { id: Date.now(), name: "Misc.", kind: "lump_sum", rate: 0 }],
                  })
                }
                className="text-sm px-2 py-1 border rounded-xl flex items-center gap-1 hover:bg-neutral-100"
              >
                <Plus className="w-4 h-4" />
                Add
              </button>
            </div>
            {(scenario.customCosts || []).length === 0 && (
              <div className="text-xs text-neutral-500 mt-1">(ว่าง) — เพิ่มหมวด FF&E/Facade Premium/Consultant/Permit ฯลฯ</div>
            )}
            {(scenario.customCosts || []).map((i) => (
              <div key={i.id} className="grid grid-cols-12 gap-2 items-center mt-2">
                <input
                  className="col-span-5 border rounded-xl px-3 py-2 text-sm"
                  value={i.name}
                  onChange={(e) =>
                    onUpdate(scenario.id, { customCosts: (scenario.customCosts || []).map((x) => (x.id === i.id ? { ...x, name: e.target.value } : x)) })
                  }
                />
                <select
                  className="col-span-3 border rounded-xl px-3 py-2 text-sm"
                  value={i.kind}
                  onChange={(e) =>
                    onUpdate(scenario.id, { customCosts: (scenario.customCosts || []).map((x) => (x.id === i.id ? { ...x, kind: e.target.value } : x)) })
                  }
                >
                  <option value="per_sqm">per m²</option>
                  <option value="per_car_conv">per car (Conv)</option>
                  <option value="per_car_auto">per car (Auto)</option>
                  <option value="lump_sum">lump sum</option>
                </select>
                <input
                  type="number"
                  className="col-span-3 border rounded-xl px-3 py-2 text-sm"
                  value={i.rate}
                  onChange={(e) =>
                    onUpdate(scenario.id, { customCosts: (scenario.customCosts || []).map((x) => (x.id === i.id ? { ...x, rate: Number(e.target.value) } : x)) })
                  }
                />
                <button
                  onClick={() => onUpdate(scenario.id, { customCosts: (scenario.customCosts || []).filter((x) => x.id !== i.id) })}
                  className="col-span-1 justify-self-end text-neutral-500 hover:text-red-600"
                >
                  <Trash2 className="w-5 h-5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Summary & Viz */}
      <div className="grid md:grid-cols-3 gap-4">
        <div className="p-4 rounded-2xl bg-emerald-50 border-2 border-emerald-300 shadow">
          <h3 className="text-sm font-semibold flex items-center gap-2 text-emerald-800">
            <TrendingUp className="w-4 h-4" /> Zoning Summary
          </h3>
          <div className="mt-2 text-sm space-y-1">
            <div>
              Max GFA: <b>{nf(derived.maxGFA)}</b> m²
            </div>
            <div>
              FAR-counted Area: <b>{nf(derived.farCounted)}</b> m²
            </div>
            <div>
              Open Space (OSR): <b>{nf(derived.openSpaceArea)}</b> m² ({scenario.osr}%)
            </div>
            <div>
              Green Area: <b>{nf(derived.greenArea)}</b> m² ({scenario.greenPctOfOSR}% of OSR)
            </div>
            <div className={`text-xs ${derived.farOk ? "text-emerald-700" : "text-red-600"} flex items-center gap-1`}>
              {!derived.farOk && <TriangleAlert className="w-3 h-3" />} FAR check: {derived.farOk ? "OK" : "Exceeds Max GFA"}
            </div>
          </div>
        </div>
        <div className="p-4 rounded-2xl bg-blue-50 border-2 border-blue-300 shadow">
          <h3 className="text-sm font-semibold flex items-center gap-2 text-blue-800">
            <Calculator className="w-4 h-4" /> Areas
          </h3>
          <div className="mt-2 text-sm space-y-1">
            <div>
              Main CFA (AG): <b>{nf(derived.mainCFA_AG)}</b> m²
            </div>
            <div>
              Main CFA (BG): <b>{nf(derived.mainCFA_BG)}</b> m²
            </div>
            <div>
              Parking CFA (Conv): <b>{nf(derived.parkConCFA)}</b> m²
            </div>
            <div>
              Parking CFA (Auto): <b>{nf(derived.parkAutoCFA)}</b> m²
            </div>
            <div>
              Total CFA: <b>{nf(derived.totalCFA)}</b> m²
            </div>
          </div>
        </div>
        <div className="p-4 rounded-2xl bg-yellow-50 border-2 border-yellow-300 shadow">
          <h3 className="text-sm font-semibold flex items-center gap-2 text-yellow-800">
            <Building2 className="w-4 h-4" /> Height
          </h3>
          <div className="mt-2 text-sm space-y-1">
            <div>
              Estimated Height (AG only): <b>{nf(derived.estHeight)}</b> m
            </div>
            <div>
              Max Height: <b>{nf(scenario.maxHeight)}</b> m
            </div>
            <div className={`text-xs ${derived.heightOk ? "text-emerald-700" : "text-red-600"} flex items-center gap-1`}>
              {!derived.heightOk && <TriangleAlert className="w-3 h-3" />} Height check: {derived.heightOk ? "OK" : "Exceeds Limit"}
            </div>
          </div>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        <div className="p-4 rounded-2xl bg-indigo-50 border-2 border-indigo-300 shadow">
          <h3 className="text-sm font-semibold flex items-center gap-2 text-indigo-800">
            <Calculator className="w-4 h-4" /> Efficiency Output
          </h3>
          <div className="mt-2 text-sm space-y-1">
            <div>
              NLA: <b>{nf(derived.nla)}</b> m² <span className="text-xs text-neutral-500">({nf(derived.nla / derived.totalCFA, 3)} × CFA)</span>
            </div>
            <div>
              NSA: <b>{nf(derived.nsa)}</b> m² <span className="text-xs text-neutral-500">({nf(derived.nsa / derived.totalCFA, 3)} × CFA)</span>
            </div>
            <div>
              GFA: <b>{nf(derived.gfa)}</b> m² <span className="text-xs text-neutral-500">({nf(derived.gfa / derived.totalCFA, 3)} × CFA)</span>
            </div>
          </div>
        </div>
        <div className="p-4 rounded-2xl bg-orange-50 border-2 border-orange-300 shadow">
          <h3 className="text-sm font-semibold flex items-center gap-2 text-orange-800">
            <Car className="w-4 h-4" /> Parking
          </h3>
          <div className="mt-2 text-sm space-y-1">
            <div>
              Cars/Floor (Conv): <b>{derived.convCarsPerFloor}</b>{" "}
              <span className="text-xs text-neutral-500">(eff {nf(effAreaConCar)} m²/car)</span>
            </div>
            <div>
              Cars/Floor (Auto): <b>{derived.autoCarsPerFloor}</b>{" "}
              <span className="text-xs text-neutral-500">(eff {nf(effAreaAutoCar)} m²/car)</span>
            </div>
            <div>
              Open-lot Cars: <b>{derived.openLotCars}</b>{" "}
              <span className="text-xs text-neutral-500">(eff {nf(effAreaOpenCar)} m²/car)</span>
            </div>
            <div>
              Total Cars (Conv): <b>{derived.totalConvCars}</b>
            </div>
            <div>
              Total Cars (Auto): <b>{derived.totalAutoCars}</b>
            </div>
            <div>
              Total Cars: <b>{derived.totalCars}</b>
            </div>
            <div>
              Disabled Spaces (calc): <b>{derived.disabledCars}</b>
            </div>
          </div>
        </div>
        <div className="p-4 rounded-2xl bg-pink-50 border-2 border-pink-300 shadow">
          <h3 className="text-sm font-semibold flex items-center gap-2 text-pink-800">
            <Factory className="w-4 h-4" /> CAPEX
          </h3>
          <div className="mt-2 text-sm space-y-1">
            <div>
              Base Build Cost: <b>{currencySymbol("THB")}
              {nf(derived.constructionCost)}</b>
            </div>
            <div>
              Green Cost: <b>{currencySymbol("THB")}
              {nf(derived.greenCost)}</b>
            </div>
            <div>
              Parking Cost: <b>{currencySymbol("THB")}
              {nf(derived.parkingCost)}</b>{" "}
              <span className="text-xs text-neutral-500">(includes open-lot)</span>
            </div>
            {(scenario.customCosts || []).length > 0 && (
              <div>
                Custom Items: <b>{currencySymbol("THB")}
                {nf(derived.customCostTotal)}</b>
              </div>
            )}
            <div className="border-t pt-2">
              Total CAPEX: <b>{currencySymbol("THB")}
              {nf(derived.capexTotal)}</b>
            </div>
            <div className={`text-xs ${derived.budgetOk ? "text-emerald-700" : "text-red-600"} flex items-center gap-1`}>
              {!derived.budgetOk && <TriangleAlert className="w-3 h-3" />} Budget check: {derived.budgetOk ? "OK" : "Over Budget"} (Budget{" "}
              {currencySymbol("THB")}
              {nf(scenario.budget)})
            </div>
          </div>
        </div>
      </div>

      {/* Viz row */}
      <div className="grid md:grid-cols-3 gap-4">
        <div className="p-3 rounded-2xl bg-white border shadow flex flex-col">
          <div className="text-sm font-semibold flex items-center gap-2 mb-2">
            <LayoutGrid className="w-4 h-4" /> Site Visualization
          </div>
          <SiteViz siteArea={scenario.siteArea} osr={scenario.osr} greenArea={derived.greenArea} className="w-full h-auto" />
          <div className="text-xs text-neutral-600 mt-2">แผนภาพสัดส่วน Site / Open Space / Green (เชิงสเกลพื้นที่แบบย่อ)</div>
        </div>
        <div className="p-3 rounded-2xl bg-white border shadow col-span-2">
          <div className="text-sm font-semibold flex items-center gap-2 mb-2">
            <BarChart3 className="w-4 h-4" /> CAPEX Breakdown
          </div>
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie data={capexData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80}>
                  {capexData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
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
          <div className="text-sm">
            <b>Design check:</b> {warnings.join(" · ")}
          </div>
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
    </div>
  );
}

// Small SVG site visualizer
function SiteViz({ siteArea, osr, greenArea, className }) {
  const W = 420;
  const H = 260;
  const P = 16;
  const siteW = W - 2 * P;
  const siteH = H - 2 * P;
  const osrRatio = clamp(osr / 100, 0, 1);
  const greenRatio = clamp(greenArea / Math.max(1e-9, siteArea * osrRatio), 0, 1);
  const osrW = siteW * Math.sqrt(osrRatio);
  const osrH = siteH * Math.sqrt(osrRatio);
  const greenW = osrW * Math.sqrt(greenRatio);
  const greenH = osrH * Math.sqrt(greenRatio);
  const cx = W / 2;
  const cy = H / 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={className}>
      <rect x={0} y={0} width={W} height={H} rx={12} fill="#f8fafc" />
      <rect x={P} y={P} width={siteW} height={siteH} fill="#fff" stroke="#CBD5E1" strokeWidth={2} />
      <rect x={cx - osrW / 2} y={cy - osrH / 2} width={osrW} height={osrH} fill="#dcfce7" stroke="#86efac" />
      <rect x={cx - greenW / 2} y={cy - greenH / 2} width={greenW} height={greenH} fill="#86efac" stroke="#059669" />
      <g fontSize={10} fill="#334155">
        <text x={P + 6} y={P + 14}>
          Site
        </text>
        <text x={cx - osrW / 2 + 6} y={cy - osrH / 2 + 14}>
          Open Space
        </text>
        <text x={cx - greenW / 2 + 6} y={cy - greenH / 2 + 14}>
          Green
        </text>
      </g>
    </svg>
  );
}

// =============================
// Test panel (ALWAYS add tests)
// =============================
function TestsPanel({ scenario, derived }) {
  const tests = useMemo(() => {
    const mAG = scenario.mainFloorsAG * scenario.mainFloorPlate;
    const mBG = scenario.mainFloorsBG * scenario.mainFloorPlate;
    const pcAG = scenario.parkingConFloorsAG * scenario.parkingConPlate;
    const pcBG = scenario.parkingConFloorsBG * scenario.parkingConPlate;
    const paAG = scenario.parkingAutoFloorsAG * scenario.parkingAutoPlate;
    const paBG = scenario.parkingAutoFloorsBG * scenario.parkingAutoPlate;

    const farExpected = computeFarCounted(
      mAG,
      mBG,
      pcAG,
      pcBG,
      paAG,
      paBG,
      scenario.countParkingInFAR,
      scenario.countBasementInFAR
    );

    const openLotExpectedCars = Math.floor(scenario.openLotArea / Math.max(1, scenario.openLotBay * (1 + scenario.openLotCircPct)));

    return [
      { name: "calcDisabledParking(0)", actual: calcDisabledParking(0), expected: 0 },
      { name: "calcDisabledParking(50)", actual: calcDisabledParking(50), expected: 2 },
      { name: "calcDisabledParking(51)", actual: calcDisabledParking(51), expected: 3 },
      { name: "calcDisabledParking(100)", actual: calcDisabledParking(100), expected: 3 },
      { name: "calcDisabledParking(101)", actual: calcDisabledParking(101), expected: 4 },
      { name: "calcDisabledParking(250)", actual: calcDisabledParking(250), expected: 5 },
      { name: "computeFarCounted(default flags)", actual: derived.farCounted, expected: farExpected },
      // synthetic sanity checks
      {
        name: "computeFarCounted(no parking, no basement)",
        actual: computeFarCounted(100, 20, 30, 40, 50, 60, false, false),
        expected: 100,
      },
      {
        name: "computeFarCounted(parking+basement)",
        actual: computeFarCounted(100, 20, 30, 40, 50, 60, true, true),
        expected: 300,
      },
      // open-lot behavior
      { name: "openLotCars formula", actual: derived.openLotCars, expected: openLotExpectedCars },
      { name: "open-lot NOT in FAR", actual: derived.farCounted, expected: farExpected },
    ];
  }, [scenario, derived.farCounted, derived.openLotCars]);

  return (
    <div className="p-4 rounded-2xl border bg-white shadow">
      <div className="font-medium mb-2">Self-check Tests</div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2 text-sm">
        {tests.map((t) => {
          const pass = deepEqual(t.actual, t.expected);
          return (
            <div
              key={t.name}
              className={`flex items-center justify-between rounded-lg border px-3 py-2 ${
                pass ? "bg-emerald-50 border-emerald-200" : "bg-rose-50 border-rose-200"
              }`}
            >
              <div className="truncate">{t.name}</div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-neutral-600">{String(t.actual)}</span>
                <span className={`px-2 py-0.5 text-xs rounded-full ${pass ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>
                  {pass ? "PASS" : "FAIL"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// helpers used by components
function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}
function currencySymbol(c) {
  return c === "THB" ? "฿" : "$";
}

// =============================
// Preview App (export default)
// =============================
export default function FeasibilityAppPreview() {
  const [scenario, setScenario] = useState({ id: 1, name: "Test Project", ...DEFAULT_SCENARIO });
  const { derived } = useScenarioCompute(scenario);

  return (
    <div className="min-h-screen bg-neutral-100 p-6 space-y-6">
      <ScenarioCard
        scenario={scenario}
        preset="None"
        onUpdate={(id, patch) => setScenario((s) => ({ ...s, ...patch }))}
        onRemove={() => setScenario({ id: 1, name: "Test Project", ...DEFAULT_SCENARIO })}
        currency="THB"
        fxTHBperUSD={36}
      />
      <TestsPanel scenario={scenario} derived={derived} />
    </div>
  );
}
