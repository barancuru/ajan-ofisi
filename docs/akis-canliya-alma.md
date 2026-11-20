# Workflow V1 — kademeli devreye alma, dağıtım ve geri dönüş

## Neyin nerede değiştiği (önce bunu ayır)

| İşlem | Neyi değiştirir | Neyi değiştirmez |
|---|---|---|
| GitHub'da PR merge | `github.com/barancuru/ajan-ofisi` `main` | Canlı çalışma kopyası `~/ajan-ofisi`, çalışan servis |
| Yerel dağıtım (`git merge --ff-only origin/main`) | `~/ajan-ofisi` dosyaları (anında) | Çalışan süreç (eski kod bellekte kalır) |
| `systemctl --user restart ajan-ofisi.service` | Çalışan kod (motor dahil) | tmux'taki ajan koşuları (sürer) |

- `~/ajan-ofisi`'nin `origin`'i GitHub'dır (fetch https, push `github-ajanofisi` SSH takma adı).
- Hattın klonu `~/beyin-is/ajan-ofisi`'nin `origin`'i `~/ajan-ofisi`'dir (`receive.denyCurrentBranch=updateInstead`). Hat bir ofis görevini canlıya alırken klondan `~/ajan-ofisi`'ye push eder, servisi yeniden başlatır, sonra `~/ajan-ofisi`'den GitHub'a push eder (`sistem/gelistirme/ajan-ofisi.sh` `canliya_al`).
- Bu yüzden GitHub'da merge commit oluşunca yerel kopya fast-forward ile eşitlenmeden hattın GitHub push'u reddedilir ("GitHub yedeği: hayir"). Sıra her zaman: **GitHub merge → yerel ff → restart**.

## Aşamalar

| Aşama | İçerik | Ön koşul |
|---|---|---|
| 0 | GitHub `main`'i canlı 1.0.86'ya eşitle (PR #2) | Yalnız **merge commit** (squash/rebase değil) |
| 1 | Workflow kodu canlıda; yalnız `ornek-arastirma-ozeti` başlatılabilir | Aşağıdaki "Aşama 1 ön koşulları" |
| 2 | HomeOS geliştirme akışı | Kod değişikliği: `akis_motor.ETKIN_AKISLAR`, `HAT_ADIMLARI_ACIK` + aşağıdaki "Aşama 2 ön koşulları" |

Aşama 1 kodda fail-closed'tır: `ETKIN_AKISLAR = ("ornek-arastirma-ozeti",)` ve `HAT_ADIMLARI_ACIK = False`. Hat görevi, kalite
kapısı ya da dağıtım/yayın onayı içeren akış — id'si ne olursa olsun — API'de 403 alır, gönderim anında da çalışmaz.
Açmak yapılandırma değil gözden geçirilmiş bir kod değişikliğidir.

### Aşama 1 ön koşulları
1. [ ] **Ajan Ofisi oto-onayını kapat** (ofis girişiyle, Geliştirme sekmesi). `bin/calistir hassas_degisim()` bugün
       `akis_*.py` ve `akislar/`'ı hassas saymıyor: hattan gelen bir ofis paketi workflow kapılarını değiştirip
       oto-onayla canlıya geçebilir. Beyin dalındaki düzeltme (`hassas_degisim` genişletmesi) canlıya alınana dek kapalı kalmalı.
2. [ ] `ajanlar.json`'a `akis-okuyucu` girdisi (`ajanlar.example.json`'dan; `cwd: ~/beyin`; yalnız Read/Glob/Grep, `tarayici: false`).
       Eksikse araştırma akışı ilk adımda `yetkisiz` ile durur (güvenli taraf). `arastirmaci`'ya dokunma.

