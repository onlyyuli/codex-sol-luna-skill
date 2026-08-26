ALLOWED_ROLES = {"admin", "editor"}


def can_calculate(role: str) -> bool:
    return role.lower() in ALLOWED_ROLES
