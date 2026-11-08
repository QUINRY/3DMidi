# 3DMidi

MIDI dosyalarından 3D yazıcı motorlarında müzik çalan G-code üretir. Windows uygulaması çevrimdışı çalışır ve 129 örnek MIDI içerir.

[Windows sürümünü indir](https://github.com/QUINRY/3DMidi/releases/latest) · [English](README.md)

## Yazıcı örnek videoları

Yazıcı motorlarının çaldığı melodileri duymak için sesi açın.

<table>
<tr>
<th width="33%">Snapmaker U1<br><em>Insomnia</em></th>
<th width="33%">Creality K2 Pro<br><em>Für Elise</em></th>
<th width="33%">Creality Ender-3 V3 KE<br><em>Mario</em></th>
</tr>
<tr>
<td align="center" valign="top"><video controls width="240" src="https://github.com/user-attachments/assets/35632834-2989-4c17-b8fd-dd31da0e4d57"></video></td>
<td align="center" valign="top"><video controls width="240" src="https://github.com/user-attachments/assets/8b0c0384-3ef2-4041-8d63-6d59684b63cd"></video></td>
<td align="center" valign="top"><video controls width="240" src="https://github.com/user-attachments/assets/6be743ec-c4a5-4889-8838-6778ac043e88"></video></td>
</tr>
<tr>
<td align="center"><a href="https://github.com/QUINRY/3DMidi/releases/download/v1.1.0/Snapmaker-U1-Insomnia.mp4">MP4 indir · 35 sn</a></td>
<td align="center"><a href="https://github.com/QUINRY/3DMidi/releases/download/v1.1.0/Creality-K2-Pro-Fur-Elise.mp4">MP4 indir · 60 sn</a></td>
<td align="center"><a href="https://github.com/QUINRY/3DMidi/releases/download/v1.1.0/Creality-Ender-3-V3-KE-Mario.mp4">MP4 indir · 23 sn</a></td>
</tr>
</table>

## Başlangıç

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
