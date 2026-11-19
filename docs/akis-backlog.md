# Workflow backlog (V2, V3)

> Bilinçli olarak `~/beyin/gorevler/` görevi olarak açılmadı: hat `durum: hazir` görevleri kendiliğinden alır ve
> ajan-ofisi oto-onaylı olabilir. Bir kalem seçilince Geliştirme sekmesinden (ya da elle) görev açılır.

## V1.1 (öncelikli)
1. **Hat maliyet eşlemesi** (kullanıcı kararı 2026-11-19: V1.1). Koşu başına gerçek maliyet var
   (`~/.local/state/beyin/kosular/<zaman>-gelistir.json` → `total_cost_usd`, `.cache/kayit-tam.jsonl` → `maliyet`) ama
   görev yolu yok; paralel hatlarda göreve bağlanamaz. Öneri: `~/beyin/bin/calistir` `kos()` `kayit`'e ve JSON yanına
   `gorev` (4. argüman, görev dosyası) yazsın; adaptör bunu okuyup tahmini (6 $/tur) gerçekleşenle değiştirsin.
   Kabul ölçümü: iki haiku hat turu gerçekte ≈0,0105 $, motor tahmini 12 $. Bütçe tavanı (30 $) değişmez.
2. **UAT kartında workflow uyarısı**: `kaynak: akis` görevlerinde Geliştirme kartı "kalite kapısı bekleniyor" göstersin.
   Şu an kapıdan önce elle onay yalnız sonradan `erken_onay` olarak işaretleniyor.
3. **Çalışan koşuyu iptal**: iptal şimdilik çalışan ajanı durdurmuyor. tmux penceresini kapatmak + `kosucu` sinyal
   yakalayıp bitiş yazmak (yarım yan etkiler için yine manual_review).
4. **Hat ara durumları**: hat `calisiyor`/`deneme` alanlarını motor adım ilerlemesine yansıtsın (şimdi yalnız son durum).
5. **Operatör kararları**: `inceleme`de "adımı başarılı say (gerekçe zorunlu, kapı imzalı)" ve "ek bütçe ver" eylemleri.
6. **Saklama**: bitmiş koşular ve `durum/akis-sonuc/*` için 90 gün sonra arşiv/silme.
7. **SSE süzgeci**: `/api/olaylar?tur=akis` ile yalnız workflow olayları; panel sayfa yenilemek yerine satır günceller.

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
