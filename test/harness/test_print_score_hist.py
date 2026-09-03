from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


HARNESS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_DIR))

import print_score_hist


class PrintScoreHistogramTests(unittest.TestCase):
    def test_cli_reads_user_supplied_experiment_tasks_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            experiment_tasks_path = root / "custom_experiment_tasks.jsonl"
            records = [
                {
                    "run_id": "run-1",
                    "task_condition": "full-ver",
                    "task_model": "test-model",
                    "score": 0.25,
                },
                {
                    "run_id": "run-2",
                    "task_condition": "vanilla-cc",
                    "task_model": "test-model",
                    "score": 0.75,
                },
            ]
            experiment_tasks_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            output_path = root / "custom_score_hist.png"
            stdout = StringIO()

            with mock.patch.object(
                print_score_hist,
                "load_experiment_tasks",
                wraps=print_score_hist.load_experiment_tasks,
            ) as load_records:
                with redirect_stdout(stdout):
                    exit_code = print_score_hist.main(
                        [
                            "--experiment-tasks",
                            str(experiment_tasks_path),
                            "--output",
                            str(output_path),
                        ]
                    )

            self.assertEqual(exit_code, 0)
            load_records.assert_called_once_with(experiment_tasks_path)
            self.assertTrue(output_path.is_file())
            self.assertGreater(output_path.stat().st_size, 0)
            self.assertIn("2 scored run(s), 2 condition(s)", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
