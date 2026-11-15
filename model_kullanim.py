"""Model kullanımı: bugün / 7 gün / 30 gün token ve USD (API liste fiyatı eşdeğeri), model ve laboratuvar başına.

Kaynaklar (yalnız sayılar okunur; metin içeriği ne önbelleğe ne API'ye girer):
  claude  ~/.claude/projects/**.jsonl (+ diğer Pro hesabının projects/; aynı dosya realpath ile bir kez)
          assistant satırları; message.id ile TÜM dosyalar arasında tekilleştirilir (alan başına en büyük değer).
  codex   ~/.codex/sessions/**.jsonl  token_usage_record satırları; response_id ile tekil; model turn_context'ten.
  antigravity ~/.gemini/antigravity-cli/conversations/*.db (SQLite, salt okunur) gen_metadata protobuf'u:
          1.19 model, 1.4 {2 giriş, 3 çıkış, 4 önbellek yazma, 5 önbellek okuma}; gün, last_step_index adımının zamanından.
  ofis    olaylar.jsonl kosu_bitti / ceo_bitti / ykb_bitti (claude -p --no-session-persistence: transkript yok).
Dosya başına özet durum/model-kullanim.json'da (mtime, boyut) anahtarıyla tutulur; değişmeyen dosya yeniden okunmaz.
Tüm zamanlar toplamı için silinen kaynak dosyanın özeti (Claude Code transkriptleri 30 günde siler) ve döndürülüp
düşen ofis olayları önbellekte kalır; önbellek silinirse toplam diskte kalan kayıtlardan yeniden kurulur.
"""
import glob
import json
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta

import ortak
import token_sayac

GUN = 30
TARAMA_ARALIK_SN = 300
ONBELLEK = os.path.join(ortak.DURUM_DIZINI, "model-kullanim.json")
ONBELLEK_SURUM = 1
CODEX_DIZINI = os.path.expanduser(os.environ.get("OFIS_CODEX_DIZINI", "~/.codex/sessions"))
ANTIGRAVITY_DIZINI = os.path.expanduser(os.environ.get("OFIS_ANTIGRAVITY_DIZINI", "~/.gemini/antigravity-cli/conversations"))

# Anthropic dışı API liste fiyatı, $ / milyon token. Kaynak ve tarih her satırda; fiyat değişince güncelle.
# model önekine göre eşleşir. Her satır: (önek, hariç tutulan ekler, [(geçerlilik başlangıcı, giriş, çıkış, önbellek okuma)],
#   uzun bağlam: (istek başına giriş eşiği, giriş, çıkış, önbellek okuma) | None). Önbellek yazma = giriş fiyatı.
DIS_FIYATLAR = [
    # developers.openai.com/api/docs/pricing (2026-11-15): standart katman; >272K giriş uzun bağlam
    ("gpt-6.1-sol", (), [("0000-00-00", 2.00, 10.00, 0.10)], (272_000, 4.00, 15.00, 0.20)),
    # aistudio.google.com/docs/pricing (2026-11-15): ücretli standart; 2027-01-01'den itibaren iki katı.
    # Antigravity'nin gemini-3.8-flash-n / -tiered adları bu modelin iç varyantları sayılır (ayrı liste fiyatı yok).
    ("gemini-3.8-flash", ("-lite", "-tts", "-live"), [("0000-00-00", 0.75, 3.75, 0.075), ("2027-01-01", 1.50, 7.50, 0.15)], None),
]


def dis_fiyat(model, gun, giris_toplam=0):
    m = str(model or "")
    for onek, haric, donemler, uzun in DIS_FIYATLAR:
        if not (m == onek or m.startswith(onek + "-")) or any(h in m[len(onek):] for h in haric):
            continue
        fiyat = [d[1:] for d in donemler if str(gun or "9999") >= d[0]][-1]
        if uzun and giris_toplam > uzun[0]:
            fiyat = uzun[1:]
        return fiyat
    return None

LAB = (("claude-", "Anthropic"), ("gpt-", "OpenAI"), ("o3", "OpenAI"), ("o4", "OpenAI"), ("codex", "OpenAI"),
       ("kimi", "Moonshot"), ("gemini", "Google"))


def lab_bul(model):
    m = str(model or "").lower()
    for on, lab in LAB:
        if m.startswith(on):
            return lab
    return "Diğer"


