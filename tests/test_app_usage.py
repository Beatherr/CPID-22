from contextlib import closing
import sqlite3
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import client


class AppUsageHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "metrics.sqlite3"
        self.database_patch = patch.object(client, "GECMIS_DOSYASI", self.database_path)
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def test_summary_sorts_apps_and_excludes_records_older_than_seven_days(self):
        now = time.time()
        client.uygulama_kullanimini_kaydet("Game.exe", 120, now - 60)
        client.uygulama_kullanimini_kaydet("Browser.exe", 300, now - 30)
        client.uygulama_kullanimini_kaydet("Game.exe", 60, now - 10)
        client.uygulama_kullanimini_kaydet("Old.exe", 900, now - 8 * 24 * 60 * 60)

        self.assertEqual(
            client.uygulama_kullanim_ozetini_getir(),
            [
                {"ad": "Browser.exe", "saniye": 300},
                {"ad": "Game.exe", "saniye": 180},
            ],
        )

    def test_expired_records_are_removed(self):
        client.uygulama_kullanimini_kaydet(
            "Old.exe", 900, time.time() - 8 * 24 * 60 * 60
        )

        client.uygulama_kullanim_gecmisini_temizle()

        with closing(sqlite3.connect(self.database_path)) as connection:
            row_count = connection.execute(
                "SELECT COUNT(*) FROM uygulama_kullanimi"
            ).fetchone()[0]
        self.assertEqual(row_count, 0)

    def test_clear_removes_all_usage_records(self):
        client.uygulama_kullanimini_kaydet("Game.exe", 120)

        client.uygulama_kullanim_gecmisini_sil()

        self.assertEqual(client.uygulama_kullanim_ozetini_getir(), [])

    def test_summary_rejects_invalid_day_ranges(self):
        with self.assertRaises(ValueError):
            client.uygulama_kullanim_ozetini_getir(8)

    def test_daily_summary_groups_records_by_local_date(self):
        now = time.time()
        client.uygulama_kullanimini_kaydet("Game.exe", 120, now - 60)
        client.uygulama_kullanimini_kaydet("Game.exe", 300, now - 24 * 60 * 60)

        summary = client.uygulama_kullanim_gunluk_ozetini_getir(2)
        today = datetime.fromtimestamp(now).astimezone().date().isoformat()
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()

        self.assertEqual(summary[today]["Game.exe"], 120)
        self.assertEqual(summary[yesterday]["Game.exe"], 300)

    def test_daily_usage_chart_returns_png(self):
        client.uygulama_kullanimini_kaydet("Game.exe", 120)

        chart = client.uygulama_kullanim_grafigi_olustur()

        self.assertEqual(chart.read(8), b"\x89PNG\r\n\x1a\n")

    def test_usage_tracking_setting_is_saved_atomically(self):
        config_path = self.database_path.parent / "config.json"
        config_path.write_text(
            '{"BOT_TOKEN":"test","TRACK_APP_USAGE":false}',
            encoding="utf-8",
        )
        with patch.object(client, "AYAR_DOSYASI", config_path):
            client.uygulama_kullanim_takibini_ayarla(True)

        saved = config_path.read_text(encoding="utf-8")
        self.assertIn('"TRACK_APP_USAGE": true', saved)
        self.assertFalse(config_path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
