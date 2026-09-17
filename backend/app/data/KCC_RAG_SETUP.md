# KCC Archive RAG Setup

Grounds the chat assistant's general farming-advice answers in ~86k cleaned
Kisan Call Centre expert Q&A pairs, retrieved from Upstash Vector.

This is **optional**. If the two env vars below are unset, the chat agent logs
`Upstash Vector not configured` and answers exactly as it did before.

## 1. Create the Upstash Vector index

In the Upstash console: **Vector → Create Index**.

- Choose **Embedding Model** (not "Custom") and pick `mxbai-embed-large-v1`.
  This matters: it lets the app upsert and query with raw text and have
  Upstash do the embedding, so you don't need a separate embedding API or key.
- Note that Upstash **Vector** is a different product from Upstash **Redis**
  (already used for the daily price snapshot). You need both; they have
  separate URLs and tokens.

Copy the index's REST URL and token.

## 2. Set env vars

Locally (`.env`) and on Render (**Environment** tab):

```
UPSTASH_VECTOR_REST_URL=https://your-index.upstash.io
UPSTASH_VECTOR_REST_TOKEN=your_token
```

## 3. Ingest the data

`kcc_cleaned.csv` in this folder is already cleaned and ready. Run once, from
your own machine (not Render — this is a one-time bulk job):

```bash
pip install upstash-vector pandas
UPSTASH_VECTOR_REST_URL=... UPSTASH_VECTOR_REST_TOKEN=... \
  python ingest_kcc_to_upstash.py kcc_cleaned.csv
```

Takes a while for ~86k rows. Safe to re-run — ids are a stable hash of the
question text, so a re-run upserts rather than duplicates.

**Check your Upstash plan limits before running.** The free tier caps vector
count and monthly request volume; 86k rows plus daily query traffic may exceed
it. If so, either upgrade or cut the corpus down (e.g. keep only rows where
`crop` is non-null — that's ~35k rows and covers the crop questions users
actually ask most).

## 4. Regenerating the cleaned CSV (optional)

If you want to re-clean from the raw Kaggle archive:

```bash
python clean_kcc_dataset.py questionsv4.csv kcc_cleaned.csv
```

What the cleaning pass removes, from 178,939 raw rows down to 86,346:

| Step | Removed | Why |
|---|---|---|
| Empty answers | 124 | Nothing to retrieve |
| Call-log placeholders | 4,536 | `"advised accordingly"`, `"transfer to agri experts"` etc. — if retrieved, the model would paraphrase these as if they were real advice |
| Phone numbers / contacts | 2,339 | Personal mobile numbers of named KVK/VLE officers — a privacy problem to put in a retrieval index, and stale/regionally useless anyway |
| Duplicate questions | 85,594 | ~49% of the raw file; keeps the longest (most informative) answer per unique question |

Also adds a best-effort `crop` tag (40.9% of rows match a known crop).

## Known limitations

- **Coverage is uneven across India.** Kisan Call Centre is a national scheme,
  but this particular extract is not a uniform national sample. Measured across
  all 178,939 raw rows: 21,207 mention Assam-specific markers (state name,
  districts, AAU Jorhat, local units like `bigha`, local varieties like `sali`),
  while every other state combined accounts for 568. Most rows name no state at
  all, but among those that do, roughly 97% are Assam.

  This doesn't make the data useless — pest biology and most agronomy travel
  fine, and a lot of the corpus is region-neutral. But sowing windows, varietal
  recommendations, and local-supplier advice may not fit a user elsewhere. The
  `[REFERENCE]` block therefore tells the model not to assume the advice applies
  to the user's area, and to prefer live search when the two conflict. That's a
  mitigation, not a fix. If you later get data from other states, appending it
  to the index would genuinely improve this.
- **The data is old** (roughly 2015–2021). Pesticide formulations get
  restricted and reformulated; scheme amounts change every budget. Retrieval
  makes old advice *available*, not *current*. This is why the block is
  labeled `[REFERENCE]` rather than `[LIVE DATA]`.
- **The 0.80 score threshold in `_get_kcc_reference_context` is a guess.** It
  was never calibrated against live traffic. Watch what actually gets retrieved
  after launch and tune it — too low and you inject irrelevant noise, too high
  and the archive never fires.
