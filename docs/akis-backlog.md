# Workflow backlog (V2, V3)

> Bilinçli olarak `~/beyin/gorevler/` görevi olarak açılmadı: hat `durum: hazir` görevleri kendiliğinden alır ve
> ajan-ofisi oto-onaylı olabilir. Bir kalem seçilince Geliştirme sekmesinden (ya da elle) görev açılır.

## V1 sonrası küçük işler (öncelikli)
1. **Pilot bütçesi**: 20 $ tavanı ile 6 $ hat turu tahmini 3. düzeltme turunu durduruyor. Ya tavan ~27 $ olmalı, ya
   hattın gerçek maliyeti (`sistem/kayit.md` / `.cache/kayit-tam.jsonl` maliyet sütunu) adaptöre okutulup tahmin
   gerçekleşenle değiştirilmeli.
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