### Aşama 2 ön koşulları (HomeOS akışı)
- **Beyin hattı** (`~/beyin` deposu, dal `hat-gorev-kilidi`, worktree `~/beyin-koruma`; hazır, canlıda DEĞİL):
  ortak görev dosyası kilidi (`fm_set`, `teslim_yaz`, eski-paket `sed`, `bitti/` taşıma, görev açan iki Python bloğu),
  `mktemp`+`mv` atomik yazım ve symlink reddi, `O_EXCL|O_NOFOLLOW` görev açılışı, paket mührüne görev kimliği
  (`<zip>.kimlik`: gorev, dal, sha256; `.sha256` ve `onay_gecerli` biçimi değişmez), oto-onayda kimlik kopyası,
  `hassas_degisim`'e `akis_*.py`/`akislar/` ve workflow/kimlik anahtar sözcükleri, `HAT_KORUMA_SURUMU=1` + durum klasöründe
  işaret; kilit kum havuzunda gizli, kum'a kilit fd'leri devredilmez; kilit beklenirken yazım atlanmaz (uyarıyla beklenir).
  Commit'ler `9711e4c`, `dd145ba`, `b589973`, `0aca078`; test: `bin/test-hat-koruma` (22/22, geçici HOME).
  `~/beyin` `main`'ine alınması hattı **anında** değiştirir (betik çalışma ağacından koşar): hat boştayken,
  `beyin-gorev.timer` durdurularak al.
- **Ofis tarafı** (bu dal, canlıda bayraklar kapalı): `sunucu.gorev_kilidi()` aynı kilit dosyasını alır (30 sn, sonra
  503); `atomik_yaz` mkstemp + replace, izin korunur; görev okumaları `O_NOFOLLOW`; `canli_onayi_yaz` kimliği mühürden
  yalnız aynı görev+dal ise `<proje>-<sürüm>.onay.kimlik`'e kopyalar; motor mühür kimliği = onay kimliği = izlediği kart
  (ve dal) olmadıkça UAT paketi, onay ya da yayın kanıtı kabul etmez.
- **İkinci katman (dağıtım göstergesi, güvenlik sınırı değil)**: `HAT_ADIMLARI_ACIK`/`DAGITIM_ONAYI_ACIK` açılsa bile
  canlı `bin/calistir`'da `HAT_KORUMA_SURUMU` satırı VE hattın her koşuda `~/.local/state/beyin/hat-koruma-surumu`'ya
  yazdığı aynı sürüm yoksa hat/kapı/dağıtım adımları kapalı kalır: bayrakları beyin dalından önce açmak işe yaramaz.
  Betiği değiştirebilen biri işareti de yazdırabilir; asıl sınır, hiçbir ajanın `~/beyin/bin/**`'e yazamamasıdır
  (hat `YASAK`/`YASAK_GELISTIR` ve ofis `varsayilan_yasak_araclar` Edit/Write reddi; Bash geçit kancasıyla sınırlı).
- Sıra: beyin dalı canlıya → yeni hatla bir HomeOS görevi UAT'ye gelip `.kimlik` yazıldığı görülür → ayrı PR ile
  `ETKIN_AKISLAR`, `HAT_ADIMLARI_ACIK`, `DAGITIM_ONAYI_ACIK`, `YAZAN_AJAN_ACIK` (gerekiyorsa) değiştirilir.
- Kalan (kilitlenemez): ajanların kendi araçlarıyla görev dosyasına yaptığı yazımlar (teşhis ajanı, `Write(~/beyin/**)`
  izinli ofis ajanları). Ofis ret yazmadan önce dosyayı yeniden okur; değiştiyse yazmaz.

## Dağıtım penceresi (her yerel dağıtımdan önce)
```bash
# 1) koşan iş yok
curl -s 127.0.0.1:8796/api/ajanlar | python3 -c "import json,sys; print('koşan:', [a['id'] for a in json.load(sys.stdin)['ajanlar'] if a.get('durum') not in ('uyuyor', 'bitti', 'hata', None)])"
test ! -s ~/ajan-ofisi/durum/kuyruk.json && echo "kuyruk boş"
# 2) açık ajan-ofisi hat görevi yok (hazir/calisiyor/uat/takildi)
grep -l '^proje: ajan-ofisi$' ~/beyin/gorevler/*.md 2>/dev/null | xargs -r grep -LE '^durum: (bitti|reddedildi)$'
# 3) hattı duraklat (pencere boyunca yeni görev almasın)
systemctl --user stop beyin-gorev.timer
```

