"""V2 zamanlayıcı tetiklemesi: tekrar eden iş bir workflow başlatır. Kaydederken akış etkin ve girdiler geçerli olmalı;
tetikte idem anahtarı = iş + dakika (çift tetik/telafi aynı koşu), motor kapıları yeniden uygular, kapanan akış koşmaz.
Ağ/model yok: python3 -m unittest test_zamanlayici_akis"""
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import akis_db
import akis_motor
import akis_tanim
import ortak
import sunucu
import zamanlayici as z
from test_akis_motor import SahteOrtam

AKIS = "ornek-arastirma-ozeti"


class AkisTetikTesti(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        for ad, deger in (("DURUM_DIZINI", self.d.name), ("OLAYLAR", os.path.join(self.d.name, "olaylar.jsonl"))):
            p = mock.patch.object(ortak, ad, deger)
            p.start()
            self.addCleanup(p.stop)
        self.tablo = {"a": {"id": "a", "ad": "A", "kurulu": True, "cwd": self.d.name, "hazir_gorevler": []}}
        self.tanimlar, _ = akis_tanim.tanimlari_yukle()
        self.depo = akis_db.Depo(os.path.join(self.d.name, "akis.db"))
        self.motor = akis_motor.Motor(self.depo, SahteOrtam(self.d.name), tanim_yukle=lambda: (self.tanimlar, {}),
                                      kapi_senkron=True)

    def ekle(self, **k):
        return z.degistir({"islem": "ekle", "akis": AKIS, "girdiler": {"konu": "haftalık özet"}, "cron": "0 9 * * 1", **k},
                          self.tablo)

    def tetik(self, is_id, an):
        return z.tetikle(is_id, mock.Mock(side_effect=AssertionError("ajan yolu çağrılmamalı")), an,
                         tablo_yukle=lambda: self.tablo, akis_baslatici=self.motor.baslat)

    def test_kayit_ve_tetik_workflow_baslatir(self):
        is_id = self.ekle()
        k = z.yukle(self.tablo)[0]
        self.assertEqual((k["akis"], k["girdiler"], k["ajan"], k["hata"]), (AKIS, {"konu": "haftalık özet"}, None, None))
        sonuc = self.tetik(is_id, datetime(2026, 11, 23, 9, 0, 3))
        self.assertTrue(sonuc.startswith("basladi (workflow r"), sonuc)
        kosular = self.depo.kosular()
        self.assertEqual(len(kosular), 1)
        self.assertEqual(kosular[0]["idem_anahtari"], f"tekrar:{is_id}:2026-11-23T09:00")
        self.assertEqual(json.loads(kosular[0]["girdi_json"]), {"konu": "haftalık özet"})
        with open(ortak.OLAYLAR, encoding="utf-8") as f:
            self.assertIn('"akis": "ornek-arastirma-ozeti"', f.read())

    def test_ayni_dakika_tek_kosu_telafi_ayni_kosuyu_doner(self):
        is_id = self.ekle()
        an = datetime(2026, 11, 23, 9, 0)
        self.tetik(is_id, an)
        self.assertIsNone(self.tetik(is_id, an.replace(second=40)))      # aynı dakika: damga
        z._alan_yaz(is_id, son_calisma=None)                            # damga kaybolsa da idem anahtarı korur
        self.assertTrue(self.tetik(is_id, an).startswith("atlandi: bu dilim zaten başladı"))
        self.assertEqual(len(self.depo.kosular()), 1)

    def test_kapanan_akis_kosmaz(self):
        is_id = self.ekle()
        with mock.patch.object(akis_motor, "ETKIN_AKISLAR", ()):
            self.assertIsNotNone(z.yukle(self.tablo)[0]["hata"])          # yüklemede de geçersiz: tetiklenmez
            self.assertIsNone(self.tetik(is_id, datetime(2026, 11, 23, 9, 0)))
        self.assertEqual(self.depo.kosular(), [])

    def test_motor_reddi_sonuca_yazilir(self):
        is_id = self.ekle()
        red = mock.Mock(side_effect=akis_motor.AkisHatasi(429, "en çok 5 etkin workflow koşusu"))
        self.assertEqual(z.tetikle(is_id, mock.Mock(), datetime(2026, 11, 23, 9, 0), tablo_yukle=lambda: self.tablo,
                                   akis_baslatici=red), "atlandi: etkin koşu sınırı")
        self.assertEqual(z.yukle(self.tablo)[0]["son_sonuc"], "atlandi: etkin koşu sınırı")

    def test_kayit_dogrulamasi(self):
        hatalar = [
            ({"akis": "yok-boyle"}, "bilinmeyen akış"),
            ({"akis": "../x"}, "geçersiz akış id"),
            ({"akis": "homeos-ozellik-gelistirme", "girdiler": {"baslik": "abc", "istek": "x"}}, "etkin değil"),
            ({"girdiler": {}}, "konu gerekli"),
            ({"girdiler": {"konu": "x", "fazla": 1}}, "bilinmeyen girdi"),
            ({"girdiler": {"konu": "sk-" + "a" * 30}}, "sır"),
            ({"ajan": "a"}, "ajan/hazır görev/prompt almaz"),
            ({"cron": "* * * * *"}, "15"),
        ]
        for ek, parca in hatalar:
            with self.assertRaises(ValueError, msg=ek) as c:
                self.ekle(**ek)
            self.assertIn(parca, str(c.exception), ek)
        self.assertEqual(z._yukle_ham(), [])

    def test_systemd_birimi_ajan_isiyle_ayni(self):
        is_id = self.ekle()
        with mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)):
            metinler = z.birimler(z.yukle(self.tablo))
        self.assertEqual(sorted(metinler), [f"ajan-ofisi-tekrar-{is_id}.service", f"ajan-ofisi-tekrar-{is_id}.timer"])
        self.assertNotIn("haftalık", "".join(metinler.values()))       # girdi birim dosyasına yazılmaz

    def test_ongorulebilirlik_yaniti_akis_secenekleri(self):
        is_id = self.ekle()
        with mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)):
            y = sunucu.ongorulebilirlik_yaniti()
        self.assertEqual([a["id"] for a in y["akislar"]], [AKIS])          # yalnız etkin akışlar
        self.assertEqual(y["akislar"][0]["girdiler"]["konu"]["tur"], "metin")
        satir = next(k for k in y["isler"] if k["id"] == is_id)
        self.assertEqual(satir["akis"], AKIS)
        self.assertTrue(satir["ad"].startswith("Workflow: "))


if __name__ == "__main__":
    unittest.main()
