# SpoChanger

Spotify'da çalan şarkının sözlerini Discord durumuna yazan küçük bir script. Sözler şarkıyla senkron gidiyor, her satır kelime kelime ekleniyor:

```
Never
Never gonna
Never gonna give
Never gonna give you up
```

Sözler [lrclib.net](https://lrclib.net)'ten geliyor. Senkron sözü olmayan şarkılarda sadece şarkının adı görünüyor.

## Kurulum

Python 3.10 veya üstü lazım.

```
pip install -r requirements.txt

python -m pip install -r requirements.txt
```

[Spotify Developer Dashboard](https://developer.spotify.com/dashboard)'dan bir uygulama oluştur, Redirect URI kısmına `http://127.0.0.1:8080` ekle. Client ID ve Client Secret'ı oradan alacaksın.

`.env.example` dosyasını `.env` adıyla kopyala ve içini doldur:

```
DISCORD_TOKEN=...
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8080
```

`.env` dosyası script'in yanında olmalı, script onu kendisi okuyor. `.env` ve `.cache` dosyaları `.gitignore`'da, yani repoya gitmiyorlar. Token'ları koda yazma.

## Çalıştırma

```
python Changer.py
```

İlk açılışta tarayıcıda Spotify girişi açılıyor, izin verdikten sonra bir daha sormuyor.

- Şarkıyı durdurunca durumda ⏹️ ile şarkı adı kalıyor.
- Şarkının enstrümantal kısımlarında 🎶 ile şarkı adı görünüyor.
- Spotify kapanınca ya da reklam girince durumun, script'i açmadan önceki haline dönüyor.
- Ctrl+C ile kapatınca da eski durumun geri geliyor.

## Telefonda (Android)

Telefon için `Cmobile.py` var. [Termux](https://f-droid.org/packages/com.termux/) ile çalışıyor (Pydroid 3'te de olur).

```
pkg install python
pip install spotipy requests
python Cmobile.py
```

`.env` dosyası `Cmobile.py` ile aynı klasörde olmalı.

Telefonda tarayıcı otomatik açılmadığı için giriş biraz farklı:

1. Script terminale bir link yazıyor, onu tarayıcıda aç ve izin ver.
2. Tarayıcı `127.0.0.1:8080/?code=...` gibi bir adrese gidip "sayfa açılmıyor" diyecek, bu normal.
3. Adres çubuğundaki linkin tamamını kopyala ve terminale yapıştır.

Bunu bir kere yapman yeterli. Arka planda çalışırken Android'in script'i kapatmaması için Termux'ta önce `termux-wake-lock` çalıştır.

## Bilmen gerekenler

- Discord'da kullanıcı token'ıyla otomatik istek atmak kurallara aykırı. Hesabın kısıtlanabilir, kullanırsan risk sende.
- Discord durumu en fazla 128 karakter alıyor, uzun satırlar kesiliyor.
- Çok sık istek atınca Discord rate limit uyguluyor. Script bekleyip devam ediyor ama bazı kelimeler atlanabilir.
- Konsol penceresini X ile kapatırsan durum geri yüklenmez, Ctrl+C ile kapat.
