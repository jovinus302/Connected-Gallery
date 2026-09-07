"""Public model selection for a synthetic demo, without provider credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re


def validate_demo_model(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) is None:
        raise ValueError("Demo model must be a public model name of 1-128 letters, digits, dots, underscores or hyphens")
    return value


def read_demo_model(root):
    marker = Path(root) / "synthetic-demo.json"
    if not marker.exists():
        return None
    value = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("synthetic") is not True:
        raise ValueError("A marked synthetic gallery is required")
    return validate_demo_model(value["model"]) if "model" in value else None


def apply_demo_model(root):
    model = read_demo_model(root)
    if model is not None:
        os.environ["CG_MODEL"] = model
    return model


def prepare_demo_profile(root, model=None):
    """Preserve existing marker fields; only this preparation helper writes it."""
    root = Path(root)
    marker = root / "synthetic-demo.json"
    if (root / "gallery.sqlite").exists() and not marker.exists():
        raise ValueError("Refusing an existing gallery without the synthetic-demo marker")
    selected = validate_demo_model(model) if model is not None else None
    if marker.exists():
        read_demo_model(root)  # Validate before replacing existing content.
        value = json.loads(marker.read_text(encoding="utf-8"))
    else:
        value = {"synthetic": True, "source": "generated starter gallery"}
    if selected is not None:
        value["model"] = selected
    root.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(marker)
    return apply_demo_model(root)
