"""Claude API yedeği: ağsız birim testleri (urlopen taklit edilir, gerçek istek yok)."""
import io
import json
import unittest
import urllib.error
from unittest import mock

import kosucu

SAHTE_ANAHTAR = "sk-ant-TEST-0123456789"


class Yanit:
    def __init__(self, veri):
        self.veri = json.dumps(veri).encode("utf-8")

    def read(self):
        return self.veri

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_hata(kod, tip="x_error"):
    return urllib.error.HTTPError(kosucu.API_URL, kod, "err", {}, io.BytesIO(
        json.dumps({"error": {"type": tip, "message": f"bad key {SAHTE_ANAHTAR}"}}).encode()))


def tamam(metin="merhaba", stop="end_turn"):
    return Yanit({"content": [{"type": "text", "text": metin}], "stop_reason": stop,
                  "usage": {"input_tokens": 5, "output_tokens": 3}})


class ClaudeApiYedekTest(unittest.TestCase):
    def setUp(self):
        env = {"ANTHROPIC_API_KEY": SAHTE_ANAHTAR}
        p = mock.patch.dict("os.environ", env)
        p.start()
        self.addCleanup(p.stop)
        s = mock.patch.object(kosucu.time, "sleep")
        self.uyku = s.start()
        self.addCleanup(s.stop)
        self.log = io.StringIO()

    def kos(self, ajan=None):
        return kosucu.claude_api_kos(ajan or {"id": "a"}, "gorev", self.log)

    def test_anahtar_yoksa_acik_hata_istek_yok(self):
        with mock.patch.dict("os.environ", clear=True), \
                mock.patch.object(kosucu.urllib.request, "urlopen") as u:
            sonuc, hata = self.kos()
        self.assertIsNone(sonuc)
        self.assertIn("ANTHROPIC_API_KEY", hata)
        u.assert_not_called()

    def test_basarili_yanit(self):
        with mock.patch.object(kosucu.urllib.request, "urlopen", return_value=tamam()) as u:
            sonuc, hata = self.kos()
        self.assertIsNone(hata)
        self.assertEqual(sonuc["result"], "merhaba")
        self.assertEqual(sonuc["saglayici"], "claude-api (yedek)")
        self.assertEqual(sonuc["usage"]["output_tokens"], 3)
        istek = u.call_args[0][0]
        self.assertEqual(u.call_args[1]["timeout"], 120)
        govde = json.loads(istek.data)
        self.assertEqual(govde["model"], "claude-sonnet-5-5")
        self.assertEqual(govde["max_tokens"], 4096)
        self.assertNotIn("tools", govde)
        self.assertNotIn("stream", govde)

    def test_429_529_402_yeniden_denemez(self):
        for kod in (429, 529, 402):
            with mock.patch.object(kosucu.urllib.request, "urlopen", side_effect=http_hata(kod)) as u:
                sonuc, hata = self.kos()
            self.assertIsNone(sonuc)
            self.assertIn(str(kod), hata)
            self.assertEqual(u.call_count, 1)

    def test_500_iki_deneme_ustel_bekleme(self):
        with mock.patch.object(kosucu.urllib.request, "urlopen", side_effect=[http_hata(500), http_hata(500)]) as u:
            sonuc, hata = self.kos()
        self.assertIsNone(sonuc)
        self.assertEqual(u.call_count, 2)
        self.uyku.assert_called_once_with(1)

    def test_baglanti_hatasi_iki_deneme_sonra_basari(self):
        with mock.patch.object(kosucu.urllib.request, "urlopen",
                               side_effect=[urllib.error.URLError("down"), tamam("ok")]) as u:
            sonuc, hata = self.kos()
        self.assertEqual(u.call_count, 2)
        self.assertEqual(sonuc["result"], "ok")

    def test_zaman_asimi(self):
        with mock.patch.object(kosucu.urllib.request, "urlopen", side_effect=TimeoutError("t")) as u:
            sonuc, hata = self.kos()
        self.assertIsNone(sonuc)
        self.assertIn("connection error", hata)
        self.assertEqual(u.call_count, 2)

    def test_max_tokens_env_ve_ust_sinir(self):
        for env, beklenen in (("100", 100), ("999999", kosucu.API_MAKS_TOKEN_UST), ("abc", 4096)):
            with mock.patch.dict("os.environ", {"OFIS_YEDEK_MAX_TOKEN": env}), \
                    mock.patch.object(kosucu.urllib.request, "urlopen", return_value=tamam()) as u:
                self.kos()
            self.assertEqual(json.loads(u.call_args[0][0].data)["max_tokens"], beklenen)

    def test_model_env(self):
        with mock.patch.dict("os.environ", {"OFIS_YEDEK_MODEL": "claude-haiku-5-5"}), \
                mock.patch.object(kosucu.urllib.request, "urlopen", return_value=tamam()) as u:
            self.kos()
        self.assertEqual(json.loads(u.call_args[0][0].data)["model"], "claude-haiku-5-5")

    def test_kirpma_isaretlenir(self):
        with mock.patch.dict("os.environ", {"OFIS_YEDEK_MAX_TOKEN": "50"}), \
                mock.patch.object(kosucu.urllib.request, "urlopen", return_value=tamam("kisa", "max_tokens")):
            sonuc, hata = self.kos()
        self.assertIn("kesildi", sonuc["result"])
        self.assertIn("max_tokens=50", sonuc["result"])

    def test_anahtar_sizmaz(self):
        sizdir = tamam(f"yanit {SAHTE_ANAHTAR}")
        with mock.patch.object(kosucu.urllib.request, "urlopen", return_value=sizdir):
            sonuc, _ = self.kos()
        self.assertNotIn(SAHTE_ANAHTAR, sonuc["result"])
        self.assertNotIn(SAHTE_ANAHTAR, self.log.getvalue())
        with mock.patch.object(kosucu.urllib.request, "urlopen", side_effect=http_hata(401)):
            _, hata = self.kos()
        self.assertNotIn(SAHTE_ANAHTAR, hata)
        self.assertNotIn("sk-ant", hata)
        self.assertNotIn(SAHTE_ANAHTAR, kosucu.maskele(f"x {SAHTE_ANAHTAR} y"))
        self.assertNotIn("sk-ant-BASKA", kosucu.maskele("sk-ant-BASKA-123"))

    def test_ssh_li_ya_da_aracli_ajanda_kapali(self):
        for ajan in ({"ssh": {"anahtar": "k"}}, {"izinli_araclar": ["Read"]}):
            with mock.patch.object(kosucu.urllib.request, "urlopen") as u:
                sonuc, hata = self.kos(ajan)
            self.assertIsNone(sonuc)
            self.assertIn("disabled", hata)
            u.assert_not_called()

    def test_eslesmeyen_hatada_yedek_tetiklenmez(self):
        self.assertIsNone(kosucu.LIMIT_DESENI.search("claude çıkış kodu 1 syntax error"))
        self.assertTrue(kosucu.LIMIT_DESENI.search("You've hit your limit"))


class SaglayiciSecimiTest(unittest.TestCase):
    def cagir(self, env):
        with mock.patch.dict("os.environ", env, clear=False), \
                mock.patch.object(kosucu, "codex_kos", return_value=("c", None)) as c, \
                mock.patch.object(kosucu, "claude_api_kos", return_value=("a", None)) as a:
            r = kosucu.yedek_kos({}, "p", "/tmp", "/tmp", None)
        return r, c, a

    def test_varsayilan_codex(self):
        with mock.patch.dict("os.environ"):
            import os
            os.environ.pop("OFIS_YEDEK_SAGLAYICI", None)
            r, c, a = self.cagir({})
        self.assertEqual(r, ("c", None))
        a.assert_not_called()

    def test_claude_api(self):
        r, c, a = self.cagir({"OFIS_YEDEK_SAGLAYICI": "claude-api"})
        self.assertEqual(r, ("a", None))
        c.assert_not_called()

    def test_yok_ve_gecersiz(self):
        for deger in ("yok", "bilinmeyen"):
            r, c, a = self.cagir({"OFIS_YEDEK_SAGLAYICI": deger})
            self.assertIsNone(r[0])
            c.assert_not_called()
            a.assert_not_called()


if __name__ == "__main__":
    unittest.main()
