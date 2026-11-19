"""V1.1 #9 operatör kararları: 'adımı başarılı say' (kapı + gerekçe, yalnız başarısız ajan adımı) ve 'ek bütçe'
(kapı + gerekçe, sınırlı, denetim olayı). Her ret yolu ve uçtan uca başarı.  python3 -m unittest test_akis_operator"""
import json
import os
import sqlite3
import tempfile
import unittest

import akis_db
import akis_motor
from test_akis_birim import taban_tanim
from test_akis_motor import MotorTabani

G = "test ortamı çıktısını elle doğruladım"


class BasariliSayTest(MotorTabani):
    def incelemede(self, **ek):
        t = taban_tanim(**ek)
        self.tanim(t)
        k = self.m.baslat(t["id"], {"konu": "x"})["run_id"]
        self.m.tur()
        self.ajan_bitir(self.son_ref(), durum="hata", hata="bozuk")   # yan etkili: elle karar (sebep adim)
        self.m.tur()
        d = self.detay(k)
        self.assertEqual((d["durum"], d["neden"]["sebep"]), ("inceleme", "adim"))
        return k

    def test_kapisiz_ya_da_gerekcesiz_reddedilir(self):
        k = self.incelemede()
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.basarili_say(k, "a", G, {"sonuc": "iyi"})
        self.assertEqual(c.exception.kod, 403)
        for g in (None, "kısa", "x" * 2001, "password=hunter2hunter2 ok"):
            with self.assertRaises(akis_motor.AkisHatasi) as c:
                self.m.basarili_say(k, "a", g, {"sonuc": "iyi"}, kapi_ok=True)
            self.assertEqual(c.exception.kod, 400, g)
        self.assertEqual(self.detay(k)["durum"], "inceleme")

    def test_cikti_dogrulanir(self):
        k = self.incelemede()
        for cikti in (None, {}, {"sonuc": "belki"}, {"sonuc": "sk-ant-abcdefghijklmnop"}, "iyi"):
            with self.assertRaises(akis_motor.AkisHatasi) as c:
                self.m.basarili_say(k, "a", G, cikti, kapi_ok=True)
            self.assertEqual(c.exception.kod, 400, cikti)

    def test_yanlis_adim_ve_ucusta_reddedilir(self):
        k = self.incelemede()
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.basarili_say(k, "k", G, {"sonuc": "iyi"}, kapi_ok=True)
        self.assertEqual(c.exception.kod, 409)
        self.depo.baglanti().execute("UPDATE denemeler SET durum='calisiyor' WHERE kosu_id=?", (k,))
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.basarili_say(k, "a", G, {"sonuc": "iyi"}, kapi_ok=True)
        self.assertEqual(c.exception.kod, 409)

    def test_tanim_yonlendirmesi_basarili_sayilamaz(self):
        """Başarılı adımın kendi geçişi @inceleme'ye götürdüyse (sebep tanim) operatör bunu atlayamaz."""
        t = taban_tanim()
        self.tanim(t)
        k = self.m.baslat(t["id"], {"konu": "x"})["run_id"]
        self.m.tur()
        self.ajan_bitir(self.son_ref(), '<akis_cikti>{"sonuc": "kotu"}</akis_cikti>')
        self.m.tur()
        self.assertEqual(self.detay(k)["neden"]["sebep"], "tanim")
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.basarili_say(k, self.detay(k)["neden"].get("adim") or "k", G, {"sonuc": "iyi"}, kapi_ok=True)
        self.assertEqual(c.exception.kod, 409)

    def test_kapi_adimi_basarili_sayilamaz(self):
        """Kapının kanıtı komut çıkışıdır: neden 'adim' olsa da quality_gate adımı reddedilir."""
        t = taban_tanim()
        t["adimlar"][0]["sonraki"] = "q"
        t["adimlar"].insert(1, {"id": "q", "tur": "quality_gate", "kontroller": [
            {"ad": "dosya", "komut": ["test", "-f", "{ofis}/yok"], "cwd": "{ofis}"}], "sonraki": "k", "basarisizsa": "@inceleme"})
        self.tanim(t)
        k = self.m.baslat(t["id"], {"konu": "x"})["run_id"]
        self.depo.baglanti().execute("UPDATE kosular SET durum='inceleme', neden=? WHERE id=?",
                                     (json.dumps({"sebep": "adim", "adim": "q"}), k))
        self.depo.baglanti().execute("UPDATE adimlar SET durum='inceleme' WHERE kosu_id=? AND adim_id='q'", (k,))
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.basarili_say(k, "q", G, {}, kapi_ok=True)
        self.assertEqual(c.exception.kod, 409)

    def test_basarili_sayilan_adim_akisi_sonuna_goturur(self):
        k = self.incelemede()
        d = self.m.basarili_say(k, "a", G, {"sonuc": "iyi"}, kapi_ok=True)
        self.m.tur()
        d = self.detay(k)
        self.assertEqual(d["durum"], "basarili")
        a = self.adim(k, "a")
        self.assertEqual((a["durum"], a["cikti"]), ("basarili", {"sonuc": "iyi"}))
        self.assertIn("operatör başarılı saydı", a["hata"])
        olay = [o for o in d["olaylar"] if o["tur"] == "operator_basarili_saydi"]
        self.assertEqual(olay[0]["gerekce"], G)
        with self.assertRaises(akis_motor.AkisHatasi):   # ikinci kez yok
            self.m.basarili_say(k, "a", G, {"sonuc": "iyi"}, kapi_ok=True)


