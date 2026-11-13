import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
import time
import re
import random
import threading # YENİ: Arka plan işlemleri için

# ================= AYARLAR =================
DISCORD_TOKEN = "BURAYA_DISCORD_TOKENIN_GELECEK"
SPOTIFY_CLIENT_ID = "Token "
SPOTIFY_CLIENT_SECRET = " senin token"
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8080"
# ===========================================

EMOJILER = ["🎛️", "🎵", "🎶", "💿", "📀", "🤘🏽", "🎼", "⏏️", "⏩", "⏪", "⏭️", "⏮️","🫰🏿","🫶🏿"]

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET,
    redirect_uri=SPOTIFY_REDIRECT_URI,
    scope="user-read-currently-playing"
))

# YENİ: İsteği arka planda atıp cevabı beklemeyen fonksiyon
def arka_planda_gonder(url, headers, payload):
    try:
        requests.patch(url, headers=headers, json=payload, timeout=2)
    except:
        pass

def discord_durum_guncelle(metin, sabit_emoji=None):
    url = "https://discord.com/api/v9/users/@me/settings"
    headers = {
        "Authorization": DISCORD_TOKEN,
        "Content-Type": "application/json"
    }
    
    secilen_emoji = sabit_emoji if sabit_emoji else random.choice(EMOJILER)
    
    payload = {
        "custom_status": {
            "text": metin,
            "emoji_name": secilen_emoji,
            "expires_at": None
        }
    }
    
    # İsteği beklemeden arka plan (Thread) işlemine yolla
    threading.Thread(target=arka_planda_gonder, args=(url, headers, payload)).start()
    print(f"[{secilen_emoji}] {metin}")

def sozleri_cek(artist, track):
    url = f"https://lrclib.net/api/get?track_name={track}&artist_name={artist}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json().get("syncedLyrics", "")
    except:
        pass
    return ""

def lrc_ayristir(lrc_metni):
    satirlar = lrc_metni.strip().split('\n')
    soz_sozlugu = []
    for satir in satirlar:
        zaman_etiketi = re.search(r'\[(\d{2}):(\d{2})\.(\d{2,3})\]', satir)
        if zaman_etiketi:
            dk = int(zaman_etiketi.group(1))
            sn = int(zaman_etiketi.group(2))
            ms_str = zaman_etiketi.group(3)
            ms = int(ms_str) * 10 if len(ms_str) == 2 else int(ms_str)
            toplam_ms = (dk * 60 * 1000) + (sn * 1000) + ms
            metin = satir[zaman_etiketi.end():].strip()
            if metin:
                soz_sozlugu.append({"sure_ms": toplam_ms, "metin": metin})
    return soz_sozlugu

son_calan_sarki = ""
son_okunan_satir_ms = -1
soz_listesi = []
duraklatildi_mi = False

print("Senkronize Threading Piramit Modu Başlatılıyor...")

while True:
    try:
        current_track = sp.current_user_playing_track()
        
        if current_track is not None:
            is_playing = current_track['is_playing']
            track_name = current_track['item']['name']
            artist_name = current_track['item']['artists'][0]['name']
            sarki_id = current_track['item']['id']
            progress_ms = current_track['progress_ms']
            
            if is_playing:
                duraklatildi_mi = False
                
                if sarki_id != son_calan_sarki:
                    discord_durum_guncelle(f"{track_name}", "▶️")
                    lrc_ham = sozleri_cek(artist_name, track_name)
                    if lrc_ham:
                        soz_listesi = lrc_ayristir(lrc_ham)
                    else:
                        soz_listesi = []
                    son_calan_sarki = sarki_id
                    son_okunan_satir_ms = -1
                
                for i, soz in enumerate(soz_listesi):
                    if progress_ms >= soz["sure_ms"] and soz["sure_ms"] > son_okunan_satir_ms:
                        
                        kelimeler = soz["metin"].split()
                        kelime_sayisi = len(kelimeler)
                        
                        if i + 1 < len(soz_listesi):
                            sonraki_satir_ms = soz_listesi[i + 1]["sure_ms"]
                            zaman_farki_ms = sonraki_satir_ms - soz["sure_ms"]
                        else:
                            zaman_farki_ms = 3000 
                            
                        if zaman_farki_ms <= 0:
                            zaman_farki_ms = 2000
                            
                        # Hız limiti kısıtlamasını 0.05'e kadar düşürdük (neredeyse anında)
                        kelime_hizi = max(0.05, (zaman_farki_ms / 1000.0) / kelime_sayisi)

                        biriken_cumle = ""
                        
                        for kelime in kelimeler:
                            if biriken_cumle == "":
                                biriken_cumle = kelime
                            else:
                                biriken_cumle += " " + kelime
                                
                            discord_durum_guncelle(biriken_cumle)
                            
                            # Artık burada interneti beklemediği için milisaniye şaşmadan kelime basacak
                            time.sleep(kelime_hizi) 
                            
                        son_okunan_satir_ms = soz["sure_ms"]
                        break 
                        
            else:
                if not duraklatildi_mi:
                    discord_durum_guncelle(f"{track_name}", "⏹️")
                    duraklatildi_mi = True
                    son_okunan_satir_ms = progress_ms 
                    
    except Exception as e:
        pass 
        
    # Spotify'ı daha sık (0.5 saniyede bir) kontrol et ki söz kaçırma ihtimali azalsın
    time.sleep(0.5) 
