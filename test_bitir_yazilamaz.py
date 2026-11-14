"""kosucu.bitir: çıktı yazılamasa da koşu kapanır: python3 -m unittest test_bitir_yazilamaz"""
import os
import tempfile
import unittest
from unittest import mock

import kosucu
import ortak


class BitirYazilamazTesti(unittest.TestCase):
    def test_cikti_klasoru_yoksa_kosu_bitti_ve_durum_hata(self):
        with tempfile.TemporaryDirectory() as d:
            durumlar, olaylar = [], []
            with mock.patch.object(ortak, "olay_yaz", olaylar.append), \
                 mock.patch.object(ortak, "durum_yaz", lambda i, s: durumlar.append((i, s))), \
                 mock.patch.object(kosucu.subprocess, "run"):
                kosucu.bitir({"id": "a"}, {"kosu_id": "k1", "ajan": "a"}, {"result": "merhaba"}, None,
                             0, os.path.join(d, "log.txt"), os.path.join(d, "yok", "klasor"), None)
            self.assertEqual(len(olaylar), 1)
            self.assertEqual(olaylar[0]["tur"], "kosu_bitti")
            self.assertEqual(olaylar[0]["durum"], "hata")
            self.assertIsNone(olaylar[0]["cikti"])
            self.assertIn("çıktı yazılamadı", olaylar[0]["hata"])
            self.assertEqual(durumlar[0][1]["durum"], "hata")
            self.assertIsNone(durumlar[0][1]["cikti"])

    def test_normal_yazim_atomik_ve_tmp_kalmaz(self):
        with tempfile.TemporaryDirectory() as d:
            olaylar = []
            with mock.patch.object(ortak, "olay_yaz", olaylar.append), \
                 mock.patch.object(ortak, "durum_yaz"), \
                 mock.patch.object(kosucu.subprocess, "run"), \
                 mock.patch.object(kosucu, "hafizaya_ekle", return_value=([], 0)):
                kosucu.bitir({"id": "a"}, {"kosu_id": "k2", "ajan": "a"}, {"result": "tamam"}, None,
                             0, os.path.join(d, "log.txt"), d, None)
            self.assertEqual(sorted(os.listdir(d)), ["k2.md"])
            self.assertEqual(olaylar[0]["durum"], "basarili")


if __name__ == "__main__":
    unittest.main()
