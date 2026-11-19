"""V2 maliyet modeli: ölçülmüş geçmişten p90 ile bütçe kontrolü; az ölçümde statik tahmin, taban oranı, yalnız gerçek
ölçüm (sıfır/boş sayılmaz), akış ve adım bazında ayrım.  python3 -m unittest test_akis_maliyet"""
import json
import unittest
from unittest import mock

import akis_motor
from test_akis_birim import taban_tanim
from test_akis_motor import HerAkis, MotorTabani

IYI = '<akis_cikti>{"sonuc": "iyi"}</akis_cikti>'


class YuzdelikTest(unittest.TestCase):
    def test_en_yakin_sira(self):
        on = list(range(1, 11))
        self.assertEqual([akis_motor.yuzdelik(on, p) for p in (50, 90, 100)], [5, 9, 10])
        self.assertEqual(akis_motor.yuzdelik([0.3], 90), 0.3)
        self.assertEqual(akis_motor.yuzdelik([3, 1, 2], 50), 2)       # sırasız girdi


class MaliyetModeliTest(MotorTabani):
    def setUp(self):
        super().setUp()
        y = mock.patch.object(akis_motor, "ETKIN_AKISLAR", HerAkis())
        y.start()
        self.addCleanup(y.stop)
        self.tanim(taban_tanim())

    def kos(self, maliyet, akis="deneme"):
        k = self.m.baslat(akis, {"konu": "x"})["run_id"]
        self.m.tur()
        self.ajan_bitir(self.son_ref(), IYI, maliyet=maliyet)
        self.m.tur()
        self.m.tur()
        self.saat[0] += 10
        self.assertEqual(self.detay(k)["durum"], "basarili")
        return k

    def son_tahmin(self):
        b = self.depo.baglanti()
        r = b.execute("SELECT veri_json FROM olaylar WHERE tur='adim_basladi' ORDER BY id DESC LIMIT 1").fetchone()
        v = json.loads(r[0])
        return v["tahmini_usd"], v["tahmin_kaynagi"]

    def test_az_olcumde_statik(self):
        for c in (0.2, 0.3, 0.25, 0.2):
            self.kos(c)
        self.m.baslat("deneme", {"konu": "x"})
        self.m.tur()
        self.assertEqual(self.son_tahmin(), (1.0, "statik"))           # ajan butce_usd = 1.0

    def test_bes_olcumden_sonra_p90(self):
        for c in (0.2, 0.3, 0.25, 0.2, 0.4):
            self.kos(c)
        self.m.baslat("deneme", {"konu": "x"})
        self.m.tur()
        self.assertEqual(self.son_tahmin(), (0.4, "p90"))
        mm = self.m.maliyet_modeli("deneme")["a"]
        self.assertEqual((mm["n"], mm["p50"], mm["p90"], mm["statik"], mm["kaynak"]), (5, 0.25, 0.4, 1.0, "p90"))

    def test_p90_tabanin_altina_inmez(self):
        for _ in range(6):
            self.kos(0.001)
        self.m.baslat("deneme", {"konu": "x"})
        self.m.tur()
        self.assertEqual(self.son_tahmin(), (0.1, "p90"))              # 1.0 × MALIYET_TABAN_ORANI

    def test_pahali_gecmis_tahmini_yukseltir(self):
        for _ in range(5):
            self.kos(2.5)
        self.m.baslat("deneme", {"konu": "x"})
        self.m.tur()
        self.assertEqual(self.son_tahmin(), (2.5, "p90"))              # statik 1.0'dan yüksek: daha temkinli

    def test_sifir_ve_olculemeyen_sayilmaz(self):
        for c in (0, 0, 0, None, None, 0.5):
            self.kos(c)
        self.assertEqual(self.m.maliyet_modeli("deneme")["a"]["n"], 1)

    def test_baska_akisin_gecmisi_karismaz(self):
        self.tanim(taban_tanim(id="diger"))
        for _ in range(5):
            self.kos(0.2, akis="diger")
        self.assertEqual(self.m.maliyet_modeli("deneme")["a"]["kaynak"], "statik")
        self.assertEqual(self.m.maliyet_modeli("diger")["a"]["kaynak"], "p90")

    def test_p90_butce_kontrolunde_kullanilir(self):
        """Statik 1.0 ile 0.5 $ tavanlı akış hiç başlayamazdı; ölçülmüş p90 (0.2) ile başlar."""
        for _ in range(5):
            self.kos(0.2)
        t = taban_tanim(id="deneme", sinirlar={"max_maliyet_usd": 0.5})
        self.tanim(t)
        k = self.m.baslat("deneme", {"konu": "x"})["run_id"]
        self.m.tur()
        self.assertEqual(self.detay(k)["durum"], "calisiyor")

    def test_bilinmeyen_akis_404(self):
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.maliyet_modeli("yok")
        self.assertEqual(c.exception.kod, 404)


if __name__ == "__main__":
    unittest.main()
