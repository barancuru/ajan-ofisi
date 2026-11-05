"""Yedek zinciri: Claude Code (Pro) → Claude Code (API anahtarı) → Codex, ve CEO yedeği.
Ağsız birim testleri: subprocess/urlopen taklit edilir, gerçek claude ya da API çağrısı yok."""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
from unittest import mock

import kosucu
import sunucu

SAHTE_ANAHTAR = "sk-ant-TEST-0123456789"
DOSYA_ANAHTARI = "dosyadan-gelen-gizli-deger-42"  # sk-ant- kalıbına uymayan anahtar da maskelenmeli


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


class SahteGirdi:
    def __init__(self):
        self.yazilan = ""

    def write(self, s):
        self.yazilan += s

    def close(self):
        pass


class SahteSurec:
    def __init__(self, satirlar, kod=0):
        self.stdout = iter(satirlar)
        self.stdin = SahteGirdi()
        self.kod = kod

    def wait(self):
        return self.kod

    def kill(self):
        pass


def limit_sureci():
    return SahteSurec([json.dumps({"type": "result", "is_error": True, "subtype": "success",
                                   "result": "You've hit your limit · resets 5pm"}) + "\n"], kod=1)


def basarili_surec(metin="bitti"):
    return SahteSurec([
        json.dumps({"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "text", "text": f"çalışıyorum {DOSYA_ANAHTARI}"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}}) + "\n",
        json.dumps({"type": "result", "is_error": False, "result": metin, "num_turns": 2,
                    "usage": {"input_tokens": 10, "output_tokens": 4}, "total_cost_usd": 0.01}) + "\n"])


class ApiYardimcilariTest(unittest.TestCase):
    def test_anahtar_dosyadan_okunur_ve_gevsek_izin_reddedilir(self):
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "anthropic.env")
            with open(yol, "w") as f:
                f.write('export ANTHROPIC_API_KEY="sk-ant-test-dosya"\n')
            os.chmod(yol, 0o600)
            with mock.patch.dict("os.environ", clear=True), mock.patch.object(kosucu, "API_ANAHTAR_DOSYASI", yol):
                self.assertEqual(kosucu.api_anahtari(), ("sk-ant-test-dosya", None))
                os.chmod(yol, 0o644)
                anahtar, hata = kosucu.api_anahtari()
                self.assertIsNone(anahtar)
                self.assertIn("chmod 600", hata)

    def test_model_ajani_izler_en_fazla_sonnet(self):
        with mock.patch.dict("os.environ", clear=True):
            self.assertEqual(kosucu.api_modeli({"model": "haiku"})[0], "claude-haiku-5-5")
            self.assertEqual(kosucu.api_modeli({"model": "sonnet"}), ("claude-sonnet-5-5", None))
            model, notu = kosucu.api_modeli({"model": "opus"})
            self.assertEqual(model, "claude-sonnet-5-5")
            self.assertIn("opus", notu)
        with mock.patch.dict("os.environ", {"OFIS_YEDEK_MODEL": "claude-opus-5-5"}):
            self.assertEqual(kosucu.api_modeli({"model": "haiku"})[0], "claude-opus-5-5")

    def test_gercek_limit_mesajlari_taninir(self):
        # 2026-11-04 gerçek olay: "weekly" araya girince yedek hiç tetiklenmedi
        for metin in ("You've hit your weekly limit · resets Nov 8, 5pm (Europe/Istanbul)",
                      "You've hit your session limit · resets 11pm", "You've hit your limit", "5-hour limit reached"):
            self.assertTrue(kosucu.LIMIT_DESENI.search(metin), metin)
        self.assertIsNone(kosucu.LIMIT_DESENI.search("kod sınırı: limit parametresi hatalı"))

    def test_429_529_yalniz_hata_kodu_olarak(self):
        for metin in ("API Error: 429 Too Many Requests", "HTTP 529 overloaded_error", "status: 429"):
            self.assertTrue(kosucu.LIMIT_DESENI.search(metin), metin)
        for metin in ("dosyada 5290 satır var", "line 429 of sunucu.py", "1.0.429", "port 15290"):
            self.assertIsNone(kosucu.LIMIT_DESENI.search(metin), metin)

    def test_limit_hatasi_mi(self):
        self.assertTrue(kosucu.limit_hatasi_mi({"is_error": True, "result": "You've hit your limit"}, None))
        self.assertTrue(kosucu.limit_hatasi_mi(None, "claude çıkış kodu 1", "Error: usage limit reached"))
        self.assertFalse(kosucu.limit_hatasi_mi(None, "claude çıkış kodu 1", "syntax error"))
        self.assertFalse(kosucu.limit_hatasi_mi({"is_error": False, "result": "rate limit hakkında rapor"}, None))

    def test_api_komutu_yalniz_model_ve_proc_yasagi_degisir(self):
        ajan = {"id": "a", "model": "opus", "cwd": "/tmp", "izinli_araclar": ["Read"], "tarayici": False, "git_okuma": False, "not_okuma": False}
        komut = kosucu.komut_kur(ajan, ["Bash", "WebFetch"], "/tmp/cikti", 0.5)
        yeni = kosucu.api_komutu(komut, "claude-sonnet-5-5")
        self.assertEqual(yeni[yeni.index("--model") + 1], "claude-sonnet-5-5")
        self.assertIn("Read(/proc/**)", yeni[yeni.index("--disallowedTools"):])
        self.assertEqual(yeni[yeni.index("--max-budget-usd") + 1], "0.50")
        geri = [x for x in yeni if x != "Read(/proc/**)"]
        geri[geri.index("--model") + 1] = "opus"
        self.assertEqual(geri, komut)  # araçlar, izin kuralları, bütçe aynı
        self.assertEqual(komut[komut.index("--model") + 1], "opus")  # ilk komut değişmez
        # --disallowedTools hiç yoksa eklenir
        self.assertEqual(kosucu.api_komutu(["claude", "-p", "--model", "x"], "m")[-2:],
                         ["--disallowedTools", "Read(/proc/**)"])

    def test_maskele_dosyadan_gelen_anahtar(self):
        with mock.patch.dict("os.environ", clear=True):
            env = kosucu.api_ortami(DOSYA_ANAHTARI)
            self.assertNotIn("ANTHROPIC_API_KEY", os.environ)  # kendi ortamımıza konmaz
        self.assertEqual(env["ANTHROPIC_API_KEY"], DOSYA_ANAHTARI)
        self.assertNotIn(DOSYA_ANAHTARI, kosucu.maskele(f"x {DOSYA_ANAHTARI} y"))
        self.assertNotIn("sk-ant-BASKA", kosucu.maskele("sk-ant-BASKA-123"))


class PingTest(unittest.TestCase):
    """api_mesaj_gonder yalnız --ping için kaldı."""

    def setUp(self):
        s = mock.patch.object(kosucu.time, "sleep")
        self.uyku = s.start()
        self.addCleanup(s.stop)

    def test_429_529_402_yeniden_denemez_anahtar_sizmaz(self):
        for kod in (429, 529, 402):
            with mock.patch.object(kosucu.urllib.request, "urlopen", side_effect=http_hata(kod)) as u:
                yanit, hata = kosucu.api_mesaj_gonder(SAHTE_ANAHTAR, "m", "ping", 16)
            self.assertIsNone(yanit)
            self.assertIn(str(kod), hata)
            self.assertNotIn("sk-ant", hata)
            self.assertEqual(u.call_count, 1)

    def test_500_iki_deneme_ustel_bekleme(self):
        with mock.patch.object(kosucu.urllib.request, "urlopen", side_effect=[http_hata(500), http_hata(500)]) as u:
            yanit, _ = kosucu.api_mesaj_gonder(SAHTE_ANAHTAR, "m", "ping", 16)
        self.assertIsNone(yanit)
        self.assertEqual(u.call_count, 2)
        self.uyku.assert_called_once_with(1)

    def test_basarili(self):
        with mock.patch.object(kosucu.urllib.request, "urlopen", return_value=tamam()):
            yanit, hata = kosucu.api_mesaj_gonder(SAHTE_ANAHTAR, "m", "ping", 16)
        self.assertIsNone(hata)
        self.assertEqual(yanit["usage"]["output_tokens"], 3)


class KosuYedekTest(unittest.TestCase):
    """kos() uçtan uca: Popen taklit edilir; kilit, durum, olay ve bitiş yakalanır."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.olaylar = []
        self.bitis = {}
        ortam = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "OFIS_YEDEK",
                                                                  "OFIS_YEDEK_SAGLAYICI", "OFIS_YEDEK_MODEL")}
        yamalar = [
            mock.patch.dict("os.environ", ortam, clear=True),
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

    def kos(self, ajan, surecler, anahtar=(SAHTE_ANAHTAR, None), codex=None):
        ajan = {"id": "a", "ad": "A", "oda": "o", "model": "opus", "cwd": self.d, **ajan}
        arg = os.path.join(self.d, "arg.json")
        with open(arg, "w") as f:
            json.dump({"ajan": "a", "kosu_id": "k1", "prompt": "görev"}, f)
        cx = None
        with contextlib.ExitStack() as yigin:
            yigin.enter_context(mock.patch.object(kosucu.ortak, "ajanlari_yukle", return_value=(
                {"varsayilan_yasak_araclar": ["Bash"]}, {"a": ajan})))
            yigin.enter_context(mock.patch.object(kosucu, "api_anahtari", return_value=anahtar))
            popen = yigin.enter_context(mock.patch.object(kosucu.subprocess, "Popen", side_effect=surecler))
            if codex is not None:
                cx = yigin.enter_context(mock.patch.object(kosucu, "codex_kos", return_value=codex))
            kosucu.kos(arg)
        with open(os.path.join(self.d, "k1.log"), encoding="utf-8") as f:
            self.log = f.read()
        return popen, cx

    def test_limitte_ikinci_kosu_anahtarla_ayni_komutla_baslar(self):
        popen, _ = self.kos({"izinli_araclar": ["Read", "Edit"], "tarayici": False, "git_okuma": False, "not_okuma": False}, [limit_sureci(), basarili_surec()],
                            anahtar=(DOSYA_ANAHTARI, None))
        self.assertEqual(popen.call_count, 2)
        ilk, ikinci = popen.call_args_list
        self.assertNotIn("ANTHROPIC_API_KEY", ilk.kwargs["env"])  # Pro koşusu anahtarsız
        self.assertEqual(ikinci.kwargs["env"]["ANTHROPIC_API_KEY"], DOSYA_ANAHTARI)
        self.assertNotIn("ANTHROPIC_API_KEY", os.environ)
        k1, k2 = ilk.args[0], ikinci.args[0]
        self.assertEqual(k2[k2.index("--model") + 1], "claude-sonnet-5-5")  # opus → en fazla Sonnet
        self.assertIn("Read(/proc/**)", k2)
        self.assertEqual(k2[k2.index("--allowedTools"):k2.index("--disallowedTools")],
                         k1[k1.index("--allowedTools"):k1.index("--disallowedTools")])
        self.assertEqual(k2[k2.index("--max-budget-usd") + 1], k1[k1.index("--max-budget-usd") + 1])
        sonuc = self.bitis["sonuc"]
        self.assertIsNone(self.bitis["hata"])
        self.assertEqual(sonuc["saglayici"], "claude (API yedeği)")
        self.assertTrue(sonuc["result"].startswith("bitti"))
        self.assertIn("[yedek:", sonuc["result"])  # opus → Sonnet notu
        # stream-json ikinci koşuda da işlendi: araç olayı yazıldı, token sayacı çağrıldı
        self.assertTrue(any(o.get("tur") == "ilerledi" and o.get("arac") == "Bash" for o in self.olaylar))
        self.assertTrue(kosucu.token_isle.called)
        # anahtar hiçbir yerde görünmez
        self.assertNotIn(DOSYA_ANAHTARI, self.log)
        self.assertIn("[maskelendi]", self.log)
        self.assertNotIn(DOSYA_ANAHTARI, json.dumps(self.olaylar))
        self.assertNotIn(DOSYA_ANAHTARI, json.dumps(sonuc))

    def test_anahtarsiz_ortamda_codexe_duser(self):
        popen, cx = self.kos({}, [limit_sureci()], anahtar=(None, "ANTHROPIC_API_KEY is not set"),
                             codex=({"result": "c", "saglayici": "codex (yedek)"}, None))
        self.assertEqual(popen.call_count, 1)
        cx.assert_called_once()
        self.assertEqual(self.bitis["sonuc"]["saglayici"], "codex (yedek)")

    def test_sshli_ajan_codexe_dusmez(self):
        ssh = {"ssh": {"anahtar": "~/.ssh/sahte", "birebir_komutlar": ["uptime"]}}
        with mock.patch.object(kosucu.subprocess, "run") as run:
            popen, _ = self.kos(ssh, [limit_sureci()], anahtar=(None, "ANTHROPIC_API_KEY is not set"))
        self.assertEqual(popen.call_count, 1)
        run.assert_not_called()  # codex/bwrap hiç çağrılmadı
        self.assertNotIn("saglayici", self.bitis["sonuc"] or {})
        self.assertIn("SSH", self.bitis["hata"])

    def test_sshli_ajanda_ikinci_claude_code_acik(self):
        ssh = {"ssh": {"anahtar": "~/.ssh/sahte", "birebir_komutlar": ["uptime"]}}
        popen, _ = self.kos(ssh, [limit_sureci(), basarili_surec()])
        self.assertEqual(popen.call_count, 2)
        k1, k2 = (c.args[0] for c in popen.call_args_list)
        self.assertTrue(any("ssh_gecit.py" in x for x in k2))  # SSH geçidi kuralı aynen
        self.assertEqual([x for x in k1 if "ssh" in x.lower()], [x for x in k2 if "ssh" in x.lower()])
        self.assertEqual(self.bitis["sonuc"]["saglayici"], "claude (API yedeği)")

    def test_servis_ortamindaki_anahtar_pro_kosusuna_gecmez(self):
        os.environ["ANTHROPIC_API_KEY"] = SAHTE_ANAHTAR  # EnvironmentFile ile gelmiş gibi (setUp yaması geri alır)
        popen, _ = self.kos({}, [basarili_surec()])
        self.assertEqual(popen.call_count, 1)
        self.assertNotIn("ANTHROPIC_API_KEY", popen.call_args.kwargs["env"])
        self.assertNotIn(SAHTE_ANAHTAR, self.log)

    def test_limit_disi_hatada_yedek_yok(self):
        hatali = SahteSurec(["Error: syntax error\n"], kod=1)
        popen, _ = self.kos({}, [hatali])
        self.assertEqual(popen.call_count, 1)
        self.assertIn("çıkış kodu 1", self.bitis["hata"])

    def test_api_kosusu_da_limitteyse_codexe_gecer_hatalar_maskeli(self):
        popen, cx = self.kos({}, [limit_sureci(), limit_sureci()], codex=(None, "codex yok"))
        self.assertEqual(popen.call_count, 2)
        self.assertNotIn("saglayici", self.bitis["sonuc"] or {})
        self.assertIn("Claude Code API fallback also failed", self.bitis["hata"])
        self.assertIn("codex yok", self.bitis["hata"])
        self.assertNotIn(SAHTE_ANAHTAR, self.bitis["hata"])


class SaglayiciSecimiTest(unittest.TestCase):
    def cagir(self, env, api_donus=("a", None)):
        with mock.patch.dict("os.environ", env), \
                mock.patch.object(kosucu, "codex_kos", return_value=("c", None)) as c, \
                mock.patch.object(kosucu, "claude_code_api_kos", return_value=api_donus) as a:
            if "OFIS_YEDEK_SAGLAYICI" not in env:
                os.environ.pop("OFIS_YEDEK_SAGLAYICI", None)
            r = kosucu.yedek_kos({}, "p", "/tmp", "/tmp", None, komut=["claude"])
        return r, c, a

    def test_zincir_api_basarili_codex_cagrilmaz(self):
        r, c, a = self.cagir({})
        self.assertEqual(r, ("a", None))
        c.assert_not_called()

    def test_zincir_api_anahtari_yok_codexe_duser(self):
        r, c, a = self.cagir({}, (None, "ANTHROPIC_API_KEY is not set"))
        self.assertEqual(r, ("c", None))
        a.assert_called_once()

    def test_codex_tek_saglayici(self):
        r, c, a = self.cagir({"OFIS_YEDEK_SAGLAYICI": "codex"})
        self.assertEqual(r, ("c", None))
        a.assert_not_called()

    def test_claude_api_ikinci_claude_code(self):
        r, c, a = self.cagir({"OFIS_YEDEK_SAGLAYICI": "claude-api"})
        self.assertEqual(r, ("a", None))
        c.assert_not_called()

    def test_yok_ve_gecersiz(self):
        for deger in ("yok", "bilinmeyen"):
            r, c, a = self.cagir({"OFIS_YEDEK_SAGLAYICI": deger})
            self.assertIsNone(r[0])
            c.assert_not_called()
            a.assert_not_called()

    def test_api_yedegi_acik(self):
        for env, beklenen in (({}, True), ({"OFIS_YEDEK_SAGLAYICI": "claude-api"}, True),
                              ({"OFIS_YEDEK_SAGLAYICI": "codex"}, False), ({"OFIS_YEDEK_SAGLAYICI": "yok"}, False),
                              ({"OFIS_YEDEK": "0"}, False)):
            with mock.patch.dict("os.environ", env):
                if "OFIS_YEDEK_SAGLAYICI" not in env:
                    os.environ.pop("OFIS_YEDEK_SAGLAYICI", None)
                if "OFIS_YEDEK" not in env:
                    os.environ.pop("OFIS_YEDEK", None)
                self.assertEqual(kosucu.api_yedegi_acik(), beklenen, env)


def tamamlanan(stdout, kod=0, stderr=""):
    return subprocess.CompletedProcess([], kod, stdout=stdout, stderr=stderr)


CEO_LIMIT = json.dumps({"type": "result", "is_error": True, "result": "You've hit your limit · resets 5pm"})
CEO_TAMAM = json.dumps({"type": "result", "is_error": False, "result": "",
                        "structured_output": {"cevap": "tamam", "atamalar": []}, "total_cost_usd": 0.02})


class CeoYedekTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.olaylar = []
        self.kayitlar = []
        ortam = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "OFIS_YEDEK",
                                                                  "OFIS_YEDEK_SAGLAYICI", "OFIS_YEDEK_MODEL")}
        yamalar = [
            mock.patch.dict("os.environ", ortam, clear=True),
            mock.patch.object(sunucu.ortak, "KOSU_DIZINI", self.d),
            mock.patch.object(sunucu.ortak, "ajanlari_yukle", return_value=({}, {"ceo": {"model": "opus"}})),
            mock.patch.object(sunucu.ortak, "olay_yaz", side_effect=self.olaylar.append),
            mock.patch.object(sunucu, "ceo_ekleri_kaydet", return_value=[]),
            mock.patch.object(sunucu, "ceo_promptu", return_value="istem"),
            mock.patch.object(sunucu, "kurul_yukle", return_value=None),
            mock.patch.object(sunucu, "ceo_kaydi_yaz", side_effect=lambda k: self.kayitlar.append(k) or "x.md"),
        ]
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)

    def calistir(self, cikislar, anahtar=(SAHTE_ANAHTAR, None)):
        with mock.patch.object(sunucu.subprocess, "run", side_effect=cikislar) as run, \
                mock.patch.object(kosucu, "api_anahtari", return_value=anahtar):
            try:
                sonuc = sunucu.ceo_calistir("merhaba", kuru=True)
            except sunucu.IstekHatasi as e:
                sonuc = e
        logs = ""
        for ad in os.listdir(self.d):
            with open(os.path.join(self.d, ad), encoding="utf-8") as f:
                logs += f.read()
        return run, sonuc, logs

    def test_limitte_ayni_komut_anahtarla_bir_kez_daha(self):
        run, sonuc, logs = self.calistir([tamamlanan(CEO_LIMIT, 1), tamamlanan(CEO_TAMAM)])
        self.assertEqual(sonuc["cevap"], "tamam")
        self.assertEqual(run.call_count, 2)
        ilk, ikinci = run.call_args_list
        self.assertNotIn("ANTHROPIC_API_KEY", ilk.kwargs["env"])
        self.assertEqual(ikinci.kwargs["env"]["ANTHROPIC_API_KEY"], SAHTE_ANAHTAR)
        self.assertNotIn("ANTHROPIC_API_KEY", os.environ)
        k1, k2 = ilk.args[0], ikinci.args[0]
        for bayrak in ("--json-schema", "--max-budget-usd", "--tools"):
            self.assertEqual(k2[k2.index(bayrak) + 1], k1[k1.index(bayrak) + 1], bayrak)
        self.assertEqual(k2[k2.index("--model") + 1], "claude-sonnet-5-5")
        self.assertIn("Read(/proc/**)", k2)
        self.assertEqual(self.kayitlar[-1]["saglayici"], "claude (API yedeği)")
        bitti = [o for o in self.olaylar if o.get("tur") == "ceo_bitti"][-1]
        self.assertEqual(bitti["saglayici"], "claude (API yedeği)")
        self.assertNotIn(SAHTE_ANAHTAR, logs + json.dumps(self.olaylar) + json.dumps(self.kayitlar))

    def test_ikinci_kosu_ciktisindaki_anahtar_loga_maskeli_yazilir(self):
        _, _, logs = self.calistir([tamamlanan(CEO_LIMIT, 1), tamamlanan(CEO_TAMAM, stderr=f"debug {SAHTE_ANAHTAR}")])
        self.assertNotIn(SAHTE_ANAHTAR, logs)
        self.assertIn("claude (API yedeği)", logs)

    def test_normal_kosu_tek_cagri(self):
        run, sonuc, _ = self.calistir([tamamlanan(CEO_TAMAM)])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.kayitlar[-1]["saglayici"], "claude")

    def test_anahtarsizsa_tek_cagri_502(self):
        run, sonuc, logs = self.calistir([tamamlanan(CEO_LIMIT, 1)], anahtar=(None, "ANTHROPIC_API_KEY is not set"))
        self.assertEqual(run.call_count, 1)
        self.assertIsInstance(sonuc, sunucu.IstekHatasi)
        self.assertEqual(sonuc.kod, 502)
        self.assertIn("atlandı", logs)

    def test_limit_disi_hatada_yedek_yok(self):
        run, sonuc, _ = self.calistir([tamamlanan("", 1, stderr="boom")])
        self.assertEqual(run.call_count, 1)
        self.assertIsInstance(sonuc, sunucu.IstekHatasi)

    def test_yedek_kapaliysa_tek_cagri(self):
        with mock.patch.dict("os.environ", {"OFIS_YEDEK_SAGLAYICI": "yok"}):
            run, sonuc, _ = self.calistir([tamamlanan(CEO_LIMIT, 1)])
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
