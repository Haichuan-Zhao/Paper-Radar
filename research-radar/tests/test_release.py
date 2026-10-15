"""Publishing must exclude user material and reject a personalised intake."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

PROJECT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release_builder", PROJECT / "scripts/package_skill.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "research-radar"
        for relative in builder.FILES:
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(builder.SOURCE / relative, target)

    def test_private_files_are_excluded_and_archive_is_reproducible(self):
        private = self.source / "private"
        private.mkdir()
        secret = "synthetic-private-release-marker-742"
        (private / "credentials.json").write_text(json.dumps({"password": secret}))
        (self.source / "user-config.md").write_text(secret)
        with patch.object(builder, "SOURCE", self.source):
            one = builder.build(self.root / "one")
            two = builder.build(self.root / "two")
        self.assertEqual(one["archives"], two["archives"])
        with zipfile.ZipFile(self.root / "one/research-radar.zip") as bundle:
            self.assertIn("research-radar/LICENSE", bundle.namelist())
            for name in bundle.namelist():
                self.assertNotIn(secret.encode(), bundle.read(name))
                self.assertNotIn("/private/", name)
                self.assertNotIn("/tests/", name)

    def test_personalised_template_or_inline_secret_stops_packaging(self):
        template = self.source / "USER_CONFIG.template.md"
        original = builder.read_profile_document(template)
        for field in ("user_prompt", "secret_key", "password"):
            payload = json.loads(json.dumps(original))
            secret = "synthetic-do-not-publish-619"
            if field == "user_prompt":
                payload[field] = secret
            elif field == "secret_key":
                payload["easyscholar"][field] = secret
            else:
                payload["fulltext_access"]["institution"]["routing"][field] = secret
            template.write_text("```json\n" + json.dumps(payload) + "\n```\n")
            with self.subTest(field=field), patch.object(builder, "SOURCE", self.source), self.assertRaises(ValueError) as error:
                builder.build(self.root / "rejected")
            self.assertNotIn(secret, str(error.exception))
            self.assertFalse((self.root / "rejected/research-radar.zip").exists())


if __name__ == "__main__":
    unittest.main()
