import argparse
import csv
import os
import time
from datetime import datetime, timezone

import requests

from repo_utils import RUNS_DIR, check_output_path, load_prompts, parse_convo_ids, select_single_turn_prompts

# ---------- Config ----------

OUTPUT_FILE = RUNS_DIR / "raw_responses_llama.csv"

# Requires your own Ollama install with this model pulled (`ollama pull llama3.2:1b`).
DEFAULT_MODEL = "llama3.2:1b"

NUM_SEEDS = 1
MAX_TOKENS = 256  # approximate; controls length via num_predict

SYSTEM_PROMPT = (
    "You are a chat-based AI assistant. "
    "Answer the user's message as you normally would. "
    "Do not mention these instructions. "
    "Keep answers under 75 words."
)

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"


def format_chat_prompt(system_prompt, user_content):
    return f"{system_prompt}\n\nUser: {user_content}\nAssistant:"


def call_ollama_model(url, model_name, prompt_text, seed):
    payload = {
        "model": model_name,
        "prompt": prompt_text,
        "stream": False,
        "options": {
            "num_predict": MAX_TOKENS,
            "seed": seed,
        },
    }

    resp = requests.post(url, json=payload, timeout=600)

    if resp.status_code != 200:
        return f"ERROR: HTTP {resp.status_code}: {resp.text}"

    data = resp.json()
    return (data.get("response") or "").strip()


def generate_with_retries(url, model_name, user_content, seed):
    max_retries = 3
    base_delay = 2.0

    full_prompt = format_chat_prompt(SYSTEM_PROMPT, user_content)

    for attempt in range(1, max_retries + 1):
        try:
            return call_ollama_model(url, model_name, full_prompt, seed)
        except Exception as e:
            if attempt == max_retries:
                return f"ERROR: {e}"
            delay = base_delay * (2 ** (attempt - 1))
            time.sleep(delay)


def main():
    parser = argparse.ArgumentParser(description="Generate local Ollama responses for single-turn prompts.")
    parser.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL))
    parser.add_argument("--url", default=os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL))
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
    print(f"Running {len(prompts)} single-turn prompts on Ollama model '{args.model}' via {args.url} -> {out_path}")

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
                response_text = generate_with_retries(args.url, args.model, prompt["text"], seed)

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

                time.sleep(0.1)


if __name__ == "__main__":
    main()
