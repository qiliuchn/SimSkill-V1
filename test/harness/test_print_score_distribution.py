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

import print_score_distribution


plt = print_score_distribution.plt


class ScoreDistributionTests(unittest.TestCase):
    def test_inclusive_survival_points_preserve_ties_and_endpoints(self) -> None:
        thresholds, survival = (
            print_score_distribution.inclusive_survival_points(
                [0.0, 0.5, 0.5, 1.0]
            )
        )

        self.assertEqual(thresholds, [0.0, 0.5, 1.0])
        self.assertEqual(survival, [1.0, 0.75, 0.25])
        self.assertTrue(
            all(left >= right for left, right in zip(survival, survival[1:]))
        )

    def test_tied_score_offsets_are_deterministic_and_bounded(self) -> None:
        scores = [0.5, 0.2, 0.5, 0.5, 1.0]

        first = print_score_distribution.tied_score_offsets(scores)
        second = print_score_distribution.tied_score_offsets(scores)

        self.assertEqual(first, second)
        self.assertEqual(first[1], 0.0)
        self.assertEqual(first[4], 0.0)
        self.assertEqual(len({first[0], first[2], first[3]}), 3)
        self.assertTrue(all(-0.14 <= value <= 0.14 for value in first))

    def test_figure_contains_one_survival_curve_per_condition(self) -> None:
        figure = print_score_distribution.create_score_distribution_figure(
            {
                "full-ver": [0.0, 0.25, 1.0],
                "vanilla-cc": [0.25, 0.75],
            },
            conditions=["full-ver", "vanilla-cc"],
            model="test-model",
        )
        try:
            survival_ax, summary_ax = figure.axes
            self.assertEqual(len(survival_ax.lines), 2)
            self.assertLess(survival_ax.get_xlim()[0], 0.0)
            self.assertGreater(survival_ax.get_xlim()[1], 1.0)
            self.assertLess(summary_ax.get_xlim()[0], 0.0)
            self.assertGreater(summary_ax.get_xlim()[1], 1.0)
            self.assertIn("≥ threshold", survival_ax.get_ylabel())
            self.assertEqual(len(summary_ax.collections), 2)
            self.assertEqual(
                sum(
                    len(collection.get_offsets())
                    for collection in summary_ax.collections
                ),
                5,
            )
            first_line = survival_ax.lines[0]
            self.assertEqual(first_line.get_drawstyle(), "steps-pre")
            self.assertEqual(list(first_line.get_xdata()), [0.0, 0.25, 1.0])
            self.assertEqual(list(first_line.get_ydata()), [1.0, 2 / 3, 1 / 3])
            first_label = figure.legends[0].get_texts()[0].get_text()
            self.assertIn("median=0.25", first_label)
            self.assertIn("mean=0.42", first_label)
        finally:
            plt.close(figure)

    def test_figure_omits_requested_conditions_without_scores(self) -> None:
        figure = print_score_distribution.create_score_distribution_figure(
            {"full-ver": [0.25, 0.75]},
            conditions=["full-ver", "vanilla-cc"],
            model="test-model",
        )
        try:
            survival_ax, summary_ax = figure.axes
            self.assertEqual(len(survival_ax.lines), 1)
            self.assertEqual(len(summary_ax.get_yticklabels()), 1)
            self.assertIn("full-ver", summary_ax.get_yticklabels()[0].get_text())
        finally:
            plt.close(figure)

    def test_survival_points_handle_endpoint_only_samples(self) -> None:
        self.assertEqual(
            print_score_distribution.inclusive_survival_points([0.0, 0.0]),
            ([0.0, 1.0], [1.0, 0.0]),
        )
        self.assertEqual(
            print_score_distribution.inclusive_survival_points([1.0, 1.0]),
            ([0.0, 1.0], [1.0, 1.0]),
        )

    def test_custom_condition_colors_do_not_duplicate_builtin_colors(self) -> None:
        colors = print_score_distribution.build_condition_color_map(
            ["full-ver", "custom-condition"]
        )

        self.assertNotEqual(colors["full-ver"], colors["custom-condition"])

    def test_save_keeps_pdf_font_settings_active(self) -> None:
        figure = mock.Mock()

        def assert_publication_settings(*args, **kwargs) -> None:
            self.assertEqual(
                print_score_distribution.matplotlib.rcParams["pdf.fonttype"], 42
            )
            self.assertEqual(
                print_score_distribution.matplotlib.rcParams["ps.fonttype"], 42
            )

        figure.savefig.side_effect = assert_publication_settings
        with tempfile.TemporaryDirectory() as temp_dir:
            print_score_distribution.save_publication_figure(
                figure, Path(temp_dir) / "figure.pdf", dpi=300
            )

        figure.savefig.assert_called_once()

    def test_cli_reads_custom_log_and_writes_publication_figure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            experiment_tasks_path = root / "paper_scores.jsonl"
            records = [
                {
                    "run_id": "run-1",
                    "task_condition": "full-ver",
                    "task_model": "paper-model",
                    "score": 0.2,
                },
                {
                    "run_id": "run-2",
                    "task_condition": "full-ver",
                    "task_model": "paper-model",
                    "score": 0.9,
                },
                {
                    "run_id": "run-3",
                    "task_condition": "vanilla-cc",
                    "task_model": "paper-model",
                    "score": 0.4,
                },
            ]
            experiment_tasks_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            output_path = root / "paper_score_distribution.png"
            stdout = StringIO()

            with mock.patch.object(
                print_score_distribution.score_hist,
                "load_experiment_tasks",
                wraps=print_score_distribution.score_hist.load_experiment_tasks,
            ) as load_records:
                with redirect_stdout(stdout):
                    exit_code = print_score_distribution.main(
                        [
                            "--experiment-tasks",
                            str(experiment_tasks_path),
                            "--output",
                            str(output_path),
                            "--dpi",
                            "150",
                        ]
                    )

            self.assertEqual(exit_code, 0)
            load_records.assert_called_once_with(experiment_tasks_path)
            self.assertTrue(output_path.is_file())
            self.assertGreater(output_path.stat().st_size, 0)
            self.assertIn("3 scored run(s), 2 condition(s)", stdout.getvalue())
            self.assertIn("model=paper-model", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
