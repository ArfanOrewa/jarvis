"""Session memory: working window (last N turns) + rolling summary + JSONL transcript."""
import datetime
import json
import time
from pathlib import Path

import config

MAX_TURNS = 12            # verbatim turns kept in context
SUMMARY_EVERY = 10        # compress evicted turns every N evictions
SUMMARY_MAX_TOKENS = 400  # target summary length (rough)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class SessionMemory:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or config.DATA_DIR
        self.turns: list[dict] = []          # [{role, text, ts}]
        self.summary: str = ""
        self._since_summary = 0
        self.session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        # append-only transcript (crash-safe)
        self.transcript_path = config.TRANSCRIPT_FILE
        # load recent session cards for continuity
        self.prior_context = self._load_recent_cards(n=2)

    # -- turns ----------------------------------------------------------
    def add_turn(self, role: str, text: str):
        entry = {"role": role, "text": text, "ts": time.time()}
        self.turns.append(entry)
        self._since_summary += 1
        # append to JSONL transcript
        try:
            with open(self.transcript_path, "a") as f:
                f.write(json.dumps({"session": self.session_id, **entry}) + "\n")
        except OSError:
            pass
        # evict oldest beyond window
        while len(self.turns) > MAX_TURNS:
            self.turns.pop(0)
        return entry

    def set_summary(self, summary: str):
        """Called by the brain after LLM compression of evicted turns."""
        self.summary = summary[:2000]
        self._since_summary = 0

    def needs_summary(self) -> bool:
        return self._since_summary >= SUMMARY_EVERY and len(self.turns) >= MAX_TURNS

    def evicted_text(self) -> str:
        """Text the brain should compress (oldest turns beyond a smaller window)."""
        # keep newest 6 verbatim, summarize the rest when needed
        if len(self.turns) <= 6:
            return ""
        return "\n".join(f"{t['role']}: {t['text']}" for t in self.turns[:-6])

    # -- prompt construction --------------------------------------------
    def context_messages(self) -> list[dict]:
        """Build the message list for the LLM: summary + recent turns."""
        msgs = []
        if self.prior_context:
            msgs.append({"role": "system",
                         "content": "[Continuity from previous sessions]\n" + self.prior_context})
        if self.summary:
            msgs.append({"role": "system",
                         "content": "[Conversation summary so far]\n" + self.summary})
        for t in self.turns:
            msgs.append({"role": t["role"], "content": t["text"]})
        return msgs

    # -- session cards ---------------------------------------------------
    def _load_recent_cards(self, n: int = 2) -> str:
        cards = sorted(config.SESSIONS_DIR.glob("*.json"))
        parts = []
        for p in cards[-n:]:
            try:
                d = json.loads(p.read_text())
                parts.append(f"- {d.get('date')}: {d.get('summary','')}")
            except (OSError, json.JSONDecodeError):
                continue
        return "\n".join(parts)

    def write_session_card(self, summary: str):
        """Persist a session card on exit / periodically."""
        card = {
            "session": self.session_id,
            "date": datetime.datetime.now().isoformat(),
            "summary": summary[:1000],
            "turns": len(self.turns),
        }
        try:
            path = config.SESSIONS_DIR / f"{self.session_id}.json"
            path.write_text(json.dumps(card, indent=2))
        except OSError:
            pass
