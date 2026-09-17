"""
One-time ingestion of the cleaned KCC Q&A archive into Upstash Vector.

Prerequisite: create a Vector index in the Upstash console FIRST, with a
built-in embedding model attached (Upstash Console -> Vector -> Create
Index -> pick "Embedding Model" instead of "Custom" -> e.g.
mxbai-embed-large-v1). That's what lets this script upsert raw text
directly and let Upstash embed it, instead of you needing a separate
embedding API/key.

Run:
    UPSTASH_VECTOR_REST_URL=... UPSTASH_VECTOR_REST_TOKEN=... \
    python ingest_kcc_to_upstash.py <path_to_cleaned_csv>

Safe to re-run: each row's id is a stable hash of the question text, so
re-running after adding more cleaned rows will only upsert new/changed
ones rather than duplicating everything.
"""
import hashlib
import os
import sys
import time

import pandas as pd
from upstash_vector import Index
from upstash_vector.types import Data

BATCH_SIZE = 100


def row_id(question: str) -> str:
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:24]


def ingest(csv_path: str):
    url = os.getenv("UPSTASH_VECTOR_REST_URL")
    token = os.getenv("UPSTASH_VECTOR_REST_TOKEN")
    if not url or not token:
        print("Set UPSTASH_VECTOR_REST_URL and UPSTASH_VECTOR_REST_TOKEN first.")
        sys.exit(1)

    index = Index(url=url, token=token)
    df = pd.read_csv(csv_path)
    df = df.dropna(subset=["questions", "answers"])
    total = len(df)
    print(f"Ingesting {total:,} rows in batches of {BATCH_SIZE}...")

    batch = []
    done = 0
    for _, row in df.iterrows():
        question = str(row["questions"]).strip()
        answer = str(row["answers"]).strip()
        crop = row.get("crop")
        metadata = {"answer": answer}
        if isinstance(crop, str) and crop:
            metadata["crop"] = crop

        # `data=question` is what gets embedded by Upstash's built-in model
        # AND is what comes back in query results as `.data` - the answer
        # itself lives in metadata since we retrieve by question similarity,
        # not by answer similarity.
        batch.append(Data(id=row_id(question), data=question, metadata=metadata))

        if len(batch) >= BATCH_SIZE:
            index.upsert(vectors=batch)
            done += len(batch)
            print(f"  {done:,}/{total:,}", end="\r")
            batch = []
            time.sleep(0.05)  # gentle on rate limits for a one-time bulk job

    if batch:
        index.upsert(vectors=batch)
        done += len(batch)

    print(f"\nDone. Upserted {done:,} rows.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python ingest_kcc_to_upstash.py <cleaned_csv_path>")
        sys.exit(1)
    ingest(sys.argv[1])
