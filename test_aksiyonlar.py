"""Operatör Panosu aksiyon ayrıştırma: python3 -m unittest test_aksiyonlar"""
import unittest

import sunucu


class AksiyonTesti(unittest.TestCase):
    def test_acik_madde_alinir_isaretli_atlanir(self):
        g = "# B\n- [ ] yap\n- [x] bitti\n- [X] bitti2\n* [ ] yıldızlı\n"
        self.assertEqual(sunucu.aksiyonlari_cikar(g), ["yap", "yıldızlı"])

    def test_karar_bolumu_maddeleri(self):
        g = "# B\ntext\n## Kullanıcı kararı gerektiren noktalar\n1. **A:** soru\n- madde\n- [x] kapalı\n## Sonuç\n- baska\n"
        self.assertEqual(sunucu.aksiyonlari_cikar(g), ["**A:** soru", "madde"])

    def test_bolum_yoksa_bos(self):
        self.assertEqual(sunucu.aksiyonlari_cikar("# B\n- liste\n1. bir\n## Sonuç\nyok"), [])

    def test_uzun_satir_kirpilir(self):
        r = sunucu.aksiyonlari_cikar("- [ ] " + "a" * 500)
        self.assertEqual(len(r[0]), 200)

    def test_sekizden_fazlasi_kesilir(self):
        g = "\n".join(f"- [ ] m{i}" for i in range(12))
        self.assertEqual(len(sunucu.aksiyonlari_cikar(g)), 8)


if __name__ == "__main__":
    unittest.main()
