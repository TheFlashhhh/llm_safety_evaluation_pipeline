"""Offline classroom demo for DS684 Assignment 3.

Uses only committed historical files and the Python standard library: no
credentials, network access, or Ollama. It:

1. Selects a few matching single-turn conversations for one indicator.
2. Creates a blank annotation sheet for them (only if none exists yet).
3. Validates any human ratings already entered in that sheet.
4. Writes a Markdown walkthrough and CSV tables to demo/output/.

Numerical model comparisons appear only when valid human scores exist for
both models on enough matched examples.
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from itertools import combinations
from statistics import mean

from repo_utils import (
    PROMPTS_TSV,
    RESPONSES_DIR,
    ROOT,
    SCORES_DIR,
    load_prompts,
    resolve,
    rubric_for,
    single_turn_convo_ids,
)

INDICATOR = "L4_HAI_DesignNoCoercion"
MODELS = ["gemini-2.5-flash", "llama3.2:1b"]
# First N single-turn conversations per difficulty, in conversation-number
# order. The rule never looks at scores or response content.
PER_DIFFICULTY = {"easy": 4, "medium": 4}

RESPONSES_CSV = RESPONSES_DIR / "responses_merged.csv"
JUDGE_CSV = SCORES_DIR / "llm_scores.csv"
DEMO_DIR = ROOT / "demo"
DEFAULT_SHEET = DEMO_DIR / "annotation_sheet.csv"
DEFAULT_OUTPUT_DIR = DEMO_DIR / "output"

# Display convenience only: avoids printing averages built from one or two
# pairs. It is not a statistical sufficiency threshold.
MIN_PAIRS = 3
THRESHOLD_NOTE = (
    f"The {MIN_PAIRS}-pair minimum is only a display convenience so that averages are not "
    "printed from one or two pairs. It does not mean the sample is statistically sufficient. "
    "These numbers are descriptive: no significance tests, confidence intervals, or "
    "general model rankings are supported."
)

SHEET_HEADER = [
    "response_id", "indicator_id", "convo_id", "turn_index", "difficulty",
    "model_name", "seed", "prompt_text", "response_text", "rater_id", "score", "notes",
]
VALID_SCORES = {"1", "2", "3", "4"}
JUDGE_LABEL = "historical Gemini judge (gemini-2.5-flash, generic 1-4 prompt, single run)"


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def convo_number(convo_id):
    return int(convo_id.rsplit("_", 1)[1])


# --------------------
# Selection
# --------------------

def select_examples(prompts, responses):
    """Pick matching single-turn conversations and verify both models' rows."""
    single = single_turn_convo_ids(prompts)
    prompt_by_convo = {p["convo_id"]: p for p in prompts if p["convo_id"] in single}

    rows_by_convo = defaultdict(list)
    for r in responses:
        if r["indicator_id"] == INDICATOR:
            rows_by_convo[r["convo_id"]].append(r)

    candidates = sorted(
        (c for c in rows_by_convo if c in single and
         {r["model_name"] for r in rows_by_convo[c]} >= set(MODELS)),
        key=convo_number,
    )

    selected = []
    for difficulty, n in PER_DIFFICULTY.items():
        picked = [c for c in candidates if prompt_by_convo[c]["difficulty"] == difficulty][:n]
        if len(picked) < n:
            sys.exit(f"Only {len(picked)} {difficulty} single-turn conversations available for {INDICATOR}.")
        selected += picked

    examples = []
    for convo_id in selected:
        prompt = prompt_by_convo[convo_id]
        by_model = {}
        for model in MODELS:
            matches = [r for r in rows_by_convo[convo_id] if r["model_name"] == model]
            if len(matches) != 1:
                sys.exit(f"{convo_id}: expected 1 {model} response, found {len(matches)}.")
            r = matches[0]
            if r["turn_index"] != "1" or r["prompt_text"] != prompt["text"]:
                sys.exit(f"{convo_id}: {model} response does not match the prompt set.")
            by_model[model] = r
        examples.append({"convo_id": convo_id, "prompt": prompt, "responses": by_model})
    return examples


def response_id(convo_id, model):
    return f"{convo_number(convo_id):02d}-{model}"


# --------------------
# Annotation sheet
# --------------------

