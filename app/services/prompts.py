import yaml
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(name: str) -> dict:
    with open(PROMPTS_DIR / name, "r") as f:
        return yaml.safe_load(f)
