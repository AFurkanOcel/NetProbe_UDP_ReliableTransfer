# NetProbe - Proje Haritası

**Bursa Teknik Üniversitesi | Bilgisayar Ağları Dersi Dönem Projesi**

NetProbe, UDP üzerinde güvenilir dosya aktarımı, trafik izleme ve ağ performans analizi yapmak için geliştirilmiş modüler bir Python projesidir.

---

## Projenin Amacı

UDP, TCP gibi güvenilir aktarım mekanizmalarını hazır olarak sunmaz. Paket kaybı, duplicate paketler, sıralama sorunları ve ACK eksikliği uygulama katmanında ele alınmalıdır.

Bu projede amaç:

- UDP üzerinde client/server dosya aktarımı yapmak
- Sequence number, ACK, timeout ve retransmission mekanizmalarını tasarlamak
- Dosya bütünlüğünü SHA-256 ile doğrulamak
- Trafik olaylarını loglamak
- Performans metrikleri üretmek
- Deney sonuçlarını grafiklerle analiz etmek

---

## Sistem Mimarisi

```text
Client
  |
  | UDP DATA packets
  v
Server
  |
  | ACK packets
  v
Client

Client/Server events -> CSV logs -> Analysis -> Graphs and metrics
```

Ana bileşenler:

| Bileşen | Açıklama |
| --- | --- |
| `config.py` | Port, paket boyutu, timeout, retry ve simülasyon parametreleri |
| `protocol.py` | DATA, ACK ve FIN paket formatları |
| `client.py` | Stop-and-Wait UDP istemci |
| `server.py` | Stop-and-Wait UDP sunucu |
| `logger.py` | Client/server olay loglama |
| `network_sim.py` | Test dosyası üretimi ve ağ koşulu simülasyonu |
| `analysis.py` | Metrik hesaplama ve grafik üretimi |
| `run_experiments.py` | Deney otomasyonu |
| `client_gbn.py`, `server_gbn.py` | Go-Back-N bonus aktarımı |
| `tcp_transfer.py` | TCP karşılaştırması |
| `dashboard.py` | Terminal dashboard |

---

## Protokol Tasarımı

### DATA Paketi

| Alan | Açıklama |
| --- | --- |
| `packet_type` | DATA paket tipi |
| `sequence_number` | Paketin sıra numarası |
| `total_packets` | Toplam paket sayısı |
| `payload_length` | Payload uzunluğu |
| `checksum` | Payload için SHA-256 hash |
| `payload` | Dosya parçası |

### ACK Paketi

| Alan | Açıklama |
| --- | --- |
| `packet_type` | ACK paket tipi |
| `ack_number` | Onaylanan sequence number |
| `reserved` | İleri kullanım için ayrılmış alan |

### FIN Paketi

| Alan | Açıklama |
| --- | --- |
| `packet_type` | FIN paket tipi |
| `file_checksum` | Tüm dosya için SHA-256 hash |

---

## Güvenilir Aktarım Akışı

1. Client dosyayı `PACKET_SIZE` değerine göre parçalara böler.
2. Her parça için DATA paketi oluşturulur.
3. Client paketi gönderir ve ACK bekler.
4. ACK doğruysa sıradaki pakete geçilir.
5. Timeout olursa aynı paket yeniden gönderilir.
6. Bir paket için maksimum `MAX_RETRIES = 5` deneme yapılır.
7. Tüm paketler başarılıysa FIN paketi gönderilir.
8. Server tüm dosyanın SHA-256 hash değerini doğrular.

Duplicate paket durumunda server aynı veriyi ikinci kez yazmaz; yalnızca ACK paketini yeniden gönderir.

---

## Deney Senaryoları

| Senaryo | Değişken | Amaç |
| --- | --- | --- |
| Paket boyutu etkisi | 256, 512, 1024, 4096 byte | Throughput ve goodput değişimini incelemek |
| Timeout etkisi | 0.5, 1.0, 2.0, 5.0 saniye | Completion time ve retransmission ilişkisini görmek |
| Kayıp oranı etkisi | 0%, 5%, 15%, 30% | Kayıp arttıkça goodput ve retry oranını analiz etmek |
| Dosya boyutu etkisi | 10KB, 100KB, 1MB, 10MB | Farklı dosya boyutlarında verimliliği ölçmek |

Her ana veri noktası 3 tekrar ile çalıştırılır. Deney çıktıları `results/graphs/` klasöründe saklanır.

---

## Bonus Özellikler

- Go-Back-N sliding window aktarımı
- Stop-and-Wait vs Go-Back-N karşılaştırması
- UDP Reliable vs TCP karşılaştırması
- Terminal dashboard
- Kayıp/gecikme simülasyonu
- Otomatik deney çalıştırma sistemi

---

## Grup Görev Dağılımı

| Üye | Sorumluluk Alanı |
| --- | --- |
| Mustafa Can ERSOY | Proje amacı, UDP protokol tasarımı, Stop-and-Wait client/server, checksum ve güvenilir aktarım |
| A. Furkan ÖCEL | Trafik izleme, loglama, ağ simülasyonu, metrik hesaplama, grafik üretimi ve deney analizi |
| Murat DEMİRBAŞ | Go-Back-N, TCP karşılaştırması, terminal dashboard, deney otomasyonu ve test doğrulama |

---

## Doğrulama

Proje şu komutlarla doğrulanır:

```bash
python -m compileall -q src tests
python -m pytest -q
```

Beklenen sonuç: tüm testlerin başarılı geçmesi.

---

## Teslim Notları

- Föy PDF'i GitHub deposuna eklenmemiştir.
- Log dosyaları, alınan dosyalar ve test binary dosyaları çalışma çıktısı olduğu için `.gitignore` ile dışarıda tutulmuştur.
- Deney grafikleri ve metrik JSON dosyası sonuçların incelenebilmesi için repoda tutulmuştur.
- Teknik rapor daha sonra `report/` klasörüne eklenecektir.
