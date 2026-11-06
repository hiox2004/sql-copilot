"""Dev/test split of the golden set, by TEMPLATE (paraphrases of one question stay together).

Why a hash and not a hand-picked list: nobody (including us) can nudge a hard question into the
dev side. The rule is fixed forever, so a template's side never changes when questions are added.

Use "dev" for every tuning decision (prompt, model, repair loop). Touch "test" only to report a
final number, otherwise the test score stops being an honest estimate.
"""

import hashlib

TEST_PERCENT = 35
# Salt 10 was picked from 0..299 as the one giving the most even easy/medium/hard mix on both sides
# (chosen from question difficulty only, before any model result was looked at). Never change it.
SALT = 10


def split_of(template: str) -> str:
    digest = hashlib.sha256(f"{SALT}:{template}".encode()).digest()
    return "test" if digest[0] * 100 // 256 < TEST_PERCENT else "dev"
