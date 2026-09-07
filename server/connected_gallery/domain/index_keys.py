"""Stable identities for mechanically derived search representations."""
import hashlib
import json


def image_key(photo_id, version, space):
    return f"{photo_id}:image:{version}:{space}"


def text_key(photo_id, text, space):
    return f"{photo_id}:text:{hashlib.sha256(text.encode()).hexdigest()}:{space}"


def region_key(photo_id, version, box, space):
    if box.x == box.y == 0 and box.width == box.height == 1:
        return image_key(photo_id, version, space)
    value = json.dumps([version, box.model_dump(), space], sort_keys=True)
    return f"{photo_id}:region:{hashlib.sha256(value.encode()).hexdigest()}"
