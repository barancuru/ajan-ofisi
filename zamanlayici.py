"""Öngörülebilirlik: kullanıcının tekrar eden işleri (durum/tekrarlar.json) ve iş başına systemd timer'ı.

Yalnız stdlib. Sunucu her değişiklikte `durum/systemd/` altına birim dosyalarını üretir; `~/.config`'e YAZMAZ.
Kullanıcı bir kez `python3 zamanlayici.py --kur` çalıştırır: bir `.path` birimi `durum/systemd/.degisti`
değişince `--esle` ile birimleri `~/.config/systemd/user/`'a eşler (içerik her seferinde doğrulanmış
`tekrarlar.json`'dan yeniden üretilir; `durum/systemd/` dosyalarına güvenilmez). Timer `Persistent=true`:
kapalıyken kaçan çalışma açılışta en çok 1 kez koşar. Vakti gelince servis `--tetikle <id>` çalıştırır;
iş `gorev_baslat(havuz=True)` ile açılır (meşgulse alt ajan ya da kuyruk; çift koşu yok). Boşta model çağrılmaz.

    python3 zamanlayici.py --kur          # bir kez: eşleme birimlerini kur + şimdi eşle
    python3 zamanlayici.py --esle         # birimleri ~/.config/systemd/user/'a eşle
    python3 zamanlayici.py --tetikle <id> # systemd servisi çağırır
"""
import contextlib
import fcntl
import json
import os
import re
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timedelta

import ortak

MAKS_IS = 50
MIN_ARALIK_DK = 15
UYARI = "Tekrar eden işler yayın, mail, ödeme yapamaz."
TEKRAR_KILIDI = threading.Lock()
IS_ID_DESENI = re.compile(r"^t[0-9a-f]{10}$")
BIRIM_ON_EKI = "ajan-ofisi-tekrar-"
BIRIM_DESENI = re.compile(r"^ajan-ofisi-tekrar-t[0-9a-f]{10}\.(timer|service)$")
ESLE_BIRIMI = "ajan-ofisi-tekrar-esle"
_SIR_SINIF = r"[A-Za-z0-9+_-]"
SIR_DESENI = re.compile(
    r"(?i:\bsk-[A-Za-z0-9_-]{16,}|\bBearer\s|password\s*=|token\s*=)"
    r"|\b[0-9a-fA-F]{20,}\b"
    rf"|(?<!{_SIR_SINIF})(?={_SIR_SINIF}*\d)(?={_SIR_SINIF}*[a-z])(?={_SIR_SINIF}*[A-Z]){_SIR_SINIF}{{20,}}")


def tekrarlar_yolu():
    return os.path.join(ortak.DURUM_DIZINI, "tekrarlar.json")


def birim_dizini():
    return os.path.join(ortak.DURUM_DIZINI, "systemd")


@contextlib.contextmanager
def _kilit():
    """tekrarlar.json oku-değiştir-yaz: iş parçacıkları ve süreçler (sunucu + systemd servisi) arası."""
    with TEKRAR_KILIDI:
        os.makedirs(ortak.DURUM_DIZINI, exist_ok=True)
        fd = os.open(os.path.join(ortak.DURUM_DIZINI, "tekrarlar.lock"), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)


# ---------- cron ----------

_ALANLAR = [("dakika", 0, 59), ("saat", 0, 23), ("ay günü", 1, 31), ("ay", 1, 12), ("hafta günü", 0, 7)]


def _alan_coz(metin, ad, alt, ust):
    degerler = set()
    for parca in metin.split(","):
        m = re.fullmatch(r"(\*|\d{1,2}(?:-\d{1,2})?)(?:/(\d{1,2}))?", parca)
        if not m:
            raise ValueError(f"geçersiz cron {ad} alanı: {parca!r}")
        aralik, adim = m.group(1), int(m.group(2)) if m.group(2) else 1
        if adim < 1:
            raise ValueError(f"cron {ad} adımı en az 1 olmalı")
        if aralik == "*":
            a, b = alt, ust
        elif "-" in aralik:
            a, b = (int(x) for x in aralik.split("-"))
        else:
            a = b = int(aralik)
            if m.group(2):
                b = ust  # "a/n" = a'dan üst sınıra n adımla
        if not (alt <= a <= ust and alt <= b <= ust) or a > b:
            raise ValueError(f"cron {ad} alanı {alt}-{ust} arasında olmalı: {parca!r}")
        degerler.update(range(a, b + 1, adim))
    return degerler


