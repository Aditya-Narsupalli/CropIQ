"""
One-time cleaning pass for the Kisan Call Centre (KCC) archive dataset
before it's embedded into Upstash Vector for RAG.

Raw dataset: ~179k question/answer rows scraped from KCC call logs.
Run: python clean_kcc_dataset.py <path_to_raw_csv> <path_to_output_csv>

What this strips out and why:
  1. Rows with a missing answer - nothing to retrieve.
  2. Exact duplicate (question, answer) pairs, and near-duplicate questions -
     keeps only the most informative (longest) answer per unique question,
     since ~49% of rows in the raw file are duplicate questions and indexing
     all of them wastes vector storage for zero retrieval benefit.
  3. "Low-value" answers that are call-log placeholders rather than actual
     advice (e.g. "transfer to agri experts", "advised accordingly") - if
     retrieved, these would get paraphrased by the model as if they were
     real guidance, which is worse than no grounding at all.
  4. Answers containing phone-number-like digit sequences - these are
     overwhelmingly personal contact numbers of named individuals (KVK
     officers, VLE contacts), which is a privacy/PII concern to have sitting
     in a retrieval index, on top of being stale/regionally useless to most
     users years later.
  5. Adds a `crop` column (best-effort tag from question+answer text) so
     retrieval/eval can be filtered or sanity-checked by crop later.
"""
import re
import sys
import pandas as pd

LOW_VALUE_PATTERNS = [
    "transfer to", "advised accordingly", "guided accordingly", "suggested accordingly",
    "given details", "discussed", "informed accordingly", "clarified", "call back",
]

# Reuse the same crop list the chat agent already matches against, so tags
# are consistent between the live chat classifier and this offline corpus.
KNOWN_CROPS = [
    "rice", "wheat", "maize", "cotton", "sugarcane", "onion", "potato", "tomato",
    "soybean", "groundnut", "mustard", "gram", "chilli", "banana", "coconut",
    "tea", "jute", "tobacco", "turmeric", "ginger", "cabbage", "cauliflower",
    "brinjal", "okra", "pea", "lentil", "wheat", "barley", "sorghum", "millet",
    "mango", "papaya", "guava", "grape", "orange", "apple", "areca", "cardamom",
    "coffee", "rubber", "sunflower", "sesame", "castor",
]

PHONE_RE = re.compile(r'\d{6,}')


def tag_crop(text: str):
    lowered = str(text).lower()
    for crop in KNOWN_CROPS:
        if re.search(r'\b' + re.escape(crop) + r'\b', lowered):
            return crop
    return None


def clean(input_path: str, output_path: str):
    df = pd.read_csv(input_path)
    start = len(df)

    df["questions"] = df["questions"].astype(str).str.strip()
    df["answers"] = df["answers"].astype(str).str.strip()

    df = df[df["answers"].notna() & (df["answers"].str.lower() != "nan") & (df["answers"] != "")]
    after_missing = len(df)

    low_value_re = "|".join(re.escape(p) for p in LOW_VALUE_PATTERNS)
    df = df[~df["answers"].str.lower().str.contains(low_value_re, regex=True)]
    df = df[df["answers"].str.len() >= 15]
    after_lowvalue = len(df)

    df = df[~df["answers"].str.contains(PHONE_RE, regex=True)]
    after_pii = len(df)

    # Keep the most informative (longest) answer per unique question.
    df["_alen"] = df["answers"].str.len()
    df = df.sort_values("_alen", ascending=False).drop_duplicates(subset="questions", keep="first")
    df = df.drop(columns="_alen")
    after_dedup = len(df)

    df["crop"] = (df["questions"] + " " + df["answers"]).apply(tag_crop)

    df = df.reset_index(drop=True)
    df.to_csv(output_path, index=False)

    print(f"Raw rows:                 {start:,}")
    print(f"After dropping empty:     {after_missing:,}  (-{start - after_missing:,})")
    print(f"After low-value filter:   {after_lowvalue:,}  (-{after_missing - after_lowvalue:,})")
    print(f"After PII/phone filter:   {after_pii:,}  (-{after_lowvalue - after_pii:,})")
    print(f"After dedup by question:  {after_dedup:,}  (-{after_pii - after_dedup:,})")
    print(f"Tagged with a known crop: {df['crop'].notna().sum():,} ({df['crop'].notna().mean()*100:.1f}%)")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python clean_kcc_dataset.py <input_csv> <output_csv>")
        sys.exit(1)
    clean(sys.argv[1], sys.argv[2])
