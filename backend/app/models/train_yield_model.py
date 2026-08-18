"""
Trains an XGBoost regression model to predict crop yield (tonnes/hectare)
from State, District, Crop, Crop Type, Season, Area and Year.

Data source: Crop_Wise_Area_Production_Yield_Filtered_Data.csv
(government-style crop-wise area/production/yield records, 2021-22 & 2022-23)

Run with:
    cd backend && python -m app.models.train_yield_model

Outputs (saved to backend/app/models/):
    yield_xgb_model.pkl   - trained XGBRegressor
    yield_model_meta.pkl  - encoders, feature list, valid categories, metrics

NOTE: This is intentionally a *separate* model/file pair from model.pkl /
model_meta.pkl, which belong to the microfarm ROI model. Do not overwrite those.
"""
import os
import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error, r2_score
try:
    from sklearn.metrics import root_mean_squared_error
except ImportError:  # older sklearn
    from sklearn.metrics import mean_squared_error
    def root_mean_squared_error(y_true, y_pred):
        return mean_squared_error(y_true, y_pred) ** 0.5
from xgboost import XGBRegressor

# --- Paths ---
script_dir = os.path.dirname(os.path.abspath(__file__))   # app/models
app_dir = os.path.dirname(script_dir)                      # app
data_dir = os.path.join(app_dir, "data")
models_dir = script_dir

DATA_PATH = os.path.join(data_dir, "yield_training_data.csv")
MODEL_PATH = os.path.join(models_dir, "yield_xgb_model.json")
META_PATH = os.path.join(models_dir, "yield_model_meta.pkl")


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
    # squared-error loss and distort predictions for every other crop.
    # Excluded here; served via the CROP_COEFFICIENTS fallback instead (see
    # yield_prediction_service.py).
    df = df[df["Crop Name"] != "Coconut"].copy()

    # Extract a numeric start year from "2021-2022" style strings
    df["YearStart"] = df["Year"].str.slice(0, 4).astype(int)

    # Winsorize extreme per-crop yield outliers (data entry/unit artifacts,
    # e.g. Coconut yield reported in nuts/ha rather than tonnes/ha) so a
    # handful of bad rows don't distort the loss for that crop.
    lo = df.groupby("Crop Name")["Yield"].transform(lambda s: s.quantile(0.01))
    hi = df.groupby("Crop Name")["Yield"].transform(lambda s: s.quantile(0.99))
    df["Yield"] = df["Yield"].clip(lower=lo, upper=hi)

    return df


def build_features(df: pd.DataFrame, encoders: dict = None, fit: bool = True):
    """Label-encode categoricals. If encoders is provided, reuse them (inference)."""
    cat_cols = ["State Name", "District Name", "Crop Name", "Crop Type", "Season"]
    encoders = encoders or {}

    X = pd.DataFrame(index=df.index)
    for col in cat_cols:
        if fit:
            le = LabelEncoder()
            X[col] = le.fit_transform(df[col].astype(str))
            encoders[col] = le
        else:
            le = encoders[col]
            # Map unseen categories to a reserved "unknown" bucket (-1 -> 0 after shift)
            known = set(le.classes_)
            mapped = df[col].astype(str).apply(lambda v: v if v in known else le.classes_[0])
            X[col] = le.transform(mapped)

    X["Area"] = df["Area"].astype(float)
    X["YearStart"] = df["YearStart"].astype(int)

    return X, encoders


def main():
    print(f"Loading training data from {DATA_PATH}")
    df = load_and_clean_data()
    print(f"Rows after cleaning: {len(df)}")

    X, encoders = build_features(df, fit=True)
    # log1p-transform the (right-skewed) target for a more stable fit;
    # invert with expm1 at inference time.
    y = np.log1p(df["Yield"].astype(float))

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)

    print("Training XGBoost yield model...")
    model = XGBRegressor(
        n_estimators=400,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        objective="reg:squarederror",
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    # --- Evaluate on original (non-log) yield scale ---
    val_pred = np.expm1(model.predict(X_val))
    val_true = np.expm1(y_val)
    mae = mean_absolute_error(val_true, val_pred)
    rmse = root_mean_squared_error(val_true, val_pred)
    r2 = r2_score(val_true, val_pred)
    print(f"Validation MAE:  {mae:.3f} tonnes/hectare")
    print(f"Validation RMSE: {rmse:.3f} tonnes/hectare")
    print(f"Validation R2:   {r2:.4f}")

    feature_importance = dict(zip(X.columns, model.feature_importances_.tolist()))
    print("Feature importance:", feature_importance)

    joblib.dump(model, MODEL_PATH.replace(".json", "_joblib_backup.pkl"))  # optional local backup, not shipped
    # Native XGBoost format (JSON) instead of pickling the whole estimator:
    # it's the format-stable, cross-version-safe way to persist a booster
    # (see https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html),
    # and being plain text it also survives zip/git transfer far more
    # reliably than a binary joblib pickle does.
    model.save_model(MODEL_PATH)
    print(f"Model saved to {MODEL_PATH}")

    import xgboost
    meta = {
        "features": list(X.columns),
        "target": "Yield (tonnes/hectare, log1p-transformed during training)",
        "encoders": encoders,
        "valid_crops": sorted(df["Crop Name"].unique().tolist()),
        "valid_states": sorted(df["State Name"].unique().tolist()),
        "valid_seasons": sorted(df["Season"].unique().tolist()),
        "crop_to_type": df.drop_duplicates("Crop Name").set_index("Crop Name")["Crop Type"].to_dict(),
        "state_avg_area": df.groupby("State Name")["Area"].median().to_dict(),
        "metrics": {"mae": mae, "rmse": rmse, "r2": r2, "n_train": len(X_train), "n_val": len(X_val)},
        "feature_importance": feature_importance,
        "xgboost_version": xgboost.__version__,
    }
    joblib.dump(meta, META_PATH)
    print(f"Metadata saved to {META_PATH}")


if __name__ == "__main__":
    main()
