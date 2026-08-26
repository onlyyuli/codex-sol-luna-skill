from __future__ import annotations

import json
import unittest
from pathlib import Path

from installer import sol_luna_installer as installer


ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_plugin_and_marketplace_identifiers_match(self) -> None:
        plugin = json.loads((ROOT / "plugins/sol-luna/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], installer.PLUGIN_NAME)
        self.assertEqual(plugin["version"], installer.VERSION)
        self.assertEqual(marketplace["name"], installer.MARKETPLACE_NAME)
        self.assertEqual(marketplace["plugins"][0]["name"], installer.PLUGIN_NAME)

    def test_skill_is_explicit_only(self) -> None:
        metadata = (ROOT / "plugins/sol-luna/skills/sol-luna/agents/openai.yaml").read_text(encoding="utf-8")
        self.assertIn("allow_implicit_invocation: false", metadata)

    def test_root_does_not_pin_codex_model(self) -> None:
        self.assertFalse((ROOT / ".codex/config.toml").exists())

    def test_agent_contracts(self) -> None:
        reader_errors = installer.inspect_agent(
            ROOT / "config/agents/sol-luna-reader.toml", "sol_luna_reader", "read-only"
        )
        worker_errors = installer.inspect_agent(
            ROOT / "config/agents/sol-luna-worker.toml", "sol_luna_worker", "workspace-write"
        )
        self.assertEqual(reader_errors, [])
        self.assertEqual(worker_errors, [])


if __name__ == "__main__":
    unittest.main()
