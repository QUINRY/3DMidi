# 3DMidi

MIDI dosyalarından 3D yazıcı motorlarında müzik çalan G-code üretir. Windows uygulaması çevrimdışı çalışır ve 129 örnek MIDI içerir.

[Windows sürümünü indir](https://github.com/QUINRY/3DMidi/releases/latest) · [English](README.md)

1. `3DMidi.exe` dosyasını indir ve çift tıkla. Python veya kurulum gerekmez.
2. Yazıcını seç; varsayılan Snapmaker U1’dir.
3. MIDI dosyanı veya kitaplıktan bir örneği seç.
4. Hareket hızını ve tempoyu ayarla, G-code oluştur.
5. Kısa testi, tam dosyayı veya kontrol raporunu Farklı Kaydet ile kaydet.

> [!IMPORTANT]
> **Klipper tabanlı yazıcılarda, oluşturulan G-code dosyalarını yazıcı ekranından değil, Klipper web arayüzünden (Mainsail / Fluidd) başlatın.**

Varsayılan dil İngilizcedir. **Settings → Language → Türkçe** yoluyla Türkçeye geçebilirsin. Dil seçimi anında uygulanır ve bilgisayarında saklanır. İngilizce, Türkçe, Almanca, İspanyolca, Fransızca, Portekizce, Çince, Japonca, Rusça ve Arapça bulunur. Çevirisi olmayan teknik ayrıntılar İngilizce gösterilir.

Windows 10/11 x64 ve [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) gerekir. EXE kod imzalı değildir.

U1’de XY, V3 KE ve K2 serisinde yalnızca X ekseni müzik için kullanılır. Desteklenen Bambu Lab modelleri yerleşik M1006 ses komutlarını kullanır. Z ekseninde melodi üretilmez. Başlangıç ve homing seçilen profile bağlıdır. Tüm modellerde fiziksel test yapılmış değildir; profil notlarını oku ve önce kısa testi dene.

Derleme, kaynak koddan çalıştırma ve lisans ayrıntıları için [İngilizce README](README.md) dosyasına bak. Uygulama kodu GPLv3; MIDI dosyalarının kaynak ve ayrı lisans bilgileri korunur.
