"""Giriş kapısı ve HTTP işleyici sertleştirmesi: python3 -m unittest test_http_sertlestirme"""
import http.client
import importlib.util
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

_AYAR = tempfile.mkdtemp()
for _ad, _icerik in (("parola", "dogru-parola"), ("oturum-anahtari", "a" * 64)):
    with open(os.path.join(_AYAR, _ad), "w", encoding="utf-8") as _f:
        _f.write(_icerik)
os.environ["OFIS_KAPI_AYAR"] = _AYAR

_spec = importlib.util.spec_from_file_location(
    "kapi_giris", os.path.join(os.path.dirname(os.path.abspath(__file__)), "kapi", "giris.py"))
giris = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(giris)

import ortak  # noqa: E402
import sunucu  # noqa: E402


def _sunucu_ac(sinif):
    s = ThreadingHTTPServer(("127.0.0.1", 0), sinif)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def _ham(port, istek, bekle=3.0):
    """Ham bayt gönder, ilk yanıt satırını döndür (kapanırsa boş)."""
    with socket.create_connection(("127.0.0.1", port), timeout=bekle) as c:
        c.sendall(istek)
        try:
            return c.recv(4096).split(b"\r\n", 1)[0].decode()
        except (TimeoutError, ConnectionError):
            return ""


def _post(uzunluk, ek=""):
    return (f"POST /giris HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-www-form-urlencoded\r\n"
            f"Content-Length: {uzunluk}\r\n{ek}\r\n").encode()


class GirisTesti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = _sunucu_ac(giris.Isleyici)
        cls.port = cls.s.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.s.shutdown()
        cls.s.server_close()

    def setUp(self):
        giris._denemeler.clear()

    def test_bozuk_ve_buyuk_content_length(self):
        t0 = time.time()
        self.assertIn(" 400 ", _ham(self.port, _post("abc")))
        self.assertIn(" 400 ", _ham(self.port, _post("-1")))
        self.assertIn(" 413 ", _ham(self.port, _post(10 * 1024 * 1024)))
        self.assertLess(time.time() - t0, 2)

    def test_yarim_govde_408(self):
        self.assertEqual(giris.Isleyici.timeout, 10)
        with mock.patch.object(giris.Isleyici, "timeout", 1):
            s = _sunucu_ac(giris.Isleyici)
            try:
                t0 = time.time()
                yanit = _ham(s.server_address[1], _post(100) + b"parol", bekle=5)
                self.assertTrue(yanit == "" or " 408 " in yanit, yanit)
                self.assertLess(time.time() - t0, 4)
                # sunucu bloklanmadı: yeni istek hemen yanıtlanır
                self.assertIn(" 404 ", _ham(s.server_address[1], b"GET /yok HTTP/1.1\r\nHost: x\r\n\r\n"))
            finally:
                s.shutdown()
                s.server_close()

    def test_sahte_xff_ilk_degeri_tek_ip_birikir(self):
        with mock.patch.object(giris.time, "sleep"):
            for i in range(giris.DENEME_SINIR):
                yanit = _ham(self.port, _post(12, f"X-Forwarded-For: 10.0.0.{i}, 203.0.113.9\r\n") + b"parola=yanlis")
                self.assertIn(" 401 ", yanit)
            yanit = _ham(self.port, _post(12, "X-Forwarded-For: 10.9.9.9, 203.0.113.9\r\n") + b"parola=yanlis")
        self.assertIn(" 429 ", yanit)

    def test_ip_secimi(self):
        def ip(xff, ortam=None):
            h = giris.Isleyici.__new__(giris.Isleyici)
            h.headers = {"X-Forwarded-For": xff} if xff is not None else {}
            h.client_address = ("127.0.0.1", 1)
            with mock.patch.dict(os.environ, {"OFIS_GUVENILIR_VEKIL": ortam} if ortam else {}):
                return h._ip()
        self.assertEqual(ip("1.1.1.1, 2.2.2.2"), "2.2.2.2")
        self.assertEqual(ip(None), "127.0.0.1")
        self.assertEqual(ip("1.1.1.1, 2.2.2.2, 3.3.3.3", "2"), "2.2.2.2")
        self.assertEqual(ip("1.1.1.1", "2"), "127.0.0.1")


class SunucuTesti(unittest.TestCase):
    def test_govde_zaman_asimi_408(self):
        self.assertEqual(sunucu.Isleyici.timeout, 30)
        with mock.patch.object(sunucu.Isleyici, "timeout", 1):
            s = _sunucu_ac(sunucu.Isleyici)
            try:
                istek = (b"POST /api/gorev HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                         b"Content-Length: 100\r\n\r\n{\"a\"")
                yanit = _ham(s.server_address[1], istek, bekle=5)
                self.assertTrue(yanit == "" or " 408 " in yanit, yanit)
                self.assertIn(" 200 ", _ham(s.server_address[1], b"GET /api/terminaller HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"))
            finally:
                s.shutdown()
                s.server_close()

    def test_canli_akis_zaman_asimindan_uzun_acik_kalir(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(ortak, "OLAYLAR", os.path.join(d, "olaylar.jsonl")), \
                    mock.patch.object(sunucu.Isleyici, "timeout", 1):
                s = _sunucu_ac(sunucu.Isleyici)
                try:
                    c = http.client.HTTPConnection("127.0.0.1", s.server_address[1], timeout=5)
                    c.request("GET", "/api/olaylar")
                    r = c.getresponse()
                    self.assertEqual(r.status, 200)
                    time.sleep(2.5)  # timeout=1'in 2 katından fazla
                    ortak.olay_yaz({"tur": "deneme"})
                    veri = b""
                    t0 = time.time()
                    while b"deneme" not in veri and time.time() - t0 < 3:
                        veri += r.fp.readline()
                    self.assertIn(b"deneme", veri)
                    c.close()
                finally:
                    s.shutdown()
                    s.server_close()


if __name__ == "__main__":
    unittest.main()
