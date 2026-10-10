"""
Learns how yield responds to fertilizer use, rainfall and irrigation, from
ICRISAT's District Level Database (560 districts, 20 states, 1990-2015).

Run with:
    cd backend && python -m app.models.train_agronomy_effects

Input:  app/data/icrisat_district_level.csv  (subset of the source, see below)
Output: app/models/agronomy_effects.json     (used by app/services/agronomy.py)

Source data, both from ICRISAT's District Level Database and licensed CC BY 4.0
(only the columns used here are kept in the CSV):
- Fertilizer, irrigation, rainfall and 5 crops' yields: "ICRISAT District-Level
  Data: Heterogeneous Climate Effect on Crop Yield and Associated Risks to
  Water Security in India", Mendeley Data, V1, doi:10.17632/ywp3y5j9vv.1
- Yields of further crops (wheat, maize, sorghum, finger millet, pigeonpea,
  cotton, soyabean, sunflower, safflower): Bowden, C. (2022) "District-Level
  Dataset cleaned", figshare, doi:10.6084/m9.figshare.19615764.v2
  Joined on ICRISAT's district code and year.

Method - two-way fixed effects, per crop:
    ln(yield) = district effect + year effect
                + b_f * ln(fertilizer + 10)
                + b_r1 * rain + b_r2 * rain^2
                + b_i * irrigated share
Comparing each district with itself across years removes everything fixed
about a district (soil, skill, market access) - so richer districts that both
use more fertilizer and get better yields don't inflate the fertilizer
effect. Year effects remove nationwide shocks and technology trends.

Caveats (also surfaced to users):
- Fertilizer is the district's total N+P+K use per hectare of gross cropped
  area, not per crop - an approximation for a single field's dose, and noisy
  measures bias effects toward zero, so these are conservative.
- Rainfall is the district's annual total, matching the app's input.
- Crops are only given measured effects with enough data (MIN_OBSERVATIONS,
  MIN_DISTRICTS); crops without district yield data (potato, onion,
  nigerseed, tobacco) keep the ICAR rule-based adjustments.
"""
import json
import os

import numpy as np
import pandas as pd

script_dir = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(os.path.dirname(script_dir), "data", "icrisat_district_level.csv")
OUT_PATH = os.path.join(script_dir, "agronomy_effects.json")

# ICRISAT crop -> app crop label
CROPS = {"RICE": "Rice", "PEARL MILLET": "Bajra", "CHICKPEA": "Gram", "GROUNDNUT": "Groundnut", "SUGARCANE": "Sugarcane"}
# Further crops, from the figshare yield file
EXTRA_CROPS = {"WHEAT": "Wheat", "MAIZE": "Maize", "SORGHUM": "Jowar", "FINGER MILLET": "Ragi",
               "PIGEONPEA": "Tur", "COTTON": "Cotton", "SOYABEAN": "Soyabean", "SUNFLOWER": "Sunflower",
               "SAFFLOWER": "Safflower"}
ALL_CROPS = {**CROPS, **EXTRA_CROPS}
MIN_YEARS_PER_DISTRICT = 8
MIN_OBSERVATIONS = 500
MIN_DISTRICTS = 40

# Effects known to be confounded in this data, used only as rules instead.
# Bt cotton spread across districts unevenly in 2002-2010, raising yields and
# input use together; year effects can't absorb district-varying adoption, so
# the measured fertilizer effect for cotton (~0.26) is inflated.
EXCLUDED = {"Cotton": {"fertilizer": "confounded with Bt cotton adoption (2002-2010)"}}
BOOTSTRAP_REPS = 60

MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
          "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]


