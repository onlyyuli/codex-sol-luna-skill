def parse_amount(value: str) -> float:
    stripped = value.strip()
    if not stripped:
        raise ValueError("amount is empty")
    return float(stripped)
