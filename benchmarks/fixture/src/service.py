from .access import can_calculate
from .calculator import add
from .parser import parse_amount


def parse_and_add(role: str, left: str, right: str) -> float:
    if not can_calculate(role):
        raise PermissionError("role cannot calculate")
    return add(parse_amount(left), parse_amount(right))
