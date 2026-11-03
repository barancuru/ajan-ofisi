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

    # ---------- systemd birimleri ----------

    def birim_dosyalari(self, dizin=None):
        dizin = dizin or z.birim_dizini()
        return sorted(a for a in os.listdir(dizin) if z.BIRIM_DESENI.match(a)) if os.path.isdir(dizin) else []

    def test_birimler_uretilir_prompt_yok(self):
        is_id = self.ekle(prompt="GIZLI_ISTEK_METNI raporu hazırla")
        self.assertEqual(self.birim_dosyalari(), [f"ajan-ofisi-tekrar-{is_id}.service",
                                                  f"ajan-ofisi-tekrar-{is_id}.timer"])
        for ad in self.birim_dosyalari():
            with open(os.path.join(z.birim_dizini(), ad), encoding="utf-8") as f:
                metin = f.read()
            self.assertNotIn("GIZLI", metin)
            self.assertNotIn("rapor", metin)
            if ad.endswith(".timer"):
                self.assertIn("OnCalendar=*-*-* 09:00:00\nPersistent=true\n", metin)
            else:
                self.assertIn(f"zamanlayici.py\" --tetikle {is_id}\n", metin)
                self.assertIn("KillMode=process\n", metin)
        self.assertTrue(os.path.exists(os.path.join(z.birim_dizini(), ".degisti")))
        z.degistir({"islem": "kapat", "id": is_id}, self.tablo)
        self.assertEqual(self.birim_dosyalari(), [])  # kapalı iş: timer yok
        z.degistir({"islem": "ac", "id": is_id}, self.tablo)
        self.assertEqual(len(self.birim_dosyalari()), 2)
        z.degistir({"islem": "sil", "id": is_id}, self.tablo)
        self.assertEqual(self.birim_dosyalari(), [])

    def test_esle(self):
        hedef = os.path.join(self.d.name, "user")
        os.makedirs(hedef)
        for ad in ("ajan-ofisi-tekrar-t0000000000.timer", "ajan-ofisi-tekrar-t0000000000.service", "baska.service"):
            with open(os.path.join(hedef, ad), "w") as f:
                f.write("eski")
        is_id = self.ekle(etiket="Özet")
        cagrilar = []
        with mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)):
            z.esle(hedef, lambda *a: cagrilar.append(a))
        self.assertEqual(self.birim_dosyalari(hedef), [f"ajan-ofisi-tekrar-{is_id}.service",
                                                       f"ajan-ofisi-tekrar-{is_id}.timer"])
        self.assertTrue(os.path.exists(os.path.join(hedef, "baska.service")))  # başka birime dokunulmaz
        self.assertEqual(cagrilar, [("disable", "--now", "ajan-ofisi-tekrar-t0000000000.timer"), ("daemon-reload",),
                                    ("enable", "--now", f"ajan-ofisi-tekrar-{is_id}.timer")])
        # durum/systemd/ içine elle yazılan bir ExecStart eşlemeye girmez (içerik tekrarlar.json'dan yeniden üretilir)
        with open(os.path.join(z.birim_dizini(), f"ajan-ofisi-tekrar-{is_id}.service"), "w") as f:
            f.write("[Service]\nExecStart=/bin/rm -rf /\n")
        with mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)):
            z.esle(hedef, lambda *a: None)
        with open(os.path.join(hedef, f"ajan-ofisi-tekrar-{is_id}.service"), encoding="utf-8") as f:
            self.assertNotIn("rm -rf", f.read())

    # ---------- tetik ----------

    def test_ayni_dakika_iki_tetik_tek_kosu(self):
        is_id = self.ekle(etiket="Özet")
        baslat = mock.Mock(return_value={"kosu_id": "k", "ajan": "a"})
        an = datetime(2026, 11, 3, 9, 0, 5)
        self.assertEqual(z.tetikle(is_id, baslat, an, tablo_yukle=lambda: self.tablo), "basladi")
        self.assertIsNone(z.tetikle(is_id, baslat, an.replace(second=35), tablo_yukle=lambda: self.tablo))
        baslat.assert_called_once_with("a", "Özet", None, "tekrar")
        self.assertEqual(z.yukle(self.tablo)[0]["son_sonuc"], "basladi")
        # Persistent=true telafisi başka dakikada gelir: koşar
        self.assertEqual(z.tetikle(is_id, baslat, datetime(2026, 11, 3, 10, 2), tablo_yukle=lambda: self.tablo),
                         "basladi")
        self.assertEqual(baslat.call_count, 2)
        with self.assertRaises(ValueError):
            z.tetikle("../x", baslat, an, tablo_yukle=lambda: self.tablo)

    def test_kapali_is_kosmaz(self):
        is_id = self.ekle(etiket="Özet")
        z.degistir({"islem": "kapat", "id": is_id}, self.tablo)
        baslat = mock.Mock()
        self.assertIsNone(z.tetikle(is_id, baslat, datetime(2026, 11, 3, 9, 0), tablo_yukle=lambda: self.tablo))
        baslat.assert_not_called()

    def test_mesgul_ajan_cift_kosu_acmaz(self):
        """Gerçek gorev_baslat: ajan 'basliyor' (kilit bekliyor) iken tetik çift koşu açmaz, işi kuyruğa alır."""
        is_id = self.ekle(etiket="Özet")
        ortak.durum_yaz("a", {"durum": "basliyor", "kosu_id": "k1", "pid": None, "baslangic_ts": time.time()})
        cagri = []
        baslatici = lambda a, e, p, k: cagri.append(a) or sunucu.gorev_baslat(  # noqa: E731
            a, etiket=e, prompt=p, kaynak=k, havuz=True)
        with mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)), \
                mock.patch.object(sunucu, "tmux_hazirla", side_effect=AssertionError("ikinci koşu açıldı")) as tm:
            an = datetime(2026, 11, 3, 9, 0)
            self.assertEqual(z.tetikle(is_id, baslatici, an, tablo_yukle=lambda: self.tablo), "kuyrukta")
            self.assertIsNone(z.tetikle(is_id, baslatici, an, tablo_yukle=lambda: self.tablo))
            tm.assert_not_called()
            self.assertEqual(sunucu.kuyrugu_isle(), [])  # hâlâ meşgul: kuyrukta kalır
        self.assertEqual(cagri, ["a"])  # aynı dakikada yeniden denenmez
        self.assertEqual(z.yukle(self.tablo)[0]["son_sonuc"], "kuyrukta")
        self.assertEqual(len(sunucu.kuyruk_oku()), 1)
        self.assertEqual(ortak.durum_oku("a")["kosu_id"], "k1")  # mevcut koşunun durumu ezilmedi
        self.assertIn("kuyrukta", self.olaylar())

    def test_mesgul_havuzsuz_409_atlanir(self):
        is_id = self.ekle(etiket="Özet")
        ortak.durum_yaz("a", {"durum": "basliyor", "kosu_id": "k1", "pid": None, "baslangic_ts": time.time()})
        baslatici = lambda a, e, p, k: sunucu.gorev_baslat(a, etiket=e, prompt=p, kaynak=k)  # noqa: E731
        with mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)), \
                mock.patch.object(sunucu, "tmux_hazirla", side_effect=AssertionError("ikinci koşu açıldı")):
            self.assertEqual(z.tetikle(is_id, baslatici, datetime(2026, 11, 3, 9, 0), tablo_yukle=lambda: self.tablo),
                             "atlandi: mesgul")
        self.assertFalse(os.path.exists(sunucu.kuyruk_yolu()))

    def test_baska_hata_ayrinti_yazmaz(self):
        is_id = self.ekle(prompt="özel istek metni")
        def patla(*_):
            raise RuntimeError("özel istek metni sızdı")
        self.assertEqual(z.tetikle(is_id, patla, datetime(2026, 11, 3, 9, 0), tablo_yukle=lambda: self.tablo), "hata")
        self.assertEqual(z.yukle(self.tablo)[0]["son_sonuc"], "hata")
        self.assertNotIn("özel istek", self.olaylar())

    def test_gecersizlesen_is_kosmaz_ama_silinmez(self):
        is_id = self.ekle(etiket="Özet")
        tablo = {**self.tablo, "a": {**self.tablo["a"], "kurulu": False}}
        baslat = mock.Mock()
        self.assertIsNone(z.tetikle(is_id, baslat, datetime(2026, 11, 3, 9, 0), tablo_yukle=lambda: tablo))
        baslat.assert_not_called()
        k = z.yukle(tablo)
        self.assertEqual(len(k), 1)
        self.assertTrue(k[0]["hata"])


