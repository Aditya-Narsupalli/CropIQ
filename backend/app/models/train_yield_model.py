"""
Trains an XGBoost regression model to predict crop yield (tonnes/hectare)
from State, District, Crop and Season.

Data source: Crop_Wise_Area_Production_Yield_Filtered_Data.csv
(government-style crop-wise area/production/yield records, 2021-22 & 2022-23)

Run with:
    cd backend && python -m app.models.train_yield_model

Outputs (saved to backend/app/models/):
    yield_xgb_model.json  - trained XGBRegressor (native XGBoost format)
    yield_model_meta.pkl  - category vocabularies, lookup tables, metrics

NOTE: This is intentionally a *separate* model/file pair from model.pkl /
model_meta.pkl, which belong to the microfarm ROI model. Do not overwrite those.

Feature choices:
  - "Area" is NOT a feature. In the source data it is the *district's* total
    cropped area for that crop (often thousands of hectares), whereas at
    inference time the only area we have is the farmer's own field size.
    Feeding one in place of the other is meaningless, so area is used only to
    turn yield into total production.
  - "Crop Type" is dropped: it is fully determined by Crop Name, so it adds
    no information and only splits feature importance.
  - "Year" is dropped: the data covers two seasons only, and at inference time
    the current year is always outside that range.
  - Categoricals use XGBoost's native categorical support instead of
    LabelEncoder integers, so the model doesn't see a fake ordering
    (e.g. "Adilabad" < "Agra").
  - District is often unknown at inference time. Training rows are duplicated
    with District set to missing, so the model learns a sensible
    state-level estimate for that case instead of guessing a district.
"""
import os
import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import mean_absolute_error, r2_score
from xgboost import XGBRegressor

# --- Paths ---
script_dir = os.path.dirname(os.path.abspath(__file__))   # app/models
app_dir = os.path.dirname(script_dir)                      # app
data_dir = os.path.join(app_dir, "data")
models_dir = script_dir

DATA_PATH = os.path.join(data_dir, "yield_training_data.csv")
MODEL_PATH = os.path.join(models_dir, "yield_xgb_model.json")
META_PATH = os.path.join(models_dir, "yield_model_meta.pkl")

CAT_COLS = ["State Name", "District Name", "Crop Name", "Season"]
FEATURES = CAT_COLS

# Quantiles of the per-row error ratio (actual / predicted) used to turn a
# point prediction into a likely range at inference time.
RANGE_QUANTILES = (0.1, 0.9)


def load_and_clean_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    # Column headers look like "Year (year)" -> normalize to "Year"
    df.columns = [c.split(" (")[0].strip() for c in df.columns]

    # Drop aggregated "Total" season rows - they double-count Kharif+Rabi+Summer
    # for the same crop/state/year and would leak duplicated signal into training.
    df = df[df["Season"] != "Total"].copy()

    # Drop rows with zero/invalid yield or area - not usable as training signal
    df = df[(df["Yield"] > 0) & (df["Area"] > 0)].copy()

    # Coconut yield in this dataset is reported in nuts/hectare (values up to
    # 37,000+), not tonnes/hectare like every other crop - a well-known unit
    # convention in Indian agri statistics. Left in, it would dominate the
    # loss and distort predictions for every other crop. Excluded here;
    # served via the CROP_COEFFICIENTS fallback instead (see
    # yield_prediction_service.py).
    df = df[df["Crop Name"] != "Coconut"].copy()

    df["YearStart"] = df["Year"].str.slice(0, 4).astype(int)

    # Winsorize extreme per-crop yield outliers (data entry/unit artifacts)
    # so a handful of bad rows don't distort the loss for that crop.
    lo = df.groupby("Crop Name")["Yield"].transform(lambda s: s.quantile(0.01))
    hi = df.groupby("Crop Name")["Yield"].transform(lambda s: s.quantile(0.99))
    df["Yield"] = df["Yield"].clip(lower=lo, upper=hi)

    return df.reset_index(drop=True)


def build_features(df: pd.DataFrame, categories: dict) -> pd.DataFrame:
    """Cast categoricals to pandas Categorical with a fixed vocabulary.
    Values outside the vocabulary (or None) become missing, which XGBoost
    routes down the learned "unknown" branch."""
    X = pd.DataFrame(index=df.index)
    for col in CAT_COLS:
        X[col] = pd.Categorical(df[col], categories=categories[col])
    return X


def with_unknown_district(df: pd.DataFrame) -> pd.DataFrame:
    """Return df plus a copy of it with District blanked out."""
    blank = df.copy()
    blank["District Name"] = None
    return pd.concat([df, blank], ignore_index=True)


def make_model() -> XGBRegressor:
    return XGBRegressor(
        n_estimators=600,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        random_state=42,
        objective="reg:squarederror",
        tree_method="hist",
        enable_categorical=True,
        max_cat_to_onehot=1,
    )


def fit(df: pd.DataFrame, categories: dict) -> XGBRegressor:
    train = with_unknown_district(df)
    model = make_model()
    model.fit(build_features(train, categories), np.log1p(train["Yield"].astype(float)), verbose=False)
    return model


