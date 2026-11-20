"""Workflow saklama (V1.1 #10): bitmiş koşuları N gün sonra arşivleyip DB'den ve durum/akis-sonuc/'dan kaldırır.

Varsayılan KURU KOŞU: yalnız neyin kaldırılacağını raporlar, hiçbir şey yazmaz/silmez. Gerçek silme `--uygula` ister
ve zamanlanmış değildir (açılması kullanıcı kararı). Sıra her koşu için: arşiv yaz (gzip JSON, fsync, atomik ad) →
tek işlemde koşulları yeniden kontrol edip DB satırlarını sil → sonuç dosyalarını sil. Arşiv yazılamazsa o koşu
silinmez. Arşiv kalıcıdır; ayrıca silinmez.

Kaldırılmayanlar: etkin koşular, uçuşta (gonderiliyor|kuyrukta|calisiyor) denemesi kalan bitmiş koşular,
bitiş zamanı olmayanlar. Sahipsiz sonuç dosyası (ref DB'de yok) yalnız N günden eskiyse ve adı ref desenine uyuyorsa.

    python3 akis_saklama.py [--gun 90]            # kuru koşu
    python3 akis_saklama.py [--gun 90] --uygula   # arşivle + sil
"""
import argparse
import gzip
import json
import os
import re
import sys
import time

import akis_db
import akis_motor
import ortak

VARSAYILAN_GUN = 90
EN_AZ_GUN = 7   # yanlışlıkla --gun 0 ile yeni koşular silinmesin
SONUC_ADI = re.compile(r"^(ak-[0-9a-f]{12})\.(?:json|basladi\.json|ara-[A-Za-z0-9_.-]{1,80}\.json)$")
TABLOLAR = ("kosular", "adimlar", "denemeler", "olaylar", "ogeler")


def arsiv_dizini():
    return os.path.join(ortak.DURUM_DIZINI, "akis-arsiv")


def adaylar(depo, sinir_ts):
    """Kaldırılabilir koşu id'leri (salt okuma)."""
    b = depo.baglanti()
    soru = ",".join("?" * len(akis_db.SON_KOSU))
    ucusta = ",".join("?" * len(akis_db.UCUSTA))
    rows = b.execute(f"SELECT id FROM kosular k WHERE durum IN ({soru}) AND bitis_ts IS NOT NULL AND bitis_ts < ? "
                     f"AND NOT EXISTS (SELECT 1 FROM denemeler d WHERE d.kosu_id=k.id AND d.durum IN ({ucusta})) "
                     "ORDER BY bitis_ts", (*akis_db.SON_KOSU, sinir_ts, *akis_db.UCUSTA)).fetchall()
    return [r["id"] for r in rows]


def _satirlar(b, kosu_id):
    sonuc = {"kosular": [dict(r) for r in b.execute("SELECT * FROM kosular WHERE id=?", (kosu_id,))]}
    for t in TABLOLAR[1:]:
        sonuc[t] = [dict(r) for r in b.execute(f"SELECT * FROM {t} WHERE kosu_id=?", (kosu_id,))]
    return sonuc


def _arsiv_yaz(kosu_id, veri):
    d = arsiv_dizini()
    os.makedirs(d, mode=0o700, exist_ok=True)
    hedef = os.path.join(d, f"{kosu_id}.json.gz")
    gecici = hedef + f".{os.getpid()}.tmp"
    fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as ham, gzip.GzipFile(fileobj=ham, mode="wb") as f:
            f.write(json.dumps(veri, ensure_ascii=False).encode("utf-8"))
            f.flush()
        with open(gecici, "rb") as f:
            os.fsync(f.fileno())
        os.replace(gecici, hedef)
    except BaseException:
        try:
            os.remove(gecici)
        except OSError:
            pass
        raise
    return hedef


