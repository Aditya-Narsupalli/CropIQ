import React, { useEffect, useMemo, useRef, useState } from "react";
import { FaRupeeSign, FaBalanceScale, FaSlidersH, FaUndo, FaSpinner, FaTrophy } from "react-icons/fa";
import { whatIfYieldApi, compareCropsApi } from "../../services/api";

// What-if sliders: [field, label, unit, min, max, step]
const SLIDERS = [
  ["fertilizer", "Fertilizer", "kg/ha", 0, 300, 5],
  ["pesticide", "Crop protection", "kg or L/ha", 0, 10, 0.5],
  ["n", "Soil nitrogen (N)", "kg/ha", 0, 700, 10],
  ["ph", "Soil pH", "", 4, 9, 0.1],
  ["organic_carbon", "Organic carbon", "%", 0.1, 1.5, 0.05],
];
const INPUT_FIELDS = ["ph", "n", "p", "k", "organic_carbon", "fertilizer", "pesticide"];

// Rs amounts in the Indian style: ₹45,300 / ₹3.28 lakh / ₹1.2 crore
const formatINR = (value) => {
  if (value == null || Number.isNaN(value)) return "–";
  const sign = value < 0 ? "−" : "";
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} crore`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} lakh`;
  return `${sign}₹${Math.round(abs).toLocaleString("en-IN")}`;
};

