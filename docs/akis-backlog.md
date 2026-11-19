# Workflow backlog (V2, V3)

> Bilinçli olarak `~/beyin/gorevler/` görevi olarak açılmadı: hat `durum: hazir` görevleri kendiliğinden alır ve
> ajan-ofisi oto-onaylı olabilir. Bir kalem seçilince Geliştirme sekmesinden (ya da elle) görev açılır.

## V1.1 (öncelikli)
1. **Hat maliyet eşlemesi** (kullanıcı kararı 2026-11-19: V1.1). Koşu başına gerçek maliyet var
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
6. **UAT kartında workflow uyarısı**: `kaynak: akis` görevlerinde Geliştirme kartı "kalite kapısı bekleniyor" göstersin.
   Şu an kapıdan önce elle onay yalnız sonradan `erken_onay` olarak işaretleniyor.
7. **Çalışan koşuyu iptal**: iptal şimdilik çalışan ajanı durdurmuyor. tmux penceresini kapatmak + `kosucu` sinyal
   yakalayıp bitiş yazmak (yarım yan etkiler için yine manual_review).
8. **Hat ara durumları**: hat `calisiyor`/`deneme` alanlarını motor adım ilerlemesine yansıtsın (şimdi yalnız son durum).
9. **Operatör kararları**: `inceleme`de "adımı başarılı say (gerekçe zorunlu, kapı imzalı)" ve "ek bütçe ver" eylemleri.
10. **Saklama**: bitmiş koşular ve `durum/akis-sonuc/*` için 90 gün sonra arşiv/silme.
11. **SSE süzgeci**: `/api/olaylar?tur=akis` ile yalnız workflow olayları; panel sayfa yenilemek yerine satır günceller.

## V2 — agentic orchestration (deterministik çekirdeğin üstünde)
- **Planlayıcı adım türü (`plan_step`)**: model, tanımın izin verdiği alt-grafik şablonlarından birini ve parametresini
  seçer. Seçim şema ile doğrulanır, yeni araç/ajan/kenar üretemez. Geçişler yine motorda deterministik.
- **Dinamik fan-out**: bir çıktı listesindeki her öğe için sınırlı sayıda (≤ N) paralel `agent_task`; birleştirme adımı.
- **Değerlendirici-iyileştirici döngüsü**: LLM-as-judge puanı + mutlaka bir gerçek kontrol. Puan tek başına kapıyı geçemez.
- **Alt workflow çağrısı** (`workflow_call`): sürüm sabitli, ayrı bütçe payı, derinlik ≤ 2.
- **CEO entegrasyonu**: CEO atama yerine "şu workflow'u şu girdilerle başlat" önerebilir. Başlatma yine kullanıcı onayıyla.
- **Maliyet modeli**: adım başına gerçekleşen maliyet geçmişinden p50/p90 tahmin; bütçe kontrolü p90 ile.
- **Zamanlayıcı tetiklemesi**: `zamanlayici.py` tekrar eden işine "workflow başlat" türü (idem anahtarı = zaman dilimi).
- **Olay tetiklemesi**: hat görevi `uat`/`takildi` olunca bağlı workflow'u ilerletmek için dosya izleme yerine bildirim.

## V3 — görsel workflow editörü
- Tanım JSON'undan otomatik çizim (seecode akış diyagramı ya da SVG): adım durumları canlı renk.
- Sürükle-bırak editör: adım ekle/bağla, alan/şablon formu, anlık şema doğrulaması (`akis_tanim.dogrula` aynı kurallar).
- Kaydetme = yeni dosya sürümü + git diff önizlemesi. Editör canlı tanımı değiştirmez; koşular tanım anlık görüntüsüyle sürer.
- Koşu yeniden oynatma: olay günlüğünden zaman çizelgesi, deneme karşılaştırması.
- Tanım şablon galerisi (araştırma, içerik, bakım, sürüm notu).