def evaluate(name: str, model: XGBRegressor, df: pd.DataFrame, categories: dict, blank_district: bool) -> dict:
    """Score on the original tonnes/ha scale. Besides R2/MAE (which are
    dominated by high-tonnage crops like sugarcane), report the median
    absolute percentage error, which treats every crop on the same footing."""
    eval_df = df.copy()
    if blank_district:
        eval_df["District Name"] = None
    pred = np.expm1(model.predict(build_features(eval_df, categories)))
    true = eval_df["Yield"].to_numpy()
    ape = np.abs(pred - true) / true
    result = {
        "r2": float(r2_score(true, pred)),
        "mae": float(mean_absolute_error(true, pred)),
        "median_ape": float(np.median(ape)),
        "n": int(len(eval_df)),
    }
    print(f"[{name}] R2={result['r2']:.3f}  MAE={result['mae']:.3f} t/ha  "
          f"median abs % error={result['median_ape'] * 100:.1f}%  (n={result['n']})")
    return result, pred, true


def per_crop_report(df: pd.DataFrame, pred: np.ndarray, true: np.ndarray) -> dict:
    tmp = pd.DataFrame({"crop": df["Crop Name"].to_numpy(), "ape": np.abs(pred - true) / true})
    report = tmp.groupby("crop")["ape"].agg(["median", "count"]).sort_values("count", ascending=False)
    print("Per-crop median abs % error (top 15 by row count):")
    for crop, row in report.head(15).iterrows():
        print(f"  {crop:<22} {row['median'] * 100:5.1f}%  (n={int(row['count'])})")
    return report["median"].to_dict()


def main():
    print(f"Loading training data from {DATA_PATH}")
    df = load_and_clean_data()
    print(f"Rows after cleaning: {len(df)}")

    categories = {col: sorted(df[col].astype(str).unique().tolist()) for col in CAT_COLS}

    # --- Honest evaluation ---
    # 1) Known district, future year: train on 2021-22, test on 2022-23.
    #    This is the realistic case when the farmer's district is matched.
    train_y1 = df[df["YearStart"] == df["YearStart"].min()]
    test_y2 = df[df["YearStart"] == df["YearStart"].max()]
    model_y = fit(train_y1, categories)
    metrics_year, pred_y, true_y = evaluate("next-year, known district", model_y, test_y2, categories, blank_district=False)

    # 2) Unseen district: hold out 20% of districts entirely and predict them
    #    with District unknown. This is the fallback case when the district
    #    can't be matched, and checks we aren't just memorising districts.
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    tr_idx, va_idx = next(gss.split(df, groups=df["District Name"]))
    model_d = fit(df.iloc[tr_idx], categories)
    va = df.iloc[va_idx]
    metrics_district, pred_d, true_d = evaluate("unseen district", model_d, va, categories, blank_district=True)
    per_crop = per_crop_report(va, pred_d, true_d)

    # Likely-range multipliers from out-of-sample error ratios. The
    # unseen-district split is the more pessimistic of the two, so ranges
    # are calibrated for the case where we know less.
    ratio_known = true_y / pred_y
    ratio_unknown = true_d / pred_d
    range_multipliers = {
        "known_district": [float(np.quantile(ratio_known, q)) for q in RANGE_QUANTILES],
        "unknown_district": [float(np.quantile(ratio_unknown, q)) for q in RANGE_QUANTILES],
    }
    print(f"80% range multipliers: {range_multipliers}")

    # --- Final model on all data ---
    print("Training final model on all rows...")
    model = fit(df, categories)
    model.save_model(MODEL_PATH)
    print(f"Model saved to {MODEL_PATH}")

    feature_importance = dict(zip(FEATURES, model.feature_importances_.tolist()))
    print("Feature importance:", feature_importance)

    # Lookup tables used at inference time.
    season_counts = (df.groupby(["Crop Name", "State Name", "Season"]).size()
                     .reset_index(name="n").sort_values("n", ascending=False))
    crop_state_seasons = {
        (c, s): grp["Season"].tolist()
        for (c, s), grp in season_counts.groupby(["Crop Name", "State Name"], sort=False)
    }
    crop_seasons = (df.groupby(["Crop Name", "Season"]).size().reset_index(name="n")
                    .sort_values("n", ascending=False).groupby("Crop Name")["Season"].apply(list).to_dict())
    state_districts = df.groupby("State Name")["District Name"].apply(lambda s: sorted(s.unique())).to_dict()

    # Historical medians for "how does my estimate compare" context.
    district_median = df.groupby(["Crop Name", "State Name", "District Name", "Season"])["Yield"].median().to_dict()
    state_median = df.groupby(["Crop Name", "State Name", "Season"])["Yield"].median().to_dict()

    import xgboost
    meta = {
        "version": 2,
        "features": FEATURES,
        "categories": categories,
        "target": "Yield (tonnes/hectare, log1p-transformed during training)",
        "valid_crops": categories["Crop Name"],
        "valid_states": categories["State Name"],
        "valid_seasons": categories["Season"],
        "state_districts": state_districts,
        "crop_state_seasons": crop_state_seasons,
        "crop_seasons": crop_seasons,
        "district_median": district_median,
        "state_median": state_median,
        "range_multipliers": range_multipliers,
        "metrics": {
            # "r2" kept as the headline number shown in the UI: next-year,
            # known-district R2 (out-of-time, not a random split).
            "r2": metrics_year["r2"],
            "next_year": metrics_year,
            "unseen_district": metrics_district,
            "per_crop_median_ape": per_crop,
            "n_train": int(len(df)),
        },
        "feature_importance": feature_importance,
        "xgboost_version": xgboost.__version__,
    }
    joblib.dump(meta, META_PATH)
    print(f"Metadata saved to {META_PATH}")


if __name__ == "__main__":
    main()
