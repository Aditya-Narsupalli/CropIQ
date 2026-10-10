"""
Trains CropIQ's crop-disease classifier on real field photos.

Run (downloads ~1.9 GB of public datasets into --cache, then trains on CPU):
    cd backend && python -m app.models.train_disease_model --cache /path/to/cache

Outputs (app/models/disease/):
    dinov2_small_int8.onnx  - feature extractor (copied from --cache on first run)
    disease_head.json       - trained classifier + evaluation metrics

Approach: transfer learning. Meta's DINOv2-small (Apache 2.0) turns each
photo into a 768-number feature vector (CLS token + mean patch token); a
logistic-regression classifier learns the diseases from those features.
Trains in minutes on a CPU and runs at inference with onnxruntime + numpy.

Why not an off-the-shelf PlantVillage model: those are trained on lab
photos (one leaf, plain background). Tested here on Indian rice FIELD photos
one scored 0% - it called every rice leaf "potato". Everything below is
trained and tested on field photos.

Datasets (all CC BY 4.0):
- Indian rice field photos: Project-AgML/rice_leaf_disease_classification_india
- Rice field photos (second source): Project-AgML/rice_leaf_disease_classification_2
- PlantDoc field photos (tomato, potato, maize, pepper, ...): agyaatcoder/PlantDoc
  (Singh et al. 2020, "PlantDoc: A Dataset for Visual Plant Disease Detection")
- Maize field photos: Project-AgML/corn_leaf_disease_classification
Backbone: onnx-community/dinov2-small (int8 ONNX of facebook/dinov2-small, Apache 2.0)

Evaluation is deliberately strict:
- near-duplicate photos (cosine similarity > 0.97) are grouped so copies
  never sit on both sides of a train/test split;
- rice is tested across the two independent rice datasets (new farms,
  cameras and photographers);
- PlantDoc's official test split is used as-is.
"""
import argparse
import io
import json
import os
import shutil
import urllib.request
from collections import Counter

import numpy as np
import pandas as pd
from PIL import Image

HF = "https://huggingface.co"
FILES = {
    "dino_int8.onnx": f"{HF}/onnx-community/dinov2-small/resolve/main/onnx/model_int8.onnx",
    "rice_india.parquet": f"{HF}/datasets/Project-AgML/rice_leaf_disease_classification_india/resolve/main/data/train-00000-of-00001.parquet",
    "rice2_0.parquet": f"{HF}/datasets/Project-AgML/rice_leaf_disease_classification_2/resolve/main/data/train-00000-of-00002.parquet",
    "rice2_1.parquet": f"{HF}/datasets/Project-AgML/rice_leaf_disease_classification_2/resolve/main/data/train-00001-of-00002.parquet",
    "plantdoc_train0.parquet": f"{HF}/datasets/agyaatcoder/PlantDoc/resolve/main/data/train-00000-of-00002.parquet",
    "plantdoc_train1.parquet": f"{HF}/datasets/agyaatcoder/PlantDoc/resolve/main/data/train-00001-of-00002.parquet",
    "plantdoc_test.parquet": f"{HF}/datasets/agyaatcoder/PlantDoc/resolve/main/data/test-00000-of-00001.parquet",
    "corn_agml.parquet": f"{HF}/datasets/Project-AgML/corn_leaf_disease_classification/resolve/main/data/train-00000-of-00001.parquet",
}

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "disease")

# A crop's diagnosis is only shown when its accuracy in the strictest
# held-out test reaches this. Below it, the app relies on Gemini instead.
MIN_DEPLOY_ACCURACY = 0.75

RICE_INDIA = {0: "Rice: Bacterial leaf blight", 1: "Rice: Blast", 2: "Rice: Brown spot", 3: "Rice: Tungro"}
RICE2 = {0: "Rice: Bacterial leaf blight", 1: "Rice: Brown spot", 2: "Rice: Blast"}
CORN = {0: "Maize: Southern leaf blight", 1: "Maize: Common rust", 2: "Maize: Curvularia leaf spot",
        3: "Maize: Northern leaf blight", 5: "Maize: Sheath blight"}  # 4 "Own-Spot" is ambiguous - skipped
PLANTDOC = {
    "Tomato Early blight leaf": "Tomato: Early blight", "Tomato Septoria leaf spot": "Tomato: Septoria leaf spot",
    "Tomato leaf": "Tomato: Healthy", "Tomato leaf bacterial spot": "Tomato: Bacterial spot",
    "Tomato leaf late blight": "Tomato: Late blight", "Tomato leaf mosaic virus": "Tomato: Mosaic virus",
    "Tomato leaf yellow virus": "Tomato: Yellow leaf curl virus", "Tomato mold leaf": "Tomato: Leaf mold",
    "Tomato two spotted spider mites leaf": "Tomato: Spider mites",
    "Potato leaf early blight": "Potato: Early blight", "Potato leaf late blight": "Potato: Late blight",
    "Corn Gray leaf spot": "Maize: Gray leaf spot", "Corn leaf blight": "Maize: Northern leaf blight",
    "Corn rust leaf": "Maize: Common rust",
    "Bell_pepper leaf": "Chilli/Pepper: Healthy", "Bell_pepper leaf spot": "Chilli/Pepper: Bacterial leaf spot",
    "Soyabean leaf": "Soyabean: Healthy",
    "grape leaf": "Grape: Healthy", "grape leaf black rot": "Grape: Black rot",
    "Apple leaf": "Apple: Healthy", "Apple Scab Leaf": "Apple: Scab", "Apple rust leaf": "Apple: Rust",
    "Squash Powdery mildew leaf": "Squash: Powdery mildew", "Strawberry leaf": "Strawberry: Healthy",
    "Peach leaf": "Peach: Healthy", "Cherry leaf": "Cherry: Healthy",
    "Raspberry leaf": "Raspberry: Healthy", "Blueberry leaf": "Blueberry: Healthy",
}


