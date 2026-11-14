"""Yönetim Kurulu Başkanı + atama başına model. Ağ yok, model yok: python3 -m unittest test_ykb"""
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime
from unittest import mock

import kosucu
import ortak
import sunucu
import ykb
import zamanlayici


def gecerli_plan(n=2):
    return {"ozet": "Kısa özet.", "plan_md": "## Plan\n- adım", "riskler": ["maliyet"],
            "sonraki_gozden_gecirme": "2026-12-01",
            "yonergeler": [{"baslik": f"İş {i}", "hedef": "hedef", "oncelik": 3 - i % 3, "kabul_kriteri": "test geçer",
                            "proje": "ajan-ofisi", "onerilen_model": ("haiku", "sonnet", "opus")[i % 3]}
                           for i in range(n)]}


class Ortam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        k = self.tmp.name
        self.beyin = os.path.join(k, "beyin")
        for d in ("projeler", "gorevler", "sistem", ".cache"):
            os.makedirs(os.path.join(self.beyin, d))
        with open(os.path.join(self.beyin, "projeler", "ajan-ofisi.md"), "w", encoding="utf-8") as f:
            f.write("# Ajan Ofisi\nproje notu")
        yamalar = [mock.patch.dict(os.environ, {"OFIS_BEYIN": self.beyin}),
                   mock.patch.object(ortak, "OLAYLAR", os.path.join(k, "olaylar.jsonl")),
                   mock.patch.object(ortak, "CIKTI_DIZINI", os.path.join(k, "cikti")),
                   mock.patch.object(ortak, "DURUM_DIZINI", os.path.join(k, "durum")),
                   mock.patch.object(ortak, "KOSU_DIZINI", os.path.join(k, "kosular"))]
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)
        for d in (ortak.DURUM_DIZINI, ortak.KOSU_DIZINI, ortak.CIKTI_DIZINI):
            os.makedirs(d, exist_ok=True)
        self.addCleanup(self.tmp.cleanup)
        self.tablo = {"ceo": {"id": "ceo", "model": "opus", "kurulu": True, "oda": "ceo"},
                      "ykb": {"id": "ykb", "model": "claude-fable-5-2", "kurulu": True, "oda": "ykb", "cwd": k,
                              "hazir_gorevler": []},
                      "a": {"id": "a", "ad": "A", "model": "sonnet", "kurulu": True, "oda": "o", "cwd": k,
                            "ne_zaman_metin": "istekte", "aciklama": "test ajanı.",
                            "hazir_gorevler": [{"etiket": "Özet", "prompt": "özetle"}]}}

    def olaylar(self):
        try:
            with open(ortak.OLAYLAR, encoding="utf-8") as f:
                return [json.loads(s) for s in f]
        except FileNotFoundError:
            return []


class SemaTesti(unittest.TestCase):
    def test_ceo_semasi_model_enum(self):
        oge = sunucu.CEO_SEMASI["properties"]["atamalar"]["items"]
        self.assertEqual(oge["properties"]["model"]["enum"], ["haiku", "sonnet", "opus"])
        self.assertNotIn("model", oge["required"])
        self.assertIn("model", sunucu.CEO_SEMASI_KURULLU["properties"]["atamalar"]["items"]["properties"])

    def test_ykb_dogrula(self):
        temiz = ykb.dogrula(gecerli_plan(3))
        self.assertEqual([y["oncelik"] for y in temiz["yonergeler"]], sorted(y["oncelik"] for y in temiz["yonergeler"]))
        with self.assertRaises(ValueError):
            ykb.dogrula(gecerli_plan(7))  # en fazla 6
        for bozuk in ({"oncelik": 4}, {"oncelik": True}, {"onerilen_model": "fable"}, {"baslik": ""}):
            p = gecerli_plan(1)
            p["yonergeler"][0].update(bozuk)
            with self.assertRaises(ValueError):
                ykb.dogrula(p)
        with self.assertRaises(ValueError):
            ykb.dogrula({"ozet": "x"})
        self.assertEqual(ykb.SEMA["properties"]["yonergeler"]["maxItems"], 6)


class ModelBeyazListeTesti(unittest.TestCase):
    def test_model_sec(self):
        ajan = {"model": "sonnet"}
        self.assertEqual(kosucu.model_sec(ajan, None), ("sonnet", None))
        self.assertEqual(kosucu.model_sec(ajan, "haiku"), ("haiku", None))
        self.assertEqual(kosucu.model_sec(ajan, "opus"), ("opus", None))
        for kotu in ("fable", "claude-fable-5-2", "claude-opus-5-5", "OPUS", "", 3):
            self.assertEqual(kosucu.model_sec(ajan, kotu)[0], "sonnet", kotu)
            self.assertIsNotNone(kosucu.model_sec(ajan, kotu)[1])

    def test_opus_butce_en_fazla_iki_kat(self):
        self.assertEqual(kosucu.secilen_butce("sonnet", "opus", 0.5), 1.0)
        self.assertEqual(kosucu.secilen_butce("opus", "opus", 0.5), 0.5)
        self.assertEqual(kosucu.secilen_butce("sonnet", "haiku", 0.5), 0.5)

    def test_ceo_dogrula_gecersiz_modeli_duser(self):
        tablo = {"a": {"id": "a", "kurulu": True}}
        _, gecerli, _ = sunucu.ceo_dogrula({"cevap": "x", "atamalar": [
            {"ajan": "a", "prompt": "p", "model": "fable"}]}, tablo, "m")
        self.assertNotIn("model", gecerli[0])


