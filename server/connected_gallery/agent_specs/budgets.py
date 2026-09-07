"""One wall-clock budget shared by the service and authorized gallery tools."""
import os


def run_timeout(role):
    if role != "explorer":
        return {"analyst": 180, "organizer": 600}[role]
    seconds = float(os.getenv("CG_EXPLORE_TIMEOUT_SECONDS", "90"))
    if not 15 <= seconds <= 180:
        raise ValueError("CG_EXPLORE_TIMEOUT_SECONDS must be between 15 and 180")
    return seconds
