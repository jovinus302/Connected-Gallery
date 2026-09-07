"""Single-owner PC credentials, independent of model-provider credentials."""
import os
import secrets
from pathlib import Path


def server_token(root: Path) -> str:
    configured = os.getenv("CG_SERVER_TOKEN")
    if configured is not None:
        token = configured.strip()
    else:
        root.mkdir(parents=True, exist_ok=True)
        path = root / "server-token.txt"
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
        token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError("CG_SERVER_TOKEN must contain at least 32 non-whitespace ASCII characters")
    return token
