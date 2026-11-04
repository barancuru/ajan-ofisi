"""Geliştirme hattı tam rapor ucu: python3 -m unittest test_gelistirme_rapor"""
import os
import tempfile
import unittest

import sunucu


class RaporTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.eski = sunucu.GOREV_DIZINI
        sunucu.GOREV_DIZINI = os.path.join(self.tmp.name, "gorevler")
        os.makedirs(os.path.join(sunucu.GOREV_DIZINI, "bitti"))
        self.uzun = "| a | b |\n|---|---|\n" + "satır\n" * 1000 + "SON-ISARET"
        self._yaz("g.md", "---\ntur: gelistirme\n---\n# B\n## İstek\nx\n## Teslim\n" + self.uzun)
        self._yaz("bitti/b.md", "---\ntur: gelistirme\n---\n# B\n## Teslim\nbitti raporu")
        self._yaz("baska.md", "---\ntur: oneri\n---\n# B\n## Sır\ngizli")
        self._yaz("yok.md", "---\ntur: gelistirme\n---\n# B\nbölüm yok")
        self._yaz(".env", "---\ntur: gelistirme\n---\n## S\ngizli")
        with open(os.path.join(self.tmp.name, "x.md"), "w") as f:
            f.write("---\ntur: gelistirme\n---\n## S\ngizli")

    def tearDown(self):
        sunucu.GOREV_DIZINI = self.eski
        self.tmp.cleanup()

    def _yaz(self, ad, icerik):
        with open(os.path.join(sunucu.GOREV_DIZINI, ad), "w", encoding="utf-8") as f:
            f.write(icerik)

    def _hata(self, dosya):
        with self.assertRaises(sunucu.IstekHatasi) as c:
            sunucu.gelistirme_rapor_yaniti(dosya)
        self.assertIn(c.exception.kod, (400, 404))

    def test_gecersiz_adlar(self):
        for d in ("../x.md", "/etc/passwd", "a/b.md", ".env", "g.txt", "", "g.md\x00", "..", None):
            self._hata(d)

    def test_tur_gelistirme_degilse_404(self):
        self._hata("baska.md")

    def test_bolum_yoksa_404(self):
        self._hata("yok.md")

    def test_tam_metin_frontmattersiz_kirpmasiz(self):
        r = sunucu.gelistirme_rapor_yaniti("g.md")
        self.assertTrue(r["metin"].startswith("## Teslim"))
        self.assertTrue(r["metin"].endswith("SON-ISARET"))
        self.assertNotIn("tur:", r["metin"])
        self.assertNotIn("## İstek", r["metin"])
        self.assertFalse(r["kirpildi"])

    def test_bitti_dizini(self):
        self.assertIn("bitti raporu", sunucu.gelistirme_rapor_yaniti("b.md")["metin"])

    def test_tavan_asilirsa_kirpildi(self):
        eski = sunucu.MAKS_SON_IS
        sunucu.MAKS_SON_IS = 100
        try:
            r = sunucu.gelistirme_rapor_yaniti("g.md")
        finally:
            sunucu.MAKS_SON_IS = eski
        self.assertTrue(r["kirpildi"])
        self.assertEqual(len(r["metin"]), 100)


if __name__ == "__main__":
    unittest.main()
