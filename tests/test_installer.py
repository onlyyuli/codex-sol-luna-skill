from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from installer import sol_luna_installer as installer


class InstallerTests(unittest.TestCase):
    def test_check_payload_includes_only_real_evidence_path(self) -> None:
        self.assertNotIn(
            "evidence_path",
            installer.check_payload(installer.Check("check", "ok", "detail")),
        )
        self.assertEqual(
            installer.check_payload(
                installer.Check("check", "ok", "detail", evidence_path="/evidence/run")
            )["evidence_path"],
            "/evidence/run",
        )

    def test_repository_remote_parsing(self) -> None:
        expected = "owner/repository"
        self.assertEqual(installer.parse_repository_from_remote("https://github.com/owner/repository.git"), expected)
        self.assertEqual(installer.parse_repository_from_remote("git@github.com:owner/repository.git"), expected)
        self.assertEqual(installer.parse_repository_from_remote("ssh://git@github.com/owner/repository"), expected)
        self.assertIsNone(installer.parse_repository_from_remote("https://example.com/owner/repository"))

    def test_settings_validation(self) -> None:
        valid = {
            "auto_min_agents": 2,
            "auto_max_agents": 4,
            "hard_max_agents": 8,
            "write_parallelism": "disjoint-only",
            "strict_model": True,
            "announce_route": True,
        }
        self.assertEqual(installer.validate_settings_data(valid), [])
        invalid = dict(valid, hard_max_agents=9, unexpected=True)
        errors = installer.validate_settings_data(invalid)
        self.assertTrue(any("unknown" in error for error in errors))
        self.assertTrue(any("<= 8" in error for error in errors))

    def test_python_39_toml_fallback(self) -> None:
        text = '''
model = "gpt-5.6-sol"
enabled = true
count = 8

[agents]
default_subagent_model = "gpt-5.6-luna"
developer_instructions = """
bounded worker
"""
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(text, encoding="utf-8")
            with mock.patch.object(installer, "_tomllib", None):
                value = installer.parse_toml_file(path)
        self.assertEqual(value["model"], "gpt-5.6-sol")
        self.assertTrue(value["enabled"])
        self.assertEqual(value["count"], 8)
        self.assertEqual(value["agents"]["default_subagent_model"], "gpt-5.6-luna")
        self.assertIn("bounded worker", value["agents"]["developer_instructions"])

    def test_managed_file_update_and_user_preservation(self) -> None:
        reporter = installer.Reporter()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.toml"
            first = installer.install_managed_file(path, b"first\n", "source", "agent", None, reporter)
            self.assertEqual(path.read_bytes(), b"first\n")
            second = installer.install_managed_file(path, b"second\n", "source", "agent", first, reporter)
            self.assertEqual(path.read_bytes(), b"second\n")
            path.write_bytes(b"user change\n")
            preserved = installer.install_managed_file(path, b"third\n", "source", "agent", second, reporter)
            self.assertEqual(path.read_bytes(), b"user change\n")
            self.assertEqual(preserved["status"], "preserved")

    def test_preexisting_file_is_never_claimed_or_overwritten(self) -> None:
        reporter = installer.Reporter()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.toml"
            path.write_bytes(b"preexisting\n")
            first = installer.install_managed_file(
                path, b"preexisting\n", "source", "agent", None, reporter
            )
            second = installer.install_managed_file(
                path, b"release two\n", "source", "agent", first, reporter
            )
            self.assertEqual(path.read_bytes(), b"preexisting\n")
            self.assertEqual(first["status"], "preserved")
            self.assertEqual(second["status"], "preserved")

    def test_uninstall_removes_unchanged_and_preserves_modified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            unchanged = codex_home / "agents/unchanged.toml"
            modified = codex_home / "sol-luna/settings.toml"
            unchanged.parent.mkdir(parents=True)
            modified.parent.mkdir(parents=True)
            unchanged.write_text("unchanged\n", encoding="utf-8")
            modified.write_text("original\n", encoding="utf-8")
            state = {
                "schema_version": 1,
                "marketplace_added": False,
                "managed_files": {
                    str(unchanged): {"sha256": installer.sha256_file(unchanged), "kind": "agent"},
                    str(modified): {"sha256": installer.sha256_file(modified), "kind": "settings"},
                },
            }
            installer.write_state(codex_home, state)
            modified.write_text("user change\n", encoding="utf-8")
            args = Namespace(codex_home=str(codex_home))
            with mock.patch("shutil.which", return_value=None):
                result = installer.uninstall(args, installer.Reporter())
            self.assertFalse(unchanged.exists())
            self.assertTrue(modified.exists())
            self.assertEqual(result["preserved"], [str(modified)])
            residual = json.loads(installer.state_path(codex_home).read_text(encoding="utf-8"))
            self.assertEqual(list(residual["managed_files"]), [str(modified)])

    def test_uninstall_preserves_smoke_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            evidence = codex_home / "sol-luna/evidence/smoke-test/manifest.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("{}\n", encoding="utf-8")
            installer.write_state(
                codex_home,
                {
                    "schema_version": 1,
                    "marketplace_added": False,
                    "managed_files": {},
                },
            )
            args = Namespace(codex_home=str(codex_home))
            with mock.patch("shutil.which", return_value=None):
                result = installer.uninstall(args, installer.Reporter())
            self.assertEqual(result["status"], "ok")
            self.assertTrue(evidence.is_file())

    def test_uninstall_preserves_preexisting_identical_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            preexisting = codex_home / "agents/sol-luna-reader.toml"
            preexisting.parent.mkdir(parents=True)
            preexisting.write_text("same as release\n", encoding="utf-8")
            state = {
                "schema_version": 1,
                "marketplace_added": False,
                "managed_files": {
                    str(preexisting): {
                        "sha256": installer.sha256_file(preexisting),
                        "kind": "agent",
                        "status": "preserved",
                    }
                },
            }
            installer.write_state(codex_home, state)
            args = Namespace(codex_home=str(codex_home))
            with mock.patch("shutil.which", return_value=None):
                result = installer.uninstall(args, installer.Reporter())
            self.assertTrue(preexisting.exists())
            self.assertEqual(result["preserved"], [str(preexisting)])

    def test_uninstall_refuses_state_path_outside_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            outside = root / "outside.toml"
            outside.write_text("do not delete\n", encoding="utf-8")
            state = {
                "schema_version": 1,
                "marketplace_added": False,
                "managed_files": {
                    str(outside): {
                        "sha256": installer.sha256_file(outside),
                        "kind": "agent",
                        "status": "managed",
                    }
                },
            }
            installer.write_state(codex_home, state)
            args = Namespace(codex_home=str(codex_home))
            with mock.patch("shutil.which", return_value=None):
                result = installer.uninstall(args, installer.Reporter())
            self.assertTrue(outside.exists())
            self.assertEqual(result["preserved"], [str(outside)])

    def test_resolve_repository_from_environment(self) -> None:
        with mock.patch.dict(os.environ, {"SOL_LUNA_REPOSITORY": "owner/repo"}, clear=False):
            self.assertEqual(installer.resolve_repository(None, None), "owner/repo")

    def test_owned_marketplace_ref_rotation_is_bounded(self) -> None:
        state = {
            "repository": "owner/repo",
            "ref": "v0.1.0",
            "marketplace_added": True,
        }
        marketplace = {
            installer.MARKETPLACE_NAME: {
                "marketplaceSource": {
                    "sourceType": "github",
                    "source": "owner/repo",
                }
            }
        }
        plugins = [
            {
                "pluginId": installer.PLUGIN_ID,
                "marketplaceName": installer.MARKETPLACE_NAME,
            }
        ]
        added = {"marketplaceName": installer.MARKETPLACE_NAME}
        with mock.patch.object(
            installer, "marketplace_map", return_value=marketplace
        ), mock.patch.object(installer, "installed_plugins", return_value=plugins):
            with mock.patch.object(
                installer, "command_json", side_effect=[{}, {}, added]
            ) as command, mock.patch.object(installer, "ensure_plugin") as ensure:
                rotated = installer.rotate_owned_marketplace_ref(
                    "codex",
                    Path("/tmp/test-codex-home"),
                    state=state,
                    repository="owner/repo",
                    ref="v0.1.1",
                    reporter=installer.Reporter(),
                )
        self.assertTrue(rotated)
        self.assertEqual(command.call_count, 3)
        self.assertIn("v0.1.1", command.call_args_list[-1].args[0])
        ensure.assert_called_once()

    def test_owned_marketplace_ref_rotation_refuses_other_plugins(self) -> None:
        state = {
            "repository": "owner/repo",
            "ref": "v0.1.0",
            "marketplace_added": True,
        }
        marketplace = {
            installer.MARKETPLACE_NAME: {
                "marketplaceSource": {
                    "sourceType": "github",
                    "source": "owner/repo",
                }
            }
        }
        plugins = [
            {
                "pluginId": "other@codex-sol-luna",
                "marketplaceName": installer.MARKETPLACE_NAME,
            }
        ]
        with mock.patch.object(
            installer, "marketplace_map", return_value=marketplace
        ), mock.patch.object(installer, "installed_plugins", return_value=plugins):
            with self.assertRaisesRegex(installer.InstallerError, "unrelated plugins"):
                installer.rotate_owned_marketplace_ref(
                    "codex",
                    Path("/tmp/test-codex-home"),
                    state=state,
                    repository="owner/repo",
                    ref="v0.1.1",
                    reporter=installer.Reporter(),
                )

    def test_smoke_models_fails_fast_without_login(self) -> None:
        version = subprocess.CompletedProcess(
            args=["codex", "--version"],
            returncode=0,
            stdout="codex-cli test\n",
            stderr="",
        )
        login = subprocess.CompletedProcess(
            args=["codex", "login", "status"],
            returncode=1,
            stdout="Not logged in\n",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            installer, "run_command", side_effect=[version, login]
        ) as run, mock.patch.object(
            installer, "make_smoke_marker", return_value="LUNA_SMOKE_OK_TEST"
        ):
            check = installer.smoke_models("codex", Path(directory), Path.cwd())
            manifest = json.loads(
                (Path(check.evidence_path) / "manifest.json").read_text(encoding="utf-8")
            )
        self.assertEqual(check.status, "error")
        self.assertIn("not logged in", check.detail.lower())
        self.assertEqual(run.call_count, 2)
        self.assertEqual(manifest["execution"]["status"], "preflight_failed")
        self.assertEqual(manifest["verification"]["verification_level"], "requested_only")

    def test_smoke_models_rejects_parent_only_success_marker(self) -> None:
        marker = "LUNA_SMOKE_OK_TEST"
        version = subprocess.CompletedProcess(
            args=["codex", "--version"], returncode=0, stdout="codex-cli test\n", stderr=""
        )
        login = subprocess.CompletedProcess(
            args=["codex", "login", "status"], returncode=0, stdout="Logged in\n", stderr=""
        )
        smoke = subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"agent_message",'
                f'"text":"{marker}"}}}}\n'
            ),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            installer, "run_command", side_effect=[version, login, smoke]
        ), mock.patch.object(installer, "make_smoke_marker", return_value=marker):
            check = installer.smoke_models("codex", Path(directory), Path.cwd())
        self.assertEqual(check.status, "error")
        self.assertIn("0 child thread", check.detail)

    def test_smoke_models_rejects_parent_marker_for_observed_child(self) -> None:
        marker = "LUNA_SMOKE_OK_TEST"
        version = subprocess.CompletedProcess(
            args=["codex", "--version"], returncode=0, stdout="codex-cli test\n", stderr=""
        )
        login = subprocess.CompletedProcess(
            args=["codex", "login", "status"], returncode=0, stdout="Logged in\n", stderr=""
        )
        smoke = subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"collab_tool_call",'
                '"receiver_thread_ids":["child-1"],"model":"gpt-5.6-luna",'
                '"reasoning_effort":"max","agents_states":{"child-1":"completed"}}}\n'
                '{"type":"item.completed","item":{"type":"agent_message",'
                f'"text":"{marker}"}}}}\n'
            ),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            installer, "run_command", side_effect=[version, login, smoke]
        ), mock.patch.object(installer, "make_smoke_marker", return_value=marker):
            check = installer.smoke_models("codex", Path(directory), Path.cwd())
            manifest = json.loads(
                (Path(check.evidence_path) / "manifest.json").read_text(encoding="utf-8")
            )
        self.assertEqual(check.status, "error")
        self.assertIn("only outside child-linked activity", check.detail)
        self.assertFalse(manifest["verification"]["marker_proven_for_child"])

    def test_cached_luna_model_check_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            cache = {
                "models": [
                    {
                        "slug": "gpt-5.6-luna",
                        "supported_reasoning_levels": [{"effort": "max"}],
                    }
                ]
            }
            (codex_home / "models_cache.json").write_text(
                json.dumps(cache), encoding="utf-8"
            )
            check = installer.inspect_cached_luna_model(codex_home)
        self.assertEqual(check.status, "ok")
        self.assertIn("runtime use still requires smoke evidence", check.detail)

    def test_smoke_models_reports_unproven_model_honestly(self) -> None:
        marker = "LUNA_SMOKE_OK_TEST"
        version = subprocess.CompletedProcess(
            args=["codex", "--version"], returncode=0, stdout="codex-cli test\n", stderr=""
        )
        login = subprocess.CompletedProcess(
            args=["codex", "login", "status"], returncode=0, stdout="Logged in\n", stderr=""
        )
        smoke = subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"collab_tool_call",'
                '"receiver_thread_ids":["child-1"],'
                f'"result":"{marker}","agents_states":{{"child-1":"completed"}}}}}}\n'
            ),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            installer, "run_command", side_effect=[version, login, smoke]
        ), mock.patch.object(installer, "make_smoke_marker", return_value=marker):
            check = installer.smoke_models("codex", Path(directory), Path.cwd())
        self.assertEqual(check.status, "error")
        self.assertIn("did not prove its effective model", check.detail)

    def test_smoke_models_requires_max_effort_proof(self) -> None:
        marker = "LUNA_SMOKE_OK_TEST"
        version = subprocess.CompletedProcess(
            args=["codex", "--version"], returncode=0, stdout="codex-cli test\n", stderr=""
        )
        login = subprocess.CompletedProcess(
            args=["codex", "login", "status"], returncode=0, stdout="Logged in\n", stderr=""
        )
        smoke = subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"collab_tool_call",'
                '"receiver_thread_ids":["child-1"],"model":"gpt-5.6-luna",'
                f'"result":"{marker}","agents_states":{{"child-1":"completed"}}}}}}\n'
            ),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            installer, "run_command", side_effect=[version, login, smoke]
        ), mock.patch.object(installer, "make_smoke_marker", return_value=marker):
            check = installer.smoke_models("codex", Path(directory), Path.cwd())
            manifest = json.loads(
                (Path(check.evidence_path) / "manifest.json").read_text(encoding="utf-8")
            )
        self.assertEqual(check.status, "error")
        self.assertIn("max effort", check.detail)
        self.assertEqual(manifest["verification"]["verification_level"], "luna_verified")

    def test_smoke_models_passes_only_with_model_and_effort_proof(self) -> None:
        marker = "LUNA_SMOKE_OK_TEST"
        version = subprocess.CompletedProcess(
            args=["codex", "--version"], returncode=0, stdout="codex-cli test\n", stderr=""
        )
        login = subprocess.CompletedProcess(
            args=["codex", "login", "status"], returncode=0, stdout="Logged in\n", stderr=""
        )
        smoke = subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"collab_tool_call",'
                '"receiver_thread_ids":["child-1"],"model":"gpt-5.6-luna",'
                f'"reasoning_effort":"max","result":"{marker}",'
                '"agents_states":{"child-1":"completed"}}}\n'
            ),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            installer, "run_command", side_effect=[version, login, smoke]
        ), mock.patch.object(installer, "make_smoke_marker", return_value=marker):
            check = installer.smoke_models("codex", Path(directory), Path.cwd())
            bundle = Path(check.evidence_path)
            manifest_bytes = (bundle / "manifest.json").read_bytes()
            events_bytes = (bundle / "events.jsonl").read_bytes()
            manifest = json.loads(manifest_bytes)
            checksums = (bundle / "SHA256SUMS").read_text(encoding="utf-8")
        self.assertEqual(check.status, "ok")
        self.assertEqual(events_bytes, smoke.stdout.encode("utf-8"))
        self.assertEqual(manifest["codex_version"], "codex-cli test")
        self.assertEqual(manifest["verification"]["verification_level"], "luna_max_verified")
        self.assertIn(installer.sha256_bytes(events_bytes), checksums)
        self.assertIn(installer.sha256_bytes(manifest_bytes), checksums)
        self.assertEqual(manifest["artifacts"]["events.jsonl"]["sha256"], installer.sha256_bytes(events_bytes))

    def test_smoke_activity_rejects_ambiguous_effective_metadata(self) -> None:
        marker = "LUNA_SMOKE_OK_TEST"
        stdout = (
            '{"type":"item.completed","item":{"type":"collab_tool_call",'
            '"receiver_thread_ids":["child-1"],"model":"gpt-5.6-luna",'
            '"selected_model":"gpt-5.6-sol","reasoning_effort":"max",'
            f'"model_reasoning_effort":"high","result":"{marker}",'
            '"agents_states":{"child-1":"completed"}}}\n'
        )
        assessment = installer.assess_smoke_activity(stdout, marker)
        self.assertFalse(assessment["luna_model_proven"])
        self.assertFalse(assessment["max_effort_proven"])
        self.assertEqual(assessment["verification_level"], "requested_only")

    def test_smoke_activity_retains_runtime_error_messages(self) -> None:
        stdout = (
            '{"type":"item.completed","item":{"type":"error",'
            '"message":"transport timed out"}}\n'
        )
        assessment = installer.assess_smoke_activity(stdout, "LUNA_SMOKE_OK_TEST")
        self.assertEqual(assessment["activity_errors"], ["transport timed out"])

    def test_smoke_models_explicitly_enables_subagent_capability(self) -> None:
        version = subprocess.CompletedProcess(
            args=["codex", "--version"], returncode=0, stdout="codex-cli test\n", stderr=""
        )
        login = subprocess.CompletedProcess(
            args=["codex", "login", "status"], returncode=0, stdout="Logged in\n", stderr=""
        )
        failed = subprocess.CompletedProcess(
            args=["codex", "exec"], returncode=0, stdout="", stderr=""
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            installer, "run_command", side_effect=[version, login, failed]
        ) as run:
            installer.smoke_models("codex", Path(directory), Path.cwd())
        command = run.call_args_list[2].args[0]
        self.assertIn("multi_agent", command)
        self.assertIn("agents.enabled=true", command)
        prompt = command[-1]
        self.assertIn("functions.collaboration.spawn_agent", prompt)
        self.assertIn("task_name luna_smoke", prompt)
        self.assertIn("fork_turns none", prompt)
        self.assertIn("model gpt-5.6-luna", prompt)
        self.assertIn("reasoning_effort max", prompt)


if __name__ == "__main__":
    unittest.main()
