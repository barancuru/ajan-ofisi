"""olaylar.jsonl döndürme ve bugünün satırlarını sondan okuma: python3 -m unittest test_olay_donme"""
import json
import os
import tempfile
import unittest
from unittest import mock

import ortak


class OlayDonmeTesti(unittest.TestCase):
    def test_boyut_asilinca_dondurur(self):
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "olaylar.jsonl")
            with mock.patch.object(ortak, "OLAYLAR", yol), mock.patch.object(ortak, "OLAY_MAKS_BAYT", 400):  # tek döndürme: .1 yalnız bir yedek tutar, ikinci döndürme öncekini ezer
                for i in range(10):
                    ortak.olay_yaz({"tur": "x", "i": i})
            self.assertTrue(os.path.exists(yol + ".1"))
            sayi = sum(len(open(p, encoding="utf-8").readlines()) for p in (yol, yol + ".1"))
            self.assertEqual(sayi, 10)

    def test_bugunun_satirlari_sondan(self):
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "olaylar.jsonl")
            with open(yol, "w", encoding="utf-8") as f:
                for i in range(30000):
                    f.write(json.dumps({"zaman": "2020-01-01T00:00:00+03:00", "tur": "token", "i": i}) + "\n")
                f.write(json.dumps({"zaman": "2026-11-03T10:00:00+03:00", "tur": "kosu_bitti"}) + "\n")
            satirlar, basa = ortak.bugunun_satirlari(yol, "2026-11-03")
            self.assertEqual(len(satirlar), 1)
            self.assertFalse(basa)


if __name__ == "__main__":
    unittest.main()
