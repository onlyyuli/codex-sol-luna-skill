from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from benchmarks.run_matrix import ROOT, activity_evidence, prepare_workspace, timeout_text
from benchmarks.run_routing_contract import evaluate, load_cases


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

    def test_routing_contract_contains_twelve_bounded_cases(self) -> None:
        cases = load_cases(ROOT / "benchmarks/routing_cases.jsonl")
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({case["id"] for case in cases}), 12)
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


if __name__ == "__main__":
    unittest.main()
