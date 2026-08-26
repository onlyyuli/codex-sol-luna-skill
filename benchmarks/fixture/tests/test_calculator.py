import unittest

from src.calculator import add, divide


class CalculatorTests(unittest.TestCase):
    def test_add(self) -> None:
        self.assertEqual(add(2, 3), 5)

    def test_divide(self) -> None:
        self.assertEqual(divide(6, 2), 3)


if __name__ == "__main__":
    unittest.main()
