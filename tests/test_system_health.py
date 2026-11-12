import unittest

from app.system_health import sistem_sagligi_ozetini_olustur


class SystemHealthTests(unittest.TestCase):
    def test_normal_status_has_no_recommendations(self):
        result = sistem_sagligi_ozetini_olustur(
            {
                "cpu": 25,
                "bellek_yuzde": 42,
                "disk_kullanilan_yuzde": 70,
                "sicakliklar": [{"celsius": 55}],
            }
        )

        self.assertEqual(result["durum"], "İyi")
        self.assertEqual(result["uyarilar"], [])
        self.assertEqual(result["oneriler"], [])

    def test_high_resource_use_produces_actionable_warnings(self):
        result = sistem_sagligi_ozetini_olustur(
            {
                "cpu": 95,
                "bellek_yuzde": 83,
                "disk_kullanilan_yuzde": 40,
                "sicakliklar": [],
            }
        )

        self.assertEqual(result["durum"], "Kritik")
        self.assertEqual(len(result["uyarilar"]), 2)
        self.assertEqual(len(result["oneriler"]), 2)

    def test_high_temperature_is_included_in_report(self):
        result = sistem_sagligi_ozetini_olustur(
            {
                "cpu": 20,
                "bellek_yuzde": 30,
                "disk_kullanilan_yuzde": 40,
                "sicakliklar": [{"celsius": 82}, {"celsius": 96}],
            }
        )

        self.assertEqual(result["durum"], "Kritik")
        self.assertIn("96°C", result["uyarilar"][0])

    def test_missing_optional_data_is_not_treated_as_critical(self):
        result = sistem_sagligi_ozetini_olustur(
            {
                "cpu": 20,
                "bellek_yuzde": 30,
                "disk_kullanilan_yuzde": 40,
                "sicakliklar": [],
                "ag_hatasi": "unavailable",
            }
        )

        self.assertEqual(result["durum"], "Kısmi veri")
        self.assertEqual(result["uyarilar"], [])
        self.assertEqual(result["eksik_veriler"], ["Ağ bilgisi alınamadı."])


if __name__ == "__main__":
    unittest.main()
