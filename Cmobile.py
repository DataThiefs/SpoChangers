# SpoChanger - mobil sürüm (Termux / Pydroid)
# Masaüstü sürümünden farkı: tarayıcı otomatik açılmıyor, giriş linki elle açılıyor.
# .env ve spotify oturum dosyası script'in olduğu klasörde tutuluyor.

import os
import queue
import random
import re
import threading
import time

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth

KLASOR = os.path.dirname(os.path.abspath(__file__))


def env_yukle(yol):
    # python-dotenv telefonda kurulu olmayabilir, basit bir okuyucu yeterli
    if not os.path.exists(yol):
        return
    with open(yol, encoding="utf-8-sig") as f:  # -sig: not defteri BOM ekliyor
        for satir in f:
            satir = satir.strip()
            if not satir or satir.startswith("#") or "=" not in satir:
                continue
            anahtar, deger = satir.split("=", 1)
            os.environ.setdefault(anahtar.strip(), deger.strip().strip('"').strip("'"))


env_yukle(os.path.join(KLASOR, ".env"))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080").strip()

EMOJILER = ["🎛️", "🎵", "🎶", "💿", "📀", "🤘🏽", "🎼", "⏏️", "⏩", "⏪", "⏭️", "⏮️", "🫰🏿", "🫶🏿"]
DISCORD_URL = "https://discord.com/api/v9/users/@me/settings"
LRCLIB_URL = "https://lrclib.net/api/get"

MIN_ADIM = 0.4       # mobil veride biraz daha yavaş gidelim
KONTROL_ARALIGI = 1  # spotify'a saniyede bir sor, pil için
HATA_BEKLEME = 10

LRC_ZAMAN = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")

kuyruk = queue.Queue(maxsize=1)


def discord_gonder(session, payload):
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    r = session.patch(DISCORD_URL, headers=headers, json=payload, timeout=10)
    if r.status_code == 429:
        try:
            bekle = float(r.json().get("retry_after", 2))
        except ValueError:
            bekle = 2
        print(f"rate limit, {bekle:.1f}s bekleniyor")
        time.sleep(bekle)
    elif r.status_code == 401:
        print("discord token geçersiz")
    elif r.status_code >= 400:
        print(f"discord hata {r.status_code}: {r.text[:100]}")


def discord_worker():
    session = requests.Session()
    while True:
        payload = kuyruk.get()
        try:
            discord_gonder(session, payload)
        except requests.RequestException as e:
            print(f"discord'a ulaşılamadı: {e}")
        finally:
            kuyruk.task_done()


def durum_guncelle(metin, emoji=None):
    emoji = emoji or random.choice(EMOJILER)
    metin = (metin or "").strip()[:128]
    payload = {"custom_status": {"text": metin, "emoji_name": emoji, "expires_at": None}}

    # gönderilmeyi bekleyen eski durum varsa çöpe at
    try:
        kuyruk.get_nowait()
        kuyruk.task_done()
    except queue.Empty:
        pass
    try:
        kuyruk.put_nowait(payload)
    except queue.Full:
        pass
    print(f"[{emoji}] {metin}")


def durumu_temizle():
    try:
        with requests.Session() as s:
            discord_gonder(s, {"custom_status": None})
        print("durum temizlendi")
    except requests.RequestException:
        pass


def sozleri_cek(sanatci, sarki, sure=None):
    denemeler = []
    if sure:
        denemeler.append({"track_name": sarki, "artist_name": sanatci, "duration": sure})
    denemeler.append({"track_name": sarki, "artist_name": sanatci})

    for params in denemeler:
        try:
            r = requests.get(LRCLIB_URL, params=params, timeout=10,
                             headers={"User-Agent": "SpoChanger-mobile"})
            if r.status_code == 200:
                sozler = r.json().get("syncedLyrics") or ""
                if sozler:
                    return sozler
        except (requests.RequestException, ValueError) as e:
            print(f"sözler alınamadı: {e}")
            break
    return ""


