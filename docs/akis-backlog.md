# Workflow backlog (V1.1, V2, V3)

> Kavramsal tasarım ve başarı ölçütleri: `akis-vizyon.md`.

> Bilinçli olarak `~/beyin/gorevler/` görevi olarak açılmadı: hat `durum: hazir` görevleri kendiliğinden alır ve
> ajan-ofisi oto-onaylı olabilir. Bir kalem seçilince Geliştirme sekmesinden (ya da elle) görev açılır.

## İş sırası (2026-11-19, kullanıcı: "ne var ne yoksa sıraya al ve başla")
Her kalem ayrı dal + PR; Aşama 1/2 sabitleri V2 PR'larında değişmez. Kalem bitince burada işaretlenir.
1. [x] Eski V1 artıkları temizlendi (worktree/dal); 1.0.87 paket artıkları kullanıcıya bırakıldı.
2. [x] V1.1 #7 canlı iptal denemesi (`r1b825e849ab1`): sinyal → claude 9 sn'de durdu, iptal sonucu, yedek/limit yok.
3. [~] HomeOS aşama 2: taslak PR #5 (`akis-asama2`, 1.0.90). Merge = pilotu açma kararı (kullanıcı); ön koşul `.zip.kimlik`.
4. [x] V2 maliyet modeli (p50/p90, bu dal).
5. [x] İptal edilen denemenin maliyeti (kosucu kısmi maliyet + motor `gec_maliyet` taraması): claude öldürülünce `total_cost_usd` yok → deneme 0/None sayılır. Bütçede
       iptal anına dek harcama görünmez (koşu zaten iptal, risk düşük); `stream-json` usage'tan kısmi maliyet.
