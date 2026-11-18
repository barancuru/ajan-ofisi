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


def php_lint(wt, taban):
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", taban) or taban.startswith("-"):
        print("geçersiz taban")
        return 2
    def git(*a):
        return subprocess.run(["git", "-C", wt, *a], capture_output=True, text=True, timeout=60)
    mb = git("merge-base", taban, "HEAD")
    if mb.returncode != 0:
        print("merge-base bulunamadı")
        return 2
    degisen = git("diff", "--name-only", "--diff-filter=AMR", mb.stdout.strip(), "--", "*.php").stdout.split()
    yeni = git("ls-files", "--others", "--exclude-standard", "--", "*.php").stdout.split()
    dosyalar = sorted(set(degisen + yeni))
    hata = 0
    for d in dosyalar:
        yol = os.path.realpath(os.path.join(wt, d))
        if not yol.startswith(os.path.realpath(wt) + os.sep) or not os.path.isfile(yol):
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
