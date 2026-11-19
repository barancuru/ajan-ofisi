"""Workflow V1 entegrasyonu: gerçek sunucu.py (gorev_baslat, kuyruk, hat görev dosyaları, HTTP uçları), kosucu.py
(başlangıç/sonuç işaretleri, limit yeniden kuyruğu) ve akis_ofis.OfisOrtami. tmux, systemctl, model ve gerçek
~/beyin yok: hepsi geçici dizinde ve sahte subprocess ile.  python3 -m unittest test_akis_entegrasyon"""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import subprocess

import akis_db
import akis_motor
import akis_ofis
import kosucu
import ortak
import sunucu


class OfisTabani(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.d, True)
        self.proje = os.path.join(self.d, "proje")
        os.makedirs(self.proje)
        dizinler = {}
        for ad in ("durum", "kosular", "cikti", "gorevler", "hafiza"):
            dizinler[ad] = os.path.join(self.d, ad)
            os.makedirs(dizinler[ad])
        self.dizin = dizinler
        ajanlar = os.path.join(self.d, "ajanlar.json")
        with open(ajanlar, "w") as f:
            json.dump({"ajanlar": [
                {"id": "ceo", "ad": "CEO", "oda": "ceo", "cwd": self.proje, "model": "sonnet"},
                {"id": "arastirmaci", "ad": "Araştırmacı", "oda": "arastirma", "cwd": self.proje, "model": "sonnet",
                 "butce_usd": 1.0, "izinli_araclar": ["Read"]},
                {"id": "gunlukcu", "ad": "Günlükçü", "oda": "yazi", "cwd": self.proje, "model": "haiku"},
                {"id": "akis-okuyucu", "ad": "Akış Okuyucu", "oda": "arastirma", "cwd": self.proje, "model": "sonnet",
                 "butce_usd": 1.5, "izinli_araclar": ["Read", "Glob", "Grep"], "tarayici": False}]}, f)
        yamalar = [mock.patch.object(ortak, "AJANLAR_DOSYASI", ajanlar),
                   mock.patch.object(ortak, "DURUM_DIZINI", dizinler["durum"]),
                   mock.patch.object(ortak, "KOSU_DIZINI", dizinler["kosular"]),
                   mock.patch.object(ortak, "CIKTI_DIZINI", dizinler["cikti"]),
                   mock.patch.object(ortak, "OLAYLAR", os.path.join(self.d, "olaylar.jsonl")),
                   mock.patch.object(sunucu, "GOREV_DIZINI", dizinler["gorevler"]),
                   mock.patch.object(sunucu, "kosucuyu_durt", lambda: None),
                   mock.patch.object(sunucu, "_AKIS_ALARM_SUREC", None),
                   mock.patch.object(sunucu, "tmux_hazirla", lambda: "tmux"),
                   mock.patch.object(sunucu.subprocess, "run", self.sahte_tmux)]
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)
        self.tmux = []
        self.ortam = akis_ofis.OfisOrtami(sunucu)

    GERCEK_RUN = subprocess.run

    def sahte_tmux(self, argv, **k):
        if argv and argv[0] != "tmux":   # sunucu.subprocess global modül: kapı komutları gerçek çalışır
            return OfisTabani.GERCEK_RUN(argv, **k)
        self.tmux.append(argv)
        return mock.Mock(returncode=0)

    def arglar(self):
        sonuc = []
        for ad in sorted(os.listdir(self.dizin["kosular"])):
            if ad.endswith(".arg.json"):
                with open(os.path.join(self.dizin["kosular"], ad)) as f:
                    sonuc.append(json.load(f))
        return sonuc

    def mesgul(self, ajan):
        ortak.durum_yaz(ajan, {"durum": "calisiyor", "pid": os.getpid(), "kosu_id": "x"})


REF = "ak-0123456789ab"


