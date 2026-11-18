"""Workflow motorunun Ajan Ofisi'ne bağlandığı tek yer (ortam). Mevcut mekanizmaları yeniden kullanır:
gorev_baslat()/kuyruk/kosucu, beyin hattı görev dosyaları, olaylar.jsonl. Yalnız stdlib.

sunucu modülü çalışma anında verilir (döngüsel import yok).
"""
import glob
import json
import os
import re
import subprocess

import akis_motor
import akis_veri
import ortak

IS_DIZINI = os.path.expanduser(os.environ.get("OFIS_IS_DIZINI", "~/beyin-is"))   # bin/calistir IS_DIZIN
KOMUT_CIKTI_MAKS = 4000


class OfisOrtami:
    def __init__(self, sunucu):
        self.s = sunucu

    # ---- ajanlar ve kuyruk
    def ajan_tablosu(self):
        return ortak.ajanlari_yukle()

    def ajan_baslat(self, ajan_id, istem, model, ref):
        try:
            return self.s.gorev_baslat(ajan_id, prompt=istem, kaynak="akis", havuz=True, model=model, akis_ref=ref)
        except self.s.IstekHatasi as e:
            raise akis_motor.BaslatmaHatasi(e.kod, str(e)) from e

    def _limit_bekleyenler(self):
        import kosucu
        for yol in glob.glob(os.path.join(kosucu.limit_bekleyen_dizini(), "*.json")):
            k = akis_motor._json_oku(yol)
            if k:
                yield yol, k

    def kuyrukta_mi(self, ref):
        if any(k.get("akis_ref") == ref for k in self.s.kuyruk_oku()):
            return True
        return any(k.get("akis_ref") == ref for _, k in self._limit_bekleyenler())

    def kuyruktan_cikar(self, ref):
        cikti = False
        with self.s.BASLATMA_KILIDI, ortak.baslatma_kilidi():
            kuyruk = self.s.kuyruk_oku()
            kalan = [k for k in kuyruk if k.get("akis_ref") != ref]
            if len(kalan) != len(kuyruk):
                self.s.kuyruk_yaz(kalan)
                cikti = True
            for yol, k in self._limit_bekleyenler():
                if k.get("akis_ref") == ref:
                    try:
                        os.remove(yol)
                        cikti = True
                    except OSError:
                        pass
        return cikti

    def arg_dosyasi_var(self, ref):
        """tmux'a verilmiş ama iz bırakmamış koşu (yeniden başlatma kurtarması). Yalnız son 2 günün dosyaları."""
        import time
        sinir = time.time() - 2 * 86400
        for yol in glob.glob(os.path.join(ortak.KOSU_DIZINI, "*.arg.json")):
            try:
                if os.path.getmtime(yol) < sinir:
                    continue
            except OSError:
                continue
            k = akis_motor._json_oku(yol)
            if k and k.get("akis_ref") == ref:
                return True
        return False

    def ajan_ciktisi_oku(self, goreli):
        if not isinstance(goreli, str) or not goreli:
            raise akis_veri.VeriHatasi("cikti_yok", "çıktı dosyası yok")
        kok = os.path.realpath(ortak.CIKTI_DIZINI)
        yol = os.path.realpath(os.path.join(ortak.KOK, goreli))
        if not yol.startswith(kok + os.sep) or not os.path.isfile(yol):
            raise akis_veri.VeriHatasi("cikti_yok", "çıktı dosyası cikti/ altında değil ya da yok")
        with open(yol, encoding="utf-8", errors="replace") as f:
            return f.read(akis_veri.MAKS_HAM_CIKTI)

    def olay_yayinla(self, olay):
        ortak.olay_yaz(olay)

    # ---- beyin hattı (adaptör)
    def gelistirme_yaz(self, proje, baslik, istek, model, ref):
        if proje not in self.s.gelistirme_projeleri():
            raise akis_motor.BaslatmaHatasi(409, "proje adaptörü yok")
        if len(baslik.strip()) < 3:
            baslik = "Workflow görevi"
        return self.s.gelistirme_gorevi_yaz(proje, baslik, istek, model,
                                            {"kaynak": "akis", "oto_onay": "hayir", "akis_adim": ref})

    def _gorev_yolu(self, dosya):
        if not isinstance(dosya, str) or not self.s.DOSYA_DESENI.match(dosya) or dosya.startswith("."):
            return None
        for d in (self.s.GOREV_DIZINI, os.path.join(self.s.GOREV_DIZINI, "bitti")):
            yol = os.path.join(d, dosya)
            if os.path.isfile(yol) and not os.path.islink(yol):
                return yol
        return None

    def gelistirme_oku(self, dosya):
        yol = self._gorev_yolu(dosya)
        if not yol:
            return None
        try:
            with open(yol, encoding="utf-8", errors="replace") as f:
                fm, _ = self.s.on_bilgi(f.read(400_000))
        except OSError:
            return None
        return fm

    def gelistirme_bul(self, ref):
        if not akis_motor.REF_DESENI.match(ref or ""):
            return None
        for d in (self.s.GOREV_DIZINI, os.path.join(self.s.GOREV_DIZINI, "bitti")):
            for yol in glob.glob(os.path.join(d, "*.md")):
                try:
                    with open(yol, encoding="utf-8", errors="replace") as f:
                        metin = f.read(400_000)
                except OSError:
                    continue
                fm, govde = self.s.on_bilgi(metin)
                if fm.get("akis_adim") == ref or f"(workflow {ref})" in govde:
                    return os.path.basename(yol)
        return None

    def gelistirme_reddet(self, dosya, not_):
        try:
            self.s.uat_reddet(dosya, not_)
        except self.s.IstekHatasi as e:
            raise akis_motor.BaslatmaHatasi(e.kod, str(e)) from e

    def hat_durt(self):
        self.s.kosucuyu_durt()

    def yayin_dizini(self):
        return os.path.join(self.s.BEYIN, "sistem", "yayin")

    def taban(self, proje):
        return "main"   # sistem/gelistirme/<proje>.sh PROJE_TABAN (üçünde de main)

    def worktree_coz(self, proje, dal):
        """Hattın worktree'si: $IS_DIZIN/wt/<proje>-<dal adı>. realpath ile kök dışına çıkış reddedilir."""
        if proje not in ("homeos", "turnusol", "ajan-ofisi") or not re.fullmatch(r"beyin/[a-z0-9-]{1,80}", dal or ""):
            return None
        kok = os.path.realpath(os.path.join(IS_DIZINI, "wt"))
        yol = os.path.realpath(os.path.join(kok, f"{proje}-{dal[len('beyin/'):]}"))
        if not yol.startswith(kok + os.sep) or not os.path.isdir(yol):
            return None
        return yol

    def komut_calistir(self, argv, cwd, zaman_asimi):
        """Shell yok, stdin yok, sırsız en dar ortam. Dönen: (çıkış kodu, çıktının son kısmı)."""
        ortam = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": os.path.expanduser("~"), "LANG": "C.UTF-8",
                 "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
        try:
            p = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               errors="replace", timeout=zaman_asimi, env=ortam)
        except subprocess.TimeoutExpired:
            return 124, f"zaman aşımı ({zaman_asimi} sn)"
        except FileNotFoundError:
            return 127, "komut bulunamadı"
        except OSError as e:
            return 126, f"çalıştırılamadı ({type(e).__name__})"
        return p.returncode, akis_veri.maskele(((p.stdout or "") + (p.stderr or ""))[-KOMUT_CIKTI_MAKS:])


def motor_kur(sunucu, depo=None):
    import akis_db
    return akis_motor.Motor(depo or akis_db.Depo(), OfisOrtami(sunucu))


def json_guvenli(o):
    return json.loads(json.dumps(o, ensure_ascii=False, default=str))
