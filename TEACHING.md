# Teaching prototype: DS684 AI Ethics, Assignment 3

A small, offline demonstration of how an evaluation moves from an **ethical
construct** to **prompts**, **model responses**, **scoring**, and **comparative
analysis**, and of the validity and reliability questions each step raises.

- Teaching fork: <https://github.com/TheFlashhhh/llm_safety_evaluation_pipeline> (branch `teaching-prototype`)
- Original project and all historical data: <https://github.com/pratrt141098/llm_safety_evaluation_pipeline>.
  See the commit history for authorship. The original repository has no license
  file, and none has been added here; check with the original author before
  redistributing beyond classroom use.

## Quick start (Windows PowerShell, offline)

No API keys, network access, Ollama, or extra packages are needed.

```powershell
git clone https://github.com/TheFlashhhh/llm_safety_evaluation_pipeline.git
cd llm_safety_evaluation_pipeline
git checkout teaching-prototype
python --version                  # 3.10 or newer
python scripts\teaching_demo.py
```

Open `demo\output\walkthrough.md` (VS Code: right-click > *Open Preview*).
The script also writes:

| File | Contents |
|---|---|
| `demo\output\walkthrough.md` | Construct, rubric, prompts, both models' responses, scores, discussion questions, limitations |
| `demo\output\selected_responses.csv` | One row per response with historical judge score/status and human score summary |
| `demo\output\annotation_issues.csv` | Annotation-sheet rows rejected by validation (header only if none) |
| `demo\output\model_comparison.csv`, `agreement.csv` | Written only when enough valid human ratings exist |
| `demo\annotation_sheet.csv` | Blank rating sheet; created on the first run, **never overwritten** |

Everything in `demo\output\` is regenerated on each run. These files are
committed so students can read [the walkthrough](demo/output/walkthrough.md)
directly on GitHub. If you change the script or the annotation sheet, re-run
the script before committing so the committed output matches. To open the historical
notebook instead, install the offline extras first:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt
jupyter notebook analysis\model_comparative_evaluation.ipynb
```

## What the demo contains

- **Indicator:** `L4_HAI_DesignNoCoercion`: does the assistant avoid
  emotional pressure, shaming, fear, or "no real choice" framing when the user
  asks to be coerced?
- **Examples:** 8 single-turn conversations (4 easy: `_01`–`_04`; 4 medium:
  `_11`–`_14`), each with saved responses from `gemini-2.5-flash` and
  `llama3.2:1b`. Single-turn status is taken from the complete prompt set. The
  selection rule (first conversations per difficulty, by number) never looks
  at scores or response text. The script stops with an error if either model's
  response is missing or its prompt text differs from `prompts/prompts.tsv`.
- **Historical judge scores:** shown for Gemini responses, labelled as a
  single historical run. **No Llama judge scores exist in the committed
  files**; the demo shows them as unavailable and never estimates them.
- **Human ratings:** none are committed. The demo runs without them.

## 10–15 minute classroom walkthrough

| Time | Step | Use | Talking points |
|---|---|---|---|
| 0–2 min | **Construct** | Walkthrough §1 | Why coercion matters ethically (autonomy, manipulation, vulnerable users). What the rubric's 1–4 levels operationalize, and what they leave out. Tension: the *user asks* to be pressured. |
| 2–4 min | **Prompts** | §2 and the prompt quotes in §3 | Adversarial prompts, difficulty labels, a transparent selection rule. Why single-turn only. |
| 4–6 min | **Responses** | §3 | Read two or three pairs aloud (for example `_02`, `_04`, `_12`). Notice differences in compliance, refusal style, and length. |
| 6–9 min | **Student scoring** | `demo\annotation_sheet.csv` (it contains no judge scores, so scoring is blind) | Students score 2–3 responses independently against the rubric, then compare with a neighbour. Is a bare "I can't help with that" a 4, given the rubric asks for choice and risk language? |
| 9–11 min | **Historical judge scores** | §3, §4 | Reveal the Gemini judge scores. It saw no rubric and judged its own model's outputs. Llama has no judge scores: what can and cannot be concluded? |
| 11–13 min | **Disagreement** | §5–§6, discussion questions §7 | Where did students disagree with each other and with the judge? Is the disagreement about the response or about the rubric? |
| 13–15 min | **Validity and reliability** | §8 and "Known issues" below | One run, unapplied seed labels, different generation settings, missing context in follow-ups, unreproducible notebook outputs. What would a credible comparison need? |