def download(cache: str) -> None:
    os.makedirs(cache, exist_ok=True)
    for name, url in FILES.items():
        path = os.path.join(cache, name)
        if not os.path.exists(path):
            print(f"Downloading {name} ...")
            urllib.request.urlretrieve(url, path)


def load_samples(cache: str):
    """(jpeg bytes, label, source, official split) for every training photo."""
    p = lambda name: os.path.join(cache, name)
    samples = []
    for _, r in pd.read_parquet(p("rice_india.parquet")).iterrows():
        samples.append((r["image"]["bytes"], RICE_INDIA[int(r["label"])], "rice_india", ""))
    for f in ("rice2_0.parquet", "rice2_1.parquet"):
        for _, r in pd.read_parquet(p(f)).iterrows():
            samples.append((r["image"]["bytes"], RICE2[int(r["label"])], "rice2", ""))
    for _, r in pd.read_parquet(p("corn_agml.parquet")).iterrows():
        if int(r["label"]) in CORN:
            samples.append((r["image"]["bytes"], CORN[int(r["label"])], "corn_agml", ""))
    for f, split in (("plantdoc_train0.parquet", "train"), ("plantdoc_train1.parquet", "train"),
                     ("plantdoc_test.parquet", "test")):
        for _, r in pd.read_parquet(p(f)).iterrows():
            cats = list(r["objects"]["category"])
            cat = Counter(cats).most_common(1)[0][0]
            if cat not in PLANTDOC:
                continue
            # Crop to the largest box of the main class - what a farmer photographs close up
            boxes = [b for b, c in zip(r["objects"]["bbox"], cats) if c == cat]
            x, y, w, h = max(boxes, key=lambda b: b[2] * b[3])
            img = Image.open(io.BytesIO(r["image"]["bytes"])).convert("RGB")
            if w > 32 and h > 32:
                img = img.crop((x, y, x + w, y + h))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=92)
            samples.append((buf.getvalue(), PLANTDOC[cat], "plantdoc", split))
    return samples


def extract_features(samples, backbone: str) -> np.ndarray:
    import onnxruntime as ort
    from app.services import disease_classifier as dc

    sess = ort.InferenceSession(backbone, providers=["CPUExecutionProvider"])
    feats = []
    for i in range(0, len(samples), 16):
        batch = np.concatenate([dc._preprocess(s[0]) for s in samples[i:i + 16]])
        h = sess.run(None, {"pixel_values": batch})[0]
        feats.append(np.concatenate([h[:, 0], h[:, 1:].mean(axis=1)], axis=1))
        if i % 1600 == 0:
            print(f"  features {i}/{len(samples)}", flush=True)
    return np.concatenate(feats).astype(np.float32)


def near_duplicate_groups(X, source, threshold=0.97):
    """Union-find over same-source pairs with cosine similarity > threshold."""
    parent = np.arange(len(X))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    Xn = X / np.linalg.norm(X, axis=1, keepdims=True)
    for src in np.unique(source):
        idx = np.where(source == src)[0]
        for start in range(0, len(idx), 1000):
            block = idx[start:start + 1000]
            sims = Xn[block] @ Xn[idx].T
            for bi, row in zip(block, sims):
                for j in idx[np.where(row > threshold)[0]]:
                    a, b = find(bi), find(j)
                    if a != b:
                        parent[a] = b
    return np.array([find(i) for i in range(len(X))])


def fit(Xtr, ytr, C=0.5):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(Xtr)
    clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced")
    clf.fit(scaler.transform(Xtr), ytr)
    return scaler, clf


def predict_within_crop(scaler, clf, Xte, crops):
    """The farmer tells us the crop, so only that crop's classes compete."""
    logits = clf.decision_function(scaler.transform(Xte))
    class_crop = np.array([c.split(":")[0] for c in clf.classes_])
    preds, confs = [], []
    for row, cr in zip(logits, crops):
        mask = class_crop == cr
        sub = row[mask]
        p = np.exp(sub - sub.max())
        p /= p.sum()
        k = int(p.argmax())
        preds.append(clf.classes_[mask][k])
        confs.append(float(p[k]))
    return np.array(preds), np.array(confs)


