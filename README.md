# 3DMidi

MIDI dosyalarından 3D yazıcı motorlarında müzik çalan G-code üretir. Windows uygulaması dosyaları bilgisayarında işler; internet bağlantısı veya Python kurulumu gerektirmez.

## Windows için indir

[Son sürüm ve 3DMidi.exe](https://github.com/QUINRY/3DMidi/releases/latest)

1. `3DMidi.exe` dosyasını indir ve çift tıkla. Kurulum gerekmez.
2. Yazıcını seç. Varsayılan seçim **Snapmaker U1**.
3. Bir `.mid` / `.midi` dosyası seç veya 129 örnekten birini aç.
4. Hareket hızını ve tempoyu **Yavaş / Orta / Hızlı** olarak ayarla.
5. G-code oluştur; kısa test dosyasını veya tam parçayı Windows'un **Farklı Kaydet** penceresiyle kaydet.

Çıktı adı: `Yazici_MIDI_Tempo_Hiz.gcode`. Kontrol raporu ayrıca JSON olarak kaydedilebilir.

Windows 10/11 **x64** ve Microsoft Edge WebView2 Runtime gerekir. Runtime çoğu güncel Windows sisteminde bulunur; eksikse [Microsoft'tan indirilebilir](https://developer.microsoft.com/microsoft-edge/webview2/). İlk sürümün `.exe` dosyası kod imzalı değildir.

## Özellikler

- 31 seçilebilir Klipper ve Bambu Lab profili; kaynaklarıyla birlikte 50 modelden oluşan katalog.
- Hız ve tempo ayarı, melodi önizlemesi, kısa test ve tam G-code çıktısı.
- Sayısal parametrelerden özel `printer.cfg` profili içe aktarma; makrolar ve includes çalıştırılmaz.
- U1 için XY müzik; Ender-3 V3 KE ve K2 / K2 Pro / K2 Plus için X ekseninde müzik.
- K2 serisinde ayarlanabilir FOC ses aralığı. Hız ve tempo seçimleri açıktır.
- Bambu Lab için yerleşik `M1006` motor müziği; Z müzik kanalı kapalıdır.
- Z eksenine melodi veya müzik hızları uygulanmaz. Homing ve başlangıç adımları seçilen profile göre üretilir.
- MIDI işleme ve dönüşüm çevrimdışı yapılır. Yazıcıya otomatik bağlantı ya da dosya gönderimi yoktur.

Her modelde fiziksel test yapılmış değildir; profil uyarılarını ve oluşturulan kontrol raporunu incele. Yazıcıda ilk denemeyi kısa test dosyasıyla yap.

## Kaynaktan çalıştır

Python 3.12, Windows x64:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r desktop/requirements.txt
.\.venv\Scripts\python desktop/launcher.py
```

Tarayıcıdaki yerel sürüm:

```powershell
.\.venv\Scripts\python app/server.py --open
```

Raspberry Pi / Docker kurulumu için [deploy/README.md](deploy/README.md).

## Windows paketi oluştur

```powershell
.\.venv\Scripts\python desktop/build.py
```

`output/windows/3DMidi.exe` tek dosyalık taşınabilir uygulamadır. Derleme, paketlenmiş uygulamanın 129 MIDI kaynağını, yerel oturum korumasını, U1 dönüşümünü ve `.gcode` indirmelerini denetler. GitHub Actions aynı paketi Windows üzerinde üretir.

Testler:

```powershell
.\.venv\Scripts\python -m pip install -r deploy/requirements.txt
.\.venv\Scripts\python -m unittest discover -s app -p "test_*.py"
.\.venv\Scripts\python -m unittest discover -s desktop -p "test_*.py"
```

## Lisans ve katkı

Uygulama kodu **GPLv3** ile sunulur. MIDI dosyalarının lisansı ve kaynak bilgisi dosya bazında korunur; uygulamanın lisansı müzikler için yeni bir kullanım hakkı vermez. Ayrıntılar [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) ve [LICENSE](LICENSE) dosyalarında.

Herkes kodu indirebilir, kendi kopyasını değiştirebilir ve pull request gönderebilir. Ana depoya yazma yetkisi yalnızca depo sahibinde ve yetki verilen katkıcılardadır.