### Optional: enter ratings and re-run

Fill in `rater_id` and `score` (an integer 1–4) in `demo\annotation_sheet.csv`.
For a second rater, copy the rows and use a different `rater_id`. Then re-run
`python scripts\teaching_demo.py`.

- Invalid rows (scores outside 1–4, a missing rater, duplicates, unknown
  responses) are listed in the walkthrough and in `annotation_issues.csv`, and
  excluded from all statistics.
- Each **response** is one observation; scores from several raters are averaged
  per response before any comparison.
- The model comparison uses only conversations where **both** models have valid
  human scores. Averages are displayed once there are at least 3 such pairs.
  Agreement statistics (between raters, and between humans and the historical
  judge for Gemini responses only) use the same minimum. Otherwise the
  walkthrough says they were skipped and why.
- The 3-pair minimum is **only a display convenience**, so that averages are not
  printed from one or two pairs. It is not evidence that the sample is
  statistically sufficient. All numbers are descriptive of these 8 prompts and
  these raters: the demo reports no significance tests or confidence intervals
  and supports no general model ranking.
- The sheet is saved as UTF-8 with a byte-order mark so Excel displays it
  correctly. If Excel re-saves it in the Windows code page, the script still
  reads it.
- To test with a separate file: `python scripts\teaching_demo.py --sheet path\to\copy.csv --output-dir path\to\out`.

## Historical files and cleanup

Unchanged historical data: `prompts/`, `responses/`, `scores/`, `rubrics/`, and
`analysis/comparison_chart.png`. The scripts refuse to write into these folders.

`analysis/model_comparative_evaluation.ipynb` and `analysis/comparison_chart.png`
are **historical and cannot be reproduced from the committed files**:

- The notebook's saved outputs showed Llama judge scores (`llm_scores shape: (540, 5)`)
  and a human–LLM correlation of 0.582. The committed `scores/llm_scores.csv`
  has 270 Gemini-only rows in every commit, and every human score is blank. Re-run on the
  committed files, the notebook gives Gemini-only results, NaN for Llama, and
  a NaN correlation. The saved Gemini numbers also differ from the committed
  scores. That shows the scores were produced or changed outside the repository; it
  is not, on its own, evidence about the judge's reliability, which would need repeated
  evaluations under recorded conditions.
- The final notebook cell plotted **hand-typed statistics**, some of which
  did not match the notebook's own computed table (for example, Llama
  DesignNoCoercion was typed as 2.99 but computed as 3.75). `comparison_chart.png` matches
  those typed values and is not produced by any committed code.

Cleanup on this branch: the notebook's stale outputs were cleared, the
hard-coded plotting cell was removed, and a note was added at the top. The
remaining code cells are unchanged. The chart image is kept as a historical file.

## Known issues in the historical data (material for validity and reliability discussion)

- **Judge coverage:** committed judge scores cover `gemini-2.5-flash` responses only.
- **Judge prompt:** the historical judge received the indicator ID, the difficulty label, and a
  generic "1 = very unsafe, 4 = fully safe" scale, not the indicator's rubric.
  The judge model was also one of the two models being evaluated.
- **Aggregation:** judge scores were averaged per conversation. The notebook
  then attached that average to every turn, so two-turn conversations were
  counted twice and confidence intervals were too narrow.
- **Follow-ups without context:** turn-2 prompts are scripted in the prompt set, but
  the turn-2 responses were generated **without** the turn-1 exchange (85 of
  270 conversations). Example: `L4_HAI_OverrideAndUndo_21` turn 2 begins "Now
  suggest language…", which the model never had context for.
- **Seeds:** the `seed` column is a label (always 1). It was not passed to
  either API, so it does not make the historical outputs reproducible.
- **Different settings:** Gemini used temperature 0.7, a 2056-token limit, and
  a one-line system prompt joined to the user text. Llama used Ollama's default
  temperature, a 256-token limit, and a different system prompt.
- **Scope:** the README's "first 30 prompts" means the first 30
  *conversations* per indicator: 270 conversations, 355 prompts per model.
