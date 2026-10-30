# Discord ile Kişisel PC Kontrolü

Windows bilgisayarını kendi Discord sunucundaki tek bir kalıcı kontrol mesajının altındaki butonlarla yönet. Yerel web paneli yoktur ve kurulmaz; kontrol yalnızca Discord üzerinden yapılır. Slash komutu kullanılmaz. Kontroller yalnızca kurulumda izin verilen kullanıcı, sunucu ve kanalda çalışır.

## Discord kontrol Embed'i

Bot açıldığında belirlediğin özel kanala tek bir kontrol Embed'i gönderir. PC adı/kullanıcısı, CPU modeli ve yükü, çekirdek/izlek, bellek, sistem diski, işletim sistemi, son açılış, çalışma süresi, pil durumu, görünür penceresi olan açık uygulamalar ve bekleyen güç işlemi Embed içinde gösterilir. Durum 60 saniyede bir güncellenir.

Açık uygulamalar bölümünde yalnızca görünür pencereye sahip uygulamaların adı gösterilir; pencere başlıkları, belge adları ve içerikleri okunmaz veya Discord'a gönderilmez. Uygulama adları durum Embed'iyle Discord'a gönderilir. Arka planda çalışan ya da sistem tepsisinde simge durumundaki uygulamalar görünmeyebilir.

Embed altındaki düğmeler:

- **Durumu yenile** — Durum Embed'ini anında günceller.
- **Ekran görüntüsü** — O anın görüntüsünü yalnızca sana özel bir Embed eki olarak gönderir; otomatik kayıt yapılmaz.
- **Yeniden başlat** / **Bilgisayarı kapat** — Önce özel bir Embed içinde onay ister; onaylarsan işlem 60 saniye sonrasına planlanır.
- **İşlemi iptal et** — Planlanmış yeniden başlatma veya kapatmayı iptal eder.
- **Yardım ve gizlilik** — Kontrolleri ve veri davranışını özel Embed içinde açıklar.

Bot yeniden başlarsa aynı kontrol mesajını bulup günceller. Mesaj silinmişse yenisini oluşturur. Buton yanıtları ve ekran görüntüsü Discord'da yalnızca sana görünür (ephemeral). Ana durum Embed'i, kurulumda seçtiğin özel kanalda görünür; bu kanalı yalnızca senin ve botun görebildiğinden emin ol.

## İlk kurulum

### 1. Discord botunu oluştur

