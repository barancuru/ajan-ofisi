"""Workflow motorunun Ajan Ofisi'ne bağlandığı tek yer (ortam). Mevcut mekanizmaları yeniden kullanır:
gorev_baslat()/kuyruk/kosucu, beyin hattı görev dosyaları, olaylar.jsonl. Yalnız stdlib.

sunucu modülü çalışma anında verilir (döngüsel import yok).
"""
import contextlib
import glob
import json
import os
import re
import subprocess

import time

import akis_kapi
import akis_motor
import akis_tanim
import akis_veri
import ortak

IS_DIZINI = os.path.expanduser(os.environ.get("OFIS_IS_DIZINI", "~/beyin-is"))   # bin/calistir IS_DIZIN
KOMUT_CIKTI_MAKS = 4000
# Kapı git'i ajanın yazabildiği worktree'de koşar: yapılandırmadan komut çalıştırma yolları kapatılır.
GIT_GUVENLI = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.pager=cat",
               "-c", "diff.external=true", "-c", "core.sshCommand=false", "-c", "protocol.allow=never"]


def guvenli_git_ortami(temel):
    return {**temel, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0"}


HAT_BETIGI = os.path.expanduser(os.environ.get("OFIS_HAT_BETIGI", "~/beyin/bin/calistir"))
# Hattın her koşuda yazdığı işaret: ajanların (Write ~/beyin/** dahil) ve kum havuzunun yazamadığı durum klasöründe
HAT_KORUMA_ISARETI = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                                  "beyin", "hat-koruma-surumu")


def duz_dosya_oku(yol, en_cok=400_000):
    """Yalnız sıradan dosya: symlink izlenmez (O_NOFOLLOW), FIFO/aygıt açılırken bloke etmez (O_NONBLOCK, fstat önce).
    Hata: OSError (FileNotFoundError dahil)."""
    import stat as _stat
    fd = os.open(yol, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not _stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"sıradan dosya değil: {os.path.basename(yol)}")
        os.set_blocking(fd, True)
        f = os.fdopen(fd, encoding="utf-8", errors="replace")
        fd = None
        with f:
            return f.read(en_cok)
    finally:
        if fd is not None:
            os.close(fd)


