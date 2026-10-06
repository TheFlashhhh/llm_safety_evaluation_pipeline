> **Teaching fork.** This is <https://github.com/TheFlashhhh/llm_safety_evaluation_pipeline>,
> prepared as a classroom example for DS684 AI Ethics, Assignment 3. The original project and all
> historical data come from <https://github.com/pratrt141098/llm_safety_evaluation_pipeline>.
> For the offline demo (`python scripts\teaching_demo.py`), Windows setup, and known issues, see
> [TEACHING.md](TEACHING.md). The text below is the original README. Notes marked **Historical**
> describe the original project's files and behavior; notes marked **On this branch** describe the
> repaired scripts. Where they differ, the "On this branch" notes are current.

This README documents how to use the LLM SAFETY EVALUATION PIPELINE.
The goal is to support a **three-signal evaluation framework**:

1. **HIJ scores**: Human raters using `rubrics/hij_evaluation_rubric.md`.
2. **LLM scores**: Gemini-as-evaluator scores in `scores/llm_scores.csv`.
3. **Combined view**: Unified table joining human and LLM scores in `scores/combined_scores.csv`.

> **Historical:** the committed `scores/` files are the original outputs. Every human score in them is
> blank, and the LLM scores cover `gemini-2.5-flash` responses only. **On this branch** the scripts never
> write to `scores/`; new outputs go to `runs/`.

---

## 1. Source Data: `responses/responses_merged.csv`

`responses_merged.csv` is the canonical table of model responses across indicators, models, and seeds.

Each row corresponds to a single **model response** to a specific prompt turn, with at least:

- `indicator_id` – L4 indicator (e.g., `L4_HAI_DesignNoCoercion`).
- `convo_id` – conversation id (e.g., `L4_HAI_DesignNoCoercion_01`).
- `turn_index` – turn within conversation (1, 2, …).
- `role` – typically `user` for the prompts stored here.
- `prompt_text` – user prompt that elicited the response.
- `difficulty` – difficulty label (`easy`, `medium`, `tough`).
- `model_name` – generator model (e.g., `gemini-2.5-flash`, `llama3.2:1b`).
- `seed` – seed label (e.g., `1`). In the historical files it was not passed to either API, so it does not make outputs reproducible.
- `response_text` – model’s response.
- `timestamp` – generation timestamp (ISO string).

This file is produced by `scripts/merge_responses.py`, which merges Gemini and Llama raw response CSVs into a unified structure.

> **On this branch:** `merge_responses.py` reads `runs/raw_responses_gemini.csv` and `runs/raw_responses_llama.csv`
> and writes `runs/responses_merged.csv` by default (`--base`, `--new`, `--out` to change). The historical
> `responses/responses_merged.csv` is kept unchanged. Its turn-2 responses were generated without the turn-1
> exchange, so the teaching demo uses single-turn conversations only.

---

## 2. HIJ Initialization Script: `scripts/init_hij_scores.py`

> **Historical description below** (paths `responses/` → `scores/`). **On this branch** the script reads
> `runs/responses_merged.csv` and writes `runs/hij_scores.csv` by default (`--responses`, `--out` to change).

### Purpose

`init_hij_scores.py` creates a **blank annotation sheet** for human raters by transforming `responses_merged.csv` into `scores/hij_scores.csv` and adding annotation-specific fields.

### Implementation Summary

The script:

1. Locates the project root relative to `scripts/`.
2. Reads `responses/responses_merged.csv` via `csv.DictReader`.
3. Writes `scores/hij_scores.csv` with a new header schema tailored for HIJ.
4. Copies key metadata fields from each response and appends empty `rater_id` and `score` columns.

Header for `hij_scores.csv`:

indicator_id,
convo_id,
turn_index,
seed,
prompt_text,
response_text,
model,
difficulty,
rater_id,
score

text

For every row in `responses_merged.csv`, the script writes:

- `indicator_id`  ← `row["indicator_id"]`
- `convo_id`      ← `row["convo_id"]`
- `turn_index`    ← `row["turn_index"]`
- `seed`          ← `row["seed"]`
- `prompt_text`   ← `row["prompt_text"]`
- `response_text` ← `row["response_text"]`
- `model`         ← `row["model_name"]`
- `difficulty`    ← `row["difficulty"]`
- `rater_id`      ← `""` (blank placeholder)
- `score`         ← `""` (blank placeholder)

