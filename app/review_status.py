from __future__ import annotations

REVIEW_STATUS_PENDING = "Pending Review"
REVIEW_STATUS_NO_ACTION = "No Action Required"

REVIEW_STATUSES = [
    REVIEW_STATUS_PENDING,
    "Make Changes to A",
    "Make Changes to B",
    "Remove From A",
    "Remove From B",
    "Under Investigation",
    "Escalated",
    REVIEW_STATUS_NO_ACTION,
]

REVIEW_STATUS_COLORS: dict[str, str] = {
    REVIEW_STATUS_PENDING: "#C8901A",
    "Make Changes to A": "#3DDC84",
    "Make Changes to B": "#2EC9A0",
    "Remove From A": "#FF6060",
    "Remove From B": "#D94C4C",
    "Under Investigation": "#4090C8",
    "Escalated": "#B040C8",
    REVIEW_STATUS_NO_ACTION: "#707070",
}

LEGACY_REVIEW_STATUS_MAP = {
    "Add Policy to Align": "Make Changes to A",
    "Add Setting to Align": "Make Changes to A",
    "Update Setting to Align": "Make Changes to A",
    "Remove Setting to Align": "Remove From A",
    "Update Required": "Make Changes to A",
}


def normalize_review_status(status: object) -> str:
    text = str(status or "").strip()
    if not text:
        return REVIEW_STATUS_PENDING
    return LEGACY_REVIEW_STATUS_MAP.get(text, text if text in REVIEW_STATUSES else REVIEW_STATUS_PENDING)
