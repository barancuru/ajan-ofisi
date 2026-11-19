# Workflow & Loop Engine — kavramsal tasarım (ürün vizyonu)

> Ürün referansıdır, geliştirme görevi ya da kapsam kararı değildir. Teknik ayrıntı `akis-motoru.md`,
> sıradaki işler `akis-backlog.md`. Kaynak: kullanıcının 2026-11-19 tarihli kavramsal tasarım metni.

## 1. Tanım

Ajan Ofisi, birden çok yapay zekâ ajanının ortak bir hedef için planlama, yürütme, değerlendirme, düzeltme ve sonuç
üretme süreçlerini yöneten, insan denetimini koruyan, kalıcı hafızalı bir çoklu ajan orkestrasyon platformudur.
Ajanları tek tek çalıştıran bir panelden, bir işi başlangıcından doğrulanmış sonucuna kadar yönetebilen bir iş
organizasyonuna geçiş hedeflenir.

| Rol | Görev |
|---|---|
| CEO ajanı | Hedefi anlar, işi ayrıştırır, uzman ajanları ve kayıtlı workflow'u **önerir** |
| Workflow Engine | Sıra, bağımlılık, durum, geçiş ve yetki sınırları |
| Loop Engine | Yetersiz çıktıyı tanımlı kalite kriterine dek kontrollü iyileştirme |
| Uzman ajanlar | Araştırma, geliştirme, analiz, test, inceleme, içerik |
| İnsan operatör | Kritik kararlar, kalite denetimi, yetki gerektiren onaylar, müdahale |
| Ofis arayüzü | Organizasyonu canlı görselleştirir, yönetilebilir ve denetlenebilir kılar |

Temel ilke: yapay zekâ neyin yapılabileceğini planlar ve çıktıyı üretir; **neyin çalıştırılacağına, hangi koşulla
ilerleneceğine ve hangi işlemin insan onayı istediğine güvenilir orkestrasyon motoru karar verir.**

## 2. Mimari katmanlar

```
Kullanıcı/Operatör: 3B ofis · görev panosu · Workflow · onay · maliyet · canlı gözlem
        │
CEO / Planlayıcı / Supervisor — hedef ayrıştırma, ajan seçimi, workflow önerisi
        │
Workflow Engine (DAG, koşul, kuyruk, checkpoint) · Loop Engine (retry, reflection, iteration)
Policy & Human Gate (yetki, risk, bütçe, onay) · State & Observability (SQLite, olay, audit, maliyet)
        │
Agent Execution: araştırma · geliştirme · test · inceleme · analiz · içerik
        │
Araçlar, modeller, kurumsal hafıza: Claude ve diğer sağlayıcılar · git · terminal · beyin hattı · bilgi grafı · notlar · skills
```

Mimari mevcut `gorev_baslat → kuyruk → tmux → kosucu` altyapısını korur; motor bunun üstünde bir kontrol düzlemidir.

## 3. Workflow Engine

Her workflow sürümlenebilir bir tanımdır: girdiler, adımlar, bağımlılıklar, geçiş koşulları, yetkili ajanlar,
kalite kriterleri, hata politikaları ve kaynak sınırları.

Hedef yetenekler: sıralı yürütme, koşullu dallanma, bağımlılık yönetimi, paralel yürütme, görev devri, dinamik
planlama (yalnız önceden izin verilmiş alt akışlar arasından), alt workflow, istisna yönetimi (başarısızlık,
belirsizlik, yetki eksikliği, zaman aşımı ayrı), kalıcı ilerleme, insan müdahalesi, çoklu tetikleme, kanıt ve
maliyetle ilişkilendirilmiş sonuç.

**Değişmez karar:** workflow, ajanın serbest metniyle yeniden programlanmaz. Ajan yalnız tanımın izin verdiği
seçenekler arasından karar önerir; durum geçişini motor yapar.

Yaşam döngüsü: talep → planlama → yürütme → doğrulama → düzeltme ya da karar → tamamlama. Doğrusal olmak zorunda
değildir; koşul, bağımlılık, alt akış ve geri dönüş kenarlarıyla yönlendirilmiş bir iş grafıdır.