def cron_coz(ifade):
    """5 alanlı cron → (dakikalar, saatler, ay_gunleri, aylar, hafta_gunleri, gun_kisitli, hafta_kisitli)."""
    if not isinstance(ifade, str):
        raise ValueError("cron ifadesi metin olmalı")
    alanlar = ifade.split()
    if len(alanlar) != 5:
        raise ValueError("cron 5 alan olmalı: dakika saat ay-günü ay hafta-günü")
    k = [_alan_coz(m, ad, alt, ust) for m, (ad, alt, ust) in zip(alanlar, _ALANLAR)]
    hg = {0 if g == 7 else g for g in k[4]}
    return (k[0], k[1], k[2], k[3], hg, alanlar[2] != "*", alanlar[4] != "*")


def _gun_eslesir(c, t):
    _, _, ag, ay, hg, gk, hk = c
    if t.month not in ay:
        return False
    gun_ok, hafta_ok = t.day in ag, (t.weekday() + 1) % 7 in hg  # cron: 0 = Pazar
    if gk and hk:
        return gun_ok or hafta_ok  # iki gün alanı da kısıtlıysa VEYA (klasik cron)
    return gun_ok and hafta_ok


def _eslesir(c, t):
    return t.minute in c[0] and t.hour in c[1] and _gun_eslesir(c, t)


def eslesir(ifade, t):
    return _eslesir(cron_coz(ifade), t)


def sonraki(ifade, simdi, c=None):
    """`simdi`den sonraki ilk çalışma dakikası (en fazla 366 gün ileri) ya da None."""
    c = c or cron_coz(ifade)
    dk, sa = sorted(c[0]), sorted(c[1])
    t = simdi.replace(second=0, microsecond=0) + timedelta(minutes=1)
    sinir = simdi + timedelta(days=366)
    gun = t.replace(hour=0, minute=0)
    while gun <= sinir:
        if _gun_eslesir(c, gun):
            for h in sa:
                for m in dk:
                    aday = gun.replace(hour=h, minute=m)
                    if aday >= t:
                        return aday if aday <= sinir else None
        gun += timedelta(days=1)
    return None


def sonrakiler(ifade, simdi, adet=3):
    c, sonuc, t = cron_coz(ifade), [], simdi
    for _ in range(adet):
        t = sonraki(ifade, t, c)
        if t is None:
            break
        sonuc.append(t)
    return sonuc


def en_kisa_aralik_dk(ifade):
    """Ardışık iki çalışma arasındaki en kısa süre (dakika); gece yarısı geçişi de sayılır."""
    c = cron_coz(ifade)
    gun_ici = [h * 60 + m for h in sorted(c[1]) for m in sorted(c[0])]
    en_kisa = min((b - a for a, b in zip(gun_ici, gun_ici[1:])), default=24 * 60)
    gece = 24 * 60 - gun_ici[-1] + gun_ici[0]
    if gece < en_kisa:
        bas = datetime(2000, 1, 1)
        if any(_gun_eslesir(c, bas + timedelta(days=i)) and _gun_eslesir(c, bas + timedelta(days=i + 1))
               for i in range(800)):
            en_kisa = gece
    return en_kisa


_HG_AD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _takvim_alani(degerler, alt, ust):
    if set(degerler) == set(range(alt, ust + 1)):
        return "*"
    return ",".join(f"{v:02d}" for v in sorted(degerler))


def oncalendar(ifade):
    """Cron → systemd `OnCalendar=`. Değerler açık listeye çevrilir (`*/n` kaymaz). Gün-VEYA kuralı
    (ay günü ve hafta günü ikisi de kısıtlı) systemd'de VE olduğundan çevrilemez: ValueError."""
    dk, sa, ag, ay, hg, gk, hk = cron_coz(ifade)
    if gk and hk:
        raise ValueError("ay günü ve hafta günü birlikte kısıtlı cron systemd'ye çevrilemez; birini * yap")
    gun = "" if not hk or hg == set(range(7)) else ",".join(_HG_AD[g] for g in sorted(hg)) + " "
    return (f"{gun}*-{_takvim_alani(ay, 1, 12)}-{_takvim_alani(ag, 1, 31)} "
            f"{_takvim_alani(sa, 0, 23)}:{_takvim_alani(dk, 0, 59)}:00")