def kimlik_oku(yol):
    """Hattın mühür kimliği (paket_muhurle) ya da onay kaydı kimliği: 'anahtar=değer' satırları. Symlink izlenmez.
    Geçersiz/eksikse None. Alanlar: gorev (görev dosyası adı), dal, sha256."""
    try:
        metin = duz_dosya_oku(yol, 4096)
    except OSError:
        return None
    k = {}
    for satir in metin.splitlines():
        a, ayr, d = satir.partition("=")
        if ayr and a in ("gorev", "dal", "sha256"):
            k[a] = d.strip()
    if not (k.get("gorev") and re.fullmatch(r"[0-9a-f]{64}", k.get("sha256", ""))):
        return None
    return k


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

    def kuyruktaki_refler(self):
        """Kuyruk ve limit-bekleyen'deki bütün akis_ref'ler (motor turu başına bir kez)."""
        refler = {k.get("akis_ref") for k in self.s.kuyruk_oku() if k.get("akis_ref")}
        refler |= {k.get("akis_ref") for _, k in self._limit_bekleyenler() if k.get("akis_ref")}
        return refler

    def hat_korumasi_var(self):
        """Canlı hat (bin/calistir) görev kilidi + güvenli yazım + mühür kimliğiyle mi çalışıyor (HAT_KORUMA_SURUMU)?"""
        # İki kanıt birlikte: betikte işaret satırı VE hattın ajanların yazamadığı durum klasörüne yazdığı işaret dosyası
        # (yalnız betiğe satır eklemek yetmez; eski hat işaret dosyası yazmaz)
        try:
            betik = duz_dosya_oku(HAT_BETIGI, 2_000_000)
            isaret = duz_dosya_oku(HAT_KORUMA_ISARETI, 64).strip()
        except OSError:
            return False
        m = re.search(r"^HAT_KORUMA_SURUMU=([1-9][0-9]*)\b", betik, re.M)
        return bool(m) and isaret == m.group(1)

    def yayinlandi(self, proje, surum, dal, sha, dosya=None):
        """'durum: bitti' kapısız yazılabilir. Yayın kanıtı üç parça: (1) hattın paket mühürü (ajanların yazamadığı
        ~/.local/state/beyin/paket-muhur) bu sürüm için bu sha, (2) klonda v<sürüm> etiketi, (3) dal o etikete alınmış.
        Olumsuz sonuç 60 sn önbellekte: bekleyen kart her turda git çalıştırmasın."""
        anahtar = (proje, surum, dal, sha, dosya)
        onbellek = self.__dict__.setdefault("_yayin_onbellek", {})
        if anahtar in onbellek and time.time() - onbellek[anahtar] < 60:
            return False
        sonuc = self._yayinlandi(proje, surum, dal, sha, dosya)
        if not sonuc:
            onbellek[anahtar] = time.time()
        return sonuc

    def muhur_var(self, proje, surum, sha, dosya=None, dal=None):
        """Hattın paket mührü (ajanların yazamadığı ~/.local/state/beyin/paket-muhur) bu sürüm için bu sha mı.
        dosya verilirse mühür kimliği (.kimlik) de bu göreve (ve verilirse dala) ait olmalı: kimliksiz mühür (eski hat)
        workflow için kanıt sayılmaz."""
        if proje not in akis_tanim.GELISTIRME_PROJELERI or not isinstance(surum, str) or not isinstance(sha, str) \
                or not akis_motor.DEGER_DESENLERI["surum"].match(surum) or not akis_motor.DEGER_DESENLERI["sha256"].match(sha):
            return False
        taban = os.path.join(self.s.PAKET_MUHUR_DIZINI, f"{proje}-{surum}.zip")
        try:
            if duz_dosya_oku(taban + ".sha256", 4096).split()[0:1] != [sha]:
                return False
        except OSError:
            return False
        if dosya is None:
            return True
        k = kimlik_oku(taban + ".kimlik")
        return bool(k and k["gorev"] == dosya and k["sha256"] == sha and (dal is None or k.get("dal") == dal))

    def _yayinlandi(self, proje, surum, dal, sha, dosya=None):
        if not akis_motor.DEGER_DESENLERI["dal"].match(dal or "") or not self.muhur_var(proje, surum, sha, dosya, dal):
            return False
        klon = os.path.join(IS_DIZINI, proje)
        ortam = guvenli_git_ortami({"PATH": "/usr/bin:/bin", "HOME": os.path.expanduser("~"), "LANG": "C.UTF-8"})
        try:
            etiket = subprocess.run(["git", *GIT_GUVENLI, "-C", klon, "rev-parse", "-q", "--verify",
                                     f"refs/tags/v{surum}^{{commit}}"], capture_output=True, text=True, timeout=20, env=ortam)
            if etiket.returncode != 0:
                return False
            # is_yayin: main ← dal (--ff-only), sonra v<sürüm> main ucuna. Yani etiket TAM dal ucunda olmalı (yalnız ata
            # olmak yetmez: kendi commit'i olmayan, etiketin gerisindeki dal da ata olurdu) ve main'den erişilebilmeli.
            dal_ucu = subprocess.run(["git", *GIT_GUVENLI, "-C", klon, "rev-parse", "-q", "--verify",
                                      f"refs/heads/{dal}^{{commit}}"], capture_output=True, text=True, timeout=20, env=ortam)
            if dal_ucu.returncode != 0 or dal_ucu.stdout.strip() != etiket.stdout.strip():
                return False
            taban = self.taban(proje)
            alindi = subprocess.run(["git", *GIT_GUVENLI, "-C", klon, "merge-base", "--is-ancestor", f"refs/tags/v{surum}",
                                     f"refs/heads/{taban}"], capture_output=True, timeout=20, env=ortam)
            return alindi.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def kuyrukta_mi(self, ref):
        return ref in self.kuyruktaki_refler()

    def canli_onay_var(self, proje, surum, sha, dosya=None, dal=None):
        """Ofis girişinin (kapı imzası) yazdığı, mühürlü pakete bağlı canlı onay kaydı (sunucu.canli_onayi_yaz).
        dosya verilirse onay kimliği (.onay.kimlik, mühürden kopyalanır) de bu göreve ait olmalı."""
        if not (isinstance(proje, str) and re.fullmatch(r"[a-z-]{1,40}", proje) and isinstance(surum, str)
                and re.fullmatch(r"[0-9.]{1,24}", surum) and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
            return False
        taban = os.path.join(self.s.CANLI_ONAY_DIZINI, f"{proje}-{surum}.onay")
        try:
            if duz_dosya_oku(taban, 4096).strip() != sha:
                return False
        except OSError:
            return False
        if dosya is None:
            return True
        # onay kimliği = mühür kimliği = izlenen kart (ve dal): ikisi de bu görev/dal/sha'yı söylemeli
        k = kimlik_oku(taban + ".kimlik")
        return bool(k and k["gorev"] == dosya and k["sha256"] == sha and (dal is None or k.get("dal") == dal)
                    and self.muhur_var(proje, surum, sha, dosya, dal))

    @contextlib.contextmanager
    def baslatma_kilidi(self):
        """Kuyruğu işleyenlerle (ofis sunucusu: iş parçacığı kilidi + dosya kilidi; systemd tekrar servisi: dosya kilidi)
        aynı kilit. İç içe alınmaz: flock aynı süreçte ikinci kez alınırsa kilitlenir."""
        with self.s.BASLATMA_KILIDI, ortak.baslatma_kilidi():
            yield

    def kuyruktan_cikar(self, ref):
        with self.baslatma_kilidi():
            return self.kuyruktan_cikar_kilitsiz(ref)

    def kuyruktan_cikar_kilitsiz(self, ref):
        """baslatma_kilidi() ALTINDA çağrılır."""
        cikti = False
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

    def ajan_durdur(self, ref):
        """V1.1 #7: çalışan workflow ajan koşusuna iptal sinyali (SIGUSR1). Süreç kosucu'nun başlangıç işaretinden
        bulunur ve /proc'tan doğrulanır: komut satırı bu koşunun arg dosyasıyla kosucu.py olmalı (PID yeniden
        kullanımına ve sahte işarete karşı). Doğrulanamazsa sinyal YOK: dönen (False, neden)."""
        import signal
        if not isinstance(ref, str) or not akis_motor.REF_DESENI.match(ref):
            return False, "geçersiz ref"
        isaret = akis_motor._json_oku(os.path.join(akis_motor.sonuc_dizini(), f"{ref}.basladi.json")) or {}
        pid, kosu_id = isaret.get("pid"), isaret.get("kosu_id")
        if isaret.get("ref") != ref or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1 \
                or not isinstance(kosu_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", kosu_id):
            return False, "başlangıç işareti yok ya da geçersiz"
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            return False, "süreç yok (bitmiş olabilir)"
        arg_yolu = os.path.join(ortak.KOSU_DIZINI, f"{kosu_id}.arg.json")
        if not (len(argv) >= 2 and os.path.basename(argv[-2]) == "kosucu.py"
                and os.path.realpath(argv[-1]) == os.path.realpath(arg_yolu)):
            return False, "süreç bu koşunun kosucu'su değil"
        try:
            os.kill(pid, signal.SIGUSR1)
        except OSError as e:
            return False, f"sinyal gönderilemedi ({type(e).__name__})"
        return True, None

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
            fm, _ = self.s.on_bilgi(duz_dosya_oku(yol))   # symlink/FIFO izlenmez
        except OSError:
            return None
        return fm

    def gelistirme_bul(self, ref):
        if not akis_motor.REF_DESENI.match(ref or ""):
            return None
        for d in (self.s.GOREV_DIZINI, os.path.join(self.s.GOREV_DIZINI, "bitti")):
            for yol in glob.glob(os.path.join(d, "*.md")):
                try:
                    metin = duz_dosya_oku(yol)   # FIFO/symlink izlenmez
                except OSError:
                    continue
                fm, govde = self.s.on_bilgi(metin)
                if fm.get("akis_adim") == ref or f"(workflow {ref})" in govde:
                    return os.path.basename(yol)
        return None

    def gelistirme_reddet(self, dosya, not_, beklenen_sha=None):
        try:
            self.s.uat_reddet(dosya, not_, beklenen_sha=beklenen_sha)
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
        if proje not in akis_tanim.GELISTIRME_PROJELERI or not akis_motor.DEGER_DESENLERI["dal"].match(dal or ""):
            return None
        kok = os.path.realpath(os.path.join(IS_DIZINI, "wt"))
        yol = os.path.realpath(os.path.join(kok, f"{proje}-{dal[len('beyin/'):]}"))
        if not yol.startswith(kok + os.sep) or not os.path.isdir(yol):
            return None
        # .git işaretçisi ajanın yazabildiği yerde: yalnız hattın klonundaki worktree kaydına gösterebilir
        # (kendi gitdir'ine çevrilmiş bir işaretçi, kapının git'ine ajan yapılandırması yükletirdi)
        isaretci = os.path.join(yol, ".git")
        if os.path.islink(isaretci) or not os.path.isfile(isaretci):
            return None
        try:
            with open(isaretci, encoding="utf-8") as f:
                satir = f.read(4096).strip()
        except OSError:
            return None
        if not satir.startswith("gitdir: "):
            return None
        gitdir = os.path.realpath(satir[len("gitdir: "):])
        beklenen = os.path.realpath(os.path.join(IS_DIZINI, proje, ".git", "worktrees"))
        if not gitdir.startswith(beklenen + os.sep) or not os.path.isdir(gitdir):
            return None
        return yol

    def komut_calistir(self, argv, cwd, zaman_asimi):
        """Shell yok, stdin yok, sırsız en dar ortam. Dönen: (çıkış kodu, çıktının son kısmı)."""
        ortam = guvenli_git_ortami({"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": os.path.expanduser("~"),
                                    "LANG": "C.UTF-8"})
        if argv and argv[0] == "git":
            suruculer = akis_kapi.git_suruculeri(cwd)
            if suruculer:
                return 126, "git yapılandırmasında komut çalıştıran sürücü tanımlı, kapı koşmadı: " + ", ".join(suruculer)[:200]
            argv = ["git", *GIT_GUVENLI, *argv[1:]]
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
