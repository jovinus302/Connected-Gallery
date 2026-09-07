"""Public model selection for a synthetic demo, without provider credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re


MAX_COMPATIBLE_CONNECTION_MODELS = 4


def validate_demo_model(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) is None:
        raise ValueError("Demo model must be a public model name of 1-128 letters, digits, dots, underscores or hyphens")
    return value


def normalize_compatible_connection_models(value, *, primary=None):
    """Public, explicit cache namespaces only; never provider fallback models."""
    if not isinstance(value, list):
        raise ValueError("Compatible connection models must be a list of public model names")
    normalized = []
    for item in value:
        model = validate_demo_model(item)
        if model != primary and model not in normalized:
            normalized.append(model)
    if len(normalized) > MAX_COMPATIBLE_CONNECTION_MODELS:
        raise ValueError("At most 4 compatible connection models are allowed")
    return normalized


def connection_models(primary=None):
    """Search the active model first, then explicitly configured old namespaces."""
    primary = validate_demo_model(primary if primary is not None else os.getenv("CG_MODEL", "gpt-5.4-mini"))
    raw = os.environ.get("CG_COMPATIBLE_CONNECTION_MODELS")
    try:
        compatible = json.loads(raw) if raw is not None else []
    except (TypeError, json.JSONDecodeError):
        raise ValueError("Compatible connection models must be a JSON list of public model names") from None
    return [primary, *normalize_compatible_connection_models(compatible, primary=primary)]


def read_demo_models(root):
    """Validate the complete public profile before changing environment or file."""
    marker = Path(root) / "synthetic-demo.json"
    if not marker.exists():
        return None
    value = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("synthetic") is not True:
        raise ValueError("A marked synthetic gallery is required")
    models = {key: validate_demo_model(value[key]) for key in ("model", "context_model") if key in value}
    if "compatible_connection_models" in value:
        models["compatible_connection_models"] = normalize_compatible_connection_models(
            value["compatible_connection_models"], primary=models.get("model"))
    return models


def read_demo_model(root):
    return (read_demo_models(root) or {}).get("model")


def public_demo_marker(root, *, default_model=None):
    models = read_demo_models(root) or {}
    if "model" not in models and default_model is not None:
        models["model"] = validate_demo_model(default_model)
    if "compatible_connection_models" in models:
        models["compatible_connection_models"] = normalize_compatible_connection_models(
            models["compatible_connection_models"], primary=models.get("model"))
    return {"synthetic": True, "source": "generated starter gallery", **models}


def effective_context_model():
    selected = os.environ.get("CG_CONTEXT_MODEL")
    return validate_demo_model(selected if selected is not None else os.getenv("CG_MODEL", "gpt-5.4-mini"))


def apply_demo_model(root):
    models = read_demo_models(root)
    if models is None:
        os.environ.pop("CG_COMPATIBLE_CONNECTION_MODELS", None)
        return None
    model = models.get("model")
    if model is not None:
        os.environ["CG_MODEL"] = model
    # A different marked gallery without an override inherits its own primary
    # model, never a context override left by the previously opened gallery.
    if "context_model" in models:
        os.environ["CG_CONTEXT_MODEL"] = models["context_model"]
    else:
        os.environ.pop("CG_CONTEXT_MODEL", None)
    if "compatible_connection_models" in models:
        compatible = normalize_compatible_connection_models(
            models["compatible_connection_models"], primary=model or os.getenv("CG_MODEL", "gpt-5.4-mini"))
        os.environ["CG_COMPATIBLE_CONNECTION_MODELS"] = json.dumps(compatible)
    else:
        os.environ.pop("CG_COMPATIBLE_CONNECTION_MODELS", None)
    return model


def prepare_demo_profile(root, model=None, *, context_model=None, compatible_connection_models=None):
    """Preserve existing marker fields; only this preparation helper writes it."""
    root = Path(root)
    marker = root / "synthetic-demo.json"
    if (root / "gallery.sqlite").exists() and not marker.exists():
        raise ValueError("Refusing an existing gallery without the synthetic-demo marker")
    selected = validate_demo_model(model) if model is not None else None
    selected_context = validate_demo_model(context_model) if context_model is not None else None
    if marker.exists():
        read_demo_models(root)  # Validate before replacing existing content.
        value = json.loads(marker.read_text(encoding="utf-8"))
    else:
        value = {"synthetic": True, "source": "generated starter gallery"}
    if selected is not None:
        value["model"] = selected
    if selected_context is not None:
        value["context_model"] = selected_context
    if compatible_connection_models is not None:
        value["compatible_connection_models"] = compatible_connection_models
    if "compatible_connection_models" in value:
        value["compatible_connection_models"] = normalize_compatible_connection_models(
            value["compatible_connection_models"], primary=value.get("model"))
    root.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(marker)
    return apply_demo_model(root)
