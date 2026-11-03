"""Öngörülebilirlik: kullanıcının tekrar eden işleri (durum/tekrarlar.json) ve sunucu içi hafif zamanlayıcı.

Yalnız stdlib. İş parçacığı yalnız saat okur; model çağırmaz. Vakti gelen iş, sunucunun `gorev_baslat`
fonksiyonuyla (meşgul kontrolü + kosucu.py kilidi) koşar. Sunucu kapalıyken kaçan koşular telafi edilmez.
"""
import json
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta

import ortak

MAKS_IS = 50
MIN_ARALIK_DK = 15
UYANMA_SN = 30
UYARI = "Tekrar eden işler yayın, mail, ödeme yapamaz."
TEKRAR_KILIDI = threading.Lock()
IS_ID_DESENI = re.compile(r"^t[0-9a-f]{10}$")
_SIR_SINIF = r"[A-Za-z0-9+_-]"
SIR_DESENI = re.compile(
    r"(?i:\bsk-[A-Za-z0-9_-]{16,}|\bBearer\s|password\s*=|token\s*=)"
    r"|\b[0-9a-fA-F]{20,}\b"
    rf"|(?<!{_SIR_SINIF})(?={_SIR_SINIF}*\d)(?={_SIR_SINIF}*[a-z])(?={_SIR_SINIF}*[A-Z]){_SIR_SINIF}{{20,}}")


def tekrarlar_yolu():
    return os.path.join(ortak.DURUM_DIZINI, "tekrarlar.json")


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


def cron_dogrula(ifade):
    if not isinstance(ifade, str) or not ifade.strip():
        raise ValueError("cron ifadesi gerekli")
    ifade = " ".join(ifade.split())
    if len(ifade) > 100:
        raise ValueError("cron ifadesi çok uzun")
    if en_kisa_aralik_dk(ifade) < MIN_ARALIK_DK:
        raise ValueError(f"cron en sık {MIN_ARALIK_DK} dakikada bir çalışabilir")
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
    """islem: ekle | sil | ac | kapat. Dönüş: iş id. Hata: ValueError (Türkçe)."""
    islem = veri.get("islem")
    if islem not in ("ekle", "sil", "ac", "kapat"):
        raise ValueError("islem: ekle | sil | ac | kapat | onizle")
    with TEKRAR_KILIDI:
        isler = _yukle_ham()
        if islem == "ekle":
            if len(isler) >= MAKS_IS:
                raise ValueError(f"en fazla {MAKS_IS} tekrar eden iş olabilir")
            alanlar = is_dogrula(veri, tablo)
            yeni = {"id": "t" + secrets.token_hex(5), **alanlar, "aktif": True, "olusturma": ortak.simdi_iso(),
                    "son_calisma": None, "son_sonuc": None}
            isler.append(yeni)
            kaydet(isler)
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
        ortak.olay_yaz({"tur": "tekrar_" + {"sil": "silindi", "ac": "acildi", "kapat": "kapatildi"}[islem],
                        "ajan": str(k.get("ajan"))[:40], "is_id": is_id})
        return is_id


# ---------- zamanlayıcı ----------

def tik(baslatici, simdi=None, tablo_yukle=None):
    """Bu dakika eşleşen aktif işleri bir kez başlatır. `baslatici(ajan, etiket, prompt, kaynak)`.
    Ajan meşgulse (409 'çalışıyor') çift koşu açmaz, 'atlandi: mesgul' yazar. Başlatılan iş id'lerini döndürür."""
    simdi = (simdi or datetime.now()).replace(second=0, microsecond=0)
    damga = simdi.strftime("%Y-%m-%dT%H:%M")
    if not os.path.exists(tekrarlar_yolu()):
        return []  # hiç iş yok: başka hiçbir şey okunmaz
    tablo = (tablo_yukle or (lambda: ortak.ajanlari_yukle()[1]))()
    with TEKRAR_KILIDI:
        gecerli = {k["id"] for k in yukle(tablo) if not k["hata"]}
        isler = _yukle_ham()
        vakti_gelen = [k for k in isler if k["id"] in gecerli and k.get("aktif") is not False
                       and k.get("son_calisma") != damga and eslesir(k["cron"], simdi)]
        if not vakti_gelen:
            return []
        for k in vakti_gelen:
            k["son_calisma"] = damga  # önce damga: aynı dakikada ikinci tik ya da hata sonrası tekrar yok
        kaydet(isler)
    baslayan = []
    for k in vakti_gelen:
        try:
            baslatici(k["ajan"], k.get("etiket"), k.get("prompt"), "tekrar")
            sonuc = "basladi"
            baslayan.append(k["id"])
        except Exception as e:  # noqa: BLE001 - ayrıntıda prompt/sır yok
            sonuc = "atlandi: mesgul" if getattr(e, "kod", None) == 409 and "çalışıyor" in str(e) else "hata"
        with TEKRAR_KILIDI:
            guncel = _yukle_ham()
            for g in guncel:
                if g["id"] == k["id"]:
                    g["son_sonuc"] = sonuc
            kaydet(guncel)
        try:
            ortak.olay_yaz({"tur": "tekrar_tetiklendi", "ajan": k["ajan"], "is_id": k["id"], "sonuc": sonuc})
        except OSError:
            pass
    return baslayan


def baslat(baslatici):
    """Daemon iş parçacığı: her 30 sn uyanır, yalnız saat karşılaştırır."""
    def dongu():
        while True:
            try:
                tik(baslatici)
            except Exception as e:  # noqa: BLE001 - zamanlayıcı sunucuyu düşürmesin
                sys.stderr.write(f"zamanlayıcı: {type(e).__name__}\n")
            time.sleep(UYANMA_SN - time.time() % UYANMA_SN + 0.5)
    t = threading.Thread(target=dongu, name="zamanlayici", daemon=True)
    t.start()
    return t
