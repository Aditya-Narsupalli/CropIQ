"""
Search India's Kisan Call Centre (KCC) archive - ~86k real farmer questions
and expert answers, indexed in Upstash Vector (see data/KCC_RAG_SETUP.md).

Shared by the chat assistant and disease detection. Optional: if Upstash
Vector isn't configured, every search returns [] and callers carry on.

The archive is historical (circa 2015-2021) and logged from specific places,
so callers must present its dosages as unverified and tell farmers to
confirm locally.
"""
import logging
import re
from typing import Dict, List, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

try:
    from upstash_vector import Index as _UpstashIndex
except Exception:  # pragma: no cover - library may be missing
    _UpstashIndex = None

_index = None
_init_done = False

DEFAULT_MIN_SCORE = 0.80


def _get_index():
    global _index, _init_done
    if _init_done:
        return _index
    _init_done = True
    settings = get_settings()
    if _UpstashIndex and settings.UPSTASH_VECTOR_REST_URL and settings.UPSTASH_VECTOR_REST_TOKEN:
        try:
            _index = _UpstashIndex(url=settings.UPSTASH_VECTOR_REST_URL, token=settings.UPSTASH_VECTOR_REST_TOKEN)
        except Exception as e:
            logger.error(f"Error initializing Upstash Vector index: {e}")
    else:
        logger.info("Upstash Vector not configured; KCC archive search disabled")
    return _index


def search(query: str, top_k: int = 3, min_score: float = DEFAULT_MIN_SCORE) -> List[Dict]:
    """Past KCC Q&A pairs similar to `query`: [{question, answer, crop, score}]."""
    index = _get_index()
    if not index or not query:
        return []
    try:
        results = index.query(data=query, top_k=top_k, include_metadata=True, include_data=True)
    except Exception as e:
        logger.warning(f"KCC archive lookup failed, skipping: {e}")
        return []
    out = []
    for r in results or []:
        meta = r.metadata or {}
        if r.score is None or r.score < min_score or not r.data or not meta.get("answer"):
            continue
        out.append({"question": r.data, "answer": meta["answer"], "crop": meta.get("crop"),
                    "score": round(float(r.score), 2)})
    return out


# Words a past question must contain to count as the same disease. Vector
# similarity alone mixes up diseases ("blast in paddy" also retrieves
# "bacterial blight in paddy" at 0.89), so matches are also checked by name.
DISEASE_KEYWORDS = {
    "Bacterial leaf blight": ["bacterial blight", "bacterial leaf blight", "blb"],
    "Blast": ["blast"],
    "Brown spot": ["brown spot"],
    "Tungro": ["tungro"],
    "Sheath blight": ["sheath blight"],
    "Early blight": ["early blight"],
    "Late blight": ["late blight"],
    "Septoria leaf spot": ["septoria", "leaf spot"],
    "Bacterial spot": ["bacterial spot", "bacterial leaf spot"],
    "Bacterial leaf spot": ["bacterial spot", "bacterial leaf spot", "leaf spot"],
    "Mosaic virus": ["mosaic"],
    "Yellow leaf curl virus": ["leaf curl"],
    "Leaf mold": ["leaf mold", "leaf mould"],
    "Spider mites": ["mite"],
    "Common rust": ["rust"],
    "Northern leaf blight": ["leaf blight", "turcicum"],
    "Southern leaf blight": ["leaf blight", "maydis"],
    "Gray leaf spot": ["gray leaf spot", "grey leaf spot", "leaf spot"],
    "Curvularia leaf spot": ["curvularia", "leaf spot"],
    "Black rot": ["black rot"],
    "Scab": ["scab"],
    "Rust": ["rust"],
    "Powdery mildew": ["powdery mildew"],
}

# How farmers and KCC operators usually name the crop
CROP_WORDS = {
    "Rice": ["paddy", "rice", "dhan"],
    "Maize": ["maize", "corn"],
    "Chilli/Pepper": ["chilli", "chili", "pepper", "capsicum"],
}


def _mostly_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isascii() for c in letters) / len(letters) > 0.8


def _disease_keywords(disease: str) -> List[str]:
    """Keywords for a disease name - a known class, or free text from Gemini
    such as "Late Blight (Phytophthora infestans)"."""
    if disease in DISEASE_KEYWORDS:
        return DISEASE_KEYWORDS[disease]
    text = re.sub(r"\(.*?\)", " ", disease.lower())
    found = [k for kws in DISEASE_KEYWORDS.values() for k in kws if re.search(r"\b" + re.escape(k) + r"\b", text)]
    if found:
        return sorted(set(found), key=len, reverse=True)
    words = [w for w in re.findall(r"[a-z]+", text) if w not in ("disease", "infection", "of", "the", "and", "leaf")]
    return [" ".join(words)] if words else []


def disease_references(crop: str, disease: str, limit: int = 3) -> List[Dict]:
    """KCC expert answers about this exact crop + disease (English only)."""
    if not disease or disease.strip().lower() in ("healthy", "unclear", "none", "unknown"):
        return []
    crop_words = CROP_WORDS.get(crop, [crop.lower()])
    keywords = _disease_keywords(disease)
    if not keywords:
        return []
    clean_name = re.sub(r"\(.*?\)", "", disease).strip().lower()
    query = f"control of {clean_name} in {crop_words[0]}"
    matches = []
    for r in search(query, top_k=10):
        q = r["question"].lower()
        if not any(re.search(rf"\b{re.escape(k)}", q) for k in keywords):
            continue  # different disease
        if not (any(w in q for w in crop_words) or (r.get("crop") or "").lower() in crop_words):
            continue  # different crop
        if not _mostly_english(r["answer"]):
            continue
        matches.append(r)
        if len(matches) >= limit:
            break
    return matches


def reference_block(references: List[Dict]) -> str:
    """Prompt text for an LLM: the KCC answers plus how to treat them."""
    if not references:
        return ""
    lines = [
        "[REFERENCE: past answers from India's Kisan Call Centre farmer helpline archive - real expert "
        "practice, but historical (not verified current) and logged from a specific place. Use them to "
        "ground your treatment advice. Treat dosages, chemical names and amounts as unverified - describe "
        "the approach and tell the farmer to confirm the exact product and dose with their local Krishi "
        "Vigyan Kendra or agriculture officer.]"
    ]
    for i, r in enumerate(references, 1):
        lines.append(f'{i}. Past Q: "{r["question"]}" -> Past A: "{r["answer"]}"')
    return "\n".join(lines)
