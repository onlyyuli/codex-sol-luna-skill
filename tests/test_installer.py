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
    def test_codex_release_channel_distinguishes_prerelease(self) -> None:
        self.assertEqual(
            installer.codex_release_channel("codex-cli 0.149.1"),
            ("ok", "stable CLI detected (0.149.1)"),
        )
        status, detail = installer.codex_release_channel("codex-cli 0.149.0-alpha.4.3")
        self.assertEqual(status, "warning")
        self.assertIn("pre-release", detail)

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
            "routing_objective": "minimize-credits",
            "auto_min_agents": 1,
            "auto_max_agents": 2,
            "hard_max_agents": 8,
            "write_parallelism": "disjoint-only",
            "parent_review": "targeted",
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

    def test_local_marketplace_upgrade_does_not_call_git_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory).resolve()
            marketplace = {
                installer.MARKETPLACE_NAME: {
                    "marketplaceSource": {
                        # Some Codex builds omit sourceType for local marketplaces.
                        "source": str(repo_root),
                    }
                }
            }
            with mock.patch.object(
                installer, "marketplace_map", return_value=marketplace
            ), mock.patch.object(installer, "run_command") as run:
                added = installer.ensure_marketplace(
                    "codex",
                    repo_root / "codex-home",
                    "owner/repo",
                    "v0.1.0",
                    repo_root,
                    installer.Reporter(),
                    upgrade=True,
                )
        self.assertFalse(added)
        run.assert_not_called()

    def test_git_marketplace_upgrade_calls_refresh(self) -> None:
        marketplace = {
            installer.MARKETPLACE_NAME: {
                "marketplaceSource": {
                    "sourceType": "github",
                    "source": "owner/repo",
                }
            }
        }
        with mock.patch.object(
            installer, "marketplace_map", return_value=marketplace
        ), mock.patch.object(installer, "run_command") as run:
            added = installer.ensure_marketplace(
                "codex",
                Path("/tmp/test-codex-home"),
                "owner/repo",
                "v0.1.0",
                None,
                installer.Reporter(),
                upgrade=True,
            )
        self.assertFalse(added)
        run.assert_called_once_with(
            ["codex", "plugin", "marketplace", "upgrade", installer.MARKETPLACE_NAME],
            codex_home=Path("/tmp/test-codex-home"),
        )

    def test_configured_marketplace_reads_broken_source_without_loading_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            (codex_home / "config.toml").write_text(
                """
[marketplaces.codex-sol-luna]
source_type = "local"
source = "/missing/old-repository"

[plugins."sol-luna@codex-sol-luna"]
enabled = true
""",
                encoding="utf-8",
            )
            marketplace = installer.configured_marketplace(
                codex_home, installer.MARKETPLACE_NAME
            )
            plugins = installer.configured_marketplace_plugins(
                codex_home, installer.MARKETPLACE_NAME
            )
        self.assertEqual(
            marketplace,
            {"source": "/missing/old-repository", "source_type": "local"},
        )
        self.assertEqual(plugins, {installer.PLUGIN_ID})

    def test_owned_broken_marketplace_source_can_be_replaced(self) -> None:
        state = {
            "repository": "owner/old-repo",
            "ref": "v0.1.0",
            "marketplace_source": "/missing/old-repository",
            "marketplace_name": installer.MARKETPLACE_NAME,
            "marketplace_added": True,
            "plugin_id": installer.PLUGIN_ID,
        }
        existing = {"source": "/missing/old-repository", "source_type": "local"}
        added = {"marketplaceName": installer.MARKETPLACE_NAME}
        with mock.patch.object(
            installer, "configured_marketplace", side_effect=[existing]
        ), mock.patch.object(
            installer, "configured_marketplace_plugins", return_value={installer.PLUGIN_ID}
        ), mock.patch.object(
            installer, "command_json", side_effect=[{}, added]
        ) as command, mock.patch.object(installer, "ensure_plugin") as ensure:
            replaced = installer.replace_owned_marketplace_source(
                "codex",
                Path("/tmp/test-codex-home"),
                state=state,
                repository="owner/new-repo",
                ref="v0.1.0",
                repo_root=Path("/tmp/new-repository"),
                reporter=installer.Reporter(),
            )
        self.assertTrue(replaced)
        self.assertEqual(command.call_count, 2)
        self.assertEqual(
            command.call_args_list[0].args[0],
            ["codex", "plugin", "marketplace", "remove", installer.MARKETPLACE_NAME, "--json"],
        )
        self.assertIn(str(Path("/tmp/new-repository")), command.call_args_list[1].args[0])
        ensure.assert_called_once()

    def test_marketplace_source_replacement_refuses_unowned_entry(self) -> None:
        existing = {"source": "/someone/else/repository", "source_type": "local"}
        with mock.patch.object(
            installer, "configured_marketplace", return_value=existing
        ), mock.patch.object(installer, "command_json") as command:
            with self.assertRaisesRegex(installer.InstallerError, "does not own"):
                installer.replace_owned_marketplace_source(
                    "codex",
                    Path("/tmp/test-codex-home"),
                    state={},
                    repository="owner/new-repo",
                    ref="v0.1.0",
                    repo_root=Path("/tmp/new-repository"),
                    reporter=installer.Reporter(),
                )
        command.assert_not_called()

    def test_marketplace_source_replacement_refuses_other_plugins(self) -> None:
        state = {
            "marketplace_source": "/old/repository",
            "marketplace_name": installer.MARKETPLACE_NAME,
            "marketplace_added": True,
            "plugin_id": installer.PLUGIN_ID,
        }
        existing = {"source": "/old/repository", "source_type": "local"}
        with mock.patch.object(
            installer, "configured_marketplace", return_value=existing
        ), mock.patch.object(
            installer,
            "configured_marketplace_plugins",
            return_value={installer.PLUGIN_ID, "other@codex-sol-luna"},
        ), mock.patch.object(installer, "command_json") as command:
            with self.assertRaisesRegex(installer.InstallerError, "unrelated configured plugins"):
                installer.replace_owned_marketplace_source(
                    "codex",
                    Path("/tmp/test-codex-home"),
                    state=state,
                    repository="owner/new-repo",
                    ref="v0.1.0",
                    repo_root=Path("/tmp/new-repository"),
                    reporter=installer.Reporter(),
                )
        command.assert_not_called()

    def test_marketplace_source_replacement_rolls_back_when_old_source_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_source = root / "old-repository"
            new_source = root / "new-repository"
            old_source.mkdir()
            new_source.mkdir()
            state = {
                "repository": "owner/old-repo",
                "ref": "v0.1.0",
                "marketplace_source": str(old_source),
                "marketplace_name": installer.MARKETPLACE_NAME,
                "marketplace_added": True,
                "plugin_id": installer.PLUGIN_ID,
            }
            existing = {"source": str(old_source), "source_type": "local"}
            restored = {"marketplaceName": installer.MARKETPLACE_NAME}
            with mock.patch.object(
                installer,
                "configured_marketplace",
                side_effect=[existing, None],
            ), mock.patch.object(
                installer,
                "configured_marketplace_plugins",
                return_value={installer.PLUGIN_ID},
            ), mock.patch.object(
                installer,
                "command_json",
                side_effect=[{}, installer.InstallerError("new source failed"), restored],
            ) as command, mock.patch.object(installer, "ensure_plugin") as ensure:
                with self.assertRaisesRegex(installer.InstallerError, "previous source was restored"):
                    installer.replace_owned_marketplace_source(
                        "codex",
                        root / "codex-home",
                        state=state,
                        repository="owner/new-repo",
                        ref="v0.1.0",
                        repo_root=new_source,
                        reporter=installer.Reporter(),
                    )
            self.assertEqual(command.call_count, 3)
            self.assertIn(str(old_source), command.call_args_list[-1].args[0])
            ensure.assert_called_once()

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

    def test_smoke_models_uses_new_linked_rollouts_when_cli_jsonl_omits_child_metadata(self) -> None:
        marker = "LUNA_SMOKE_OK_TEST"
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            sessions = codex_home / "sessions/2026/08/27"

            def fake_run(command, **kwargs):
                if command[1:] == ["--version"]:
                    return subprocess.CompletedProcess(
                        args=command, returncode=0, stdout="codex-cli test\n", stderr=""
                    )
                if command[1:] == ["login", "status"]:
                    return subprocess.CompletedProcess(
                        args=command, returncode=0, stdout="Logged in\n", stderr=""
                    )
                sessions.mkdir(parents=True)
                parent = sessions / "rollout-parent.jsonl"
                child = sessions / "rollout-child.jsonl"
                parent.write_text(
                    "\n".join(
                        [
                            json.dumps(
                                {"type": "session_meta", "payload": {"id": "parent-1"}}
                            ),
                            json.dumps(
                                {
                                    "type": "event_msg",
                                    "payload": {
                                        "type": "item_completed",
                                        "item": {
                                            "type": "SubAgentActivity",
                                            "kind": "started",
                                            "agent_thread_id": "child-1",
                                        },
                                    },
                                }
                            ),
                            json.dumps(
                                {
                                    "type": "event_msg",
                                    "payload": {
                                        "type": "item_completed",
                                        "item": {
                                            "type": "SubAgentActivity",
                                            "kind": "completed",
                                            "agent_thread_id": "child-1",
                                        },
                                    },
                                }
                            ),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                child.write_text(
                    "\n".join(
                        [
                            json.dumps(
                                {
                                    "type": "session_meta",
                                    "payload": {
                                        "id": "child-1",
                                        "parent_thread_id": "parent-1",
                                    },
                                }
                            ),
                            json.dumps(
                                {
                                    "type": "turn_context",
                                    "payload": {
                                        "model": "gpt-5.6-luna",
                                        "collaboration_mode": {
                                            "settings": {"reasoning_effort": "max"}
                                        },
                                    },
                                }
                            ),
                            json.dumps(
                                {
                                    "type": "response_item",
                                    "payload": {
                                        "type": "message",
                                        "role": "assistant",
                                        "content": [{"type": "output_text", "text": marker}],
                                    },
                                }
                            ),
                            json.dumps(
                                {"type": "event_msg", "payload": {"type": "task_complete"}}
                            ),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                stdout = (
                    '{"type":"thread.started","thread_id":"parent-1"}\n'
                    '{"type":"item.completed","item":{"type":"collab_tool_call",'
                    '"receiver_thread_ids":[],"agents_states":{}}}\n'
                )
                return subprocess.CompletedProcess(
                    args=command, returncode=0, stdout=stdout, stderr=""
                )

            with mock.patch.object(installer, "run_command", side_effect=fake_run), mock.patch.object(
                installer, "make_smoke_marker", return_value=marker
            ):
                check = installer.smoke_models("codex", codex_home, Path.cwd())
            bundle = Path(check.evidence_path)
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(check.status, "ok")
        self.assertEqual(manifest["verification"]["child_thread_ids"], ["child-1"])
        self.assertEqual(
            manifest["verification"]["verification_sources"], ["persisted_rollouts"]
        )
        self.assertIn("parent-rollout.jsonl", manifest["artifacts"])
        self.assertIn("child-rollout-child-1.jsonl", manifest["artifacts"])

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
        self.assertIn("--strict-config", command)
        self.assertNotIn("--ephemeral", command)
        self.assertNotIn("model_providers.openai.supports_websockets=false", command)
        self.assertIn('model_provider="sol_luna_smoke_http"', command)
        provider_config = next(item for item in command if item.startswith("model_providers="))
        self.assertIn("sol_luna_smoke_http", provider_config)
        self.assertIn("supports_websockets=false", provider_config)
        self.assertIn("requires_openai_auth=true", provider_config)
        prompt = command[-1]
        self.assertIn("functions.collaboration.spawn_agent", prompt)
        self.assertIn("task_name luna_smoke", prompt)
        self.assertIn("fork_turns none", prompt)
        self.assertIn("model gpt-5.6-luna", prompt)
        self.assertIn("reasoning_effort max", prompt)


if __name__ == "__main__":
    unittest.main()
