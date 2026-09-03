from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


HARNESS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_DIR))

import aggregate_results
import add_interactive_task_execution_result as interactive_results
import cost_time


class CostAccountingTests(unittest.TestCase):
    def test_model_usage_replaces_top_level_usage_and_sums_subagents(self) -> None:
        raw = {
            "usage": {
                "input_tokens": 1,
                "output_tokens": 2,
                "cache_creation_input_tokens": 3,
                "cache_read_input_tokens": 4,
            },
            "modelUsage": {
                "deepseek-v4-pro[1m]": {
                    "inputTokens": 100,
                    "outputTokens": 200,
                    "cacheCreationInputTokens": 300,
                    "cacheReadInputTokens": 400,
                },
                "deepseek-v4-flash": {
                    "inputTokens": 10,
                    "outputTokens": 20,
                    "cacheCreationInputTokens": 30,
                    "cacheReadInputTokens": 40,
                },
            },
        }

        usage = cost_time.parse_claude_json_result(raw)

        self.assertEqual(usage.usage_source, "modelUsage")
        self.assertEqual(usage.input_tokens, 110)
        self.assertEqual(usage.output_tokens, 220)
        self.assertEqual(usage.cache_creation_input_tokens, 330)
        self.assertEqual(usage.cache_read_input_tokens, 440)

    def test_per_model_rates_are_applied_to_whole_tree_usage(self) -> None:
        usage = cost_time.parse_claude_json_result(
            {
                "modelUsage": {
                    "deepseek-v4-pro[1m]": {
                        "inputTokens": 1_000_000,
                        "outputTokens": 1_000_000,
                        "cacheCreationInputTokens": 0,
                        "cacheReadInputTokens": 1_000_000,
                    },
                    "deepseek-v4-flash": {
                        "inputTokens": 1_000_000,
                        "outputTokens": 0,
                        "cacheCreationInputTokens": 0,
                        "cacheReadInputTokens": 0,
                    },
                }
            }
        )
        price_table = {
            "price_table_date": "2026-08-17",
            "rates": {
                "deepseek-v4-pro": {
                    "input": 1.0,
                    "output": 2.0,
                    "cache_write": 1.0,
                    "cache_read": 0.1,
                },
                "deepseek-v4-flash": {
                    "input": 0.25,
                    "output": 0.5,
                    "cache_write": 0.25,
                    "cache_read": 0.01,
                },
            },
        }

        cost, warnings = cost_time.compute_dollar_cost(
            usage, "deepseek-v4-pro", price_table
        )

        self.assertAlmostEqual(cost or 0.0, 3.35)
        self.assertEqual(warnings, [])

    def test_provider_namespace_is_removed_for_price_lookup(self) -> None:
        usage = cost_time.parse_claude_json_result(
            {
                "modelUsage": {
                    "kimi/kimi-k3": {
                        "inputTokens": 1_000_000,
                    }
                }
            }
        )
        price_table = {
            "price_table_date": "2026-08-17",
            "rates": {
                "kimi-k3": {
                    "input": 0.60,
                }
            },
        }

        cost, warnings = cost_time.compute_dollar_cost(
            usage, "unmatched-configured-model", price_table
        )

        self.assertAlmostEqual(cost or 0.0, 0.60)
        self.assertEqual(warnings, [])

    def test_historical_result_is_repriced_from_raw_model_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_path = root / "run.stdout.log"
            raw_path.write_text(
                json.dumps(
                    {
                        "total_cost_usd": 99.0,
                        "usage": {
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 1,
                        },
                        "modelUsage": {
                            "deepseek-v4-pro[1m]": {
                                "inputTokens": 1_000_000,
                                "outputTokens": 1_000_000,
                                "cacheCreationInputTokens": 0,
                                "cacheReadInputTokens": 1_000_000,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            result_path = root / "run.json"
            result = {
                "run_id": "run",
                "model": "deepseek-v4-pro",
                "raw_stdout_path": str(raw_path),
                "cost_usd": 0.01,
            }
            price_table = {
                "price_table_date": "2026-08-17",
                "rates": {
                    "deepseek-v4-pro": {
                        "input": 1.0,
                        "output": 2.0,
                        "cache_write": 1.0,
                        "cache_read": 0.1,
                    }
                },
            }

            repriced, warnings = aggregate_results.reprice_result(
                result, result_path, price_table
            )

            self.assertAlmostEqual(repriced["cost_usd"], 3.1)
            self.assertEqual(repriced["tokens"]["input"], 1_000_000)
            self.assertEqual(
                repriced["cost_accounting"]["usage_source"], "modelUsage"
            )
            self.assertEqual(warnings, [])
            self.assertEqual(result["cost_usd"], 0.01)

    def test_interactive_placeholder_stdout_reprices_from_usage_sidecar(self) -> None:
        """An interactive run's stdout log is a placeholder, not JSON.

        Its whole-tree usage lives in the ``<run_id>.claude_result.json`` sidecar,
        which must be preferred so the run is priced rather than dropped to null.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            (raw_dir / "run.stdout.log").write_text(
                interactive_results.INTERACTIVE_OUTPUT_PLACEHOLDER, encoding="utf-8"
            )
            (raw_dir / "run.claude_result.json").write_text(
                json.dumps(
                    {
                        "subtype": "interactive",
                        "modelUsage": {
                            "deepseek-v4-pro": {
                                "inputTokens": 1_000_000,
                                "outputTokens": 1_000_000,
                                "cacheCreationInputTokens": 0,
                                "cacheReadInputTokens": 1_000_000,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = {
                "run_id": "run",
                "model": "deepseek-v4-pro",
                "raw_stdout_path": str(raw_dir / "run.stdout.log"),
                "tokens": {"input": 7, "output": 7, "cache_creation": 0, "cache_read": 7},
                "cost_usd": 0.01,
            }

            repriced, warnings = aggregate_results.reprice_result(
                result, root / "run.json", self._price_table()
            )

            self.assertAlmostEqual(repriced["cost_usd"], 3.1)
            self.assertEqual(repriced["cost_accounting"]["usage_source"], "modelUsage")
            self.assertEqual(warnings, [])

    def test_unreadable_raw_result_falls_back_to_stored_token_counters(self) -> None:
        """A missing raw result must not silently null out an otherwise costed run."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = {
                "run_id": "run",
                "model": "deepseek-v4-pro",
                "tokens": {
                    "input": 1_000_000,
                    "output": 1_000_000,
                    "cache_creation": 0,
                    "cache_read": 1_000_000,
                },
                "cost_usd": 0.01,
            }

            repriced, warnings = aggregate_results.reprice_result(
                result, root / "run.json", self._price_table()
            )

            self.assertAlmostEqual(repriced["cost_usd"], 3.1)
            self.assertEqual(
                repriced["cost_accounting"]["usage_source"], "stored_tokens"
            )
            self.assertTrue(any("repriced from the token counters" in w for w in warnings))

    def test_reprice_returns_null_when_no_usage_survives_anywhere(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = {"run_id": "run", "model": "deepseek-v4-pro", "cost_usd": 0.01}

            repriced, warnings = aggregate_results.reprice_result(
                result, root / "run.json", self._price_table()
            )

            self.assertIsNone(repriced["cost_usd"])
            self.assertTrue(any("cannot reprice" in w for w in warnings))

    @staticmethod
    def _price_table() -> dict:
        return {
            "price_table_date": "2026-08-17",
            "rates": {
                "deepseek-v4-pro": {
                    "input": 1.0,
                    "output": 2.0,
                    "cache_write": 1.0,
                    "cache_read": 0.1,
                }
            },
        }

    def test_deepseek_peak_cache_hit_conversion_is_not_off_by_ten(self) -> None:
        price_table = cost_time.load_price_table(HARNESS_DIR / "price_table.yaml")

        self.assertAlmostEqual(
            price_table["rates"]["deepseek-v4-pro"]["cache_read"],
            0.30 / 7,
            places=6,
        )

    def test_summary_reports_total_and_number_of_costed_runs(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "condition": "full-ver",
                    "model": "deepseek-v4-pro",
                    "run_id": "one",
                    "verified_success": True,
                    "verification_agreement": True,
                    "cost_usd": 1.25,
                    "wall_clock_total_s": 10.0,
                    "attempts": 1,
                },
                {
                    "condition": "full-ver",
                    "model": "deepseek-v4-pro",
                    "run_id": "two",
                    "verified_success": False,
                    "verification_agreement": True,
                    "cost_usd": None,
                    "wall_clock_total_s": 20.0,
                    "attempts": 1,
                },
            ]
        )

        row = aggregate_results.summary_table(df).iloc[0]

        self.assertEqual(row["n"], 2)
        self.assertEqual(row["n_costed"], 1)
        self.assertEqual(row["total_cost_usd"], 1.25)

    def test_interactive_transcript_accounting_includes_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = "session-123"
            transcript_path = root / f"{session_id}.jsonl"
            subagent_dir = root / session_id / "subagents"
            subagent_dir.mkdir(parents=True)

            main_record = {
                "type": "assistant",
                "sessionId": session_id,
                "timestamp": "2026-08-17T00:00:00Z",
                "message": {
                    "id": "main-message",
                    "model": "deepseek-v4-pro",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 20,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 30,
                    },
                },
            }
            # Duplicate content chunks with one message id must count once.
            transcript_path.write_text(
                json.dumps(main_record) + "\n" + json.dumps(main_record) + "\n",
                encoding="utf-8",
            )
            subagent_record = {
                "type": "assistant",
                "sessionId": session_id,
                "timestamp": "2026-08-17T00:01:00Z",
                "message": {
                    "id": "subagent-message",
                    "model": "deepseek-v4-pro",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 200,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 300,
                    },
                },
            }
            (subagent_dir / "agent-one.jsonl").write_text(
                json.dumps(subagent_record) + "\n", encoding="utf-8"
            )

            summary = interactive_results.summarize_transcript(
                transcript_path, session_id
            )

            self.assertEqual(summary.usage["input_tokens"], 110)
            self.assertEqual(summary.usage["output_tokens"], 220)
            self.assertEqual(
                summary.model_usage["deepseek-v4-pro"]["cacheReadInputTokens"],
                330,
            )
            self.assertEqual(summary.num_turns, 2)


if __name__ == "__main__":
    unittest.main()