def cron_dogrula(ifade):
    if not isinstance(ifade, str) or not ifade.strip():
        raise ValueError("cron ifadesi gerekli")
    ifade = " ".join(ifade.split())
    if len(ifade) > 100:
        raise ValueError("cron ifadesi çok uzun")
    if en_kisa_aralik_dk(ifade) < MIN_ARALIK_DK:
        raise ValueError(f"cron en sık {MIN_ARALIK_DK} dakikada bir çalışabilir")
    oncalendar(ifade)
    return ifade


_GUNLER = ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"]


def ozet(ifade):
    """Okunur kısa sıklık özeti (yaygın kalıplar; diğerlerinde cron'un kendisi)."""
    try:
        dk, sa, ag, ay, hg = ifade.split()
    except ValueError:
        return ifade
    if not dk.isdigit() or ay != "*":
        return ifade
    if sa == "*" and ag == "*" and hg == "*":
        return f"her saat :{int(dk):02d}"
    if not sa.isdigit():
        return ifade
    saat = f"{int(sa):02d}:{int(dk):02d}"
    if ag == "*" and hg == "*":
        return f"her gün {saat}"
    if ag == "*" and hg == "1-5":
        return f"hafta içi {saat}"
    if ag == "*" and hg.isdigit() and int(hg) <= 7:
        return f"her {_GUNLER[int(hg) % 7]} {saat}"
    if ag.isdigit() and hg == "*":
        return f"her ayın {int(ag)}. günü {saat}"
    return ifade


# ---------- doğrulama + depo ----------

def is_dogrula(ham, tablo):
    """Kullanıcı girdisi → temiz alanlar {ajan, etiket, prompt, cron}. Hata: ValueError (Türkçe)."""
    if not isinstance(ham, dict):
        raise ValueError("geçersiz iş")
    ajan_id = ham.get("ajan")
    ajan = tablo.get(ajan_id) if isinstance(ajan_id, str) else None
    if not ajan or ajan_id == "ceo":
        raise ValueError("bilinmeyen ajan")
    if not ajan.get("kurulu"):
        raise ValueError("ajan kurulmadı (klasör yok)")
    etiket, prompt = ham.get("etiket") or None, ham.get("prompt") or None
    if isinstance(prompt, str) and not prompt.strip():
        prompt = None
    if (etiket is None) == (prompt is None):
        raise ValueError("hazır görev ya da prompt'tan tam biri gerekli")
    if etiket is not None:
        if not isinstance(etiket, str) or etiket not in {g.get("etiket") for g in ajan.get("hazir_gorevler", [])}:
            raise ValueError("bilinmeyen hazır görev")
    else:
        if not isinstance(prompt, str):
            raise ValueError("prompt metin olmalı")
        prompt = prompt.strip()
        if len(prompt) > ortak.MAKS_GIRDI:
            raise ValueError(f"prompt en fazla {ortak.MAKS_GIRDI} karakter")
        if SIR_DESENI.search(prompt):
            raise ValueError("prompt'ta sır gibi görünen bir dizi var (anahtar/şifre/token); kaldır")
    return {"ajan": ajan_id, "etiket": etiket, "prompt": prompt, "cron": cron_dogrula(ham.get("cron"))}


def _yukle_ham():
    """Yapısal olarak geçerli kayıtlar. Bozuk dosya .bozuk-<zaman> olarak yana alınır, boş listeyle devam edilir."""
    yol = tekrarlar_yolu()
    try:
        with open(yol, encoding="utf-8") as f:
            veri = json.load(f)
        if not isinstance(veri, dict) or not isinstance(veri.get("isler"), list):
            raise ValueError("isler listesi yok")
    except FileNotFoundError:
        return []
    except (ValueError, OSError, UnicodeDecodeError) as e:
        try:
            os.replace(yol, f"{yol}.bozuk-{datetime.now():%Y%m%d-%H%M%S}")
        except OSError:
            pass
        try:
            ortak.olay_yaz({"tur": "hata", "ajan": "ofis",
                            "detay": f"tekrarlar.json bozuk, yana alındı ({type(e).__name__})"})
        except OSError:
            pass
        return []
    return [k for k in veri["isler"][:MAKS_IS]
            if isinstance(k, dict) and IS_ID_DESENI.match(str(k.get("id"))) and isinstance(k.get("cron"), str)]


