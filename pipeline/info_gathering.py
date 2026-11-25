"""Concept: Info-Gathering Node — the first LLM call in the customer-turn
graph (Section 4).

Job of this node, and *only* this node: look at the full conversation and
decide whether there's enough information to act. If not, produce a single
clarifying question and stop the turn there. It deliberately does NOT
produce the structured `CompactedTicketInfo` — that's the Context
Compaction node's job (pipeline/compaction.py). Keeping these separate is
the teaching point: "enough info to proceed?" and "what exactly is the
structured ticket?" are different questions, and conflating them into one
LLM call makes both harder to prompt for and to test.
"""
from llm.client import complete_json
from pipeline.state import SessionState, now_iso

SYSTEM_PROMPT = """You are the info-gathering step of a customer support bot.

Read the full conversation so far and extract what the customer has told
you. Do not solve the issue and do not decide whether it is complete — the
code that calls you does that from the fields below.

Respond with ONLY a JSON object, no markdown fences, no commentary:
{
  "issue_type": "billing" | "refund" | "other" | "unclear",
  "issue_described": true | false,   // has the customer said what the problem is?
  "order_id": string | null,         // e.g. "ORD-1003", exactly as given
  "refund_amount": number | null     // rupee amount the customer wants back
}

Use "billing" for charges, payments, invoices. Use "refund" when the
customer asks for money back or a return. Use "other" for account,
technical, or anything else. Use "unclear" only if you cannot tell.
"""


def _missing_fields(result: dict) -> list:
    """Decide completeness in code, not in the prompt, so the same facts
    always give the same answer."""
    issue_type = result.get("issue_type")
    missing = []
    if not result.get("issue_described") or issue_type == "unclear":
        missing.append("a description of the issue")
    if issue_type in ("billing", "refund") and not result.get("order_id"):
        missing.append("the order ID")
    if issue_type == "refund" and result.get("refund_amount") in (None, 0):
        missing.append("the refund amount in rupees")
    return missing


def _clarifying_question(missing: list) -> str:
    if len(missing) == 1:
        return f"Could you share {missing[0]}?"
    return f"Could you share {', '.join(missing[:-1])} and {missing[-1]}?"


def _format_transcript(history: list) -> str:
    lines = [f"{m['role']}: {m['content']}" for m in history]
    return "\n".join(lines)


def run(state: SessionState) -> SessionState:
    transcript = _format_transcript(state["conversation_history"])
    result = complete_json(SYSTEM_PROMPT, transcript)

    missing = _missing_fields(result)
    info_complete = not missing

    if not info_complete:
        state["conversation_history"].append(
            {"role": "assistant", "content": _clarifying_question(missing), "timestamp": now_iso()}
        )

    state["awaiting_clarification"] = not info_complete
    return state
