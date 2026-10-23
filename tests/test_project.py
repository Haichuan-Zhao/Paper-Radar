import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_project import SKILL_DIR, check_project, parse_yaml, prose_only


class DistributionContracts(unittest.TestCase):
    def test_real_repository_passes(self):
        self.assertEqual(check_project()["skill_files"], 3)

    def test_unexpected_private_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / SKILL_DIR, root / SKILL_DIR)
            (root / SKILL_DIR / "USER_CONFIG.md").write_text("private sentinel")
            with self.assertRaisesRegex(ValueError, "allowlist"):
                check_project(root)

    def test_symlinked_skill_ancestor_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".agents").symlink_to(ROOT / ".agents", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symbolic"):
                check_project(root)

    def test_symlinked_bundle_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / SKILL_DIR, root / SKILL_DIR)
            (root / SKILL_DIR / "LICENSE").unlink()
            (root / SKILL_DIR / "LICENSE").symlink_to(ROOT / "LICENSE")
            with self.assertRaisesRegex(ValueError, "symbolic"):
                check_project(root)

    def test_yaml_rejects_duplicate_settings(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            parse_yaml("interface:\n  display_name: first\n  display_name: second\n")

    def test_markdown_fences_and_code_examples(self):
        self.assertEqual(prose_only("before\n```text\n[example](nonexistent)\n```\nafter"), "before\nafter")
        with self.assertRaisesRegex(ValueError, "Unclosed"):
            prose_only("```json\n{}")


if __name__ == "__main__":
    unittest.main()
