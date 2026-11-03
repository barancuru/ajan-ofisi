"""POST /api/revize mantığı: python3 -m unittest test_revize"""
import os
import tempfile
import unittest
from unittest import mock

import ortak
import sunucu


def _hata_kodu(veri):
    with unittest.TestCase().assertRaises(sunucu.IstekHatasi) as c:
        sunucu.revize_baslat(veri)
    return c.exception.kod


GECERLI = {"ajan": "a", "kosu_id": "k1", "not": "daha kısa olsun"}


class RevizeTesti(unittest.TestCase):
    def test_gecersiz_girdiler(self):
        with mock.patch.object(sunucu, "gorev_baslat") as gb:
            self.assertEqual(_hata_kodu({**GECERLI, "not": ""}), 400)
            self.assertEqual(_hata_kodu({**GECERLI, "not": "  \n "}), 400)
            self.assertEqual(_hata_kodu({**GECERLI, "not": 5}), 400)
            self.assertEqual(_hata_kodu({**GECERLI, "not": "x" * 1001}), 413)
            self.assertEqual(_hata_kodu({**GECERLI, "kosu_id": "../x"}), 400)
            self.assertEqual(_hata_kodu({**GECERLI, "ajan": "../x"}), 400)
            gb.assert_not_called()

    def test_bilinmeyen_ajan_404(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ortak, "CIKTI_DIZINI", d):
            self.assertEqual(_hata_kodu({**GECERLI, "ajan": "yok-boyle-ajan"}), 404)

    def test_mesgul_409_olay_yazmaz(self):
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "olaylar.jsonl")
            hata = sunucu.IstekHatasi(409, "ajan zaten çalışıyor")
            with mock.patch.object(ortak, "OLAYLAR", yol), mock.patch.object(ortak, "CIKTI_DIZINI", d), \
                    mock.patch.object(sunucu, "gorev_baslat", side_effect=hata):
                self.assertEqual(_hata_kodu(GECERLI), 409)
            self.assertFalse(os.path.exists(yol))

    def test_basarili_cagri_ve_gecmis(self):
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "olaylar.jsonl")
            os.makedirs(os.path.join(d, "a"))
            with open(os.path.join(d, "a", "k1.md"), "w", encoding="utf-8") as f:
                f.write("Ç" * 5000)
            with mock.patch.object(ortak, "OLAYLAR", yol), mock.patch.object(ortak, "CIKTI_DIZINI", d), \
                    mock.patch.object(ortak, "KOK", os.path.dirname(d)), \
                    mock.patch.object(ortak, "ajanlari_yukle", return_value=([], {"a": {"oda": "genel"}})), \
                    mock.patch.object(sunucu, "son_is_yaniti",
                                      return_value={"metin": "Ç" * 5000}), \
                    mock.patch.object(sunucu, "gorev_baslat", return_value={"kosu_id": "k2", "ajan": "a"}) as gb:
                self.assertEqual(sunucu.revize_baslat({**GECERLI, "not": "  daha kısa olsun  "})["kosu_id"], "k2")
                ortak.olay_yaz({"tur": "kosu_bitti", "ajan": "a", "kosu_id": "k1", "durum": "bitti"})
                ortak.olay_yaz({"tur": "kosu_bitti", "ajan": "a", "kosu_id": "k0", "durum": "bitti"})
                g = sunucu.gecmis_yaniti()
            args, kw = gb.call_args
            self.assertEqual(args[0], "a")
            self.assertEqual(kw["kaynak"], "revize")
            self.assertEqual(kw["ust"], "k1")
            self.assertIn("daha kısa olsun", kw["prompt"])
            self.assertLessEqual(kw["prompt"].count("Ç"), sunucu.MAKS_REVIZE_CIKTI)
            self.assertLess(len(kw["prompt"]), ortak.MAKS_GIRDI)
            olaylar = [o for o in g["kayitlar"]]
            k1 = next(o for o in olaylar if o["kosu_id"] == "k1")
            self.assertEqual(k1["revize"], {"not": "daha kısa olsun", "yeni_kosu_id": "k2"})
            self.assertIsNone(next(o for o in olaylar if o["kosu_id"] == "k0")["revize"])
            with mock.patch.object(ortak, "OLAYLAR", yol):
                ev = [o for o in sunucu.olaylari_oku(eski=True) if o.get("tur") == "revize_istendi"]
            self.assertEqual(len(ev), 1)
            self.assertEqual((ev[0]["kosu_id"], ev[0]["yeni_kosu_id"], ev[0]["oda"]), ("k1", "k2", "genel"))


if __name__ == "__main__":
    unittest.main()
