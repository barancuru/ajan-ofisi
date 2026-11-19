"""Limit yüzünden düşen ofis koşusu sıfırlanınca kuyruğa yeniden girer (kullanıcı, 2026-11-15).
Model, ağ, gerçek hesap ya da gerçek ~/beyin/.cache yok: tmux yerine sahte subprocess.run, işaretler geçici dizinde.
python3 -m unittest test_limit_kuyruk"""
import glob
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import kosucu
import ortak
import sunucu
import test_claude_api_yedek as tay
from test_claude_hesaplar import HesapOrtami


class KosucuLimitBekleyenTest(HesapOrtami):
    """kosucu: bütün Pro hesapları ve yedekler limitte → durum/limit-bekleyen/<kosu>.json."""

    def bekleyenler(self):
        return sorted(glob.glob(os.path.join(self.d, "limit-bekleyen", "*.json")))

    def test_hepsi_limitte_dusen_kosu_bekleyene_yazilir(self):
        with mock.patch.dict(os.environ, {"OFIS_YEDEK": "0"}):
            self.kos([tay.limit_sureci(), tay.limit_sureci()])
        dosyalar = self.bekleyenler()
        self.assertEqual(len(dosyalar), 1)
        with open(dosyalar[0], encoding="utf-8") as f:
            k = json.load(f)
        self.assertEqual((k["ajan"], k["limit_deneme"], k["onceki_kosu"]), ("a", 1, "k1"))
        self.assertTrue(k["prompt"].startswith(kosucu.ONCEKI_BASLIK))
        self.assertTrue(k["prompt"].endswith(f"\n{kosucu.ASIL_GOREV}\ngörev"))
        self.assertIn("şu anki durumunu kontrol et", k["prompt"])
        self.assertEqual(k["sonra"], kosucu.limit_acilisi())
        self.assertGreater(k["sonra"], time.time())
        self.assertIn("kuyruğa yeniden girecek", self.bitis["hata"])
        self.assertTrue(any(o.get("tur") == "limit_bekliyor" for o in self.olaylar))

    def test_onceki_adimlar_istemde_sirlar_maskeli(self):
        arac = json.dumps({"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "text", "text": "Notu ekliyorum"},
            {"type": "tool_use", "name": "Write", "input": {"file_path": "/x/notlar/a.md"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "echo " + tay.DOSYA_ANAHTARI}}]}}) + "\n"
        limit = json.dumps({"type": "result", "is_error": True, "subtype": "success",
                            "result": "You've hit your limit · resets 5pm"}) + "\n"
        with mock.patch.dict(os.environ, {"OFIS_YEDEK": "0", "ANTHROPIC_API_KEY": tay.DOSYA_ANAHTARI}):
            self.kos([tay.SahteSurec([arac, limit], kod=1), tay.limit_sureci()])
        with open(self.bekleyenler()[0], encoding="utf-8") as f:
            istem = json.load(f)["prompt"]
        self.assertIn("⚙ Write file_path=/x/notlar/a.md", istem)
        self.assertIn("💬 Notu ekliyorum", istem)
        self.assertNotIn(tay.DOSYA_ANAHTARI, istem)

    def test_ikinci_denemede_baslik_ust_uste_binmez(self):
        log = os.path.join(self.d, "bos.log")
        open(log, "w").close()
        ilk = kosucu.limit_istemi({"prompt": "görev", "kosu_id": "k1"}, log, 1)
        ikinci = kosucu.limit_istemi({"prompt": ilk, "kosu_id": "k2"}, log, 2)
        self.assertEqual(ikinci.count(kosucu.ONCEKI_BASLIK), 1)
        self.assertIn("deneme 2, önceki koşu k2", ikinci)
        self.assertTrue(ikinci.endswith(f"\n{kosucu.ASIL_GOREV}\ngörev"))

    def test_yedek_basarili_ise_bekleyen_yok(self):
        self.kos([tay.limit_sureci(), tay.limit_sureci(), tay.basarili_surec()])
        self.assertIsNone(self.bitis["hata"])
        self.assertEqual(self.bekleyenler(), [])

    def test_limit_disi_hata_bekleyene_yazilmaz(self):
        self.kos([tay.SahteSurec(["Error: syntax error\n"], kod=1)])
        self.assertEqual(self.bekleyenler(), [])

    def test_ucuncu_denemeden_sonra_birakir(self):
        self.assertIsNone(kosucu.limit_bekleyen_yaz({"ajan": "a", "prompt": "p", "kosu_id": "k9",
                                                     "limit_deneme": kosucu.MAKS_LIMIT_DENEME}))
        self.assertEqual(self.bekleyenler(), [])
        self.assertIsNotNone(kosucu.limit_bekleyen_yaz({"ajan": "a", "prompt": "p", "kosu_id": "k8",
                                                        "limit_deneme": kosucu.MAKS_LIMIT_DENEME - 1}))