class KuyrukGecisTest(OfisTabani):
    def test_gorev_baslat_akis_ref_arg_dosyasinda(self):
        r = sunucu.gorev_baslat("arastirmaci", prompt="p", kaynak="akis", havuz=True, akis_ref=REF)
        self.assertTrue(r["kosu_id"])
        self.assertEqual(self.arglar()[0]["akis_ref"], REF)
        self.assertEqual(self.arglar()[0]["kaynak"], "akis")
        self.assertTrue(self.ortam.arg_dosyasi_var(REF))

    def test_gecersiz_akis_ref_dusurulur(self):
        sunucu.gorev_baslat("arastirmaci", prompt="p", havuz=True, akis_ref="../../x")
        self.assertNotIn("akis_ref", self.arglar()[0])

    def test_mesgul_ajan_kuyruga_ref_ile_girer_ve_tasinir(self):
        self.ucusta = mock.patch.object(sunucu, "akis_ref_durumu", lambda ref: "gecerli")
        self.ucusta.start()
        self.addCleanup(self.ucusta.stop)
        self.mesgul("arastirmaci")
        r = self.ortam.ajan_baslat("arastirmaci", "p", None, REF)
        self.assertTrue(r["kuyrukta"])
        self.assertTrue(self.ortam.kuyrukta_mi(REF))
        self.assertEqual(self.tmux, [])
        ortak.durum_yaz("arastirmaci", {"durum": "bitti"})
        sunucu.kuyrugu_isle()
        self.assertEqual(self.arglar()[0]["akis_ref"], REF)   # kuyruktan çıkan koşu aynı denemeyi taşır
        self.assertFalse(self.ortam.kuyrukta_mi(REF))

    def test_kuyruktan_cikar_yalniz_o_deneme(self):
        self.mesgul("arastirmaci")
        self.ortam.ajan_baslat("arastirmaci", "p", None, REF)
        sunucu.gorev_baslat("arastirmaci", prompt="elle", havuz=True)
        self.assertTrue(self.ortam.kuyruktan_cikar(REF))
        kalan = sunucu.kuyruk_oku()
        self.assertEqual([k["prompt"] for k in kalan], ["elle"])

    def test_eski_kuyruk_kaydi_gecerli(self):
        """Regresyon: akis_ref'siz eski kayıtlar ve eski kaynaklar aynen geçer."""
        k = {"id": "q0123456789", "ajan": "arastirmaci", "kaynak": "tekrar", "prompt": "p", "etiket": None, "ust": None}
        self.assertEqual(sunucu._kuyruk_dogrula([k]), [k])
        self.assertEqual(sunucu._kuyruk_dogrula([{**k, "akis_ref": "kotu"}]), [])

    def test_terk_edilen_deneme_kuyruktan_kosmaz(self):
        """İkinci inceleme: iptal/terk edilmiş denemenin kuyruk ya da limit-bekleyen kaydı koşturulmaz."""
        self.mesgul("arastirmaci")
        self.ortam.ajan_baslat("arastirmaci", "p", None, REF)
        arg = {"kosu_id": "2026-11-18-1-arastirmaci", "ajan": "arastirmaci", "prompt": "p", "kaynak": "akis",
               "akis_ref": "ak-0123456789ac"}
        self.assertTrue(kosucu.limit_bekleyen_yaz(arg))
        ortak.durum_yaz("arastirmaci", {"durum": "bitti"})
        m = akis_motor.Motor(akis_db.Depo(os.path.join(self.dizin["durum"], "akis.db")), self.ortam)
        with mock.patch.object(sunucu, "_MOTOR", m), mock.patch.object(kosucu, "hepsi_limitte", lambda: False):
            baslayan = sunucu.kuyrugu_isle()
        self.assertEqual(baslayan, [])
        self.assertEqual(self.tmux, [])
        self.assertFalse(os.path.exists(sunucu.kuyruk_yolu()))
        self.assertEqual(os.listdir(kosucu.limit_bekleyen_dizini()), [])
        with open(ortak.OLAYLAR) as f:
            olaylar = [json.loads(s) for s in f]
        self.assertFalse([o for o in olaylar if o["tur"] == "hata"])       # bildirimci Telegram'a yollamaz
        self.assertEqual(sum(1 for o in olaylar if o.get("olay") == "terk_edilen_is_dusuruldu"), 2)

    def test_limit_bekleyen_akis_ref_tasir(self):
        arg = {"kosu_id": "2026-11-18-1-arastirmaci", "ajan": "arastirmaci", "prompt": "p", "kaynak": "akis",
               "akis_ref": REF}
        self.assertTrue(kosucu.limit_bekleyen_yaz(arg))
        self.assertTrue(self.ortam.kuyrukta_mi(REF))           # limit beklerken de "kuyrukta"
        kuyruk = []
        with mock.patch.object(sunucu, "akis_ref_durumu", lambda ref: "gecerli"):
            sunucu.limit_bekleyenleri_al(kuyruk)
        self.assertEqual(kuyruk[0]["akis_ref"], REF)

    def test_workflow_ceo_ve_ykb_baslatamaz(self):
        with self.assertRaises(akis_motor.BaslatmaHatasi) as c:
            self.ortam.ajan_baslat("ceo", "p", None, REF)
        self.assertEqual(c.exception.kod, 404)


class KosucuIsaretTest(OfisTabani):
    def test_sonuc_ve_baslangic_isareti(self):
        arg = {"kosu_id": "k1", "akis_ref": REF}
        kosucu.akis_isaret_yaz(arg, ".basladi", {"pid": 42})
        kosucu.akis_sonuc_yaz(arg, {"durum": "basarili", "hata": None, "sure_sn": 2, "maliyet_usd": 0.3,
                                    "cikti": "cikti/a/k1.md", "ozet": "GİZLİ ÖZET", "kullanim": {"x": 1}}, son=True)
        with open(os.path.join(akis_motor.sonuc_dizini(), f"{REF}.json")) as f:
            s = json.load(f)
        self.assertEqual((s["ref"], s["son"], s["maliyet_usd"]), (REF, True, 0.3))
        self.assertNotIn("ozet", s)                               # tam çıktı/özet işarete yazılmaz
        self.assertTrue(os.path.exists(os.path.join(akis_motor.sonuc_dizini(), f"{REF}.basladi.json")))

    def test_akissiz_kosuda_dosya_yok(self):
        kosucu.akis_isaret_yaz({"kosu_id": "k1"}, ".basladi", {"pid": 1})
        kosucu.akis_isaret_yaz({"kosu_id": "k1", "akis_ref": "../x"}, "", {})
        self.assertFalse(os.path.exists(akis_motor.sonuc_dizini()))

    def test_bitir_olayi_doner(self):
        ajan = {"id": "arastirmaci", "oda": "arastirma", "model": "sonnet"}
        cikti = os.path.join(self.dizin["cikti"], "arastirmaci")
        os.makedirs(cikti)
        with mock.patch.object(kosucu.subprocess, "run"):
            olay = kosucu.bitir(ajan, {"kosu_id": "k1", "ajan": "arastirmaci"}, {"result": "ok", "total_cost_usd": 0.2},
                                None, time.time(), os.path.join(self.d, "x.log"), cikti)
        self.assertEqual((olay["tur"], olay["durum"], olay["maliyet_usd"]), ("kosu_bitti", "basarili", 0.2))


