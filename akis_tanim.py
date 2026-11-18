"""Workflow (akış) tanımları: akislar/<id>.json yükleme ve şema doğrulaması. Yalnız stdlib.

Tanımlar depoda sürüm kontrollüdür; API'den tanım gövdesi kabul edilmez (yalnız id ile başlatılır).
Doğrulama, döngü kenarı (dongu) dışında grafiğin döngüsüz olmasını ister: her döngü sayaçlı ve sınırlıdır.
"""
import hashlib
import json
import os
import re

import ortak

TANIM_DIZINI = os.environ.get("OFIS_AKISLAR") or os.path.join(ortak.KOK, "akislar")   # kabul testi: ayrı tanım klasörü
SEMA_SURUMU = 1
ID_DESENI = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
ADIM_TURLERI = ("agent_task", "gelistirme_gorevi", "quality_gate", "condition", "approval", "end")
INCELEME = "@inceleme"   # özel hedef: koşu PAUSED / manual_review
MAKS_ADIM = 30
MAKS_SABLON = 8000
MAKS_KONTROL = 10

VARSAYILAN_SINIRLAR = {"max_iterasyon": 3, "max_ajan_cagrisi": 10, "max_sure_sn": 6 * 3600, "max_maliyet_usd": 5.0}
SINIR_TAVANLARI = {"max_iterasyon": 10, "max_ajan_cagrisi": 50, "max_sure_sn": 7 * 24 * 3600, "max_maliyet_usd": 100.0}
HATA_EYLEMLERI = ("retry", "pause", "fail", "loop")
ONAY_KATEGORILERI = ("genel", "dagitim", "yayin", "odeme", "posta", "guvenlik")
HASSAS_KATEGORILER = ("dagitim", "yayin", "odeme", "posta", "guvenlik")   # her zaman ofis girişi (kapı) ister
OPERATORLER = ("eq", "ne", "in", "not_in", "lt", "le", "gt", "ge", "var")
ALAN_TURLERI = ("metin", "secim", "sayi", "evet_hayir")
MODELLER = ("haiku", "sonnet", "opus")
GELISTIRME_PROJELERI = ("homeos", "turnusol", "ajan-ofisi")

# Kalite kapısı komutları: shell yok, yalnız bu çalıştırılabilirler. python3 yalnız ofisin kendi kapı betiğini koşar.
KAPI_KOMUTLARI = ("git", "php", "sha256sum", "python3", "test")
KAPI_YER_TUTUCULAR = ("worktree", "taban", "paket", "paket_sha", "yayin", "ofis")
KAPI_CWD = ("{worktree}", "{yayin}", "{ofis}")
YER_TUTUCU = re.compile(r"\{([a-z_]+)\}")

# Yerleşik adım çıktıları (agent_task kendi cikti_alanlari'nı bildirir)
YERLESIK_CIKTILAR = {
    "gelistirme_gorevi": {"durum": "secim", "surum": "metin", "dal": "metin", "sha256": "metin", "uyari": "sayi",
                          "dosya": "metin", "rapor": "metin"},
    "quality_gate": {"gecti": "evet_hayir", "rapor": "metin"},
    "approval": {"karar": "secim", "not": "metin"},
    "condition": {"sonuc": "evet_hayir"},
    "end": {},
}
SABLON_REF = re.compile(r"\{\{\s*([a-z0-9_.-]+)\s*\}\}")


class TanimHatasi(Exception):
    pass


def _id(deger, ne):
    if not isinstance(deger, str) or not ID_DESENI.match(deger):
        raise TanimHatasi(f"{ne}: geçersiz id (küçük harf, rakam, _ ve -, en çok 40)")
    return deger


def _metin(deger, ne, maks, zorunlu=True):
    if deger is None and not zorunlu:
        return None
    if not isinstance(deger, str) or not deger.strip() or len(deger) > maks:
        raise TanimHatasi(f"{ne}: boş olmayan metin, en çok {maks} karakter")
    return deger


def _bilinmeyen_anahtar(sozluk, izinli, ne):
    fazla = set(sozluk) - set(izinli)
    if fazla:
        raise TanimHatasi(f"{ne}: bilinmeyen alan(lar): {', '.join(sorted(fazla))}")


