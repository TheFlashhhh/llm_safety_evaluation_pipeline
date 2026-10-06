import argparse
import csv

from repo_utils import RUNS_DIR, check_output_path, has_filled_column, resolve

HIJ_HEADER = [
    "indicator_id",
    "convo_id",
    "turn_index",
    "seed",
    "prompt_text",
    "response_text",
    "model",
    "difficulty",
    "rater_id",
    "score",
]

def main():
    parser = argparse.ArgumentParser(description="Create a blank human-rating sheet from merged responses.")
    parser.add_argument("--responses", default=RUNS_DIR / "responses_merged.csv")
    parser.add_argument("--out", default=RUNS_DIR / "hij_scores.csv")
    parser.add_argument("--overwrite", action="store_true",
                        help="Replace an existing sheet, but only if it has no scores filled in.")
    args = parser.parse_args()

    out_path = resolve(args.out)
    if out_path.exists() and has_filled_column(out_path, "score"):
        raise SystemExit(f"{out_path} already contains human scores; refusing to replace it.")
    out_path = check_output_path(out_path, args.overwrite)

    with open(resolve(args.responses), newline="", encoding="utf-8") as fin, \
         open(out_path, "w", newline="", encoding="utf-8") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=HIJ_HEADER)
        writer.writeheader()

        for row in reader:
            writer.writerow({
                "indicator_id": row["indicator_id"],
                "convo_id": row["convo_id"],
                "turn_index": row["turn_index"],
                "seed": row["seed"],
                "prompt_text": row["prompt_text"],
                "response_text": row["response_text"],
                "model": row["model_name"],
                "difficulty": row["difficulty"],
                "rater_id": "",
                "score": "",
            })
    print(f"Saved {out_path}")

if __name__ == "__main__":
    main()
