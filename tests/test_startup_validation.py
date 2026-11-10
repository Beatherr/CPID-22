import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import start_services
from app import setup_config


class StartupValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.config_patch = patch.object(
            start_services, "AYAR_DOSYASI", self.config_path
        )
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def write_config(self, notice_version):
        self.config_path.write_text(
            json.dumps(
                {
                    "BOT_TOKEN": "test-token",
                    "ALLOWED_USER_ID": 1,
                    "GUILD_ID": 2,
                    "CHANNEL_ID": 3,
                    "CONSENT": {
                        "notice_version": notice_version,
                        "accepted_at_utc": "2026-11-06T00:00:00+00:00",
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_outdated_consent_explains_how_to_renew_without_exposing_token(self):
        self.write_config("older-notice")

        with self.assertRaisesRegex(ValueError, "setup.bat içinden 1'i seçin"):
            start_services.ayarlari_oku()

    def test_current_consent_allows_startup(self):
        self.write_config(start_services.ONAY_SURUMU)

        config = start_services.ayarlari_oku()

        self.assertEqual(config["ALLOWED_USER_ID"], 1)

    def test_startup_uses_the_consent_version_written_by_setup(self):
        self.assertEqual(start_services.ONAY_SURUMU, setup_config.ONAY_SURUMU)


if __name__ == "__main__":
    unittest.main()