def _gecis(deger, ne, liste_olabilir=False):
    """Geçiş → [{"hedef": id|@inceleme, "dongu": ad|None}]. None → []."""
    if deger is None:
        return []
    if isinstance(deger, list):
        if not liste_olabilir or not deger:
            raise TanimHatasi(f"{ne}: liste burada kullanılamaz")
        return [g for d in deger for g in _gecis(d, ne)]
    if isinstance(deger, str):
        return [{"hedef": deger if deger == INCELEME else _id(deger, ne), "dongu": None}]
    if isinstance(deger, dict):
        _bilinmeyen_anahtar(deger, ("hedef", "dongu"), ne)
        hedef = deger.get("hedef")
        hedef = hedef if hedef == INCELEME else _id(hedef, ne)
        dongu = deger.get("dongu")
        return [{"hedef": hedef, "dongu": _id(dongu, ne + ".dongu") if dongu is not None else None}]
    raise TanimHatasi(f"{ne}: geçiş adım id'si, '@inceleme' ya da {{hedef, dongu}} olmalı")


def _alanlar(deger, ne):
    if deger is None:
        return {}
    if not isinstance(deger, dict) or len(deger) > 12:
        raise TanimHatasi(f"{ne}: en çok 12 alanlı nesne")
    sonuc = {}
    for ad, t in deger.items():
        _id(ad, f"{ne}.{ad}")
        if not isinstance(t, dict):
            raise TanimHatasi(f"{ne}.{ad}: nesne olmalı")
        _bilinmeyen_anahtar(t, ("tur", "maks", "secenekler", "zorunlu", "aciklama"), f"{ne}.{ad}")
        tur = t.get("tur", "metin")
        if tur not in ALAN_TURLERI:
            raise TanimHatasi(f"{ne}.{ad}: tur {ALAN_TURLERI} olmalı")
        n = {"tur": tur, "zorunlu": t.get("zorunlu", True) is not False}
        if tur == "metin":
            maks = t.get("maks", 2000)
            if isinstance(maks, bool) or not isinstance(maks, int) or not 1 <= maks <= 8000:
                raise TanimHatasi(f"{ne}.{ad}: maks 1–8000")
            n["maks"] = maks
        if tur == "secim":
            s = t.get("secenekler")
            if not isinstance(s, list) or not s or len(s) > 12 or not all(isinstance(x, str) and 0 < len(x) <= 40 for x in s):
                raise TanimHatasi(f"{ne}.{ad}: secenekler 1–12 kısa metin")
            n["secenekler"] = list(s)
        if t.get("aciklama") is not None:
            n["aciklama"] = _metin(t["aciklama"], f"{ne}.{ad}.aciklama", 300)
        sonuc[ad] = n
    return sonuc


def _sayi(deger, ne, alt, ust, tam=True):
    if isinstance(deger, bool) or not isinstance(deger, (int,) if tam else (int, float)) or not alt <= deger <= ust:
        raise TanimHatasi(f"{ne}: {alt}–{ust} arası {'tamsayı' if tam else 'sayı'}")
    return deger


def _hata_politikasi(deger, ne):
    if deger is None:
        return {"eylem": "pause", "max_deneme": 1, "geri_cekilme_sn": 30, "geri_cekilme_maks_sn": 1800,
                "tukenince": "pause", "hedef": []}
    if not isinstance(deger, dict):
        raise TanimHatasi(f"{ne}: nesne olmalı")
    _bilinmeyen_anahtar(deger, ("eylem", "max_deneme", "geri_cekilme_sn", "geri_cekilme_maks_sn", "tukenince", "hedef"), ne)
    eylem = deger.get("eylem", "pause")
    if eylem not in HATA_EYLEMLERI:
        raise TanimHatasi(f"{ne}.eylem: {HATA_EYLEMLERI}")
    p = {"eylem": eylem,
         "max_deneme": _sayi(deger.get("max_deneme", 3 if eylem == "retry" else 1), f"{ne}.max_deneme", 1, 10),
         "geri_cekilme_sn": _sayi(deger.get("geri_cekilme_sn", 30), f"{ne}.geri_cekilme_sn", 1, 3600),
         "geri_cekilme_maks_sn": _sayi(deger.get("geri_cekilme_maks_sn", 1800), f"{ne}.geri_cekilme_maks_sn", 1, 86400),
         "tukenince": deger.get("tukenince", "pause"),
         "hedef": _gecis(deger.get("hedef"), f"{ne}.hedef")}
    if p["tukenince"] not in ("pause", "fail"):
        raise TanimHatasi(f"{ne}.tukenince: pause | fail")
    if eylem == "loop" and (len(p["hedef"]) != 1 or not p["hedef"][0]["dongu"]):
        raise TanimHatasi(f"{ne}: loop eylemi {{hedef, dongu}} ister")
    return p