### How to Run

From the repo root:

python scripts/init_hij_scores.py

text

> **On this branch:** this needs `runs/responses_merged.csv` (or pass `--responses`). It refuses to write
> into the historical `scores/` folder, refuses to overwrite an existing file without `--overwrite`, and
> never replaces a sheet that already contains scores.

---

## 3. HIJ Scores File: `scores/hij_scores.csv`

> **Historical file.** The committed `scores/hij_scores.csv` is the original sheet, and all 710 scores are
> blank. Leave it unchanged. For the classroom demo, rate in `demo/annotation_sheet.csv` (see
> [TEACHING.md](TEACHING.md)); for new runs, `init_hij_scores.py` creates `runs/hij_scores.csv`.

### Purpose

`hij_scores.csv` is the **master spreadsheet for human evaluation**. Each row is a single human-judged response aligned with the same granularity as `responses_merged.csv`.

### Schema

- `indicator_id` – L4 indicator id.
- `convo_id` – conversation id.
- `turn_index` – which turn in the conversation this response corresponds to.
- `seed` – seed label from generation (in the historical runs it was not passed to the APIs).
- `prompt_text` – original user prompt.
- `response_text` – model response being evaluated.
- `model` – generating model (e.g., `gemini-2.5-flash`, `llama3.2:1b`).
- `difficulty` – prompt difficulty (`easy`, `medium`, `tough`).
- `rater_id` – identifier for the human rater (e.g., `r1`, `alice`, `mturk_worker_42`).
- `score` – numeric HIJ score on the 1–4 scale defined in `rubrics/hij_evaluation_rubric.md`.

### Annotation Workflow

1. **Assign rater ids**:
   - Before annotating, decide simple ids (e.g., `r1`, `r2` or '1', '2'). Use consistent ids across the file.
2. **Split work if needed**:
   - You can copy `hij_scores.csv` to per-rater files and later merge on the shared keys (`indicator_id`, `convo_id`, `turn_index`, `model`, `seed`).
3. **Scoring guidelines**:
   - Use `rubrics/hij_evaluation_rubric.md` for definitions of 1–4 per indicator and lexical hints.
4. **Multiple raters**:
   - Option A (single file, multiple rows per response):
     - Duplicate rows so each `(indicator_id,convo_id,turn_index,model,seed)` appears once per rater.
   - Option B (one file per rater):
     - Keep one row per response per file and later compute aggregates (mean, std) via a separate script.

For the current pipeline, the simplest path is **one row per response per rater** in `hij_scores.csv`. Downstream scripts can average scores by grouping on the key fields.

---

## 4. LLM Scores File: `scores/llm_scores.csv`

> **Historical description below.** It describes the committed file and the original judge prompt, which gave
> the judge only the indicator ID, the difficulty label, and a generic 1–4 scale (no rubric). See the
> "On this branch" note at the end of this section for the repaired script.

`llm_scores.csv` is produced by `scripts/aie_llm_scoring.py`, which uses Gemini 2.5 Flash as an evaluator to rate responses along the same L4 indicators.

### Schema

- `indicator_id` – L4 indicator.
- `convo_id` – conversation id.
- `model_name` – generator model being evaluated.
- `seed` – seed for that model run.
- `aiescore` – numeric LLM-based ethics score, 1–4 (possibly averaged across turns within a conversation).

`aie_llm_scoring.py`:

- Reads merged responses, constructs evaluation prompts with indicator, difficulty, user prompt, and candidate response.
- Calls Gemini 2.5 Flash with a config that allows reading harmful text but blocks generating harmful content.
- Parses the first digit 1–4 from the evaluator’s output and stores it as `aiescore`.
- Aggregates by `(indicator_id, convo_id, model_name, seed)` (e.g., averaging across multi-turn conversations).

This file provides the **LLM scoring signal** that will be aligned with HIJ scores in the combined file.

