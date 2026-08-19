"""What an agent cost, and when the environment will let us work again.

Two capabilities the runner needed and did not have.

**Token accounting.** `ORCHESTRATOR_SPEC.md` §REPORT.md has always specified a
`tokens` column and it was never implemented, because `claude -p` was invoked
without `--output-format`, so the transcript was the final text message and
nothing else. Five runs produced no cost data at all, which made every
model-tier decision guesswork.

**When the usage window reopens.** run-20260818-2244 died because four agents
printed `You're out of extra usage · resets 3:30am` and the runner had no way
to read that sentence. `rate_limit.max_backoff_seconds` was 900 — fifteen
minutes against a window measured in hours.

The parsers are deliberately forgiving. If the CLI's output schema shifts, the
extractor must degrade to "no usage recorded" and the transcript must survive
unchanged — a harness that hard-fails on an unrecognised line is worse than one
that reports nothing.
"""

from datetime import datetime

import pytest

from orchestrator.agent import (
    extract_text, extract_usage, parse_reset_delay_seconds,
)
from orchestrator.gates.review import parse_findings


# A `--output-format stream-json --verbose` session, trimmed to its shape.
STREAM_JSON = "\n".join([
    '{"type":"system","subtype":"init","model":"claude-sonnet-5","tools":["Bash"]}',
    '{"type":"assistant","message":{"content":[{"type":"text","text":"Reading the ticket."}]}}',
    '{"type":"assistant","message":{"content":['
    '{"type":"text","text":"Now the tests."},'
    '{"type":"tool_use","name":"Bash","input":{"command":"pytest"}}]}}',
    '{"type":"user","message":{"content":[{"type":"tool_result","content":"4 passed"}]}}',
    '{"type":"result","subtype":"success","is_error":false,"duration_ms":812345,'
    '"num_turns":37,"result":"T14 complete.","total_cost_usd":1.8342,'
    '"usage":{"input_tokens":4211,"output_tokens":90210,'
    '"cache_creation_input_tokens":128400,"cache_read_input_tokens":2950111}}',
])

SINGLE_JSON = (
    '{"type":"result","subtype":"success","is_error":false,"duration_ms":42000,'
    '"num_turns":9,"result":"T09 complete.","total_cost_usd":0.25,'
    '"usage":{"input_tokens":100,"output_tokens":2000,'
    '"cache_creation_input_tokens":5000,"cache_read_input_tokens":60000}}'
)


# ── token accounting ─────────────────────────────────────────────────────────

def test_usage_is_extracted_from_a_stream_json_transcript():
    usage = extract_usage(STREAM_JSON)

    assert usage is not None
    assert usage.input_tokens == 4211
    assert usage.output_tokens == 90210
    assert usage.cache_creation_tokens == 128400
    assert usage.cache_read_tokens == 2950111
    assert usage.cost_usd == pytest.approx(1.8342)
    assert usage.num_turns == 37


def test_usage_is_extracted_from_a_single_json_transcript():
    """`--output-format json` emits one object rather than a stream."""
    usage = extract_usage(SINGLE_JSON)

    assert usage is not None
    assert usage.output_tokens == 2000
    assert usage.cost_usd == pytest.approx(0.25)


def test_total_tokens_counts_every_class_of_input():
    """Cache reads are the bulk of a long agent session and are billed.

    Reporting only `input_tokens` would show 4k against a session that actually
    moved three million, which is worse than reporting nothing.
    """
    usage = extract_usage(STREAM_JSON)

    assert usage.total_tokens == 4211 + 90210 + 128400 + 2950111


def test_a_plain_text_transcript_yields_no_usage_rather_than_raising():
    """Graceful degradation: an unrecognised format costs the tokens column,
    not the run."""
    assert extract_usage("T14 complete.\nNothing structured here.\n") is None


def test_a_truncated_stream_yields_no_usage_rather_than_raising():
    """A killed agent never emits its `result` line."""
    truncated = "\n".join(STREAM_JSON.splitlines()[:3]) + '\n{"type":"assis'

    assert extract_usage(truncated) is None


def test_usage_adds():
    """A ticket's cost is its agent plus its reviews plus its fix rounds."""
    a = extract_usage(STREAM_JSON)
    b = extract_usage(SINGLE_JSON)

    total = a + b

    assert total.output_tokens == 90210 + 2000
    assert total.cost_usd == pytest.approx(1.8342 + 0.25)
    assert total.num_turns == 37 + 9


# ── the transcript stays readable ────────────────────────────────────────────

