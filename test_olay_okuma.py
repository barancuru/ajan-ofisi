"""olaylari_oku tür ön elemesi ve geçmiş uçları: python3 -m unittest test_olay_okuma"""
import json
import os
import tempfile
import unittest
from unittest import mock

import ortak
import sunucu

TURLER = ("kosu_bitti", "ceo_bitti")


def _dosyalari_kur(d):
    """.1 (döndürülmüş) ve ana dosyaya karışık türler yazar; her dosyada bir bozuk satır var."""
    yol = os.path.join(d, "olaylar.jsonl")
    with mock.patch.object(ortak, "OLAYLAR", yol):
        ortak.olay_yaz({"tur": "ilerledi", "ajan": "a", "metin": "x"})
        ortak.olay_yaz({"tur": "token", "ajan": "a", "sayi": 3})
        ortak.olay_yaz({"tur": "kosu_bitti", "ajan": "a", "kosu_id": "k1", "durum": "bitti"})
        with open(yol, "a", encoding="utf-8") as f:
            f.write('{"zaman": "x", "tur": "ceo_bitti", "kosu_id": \n')  # bozuk
    os.replace(yol, yol + ".1")
    with mock.patch.object(ortak, "OLAYLAR", yol):
        ortak.olay_yaz({"tur": "ceo_bitti", "kosu_id": "c1", "cevap": "tamam",
                        "kurul": {"soru": "s", "uyeler": ["x"]}})
        ortak.olay_yaz({"tur": "token", "ajan": "b", "sayi": 1})
        ortak.olay_yaz({"tur": "kosu_bitti", "ajan": "b", "kosu_id": "k2", "durum": "hata", "hata": "ü ş ğ"})
        ortak.olay_yaz({"tur": "ilerledi", "ajan": "b", "metin": "y"})
        with open(yol, "a", encoding="utf-8") as f:
            f.write("{bozuk satır\n")
    return yol


class OlayOkumaTesti(unittest.TestCase):
    def test_olay_yazimi_on_eleme_ile_uyumlu(self):
        """olay_yaz'ın ürettiği satırda `"tur": "<tür>"` alt dizgisi birebir bulunmalı."""
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "olaylar.jsonl")
            with mock.patch.object(ortak, "OLAYLAR", yol):
                ortak.olay_yaz({"tur": "kosu_bitti", "ajan": "a"})
            with open(yol, encoding="utf-8") as f:
                satir = f.readline()
            self.assertIn('"tur": "kosu_bitti"', satir)

    def test_turler_ile_eski_yontem_ayni_olaylar(self):
        with tempfile.TemporaryDirectory() as d:
            yol = _dosyalari_kur(d)
            with mock.patch.object(ortak, "OLAYLAR", yol):
                eski = [o for o in sunucu.olaylari_oku(eski=True) if o.get("tur") in TURLER]
                yeni = list(sunucu.olaylari_oku(eski=True, turler=TURLER))
                yeni = [o for o in yeni if o.get("tur") in TURLER]
            self.assertEqual(eski, yeni)
            self.assertEqual([o["kosu_id"] for o in yeni], ["k1", "c1", "k2"])

    def test_turler_bozuk_satiri_atlar(self):
        with tempfile.TemporaryDirectory() as d:
            yol = _dosyalari_kur(d)
            with mock.patch.object(ortak, "OLAYLAR", yol):
                yeni = list(sunucu.olaylari_oku(eski=True, turler=TURLER))
            self.assertTrue(all(isinstance(o, dict) for o in yeni))
            self.assertEqual(len(yeni), 3)

    def test_turler_none_varsayilan_hepsini_verir(self):
        with tempfile.TemporaryDirectory() as d:
            yol = _dosyalari_kur(d)
            with mock.patch.object(ortak, "OLAYLAR", yol):
                self.assertEqual(len(list(sunucu.olaylari_oku(eski=True))), 7)  # 2 bozuk satır atlanır

    def test_gecmis_yaniti_ciktisi(self):
        with tempfile.TemporaryDirectory() as d:
            yol = _dosyalari_kur(d)
            with mock.patch.object(ortak, "OLAYLAR", yol):
                s = sunucu.gecmis_yaniti()
                self.assertEqual([k["kosu_id"] for k in s["kayitlar"]], ["k2", "c1", "k1"])
                self.assertFalse(s["daha_var"])
                b = sunucu.gecmis_yaniti(ajan_id="b")
                self.assertEqual([k["kosu_id"] for k in b["kayitlar"]], ["k2"])  # ajan süzgeci CEO kaydını içermez (README)

    def test_kurul_ve_ceo_kayit_yanitlari(self):
        with tempfile.TemporaryDirectory() as d:
            yol = _dosyalari_kur(d)
            with mock.patch.object(ortak, "OLAYLAR", yol), mock.patch.object(ortak, "CIKTI_DIZINI", d):
                k = sunucu.kurul_gecmis_yaniti()
                self.assertEqual([r["kosu_id"] for r in k["kayitlar"]], ["c1"])
                self.assertEqual(k["kayitlar"][0]["soru"], "s")
                c = sunucu.ceo_kayit_yaniti("c1")
                self.assertTrue(c["eksik"])
                self.assertEqual(c["kayit"]["cevap"], "tamam")
                self.assertIsNone(sunucu.ceo_kayit_yaniti("k1")["kayit"])


if __name__ == "__main__":
    unittest.main()
