"""The ONE prompt builder, shared by training, evaluation and production.

If training used a different prompt format than production, a fine-tuned model would quietly get
worse. So everything that makes a prompt lives here, versioned, and nothing else builds prompts.
"""

from datetime import UTC, datetime

# v2 (2026-11-07): dropped "tables_used" from the output (saves about 1 s per answer).
PROMPT_VERSION = "v2"

SYSTEM_PROMPT = """You are an expert PostgreSQL analyst. Turn the user's question into ONE \
read-only SELECT query.

Rules:
- Use ONLY the tables and columns listed under "Tables". Never invent names.
- Today is {today}. Never use NOW(), CURRENT_DATE or CURRENT_TIMESTAMP; write dates relative to \
today as TIMESTAMPTZ '{today_sql}'.
- Money columns are integer cents: divide by 100.0 to report dollars.
- Follow the business rules and metric definitions given. Do not select personal data.
- Reply with JSON only, with exactly these keys:
  "sql": the query (a single SELECT, no trailing semicolon),
  "assumptions": list of short strings stating any interpretation you made (for example what \
"this month" means)."""

# Passed to the server as a JSON schema so the output is always parseable.
# Bounded on purpose: without limits a small model rambles inside "assumptions" until it runs out
# of tokens, which truncates the JSON and wastes seconds of latency.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string", "maxLength": 1500},
        "assumptions": {
            "type": "array",
            "items": {"type": "string", "maxLength": 140},
            "maxItems": 3,
        },
    },
    "required": ["sql", "assumptions"],
}


def build_repair_message(error: str, hint: str) -> dict[str, str]:
    """Follow-up turn after a failed attempt: the error, real facts, and the same output format."""
    text = f"That query failed: {error}\n"
    if hint:
        text += f"Facts about the real schema:\n{hint}\n"
    text += "Fix it. Use only real tables and columns. Reply with the same JSON format."
    return {"role": "user", "content": text}


def build_messages(question: str, context: str, today: datetime) -> list[dict[str, str]]:
    """Chat messages for the model: system rules, then context and question."""
    if today.tzinfo is None:
        raise ValueError("today must include a timezone")
    utc = today.astimezone(UTC)
    system = SYSTEM_PROMPT.format(
        today=utc.strftime("%Y-%m-%d %H:%M UTC"),
        today_sql=utc.strftime("%Y-%m-%d %H:%M:%S+00"),
    )
    user = f"{context}\n\n## Question\n{question}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