def build_csv_from_source(xls_path: str, figshare_csv_path: str) -> None:
    """One-off: extract the columns this script needs from the two sources."""
    src = pd.read_excel(xls_path)
    keep = ["Dist Code", "Year", "State Name", "Dist Name", "GROSS CROPPED AREA (1000 ha)",
            "TOTAL FERTILISER CONSUMPTION (tons)", "GROSS IRRIGATED AREA (1000 ha)"]
    keep += [f"{c} {k}" for c in CROPS for k in ("AREA (1000 ha)", "YIELD (Kg per ha)")]
    out = src[keep].copy()
    out["ANNUAL RAINFALL (mm)"] = sum(src[f"{m} PERCIPITATION (Millimeters)"] for m in MONTHS).round(1)

    # Further crops' yields: figshare uses the same district codes, with
    # dotted column names ("WHEAT.YIELD..Kg.per.ha.")
    fig = pd.read_csv(figshare_csv_path)
    extra = {"Dist.Code": "Dist Code", "Year": "Year", "Dist.Name": "fig_dist_name"}
    for c in EXTRA_CROPS:
        dotted = c.replace(" ", ".")
        extra[f"{dotted}.AREA..1000.ha."] = f"{c} AREA (1000 ha)"
        extra[f"{dotted}.YIELD..Kg.per.ha."] = f"{c} YIELD (Kg per ha)"
    fig = fig[list(extra)].rename(columns=extra)
    out = out.merge(fig, on=["Dist Code", "Year"], how="left")
    # Keep the joined values only where the district names agree, guarding
    # against code reuse after district splits
    mismatch = out["fig_dist_name"].notna() & (out["fig_dist_name"].str.lower() != out["Dist Name"].str.lower())
    out.loc[mismatch, [col for col in extra.values() if col not in ("Dist Code", "Year")]] = np.nan
    out.drop(columns="fig_dist_name").to_csv(DATA_PATH, index=False)


def load() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    gca = df["GROSS CROPPED AREA (1000 ha)"]
    # tons / 1000 ha = kg/ha
    df["fert"] = (df["TOTAL FERTILISER CONSUMPTION (tons)"] / gca).where(gca > 0)
    df["irr"] = (df["GROSS IRRIGATED AREA (1000 ha)"] / gca).where(gca > 0).clip(0, 1)
    df["rain"] = df["ANNUAL RAINFALL (mm)"]
    return df


def _demean(frame: pd.DataFrame, cols, groups, iters: int = 50) -> pd.DataFrame:
    """Two-way fixed effects by alternating projections."""
    out = frame[cols].astype(float).copy()
    for _ in range(iters):
        for g in groups:
            out = out - out.groupby(frame[g]).transform("mean")
    return out


def _fit(sub: pd.DataFrame) -> dict:
    sub = sub.assign(
        ly=np.log(sub["y"]), lf=np.log(sub["fert"] + 10),
        r=sub["rain"] / 1000, r2=(sub["rain"] / 1000) ** 2,
    )
    X = ["lf", "r", "r2", "irr"]
    d = _demean(sub, ["ly"] + X, ["Dist Code", "Year"])
    beta, *_ = np.linalg.lstsq(d[X].values, d["ly"].values, rcond=None)
    return dict(zip(X, beta.tolist()))


