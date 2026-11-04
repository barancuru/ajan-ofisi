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
    def test_yuvalar_ve_kuyruk_dolunca_429_ve_sayac_temizlenir(self):
        # Tasarım: CEO aynı anda 1 + MAKS_ALT koşu yapar; fazlası _ceo_sira kuyruğunda bekler,
        # 429 yalnız yuvalar VE kuyruk doluyken döner (README)
        import threading
        import time
        yuva, kuyruk = 1 + sunucu.MAKS_ALT, 2
        baslayan, sonuc, hatalar = [], [], []
        yuvalar_basladi, birak = threading.Event(), threading.Event()
        kilit = threading.Lock()

        def yavas(metin, kuru=False, ekler=None):
            with kilit:
                baslayan.append(metin)
                if len(baslayan) == yuva:
                    yuvalar_basladi.set()
            birak.wait(5)
            return {"ok": metin}

        def calis(metin):
            try:
                r = sunucu.ceo_calistir(metin)
                with kilit:
                    sonuc.append(r)
            except BaseException as e:  # thread sessizce ölüp işi kaybettirmesin
                with kilit:
                    hatalar.append(e)

        ts = []
        with mock.patch.object(sunucu, "_ceo_calistir", side_effect=yavas), \
                mock.patch.object(sunucu, "MAKS_KUYRUK", kuyruk), \
                mock.patch.object(sunucu.ortak, "olay_yaz"):
            try:
                for i in range(yuva):
                    ts.append(threading.Thread(target=calis, args=(f"yuva{i}",), daemon=True))
                    ts[-1].start()
                self.assertTrue(yuvalar_basladi.wait(2))
                for i in range(kuyruk):
                    ts.append(threading.Thread(target=calis, args=(f"sira{i}",), daemon=True))
                    ts[-1].start()
                son = time.monotonic() + 2
                while sunucu.ceo_kuyruk_sayisi() < kuyruk and time.monotonic() < son:
                    time.sleep(0.005)
                self.assertEqual(sunucu.ceo_kuyruk_sayisi(), kuyruk)
                self.assertEqual(len(baslayan), yuva)  # kuyruktakiler henüz çalışmadı
                t0 = time.monotonic()
                with self.assertRaises(sunucu.IstekHatasi) as c:
                    sunucu.ceo_calistir("fazla")
                self.assertEqual(c.exception.kod, 429)
                self.assertLess(time.monotonic() - t0, 1)  # beklemeden döndü
                self.assertNotIn("fazla", baslayan)
            finally:
                birak.set()
                for t in ts:
                    t.join(3)
            self.assertFalse(any(t.is_alive() for t in ts))
            self.assertEqual(hatalar, [])
            beklenen = {f"yuva{i}" for i in range(yuva)} | {f"sira{i}" for i in range(kuyruk)}
            self.assertEqual(len(sonuc), yuva + kuyruk)
            self.assertEqual({r["ok"] for r in sonuc}, beklenen)
            self.assertEqual(sorted(baslayan), sorted(beklenen))
            self.assertEqual(sunucu.ceo_kuyruk_sayisi(), 0)
            self.assertEqual(sunucu.ceo_calistir("uc"), {"ok": "uc"})  # sayaç/kuyruk temizlendi
        with mock.patch.object(sunucu, "_ceo_calistir", side_effect=sunucu.IstekHatasi(502, "x")):
            with self.assertRaises(sunucu.IstekHatasi):
                sunucu.ceo_calistir("hata")
        self.assertFalse(sunucu._ceo_kosuyor)


if __name__ == "__main__":
    unittest.main()
