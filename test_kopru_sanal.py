"""Sanal gözlem ajanları (ana-ajan, gelistirme-hatti): köprü eşlemesi ve token sayacı. python3 -m unittest test_kopru_sanal"""
import os
import tempfile
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


if __name__ == "__main__":
    unittest.main()