def _kosullar(deger, ne):
    if not isinstance(deger, list) or not deger or len(deger) > 10:
        raise TanimHatasi(f"{ne}: 1–10 koşul listesi")
    sonuc = []
    for i, k in enumerate(deger):
        if not isinstance(k, dict):
            raise TanimHatasi(f"{ne}[{i}]: nesne olmalı")
        _bilinmeyen_anahtar(k, ("alan", "op", "deger"), f"{ne}[{i}]")
        if not isinstance(k.get("alan"), str) or not re.fullmatch(r"(girdi\.[a-z0-9_-]+|adim\.[a-z0-9_-]+\.[a-z0-9_-]+)", k["alan"]):
            raise TanimHatasi(f"{ne}[{i}].alan: girdi.<ad> ya da adim.<id>.<alan>")
        if k.get("op") not in OPERATORLER:
            raise TanimHatasi(f"{ne}[{i}].op: {OPERATORLER}")
        if k["op"] in ("in", "not_in") and not isinstance(k.get("deger"), list):
            raise TanimHatasi(f"{ne}[{i}].deger: liste olmalı")
        sonuc.append({"alan": k["alan"], "op": k["op"], "deger": k.get("deger")})
    return sonuc


def _kontroller(deger, ne):
    if deger is None:
        return []
    if not isinstance(deger, list) or len(deger) > MAKS_KONTROL:
        raise TanimHatasi(f"{ne}: en çok {MAKS_KONTROL} kontrol")
    sonuc = []
    for i, k in enumerate(deger):
        n = f"{ne}[{i}]"
        if not isinstance(k, dict):
            raise TanimHatasi(f"{n}: nesne olmalı")
        _bilinmeyen_anahtar(k, ("ad", "komut", "cwd", "zaman_asimi_sn", "beklenen_cikis"), n)
        komut = k.get("komut")
        if not isinstance(komut, list) or not komut or len(komut) > 20 or \
                not all(isinstance(x, str) and 0 < len(x) <= 300 and "\x00" not in x for x in komut):
            raise TanimHatasi(f"{n}.komut: 1–20 öğelik argv listesi")
        if komut[0] not in KAPI_KOMUTLARI:
            raise TanimHatasi(f"{n}.komut: yalnız {KAPI_KOMUTLARI}")
        if komut[0] == "python3" and (len(komut) < 2 or komut[1] != "{ofis}/akis_kapi.py"):
            raise TanimHatasi(f"{n}.komut: python3 yalnız {{ofis}}/akis_kapi.py çalıştırabilir")
        for x in komut:
            for ad in YER_TUTUCU.findall(x):
                if ad not in KAPI_YER_TUTUCULAR:
                    raise TanimHatasi(f"{n}.komut: bilinmeyen yer tutucu {{{ad}}}")
        cwd = k.get("cwd", "{worktree}")
        if cwd not in KAPI_CWD:
            raise TanimHatasi(f"{n}.cwd: {KAPI_CWD}")
        sonuc.append({"ad": _metin(k.get("ad"), f"{n}.ad", 80), "komut": list(komut), "cwd": cwd,
                      "zaman_asimi_sn": _sayi(k.get("zaman_asimi_sn", 300), f"{n}.zaman_asimi_sn", 1, 1800),
                      "beklenen_cikis": _sayi(k.get("beklenen_cikis", 0), f"{n}.beklenen_cikis", 0, 255)})
    return sonuc