const signed = (value, digits = 1) => `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;

const sameInputs = (a, b) => INPUT_FIELDS.every((f) => Number(a[f]) === Number(b[f]));

function IncomeCard({ economics, prediction, price, cost, onPriceChange, onCostChange, isScenario }) {
  const priceInfo = prediction.price;
  if (!priceInfo) {
    return (
      <div className="bg-gray-50 p-3 rounded-lg border border-gray-100 text-xs text-gray-500">
        Market price isn't available for this crop, so expected income can't be estimated.
      </div>
    );
  }
  const converted = economics && (prediction.scenario_context?.price_conversion ?? 1) !== 1;

  return (
    <div className="bg-emerald-50 p-4 rounded-lg border border-emerald-100">
      <h4 className="text-sm font-semibold text-emerald-900 mb-3 flex items-center">
        <FaRupeeSign className="mr-2" /> Expected income
        {isScenario && (
          <span className="ml-2 text-[10px] font-medium bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded">
            what-if scenario
          </span>
        )}
      </h4>
      {economics && (
        <>
          {economics.profit != null && (
            <div className="text-center mb-3">
              <p className="text-[11px] uppercase tracking-wider text-emerald-700">Estimated profit</p>
              <p className={`text-2xl font-bold ${economics.profit < 0 ? "text-red-600" : "text-emerald-800"}`}>
                {formatINR(economics.profit)}
              </p>
              {economics.profit_per_ha != null && (
                <p className="text-[11px] text-emerald-700">{formatINR(economics.profit_per_ha)} per hectare</p>
              )}
            </div>
          )}
          <div className="text-xs space-y-1.5 border-t border-emerald-100 pt-2">
            <div className="flex justify-between gap-2">
              <span className="text-gray-600">Revenue</span>
              <span className="text-right">
                <span className="font-semibold text-gray-900">{formatINR(economics.revenue)}</span>
                {economics.revenue_low != null && (
                  <span className="block text-[11px] text-gray-500">
                    likely {formatINR(economics.revenue_low)} – {formatINR(economics.revenue_high)}
                  </span>
                )}
              </span>
            </div>
            {economics.cost != null && (
              <div className="flex justify-between gap-2">
                <span className="text-gray-600">Cultivation cost</span>
                <span className="font-semibold text-gray-900">− {formatINR(economics.cost)}</span>
              </div>
            )}
          </div>
        </>
      )}

      <div className="mt-4 grid grid-cols-1 gap-3 text-xs">
        <label className="block">
          <span className="text-gray-600">Selling price (₹ per quintal of {priceInfo.commodity})</span>
          <input
            type="number"
            min="0"
            value={price}
            onChange={(e) => onPriceChange(e.target.value)}
            className="mt-1 w-full p-2 border border-gray-300 rounded-md text-sm bg-white"
          />
          <span className="text-[11px] text-gray-500">
            Default: {priceInfo.source}
            {priceInfo.date ? `, ${priceInfo.date}` : ""}
          </span>
        </label>
        <label className="block">
          <span className="text-gray-600">Your cultivation cost (₹ per hectare)</span>
          <input
            type="number"
            min="0"
            value={cost}
            onChange={(e) => onCostChange(e.target.value)}
            className="mt-1 w-full p-2 border border-gray-300 rounded-md text-sm bg-white"
          />
          <span className="text-[11px] text-gray-500">
            Default is a typical figure — enter your own for a better estimate
          </span>
        </label>
      </div>
      {converted && (
        <p className="text-[11px] text-gray-500 mt-2">
          Yield is reported as milled rice; income uses the equivalent paddy you'd sell (~
          {economics.marketed_production_t.toFixed(1)} t).
        </p>
      )}
    </div>
  );
}

function WhyBreakdown({ current, modelSource }) {
  const items = (current.breakdown || []).filter((b) => Math.abs(b.pct) >= 0.5);
  const maxAbs = Math.max(20, ...items.map((b) => Math.abs(b.pct)));

  return (
    <div className="border-t pt-4 border-gray-100">
      <h4 className="text-sm font-semibold text-gray-800 mb-3 flex items-center">
        <FaBalanceScale className="mr-2 text-sky-600" /> Why this number
      </h4>
      <div className="text-xs space-y-2">
        <div className="flex justify-between text-gray-700">
          <span>
            {modelSource === "ml"
              ? "Typical yield for this area and season"
              : "General estimate for this crop"}
          </span>
          <span className="font-semibold">{current.base_yield?.toFixed(2)} t/ha</span>
        </div>
        {items.length === 0 && (
          <p className="text-gray-500 italic">Your soil and inputs are close to a typical farm's.</p>
        )}
        {items.map((b) => {
          const width = `${(Math.abs(b.pct) / maxAbs) * 50}%`;
          const positive = b.pct >= 0;
          return (
            <div key={b.factor} className="flex items-center gap-2">
              <span className="w-28 shrink-0 text-gray-600">{b.label}</span>
              <div className="relative flex-1 h-3 bg-gray-100 rounded">
                <div className="absolute left-1/2 top-0 bottom-0 w-px bg-gray-300" />
                <div
                  className={`absolute top-0 bottom-0 rounded ${positive ? "bg-emerald-400" : "bg-red-400"}`}
                  style={positive ? { left: "50%", width } : { right: "50%", width }}
                />
              </div>
              <span className={`w-14 text-right font-medium ${positive ? "text-emerald-700" : "text-red-600"}`}>
                {signed(b.pct)}%
              </span>
            </div>
          );
        })}
        <div className="flex justify-between border-t border-gray-100 pt-2 text-gray-800">
          <span className="font-medium">Your estimate</span>
          <span className="font-bold">{current.yield.toFixed(2)} t/ha</span>
        </div>
        {current.agronomy_basis && <p className="text-[11px] text-gray-500 pt-1">{current.agronomy_basis}</p>}
      </div>
    </div>
  );
}

function WhatIfPanel({ inputs, baseline, current, loading, onChange, onReset, changed, irrigation, onIrrigationChange }) {
  const yieldDelta = current.yield - baseline.yield;
  const profitDelta =
    current.economics?.profit != null && baseline.economics?.profit != null
      ? current.economics.profit - baseline.economics.profit
      : null;

  return (
    <div className="border-t pt-4 border-gray-100">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold text-gray-800 flex items-center">
          <FaSlidersH className="mr-2 text-amber-600" /> What if…
          {loading && <FaSpinner className="ml-2 animate-spin text-gray-400" />}
        </h4>
        {changed && (
          <button
            type="button"
            onClick={onReset}
            className="text-xs text-sky-700 hover:text-sky-900 flex items-center"
          >
            <FaUndo className="mr-1" /> Reset
          </button>
        )}
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Move a slider to see how changing your inputs or soil would change yield and profit.
      </p>
      <div className="space-y-3">
        {SLIDERS.map(([field, label, unit, min, max, step]) => (
          <div key={field} className="text-xs">
            <div className="flex justify-between text-gray-700 mb-1">
              <span>{label}</span>
              <span className="font-medium">
                {Number(inputs[field]).toFixed(step < 1 ? (step < 0.1 ? 2 : 1) : 0)} {unit}
              </span>
            </div>
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={inputs[field]}
              onChange={(e) => onChange(field, e.target.value)}
              className="w-full accent-amber-600"
              aria-label={label}
            />
          </div>
        ))}
        {irrigation != null && (
          <div className="text-xs">
            <div className="flex justify-between text-gray-700 mb-1">
              <span>Irrigated share of field</span>
              <span className="font-medium">{Math.round(irrigation * 100)}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={irrigation}
              onChange={(e) => onIrrigationChange(Number(e.target.value))}
              className="w-full accent-amber-600"
              aria-label="Irrigated share of field"
            />
          </div>
        )}
      </div>
      {changed && (
        <div className="mt-4 grid grid-cols-2 gap-3 text-center bg-amber-50 border border-amber-100 rounded-lg p-3">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-amber-700">Yield</p>
            <p className="text-base font-bold text-amber-900">{current.yield.toFixed(2)} t/ha</p>
            <p className={`text-[11px] ${yieldDelta >= 0 ? "text-emerald-700" : "text-red-600"}`}>
              {signed(yieldDelta, 2)} t/ha
            </p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wider text-amber-700">Profit</p>
            <p className="text-base font-bold text-amber-900">{formatINR(current.economics?.profit)}</p>
            {profitDelta != null && (
              <p className={`text-[11px] ${profitDelta >= 0 ? "text-emerald-700" : "text-red-600"}`}>
                {profitDelta >= 0 ? "+" : ""}
                {formatINR(profitDelta)}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** "Best crops for my field": every crop grown here this season, ranked by profit/ha. */
function CropComparison({ formData, currentCrop }) {
  const [state, setState] = useState({ status: "idle" });

  const run = async () => {
    setState({ status: "loading" });
    const num = (v) => Number.parseFloat(v) || 0;
    const body = {
      crop: formData.crop, area: 1, area_unit: "hectares", season: formData.season, state: formData.state,
      district: formData.district || null, annual_rainfall: num(formData.annual_rainfall),
      fertilizer: num(formData.fertilizer), pesticide: num(formData.pesticide), ph: num(formData.ph),
      n: num(formData.n), p: num(formData.p), k: num(formData.k), organic_carbon: num(formData.organic_carbon),
      irrigation: formData.irrigation === "" ? null : Number.parseFloat(formData.irrigation),
    };
    if (formData.latitude && formData.longitude) {
      body.latitude = Number.parseFloat(formData.latitude);
      body.longitude = Number.parseFloat(formData.longitude);
    }
    try {
      setState({ status: "done", data: await compareCropsApi(body) });
    } catch (err) {
      console.error("Crop comparison failed:", err);
      setState({ status: "error" });
    }
  };

  const data = state.data;
  const best = data?.crops?.[0]?.profit_per_ha;

  return (
    <div className="border-t pt-4 border-gray-100">
      <h4 className="text-sm font-semibold text-gray-800 mb-2 flex items-center">
        <FaTrophy className="mr-2 text-amber-500" /> Best crops for my field
      </h4>
      {state.status === "idle" && (
        <>
          <p className="text-xs text-gray-500 mb-2">
            Compare every crop grown in {formData.state || "your state"} this {formData.season} season, using your
            soil and inputs, ranked by expected profit.
          </p>
          <button
            type="button"
            onClick={run}
            className="w-full text-sm bg-amber-100 hover:bg-amber-200 text-amber-900 py-2 rounded-lg transition-colors"
          >
            Compare crops
          </button>
        </>
      )}
      {state.status === "loading" && (
        <p className="text-xs text-gray-500 flex items-center"><FaSpinner className="animate-spin mr-2" /> Comparing crops…</p>
      )}
      {state.status === "error" && <p className="text-xs text-red-600">Comparison is unavailable right now.</p>}
      {state.status === "done" && (
        data.crops.length === 0 ? (
          <p className="text-xs text-gray-500">{data.message || "No crops to compare here."}</p>
        ) : (
          <div className="text-xs space-y-1.5">
            {data.crops.map((c, i) => {
              const isCurrent = c.crop === currentCrop;
              const width = best > 0 && c.profit_per_ha > 0 ? `${(c.profit_per_ha / best) * 100}%` : "0%";
              return (
                <div key={c.crop} className={`rounded p-1.5 ${isCurrent ? "bg-sky-50 ring-1 ring-sky-200" : ""}`}>
                  <div className="flex justify-between gap-2">
                    <span className="text-gray-800">
                      <span className="text-gray-400 mr-1">{i + 1}.</span>
                      {c.crop}
                      {isCurrent && <span className="ml-1 text-sky-700">(your crop)</span>}
                      {c.year_round && <span className="ml-1 text-gray-400">· year-round</span>}
                    </span>
                    <span className={`font-semibold ${c.profit_per_ha < 0 ? "text-red-600" : "text-emerald-700"}`}>
                      {formatINR(c.profit_per_ha)}/ha
                    </span>
                  </div>
                  <div className="h-1.5 bg-gray-100 rounded mt-1">
                    <div className="h-1.5 bg-emerald-400 rounded" style={{ width }} />
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">
                    {c.yield_t_per_ha.toFixed(2)} t/ha · ₹{Math.round(c.price_per_quintal).toLocaleString("en-IN")}/qtl
                  </div>
                </div>
              );
            })}
            <p className="text-[11px] text-gray-500 pt-1">
              {data.compared} crops compared{data.district_used ? ` using ${data.district_used} district data` : ""}. {data.note}
            </p>
          </div>
        )
      )}
    </div>
  );
}

/**
 * Expected income, "why this number" breakdown and what-if sliders for a
 * yield prediction. Remount (via `key`) for each new prediction.
 */
export default function YieldInsights({ prediction, formData }) {
  const initialInputs = useMemo(
    () => Object.fromEntries(INPUT_FIELDS.map((f) => [f, Number.parseFloat(formData[f]) || 0])),
    // Snapshot of the form at prediction time
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [prediction]
  );
  const initialPrice = prediction.price?.price_per_quintal?.toFixed(0) ?? "";
  const initialCost = prediction.economics?.base_cost_per_ha?.toFixed(0) ?? "";

  const [inputs, setInputs] = useState(initialInputs);
  // Irrigated share (0-1). Starts at the farmer's answer, or the state's
  // typical share if they weren't sure; only crops with measured
  // irrigation effects (irrigation_baseline set) get the slider.
  const initialIrrigation = useMemo(() => {
    if (formData.irrigation !== "" && formData.irrigation != null) return Number.parseFloat(formData.irrigation);
    return prediction.irrigation_baseline ?? null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prediction]);
  const [irrigation, setIrrigation] = useState(initialIrrigation);
  const [price, setPrice] = useState(initialPrice);
  const [cost, setCost] = useState(initialCost);
  const [scenario, setScenario] = useState(null);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef(null);

  const inputsChanged = !sameInputs(inputs, initialInputs) || irrigation !== initialIrrigation;
  const economicsChanged = price !== initialPrice || cost !== initialCost;

  useEffect(() => {
    if (!prediction.scenario_context || (!inputsChanged && !economicsChanged)) {
      setScenario(null);
      return undefined;
    }
    const timer = setTimeout(async () => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      const bodyFor = (values, irr) => {
        const body = {
          context: prediction.scenario_context,
          ...Object.fromEntries(INPUT_FIELDS.map((f) => [f, Number(values[f])])),
        };
        // Only send irrigation once the farmer has set it or moved the slider
        if (irr != null && (irr !== prediction.irrigation_baseline || formData.irrigation !== "")) body.irrigation = irr;
        if (price !== "") body.price_per_quintal = Number(price);
        if (cost !== "") body.cost_per_ha = Number(cost);
        return body;
      };
      try {
        // With a custom price/cost, the "before" for the what-if deltas is
        // the original inputs at *that* price/cost, not the default one.
        const [result, base] = await Promise.all([
          whatIfYieldApi(bodyFor(inputs, irrigation), controller.signal),
          inputsChanged && economicsChanged
            ? whatIfYieldApi(bodyFor(initialInputs, initialIrrigation), controller.signal)
            : null,
        ]);
        setScenario({ result, base });
      } catch (err) {
        if (err.name !== "CanceledError" && err.name !== "AbortError") {
          console.error("What-if calculation failed:", err);
        }
      } finally {
        if (abortRef.current === controller) setLoading(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [inputs, irrigation, price, cost, inputsChanged, economicsChanged, initialInputs, initialIrrigation,
      prediction.scenario_context, prediction.irrigation_baseline, formData.irrigation]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const current = scenario?.result || prediction;
  const baseline = scenario?.base || prediction;

  return (
    <>
      <IncomeCard
        economics={current.economics}
        prediction={prediction}
        price={price}
        cost={cost}
        onPriceChange={setPrice}
        onCostChange={setCost}
        isScenario={inputsChanged}
      />
      <WhyBreakdown current={current} modelSource={prediction.model_source} />
      {prediction.scenario_context && (
        <WhatIfPanel
          inputs={inputs}
          baseline={baseline}
          current={current}
          loading={loading}
          changed={inputsChanged}
          onChange={(field, value) => setInputs((prev) => ({ ...prev, [field]: Number(value) }))}
          onReset={() => {
            setInputs(initialInputs);
            setIrrigation(initialIrrigation);
          }}
          irrigation={irrigation}
          onIrrigationChange={setIrrigation}
        />
      )}
      <CropComparison formData={formData} currentCrop={prediction.scenario_context?.crop || formData.crop} />
    </>
  );
}
