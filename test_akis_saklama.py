"""V1.1 #10 saklama: kuru koşu hiçbir şey değiştirmez; --uygula arşivler, sonra siler; etkin ya da uçuşta denemesi
olan koşu ve yeni dosyalar korunur.  python3 -m unittest test_akis_saklama"""
import gzip
import json
import os
import unittest
from unittest import mock

import akis_motor
import akis_saklama
from test_akis_motor import MotorTabani

GUN = 86400


class SaklamaTest(MotorTabani):
    def setUp(self):
        super().setUp()
        tanimlar, _ = __import__("akis_tanim").tanimlari_yukle()
        self.tanimlar.update(tanimlar)

    def kosu(self, bitir=True):
        k = self.m.baslat("ornek-arastirma-ozeti", {"konu": "x"})["run_id"]
        self.m.tur()
        ref = self.son_ref()
        if bitir:
            self.ajan_bitir(ref, "bitti")
            self.m.tur()
            self.m.iptal(k)
            self.m.tur()
        return k, ref

    def eskit(self, k, gun=100):
        b = self.depo.baglanti()
        b.execute("UPDATE kosular SET bitis_ts=? WHERE id=?", (self.saat[0] - gun * GUN, k))

    def satir_sayisi(self, k):
        b = self.depo.baglanti()
        return sum(b.execute(f"SELECT COUNT(*) FROM {t} WHERE kosu_id=?", (k,)).fetchone()[0]
                   for t in akis_saklama.TABLOLAR[1:]) + b.execute("SELECT COUNT(*) FROM kosular WHERE id=?", (k,)).fetchone()[0]

    def calistir(self, **k):
        return akis_saklama.calistir(self.depo, saat=lambda: self.saat[0], **k)

    def test_kuru_kosu_hicbir_seyi_degistirmez(self):
        k, ref = self.kosu()
        self.eskit(k)
        once = self.satir_sayisi(k)
        dosyalar = sorted(os.listdir(akis_motor.sonuc_dizini()))
        r = self.calistir()
        self.assertEqual([x["run_id"] for x in r["kosular"]], [k])
        self.assertFalse(r["uygula"])
        self.assertEqual(self.satir_sayisi(k), once)
        self.assertEqual(sorted(os.listdir(akis_motor.sonuc_dizini())), dosyalar)
        self.assertFalse(os.path.exists(akis_saklama.arsiv_dizini()))

    def test_uygula_arsivler_ve_siler(self):
        k, ref = self.kosu()
        self.eskit(k)
        yeni, _ = self.kosu()                 # bitmiş ama yeni: kalır
        etkin, eref = self.kosu(bitir=False)  # etkin: kalır
        self.eskit(etkin)
        r = self.calistir(uygula=True)
        self.assertEqual([x["run_id"] for x in r["kosular"]], [k])
        self.assertEqual(self.satir_sayisi(k), 0)
        self.assertGreater(self.satir_sayisi(yeni), 0)
        self.assertGreater(self.satir_sayisi(etkin), 0)
        self.assertFalse([a for a in os.listdir(akis_motor.sonuc_dizini()) if a.startswith(ref)])
        with gzip.open(os.path.join(akis_saklama.arsiv_dizini(), f"{k}.json.gz")) as f:
            arsiv = json.load(f)
        self.assertEqual(arsiv["kosular"][0]["id"], k)
        self.assertTrue(arsiv["denemeler"] and arsiv["olaylar"])
        self.assertEqual(oct(os.stat(os.path.join(akis_saklama.arsiv_dizini(), f"{k}.json.gz")).st_mode & 0o777), "0o600")
        with self.assertRaises(akis_motor.AkisHatasi):
            self.m.detay(k)

    def test_ucusta_denemesi_olan_bitmis_kosu_korunur(self):
        """İptal edilen koşunun ajanı hâlâ koşuyor olabilir: sonucu gelmeden kaldırılmaz."""
        k, ref = self.kosu(bitir=False)
        self.m.iptal(k)
        self.eskit(k)
        self.depo.baglanti().execute("UPDATE denemeler SET durum='calisiyor' WHERE kosu_id=?", (k,))
        self.assertEqual(self.calistir(uygula=True)["kosular"], [])
        self.assertGreater(self.satir_sayisi(k), 0)

    def test_arsiv_yazilamazsa_silinmez(self):
        k, _ = self.kosu()
        self.eskit(k)
        with mock.patch.object(akis_saklama, "_arsiv_yaz", side_effect=OSError("disk dolu")):
            r = self.calistir(uygula=True)
        self.assertEqual(r["atlanan"][0]["run_id"], k)
        self.assertGreater(self.satir_sayisi(k), 0)

    def test_sahipsiz_eski_dosya_silinir_yenisi_ve_yabanci_ad_kalir(self):
        d = akis_motor.sonuc_dizini()
        os.makedirs(d, exist_ok=True)
        eski, yeni, yabanci = (os.path.join(d, a) for a in ("ak-aaaaaaaaaaaa.json", "ak-bbbbbbbbbbbb.basladi.json", "notlar.json"))
        for y in (eski, yeni, yabanci):
            with open(y, "w") as f:
                f.write("{}")
        os.utime(eski, (self.saat[0] - 100 * GUN,) * 2)
        os.utime(yabanci, (self.saat[0] - 100 * GUN,) * 2)
        self.assertEqual(self.calistir()["sahipsiz_dosyalar"], ["ak-aaaaaaaaaaaa.json"])
        self.assertTrue(os.path.exists(eski))
        self.calistir(uygula=True)
        self.assertFalse(os.path.exists(eski))
        self.assertTrue(os.path.exists(yeni) and os.path.exists(yabanci))

    def test_cok_kisa_sure_reddedilir(self):
        with self.assertRaises(ValueError):
            self.calistir(gun=0, uygula=True)
        self.assertEqual(akis_saklama.main(["--gun", "1"]), 2)


if __name__ == "__main__":
    unittest.main()
