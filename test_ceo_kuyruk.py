"""CEO atama sınırı ve CEO kuyruğu: python3 -m unittest test_ceo_kuyruk"""
import threading
import time
import unittest
from unittest import mock

import sunucu


def _atamalar(n):
    return {"cevap": "x", "atamalar": [{"ajan": "a", "prompt": "p"} for _ in range(n)]}


class AtamaSiniriTesti(unittest.TestCase):
    tablo = {"a": {"kurulu": True}}

    def test_sinir_3(self):
        self.assertEqual(sunucu.MAKS_ATAMA, 3)
        with self.assertRaises(ValueError):
            sunucu.ceo_dogrula(_atamalar(4), self.tablo, "m")
        _, gecerli, _ = sunucu.ceo_dogrula(_atamalar(3), self.tablo, "m")
        self.assertEqual(len(gecerli), 3)


class CeoKuyrukTesti(unittest.TestCase):
    def _calistir(self, n):
        birak = threading.Event()
        sonuc, hata, ayni = [], [], []
        simdi = [0]
        kilit = threading.Lock()

        def sahte(metin, kuru=False, ekler=None):
            with kilit:
                simdi[0] += 1
                ayni.append(simdi[0])
            birak.wait(5)
            with kilit:
                simdi[0] -= 1
            return {"ok": metin}

        def is_(i):
            try:
                sonuc.append(sunucu.ceo_calistir(str(i)))
            except sunucu.IstekHatasi as e:
                hata.append(e.kod)

        with mock.patch.object(sunucu, "_ceo_calistir", side_effect=sahte), \
                mock.patch.object(sunucu.ortak, "olay_yaz"):
            ts = [threading.Thread(target=is_, args=(i,)) for i in range(n)]
            for t in ts:
                t.start()
            time.sleep(0.5)
            kuyrukta = sunucu.ceo_kuyruk_sayisi()
            birak.set()
            for t in ts:
                t.join(10)
        return sonuc, hata, ayni, kuyrukta

    def test_fazlalar_kuyruga_girer_429_almaz(self):
        n = sunucu.MAKS_ALT + 3
        sonuc, hata, ayni, kuyrukta = self._calistir(n)
        self.assertEqual(hata, [])
        self.assertEqual(len(sonuc), n)
        self.assertEqual(kuyrukta, 2)
        self.assertLessEqual(max(ayni), sunucu.MAKS_ALT + 1)
        self.assertEqual((sunucu._ceo_kosuyor, sunucu.ceo_kuyruk_sayisi()), (0, 0))

    def test_kuyruk_dolunca_429(self):
        n = sunucu.MAKS_ALT + 1 + sunucu.MAKS_KUYRUK + 2
        sonuc, hata, _, _ = self._calistir(n)
        self.assertEqual(hata, [429, 429])
        self.assertEqual(len(sonuc), n - 2)
        self.assertEqual((sunucu._ceo_kosuyor, sunucu.ceo_kuyruk_sayisi()), (0, 0))


if __name__ == "__main__":
    unittest.main()
