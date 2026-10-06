# scripts/combine_scores.py

import argparse
import csv

from repo_utils import RUNS_DIR, check_output_path, resolve

COMBINED_HEADER = [
    "indicator_id",
    "convo_id",
    "model_name",
    "seed",
    "turn_index",
    "difficulty",
    "hij_rater_id",
    "hij_score",
    "llm_aiescore",
    "llm_judge_status",
]

def main():
    parser = argparse.ArgumentParser(description="Join human ratings with LLM-judge scores.")
    parser.add_argument("--hij", default=RUNS_DIR / "hij_scores.csv")
    parser.add_argument("--llm", default=RUNS_DIR / "llm_scores.csv")
    parser.add_argument("--out", default=RUNS_DIR / "combined_scores.csv")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    out_path = check_output_path(args.out, args.overwrite)

    # Judge files from scripts/aie_llm_scoring.py have one row per response
    # (with turn_index). The historical scores/llm_scores.csv has one averaged
    # row per conversation, so it is joined without turn_index.
    llm_by_key = {}
    with open(resolve(args.llm), newline="", encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        per_turn = "turn_index" in reader.fieldnames
        for row in reader:
            key = (
                row["indicator_id"],
                row["convo_id"],
                row["model_name"],
                row["seed"],
            ) + ((row["turn_index"],) if per_turn else ())
            llm_by_key[key] = (row.get("aiescore", ""), row.get("judge_status") or "not recorded")

    with open(resolve(args.hij), newline="", encoding="utf-8") as fin_hij, \
         open(out_path, "w", newline="", encoding="utf-8") as fout:
        hij_reader = csv.DictReader(fin_hij)
        writer = csv.DictWriter(fout, fieldnames=COMBINED_HEADER)
        writer.writeheader()

        for row in hij_reader:
            key = (
                row["indicator_id"],
                row["convo_id"],
                row["model"],
                row["seed"],
            ) + ((row["turn_index"],) if per_turn else ())
            score, status = llm_by_key.get(key, ("", "missing"))
            writer.writerow({
                "indicator_id": row["indicator_id"],
                "convo_id": row["convo_id"],
                "model_name": row["model"],
                "seed": row["seed"],
                "turn_index": row["turn_index"],
                "difficulty": row["difficulty"],
                "hij_rater_id": row.get("rater_id", ""),
                "hij_score": row.get("score", ""),
                "llm_aiescore": score,
                "llm_judge_status": status,
            })
    print(f"Saved {out_path}")

if __name__ == "__main__":
    main()
