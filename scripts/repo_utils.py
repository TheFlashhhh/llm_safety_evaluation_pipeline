"""Shared paths, prompt loading, rubric lookup, and write-protection helpers.

All paths resolve relative to the repository root, so scripts behave the same
no matter which directory they are launched from.
"""

import csv
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_TSV = ROOT / "prompts" / "prompts.tsv"
RUBRIC_MD = ROOT / "rubrics" / "hij_evaluation_rubric.md"
RESPONSES_DIR = ROOT / "responses"
SCORES_DIR = ROOT / "scores"

# New live-run outputs go here, never into the historical folders below.
RUNS_DIR = ROOT / "runs"

# Committed historical data. Scripts refuse to write anywhere inside these.
HISTORICAL_DIRS = [ROOT / "prompts", RESPONSES_DIR, SCORES_DIR, ROOT / "rubrics"]
HISTORICAL_FILES = [ROOT / "analysis" / "comparison_chart.png"]

# Data files use L4_HAI_* IDs; rubric headings drop the underscores.
RUBRIC_HEADINGS = {
    "L4_HAI_DesignNoCoercion": "L4HAIDesignNoCoercion",
    "L4_HAI_DarkPatternAudit": "L4HAIDarkPatternAudit",
    "L4_HAI_AgencyRespectInTests": "L4HAIAgencyRespectInTests",
    "L4_HAI_OverrideAndUndo": "L4HAIOverrideAndUndo",
    "L4_HAI_DeceptiveAnthropomorphism": "L4HAIDeceptiveAnthropomorphism",
    "L4_HAI_AnthropomorphismDisclosure": "L4HAIAnthropomorphismDisclosure",
    "L4_HAI_IdentityControls": "L4HAIIdentityControls",
    "L4_HAI_MinorsAntiPersuasion": "L4HAIMinorsAntiPersuasion",
    "L4_HAI_MinorsDefaultPrivate": "L4HAIMinorsDefaultPrivate",
}


def resolve(path) -> Path:
    """Resolve a user-supplied path relative to the repository root."""
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def load_prompts(path=PROMPTS_TSV):
    """Load the prompt set. The file is tab-separated, not comma-separated."""
    with open(resolve(path), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def single_turn_convo_ids(prompts):
    """Conversations with exactly one prompt row in the complete prompt set."""
    turns = Counter(p["convo_id"] for p in prompts)
    return {
        p["convo_id"]
        for p in prompts
        if turns[p["convo_id"]] == 1 and p.get("scenario_type") == "single_turn"
    }


def parse_convo_ids(text):
    """Parse a comma-separated --convo-ids argument."""
    return [c.strip() for c in text.split(",") if c.strip()]


def select_single_turn_prompts(prompts, indicator=None, limit=None, convo_ids=None):
    """User prompts from single-turn conversations, optionally filtered.

    Follow-up turns are skipped because these scripts send each prompt on its
    own, without earlier turns, so a follow-up would lack its context.
    """
    single = single_turn_convo_ids(prompts)
    if convo_ids:
        not_single = sorted(set(convo_ids) - single)
        if not_single:
            raise SystemExit(f"Not single-turn conversations in the prompt set: {', '.join(not_single)}")
    selected = [
        p for p in prompts
        if p["role"] == "user"
        and p["convo_id"] in single
        and (indicator is None or p["indicator_id"] == indicator)
        and (not convo_ids or p["convo_id"] in convo_ids)
    ]
    return selected[:limit] if limit else selected


@lru_cache(maxsize=None)
def _rubric_sections():
    text = RUBRIC_MD.read_text(encoding="utf-8").replace("\r\n", "\n")
    sections = {}
    for block in re.split(r"\n-{3,}\n", text):
        m = re.search(r"^## (.+)$", block, flags=re.MULTILINE)
        if m:
            sections[m.group(1).strip()] = block.strip()
    return sections


def rubric_for(indicator_id):
    """Return (global 1-4 scale, full indicator-specific rubric section)."""
    heading = RUBRIC_HEADINGS.get(indicator_id)
    if heading is None:
        raise KeyError(f"No rubric mapping for indicator {indicator_id!r}")
    sections = _rubric_sections()
    if heading not in sections:
        raise KeyError(f"Rubric heading {heading!r} not found in {RUBRIC_MD.name}")
    global_scale = next(v for k, v in sections.items() if k.startswith("Global"))
    return global_scale, sections[heading]


def has_filled_column(path, column="score"):
    """True if any row in the CSV has a non-blank value in `column`."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return any((row.get(column) or "").strip() for row in csv.DictReader(f))


def check_output_path(path, overwrite=False):
    """Validate an output path and create its folder.

    Refuses historical files and folders outright, and refuses existing files
    unless `overwrite` is set.
    """
    path = resolve(path)
    for d in HISTORICAL_DIRS:
        if path == d or d in path.parents:
            raise SystemExit(
                f"Refusing to write {path}: {d.name}/ holds historical data. "
                f"Write to {RUNS_DIR.name}/ instead."
            )
    if path in HISTORICAL_FILES:
        raise SystemExit(f"Refusing to overwrite historical file {path}.")
    if path.exists() and not overwrite:
        raise SystemExit(
            f"{path} already exists. Choose another --out path or pass --overwrite."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
