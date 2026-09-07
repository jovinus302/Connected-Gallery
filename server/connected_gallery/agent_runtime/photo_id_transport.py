"""Compact opaque photo IDs only at the model boundary; repository IDs stay unchanged."""
import re


class PhotoIdTransport:
    def __init__(self, photo_ids):
        actual = set(photo_ids)
        self.forward = {}
        for index, pid in enumerate(sorted(actual)):
            alias = f"__cg_photo_{index:04d}__"
            if len(pid) > 32 and alias not in actual:
                self.forward[pid] = alias
        self.reverse = {value: key for key, value in self.forward.items()}
        self.out_pattern = self._pattern(self.forward)
        self.in_pattern = self._pattern(self.reverse)

    @staticmethod
    def _pattern(mapping):
        return re.compile(r"(?<![A-Za-z0-9_-])(?:" + "|".join(re.escape(k) for k in mapping) + r")(?![A-Za-z0-9_-])") if mapping else None

    def _rewrite(self, value, mapping, pattern):
        if pattern is None:
            return value
        if isinstance(value, str):
            return pattern.sub(lambda match: mapping[match.group()], value)
        if isinstance(value, list):
            return [self._rewrite(item, mapping, pattern) for item in value]
        if isinstance(value, dict):
            # Image bytes are opaque. Never inspect or rewrite base64 payloads.
            if value.get("type") in ("image", "image_url"):
                return value
            return {key: self._rewrite(item, mapping, pattern) for key, item in value.items()}
        return value

    def outbound(self, messages):
        return [message.model_copy(update={
            "content": self._rewrite(message.content, self.forward, self.out_pattern),
            **({"tool_calls": self._rewrite(message.tool_calls, self.forward, self.out_pattern)}
               if hasattr(message, "tool_calls") else {}),
        }) for message in messages]

    def schemas(self, schemas):
        """Keep schema ID constraints in the same namespace as message IDs."""
        return self._rewrite(schemas, self.forward, self.out_pattern)

    def outbound_schemas(self, schemas):
        """Explicit outbound name for the same schema alias transformation."""
        return self.schemas(schemas)

    def inbound(self, response):
        return response.model_copy(update={
            "content": self._rewrite(response.content, self.reverse, self.in_pattern),
            "tool_calls": self._rewrite(response.tool_calls, self.reverse, self.in_pattern),
        })
