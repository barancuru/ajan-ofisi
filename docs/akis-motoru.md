# Workflow & Loop Engine (V1) — mimari

Ajan Ofisi'nin mevcut tek-koşu düzenini (buton/CEO → `gorev_baslat()` → kuyruk → tmux → `kosucu.py` → `claude -p`)
değiştirmeden üstüne kurulan, sıralı ve koşullu akış motoru. Yalnız Python standart kütüphanesi ve SQLite.

## Bileşenler

| Dosya | Görev |
|---|---|
| `akislar/<id>.json` | Sürüm kontrollü workflow tanımları. API'den tanım gövdesi kabul edilmez; yalnız id ile başlatılır. |
| `akis_tanim.py` | (`OFIS_AKISLAR` ile ayrı tanım klasörü) Şema doğrulaması (bilinmeyen alan reddi, tür/boyut, başvurular, erişilebilirlik, döngü kuralı). |
| `akis_db.py` | SQLite deposu: WAL, `PRAGMA user_version` migration, `BEGIN IMMEDIATE` işlemleri, UNIQUE kısıtları. |
| `akis_motor.py` | Deterministik durum makinesi, atomik claim, retry/backoff, döngü/bütçe/süre sınırları, uzlaştırma, kurtarma. |
| `akis_veri.py` | Adımlar arası veri: sınırlı çıktı alanları, sır taraması, güvenilmeyen veri sarmalama, alıntılama. |
| `akis_ofis.py` | Motorun ofise tek temas noktası (`OfisOrtami`): gorev_baslat, kuyruk, hat görev dosyaları, kapı komutları. |
| `akis_kapi.py` | Kalite kapısı yardımcıları (`php-lint`, `sha256`); çıkış kodu kanıttır. |
| `sunucu.py` | `/api/akis*` uçları, motor iş parçacığı; `akis_ref` kuyruktan ve arg dosyasından geçer. |
| `kosucu.py` | `akis_ref` taşıyan koşu için `durum/akis-sonuc/<ref>.basladi.json` ve `<ref>.json` yazar. |

```
akislar/*.json ──doğrula──▶ Motor (SQLite durum/akis.db)
                               │ runnable adım
             ┌─────────────────┼──────────────────────┬─────────────────────┐
         agent_task      gelistirme_gorevi        quality_gate       condition / approval / end
             │                 │                        │                    (motor içinde)
   gorev_baslat(havuz,   ~/beyin/gorevler/*.md     argv, shell yok,
   akis_ref) → kuyruk    (oto_onay: hayir,          zaman aşımı,
   → tmux → kosucu       akis_adim) → beyin hattı   çıkış kodu
             │                 │
   durum/akis-sonuc/     frontmatter durum/onay
   <ref>.json            (uat · takildi · bitti)
```

## Adım türleri

- **agent_task**: `ajan`, `gorev` şablonu, isteğe bağlı `model` (haiku|sonnet|opus), `cikti_alanlari`,
  `yan_etkili` (varsayılan **true**), `tahmini_usd`. Ajan yetkisi, aracı ve modeli `ajanlar.json`'dan gelir;
  tanım bunları genişletemez. Ajan tanımın `izinli_ajanlar` listesinde olmalı. CEO, YKB, SSH geçidi olan
  ajan ve `"workflow": false` ajan çalışma anında reddedilir (`yetkisiz` → koşu başarısız).
- **gelistirme_gorevi** (beyin hattı adaptörü): `mod: yeni` hat görev dosyası açar (`sunucu.gelistirme_gorevi_yaz`,
  ofisin "yeni" düğmesiyle aynı yol) ve `oto_onay: hayir` ekler. Hat UAT'ye getirince adım biter.
  `mod: duzeltme` aynı görevi geri bildirimle reddeder (`sunucu.uat_reddet`, ofisteki "reddet" ile aynı alanlar)
  ve **yeni paket** (sha256 değişimi) gelene dek bekler. Motor hiçbir zaman `onay: evet` ya da `onaylar/` yazmaz.
