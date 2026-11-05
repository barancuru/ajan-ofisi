"""Production permission: only a request carrying the gateway secret writes a record, bound to the sealed package."""
import os
import tempfile
import unittest
from unittest import mock

import sunucu


class CanliOnayTesti(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.imza = os.path.join(self.d, "kapi.env")
        with open(self.imza, "w", encoding="utf-8") as f:
            f.write("OFIS_KAPI_IMZA=dogru\n")
        self.muhur = os.path.join(self.d, "muhur")
        self.onay = os.path.join(self.d, "onay")
        os.makedirs(self.muhur)
        for ad, deger in (("KAPI_IMZA_DOSYASI", self.imza), ("PAKET_MUHUR_DIZINI", self.muhur), ("CANLI_ONAY_DIZINI", self.onay)):
            y = mock.patch.object(sunucu, ad, deger)
            y.start()
            self.addCleanup(y.stop)

    def test_imza_yalniz_birebir_eslesince_gecerli(self):
        self.assertTrue(sunucu.kapidan_geldi("dogru"))
        for sahte in ("", "yanlis", "dogru ", "onizleme"):
            self.assertFalse(sunucu.kapidan_geldi(sahte))

    def test_imza_dosyasi_yoksa_gecersiz(self):
        os.remove(self.imza)
        self.assertFalse(sunucu.kapidan_geldi("dogru"))

    def test_onay_muhurlu_pakete_baglanir(self):
        sha = "a" * 64
        with open(os.path.join(self.muhur, "homeos-0.10.7.zip.sha256"), "w", encoding="utf-8") as f:
            f.write(sha + "\n")
        self.assertTrue(sunucu.canli_onayi_yaz({"proje": "homeos", "surum": "0.10.7"}))
        with open(os.path.join(self.onay, "homeos-0.10.7.onay"), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), sha)

    def test_muhur_yoksa_ya_da_alan_bozuksa_onay_yazilmaz(self):
        self.assertFalse(sunucu.canli_onayi_yaz({"proje": "homeos", "surum": "0.10.8"}))
        self.assertFalse(sunucu.canli_onayi_yaz({"proje": "../x", "surum": "0.10.7"}))
        self.assertFalse(sunucu.canli_onayi_yaz({"proje": "homeos", "surum": "../../x"}))
        self.assertFalse(os.path.exists(self.onay))


if __name__ == "__main__":
    unittest.main()
