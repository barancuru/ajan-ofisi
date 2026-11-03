"""CEO koşusunda claude bulunamazsa ceo_bitti/hata yazılmalı ve 502 dönmeli: python3 -m unittest test_ceo_hata"""
import unittest
from unittest import mock

import sunucu


class CeoOSErrorTesti(unittest.TestCase):
    def test_claude_yok_ceo_bitti_hata_yazar(self):
        olaylar = []
        tablo = {"ceo": {"model": "sonnet"}}
        with mock.patch.object(sunucu.ortak, "ajanlari_yukle", return_value=({}, tablo)), \
                mock.patch.object(sunucu.ortak, "olay_yaz", side_effect=olaylar.append), \
                mock.patch.object(sunucu, "ceo_ekleri_kaydet", return_value=[]), \
                mock.patch.object(sunucu, "ceo_promptu", return_value="x"), \
                mock.patch.object(sunucu, "ceo_kaydi_yaz", return_value="cikti/ceo/x.md"), \
                mock.patch.object(sunucu.subprocess, "run", side_effect=FileNotFoundError("claude")):
            with self.assertRaises(sunucu.IstekHatasi) as c:
                sunucu.ceo_calistir("merhaba")
        self.assertEqual(c.exception.kod, 502)
        self.assertEqual([o["tur"] for o in olaylar], ["ceo_basladi", "ceo_bitti"])
        self.assertEqual(olaylar[1]["durum"], "hata")
        self.assertIsNone(getattr(sunucu._ceo_acik, "id", None))


if __name__ == "__main__":
    unittest.main()