1. [Discord Developer Portal](https://discord.com/developers/applications) üzerinden kendi uygulamanı oluştur.
2. **Bot** sayfasından botu oluştur ve token'ı kopyala. Token'ı kimseyle paylaşma; şüphelenirsen Developer Portal'dan yenile.
3. OAuth2 URL Generator/Installation bölümünde `bot` ve `applications.commands` kapsamlarını seçip botu kendi sunucuna ekle. Uygulama eski sürümden kalmış slash komutlarını temizlemek için `applications.commands` kapsamını kullanır; yeni sürüm hiçbir slash komutu kaydetmez.
4. Bot için **View Channel**, **Send Messages**, **Embed Links**, **Attach Files** ve **Read Message History** izinlerini ver. Botu yalnızca kontrol kanalına erişecek şekilde sınırlandır.
5. Sunucunda yalnızca senin ve botun görebildiği bir metin kanalı oluştur.
6. Discord **User Settings → Advanced → Developer Mode** seçeneğini aç. Kendi kullanıcı ID'ni, sunucu ID'sini ve kontrol kanalının ID'sini **Copy ID** ile al.

Bot token'ı Windows'ta ayrı, maskeli bir giriş penceresinde istenir; token'ı bu pencereye yapıştırabilirsin ve karakterleri görünmez. Uygulama adları Discord'a gönderildiği için güncel kurulum bu veri davranışını ayrıca onaylatır. Mesaj içeriği veya üye listesi gibi ayrıcalıklı Gateway intent'leri istenmez.

### 2. Windows uygulamasını kur

1. `README.md`, `setup.bat` ve `app` klasörünü birlikte kalıcı bir klasöre çıkar; kurulumdan sonra klasörü taşıma.
2. `setup.bat` çalıştır ve **1 — Install or reconfigure** seç. Önceden kurulum varsa kayıtlı token ve ID'lerle devam etme veya yeni ayar girme seçeneği sunulur.
3. Kayıtlı ayarlarla devam edersen token ve kullanıcı/sunucu/kanal ID'leri korunur; yeniden girmen gerekmez. Önceki sürümden kalan yerel panel ayarları kaldırılır. Yeni ayar seçersen açılan maskeli token penceresine bot token'ını yapıştırıp ID'leri gir.
4. Güncel gizlilik bildirimini okuyup `KABUL EDİYORUM` yazarak onayla. Her iki seçenek de özel Python ortamını, Discord botunu ve Windows oturum açılışını kurar.
5. Başarılı kurulumdan sonra özel Discord kanalını aç. Bot bir kontrol Embed'i göndermeli; kontrolleri altındaki düğmelerden kullan.

Python 3.14 yoksa kurulum, WinGet ile resmi Python sürümünü kullanıcı hesabına yüklemeyi dener. WinGet ve internet ilk kurulumda gereklidir. Paketler uygulamanın özel sanal ortamına kurulur. Yeniden yapılandırma eski ortamı ve geçmiş logları silip yenisini kurar; genel Python kurulumlarına dokunmaz.

## Güvenlik ve gizlilik

- Düğmeler yalnızca kurulumdaki kullanıcı, sunucu ve kanal ID'si eşleştiğinde işler. Kontrol mesajı kanalı özel tutulmalıdır.
- Ekran görüntüsü ve sistem durumu Discord'a yüklenir/gönderilir. Discord bu veriyi kendi hizmetinde işleyebilir; ekran görüntüsünü yalnızca güvenilir, özel kontrol kanalında iste.
- Bot token'ı `%APPDATA%\PCActivityMonitor\config.json` içinde saklanır ve uygulama tarafından şifrelenmez. Bu dosyayı paylaşma.
- Güç işlemleri uygulamanın sabit Windows `shutdown.exe` çağrılarıdır; özel Embed üzerinden onay ister, 60 saniye gecikmeli başlar ve iptal edilebilir. Genel shell/komut çalıştırma yoktur.
- Herhangi bir bot kullanıcısı için işlem yürütülmez; uygulama izinli kullanıcı kimliğini kontrol eder. Token'ı sızdırırsan Developer Portal'dan hemen sıfırla ve kurulumu yeni token ile yapılandır.
- Yerel web sunucusu veya modem port yönlendirmesi kullanılmaz. Uzaktan kontrol Discord üzerinden sağlanır.
- Bot logları `%APPDATA%\PCActivityMonitor\discord.log`; uygulama logları aynı klasördeki `client.log` ve `startup.log` dosyalarındadır. Logları paylaşmadan önce gözden geçir.

## Yeniden başlatma veya kaldırma

- Kaynak dosyaları güncelledikten sonra `setup.bat` menüsündeki **3 — Restart the PC control panel** seçeneğiyle botu yeniden başlat.
- Bot token'ı, izinli kullanıcıyı, sunucuyu veya kanalı değiştirmek için **1 — Install or reconfigure** seçip yeni ayar girme seçeneğini kullan.
- **2 — Remove** çalışan servisi, Windows başlangıç kayıtlarını, bot token'ı dahil yerel ayarları, logları ve özel Python ortamını kaldırır. Kaynak dosyalar klasörde kalır.
- Sistem tepsisinden uygulamayı oturum sonuna kadar kapatabilir veya otomatik başlangıcı devre dışı bırakabilirsin.

## Sorun giderme

- Kurulum ve servis logları: `%APPDATA%\PCActivityMonitor\startup.log`, `client.log` ve `discord.log`.
- Bot çevrimiçi değilse bilgisayarın internet bağlantısını, bot token'ını, botun sunucudaki durumunu ve `discord.log` dosyasını kontrol et.
- Embed görünmüyorsa botun doğru sunucu ve kanala eriştiğini; **View Channel**, **Send Messages**, **Embed Links**, **Attach Files**, **Read Message History** izinlerini kontrol et.
- Ekran görüntüsü alınamıyorsa Windows masaüstü oturumunun açık olduğunu ve bilgisayarın kilitli/oturumu kapalı olmadığını doğrula.
- Kapatma/yeniden başlatma işlemi hata verirse Windows oturum izinlerini ve `shutdown.exe` durumunu kontrol et.

## Kaynak kullanımı

Bu proje bilgisayar kullanıcısının kişisel kullanımına yöneliktir. Telif hakkı sahibinin yazılı izni olmadan projeyi veya değiştirilmiş kopyalarını satma, alt lisanslama ya da yeniden dağıtma. Üçüncü taraf paketler kendi lisanslarına tabidir. Bu açıklama yasal tavsiye değildir; dağıtım lisansı için uygun hukuki danışmanlık al.