def model_normal(model):
    """claude-opus-5-5-20261001 / opus / claude-opus-5-5[1m] → claude-opus-5-5; diğerleri küçük harf."""
    m = str(model or "").strip().lower()
    m = token_sayac.KISA_MODEL.get(m, m)
    for ad in token_sayac.FIYATLAR:
        if m == ad or m.startswith(ad + "-") or m.startswith(ad + "["):
            return ad
    return m or "bilinmiyor"


def usd(usage, model, gun=None):
    """Tek istek/yanıt usage'ı → USD. Uzun bağlam katmanı istek başına girişe (önbellek dahil) bakar."""
    v = token_sayac.usd_tahmini(usage, model)
    if v is not None:
        return v
    u = token_sayac.usage_al(usage)
    fiyat = dis_fiyat(model, gun, u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"])
    if not fiyat:
        return None
    giris, cikis, okuma = fiyat
    return round((u["input_tokens"] * giris + u["output_tokens"] * cikis + u["cache_read_input_tokens"] * okuma
                  + u["cache_creation_input_tokens"] * giris) / 1_000_000, 6)


def _u4(u):
    return [int(u.get(k) or 0) if isinstance(u.get(k), (int, float)) else 0 for k in token_sayac.ALANLAR]


# ---------- dosya ayrıştırıcıları: {kimlik: [gün, model, giriş, çıkış, önb_yazma, önb_okuma]} ----------
def claude_dosyasi(yol):
    kayit = {}
    with open(yol, "rb") as f:
        for ham in f:
            if b'"usage"' not in ham or b'"assistant"' not in ham:
                continue
            try:
                o = json.loads(ham)
            except ValueError:
                continue
            m = o.get("message") if isinstance(o, dict) else None
            if o.get("type") != "assistant" or not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
                continue
            model = m.get("model") or ""
            if not model or model.startswith("<"):        # <synthetic>: model çağrısı değil
                continue
            gun = token_sayac.yerel_tarih(o.get("timestamp"))
            if not gun:
                continue
            kimlik = m.get("id") or o.get("uuid")
            if not kimlik:
                continue
            yeni = [gun, model_normal(model)] + _u4(m["usage"])
            eski = kayit.get(kimlik)
            kayit[kimlik] = yeni if not eski else eski[:2] + [max(a, b) for a, b in zip(eski[2:], yeni[2:])]
    return kayit


def codex_dosyasi(yol):
    kayit, model = {}, ""
    with open(yol, "rb") as f:
        for ham in f:
            if b'"turn_context"' not in ham and b'"token_usage_record"' not in ham:
                continue
            try:
                o = json.loads(ham)
            except ValueError:
                continue
            p = o.get("payload") if isinstance(o, dict) else None
            if not isinstance(p, dict):
                continue
            if o.get("type") == "turn_context":
                model = str(p.get("model") or model)
                continue
            if o.get("type") != "token_usage_record" or not isinstance(p.get("usage"), dict):
                continue
            gun = token_sayac.yerel_tarih(o.get("timestamp"))
            kimlik = p.get("response_id")
            if not gun or not kimlik:
                continue
            u = p["usage"]
            giris, onb = int(u.get("input_tokens") or 0), int(u.get("cached_input_tokens") or 0)
            # Codex: cached_input input'un içinde, reasoning output'un içinde → çift sayma yok
            kayit["codex:" + kimlik] = [gun, (model or "codex").lower(), max(giris - onb, 0),
                                        int(u.get("output_tokens") or 0), int(u.get("cache_write_input_tokens") or 0), onb]
    return kayit


def _vint(b, i):
    r = s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        s += 7
        if x < 0x80:
            return r, i


def pb_coz(b, derinlik=0):
    """Şemasız protobuf: [(alan, tür, değer)]; iç ileti çözülebiliyorsa liste, değilse bytes. Çözülemezse None."""
    i, cikti = 0, []
    try:
        while i < len(b):
            k, i = _vint(b, i)
            f, t = k >> 3, k & 7
            if f == 0:
                return None
            if t == 0:
                v, i = _vint(b, i)
            elif t == 1:
                v, i = b[i:i + 8], i + 8
            elif t == 5:
                v, i = b[i:i + 4], i + 4
            elif t == 2:
                n, i = _vint(b, i)
                v, i = b[i:i + n], i + n
                if derinlik < 4 and n:
                    v = pb_coz(v, derinlik + 1) or v
            else:
                return None
            cikti.append((f, t, v))
        return cikti if i == len(b) else None
    except IndexError:
        return None


def pb_al(o, yol):
    for f, _, v in o or []:
        if f == yol[0]:
            if len(yol) == 1:
                return v
            if isinstance(v, list):
                r = pb_al(v, yol[1:])
                if r is not None:
                    return r
    return None


def _metin(v):
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode()
        except UnicodeDecodeError:
            return None
    return None


def antigravity_dosyasi(yol):
    kayit = {}
    c = sqlite3.connect(f"file:{yol}?mode=ro", uri=True)
    try:
        zaman = {}
        for idx, meta in c.execute("select idx, metadata from steps"):
            ts = pb_al(pb_coz(meta or b""), (1, 1))
            if isinstance(ts, int):
                zaman[idx] = ts
        for idx, veri in c.execute("select idx, data from gen_metadata"):
            o = pb_coz(veri or b"")
            u = pb_al(o, (1, 4))
            model = _metin(pb_al(o, (1, 19)))
            if not isinstance(u, list) or not model:
                continue
            d = {f: v for f, t, v in u if t == 0}
            adim = idx
            for f, _, kv in (pb_al(o, (1,)) or []) if isinstance(pb_al(o, (1,)), list) else []:
                if f == 20 and isinstance(kv, list) and _metin(pb_al(kv, (1,))) == "last_step_index":
                    m = _metin(pb_al(kv, (2,)))
                    adim = int(m) if m and m.isdigit() else idx
            ts = zaman.get(adim) or max((v for k, v in zaman.items() if k <= adim), default=None)
            if not ts:
                continue
            gun = datetime.fromtimestamp(ts).date().isoformat()
            kayit[f"ag:{os.path.basename(yol)}:{idx}"] = [gun, model_normal(model), int(d.get(2, 0)), int(d.get(3, 0)),
                                                          int(d.get(4, 0)), int(d.get(5, 0))]
    finally:
        c.close()
    return kayit


def claude_kokleri():
    try:
        import kopru
        kokler = kopru.proje_dizinleri()
    except Exception:
        kokler = [os.path.join(os.path.expanduser("~"), ".claude", "projects")]
    return kokler


def dosyalar(sinir_ts):
    """(tür, gerçek yol) çiftleri; sembolik bağla iki hesapta görünen dosya bir kez."""
    gorulen, liste = set(), []
    for tur, kokler, desen in (("claude", claude_kokleri(), "**/*.jsonl"), ("codex", [CODEX_DIZINI], "**/*.jsonl"),
                               ("antigravity", [ANTIGRAVITY_DIZINI], "*.db")):
        for kok in kokler:
            for yol in glob.glob(os.path.join(kok, desen), recursive=True):
                try:
                    gercek = os.path.realpath(yol)
                    st = os.stat(gercek)
                except OSError:
                    continue
                if st.st_mtime < sinir_ts or gercek in gorulen:
                    continue
                gorulen.add(gercek)
                liste.append((tur, gercek, st))
    return liste


# ---------- tarama ve önbellek ----------
_kilit = threading.Lock()
_durum = {"zaman": 0.0, "dosyalar": None}


def _onbellek_ham():
    try:
        with open(ONBELLEK, encoding="utf-8") as f:
            v = json.load(f)
        if isinstance(v, dict) and v.get("surum") == ONBELLEK_SURUM:
            return v
    except (OSError, ValueError):
        pass
    return {}


def _onbellek_oku():
    d = _onbellek_ham().get("dosyalar")
    return d if isinstance(d, dict) else {}


def _onbellek_yaz(dos=None, ofis=None):
    ham = _onbellek_ham()
    if dos is None:
        dos = ham.get("dosyalar") if isinstance(ham.get("dosyalar"), dict) else {}
    if ofis is None:
        ofis = ham.get("ofis") if isinstance(ham.get("ofis"), dict) else {}
    os.makedirs(ortak.DURUM_DIZINI, exist_ok=True)
    gecici = ONBELLEK + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump({"surum": ONBELLEK_SURUM, "dosyalar": dos, "ofis": ofis}, f, separators=(",", ":"))
    os.replace(gecici, ONBELLEK)


def ofis_arsivle(satirlar):
    """Ofis olay satırlarını {anahtar: satır} arşiviyle birleştirir (olaylar.jsonl döndürülünce kaybolmasın)."""
    with _kilit:
        arsiv = _onbellek_ham().get("ofis")
        arsiv = dict(arsiv) if isinstance(arsiv, dict) else {}
        yeni = {k: v for k, v in satirlar.items() if k not in arsiv}
        if yeni:
            arsiv.update(yeni)
            _onbellek_yaz(ofis=arsiv)
    return list(arsiv.values())


def tara(zorla=False):
    """Değişen dosyaları yeniden okur; {gerçek yol: {mt, boy, kayit}} döndürür."""
    with _kilit:
        if not zorla and _durum["dosyalar"] is not None and time.time() - _durum["zaman"] < TARAMA_ARALIK_SN:
            return _durum["dosyalar"]
        eski = _durum["dosyalar"] if _durum["dosyalar"] is not None else _onbellek_oku()
        yeni, degisti = {}, _durum["dosyalar"] is None
        for tur, yol, st in dosyalar(0):
            e = eski.get(yol)
            if e and e.get("mt") == st.st_mtime and e.get("boy") == st.st_size:
                yeni[yol] = e
                continue
            try:
                kayit = {"claude": claude_dosyasi, "codex": codex_dosyasi, "antigravity": antigravity_dosyasi}[tur](yol)
            except (OSError, sqlite3.Error):
                continue
            yeni[yol] = {"mt": st.st_mtime, "boy": st.st_size, "kayit": kayit}
            degisti = True
        for yol, e in eski.items():          # diskten silinen dosya: özeti tüm zamanlar için kalır
            if yol not in yeni and e.get("kayit"):
                yeni[yol] = {**e, "silindi": True}
        if degisti or set(yeni) != set(eski):
            _onbellek_yaz(yeni)
        _durum.update(zaman=time.time(), dosyalar=yeni)
        return yeni


def ofis_kayitlari(olaylar, tablo):
    """Ofis olayları → {anahtar: [gün, model, 4 alan, usd ölçülen|None]}."""
    satirlar = {}
    for o in olaylar:
        if o.get("tur") not in ("kosu_bitti", "ceo_bitti", "ykb_bitti") or not isinstance(o.get("kullanim"), dict):
            continue
        gun = str(o.get("zaman", ""))[:10]
        ajan = "ceo" if o["tur"] == "ceo_bitti" and not o.get("ajan") else o.get("ajan")
        model = o.get("model") or (tablo.get(ajan) or {}).get("model") or ""
        olcum = o.get("maliyet_usd") if isinstance(o.get("maliyet_usd"), (int, float)) else None
        anahtar = f'{o["tur"]}:{o.get("kosu_id") or o.get("zaman")}'
        satirlar[anahtar] = [gun, model_normal(model)] + _u4(o["kullanim"]) + [olcum]
    return satirlar


# ---------- özet ----------
MODEL_ADLARI = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5", "claude-haiku-5-5": "Haiku 5.5",
                "claude-fable-5-2": "Fable 5.2"}


