import csv
import re
from pathlib import Path

from frappe.tests import UnitTestCase

APP = Path(__file__).resolve().parent.parent
SOURCE = re.compile(r'_\("((?:[^"\\]|\\.)*)"\)')


class TestTranslations(UnitTestCase):
	def test_every_source_string_has_a_german_translation(self):
		with open(APP / "translations" / "de.csv", newline="") as f:
			german = {row[0]: row[1] for row in csv.reader(f) if row}
		for path in APP.rglob("*.py"):
			if "tests" in path.parts:
				continue
			for text in SOURCE.findall(path.read_text()):
				with self.subTest(path=path.name, text=text):
					self.assertTrue(german.get(text), text)