def yukle(tablo):
    """Kalıcı işler, her biri doğrulanmış. Geçersiz kayıt silinmez; `hata` alanıyla döner ve koşmaz."""
    sonuc = []
    for k in _yukle_ham():
        try:
            alanlar, hata = is_dogrula(k, tablo), None
        except ValueError as e:
            alanlar = {"ajan": str(k.get("ajan"))[:40], "etiket": None, "prompt": None, "cron": str(k["cron"])[:100]}
            hata = str(e)
        sonuc.append({"id": k["id"], **alanlar, "aktif": k.get("aktif") is not False,
                      "olusturma": str(k.get("olusturma") or "")[:40],
                      "son_calisma": str(k["son_calisma"])[:40] if k.get("son_calisma") else None,
                      "son_sonuc": str(k["son_sonuc"])[:80] if k.get("son_sonuc") else None,
                      "hata": hata})
    return sonuc


def kaydet(isler):
    os.makedirs(ortak.DURUM_DIZINI, exist_ok=True)
    yol = tekrarlar_yolu()
    gecici = yol + ".ofis.tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump({"surum": 1, "isler": isler}, f, ensure_ascii=False, indent=1)
    os.replace(gecici, yol)


def degistir(veri, tablo):
    """islem: ekle | sil | ac | kapat. Dönüş: iş id. Hata: ValueError (Türkçe). Sonra birimleri yeniden üretir."""
    islem = veri.get("islem")
    if islem not in ("ekle", "sil", "ac", "kapat"):
        raise ValueError("islem: ekle | sil | ac | kapat | onizle")
    with _kilit():
        isler = _yukle_ham()
        if islem == "ekle":
            if len(isler) >= MAKS_IS:
                raise ValueError(f"en fazla {MAKS_IS} tekrar eden iş olabilir")
            alanlar = is_dogrula(veri, tablo)
            yeni = {"id": "t" + secrets.token_hex(5), **alanlar, "aktif": True, "olusturma": ortak.simdi_iso(),
                    "son_calisma": None, "son_sonuc": None}
            isler.append(yeni)
            kaydet(isler)
            birimleri_uret(tablo)
            ortak.olay_yaz({"tur": "tekrar_eklendi", "ajan": yeni["ajan"], "is_id": yeni["id"]})
            return yeni["id"]
        is_id = veri.get("id")
        if not isinstance(is_id, str) or not IS_ID_DESENI.match(is_id):
            raise ValueError("geçersiz iş id")
        k = next((k for k in isler if k.get("id") == is_id), None)
        if not k:
            raise ValueError("iş bulunamadı (sayfayı yenile)")
        if islem == "sil":
            isler.remove(k)
        else:
            k["aktif"] = islem == "ac"
        kaydet(isler)
        birimleri_uret(tablo)
        ortak.olay_yaz({"tur": "tekrar_" + {"sil": "silindi", "ac": "acildi", "kapat": "kapatildi"}[islem],
                        "ajan": str(k.get("ajan"))[:40], "is_id": is_id})
        return is_id


# ---------- systemd birimleri ----------

def _birim_yolu(metin):
    return metin.replace("%", "%%")  # systemd belirteç kaçışı