## Aşama 0 — GitHub eşitleme (PR #2, `ofis-1.0.86` → `main`)
1. GitHub'da **"Create a merge commit"** ile birleştir. (Squash/rebase yeni SHA'lar üretir; yerel `0c0c91b` uzak geçmişin atası olmaz ve `--ff-only` çalışmaz.)
2. Yerelde doğrula ve eşitle:
   ```bash
   cd ~/ajan-ofisi
   test "$(git rev-parse HEAD)" = 0c0c91b0a3643c5c60d028cc02dff8ec395378eb && git diff --quiet && git diff --cached --quiet && echo "beklenen ve temiz"
   git fetch origin
   git merge-base --is-ancestor HEAD origin/main && echo "ff mümkün"
   git diff --stat HEAD origin/main          # beklenen: boş (merge commit içerik değiştirmez)
   git merge --ff-only origin/main
   ```
   İçerik değişmediği için yeniden başlatma gerekmez.

## Aşama 1 — Workflow dağıtımı (PR #1 → `main`)
1. PR #1'in hedefini `main` yap, farkı doğrula: yalnız workflow commit'leri (`git log --oneline origin/main..origin/akis-motoru-v1`).
2. GitHub'da **merge commit** ile birleştir.
3. Dağıtım penceresi adımları (yukarıda) + Aşama 1 ön koşulları.
4. Yerel:
   ```bash
   cd ~/ajan-ofisi
   ONCEKI=$(git rev-parse HEAD); echo "$ONCEKI" > ~/ajan-ofisi-onceki-sha   # geri dönüş noktası
   git diff --quiet && git diff --cached --quiet || { echo "yerel değişiklik var, dur"; exit 1; }
   git fetch origin && git merge-base --is-ancestor HEAD origin/main && git merge --ff-only origin/main
   cat SURUM                                   # 1.0.88
   OFIS_AJANLAR=$PWD/ajanlar.example.json python3 -m unittest discover -p 'test_*.py' 2>&1 | tail -3
   ```
5. Yeniden başlat ve doğrula:
   ```bash
   systemctl --user restart ajan-ofisi.service
   systemctl --user is-active ajan-ofisi.service
   curl -s 127.0.0.1:8796/api/akis | python3 -c "import json,sys; d=json.load(sys.stdin); print([(t['id'], t['etkin']) for t in d['tanimlar']])"
   # beklenen: ornek-arastirma-ozeti True, homeos-ozellik-gelistirme False
   curl -s -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' \
     -d '{"akis":"homeos-ozellik-gelistirme","girdiler":{"baslik":"x x x","istek":"x"}}' 127.0.0.1:8796/api/akis/baslat   # 403
   curl -s -o /dev/null -w '%{http_code}\n' 127.0.0.1:8796/api/ajanlar   # 200 (eski uçlar)
   ```
6. Hattı yeniden aç: `systemctl --user start beyin-gorev.timer`. Hat klonu sonraki ajan-ofisi görevinde `~/ajan-ofisi`'den
   ileri sarılır (`is_gelistir`: fetch + `--ff-only`).
7. 10 dk boşta: `olaylar.jsonl`'de yeni `tur: akis` olayı ve model çağrısı olmamalı. Sonra araştırma akışını bir kez koş.

## Geri dönüş (Aşama 1)
```bash
# 1) etkin workflow koşularını panelden iptal et (çalışan ajan durmaz, sonucu yok sayılır);
#    kuyrukta/limit-bekleyen'de akis kaydı kalmadığını kontrol et (eski kod 'kaynak: akis' kaydını sessizce düşürür)
grep -c akis_ref ~/ajan-ofisi/durum/kuyruk.json 2>/dev/null; grep -l akis_ref ~/ajan-ofisi/durum/limit-bekleyen/*.json 2>/dev/null
# 2) kodu geri al (yalnız yerel; GitHub'a dokunmaz)
systemctl --user stop beyin-gorev.timer
cd ~/ajan-ofisi && git reset --hard "$(cat ~/ajan-ofisi-onceki-sha)"
systemctl --user restart ajan-ofisi.service && systemctl --user is-active ajan-ofisi.service
systemctl --user start beyin-gorev.timer
```
- `durum/akis.db` ve `durum/akis-sonuc/` kalabilir (eski kod okumaz; yeniden ileri alınca kaldığı yerden).
- `ajanlar.json`'daki `akis-okuyucu` eski kodda sıradan salt okunur ajandır.
- GitHub `main` ileride kalır; bir sonraki yerel ileri alma yine `--ff-only` ile yapılır. Hat bu arada bir ofis sürümünü
  canlıya alırsa GitHub push'u reddedilir (yerel geride): geri dönüş sürdükçe ajan-ofisi hat görevi açma.

