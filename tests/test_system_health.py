import unittest

from app.system_health import sistem_sagligi_ozetini_olustur


class SystemHealthTests(unittest.TestCase):
    def test_critical_resource_and_temperature_warnings_are_reported(self):
        health = sistem_sagligi_ozetini_olustur(
            {
                "cpu": 92,
                "bellek_yuzde": 85,
                "disk_kullanilan_yuzde": 91,
                "sicakliklar": [{"celsius": 96}],
            }
        )

        self.assertEqual(health["durum"], "Kritik")
        self.assertEqual(health["emoji"], "🔴")
        self.assertEqual(len(health["uyarilar"]), 4)
        self.assertEqual(
            health["uyarilar"][0], "İşlemci kullanımı kritik seviyede: %92."
        )
        self.assertEqual(len(health["oneriler"]), 4)

    def test_missing_measurements_are_reported_as_partial_data(self):
        health = sistem_sagligi_ozetini_olustur(
            {
                "cpu": None,
                "bellek_yuzde": "unavailable",
                "disk_kullanilan_yuzde": None,
                "sicakliklar": [],
                "surec_hatasi": "unavailable",
                "ag_hatasi": None,
                "uygulama_hatasi": None,
                "gecmis_hatasi": "unavailable",
            }
        )

        self.assertEqual(health["durum"], "Kısmi veri")
        self.assertEqual(health["uyarilar"], [])
        self.assertEqual(
            health["eksik_veriler"],
            ["Süreç bilgisi alınamadı.", "Kaynak geçmişi alınamadı."],
        )

    def test_high_resource_and_temperature_levels_need_attention(self):
        health = sistem_sagligi_ozetini_olustur(
            {
                "cpu": 80,
                "bellek_yuzde": 79,
                "disk_kullanilan_yuzde": 20,
                "sicakliklar": [{"celsius": 85}],
            }
        )

        self.assertEqual(health["durum"], "Dikkat")
        self.assertEqual(len(health["uyarilar"]), 2)


if __name__ == "__main__":
    unittest.main()
