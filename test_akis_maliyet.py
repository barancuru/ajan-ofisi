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

    def test_ajan_adimi_butcede_tavan_kalir_p90_ongoru(self):
        """agent_task: --max-budget-usd sert tavanı (statik) bütçe kontrolünde kalır; p90 yalnız öngörü."""
        for c in (0.2, 0.3, 0.25, 0.2, 0.4):
            self.kos(c)
        self.m.baslat("deneme", {"konu": "x"})
        self.m.tur()
        self.assertEqual(self.son_tahmin(), (1.0, "tavan"))             # ajan butce_usd = 1.0
        mm = self.m.maliyet_modeli("deneme")["a"]
        self.assertEqual((mm["n"], mm["p50"], mm["p90"], mm["statik"], mm["kullanilan"], mm["kaynak"]),
                         (5, 0.25, 0.4, 1.0, 1.0, "tavan"))

    def test_ajan_adimi_ucuz_gecmisle_tavani_asmaz(self):
        """Statik 1.0 ile 0.5 $ tavanlı akış, geçmiş ucuz olsa da başlamaz: bütçe çağrı başına tavanla kontrol edilir."""
        for _ in range(5):
            self.kos(0.2)
        self.tanim(taban_tanim(id="deneme", sinirlar={"max_maliyet_usd": 0.5}))
        k = self.m.baslat("deneme", {"konu": "x"})["run_id"]
        self.m.tur()
        self.assertEqual((self.detay(k)["durum"], self.detay(k)["neden"]["sebep"]), ("inceleme", "butce"))

    def test_sifir_ve_olculemeyen_sayilmaz(self):
        for c in (0, 0, 0, None, None, 0.5):
            self.kos(c)
        self.assertEqual(self.m.maliyet_modeli("deneme")["a"]["n"], 1)

    def test_baska_akisin_gecmisi_karismaz(self):
        self.tanim(taban_tanim(id="diger"))
        for c in (0.2, 0.3):
            self.kos(c, akis="diger")
        self.assertEqual(self.m.maliyet_modeli("deneme")["a"]["n"], 0)
        self.assertEqual(self.m.maliyet_modeli("diger")["a"]["n"], 2)


class HatMaliyetModeliTest(MotorTabani):
    """gelistirme_gorevi: sert tavan yok (6 $ tahmin); ≥5 ölçümde p90, taban statiğin %10'u."""
    HAT = {"id": "uygulama", "tur": "gelistirme_gorevi", "tahmini_usd": 6}

    def olcum_yaz(self, maliyetler, akis="homeos-ozellik-gelistirme", adim="uygulama"):
        b = self.depo.baglanti()
        for m in maliyetler:
            self.sayac = getattr(self, "sayac", 0) + 1
            i = self.sayac
            k = f"r{i:012x}"
            b.execute("INSERT INTO kosular(id, akis_id, akis_surum, tanim_ozet, tanim_json, girdi_json, durum, olusturma_ts, "
                      "guncelleme_ts) VALUES (?,?,1,'x','{}','{}','basarili',0,0)", (k, akis))
            b.execute("INSERT INTO denemeler(kosu_id, adim_id, iterasyon, deneme, ref, durum, maliyet_usd, baslangic_ts, "
                      "bitis_ts) VALUES (?,?,1,1,?,'basarili',?,?,?)", (k, adim, f"ak-{i:012x}", m, i, i + 1))

    def tahmin(self, akis="homeos-ozellik-gelistirme"):
        return self.m._tahmin(self.HAT, self.depo.baglanti(), akis)

    def test_az_olcumde_statik(self):
        self.olcum_yaz([0.005] * 4)
        self.assertEqual(self.tahmin(), (6.0, "statik"))

    def test_bes_olcumde_p90_taban_ile(self):
        self.olcum_yaz([0.005, 0.006, 0.004, 0.005, 0.007])
        usd, kaynak = self.tahmin()
        self.assertEqual(kaynak, "p90")
        self.assertAlmostEqual(usd, 0.6)                                # p90 0.007 < taban 6 × 0.1

    def test_pahali_hat_gecmisi(self):
        self.olcum_yaz([2.0, 3.0, 2.5, 2.0, 4.0, 2.2])
        self.assertEqual(self.tahmin(), (4.0, "p90"))

    def test_baska_akis_ya_da_adim_sayilmaz(self):
        self.olcum_yaz([1.0] * 5, akis="baska-akis")
        self.olcum_yaz([1.0] * 5, adim="duzeltme")
        self.assertEqual(self.tahmin(), (6.0, "statik"))

    def test_son_50_olcum(self):
        self.olcum_yaz([5.0] * 10 + [1.0] * 50)                         # eski pahalı ölçümler pencere dışında
        self.assertEqual(self.tahmin(), (1.0, "p90"))

    def test_bilinmeyen_akis_404(self):
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.maliyet_modeli("yok")
        self.assertEqual(c.exception.kod, 404)


if __name__ == "__main__":
    unittest.main()