def ensure_sheet(path, examples):
    """Create a blank sheet if none exists. Never overwrite an existing one."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for ex in examples:
        for model, r in ex["responses"].items():
            rows.append({
                "response_id": response_id(ex["convo_id"], model),
                "indicator_id": INDICATOR,
                "convo_id": ex["convo_id"],
                "turn_index": r["turn_index"],
                "difficulty": r["difficulty"],
                "model_name": model,
                "seed": r["seed"],
                "prompt_text": r["prompt_text"],
                "response_text": r["response_text"],
                "rater_id": "",
                "score": "",
                "notes": "",
            })
    # utf-8-sig so Excel on Windows shows curly quotes and dashes correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return True


def read_sheet(path):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f)), None
    except UnicodeDecodeError:
        # Excel's plain "CSV" save uses the Windows code page.
        with open(path, newline="", encoding="cp1252") as f:
            return list(csv.DictReader(f)), "Sheet was not UTF-8; read it as Windows-1252."


def validate_ratings(sheet_rows, examples):
    """Return ({(convo_id, model): {rater: score}}, [issues])."""
    expected = {(ex["convo_id"], m) for ex in examples for m in MODELS}
    ratings = defaultdict(dict)
    issues = []
    for line, row in enumerate(sheet_rows, start=2):  # header is line 1
        score = (row.get("score") or "").strip()
        rater = (row.get("rater_id") or "").strip()
        key = ((row.get("convo_id") or "").strip(), (row.get("model_name") or "").strip())
        if not score and not rater:
            continue  # not rated yet
        problem = None
        if key not in expected:
            problem = f"convo_id/model_name {key} is not one of the selected responses"
        elif score not in VALID_SCORES:
            problem = f"score {score!r} is not an integer from 1 to 4"
        elif not rater:
            problem = "score has no rater_id"
        elif rater in ratings[key]:
            problem = f"duplicate rating by {rater!r}; kept the first one"
        if problem:
            issues.append({"sheet_line": line, "response_id": row.get("response_id", ""),
                           "rater_id": rater, "score": score, "problem": problem})
        else:
            ratings[key][rater] = int(score)
    return ratings, issues


# --------------------
# Analysis
# --------------------

def load_judge_scores():
    """Historical judge scores keyed by (convo_id, model). Missing keys stay missing."""
    scores = {}
    for r in read_csv(JUDGE_CSV):
        if r["indicator_id"] == INDICATOR and r["seed"] == "1" and r["aiescore"]:
            scores[(r["convo_id"], r["model_name"])] = float(r["aiescore"])
    return scores


def model_comparison(examples, human_mean):
    """Paired comparison on conversations where both models have human scores."""
    pairs = [
        (ex["convo_id"], human_mean[(ex["convo_id"], MODELS[0])], human_mean[(ex["convo_id"], MODELS[1])])
        for ex in examples
        if (ex["convo_id"], MODELS[0]) in human_mean and (ex["convo_id"], MODELS[1]) in human_mean
    ]
    if len(pairs) < MIN_PAIRS:
        return pairs, None
    diffs = [a - b for _, a, b in pairs]
    summary = {
        "n_matched_conversations": len(pairs),
        f"mean_human_{MODELS[0]}": round(mean(a for _, a, _ in pairs), 2),
        f"mean_human_{MODELS[1]}": round(mean(b for _, _, b in pairs), 2),
        "mean_paired_difference": round(mean(diffs), 2),
        f"n_{MODELS[0]}_higher": sum(d > 0 for d in diffs),
        "n_tied": sum(d == 0 for d in diffs),
        f"n_{MODELS[1]}_higher": sum(d < 0 for d in diffs),
    }
    return pairs, summary


def inter_rater(ratings):
    """Pairwise agreement between raters who scored the same response."""
    pairs = [
        (a, b)
        for by_rater in ratings.values()
        for a, b in combinations(by_rater.values(), 2)
    ]
    if len(pairs) < MIN_PAIRS:
        return len(pairs), None
    return len(pairs), {
        "rater_pairs": len(pairs),
        "exact_agreement": round(sum(a == b for a, b in pairs) / len(pairs), 2),
        "within_one_point": round(sum(abs(a - b) <= 1 for a, b in pairs) / len(pairs), 2),
    }


def human_vs_judge(human_mean, judge):
    rows = [
        (key, human_mean[key], judge[key])
        for key in sorted(human_mean)
        if key in judge
    ]
    if len(rows) < MIN_PAIRS:
        return rows, None
    return rows, {
        "n_responses": len(rows),
        "mean_absolute_difference": round(mean(abs(h - j) for _, h, j in rows), 2),
        "n_differ_by_2_or_more": sum(abs(h - j) >= 2 for _, h, j in rows),
    }


# --------------------
# Markdown
# --------------------

def quote(text):
    return "\n".join("> " + line if line.strip() else ">" for line in text.strip().splitlines())


def demote(markdown):
    """Push rubric headings one level down so they nest under this document's sections."""
    return "\n".join("#" + line if line.startswith("#") else line for line in markdown.splitlines())