## 4. Loop Engine

- **Retry loop:** geçici altyapı/kota hatasında üstel geri çekilme, en çok deneme. Yan etki üretmiş ve sonucu
  belirsiz işlem körlemesine tekrarlanmaz.
- **Reflection loop:** üretici → değerlendirici → test/kalite → düzeltme → yeniden değerlendirme.
- **Iteration loop:** dosya listesi, issue kümesi, belge grubu aynı işlemden sınırlı paralellikle geçer, sonuç
  birleştirme adımında değerlendirilir.

Her döngüde durdurma koşulu zorunludur (başarı, yineleme, süre, bütçe, çağrı sınırı). Sınırsız otonom döngü
tasarımın parçası değildir.

## 5. Çoklu ajan koordinasyonu ve CEO

CEO üst düzey planlayıcıdır; motor yürütme ve politika otoritesidir. CEO bir yol önerir, motor yetkili ve geçerli
bir süreç dışında işlem başlatmaz. Hedef yetenekler: hedef ayrıştırma, uzman seçimi, model yönlendirme (zorluk,
maliyet, kapasite), yapılandırılmış devir, supervisor izleme, kapasite yönetimi, kayıtlı workflow önerisi, operatöre
eskalasyon. Sağlayıcı yedek zinciri (tek çağrının tamamlanması) ile workflow retry'ı (adımın yeniden yürütülmesi)
ayrıdır.

## 6. Hafıza ve bilgi

İki katman: **operasyonel hafıza** (adımlar, checkpoint, idempotency anahtarı, onaylar) ve **bilgi hafızası**
(`~/beyin` notları, depolar, salt okunur git geçitleri, bilgi grafı).

| Veri sınıfı | İçerik | İlke |
|---|---|---|
| Workflow tanımı | Adımlar, yetkiler, geçişler, sınırlar | Sürümlü, doğrulanmış, güvenilir |
| Koşu durumu | Aktif adım, deneme, checkpoint, onay | Kalıcı ve tutarlı |
| Ajan çıktısı | Bulgu, plan, özet, karar önerisi | **Güvenilmeyen veri** |
| Proje bilgisi | Kod, doküman, graf, önceki kararlar | Görevin yetkisine göre erişim |
| Denetim izi | Kim, ne zaman, hangi işlem, sonuç | İzlenebilirlik |

Ajan çıktısındaki komut, yetki talebi ya da sahte onay motor tarafından uygulanmaz.

## 7. İnsan denetimi ve güvenlik

- **Quality gate:** test, lint, git kontrolleri, paket bütünlüğü. Kanıt gerçek komut çıkışıdır; "testler geçti"
  cümlesi yetmez.
- **Human approval:** genel onay ile dağıtım, yayın, ödeme, posta, güvenlik kategorileri ayrıdır; hassas olanlar
  kimlik doğrulaması ve işlem kanıtı ister.
- **Manual review:** belirsiz sonuç, güvenilmeyen çıktı, kimlik uyuşmazlığı, kritik hata, limit aşımı. Operatör
  yeniden dene / başarısız say / iptal kararı verir.

Tamamlayıcılar: maliyet yönetimi, sır tespiti, araç izinleri, salt okunur ajan profilleri, süreç izolasyonu,
güvenli dosya işlemleri, olay kaydı. Özü **fail-closed**: yetki ya da durum kesin doğrulanamıyorsa riskli işlem
çalışmaz, iş güvenle bekletilir.

## 8. Workflow Control Center

Workflow panosu, koşu görünümü (adım, deneme, iterasyon), ajan görünümü, onay merkezi, müdahale paneli (duraklat,
devam, yeniden dene, iptal), maliyet paneli, denetim zaman çizelgesi, görsel editör, şablon galerisi, koşu yeniden
oynatma. 3B ofis ajanın hangi görevde çalıştığını, beklediğini, takıldığını ya da karar beklediğini gösterir.
Editör sürümlü tanım üstünde çalışır; çalışan koşunun tanımını geriye dönük değiştirmez.

