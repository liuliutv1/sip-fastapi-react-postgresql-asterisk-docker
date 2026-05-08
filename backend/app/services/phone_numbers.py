import re

PHONE_NUMBER_PATTERN = re.compile(r"^\+?[1-9]\d{5,18}$")


def normalize_phone_number(value: str) -> str:
    normalized = value.strip()
    normalized = re.sub(r"[\s\-().]", "", normalized)
    if normalized.startswith("00"):
        normalized = f"+{normalized[2:]}"
    return normalized


def is_valid_phone_number(value: str) -> bool:
    return bool(PHONE_NUMBER_PATTERN.fullmatch(normalize_phone_number(value)))


def mask_phone_number(value: str | None) -> str:
    if not value:
        return ""
    normalized = normalize_phone_number(value)
    prefix_len = 4 if normalized.startswith("+") else 3
    if len(normalized) <= prefix_len + 4:
        return f"{normalized[:1]}****{normalized[-1:]}"
    return f"{normalized[:prefix_len]}****{normalized[-4:]}"
