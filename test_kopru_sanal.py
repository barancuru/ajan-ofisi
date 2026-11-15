"""Sanal gözlem ajanları (ana-ajan, gelistirme-hatti): köprü eşlemesi ve token sayacı. python3 -m unittest test_kopru_sanal"""
import json
import os
import tempfile
from datetime import datetime, timezone
import unittest
from unittest import mock

import kopru
import ortak
import token_sayac

EV = os.path.expanduser("~")
HAT = os.path.join(EV, "beyin-is", "wt")


def kopru_kur(esleme=None):
    k = kopru.Kopru()
    tablo = {"ceo": {"id": "ceo", "oda": "ceo"}, "gorevci": {"id": "gorevci", "oda": "genel"},
             "kodcu": {"id": "kodcu", "oda": "kod"}}
    k.ajanlar = {**tablo, **ortak.sanal_ajanlar(tablo)}
    k.esleme = esleme if esleme is not None else {"varsayilan": "", "cwd": {"~/beyin": "gorevci"}}
    return k


class AjanBulTesti(unittest.TestCase):
    def test_ev_klasoru_ana_ajan(self):
        self.assertEqual(kopru_kur().ajan_bul(EV, "", ""), ("ana-ajan", False))

    def test_ev_klasoru_etkilesimsiz_eslenmez(self):
        self.assertEqual(kopru_kur().ajan_bul(EV, "", "", etkilesimli=False), (None, False))

    def test_ev_alt_klasoru_eski_kural(self):
        k = kopru_kur()
        self.assertEqual(k.ajan_bul(os.path.join(EV, "beyin", "x"), "", ""), ("gorevci", False))
        self.assertEqual(k.ajan_bul(os.path.join(EV, "baska"), "", ""), (None, False))   # varsayilan ""

    def test_hat_etkilesimsiz(self):
        k = kopru_kur()
        self.assertEqual(k.ajan_bul(os.path.join(HAT, "homeos-1114-x"), "", "", etkilesimli=False),
                         ("gelistirme-hatti", False))
        self.assertEqual(k.ajan_bul(os.path.join(HAT, "homeos-1114-x", "on-yuz"), "", ""), ("gelistirme-hatti", False))

    def test_hat_kardes_klasor_eslenmez(self):
        self.assertEqual(kopru_kur().ajan_bul(HAT + "-eski", "", "", etkilesimli=False), (None, False))

    def test_oneri_taramasi_hat_kokunde_taninir(self):
        # calistir `oneri` kod kopyasını ~/beyin-is/wt/<proje>-oneri altında açar; /tmp altındaki oturum tanınmaz
        k = kopru_kur()
        self.assertEqual(k.ajan_bul(os.path.join(HAT, "homeos-oneri"), "", "", etkilesimli=False),
                         ("gelistirme-hatti", False))
        self.assertEqual(kopru.hat_etiketi(os.path.join(HAT, "homeos-oneri"), HAT), "homeos-oneri")
        self.assertEqual(kopru.hat_projesi("homeos-oneri", ["homeos"]), "homeos")
        self.assertEqual(k.ajan_bul("/tmp/tmp.abc123", "", "", etkilesimli=False), (None, False))

    def test_gizle_onceligi(self):
        k = kopru_kur({"varsayilan": "", "gizle": ["homeos"]})
        self.assertEqual(k.ajan_bul(os.path.join(HAT, "homeos-1114-x"), "", "", etkilesimli=False), (None, True))
        k = kopru_kur({"varsayilan": "", "atla_cwd": ["~"]})
        self.assertEqual(k.ajan_bul(EV, "", ""), (None, True))

    def test_bos_liste_kapatir(self):
        k = kopru_kur({"varsayilan": "", "ana_ajan_cwd": [], "hat_cwd": []})
        self.assertEqual(k.ajan_bul(EV, "", ""), (None, False))
        self.assertEqual(k.ajan_bul(os.path.join(HAT, "x"), "", "", etkilesimli=False), (None, False))

    def test_acik_cwd_eslemesi_kazanir(self):
        k = kopru_kur({"varsayilan": "", "cwd": {"~": "kodcu"}})
        self.assertEqual(k.ajan_bul(EV, "", ""), ("kodcu", False))

    def test_ceo_hala_eslenmez(self):
        k = kopru_kur({"varsayilan": "ceo", "cwd": {"/tmp/ceo-klasoru": "ceo"}})
        self.assertEqual(k.ajan_bul("/tmp/ceo-klasoru", "", ""), (None, False))

    def test_ilk_ajan_sanal_degil(self):
        k = kopru_kur({})
        k.ajanlar = {"ceo": {"oda": "ceo"}, **ortak.sanal_ajanlar({}), "gorevci": {"oda": "genel"}}
        self.assertEqual(k.ilk_ajan(), "gorevci")

    def test_hat_etiketi(self):
        self.assertEqual(kopru.hat_etiketi(os.path.join(HAT, "homeos-1114-isik", "a", "b"), HAT), "homeos-1114-isik")

    def test_gercek_ajan_ayni_id_sanali_ezer(self):
        self.assertNotIn("ana-ajan", ortak.sanal_ajanlar({"ana-ajan": {}}))


class SayacTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        for yama in (mock.patch.object(ortak, "DURUM_DIZINI", self.gecici.name),
                     mock.patch.object(token_sayac, "KILIT", os.path.join(self.gecici.name, "token.lock"))):
            yama.start()
            self.addCleanup(yama.stop)
        self.addCleanup(self.gecici.cleanup)

    def test_birlestirme_ve_kosu_satirlari(self):
        t = "2026-11-14"
        u = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100}
        token_sayac.kayit_koy(t, "_kosular", "k1", "gorevci", u)
        token_sayac.kayit_koy(t, "_oturumlar", "s-gorevci", "gorevci", u, etiket="terminal · beyin")
        token_sayac.kayit_koy(t, "_oturumlar", "s-hat-1", "gelistirme-hatti", u, etiket="homeos-1114-a", model="claude-opus-5-5")
        g = token_sayac.kayit_koy(t, "_oturumlar", "s-hat-2", "gelistirme-hatti", u, etiket="homeos-1114-b")
        # aynı koşu yeniden yazılınca çift sayılmaz; etiket/model/ilk korunur
        ilk = token_sayac._oku(t)["_oturumlar"]["s-hat-1"]["ilk"]
        token_sayac.kayit_koy(t, "_oturumlar", "s-hat-1", "gelistirme-hatti", {**u, "output_tokens": 7})
        ozet = token_sayac.gun_ozeti(t)
        self.assertEqual(sum(ozet["gorevci"]["ofis"].values()), 115)
        self.assertEqual(sum(ozet["gorevci"]["terminal"].values()), 115)
        self.assertEqual(sum(ozet["gelistirme-hatti"]["terminal"].values()), 115 + 117)
        self.assertEqual(sum(g["terminal"].values()), 230)
        satirlar = token_sayac.oturum_satirlari(t)
        hat = [s for s in satirlar if s["kaynak"] == "hat"]
        self.assertEqual(len(hat), 2)
        bir = next(s for s in hat if s["etiket"] == "homeos-1114-a")
        self.assertEqual((bir["model"], bir["toplam"], bir["ilk"]), ("claude-opus-5-5", 117, ilk))
        self.assertEqual([s["kaynak"] for s in satirlar if s["ajan"] == "gorevci"], ["terminal"])

    def test_eski_satirlar_en_altta_ve_usd_yok(self):
        t = "2026-11-14"
        u = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        token_sayac.kayit_koy(t, "_oturumlar", "yeni", "gorevci", u, etiket="terminal · beyin", model="opus")
        # 1.0.72 öncesi biçim: ilk/model/etiket yok
        token_sayac._yaz(t, {**token_sayac._oku(t), "_oturumlar": {**token_sayac._oku(t)["_oturumlar"],
                                                                    "eski": {"ajan": "gorevci", "usage": u}}})
        token_sayac.kayit_koy(t, "_oturumlar", "yeni-2", "gelistirme-hatti", u, etiket="homeos-1114-a", model="claude-haiku-5-5")
        satirlar = token_sayac.oturum_satirlari(t)
        self.assertEqual([s["eski"] for s in satirlar], [False, False, True])
        self.assertEqual(satirlar[-1]["oturum"], "eski")
        self.assertIsNone(satirlar[-1]["usd_tahmini"])
        self.assertAlmostEqual(satirlar[0]["usd_tahmini"], (10 * 4 + 5 * 20) / 1e6)

    def test_alt_ajan_tokeni_ebeveyne_eklenir(self):
        t = "2026-11-14"
        u = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100}
        alt = {"input_tokens": 1, "output_tokens": 2, "cache_creation_input_tokens": 3, "cache_read_input_tokens": 4}
        token_sayac.kayit_koy(t, "_oturumlar", "s-ana", "ana-ajan", u, etiket="terminal · ~", model="claude-opus-5-5", alt_usage=alt)
        token_sayac.kayit_koy(t, "_oturumlar", "s-ana", "ana-ajan", u)          # alt_usage verilmezse korunur
        satir = token_sayac.oturum_satirlari(t)[0]
        self.assertEqual((satir["toplam"], satir["alt_toplam"]), (125, 10))
        self.assertEqual(satir["usd_tahmini"], token_sayac.usd_tahmini(token_sayac.topla(u, alt), "claude-opus-5-5"))
        self.assertEqual(sum(token_sayac.gun_ozeti(t)["ana-ajan"]["terminal"].values()), 125)

    def test_tahmini_toplam(self):
        satirlar = [{"kaynak": "hat", "usd_tahmini": .5}, {"kaynak": "hat", "usd_tahmini": None},
                    {"kaynak": "terminal", "usd_tahmini": .25}]
        self.assertEqual(token_sayac.tahmini_toplam(satirlar, 1.0), {"hat": .5, "terminal": .25, "ofis": 1.0, "toplam": 1.75})