## 9. Tetikleme

Manuel, CEO önerisi (onay sonrası), zamanlayıcı, sistem olayı (ör. hat görevi UAT'ye geldi), bağımlılık tamamlanması.
Bütün tetikleyiciler aynı güvenlik, bütçe, idempotency ve kaynak sınırlarına tabidir; zamanlayıcının ya da CEO'nun
başlattığı iş normalde yasak bir işleme yetki kazanmaz.

## 10. Senaryolar

- **A — Araştırma ve raporlama:** araştır → kaynak kontrolü → özetle → insan onayı. 1.0.88'de canlıda kabul edildi.
- **B — HomeOS özellik geliştirme:** istek → plan → uygulama → test → güvenlik → kalite kapısı; başarısızsa
  gerekçeli düzeltme; başarılıysa UAT → insan dağıtım onayı. Pilot bütçesi 3 iterasyon, 12 çağrı, 72 saat, 30 $
  (akışın bütçesi, platform varsayılanı değil). Canlıda **bilerek kapalı**; açılması ayrı sürüm kararı.
- **C — Çoklu iş:** örneğin on GitHub issue'su değerlendirilir, kapasite sınırıyla dağıtılır, her biri kalite
  döngüsünden geçer, sonuçlar tek raporda birleşir. Iteration loop + fan-out + alt workflow + supervisor; vizyonun
  parçası, V1'de yok.

## 11. Yol haritası

| Sürüm | Kapsam | Durum (2026-11-19) |
|---|---|---|
| V1 — Deterministik çekirdek | JSON tanım, ajan görevleri, koşul, temel retry/loop, kalite kapısı, insan onayı, SQLite, maliyet sınırı, kurtarma, panel | Teslim (1.0.88, `cdc6d76`, 489/489 test, ilk koşu 0,251 $) |
| V1.1 — Operasyonel olgunlaşma | Gerçek hat maliyeti, UAT deneyimi, operatör müdahaleleri, saklama, iptal, gözlemlenebilirlik | Geliştiriliyor (`akis-backlog.md`) |
| V2 — Agentic orchestration | Dinamik planlama, reflection, fan-out, alt workflow, CEO önerisi, zaman/olay tetikleyici, tahmine dayalı bütçe | Tasarım |
| V3 — Görsel orkestrasyon | Sürükle-bırak editör, canlı graf, versiyonlama, zaman çizelgesi, replay, şablon galerisi | Tasarım |

Canlıda etkin: salt okunur araştırma workflow'u, insan onayı, maliyet kontrolü, durum takibi, güvenli yeniden
deneme. Etkin değil: HomeOS geliştirme workflow'u, otomatik dağıtım onayı, dinamik planlama, görsel editör.

## 12. Başarı ölçütleri

Otonomi (insan müdahalesiz tamamlanan uygun iş oranı), kalite (ilk denemede geçiş, düzeltme sonrası başarı, yeniden
açılan iş), verimlilik (talepten doğrulanmış sonuca süre), maliyet (iş başına gerçek maliyet, tahmin sapması),
güvenlik (engellenen yetkisiz işlem, onaysız yan etki sayısı), dayanıklılık (kesinti sonrası kurtarma, mükerrer
işlem önleme), izlenebilirlik (sonucun karar/kaynak/test kanıtına bağlanma oranı), kullanılabilirlik (operatör
müdahale süresi), tekrar kullanılabilirlik.

## 13. Değişmez üç ilke

1. **Deterministik kontrol, esnek zekâ:** ajanlar üretir ve önerir; motor yetki ve geçişleri belirler.
2. **Ölçülebilir tamamlanma:** "ajan bitirdi" değil, "iş kabul kriterlerini geçti ve sonucu doğrulandı".
3. **Kademeli otonomi:** güvenilirliği kanıtlanan süreç daha az müdahale ister; kritik kararlar insanda kalır.
