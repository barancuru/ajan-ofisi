"""Diyagramlar sekmesi uçları: python3 -m unittest test_diyagram"""
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


def _yaz(kok, yol, metin=""):
    tam = os.path.join(kok, yol)
    os.makedirs(os.path.dirname(tam), exist_ok=True)
    with open(tam, "wb") as f:
        f.write(metin if isinstance(metin, bytes) else metin.encode("utf-8"))
    return tam


class DiyagramTesti(unittest.TestCase):
    def setUp(self):
        gecici = tempfile.TemporaryDirectory()
        self.addCleanup(gecici.cleanup)
        self.dis = gecici.name
        self.d = os.path.join(gecici.name, "diyagram")
        os.makedirs(self.d)
        for p in (mock.patch.object(sunucu, "DIYAGRAM_KOK", self.d),
                  mock.patch.object(ortak, "ajanlari_yukle", return_value=({"ajanlar": []}, {}))):
            p.start()
            self.addCleanup(p.stop)

    def _liste(self):
        g = sunucu.diyagramlar_yaniti()
        self.assertEqual([p["proje"] for p in g["projeler"]], list(sunucu.GRAF_PROJELER))
        return {p["proje"]: p["diyagramlar"] for p in g["projeler"]}

    def test_yok_klasor_bos_liste(self):
        os.rmdir(self.d)
        self.assertTrue(all(v == [] for v in self._liste().values()))

    def test_baslik_ve_tur_spec_ten(self):
        _yaz(self.d, "homeos/mimari.html", "<html></html>")
        _yaz(self.d, "homeos/mimari.json", json.dumps({"title": "HomeOS mimarisi", "type": "architecture"}))
        _yaz(self.d, "homeos/akis.html", "<html></html>")
        _yaz(self.d, "homeos/akis.json", "{bozuk")
        _yaz(self.d, "homeos/yalniz.html", "<html></html>")
        _yaz(self.d, "homeos/notlar.json", "{}")  # .html yoksa listelenmez
        d = {x["ad"]: x for x in self._liste()["homeos"]}
        self.assertEqual(set(d), {"mimari", "akis", "yalniz"})
        self.assertEqual((d["mimari"]["baslik"], d["mimari"]["tur"]), ("HomeOS mimarisi", "architecture"))
        self.assertEqual((d["akis"]["baslik"], d["akis"]["tur"]), ("akis", ""))
        self.assertEqual((d["yalniz"]["baslik"], d["yalniz"]["tur"]), ("yalniz", ""))
        self.assertTrue(d["mimari"]["guncelleme"])
        self.assertEqual(set(d["mimari"]), {"ad", "baslik", "tur", "guncelleme"})

    def test_baslik_maskelenir(self):
        _yaz(self.d, "turnusol/m.html", "x")
        _yaz(self.d, "turnusol/m.json", json.dumps({"title": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"}))
        baslik = self._liste()["turnusol"][0]["baslik"]
        self.assertNotIn("abc", baslik)

    def test_gecersiz_gizli_symlink_kok_disi_buyuk_atlanir(self):
        _yaz(self.d, "ajan-ofisi/iyi.html", "x")
        _yaz(self.d, "ajan-ofisi/.gizli.html", "x")
        _yaz(self.d, "ajan-ofisi/Buyuk.html", "x")
        _yaz(self.d, "ajan-ofisi/alt_cizgi.html", "x")
        disari = _yaz(self.dis, "disari.html", "sır")
        os.symlink(disari, os.path.join(self.d, "ajan-ofisi", "bag.html"))
        _yaz(self.d, "ajan-ofisi/kocaman.html", b"x" * (sunucu.DIYAGRAM_MAKS + 1))
        self.assertEqual([x["ad"] for x in self._liste()["ajan-ofisi"]], ["iyi"])

    def test_proje_klasoru_symlink_kok_disi(self):
        _yaz(self.dis, "baska/m.html", "x")
        os.symlink(os.path.join(self.dis, "baska"), os.path.join(self.d, "homeos"))
        self.assertEqual(self._liste()["homeos"], [])
        self.assertIsNone(sunucu._diyagram_yolu("homeos", "m", ".html"))

    def test_spec_symlink_okunmaz(self):
        _yaz(self.d, "homeos/m.html", "x")
        spec = _yaz(self.dis, "s.json", json.dumps({"title": "dışarıdan"}))
        os.symlink(spec, os.path.join(self.d, "homeos", "m.json"))
        self.assertEqual(self._liste()["homeos"][0]["baslik"], "m")

    # ---------- HTTP ----------
    def _sunucu(self):
        sv = ThreadingHTTPServer(("127.0.0.1", 0), sunucu.Isleyici)
        threading.Thread(target=sv.serve_forever, daemon=True).start()
        self.addCleanup(sv.server_close)
        self.addCleanup(sv.shutdown)
        ac = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
        return f"http://127.0.0.1:{sv.server_address[1]}", ac

    def _kod(self, ac, url):
        try:
            with ac(url) as y:
                return y.status
        except urllib.error.HTTPError as h:
            return h.code

    def test_http_liste_ve_goster(self):
        _yaz(self.d, "homeos/mimari.html", "<html><body>diyagram</body></html>")
        kok, ac = self._sunucu()
        with ac(kok + "/api/diyagramlar") as y:
            self.assertEqual(y.status, 200)
            veri = json.loads(y.read())
        self.assertEqual(veri["projeler"][1]["diyagramlar"][0]["ad"], "mimari")
        with ac(kok + "/api/diyagramlar/goster?proje=homeos&ad=mimari") as y:
            self.assertEqual(y.status, 200)
            self.assertIn(b"diyagram", y.read())
            self.assertEqual(y.headers["Content-Security-Policy"], sunucu.DIYAGRAM_CSP)
            self.assertTrue(y.headers["Content-Security-Policy"].startswith("sandbox allow-scripts;"))
            self.assertIn("connect-src 'none'", y.headers["Content-Security-Policy"])
            self.assertEqual(y.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(y.headers["Cache-Control"], "no-cache")
            self.assertTrue(y.headers["Content-Type"].startswith("text/html"))

    def test_http_gecersiz_ve_bilinmeyen_404(self):
        _yaz(self.d, "homeos/mimari.html", "x")
        _yaz(self.d, "homeos/.gizli.html", "x")
        _yaz(self.d, "homeos/Buyuk.html", "x")
        _yaz(self.dis, "x.html", "sır")
        kok, ac = self._sunucu()
        for sorgu in ("proje=homeos&ad=..%2Fx", "proje=homeos&ad=../x", "proje=homeos&ad=.gizli",
                      "proje=homeos&ad=Buyuk", "proje=homeos&ad=yok", "proje=homeos&ad=",
                      "proje=bilinmeyen&ad=mimari", "proje=..&ad=x", "ad=mimari", "proje=homeos&ad=mimari%0A"):
            self.assertEqual(self._kod(ac, kok + "/api/diyagramlar/goster?" + sorgu), 404, sorgu)

    def test_http_yabanci_host_403(self):
        kok, ac = self._sunucu()
        kotu = urllib.request.Request(kok + "/api/diyagramlar", headers={"Host": "kotu.example"})
        with self.assertRaises(urllib.error.HTTPError) as h:
            ac(kotu)
        self.assertEqual(h.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
