"""Workflow durum deposu: SQLite (WAL), sürümlü migration, kısa ve atomik işlemler. Yalnız stdlib.

Kurallar
- Her yazma `islem()` içinde (BEGIN IMMEDIATE): aynı anda tek yazar, yarım durum kalmaz.
- `denemeler` satırı (kosu, adim, iterasyon, deneme) ve idempotency anahtarı UNIQUE: aynı adım denemesi iki kez açılamaz.
- `olaylar.anahtar` UNIQUE: aynı olay iki kez yayınlanmaz (duplicate event).
"""
import contextlib
import json
import os
import sqlite3
import threading
import time

import ortak

MIGRATIONLAR = [
    # 1: ilk şema
    """
    CREATE TABLE kosular (
        id TEXT PRIMARY KEY,
        akis_id TEXT NOT NULL,
        akis_surum INTEGER NOT NULL,
        tanim_ozet TEXT NOT NULL,
        tanim_json TEXT NOT NULL,
        girdi_json TEXT NOT NULL,
        idem_anahtari TEXT UNIQUE,
        durum TEXT NOT NULL,
        neden TEXT,
        dongu_json TEXT NOT NULL DEFAULT '{}',
        ajan_cagrisi INTEGER NOT NULL DEFAULT 0,
        maliyet_usd REAL NOT NULL DEFAULT 0,
        tahmini_usd REAL NOT NULL DEFAULT 0,
        olusturma_ts REAL NOT NULL,
        guncelleme_ts REAL NOT NULL,
        bitis_ts REAL
    );
    CREATE INDEX kosular_durum ON kosular(durum);
    CREATE TABLE adimlar (
        kosu_id TEXT NOT NULL REFERENCES kosular(id),
        adim_id TEXT NOT NULL,
        durum TEXT NOT NULL,
        iterasyon INTEGER NOT NULL DEFAULT 0,
        deneme INTEGER NOT NULL DEFAULT 0,
        sonraki_ts REAL NOT NULL DEFAULT 0,
        cikti_json TEXT,
        hata TEXT,
        guncelleme_ts REAL NOT NULL,
        PRIMARY KEY (kosu_id, adim_id)
    );
    CREATE TABLE denemeler (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kosu_id TEXT NOT NULL REFERENCES kosular(id),
        adim_id TEXT NOT NULL,
        iterasyon INTEGER NOT NULL,
        deneme INTEGER NOT NULL,
        ref TEXT NOT NULL UNIQUE,
        durum TEXT NOT NULL,
        tutamac_json TEXT NOT NULL DEFAULT '{}',
        siniflama TEXT,
        hata TEXT,
        maliyet_usd REAL,
        tahmini_usd REAL NOT NULL DEFAULT 0,
        baslangic_ts REAL NOT NULL,
        bitis_ts REAL,
        UNIQUE (kosu_id, adim_id, iterasyon, deneme)
    );
    CREATE INDEX denemeler_durum ON denemeler(durum);
    CREATE TABLE olaylar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kosu_id TEXT NOT NULL,
        anahtar TEXT NOT NULL UNIQUE,
        tur TEXT NOT NULL,
        veri_json TEXT NOT NULL,
        zaman_ts REAL NOT NULL
    );
    CREATE INDEX olaylar_kosu ON olaylar(kosu_id, id);
    """,
    # 2: operatör beklemesi (inceleme/duraklatma) süre sınırına sayılmaz
    """
    ALTER TABLE kosular ADD COLUMN bekleme_sn REAL NOT NULL DEFAULT 0;
    ALTER TABLE kosular ADD COLUMN bekleme_baslangic_ts REAL
    """,
    # 3: migration 2'den önce beklemeye girmiş koşuların bekleme başlangıcı (idempotent)
    """
    UPDATE kosular SET bekleme_baslangic_ts=guncelleme_ts
        WHERE durum IN ('inceleme','duraklatildi') AND bekleme_baslangic_ts IS NULL
    """,
    # 4 (V1.1 #9): operatörün verdiği ek bütçe. Tanım anlık görüntüsü (tanim_json) değişmez; etkin sınır = tanım + ek.
    # Eski kod (1.0.88) bu sütunları okumaz: geri dönüşte ek bütçe yok sayılır (sınır daralır, fail-closed).
    """
    ALTER TABLE kosular ADD COLUMN ek_maliyet_usd REAL NOT NULL DEFAULT 0;
    ALTER TABLE kosular ADD COLUMN ek_ajan_cagrisi INTEGER NOT NULL DEFAULT 0
    """,
]

AKTIF_KOSU = ("calisiyor", "duraklatildi", "inceleme")
SON_KOSU = ("basarili", "basarisiz", "iptal")
UCUSTA = ("gonderiliyor", "kuyrukta", "calisiyor")   # sonucu beklenen deneme durumları


def varsayilan_yol():
    return os.path.join(ortak.DURUM_DIZINI, "akis.db")