def _adim(ham, ne):
    if not isinstance(ham, dict):
        raise TanimHatasi(f"{ne}: nesne olmalı")
    tur = ham.get("tur")
    if tur not in ADIM_TURLERI:
        raise TanimHatasi(f"{ne}.tur: {ADIM_TURLERI}")
    ortak_alanlar = ("id", "tur", "ad", "sonraki", "bagimli", "hata", "zaman_asimi_sn")
    ozel = {
        "agent_task": ("ajan", "gorev", "model", "cikti_alanlari", "yan_etkili", "tahmini_usd"),
        "gelistirme_gorevi": ("mod", "proje", "baslik", "istek", "model", "hedef_adim", "geri_bildirim", "tahmini_usd"),
        "quality_gate": ("kontroller", "kosullar", "kaynak_adim", "basarisizsa"),
        "condition": ("kosullar", "dogru", "yanlis"),
        "approval": ("kategori", "mesaj", "izle_adim", "reddedilirse"),
        "end": ("sonuc",),
    }[tur]
    _bilinmeyen_anahtar(ham, ortak_alanlar + ozel, ne)
    a = {"id": _id(ham.get("id"), f"{ne}.id"), "tur": tur, "ad": _metin(ham.get("ad") or ham.get("id"), f"{ne}.ad", 80)}
    ne = f"adım {a['id']}"
    a["bagimli"] = [_id(b, f"{ne}.bagimli") for b in (ham.get("bagimli") or [])]
    a["zaman_asimi_sn"] = _sayi(ham.get("zaman_asimi_sn", 3 * 3600), f"{ne}.zaman_asimi_sn", 10, 3 * 24 * 3600)
    a["hata"] = _hata_politikasi(ham.get("hata"), f"{ne}.hata")
    a["sonraki"] = _gecis(ham.get("sonraki"), f"{ne}.sonraki", liste_olabilir=True)
    if tur == "agent_task":
        a["ajan"] = _id(ham.get("ajan"), f"{ne}.ajan")
        a["gorev"] = _metin(ham.get("gorev"), f"{ne}.gorev", MAKS_SABLON)
        if ham.get("model") is not None and ham["model"] not in MODELLER:
            raise TanimHatasi(f"{ne}.model: {MODELLER}")
        a["model"] = ham.get("model")
        a["cikti_alanlari"] = _alanlar(ham.get("cikti_alanlari"), f"{ne}.cikti_alanlari")
        if "yan_etkili" in ham and not isinstance(ham["yan_etkili"], bool):
            raise TanimHatasi(f"{ne}.yan_etkili: true | false")
        a["yan_etkili"] = ham.get("yan_etkili", True)   # bilinmiyorsa yan etkili say: körlemesine tekrar yok
        a["tahmini_usd"] = _sayi(ham["tahmini_usd"], f"{ne}.tahmini_usd", 0, 50, tam=False) if "tahmini_usd" in ham else None
    elif tur == "gelistirme_gorevi":
        a["mod"] = ham.get("mod", "yeni")
        if a["mod"] not in ("yeni", "duzeltme"):
            raise TanimHatasi(f"{ne}.mod: yeni | duzeltme")
        if a["mod"] == "yeni":
            if ham.get("proje") not in GELISTIRME_PROJELERI:
                raise TanimHatasi(f"{ne}.proje: {GELISTIRME_PROJELERI}")
            a["proje"] = ham["proje"]
            a["baslik"] = _metin(ham.get("baslik"), f"{ne}.baslik", 300)
            a["istek"] = _metin(ham.get("istek"), f"{ne}.istek", MAKS_SABLON)
            a["model"] = ham.get("model", "sonnet")
            if a["model"] not in MODELLER:
                raise TanimHatasi(f"{ne}.model: {MODELLER}")
        else:
            a["hedef_adim"] = _id(ham.get("hedef_adim"), f"{ne}.hedef_adim")
            a["geri_bildirim"] = _metin(ham.get("geri_bildirim"), f"{ne}.geri_bildirim", MAKS_SABLON)
        a["yan_etkili"] = True
        a["tahmini_usd"] = _sayi(ham.get("tahmini_usd", 6.0), f"{ne}.tahmini_usd", 0, 50, tam=False)
    elif tur == "quality_gate":
        a["kontroller"] = _kontroller(ham.get("kontroller"), f"{ne}.kontroller")
        a["kosullar"] = _kosullar(ham["kosullar"], f"{ne}.kosullar") if ham.get("kosullar") is not None else []
        if not a["kontroller"]:
            # bir modelin "testler geçti" demesi tek başına yetmez: her kapı en az bir gerçek komut çıkış kodu ister
            raise TanimHatasi(f"{ne}: quality_gate en az bir kontrol komutu ister")
        a["kaynak_adim"] = _id(ham["kaynak_adim"], f"{ne}.kaynak_adim") if ham.get("kaynak_adim") else None
        if a["kontroller"] and any(k["cwd"] == "{worktree}" or "{worktree}" in " ".join(k["komut"]) for k in a["kontroller"]) \
                and not a["kaynak_adim"]:
            raise TanimHatasi(f"{ne}: {{worktree}} kullanan kontrol kaynak_adim (gelistirme_gorevi) ister")
        a["basarisizsa"] = _gecis(ham.get("basarisizsa"), f"{ne}.basarisizsa")
        a["yan_etkili"] = False
    elif tur == "condition":
        a["kosullar"] = _kosullar(ham.get("kosullar"), f"{ne}.kosullar")
        a["dogru"] = _gecis(ham.get("dogru"), f"{ne}.dogru")
        a["yanlis"] = _gecis(ham.get("yanlis"), f"{ne}.yanlis")
        if not a["dogru"] or not a["yanlis"]:
            raise TanimHatasi(f"{ne}: dogru ve yanlis geçişleri gerekli")
        if a["sonraki"]:
            raise TanimHatasi(f"{ne}: condition sonraki yerine dogru/yanlis kullanır")
    elif tur == "approval":
        a["kategori"] = ham.get("kategori", "genel")
        if a["kategori"] not in ONAY_KATEGORILERI:
            raise TanimHatasi(f"{ne}.kategori: {ONAY_KATEGORILERI}")
        a["mesaj"] = _metin(ham.get("mesaj"), f"{ne}.mesaj", 1000)
        a["izle_adim"] = _id(ham["izle_adim"], f"{ne}.izle_adim") if ham.get("izle_adim") else None
        if a["kategori"] == "dagitim" and not a["izle_adim"]:
            # dağıtım onayı yalnız mevcut Geliştirme kartında verilir; workflow kendi dağıtım onayını üretemez
            raise TanimHatasi(f"{ne}: dagitim onayı izle_adim (gelistirme_gorevi) ister")
        a["reddedilirse"] = _gecis(ham.get("reddedilirse"), f"{ne}.reddedilirse") or [{"hedef": INCELEME, "dongu": None}]
    elif tur == "end":
        a["sonuc"] = ham.get("sonuc", "basarili")
        if a["sonuc"] not in ("basarili", "basarisiz"):
            raise TanimHatasi(f"{ne}.sonuc: basarili | basarisiz")
        if a["sonraki"]:
            raise TanimHatasi(f"{ne}: end adımının sonrakisi olamaz")
    if tur not in ("end", "condition") and not a["sonraki"]:
        raise TanimHatasi(f"{ne}: sonraki gerekli")
    return a


