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


class CeoCiftIstekTesti(unittest.TestCase):
    def test_ikinci_istek_409_ve_bayrak_temizlenir(self):
        # Tasarım: CEO aynı anda 1 + MAKS_ALT koşu yapabilir; sınır aşılınca 429 (README)
        import threading
        sinir = 1 + sunucu.MAKS_ALT
        sayac = []
        hepsi_basladi, birak = threading.Event(), threading.Event()
        kilit = threading.Lock()

        def yavas(metin, kuru=False, ekler=None):
            with kilit:
                sayac.append(metin)
                if len(sayac) == sinir:
                    hepsi_basladi.set()
            birak.wait(5)
            return {"ok": True}

        with mock.patch.object(sunucu, "_ceo_calistir", side_effect=yavas):
            ts = [threading.Thread(target=sunucu.ceo_calistir, args=(f"is{i}",)) for i in range(sinir)]
            for t in ts:
                t.start()
            self.assertTrue(hepsi_basladi.wait(5))
            with self.assertRaises(sunucu.IstekHatasi) as c:
                sunucu.ceo_calistir("fazla")
            self.assertEqual(c.exception.kod, 429)
            birak.set()
            for t in ts:
                t.join(5)
            self.assertEqual(len(sayac), sinir)
            self.assertEqual(sunucu.ceo_calistir("uc"), {"ok": True})  # bayrak temizlendi
        with mock.patch.object(sunucu, "_ceo_calistir", side_effect=sunucu.IstekHatasi(502, "x")):
            with self.assertRaises(sunucu.IstekHatasi):
                sunucu.ceo_calistir("hata")
        self.assertFalse(sunucu._ceo_kosuyor)


if __name__ == "__main__":
    unittest.main()