class SunucuLimitKuyrukTest(unittest.TestCase):
    """sunucu: bekleyen dosyası kuyruğa girer, sıfırlanma saatine ve açık bir Pro hesabına kadar bekler."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.tablo = {"a": {"id": "a", "ad": "A", "kurulu": True, "cwd": self.d.name, "hazir_gorevler": []}}
        self.run = mock.Mock()
        self.limitte = mock.Mock(return_value=False)
        yamalar = [mock.patch.object(ortak, "DURUM_DIZINI", self.d.name),
                   mock.patch.object(ortak, "KOSU_DIZINI", self.d.name),
                   mock.patch.object(ortak, "CIKTI_DIZINI", self.d.name),
                   mock.patch.object(ortak, "OLAYLAR", os.path.join(self.d.name, "olaylar.jsonl")),
                   mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)),
                   mock.patch.object(kosucu, "hepsi_limitte", self.limitte),
                   mock.patch.object(sunucu, "tmux_hazirla", return_value="tmux"),
                   mock.patch.object(sunucu.subprocess, "run", self.run)]
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)

    def bekleyen(self, sonra, ad="k1", **ek):
        os.makedirs(kosucu.limit_bekleyen_dizini(), exist_ok=True)
        with open(os.path.join(kosucu.limit_bekleyen_dizini(), f"{ad}.json"), "w", encoding="utf-8") as f:
            json.dump({"ajan": "a", "etiket": "e", "prompt": "iş", "kaynak": "buton", "ust": None, "model": None,
                       "sonra": int(sonra), "limit_deneme": 1, "onceki_kosu": ad, **ek}, f)

    def test_saatinden_once_baslamaz_sonra_baslar(self):
        self.bekleyen(time.time() + 3600)
        self.assertEqual(sunucu.kuyrugu_isle(), [])
        self.run.assert_not_called()
        self.assertEqual(os.listdir(kosucu.limit_bekleyen_dizini()), [])  # kuyruğa alındı
        kuyruk = sunucu.kuyruk_oku()
        self.assertEqual(len(kuyruk), 1)
        self.assertEqual(kuyruk[0]["limit_deneme"], 1)
        # saat geldi
        kuyruk[0]["sonra"] = int(time.time()) - 1
        sunucu.kuyruk_yaz(kuyruk)
        b = sunucu.kuyrugu_isle()
        self.assertEqual(len(b), 1)
        self.assertFalse(os.path.exists(sunucu.kuyruk_yolu()))
        with open(os.path.join(self.d.name, f"{b[0]['kosu_id']}.arg.json"), encoding="utf-8") as f:
            arg = json.load(f)
        self.assertEqual((arg["prompt"], arg["etiket"], arg["limit_deneme"]), ("iş", "e", 1))

    def test_saat_gecse_de_hepsi_limitteyse_bekler(self):
        self.limitte.return_value = True
        self.bekleyen(time.time() - 5)
        self.assertEqual(sunucu.kuyrugu_isle(), [])
        self.run.assert_not_called()
        self.assertEqual(len(sunucu.kuyruk_oku()), 1)
        self.limitte.return_value = False
        self.assertEqual(len(sunucu.kuyrugu_isle()), 1)

    def test_bekleyen_is_digerlerini_tikamaz(self):
        sunucu.kuyruk_yaz([{"id": "q0123456789", "ajan": "a", "etiket": None, "prompt": "normal", "kaynak": "buton",
                            "ust": None, "zaman": ortak.simdi_iso()}])
        self.bekleyen(time.time() + 3600)
        b = sunucu.kuyrugu_isle()
        self.assertEqual(len(b), 1)  # normal iş başladı, limit bekleyen kaldı
        kalan = sunucu.kuyruk_oku()
        self.assertEqual([k.get("limit_deneme") for k in kalan], [1])

    def test_gecersiz_bekleyen_dusurulur(self):
        self.bekleyen(time.time(), ajan="../kotu")
        self.assertEqual(sunucu.kuyrugu_isle(), [])
        self.assertEqual(sunucu.kuyruk_oku(), [])
        self.assertEqual(os.listdir(kosucu.limit_bekleyen_dizini()), [])

    def test_liste_bekleme_saatini_gosterir_prompt_gostermez(self):
        self.bekleyen(time.time() + 3600)
        sunucu.kuyrugu_isle()
        veri = sunucu.ongorulebilirlik_yaniti()
        q = veri["kuyruk"][0]
        self.assertIn("limit_sonra", q)
        self.assertNotIn("prompt", q)


if __name__ == "__main__":
    unittest.main()
