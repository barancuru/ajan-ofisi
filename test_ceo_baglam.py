"""CEO fact requests: only fixed gateways, validated arguments, output returned as data; a bad request never breaks the run."""
import subprocess
import unittest
from unittest import mock

import kosucu
import sunucu


class BaglamTesti(unittest.TestCase):
    def test_gecerli_istekler_sabit_gecide_gider(self):
        self.assertEqual(sunucu.baglam_komutu({"tur": "not", "sorgu": "VM envanteri"}), [kosucu.NOT_OKU, "bul", "VM envanteri"])
        self.assertEqual(sunucu.baglam_komutu({"tur": "kod", "proje": "homeos", "sorgu": "inspectRelease"}),
                         [kosucu.GRAF_OKU, "homeos", "query", "inspectRelease", "--budget=1200"])

    def test_bozuk_istekler_reddedilir(self):
        for kotu in ({"tur": "kod", "proje": "beyin", "sorgu": "xx"}, {"tur": "kod", "sorgu": "xx"},
                     {"tur": "kabuk", "sorgu": "ls"}, {"tur": "not", "sorgu": "--derinlik=2"},
                     {"tur": "not", "sorgu": "a\nb"}, {"tur": "not", "sorgu": "x"}, {"tur": "not", "sorgu": "y" * 201},
                     {"tur": "not"}, "not", None):
            self.assertIsNone(sunucu.baglam_komutu(kotu), kotu)

    def test_istek_yoksa_arac_calismaz(self):
        with mock.patch.object(sunucu.subprocess, "run") as r:
            for ham in ({"cevap": "x"}, {"baglam": []}, {"baglam": "x"}, {"baglam": [{"tur": "kabuk", "sorgu": "ls"}]}, None):
                self.assertIsNone(sunucu.ceo_baglam_getir(ham))
            r.assert_not_called()

    def test_en_fazla_uc_istek_ve_kirpma(self):
        p = subprocess.CompletedProcess([], 0, "z" * 20000, "")
        with mock.patch.object(sunucu.subprocess, "run", return_value=p) as r:
            metin = sunucu.ceo_baglam_getir({"baglam": [{"tur": "not", "sorgu": f"konu {i}"} for i in range(9)]})
        self.assertEqual(r.call_count, sunucu.CEO_BAGLAM_MAKS)
        self.assertLess(len(metin), 3 * (sunucu.CEO_BAGLAM_CIKTI + 100))

    def test_arac_hatasi_kosuyu_bozmaz(self):
        with mock.patch.object(sunucu.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertIn("araç çalışmadı", sunucu.ceo_baglam_getir({"baglam": [{"tur": "not", "sorgu": "konu"}]}))

    def test_sorgu_etiketi_kacirilir(self):
        p = subprocess.CompletedProcess([], 0, "ok", "")
        with mock.patch.object(sunucu.subprocess, "run", return_value=p):
            metin = sunucu.ceo_baglam_getir({"baglam": [{"tur": "not", "sorgu": 'a"><x'}]})
        self.assertNotIn('"><x', metin)


if __name__ == "__main__":
    unittest.main()
