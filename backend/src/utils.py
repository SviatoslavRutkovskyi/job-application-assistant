import re


def sanitize_filename(name: str) -> str:
    if not name:
        return ""
    sanitized = re.sub(r"[^\w\s-]", "", name)
    sanitized = re.sub(r"[-\s]+", "_", sanitized)
    return sanitized.lower().strip("_")