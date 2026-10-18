"""Long-term memory: file-based fact store with keyword recall and a privacy sanitizer."""
import json
import os
import re
import time
import uuid
from pathlib import Path

import config

# ---------------------------------------------------------------------------
# Privacy sanitizer — runs BEFORE anything is stored or sent to the LLM.
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|pwd|api[_-]?key|secret|client[_-]?secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(password|passwd|pwd|api[ _-]?key|secret)\s+is\s+\S+"),
    re.compile(r"(?i)\b(bearer|token)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),          # card numbers
    re.compile(r"(?i)\botp\b.{0,10}\b\d{6}\b"),                       # OTP codes
    re.compile(r"\b[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),  # JWT-ish
]


def _shannon_entropy(s: str) -> float:
    import math
    from collections import Counter
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def contains_secret(text: str) -> bool:
    """True if text looks like it contains a secret that must never be stored."""
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            return True
    # high-entropy alphanumeric runs (API keys, tokens)
    for token in re.findall(r"[A-Za-z0-9_\-]{16,}", text):
        if _shannon_entropy(token) > 4.5 and re.search(r"\d", token) and re.search(r"[A-Za-z]", token):
            return True
    return False


# ---------------------------------------------------------------------------
# Memory store
# ---------------------------------------------------------------------------

CATEGORIES = {"preference", "person", "project", "schedule", "device", "fact"}


class Memory:
    """JSON-file fact store. Keyword recall, supersede-on-update, atomic writes."""

    def __init__(self, path: Path | None = None):
        self.path = path or config.MEMORY_FILE
        self._facts: list[dict] = []
        self.load()

    # -- persistence ----------------------------------------------------
    def load(self):
        try:
            self._facts = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._facts = []

    def save(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._facts, indent=2))
        os.replace(tmp, self.path)

    # -- write ----------------------------------------------------------
    def remember(self, fact: str, category: str = "fact", confidence: float = 1.0) -> str:
        fact = fact.strip()
        if not fact:
            return "Nothing to remember."
        if contains_secret(fact):
            return "I can't store that — it looks like a secret (password, key, or token)."
        if category not in CATEGORIES:
            category = "fact"
        now = time.time()
        # dedupe: supersede near-identical existing fact
        norm = re.sub(r"\W+", " ", fact.lower()).strip()
        for f in self._facts:
            if f.get("superseded_by"):
                continue
            if re.sub(r"\W+", " ", f["fact"].lower()).strip() == norm:
                return f"Already remembered: {f['fact']}"
        # explicit facts never silently overwritten by inferred ones
        entry = {
            "id": uuid.uuid4().hex[:8],
            "fact": fact,
            "category": category,
            "confidence": confidence,
            "created": now,
            "updated": now,
            "access_count": 0,
        }
        self._facts.append(entry)
        self.save()
        return f"Remembered: {fact}"

    def forget(self, query: str) -> str:
        """Remove facts matching query. Returns what was removed."""
        q = query.lower()
        removed = [f for f in self._facts
                   if q in f["fact"].lower() and not f.get("superseded_by")]
        if not removed:
            return f"I don't have anything stored about '{query}'."
        ids = {f["id"] for f in removed}
        self._facts = [f for f in self._facts if f["id"] not in ids]
        self.save()
        return "Forgot: " + "; ".join(f["fact"] for f in removed)

    def update(self, old_query: str, new_fact: str) -> str:
        """Supersede old fact with new one (never mutate in place)."""
        if contains_secret(new_fact):
            return "I can't store that — it looks like a secret."
        q = old_query.lower()
        target = next((f for f in self._facts
                       if q in f["fact"].lower() and not f.get("superseded_by")), None)
        now = time.time()
        entry = {
            "id": uuid.uuid4().hex[:8],
            "fact": new_fact.strip(),
            "category": target["category"] if target else "fact",
            "confidence": 1.0,
            "created": now,
            "updated": now,
            "access_count": 0,
        }
        if target:
            entry["supersedes"] = target["id"]
            target["superseded_by"] = entry["id"]
        self._facts.append(entry)
        self.save()
        return f"Updated: {new_fact.strip()}"

    # -- read -----------------------------------------------------------
    def recall(self, query: str, k: int = 5) -> list[dict]:
        """Keyword recall: token overlap + preference boost + recency tiebreak."""
        qtokens = set(re.findall(r"\w+", query.lower()))
        if not qtokens:
            return []
        scored = []
        for f in self._facts:
            if f.get("superseded_by"):
                continue
            ftokens = set(re.findall(r"\w+", f["fact"].lower()))
            overlap = len(qtokens & ftokens)
            if overlap == 0:
                continue
            score = overlap * 2.0
            if f["category"] == "preference":
                score += 1.5
            score += min(f.get("access_count", 0) * 0.1, 1.0)
            scored.append((score, f))
        scored.sort(key=lambda s: (-s[0], -s[1].get("updated", 0)))
        results = [f for _, f in scored[:k]]
        for f in results:
            f["access_count"] = f.get("access_count", 0) + 1
        if results:
            self.save()
        return results

    def all(self, include_superseded: bool = False) -> list[dict]:
        if include_superseded:
            return list(self._facts)
        return [f for f in self._facts if not f.get("superseded_by")]

    def facts_for_prompt(self, query: str, k: int = 5) -> str:
        """Render top-k facts as a prompt block. Empty string if none."""
        results = self.recall(query, k)
        if not results:
            return ""
        lines = ["[User facts — use these when relevant]"]
        for f in results:
            lines.append(f"- ({f['category']}) {f['fact']}")
        return "\n".join(lines)