def birim_metinleri(is_id, takvim, kok=None, python=None):
    """Bir iş için {ad.timer: metin, ad.service: metin}. İçinde yalnız iş id'si ve takvim var; prompt yok."""
    if not IS_ID_DESENI.match(str(is_id)):
        raise ValueError("geçersiz iş id")
    if not re.fullmatch(r"[A-Za-z0-9*:,. -]{1,400}", takvim):
        raise ValueError("geçersiz takvim")
    kok, python = _birim_yolu(kok or ortak.KOK), _birim_yolu(python or sys.executable)
    ad = BIRIM_ON_EKI + is_id
    baslik = f"# Ajan Ofisi tekrar eden iş {is_id}. Üretilmiş dosya: zamanlayici.py --esle yeniden yazar.\n"
    timer = (f"{baslik}[Unit]\nDescription=Ajan Ofisi tekrar eden iş {is_id}\n\n"
             f"[Timer]\nOnCalendar={takvim}\nPersistent=true\nUnit={ad}.service\n\n"
             "[Install]\nWantedBy=timers.target\n")
    service = (f"{baslik}[Unit]\nDescription=Ajan Ofisi tekrar eden iş {is_id}\n\n"
               "[Service]\nType=oneshot\n"
               "KillMode=process\n"  # tmux sunucusunu bu servis açtıysa servis bitince öldürülmesin
               "Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin\n"
               "EnvironmentFile=-%h/.config/ofis-kapi/anthropic.env\n"  # yalnız yol; dosya yoksa servis yine başlar
               f"WorkingDirectory={kok}\n"
               f'ExecStart="{python}" "{kok}/zamanlayici.py" --tetikle {is_id}\n')
    return {f"{ad}.timer": timer, f"{ad}.service": service}


def birimler(isler):
    """Aktif ve geçerli işlerin birimleri."""
    sonuc = {}
    for k in isler:
        if k["aktif"] and not k["hata"]:
            sonuc.update(birim_metinleri(k["id"], oncalendar(k["cron"])))
    return sonuc


def _dizine_yaz(dizin, hedef):
    """Dizindeki ajan-ofisi-tekrar-* birimlerini tam olarak `hedef` yap. Başka dosyaya dokunmaz. Değişti mi?"""
    os.makedirs(dizin, exist_ok=True)
    degisti = False
    for ad in os.listdir(dizin):
        if BIRIM_DESENI.match(ad) and ad not in hedef:
            os.remove(os.path.join(dizin, ad))
            degisti = True
    for ad, metin in hedef.items():
        yol = os.path.join(dizin, ad)
        try:
            with open(yol, encoding="utf-8") as f:
                if f.read() == metin:
                    continue
        except FileNotFoundError:
            pass
        with open(yol + ".tmp", "w", encoding="utf-8") as f:
            f.write(metin)
        os.replace(yol + ".tmp", yol)
        degisti = True
    return degisti


def birimleri_uret(tablo):
    """durum/systemd/ altına birimleri yazar (önizleme + eşleme tetiği). ~/.config'e yazmaz."""
    if not _dizine_yaz(birim_dizini(), birimler(yukle(tablo))):
        return False
    with open(os.path.join(birim_dizini(), ".degisti"), "w", encoding="utf-8") as f:
        f.write(ortak.simdi_iso() + "\n")  # .path birimi bunu izler (yerinde yazma: IN_CLOSE_WRITE)
    return True


def _systemctl(*arg):
    return subprocess.run(["systemctl", "--user", *arg], capture_output=True, text=True, timeout=60)


def esle(hedef=None, systemctl=_systemctl):
    """Birimleri doğrulanmış tekrarlar.json'dan yeniden üretip hedefe eşler; fazlaları durdurup siler."""
    hedef = hedef or os.path.expanduser("~/.config/systemd/user")
    _, tablo = ortak.ajanlari_yukle()
    with _kilit():
        yeni = birimler(yukle(tablo))
    eski = {ad for ad in os.listdir(hedef) if BIRIM_DESENI.match(ad)} if os.path.isdir(hedef) else set()
    for ad in sorted(eski - set(yeni)):
        if ad.endswith(".timer"):
            systemctl("disable", "--now", ad)
    _dizine_yaz(hedef, yeni)
    systemctl("daemon-reload")
    zamanlar = sorted(a for a in yeni if a.endswith(".timer"))
    if zamanlar:
        systemctl("enable", "--now", *zamanlar)
    return zamanlar


