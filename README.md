# Discord ile Kişisel PC Kontrolü

Windows bilgisayarını kendi Discord sunucundaki tek bir kalıcı kontrol mesajının altındaki butonlarla yönet. Yerel web paneli yoktur ve kurulmaz; kontrol yalnızca Discord üzerinden yapılır. Slash komutu kullanılmaz. Kontroller yalnızca kurulumda izin verilen kullanıcı, sunucu ve kanalda çalışır.

## Discord kontrol Embed'i

Bot açıldığında belirlediğin özel kanala tek bir kontrol Embed'i gönderir. PC adı/kullanıcısı, sistem sağlığı özeti, renkli CPU/RAM/disk kullanım göstergeleri, bağlı disklerin kapasitesi, donanım destekliyorsa sıcaklık sensörleri, ağ trafiği ve varsayılan ağ geçidi durumu, işletim sistemi, çalışma süresi, süreçler ve açık uygulamalar gösterilir. Durum 60 saniyede bir güncellenir. Sağlık önerileri ve eşik uyarıları yalnızca panelde gösterilir; otomatik işlem yapılmaz.

Açık uygulamalar bölümünde yalnızca görünür pencereye sahip uygulamaların adı gösterilir; pencere başlıkları, belge adları ve içerikleri okunmaz veya Discord'a gönderilmez. Uygulama adları durum Embed'iyle Discord'a gönderilir. Arka planda çalışan ya da sistem tepsisinde simge durumundaki uygulamalar görünmeyebilir.

Embed altında durum yenileme düğmesi ve diğer işlemleri içeren tek bir menü bulunur:

- **Durumu yenile** — Durum Embed'ini anında günceller; doluluk renkleri yalnızca anlık kullanım seviyesini gösterir.
- **Sistem sağlığı ve öneriler** — CPU, bellek, disk ve erişilebilen sıcaklık ölçümlerini isteğe bağlı, özel yanıtla değerlendirir; bu görüntüleme kaynak geçmişine yeni kayıt eklemez.
- **Kaynak geçmişi** — CPU, bellek ve disk kullanımının 1 saat, 24 saat veya 7 günlük grafiğini özel yanıtla gönderir.
- **Uygulama süreleri / Günlük kullanım grafiği** — İsteğe bağlı aktif pencere takibiyle son 7 günün en çok kullanılan uygulamalarını ve günlere göre grafiği özel yanıtla gösterir.
- **Başlangıç uygulamaları** — Windows başlangıç kayıtlarını yalnızca listeler; hiçbir uygulama veya ayar değiştirilmez.
- **Uygulama takibini duraklat/sürdür / Kullanım geçmişini sil** — Uygulama ölçümünü anında açıp kapatabilir ve yerel kullanım kayıtlarını silebilirsin.
- **Ekran görüntüsü al / Uygulama kapat / Uygulamayı öne getir** — İsteğe bağlı görüntüyü özel yanıtla gönderir; görünür uygulamayı kapatır veya seçilen pencereyi öne alır. Windows pencereyi öne almayı engellerse uygulama görev çubuğunda yanıp sönerek dikkat çeker.
- **Hatırlatıcı kur / Hatırlatıcıları yönet** — Tarih (GG.AA.YYYY) ve saat (SS:DD) girerek süre sınırı olmadan ileri bir zamana notlu alarm kurabilir, bekleyen alarmları görebilir ve iptal edebilirsin. Kurulumdan sonra sana özel bir teyit gösterilir. Zamanı gelince bu bilgisayarda sistem sesi çalar ve önde bir uyarı penceresi açılır; alarm Discord kanalına veya DM olarak gönderilmez. Hatırlatıcı kaydı uygulama yeniden başlatılsa da korunur.
- **Yeniden başlat / Bilgisayarı kapat / Planlanan işlemi iptal et** — 1 dakika ile 7 gün arasında zaman seçilir; işlem ek onay gerektirir ve başlamadan iptal edilebilir.

Durum paneli en çok bellek kullanan beş sürecin adını, yaklaşık CPU/RAM kullanımını ve Windows açılışından beri toplam ağ gönderim/alım miktarını gösterir. Anlık ağ hızları ardışık ölçümlerden hesaplanır; ilk ölçümde hız henüz gösterilmeyebilir.

Bot yeniden başlarsa aynı kontrol mesajını bulup günceller. Mesaj silinmişse yenisini oluşturur. Buton yanıtları ve ekran görüntüsü Discord'da yalnızca sana görünür (ephemeral). Ana durum Embed'i, kurulumda seçtiğin özel kanalda görünür; bu kanalı yalnızca senin ve botun görebildiğinden emin ol.

Uygulama süresi ölçümü her 10 saniyede bir aktif pencerenin uygulama adını örnekler; süre yaklaşık olduğundan çok kısa odak değişimleri kaçabilir. Kullanıcı girişi 5 dakikadan uzun süredir yoksa boşta süre sayılmaz. Pencere başlıkları, web adresleri, belge adları ve içerikleri alınmaz. Kayıtlar yerel SQLite veritabanında 7 gün saklanır ve istenirse duraklatılır veya silinir. Discord'a otomatik gönderilmez.