class FiyatTesti(unittest.TestCase):
    M = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
         "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}

    def test_onbellek_alanlari_dahil(self):
        # opus: giriş 4 + çıkış 20 + önbellek yazma 4×1,25 + önbellek okuma 0,20
        self.assertAlmostEqual(token_sayac.usd_tahmini(self.M, "claude-opus-5-5"), 29.2)
        self.assertAlmostEqual(token_sayac.usd_tahmini(self.M, "claude-fable-5-2"), 8 + 40 + 10 + .2)
        self.assertAlmostEqual(token_sayac.usd_tahmini(self.M, "claude-haiku-5-5"), .1 + .5 + .125 + .01)

    def test_kisa_ad_ve_surum_eki(self):
        self.assertEqual(token_sayac.usd_tahmini(self.M, "sonnet"), token_sayac.usd_tahmini(self.M, "claude-sonnet-5-5"))
        self.assertEqual(token_sayac.usd_tahmini(self.M, "claude-opus-5-5-20261101"), 29.2)

    def test_bilinmeyen_model_null(self):
        self.assertIsNone(token_sayac.usd_tahmini(self.M, "gpt-9"))
        self.assertIsNone(token_sayac.usd_tahmini(self.M, ""))
        self.assertIsNone(token_sayac.usd_tahmini(self.M, "claude-opus-5-50"))


class HatOrnekTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)
        conf = os.path.join(self.gecici.name, "projeler.conf")
        with open(conf, "w", encoding="utf-8") as f:
            f.write("# yorum\nturnusol=~/development/turnusol\nhomeos=~/development/homeos\najan-ofisi=~/ajan-ofisi\najan=~/x\n")
        for yama in (mock.patch.object(kopru, "PROJELER_DOSYASI", conf),
                     mock.patch.object(kopru, "PROJE_DIZINI", os.path.join(self.gecici.name, "projects"))):
            yama.start()
            self.addCleanup(yama.stop)

    def test_etiketten_proje(self):
        adlar = kopru.proje_adlari()
        self.assertEqual(kopru.hat_projesi("ajan-ofisi-1114-ofiste-her", adlar), "ajan-ofisi")   # uzun ad önce
        self.assertEqual(kopru.hat_projesi("homeos-1114-isik", adlar), "homeos")
        self.assertEqual(kopru.hat_projesi("homeosx-1114", adlar), "hat")
        self.assertEqual(kopru.hat_projesi("baska-1114", adlar), "hat")
        self.assertEqual(kopru.hat_projesi("homeos-1114", []), "hat")

    def test_iki_projeden_paralel_hat_iki_ornek(self):
        k = kopru_kur()
        for pid, ad in ((1, "homeos-1114-isik"), (2, "ajan-ofisi-1114-masa"), (3, "homeos-1114-eski")):
            kayit = k.kayit_kur(pid, {"cwd": os.path.join(HAT, ad), "sessionId": f"s{pid}"}, "gelistirme-hatti", "", "")
            kayit.update(durum="calisiyor", son_satir_ts=100.0 + pid * (-1 if pid == 3 else 1))
            k.oturumlar[pid] = kayit
        ornekler = k.ornekler()
        self.assertEqual([o["id"] for o in ornekler], ["gelistirme-hatti:ajan-ofisi", "gelistirme-hatti:homeos"])
        self.assertEqual(next(o for o in ornekler if o["proje"] == "homeos")["etiket"], "homeos-1114-isik")  # en yeni koşu
        self.assertEqual(k.disari(k.oturumlar[2])["ornek"], "gelistirme-hatti:ajan-ofisi")
        # koşu bitince HAT_BITTI_SN "bitti" kalır, sonra yuva boşalır
        k.hat_bitti(k.oturumlar.pop(2))
        self.assertEqual(next(o for o in k.ornekler() if o["proje"] == "ajan-ofisi")["durum"], "bitti")
        k.biten_hat["gelistirme-hatti:ajan-ofisi"]["bitis_ts"] -= kopru.HAT_BITTI_SN + 1
        self.assertEqual([o["proje"] for o in k.ornekler()], ["homeos"])

    def test_ana_ajan_ornek_degil(self):
        k = kopru_kur()
        kayit = k.kayit_kur(1, {"cwd": EV, "sessionId": "s1"}, "ana-ajan", "", "")
        self.assertNotIn("ornek", k.disari(kayit))

    def test_alt_ajan_tokeni_taranir(self):
        k = kopru_kur()
        kayit = k.kayit_kur(1, {"cwd": os.path.join(HAT, "homeos-1114-a"), "sessionId": "s1"}, "gelistirme-hatti", "", "")
        alt_dizin = os.path.join(kayit["yol"][:-6], "subagents")
        os.makedirs(alt_dizin)
        zaman = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        u = {"input_tokens": 3, "output_tokens": 4, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 6}
        with open(os.path.join(alt_dizin, "agent-x.jsonl"), "w", encoding="utf-8") as f:
            for _ in range(2):    # aynı message.id iki kez: çift sayılmaz
                f.write(json.dumps({"type": "assistant", "isSidechain": True, "timestamp": zaman,
                                    "message": {"id": "m1", "usage": u}}) + "\n")
        k.alt_token_tara(kayit)
        self.assertEqual(kayit["alt_usage"][ortak.bugun()], u)
        self.assertIn(ortak.bugun(), kayit["token_bekleyen"])
        self.assertEqual(k.ornek_disari(kayit, "calisiyor")["alt_token"], 18)


class DemoVeriTesti(unittest.TestCase):
    def test_iki_paralel_hat_ve_alt_ajan(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "on-yuz", "demo-veri.json"), encoding="utf-8") as f:
            so = json.load(f)["sanal_ornek"]
        projeler = {o["proje"] for o in so["ornekler"] if o["durum"] == "calisiyor"}
        self.assertTrue({"homeos", "ajan-ofisi"} <= projeler)
        self.assertTrue(all(o["id"] == "gelistirme-hatti:" + o["proje"] for o in so["ornekler"]))
        self.assertEqual(len(so["alt_ajanlar"]), 1)
        for r in so["oturumlar"]:      # demo ≈USD fiyat tablosuyla tutarlı
            beklenen = token_sayac.usd_tahmini(r["kullanim"], r["model"]) if r["model"] else None
            self.assertEqual(r["usd_tahmini"] is None, beklenen is None)
            if beklenen is not None:
                self.assertAlmostEqual(r["usd_tahmini"], beklenen, places=6)


if __name__ == "__main__":
    unittest.main()
