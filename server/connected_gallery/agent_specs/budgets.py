"""One wall-clock budget shared by the service and authorized gallery tools."""
import os


def initial_candidate_limit():
    """Host-supplied exploration leads. 0 disables the supply entirely."""
    value = int(os.getenv("CG_EXPLORE_INITIAL_CANDIDATES", "8"))
    if not 0 <= value <= 16:
        raise ValueError("CG_EXPLORE_INITIAL_CANDIDATES must be between 0 and 16")
    return value


def run_timeout(role):
    if role == "context":
        seconds = float(os.getenv("CG_CONTEXT_TIMEOUT_SECONDS", "300"))
        if not 60 <= seconds <= 600:
            raise ValueError("CG_CONTEXT_TIMEOUT_SECONDS must be between 60 and 600")
        return seconds
    if role != "explorer":
        return {"analyst": 180, "organizer": 600}[role]
    seconds = float(os.getenv("CG_EXPLORE_TIMEOUT_SECONDS", "90"))
    if not 15 <= seconds <= 180:
        raise ValueError("CG_EXPLORE_TIMEOUT_SECONDS must be between 15 and 180")
    return seconds
