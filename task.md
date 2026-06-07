# NetProbe - Teknik Teslim Takibi

## Durum

Hedef: UDP üzerinde güvenilir dosya aktarımı, trafik izleme ve performans analizi gereksinimlerini karşılayan tamamlanmış bir dönem projesi sunmak.

## Temel Sistem

- [x] UDP client/server dosya aktarımı
- [x] Stop-and-Wait aktarım
- [x] DATA / ACK / FIN paket yapısı
- [x] SHA-256 paket checksum
- [x] Transfer sonu dosya bütünlük kontrolü

## Güvenilir Aktarım

- [x] Sequence number
- [x] ACK kontrolü
- [x] Timeout
- [x] Retransmission
- [x] `MAX_RETRIES = 5`
- [x] Duplicate paket algılama
- [x] Başarısız paket varsa transferi başarısız işaretleme

## Trafik İzleme ve Analiz

- [x] Client/server ayrı CSV logları
- [x] SENT, ACK_RECEIVED, TIMEOUT, RETRANSMIT, FAILED, COMPLETE olayları
- [x] Throughput, goodput, RTT, loss rate, retransmission rate
- [x] Grafik üretimi

## Deneyler

- [x] Senaryo 1: Paket boyutu 256, 512, 1024, 4096
- [x] Senaryo 2: Timeout 0.5, 1.0, 2.0, 5.0
- [x] Senaryo 3: Kayıp oranı 0%, 5%, 15%, 30%
- [x] Senaryo 4: Dosya boyutu 10KB, 100KB, 1MB, 10MB
- [x] Her ana veri noktası için 3 tekrar
- [x] Başarısız runları sıfır metrik olarak grafikte kullanmama

## Bonuslar

- [x] Go-Back-N sliding window
- [x] Stop-and-Wait vs Go-Back-N karşılaştırma grafiği
- [x] UDP Reliable vs TCP karşılaştırma grafiği
- [x] Terminal dashboard
- [x] Otomatik deney çalıştırma sistemi

## Grup Görev Dağılımı

| Üye | Sorumluluk Alanı |
| --- | --- |
| Mustafa Can ERSOY | Proje amacı, UDP protokol tasarımı, Stop-and-Wait client/server, checksum ve güvenilir aktarım |
| A. Furkan ÖCEL | Trafik izleme, loglama, ağ simülasyonu, metrik hesaplama, grafik üretimi ve deney analizi |
| Murat DEMİRBAŞ | Go-Back-N, TCP karşılaştırması, terminal dashboard, deney otomasyonu ve test doğrulama |

## Doğrulama Komutları

```bash
pip install -r requirements.txt
python -m compileall -q src tests
python -m pytest -q
cd src
python run_experiments.py
```

## GitHub Teslim Durumu

- [x] Kaynak kodlar parça parça commit edildi
- [x] Testler ve deney grafikleri eklendi
- [x] README hazırlandı
- [x] Grup görev dağılımı eklendi
- [x] Föy PDF'i GitHub dışında tutuldu
- [x] Loglar, received dosyaları ve test binary dosyaları `.gitignore` ile dışarıda bırakıldı

## Kapsam Dışı

- [ ] Teknik rapor daha sonra eklenecek
- [ ] Ders sunumu sınıfta yapılacak