def gecisler(a):
    """Adımın bütün çıkış geçişleri (doğrulama ve grafik için)."""
    g = list(a.get("sonraki", []))
    for alan in ("basarisizsa", "dogru", "yanlis", "reddedilirse"):
        g += a.get(alan) or []
    g += a["hata"].get("hedef") or []
    return g


def _ref_dogrula(tanim, adimlar, metin, ne):
    for ref in SABLON_REF.findall(metin or ""):
        _alan_ref_dogrula(tanim, adimlar, ref, ne)


def _alan_ref_dogrula(tanim, adimlar, ref, ne):
    parca = ref.split(".")
    if parca[0] == "girdi" and len(parca) == 2:
        if parca[1] not in tanim["girdiler"]:
            raise TanimHatasi(f"{ne}: bilinmeyen girdi {ref}")
        return
    if parca[0] == "adim" and len(parca) == 3:
        kaynak = adimlar.get(parca[1])
        if not kaynak:
            raise TanimHatasi(f"{ne}: bilinmeyen adım {ref}")
        alanlar = kaynak.get("cikti_alanlari") if kaynak["tur"] == "agent_task" else YERLESIK_CIKTILAR[kaynak["tur"]]
        if parca[2] not in alanlar:
            raise TanimHatasi(f"{ne}: {parca[1]} adımının {parca[2]} çıktısı yok")
        return
    raise TanimHatasi(f"{ne}: geçersiz başvuru {ref}")


