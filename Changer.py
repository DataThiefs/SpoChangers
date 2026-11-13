"""SpoChanger - Spotify'da çalan şarkının sözlerini Discord durumuna yazar."""

import os
import queue
import random
import re
import sys
import threading
import time

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth

KLASOR = os.path.dirname(os.path.abspath(__file__))

# Çıktı dosyaya yönlendirilirse emojiler yüzünden çökmesin
for _akis in (sys.stdout, sys.stderr):
    try:
        _akis.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def env_yukle(yol: str) -> None:
    """Basit .env okuyucu (python-dotenv gerekmez). Var olan ortam değişkenlerini ezmez."""
    if not os.path.exists(yol):
        return
    with open(yol, encoding="utf-8-sig") as f:  # -sig: not defteri BOM ekleyebiliyor
        for satir in f:
            satir = satir.strip()
            if not satir or satir.startswith("#") or "=" not in satir:
                continue
            anahtar, deger = satir.split("=", 1)
            os.environ.setdefault(anahtar.strip(), deger.strip().strip('"').strip("'"))


env_yukle(os.path.join(KLASOR, ".env"))

# ================= AYARLAR =================
# Değerleri koda yazma; .env dosyasına gir (bkz. .env.example)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080").strip()
# ===========================================

EMOJILER = ["🎛️", "🎵", "🎶", "💿", "📀", "🤘🏽", "🎼", "⏏️", "⏩", "⏪", "⏭️", "⏮️", "🫰🏿", "🫶🏿"]
DISCORD_API = "https://discord.com/api/v9/users/@me/settings"
LRCLIB_URL = "https://lrclib.net/api/get"
USER_AGENT = "SpoChanger/1.0"

DISCORD_MAX_STATUS_LEN = 128
MIN_ADIM_SN = 0.25          # iki Discord güncellemesi arası en kısa süre
MAX_KELIME_SN = 0.6         # uzun aralarda yazım uzamasın, şarkı değişimi kaçmasın
SPOTIFY_KONTROL_SN = 0.5
HATA_BEKLEME_SN = 5
SOZ_TEKRAR_SN = 15          # ağ hatasında sözleri tekrar deneme aralığı
SON_SATIR_SURESI_MS = 3000

LRC_ZAMAN = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
LRC_OFFSET = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)
KELIME_ZAMANI = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>")

_kuyruk: "queue.Queue[dict]" = queue.Queue(maxsize=1)
_istek_kilidi = threading.Lock()
_kapaniyor = threading.Event()
token_gecersiz = threading.Event()


# ---------------------------------------------------------------- Discord
def _discord_istek(session: requests.Session, method: str, payload=None):
    """Discord'a istek atar. Başarılıysa yanıtı, değilse None döndürür."""
    headers = {"Authorization": DISCORD_TOKEN}
    r = session.request(method, DISCORD_API, headers=headers, json=payload, timeout=5)

    if r.status_code == 429:
        try:
            bekle = float(r.json().get("retry_after", 1.5))
        except ValueError:
            bekle = 1.5
        print(f"[Uyarı] Discord rate limit, {bekle:.2f}s bekleniyor...")
        time.sleep(bekle)
        return None
    if r.status_code == 401:
        token_gecersiz.set()
        print("[Hata] Discord token geçersiz (401). DISCORD_TOKEN değerini kontrol et.")
        return None
    if r.status_code >= 400:
        print(f"[Hata] Discord API {r.status_code}: {r.text[:120]}")
        return None

    # Limit dolduysa 429 yemeden önce bekle
    if r.headers.get("X-RateLimit-Remaining") == "0":
        try:
            time.sleep(float(r.headers.get("X-RateLimit-Reset-After", 0)))
        except ValueError:
            pass
    return r