> **Historical:** the committed `scores/llm_scores.csv` contains `gemini-2.5-flash` responses only; no Llama
> responses were judged.
>
> **On this branch:** `aie_llm_scoring.py` reads `runs/responses_merged.csv` by default and scores only
> single-turn conversations, each response separately (no averaging across turns). It sends the indicator's
> definition and full 1–4 rubric, using an explicit `L4_HAI_*` → rubric-heading mapping, and runs at
> temperature 0. The model is set with `--model` or `JUDGE_MODEL`. It writes `runs/llm_scores.csv` with columns
> `indicator_id, convo_id, turn_index, model_name, seed, judge_model, judge_status, aiescore, judge_raw_output`.
> Only rows with `judge_status = valid` have a score; `parse_failure`, `blocked`, `empty` and `api_error` rows
> are kept but left unscored. `--dry-run` prints the judge prompt without calling an API, and `--convo-ids`
> and `--indicator` select rows.

---

## 5. Combined Scores Script: `scripts/combine_scores.py`

> **Historical description below** (paths in `scores/`, conversation-level join). **On this branch** the
> script reads `runs/hij_scores.csv` and `runs/llm_scores.csv` and writes `runs/combined_scores.csv` by
> default (`--hij`, `--llm`, `--out` to change). With a judge file from the repaired scorer, the join key also
> includes `turn_index`. It adds an `llm_judge_status` column: the judge status, `missing` if no judge row
> exists, or `not recorded` for the historical judge file.

### Purpose

`combine_scores.py` builds `scores/combined_scores.csv`, which **joins human and LLM scores** on a shared key so both signals can be analyzed together per response or per (indicator, conversation, model, seed).

### Key Join

The join key is:

(indicator_id, convo_id, model_name, seed)

text

- On the HIJ side, `model` is used as `model_name`.
- On the LLM side, the same `model_name` column exists in `llm_scores.csv`.

### Implementation Summary

The script:

1. Reads `scores/llm_scores.csv` into a dictionary keyed by `(indicator_id, convo_id, model_name, seed)` with values `aiescore`.
2. Iterates over `scores/hij_scores.csv`, building the same key from:
   - `indicator_id`, `convo_id`, `model` (→ `model_name`), `seed`.
3. Writes `scores/combined_scores.csv` with header:

indicator_id,
convo_id,
model_name,
seed,
turn_index,
difficulty,
hij_rater_id,
hij_score,
llm_aiescore

text

For each HIJ row:

- Copies metadata fields:
  - `indicator_id`, `convo_id`, `model_name`, `seed`, `turn_index`, `difficulty`.
- Copies HIJ fields:
  - `hij_rater_id` ← `rater_id`
  - `hij_score`    ← `score`
- Looks up LLM score:
  - `llm_aiescore` ← `aiescore` from `llm_scores.csv` if present, else empty string.

### How to Run

From repo root:

python scripts/combine_scores.py

> **On this branch:** this needs `runs/hij_scores.csv` and `runs/llm_scores.csv` (or pass `--hij` and
> `--llm`). It refuses to write into historical folders and will not overwrite an existing file without
> `--overwrite`.

---

## 6. Combined Scores File: `scores/combined_scores.csv`

> **Historical file and description.** In the committed file every `hij_score` is blank and `llm_aiescore`
> is filled only for Gemini rows. New combined files in `runs/` also have an `llm_judge_status` column, and
> their judge scores are per response rather than repeated per conversation.

### Schema

- `indicator_id`   – L4 indicator id.
- `convo_id`       – conversation id.
- `model_name`     – generator model (as used in `llm_scores.csv`).
- `seed`           – random seed for that generation.
- `turn_index`     – turn within conversation for this particular response.
- `difficulty`     – prompt difficulty (`easy`, `medium`, `tough`).
- `hij_rater_id`   – human rater id (copied from `hij_scores.csv`).
- `hij_score`      – HIJ score (1–4 or blank if not rated yet).
- `llm_aiescore`   – LLM evaluator score (1–4, possibly averaged; blank if no LLM score for that key).

### Interpretation

- Multiple rows with the **same** `(indicator_id, convo_id, model_name, seed)` but different `turn_index` are **different turns** of the same conversation.
- Multiple rows with different `hij_rater_id` but same key represent **multiple human ratings** for the same response, enabling inter-rater analysis.
- `llm_aiescore` is constant for a given `(indicator_id, convo_id, model_name, seed)` and is attached to each corresponding HIJ row.

---

## 7. Recommended Analysis Patterns

Once `combined_scores.csv` exists, you can:

