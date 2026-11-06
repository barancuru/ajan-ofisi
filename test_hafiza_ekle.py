"""kosucu.hafizaya_ekle: python3 -m unittest test_hafiza_ekle"""
import os
import tempfile
import unittest
from unittest import mock

import kosucu
import ortak
import sunucu


def _blok(m):
    return f"<hafiza_ekle>{m}</hafiza_ekle>"


class HafizaEkleTesti(unittest.TestCase):
    def setUp(self):
        self.dizin = tempfile.TemporaryDirectory()
        self.addCleanup(self.dizin.cleanup)
        p = mock.patch.object(ortak, "HAFIZA_DIZINI", self.dizin.name)
        p.start()
        self.addCleanup(p.stop)
        self.yol = os.path.join(self.dizin.name, "a.md")

    def _satirlar(self):
        with open(self.yol, encoding="utf-8") as f:
            return f.read().splitlines()

    def test_cok_satirli_ve_sahte_madde_tek_madde(self):
        eklenen, atlanan = kosucu.hafizaya_ekle("a", _blok("birinci\nikinci\n- sahte madde\n\n  üçüncü"))
        self.assertEqual(atlanan, 0)
        self.assertEqual(eklenen, ["birinci ikinci - sahte madde üçüncü"])
        satirlar = [s for s in self._satirlar() if s.strip()]
        self.assertEqual(len(satirlar), 1)
        self.assertEqual(len(sunucu.hafiza_maddeleri(self._satirlar())), 1)

    def test_bes_blok_uc_madde(self):
        metin = "".join(_blok(f"madde {i}") for i in range(5))
        eklenen, atlanan = kosucu.hafizaya_ekle("a", metin)
        self.assertEqual(len(eklenen), 3)
        self.assertEqual(atlanan, 2)
        self.assertEqual(len(sunucu.hafiza_maddeleri(self._satirlar())), 3)

    def test_uzun_madde_kirpilir_bos_blok_sayilmaz(self):
        eklenen, atlanan = kosucu.hafizaya_ekle("a", _blok("x" * 5000) + _blok(" \n ") + _blok("ok"))
        self.assertEqual(atlanan, 0)
        self.assertEqual(len(eklenen), 2)
        self.assertEqual(len(eklenen[0]), ortak.MAKS_HAFIZA_EKI)

    def test_blok_yoksa_dosya_olusmaz(self):
        self.assertEqual(kosucu.hafizaya_ekle("a", "düz çıktı"), ([], 0))
        self.assertFalse(os.path.exists(self.yol))


if __name__ == "__main__":
    unittest.main()