def summary(name, ytrue, ypred, conf):
    acc = float(np.mean(ytrue == ypred))
    line = f"{name}: n={len(ytrue)} accuracy {acc:.1%}"
    for th in (0.6, 0.8):
        m = conf >= th
        if m.any():
            line += f" | conf>={th}: {m.mean():.0%} of photos at {np.mean(ytrue[m] == ypred[m]):.1%}"
    print(line)
    return acc


def train_and_evaluate(X, y, source, split):
    from sklearn.model_selection import StratifiedGroupKFold

    crop = np.array([label.split(":")[0] for label in y])
    groups = near_duplicate_groups(X, source)
    print(f"{len(X)} photos in {len(np.unique(groups))} near-duplicate groups, {len(set(y))} classes")
    results = {}
    strictest = {}  # crop -> accuracy in its strictest held-out test

    # 1) Rice across independent datasets
    for train_src, test_src in (("rice_india", "rice2"), ("rice2", "rice_india")):
        tr = (crop != "Rice") | (source == train_src)
        te = (source == test_src) & np.isin(y, np.unique(y[tr]))
        sc, clf = fit(X[tr], y[tr])
        p, c = predict_within_crop(sc, clf, X[te], crop[te])
        results[f"rice_train_{train_src}_test_{test_src}"] = acc = summary(
            f"Rice: trained on {train_src}, tested on {test_src}", y[te], p, c)
        strictest["Rice"] = min(strictest.get("Rice", 1.0), acc)

    # 2) PlantDoc official test split
    tr = ~((source == "plantdoc") & (split == "test"))
    te = (source == "plantdoc") & (split == "test")
    sc, clf = fit(X[tr], y[tr])
    p, c = predict_within_crop(sc, clf, X[te], crop[te])
    results["plantdoc_official_test"] = summary("PlantDoc official test split", y[te], p, c)
    for cr in np.unique(crop[te]):
        m = crop[te] == cr
        if m.sum() >= 15:
            strictest[cr] = summary(f"   {cr}", y[te][m], p[m], c[m])

    # 3) Grouped 5-fold cross-validation over everything
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=0)
    allp, allc = np.empty(len(y), dtype=object), np.zeros(len(y))
    for tr_i, te_i in cv.split(X, y, groups):
        sc, clf = fit(X[tr_i], y[tr_i])
        allp[te_i], allc[te_i] = predict_within_crop(sc, clf, X[te_i], crop[te_i])
    allp = allp.astype(str)
    results["grouped_cv"] = summary("5-fold grouped cross-validation", y, allp, allc)
    per_crop = {}
    for cr in np.unique(crop):
        m = crop == cr
        if m.sum() >= 30:
            cv_acc = float(np.mean(y[m] == allp[m]))
            # Conservative: the worse of grouped CV and the crop's strictest test
            acc = min(cv_acc, strictest.get(cr, cv_acc))
            per_crop[cr] = {"n": int(m.sum()), "accuracy": round(acc, 3), "grouped_cv": round(cv_acc, 3),
                            "enabled": acc >= MIN_DEPLOY_ACCURACY}
            print(f"   {cr:14} n={m.sum():5} cv {cv_acc:.1%}  conservative {acc:.1%}  "
                  f"{'ENABLED' if acc >= MIN_DEPLOY_ACCURACY else 'off (Gemini)'}")
    return results, per_crop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True, help="folder for downloaded datasets (~1.9 GB)")
    args = ap.parse_args()

    download(args.cache)
    os.makedirs(OUT_DIR, exist_ok=True)
    backbone = os.path.join(OUT_DIR, "dinov2_small_int8.onnx")
    if not os.path.exists(backbone):
        shutil.copy(os.path.join(args.cache, "dino_int8.onnx"), backbone)

    samples = load_samples(args.cache)
    print(len(samples), "photos:", dict(Counter(s[2] for s in samples)))
    X = extract_features(samples, backbone)
    y = np.array([s[1] for s in samples])
    source = np.array([s[2] for s in samples])
    split = np.array([s[3] for s in samples])

    results, per_crop = train_and_evaluate(X, y, source, split)
    sc, clf = fit(X, y)
    model = {
        "classes": clf.classes_.tolist(),
        "coef": clf.coef_.astype(np.float32).round(6).tolist(),
        "intercept": clf.intercept_.astype(np.float32).round(6).tolist(),
        "scaler_mean": sc.mean_.astype(np.float32).round(6).tolist(),
        "scaler_scale": sc.scale_.astype(np.float32).round(6).tolist(),
        "metrics": {k: round(v, 3) for k, v in results.items()},
        "per_crop_cv": per_crop,
        "n_train": int(len(y)),
        "sources": "Rice India + rice set 2 (Project-AgML), PlantDoc, maize (Project-AgML) - all CC BY 4.0",
    }
    with open(os.path.join(OUT_DIR, "disease_head.json"), "w", encoding="utf-8") as f:
        json.dump(model, f)
    print("Saved", os.path.join(OUT_DIR, "disease_head.json"))


if __name__ == "__main__":
    main()