## Kabul testinden kalanlar (kullanıcı kararıyla silinecek)
- `~/ajan-ofisi` içindeki `beyin/1119-workflow-v1-hat-adaptoru-kabul-testi` dalı ve `~/beyin-is/wt/ajan-ofisi-1119-workflow-v1-hat-adaptoru-kabul-testi` worktree'si
- `~/beyin/sistem/yayin/ajan-ofisi-1.0.87.zip` + `.sha256`, `~/.local/state/beyin/paket-muhur/ajan-ofisi-1.0.87.zip*`
- `~/beyin/gorevler/bitti/Workflow V1 hat adaptoru kabul testi.md` (reddedildi)

## V1.1 (1.0.89, canlı 2026-11-19: PR #3 `cd14a8e`, beyin `adc0346`)
Kapsam: backlog #1, #6, #7, #8, #9, #10, #11 (#5 ertelendi). Aşama 1 sabitleri (`ETKIN_AKISLAR`, `HAT_ADIMLARI_ACIK`,
`DAGITIM_ONAYI_ACIK`, `YAZAN_AJAN_ACIK`) **değişmedi**: HomeOS akışı yine kapalı.

Ön koşullar ve sıra:
1. `SURUM` 1.0.89 (kullanıcı kararı, 2026-11-19).
2. **DB migration 4** (`kosular.ek_maliyet_usd`, `ek_ajan_cagrisi`) yeniden başlatmada kendiliğinden koşar (yalnız
   `ALTER TABLE ADD COLUMN`). Önce yedek (makinede `sqlite3` komutu yok; Python ile, bütünlük kontrolüyle):
   ```bash
   python3 -c "import sqlite3,os; y=os.path.expanduser; k=sqlite3.connect(y('~/ajan-ofisi/durum/akis.db')); h=sqlite3.connect(y('~/akis.db.1.0.88.bak')); k.backup(h); print(h.execute('PRAGMA integrity_check').fetchone(), h.execute('PRAGMA user_version').fetchone())"
   chmod 600 ~/akis.db.1.0.88.bak   # beklenen: ('ok',) (3,)
   ```
3. `kosucu.py` değişti (SIGUSR1 iptal yolu): restart'tan önce tmux'ta çalışan workflow koşusu olmamalı (eski kosucu
   sinyali dinlemez; varsayılan eylem süreci öldürür). `tmux list-windows -t ofis` + `/api/akis` etkin koşu kontrolü.
4. Beyin dalı `hat-maliyet-esleme` (`adc0346`, `bin/test-hat-koruma` 25/25) ofisten bağımsızdır: önce ya da sonra
   alınabilir. Alınmazsa motor hat tahmini (6 $/tur) ile sürer; yalnız HomeOS akışı açılınca anlam kazanır.
5. Saklama aracı zamanlanmadı. İlk kez: `python3 akis_saklama.py` (kuru koşu) çıktısına bak; `--uygula` kullanıcı kararı.

Geri dönüş: Aşama 1 geri dönüşüyle aynı. Migration 4 sütunları eski kodda okunmaz (verilmiş ek bütçe yok sayılır =
sınır daralır). `durum/akis-arsiv/` eski kodda kullanılmaz.

## Aşama 2 — HomeOS geliştirme akışı (dal `akis-asama2`, 1.0.90, taslak PR; merge = pilotu açma kararı)
Değişen yalnız üç sabit: `ETKIN_AKISLAR` += `homeos-ozellik-gelistirme`, `HAT_ADIMLARI_ACIK = True`,
`DAGITIM_ONAYI_ACIK = True`. `YAZAN_AJAN_ACIK` kapalı kalır (akıştaki iki ajan adımı salt okunur `akis-okuyucu`).
Kapı mekanizması testleri aşama 1 değerleriyle (`asama1()`) koşmaya devam eder.

