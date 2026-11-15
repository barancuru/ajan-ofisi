"""Metin girdisi sınırı (ortak.MAKS_GIRDI) ve /api/gelistirme gövde sınırı: python3 -m unittest test_girdi_siniri"""
import io
import json
import tempfile
import types
import unittest
from unittest import mock

import ortak
import sunucu


def _govde_oku(govde_bayt, maks):
    """Isleyici._govde'yi gerçek soket olmadan çalıştır."""
    kendi = types.SimpleNamespace(
        headers={"Content-Length": str(len(govde_bayt)), "Content-Type": "application/json"},
        rfile=io.BytesIO(govde_bayt), close_connection=False)
    return sunucu.Isleyici._govde(kendi, maks)


class GirdiSiniriTesti(unittest.TestCase):
    def test_sinir_yirmi_bin(self):
        self.assertEqual(ortak.MAKS_GIRDI, 20_000)

    def test_gelistirme_govdesi_en_kotu_durumu_karsilar(self):
        # Türkçe harf (2 bayt) ve satır sonu (JSON'da \n = 2 bayt): 20.000 karakter
        istek = ("Şğüöçı\n" * 4000)[:ortak.MAKS_GIRDI]
        ham = json.dumps({"islem": "yeni", "proje": "ajan-ofisi", "baslik": "Deneme başlığı", "istek": istek},
                         ensure_ascii=False).encode("utf-8")
        self.assertGreater(len(ham), sunucu.MAKS_GOVDE)  # varsayılan sınıra takılırdı
        self.assertEqual(len(_govde_oku(ham, sunucu.MAKS_GOVDE_GELISTIRME)["istek"]), ortak.MAKS_GIRDI)
        # kontrol karakterleri JSON'da \u00XX (6 bayt): yine sığmalı
        ham = json.dumps({"istek": "\x01" * ortak.MAKS_GIRDI}).encode()
        self.assertLessEqual(len(ham), sunucu.MAKS_GOVDE_GELISTIRME)

    def test_asiri_buyuk_govde_413(self):
        with self.assertRaises(sunucu.IstekHatasi) as h:
            _govde_oku(b"x" * 1_000_000, sunucu.MAKS_GOVDE_GELISTIRME)
        self.assertEqual(h.exception.kod, 413)

    def test_varsayilan_govde_siniri_degismedi(self):
        self.assertEqual(sunucu.MAKS_GOVDE, 16_000)

    def test_kuyruk_prompt_siniri_turetilmis(self):
        self.assertGreaterEqual(sunucu.MAKS_KUYRUK_PROMPT, ortak.MAKS_GIRDI)

    def test_gelistirme_yeni_istek_siniri(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(sunucu, "GOREV_DIZINI", d), \
                mock.patch.object(sunucu, "gelistirme_projeleri", return_value=["ajan-ofisi"]):
            temel = {"islem": "yeni", "proje": "ajan-ofisi", "baslik": "Sınır denemesi"}
            with self.assertRaises(sunucu.IstekHatasi) as h:
                sunucu.gelistirme_degistir({**temel, "istek": "a" * (ortak.MAKS_GIRDI + 1)})
            self.assertEqual(h.exception.kod, 400)
            self.assertIn("20000", str(h.exception))
            with mock.patch.object(sunucu, "gelistirme_yaniti", return_value={}):
                sunucu.gelistirme_degistir({**temel, "istek": "ğ\n" * (ortak.MAKS_GIRDI // 2)})


if __name__ == "__main__":
    unittest.main()