def fmt(x):
    return f"{x:g}" if isinstance(x, (int, float)) else x


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(fmt(v)) for v in row) + " |" for row in rows]
    return "\n".join(out)


def render(examples, judge, ratings, human_mean, issues, sheet_path, sheet_note, comparison, irr, hvj):
    global_scale, indicator_rubric = rubric_for(INDICATOR)
    rel_sheet = sheet_path.relative_to(ROOT) if ROOT in sheet_path.parents else sheet_path
    n_rated = sum(len(v) for v in ratings.values())
    md = []
    add = md.append

    add(f"# Teaching demo walkthrough: {INDICATOR}\n")
    add("*Generated offline by `scripts/teaching_demo.py` from committed historical files. "
        "Re-run the script after editing the annotation sheet; do not edit this file by hand.*\n")
    add("Data sources (unchanged historical files from the original project):\n")
    add(f"- Prompts: `{PROMPTS_TSV.relative_to(ROOT).as_posix()}`")
    add(f"- Responses: `{RESPONSES_CSV.relative_to(ROOT).as_posix()}` "
        f"(`{MODELS[0]}` and `{MODELS[1]}`, generated December 2025, one run each)")
    add(f"- Historical judge scores: `{JUDGE_CSV.relative_to(ROOT).as_posix()}` "
        f"(contains `{MODELS[0]}` responses only)")
    add(f"- Human ratings: `{rel_sheet.as_posix()}`\n")

    add("## 1. Construct and rubric\n")
    add("Verbatim from `rubrics/hij_evaluation_rubric.md`:\n")
    add(demote(indicator_rubric) + "\n")
    add("<details><summary>Global 1-4 scale used for every indicator</summary>\n")
    add(demote(global_scale) + "\n")
    add("</details>\n")

    add("## 2. How the examples were selected\n")
    counts = Counter(ex["prompt"]["difficulty"] for ex in examples)
    add(f"- Indicator `{INDICATOR}`; {len(examples)} conversations: "
        + ", ".join(f"{n} {d}" for d, n in counts.items()) + ".")
    add("- Single-turn status comes from the complete prompt set: each conversation has exactly "
        "one prompt row and `scenario_type = single_turn`.")
    add("- Rule: the first conversations per difficulty in conversation-number order. "
        "The rule does not look at scores or response content.")
    add("- Checked: each model has exactly one saved response per conversation, at turn 1, "
        "with prompt text identical to the prompt set.\n")

    add("## 3. Prompts, responses, and scores\n")
    add(f"**Historical judge scores** are from the {JUDGE_LABEL}. The judge saw only the indicator "
        "ID, the difficulty label, and a generic scale, not this rubric. No judge scores were committed for "
        f"`{MODELS[1]}`; they are shown as unavailable, not estimated.\n")
    for ex in examples:
        c = ex["convo_id"]
        add(f"### {c} ({ex['prompt']['difficulty']})\n")
        add("**Prompt**\n")
        add(quote(ex["prompt"]["text"]) + "\n")
        for model in MODELS:
            r = ex["responses"][model]
            j = judge.get((c, model))
            judge_text = f"{j:g}" if j is not None else "unavailable (not in the committed scores)"
            hr = ratings.get((c, model), {})
            human_text = (", ".join(f"{k}: {v}" for k, v in sorted(hr.items()))
                          if hr else "not yet rated")
            add(f"**{model}** (`{response_id(c, model)}`, {len(r['response_text'].split())} words)\n")
            add(quote(r["response_text"]) + "\n")
            add(f"- Historical judge score: {judge_text}")
            add(f"- Human score(s): {human_text}\n")

    add("## 4. Score availability\n")
    add(table(
        ["Model", "Responses", "Historical judge scores", "Responses with valid human scores"],
        [[m, len(examples),
          sum((ex["convo_id"], m) in judge for ex in examples),
          sum((ex["convo_id"], m) in human_mean for ex in examples)] for m in MODELS],
    ) + "\n")
    if sheet_note:
        add(f"Note: {sheet_note}\n")
    add(f"Valid human ratings: {n_rated}. Rows with problems (excluded): {len(issues)}.\n")
    if issues:
        add(table(["Sheet line", "response_id", "rater_id", "score", "Problem"],
                  [[i["sheet_line"], i["response_id"], i["rater_id"], i["score"], i["problem"]]
                   for i in issues]) + "\n")

    add("## 5. Model comparison\n")
    add("The historical judge scores cannot compare the two models: they cover only "
        f"`{MODELS[0]}`.\n")
    pairs, summary = comparison
    if summary:
        add(f"Human scores, one observation per response (averaged over raters when "
            f"several rated it), compared only on conversations where both models were rated: "
            f"{summary['n_matched_conversations']} rule-selected prompts from one indicator, "
            "rated by whoever filled in the sheet. The counts below describe these responses "
            "only; they do not show that one model is better in general.\n")
        add(f"*{THRESHOLD_NOTE}*\n")
        add(table(["Measure", "Value"], [[k, v] for k, v in summary.items()]) + "\n")
        add(table(["Conversation", MODELS[0], MODELS[1]], [[c, a, b] for c, a, b in pairs]) + "\n")
    else:
        add(f"**No numerical comparison yet.** It needs valid human scores for both models on at "
            f"least {MIN_PAIRS} matching conversations; there are currently {len(pairs)}. "
            f"Compare the paired responses in section 3 qualitatively, then fill in "
            f"`rater_id` and `score` (1-4) in `{rel_sheet.as_posix()}` and re-run the script. "
            f"(The {MIN_PAIRS}-pair minimum is a display convenience, not a statistical "
            "sufficiency threshold.)\n")

    add("## 6. Agreement\n")
    if irr[1] or hvj[1]:
        add(f"*{THRESHOLD_NOTE}*\n")
    n_irr, irr_summary = irr
    if irr_summary:
        add("**Between human raters** (pairs of raters on the same response):\n")
        add(table(["Measure", "Value"], [[k, v] for k, v in irr_summary.items()]) + "\n")
    else:
        add(f"**Between human raters: skipped.** Needs at least {MIN_PAIRS} pairs of raters "
            f"scoring the same response; there are {n_irr}. Add rows with a second `rater_id` "
            "to the annotation sheet to enable it.\n")
    hvj_rows, hvj_summary = hvj
    if hvj_summary:
        add(f"**Human vs historical judge** ({MODELS[0]} responses only):\n")
        add(table(["Measure", "Value"], [[k, v] for k, v in hvj_summary.items()]) + "\n")
        add(table(["Response", "Human (mean)", "Judge"],
                  [[response_id(c, m), round(h, 2), j] for (c, m), h, j in hvj_rows]) + "\n")
    else:
        add(f"**Human vs historical judge: skipped.** Needs at least {MIN_PAIRS} "
            f"{MODELS[0]} responses with both a human and a judge score; there are "
            f"{len(hvj_rows)}. Not possible for {MODELS[1]} because its judge scores are "
            "unavailable.\n")

    add("## 7. Discussion questions\n")
    add("1. Which responses would you score differently from the historical judge, and why? "
        "Point to rubric wording.")
    add("2. The judge never saw the rubric. How could that affect what its scores measure?")
    add("3. The same model generated one set of responses and judged them. What bias could that introduce?")
    add(f"4. One run, one seed label, {len(examples)} prompts: what would you need before ranking the models?")
    add("5. Does refusing a manipulative request fully capture \"respecting autonomy\"? "
        "What does the construct leave out?\n")

    add("## 8. Limitations to report\n")
    add("- Historical responses come from a single generation run per model; the `seed` column is "
        "a label that was not passed to either API, so it does not make outputs reproducible.")
    add("- The two models were run with different system prompts, temperatures, and token limits.")
    add("- Historical follow-up (turn 2) responses were generated without the earlier turn, so this "
        "demo uses single-turn conversations only.")
    add("- Historical judge scores are a single run under conditions that were not fully recorded; "
        "the original notebook's saved outputs could not be reproduced from the committed files.")
    add(f"- {len(examples)} prompts from one indicator are a teaching sample, not a benchmark.")
    return "\n".join(md) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet", default=DEFAULT_SHEET, help="Annotation sheet (relative to the repo root).")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    sheet_path = resolve(args.sheet)
    out_dir = resolve(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    examples = select_examples(load_prompts(), read_csv(RESPONSES_CSV))
    created = ensure_sheet(sheet_path, examples)
    sheet_rows, sheet_note = read_sheet(sheet_path)
    ratings, issues = validate_ratings(sheet_rows, examples)
    human_mean = {k: mean(v.values()) for k, v in ratings.items() if v}
    judge = load_judge_scores()

    comparison = model_comparison(examples, human_mean)
    irr = inter_rater(ratings)
    hvj = human_vs_judge(human_mean, judge)

    # CSV tables
    response_rows = []
    for ex in examples:
        for model in MODELS:
            r = ex["responses"][model]
            key = (ex["convo_id"], model)
            response_rows.append({
                "response_id": response_id(ex["convo_id"], model),
                "convo_id": ex["convo_id"],
                "difficulty": r["difficulty"],
                "model_name": model,
                "seed_label": r["seed"],
                "prompt_text": r["prompt_text"],
                "response_text": r["response_text"],
                "word_count": len(r["response_text"].split()),
                "historical_judge_score": fmt(judge[key]) if key in judge else "",
                "historical_judge_status": "available" if key in judge else "unavailable",
                "n_human_ratings": len(ratings.get(key, {})),
                "human_mean_score": round(human_mean[key], 2) if key in human_mean else "",
            })
    write_csv(out_dir / "selected_responses.csv", list(response_rows[0]), response_rows)
    write_csv(out_dir / "annotation_issues.csv",
              ["sheet_line", "response_id", "rater_id", "score", "problem"], issues)

    # Remove tables from earlier runs that no longer have enough data.
    for name, summary in (("model_comparison.csv", comparison[1]),
                          ("agreement.csv", irr[1] or hvj[1])):
        path = out_dir / name
        if path.exists():
            path.unlink()
    if comparison[1]:
        write_csv(out_dir / "model_comparison.csv", ["convo_id", MODELS[0], MODELS[1]],
                  [{"convo_id": c, MODELS[0]: a, MODELS[1]: b} for c, a, b in comparison[0]])
    agreement = []
    if irr[1]:
        agreement += [{"comparison": "human_vs_human", "measure": k, "value": v} for k, v in irr[1].items()]
    if hvj[1]:
        agreement += [{"comparison": f"human_vs_historical_judge ({MODELS[0]} only)", "measure": k, "value": v}
                      for k, v in hvj[1].items()]
    if agreement:
        write_csv(out_dir / "agreement.csv", ["comparison", "measure", "value"], agreement)

    walkthrough = render(examples, judge, ratings, human_mean, issues, sheet_path, sheet_note,
                         comparison, irr, hvj)
    (out_dir / "walkthrough.md").write_text(walkthrough, encoding="utf-8")

    print(f"Selected {len(examples)} conversations x {len(MODELS)} models for {INDICATOR}.")
    print(("Created blank annotation sheet: " if created else "Using existing annotation sheet: ") + str(sheet_path))
    print(f"Valid human ratings: {sum(len(v) for v in ratings.values())}; rows with problems: {len(issues)}")
    print(f"Model comparison: {'shown' if comparison[1] else 'skipped (not enough matched human scores)'}")
    print(f"Wrote {out_dir / 'walkthrough.md'} and CSV tables.")


if __name__ == "__main__":
    main()
