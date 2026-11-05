"""Not grafı ucu: python3 -m unittest test_not_grafi"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import ortak
import sunucu

ALANLAR = {"dugumler", "kenarlar", "okunamayan", "kirik", "kesildi", "guncelleme"}


def _yaz(kok, yol, metin=""):
    tam = os.path.join(kok, yol)
    os.makedirs(os.path.dirname(tam), exist_ok=True)
    with open(tam, "wb") as f:
        f.write(metin if isinstance(metin, bytes) else metin.encode("utf-8"))
    return tam


class NotGrafiTesti(unittest.TestCase):
    def setUp(self):
        gecici = tempfile.TemporaryDirectory()
        self.addCleanup(gecici.cleanup)
        self.d = os.path.join(gecici.name, "beyin")
        os.makedirs(self.d)
        self.dis = gecici.name  # BEYIN dışı
        for p in (mock.patch.object(sunucu, "BEYIN", self.d),
                  mock.patch.object(ortak, "ajanlari_yukle", return_value={"ajanlar": []})):
            p.start()
            self.addCleanup(p.stop)

    def _graf(self):
        g = sunucu.not_grafi_yaniti()
        self.assertEqual(set(g), ALANLAR)
        return g

    def _yollar(self, g):
        return {n["yol"] for n in g["dugumler"]}

    def _kenarlar(self, g):
        ad = {n["id"]: n["yol"] for n in g["dugumler"]}
        return {(ad[k["kaynak"]], ad[k["hedef"]]) for k in g["kenarlar"]}

    def test_wikilink_bicimleri(self):
        _yaz(self.d, "notlar/A.md", "[[B]] [[C|takma ad]] [[D#bölüm]] [[ e | x ]] [[F\\|tablo]] [[G.md]]")
        for ad in "BCDEFG":
            _yaz(self.d, f"notlar/{ad}.md")
        g = self._graf()
        self.assertEqual(self._kenarlar(g), {("notlar/A.md", f"notlar/{ad}.md") for ad in "BCDEFG"})
        self.assertEqual(g["kirik"], 0)
        a = next(n for n in g["dugumler"] if n["baslik"] == "A")
        self.assertEqual((a["grup"], a["derece"]), ("notlar", 6))
        self.assertEqual(next(n for n in g["dugumler"] if n["baslik"] == "E")["derece"], 1)

    def test_kirik_tekrarli_ve_kendine_kenar(self):
        _yaz(self.d, "notlar/A.md", "[[B]] [[b]] [[B|x]] [[A]] [[Yok]] [[Yok2]] [[#yalnız bölüm]]")
        _yaz(self.d, "notlar/B.md", "[[A]]")
        g = self._graf()
        self.assertEqual(self._kenarlar(g), {("notlar/A.md", "notlar/B.md"), ("notlar/B.md", "notlar/A.md")})
        self.assertEqual(g["kirik"], 2)
        self.assertTrue(all(n["derece"] == 2 for n in g["dugumler"]))

    def test_gorsel_gomme_yok_sayilir(self):
        _yaz(self.d, "notlar/A.md", "![[foto.png]] [[belge.PDF]] ![[B]]")
        _yaz(self.d, "notlar/B.md")
        g = self._graf()
        self.assertEqual(self._kenarlar(g), {("notlar/A.md", "notlar/B.md")})
        self.assertEqual(g["kirik"], 0)

    def test_ayni_ad_notlar_oncelikli_ve_iki_dugum(self):
        _yaz(self.d, "projeler/x/Ortak.md")
        _yaz(self.d, "notlar/alt/Ortak.md")
        _yaz(self.d, "projeler/Bag.md", "[[Ortak]] [[projeler/x/Ortak]]")
        g = self._graf()
        self.assertEqual(len(g["dugumler"]), 3)
        self.assertEqual(self._kenarlar(g), {("projeler/Bag.md", "notlar/alt/Ortak.md"),
                                             ("projeler/Bag.md", "projeler/x/Ortak.md")})

    def test_yalniz_notlar_ve_projeler_taranir(self):
        _yaz(self.d, "notlar/A.md", "[[Gorev]]")
        _yaz(self.d, "projeler/p/P.md")
        _yaz(self.d, "gelen/G.md")
        _yaz(self.d, "gorevler/Gorev.md")
        _yaz(self.d, "kok.md")
        _yaz(self.d, "notlar/metin.txt", "[[A]]")
        g = self._graf()
        self.assertEqual(self._yollar(g), {"notlar/A.md", "projeler/p/P.md"})
        self.assertEqual(g["kirik"], 1)
        self.assertEqual({n["grup"] for n in g["dugumler"]}, {"notlar", "projeler"})

    def test_gizli_sir_ve_atlanan_adlar(self):
        _yaz(self.d, "notlar/A.md")
        for yol in (".gizli.md", ".obsidian/ayar.md", ".env.md", "secrets.md", "api-token.md", "uretim.env.md",
                    "SSH anahtarı.md", "secrets/acik.md", "node_modules/m.md"):
            _yaz(self.d, "notlar/" + yol, "[[A]]")
        _yaz(self.d, "notlar/.env", "GIZLI=1")
        with mock.patch.object(sunucu, "open", wraps=open, create=True) as acilan:
            g = self._graf()
        self.assertEqual(self._yollar(g), {"notlar/A.md"})
        self.assertEqual(g["kenarlar"], [])
        acilanlar = [c.args[0] for c in acilan.call_args_list]
        self.assertEqual(acilanlar, [os.path.join(os.path.realpath(self.d), "notlar", "A.md")])

    def test_sir_olmayan_benzer_adlar_kalir(self):
        _yaz(self.d, "notlar/Tokenizer notu.md")
        _yaz(self.d, "notlar/Environment.md")
        self.assertEqual(len(self._graf()["dugumler"]), 2)

    def test_symlink_kok_disina_cikamaz(self):
        _yaz(self.d, "notlar/A.md", "[[Dis]] [[Ic]]")
        _yaz(self.d, "notlar/Hedef.md")
        dis_not = _yaz(self.dis, "dis/Dis.md", "[[A]]")
        os.symlink(dis_not, os.path.join(self.d, "notlar", "Dis.md"))
        os.symlink(os.path.dirname(dis_not), os.path.join(self.d, "notlar", "dis-klasor"))
        os.symlink(os.path.join(self.d, "notlar", "Hedef.md"), os.path.join(self.d, "notlar", "Ic.md"))
        os.symlink(os.path.dirname(dis_not), os.path.join(self.d, "projeler"))
        g = self._graf()
        self.assertEqual(self._yollar(g), {"notlar/A.md", "notlar/Hedef.md"})
        self.assertEqual(g["kirik"], 2)

    def test_gecersiz_utf8_listelenir_digerleri_doner(self):
        _yaz(self.d, "notlar/Bozuk.md", b"\xff\xfe [[A]] \x80")
        _yaz(self.d, "notlar/A.md", "[[Bozuk]]")
        g = self._graf()
        self.assertEqual(g["okunamayan"], ["notlar/Bozuk.md"])
        self.assertEqual(self._kenarlar(g), {("notlar/A.md", "notlar/Bozuk.md")})

    def test_izin_hatasi_cokertmez(self):
        _yaz(self.d, "notlar/A.md")
        with mock.patch.object(sunucu, "open", side_effect=PermissionError, create=True):
            g = self._graf()
        self.assertEqual(g["okunamayan"], ["notlar/A.md"])

    def test_utf8_olmayan_dosya_adi_json_bozmaz(self):
        _yaz(self.d, "notlar/A.md")
        kok = os.fsencode(os.path.join(self.d, "notlar"))
        try:
            with open(os.path.join(kok, b"k\xf6t\xfc.md"), "wb"):
                pass
        except OSError:
            self.skipTest("dosya sistemi bu adı kabul etmiyor")
        g = self._graf()
        self.assertEqual(self._yollar(g), {"notlar/A.md"})
        self.assertEqual(len(g["okunamayan"]), 1)
        json.dumps(g, ensure_ascii=False).encode("utf-8")

    def test_okuma_tavani_cok_baytli_harfi_bolunce_okunamaz_saymaz(self):
        with mock.patch.object(sunucu, "DIZIN_MAKS_OKU", 10):
            _yaz(self.d, "notlar/Uzun.md", "[[A]]  " + "ş" * 50 + " [[Sonra]]")  # 7 + 2 = 9: 10. bayt harfin ortası
            _yaz(self.d, "notlar/A.md")
            g = self._graf()
        self.assertEqual(g["okunamayan"], [])
        self.assertEqual(g["kirik"], 0)  # tavandan sonraki [[Sonra]] okunmadı
        self.assertEqual(self._kenarlar(g), {("notlar/Uzun.md", "notlar/A.md")})

    def test_dugum_ve_okunamayan_tavani(self):
        for i in range(5):
            _yaz(self.d, f"notlar/n{i}.md", b"\xff")
        with mock.patch.object(sunucu, "NOT_GRAFI_MAKS_OKUNAMAYAN", 2):
            g = self._graf()
        self.assertEqual(len(g["okunamayan"]), 2)
        self.assertEqual(len(g["dugumler"]), 5)
        self.assertFalse(g["kesildi"])
        with mock.patch.object(sunucu, "NOT_GRAFI_MAKS_DUGUM", 3):
            g = self._graf()
        self.assertEqual(len(g["dugumler"]), 3)
        self.assertTrue(g["kesildi"])

    def test_tam_tavanda_kesildi_yanlis(self):
        for i in range(3):
            _yaz(self.d, f"notlar/n{i}.md")
        with mock.patch.object(sunucu, "NOT_GRAFI_MAKS_DUGUM", 3):
            self.assertFalse(self._graf()["kesildi"])

    def test_bos_ve_yok_dizin(self):
        g = self._graf()
        self.assertEqual((g["dugumler"], g["kenarlar"], g["okunamayan"], g["kirik"], g["kesildi"]),
                         ([], [], [], 0, False))
        os.makedirs(os.path.join(self.d, "notlar"))
        self.assertEqual(self._graf()["dugumler"], [])
        with mock.patch.object(sunucu, "BEYIN", os.path.join(self.d, "yok")):
            self.assertEqual(self._graf()["dugumler"], [])

    def test_maskele_uygulanir(self):
        ajanlar = {"ajanlar": [{"ssh": {"anahtar": "/k/gizli_kimlik"}}]}
        _yaz(self.d, "notlar/gizli_kimlik notu.md", "[[gizli_kimlik notu]]")
        _yaz(self.d, "notlar/Bozuk gizli_kimlik.md", b"\xff")
        with mock.patch.object(ortak, "ajanlari_yukle", return_value=ajanlar):
            g = self._graf()
        metin = json.dumps(g, ensure_ascii=False)
        self.assertNotIn("gizli_kimlik", metin)
        self.assertIn("[anahtar-yolu]", metin)
        self.assertEqual(len(g["dugumler"]), 2)
        self.assertEqual(len(g["okunamayan"]), 1)

    def test_bozuk_yapilandirma_cokertmez(self):
        _yaz(self.d, "notlar/A.md")
        with mock.patch.object(ortak, "ajanlari_yukle", side_effect=ortak.YapilandirmaHatasi("x")):
            self.assertEqual(len(self._graf()["dugumler"]), 1)

    def test_yanit_not_icerigi_tasimaz(self):
        _yaz(self.d, "notlar/A.md", "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n[[B]] icerik-ozel-metin")
        _yaz(self.d, "notlar/B.md")
        self.assertNotIn("icerik-ozel-metin", json.dumps(self._graf(), ensure_ascii=False))

    def test_http_uc(self):
        _yaz(self.d, "notlar/A.md", "[[B]]")
        _yaz(self.d, "notlar/B.md")
        sv = ThreadingHTTPServer(("127.0.0.1", 0), sunucu.Isleyici)
        threading.Thread(target=sv.serve_forever, daemon=True).start()
        self.addCleanup(sv.server_close)
        self.addCleanup(sv.shutdown)
        url = f"http://127.0.0.1:{sv.server_address[1]}/api/not-grafi"
        ac = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
        with ac(url) as y:
            self.assertEqual(y.status, 200)
            g = json.load(y)
        self.assertEqual(set(g), ALANLAR)
        self.assertEqual(len(g["kenarlar"]), 1)
        kotu = urllib.request.Request(url, headers={"Host": "kotu.example"})
        with self.assertRaises(urllib.error.HTTPError) as h:
            ac(kotu)
        self.assertEqual(h.exception.code, 403)
        h.exception.close()
        yaz = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as h:
            ac(yaz)
        self.assertGreaterEqual(h.exception.code, 400)
        h.exception.close()


if __name__ == "__main__":
    unittest.main()