def _discord_worker() -> None:
    session = requests.Session()
    while not _kapaniyor.is_set():
        try:
            payload = _kuyruk.get(timeout=0.5)
        except queue.Empty:
            continue
        with _istek_kilidi:
            if _kapaniyor.is_set():
                break
            try:
                _discord_istek(session, "PATCH", payload)
            except requests.RequestException as exc:
                print(f"[Hata] Discord isteği başarısız: {exc}")


def _kuyruga_koy(payload: dict) -> None:
    if _kapaniyor.is_set():
        return
    # Gönderilmeyi bekleyen eski durum varsa at, en güncelini koy
    try:
        _kuyruk.get_nowait()
    except queue.Empty:
        pass
    try:
        _kuyruk.put_nowait(payload)
    except queue.Full:
        pass


def durum_guncelle(metin: str, emoji: "str | None" = None) -> None:
    emoji = emoji or random.choice(EMOJILER)
    metin = (metin or "").strip()[:DISCORD_MAX_STATUS_LEN]
    _kuyruga_koy({"custom_status": {"text": metin, "emoji_name": emoji, "expires_at": None}})
    print(f"[{emoji}] {metin}")


def durumu_geri_al(eski_durum) -> None:
    _kuyruga_koy({"custom_status": eski_durum})
    print("[Bilgi] Çalan bir şey yok, Discord durumu eski haline döndü.")


def mevcut_durumu_al():
    """Başlangıçtaki durumu okur; çıkışta geri yüklemek için. (durum, başarılı_mı) döner."""
    try:
        with requests.Session() as s:
            r = _discord_istek(s, "GET")
        if r is not None:
            return r.json().get("custom_status"), True
    except (requests.RequestException, ValueError) as exc:
        print(f"[Uyarı] Discord durumu okunamadı: {exc}")
    return None, False


def kapat(eski_durum) -> None:
    """Worker'ı durdurur ve durumu başlangıçtaki haline döndürür."""
    _kapaniyor.set()
    try:
        _kuyruk.get_nowait()
    except queue.Empty:
        pass
    if token_gecersiz.is_set():
        return

    # Worker'ın o an gönderdiği istek bitsin, sonra geri yükle (yoksa üstüne yazabilir)
    alindi = _istek_kilidi.acquire(timeout=10)
    try:
        with requests.Session() as s:
            if _discord_istek(s, "PATCH", {"custom_status": eski_durum}) is not None:
                print("Discord durumu eski haline döndürüldü.")
    except requests.RequestException as exc:
        print(f"[Hata] Durum geri yüklenemedi: {exc}")
    finally:
        if alindi:
            _istek_kilidi.release()


# ---------------------------------------------------------------- Sözler
def isim_temizle(ad: str) -> str:
    """'Song - Remastered 2011', 'Song (feat. X)' -> 'Song'"""
    ad = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", ad)
    ad = re.sub(r"\s+-\s.*$", "", ad)
    return ad.strip()


def sozleri_cek(sanatci: str, ad: str, sure_sn: "int | None" = None) -> "str | None":
    """Senkron sözleri döndürür. Bulunamazsa "", ağ/sunucu hatasında None."""
    adlar = [ad]
    temiz = isim_temizle(ad)
    if temiz and temiz.lower() != ad.lower():
        adlar.append(temiz)

    denemeler = []
    for a in adlar:
        if sure_sn:
            denemeler.append({"track_name": a, "artist_name": sanatci, "duration": sure_sn})
        denemeler.append({"track_name": a, "artist_name": sanatci})

    for params in denemeler:
        try:
            r = requests.get(LRCLIB_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=5)
        except requests.RequestException as exc:
            print(f"[Hata] Şarkı sözleri alınamadı: {exc}")
            return None
        if r.status_code == 200:
            try:
                lrc = r.json().get("syncedLyrics") or ""
            except ValueError:
                lrc = ""
            if lrc:
                return lrc
        elif r.status_code == 429 or r.status_code >= 500:
            print(f"[Hata] lrclib {r.status_code} döndü.")
            return None
    return ""


