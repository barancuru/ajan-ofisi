"""Ajan başına günlük token sayacı. Yalnız gerçek usage alanları; USD yalnız FIYATLAR'dan liste fiyatı tahmini.

Kalıcı dosya: durum/token-<YYYY-MM-DD>.json
  {"<ajan>": {"ofis": {4 alan}, "terminal": {4 alan}},          ← toplam görünüm (türetilir)
   "_kosular": {"<kosu_id>": {"ajan": .., "usage": {4 alan}}},   ← ofis koşusu başına (değiştirilerek yazılır)
   "_oturumlar": {"<session_id>": {"ajan": .., "usage": {..}, "ilk", "etiket", "model"}}}   ← terminal oturumu / hat koşusu başına
Kayıtlar "ekle" değil "yerine koy" ile yazılır: aynı koşu/oturum yeniden sayılırsa çift sayılmaz.
Süreçler arası (sunucu + kosucu) fcntl kilidiyle korunur.
"""
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime

import ortak

ALANLAR = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
KILIT = os.path.join(ortak.DURUM_DIZINI, "token.lock")

# API liste fiyatı, $ / milyon token: (giriş, çıkış, önbellek okuma). Önbelleğe yazma = giriş × ONBELLEK_YAZMA_KAT.
# Hat ve terminal koşularının USD tahmini YALNIZ bu tablodan gelir; fiyat değişince burayı güncelle (README: Maliyet).
FIYATLAR = {
    "claude-fable-5-2": (8.0, 40.0, 0.20),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),   # Antigravity üzerinden kullanıldı
}
KISA_MODEL = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
ONBELLEK_YAZMA_KAT = 1.25


def bos():
    return {k: 0 for k in ALANLAR}


def usage_al(u):
    """Ham usage sözlüğünden yalnız 4 sayısal alan."""
    u = u if isinstance(u, dict) else {}
    return {k: int(u.get(k) or 0) if isinstance(u.get(k), (int, float)) else 0 for k in ALANLAR}


def topla(*usagelar):
    t = bos()
    for u in usagelar:
        for k in ALANLAR:
            t[k] += int((u or {}).get(k) or 0)
    return t


def fiyat_bul(model):
    """Model kimliği (ör. claude-opus-5-5, claude-opus-5-5-20261001, opus) → FIYATLAR satırı; bilinmiyorsa None."""
    m = str(model or "").strip().lower()
    m = KISA_MODEL.get(m, m)
    for ad, fiyat in FIYATLAR.items():
        if m == ad or m.startswith(ad + "-") or m.startswith(ad + "["):
            return fiyat
    return None


def usd_tahmini(usage, model):
    """usage (4 alan) + model → API liste fiyatı eşdeğeri USD; model bilinmiyorsa None. Gerçek fatura değildir."""
    fiyat = fiyat_bul(model)
    if not fiyat:
        return None
    giris, cikis, okuma = fiyat
    u = usage_al(usage)
    usd = (u["input_tokens"] * giris + u["output_tokens"] * cikis + u["cache_read_input_tokens"] * okuma
           + u["cache_creation_input_tokens"] * giris * ONBELLEK_YAZMA_KAT) / 1_000_000
    return round(usd, 6)


class MesajTekil:
    """message.id ile tekilleştirir. Aynı id'li satırlar tekrar ederse yalnız artan fark sayılır."""

    def __init__(self):
        self.gorulen = {}
        self.toplam = bos()

    def isle(self, mesaj_id, usage):
        u = usage_al(usage)
        onceki = self.gorulen.get(mesaj_id, bos()) if mesaj_id else bos()
        yeni = {k: max(u[k], onceki[k]) for k in ALANLAR}
        fark = {k: yeni[k] - onceki[k] for k in ALANLAR}
        if mesaj_id:
            self.gorulen[mesaj_id] = yeni
        if not any(fark.values()):
            return False
        self.toplam = topla(self.toplam, fark)
        return True


def yol(tarih):
    return os.path.join(ortak.DURUM_DIZINI, f"token-{tarih}.json")


