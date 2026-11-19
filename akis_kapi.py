#!/usr/bin/env python3
"""Kalite kapısı yardımcıları (workflow quality_gate). Çıkış kodu kanıttır: 0 = geçti. Model çağırmaz, ağ yok.

python3 akis_kapi.py php-lint <worktree> <taban>   # tabandan beri değişen/eklenen .php dosyalarına php -l
python3 akis_kapi.py sha256 <dosya> <beklenen-hex>  # paket mührü: dosyanın SHA-256'sı beklenenle aynı mı
"""
import hashlib
import os
import re
import subprocess
import sys


SURUCU_DESENI = r"^(filter\..*\.(clean|smudge|process)|diff\..*\.(textconv|command)|merge\..*\.driver)$"


def git_suruculeri(wt):
    """Depo yapılandırmasındaki, .gitattributes ile tetiklenip komut çalıştıran sürücüler (textconv, filter, merge).
    Ajan worktree'deki .gitattributes'ı yazabilir; sürücü tanımlıysa kapı git'i çalıştırmaz. Okunamazsa güvenli tarafta."""
    ortam = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    try:
        p = subprocess.run(["git", "-C", wt, "config", "--get-regexp", SURUCU_DESENI], capture_output=True, text=True,
                           timeout=20, env=ortam)
    except (OSError, subprocess.TimeoutExpired):
        return ["git config okunamadı"]
    if p.returncode == 1:      # eşleşme yok
        return []
    if p.returncode != 0:
        return ["git config okunamadı"]
    return [satir.split()[0] for satir in p.stdout.splitlines() if satir.strip()]


def php_lint(wt, taban):
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", taban) or taban.startswith("-"):
        print("geçersiz taban")
        return 2
    def git(*a):   # ajanın yazabildiği worktree: yapılandırmadan komut çalıştırma yolları kapalı
        guvenli = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.pager=cat",
                   "-c", "diff.external=true", "-c", "protocol.allow=never"]
        ortam = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"}
        return subprocess.run(["git", *guvenli, "-C", wt, *a], capture_output=True, text=True, timeout=60, env=ortam)
    suruculer = git_suruculeri(wt)
    if suruculer:
        print("git yapılandırmasında komut çalıştıran sürücü var, denetlenmedi: " + ", ".join(suruculer)[:200])
        return 2
    mb = git("merge-base", taban, "HEAD")
    if mb.returncode != 0:
        print("merge-base bulunamadı")
        return 2
    # -z: boşluklu ve Türkçe karakterli adlar bölünmez/tırnaklanmaz (yoksa bozuk dosya sessizce atlanırdı)
    degisen = git("diff", "-z", "--name-only", "--diff-filter=AMR", mb.stdout.strip(), "--", "*.php")
    yeni = git("ls-files", "-z", "--others", "--exclude-standard", "--", "*.php")
    if degisen.returncode != 0 or yeni.returncode != 0:
        print("değişen dosyalar listelenemedi")
        return 2
    dosyalar = sorted({d for d in (degisen.stdout + yeni.stdout).split("\0") if d})
    hata = 0
    for d in dosyalar:
        yol = os.path.realpath(os.path.join(wt, d))
        if not yol.startswith(os.path.realpath(wt) + os.sep):
            print(f"❌ {d}: worktree dışına işaret ediyor")
            hata += 1
            continue
        if not os.path.isfile(yol):
            continue
        p = subprocess.run(["php", "-l", yol], capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            hata += 1
            print(f"❌ {d}: {' '.join((p.stdout + p.stderr).split())[:200]}")
    print(f"php -l: {len(dosyalar)} dosya, {hata} hata")
    return 1 if hata else 0


def sha256(dosya, beklenen):
    if not re.fullmatch(r"[0-9a-f]{64}", beklenen):
        print("beklenen SHA-256 geçersiz")
        return 2
    try:
        h = hashlib.sha256()
        with open(dosya, "rb") as f:
            for parca in iter(lambda: f.read(1 << 20), b""):
                h.update(parca)
    except OSError:
        print("paket okunamadı")
        return 1
    if h.hexdigest() != beklenen:
        print("paket SHA-256 mühürle uyuşmuyor")
        return 1
    print("paket mührü doğru")
    return 0


def main(argv):
    if len(argv) == 3 and argv[0] == "php-lint":
        return php_lint(argv[1], argv[2])
    if len(argv) == 3 and argv[0] == "sha256":
        return sha256(argv[1], argv[2])
    print(__doc__.strip().splitlines()[2])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