> **Teaching note:** count each scored unit once. In the historical files, one conversation-level judge
> score is repeated on every turn row, so treating rows as independent double-counts two-turn conversations
> and makes confidence intervals too narrow. Average turns, or raters, to one value per unit first.

### 7.1 Per-Indicator, Per-Model Aggregation

Use a small Python or notebook script to:

- Group by `indicator_id, model_name` and compute:
  - `mean_hij` and `std_hij` (averaging across raters / seeds / turns).
  - `mean_llm` and `std_llm` (averaging `llm_aiescore` where present).

This mirrors the aggregation done in `aggregate_mixed.py` for mixed scores, but now for HIJ vs LLM signals. (`aggregate_mixed.py` is not included in this repository.)

### 7.2 Disagreement Analysis

Identify cases where:

- `hij_score` is high but `llm_aiescore` is low, or vice versa.
- Use these to find where Gemini-as-evaluator is stricter or more lenient than humans for specific indicators or difficulty levels.

### 7.3 Difficulty and Indicator Slices

Slice by:

- `difficulty` (`easy`, `medium`, `tough`) to see how performance varies with adversarial pressure.
- `indicator_id` to compare dimensions such as `DesignNoCoercion` vs `DarkPatternAudit`, `AnthropomorphismDisclosure`, etc.

---

## 8. End-to-End Workflow Summary

> **On this branch** (current workflow, all outputs in `runs/`; exact Windows commands in the
> "Optional live runs" section of [TEACHING.md](TEACHING.md)):
>
> 1. `python scripts/run_eval_gemini.py` → `runs/raw_responses_gemini.csv` (needs your Gemini API key)
> 2. `python scripts/run_eval_llama.py` → `runs/raw_responses_llama.csv` (needs your local Ollama and model)
> 3. `python scripts/merge_responses.py` → `runs/responses_merged.csv`
> 4. `python scripts/init_hij_scores.py` → `runs/hij_scores.csv`, then raters fill in `rater_id` and `score`
> 5. `python scripts/aie_llm_scoring.py` → `runs/llm_scores.csv` (needs your Gemini API key; `--dry-run` does not)
> 6. `python scripts/combine_scores.py` → `runs/combined_scores.csv`
>
> Steps 1–2 and 5 accept `--convo-ids` or `--indicator`/`--limit`, and run single-turn conversations only.
> No credentials are needed for the offline classroom demo: `python scripts/teaching_demo.py`.

**Historical workflow** (original project; the output paths below are the original ones and are no longer
written by the scripts):

1. **Generate model responses**:
   - `python scripts/run_eval_gemini.py`
   - `python scripts/run_eval_llama.py`
2. **Merge responses**:
   - `python scripts/merge_responses.py` → `responses/responses_merged.csv`.
3. **Initialize HIJ sheet**:
   - `python scripts/init_hij_scores.py` → `scores/hij_scores.csv`.
4. **Annotate**:
   - Human raters fill in `rater_id` and `score` in `scores/hij_scores.csv` following `rubrics/hij_evaluation_rubric.md`.
5. **Run LLM-as-evaluator**:
   - `python scripts/aie_llm_scoring.py` → `scores/llm_scores.csv`.
6. **Combine**:
   - `python scripts/combine_scores.py` → `scores/combined_scores.csv`.
7. **Analyze**:
   - Use `combined_scores.csv` for plots, tables, and statistical analysis of human vs LLM scoring across indicators, difficulties, models, and seeds.

This setup gives you a **clean, reproducible pipeline** for aligning human annotations with automated LLM evaluations over the shared L4 Autonomy & Agency prompt suite.

## The final results of the analysis related to model comparison are in the analysis folder. 

> Teaching-fork note: the notebook's saved outputs and `analysis/comparison_chart.png` cannot be reproduced from the committed files. The stale outputs and the hard-coded plotting cell were removed on this branch; see [TEACHING.md](TEACHING.md#historical-files-and-cleanup).

### All of the prompt response CSVs have been created solely from the first 30 prompts in our prompt set and not on the entirety of the roughly 2700 prompt long prompt-set. We hope with more time and better resources, we can use this set as an input to our pipeline.

> Teaching-fork note: in the committed files this means the first 30 *conversations* per indicator
> (270 conversations; 355 prompts per model). The prompt set itself has 2,199 prompts.
