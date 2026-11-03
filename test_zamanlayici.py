"""Öngörülebilirlik: cron, doğrulama, depo ve zamanlayıcı tik'i. Ağ yok, model yok: python3 -m unittest test_zamanlayici"""
import glob
import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from unittest import mock

import ortak
import sunucu
import zamanlayici as z


class CronTesti(unittest.TestCase):
    def test_ay_sonu(self):
        self.assertEqual(z.sonraki("0 0 31 * *", datetime(2026, 11, 3, 10, 0)), datetime(2026, 12, 31, 0, 0))

    def test_subat_29(self):
        self.assertEqual(z.sonraki("0 12 29 2 *", datetime(2027, 3, 1)), datetime(2028, 2, 29, 12, 0))
        self.assertIsNone(z.sonraki("0 12 29 2 *", datetime(2026, 11, 3)))  # 366 günden ileride
        self.assertIsNone(z.sonraki("0 0 30 2 *", datetime(2026, 11, 3)))

    def test_her_15_dk(self):
        self.assertEqual(z.sonraki("*/15 * * * *", datetime(2026, 11, 3, 10, 7, 30)), datetime(2026, 11, 3, 10, 15))
        self.assertEqual(z.sonraki("*/15 * * * *", datetime(2026, 11, 3, 10, 15)), datetime(2026, 11, 3, 10, 30))
        self.assertEqual(z.sonraki("*/15 * * * *", datetime(2026, 11, 3, 23, 50)), datetime(2026, 11, 4, 0, 0))

    def test_hafta_gunu(self):
        # 2026-11-03 Salı → Pazartesi 9 Kasım
        self.assertEqual(z.sonraki("30 8 * * 1", datetime(2026, 11, 3, 12, 0)), datetime(2026, 11, 9, 8, 30))
        self.assertTrue(z.eslesir("0 9 * * 7", datetime(2026, 11, 8, 9, 0)))  # 7 = Pazar
        self.assertTrue(z.eslesir("0 9 * * 0", datetime(2026, 11, 8, 9, 0)))
        self.assertEqual(z.sonraki("0 9 * * 1-5", datetime(2026, 11, 6, 9, 0)), datetime(2026, 11, 9, 9, 0))

    def test_gun_veya_kurali(self):
        # ay günü 10 VEYA Cuma: 7 Kasım Cmt → 10 Kasım Salı (ay günü); 11 Kasım → 13 Kasım Cuma
        self.assertEqual(z.sonraki("0 9 10 * 5", datetime(2026, 11, 7)), datetime(2026, 11, 10, 9, 0))
        self.assertEqual(z.sonraki("0 9 10 * 5", datetime(2026, 11, 11)), datetime(2026, 11, 13, 9, 0))

    def test_sonrakiler(self):
        self.assertEqual(z.sonrakiler("0 9 * * *", datetime(2026, 11, 3, 10, 0)),
                         [datetime(2026, 11, d, 9, 0) for d in (4, 5, 6)])

    def test_gecersiz(self):
        for ifade in ("", "* * * *", "60 * * * *", "0 24 * * *", "0 0 0 * *", "0 0 * 13 *", "0 0 * * 8",
                      "a b c d e", "5-1 * * * *", "*/0 * * * *", "0 0 * * * *", None, 5):
            with self.assertRaises(ValueError, msg=repr(ifade)):
                z.cron_dogrula(ifade)

    def test_15_dk_alt_siniri(self):
        for ifade in ("* * * * *", "*/10 * * * *", "0,5 9 * * *", "0,50 0,23 * * *"):
            with self.assertRaises(ValueError, msg=ifade):
                z.cron_dogrula(ifade)
        for ifade in ("*/15 * * * *", "0 * * * *", "0,50 0,23 1 * *", "30 8 * * 1"):
            self.assertEqual(z.cron_dogrula(ifade), ifade)

    def test_ozet(self):
        self.assertEqual(z.ozet("0 9 * * *"), "her gün 09:00")
        self.assertEqual(z.ozet("0 9 * * 1-5"), "hafta içi 09:00")
        self.assertEqual(z.ozet("0 * * * *"), "her saat :00")
        self.assertEqual(z.ozet("30 8 * * 1"), "her Pazartesi 08:30")
        self.assertEqual(z.ozet("*/20 * * * *"), "*/20 * * * *")