def _oku(tarih):
    try:
        with open(yol(tarih), encoding="utf-8") as f:
            veri = json.load(f)
        return veri if isinstance(veri, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@contextmanager
def _kilitli():
    os.makedirs(ortak.DURUM_DIZINI, exist_ok=True)
    with open(KILIT, "a") as k:
        fcntl.flock(k, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(k, fcntl.LOCK_UN)


def _ozet_kur(veri):
    """_kosular + _oturumlar → {ajan: {ofis, terminal}} görünümü."""
    ajanlar = {}
    for kaynak, anahtar in (("ofis", "_kosular"), ("terminal", "_oturumlar")):
        for kayit in (veri.get(anahtar) or {}).values():
            ajan = kayit.get("ajan")
            if not ajan:
                continue
            a = ajanlar.setdefault(ajan, {"ofis": bos(), "terminal": bos()})
            a[kaynak] = topla(a[kaynak], kayit.get("usage"), kayit.get("alt_usage"))   # alt-ajanlar ebeveyne eklenir
    return ajanlar


def _yaz(tarih, veri):
    temiz = {"_kosular": veri.get("_kosular") or {}, "_oturumlar": veri.get("_oturumlar") or {}}
    tam = {**_ozet_kur(temiz), **temiz}
    gecici = yol(tarih) + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(tam, f, ensure_ascii=False, indent=1)
    os.replace(gecici, yol(tarih))
    return tam


def kayit_koy(tarih, tur, anahtar, ajan, usage, etiket=None, model=None, alt_usage=None):
    """tur: '_kosular' | '_oturumlar'. Kaydı yerine koyar; ajanın o günkü {ofis, terminal} değerini döndürür.
    etiket/model (terminal oturumu adı, model kimliği) yalnız Maliyet tablosu için; metin içeriği değildir.
    alt_usage: oturumun alt-ajanlarının o günkü toplamı (verilmezse önceki korunur); ebeveynin toplamına eklenir."""
    with _kilitli():
        veri = _oku(tarih)
        bolum = dict(veri.get(tur) or {})
        onceki = bolum.get(anahtar) if isinstance(bolum.get(anahtar), dict) else {}
        kayit = {"ajan": ajan, "usage": usage_al(usage)}
        if tur == "_oturumlar":
            kayit["ilk"] = onceki.get("ilk") or ortak.simdi_iso()
            for ad, deger in (("etiket", etiket), ("model", model)):
                if isinstance(deger, str) and deger:
                    kayit[ad] = deger[:60]
                elif onceki.get(ad):
                    kayit[ad] = onceki[ad]
            alt = usage_al(alt_usage) if alt_usage is not None else onceki.get("alt_usage")
            if alt and any(alt.values()):
                kayit["alt_usage"] = usage_al(alt)
        bolum[anahtar] = kayit
        tam = _yaz(tarih, {**veri, tur: bolum})
    return tam.get(ajan, {"ofis": bos(), "terminal": bos()})


def kosu_eksikse_koy(tarih, kosu_id, ajan, usage):
    """Geçmiş koşuyu (olaylar.jsonl'den) yalnız dosyada yoksa ekler."""
    with _kilitli():
        veri = _oku(tarih)
        if kosu_id in (veri.get("_kosular") or {}):
            return False
        bolum = {**(veri.get("_kosular") or {}), kosu_id: {"ajan": ajan, "usage": usage_al(usage)}}
        _yaz(tarih, {**veri, "_kosular": bolum})
    return True


def gun_ozeti(tarih):
    veri = _oku(tarih)
    return _ozet_kur(veri)


def ajan_gun(tarih, ajan):
    return gun_ozeti(tarih).get(ajan, {"ofis": bos(), "terminal": bos()})


def disari(ajan_kaydi):
    """{ofis, terminal} → API biçimi."""
    o, t = ajan_kaydi.get("ofis") or bos(), ajan_kaydi.get("terminal") or bos()
    h = topla(o, t)
    return {"toplam": sum(h.values()), "girdi": h["input_tokens"], "cikti": h["output_tokens"],
            "onbellek_yazma": h["cache_creation_input_tokens"], "onbellek_okuma": h["cache_read_input_tokens"],
            "ofis_toplam": sum(o.values()), "terminal_toplam": sum(t.values())}


HAT_AJAN = "gelistirme-hatti"


def oturum_satirlari(tarih):
    """Maliyet tablosu için terminal oturumu başına satır (hat koşusu = bir oturum). Kaynak: hat | terminal.
    kullanim/toplam alt-ajanları içerir (alt_toplam ayrıca); usd_tahmini model bilinmiyorsa None.
    ilk/model/etiket'i boş eski satırlar (1.0.72 öncesi biçim) `eski: True` ile en alta gider."""
    satirlar = []
    for sid, k in (_oku(tarih).get("_oturumlar") or {}).items():
        if not isinstance(k, dict) or not k.get("ajan"):
            continue
        alt = usage_al(k.get("alt_usage"))
        u = topla(usage_al(k.get("usage")), alt)
        model = k.get("model") or ""
        satirlar.append({"oturum": str(sid)[:8], "ajan": k["ajan"], "kaynak": "hat" if k["ajan"] == HAT_AJAN else "terminal",
                         "etiket": k.get("etiket") or "", "model": model, "ilk": k.get("ilk") or "",
                         "kullanim": u, "toplam": sum(u.values()), "alt_toplam": sum(alt.values()),
                         "usd_tahmini": usd_tahmini(u, model) if model else None,
                         "eski": not (k.get("ilk") and model and k.get("etiket"))})
    return sorted(satirlar, key=lambda s: (s["eski"], s["ilk"]))


def tahmini_toplam(oturumlar, ofis_usd):
    """Maliyet özet kutuları: ofis (ölçülen), hat ≈, terminal ≈, toplam ≈ (USD; modeli bilinmeyen satır sayılmaz)."""
    t = {k: round(sum(s["usd_tahmini"] for s in oturumlar if s["kaynak"] == k and s.get("usd_tahmini") is not None), 6)
         for k in ("hat", "terminal")}
    t["ofis"] = round(float(ofis_usd or 0), 6)
    t["toplam"] = round(t["ofis"] + t["hat"] + t["terminal"], 6)
    return t


def api_yaniti():
    tarih = ortak.bugun()
    ajanlar = {a: disari(k) for a, k in gun_ozeti(tarih).items()}
    return {"tarih": tarih, "ajanlar": ajanlar, "genel_toplam": sum(a["toplam"] for a in ajanlar.values())}


def yerel_tarih(iso_zaman):
    """Transkript timestamp'i (UTC, 'Z') → yerel YYYY-MM-DD; çözülemezse None."""
    try:
        return datetime.fromisoformat(str(iso_zaman).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def olaylardan_geri_kur(olaylar):
    """Bugünkü kosu_bitti/ceo_bitti olaylarının usage'ını dosyada eksikse ekler (özellik öncesi koşular)."""
    tarih = ortak.bugun()
    for o in olaylar:
        if o.get("tur") not in ("kosu_bitti", "ceo_bitti") or not str(o.get("zaman", "")).startswith(tarih):
            continue
        if o.get("kosu_id") and o.get("ajan") and o.get("kullanim"):
            kosu_eksikse_koy(tarih, o["kosu_id"], o["ajan"], o["kullanim"])