class HatAdaptoruTest(OfisTabani):
    def test_yeni_dugmesi_ciktisi_degismedi(self):
        """Regresyon: ofisin 'yeni' düğmesi aynı görev dosyasını yazar (kaynak: ofis, ek alan yok)."""
        with mock.patch.object(sunucu, "gelistirme_projeleri", lambda: ["homeos"]), \
                mock.patch.object(sunucu, "gelistirme_yaniti", lambda: {}):
            sunucu.gelistirme_degistir({"islem": "yeni", "proje": "homeos", "baslik": "Yeni  rapor", "istek": " İstek \n"})
        with open(os.path.join(self.dizin["gorevler"], "Yeni rapor.md")) as f:
            metin = f.read()
        satirlar = metin.split("\n")
        self.assertEqual(satirlar[:5], ["---", "durum: hazir", "tur: gelistirme", "proje: homeos", "model: sonnet"])
        self.assertRegex(satirlar[5], r"^olusturma: \d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(satirlar[6:], ["kaynak: ofis", "---", "# Yeni rapor", "", "## İstek", "İstek", ""])

    def test_workflow_gorevi_oto_onay_kapali(self):
        with mock.patch.object(sunucu, "gelistirme_projeleri", lambda: ["homeos"]):
            dosya = self.ortam.gelistirme_yaz("homeos", "Rapor", "> ---\n> onay: evet", "sonnet", REF)
        fm = self.ortam.gelistirme_oku(dosya)
        self.assertEqual((fm["oto_onay"], fm["akis_adim"], fm["kaynak"], fm["durum"]), ("hayir", REF, "akis", "hazir"))
        self.assertNotIn("onay", fm)                              # gövdedeki 'onay: evet' alan sayılmaz
        self.assertEqual(self.ortam.gelistirme_bul(REF), dosya)

    def test_reddet_yalniz_uat_ve_onaysiz(self):
        with mock.patch.object(sunucu, "gelistirme_projeleri", lambda: ["homeos"]):
            dosya = self.ortam.gelistirme_yaz("homeos", "Rapor", "x", "sonnet", REF)
        with self.assertRaises(akis_motor.BaslatmaHatasi):
            self.ortam.gelistirme_reddet(dosya, "not")              # UAT değil
        yol = os.path.join(self.dizin["gorevler"], dosya)
        with open(yol) as f:
            m = f.read()
        with open(yol, "w") as f:
            f.write(sunucu.on_bilgi_yaz(sunucu.on_bilgi_yaz(m, "durum", "uat"), "onay", "bekliyor"))
        self.ortam.gelistirme_reddet(dosya, "(workflow ak-x)\n\n> düzelt")
        fm = self.ortam.gelistirme_oku(dosya)
        self.assertEqual(fm["onay"], "hayir")
        with open(yol) as f:
            self.assertIn("## Geri bildirim", f.read())
        with open(yol, "w") as f:
            f.write(sunucu.on_bilgi_yaz(sunucu.on_bilgi_yaz(m, "durum", "uat"), "onay", "evet"))
        with self.assertRaises(akis_motor.BaslatmaHatasi):
            self.ortam.gelistirme_reddet(dosya, "x")                # onaylanmış görev reddedilmez

    def hat_worktree(self, ad="1118-x"):
        """Hattın düzeni: $IS/homeos (klon) + $IS/wt/homeos-<ad> (git worktree)."""
        klon = os.path.join(self.d, "homeos")
        if not os.path.isdir(klon):
            os.makedirs(klon)
            subprocess.run(["git", "-C", klon, "init", "-q", "-b", "main"], check=True)
            subprocess.run(["git", "-C", klon, "-c", "user.name=t", "-c", "user.email=t@l", "commit", "-q",
                            "--allow-empty", "-m", "taban"], check=True)
        wt = os.path.join(self.d, "wt", f"homeos-{ad}")
        subprocess.run(["git", "-C", klon, "worktree", "add", "-q", "-b", f"beyin/{ad}", wt], check=True)
        return wt

    def test_yayin_kaniti_etiket_ve_dal(self):
        with mock.patch.object(akis_ofis, "IS_DIZINI", self.d):
            self.hat_worktree("1119-z")
            klon = os.path.join(self.d, "homeos")
            muhur = os.path.join(self.d, "muhur")
            os.makedirs(muhur)
            with mock.patch.object(sunucu, "PAKET_MUHUR_DIZINI", muhur):
                subprocess.run(["git", "-C", klon, "tag", "v0.10.9", "beyin/1119-z"], check=True)
                self.assertFalse(self.ortam._yayinlandi("homeos", "0.10.9", "beyin/1119-z", "a" * 64))   # mühür yok
                with open(os.path.join(muhur, "homeos-0.10.9.zip.sha256"), "w") as f:
                    f.write("a" * 64 + "\n")
                self.assertTrue(self.ortam._yayinlandi("homeos", "0.10.9", "beyin/1119-z", "a" * 64))
                self.assertFalse(self.ortam._yayinlandi("homeos", "0.10.9", "beyin/1119-z", "b" * 64))  # başka paket
                self.assertFalse(self.ortam._yayinlandi("homeos", "0.10.8", "beyin/1119-z", "a" * 64))  # etiket yok
                self.assertFalse(self.ortam._yayinlandi("homeos", "0.10.9", "beyin/../x", "a" * 64))

    def test_worktree_isaretcisi_dogrulanir(self):
        with mock.patch.object(akis_ofis, "IS_DIZINI", self.d):
            wt = self.hat_worktree()
            self.assertEqual(self.ortam.worktree_coz("homeos", "beyin/1118-x"), os.path.realpath(wt))
            sahte = os.path.join(wt, "sahte-git")             # ajan kendi gitdir'ini kurup işaretçiyi çevirdi
            os.makedirs(sahte)
            with open(os.path.join(wt, ".git"), "w") as f:
                f.write(f"gitdir: {sahte}\n")
            self.assertIsNone(self.ortam.worktree_coz("homeos", "beyin/1118-x"))
            os.remove(os.path.join(wt, ".git"))
            os.symlink(os.path.join(self.d, "homeos", ".git"), os.path.join(wt, ".git"))
            self.assertIsNone(self.ortam.worktree_coz("homeos", "beyin/1118-x"))

    def test_kapi_git_yapilandirmadan_komut_calistirmaz(self):
        """Ajanın etkileyebildiği git yapılandırması (fsmonitor, hooks, external diff) kapıda komut çalıştıramaz."""
        with mock.patch.object(akis_ofis, "IS_DIZINI", self.d):
            wt = self.hat_worktree("1119-y")
            iz = os.path.join(self.d, "calisti")
            for ayar in (f"core.fsmonitor=touch {iz}", f"diff.external=touch {iz}"):
                k, v = ayar.split("=", 1)
                subprocess.run(["git", "-C", wt, "config", k, v], check=True)
            with open(os.path.join(wt, "a.php"), "w") as f:
                f.write("<?php echo 1;")
            kod, _ = self.ortam.komut_calistir(["git", "diff", "--check", "main...HEAD"], wt, 30)
            self.assertEqual(kod, 0)
            self.ortam.komut_calistir(["git", "diff", "--quiet", "HEAD"], wt, 30)
            self.assertEqual(self.ortam.komut_calistir(["git", "diff", "HEAD"], wt, 30)[0], 0)   # düz diff bozulmadı
            import akis_kapi
            akis_kapi.main(["php-lint", wt, "main"])
            self.assertFalse(os.path.exists(iz), "git yapılandırmadaki komutu çalıştırdı")

    def test_git_suruculeri_kapida_calismaz(self):
        """Üçüncü inceleme: .gitattributes + depo yapılandırmasındaki filter/textconv sürücüsü kapıda komut çalıştıramaz."""
        import akis_kapi
        with mock.patch.object(akis_ofis, "IS_DIZINI", self.d):
            wt = self.hat_worktree("1119-s")
            iz = os.path.join(self.d, "surucu-calisti")
            subprocess.run(["git", "-C", wt, "config", "filter.x.clean", f"touch {iz}; cat"], check=True)
            with open(os.path.join(wt, ".gitattributes"), "w") as f:
                f.write("* filter=x diff=x\n")
            with open(os.path.join(wt, "a.php"), "w") as f:
                f.write("<?php echo 1;")
            kod, cikti = self.ortam.komut_calistir(["git", "diff", "--check", "main...HEAD"], wt, 30)
            self.assertEqual(kod, 126)
            self.assertIn("filter.x.clean", cikti)
            self.assertEqual(akis_kapi.main(["php-lint", wt, "main"]), 2)
            self.assertFalse(os.path.exists(iz))

    def test_db_okunamazsa_durum_bilinmiyor_ve_alarm(self):
        """P0-1: DB okunamazsa ne 'geçerli' ne 'geçersiz': bilinmiyor (iş korunur, başlatılmaz) + hata olayı."""
        with mock.patch.object(sunucu, "motor", side_effect=RuntimeError("db")):
            self.assertEqual(sunucu.akis_ref_durumu(REF), "bilinmiyor")
        self.assertEqual(sunucu.akis_ref_durumu(None), "gecerli")
        with open(ortak.OLAYLAR) as f:
            self.assertTrue(any(json.loads(s)["tur"] == "hata" for s in f))

    def test_yayin_kaniti_gercek_yayin_bicimi(self):
        """Ek kontrol: is_yayin dalı main'e fast-forward alır ve v<sürüm>'ü o commit'e koyar. Kanıt: etiket = dal ucu ve
        etiket main'den erişilebilir. Kendine ait commit'i olmayan (etiketin gerisindeki) dal ya da main'e alınmamış
        etiket kanıt sayılmaz."""
        def git(*a):
            subprocess.run(["git", "-C", klon, "-c", "user.name=t", "-c", "user.email=t@l", *a], check=True,
                           capture_output=True)
        muhur = os.path.join(self.d, "muhur")
        os.makedirs(muhur)
        for s_ in ("0.10.9", "0.10.10", "0.10.11"):
            with open(os.path.join(muhur, f"homeos-{s_}.zip.sha256"), "w") as f:
                f.write("a" * 64 + "\n")
        with mock.patch.object(akis_ofis, "IS_DIZINI", self.d), mock.patch.object(sunucu, "PAKET_MUHUR_DIZINI", muhur):
            wt = self.hat_worktree("1119-gercek")
            klon = os.path.join(self.d, "homeos")
            with open(os.path.join(wt, "a.txt"), "w") as f:
                f.write("x")
            subprocess.run(["git", "-C", wt, "add", "a.txt"], check=True)
            subprocess.run(["git", "-C", wt, "-c", "user.name=t", "-c", "user.email=t@l", "commit", "-qm", "is"], check=True)
            git("merge", "-q", "--ff-only", "beyin/1119-gercek")          # is_yayin: main ← dal (ff)
            git("tag", "-a", "v0.10.9", "-m", "homeos 0.10.9 (beyin)")      # etiket main ucunda = dal ucu
            git("commit", "-q", "--allow-empty", "-m", "sonraki is")       # main ilerledi: kanıt bozulmaz
            self.assertTrue(self.ortam._yayinlandi("homeos", "0.10.9", "beyin/1119-gercek", "a" * 64))
            # dal kendi commit'i olmadan tabanda; etiket daha ileride (ata ama dal ucu değil)
            git("branch", "beyin/1119-bos", "v0.10.9~1")
            git("tag", "-a", "v0.10.10", "-m", "baska")
            self.assertFalse(self.ortam._yayinlandi("homeos", "0.10.10", "beyin/1119-bos", "a" * 64))
            # etiket dal ucunda ama main'e alınmamış
            git("branch", "beyin/1119-alinmadi", "main")
            git("checkout", "-q", "beyin/1119-alinmadi")
            git("commit", "-q", "--allow-empty", "-m", "yan")
            git("tag", "-a", "v0.10.11", "-m", "yan")
            git("checkout", "-q", "main")
            self.assertFalse(self.ortam._yayinlandi("homeos", "0.10.11", "beyin/1119-alinmadi", "a" * 64))

    def test_muhur_var(self):
        muhur = os.path.join(self.d, "muhur2")
        os.makedirs(muhur)
        with open(os.path.join(muhur, "homeos-0.10.2.zip.sha256"), "w") as f:
            f.write("c" * 64 + "  homeos-0.10.2.zip\n")
        with mock.patch.object(sunucu, "PAKET_MUHUR_DIZINI", muhur):
            self.assertTrue(self.ortam.muhur_var("homeos", "0.10.2", "c" * 64))
            self.assertFalse(self.ortam.muhur_var("homeos", "0.10.2", "d" * 64))
            self.assertFalse(self.ortam.muhur_var("homeos", "../0.10.2", "c" * 64))

    def test_canli_onay_kaydi(self):
        with mock.patch.object(sunucu, "CANLI_ONAY_DIZINI", self.d):
            with open(os.path.join(self.d, "homeos-0.10.1.onay"), "w") as f:
                f.write("a" * 64 + "\n")
            self.assertTrue(self.ortam.canli_onay_var("homeos", "0.10.1", "a" * 64))
            self.assertFalse(self.ortam.canli_onay_var("homeos", "0.10.1", "b" * 64))
            self.assertFalse(self.ortam.canli_onay_var("homeos", "../x", "a" * 64))

    def test_worktree_kok_disina_cikamaz(self):
        with mock.patch.object(akis_ofis, "IS_DIZINI", self.d):
            self.hat_worktree()
            self.assertTrue(self.ortam.worktree_coz("homeos", "beyin/1118-x"))
            for dal in ("beyin/../../etc", "main", "beyin/1118-x/..", "beyin/YOK"):
                self.assertIsNone(self.ortam.worktree_coz("homeos", dal), dal)
            self.assertIsNone(self.ortam.worktree_coz("baska", "beyin/1118-x"))

    def test_komut_cikis_kodu_shell_yok(self):
        self.assertEqual(self.ortam.komut_calistir(["true"], self.d, 5)[0], 0)
        self.assertEqual(self.ortam.komut_calistir(["false"], self.d, 5)[0], 1)
        kod, cikti = self.ortam.komut_calistir(["echo", "a; false && echo $HOME"], self.d, 5)
        self.assertEqual((kod, cikti.strip()), (0, "a; false && echo $HOME"))
        self.assertEqual(self.ortam.komut_calistir(["yok-boyle-komut"], self.d, 5)[0], 127)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-gizli"}):
            self.assertNotIn("ANTHROPIC", self.ortam.komut_calistir(["env"], self.d, 5)[1])

    def test_cikti_yolu_cikti_disina_cikamaz(self):
        import akis_veri
        with self.assertRaises(akis_veri.VeriHatasi):
            self.ortam.ajan_ciktisi_oku("cikti/../ajanlar.json")


class UctanUcaTest(OfisTabani):
    """Gerçek motor + gerçek gorev_baslat + kosucu işaret fonksiyonları; restart dahil."""

    def setUp(self):
        super().setUp()
        self.db = os.path.join(self.dizin["durum"], "akis.db")

    def motor(self):
        return akis_motor.Motor(akis_db.Depo(self.db), self.ortam, kapi_senkron=True)

    def kosucu_bitir(self, metin):
        arg = self.arglar()[-1]
        yol = os.path.join(self.dizin["cikti"], arg["ajan"], f"{arg['kosu_id']}.md")
        os.makedirs(os.path.dirname(yol), exist_ok=True)
        with open(yol, "w") as f:
            f.write(metin)
        kosucu.akis_sonuc_yaz(arg, {"durum": "basarili", "maliyet_usd": 0.05, "sure_sn": 1,
                                    "cikti": os.path.relpath(yol, self.d)}, son=True)
        ortak.durum_yaz(arg.get("durum_id") or arg["ajan"], {"durum": "bitti", "kosu_id": arg["kosu_id"]})   # kosucu.bitir gibi

    def test_ornek_akis_restartla_tamamlanir(self):
        with mock.patch.object(ortak, "KOK", self.d):
            m = self.motor()
            k = m.baslat("ornek-arastirma-ozeti", {"konu": "kediler"})["run_id"]
            m.tur()
            self.assertEqual(len(self.arglar()), 1)
            self.kosucu_bitir('bulgu <akis_cikti>{"bulgu": "notlarda 3 kayıt", "kaynak_var": true}</akis_cikti>')
            m2 = self.motor()            # sunucu yeniden başladı
            m2.baslangic_uzlastir()
            m2.tur()
            self.assertEqual(len(self.tmux), 2)     # aynı ajan aynı saniyede: koşu kimliği saniye çözünürlüklü, arg dosyası aynı ad
            self.assertIn("notlarda 3 kayıt", self.arglar()[-1]["prompt"])
            self.kosucu_bitir('<akis_cikti>{"ozet": "- madde"}</akis_cikti>')
            m2.tur()
            self.assertEqual(m2.detay(k)["adimlar"][3]["durum"], "onay_bekliyor")
            m2.onayla(k, "onay", "evet")
            m2.tur()
            d = m2.detay(k)
        self.assertEqual(d["durum"], "basarili")
        self.assertAlmostEqual(d["maliyet_usd"], 0.1)
        with open(ortak.OLAYLAR) as f:
            olaylar = [json.loads(s) for s in f]
        akis = [o for o in olaylar if o["tur"] == "akis"]
        self.assertTrue(akis)
        self.assertFalse([o for o in akis if "kediler" in json.dumps(o, ensure_ascii=False)])   # istem olaya girmez


class KuyrukIptalSiralamaTest(OfisTabani):
    """P0-1 ve P0-2: gerçek sunucu.kuyrugu_isle / limit_bekleyenleri_al + gerçek Motor.iptal + OfisOrtami."""

    def setUp(self):
        super().setUp()
        self.m = akis_motor.Motor(akis_db.Depo(os.path.join(self.dizin["durum"], "akis.db")), self.ortam, kapi_senkron=True)
        for y in (mock.patch.object(sunucu, "_MOTOR", self.m), mock.patch.object(kosucu, "hepsi_limitte", lambda: False)):
            y.start()
            self.addCleanup(y.stop)

    def kuyruktaki_kosu(self):
        self.mesgul("akis-okuyucu")
        k = self.m.baslat("ornek-arastirma-ozeti", {"konu": "x"})["run_id"]
        self.m.tur()
        d = self.m.depo.denemeler(k)[0]
        self.assertEqual(d["durum"], "kuyrukta")
        ortak.durum_yaz("akis-okuyucu", {"durum": "bitti"})
        return k, d["ref"]

    def hata_olaylari(self):
        try:
            with open(ortak.OLAYLAR) as f:
                return [json.loads(s) for s in f if '"tur": "hata"' in s]
        except FileNotFoundError:
            return []

    def test_db_okunamazsa_kuyruk_isi_korunur_baslatilmaz(self):
        k, ref = self.kuyruktaki_kosu()
        with mock.patch.object(sunucu, "motor", side_effect=RuntimeError("db kilitli")):
            self.assertEqual(sunucu.kuyrugu_isle(), [])
        self.assertEqual(self.tmux, [])                                    # başlatılmadı
        self.assertEqual([x.get("akis_ref") for x in sunucu.kuyruk_oku()], [ref])   # korundu
        self.assertTrue(self.hata_olaylari())                              # alarm
        sunucu.kuyrugu_isle()                                              # DB geri geldi: normal akış
        self.assertEqual(len(self.tmux), 1)

    def test_db_okunamazsa_alarm_her_turda_tekrarlanmaz(self):
        """Son inceleme 2: DB okunamazken her kuyruk turu yeni hata olayı (Telegram) yazmaz."""
        self.kuyruktaki_kosu()
        with mock.patch.object(sunucu, "motor", side_effect=RuntimeError("db kilitli")):
            for _ in range(5):
                sunucu.kuyrugu_isle()
        self.assertEqual(len(self.hata_olaylari()), 1)
        self.assertEqual(self.tmux, [])

    def alarm(self, saat):
        with mock.patch.object(sunucu, "_alarm_saati", lambda: saat):
            return sunucu._akis_alarm_zamani_geldi()

    def test_alarm_seyreltme_acilis_ve_saat(self):
        """Alarm: aynı açılışta 10 dk'da bir; yeni açılış (boot_id farklı) hemen; bozuk dosya alarm verir."""
        self.assertTrue(self.alarm(("acilis-1", 100.0)))
        self.assertFalse(self.alarm(("acilis-1", 400.0)))
        self.assertTrue(self.alarm(("acilis-1", 701.0)))
        self.assertTrue(self.alarm(("acilis-2", 5.0)))        # yeniden açılış: monotonik saat küçük ama yeni açılış
        self.assertFalse(self.alarm(("acilis-2", 60.0)))
        with open(os.path.join(self.dizin["durum"], "akis-alarm.ts"), "w") as f:
            f.write("bozuk")
        self.assertFalse(self.alarm(("acilis-2", 61.0)))      # aynı süreç az önce alarm verdi (süreç içi yedek)
        with mock.patch.object(sunucu, "_AKIS_ALARM_SUREC", None):   # başka süreç (systemd tekrar servisi)
            with open(os.path.join(self.dizin["durum"], "akis-alarm.ts"), "w") as f:
                f.write("bozuk")
            self.assertTrue(self.alarm(("acilis-2", 62.0)))     # bozuk dosya: alarm verir ve dosyayı düzeltir
            self.assertFalse(self.alarm(("acilis-2", 63.0)))

    def test_acilis_kimligi_okunamazsa_eslesmez(self):
        self.assertTrue(self.alarm(("?", 500.0)))
        self.assertFalse(self.alarm(("?", 520.0)))           # aynı süreç: süreç içi seyreltme yine çalışır
        with mock.patch.object(sunucu, "_AKIS_ALARM_SUREC", None):   # yeniden açılış, kimlik yine okunamıyor
            self.assertTrue(self.alarm(("?", 600.0)))

    def test_alarm_dosyasi_yazilamazsa_surec_ici_seyreltme(self):
        """Disk dolu/salt okunur: dosya yazılamazsa her turda alarm yağmuru olmaz (süreç içi yedek)."""
        with mock.patch.object(sunucu, "atomik_yaz", side_effect=OSError("disk dolu")):
            sonuclar = [self.alarm(("acilis-1", t)) for t in (100.0, 120.0, 140.0)]
            self.assertEqual(sonuclar, [True, False, False])
            self.assertTrue(self.alarm(("acilis-1", 701.0)))

    def test_db_okunamazsa_limit_kaydi_korunur_baslatilmaz(self):
        arg = {"kosu_id": "2026-11-19-1-akis-okuyucu", "ajan": "akis-okuyucu", "prompt": "p", "kaynak": "akis",
               "akis_ref": REF}
        self.assertTrue(kosucu.limit_bekleyen_yaz(arg))
        with mock.patch.object(sunucu, "motor", side_effect=RuntimeError("db kilitli")):
            self.assertEqual(sunucu.kuyrugu_isle(), [])
        self.assertEqual(self.tmux, [])
        self.assertEqual(len(os.listdir(kosucu.limit_bekleyen_dizini())), 1)   # limit kaydı yerinde
        self.assertFalse(os.path.exists(sunucu.kuyruk_yolu()))
        self.assertTrue(self.hata_olaylari())

    def test_tek_kosunun_hatasi_digerlerini_durdurmaz(self):
        """Önceden var olan: bir koşunun uzlaştırması hata verirse aynı turdaki diğer koşular yine işlenir."""
        k1 = self.m.baslat("ornek-arastirma-ozeti", {"konu": "a"})["run_id"]
        asil = self.m._kosu_isle

        def bozuk(kosu_id):
            if kosu_id == k1:
                raise RuntimeError("bozuk tutamaç")
            return asil(kosu_id)
        self.m._kosu_isle = bozuk
        k2 = self.m.baslat("ornek-arastirma-ozeti", {"konu": "b"})["run_id"]
        self.m.tur()                                       # istisna dışarı sızmaz
        self.assertEqual(len(self.tmux), 1)               # k2 başlatıldı
        self.assertEqual(self.m.depo.denemeler(k2)[0]["durum"], "calisiyor")
        with open(ortak.OLAYLAR) as f:
            self.assertTrue(any(json.loads(s).get("olay") == "motor_hatasi" for s in f))

    def test_reddetme_beklenen_sha_kilit_altinda(self):
        with mock.patch.object(sunucu, "gelistirme_projeleri", lambda: ["homeos"]):
            dosya = self.ortam.gelistirme_yaz("homeos", "Rapor", "x", "sonnet", REF)
        yol = os.path.join(self.dizin["gorevler"], dosya)
        with open(yol) as f:
            m = f.read()
        m = sunucu.on_bilgi_yaz(sunucu.on_bilgi_yaz(sunucu.on_bilgi_yaz(m, "durum", "uat"), "onay", "bekliyor"), "sha256", "b" * 64)
        with open(yol, "w") as f:
            f.write(m)
        with self.assertRaises(akis_motor.BaslatmaHatasi):
            self.ortam.gelistirme_reddet(dosya, "düzelt", "a" * 64)   # test edilen A, kart artık B
        self.assertEqual(self.ortam.gelistirme_oku(dosya)["onay"], "bekliyor")

    def test_reddetme_sonrasi_tetik_hatasi_basarisizlik_sayilmaz(self):
        with mock.patch.object(sunucu, "gelistirme_projeleri", lambda: ["homeos"]):
            dosya = self.ortam.gelistirme_yaz("homeos", "Rapor", "x", "sonnet", REF)
        yol = os.path.join(self.dizin["gorevler"], dosya)
        with open(yol) as f:
            m = f.read()
        with open(yol, "w") as f:
            f.write(sunucu.on_bilgi_yaz(sunucu.on_bilgi_yaz(m, "durum", "uat"), "onay", "bekliyor"))
        with mock.patch.object(sunucu, "kosucuyu_durt", side_effect=subprocess.TimeoutExpired("systemctl", 10)):
            self.ortam.gelistirme_reddet(dosya, "düzelt")             # istisna yok: ret yazıldı
        with open(yol) as f:
            self.assertEqual(f.read().count("## Geri bildirim"), 1)

    def test_iptal_once_commit_sonra_kuyruk_kosmaz(self):
        k, ref = self.kuyruktaki_kosu()
        self.m.iptal(k)
        sunucu.kuyrugu_isle()
        self.assertEqual(self.tmux, [])

    def test_kuyruk_kontrolu_ile_baslatma_arasinda_iptal_commit_edilemez(self):
        """P0-2: kuyruk 'geçerli' dedikten sonra iptal başlarsa, iptal commit'i başlatma bitene dek bekler.
        Başlatma anında koşu DB'de hâlâ 'calisiyor' olmalı; iptal commit'inden SONRA hiçbir koşu başlamamalı."""
        k, ref = self.kuyruktaki_kosu()
        kontrol_yapildi = threading.Event()
        iptal_ilerledi = threading.Event()   # iptal ya başlatma kilidinde bekliyor ya da commit etti: hangisi önce
        baslatma_anindaki_durum = []
        asil_ucusta, asil_kilit, asil_commit = self.m.ref_ucusta, self.ortam.baslatma_kilidi, self.m._iptal_commit
        iptal_is = threading.Thread(target=lambda: self.m.iptal(k), name="iptal")

        def kilit_izle():
            if threading.current_thread() is iptal_is:
                iptal_ilerledi.set()          # düzeltmeyle: iptal commit'ten ÖNCE buraya gelir ve bekler
            return asil_kilit()

        def commit_izle(*a, **kw):
            sonuc = asil_commit(*a, **kw)
            iptal_ilerledi.set()              # düzeltme yoksa: kontrol ile başlatma arasında commit etti
            return sonuc

        bekleme_sonucu = []

        def ucusta_sonra_bekle(r):
            sonuc = asil_ucusta(r)
            kontrol_yapildi.set()
            bekleme_sonucu.append(iptal_ilerledi.wait(10))   # akis_ref_durumu istisnayı yutar: ana iş parçacığında doğrula
            return sonuc
        self.ortam.baslatma_kilidi = kilit_izle
        self.m._iptal_commit = commit_izle
        self.m.ref_ucusta = ucusta_sonra_bekle
        asil_tmux = self.sahte_tmux

        def tmux_kaydet(argv, **kw):
            if argv and argv[0] == "tmux":
                baslatma_anindaki_durum.append(akis_db.Depo(self.m.depo.yol).kosu(k)["durum"])
            return asil_tmux(argv, **kw)
        with mock.patch.object(sunucu.subprocess, "run", tmux_kaydet):
            kuyruk_is = threading.Thread(target=sunucu.kuyrugu_isle, name="kuyruk")
            kuyruk_is.start()
            self.assertTrue(kontrol_yapildi.wait(5))
            iptal_is.start()
            kuyruk_is.join(10)
            iptal_is.join(10)
        self.assertFalse(kuyruk_is.is_alive() or iptal_is.is_alive(), "kilitlenme")
        self.assertEqual(bekleme_sonucu, [True], "iptal ne kilide ulaştı ne commit etti")
        self.assertEqual(baslatma_anindaki_durum, ["calisiyor"])        # iptal commit'inden sonra başlatma yok
        d = self.m.detay(k)
        self.assertEqual(d["durum"], "iptal")
        self.assertIn("çalışan ajan koşusu durdurulmadı", d["neden"]["metin"])   # dürüst not: koşu açılmıştı
        self.assertEqual(sunucu.kuyruk_oku(), [])


class ApiTest(OfisTabani):
    def setUp(self):
        super().setUp()
        self.m = akis_motor.Motor(akis_db.Depo(os.path.join(self.dizin["durum"], "akis.db")), self.ortam, kapi_senkron=True)
        y = mock.patch.object(sunucu, "_MOTOR", self.m)
        y.start()
        self.addCleanup(y.stop)
        self.s = ThreadingHTTPServer(("127.0.0.1", 0), sunucu.Isleyici)
        self.s.daemon_threads = True
        threading.Thread(target=self.s.serve_forever, daemon=True).start()
        self.addCleanup(self.s.server_close)
        self.addCleanup(self.s.shutdown)

    def iste(self, yontem, yol, govde=None, basliklar=None):
        c = http.client.HTTPConnection("127.0.0.1", self.s.server_address[1], timeout=10)
        b = {"Host": "127.0.0.1", **(basliklar or {})}
        if govde is not None:
            b["Content-Type"] = "application/json"
        c.request(yontem, yol, body=json.dumps(govde) if govde is not None else None, headers=b)
        r = c.getresponse()
        veri = r.read()
        c.close()
        return r.status, json.loads(veri or b"{}")

    def test_liste_baslat_detay_duraklat_devam_iptal(self):
        kod, v = self.iste("GET", "/api/akis")
        self.assertEqual(kod, 200)
        self.assertIn("homeos-ozellik-gelistirme", [t["id"] for t in v["tanimlar"]])
        kod, v = self.iste("POST", "/api/akis/baslat", {"akis": "ornek-arastirma-ozeti", "girdiler": {"konu": "x"},
                                                        "idem_anahtari": "ui-1234567"})
        self.assertEqual(kod, 202)
        run = v["run_id"]
        kod, v2 = self.iste("POST", "/api/akis/baslat", {"akis": "ornek-arastirma-ozeti", "girdiler": {"konu": "x"},
                                                         "idem_anahtari": "ui-1234567"})
        self.assertEqual((v2["run_id"], v2["tekrar"]), (run, True))
        kod, v = self.iste("GET", f"/api/akis/detay?id={run}")
        self.assertEqual((kod, v["durum"], len(v["adimlar"])), (200, "calisiyor", 6))
        self.assertEqual(self.iste("POST", "/api/akis/duraklat", {"run_id": run})[1]["durum"], "duraklatildi")
        self.assertEqual(self.iste("POST", "/api/akis/devam", {"run_id": run})[1]["durum"], "calisiyor")
        self.assertEqual(self.iste("POST", "/api/akis/iptal", {"run_id": run})[1]["durum"], "iptal")
        self.assertEqual(self.iste("POST", "/api/akis/iptal", {"run_id": run})[0], 409)

    def test_girdi_dogrulama(self):
        for govde, kod in (({"akis": "../x"}, 400), ({"akis": "yok-boyle"}, 404),
                           ({"akis": "ornek-arastirma-ozeti", "girdiler": {"konu": "x" * 501}}, 400),
                           ({"akis": "ornek-arastirma-ozeti", "girdiler": {"konu": "x", "ajan": "gorevci"}}, 400),
                           ({"akis": "ornek-arastirma-ozeti", "girdiler": {"konu": "x"}, "idem_anahtari": "a b"}, 400)):
            self.assertEqual(self.iste("POST", "/api/akis/baslat", govde)[0], kod, govde)
        self.assertEqual(self.iste("GET", "/api/akis/detay?id=r'or'1")[0], 400)
        self.assertEqual(self.iste("GET", "/api/akis/detay?id=r000000000000")[0], 404)
        self.assertEqual(self.iste("POST", "/api/akis/devam", {"run_id": "r000000000000", "karar": "sil"})[0], 400)

    def test_host_ve_origin_kurali(self):
        self.assertEqual(self.iste("GET", "/api/akis", basliklar={"Host": "kotu.example"})[0], 403)
        self.assertEqual(self.iste("POST", "/api/akis/baslat", {"akis": "ornek-arastirma-ozeti"},
                                   basliklar={"Origin": "https://kotu.example"})[0], 403)

    def test_hassas_onay_kapisiz_reddedilir(self):
        t, _ = self.m.tanimlar()
        import akis_tanim
        with open(os.path.join(akis_tanim.TANIM_DIZINI, "ornek-arastirma-ozeti.json")) as f:
            ham = json.load(f)
        ham["id"] = "hassas"
        ham["adimlar"][3]["kategori"] = "posta"
        hassas = akis_tanim.dogrula(ham)
        self.m.tanim_yukle = lambda: ({**t, "hassas": hassas}, {})
        run = self.m.baslat("hassas", {"konu": "x"})["run_id"]
        with self.m.depo.islem() as b:
            b.execute("UPDATE adimlar SET durum='onay_bekliyor' WHERE kosu_id=? AND adim_id='onay'", (run,))
        kod, v = self.iste("POST", "/api/akis/onay", {"run_id": run, "adim": "onay", "karar": "evet"},
                           basliklar={"X-Ofis-Kapi": "tahmin"})
        self.assertEqual(kod, 403)

    def test_eski_uclar_calisiyor(self):
        self.assertEqual(self.iste("GET", "/api/ajanlar")[0], 200)
        self.assertEqual(self.iste("GET", "/api/yok")[0], 404)
        self.assertEqual(self.iste("POST", "/api/gorev", {"ajan": "arastirmaci", "prompt": "p"})[0], 202)


if __name__ == "__main__":
    unittest.main()
