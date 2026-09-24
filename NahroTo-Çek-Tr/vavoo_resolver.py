#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vavoo_resolver.py - TAM VERSİYON + ÜLKE SEÇİMİ + OTOMATİK KÜTÜPHANE KONTROLÜ
"""

import sys
import subprocess  # pip install için

# === OTOMATİK KÜTÜPHANE KONTROLÜ ===
def install_package(package):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"[INFO] {package} başarıyla yüklendi!")
    except Exception as e:
        print(f"[HATA] {package} yüklenemedi: {e}. Lütfen elle yükleyin: pip install {package}", file=sys.stderr)
        sys.exit(1)

try:
    import requests
except ImportError:
    print("[INFO] requests kütüphanesi yüklü değil, otomatik yüklüyorum...")
    install_package("requests")
    import requests

try:
    import json
    import os
    import re
except ImportError:
    print("[HATA] Standart Python modülleri eksik! Python kurulumunuzu kontrol edin.", file=sys.stderr)
    sys.exit(1)

# config/domains.json
try:
    with open(os.path.join(os.path.dirname(__file__), 'config/domains.json'), encoding='utf-8') as f:
        DOMAINS = json.load(f)
    VAVOO_DOMAIN = DOMAINS.get("vavoo", "vavoo.to")
except Exception as e:
    print(f"[HATA] config/domains.json bulunamadı: {e}", file=sys.stderr)
    sys.exit(1)

def getAuthSignature():
    headers = {
        "user-agent": "okhttp/4.11.0",
        "accept": "application/json",
        "content-type": "application/json; charset=utf-8",
        "content-length": "1106",
        "accept-encoding": "gzip"
    }
    data = {
        "token": "tosFwQCJMS8qrW_AjLoHPQ41646J5dRNha6ZWHnijoYQQQoADQoXYSo7ki7O5-CsgN4CH0uRk6EEoJ0728ar9scCRQW3ZkbfrPfeCXW2VgopSW2FWDqPOoVYIuVPAOnXCZ5g",
        "reason": "app-blur",
        "locale": "de",
        "theme": "dark",
        "metadata": {
            "device": {
                "type": "Handset",
                "brand": "google",
                "model": "Nexus",
                "name": "21081111RG",
                "uniqueId": "d10e5d99ab665233"
            },
            "os": {
                "name": "android",
                "version": "7.1.2",
                "abis": ["arm64-v8a", "armeabi-v7a", "armeabi"],
                "host": "android"
            },
            "app": {
                "platform": "android",
                "version": "3.1.20",
                "buildId": "289515000",
                "engine": "hbc85",
                "signatures": ["6e8a975e3cbf07d5de823a760d4c2547f86c1403105020adee5de67ac510999e"],
                "installer": "app.revanced.manager.flutter"
            },
            "version": {
                "package": "tv.vavoo.app",
                "binary": "3.1.20",
                "js": "3.1.20"
            }
        },
        "appFocusTime": 0,
        "playerActive": False,
        "playDuration": 0,
        "devMode": False,
        "hasAddon": True,
        "castConnected": False,
        "package": "tv.vavoo.app",
        "version": "3.1.20",
        "process": "app",
        "firstAppStart": 1743962904623,
        "lastAppStart": 1743962904623,
        "ipLocation": "",
        "adblockEnabled": True,
        "proxy": {
            "supported": ["ss", "openvpn"],
            "engine": "ss",
            "ssVersion": 1,
            "enabled": True,
            "autoServer": True,
            "id": "pl-waw"
        },
        "iap": {
            "supported": False
        }
    }
    try:
        resp = requests.post("https://www.vavoo.tv/api/app/ping", json=data, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("addonSig")
    except Exception as e:
        print(f"[DEBUG] Signature error: {e}", file=sys.stderr)
        return None

def get_channels(group=None):
    signature = getAuthSignature()
    if not signature:
        return []
    headers = {
        "user-agent": "okhttp/4.11.0",
        "accept": "application/json",
        "content-type": "application/json; charset=utf-8",
        "accept-encoding": "gzip",
        "mediahubmx-signature": signature
    }
    all_channels = []
    groups = [group] if group else [
        "Turkey", "Germany", "Balkans", "Bulgaria", "France", "Arabia", "Italy",
        "Netherlands", "Poland", "Portugal", "Romania", "Russia", "Spain", "Albania",
        "United Kingdom", "United States"
    ]
    for g in groups:
        cursor = 0
        while True:
            data = {
                "language": "de", "region": "AT", "catalogId": "iptv", "id": "iptv",
                "adult": False, "search": "", "sort": "name", "filter": {"group": g},
                "cursor": cursor, "clientVersion": "3.0.2"
            }
            try:
                resp = requests.post(f"https://{VAVOO_DOMAIN}/mediahubmx-catalog.json", json=data, headers=headers, timeout=12)
                resp.raise_for_status()
                r = resp.json()
                all_channels.extend(r.get("items", []))
                cursor = r.get("nextCursor")
                if not cursor:
                    break
            except Exception:
                break
    return all_channels

def resolve_to_vavoo_iptv(url, channel_data):
    if isinstance(channel_data.get("ids"), dict) and channel_data["ids"].get("id"):
        return f"https://bynicola.manevibilgeniz.workers.dev/?url=https://vavoo.to/vavoo-iptv/play/{channel_data['ids']['id']}"
    return re.sub(r'https?://[^/]+/play/', 'https://bynicola.manevibilgeniz.workers.dev/?url=https://vavoo.to/vavoo-iptv/play/', url)

def normalize_vavoo_name(name):
    name = name.strip()
    name = re.sub(r'\s+\.[a-zA-Z]$', '', name)
    return name.upper()

# ====================== ANA KISIM ======================
if __name__ == "__main__":
    if len(sys.argv) < 2 and "--full-m3u" not in sys.argv and "--country-m3u" not in sys.argv:
        print("Kullanım: python vavoo_resolver.py <kanal_adi> [--vavoo-iptv] [--full-m3u] [--country-m3u <ulke>]", file=sys.stderr)
        sys.exit(1)

    # === TÜM ÜLKELER M3U ===
    if "--full-m3u" in sys.argv:
        print("[INFO] Tüm ülkelerden kanallar çekiliyor... (30-60 saniye sürebilir)")
        channels = get_channels()
        print(f"[INFO] {len(channels)} kanal bulundu. M3U oluşturuluyor...")
        with open("NahroTo_full.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in channels:
                name = ch.get("name", "Bilinmeyen").strip()
                url = ch.get("url")
                if not url: continue
                real_link = resolve_to_vavoo_iptv(url, ch)
                group = ch.get("group", "General")
                f.write(f'#EXTINF:-1 group-title="{group}",{name}\n')
                f.write(f"{real_link}\n")
        print(f"✅ NahroTo_full.m3u başarıyla oluşturuldu! ({len(channels)} kanal)")
        sys.exit(0)

    # === BELİRLİ ÜLKE M3U ===
    country_index = sys.argv.index("--country-m3u") if "--country-m3u" in sys.argv else -1
    if country_index != -1:
        country = sys.argv[country_index + 1]
        print(f"[INFO] {country} kanalları çekiliyor...")
        channels = get_channels(group=country)
        if not channels:
            print(f"[HATA] {country} grubu bulunamadı veya boş!")
            sys.exit(1)
        print(f"[INFO] {len(channels)} kanal bulundu. M3U oluşturuluyor...")
        with open(f"NahroTo_{country}.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in channels:
                name = ch.get("name", "Bilinmeyen").strip()
                url = ch.get("url")
                if not url: continue
                real_link = resolve_to_vavoo_iptv(url, ch)
                f.write(f'#EXTINF:-1 group-title="{country}",{name}\n')
                f.write(f"{real_link}\n")
        print(f"✅ NahroTo_{country}.m3u başarıyla oluşturuldu! ({len(channels)} kanal)")
        sys.exit(0)

    # === TEK KANAL MODU ===
    input_arg = sys.argv[1]
    use_vavoo_iptv = "--vavoo-iptv" in sys.argv
    return_original = "--original-link" in sys.argv

    if "vavoo.to" in input_arg and "/play/" in input_arg:
        if use_vavoo_iptv:
            input_arg = re.sub(r'https?://[^/]+/play/', 'https://bynicola.manevibilgeniz.workers.dev/?url=https://vavoo.to/vavoo-iptv/play/', input_arg)
        print(input_arg)
        sys.exit(0)

    wanted = normalize_vavoo_name(input_arg)
    channels = get_channels()

    found = None
    for ch in channels:
        if normalize_vavoo_name(ch.get('name', '')) == wanted:
            found = ch
            break
    if not found:
        for ch in channels:
            clean = re.sub(r'\s+\.[a-zA-Z]$|\s+(HD|FHD|4K)$', '', ch.get('name', '').upper())
            if wanted in clean or clean in wanted:
                found = ch
                break
    if not found:
        for ch in channels:
            simple_name = re.sub(r'[^A-Z0-9]', '', ch.get('name', '').upper())
            simple_wanted = re.sub(r'[^A-Z0-9]', '', wanted)
            if simple_wanted in simple_name or simple_name in simple_wanted:
                found = ch
                break

    if not found:
        print("NOT_FOUND", file=sys.stderr)
        sys.exit(2)

    url = found.get('url')
    if not url:
        print("NO_URL", file=sys.stderr)
        sys.exit(3)

    if use_vavoo_iptv:
        url = resolve_to_vavoo_iptv(url, found)

    if return_original or use_vavoo_iptv:
        print(url)
        sys.exit(0)

    print(url)