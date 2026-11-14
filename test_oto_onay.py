"""Auto-approval switch: only the web login may change it, only allowlisted projects, and it expires."""
import os
import tempfile
import time
import unittest
from unittest import mock

import sunucu


class OtoOnayTesti(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        imza = os.path.join(self.d, "kapi.env")
        with open(imza, "w", encoding="utf-8") as f:
            f.write("OFIS_KAPI_IMZA=dogru\n")
        self.dizin = os.path.join(self.d, "oto")
        for ad, deger in (("KAPI_IMZA_DOSYASI", imza), ("OTO_ONAY_DIZINI", self.dizin)):
            y = mock.patch.object(sunucu, ad, deger)
            y.start()
            self.addCleanup(y.stop)

    def test_kapisiz_istek_acamaz(self):
        with self.assertRaises(sunucu.IstekHatasi) as h:
            sunucu.oto_onay_degistir("turnusol", True, "yanlis")
        self.assertEqual(h.exception.kod, 403)
        self.assertFalse(sunucu.oto_onay_durumu()["turnusol"]["acik"])

    def test_listedisi_proje_reddedilir(self):
        for proje in ("baska-proje", "../x"):
            with self.assertRaises(sunucu.IstekHatasi):
                sunucu.oto_onay_degistir(proje, True, "dogru")
        self.assertFalse(os.path.exists(self.dizin))

    def test_ac_kapat(self):
        sunucu.oto_onay_degistir("turnusol", True, "dogru")
        self.assertTrue(sunucu.oto_onay_durumu()["turnusol"]["acik"])
        sunucu.oto_onay_degistir("turnusol", False, "dogru")
        self.assertFalse(sunucu.oto_onay_durumu()["turnusol"]["acik"])

    def test_ajan_ofisi_ac_kapat(self):
        self.assertFalse(sunucu.oto_onay_durumu()["ajan-ofisi"]["acik"])
        sunucu.oto_onay_degistir("ajan-ofisi", True, "dogru")
        d = sunucu.oto_onay_durumu()["ajan-ofisi"]
        self.assertTrue(d["acik"])
        self.assertTrue(d["bitis"])
        sunucu.oto_onay_degistir("ajan-ofisi", False, "dogru")
        self.assertFalse(sunucu.oto_onay_durumu()["ajan-ofisi"]["acik"])

    def test_suresi_dolunca_kapali(self):
        sunucu.oto_onay_degistir("turnusol", True, "dogru")
        eski = time.time() - (sunucu.OTO_ONAY_GUN + 1) * 86400
        os.utime(os.path.join(self.dizin, "turnusol"), (eski, eski))
        self.assertFalse(sunucu.oto_onay_durumu()["turnusol"]["acik"])


if __name__ == "__main__":
    unittest.main()
