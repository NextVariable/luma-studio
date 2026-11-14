"""The optional realtime dependency is pinned in two files; they must agree."""
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PackagingTests(unittest.TestCase):
    def test_realtime_pin_matches_requirements_file(self):
        extra = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['optional-dependencies']['realtime']
        listed = [line.strip() for line in (ROOT / 'requirements-realtime.txt').read_text().splitlines()
                  if line.strip() and not line.startswith('#')]
        self.assertEqual(sorted(extra), sorted(listed))

    def test_realtime_pin_is_exact(self):
        for line in (ROOT / 'requirements-realtime.txt').read_text().splitlines():
            if line.strip() and not line.startswith('#'):
                self.assertRegex(line.strip(), re.compile(r'^[A-Za-z0-9_.-]+==\d+(\.\d+)*$'))


if __name__ == '__main__':
    unittest.main()
