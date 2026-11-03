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


SSH_AD_DESENI = re.compile(r"[A-Za-z0-9._-]+")
SSH_VARSAYILAN_KNOWN_HOSTS = "~/.ssh/known_hosts"


def _ssh_liste(ajan_id, ssh, alan, mutlak=False):
    deger = ssh.get(alan)
    if deger is None:
        return
    if not isinstance(deger, list) or not all(isinstance(x, str) and x.strip() for x in deger):
        raise YapilandirmaHatasi(f"ajan {ajan_id}: ssh.{alan} boş olmayan metinlerden oluşan liste olmalı")
    if mutlak and not all(os.path.isabs(x) for x in deger):
        raise YapilandirmaHatasi(f"ajan {ajan_id}: ssh.{alan} mutlak yollardan oluşmalı")


def ssh_dogrula(ajan_id, ssh):
    """ajanlar.json'daki ajan başına isteğe bağlı 'ssh' bölümünü doğrular. Hata mesajları yol/değer içermez."""
    if not isinstance(ssh, dict):
        raise YapilandirmaHatasi(f"ajan {ajan_id}: ssh bir nesne olmalı")
    for alan in ("host", "user"):
        d = ssh.get(alan)
        if not isinstance(d, str) or not SSH_AD_DESENI.fullmatch(d) or d.startswith("-"):
            raise YapilandirmaHatasi(f"ajan {ajan_id}: ssh.{alan} geçersiz ([A-Za-z0-9._-]+ olmalı)")
    port = ssh.get("port", 22)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise YapilandirmaHatasi(f"ajan {ajan_id}: ssh.port 1-65535 arası tamsayı olmalı")
    for alan, bosluksuz in (("anahtar", False), ("known_hosts", True)):
        d = ssh.get(alan, SSH_VARSAYILAN_KNOWN_HOSTS if alan == "known_hosts" else None)
        if not isinstance(d, str) or not d or any(ord(c) < 32 or ord(c) == 127 for c in d) \
                or not os.path.isabs(os.path.expanduser(d)) or (bosluksuz and any(c.isspace() for c in d)):
            raise YapilandirmaHatasi(f"ajan {ajan_id}: ssh.{alan} geçersiz (mutlak dosya yolu olmalı)")
    _ssh_liste(ajan_id, ssh, "izinli_komutlar")
    _ssh_liste(ajan_id, ssh, "birebir_komutlar")
    _ssh_liste(ajan_id, ssh, "izinli_dizinler", mutlak=True)
    _ssh_liste(ajan_id, ssh, "onay_gerekli")


def maske_yollari(veri):
    """Maskelenecek anahtar yolları: tam yol, expanduser hali, dosya adı (uzunluk>=4); uzunlar önce."""
    kume = set()
    for ajan in (veri or {}).get("ajanlar", []):
        ssh = ajan.get("ssh") if isinstance(ajan, dict) else None
        yol = ssh.get("anahtar") if isinstance(ssh, dict) else None
        if isinstance(yol, str) and yol:
            kume.update({yol, os.path.expanduser(yol)})
            ad = os.path.basename(os.path.expanduser(yol))
            if len(ad) >= 4:
                kume.add(ad)
    return sorted(kume, key=len, reverse=True)


OZEL_ANAHTAR_DESENI = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)


def maskele(metin, yollar):
    """Özel anahtar bloklarını '[maskelendi]', anahtar yollarını '[anahtar-yolu]' yapar."""
    if not isinstance(metin, str):
        return metin
    metin = OZEL_ANAHTAR_DESENI.sub("[maskelendi]", metin)
    for y in yollar or []:
        metin = metin.replace(y, "[anahtar-yolu]")
    return metin


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
        if ajan.get("ssh") is not None:
            ssh_dogrula(ajan["id"], ajan["ssh"])
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
