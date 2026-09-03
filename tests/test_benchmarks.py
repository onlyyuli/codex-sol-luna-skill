from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from benchmarks.run_matrix import ROOT, activity_evidence, prepare_workspace, timeout_text
from benchmarks.run_routing_contract import evaluate, load_cases
from benchmarks.summarize import summarize_records
from benchmarks.usage_accounting import account_rollouts, estimate_credits, load_rate_card


class BenchmarkEvidenceTests(unittest.TestCase):
    def test_activity_evidence_uses_runtime_fields(self) -> None:
        stdout = (
            '{"type":"item.completed","item":{"type":"collab_tool_call",'
            '"receiver_thread_ids":["child-1"],"model":"gpt-5.6-luna",'
            '"reasoning_effort":"max","agents_states":{"child-1":"completed"}}}\n'
            '{"type":"item.completed","item":{"type":"agent_message",'
            '"text":"Route: LUNA_READ_PARALLEL"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}\n'
        )
        evidence = activity_evidence(stdout)
        self.assertEqual(evidence["child_thread_ids"], ["child-1"])
        self.assertTrue(evidence["luna_model_proven"])
        self.assertTrue(evidence["max_effort_proven"])
        self.assertEqual(evidence["reported_route"], "LUNA_READ_PARALLEL")
        self.assertEqual(evidence["usage"]["input_tokens"], 10)

    def test_activity_evidence_retains_route_from_intermediate_message(self) -> None:
        stdout = (
            '{"type":"item.completed","item":{"type":"agent_message",'
            '"text":"Route: LUNA_SINGLE_WRITE"}}\n'
            '{"type":"item.completed","item":{"type":"agent_message",'
            '"text":"Implementation completed."}}\n'
        )
        evidence = activity_evidence(stdout)
        self.assertEqual(evidence["final_message"], "Implementation completed.")
        self.assertEqual(evidence["reported_route"], "LUNA_SINGLE_WRITE")

    def test_parent_claim_does_not_create_child_evidence(self) -> None:
        stdout = (
            '{"type":"item.completed","item":{"type":"agent_message",'
            '"text":"I used GPT-5.6 Luna Max"}}\n'
        )
        evidence = activity_evidence(stdout)
        self.assertEqual(evidence["child_count"], 0)
        self.assertFalse(evidence["luna_model_proven"])

    def test_parent_metadata_outside_child_activity_is_not_proof(self) -> None:
        stdout = (
            '{"type":"thread.started","model":"gpt-5.6-luna",'
            '"reasoning_effort":"max"}\n'
            '{"type":"item.completed","item":{"type":"agent_message",'
            '"text":"done"}}\n'
        )
        evidence = activity_evidence(stdout)
        self.assertFalse(evidence["luna_model_proven"])
        self.assertFalse(evidence["max_effort_proven"])

    def test_timeout_text_accepts_bytes(self) -> None:
        self.assertEqual(timeout_text(b"timeout"), "timeout")

    def test_prepare_workspace_installs_skill_only_for_delegated_arm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            shutil.copytree(ROOT / "benchmarks/fixture", workspace)
            prepare_workspace(workspace, "B")
            self.assertTrue((workspace / ".git").is_dir())
            self.assertTrue((workspace / ".agents/skills/sol-luna/SKILL.md").is_file())

    def test_routing_contract_contains_fifteen_bounded_cases(self) -> None:
        cases = load_cases(ROOT / "benchmarks/routing_cases.jsonl")
        self.assertEqual(len(cases), 15)
        self.assertEqual(len({case["id"] for case in cases}), 15)
        self.assertTrue(all(0 <= case["min_children"] <= case["max_children"] <= 8 for case in cases))

    def test_routing_contract_rejects_unproven_delegation(self) -> None:
        case = {
            "min_children": 1,
            "max_children": 1,
            "expected_route": "LUNA_READ_PARALLEL",
            "allowed_changed_paths": [],
            "required_final_text": [],
        }
        record = {
            "child_count": 1,
            "reported_route": "LUNA_READ_PARALLEL",
            "luna_model_proven": False,
            "max_effort_proven": False,
            "codex_exit_code": 0,
            "validation_exit_code": 0,
            "changed_paths": [],
            "final_message": "done",
        }
        violations = evaluate(case, record)
        self.assertIn("delegation lacks Luna runtime proof", violations)
        self.assertIn("delegation lacks max-effort runtime proof", violations)

    def test_credit_estimate_separates_cached_input(self) -> None:
        rate_card = load_rate_card()
        usage = {
            "input_tokens": 14_476_061,
            "cached_input_tokens": 14_214_144,
            "output_tokens": 28_844,
        }
        self.assertAlmostEqual(
            estimate_credits("gpt-5.6-sol", usage, rate_card),
            182.75514,
            places=6,
        )

    def test_rollout_accounting_splits_parent_and_child(self) -> None:
        rate_card = load_rate_card()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "parent.jsonl"
            child = root / "child.jsonl"
            parent.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"id":"parent"}}',
                        '{"type":"turn_context","payload":{"model":"gpt-5.6-sol","effort":"high"}}',
                        '{"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\\"cmd\\":\\"rg TODO src/app.py\\"}"}}',
                        '{"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":1000,"cached_input_tokens":500,"output_tokens":100}}}}',
                    ]
                ),
                encoding="utf-8",
            )
            child.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"id":"child","parent_thread_id":"parent"}}',
                        '{"type":"turn_context","payload":{"model":"gpt-5.6-luna","effort":"max"}}',
                        '{"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\\"cmd\\":\\"rg TODO src/app.py\\"}"}}',
                        '{"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":2000,"cached_input_tokens":1000,"output_tokens":100}}}}',
                    ]
                ),
                encoding="utf-8",
            )
            evidence = account_rollouts(
                parent,
                [child],
                expected_children=1,
                rate_card=rate_card,
            )
        self.assertTrue(evidence["complete"])
        self.assertAlmostEqual(evidence["parent_credits"], 0.105, places=6)
        self.assertAlmostEqual(evidence["child_credits"], 0.0085, places=6)
        self.assertAlmostEqual(evidence["total_credits"], 0.1135, places=6)
        self.assertEqual(evidence["duplicate_tool_call_count"], 1)
        self.assertTrue(evidence["economy_failure"])

    def test_summary_enforces_credit_savings_gate(self) -> None:
        def record(
            arm: str,
            credits: float,
            *,
            delegated: bool,
            task_id: str,
            trial: int,
        ) -> dict[str, object]:
            return {
                "task_id": task_id,
                "trial": trial,
                "arm": arm,
                "codex_exit_code": 0,
                "validation_exit_code": 0,
                "elapsed_seconds": 1.0,
                "parallelizable": True,
                "economy_eligible": True,
                "preferred_route": "LUNA_SINGLE_WRITE",
                "reported_route": "LUNA_SINGLE_WRITE",
                "child_count": 1 if delegated else 0,
                "luna_model_proven": delegated,
                "max_effort_proven": delegated,
                "usage": {},
                "credit_evidence": {
                    "complete": True,
                    "total_credits": credits,
                    "parent_credits": credits * 0.8,
                    "child_credits": credits * 0.2,
                    "economy_failure": False,
                },
            }

        canary = summarize_records(
            [
                record("A", 100.0, delegated=False, task_id="task-01", trial=1),
                record("B", 60.0, delegated=True, task_id="task-01", trial=1),
            ]
        )
        self.assertFalse(canary["economy_release_gate"]["passed"])
        self.assertFalse(
            canary["economy_release_gate"]["checks"]["full_task_and_trial_coverage"]
        )

        records = []
        for task_number in range(1, 19):
            for trial in range(1, 4):
                task_id = f"task-{task_number:02d}"
                records.append(
                    record("A", 100.0, delegated=False, task_id=task_id, trial=trial)
                )
                records.append(
                    record("B", 60.0, delegated=True, task_id=task_id, trial=trial)
                )
        summary = summarize_records(records)
        self.assertEqual(summary["B"]["median_credit_savings_vs_A"], 0.4)
        self.assertTrue(summary["economy_release_gate"]["passed"])


if __name__ == "__main__":
    unittest.main()
