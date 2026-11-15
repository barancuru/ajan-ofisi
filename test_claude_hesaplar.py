"""Two Claude Pro accounts: same order and markers as beyin/bin/calistir, then the API → Codex chain.
No network, no real account, no real ~/beyin/.cache: Popen/claude_calistir are faked, markers live in a temp dir.
python3 -m unittest test_claude_hesaplar"""
import contextlib
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import kosucu

kosucu.CODEX_KAPALI = "/nonexistent/codex-yedek-kapali"  # hermetic, as in test_claude_api_yedek
import kopru  # noqa: E402
import test_claude_api_yedek as tay  # noqa: E402  (helpers only; its TestCase classes are not re-run here)
import ykb  # noqa: E402
from test_kopru_sanal import kopru_kur  # noqa: E402

ANAHTAR = "sk-ant-HESAP-TEST-987654"


class HesapOrtami(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cache = os.path.join(self.d, "cache")
        self.hesap2 = os.path.join(self.d, "ofis-kapi", "claude-hesap2")
        os.makedirs(self.hesap2)
        with open(os.path.join(self.hesap2, ".credentials.json"), "w") as f:
            f.write("{}")
        self.olaylar, self.bitis = [], {}
        ortam = {k: v for k, v in os.environ.items() if k not in ("OFIS_YEDEK", "OFIS_YEDEK_SAGLAYICI",
                                                                  "OFIS_YEDEK_MODEL", "CLAUDE_CONFIG_DIR")}
        ortam["ANTHROPIC_API_KEY"] = ANAHTAR  # as if the service got it via EnvironmentFile
        yamalar = [
            mock.patch.dict("os.environ", ortam, clear=True),
            mock.patch.object(kosucu, "CLAUDE_HESAPLARI", ["-", self.hesap2]),
            mock.patch.object(kosucu, "LIMIT_DIZINI", self.cache),
            mock.patch.object(kosucu.ortak, "KOSU_DIZINI", self.d),
            mock.patch.object(kosucu.ortak, "CIKTI_DIZINI", self.d),
            mock.patch.object(kosucu.ortak, "HAFIZA_DIZINI", self.d),
            mock.patch.object(kosucu.ortak, "durum_yaz"),
            mock.patch.object(kosucu.ortak, "olay_yaz", side_effect=self.olaylar.append),
            mock.patch.object(kosucu.ortak, "maske_yollari", return_value=[]),
            mock.patch.object(kosucu, "kilit_al", side_effect=lambda: os.open(os.devnull, os.O_RDONLY)),
            mock.patch.object(kosucu, "token_isle"),
            mock.patch.object(kosucu, "token_kesinle"),
            mock.patch.object(kosucu, "bitir", side_effect=self.bitti),
        ]
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)

    def bitti(self, ajan, baglam, sonuc, hata, *a, **k):
        self.bitis.update(sonuc=sonuc, hata=hata)

    def isaret(self, ad):
        return os.path.join(self.cache, ad)

    def isaretle(self, ad, zaman=None):
        os.makedirs(self.cache, exist_ok=True)
        with open(self.isaret(ad), "w") as f:
            f.write(str(int(zaman if zaman is not None else time.time() + kosucu.CLAUDE_LIMIT_SN)))

    def kos(self, surecler, anahtar=(ANAHTAR, None), codex=None):
        ajan = {"id": "a", "ad": "A", "oda": "o", "model": "sonnet", "cwd": self.d}
        arg = os.path.join(self.d, "arg.json")
        with open(arg, "w") as f:
            json.dump({"ajan": "a", "kosu_id": "k1", "prompt": "görev"}, f)
        with contextlib.ExitStack() as yigin:
            yigin.enter_context(mock.patch.object(kosucu.ortak, "ajanlari_yukle", return_value=(
                {"varsayilan_yasak_araclar": ["Bash"]}, {"a": ajan})))
            yigin.enter_context(mock.patch.object(kosucu, "api_anahtari", return_value=anahtar))
            popen = yigin.enter_context(mock.patch.object(kosucu.subprocess, "Popen", side_effect=surecler))
            if codex is not None:
                yigin.enter_context(mock.patch.object(kosucu, "codex_kos", return_value=codex))
            kosucu.kos(arg)
        with open(os.path.join(self.d, "k1.log"), encoding="utf-8") as f:
            self.log = f.read()
        self.envler = [c.kwargs["env"] for c in popen.call_args_list]
        return popen

    def pro_envleri_anahtarsiz(self, n):
        for env in self.envler[:n]:
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertNotIn(ANAHTAR, json.dumps(env))


