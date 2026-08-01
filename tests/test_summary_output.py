"""Two ways the protokoll's filename and body could be wrong.

Both were found by exercising the pipeline hard, and both are silent: the
meeting is transcribed and summarized correctly, and only the document you
end up opening is wrong.

Run with:  .venv\\Scripts\\python -m pytest tests -q
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recorder import (
    TRANSCRIPT_FILENAME,
    clear_previous_protokoll,
    parse_title_from_summary,
    title_to_filename,
)

SUMMARY = "TITLE: Budgetplanering Q3\n\n## Sammanfattning\nText."


# ── The model fences its reply ────────────────────────────────
#
# Mistral intermittently wraps the whole protokoll in ```markdown ... ```.
# The TITLE match is anchored at the start of the reply, so the fence cost
# the meeting its filename and heading and left the raw TITLE line and the
# backticks in the document. Observed on 2026-08-01 with
# mistralai/Mistral-Small-3.2-24B-Instruct-2506.


@pytest.mark.parametrize(
    "reply,expected",
    [
        (SUMMARY, "Budgetplanering Q3"),
        (f"```markdown\n{SUMMARY}\n```", "Budgetplanering Q3"),
        (f"```\n{SUMMARY}\n```", "Budgetplanering Q3"),
        (f"\n\n{SUMMARY}", "Budgetplanering Q3"),
        ("## Sammanfattning\nText.", ""),
        # Closes before the end, so it is not a wrapper and nothing is
        # stripped — and the reply genuinely does not start with a title.
        ("```markdown\nTITLE: Avbruten\n```\nEfterord utanför staketet.", ""),
    ],
)
def test_a_fenced_reply_still_yields_its_title(reply, expected):
    assert parse_title_from_summary(reply)[0] == expected


def test_a_fenced_reply_leaves_no_backticks_in_the_document():
    _, body = parse_title_from_summary(f"```markdown\n{SUMMARY}\n```")
    assert "```" not in body
    assert "TITLE:" not in body


def test_a_fence_inside_the_reply_is_content_and_survives():
    """A meeting that discussed SQL keeps its SQL."""
    reply = ("```markdown\nTITLE: Sprint review\n\n## Mötesanteckningar\n"
             "```sql\nSELECT 1\n```\n```")
    title, body = parse_title_from_summary(reply)
    assert title == "Sprint review"
    assert "```sql" in body
    assert "SELECT 1" in body


def test_the_fenced_title_produces_the_right_filename():
    title, _ = parse_title_from_summary(f"```markdown\n{SUMMARY}\n```")
    assert title_to_filename(title, "2026-04-01_14-31") == \
        "2026-04-01_14-31_budgetplanering-q3.md"


# ── A folder holds exactly one protokoll ──────────────────────
#
# Regenerating a summary produces a different filename whenever the model
# picks a different title. Leaving the old file beside the new one turns
# "which is the protokoll" into a question of which name sorts first.


@pytest.fixture
def folder(tmp_path):
    made = tmp_path / "2026-04-01_14-31"
    made.mkdir()
    (made / TRANSCRIPT_FILENAME).write_text("Rå text.", encoding="utf-8")
    return made


def protokoll_in(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.glob("*.md") if p.name != TRANSCRIPT_FILENAME)


def test_a_previous_protokoll_is_removed(folder):
    (folder / "2026-04-01_14-31_budgetplanering-q3.md").write_text("gammal", encoding="utf-8")
    target = folder / "2026-04-01_14-31_avstämning.md"

    clear_previous_protokoll(folder, keep=target)
    target.write_text("ny", encoding="utf-8")

    assert protokoll_in(folder) == ["2026-04-01_14-31_avstämning.md"]


def test_the_transcript_survives(folder):
    (folder / "2026-04-01_14-31_budgetplanering-q3.md").write_text("gammal", encoding="utf-8")

    clear_previous_protokoll(folder)

    assert (folder / TRANSCRIPT_FILENAME).read_text(encoding="utf-8") == "Rå text."


def test_the_file_being_written_is_kept(folder):
    target = folder / "2026-04-01_14-31_budgetplanering-q3.md"
    target.write_text("samma titel som förra gången", encoding="utf-8")

    clear_previous_protokoll(folder, keep=target)

    assert target.exists()


def test_an_empty_folder_is_not_a_problem(folder):
    clear_previous_protokoll(folder)

    assert protokoll_in(folder) == []