Durum (2026-11-19):
- [x] Beyin hat koruması canlıda (`~/beyin` `adc0346`, `HAT_KORUMA_SURUMU=1`, işaret dosyası var).
- [x] Pilot paketi oto-onaylanmaz: HomeOS oto-onayı kullanıcı kararıyla AÇIK (2026-11-19 22:39, 30 gün), ama workflow'un
      açtığı her hat görevi `oto_onay: hayir` taşır (`akis_ofis.gelistirme_yaz`) ve canlı `bin/calistir oto_onay_dene` bunu
      ilk satırda okuyup çıkar (gerçek `fm_get` ile doğrulandı). Dağıtım onayı yalnız Geliştirme UAT kartından (kapı).
- [ ] **Yeni hatla bir HomeOS görevi UAT'ye gelip `sistem/yayin/homeos-<sürüm>.zip.kimlik` yazıldı** (henüz yok: 2026-11-16'dan
      beri HomeOS görevi koşmadı). Bu görülmeden merge edilmemeli; motor kimliksiz paketi zaten kabul etmez (fail-closed),
      ama ilk gerçek kimlik dosyasının biçimi canlıda bir kez gözle doğrulanmalı.
- [ ] Merge + restart (Aşama 1 dağıtım penceresi ve adımlarıyla aynı; migration yok).

İlk pilot koşusu (kullanıcı başlatır): Workflow sekmesinden `homeos-ozellik-gelistirme`, küçük ve geri alınabilir bir
istek. Tavan 3 tur / 12 çağrı / 72 saat / 30 $. Dağıtım onayı yalnız Geliştirme UAT kartından (kapı imzalı).
Geri dönüş: 1.0.89'a `git reset --hard` (Aşama 1 geri dönüşü); etkin HomeOS koşusu önce panelden iptal edilir.

## V2 fan-out (dal `akis-fanout`, 1.0.91, taslak PR)
Davranış değişmez: `FANOUT_ACIK = False`, örnek akış `ETKIN_AKISLAR`'da değil. Tek etkisi DB migration 5 (yalnız ekleme).
1. Yedek: `python3 -c "import os,sqlite3; h=os.path.expanduser('~'); s=sqlite3.connect(h+'/ajan-ofisi/durum/akis.db'); s.backup(sqlite3.connect(h+'/akis.db.1.0.90.bak'))"`
   ve `git -C ~/ajan-ofisi rev-parse HEAD > ~/ajan-ofisi-onceki-sha`.
2. Merge → `git -C ~/ajan-ofisi pull --ff-only` → **hemen** `systemctl --user restart ajan-ofisi.service` (tekrar timer'ı
   `zamanlayici.py --tetikle` çalışma ağacından `Depo` açıp migrate eder; eski süreç yeni şemayla sorunsuz çalışır,
   migration yalnız ekler).
3. Kontrol: `PRAGMA user_version` = 5, testler 573/573.
Geri dönüş: `git reset --hard $(cat ~/ajan-ofisi-onceki-sha)` + restart. Eski kod sürüm 5 DB'de migration çalıştırmaz
ve `oge`/`ogeler`'i okumaz (eski INSERT/okuma test edildi). `ogeler.kosu_id` bilerek FK değildir: eski saklama koşuyu
silince `ogeler` satırları sahipsiz kalır (zararsız, yeni kod geri gelince okunmaz). Fan-out bayrağı açıldıysa süren fan-out koşuları önce iptal edilir.
Bayrağı açmak (`FANOUT_ACIK = True` + örneği `ETKIN_AKISLAR`'a eklemek) ayrı kod değişikliği ve kullanıcı kararıdır.

## V2 workflow_call (dal `akis-workflow-call`, 1.0.94, taslak PR; PR #9 `akis-graf` üstüne kurulu)
Davranış değişmez: `WORKFLOW_CALL_ACIK = False`, örnek akış `ETKIN_AKISLAR`'da değil. Tek etkisi DB migration 6 (yalnız ekleme).
Sıra: önce PR #9 (1.0.93), sonra bu PR. Adımlar fan-out ile aynı: yedek (`~/akis.db.1.0.93.bak`), önceki SHA, merge,
**hemen** `systemctl --user restart ajan-ofisi.service`, `PRAGMA user_version` = 6.
Geri dönüş: önceki SHA + restart. Bayrak açıldıysa önce alt akış çağıran üst koşular iptal edilir (eski kod
`workflow_call` adımını tanımaz; iptal alt koşuları da kapatır). Eski kod v6 DB'de çalışır (sütunlar eklemeli).