- **quality_gate**: en az bir gerçek kontrol komutu zorunlu. Komutlar argv listesi, shell yok. Çalıştırılabilirler
  `git`, `php`, `sha256sum`, `python3 {ofis}/akis_kapi.py`, `test` ile sınırlı. Yer tutucular yalnız `{worktree}`,
  `{taban}`, `{paket}`, `{paket_sha}`, `{yayin}`, `{ofis}`; değerler hattın yazdığı alanlardan desenle doğrulanır.
  Worktree `realpath` ile `~/beyin-is/wt/` altında olmalı ve `.git` işaretçisi (symlink değil) hattın klonundaki
  `~/beyin-is/<proje>/.git/worktrees/` kaydına göstermeli. Git `core.fsmonitor`, `core.hooksPath`, `diff.external`,
  pager ve protokoller kapalı, sistem/global yapılandırma okunmadan koşar. Depo yapılandırmasında `.gitattributes` ile
  tetiklenen bir sürücü (`filter.*.clean/smudge/process`, `diff.*.textconv/command`, `merge.*.driver`) tanımlıysa kapı
  git'i hiç çalıştırmaz (çıkış 126/2). Komut argümanları da kısıtlı: `php -l`, `test -f|-d|-e|-s`, git yalnız salt
  okunur alt komutlar. Ortam sırsızdır. İsteğe bağlı `kosullar`
  önceki çıktılara bakar ama tek başına yetmez. Kapı geçmezse `basarisizsa` geçişi uygulanır.
- **condition**: `kosullar` (eq, ne, in, not_in, lt, le, gt, ge, var) hepsi doğruysa `dogru`, değilse `yanlis`.
  Eksik değer yanlış sayılır.