class Depo:
    def __init__(self, yol=None):
        self.yol = yol or varsayilan_yol()
        os.makedirs(os.path.dirname(self.yol), exist_ok=True)
        self._yerel = threading.local()
        self._kilit = threading.RLock()   # süreç içi tek yazar (SQLite ayrıca süreçler arası kilitler)
        self.migrate()

    def baglanti(self):
        b = getattr(self._yerel, "b", None)
        if b is None:
            b = sqlite3.connect(self.yol, timeout=15, isolation_level=None, check_same_thread=False)
            b.row_factory = sqlite3.Row
            b.execute("PRAGMA journal_mode=WAL")
            b.execute("PRAGMA synchronous=NORMAL")
            b.execute("PRAGMA foreign_keys=ON")
            b.execute("PRAGMA busy_timeout=15000")
            self._yerel.b = b
        return b

    def kapat(self):
        b = getattr(self._yerel, "b", None)
        if b is not None:
            b.close()
            self._yerel.b = None

    @contextlib.contextmanager
    def islem(self):
        """BEGIN IMMEDIATE ... COMMIT; hata olursa ROLLBACK. İç içe çağrılırsa dıştakine katılır."""
        b = self.baglanti()
        with self._kilit:
            if b.in_transaction:
                yield b
                return
            b.execute("BEGIN IMMEDIATE")
            try:
                yield b
            except BaseException:
                self._geri_al(b)
                raise
            try:
                b.execute("COMMIT")
            except BaseException:
                # COMMIT başarısızsa bağlantı açık işlemde kalmamalı: sonraki islem() çağrıları bu işleme "katılıp"
                # hiç commit etmezdi (sessiz durum kaybı)
                self._geri_al(b)
                raise

    def _geri_al(self, b):
        """ROLLBACK; o da başarısız olur ve işlem açık kalırsa bağlantı bırakılır (sonraki çağrı yenisini açar).
        Asıl istisnayı gölgelemez."""
        try:
            if b.in_transaction:
                b.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        try:
            acik = b.in_transaction
        except sqlite3.Error:   # kapalı bağlantı: yenisi açılsın
            acik = True
        if acik:
            try:
                b.close()
            except Exception:  # noqa: BLE001
                pass
            if getattr(self._yerel, "b", None) is b:   # gövde yeni bağlantı açtıysa ona dokunma
                self._yerel.b = None

    def migrate(self):
        b = self.baglanti()
        with self._kilit:
            surum = b.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONLAR[surum:], start=surum + 1):
                b.execute("BEGIN IMMEDIATE")
                try:
                    for parca in [p.strip() for p in sql.split(";") if p.strip()]:
                        b.execute(parca)
                    b.execute(f"PRAGMA user_version={i}")
                except BaseException:
                    b.execute("ROLLBACK")
                    raise
                b.execute("COMMIT")

    def surum(self):
        return self.baglanti().execute("PRAGMA user_version").fetchone()[0]

    # ---- okuma yardımcıları ----
    def kosu(self, kosu_id):
        r = self.baglanti().execute("SELECT * FROM kosular WHERE id=?", (kosu_id,)).fetchone()
        return dict(r) if r else None

    def kosular(self, durumlar=None, sinir=50):
        b = self.baglanti()
        if durumlar:
            soru = ",".join("?" * len(durumlar))
            rows = b.execute(f"SELECT * FROM kosular WHERE durum IN ({soru}) ORDER BY olusturma_ts DESC LIMIT ?",
                             (*durumlar, sinir)).fetchall()
        else:
            rows = b.execute("SELECT * FROM kosular ORDER BY olusturma_ts DESC LIMIT ?", (sinir,)).fetchall()
        return [dict(r) for r in rows]

    def aktif_var_mi(self):
        soru = ",".join("?" * len(AKTIF_KOSU))
        return self.baglanti().execute(f"SELECT 1 FROM kosular WHERE durum IN ({soru}) LIMIT 1", AKTIF_KOSU).fetchone() is not None

    def adimlar(self, kosu_id):
        return {r["adim_id"]: dict(r) for r in
                self.baglanti().execute("SELECT * FROM adimlar WHERE kosu_id=?", (kosu_id,)).fetchall()}

    def denemeler(self, kosu_id, adim_id=None):
        if adim_id:
            rows = self.baglanti().execute("SELECT * FROM denemeler WHERE kosu_id=? AND adim_id=? ORDER BY id",
                                           (kosu_id, adim_id)).fetchall()
        else:
            rows = self.baglanti().execute("SELECT * FROM denemeler WHERE kosu_id=? ORDER BY id", (kosu_id,)).fetchall()
        return [dict(r) for r in rows]

    def ucustaki_denemeler(self, kosu_id=None):
        soru = ",".join("?" * len(UCUSTA))
        if kosu_id:
            rows = self.baglanti().execute(f"SELECT * FROM denemeler WHERE kosu_id=? AND durum IN ({soru}) ORDER BY id",
                                           (kosu_id, *UCUSTA)).fetchall()
        else:
            rows = self.baglanti().execute(f"SELECT * FROM denemeler WHERE durum IN ({soru}) ORDER BY id", UCUSTA).fetchall()
        return [dict(r) for r in rows]

    def olaylar(self, kosu_id, sinir=200):
        rows = self.baglanti().execute("SELECT * FROM olaylar WHERE kosu_id=? ORDER BY id DESC LIMIT ?",
                                       (kosu_id, sinir)).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ---- yazma yardımcıları (islem içinde çağrılır) ----
    @staticmethod
    def olay_ekle(b, kosu_id, anahtar, tur, veri):
        """Aynı anahtar ikinci kez gelirse eklenmez. Dönen: eklendi mi."""
        c = b.execute("INSERT OR IGNORE INTO olaylar(kosu_id, anahtar, tur, veri_json, zaman_ts) VALUES (?,?,?,?,?)",
                      (kosu_id, anahtar, tur, json.dumps(veri, ensure_ascii=False), time.time()))
        return c.rowcount == 1