class YalnizKullaniciTesti(Ortam):
    def test_gorev_baslat_ykb_reddeder(self):
        with mock.patch.object(ortak, "ajanlari_yukle", return_value=({}, self.tablo)), \
                mock.patch.object(sunucu, "tmux_hazirla", side_effect=AssertionError("koşu açıldı")):
            with self.assertRaises(sunucu.IstekHatasi) as e:
                sunucu.gorev_baslat("ykb", prompt="plan yap", kaynak="ceo")
            self.assertEqual(e.exception.kod, 404)

    def test_zamanlayici_ykb_reddeder(self):
        with self.assertRaises(ValueError):
            zamanlayici.is_dogrula({"ajan": "ykb", "prompt": "plan", "cron": "0 9 * * 1"}, self.tablo)

    def test_ceo_ykb_atayamaz(self):
        _, gecerli, reddedilen = sunucu.ceo_dogrula({"cevap": "x", "atamalar": [{"ajan": "ykb", "prompt": "p"}]},
                                                    self.tablo, "m")
        self.assertEqual(gecerli, [])
        self.assertEqual(reddedilen[0]["neden"], "bilinmeyen ajan")
        self.assertNotIn("- ykb", sunucu.ceo_promptu("m", self.tablo))


class TekKosuTesti(Ortam):
    def test_ikinci_istek_409(self):
        dur = threading.Event()
        with mock.patch.object(ykb, "kos", side_effect=lambda *a: dur.wait(5)):
            ilk = ykb.baslat("plan yap", None, True, mock.Mock(), self.tablo)
            self.assertTrue(ykb.calisiyor())
            with self.assertRaises(ykb.YkbHatasi) as e:
                ykb.baslat("plan yap", None, True, mock.Mock(), self.tablo)
            self.assertEqual(e.exception.kod, 409)
            dur.set()
        for _ in range(100):
            if not ykb.calisiyor():
                break
            threading.Event().wait(0.02)
        self.assertFalse(ykb.calisiyor())
        self.assertIn("-ykb-", ilk["kosu_id"])
        self.assertEqual([o["tur"] for o in self.olaylar()], ["ykb_basladi"])  # ikinci istek koşu açmadı

    def test_bilinmeyen_proje(self):
        with self.assertRaises(ykb.YkbHatasi):
            ykb.baslat("x", "../etc", True, mock.Mock(), self.tablo)
        self.assertFalse(ykb.calisiyor())


class LimitTesti(Ortam):
    LIMIT = ({"is_error": True, "result": "usage limit reached"}, "claude çıkış kodu 1", "")

    def test_limitte_fable_api_yedegi_yok(self):
        cagri = []
        with mock.patch.object(ykb, "claude_calistir", side_effect=lambda k, *a: cagri.append(k) or self.LIMIT), \
                mock.patch.dict(os.environ, {"OFIS_YKB_API_YEDEK": ""}), \
                mock.patch.object(kosucu, "api_anahtari", return_value=("sk-test", None)):
            sonuc, hata, model, _ = ykb.model_cagir(ykb.tanim(self.tablo), "istem")
        self.assertIsNone(sonuc)
        self.assertIn("limit", hata)
        self.assertEqual(len(cagri), 1)

    def test_opus_yedegi_acikken_yalniz_opus(self):
        cagri = []
        with mock.patch.object(ykb, "claude_calistir", side_effect=lambda k, *a: cagri.append(k) or self.LIMIT), \
                mock.patch.dict(os.environ, {"OFIS_YKB_API_YEDEK": "opus"}), \
                mock.patch.object(kosucu, "api_anahtari", return_value=("sk-test", None)):
            ykb.model_cagir(ykb.tanim(self.tablo), "istem")
        self.assertEqual(len(cagri), 2)
        ikinci = cagri[1][cagri[1].index("--model") + 1]
        self.assertEqual(ikinci, "claude-opus-5-5")
        self.assertNotIn("fable", ikinci)


