"""
Trained crop-disease classifier (see app/models/train_disease_model.py).

Two parts, both run with onnxruntime/numpy - no PyTorch needed at runtime:
- Backbone: Meta's DINOv2-small (Apache 2.0), int8-quantized ONNX, turns a
  photo into a 768-number feature vector (CLS token + mean patch token).
- Head: a logistic-regression classifier trained on those features from
  real FIELD photos (Indian rice fields, PlantDoc field images, maize field
  images) - not lab photos, which is why an off-the-shelf PlantVillage model
  was rejected: it scored 0% on Indian rice field photos.

The farmer tells us the crop, so only that crop's diseases compete - this is
both more accurate and avoids answers like "potato blight" for a rice leaf.
Crops the model doesn't cover return None, and the caller relies on Gemini.
"""
import io
import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "disease")
BACKBONE_PATH = os.path.join(_DIR, "dinov2_small_int8.onnx")
HEAD_PATH = os.path.join(_DIR, "disease_head.json")

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# Disease Detector crop choices -> model crop names
CROP_ALIASES = {
    "rice": "Rice", "paddy": "Rice",
    "tomato": "Tomato",
    "potato": "Potato",
    "corn": "Maize", "maize": "Maize",
    "chili": "Chilli/Pepper", "chilli": "Chilli/Pepper", "pepper": "Chilli/Pepper", "capsicum": "Chilli/Pepper",
}

# Below this, the top answer isn't trusted on its own
MIN_CONFIDENCE = 0.6

_session = None
_head = None


def _load() -> bool:
    global _session, _head
    if _session is not None:
        return True
    try:
        import onnxruntime as ort
        # Keep memory low on a 512 MB server: no persistent memory arena or
        # pre-planned buffers between requests, and few threads.
        opts = ort.SessionOptions()
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        opts.intra_op_num_threads = 2
        _session = ort.InferenceSession(BACKBONE_PATH, sess_options=opts, providers=["CPUExecutionProvider"])
        with open(HEAD_PATH, encoding="utf-8") as f:
            head = json.load(f)
        _head = {
            "classes": head["classes"],
            "class_crop": np.array([c.split(":")[0] for c in head["classes"]]),
            "coef": np.array(head["coef"], dtype=np.float32),
            "intercept": np.array(head["intercept"], dtype=np.float32),
            "mean": np.array(head["scaler_mean"], dtype=np.float32),
            "scale": np.array(head["scaler_scale"], dtype=np.float32),
            "per_crop_cv": head.get("per_crop_cv", {}),
        }
        logger.info(f"Disease classifier loaded ({len(_head['classes'])} classes)")
        return True
    except Exception as e:
        logger.error(f"Disease classifier unavailable: {e}")
        _session = None
        return False


def model_crop(crop_type: str) -> Optional[str]:
    return CROP_ALIASES.get((crop_type or "").strip().lower())


def supported_crops() -> List[str]:
    return sorted(set(CROP_ALIASES.values()))


def _preprocess(image_bytes: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(image_bytes))
    # JPEGs decode straight to a reduced size (a 12 MP phone photo would
    # otherwise take ~36 MB as raw pixels) - the model only needs 224 px.
    img.draft("RGB", (512, 512))
    img = img.convert("RGB")
    w, h = img.size
    s = 256 / min(w, h)
    img = img.resize((max(224, round(w * s)), max(224, round(h * s))), Image.BICUBIC)
    w, h = img.size
    left, top = (w - 224) // 2, (h - 224) // 2
    img = img.crop((left, top, left + 224, top + 224))
    x = (np.asarray(img, dtype=np.float32) / 255.0 - _MEAN) / _STD
    return x.transpose(2, 0, 1)[None]


def classify(image_bytes: bytes, crop_type: str) -> Optional[Dict]:
    """Top diseases for this crop with probabilities, or None if the crop
    isn't covered or the model can't be loaded."""
    crop = model_crop(crop_type)
    if crop is None or not _load():
        return None
    stats = _head["per_crop_cv"].get(crop, {})
    if not stats.get("enabled"):
        # Not accurate enough on held-out field photos for this crop (see
        # train_disease_model.MIN_DEPLOY_ACCURACY) - leave it to Gemini.
        return None
    hidden = _session.run(None, {"pixel_values": _preprocess(image_bytes)})[0]
    features = np.concatenate([hidden[:, 0], hidden[:, 1:].mean(axis=1)], axis=1)[0]
    logits = _head["coef"] @ ((features - _head["mean"]) / _head["scale"]) + _head["intercept"]

    mask = _head["class_crop"] == crop
    if not mask.any():
        return None
    sub = logits[mask]
    probs = np.exp(sub - sub.max())
    probs /= probs.sum()
    names = np.array(_head["classes"])[mask]
    order = np.argsort(-probs)
    top = [{"disease": names[i].split(": ", 1)[1], "probability": round(float(probs[i]), 3)} for i in order[:3]]
    accuracy = stats.get("accuracy")
    return {
        "crop": crop,
        "disease": top[0]["disease"],
        "confidence": top[0]["probability"],
        "confident": top[0]["probability"] >= MIN_CONFIDENCE,
        "top_predictions": top,
        "model_accuracy": accuracy,
        "possible_diseases": [n.split(": ", 1)[1] for n in names],
    }
