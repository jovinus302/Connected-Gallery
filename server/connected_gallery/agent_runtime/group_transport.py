"""Decode JSON container transport only where the submitted schema expects one."""
from __future__ import annotations

import json

MAX_CONTAINER_JSON_LENGTH = 65536


def _schema(schema, root):
    reference = schema.get("$ref", "")
    if reference.startswith("#/"):
        node = root
        for part in reference[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node
    return schema


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("Non-JSON numeric constant")


def decode_containers(value, schema, root=None):
    """Never parse scalar strings, wrap objects, fill fields or remove members."""
    root = schema if root is None else root
    schema = _schema(schema, root)
    expected = schema.get("type")
    if expected in ("array", "object") and isinstance(value, str):
        if len(value) > MAX_CONTAINER_JSON_LENGTH:
            return value
        try:
            decoded = json.loads(value, object_pairs_hook=_pairs, parse_constant=_constant)
        except (ValueError, RecursionError):
            return value  # Leave malformed data for the ordinary model validator.
        if (expected == "array" and isinstance(decoded, list)) or (expected == "object" and isinstance(decoded, dict)):
            value = decoded
    if expected == "array" and isinstance(value, list):
        return [decode_containers(item, schema.get("items", {}), root) for item in value]
    if expected == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        return {key: decode_containers(item, properties[key], root) if key in properties else item
                for key, item in value.items()}
    return value


def container_shapes(value, schema, root=None, path=()):
    """Diagnostics contain only trusted schema paths and input type/length."""
    root = schema if root is None else root
    schema = _schema(schema, root)
    expected = schema.get("type")
    rows = []
    if expected in ("array", "object"):
        row = {"path": list(path), "expected": expected, "actual_type": type(value).__name__}
        if isinstance(value, (dict, list, str)):
            row["length"] = len(value)
        rows.append(row)
    if expected == "array" and isinstance(value, list):
        for index, item in enumerate(value[:24]):
            rows.extend(container_shapes(item, schema.get("items", {}), root, (*path, index)))
    if expected == "object" and isinstance(value, dict):
        for key, definition in schema.get("properties", {}).items():
            if key in value:
                rows.extend(container_shapes(value[key], definition, root, (*path, key)))
    return rows[:64]
