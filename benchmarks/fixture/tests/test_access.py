import unittest

from src.access import can_calculate


class AccessTests(unittest.TestCase):
    def test_known_role(self) -> None:
        self.assertTrue(can_calculate("ADMIN"))

    def test_unknown_role(self) -> None:
        self.assertFalse(can_calculate("viewer"))


if __name__ == "__main__":
    unittest.main()
