# Teaching prototype: DS684 AI Ethics, Assignment 3

A small demonstration of how an evaluation moves from an **ethical
construct** to **prompts**, **model responses**, **scoring**, and **comparative
analysis**, and of the validity and reliability questions each step raises.

- **Live demo (primary):** type a new prompt, send it to two models, and have an
  LLM judge score both responses against the rubric:
  `.\.venv\Scripts\python.exe scripts\live_demo.py --judge gemini:gemini-3.5-flash-lite`
  (the tested command). See [Live classroom demo](#live-classroom-demo).
- **Offline demo (fallback):** historical responses, no keys or network:
  `python scripts\teaching_demo.py`. See [Quick start](#quick-start-windows-powershell-offline).

- Teaching fork: <https://github.com/TheFlashhhh/llm_safety_evaluation_pipeline> (branch `teaching-prototype`)
- Original project and all historical data: <https://github.com/pratrt141098/llm_safety_evaluation_pipeline>.
  See the commit history for authorship. The original repository has no license
  file, and none has been added here; check with the original author before
  redistributing beyond classroom use.

## Live classroom demo

One command starts an interactive terminal session:

1. It shows the indicator's construct and 1–4 rubric (default
   `L4_HAI_DesignNoCoercion`; change it with `--indicator`).
2. You type a prompt.
3. The same prompt, with the same system instruction ("Answer in under 75
   words.") and settings, goes to **model A** and **model B**.
4. Both responses are displayed. A **judge model** then scores each response
   separately using the full indicator rubric and the global scale. It returns
   a score from 1 to 4 and a one- or two-sentence explanation.
5. Type another prompt, `:rubric` for the full rubric, or `:quit`.

### Tested classroom command

```powershell
.\.venv\Scripts\python.exe scripts\live_demo.py --judge gemini:gemini-3.5-flash-lite
```

| Role | Model | Runs on |
|---|---|---|
| Model A | `gemini:gemini-3.5-flash-lite` | Gemini API (free tier) |
| Model B | `ollama:llama3.2:1b` | your machine (Ollama) |
| Judge | `gemini:gemini-3.5-flash-lite` | Gemini API (free tier) |

**Test record (6 October 2026, one free-tier key):**

- With this command, a full live session succeeded: two prompts, all four
  responses generated, and all four judgments valid on the first attempt. A
  rejudge of an earlier run with the same judge also succeeded.
- The preset's default judge, `gemini-3.8-flash`, and the alternative
  `gemini-3.7-flash` both returned **503 UNAVAILABLE** ("high demand") on
  every attempt in the same session.
- This shows only what worked on that day for that key. Availability, demand
  and free-tier limits change, so no model is guaranteed to respond in class.
  Run `--check` beforehand and keep the offline demo ready as a fallback.

**Limitation: the judge is also model A.** The judge never sees which model
wrote a response; it receives only the rubric, the prompt, and one response.
But model A and the judge are the same model, so the judge may still recognize
or favour text in its own style (self-preference). Treat any A-versus-B
difference in automated scores with extra caution, and say so in class: it is
a useful example of an evaluation risk. The demo prints a reminder when the
judge is also a generator.

The judge stays configurable. The preset's default (`gemini-3.8-flash`) is
unchanged, and the tested command overrides it explicitly. To use a judge that
did not generate either response, pass another model, for example
`--judge gemini:gemini-3.7-flash` or `--judge gemini:gemini-3.6-flash`, and run
`--check` first. The demo never switches judges on its own. Every result row
records the judge actually used (`judge_spec`) and its attempts.

What the judge sees and how results are handled:

- **Blind:** the judge sees the rubric, the prompt, and one response, but never
  which model wrote it. (A response that names itself, such as "As Gemini…",
  can still reveal its source.)
- **Untrusted text:** the prompt and responses are passed to the judge as
  untrusted data inside tags, with an instruction never to follow anything
  written in them. Tag look-alikes inside the text are neutralized. This
  reduces prompt-injection risk but does not eliminate it.
- **Validation:** the judge must return JSON with an integer score from 1 to 4
  and a non-empty explanation. Anything else is shown as `JUDGE FAILED
  (invalid_output)` and recorded with no score.
- **Failures are never scores:** a failed or blocked generation is shown as
  `GENERATION FAILED` and is not judged. A failed judge call is shown as
  `JUDGE FAILED`. Statuses: `ok`, `truncated`, `blocked`, `empty`, `api_error`,
  `invalid_output`, `not_judged`.
- **Labelled as automated:** every score is marked "AUTOMATED JUDGMENT: one
  LLM's rubric-based opinion, not an objective grade".
- **Saved:** every session writes `runs\live_<UTC timestamp>\`, which is git-ignored:
  - `session.json`: model IDs, presets, system prompts, the judge schema, the
    rubric hash, settings (temperature, token limit, seed, thinking level),
    git commit, and package versions. API keys are never saved.
  - `results.jsonl` and `results.csv`: one row per response, with prompt,
    response, statuses, latencies, score, explanation, and raw judge output.

### Choose a configuration

| Preset | Model A | Model B | Judge | You need |
|---|---|---|---|---|
| `gemini-only` (**least setup**) | `gemini-3.5-flash-lite` | `gemini-3.6-flash` | `gemini-3.8-flash` | A Gemini API key |
| `gemini-ollama` (default) | `gemini-3.5-flash-lite` | `llama3.2:1b` (local) | `gemini-3.8-flash` | A Gemini API key **and** Ollama with `llama3.2:1b` pulled |
| `mock` | fixed MOCK text | fixed MOCK text | fixed MOCK judgment | Nothing. For rehearsing the flow only; the scores are placeholders |

- **`gemini-only`** needs only `pip install` and a key: no installer and no
  model download. All three models come from one developer (Google), so the
  comparison is narrower and the judge may share the generators' biases.
- **`gemini-ollama`** contrasts a hosted model with a small local open-weight
  model from a different developer, which mirrors the original project. It
  needs the Ollama installer and a 1.3 GB model download. A CPU is enough for a
  1B model, but responses will be slower.
- Any model can be overridden: `--model-a`, `--model-b`, `--judge` take
  `gemini:<model id>` or `ollama:<model tag>`. Where an accessible model
  allows it, choose a judge that is not one of the two generators (see the
  self-preference limitation above).
- Model IDs were checked against Google's model list in October 2026. Model
  availability changes; if a call fails with "model not found", pick a current
  ID from <https://ai.google.dev/gemini-api/docs/models>.

**Costs and data:** each prompt makes **4 calls** (2 responses + 2 judgments).
On the Gemini API free tier these calls are free of charge, but Google states
that free-tier content may be used to improve its products, so **no personal
data in prompts**. If billing is enabled on your Google Cloud project, calls are
billed. Free-tier rate limits are shown in AI Studio. Ollama runs locally at no
cost.

### Windows setup (PowerShell, from the repository folder)

**Project environment (once).** This creates a git-ignored `.venv` folder.
Calling its `python.exe` directly avoids PowerShell's script-activation policy.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-live.txt
```

**Gemini key (both live presets).** Create a key at
<https://aistudio.google.com/apikey> without enabling billing; the key's
project then stays on the free tier, which AI Studio shows next to the key.
Then, in the PowerShell window you will present from, run:

```powershell
# Paste the key at the prompt. It is not echoed and not saved in history or files.
$secure = Read-Host "Gemini API key" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new("", $secure).Password
```

The variable lasts only for that PowerShell window. Never commit a key or
paste it into chat or slides.

**Ollama (only for `gemini-ollama`):**

```powershell
winget install --id Ollama.Ollama -e        # or the installer from https://ollama.com/download
# Open a new PowerShell window so `ollama` is on PATH. Ollama runs in the background.
ollama pull llama3.2:1b                     # about 1.3 GB
ollama list                                 # should list llama3.2:1b
```

**Check, then run.** `--check` generates nothing. It confirms the packages,
the key's presence, the Ollama model, and, through a metadata lookup, that each
Gemini model ID is available to your key.

```powershell
# Tested configuration (Gemini + Ollama, judge = gemini-3.5-flash-lite)
.\.venv\Scripts\python.exe scripts\live_demo.py --judge gemini:gemini-3.5-flash-lite --check
.\.venv\Scripts\python.exe scripts\live_demo.py --judge gemini:gemini-3.5-flash-lite

# Preset default judge (gemini-3.8-flash; returned 503 in testing)
.\.venv\Scripts\python.exe scripts\live_demo.py --check
.\.venv\Scripts\python.exe scripts\live_demo.py

# or, without Ollama:
.\.venv\Scripts\python.exe scripts\live_demo.py --preset gemini-only --check
.\.venv\Scripts\python.exe scripts\live_demo.py --preset gemini-only
```

Rehearse without any key: `.\.venv\Scripts\python.exe scripts\live_demo.py --preset mock`.
If anything fails during class, fall back to the offline demo:
`python scripts\teaching_demo.py`.

Useful options:

- `--thinking-level low`: faster Gemini responses (`minimal` works only on Flash-Lite models).
- `--temperature`, `--judge-temperature`, `--seed`: unset means the provider's default.
- `--max-tokens` (default 4096): Gemini thinking tokens count toward this limit.
- `--prompt "..."`: run one prompt without the interactive loop.
- `--judge gemini:<model id>`: use a different judge, for example when the default is overloaded. Check it first with
  `--check`. Prefer a judge that is not one of the two generators; the demo prints a note if it is.

### Busy models, retries, and rejudging

- **Retries:** HTTP 503 (model overloaded) and 429 (rate limited) are retried on
  the **same** model, up to **3 attempts in total**. The wait is about 2 s, then
  4 s, or the server's `Retry-After`/retry delay if it gives one. The demo never
  waits more than 30 s for one retry; a longer requested wait (for example, a
  daily quota) fails immediately. A status line such as
  `[judge for A: gemini-3.8-flash busy (HTTP 503); retrying in 2 s (attempt 2 of 3)]`
  shows that the terminal is not frozen.
- **No retries for permanent errors:** a bad key, missing permission, invalid
  request, unknown model, or a 500 error fails at once.
- **No silent switching:** the demo never falls back to another model. Each row
  records the judge actually used (`judge_spec`) and the number of attempts
  (`generation_attempts`, `judge_attempts`). `session.json` records the retry policy.
- **Rejudge a saved run:** if the responses were generated but the judge failed,
  re-score the saved responses without regenerating them:

  ```powershell
  .\.venv\Scripts\python.exe scripts\live_demo.py --rejudge runs\live_<timestamp> --judge gemini:<model id>
  ```

  Without `--judge`, the original run's judge is used. Results go to a new
  folder, `runs\rejudge_<timestamp>_of_live_<timestamp>\`, whose `session.json`
  links the source run and the SHA-256 hashes of its files. The original
  folder is only read, never modified. Add `--check` to verify the judge first.

### Suggested live flow (10–15 minutes)

1. **Construct (2 min):** read the construct and rubric printed at start-up.
2. **Prompt (2 min):** ask the class for a coercion request ("Push me to…",
   "Make me feel stupid if I don't…"). Avoid personal details.
3. **Responses (3 min):** read both responses. Have students score them with the
   rubric **before** looking at the automated scores.
4. **Automated judgments (3 min):** compare the students' scores with the
   judge's scores and explanations. Where they disagree, is the disagreement
   about the response or about the rubric?
5. **Reliability (3 min):** re-enter the same prompt. Do the responses or
   scores change? What would a credible comparison need (many prompts,
   repeated runs, human ratings, a judge from a different model family)?

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

## Optional batch runs over the prompt set (your own credentials and models)

This is the original pipeline (generate, merge, judge, combine) for many
prompts at once. It is separate from the interactive live demo and not needed
for either demo. Outputs go to `runs/`, which is git-ignored, and are not read
by the offline demo.

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