def test_assistant_text_is_reconstructed_from_stream_json():
    """Everything downstream — the findings parser, the retry tail, the human
    at 8am — reads prose. Structured output must not cost us that."""
    text = extract_text(STREAM_JSON)

    assert "Reading the ticket." in text
    assert "Now the tests." in text
    assert "T14 complete." in text
    assert '"type":"assistant"' not in text, "raw JSON leaked into the transcript"


def test_plain_text_passes_through_unchanged():
    plain = "## Standards\n\nNothing to report.\n"

    assert extract_text(plain) == plain


def test_the_findings_block_survives_the_round_trip():
    """The review gate greps the transcript for a fenced block. If structured
    output buries that block in a JSON string literal, every review silently
    returns zero findings and every ticket merges unreviewed."""
    review = (
        '{"type":"result","subtype":"success","num_turns":4,"total_cost_usd":0.1,'
        '"result":"## Standards\\n\\nOne finding.\\n\\n```findings\\n'
        'standards | 1.1 | - | UI import in Working/\\n```\\n",'
        '"usage":{"input_tokens":1,"output_tokens":2,'
        '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}'
    )

    findings = parse_findings(extract_text(review))

    assert len(findings) == 1
    assert findings[0].axis == "standards"
    assert findings[0].rule == "1.1"


# ── when the window reopens ──────────────────────────────────────────────────

NOW = datetime(2026, 8, 19, 23, 10, 0)


def test_an_exhaustion_message_yields_the_seconds_until_reset():
    transcript = "You're out of extra usage · resets 3:30am (Australia/Brisbane)"

    delay = parse_reset_delay_seconds(transcript, now=NOW)

    # 23:10 -> 03:30 the next day is 4h20m.
    assert delay == pytest.approx((4 * 60 + 20) * 60, abs=60)


def test_an_afternoon_reset_is_parsed_as_pm():
    transcript = "You're out of extra usage · resets 3:30pm (Australia/Brisbane)"

    delay = parse_reset_delay_seconds(transcript, now=datetime(2026, 8, 19, 11, 0))

    assert delay == pytest.approx((4 * 60 + 30) * 60, abs=60)


def test_a_reset_time_already_past_today_rolls_to_tomorrow():
    """`resets 3:30am` read at 4am means tomorrow, not sixteen hours ago."""
    delay = parse_reset_delay_seconds(
        "resets 3:30am", now=datetime(2026, 8, 19, 4, 0))

    assert delay > 0
    assert delay == pytest.approx((23 * 60 + 30) * 60, abs=60)


def test_a_reset_time_on_the_hour_is_parsed():
    delay = parse_reset_delay_seconds("resets 5pm", now=datetime(2026, 8, 19, 16, 0))

    assert delay == pytest.approx(3600, abs=60)


def test_a_transcript_with_no_reset_time_yields_none():
    """A plain 429 carries no reset sentence; the caller falls back to its
    exponential backoff rather than inventing a wait."""
    assert parse_reset_delay_seconds("api_error: overloaded", now=NOW) is None


def test_a_reset_delay_is_never_negative_or_absurd():
    """Whatever the sentence says, the runner must not sleep past its own night."""
    delay = parse_reset_delay_seconds("resets 12:00am", now=datetime(2026, 8, 19, 23, 59))

    assert 0 < delay <= 24 * 3600


# ── a killed agent still leaves something to read ────────────────────────────
#
# `subprocess.run(capture_output=True, timeout=...)` returns no stdout at all on
# Windows when the timeout fires. That is why T35's transcript was 69 bytes and
# its diagnosis took a branch inspection rather than a log read. The *watched*
# path was rewritten to use a file sink; the unwatched one — which is what the
# review and fix agents use — was left, so a reviewer that hung burned its full
# thirty minutes and left nothing behind.

def test_a_killed_unwatched_agent_keeps_what_it_printed(tmp_path):
    """The review and fix agents take this path: no commits to watch, so no
    stall detection, but the budget can still fire."""
    import sys
    import textwrap

    from orchestrator.agent import run_agent

    script = tmp_path / "chatty.py"
    script.write_text(textwrap.dedent("""
        import sys, time
        print("I am about to hang", flush=True)
        time.sleep(60)
    """), encoding="utf-8")

    result = run_agent([sys.executable, str(script)], cwd=tmp_path, prompt="p",
                       model="m", budget_minutes=1 / 60)   # 1 s

    assert result.timed_out
    assert "I am about to hang" in result.transcript, (
        "output printed before the kill was lost — the defect FOLLOWUPS.md "
        "records as [open]"
    )
    assert "exceeded its" in result.transcript, "the kill must say so in the log"
