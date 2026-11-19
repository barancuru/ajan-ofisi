# Workflow V1 — canlıya alma kontrol listesi ve rollback planı

> Canlı ofis `~/ajan-ofisi` (systemd `--user` servisi, `main` çalışma kopyası). Bu dalı `main`'e almak dosyaları
> **hemen** değiştirir; yeniden başlatma yalnız yeni kodu (motor iş parçacığı dahil) devreye alır. Bu yüzden merge
> fiilen bir dağıtımdır ve yalnız kullanıcı kararıyla yapılır.

## Önce (merge'den önce)
1. [ ] PR incelendi; CI yok, testler yerelde: `OFIS_AJANLAR=ajanlar.example.json python3 -m unittest discover -p 'test_*.py'`
       hepsi geçer (yalın çalıştırmada `test_revize.test_bilinmeyen_ajan_404` zaten main'de de hata verir).
2. [ ] Ofiste koşan ajan yok (`GET /api/ajanlar` hepsi uyuyor), `durum/kuyruk.json` boş, hat ajan-ofisi görevi açık değil.
3. [ ] Yedek: `git -C ~/ajan-ofisi rev-parse main` değerini not et (geri dönüş noktası; şu an `0c0c91b`).
       `cp ~/ajan-ofisi/ajanlar.json ~/ajan-ofisi/ajanlar.json.yedek-<tarih>`.
4. [ ] Sürüm: dal `1.0.88`. `~/beyin/gorevler/bitti/Workflow V1 hat adaptoru kabul testi.md` 1.0.87 kullandı; çakışma yok.

## Merge ve açılış
5. [ ] PR'ı `main`'e al (tercihen merge commit, `--no-ff`: tek komutla geri alınır; push sonrası `~/ajan-ofisi` `receive.denyCurrentBranch=updateInstead`
       ile güncellenir ya da `git -C ~/ajan-ofisi pull --ff-only`).
6. [ ] `ajanlar.json`'a pilot ajanı ekle (`arastirmaci`'ya dokunma): `ajanlar.example.json` içindeki `akis-okuyucu`
       girdisini kopyala, `cwd`'yi `~/beyin` yap. Yalnız `Read`, `Glob`, `Grep`; `tarayici: false`.
       Eklemezsen pilot ilk ajan adımında `yetkisiz` ile durur (güvenli taraf).
7. [ ] Servisi yeniden başlat (`systemctl --user restart <ofis servisi>`). İlk açılışta `durum/akis.db` oluşur (WAL).
8. [ ] Doğrula: `curl -s 127.0.0.1:8796/api/akis` iki tanım döner, `gecersiz` boş; ofiste Araçlar → Workflow açılır;
       mevcut sekmeler (Geliştirme, Operatör, Maliyet, Model kullanımı) açılır; `/api/gorev` ile bir hazır görev koşar.
9. [ ] Boşta maliyet: 10 dk sonra `olaylar.jsonl`'de `tur: akis` olayı yok, yeni `kosu_basladi` yok.

## İlk kullanım
10. [ ] Önce `ornek-arastirma-ozeti` (salt okunur, ~0,2–0,5 $). Onay adımında onayla; koşu `basarili`.
11. [ ] Pilot `homeos-ozellik-gelistirme` küçük bir HomeOS işiyle. Hat görevi `oto_onay: hayir` taşır; dağıtım onayı
        Geliştirme kartından **ofis girişiyle** verilir. Workflow yalnız kaydı görünce `uat_onayi`'ni geçer.
12. [ ] Bütçe sınırı 30 $ (pilot), döngü 3 iterasyon; değiştirme.

## Rollback
- **Motoru durdurmak, kodu tutmak (en hızlı):** etkin koşuları panelden "İptal" et. Gerekirse `akislar/` içindeki
  tanımları başka yere taşı: tanımsız akış başlatılamaz, motor etkin koşu yokken yalnız bir SELECT yapar.
- **Kodu geri almak:**
  1. Etkin workflow koşularını iptal et (çalışan ajan durdurulmaz; bitince sonucu yok sayılır). Açık hat görevleri
     (`kaynak: akis`) normal hat görevi olarak kalır ve Geliştirme sekmesinden yönetilir.
  2. Kodu geri al ve servisi yeniden başlat:
     - merge commit ile alındıysa (`--no-ff`, önerilen): `git -C ~/ajan-ofisi revert -m 1 <merge commit>`;
     - fast-forward alındıysa: `git -C ~/ajan-ofisi revert --no-edit <adım 3'teki SHA>..<alınan HEAD>`;
     - push edilmediyse yerelde `git -C ~/ajan-ofisi reset --hard <adım 3'teki SHA>` de olur.
  3. Eski kod `durum/akis.db`'yi okumaz; dosya kalabilir (veri kaybı yok, yeniden ileri alınca devam eder).
     `durum/akis-sonuc/` işaretleri zararsızdır.
  4. Kuyruk uyumluluğu: eski kod `kaynak: "akis"` kuyruk kaydını geçersiz sayıp **sessizce düşürür**
     (`_kuyruk_dogrula`, `KUYRUK_KAYNAKLARI` yalnız buton/ceo/tekrar); limit-bekleyen kaydını ise `kaynak` alanını
     "buton"a çevirip `akis_ref`'siz koşturur. Geri almadan önce `durum/kuyruk.json` ve `durum/limit-bekleyen/` içinde
     `akis_ref` taşıyan kayıt kalmadığını kontrol et (iptal bunları zaten temizler).
  5. `ajanlar.json`'daki `akis-okuyucu` girdisi eski kodda sıradan bir salt okunur ajandır; kalabilir ya da silinir.
- **Kabul testinden kalanlar (kullanıcı kararıyla silinecek):** `~/ajan-ofisi` içindeki
  `beyin/1119-workflow-v1-hat-adaptoru-kabul-testi` dalı, `~/beyin-is/wt/ajan-ofisi-1119-workflow-v1-hat-adaptoru-kabul-testi`
  worktree'si, `~/beyin/sistem/yayin/ajan-ofisi-1.0.87.zip` + `.sha256` ve `~/.local/state/beyin/paket-muhur/ajan-ofisi-1.0.87.zip*`.
