"""Answer generation — Ledger prompt 7b (M5): cite exact ids, surface disputes.

answer_question() calls the LLM once with pre-filtered facts. Facts outside the
caller's scope can never appear here — retrieve() guarantees that.
No facts -> deterministic "I don't know" WITHOUT an LLM call.
"""
import json
from datetime import datetime

from .llm_provider import BaseProvider, get_provider

ANSWER_PROMPT = """SYSTEM:
You answer a question using ONLY the facts provided below. These facts have already been
filtered for workspace and privacy — do not second-guess that filtering.
Do not use any fact whose status is 'superseded', 'forgotten', or 'stale' UNLESS the user is
explicitly asking about history or what changed.
If the relevant facts include a status='disputed' entry, say so explicitly and do not pick a side.
The asker is @__ASKER__. Each fact below has ABOUT (who it describes) and SAID-BY
(who stated it) — these are different things. NEVER confuse them: a fact ABOUT alice
SAID-BY @bob means "you told us alice ...", NOT "you are alice". When the asker states
a fact about someone else, say "you said alice ...". Only use second person ("you")
for facts ABOUT the asker. Facts ABOUT other people keep their name ("alice likes ...").
Attribute facts to their authors with @username where it matters.
Cite every fact you use with its [M-number] tag in the answer text.
Return JSON ONLY, no prose, no markdown fences: {"answer": string, "used_ids": [fact uuid strings]}

<memory>
__FACTS__
</memory>

QUESTION:
__QUESTION__
"""


def _fact_block(facts: list[dict]) -> str:
    lines = []
    for i, f in enumerate(facts, 1):
        date = f["valid_from"]
        if isinstance(date, datetime):
            date = date.date().isoformat()
        lines.append(
            f"[M{i}] id={f['id']} status={f['status']} ABOUT={f['subject']} "
            f"SAID-BY=@{f['author']} date={date} conf={f.get('confidence')} :: "
            f"{f['subject']} {f['predicate']} {f['object']}"
        )
    return "\n".join(lines)


def answer_question(question: str, facts: list[dict],
                    provider: BaseProvider | None = None,
                    owner_hint: str | None = None,
                    asker: str | None = None) -> dict:
    """Returns {answer, used_ids}. used_ids is always a subset of fact ids."""
    valid_ids = {f["id"] for f in facts}
    if not facts:
        suggestion = f" Ask @{owner_hint} — they may own this domain." if owner_hint else ""
        return {"answer": f"I don't know.{suggestion}", "used_ids": []}
    prov = get_provider(provider)
    if prov is None:  # offline: deterministic extractive fallback
        top = facts[0]
        return {"answer": f"{top['subject']} {top['predicate']} {top['object']} [M1]",
                "used_ids": [top["id"]]}
    prompt = (ANSWER_PROMPT
              .replace("__FACTS__", _fact_block(facts))
              .replace("__QUESTION__", question.strip())
              .replace("__ASKER__", asker or "unknown"))
    try:
        data = json.loads(prov.generate(prompt))
        answer = str(data.get("answer", "")).strip()
        used = [u for u in (data.get("used_ids") or []) if u in valid_ids]
    except Exception:
        answer, used = "", []
    if not answer:
        top = facts[0]
        answer, used = (f"{top['subject']} {top['predicate']} {top['object']} [M1]",
                        [top["id"]])
    return {"answer": answer, "used_ids": used}