- **Duplicate ID:** in `prompts/prompts.tsv`, `L4_HAI_AnthropomorphismDisclosure_293`
  labels two different prompts with conflicting `scenario_type` and difficulty labels.
  Because it has two rows, the single-turn rule excludes it. It is not among the
  conversations with saved responses.
- **Missing files:** the README and rubric mention `aggregate_mixed.py` and
  `mixed_score.py`, which are not in the repository.

## Optional live runs (your own credentials and models)

None of this is needed for the demo. Live outputs go to `runs/`, which is
git-ignored, and are not read by the demo.

- **Gemini** needs your own API key. Google currently limits Gemini 2.5
  models to users who have used them before, so a new key may need a newer
  model ID. Report the model you actually used; results will not match the
  historical `gemini-2.5-flash` data.
- **Llama** needs your own [Ollama](https://ollama.com) installation, running
  locally, with the model pulled (`llama3.2:1b` is about 1.3 GB).

The commands below use **the same 8 conversation IDs as the offline demo**
(listed in `demo\output\selected_responses.csv`), so new responses can be set
beside the historical ones for the same prompts.

```powershell
pip install -r requirements-live.txt
$env:GEMINI_API_KEY = "<your key>"          # current session only; never commit keys
$env:GEMINI_MODEL   = "<a model your key can call>"
$env:JUDGE_MODEL    = "<a model your key can call>"

# The demo's 8 conversations (4 easy, 4 medium)
$ids = "L4_HAI_DesignNoCoercion_01,L4_HAI_DesignNoCoercion_02,L4_HAI_DesignNoCoercion_03,L4_HAI_DesignNoCoercion_04,L4_HAI_DesignNoCoercion_11,L4_HAI_DesignNoCoercion_12,L4_HAI_DesignNoCoercion_13,L4_HAI_DesignNoCoercion_14"

python scripts\run_eval_gemini.py --convo-ids $ids      # runs\raw_responses_gemini.csv
ollama pull llama3.2:1b
python scripts\run_eval_llama.py  --convo-ids $ids      # runs\raw_responses_llama.csv
python scripts\merge_responses.py                       # runs\responses_merged.csv
python scripts\aie_llm_scoring.py --convo-ids $ids --dry-run   # shows the judge prompt; no API call
python scripts\aie_llm_scoring.py --convo-ids $ids      # runs\llm_scores.csv
python scripts\init_hij_scores.py                       # runs\hij_scores.csv (blank)
python scripts\combine_scores.py                        # runs\combined_scores.csv
```

To preview the judge prompt offline on the **historical** responses for the
same IDs, without a key: `python scripts\aie_llm_scoring.py --responses responses\responses_merged.csv --convo-ids $ids --dry-run`.

Other selections: `--indicator <id>` with or without `--limit N` takes the
first N single-turn prompts for that indicator in file order. That is a
different subset from the demo. Optional variables: `OLLAMA_MODEL`,
`OLLAMA_URL`. A second run refuses to overwrite files in `runs\`; pass
`--overwrite` or a new `--out` path.

### What changed in the scripts

- `prompts.tsv` is read as tab-separated; the Llama script reads it too (it
  previously pointed at a non-existent `prompts/prompts.csv` and wrote to `data/`).
- All paths resolve relative to the repository root (`scripts/repo_utils.py`).
- Model IDs are configurable (`--model`, or the `GEMINI_MODEL`, `OLLAMA_MODEL` and `JUDGE_MODEL` environment variables).
- `--convo-ids` (generation and judging) selects exact conversations. IDs that
  are not single-turn in the full prompt set are rejected.
- New outputs default to `runs/`. Scripts refuse to write into the historical
  folders, refuse to overwrite existing files without `--overwrite`, and
  `init_hij_scores.py` never replaces a sheet that already contains scores.
- Generation and judging use **single-turn conversations only**; follow-up
  turns are skipped rather than sent without context. Full multi-turn support
  is not implemented.
- The seed is now passed to Ollama (`options.seed`) and Gemini (`seed`). Gemini
  treats it as best effort and does not guarantee identical outputs.
- The judge now receives the indicator's full rubric section and the global
  1–4 scale (explicit `L4_HAI_*` → rubric-heading mapping), runs at
  temperature 0, and scores each response separately. Every row records
  `judge_status` (`valid`, `parse_failure`, `blocked`, `empty`, `api_error`),
  and only `valid` rows carry a score. The live scripts have not been run
  against real APIs on this branch.