class DepoTesti(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        for ad, deger in (("DURUM_DIZINI", self.d.name), ("OLAYLAR", os.path.join(self.d.name, "olaylar.jsonl"))):
            p = mock.patch.object(ortak, ad, deger)
            p.start()
            self.addCleanup(p.stop)
        self.tablo = {
            "ceo": {"id": "ceo", "kurulu": True, "hazir_gorevler": []},
            "a": {"id": "a", "ad": "A", "kurulu": True, "cwd": self.d.name,
                  "hazir_gorevler": [{"etiket": "Özet", "prompt": "özet çıkar"}]},
            "kurulmamis": {"id": "kurulmamis", "kurulu": False, "hazir_gorevler": []},
        }

    def olaylar(self):
        try:
            with open(ortak.OLAYLAR, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def ekle(self, **k):
        return z.degistir({"islem": "ekle", "ajan": "a", "cron": "0 9 * * *", **k}, self.tablo)

    def test_dogrulama_reddi(self):
        hatalar = [
            {"ajan": "yok", "etiket": "Özet"}, {"ajan": "ceo", "prompt": "x"}, {"ajan": "kurulmamis", "prompt": "x"},
            {"etiket": "Özet", "prompt": "ikisi birden"}, {}, {"prompt": "   "}, {"etiket": "Bilinmeyen"},
            {"prompt": "x" * (ortak.MAKS_GIRDI + 1)}, {"prompt": "rapor", "cron": "*/5 * * * *"},
            {"prompt": "rapor", "cron": "bozuk"},
        ]
        for h in hatalar:
            with self.assertRaises(ValueError, msg=repr(h)):
                z.is_dogrula({"ajan": "a", "cron": "0 9 * * *", **h}, self.tablo)

    def test_sir_kalibi(self):
        for p in ("anahtar sk-ant-api03-abcdefghijklmnop kullan", "Authorization: Bearer xyz", "password=1234",
                  "token = abc", "a3f9c2d17b8e4f6a90c1d2e3", "ghp_A1b2C3d4E5f6G7h8I9j0kLmN"):
            with self.assertRaises(ValueError, msg=p):
                z.is_dogrula({"ajan": "a", "cron": "0 9 * * *", "prompt": p}, self.tablo)
        temiz = "Haftalık özeti cikti/yazar/2026-11 klasörüne yaz; task-list güncel mi bak."
        self.assertEqual(z.is_dogrula({"ajan": "a", "cron": "0 9 * * *", "prompt": temiz}, self.tablo)["prompt"], temiz)

    def test_ekle_ac_kapat_sil_kalici(self):
        is_id = self.ekle(etiket="Özet")
        self.assertRegex(is_id, z.IS_ID_DESENI)
        with open(z.tekrarlar_yolu(), encoding="utf-8") as f:
            veri = json.load(f)
        self.assertEqual(veri["surum"], 1)
        self.assertEqual(veri["isler"][0]["etiket"], "Özet")
        z.degistir({"islem": "kapat", "id": is_id}, self.tablo)
        self.assertFalse(z.yukle(self.tablo)[0]["aktif"])
        z.degistir({"islem": "ac", "id": is_id}, self.tablo)
        self.assertTrue(z.yukle(self.tablo)[0]["aktif"])
        z.degistir({"islem": "sil", "id": is_id}, self.tablo)
        self.assertEqual(z.yukle(self.tablo), [])
        with self.assertRaises(ValueError):
            z.degistir({"islem": "sil", "id": "../../x"}, self.tablo)

    def test_prompt_olaya_yazilmaz(self):
        self.ekle(prompt="GIZLI_METIN_OLAYA_GITMESIN gibi bir istek")
        self.assertNotIn("GIZLI_METIN", self.olaylar())

    def test_en_fazla_50(self):
        for _ in range(z.MAKS_IS):
            self.ekle(etiket="Özet")
        with self.assertRaises(ValueError):
            self.ekle(etiket="Özet")

    def test_bozuk_json_dusurmez(self):
        os.makedirs(ortak.DURUM_DIZINI, exist_ok=True)
        with open(z.tekrarlar_yolu(), "w", encoding="utf-8") as f:
            f.write("{bozuk")
        self.assertEqual(z.yukle(self.tablo), [])
        self.assertFalse(os.path.exists(z.tekrarlar_yolu()))
        self.assertEqual(len(glob.glob(z.tekrarlar_yolu() + ".bozuk-*")), 1)
        self.assertIn("tekrarlar.json bozuk", self.olaylar())
        self.ekle(etiket="Özet")  # sonra normal çalışır
        self.assertEqual(len(z.yukle(self.tablo)), 1)

    def test_sunucu_400_turkce(self):
        with mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)):
            with self.assertRaises(sunucu.IstekHatasi) as h:
                sunucu.ongorulebilirlik_degistir({"islem": "ekle", "ajan": "a", "prompt": "x", "cron": "* * * * *"})
            self.assertEqual(h.exception.kod, 400)
            self.assertIn("dakikada", str(h.exception))
            r = sunucu.ongorulebilirlik_degistir({"islem": "onizle", "cron": "0 9 * * *"})
            self.assertEqual(len(r["sonrakiler"]), 3)
            r = sunucu.ongorulebilirlik_degistir({"islem": "ekle", "ajan": "a", "etiket": "Özet", "cron": "0 9 * * *"})
            self.assertEqual(r["isler"][0]["ozet"], "her gün 09:00")
            self.assertIsNotNone(r["isler"][0]["sonraki"])

    # ---------- tik ----------

    def test_bosta_hicbir_sey_okumaz(self):
        yukle = mock.Mock()
        baslat = mock.Mock()
        self.assertEqual(z.tik(baslat, datetime(2026, 11, 3, 9, 0), tablo_yukle=yukle), [])
        yukle.assert_not_called()
        baslat.assert_not_called()

    def test_ayni_dakika_iki_tik_tek_kosu(self):
        is_id = self.ekle(etiket="Özet")
        baslat = mock.Mock()
        an = datetime(2026, 11, 3, 9, 0, 5)
        self.assertEqual(z.tik(baslat, an, tablo_yukle=lambda: self.tablo), [is_id])
        self.assertEqual(z.tik(baslat, an.replace(second=35), tablo_yukle=lambda: self.tablo), [])
        baslat.assert_called_once_with("a", "Özet", None, "tekrar")
        self.assertEqual(z.yukle(self.tablo)[0]["son_sonuc"], "basladi")
        self.assertEqual(z.tik(baslat, datetime(2026, 11, 3, 9, 1), tablo_yukle=lambda: self.tablo), [])  # vakti değil
        baslat.assert_called_once()

    def test_kapali_is_kosmaz(self):
        is_id = self.ekle(etiket="Özet")
        z.degistir({"islem": "kapat", "id": is_id}, self.tablo)
        baslat = mock.Mock()
        z.tik(baslat, datetime(2026, 11, 3, 9, 0), tablo_yukle=lambda: self.tablo)
        baslat.assert_not_called()

    def test_mesgul_ajan_cift_kosu_acmaz(self):
        """Gerçek gorev_baslat: ajan 'basliyor' (kilit bekliyor) iken tetik 409'u yutar, tmux açılmaz."""
        self.ekle(etiket="Özet")
        ortak.durum_yaz("a", {"durum": "basliyor", "kosu_id": "k1", "pid": None, "baslangic_ts": time.time()})
        cagri = []
        baslatici = lambda a, e, p, k: cagri.append(a) or sunucu.gorev_baslat(a, etiket=e, prompt=p, kaynak=k)  # noqa: E731
        with mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)), \
                mock.patch.object(sunucu, "tmux_hazirla", side_effect=AssertionError("ikinci koşu açıldı")) as tm:
            an = datetime(2026, 11, 3, 9, 0)
            self.assertEqual(z.tik(baslatici, an, tablo_yukle=lambda: self.tablo), [])
            self.assertEqual(z.tik(baslatici, an, tablo_yukle=lambda: self.tablo), [])
            tm.assert_not_called()
        self.assertEqual(cagri, ["a"])  # aynı dakikada yeniden denenmez
        self.assertEqual(z.yukle(self.tablo)[0]["son_sonuc"], "atlandi: mesgul")
        self.assertEqual(ortak.durum_oku("a")["kosu_id"], "k1")  # mevcut koşunun durumu ezilmedi
        self.assertIn("atlandi: mesgul", self.olaylar())

    def test_baska_hata_ayrinti_yazmaz(self):
        self.ekle(prompt="özel istek metni")
        def patla(*_):
            raise RuntimeError("özel istek metni sızdı")
        z.tik(patla, datetime(2026, 11, 3, 9, 0), tablo_yukle=lambda: self.tablo)
        self.assertEqual(z.yukle(self.tablo)[0]["son_sonuc"], "hata")
        self.assertNotIn("özel istek", self.olaylar())

    def test_gecersizlesen_is_kosmaz_ama_silinmez(self):
        self.ekle(etiket="Özet")
        tablo = {**self.tablo, "a": {**self.tablo["a"], "kurulu": False}}
        baslat = mock.Mock()
        z.tik(baslat, datetime(2026, 11, 3, 9, 0), tablo_yukle=lambda: tablo)
        baslat.assert_not_called()
        k = z.yukle(tablo)
        self.assertEqual(len(k), 1)
        self.assertTrue(k[0]["hata"])


if __name__ == "__main__":
    unittest.main()