def lrc_ayristir(lrc: str) -> "list[dict]":
    """LRC'yi [{'sure_ms', 'metin'}] listesine çevirir. Boş metin = enstrümantal ara."""
    offset = 0
    m = LRC_OFFSET.search(lrc)
    if m:
        offset = int(m.group(1))

    sozler = []
    for satir in lrc.splitlines():
        satir = satir.strip()
        zamanlar = []
        konum = 0
        while (eslesme := LRC_ZAMAN.match(satir, konum)) is not None:
            dk, sn, ms = eslesme.groups()
            ms = int(ms.ljust(3, "0")) if ms else 0
            zamanlar.append(int(dk) * 60_000 + int(sn) * 1000 + ms)
            konum = eslesme.end()

        metin = " ".join(KELIME_ZAMANI.sub("", satir[konum:]).split())
        for z in zamanlar:
            sozler.append({"sure_ms": max(0, z - offset), "metin": metin})

    sozler.sort(key=lambda s: s["sure_ms"])
    if not any(s["metin"] for s in sozler):
        return []
    return sozler


def sozleri_hazirla(sanatci: str, ad: str, sure_sn: "int | None"):
    """(sozler, tekrar_deneme_zamani) döner."""
    lrc = sozleri_cek(sanatci, ad, sure_sn)
    if lrc is None:
        print(f"[Uyarı] Sözler {SOZ_TEKRAR_SN}s sonra tekrar denenecek.")
        return [], time.monotonic() + SOZ_TEKRAR_SN
    sozler = lrc_ayristir(lrc)
    if not sozler:
        print(f"[Bilgi] '{ad}' için senkron söz bulunamadı.")
    return sozler, None


def guncel_satir_indeksi(sozler: "list[dict]", progress_ms: float) -> "int | None":
    secilen = None
    for i, soz in enumerate(sozler):
        if soz["sure_ms"] > progress_ms:
            break
        secilen = i
    return secilen


def satiri_yaz(metin: str, kalan_ms: float) -> None:
    """Satırı piramit şeklinde yazar; bir sonraki satıra taşmaz."""
    kelimeler = metin.split()
    if not kelimeler:
        return

    sure = min(max(0.0, kalan_ms / 1000.0) * 0.9, len(kelimeler) * MAX_KELIME_SN)
    adim_sayisi = max(1, min(len(kelimeler), int(sure / MIN_ADIM_SN)))
    adim_suresi = sure / adim_sayisi

    for adim in range(1, adim_sayisi + 1):
        bitis = round(len(kelimeler) * adim / adim_sayisi)
        durum_guncelle(" ".join(kelimeler[:bitis]))
        if adim < adim_sayisi:
            time.sleep(adim_suresi)


# ---------------------------------------------------------------- Ana döngü
def ayarlari_kontrol_et() -> None:
    eksik = [
        ad
        for ad, deger in {
            "DISCORD_TOKEN": DISCORD_TOKEN,
            "SPOTIFY_CLIENT_ID": SPOTIFY_CLIENT_ID,
            "SPOTIFY_CLIENT_SECRET": SPOTIFY_CLIENT_SECRET,
        }.items()
        if not deger
    ]
    if eksik:
        raise SystemExit(
            f"Eksik ayar: {', '.join(eksik)}\n"
            ".env.example dosyasını .env olarak kopyalayıp doldur."
        )


def spotify_baglan() -> spotipy.Spotify:
    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope="user-read-currently-playing",
            cache_path=os.path.join(KLASOR, ".cache"),
        ),
        requests_timeout=10,
    )
    # Girişi döngüden önce yap; hata varsa her 5 saniyede tarayıcı açılmasın
    try:
        kullanici = sp.current_user()
    except Exception as exc:
        raise SystemExit(
            f"Spotify'a bağlanılamadı: {exc}\n"
            "Client ID / Secret ve dashboard'daki Redirect URI'yi kontrol et."
        )
    print(f"Spotify hesabı: {kullanici.get('display_name') or kullanici.get('id')}")
    return sp


