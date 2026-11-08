# 3DMidi — Raspberry Pi yayını

Hedef cihaz: Raspberry Pi 5, 8 GB, Raspberry Pi OS Lite 64 bit. Docker ve Compose gerekir. Python dönüşüm motoru Flask/Waitress ile çalışır; masaüstü `app/server.py` yerel kullanım için korunur.

Web hizmeti yalnızca G-code üretir ve indirir. Kullanıcı MIDI'leri ve özel yazıcı profilleri imzalı tarayıcı oturumuna bağlı, süreli ve boyutu sınırlı bellekte tutulur. HTTPS oturum çerezleri kullanılır. Yeniden başlatıldığında geçici oturumlar ve indirmeler sıfırlanır. G-code doğrulamaları, K2 X hareketi ve U1 varsayılan seçimi korunur.

Yayın paketinde kullanıcının seçtiği yerel kitaplığın 129 MIDI dosyası vardır: 120 popüler parça, Mario ve sekiz Mutopia örneği. Kaynak, atıf ve mevcut lisans bilgileri aynen korunur; lisansı belirtilmemiş kayıtlar bu şekilde gösterilir. Kayıtlar `app/popular_midi_sources.json`, `app/assets/library/SOURCES_AND_LICENSES.md` ve dönüşüm raporlarında bulunur. Ziyaretçiler ayrıca kendi MIDI'lerini yükleyebilir.

## Başlatma

Paketi Pi'de ayrı bir klasöre aç ve o klasörde çalış:

```sh
cp deploy/.env.example deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yaml build web
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d web
```

Sağlık kontrolü: `curl http://127.0.0.1:8765/api/health`. Port yalnızca Pi'nin loopback arayüzünde yayınlanır. Uygulamanın dış bağlantısı Cloudflare Tunnel üzerinden yapılır.

## Alan adı olmadan HTTPS denemesi

```sh
python3 deploy/enable_preview.py
```

Bu komut Cloudflare Quick Tunnel oluşturur, üretilen tek sunucu adını izin listesine ekler ve URL'yi `deploy/preview-url.txt` dosyasına kaydeder. Quick Tunnel test içindir: yeniden oluşturulduğunda adres değişir ve çalışma süresi garantisi yoktur. Pi/tünel yeniden başlatıldıktan sonra adresi güncellemek için aynı komutu tekrar çalıştır. Kalıcı yayın için aşağıdaki alan adı yöntemini kullan.

## Kalıcı alan adı

### Mevcut Tailscale hesabıyla sabit HTTPS

Alan adı satın alınana kadar Pi'nin Tailscale DNS adı kullanılabilir. Bu kurulumda adres `https://your-device.your-tailnet.ts.net` olur. Tailscale Funnel `--bg` ayarı daemon tarafından saklanır ve yeniden başlatmadan sonra geri gelir. `.env` içinde bu tam sunucu adı `MIDI_ALLOWED_HOSTS` listesine eklenir, `MIDI_PROXY_MODE=tailscale` seçilir. Dış ziyaretçilerin Tailscale kurması gerekmez. Funnel, Tailscale'ın bant genişliği sınırlarına tabidir; kendi alan adıyla Cloudflare seçeneği aşağıdadır.

```sh
tailscale funnel --bg --yes http://127.0.0.1:8765
python3 deploy/manage.py install
```

Yönetim komutu mevcut cron işlerini koruyarak 3DMidi için açılış kontrolü ve iki dakikalık sağlık denetimi ekler. Uygulama durmuşsa başlatılır; art arda üç başarısız kontrolde yalnızca 3DMidi web konteyneri yeniden başlatılır. Funnel'ın mevcut 443 portu başka bir servise aitse değiştirilmez.

İstanbul saatine göre her gün 03:00 sonrasındaki ilk kontrolde yapılandırma/kod yedeği alınır; yedi yedek tutulur. Yedekler `backups/` altında yalnızca kullanıcı tarafından okunabilir. Tünel token'ları, loglar ve eski yedekler arşive eklenmez. Kullanıcı MIDI'leri bellekte geçici tutulduğu için bu yedeklerde bulunmaz.

```sh
python3 deploy/manage.py status
python3 deploy/manage.py backup
python3 deploy/manage.py maintenance on
python3 deploy/manage.py maintenance off
```

Planlı bakımda önce bakım modunu aç. Bu sırada otomatik yeniden başlatma çalışmaz. Kalıcı adres `deploy/public-url.txt`, son kontrol ve yedek bilgisi `deploy/operations-state.json` içindedir.

### Pi bellek kotasını etkinleştirme

`python3 deploy/enable_memory.py` yalnızca önerilen boot değişikliğini gösterir. İncelenen değişikliği uygulayıp yeniden başlatmak için Pi üzerinde:

```sh
sudo python3 /home/quinry/3dmidi/deploy/enable_memory.py --apply --reboot
```

Komut `cmdline.txt` dosyasının yedeğini alır ve mevcut boot parametrelerini koruyarak yalnızca bellek cgroup bayraklarını düzenler. Yeniden açılışta `docker info` içinde bellek desteği, web konteynerinde 1 GiB RAM/swap toplam sınırı ve 2 CPU kotası doğrulanmalıdır. `manage.py status` desteğin etkinliğini gösterir. Yönetici parolası sohbette paylaşılmaz.

### Sahip olunan alan adıyla Cloudflare

1. Sahip olduğun alan adını Cloudflare'a ekle.
2. Cloudflare panelinde bir Tunnel oluştur. Public hostname'i yerel servis `http://web:8765` ile eşleştir. HTTP Host Header değerini değiştirme.
3. Tünel token'ını Pi'de `deploy/secrets/cloudflare_tunnel_token` dosyasına kaydet. Token'ı sohbet, kaynak kodu veya `.env` içine koyma. Bu dosya Docker secret olarak yalnızca tünel konteynerine bağlanır.
4. `deploy/.env` içinde `MIDI_ALLOWED_HOSTS=localhost,127.0.0.1,tam-alan-adin` olarak kullandığın tam sunucu adını yaz.
5. Çalıştır:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile preview stop preview
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile public up -d web tunnel
```

Her iki hizmet `unless-stopped` ilkesiyle yeniden başlatılır. Uygulama tek Waitress sürecinde dört iş parçacığı kullanır; dönüşümler sınırlı bir sırayla işlenir. Daha fazla süreç/kopya için ortak oturum ve iş deposu gerekir.

## Güncelleme ve izleme

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
docker compose --env-file deploy/.env -f deploy/compose.yaml logs --tail 60 web
docker compose --env-file deploy/.env -f deploy/compose.yaml build web
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --no-deps web
```

Uygulama konteyneri root olmadan, salt okunur dosya sistemi ve geçici `/tmp` ile çalışır. Kod ve dağıtım dosyaları Pi'nin proje klasöründedir; kullanıcı MIDI'leri için kalıcı dosya arşivi oluşturulmaz. Dönüşüm ve yükleme sınırları başlangıç ölçeği içindir; Pi üzerindeki gerçek trafik ölçülerek artırılmalıdır.

Kaynaklar: [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/), [Quick Tunnel sınırları](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), [Docker secret dosyaları](https://docs.docker.com/compose/how-tos/use-secrets/), [Flask oturum güvenliği](https://flask.palletsprojects.com/en/stable/web-security/), [Waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/).

Kalıcı Funnel davranışı: [Tailscale CLI](https://tailscale.com/docs/reference/tailscale-cli/funnel). Pi OS Lite bellek ayarı: [Pi OS üreticisinin kaydı](https://github.com/RPi-Distro/pi-gen/issues/917).
