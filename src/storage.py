import json
from pathlib import Path

STATE_FILE = Path("data/state.json")

def load_state():
    if not STATE_FILE.exists():
        return {"incidents": {}, "last_run": None}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
