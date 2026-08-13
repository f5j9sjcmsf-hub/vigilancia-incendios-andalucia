import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "data" / "state.json"


def load_state():
    if not STATE_FILE.exists():
        return {"incidents": {}, "last_run": None}

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"No se ha podido leer un estado válido de {STATE_FILE}."
        ) from exc

    if not isinstance(state, dict):
        raise RuntimeError(
            f"El estado guardado en {STATE_FILE} no es un objeto JSON."
        )

    return state


def save_state(state):
    if not isinstance(state, dict):
        raise TypeError("El estado debe ser un diccionario.")

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = STATE_FILE.with_suffix(".json.tmp")
    temporary_file.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_file.replace(STATE_FILE)