class KosucuHesapTest(HesapOrtami):
    def test_limit_yok_yalniz_hesap1(self):
        popen = self.kos([tay.basarili_surec()])
        self.assertEqual(popen.call_count, 1)
        self.assertNotIn("CLAUDE_CONFIG_DIR", self.envler[0])
        self.pro_envleri_anahtarsiz(1)
        self.assertNotIn("saglayici", self.bitis["sonuc"])  # hesap1: label unchanged
        self.assertFalse(os.path.exists(self.cache))

    def test_hesap1_limitte_hesap2_isaret_yazilir(self):
        popen = self.kos([tay.limit_sureci(), tay.basarili_surec()])
        self.assertEqual(popen.call_count, 2)
        self.assertNotIn("CLAUDE_CONFIG_DIR", self.envler[0])
        self.assertEqual(self.envler[1]["CLAUDE_CONFIG_DIR"], self.hesap2)
        self.pro_envleri_anahtarsiz(2)
        with open(self.isaret("claude-limit")) as f:
            self.assertGreater(int(f.read()), time.time())  # reset time, not the write time
        self.assertFalse(os.path.exists(self.isaret("claude-limit-claude-hesap2")))
        self.assertIsNone(self.bitis["hata"])
        self.assertEqual(self.bitis["sonuc"]["saglayici"], "claude (hesap2)")
        self.assertIn("--- claude (hesap2) ---", self.log)
        self.assertNotIn(self.hesap2, self.log)  # no account path in the log
        self.assertNotIn(self.hesap2, json.dumps(self.olaylar))

    def test_iki_hesap_limitte_api_yedegi(self):
        popen = self.kos([tay.limit_sureci(), tay.limit_sureci(), tay.basarili_surec()])
        self.assertEqual(popen.call_count, 3)
        self.pro_envleri_anahtarsiz(2)
        self.assertEqual(self.envler[1]["CLAUDE_CONFIG_DIR"], self.hesap2)
        self.assertEqual(self.envler[2]["ANTHROPIC_API_KEY"], ANAHTAR)
        self.assertTrue(os.path.exists(self.isaret("claude-limit")))
        self.assertTrue(os.path.exists(self.isaret("claude-limit-claude-hesap2")))
        self.assertEqual(self.bitis["sonuc"]["saglayici"], kosucu.API_SAGLAYICI)

    def test_isaretli_hesap1_dogrudan_hesap2(self):
        self.isaretle("claude-limit")
        popen = self.kos([tay.basarili_surec()])
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(self.envler[0]["CLAUDE_CONFIG_DIR"], self.hesap2)
        self.pro_envleri_anahtarsiz(1)
        self.assertEqual(self.bitis["sonuc"]["saglayici"], "claude (hesap2)")

    def test_suresi_dolmus_isaret_hesap1_ile_baslar(self):
        self.isaretle("claude-limit", time.time() - 5)
        self.kos([tay.basarili_surec()])
        self.assertNotIn("CLAUDE_CONFIG_DIR", self.envler[0])

    def test_hepsi_isaretliyse_hepsi_sirayla_denenir(self):
        self.isaretle("claude-limit")
        self.isaretle("claude-limit-claude-hesap2")
        self.assertEqual(kosucu.hesap_sirasi(), ["-", self.hesap2])
        popen = self.kos([tay.basarili_surec()])
        self.assertEqual(popen.call_count, 1)
        self.assertNotIn("CLAUDE_CONFIG_DIR", self.envler[0])

    def test_oturumu_olmayan_hesap2_atlanir(self):
        os.remove(os.path.join(self.hesap2, ".credentials.json"))
        popen = self.kos([tay.limit_sureci(), tay.basarili_surec()])
        self.assertEqual(popen.call_count, 2)  # hesap1 → API (no hesap2 attempt)
        self.assertNotIn("CLAUDE_CONFIG_DIR", self.envler[1])
        self.assertEqual(self.envler[1]["ANTHROPIC_API_KEY"], ANAHTAR)
        self.assertFalse(os.path.exists(self.isaret("claude-limit-claude-hesap2")))

    def test_limit_disi_hata_baska_hesapta_denenmez(self):
        popen = self.kos([tay.SahteSurec(["Error: syntax error\n"], kod=1)])
        self.assertEqual(popen.call_count, 1)
        self.assertIn("çıkış kodu 1", self.bitis["hata"])
        self.assertFalse(os.path.exists(self.cache))

    def test_etiket_yol_icermez(self):
        self.assertEqual(kosucu.hesap_saglayici("-"), "claude")
        self.assertEqual(kosucu.hesap_saglayici(self.hesap2), "claude (hesap2)")
        self.assertEqual(kosucu.hesap_isaret("-"), self.isaret("claude-limit"))
        self.assertEqual(kosucu.hesap_isaret(self.hesap2), self.isaret("claude-limit-claude-hesap2"))