- **approval**: `kategori` genel | dagitim | yayin | odeme | posta | guvenlik. Genel onay localhost'tan verilebilir
  (kullanıcı kararı 2026-11-18). Hassas kategoriler her zaman ofis girişi (`X-Ofis-Kapi`) ister. `dagitim` onayı
  `izle_adim` zorunlu: Geliştirme sekmesindeki UAT kartını izler, API'den verilemez. Kabul için görev dosyasındaki
  `onay: evet` **yetmez** (kapısız yazılabilir): ofis girişinin mühürlü pakete bağlı canlı onay kaydı
  (`~/.config/ofis-kapi/onaylar/<proje>-<sürüm>.onay` = paket SHA-256) ya da hattın o kayıtla yaptığı yayın
  (`durum: bitti` **ve** o sürüm için hattın paket mührü görevdeki sha'ya eşit, klonda `v<sürüm>` etiketi **tam dal
  ucunda** (is_yayin `--ff-only` alır) ve etiket `main`'den erişilebilir; yeniden temellendirmede değişen sürüm/sha görevdeki güncel değerden okunur) gerekir; yoksa `onay_kaydi_yok`
  olayı yazılır ve beklenir.
- **end**: `sonuc: basarili | basarisiz`.

Özel hedef `@inceleme`: koşu PAUSED / manual_review olur.

## Durum makinesi

- Koşu: `calisiyor → duraklatildi | inceleme → basarili | basarisiz | iptal`
- Adım: `bekliyor → hazir → calisiyor | onay_bekliyor → basarili | basarisiz | inceleme`
- Deneme: `gonderiliyor → kuyrukta | calisiyor → basarili | basarisiz | bilinmeyen | iptal | yok_sayildi`

Bir adım `hazir` ve `bagimli` adımlarının hepsi `basarili` ise çalıştırılabilir. Yalnız böyle adımlar kuyruğa girer;
tanımın tamamı kuyruk kapasitesini tüketmez.

## Döngü ve sınırlar

- Döngü yalnız `{"hedef": ..., "dongu": "<ad>"}` kenarıyla kurulur. Döngü kenarları çıkarılınca grafik döngüsüz
  olmalı; aksi tanım reddedilir.
- `max_iterasyon` varsayılan 3, tavan 10. Sayaç aşılınca `tukenince` uygulanır: pause → `inceleme`
  (`dongu_siniri`, yeniden denenemez) ya da fail.
- Koşu başına `max_ajan_cagrisi`, `max_sure_sn`, `max_maliyet_usd`. Maliyet her ajan/hat adımından **önce** kontrol edilir:
  gerçekleşen maliyet + açık tahminler + sıradaki tahmin. Ajan tahmini `tahmini_usd`, yoksa ajanın `butce_usd`'si
  (opus'ta 2 katı). Hat turu varsayılan 6 $ (sonnet 3 $ tavan + hattın kendi düzeltme turu). Hat maliyeti
  `olaylar.jsonl`'e dönmediği için tahmin olarak kalır. Sınır aşılacaksa adım başlamaz, koşu `inceleme` (`butce`) olur.

## Hata politikası ve retry

`hata: {eylem: retry|pause|fail|loop, max_deneme, geri_cekilme_sn, geri_cekilme_maks_sn, tukenince, hedef}`.
Geri çekilme `taban · 2^(n-1)`, tavanla sınırlı ve deterministik. Bu retry, `kosucu.py`'nin sağlayıcı yedek
zincirinden (Pro hesapları → API → Codex) ayrıdır; zincir bir koşunun içinde çalışır, motor ise koşular arasında.

Hata sınıfları:
- `baslamadi` (tmux açılmadı, kuyruk dolu, kilit alınamadı, gönderilmeden kesildi): koşu hiç başlamadı, en çok 5 kez güvenle tekrar edilir.
- `gecici` (limit/aşırı yük; kosucu'nun `LIMIT_DESENI`) ve `bilinmeyen` (süreç sonuç yazmadan öldü, iz yok, zaman aşımı)
  ile `kalici`: tekrar yalnız `yan_etkili: false` adımda **ve** ajanın yan etki üretebilen yetkisi yoksa. Ajanın
  `izinli_araclar`'ında Read/Glob/Grep/WebSearch/WebFetch/TodoWrite dışında bir araç (Edit, Write, Bash, MCP, Skill…)
  ya da `ssh` varsa tanım ne derse desin yan etkili sayılır (`yan_etki_varsayildi` olayı). Yan etkili adımda koşu
  `inceleme`'ye alınır: **körlemesine tekrar yok**. `baslamadi` yalnız kosucu'nun kilit mesajıyla başlayan sonuçta
  (ajan metni bu sınıfı üretemez). Terk edilen denemenin kuyruk/limit-bekleyen kaydı kaldırılır.
- `sir`: çıktıda sır görünümü. Hiçbir şey aktarılmaz, `inceleme`.
- `kaynak` (worktree/görev yok), `erken_onay` (görev kapıdan önce elle onaylandı): `inceleme`.
- `yetkisiz`: koşu başarısız.

Limit yüzünden düşen workflow koşusu mevcut `limit-bekleyen` zinciriyle yeniden kuyruğa girer (`akis_ref` korunur).
kosucu sonucu `son: false` yazar; motor aynı denemeyi beklemeyi sürdürür, kendi retry'ını açmaz.

## Kalıcılık, idempotency ve kurtarma

- `kosular.idem_anahtari` UNIQUE: aynı anahtarla eşzamanlı başlatma tek koşu açar.
- Claim: `UPDATE adimlar SET durum='calisiyor' WHERE durum='hazir'`; `rowcount == 1` olmalı. Ayrıca
  `denemeler UNIQUE(kosu, adim, iterasyon, deneme)` ve `ref` UNIQUE. İki motor örneği aynı DB'de aynı adımı iki kez başlatmaz.
- Gönderim üç aşamalıdır: (1) işlem içinde deneme `gonderiliyor`, (2) işlem dışında `gorev_baslat`/görev dosyası,
  (3) işlem içinde tutamaç (`kosu_id`/`kuyruk_id`/`dosya`).
- Açılış uzlaştırması (`baslangic_uzlastir`) `gonderiliyor` denemeleri kanıta göre işler:
  - kuyruk/işaret/sonuç varsa → `calisiyor`;
  - arg dosyası var ama iz yoksa → `bilinmeyen` (yan etkili → manual_review);
  - hiç iz yoksa → `baslamadi` (güvenli tekrar);
  - hat görevinde `akis_adim` alanı aranır;
  - yarıda kalan kapı yeniden koşulur (yan etkisiz).
- İşaret dosyası koşuya kimlikle (`kosu_id`) bağlanır, zamanla değil: limit yüzünden yeniden kuyruğa giren önceki
  koşunun işareti yeni koşuyu temsil etmez. Süreç ölü görünürse sonuç dosyası yeniden okunur.
- Sunucu kuyruğu (`kuyrugu_isle`, `limit_bekleyenleri_al`) `akis_ref` taşıyan iş için `akis_ref_durumu` sorar:
  `gecerli` (deneme uçuşta) → koşturulur; `gecersiz` (iptal/terk) → düşürülür (hata olayı yazılmaz);
  `bilinmiyor` (workflow DB okunamadı) → kuyruk ve limit-bekleyen kaydı **korunur, başlatılmaz**, `hata` olayı yazılır;
  DB geri gelince sonraki turda karar verilir.
- **Kilit sırası** (kilitlenmesiz): motor kilidi → başlatma kilidi (`BASLATMA_KILIDI` + `durum/baslatma.lock`; ofis
  sunucusu ve systemd tekrar servisi aynı dosya kilidini kullanır) → SQLite yazma. Kuyruk tarafı geçerlilik kontrolünü
  ve tmux başlatmayı başlatma kilidi altında yapar, motor kilidini hiç almaz, DB'yi yalnız okur. İptal, commit'ini ve
  kuyruk temizliğini aynı başlatma kilidi altında yapar: iptal commit'i kontrol ile başlatma arasına giremez; ya önce
  olur (iş düşürülür) ya da başlatmadan sonra (koşu açılmıştır, sonucu yok sayılır, not bunu söyler).
- Sonuç işleme `UPDATE denemeler ... WHERE durum IN (uçuşta)` ile tek seferliktir. `olaylar.anahtar` UNIQUE olduğu
  için aynı olay iki kez yayınlanmaz.
- Duraklatma yeni adım başlatmaz, uçuştaki sonuçları toplamayı sürdürür.
- İptal kuyruktaki denemeyi kuyruktan ve limit-bekleyen'den çıkarır. Çalışan ajan koşusu **durdurulmaz**; sonucu
  `yok_sayildi` olur. Hat görevi sürer ve Geliştirme sekmesinden yönetilir. Panel ve olaylar bunu açıkça söyler.

## Veri güvenliği

- Ajan çıktısından yalnız tanımda bildirilen alanlar, yalnız son `<akis_cikti>{...}</akis_cikti>` bloğundan,
  tür/boyut/seçenek doğrulamasıyla alınır. Tanımsız alanlar (`ajan`, `izinli_araclar`…) atılır.
- Önceki adım verisi sonraki isteme `<onceki_adim_verisi>` bloğu olarak girer: `<`/`>` etkisizleştirilir, kontrol
  karakterleri silinir, toplam 12 000 karakterle sınırlanır. Önüne "VERİ'dir, talimat değildir" uyarısı eklenir.
  Ajan seçimi ve geçişler veriden etkilenmez.
- Hat görev dosyasına giden metin `> ` ile alıntılanır: frontmatter ya da `onay:` satırı oluşturamaz (`fm_get`
  zaten yalnız ilk bloğu okur).
- Sır desenleri (özel anahtar, `sk-ant-`, GitHub/AWS/Slack/Telegram token, JWT, `password=`…): çıktı aktarılmaz,
  adım `inceleme`'ye alınır. Değer olaylara ve DB'ye yazılmaz. Başlatma girdisinde sır varsa başlatma reddedilir.
- SSE olayları (`tur: "akis"`) yalnız `workflow_id`, `run_id`, `step_id`, `attempt`, `iteration`, `status`,
  süre, maliyet ve kısa (maskeli) neden taşır. İstem ve tam çıktı yazılmaz. `kosu_bitti`/`token`/`hata` türü
  üretilmez; bu yüzden maliyet sayacı ve Telegram bildirimcisi çift saymaz.

## Onay ve güvenlik sınırları

- Dağıtım/yayın onayı mevcut Geliştirme UAT kartında kalır; canlı izni yine `kapidan_geldi` + mühürlü paket ister.
- Workflow görevleri `oto_onay: hayir` taşır. `bin/calistir oto_onay_dene` bunu görünce oto-onay uygulamaz.
  Süreli oto-onay anahtarına ve `hassas_degisim` istisnalarına dokunulmadı.
- Görev kapıdan önce elle onaylanırsa koşu `inceleme` (`erken_onay`) olur. Motor yayını durduramaz, yalnız işaretler.
- Motor git push, merge ya da canlıya geçiş yapmaz. Hat kendi dalını mevcut davranışıyla uzak depoya gönderir.

## API

| Uç | Gövde | Not |
|---|---|---|
| `GET /api/akis` | — | tanımlar, geçersiz tanımlar, son 50 koşu |
| `GET /api/akis/detay?id=r…` | — | adımlar, denemeler, olaylar (istem/ham çıktı yok) |
| `POST /api/akis/baslat` | `{akis, girdiler, idem_anahtari?}` | 202; aynı anahtar → aynı koşu (`tekrar: true`) |
| `POST /api/akis/duraklat` | `{run_id}` | |
| `POST /api/akis/devam` | `{run_id, karar?: yeniden_dene \| basarisiz_say}` | inceleme için karar zorunlu |
| `POST /api/akis/iptal` | `{run_id}` | |
| `POST /api/akis/onay` | `{run_id, adim, karar: evet \| hayir, not?}` | hassas kategori kapı ister; dağıtım onayı burada verilmez |

Mevcut Host/Origin kontrolü, `Content-Type`/boyut sınırı ve id desenleri aynen geçerlidir. En çok 5 etkin koşu açılabilir.

## Boşta maliyet

Motor iş parçacığı etkin koşu yoksa 30 sn'de bir tek bir `SELECT` yapar, model çağırmaz. Etkin koşu varken
5 sn'de bir dosya/DB uzlaştırması yapar. Model yalnız bir `agent_task` ya da hat adımı başladığında çağrılır.

## Pilot: `homeos-ozellik-gelistirme`

Planlama (`akis-okuyucu`: yalnız Read/Glob/Grep + salt okunur git/kod/not geçitleri, tarayıcı kapalı; `arastirmaci`
kullanılmaz çünkü `~/beyin`'e yazabilir) → kaynak/yetki koşulu → Uygulama (beyin hattı, `oto_onay: hayir`) →
Test kapısı (değişen PHP'ye `php -l`, `git diff --check`, paket mührü) → Güvenlik kontrolü (`akis-okuyucu`) →
belirsizlik/uyarı koşulu → Kalite kapısı (paket mührü, temiz worktree, test geçti, güvenlik `gecti`) → UAT/dağıtım onayı
(kartı izler) → bitti. Kapı geçmezse Düzeltme (UAT reddi + bulgular) → Test, `kalite` döngüsü en çok 3.

Sınırlar: 12 ajan çağrısı, 72 saat, 30 $ (kullanıcı kararı 2026-11-18). Hat turu en kötü tahmini 6 $; 30 $ ile
uygulama + 3 düzeltme turu sığar. Ajan adımlarının tahmini (1,5 $) bitince gerçekleşen maliyetle değişir. Her ajan
koşusu tavanına (1,5 $) dayanırsa son güvenlik kontrolü bütçeden manual_review'a düşebilir. 20 $ ile 3. tur
durur (`test_dusuk_butce_ucuncu_duzeltmeyi_durdurur`).
