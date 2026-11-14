"""Nöbetçi alarmları ve takılan görevler: bozuk dosya, yol enjeksiyonu, durum kontrolü, kapı imzası, kalıcılık."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import sunucu


def gorev(durum="takildi", ek=""):
    return f"---\ndurum: {durum}\ntur: gelistirme\nproje: ajan-ofisi\ndeneme: 3\nteshis: hata\n---\n# Örnek\n\n## İstek\nx\n{ek}"


class NobetciTesti(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        imza = os.path.join(self.d, "kapi.env")
        with open(imza, "w", encoding="utf-8") as f:
            f.write("OFIS_KAPI_IMZA=dogru\n")
        self.gorevler = os.path.join(self.d, "gorevler")
        os.makedirs(self.gorevler)
        self.alarm = os.path.join(self.d, "alarm.json")
        self.takilan = os.path.join(self.d, "takilanlar.json")
        for ad, deger in (("KAPI_IMZA_DOSYASI", imza), ("GOREV_DIZINI", self.gorevler), ("ALARM_DOSYASI", self.alarm),
                          ("TAKILAN_DOSYASI", self.takilan), ("ALARM_OKUNDU_DOSYASI", os.path.join(self.d, "durum", "okundu.json"))):
            y = mock.patch.object(sunucu, ad, deger)
            y.start()
            self.addCleanup(y.stop)
        y = mock.patch.object(sunucu, "kosucuyu_durt")
        y.start()
        self.addCleanup(y.stop)

    def yaz(self, yol, icerik):
        with open(yol, "w", encoding="utf-8") as f:
            f.write(icerik if isinstance(icerik, str) else json.dumps(icerik))

    def gorev_yaz(self, ad="A.md", **kw):
        yol = os.path.join(self.gorevler, ad)
        self.yaz(yol, gorev(**kw))
        return yol

    def okut(self, yol):
        with open(yol, encoding="utf-8") as f:
            return sunucu.on_bilgi(f.read())[0]

    def alarm_yaz(self, *kayitlar):
        self.yaz(self.alarm, list(kayitlar))

    @staticmethod
    def kayit(dk=5, seviye="kritik", mesaj="m"):
        return {"zaman": (datetime.now() - timedelta(minutes=dk)).isoformat(timespec="seconds"), "proje": "homeos", "seviye": seviye, "mesaj": mesaj}

    # --- okuma ---
    def test_dosyalar_yok_bos(self):
        self.assertEqual(sunucu.alarmlar_oku(), [])
        self.assertEqual(sunucu.takilanlari_oku(), [])

    def test_bozuk_json_bos(self):
        for icerik in ("{bozuk", "", '{"a": 1}', "[1, 2, null]", "\x00\xff"):
            self.yaz(self.alarm, icerik)
            self.yaz(self.takilan, icerik)
            self.assertEqual(sunucu.alarmlar_oku(), [])
            self.assertEqual(sunucu.takilanlari_oku(), [])

    def test_alarm_son_24_saat(self):
        self.alarm_yaz(self.kayit(5), self.kayit(60 * 25, mesaj="eski"), {"zaman": "bozuk", "mesaj": "x"})
        a = sunucu.alarmlar_oku()
        self.assertEqual([x["mesaj"] for x in a], ["m"])
        self.assertFalse(a[0]["okundu"])

    def test_takilan_yalniz_takildi_olan_gercek_dosya(self):
        self.gorev_yaz("A.md", ek="\n## Teşhis (nöbetçi)\nneden şu\n\n## Son\nz\n")
        self.gorev_yaz("B.md", durum="hazir")
        self.yaz(self.takilan, [
            {"gorev": "A.md", "proje": "p", "neden": "n", "ayrinti": "a", "deneme": 3, "teshis": "yapildi", "degisti": False},
            {"gorev": "B.md"}, {"gorev": "yok.md"}, {"gorev": "../x.md"}, "metin"])
        t = sunucu.takilanlari_oku()
        self.assertEqual([x["gorev"] for x in t], ["A.md"])
        self.assertTrue(t[0]["teshis_metin"].startswith("## Teşhis (nöbetçi)"))
        self.assertNotIn("Son", t[0]["teshis_metin"])

    # --- Gördüm ---
    def test_gordum_kapisiz_reddedilir(self):
        self.alarm_yaz(self.kayit())
        with self.assertRaises(sunucu.IstekHatasi) as h:
            sunucu.gelistirme_degistir({"islem": "alarm-gordum"}, "yanlis")
        self.assertEqual(h.exception.kod, 403)
        self.assertFalse(sunucu.alarmlar_oku()[0]["okundu"])

    def test_okundu_kalici_yeni_alarm_gelir(self):
        self.alarm_yaz(self.kayit(5))
        sunucu.alarm_gordum("dogru")
        self.assertTrue(sunucu.alarmlar_oku()[0]["okundu"])
        self.assertTrue(sunucu.alarmlar_oku()[0]["okundu"])  # "yenileme": dosyadan yeniden okunur
        self.alarm_yaz(self.kayit(5), self.kayit(1, mesaj="yeni"))
        durum = {a["mesaj"]: a["okundu"] for a in sunucu.alarmlar_oku()}
        self.assertEqual(durum, {"m": True, "yeni": False})

    # --- takılan görev işlemleri ---
    def test_kapisiz_reddedilir(self):
        yol = self.gorev_yaz()
        for imza in ("", "yanlis"):
            with self.assertRaises(sunucu.IstekHatasi) as h:
                sunucu.takilan_islem("A.md", "iptal", imza)
            self.assertEqual(h.exception.kod, 403)
        self.assertEqual(self.okut(yol)["durum"], "takildi")

    def test_gecersiz_gorev_adi(self):
        self.gorev_yaz()
        self.yaz(os.path.join(self.d, "disarida.md"), gorev())
        for ad in ("../disarida.md", "/etc/passwd", "a/../A.md", "yok.md", "", None, 5, ".gizli.md", "A.md\x00"):
            with self.assertRaises(sunucu.IstekHatasi, msg=repr(ad)):
                sunucu.takilan_islem(ad, "iptal", "dogru")
        self.assertEqual(self.okut(os.path.join(self.d, "disarida.md"))["durum"], "takildi")

    def test_takildi_disindaki_reddedilir(self):
        for durum in ("hazir", "calisiyor", "uat", "reddedildi"):
            yol = self.gorev_yaz(durum=durum)
            with self.assertRaises(sunucu.IstekHatasi) as h:
                sunucu.takilan_islem("A", "yeniden-dene", "dogru")
            self.assertEqual(h.exception.kod, 409)
            self.assertEqual(self.okut(yol)["durum"], durum)

    def test_gecersiz_eylem(self):
        self.gorev_yaz()
        with self.assertRaises(sunucu.IstekHatasi):
            sunucu.takilan_islem("A.md", "sil", "dogru")

    def test_yeniden_dene(self):
        yol = self.gorev_yaz()
        sunucu.gelistirme_degistir({"islem": "takilan", "gorev": "A.md", "eylem": "yeniden-dene"}, "dogru")
        fm = self.okut(yol)
        self.assertEqual((fm["durum"], fm["deneme"], fm["teshis"]), ("hazir", "0", "hata"))

    def test_teshis_iste(self):
        yol = self.gorev_yaz()
        sunucu.takilan_islem("A.md", "teshis-iste", "dogru")
        fm = self.okut(yol)
        self.assertEqual((fm["durum"], fm["deneme"], fm["teshis"]), ("takildi", "3", ""))

    def test_iptal(self):
        yol = self.gorev_yaz()
        sunucu.takilan_islem("A.md", "iptal", "dogru")
        fm = self.okut(yol)
        self.assertEqual((fm["durum"], fm["deneme"]), ("reddedildi", "3"))

    def test_symlink_reddedilir(self):
        hedef = os.path.join(self.d, "hedef.md")
        self.yaz(hedef, gorev())
        os.symlink(hedef, os.path.join(self.gorevler, "L.md"))
        with self.assertRaises(sunucu.IstekHatasi):
            sunucu.takilan_islem("L.md", "iptal", "dogru")
        self.assertEqual(self.okut(hedef)["durum"], "takildi")


if __name__ == "__main__":
    unittest.main()