Ağ kontrolü Windows'un varsayılan ağ geçidini bulup yalnızca o yerel adrese ping atar; genel internet hedeflerine ping veya bağlantı testi yapmaz. Başlangıç uygulaması listesi yalnızca kayıt defteri ve başlangıç klasörlerinden okunur; çalıştırma veya ayar değiştirme yapılmaz. Sıcaklık sensörleri Windows/üretici sürücüsüne bağlıdır; desteklenmiyorsa panelde açıkça belirtilir.

## İlk kurulum

### 1. Discord botunu oluştur

1. [Discord Developer Portal](https://discord.com/developers/applications) üzerinden kendi uygulamanı oluştur.
2. **Bot** sayfasından botu oluştur ve token'ı kopyala. Token'ı kimseyle paylaşma; şüphelenirsen Developer Portal'dan yenile.
3. OAuth2 URL Generator/Installation bölümünde `bot` ve `applications.commands` kapsamlarını seçip botu kendi sunucuna ekle. Uygulama eski genel ve sunucu slash komutlarını temizler; yeni sürüm hiçbir slash komutu kaydetmez.
4. Bot için **View Channel**, **Send Messages**, **Embed Links**, **Attach Files** ve **Read Message History** izinlerini ver. Botu yalnızca kontrol kanalına erişecek şekilde sınırlandır.
5. Sunucunda yalnızca senin ve botun görebildiği bir metin kanalı oluştur.
6. Discord **User Settings → Advanced → Developer Mode** seçeneğini aç. Kendi kullanıcı ID'ni, sunucu ID'sini ve kontrol kanalının ID'sini **Copy ID** ile al.

Bot token'ı Windows'ta ayrı, maskeli bir giriş penceresinde istenir; token'ı bu pencereye yapıştırabilirsin ve karakterleri görünmez. Uygulama ve süreç adları, ağ geçidi adresi ve ağ sayaçları Discord'a gönderilebildiği için güncel kurulum bu veri davranışını ayrıca onaylatır. Aktif pencere süre takibi ayrıca sorulur ve varsayılan olarak kapalıdır. Mesaj içeriği veya üye listesi gibi ayrıcalıklı Gateway intent'leri istenmez.

### 2. Windows uygulamasını kur

1. `README.md`, `setup.bat` ve `app` klasörünü birlikte kalıcı bir klasöre çıkar; kurulumdan sonra klasörü taşıma.
2. `setup.bat` çalıştır ve **1 — Kur veya yeniden yapılandır** seç. Önceden kurulum varsa kayıtlı token ve ID'lerle devam etme veya yeni ayar girme seçeneği sunulur.
3. Kayıtlı ayarlarla devam edersen token ve kullanıcı/sunucu/kanal ID'leri korunur; yeniden girmen gerekmez. Önceki sürümden kalan yerel panel ayarları kaldırılır. Yeni ayar seçersen açılan maskeli token penceresine bot token'ını yapıştırıp ID'leri gir.
4. Aktif pencere uygulama süre takibini isteğe bağlı açıp kapat; ardından güncel gizlilik bildirimini okuyup `KABUL EDİYORUM` yazarak onayla. Takibi açarsan yalnızca uygulama adları ve yaklaşık aktif süre yerel olarak saklanır; içerik ve pencere başlıkları izlenmez. Her iki seçenek de özel Python ortamını, Discord botunu ve Windows oturum açılışını kurar.
5. Başarılı kurulumdan sonra özel Discord kanalını aç. Bot bir kontrol Embed'i göndermeli; kontrolleri altındaki düğmelerden kullan.

Python 3.14 yoksa kurulum, WinGet ile resmi Python sürümünü kullanıcı hesabına yükler ve Python klasörlerini bu kullanıcının `PATH` değişkenine ekler. İlk kurulum için WinGet ve internet bağlantısı gereklidir. Paketler uygulamanın özel sanal ortamına kurulur. Yeniden yapılandırma eski ortamı ve geçmiş logları silip yenisini kurar; genel Python kurulumlarına dokunmaz.

## Güvenlik ve gizlilik

- Düğmeler yalnızca kurulumdaki kullanıcı, sunucu ve kanal ID'si eşleştiğinde işler. Kontrol mesajı kanalı özel tutulmalıdır.
- Ekran görüntüsü ve sistem durumu Discord'a yüklenir/gönderilir. Discord bu veriyi kendi hizmetinde işleyebilir; ekran görüntüsünü yalnızca güvenilir, özel kontrol kanalında iste.
- Hatırlatıcı notları `%APPDATA%\PCActivityMonitor\reminders.json` içinde yerel olarak saklanır. Zamanı gelince Windows sistem sesi çalar ve not üstte açılan pencerede gösterilir; alarm Discord kanalına veya DM olarak gönderilmez. Alarmın çalması için bilgisayarın açık ve uygulamanın çalışır durumda olması gerekir.
- Windows, başka bir uygulamayı öne alma isteğini kısıtlayabilir; bu durumda hedef uygulama görev çubuğunda yanıp söner.
- Görünür uygulama adları, en çok kaynak kullanan süreç adları, ağ geçidi adresi ve ağ trafiği özeti kontrol kanalında gösterilir. CPU, bellek ve disk örnekleri `%APPDATA%\PCActivityMonitor\metrics.sqlite3` içinde yerel olarak saklanır; 7 günden eski veriler temizlenir. Grafik yalnızca istediğinde Discord'a özel yanıt olarak yüklenir.
- Aktif pencere uygulama süre takibi varsayılan olarak kapalıdır. Açarsan uygulama adı ve yaklaşık süre aynı yerel veritabanında tutulur; pencere başlığı, web adresi, belge adı veya içerik kaydedilmez. Yalnızca istediğinde, en çok kullanılan uygulamaların son 7 günlük özeti Discord'a özel yanıtla gönderilir. Özeti açıp **Yerel geçmişi sil** düğmesiyle bu kayıtları silebilirsin. Takibi kapatmak için `setup.bat` ile yeniden yapılandırıp soruya **H** yanıtını ver.
- Ağ durumu için yalnızca yerel varsayılan ağ geçidi kontrol edilir; internet servisine ping gönderilmez. Başlangıç uygulamaları yalnızca görüntülenir, sistem ayarı değiştirilmez. Donanım sıcaklıkları yalnızca sürücü sağlıyorsa gösterilir.
- CPU/RAM/disk renk göstergeleri bilgi amaçlıdır; sistem sağlığı eşik uyarıları yalnızca panelde gösterilir, otomatik DM veya güç işlemi yoktur. Hatırlatıcılar yalnızca bu bilgisayarda sesli uyarı verir.
- Bot token'ı `%APPDATA%\PCActivityMonitor\config.json` içinde saklanır ve uygulama tarafından şifrelenmez. Bu dosyayı paylaşma.
- Güç işlemleri uygulamanın sabit Windows `shutdown.exe` çağrılarıdır; 1 dakika ile 7 gün arasında zamanlanır, onay ister ve başlamadan iptal edilebilir. Genel shell/komut çalıştırma yoktur.
- Herhangi bir bot kullanıcısı için işlem yürütülmez; uygulama izinli kullanıcı kimliğini kontrol eder. Token'ı sızdırırsan Developer Portal'dan hemen sıfırla ve kurulumu yeni token ile yapılandır.
- Yerel web sunucusu veya modem port yönlendirmesi kullanılmaz. Uzaktan kontrol Discord üzerinden sağlanır.
- Bot logları `%APPDATA%\PCActivityMonitor\discord.log`; uygulama logları aynı klasördeki `client.log` ve `startup.log` dosyalarındadır. Logları paylaşmadan önce gözden geçir.

## Yeniden başlatma veya kaldırma

- Kaynak dosyaları güncelledikten sonra `setup.bat` menüsündeki **3 — Bilgisayar kontrol panelini yeniden başlat** seçeneğiyle botu yeniden başlat.
- Bot token'ı, izinli kullanıcıyı, sunucuyu veya kanalı değiştirmek için **1 — Kur veya yeniden yapılandır** seçip yeni ayar girme seçeneğini kullan.
- **2 — Bu kullanıcının kurulumunu ve yerel verileri kaldır** çalışan servisi, Windows başlangıç kayıtlarını, bot token'ı ve hatırlatıcılar dahil yerel ayarları, geçmiş veritabanını, logları ve özel Python ortamını kaldırır. Kaynak dosyalar klasörde kalır.
- Sistem tepsisinden uygulamayı oturum sonuna kadar kapatabilir veya otomatik başlangıcı devre dışı bırakabilirsin.

## Sorun giderme

- Kurulum ve servis logları: `%APPDATA%\PCActivityMonitor\startup.log`, `client.log` ve `discord.log`.
- Bot çevrimiçi değilse bilgisayarın internet bağlantısını, bot token'ını, botun sunucudaki durumunu ve `discord.log` dosyasını kontrol et.
- Embed görünmüyorsa botun doğru sunucu ve kanala eriştiğini; **View Channel**, **Send Messages**, **Embed Links**, **Attach Files**, **Read Message History** izinlerini kontrol et.
- Ekran görüntüsü alınamıyorsa Windows masaüstü oturumunun açık olduğunu ve bilgisayarın kilitli/oturumu kapalı olmadığını doğrula.
- Kapatma/yeniden başlatma işlemi hata verirse Windows oturum izinlerini ve `shutdown.exe` durumunu kontrol et.

## Kaynak kullanımı

Bu proje bilgisayar kullanıcısının kişisel kullanımına yöneliktir. Telif hakkı sahibinin yazılı izni olmadan projeyi veya değiştirilmiş kopyalarını satma, alt lisanslama ya da yeniden dağıtma. Üçüncü taraf paketler kendi lisanslarına tabidir. Bu açıklama yasal tavsiye değildir; dağıtım lisansı için uygun hukuki danışmanlık al.