class OnCalendarTesti(unittest.TestCase):
    def test_ceviri(self):
        self.assertEqual(z.oncalendar("0 9 * * *"), "*-*-* 09:00:00")
        self.assertEqual(z.oncalendar("0 9 * * 1-5"), "Mon,Tue,Wed,Thu,Fri *-*-* 09:00:00")
        self.assertEqual(z.oncalendar("30 8 * * 1"), "Mon *-*-* 08:30:00")
        self.assertEqual(z.oncalendar("0 9 * * 7"), "Sun *-*-* 09:00:00")
        self.assertEqual(z.oncalendar("0 9 * * 0-6"), "*-*-* 09:00:00")
        self.assertEqual(z.oncalendar("*/15 * * * *"), "*-*-* *:00,15,30,45:00")  # kayma yok: açık liste
        self.assertEqual(z.oncalendar("0 0 31 * *"), "*-*-31 00:00:00")  # 31'i olmayan ay atlanır (cron gibi)
        self.assertEqual(z.oncalendar("0 12 29 2 *"), "*-02-29 12:00:00")
        self.assertEqual(z.oncalendar("5 */6 1,15 */3 *"), "*-01,04,07,10-01,15 00,06,12,18:05:00")

    def test_gun_veya_cevrilemez(self):
        with self.assertRaises(ValueError) as h:
            z.cron_dogrula("0 9 10 * 5")
        self.assertIn("systemd", str(h.exception))