class EkButceTest(MotorTabani):
    def butcede(self, **sinir):
        t = taban_tanim(sinirlar={"max_ajan_cagrisi": 1, "max_maliyet_usd": 2, **sinir})
        t["adimlar"][1]["yanlis"] = "a2"
        t["adimlar"].insert(2, {"id": "a2", "tur": "agent_task", "ajan": "arastirmaci", "gorev": "tekrar",
                                "cikti_alanlari": {}, "sonraki": "son"})
        self.tanim(t)
        k = self.m.baslat(t["id"], {"konu": "x"})["run_id"]
        self.m.tur()
        self.ajan_bitir(self.son_ref(), '<akis_cikti>{"sonuc": "kotu"}</akis_cikti>')
        self.m.tur()
        d = self.detay(k)
        self.assertEqual((d["durum"], d["neden"]["sebep"], d["neden"]["adim"]), ("inceleme", "butce", "a2"))
        return k

    def test_ek_cagri_ile_devam_ve_denetim(self):
        k = self.butcede()
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.ek_butce(k, G, ek_cagri=1)
        self.assertEqual(c.exception.kod, 403)
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.devam(k, "yeniden_dene")              # bütçe incelemesi yeniden denenmez: tek çıkış ek bütçe
        self.assertEqual(c.exception.kod, 409)
        d = self.m.ek_butce(k, G, ek_cagri=1, kapi_ok=True)
        self.assertEqual((d["sinirlar"]["max_ajan_cagrisi"], d["ek"]["ajan_cagrisi"]), (2, 1))
        self.m.tur()
        self.assertEqual(len(self.ortam.baslatilan), 2)
        self.ajan_bitir(self.son_ref(), "")
        self.m.tur()
        d = self.detay(k)
        self.assertEqual(d["durum"], "basarili")
        self.assertEqual([o["gerekce"] for o in d["olaylar"] if o["tur"] == "ek_butce"], [G])

    def test_ek_butce_tavani_ve_girdi(self):
        k = self.butcede()
        for ek in ({"ek_usd": -1}, {"ek_usd": True}, {"ek_cagri": 1.5}, {"ek_usd": float("nan")}, {}):
            with self.assertRaises(akis_motor.AkisHatasi) as c:
                self.m.ek_butce(k, G, kapi_ok=True, **ek)
            self.assertEqual(c.exception.kod, 400, ek)
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.ek_butce(k, G, ek_cagri=2, kapi_ok=True)   # tanım sınırı 1: en çok +1
        self.assertEqual(c.exception.kod, 409)
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.ek_butce(k, G, ek_usd=2.01, kapi_ok=True)
        self.assertEqual(c.exception.kod, 409)
        self.assertEqual(self.detay(k)["durum"], "inceleme")

    def test_yalniz_butce_incelemesinde(self):
        t = taban_tanim()
        self.tanim(t)
        k = self.m.baslat(t["id"], {"konu": "x"})["run_id"]
        self.m.tur()
        self.ajan_bitir(self.son_ref(), durum="hata", hata="bozuk")
        self.m.tur()
        with self.assertRaises(akis_motor.AkisHatasi) as c:
            self.m.ek_butce(k, G, ek_usd=1, kapi_ok=True)
        self.assertEqual(c.exception.kod, 409)


class MigrationGeriUyumTest(unittest.TestCase):
    def test_eski_kod_surum_4_db_ile_calisir(self):
        """1.0.88'e geri dönüş: migration 3'e kadar bilen kod user_version 4 DB'de migration çalıştırmaz,
        ek sütunları okumaz (ek bütçe yok sayılır = sınır daralır)."""
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "akis.db")
            akis_db.Depo(yol).kapat()
            self.assertEqual(sqlite3.connect(yol).execute("PRAGMA user_version").fetchone()[0], 4)
            eski = akis_db.MIGRATIONLAR[:3]
            from unittest import mock
            with mock.patch.object(akis_db, "MIGRATIONLAR", eski):
                depo = akis_db.Depo(yol)
                self.assertEqual(depo.surum(), 4)
                depo.kapat()


if __name__ == "__main__":
    unittest.main()