def main():
    df = load()
    effects = {}
    for icrisat_name, label in ALL_CROPS.items():
        y, a = df[f"{icrisat_name} YIELD (Kg per ha)"], df[f"{icrisat_name} AREA (1000 ha)"]
        sub = df.assign(y=y)[(y > 0) & (a > 1)].dropna(subset=["fert", "irr", "rain"])
        sub = sub[(sub["fert"] > 0) & (sub["fert"] < 600) & (sub["rain"] > 0)]
        sub = sub[sub.groupby("Dist Code")["Year"].transform("count") >= MIN_YEARS_PER_DISTRICT]
        if len(sub) < MIN_OBSERVATIONS or sub["Dist Code"].nunique() < MIN_DISTRICTS:
            print(f"{label:10} skipped - not enough data ({len(sub)} rows, {sub['Dist Code'].nunique()} districts)")
            continue

        point = _fit(sub)
        # District-level bootstrap for uncertainty (years within a district are correlated)
        rng = np.random.default_rng(0)
        dists = sub["Dist Code"].unique()
        by_dist = {d: g for d, g in sub.groupby("Dist Code")}
        boots = []
        for _ in range(BOOTSTRAP_REPS):
            pick = rng.choice(dists, size=len(dists), replace=True)
            boots.append(_fit(pd.concat([by_dist[d].assign(**{"Dist Code": i}) for i, d in enumerate(pick)])))
        b = pd.DataFrame(boots)

        def ci(k):
            return [round(float(b[k].quantile(0.05)), 4), round(float(b[k].quantile(0.95)), 4)]

        # Rainfall: effect of a dry (10th percentile) vs wet (90th) year
        r_lo, r_hi = sub["rain"].quantile(0.1) / 1000, sub["rain"].quantile(0.9) / 1000
        rain_swing = b["r"] * (r_hi - r_lo) + b["r2"] * (r_hi ** 2 - r_lo ** 2)
        rain_ci = [float(rain_swing.quantile(0.05)), float(rain_swing.quantile(0.95))]

        # Quality gate per factor: use a measured effect only when its 90% CI
        # excludes zero and the direction is agronomically plausible (more
        # fertilizer or irrigation doesn't lower yield). Otherwise the app
        # falls back to the ICAR rule for that factor.
        fert_ci, irr_ci = ci("lf"), ci("irr")
        use = {
            "fertilizer": fert_ci[0] > 0,
            "irrigation": irr_ci[0] > 0,
            "rainfall": rain_ci[0] > 0 or rain_ci[1] < 0,
        }
        reasons = {}
        for factor, reason in EXCLUDED.get(label, {}).items():
            use[factor] = False
            reasons[factor] = reason
        for factor, ok in use.items():
            if not ok and factor not in reasons:
                reasons[factor] = "effect not clearly measurable in this data"

        effects[label] = {
            "fertilizer_elasticity": round(point["lf"], 4),
            "fertilizer_elasticity_90ci": ci("lf"),
            "rain_linear": round(point["r"], 4),
            "rain_quadratic": round(point["r2"], 4),
            # Rain effect is only trusted within the range actually observed
            "rain_range_mm": [round(float(sub["rain"].quantile(0.05))), round(float(sub["rain"].quantile(0.95)))],
            "irrigation_coef": round(point["irr"], 4),
            "irrigation_coef_90ci": ci("irr"),
            "rain_dry_vs_wet_log_effect_90ci": [round(v, 4) for v in rain_ci],
            "use": use,
            "not_used_because": reasons,
            "n_observations": int(len(sub)),
            "n_districts": int(len(dists)),
            "years": [int(sub["Year"].min()), int(sub["Year"].max())],
        }
        e = effects[label]
        print(f"{label:10} n={e['n_observations']:5} districts={e['n_districts']:3}  "
              f"fert elasticity {e['fertilizer_elasticity']:+.3f} {e['fertilizer_elasticity_90ci']}  "
              f"irrigation {e['irrigation_coef']:+.2f} {e['irrigation_coef_90ci']}  "
              f"using: {[f for f, ok in use.items() if ok]}")

    # Typical irrigated share per state - the baseline the ML estimate
    # implicitly assumes, so a farmer's own irrigation is compared to it.
    # Latest 10 years with data; exact zeros are missing records in this
    # source (e.g. West Bengal reports none), not unirrigated states.
    reported = df[(df["irr"] > 0) & (df["Year"] >= df["Year"].max() - 9)]
    state_irr = reported.groupby("State Name")["irr"].median().round(3).dropna().to_dict()
    renames = {"Orissa": "Odisha"}

    out = {
        "source": "ICRISAT District Level Database via Mendeley Data doi:10.17632/ywp3y5j9vv.1 (CC BY 4.0)",
        "method": "Two-way fixed effects (district, year) per crop; 90% CIs from district bootstrap",
        "crops": effects,
        "state_irrigated_share": {renames.get(k.title(), k.title()): v for k, v in state_irr.items()},
        # Fallback for states not in the source
        "national_irrigated_share": round(float(reported["irr"].median()), 3),
        # Normal annual rainfall per state (median district-year), so a
        # farmer's rainfall is judged against what's normal where they are
        "state_normal_rainfall_mm": {
            renames.get(k.title(), k.title()): round(v)
            for k, v in df[df["rain"] > 0].groupby("State Name")["rain"].median().dropna().items()
        },
        "national_normal_rainfall_mm": round(float(df.loc[df["rain"] > 0, "rain"].median())),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Saved {OUT_PATH}")


if __name__ == "__main__":
    main()
