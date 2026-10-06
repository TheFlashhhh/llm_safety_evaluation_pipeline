import argparse

import pandas as pd

from repo_utils import RUNS_DIR, check_output_path, resolve

parser = argparse.ArgumentParser(description="Merge two raw response CSVs into one table.")
parser.add_argument("--base", default=RUNS_DIR / "raw_responses_gemini.csv")
parser.add_argument("--new", default=RUNS_DIR / "raw_responses_llama.csv")
parser.add_argument("--out", default=RUNS_DIR / "responses_merged.csv")
parser.add_argument("--overwrite", action="store_true")
args = parser.parse_args()

OUT = check_output_path(args.out, args.overwrite)

# Load existing and new
base = pd.read_csv(resolve(args.base))
new = pd.read_csv(resolve(args.new))

# Inspect columns to map them if needed
print("BASE columns:", base.columns.tolist())
print("NEW columns:", new.columns.tolist())


# Ensure all required columns exist in NEW (add empty ones if missing)
for col in base.columns:
    if col not in new.columns:
        new[col] = None

# Restrict NEW to the same column order as BASE
new = new[base.columns]

# Define composite key to prevent duplicates
key_cols = ["indicator_id", "convo_id", "turn_index", "model_name", "seed"]

# If NEW is missing any key columns, that's a schema problem; fail fast
missing_keys = [c for c in key_cols if c not in new.columns]
if missing_keys:
    raise ValueError(f"NEW is missing key columns: {missing_keys}")

# Drop any NEW rows whose key already exists in BASE
base_keys = set(
    tuple(x) for x in base[key_cols].astype(str).itertuples(index=False, name=None)
)
mask = []
for row in new[key_cols].astype(str).itertuples(index=False, name=None):
    mask.append(tuple(row) not in base_keys)
new = new[mask]

print(f"Appending {len(new)} new rows to {len(base)} existing rows.")

merged = pd.concat([base, new], ignore_index=True)
merged.to_csv(OUT, index=False)
print(f"Saved {OUT}")