def dogrula(ham, beklenen_id=None):
    """Ham JSON → normalize tanım. Hata: TanimHatasi (yol/değer sızdırmaz)."""
    if not isinstance(ham, dict):
        raise TanimHatasi("tanım bir JSON nesnesi olmalı")
    _bilinmeyen_anahtar(ham, ("sema_surumu", "id", "surum", "ad", "aciklama", "girdiler", "izinli_ajanlar",
                              "sinirlar", "donguler", "baslangic", "adimlar"), "tanım")
    if ham.get("sema_surumu") != SEMA_SURUMU:
        raise TanimHatasi(f"sema_surumu {SEMA_SURUMU} olmalı")
    t = {"sema_surumu": SEMA_SURUMU, "id": _id(ham.get("id"), "id")}
    if beklenen_id is not None and t["id"] != beklenen_id:
        raise TanimHatasi("id dosya adıyla aynı olmalı")
    t["surum"] = _sayi(ham.get("surum"), "surum", 1, 1_000_000)
    t["ad"] = _metin(ham.get("ad"), "ad", 80)
    t["aciklama"] = _metin(ham.get("aciklama"), "aciklama", 1000, zorunlu=False) or ""
    t["girdiler"] = _alanlar(ham.get("girdiler"), "girdiler")
    izinli = ham.get("izinli_ajanlar") or []
    if not isinstance(izinli, list) or len(izinli) > 20:
        raise TanimHatasi("izinli_ajanlar: en çok 20 ajan id'si")
    t["izinli_ajanlar"] = [_id(x, "izinli_ajanlar") for x in izinli]
    s = ham.get("sinirlar") or {}
    if not isinstance(s, dict):
        raise TanimHatasi("sinirlar: nesne olmalı")
    _bilinmeyen_anahtar(s, VARSAYILAN_SINIRLAR, "sinirlar")
    t["sinirlar"] = {}
    for ad, vars in VARSAYILAN_SINIRLAR.items():
        tam = ad != "max_maliyet_usd"
        t["sinirlar"][ad] = _sayi(s.get(ad, vars), f"sinirlar.{ad}", 1 if tam else 0.01, SINIR_TAVANLARI[ad], tam=tam)
    d = ham.get("donguler") or {}
    if not isinstance(d, dict) or len(d) > 5:
        raise TanimHatasi("donguler: en çok 5 döngü")
    t["donguler"] = {}
    for ad, dt in d.items():
        _id(ad, "donguler")
        if not isinstance(dt, dict):
            raise TanimHatasi(f"donguler.{ad}: nesne olmalı")
        _bilinmeyen_anahtar(dt, ("max_iterasyon", "tukenince"), f"donguler.{ad}")
        t["donguler"][ad] = {
            "max_iterasyon": _sayi(dt.get("max_iterasyon", t["sinirlar"]["max_iterasyon"]), f"donguler.{ad}.max_iterasyon",
                                   1, t["sinirlar"]["max_iterasyon"]),
            "tukenince": dt.get("tukenince", "pause")}
        if t["donguler"][ad]["tukenince"] not in ("pause", "fail"):
            raise TanimHatasi(f"donguler.{ad}.tukenince: pause | fail")
    ham_adimlar = ham.get("adimlar")
    if not isinstance(ham_adimlar, list) or not 1 <= len(ham_adimlar) <= MAKS_ADIM:
        raise TanimHatasi(f"adimlar: 1–{MAKS_ADIM} adım")
    adimlar = {}
    for i, h in enumerate(ham_adimlar):
        a = _adim(h, f"adimlar[{i}]")
        if a["id"] in adimlar:
            raise TanimHatasi(f"adım {a['id']}: tekrar eden id")
        adimlar[a["id"]] = a
    t["baslangic"] = _id(ham.get("baslangic"), "baslangic")
    if t["baslangic"] not in adimlar:
        raise TanimHatasi("baslangic bilinmeyen adım")
    # başvurular
    for a in adimlar.values():
        ne = f"adım {a['id']}"
        for g in gecisler(a):
            if g["hedef"] != INCELEME and g["hedef"] not in adimlar:
                raise TanimHatasi(f"{ne}: bilinmeyen hedef {g['hedef']}")
            if g["dongu"] and g["dongu"] not in t["donguler"]:
                raise TanimHatasi(f"{ne}: tanımsız döngü {g['dongu']}")
        for b in a["bagimli"]:
            if b not in adimlar or b == a["id"]:
                raise TanimHatasi(f"{ne}: bilinmeyen bağımlılık {b}")
        if a["tur"] == "agent_task" and a["ajan"] not in t["izinli_ajanlar"]:
            raise TanimHatasi(f"{ne}: ajan {a['ajan']} izinli_ajanlar listesinde yok")
        for alan in ("gorev", "baslik", "istek", "geri_bildirim", "mesaj"):
            _ref_dogrula(t, adimlar, a.get(alan), ne)
        for k in a.get("kosullar") or []:
            _alan_ref_dogrula(t, adimlar, k["alan"], ne)
        for alan in ("kaynak_adim", "hedef_adim", "izle_adim"):
            if a.get(alan) and (a[alan] not in adimlar or adimlar[a[alan]]["tur"] != "gelistirme_gorevi"
                                or adimlar[a[alan]].get("mod") != "yeni"):
                raise TanimHatasi(f"{ne}.{alan}: mod=yeni bir gelistirme_gorevi adımı olmalı")
    if not any(a["tur"] == "end" for a in adimlar.values()):
        raise TanimHatasi("en az bir end adımı gerekli")
    _dongusuz_mu(t["baslangic"], adimlar)
    t["adimlar"] = [adimlar[h["id"]] for h in ham_adimlar]
    t["ozet"] = hashlib.sha256(json.dumps(t, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return t


def _dongusuz_mu(baslangic, adimlar):
    """Döngü (dongu) kenarları çıkarılınca grafik döngüsüz olmalı; her adım başlangıçtan erişilebilir olmalı."""
    kenar = {k: [g["hedef"] for g in gecisler(a) if not g["dongu"] and g["hedef"] != INCELEME]
             for k, a in adimlar.items()}
    tum = {k: [g["hedef"] for g in gecisler(a) if g["hedef"] != INCELEME] for k, a in adimlar.items()}
    renk = {}

    def gez(d):
        renk[d] = 1
        for h in kenar[d]:
            if renk.get(h) == 1:
                raise TanimHatasi(f"sınırsız döngü: {d} → {h} (geri dönüş kenarına dongu ver)")
            if not renk.get(h):
                gez(h)
        renk[d] = 2

    for k in adimlar:
        if not renk.get(k):
            gez(k)
    erisilen, yigin = set(), [baslangic]
    while yigin:
        d = yigin.pop()
        if d in erisilen:
            continue
        erisilen.add(d)
        yigin += tum[d]
    eksik = set(adimlar) - erisilen
    if eksik:
        raise TanimHatasi(f"başlangıçtan erişilemeyen adım(lar): {', '.join(sorted(eksik))}")


def tanimlari_yukle(dizin=None):
    """{id: tanim} ve {dosya: hata}. Bozuk tanım diğerlerini engellemez; başlatılamaz."""
    dizin = dizin or TANIM_DIZINI
    tanimlar, hatalar = {}, {}
    try:
        adlar = sorted(a for a in os.listdir(dizin) if a.endswith(".json"))
    except OSError:
        return tanimlar, hatalar
    for ad in adlar:
        yol = os.path.join(dizin, ad)
        if os.path.islink(yol) or not os.path.isfile(yol):
            continue
        try:
            with open(yol, encoding="utf-8") as f:
                ham = json.load(f)
            t = dogrula(ham, beklenen_id=ad[:-5])
            tanimlar[t["id"]] = t
        except (OSError, ValueError, TanimHatasi) as e:
            hatalar[ad] = str(e)[:300] if isinstance(e, TanimHatasi) else f"okunamadı ({type(e).__name__})"
    return tanimlar, hatalar


def adim_bul(tanim, adim_id):
    return next((a for a in tanim["adimlar"] if a["id"] == adim_id), None)


def girdileri_dogrula(tanim, girdiler):
    """Başlatma girdileri: tanımdaki alanlar, tür ve boyut. Fazla alan reddedilir."""
    from akis_veri import VeriHatasi, alan_dogrula, sir_bul
    if girdiler is None:
        girdiler = {}
    if not isinstance(girdiler, dict):
        raise TanimHatasi("girdiler nesne olmalı")
    fazla = set(girdiler) - set(tanim["girdiler"])
    if fazla:
        raise TanimHatasi("bilinmeyen girdi: " + ", ".join(sorted(fazla))[:200])
    sonuc = {}
    for ad, alan in tanim["girdiler"].items():
        if ad not in girdiler:
            if alan["zorunlu"]:
                raise TanimHatasi(f"girdi {ad} gerekli")
            continue
        try:
            sonuc[ad] = alan_dogrula(ad, alan, girdiler[ad])
        except VeriHatasi as e:
            raise TanimHatasi(f"girdi {e}") from e
        if isinstance(sonuc[ad], str) and sir_bul(sonuc[ad]):
            raise TanimHatasi(f"girdi {ad}: sır görünümlü değer içeriyor")
        if alan["tur"] == "metin" and alan["zorunlu"] and not sonuc[ad]:
            raise TanimHatasi(f"girdi {ad} boş olamaz")
    return sonuc