def dongu(sp: spotipy.Spotify, eski_durum) -> None:
    son_sarki = None
    son_idx = None
    sozler: "list[dict]" = []
    soz_tekrar = None
    duraklatildi = False
    bos = False

    while True:
        if token_gecersiz.is_set():
            raise SystemExit("Discord token geçersiz, kapatılıyor.")
        try:
            veri = sp.current_user_playing_track()
            alinma = time.monotonic()
            item = veri.get("item") if veri else None

            # Hiçbir şey çalmıyor, reklam ya da podcast
            if not item:
                if not bos:
                    durumu_geri_al(eski_durum)
                    bos = True
                    son_sarki = None
                time.sleep(SPOTIFY_KONTROL_SN)
                continue
            bos = False

            caliyor = veri.get("is_playing", False)
            ad = item.get("name") or "Bilinmeyen Şarkı"
            sanatcilar = item.get("artists") or []
            sanatci = sanatcilar[0].get("name", "") if sanatcilar else ""
            sarki_id = item.get("id") or f"{sanatci}-{ad}"
            sure_sn = round((item.get("duration_ms") or 0) / 1000) or None
            ilerleme = veri.get("progress_ms") or 0

            if sarki_id != son_sarki:
                son_sarki = sarki_id
                son_idx = None
                duraklatildi = not caliyor
                durum_guncelle(ad, "▶️" if caliyor else "⏹️")
                sozler, soz_tekrar = sozleri_hazirla(sanatci, ad, sure_sn)
                continue  # söz çekmek zaman aldı, ilerlemeyi tazele

            if soz_tekrar and time.monotonic() >= soz_tekrar:
                sozler, soz_tekrar = sozleri_hazirla(sanatci, ad, sure_sn)
                continue

            if caliyor:
                devam_etti = duraklatildi
                duraklatildi = False
                simdi = ilerleme + (time.monotonic() - alinma) * 1000
                idx = guncel_satir_indeksi(sozler, simdi)

                if idx is None:
                    # İlk satırdan önce: başa sarıldı, şarkı tekrarlandı ya da duraklatmadan dönüldü
                    if son_idx is not None or devam_etti:
                        son_idx = None
                        durum_guncelle(ad, "▶️")
                elif idx != son_idx:
                    son_idx = idx
                    metin = sozler[idx]["metin"]
                    if not metin:
                        durum_guncelle(ad, "🎶")  # enstrümantal ara
                    else:
                        if idx + 1 < len(sozler):
                            kalan = sozler[idx + 1]["sure_ms"] - simdi
                        else:
                            kalan = SON_SATIR_SURESI_MS
                        satiri_yaz(metin, kalan)
            elif not duraklatildi:
                durum_guncelle(ad, "⏹️")
                duraklatildi = True
                son_idx = None  # devam edince mevcut satır yeniden yazılsın

        except Exception as exc:
            print(f"[Hata] {type(exc).__name__}: {exc}")
            time.sleep(HATA_BEKLEME_SN)
            continue

        time.sleep(SPOTIFY_KONTROL_SN)


def main() -> None:
    ayarlari_kontrol_et()

    eski_durum, okundu = mevcut_durumu_al()
    if token_gecersiz.is_set():
        raise SystemExit("Discord token geçersiz.")
    if not okundu:
        print("[Uyarı] Mevcut durum okunamadı, çıkışta durum temizlenecek.")

    sp = spotify_baglan()
    threading.Thread(target=_discord_worker, daemon=True).start()
    print("SpoChanger başladı. Çıkmak için Ctrl+C.")

    try:
        dongu(sp, eski_durum)
    finally:
        kapat(eski_durum)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nKapatıldı.")
