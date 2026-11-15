import json
import os
import tempfile
import unittest

import model_kullanim as mk


def yaz(yol, satirlar):
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "w", encoding="utf-8") as f:
        for s in satirlar:
            f.write(json.dumps(s) + "\n")


def asistan(mid, model, zaman, giris=10, cikis=5, okuma=100):
    return {"type": "assistant", "timestamp": zaman, "message": {"id": mid, "model": model, "role": "assistant",
            "content": [{"type": "text", "text": "GİZLİ METİN"}],
            "usage": {"input_tokens": giris, "output_tokens": cikis, "cache_read_input_tokens": okuma,
                      "cache_creation_input_tokens": 0}}}


class ModelKullanimTest(unittest.TestCase):
    def test_claude_dosya_ici_ve_dosyalar_arasi_tekil(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.jsonl"), os.path.join(d, "b.jsonl")
            z = "2026-11-15T09:00:00Z"
            yaz(a, [asistan("m1", "claude-opus-5-5", z, cikis=2), asistan("m1", "claude-opus-5-5", z, cikis=5),
                    asistan("m2", "<synthetic>", z), {"type": "user", "message": {"content": "x"}}])
            yaz(b, [asistan("m1", "claude-opus-5-5", z, cikis=5), asistan("m3", "claude-haiku-5-5", z)])
            dos = {p: {"kayit": mk.claude_dosyasi(p)} for p in (a, b)}
            self.assertNotIn("GİZLİ", json.dumps(dos))
            o = mk.ozet([], {}, bugun=mk.token_sayac.yerel_tarih(z), dosya_ozeti=dos)
            m = {x["model"]: x["token"] for x in o["donemler"]["bugun"]["modeller"]}
            self.assertEqual(m, {"claude-opus-5-5": 115, "claude-haiku-5-5": 115})

    def test_codex_yanit_basina_cift_sayma_yok(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.jsonl")
            z = "2026-10-31T11:53:32Z"
            kayit = {"type": "token_usage_record", "timestamp": z, "payload": {"response_id": "r1", "usage": {
                "input_tokens": 1000, "cached_input_tokens": 800, "output_tokens": 50, "reasoning_output_tokens": 20,
                "total_tokens": 1050}}}
            yaz(p, [{"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}}, kayit, kayit])
            k = mk.codex_dosyasi(p)
            self.assertEqual(list(k.values()), [[mk.token_sayac.yerel_tarih(z), "gpt-6.1-sol", 200, 50, 0, 800]])
            o = mk.ozet([], {}, bugun=mk.token_sayac.yerel_tarih(z), dosya_ozeti={p: {"kayit": k}})
            d1 = o["donemler"]["bugun"]
            self.assertEqual(d1["token"], 1050)
            self.assertEqual(d1["laboratuvar"][0]["lab"], "OpenAI")
            self.assertEqual(d1["eksik_fiyat"], [])

    def test_dis_fiyat_uzun_baglam_ve_tarih(self):
        u = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 0}
        self.assertEqual(mk.usd(u, "gpt-6.1-sol", "2026-10-31"), 19.0)           # >272K → 4 + 15
        kucuk = {"input_tokens": 100_000, "output_tokens": 0, "cache_read_input_tokens": 100_000}
        self.assertAlmostEqual(mk.usd(kucuk, "gpt-6.1-sol", "2026-10-31"), 0.21)  # 0.2 + 0.01
        self.assertEqual(mk.usd(u, "gemini-3.8-flash-n", "2026-11-01"), 4.5)
        self.assertEqual(mk.usd(u, "gemini-3.8-flash-n", "2027-01-02"), 9.0)
        self.assertIsNone(mk.usd(u, "gemini-3.8-flash-lite", "2026-11-01"))
        self.assertEqual(mk.usd(u, "claude-sonnet-4-6"), 18.0)

    def test_ofis_olayi_olculen_usd_ve_ajan_modeli(self):
        olay = {"tur": "kosu_bitti", "zaman": "2026-11-15T10:00:00", "ajan": "veri", "maliyet_usd": 0.5,
                "kullanim": {"input_tokens": 10, "output_tokens": 10}}
        o = mk.ozet([olay], {"veri": {"id": "veri", "model": "sonnet"}}, bugun="2026-11-15", dosya_ozeti={})
        m = o["donemler"]["30"]["modeller"][0]
        self.assertEqual((m["model"], m["token"], m["usd"]), ("claude-sonnet-5-5", 20, 0.5))
        self.assertEqual(o["roller"][0]["model_ad"], "Sonnet 5.5")
        self.assertEqual(len(o["seri"]), 30)



class SuAnTest(unittest.TestCase):
    def test_alt_ajan_transkripti_su_an_olmaz(self):
        dos = {"/p/ana.jsonl": {"mt": 1, "kayit": {"a": ["2026-11-15", "claude-opus-5-5", 1, 1, 0, 0]}},
               "/p/ana/subagents/agent-x.jsonl": {"mt": 2, "kayit": {"b": ["2026-11-15", "claude-haiku-5-5", 1, 1, 0, 0]}}}
        self.assertEqual(mk.ozet([], {}, bugun="2026-11-15", dosya_ozeti=dos)["su_an"]["model"], "claude-opus-5-5")


def _pb(alan, deger):
    def v(n):
        b = bytearray()
        while True:
            x = n & 0x7F
            n >>= 7
            b.append(x | (0x80 if n else 0))
            if not n:
                return bytes(b)
    if isinstance(deger, int):
        return v(alan << 3) + v(deger)
    deger = deger.encode() if isinstance(deger, str) else deger
    return v(alan << 3 | 2) + v(len(deger)) + deger


class AntigravityTest(unittest.TestCase):
    def test_gen_metadata_adim_zamaniyla(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "x.db")
            c = sqlite3.connect(yol)
            c.execute("create table steps (idx integer primary key, metadata blob)")
            c.execute("create table gen_metadata (idx integer primary key, data blob)")
            ts = 1761900000  # 2025-10-31 civarı
            c.execute("insert into steps values (5, ?)", (_pb(1, _pb(1, ts)),))
            kullanim = _pb(1, 1318) + _pb(2, 100) + _pb(3, 20) + _pb(5, 900)
            kv = _pb(1, "last_step_index") + _pb(2, "5")
            veri = _pb(1, _pb(4, kullanim) + _pb(19, "gemini-3.8-flash-n") + _pb(20, kv))
            c.execute("insert into gen_metadata values (0, ?)", (veri,))
            c.commit()
            c.close()
            k = mk.antigravity_dosyasi(yol)
            gun = mk.datetime.fromtimestamp(ts).date().isoformat()
            self.assertEqual(list(k.values()), [[gun, "gemini-3.8-flash-n", 100, 20, 0, 900]])
            o = mk.ozet([], {}, bugun=gun, dosya_ozeti={yol: {"kayit": k}})
            m = o["donemler"]["bugun"]["modeller"][0]
            self.assertEqual((m["ad"], m["lab"], m["token"]), ("Gemini 3.8 Flash N", "Google", 1020))
            self.assertEqual(o["donemler"]["bugun"]["kaynaklar"], {"antigravity": 1020})
        self.assertEqual(mk.model_adi("claude-sonnet-4-6"), "Sonnet 4.6")


class TumZamanlarTest(unittest.TestCase):
    def test_otuz_gun_disi_tumde_sayilir(self):
        dos = {"/p/a.jsonl": {"kayit": {"eski": ["2026-09-01", "claude-opus-5-5", 1, 1, 0, 0],
                                         "yeni": ["2026-11-15", "claude-opus-5-5", 2, 2, 0, 0],
                                         "gelecek": ["2026-11-16", "claude-opus-5-5", 9, 9, 0, 0]}}}
        o = mk.ozet([], {}, bugun="2026-11-15", dosya_ozeti=dos)
        self.assertEqual((o["donemler"]["30"]["token"], o["donemler"]["tum"]["token"]), (4, 6))
        self.assertEqual(o["ilk_gun"], "2026-09-01")

    def test_silinen_dosya_ve_dusen_ofis_olayi_arsivde_kalir(self):
        with tempfile.TemporaryDirectory() as d:
            eski_onb, eski_kok, eski_cx, eski_ag = mk.ONBELLEK, mk.claude_kokleri, mk.CODEX_DIZINI, mk.ANTIGRAVITY_DIZINI
            try:
                mk.ONBELLEK = os.path.join(d, "onb.json")
                kok = os.path.join(d, "projects")
                mk.claude_kokleri = lambda: [kok]
                mk.CODEX_DIZINI = mk.ANTIGRAVITY_DIZINI = os.path.join(d, "yok")
                mk._durum.update(zaman=0.0, dosyalar=None)
                yol = os.path.join(kok, "x", "s.jsonl")
                yaz(yol, [asistan("m1", "claude-opus-5-5", "2026-11-01T10:00:00Z")])
                self.assertEqual(len(mk.tara(zorla=True)), 1)
                os.remove(yol)
                kalan = mk.tara(zorla=True)
                self.assertTrue(next(iter(kalan.values()))["silindi"])
                olay = {"tur": "kosu_bitti", "kosu_id": "k1", "zaman": "2026-11-01T10:00:00", "ajan": "veri",
                        "kullanim": {"input_tokens": 5}}
                mk.ofis_arsivle(mk.ofis_kayitlari([olay], {}))
                self.assertEqual(len(mk.ofis_arsivle({})), 1)          # olay artık okunmasa da arşivde
                mk._durum.update(zaman=0.0, dosyalar=None)              # sunucu yeniden başladı
                self.assertEqual(len(mk.tara(zorla=True)), 1)
            finally:
                mk.ONBELLEK, mk.claude_kokleri, mk.CODEX_DIZINI, mk.ANTIGRAVITY_DIZINI = eski_onb, eski_kok, eski_cx, eski_ag
                mk._durum.update(zaman=0.0, dosyalar=None)


class RollerTest(unittest.TestCase):
    def test_tum_roller_ve_rol_kullanimi(self):
        ev = os.path.expanduser("~")
        kok = "/x/.claude/projects/"
        ana = kok + mk.re.sub(r"[^A-Za-z0-9]", "-", ev) + "/s.jsonl"
        hat = kok + mk.re.sub(r"[^A-Za-z0-9]", "-", os.path.join(ev, "beyin-is/wt")) + "-homeos-1114-x/s.jsonl"
        dos = {ana: {"kayit": {"a": ["2026-11-15", "claude-opus-5-5", 5, 5, 0, 0]}},
               hat: {"kayit": {"h": ["2026-11-15", "claude-sonnet-5-5", 3, 3, 0, 0]}}}
        olay = {"tur": "kosu_bitti", "kosu_id": "k", "zaman": "2026-11-15T09:00:00", "ajan": "veri",
                "kullanim": {"input_tokens": 7}}
        tablo = {"veri": {"id": "veri", "ad": "Veri", "model": "haiku"}}
        kurul = [{"id": "finans", "ad": "Ayla · Finans", "uzmanlik": "bütçe", "model": "sonnet"}]
        o = mk.ozet([olay], tablo, bugun="2026-11-15", dosya_ozeti=dos, kurul=kurul)
        r = {x["id"]: x for x in o["roller"]}
        self.assertEqual(set(r), {"veri", "ykb", "kurul-finans", "ana-ajan", "gelistirme-hatti", "cayci-kedi"})
        self.assertEqual((r["veri"]["token_30"], r["ana-ajan"]["token_30"], r["gelistirme-hatti"]["token_30"]), (7, 10, 6))
        self.assertEqual(r["ana-ajan"]["model_ad"], "Opus 5.5")
        self.assertEqual(r["ykb"]["model_ad"], "Fable 5.2")
        self.assertEqual((r["cayci-kedi"]["model_ad"], r["cayci-kedi"]["grup"]), ("model yok", "Ofis maskotu"))


if __name__ == "__main__":
    unittest.main()