def _sonuc_dosyalari(refler=None, sinir_ts=None, bilinen=frozenset()):
    """refler verilirse onların dosyaları; yoksa sahipsiz (ref bilinmeyen) ve sinir_ts'den eski dosyalar."""
    d = akis_motor.sonuc_dizini()
    try:
        adlar = os.listdir(d)
    except OSError:
        return []
    sonuc = []
    for ad in sorted(adlar):
        m = SONUC_ADI.match(ad)
        if not m:
            continue
        yol = os.path.join(d, ad)
        if refler is not None:
            if m.group(1) in refler:
                sonuc.append(yol)
            continue
        try:
            st = os.lstat(yol)
        except OSError:
            continue
        if m.group(1) not in bilinen and st.st_mtime < sinir_ts:
            sonuc.append(yol)
    return sonuc


def calistir(depo=None, gun=VARSAYILAN_GUN, uygula=False, saat=time.time):
    if gun < EN_AZ_GUN:
        raise ValueError(f"--gun en az {EN_AZ_GUN}")
    depo = depo or akis_db.Depo()
    sinir = saat() - gun * 86400
    rapor = {"gun": gun, "uygula": uygula, "kosular": [], "sahipsiz_dosyalar": [], "atlanan": []}
    for kosu_id in adaylar(depo, sinir):
        b = depo.baglanti()
        veri = _satirlar(b, kosu_id)
        refler = {d["ref"] for d in veri["denemeler"]}
        dosyalar = _sonuc_dosyalari(refler)
        satir = {"run_id": kosu_id, "durum": veri["kosular"][0]["durum"], "denemeler": len(veri["denemeler"]),
                 "olaylar": len(veri["olaylar"]), "dosyalar": len(dosyalar)}
        if not uygula:
            rapor["kosular"].append(satir)
            continue
        try:
            satir["arsiv"] = _arsiv_yaz(kosu_id, {"surum": 1, "arsiv_ts": saat(), **veri})
        except OSError as e:
            rapor["atlanan"].append({"run_id": kosu_id, "neden": f"arşiv yazılamadı: {type(e).__name__}"})
            continue
        with depo.islem() as b:
            # arşivle silme arasında durum değişmiş olabilir (yeniden açılmaz ama uçuşta deneme dönebilir): yeniden kontrol
            if kosu_id not in adaylar(depo, sinir):
                rapor["atlanan"].append({"run_id": kosu_id, "neden": "koşul değişti"})
                continue
            # arşivlenmemiş satır silinmesin: arşivden sonra eklenen olay/deneme varsa bu tur atlanır
            if {t: len(v) for t, v in _satirlar(b, kosu_id).items()} != {t: len(v) for t, v in veri.items()}:
                rapor["atlanan"].append({"run_id": kosu_id, "neden": "arşivden sonra satır değişti"})
                continue
            for t in ("olaylar", "ogeler", "denemeler", "adimlar"):
                b.execute(f"DELETE FROM {t} WHERE kosu_id=?", (kosu_id,))
            b.execute("DELETE FROM kosular WHERE id=?", (kosu_id,))
        for yol in dosyalar:
            try:
                os.remove(yol)
            except FileNotFoundError:
                pass
        rapor["kosular"].append(satir)
    bilinen = {r["ref"] for r in depo.baglanti().execute("SELECT ref FROM denemeler")}
    for yol in _sonuc_dosyalari(sinir_ts=sinir, bilinen=bilinen):
        rapor["sahipsiz_dosyalar"].append(os.path.basename(yol))
        if uygula:
            try:
                os.remove(yol)
            except FileNotFoundError:
                pass
    return rapor


def main(argv=None):
    p = argparse.ArgumentParser(description="Workflow saklama: bitmiş koşuları arşivle ve kaldır (varsayılan kuru koşu)")
    p.add_argument("--gun", type=int, default=VARSAYILAN_GUN)
    p.add_argument("--uygula", action="store_true", help="gerçekten arşivle ve sil")
    a = p.parse_args(argv)
    try:
        rapor = calistir(gun=a.gun, uygula=a.uygula)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    print(json.dumps(rapor, ensure_ascii=False, indent=1))
    if not a.uygula:
        print(f"KURU KOŞU: {len(rapor['kosular'])} koşu, {len(rapor['sahipsiz_dosyalar'])} sahipsiz dosya kaldırılırdı. "
              "Uygulamak için --uygula.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
