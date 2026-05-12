import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from src.recommendations.writer import (
    dataclass_to_dict,
    write_json_artifact,
    write_markdown_report,
)


@dataclass(frozen=True)
class Sample:
    a: int
    b: str


class WriterTests(unittest.TestCase):
    def test_dataclass_to_dict_nested(self) -> None:
        result = dataclass_to_dict({"x": Sample(1, "y"), "z": [Sample(2, "w")]})
        self.assertEqual(result, {"x": {"a": 1, "b": "y"}, "z": [{"a": 2, "b": "w"}]})

    def test_write_json_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "dir" / "out.json"
            write_json_artifact(target, {"a": 1, "b": [Sample(2, "x")]})
            self.assertTrue(target.exists())
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(data["a"], 1)
            self.assertEqual(data["b"][0]["a"], 2)

    def test_write_markdown_basic_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.md"
            write_markdown_report(target, "Hello", [("Intro", "Body line")])
            content = target.read_text(encoding="utf-8")
            self.assertIn("# Hello", content)
            self.assertIn("## Intro", content)
            self.assertIn("Body line", content)


if __name__ == "__main__":
    unittest.main()
