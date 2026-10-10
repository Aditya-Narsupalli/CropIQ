import React, { useEffect, useMemo, useState } from "react";
import {
  FaArrowUp, FaArrowDown, FaExclamationTriangle, FaCalculator, FaStar, FaBell, FaTrash, FaChartLine,
} from "react-icons/fa";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { getMarketInsightsApi, getMarketTrendsApi } from "../../services/api";

const inr = (v) => (v == null ? "–" : `₹${Math.round(v).toLocaleString("en-IN")}`);

const inrLarge = (v) => {
  if (v == null) return "–";
  if (Math.abs(v) >= 1e5) return `₹${(v / 1e5).toFixed(2)} lakh`;
  return inr(v);
};

/** Today's biggest movers and crops selling below MSP. Clicking a crop opens its trend. */
export function MarketInsightsPanel({ onSelectCrop }) {
  const [insights, setInsights] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getMarketInsightsApi()
      .then(setInsights)
      .catch((err) => {
        console.error("Market insights failed:", err);
        setFailed(true);
      });
  }, []);

  if (failed || !insights) return null;

  const CropButton = ({ crop, children }) => (
    <button
      type="button"
      onClick={() => onSelectCrop(crop)}
      className="w-full flex justify-between items-center text-left text-sm py-1.5 px-2 rounded hover:bg-white/70"
    >
      {children}
    </button>
  );

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
      <div className="bg-green-50 border border-green-100 rounded-lg p-4">
        <h4 className="font-semibold text-green-800 text-sm mb-2 flex items-center">
          <FaArrowUp className="mr-2" /> Biggest gains (latest day)
        </h4>
        {insights.gainers.length === 0 && <p className="text-xs text-gray-500">No price rises in the latest data.</p>}
        {insights.gainers.map((g) => (
          <CropButton key={g.crop} crop={g.crop}>
            <span className="text-gray-800 truncate mr-2">{g.crop}</span>
            <span className="text-green-700 font-semibold whitespace-nowrap">+{g.change_pct}%</span>
          </CropButton>
        ))}
      </div>

      <div className="bg-red-50 border border-red-100 rounded-lg p-4">
        <h4 className="font-semibold text-red-800 text-sm mb-2 flex items-center">
          <FaArrowDown className="mr-2" /> Biggest falls (latest day)
        </h4>
        {insights.losers.length === 0 && <p className="text-xs text-gray-500">No price falls in the latest data.</p>}
        {insights.losers.map((l) => (
          <CropButton key={l.crop} crop={l.crop}>
            <span className="text-gray-800 truncate mr-2">{l.crop}</span>
            <span className="text-red-600 font-semibold whitespace-nowrap">{l.change_pct}%</span>
          </CropButton>
        ))}
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
        <h4 className="font-semibold text-amber-900 text-sm mb-1 flex items-center">
          <FaExclamationTriangle className="mr-2" /> Selling below MSP
        </h4>
        <p className="text-[11px] text-amber-800 mb-2">
          Market price is under the government support price. Check whether procurement is open near you.
        </p>
        {insights.below_msp.length === 0 && (
          <p className="text-xs text-gray-500">Every tracked crop is at or above its MSP.</p>
        )}
        <div className="max-h-40 overflow-y-auto">
          {insights.below_msp.map((m) => (
            <CropButton key={m.crop} crop={m.crop}>
              <span className="text-gray-800 truncate mr-2">{m.crop}</span>
              <span className="text-amber-800 font-semibold whitespace-nowrap">{m.gap_pct}%</span>
            </CropButton>
          ))}
        </div>
      </div>
      <p className="md:col-span-3 text-[11px] text-gray-500 -mt-2">
        {insights.source}
        {insights.date ? `, ${insights.date}` : ""}. Click a crop to see its trend.
      </p>
    </div>
  );
}

/** Where today's price sits in its real recorded range, with MSP marked. */
export function PriceRangeBar({ signal, msp }) {
  if (signal?.recorded_low == null || signal.recorded_high <= signal.recorded_low) return null;
  const { recorded_low: low, recorded_high: high, latest_price: latest } = signal;
  const pos = (v) => `${Math.min(100, Math.max(0, ((v - low) / (high - low)) * 100))}%`;

  return (
    <div className="mt-3">
      <div className="flex justify-between text-[11px] text-gray-500 mb-1">
        <span>Low {inr(low)}</span>
        <span>High {inr(high)}</span>
      </div>
      <div className="relative h-2 bg-gradient-to-r from-red-200 via-yellow-200 to-green-200 rounded-full">
        {msp && msp >= low && msp <= high && (
          <div
            className="absolute -top-1 -bottom-1 w-0.5 bg-amber-700"
            style={{ left: pos(msp) }}
            title={`MSP ${inr(msp)}`}
          />
        )}
        <div
          className="absolute -top-1 w-4 h-4 -ml-2 rounded-full bg-blue-600 border-2 border-white shadow"
          style={{ left: pos(latest) }}
          title={`Latest ${inr(latest)}`}
        />
      </div>
      <p className="text-[11px] text-gray-600 mt-1.5">
        Latest price {inr(latest)} is at {signal.range_position}% of its recorded range ({signal.period}
        {msp ? `; MSP ${inr(msp)}` : ""}). Typical daily move: {signal.volatility_pct}%.
      </p>
    </div>
  );
}