6. [x] V2 zamanlayıcı tetiklemesi → 7. [ ] olay tetiklemesi (yeni yetki eklemez; beyin `bin/calistir` değişikliği ister → yalnız beyin dalında, #5 canlıya alınınca anlamlı).
8. [ ] V2 dinamik fan-out (liste çıktı türü + DB migration 5; dağıtımda tekrar timer'ları durdurulur ya da merge'den hemen sonra restart: `zamanlayici.py --tetikle` çalışma ağacından `Depo` açıp migrate eder) → 9. [ ] `workflow_call` (derinlik ≤ 2).
10. [ ] V2 değerlendirici-iyileştirici döngüsü.
11. [ ] V2 `plan_step` → 12. [ ] CEO workflow önerisi (model çıktısı yol seçtiği için en son).
13. [ ] V3 görsel editör / replay.
- #5 (dış çağrıda kilit) ertelendi: yalnız eşzamanlılık testiyle birlikte ele alınır.

## V1.1 (öncelikli)
1. ~~**Hat maliyet eşlemesi**~~ — V1.1: beyin dalı `hat-maliyet-esleme` (`adc0346`, `maliyet_kimligi_yaz`) + ofis `hat_maliyeti`; kabul: iki haiku turu 0,0105 $ (tahmin 12 $): (kullanıcı kararı 2026-11-19: V1.1). Koşu başına gerçek maliyet var
   (`~/.local/state/beyin/kosular/<zaman>-gelistir.json` → `total_cost_usd`, `.cache/kayit-tam.jsonl` → `maliyet`) ama
   görev yolu yok; paralel hatlarda göreve bağlanamaz. Öneri: `~/beyin/bin/calistir` `kos()` `kayit`'e ve JSON yanına
   `gorev` (4. argüman, görev dosyası) yazsın; adaptör bunu okuyup tahmini (6 $/tur) gerçekleşenle değiştirsin.
   Kabul ölçümü: iki haiku hat turu gerçekte ≈0,0105 $, motor tahmini 12 $. Bütçe tavanı (30 $) değişmez.
2. ~~**Görev dosyası için ortak dosya kilidi (hat değişikliği)**~~ — beyin dalı `hat-gorev-kilidi` + ofis `gorev_kilidi()`; canlıya alınması aşama 2 ön koşulu: `bin/calistir fm_set` kilitsiz yazar; ofis/workflow `uat_reddet` yazmadan hemen önce dosyayı yeniden okuyarak yarışı daraltır ama kapatamaz. İki taraf aynı `flock`'u alsın.
3. ~~**Görev dosyası yazımında symlink yarışı**~~ — mkstemp/`O_NOFOLLOW` (ofis), mktemp+mv ve symlink reddi (beyin dalı): (önceden var, ofisin elle `reddet` yolu da): `uat_reddet`/`atomik_yaz` symlink kontrolünü kilitten önce yapar ve okuma/yazma symlink izler; `~/beyin`'e yazabilen bir ajan kartı ya da `.ofis.tmp`'yi symlink'e çevirebilir. `O_NOFOLLOW` ve `mkstemp` ile yaz.
4. ~~**Onay kaydını göreve bağlama (hat değişikliği)**~~ — `<zip>.kimlik` + `.onay.kimlik`, motor kimlik denetimi: `~/.config/ofis-kapi/onaylar/<proje>-<sürüm>.onay` ve paket mührü
   yalnız proje-sürüme bağlı; görev dosyası kapısız yazılabildiği için workflow UAT anındaki kart değerine güvenmek
   zorunda. `canli_onayi_yaz` ve `paket_muhurle` görev dosya adını ve dalı da yazsın; motor bunları karşılaştırsın.
5. **Dış çağrıda kilit tutma**: motor, iptal yarışını kapatmak için `gorev_baslat`/görev dosyası yazımı süresince
   kendi kilidini tutuyor; `baslatma.lock` doluysa API birkaç saniye bekleyebilir (kilitlenme yolu yok: kuyruk tarafı
   motor kilidini almaz). Daha dar çözüm: denemeyi DB'de "sahiplenildi" işaretle, çağrıdan sonra yeniden kontrol et.
6. ~~**UAT kartında workflow uyarısı**~~ — V1.1: `Motor.hat_karti_durumu` + kart uyarısı (kapı bekleniyor / onay bekliyor / kapandı / okunamadı):: `kaynak: akis` görevlerinde Geliştirme kartı "kalite kapısı bekleniyor" göstersin.
   Şu an kapıdan önce elle onay yalnız sonradan `erken_onay` olarak işaretleniyor.
7. ~~**Çalışan koşuyu iptal**~~ — V1.1: doğrulanmış SIGUSR1 + kosucu iptal yolu (yedeğe/limite geçmez):: iptal şimdilik çalışan ajanı durdurmuyor. tmux penceresini kapatmak + `kosucu` sinyal
   yakalayıp bitiş yazmak (yarım yan etkiler için yine manual_review).
8. ~~**Hat ara durumları**~~ — V1.1: deneme tutamacında `hat: {durum, deneme}`, değişince `hat_ilerledi` olayı; karar vermez:: hat `calisiyor`/`deneme` alanlarını motor adım ilerlemesine yansıtsın (şimdi yalnız son durum).
9. ~~**Operatör kararları**~~ — V1.1: `basarili_say` (yalnız başarısız agent_task, kapı + gerekçe) ve `ek_butce` (migration 4, en çok 2×):: `inceleme`de "adımı başarılı say (gerekçe zorunlu, kapı imzalı)" ve "ek bütçe ver" eylemleri.
10. ~~**Saklama**~~ — V1.1: `akis_saklama.py` (varsayılan kuru koşu; `--uygula` arşivler `durum/akis-arsiv/<run>.json.gz` sonra siler; zamanlanmadı, açılması kullanıcı kararı):: bitmiş koşular ve `durum/akis-sonuc/*` için 90 gün sonra arşiv/silme.
11. ~~**SSE süzgeci**~~ — V1.1: `?tur=` (geçmiş + canlı), Workflow sekmesi ayrı akış açar ve olay gelen koşu satırını yerinde günceller; önceden `akis` olayı istemcide hiç dinlenmiyordu:: `/api/olaylar?tur=akis` ile yalnız workflow olayları; panel sayfa yenilemek yerine satır günceller.

## V2 — agentic orchestration (deterministik çekirdeğin üstünde)
- **Planlayıcı adım türü (`plan_step`)**: model, tanımın izin verdiği alt-grafik şablonlarından birini ve parametresini
  seçer. Seçim şema ile doğrulanır, yeni araç/ajan/kenar üretemez. Geçişler yine motorda deterministik.
- **Dinamik fan-out**: bir çıktı listesindeki her öğe için sınırlı sayıda (≤ N) paralel `agent_task`; birleştirme adımı.
- **Değerlendirici-iyileştirici döngüsü**: LLM-as-judge puanı + mutlaka bir gerçek kontrol. Puan tek başına kapıyı geçemez.
- **Alt workflow çağrısı** (`workflow_call`): sürüm sabitli, ayrı bütçe payı, derinlik ≤ 2.
- **CEO entegrasyonu**: CEO atama yerine "şu workflow'u şu girdilerle başlat" önerebilir. Başlatma yine kullanıcı onayıyla.
- ~~**Maliyet modeli**~~ — V2: hat adımında ≥5 ölçümde p90 (son 50, yalnız >0 ölçüm, statiğin %10'u taban); ajan adımında bütçe sert tavanla (`--max-budget-usd`) kalır, p50/p90 öngörü; `maliyet_modeli()` API'de; olayda `tahmin_kaynagi`.
- ~~**Zamanlayıcı tetiklemesi**~~ — V2: tekrar eden iş `{akis, girdiler, cron}`; hat/kalite kapısı/dağıtım onayı içeren akış aşama bayraklarından bağımsız zamanlanamaz (`zamanlama_engeli`); kayıtta akış etkin + girdi doğrulaması, tetikte idem `tekrar:<iş>:<dakika>`, motor kapıları yeniden uygular; Öngörülebilirlik formunda "Workflow" türü.
- **Olay tetiklemesi**: hat görevi `uat`/`takildi` olunca bağlı workflow'u ilerletmek için dosya izleme yerine bildirim.

## V3 — görsel workflow editörü
- Tanım JSON'undan otomatik çizim (seecode akış diyagramı ya da SVG): adım durumları canlı renk.
- Sürükle-bırak editör: adım ekle/bağla, alan/şablon formu, anlık şema doğrulaması (`akis_tanim.dogrula` aynı kurallar).
- Kaydetme = yeni dosya sürümü + git diff önizlemesi. Editör canlı tanımı değiştirmez; koşular tanım anlık görüntüsüyle sürer.
- Koşu yeniden oynatma: olay günlüğünden zaman çizelgesi, deneme karşılaştırması.
- Tanım şablon galerisi (araştırma, içerik, bakım, sürüm notu).
