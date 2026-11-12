import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    def test_packaged_client_process_requires_the_client_mode_argument(self):
        executable = r"C:\Program Files\PCActivityMonitor\PCActivityMonitor.exe"
        normalized_path = start_services.os.path.normcase(
            start_services.os.path.abspath(executable)
        )
        with patch.object(start_services, "PAKETLENMIS", True), patch.object(
            start_services, "ISTEMCI_BETIGI", normalized_path
        ):
            client_process = SimpleNamespace(info={"cmdline": [executable, "--client"]})
            services_process = SimpleNamespace(info={"cmdline": [executable, "--services"]})

            self.assertTrue(start_services.surec_istemciyle_eslesiyor(client_process))
            self.assertFalse(start_services.surec_istemciyle_eslesiyor(services_process))

    def test_packaged_client_is_started_with_client_mode_argument(self):
        executable = r"C:\Program Files\PCActivityMonitor\PCActivityMonitor.exe"
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(start_services, "DURUM_DIZINI", Path(temp_dir)), patch.object(
                start_services, "PAKETLENMIS", True
            ), patch.object(start_services.sys, "executable", executable), patch.object(
                start_services.subprocess, "Popen", return_value=object()
            ) as popen:
                start_services.istemciyi_baslat(None)

        self.assertEqual(popen.call_args.args[0], [executable, "--client"])


if __name__ == "__main__":
    unittest.main()