def lrc_ayristir(lrc):
    sonuc = []
    for satir in lrc.splitlines():
        satir = satir.strip()
        zamanlar = []
        i = 0
        while (m := LRC_ZAMAN.match(satir, i)):
            dk, sn, ms = m.groups()
            ms = int(ms.ljust(3, "0")) if ms else 0
            zamanlar.append(int(dk) * 60000 + int(sn) * 1000 + ms)
            i = m.end()
        metin = satir[i:].strip()
        if metin:
            for z in zamanlar:
                sonuc.append({"ms": z, "metin": metin})
    sonuc.sort(key=lambda x: x["ms"])
    return sonuc


def satir_bul(sozler, ms):
    bulunan = None
    for i, s in enumerate(sozler):
        if s["ms"] > ms:
            break
        bulunan = i
    return bulunan


def satiri_yaz(metin, kalan_ms):
    kelimeler = metin.split()
    if not kelimeler:
        return
    sure = max(0, kalan_ms / 1000) * 0.9
    adim = max(1, min(len(kelimeler), int(sure / MIN_ADIM)))
    for n in range(1, adim + 1):
        durum_guncelle(" ".join(kelimeler[:round(len(kelimeler) * n / adim)]))
        if n < adim:
            time.sleep(sure / adim)


def spotify_baglan():
    # open_browser=False -> spotipy linki yazdırıyor, giriş yapıp
    # yönlendirilen adresi (açılmasa da olur) kopyalayıp terminale yapıştırıyorsun
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope="user-read-currently-playing",
        open_browser=False,
        cache_path=os.path.join(KLASOR, ".cache"),
    ))


def main():
    eksik = [k for k, v in {"DISCORD_TOKEN": DISCORD_TOKEN,
                            "SPOTIFY_CLIENT_ID": SPOTIFY_CLIENT_ID,
                            "SPOTIFY_CLIENT_SECRET": SPOTIFY_CLIENT_SECRET}.items() if not v]
    if eksik:
        raise SystemExit(f"eksik ayar: {', '.join(eksik)} (.env dosyasını doldur)")

    sp = spotify_baglan()
    sp.current_user()  # giriş adımını en başta yaptıralım
    threading.Thread(target=discord_worker, daemon=True).start()

    son_sarki = None
    son_idx = None
    sozler = []
    durdu = False

    print("başladı, çıkmak için ctrl+c")

    while True:
        try:
            veri = sp.current_user_playing_track()
            alinma = time.monotonic()
            item = veri.get("item") if veri else None

            if veri and item:
                caliyor = veri.get("is_playing", False)
                ad = item.get("name") or "?"
                sanatcilar = item.get("artists") or []
                sanatci = sanatcilar[0].get("name", "") if sanatcilar else ""
                sarki_id = item.get("id") or f"{sanatci}-{ad}"
                ilerleme = veri.get("progress_ms") or 0

                if sarki_id != son_sarki:
                    son_sarki = sarki_id
                    son_idx = None
                    durdu = False
                    durum_guncelle(ad, "▶️" if caliyor else "⏹️")
                    sure = round((item.get("duration_ms") or 0) / 1000) or None
                    sozler = lrc_ayristir(sozleri_cek(sanatci, ad, sure))
                    if not sozler:
                        print(f"'{ad}' için söz yok")
                    continue

                if caliyor:
                    durdu = False
                    simdi = ilerleme + (time.monotonic() - alinma) * 1000
                    idx = satir_bul(sozler, simdi)
                    if idx is not None and idx != son_idx:
                        son_idx = idx
                        if idx + 1 < len(sozler):
                            kalan = sozler[idx + 1]["ms"] - simdi
                        else:
                            kalan = 3000
                        satiri_yaz(sozler[idx]["metin"], kalan)
                elif not durdu:
                    durum_guncelle(ad, "⏹️")
                    durdu = True
                    son_idx = None

        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"hata: {e}")
            time.sleep(HATA_BEKLEME)
            continue

        time.sleep(KONTROL_ARALIGI)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nkapatılıyor")
        if DISCORD_TOKEN:
            durumu_temizle()
