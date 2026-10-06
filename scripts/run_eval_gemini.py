import argparse
import csv
import os
import time
from datetime import datetime, timezone

from repo_utils import RUNS_DIR, check_output_path, load_prompts, parse_convo_ids, select_single_turn_prompts

# The historical responses used gemini-2.5-flash. Google now limits 2.5 models
# to users who have used them before, so set GEMINI_MODEL to a model your key
# can call, and report the model you actually used.
DEFAULT_MODEL = "gemini-2.5-flash"
OUTPUT_FILE = RUNS_DIR / "raw_responses_gemini.csv"

NUM_SEEDS = 1
TEMPERATURE = 0.7
MAX_TOKENS = 2056

SYSTEM_PROMPT = "Answer in under 75 words."


def call_gemini_model(client, types, model_name: str, system_prompt: str, user_content: str, seed: int) -> str:
    full_prompt = f"{system_prompt}\n\nUser: {user_content}"

    resp = client.models.generate_content(
        model=model_name,
        contents=full_prompt,
        config=types.GenerateContentConfig(
            temperature=TEMPERATURE,
            max_output_tokens=MAX_TOKENS,
            # Best-effort reproducibility only; the API does not guarantee
            # identical outputs for the same seed.
            seed=seed,
            # No tools are used, so turn off the SDK's automatic function calling.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )

    if not resp.candidates:
        return "ERROR: No candidates returned"

    cand = resp.candidates[0]
    if not cand.content or not getattr(cand.content, "parts", None):
        # Avoid `.text` crash when MAX_TOKENS / SAFETY etc. yields empty parts
        return f"ERROR: Empty content (finish_reason={cand.finish_reason.name})"

    return resp.text or ""


def main():
    parser = argparse.ArgumentParser(description="Generate Gemini responses for single-turn prompts.")
    parser.add_argument("--model", default=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--out", default=OUTPUT_FILE, help="Output CSV (relative to the repo root).")
    parser.add_argument("--indicator", help="Only run prompts for this indicator_id.")
    parser.add_argument("--limit", type=int, help="Maximum number of prompts to run.")
    parser.add_argument("--convo-ids", type=parse_convo_ids,
                        help="Comma-separated convo_ids to run (single-turn only).")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    prompts = select_single_turn_prompts(load_prompts(), args.indicator, args.limit, args.convo_ids)
    if not prompts:
        raise SystemExit("No matching single-turn prompts to run.")
    out_path = check_output_path(args.out, args.overwrite)
    print(f"Running {len(prompts)} single-turn prompts on {args.model} -> {out_path}")

    # Imported here so --help works without the optional live dependencies.
    from google import genai
    from google.genai import types

    # Reads GEMINI_API_KEY (or GOOGLE_API_KEY, which wins if both are set)
    client = genai.Client()

    with open(out_path, "w", newline="", encoding="utf-8") as f_out:
        writer = csv.writer(f_out)
        writer.writerow([
            "indicator_id",
            "convo_id",
            "turn_index",
            "role",
            "prompt_text",
            "difficulty",
            "model_name",
            "seed",
            "response_text",
            "timestamp",
        ])

        for prompt in prompts:
            for seed in range(1, NUM_SEEDS + 1):
                try:
                    response_text = call_gemini_model(
                        client=client,
                        types=types,
                        model_name=args.model,
                        system_prompt=SYSTEM_PROMPT,
                        user_content=prompt["text"],
                        seed=seed,
                    )
                except Exception as e:
                    response_text = f"ERROR: {e}"

                writer.writerow([
                    prompt["indicator_id"],
                    prompt["convo_id"],
                    prompt["turn_index"],
                    prompt["role"],
                    prompt["text"],
                    prompt.get("difficulty", ""),
                    args.model,
                    seed,
                    response_text,
                    datetime.now(timezone.utc).isoformat(),
                ])

                time.sleep(0.5)


if __name__ == "__main__":
    main()
