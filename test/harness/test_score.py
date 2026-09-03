from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


HARNESS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_DIR))

import score


class ScoreJobSelectionTests(unittest.TestCase):
    def _write_cli_fixture(
        self, root: Path, experiment_record: dict
    ) -> tuple[Path, Path, list[str]]:
        experiment_tasks_path = root / "experiment_tasks.jsonl"
        experiment_tasks_path.write_text(
            json.dumps(experiment_record) + "\n", encoding="utf-8"
        )

        benchmark_path = root / "benchmark.yaml"
        benchmark_path.write_text(
            "tasks:\n  - id: task-1\n    task: Complete task one.\n",
            encoding="utf-8",
        )
        models_path = root / "models.yaml"
        models_path.write_text("models:\n  judge-model: {}\n", encoding="utf-8")
        conditions_path = root / "conditions.yaml"
        conditions_path.write_text(
            "conditions:\n  verification: {}\n", encoding="utf-8"
        )
        prompt_path = root / "prompt.txt"
        prompt_path.write_text(
            "{run_id_json} {task_id_json} {task_text_json} "
            "{episodic_path_json} {score_result_path_json}",
            encoding="utf-8",
        )
        results_dir = root / "scores"
        argv = [
            "--experiment-tasks",
            str(experiment_tasks_path),
            "--benchmark",
            str(benchmark_path),
            "--models-file",
            str(models_path),
            "--conditions-file",
            str(conditions_path),
            "--prompt-template",
            str(prompt_path),
            "--results-dir",
            str(results_dir),
            "--worktree-root",
            str(root / "worktrees"),
            "--judge-model",
            "judge-model",
        ]
        return experiment_tasks_path, results_dir, argv

    def test_records_with_existing_numeric_scores_are_skipped(self) -> None:
        benchmark_tasks = [
            {"id": "task-1", "task": "Complete task one."},
            {"id": "task-2", "task": "Complete task two."},
            {"id": "task-3", "task": "Complete task three."},
            {"id": "task-4", "task": "Complete task four."},
        ]
        experiment_tasks = [
            {
                "run_id": "already-scored-zero",
                "task_id": "task-1",
                "score": 0,
                "score_result_path": "/previous/score/zero.json",
            },
            {
                "run_id": "already-scored-partial",
                "task_id": "task-2",
                "score": 0.5,
                "score_result_path": "/previous/score/partial.json",
            },
            {
                "run_id": "already-scored-perfect",
                "task_id": "task-3",
                "score": 1,
                "score_result_path": "/previous/score/perfect.json",
            },
            {
                "run_id": "pending",
                "task_id": "task-4",
            },
        ]

        pending, already_scored, unavailable = score.collect_scoring_jobs(
            benchmark_tasks, experiment_tasks
        )

        self.assertEqual([job.run_id for job in pending], ["pending"])
        self.assertEqual(already_scored, 3)
        self.assertEqual(unavailable, 0)

    def test_existing_score_is_checked_before_other_record_fields(self) -> None:
        pending, already_scored, unavailable = score.collect_scoring_jobs(
            [], [{"score": 0.25}]
        )

        self.assertEqual(pending, [])
        self.assertEqual(already_scored, 1)
        self.assertEqual(unavailable, 0)

    def test_invalid_existing_score_is_not_treated_as_completed(self) -> None:
        benchmark_tasks = [{"id": "task-1", "task": "Complete task one."}]
        experiment_tasks = [
            {
                "run_id": "invalid-score",
                "task_id": "task-1",
                "score": "not-a-score",
            }
        ]

        with redirect_stderr(StringIO()):
            pending, already_scored, unavailable = score.collect_scoring_jobs(
                benchmark_tasks, experiment_tasks
            )

        self.assertEqual([job.run_id for job in pending], ["invalid-score"])
        self.assertEqual(already_scored, 0)
        self.assertEqual(unavailable, 0)

    def test_cli_exits_without_creating_worktree_when_every_record_is_scored(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            experiment_tasks_path, _results_dir, argv = self._write_cli_fixture(
                root,
                {"run_id": "done", "task_id": "task-1", "score": 0},
            )
            original_log = experiment_tasks_path.read_text(encoding="utf-8")

            output = StringIO()
            with mock.patch.object(score.re1, "create_worktree") as create_worktree:
                with redirect_stdout(output):
                    exit_code = score.main(argv)

            self.assertEqual(exit_code, 0)
            create_worktree.assert_not_called()
            self.assertIn("0 to score, 1 already scored", output.getvalue())
            self.assertEqual(
                experiment_tasks_path.read_text(encoding="utf-8"), original_log
            )

    def test_cli_prints_process_diagnostics_when_judge_writes_no_result(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            experiment_tasks_path, _results_dir, argv = self._write_cli_fixture(
                root, {"run_id": "failed-run", "task_id": "task-1"}
            )
            original_log = experiment_tasks_path.read_text(encoding="utf-8")
            process = subprocess.CompletedProcess(
                args=["claude"],
                returncode=17,
                stdout="partial judge stdout\n",
                stderr="provider failure detail\n",
            )
            output = StringIO()
            diagnostics = StringIO()

            with mock.patch.object(score.re1, "create_worktree"):
                with mock.patch.object(score.re1, "remove_worktree") as remove:
                    with mock.patch.object(score.re1.memory_ops, "apply_condition"):
                        with mock.patch.object(
                            score.re1, "write_worktree_settings", return_value=None
                        ):
                            with mock.patch.object(
                                score.subprocess, "run", return_value=process
                            ):
                                with redirect_stdout(output), redirect_stderr(
                                    diagnostics
                                ):
                                    exit_code = score.main(argv)

            diagnostic_text = diagnostics.getvalue()
            self.assertEqual(exit_code, 1)
            self.assertIn("scoring failed for run_id=failed-run", diagnostic_text)
            self.assertIn("stage: validating judge result", diagnostic_text)
            self.assertIn("judge did not write result file", diagnostic_text)
            self.assertIn("score result status: not written", diagnostic_text)
            self.assertIn("judge exit code: 17", diagnostic_text)
            self.assertIn("partial judge stdout", diagnostic_text)
            self.assertIn("provider failure detail", diagnostic_text)
            self.assertNotIn("partial judge stdout", output.getvalue())
            self.assertNotIn("provider failure detail", output.getvalue())
            self.assertEqual(
                experiment_tasks_path.read_text(encoding="utf-8"), original_log
            )
            remove.assert_called_once()

    def test_cli_prints_result_contents_when_judge_result_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            experiment_tasks_path, results_dir, argv = self._write_cli_fixture(
                root, {"run_id": "invalid-result", "task_id": "task-1"}
            )
            original_log = experiment_tasks_path.read_text(encoding="utf-8")
            result_path = results_dir / "invalid-result.json"

            def write_invalid_result(*_args, **_kwargs):
                result_path.write_text("{not json", encoding="utf-8")
                return subprocess.CompletedProcess(
                    args=["claude"],
                    returncode=0,
                    stdout="judge claimed completion\n",
                    stderr="judge validation context\n",
                )

            diagnostics = StringIO()
            with mock.patch.object(score.re1, "create_worktree"):
                with mock.patch.object(score.re1, "remove_worktree"):
                    with mock.patch.object(score.re1.memory_ops, "apply_condition"):
                        with mock.patch.object(
                            score.re1, "write_worktree_settings", return_value=None
                        ):
                            with mock.patch.object(
                                score.subprocess,
                                "run",
                                side_effect=write_invalid_result,
                            ):
                                with redirect_stdout(StringIO()), redirect_stderr(
                                    diagnostics
                                ):
                                    exit_code = score.main(argv)

            diagnostic_text = diagnostics.getvalue()
            self.assertEqual(exit_code, 1)
            self.assertIn("result file is not valid JSON", diagnostic_text)
            self.assertIn("score result contents", diagnostic_text)
            self.assertIn("{not json", diagnostic_text)
            self.assertIn("judge exit code: 0", diagnostic_text)
            self.assertIn("judge claimed completion", diagnostic_text)
            self.assertIn("judge validation context", diagnostic_text)
            self.assertEqual(
                experiment_tasks_path.read_text(encoding="utf-8"), original_log
            )


if __name__ == "__main__":
    unittest.main()