/** "What is my harvest worth?" at today's price, MSP, and the recorded high/low. */
export function HarvestValueCalculator({ crop, currentPrice, msp, signal }) {
  const [quintals, setQuintals] = useState("");
  const qty = Number.parseFloat(quintals);
  if (!currentPrice) return null;

  const rows = [
    ["At today's price", currentPrice],
    msp ? ["At MSP", msp] : null,
    signal?.recorded_high ? ["At the recorded high", signal.recorded_high] : null,
    signal?.recorded_low ? ["At the recorded low", signal.recorded_low] : null,
  ].filter(Boolean);

  return (
    <div className="mt-4 pt-4 border-t border-blue-200">
      <h5 className="font-semibold text-blue-700 text-sm mb-2 flex items-center">
        <FaCalculator className="mr-2" /> What is my {crop} worth?
      </h5>
      <label className="text-xs text-gray-600 flex items-center gap-2">
        Quantity
        <input
          type="number"
          min="0"
          step="0.5"
          value={quintals}
          onChange={(e) => setQuintals(e.target.value)}
          placeholder="e.g. 20"
          className="w-24 p-1.5 border border-gray-300 rounded text-sm"
        />
        quintals
      </label>
      {qty > 0 && (
        <table className="w-full mt-3 text-sm">
          <tbody>
            {rows.map(([label, price]) => (
              <tr key={label} className="border-b border-blue-100 last:border-0">
                <td className="py-1.5 text-gray-600">{label}</td>
                <td className="py-1.5 text-gray-500 text-xs">{inr(price)}/qtl</td>
                <td className="py-1.5 text-right font-semibold text-gray-900">{inrLarge(qty * price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="text-[11px] text-gray-500 mt-2">
        All-India averages; your local mandi price, quality grade and transport costs will change the actual amount.
      </p>
    </div>
  );
}


// --- Watchlist ---------------------------------------------------------------

const WATCHLIST_KEY = "cropiq.market.watchlist";

const loadWatchlist = () => {
  try {
    return JSON.parse(localStorage.getItem(WATCHLIST_KEY)) || [];
  } catch {
    return [];
  }
};

const saveWatchlist = (list) => {
  try {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(list));
  } catch {
    /* storage unavailable (private mode) - watchlist just won't persist */
  }
};

/**
 * "My crops": the crops a farmer cares about, pinned with today's price and
 * an optional target ("tell me when wheat is above ₹2,700"). Saved in this
 * browser; alerts show whenever the page is opened and the target is met.
 */
export function WatchlistPanel({ marketData, onSelectCrop }) {
  const [list, setList] = useState(loadWatchlist);
  const [crop, setCrop] = useState("");
  const [target, setTarget] = useState("");
  const [direction, setDirection] = useState("above");

  const byCrop = useMemo(() => Object.fromEntries(marketData.map((m) => [m.crop, m])), [marketData]);
  const crops = useMemo(() => marketData.filter((m) => m.price_per_quintal).map((m) => m.crop).sort(), [marketData]);

  const update = (next) => {
    setList(next);
    saveWatchlist(next);
  };

  const add = (e) => {
    e.preventDefault();
    if (!crop) return;
    const entry = { crop, target: target ? Number(target) : null, direction };
    update([...list.filter((w) => w.crop !== crop), entry]);
    setCrop("");
    setTarget("");
  };

  const reached = (w) => {
    const price = byCrop[w.crop]?.price_per_quintal;
    if (!price || !w.target) return false;
    return w.direction === "above" ? price >= w.target : price <= w.target;
  };
  const alerts = list.filter(reached);

  return (
    <div className="bg-sky-50 border border-sky-100 rounded-lg p-4 mb-6">
      <h4 className="font-semibold text-sky-900 text-sm mb-3 flex items-center">
        <FaStar className="mr-2 text-amber-500" /> My crops
      </h4>

      {alerts.length > 0 && (
        <div className="mb-3 bg-amber-100 border border-amber-300 rounded p-2 text-sm text-amber-900">
          <FaBell className="inline mr-2" />
          {alerts.map((w) => `${w.crop} is ${w.direction} your target of ${inr(w.target)}`).join(" · ")}
        </div>
      )}

      {list.length === 0 ? (
        <p className="text-xs text-gray-600 mb-3">
          Add the crops you grow or sell to see their price here first, with an alert when they reach your target.
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mb-3">
          {list.map((w) => {
            const m = byCrop[w.crop];
            const change = m?.price_change_pct;
            const hit = reached(w);
            return (
              <div key={w.crop} className={`bg-white rounded border p-2 text-sm ${hit ? "border-amber-400" : "border-sky-100"}`}>
                <div className="flex justify-between items-start gap-2">
                  <button
                    type="button"
                    className="text-left font-medium text-gray-800 hover:text-green-700 truncate"
                    onClick={() => onSelectCrop(w.crop)}
                  >
                    {w.crop}
                  </button>
                  <button
                    type="button"
                    aria-label={`Remove ${w.crop}`}
                    className="text-gray-300 hover:text-red-500"
                    onClick={() => update(list.filter((x) => x.crop !== w.crop))}
                  >
                    <FaTrash className="text-xs" />
                  </button>
                </div>
                <div className="flex justify-between items-baseline">
                  <span className="font-semibold">
                    {m?.price_per_quintal ? `${inr(m.price_per_quintal)}/qtl` : "No price today"}
                  </span>
                  {change != null && (
                    <span className={`text-xs ${change > 0 ? "text-green-600" : change < 0 ? "text-red-600" : "text-gray-500"}`}>
                      {change > 0 ? "+" : ""}
                      {change}%
                    </span>
                  )}
                </div>
                {w.target && (
                  <p className={`text-[11px] ${hit ? "text-amber-700 font-semibold" : "text-gray-500"}`}>
                    {hit ? "Target reached: " : "Target: "}
                    {w.direction} {inr(w.target)}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      <form onSubmit={add} className="flex flex-wrap items-center gap-2 text-xs">
        <select
          value={crop}
          onChange={(e) => setCrop(e.target.value)}
          className="border border-gray-300 rounded p-1.5 bg-white"
          aria-label="Crop to watch"
        >
          <option value="">Add a crop…</option>
          {crops.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <span className="text-gray-600">alert when</span>
        <select
          value={direction}
          onChange={(e) => setDirection(e.target.value)}
          className="border border-gray-300 rounded p-1.5 bg-white"
          aria-label="Alert direction"
        >
          <option value="above">above</option>
          <option value="below">below</option>
        </select>
        <input
          type="number"
          min="0"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="₹ per quintal (optional)"
          aria-label="Target price"
          className="w-40 border border-gray-300 rounded p-1.5"
        />
        <button type="submit" disabled={!crop} className="px-3 py-1.5 rounded bg-sky-600 text-white disabled:opacity-40">
          Add
        </button>
      </form>
    </div>
  );
}

// --- Compare crops chart -----------------------------------------------------

const COMPARE_COLORS = ["#2563eb", "#d97706", "#059669"];

/** Price change (%) of up to 3 crops over the same real recorded days. */
export function PriceComparisonChart({ marketData }) {
  const crops = useMemo(() => marketData.filter((m) => m.price_per_quintal).map((m) => m.crop).sort(), [marketData]);
  const [selected, setSelected] = useState([]);
  const [series, setSeries] = useState({});

  useEffect(() => {
    selected
      .filter((c) => !series[c])
      .forEach((c) => {
        getMarketTrendsApi(c)
          .then((d) => setSeries((prev) => ({ ...prev, [c]: d.historical_data || [] })))
          .catch(() => setSeries((prev) => ({ ...prev, [c]: [] })));
      });
  }, [selected, series]);

  // Rows keyed by date; each crop as % change from its first price in the window
  const rows = useMemo(() => {
    const byDate = {};
    selected.forEach((c) => {
      const hist = series[c] || [];
      const base = hist[0]?.price;
      if (!base) return;
      hist.forEach((h) => {
        byDate[h.date] = {
          ...(byDate[h.date] || { date: h.date }),
          [c]: Math.round(((h.price - base) / base) * 1000) / 10,
        };
      });
    });
    return Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date));
  }, [selected, series]);

  const toggle = (c) =>
    setSelected((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : prev.length < 3 ? [...prev, c] : prev));

  return (
    <div className="bg-white p-6 rounded-lg shadow-sm border border-amber-100 mt-8">
      <h3 className="font-semibold text-lg text-gray-800 mb-1 flex items-center">
        <FaChartLine className="mr-2 text-green-500" /> Compare crops
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        Pick up to 3 crops to see which has gained or lost the most over the recorded period (% change).
      </p>
      <div className="flex flex-wrap gap-2 mb-4">
        {crops.map((c) => {
          const idx = selected.indexOf(c);
          return (
            <button
              key={c}
              type="button"
              onClick={() => toggle(c)}
              disabled={idx === -1 && selected.length >= 3}
              className={`px-2.5 py-1 rounded-full text-xs border transition-colors disabled:opacity-40 ${
                idx >= 0 ? "text-white" : "bg-white text-gray-700 border-gray-200 hover:bg-gray-50"
              }`}
              style={idx >= 0 ? { backgroundColor: COMPARE_COLORS[idx], borderColor: COMPARE_COLORS[idx] } : undefined}
            >
              {c}
            </button>
          );
        })}
      </div>
      {selected.length > 0 && rows.length > 1 && (
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" fontSize={10} tickFormatter={(d) => d.slice(5)} />
              <YAxis fontSize={10} tickFormatter={(v) => `${v}%`} />
              <Tooltip formatter={(v, name) => [`${v > 0 ? "+" : ""}${v}%`, name]} />
              <Legend />
              {selected.map((c, i) => (
                <Line key={c} type="monotone" dataKey={c} stroke={COMPARE_COLORS[i]} dot={false} connectNulls strokeWidth={2} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