def kur(hedef=None, systemctl=_systemctl):
    """Kullanıcının bir kez çalıştırdığı kurulum: durum/systemd/.degisti'yi izleyen .path + eşleme servisi."""
    hedef = hedef or os.path.expanduser("~/.config/systemd/user")
    os.makedirs(hedef, exist_ok=True)
    os.makedirs(birim_dizini(), exist_ok=True)
    damga = os.path.join(birim_dizini(), ".degisti")
    if not os.path.exists(damga):
        with open(damga, "w", encoding="utf-8") as f:
            f.write(ortak.simdi_iso() + "\n")
    kok, python = _birim_yolu(ortak.KOK), _birim_yolu(sys.executable)
    metinler = {
        f"{ESLE_BIRIMI}.path": ("[Unit]\nDescription=Ajan Ofisi tekrar eden işleri systemd ile eşle\n\n"
                                f"[Path]\nPathChanged={_birim_yolu(damga)}\nUnit={ESLE_BIRIMI}.service\n\n"
                                "[Install]\nWantedBy=default.target\n"),
        f"{ESLE_BIRIMI}.service": ("[Unit]\nDescription=Ajan Ofisi tekrar eden işleri systemd ile eşle\n\n"
                                   f"[Service]\nType=oneshot\nWorkingDirectory={kok}\n"
                                   f'ExecStart="{python}" "{kok}/zamanlayici.py" --esle\n'),
    }
    for ad, metin in metinler.items():
        with open(os.path.join(hedef, ad), "w", encoding="utf-8") as f:
            f.write(metin)
    systemctl("daemon-reload")
    systemctl("enable", "--now", f"{ESLE_BIRIMI}.path")
    return esle(hedef, systemctl)


# ---------- tetik (systemd servisi) ----------

def tetikle(is_id, baslatici, simdi=None, tablo_yukle=None):
    """Tek bir işi bir kez başlatır. `baslatici(ajan, etiket, prompt, kaynak)` → gorev_baslat yanıtı.
    Aynı dakikada ikinci tetik koşmaz. Meşgulde çift koşu açılmaz (alt ajan / kuyruk / atlandı). Sonucu döndürür."""
    if not isinstance(is_id, str) or not IS_ID_DESENI.match(is_id):
        raise ValueError("geçersiz iş id")
    damga = (simdi or datetime.now()).strftime("%Y-%m-%dT%H:%M")
    tablo = (tablo_yukle or (lambda: ortak.ajanlari_yukle()[1]))()
    with _kilit():
        k = next((k for k in yukle(tablo) if k["id"] == is_id), None)
        if not k or k["hata"] or not k["aktif"] or k["son_calisma"] == damga:
            return None
        _alan_yaz(is_id, son_calisma=damga)  # önce damga: aynı dakikada ikinci tetik ya da hata sonrası tekrar yok
    try:
        y = baslatici(k["ajan"], k["etiket"], k["prompt"], "tekrar")
        y = y if isinstance(y, dict) else {}
        sonuc = "kuyrukta" if y.get("kuyrukta") else "basladi (alt ajan)" if y.get("alt") else "basladi"
    except Exception as e:  # noqa: BLE001 - ayrıntıda prompt/sır yok
        kod = getattr(e, "kod", None)
        sonuc = ("atlandi: mesgul" if kod == 409 and "çalışıyor" in str(e)
                 else "atlandi: kuyruk dolu" if kod == 429 else "hata")
    with _kilit():
        _alan_yaz(is_id, son_sonuc=sonuc)
    try:
        ortak.olay_yaz({"tur": "tekrar_tetiklendi", "ajan": k["ajan"], "is_id": is_id, "sonuc": sonuc})
    except OSError:
        pass
    return sonuc


def _alan_yaz(is_id, **alanlar):
    isler = _yukle_ham()
    for g in isler:
        if g["id"] == is_id:
            g.update(alanlar)
    kaydet(isler)


def main(argv):
    if len(argv) == 2 and argv[0] == "--tetikle":
        import sunucu  # sunucu sürecine değil, bu servis sürecine yüklenir (HTTP açılmaz)
        sonuc = tetikle(argv[1], lambda a, e, p, k: sunucu.gorev_baslat(a, etiket=e, prompt=p, kaynak=k, havuz=True))
        try:
            sunucu.kuyrugu_isle()
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"kuyruk: {type(e).__name__}\n")
        print(f"tekrar {argv[1]}: {sonuc or 'koşmadı (kapalı, geçersiz ya da bu dakika koştu)'}")
        return 0
    if argv == ["--esle"]:
        print("eşlendi:", " ".join(esle()) or "(iş yok)")
        return 0
    if argv == ["--kur"]:
        print("kuruldu; eşlenen:", " ".join(kur()) or "(iş yok)")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