class HavuzTesti(unittest.TestCase):
    """Alt ajan havuzu + kuyruk; tmux yerine sahte subprocess.run, model yok."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.tablo = {
            "gorevci": {"id": "gorevci", "ad": "Görevci", "kurulu": True, "cwd": self.d.name, "hazir_gorevler": []},
            "a": {"id": "a", "ad": "A", "kurulu": True, "cwd": self.d.name, "hazir_gorevler": []},
        }
        self.run = mock.Mock()
        yamalar = [mock.patch.object(ortak, "DURUM_DIZINI", self.d.name),
                   mock.patch.object(ortak, "KOSU_DIZINI", self.d.name),
                   mock.patch.object(ortak, "CIKTI_DIZINI", self.d.name),
                   mock.patch.object(ortak, "OLAYLAR", os.path.join(self.d.name, "olaylar.jsonl")),
                   mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)),
                   mock.patch.object(sunucu, "tmux_hazirla", return_value="tmux"),
                   mock.patch.object(sunucu.subprocess, "run", self.run)]
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)

    def gb(self, ajan, havuz=True, prompt="iş metni"):
        return sunucu.gorev_baslat(ajan, prompt=prompt, kaynak="ceo", havuz=havuz)

    def test_gorevci_iki_alt_sonra_kuyruk(self):
        self.assertNotIn("alt", self.gb("gorevci"))
        self.assertEqual(self.gb("gorevci")["alt"], "gorevci--alt-1")
        self.assertEqual(self.gb("gorevci")["alt"], "gorevci--alt-2")
        q = self.gb("gorevci")
        self.assertIsNone(q["kosu_id"])
        self.assertEqual(q["sira"], 1)
        self.assertEqual(self.run.call_count, 3)  # 2'den fazla alt ajan hiç açılmadı
        self.assertEqual(sunucu.kuyrugu_isle(), [])  # yuva yok: bekler
        self.assertEqual(self.run.call_count, 3)
        ortak.durum_yaz("gorevci--alt-1", {"durum": "bitti", "kosu_id": "x"})  # bir alt ajan bitti
        b = sunucu.kuyrugu_isle()
        self.assertEqual([x["alt"] for x in b], ["gorevci--alt-1"])
        self.assertEqual(self.run.call_count, 4)
        self.assertFalse(os.path.exists(sunucu.kuyruk_yolu()))
        with open(os.path.join(self.d.name, f"{b[0]['kosu_id']}.arg.json"), encoding="utf-8") as f:
            arg = json.load(f)
        self.assertEqual((arg["ajan"], arg["durum_id"]), ("gorevci", "gorevci--alt-1"))
        self.assertEqual(ortak.durum_oku("gorevci--alt-1")["durum"], "basliyor")

    def test_alt_ajansiz_ajan_kuyruga_havuzsuz_409(self):
        self.gb("a")
        with self.assertRaises(sunucu.IstekHatasi) as h:
            self.gb("a", havuz=False)
        self.assertEqual((h.exception.kod, str(h.exception)), (409, "ajan zaten çalışıyor"))
        self.assertTrue(self.gb("a")["kuyrukta"])
        self.assertEqual(self.run.call_count, 1)

    def test_kuyruk_dolu_429(self):
        self.gb("a")
        with mock.patch.object(sunucu, "MAKS_KUYRUK", 2):
            self.gb("a")
            self.gb("a")
            with self.assertRaises(sunucu.IstekHatasi) as h:
                self.gb("a")
        self.assertEqual(h.exception.kod, 429)
        self.assertIn("kuyruk dolu", str(h.exception))

    def test_kuyruk_prompt_olaya_yazilmaz_bozuk_dusurmez(self):
        self.gb("a")
        self.gb("a", prompt="GIZLI_KUYRUK_METNI")
        with open(ortak.OLAYLAR, encoding="utf-8") as f:
            self.assertNotIn("GIZLI", f.read())
        with open(sunucu.kuyruk_yolu(), "w") as f:
            f.write("{bozuk")
        self.assertEqual(sunucu.kuyrugu_isle(), [])
        self.assertEqual(len(glob.glob(sunucu.kuyruk_yolu() + ".bozuk-*")), 1)

    def test_ceo_eszamanli_sinir(self):
        with mock.patch.object(sunucu, "_ceo_kosuyor", sunucu.MAKS_ALT + 1):
            with self.assertRaises(sunucu.IstekHatasi) as h:
                sunucu.ceo_calistir("merhaba")
        self.assertEqual(h.exception.kod, 429)


if __name__ == "__main__":
    unittest.main()