def model_adi(m):
    if m in MODEL_ADLARI:
        return MODEL_ADLARI[m]
    e = re.fullmatch(r"claude-(opus|sonnet|haiku|fable)-(\d+)-(\d+)", m)
    if e:
        return f"{e[1].capitalize()} {e[2]}.{e[3]}"
    if m.startswith("gemini-"):
        return "Gemini " + " ".join(p if p[0].isdigit() else p.capitalize() for p in m[7:].split("-"))
    if m.startswith("gpt-"):
        return "GPT-" + " ".join(p.capitalize() if not p[0].isdigit() else p for p in m[4:].split("-"))
    return m


def ozet(olaylar, tablo, bugun=None, dosya_ozeti=None):
    bugun = bugun or ortak.bugun()
    b = date.fromisoformat(bugun)
    gunler = [(b - timedelta(days=i)).isoformat() for i in range(GUN - 1, -1, -1)]
    # (gün, model, kaynak) → [4 alan, usd]; tüm günler (tüm zamanlar toplamı için), bugünden sonrası yok
    hucre = {}

    def ekle(gun, model, kaynak, u4, olcum=None):
        if not gun or gun > bugun:
            return
        h = hucre.setdefault((gun, model, kaynak), [0, 0, 0, 0, 0.0, True])
        for i in range(4):
            h[i] += u4[i]
        d = olcum if olcum is not None else usd(dict(zip(token_sayac.ALANLAR, u4)), model, gun)
        if d is None:
            h[5] = False
        else:
            h[4] += d

    dos = dosya_ozeti if dosya_ozeti is not None else tara()
    birlesik = {}
    for yol, e in dos.items():
        for kimlik, r in (e.get("kayit") or {}).items():
            onceki = birlesik.get(kimlik)
            birlesik[kimlik] = r if not onceki else onceki[:2] + [max(a, c) for a, c in zip(onceki[2:], r[2:])]
    son = None
    for kimlik, r in birlesik.items():
        kaynak = "codex" if kimlik.startswith("codex:") else "antigravity" if kimlik.startswith("ag:") else "terminal"
        ekle(r[0], r[1], kaynak, r[2:6])
    ofis = ofis_kayitlari(olaylar, tablo)
    for r in (ofis_arsivle(ofis) if dosya_ozeti is None else ofis.values()):
        ekle(r[0], r[1], "ofis", r[2:6], r[6])
    tum_gunler = sorted({g for g, _, _ in hucre})

    def donem(n):
        kapsam = set(gunler[-n:]) if n else set(tum_gunler)
        modeller, kaynaklar = {}, {}
        for (g, m, k), h in hucre.items():
            if g not in kapsam:
                continue
            t = sum(h[:4])
            a = modeller.setdefault(m, {"model": m, "ad": model_adi(m), "lab": lab_bul(m), "token": 0, "usd": 0.0,
                                        "fiyatli": True, "girdi": 0, "cikti": 0, "onbellek_yazma": 0, "onbellek_okuma": 0})
            a["token"] += t
            a["usd"] += h[4]
            a["fiyatli"] = a["fiyatli"] and h[5]
            for i, ad in enumerate(("girdi", "cikti", "onbellek_yazma", "onbellek_okuma")):
                a[ad] += h[i]
            kaynaklar[k] = kaynaklar.get(k, 0) + t
        toplam = sum(a["token"] for a in modeller.values())
        satirlar = sorted(modeller.values(), key=lambda a: -a["token"])
        for a in satirlar:
            a["pay"] = round(a["token"] / toplam, 4) if toplam else 0
            a["usd"] = round(a["usd"], 2) if a["fiyatli"] else (round(a["usd"], 2) or None)
        lab = {}
        for a in satirlar:
            lab[a["lab"]] = lab.get(a["lab"], 0) + a["token"]
        return {"token": toplam, "usd": round(sum(a["usd"] or 0 for a in satirlar), 2),
                "eksik_fiyat": [a["ad"] for a in satirlar if not a["fiyatli"]],
                "modeller": satirlar, "kaynaklar": kaynaklar,
                "laboratuvar": [{"lab": k, "token": v, "pay": round(v / toplam, 4) if toplam else 0}
                                for k, v in sorted(lab.items(), key=lambda x: -x[1])]}

    seri = []
    for g in gunler:
        m = {}
        for (gg, mm, _), h in hucre.items():
            if gg == g:
                m[mm] = m.get(mm, 0) + sum(h[:4])
        seri.append({"tarih": g, "modeller": m})
    # "Şu an": en son yazılan ana oturum transkriptindeki son model (alt-ajan transkriptleri sayılmaz)
    ana = [y for y in dos if "/subagents/" not in y and dos[y].get("kayit")]
    if ana:
        yol = max(ana, key=lambda y: dos[y].get("mt") or 0)
        kayitlar = list((dos[yol].get("kayit") or {}).values())
        if kayitlar:
            son = kayitlar[-1][1]
    roller = [{"id": a["id"], "ad": a.get("ad") or a["id"], "model": model_normal(a.get("model")),
               "model_ad": model_adi(model_normal(a.get("model"))), "lab": lab_bul(model_normal(a.get("model"))),
               "effort": a.get("effort") or "", "aciklama": str(a.get("aciklama") or a.get("uzmanlik") or "")[:140]}
              for a in tablo.values() if a.get("model")]
    return {"tarih": bugun, "guncelleme": datetime.fromtimestamp(_durum["zaman"] or time.time()).isoformat(timespec="minutes"),
            "su_an": {"model": son, "ad": model_adi(son)} if son else None,
            "donemler": {"bugun": donem(1), "7": donem(7), "30": donem(GUN), "tum": donem(0)},
            "ilk_gun": tum_gunler[0] if tum_gunler else None,
            "seri": seri, "roller": roller,
            "not": "Token = giriş + çıkış + önbellek yazma + önbellek okuma. USD API liste fiyatı eşdeğeridir; "
                   "Pro aboneliğinde fatura değildir. Ofis koşularında ölçülen total_cost_usd kullanılır."}