class DagitimTesti(Ortam):
    def kos(self, once_goster, cikti=None):
        dagit = mock.Mock()
        sonuc = cikti or {"subtype": "success", "structured_output": gecerli_plan(2), "total_cost_usd": 0.5,
                          "usage": {"input_tokens": 10, "output_tokens": 5}}
        with mock.patch.object(ykb, "claude_calistir", return_value=(sonuc, None, "")):
            kayit = ykb.kos("2026-11-14-101500-ykb-abcd", "plan", None, "Yol haritası", ykb.tanim(self.tablo),
                            once_goster, dagit)
        return kayit, dagit

    def test_once_goster_acikken_ceo_cagrilmaz(self):
        kayit, dagit = self.kos(True)
        self.assertEqual(kayit["durum"], "basarili")
        dagit.assert_not_called()
        bitti = [o for o in self.olaylar() if o["tur"] == "ykb_bitti"][-1]
        self.assertEqual(bitti["yonerge_sayisi"], 2)
        self.assertNotIn("plan_md", json.dumps(bitti))  # olaya plan metni yazılmaz

    def test_once_goster_kapaliyken_hemen_dagitilir(self):
        _, dagit = self.kos(False)
        dagit.assert_called_once_with("2026-11-14-101500-ykb-abcd", None)

    def test_refusal_plan_yazmaz(self):
        kayit, dagit = self.kos(False, {"subtype": "success", "stop_reason": "refusal", "result": ""})
        self.assertEqual(kayit["durum"], "hata")
        self.assertIn("refusal", kayit["hata"])
        self.assertFalse(os.path.isdir(os.path.join(self.beyin, "planlar")))
        dagit.assert_not_called()

    def test_ceo_metni_secilen(self):
        kayit, _ = self.kos(True)
        metin = ykb.ceo_metni(kayit, [1])
        self.assertTrue(metin.startswith("YKB yönergeleri"))
        self.assertIn(kayit["yonergeler"][1]["baslik"], metin)
        self.assertNotIn(kayit["yonergeler"][0]["baslik"] + ":", metin)
        with self.assertRaises(ykb.YkbHatasi):
            ykb.ceo_metni(kayit, [])

    def test_dagit_ceo_istegi_ve_cift_dagitim(self):
        kayit, _ = self.kos(True)
        with mock.patch.object(sunucu, "ceo_calistir", return_value={"kosu_id": "c1", "atamalar": [], "baslatilan": []}) as c:
            sunucu.ykb_dagit(kayit["kosu_id"], None)
            c.assert_called_once()
            self.assertIn("YKB yönergeleri", c.call_args[0][0])
            with self.assertRaises(ykb.YkbHatasi) as e:
                sunucu.ykb_dagit(kayit["kosu_id"], None)
            self.assertEqual(e.exception.kod, 409)


class PlanDosyasiTesti(Ortam):
    def test_ad_ve_on_bilgi(self):
        plan = ykb.dogrula(gecerli_plan(1))
        yol = ykb.plan_yaz(plan, "k-1", 'Yol/haritası: "Q1"', "ajan-ofisi", simdi=datetime(2026, 11, 14, 9, 5))
        self.assertEqual(os.path.dirname(yol), os.path.join(self.beyin, "planlar"))
        self.assertEqual(os.path.basename(yol), "2026-11-14 0905 Yol haritası Q1.md")
        with open(yol, encoding="utf-8") as f:
            metin = f.read()
        self.assertTrue(metin.startswith("---\ntur: plan\nkaynak: ykb\nkosu_id: k-1\n"))
        self.assertIn("[[ajan-ofisi]]", metin)
        ikinci = ykb.plan_yaz(plan, "k-2", 'Yol/haritası: "Q1"', None, simdi=datetime(2026, 11, 14, 9, 5))
        self.assertNotEqual(yol, ikinci)  # üzerine yazmaz


class BaglamTesti(Ortam):
    def test_boyut_siniri(self):
        for i in range(30):
            with open(os.path.join(self.beyin, "projeler", f"p{i}.md"), "w", encoding="utf-8") as f:
                f.write("x" * 9000)
            with open(os.path.join(self.beyin, "gorevler", f"g{i}.md"), "w", encoding="utf-8") as f:
                f.write(f"---\ndurum: {'bitti' if i % 2 else 'calisiyor'}\nproje: p{i}\n---\n# g")
        with open(os.path.join(self.beyin, "sistem", "kayit.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(f"satır {i}" for i in range(500)))
        ozet = ykb.baglam_ozeti()
        self.assertLessEqual(len(ozet), ykb.MAKS_BAGLAM)
        self.assertIn("g0 · durum: calisiyor", ozet)
        self.assertNotIn("g1 ·", ozet)  # kapalı görev yok
        self.assertIn("satır 499", ozet)
        self.assertNotIn("satır 459\n", ozet)  # yalnız son 40 satır
        self.assertLessEqual(len(ykb.baglam_ozeti(sinir=5000)), 5000)


if __name__ == "__main__":
    unittest.main()
