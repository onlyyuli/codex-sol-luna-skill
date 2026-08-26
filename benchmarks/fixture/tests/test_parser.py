import unittest

from src.parser import parse_amount


class ParserTests(unittest.TestCase):
    def test_parse_amount(self) -> None:
        self.assertEqual(parse_amount(" 12.5 "), 12.5)


if __name__ == "__main__":
    unittest.main()
