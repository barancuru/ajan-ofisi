"""Ajan Ofisi ortak yardımcıları: yollar, ajan tablosu, olay günlüğü, durum dosyaları."""
import contextlib
import fcntl
import json
import os
import re
import time
from datetime import datetime, timezone

KOK = os.path.dirname(os.path.abspath(__file__))
# Yapılandırma: ajanlar.example.json'ı ajanlar.json olarak kopyala (ajanlar.json .gitignore'da).
AJANLAR_DOSYASI = os.environ.get("OFIS_AJANLAR", os.path.join(KOK, "ajanlar.json"))
OLAYLAR = os.path.join(KOK, "olaylar.jsonl")
DURUM_DIZINI = os.path.join(KOK, "durum")
KOSU_DIZINI = os.path.join(KOK, "kosular")
CIKTI_DIZINI = os.path.join(KOK, "cikti")
HAFIZA_DIZINI = os.path.join(KOK, "hafiza")

MAKS_GIRDI = 4000
MAKS_HAFIZA_EKI = 1200
AJAN_ID_DESENI = re.compile(r"^[a-z0-9-]{1,40}$")
# Oda id'si serbest (sahnede yoksa otomatik açılır) ama prompt'a ve olaylara girdiği için harf/rakam/_/- ve en çok 40 karakter.
ODA_ID_DESENI = re.compile(r"[\w-]{1,40}")


def simdi_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def bugun():
    return datetime.now().strftime("%Y-%m-%d")


class YapilandirmaHatasi(Exception):
    pass


def ajanlari_yukle():
    try:
        with open(AJANLAR_DOSYASI, encoding="utf-8") as f:
            veri = json.load(f)
    except FileNotFoundError as e:
        raise YapilandirmaHatasi(
            f"{os.path.basename(AJANLAR_DOSYASI)} yok. Önce: cp ajanlar.example.json ajanlar.json") from e
    if not isinstance(veri, dict) or not isinstance(veri.get("ajanlar"), list):
        raise YapilandirmaHatasi("ajanlar.json içinde 'ajanlar' listesi olmalı")
    tablo = {}
    for ajan in veri["ajanlar"]:
        if not AJAN_ID_DESENI.match(ajan["id"]):
            raise ValueError(f"geçersiz ajan id: {ajan['id']!r}")
        oda = ajan.get("oda") or "genel"
        if not isinstance(oda, str) or not ODA_ID_DESENI.fullmatch(oda):
            raise ValueError(f"geçersiz oda id: {oda!r} (ajan {ajan['id']})")
        kurulu = os.path.isdir(os.path.expanduser(ajan.get("cwd") or ""))
        tablo[ajan["id"]] = {**ajan, "oda": oda, "cwd": os.path.expanduser(ajan.get("cwd") or ""), "kurulu": kurulu}
    return veri, tablo


def ayarlar(veri):
    """Arayüz ayarları: kullanıcı adı (selamlama) ve marka. İkisi de isteğe bağlı."""
    a = veri.get("ayarlar") if isinstance(veri.get("ayarlar"), dict) else {}
    return {"kullanici": str(a.get("kullanici") or "")[:40], "marka": str(a.get("marka") or "Ajan Ofisi")[:40]}


OLAY_MAKS_BAYT = 20 * 1024 * 1024  # bu boyutu aşınca olaylar.jsonl -> olaylar.jsonl.1


def olay_yaz(olay):
    """olaylar.jsonl'e tek satır ekler (süreçler arası kilitli). Dosya OLAY_MAKS_BAYT'ı aşarsa .1'e döndürür."""
    satir = json.dumps({"zaman": simdi_iso(), **olay}, ensure_ascii=False)
    for _ in range(5):
        with open(OLAYLAR, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                try:
                    if os.fstat(f.fileno()).st_ino != os.stat(OLAYLAR).st_ino:
                        continue  # başka süreç bu arada döndürdü: yeni dosyayı açıp yeniden dene
                except FileNotFoundError:
                    continue
                if os.fstat(f.fileno()).st_size >= OLAY_MAKS_BAYT:
                    os.replace(OLAYLAR, OLAYLAR + ".1")
                    continue
                f.write(satir + "\n")
                f.flush()
                return
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    raise OSError("olaylar.jsonl yazılamadı (döndürme yarışı)")


def _satir_tarihi(satir):
    m = re.match(rb'\{"zaman": "(\d{4}-\d\d-\d\d)', satir)
    return m.group(1).decode() if m else None


def bugunun_satirlari(yol, tarih):
    """Dosyayı sondan okuyup zaman'ı `tarih`ten (YYYY-MM-DD) önce olmayan satırları (bayt) döndürür.
    Büyük dosyada yalnız sondaki parçaları okur. İkinci dönüş: dosyanın başına kadar inildi mi."""
    try:
        with open(yol, "rb") as f:
            konum = f.seek(0, os.SEEK_END)
            tampon = b""
            while konum > 0:
                oku = min(1 << 20, konum)
                konum -= oku
                f.seek(konum)
                tampon = f.read(oku) + tampon
                if konum > 0:
                    satirlar = tampon.split(b"\n", 2)
                    if len(satirlar) > 2:  # satirlar[0] yarım olabilir; ikincisi tam satır
                        t = _satir_tarihi(satirlar[1])
                        if t is not None and t < tarih:
                            break
    except FileNotFoundError:
        return [], False
    satirlar = tampon.split(b"\n")
    if konum > 0:
        satirlar = satirlar[1:]  # baştaki yarım satır
    sonuc = [s for s in satirlar if s.strip() and (_satir_tarihi(s) or tarih) >= tarih]
    return sonuc, konum == 0


@contextlib.contextmanager
def hafiza_kilidi(ajan_id):
    """hafiza/<ajan>.lock üzerinde süreçler arası özel kilit (oku-değiştir-yaz ve ekleme için)."""
    if not AJAN_ID_DESENI.match(str(ajan_id)):
        raise ValueError(f"geçersiz ajan id: {ajan_id!r}")
    os.makedirs(HAFIZA_DIZINI, exist_ok=True)
    fd = os.open(os.path.join(HAFIZA_DIZINI, f"{ajan_id}.lock"), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # kapatmak kilidi de bırakır


@contextlib.contextmanager
def baslatma_kilidi():
    """durum/baslatma.lock: Ofis sunucusu ve systemd tekrar servisi koşu açma kararını (meşgul/alt/kuyruk) sırayla verir."""
    os.makedirs(DURUM_DIZINI, exist_ok=True)
    fd = os.open(os.path.join(DURUM_DIZINI, "baslatma.lock"), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def durum_yolu(ajan_id):
    return os.path.join(DURUM_DIZINI, f"{ajan_id}.json")


def durum_oku(ajan_id):
    try:
        with open(durum_yolu(ajan_id), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def durum_yaz(ajan_id, durum):
    gecici = durum_yolu(ajan_id) + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(durum, f, ensure_ascii=False, indent=1)
    os.replace(gecici, durum_yolu(ajan_id))


def surec_yasiyor(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def ajan_mesgul(ajan_id):
    """Ajan şu an koşuyor mu? Ölü süreçten kalan 'calisiyor' kaydını meşgul saymaz."""
    d = durum_oku(ajan_id)
    if not d or d.get("durum") not in ("basliyor", "calisiyor"):
        return False
    if surec_yasiyor(d.get("pid")):
        return True
    # tmux penceresi açılırken pid henüz yazılmamış olabilir
    return d.get("durum") == "basliyor" and time.time() - d.get("baslangic_ts", 0) < 30
