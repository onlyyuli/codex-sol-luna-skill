import unittest

from src.service import parse_and_add


class ServiceTests(unittest.TestCase):
    def test_parse_and_add(self) -> None:
        self.assertEqual(parse_and_add("editor", "2", "3"), 5)

    def test_denied_role(self) -> None:
        with self.assertRaises(PermissionError):
            parse_and_add("viewer", "2", "3")


if __name__ == "__main__":
    unittest.main()