class YkbHesapTest(HesapOrtami):
    LIMIT = ({"is_error": True, "result": "usage limit reached"}, "claude çıkış kodu 1", "")
    TAMAM = ({"is_error": False, "result": "{}"}, None, "")

    def cagir(self, yanitlar):
        envler = []

        def sahte(komut, prompt, zaman, env):
            envler.append(env)
            return yanitlar.pop(0)

        t = {"model": "claude-fable-5-2", "zaman_asimi_dk": 1}
        with mock.patch.object(ykb, "komut_kur", return_value=["claude", "-p", "--model", "m"]), \
                mock.patch.object(ykb, "claude_calistir", side_effect=sahte), \
                mock.patch.dict(os.environ, {"OFIS_YKB_API_YEDEK": ""}):
            return ykb.model_cagir(t, "istem"), envler

    def test_hesap1_limitte_hesap2(self):
        (sonuc, hata, _, saglayici), envler = self.cagir([self.LIMIT, self.TAMAM])
        self.assertIsNone(hata)
        self.assertEqual(saglayici, "claude (hesap2)")
        self.assertEqual(len(envler), 2)
        self.assertEqual(envler[1]["CLAUDE_CONFIG_DIR"], self.hesap2)
        for env in envler:
            self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertTrue(os.path.exists(self.isaret("claude-limit")))

    def test_iki_hesap_limitte_mevcut_yedek_kurali(self):
        (sonuc, hata, _, saglayici), envler = self.cagir([self.LIMIT, self.LIMIT])
        self.assertIsNone(sonuc)
        self.assertIn("limit", hata)
        self.assertEqual(len(envler), 2)


class KopruHesapTest(HesapOrtami):
    def test_hesap2_transkripti_okunur(self):
        projeler = os.path.join(self.d, "projects")
        with mock.patch.object(kopru, "PROJE_DIZINI", projeler):
            self.assertEqual(kopru.proje_dizinleri(), [projeler, os.path.join(self.hesap2, "projects")])
            k = kopru_kur()
            cwd = os.path.expanduser("~")
            klasor = os.path.join(self.hesap2, "projects", kopru.proje_klasoru(cwd))
            os.makedirs(klasor)
            with open(os.path.join(klasor, "s1.jsonl"), "w") as f:
                f.write("")
            kayit = k.kayit_kur(1, {"cwd": cwd, "sessionId": "s1"}, "ana-ajan", "", "")
            self.assertEqual(kayit["yol"], os.path.join(klasor, "s1.jsonl"))
            self.assertNotIn(self.hesap2, json.dumps(k.disari(kayit)))
            # no transcript anywhere: default root as before
            kayit = k.kayit_kur(2, {"cwd": cwd, "sessionId": "s2"}, "ana-ajan", "", "")
            self.assertTrue(kayit["yol"].startswith(projeler))


if __name__ == "__main__":
    unittest.main()
