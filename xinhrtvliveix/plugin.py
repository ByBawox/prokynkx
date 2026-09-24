
import re
import sys
import os
import uuid
import time
import gzip
import json
import html
import threading
import urllib.parse
import unicodedata
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import xbmc
import xbmcplugin
import xbmcgui
import xbmcaddon
import xbmcvfs
import requests

addon        = xbmcaddon.Addon()
addon_handle = int(sys.argv[1])
base_url     = sys.argv[0]

ADDON_DATA  = xbmcvfs.translatePath("special://userdata/addon_data/xinhrtvliveix/")
CACHE_FILE  = os.path.join(ADDON_DATA, "catalog_cache.json")
FAV_FILE    = os.path.join(ADDON_DATA, "favourites.json")
ORDER_FILE  = os.path.join(ADDON_DATA, "country_order.json")
EPG_INDEX_FILE = os.path.join(ADDON_DATA, "epg_index.json")

os.makedirs(ADDON_DATA, exist_ok=True)

PING_URLS   = [
    "https://www.vypn.net/api/app/ping",
    "https://cache.vypn.net/api/app/ping",
]
BASE_SITES  = ["https://huhu.to", "https://www.huhu.to"]
BROWSER_UA  = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0.0.0 Safari/537.36")
MEDIAURL_UA = "MediaUrl/2"
PING_HEADERS = {"accept": "*/*", "user-agent": BROWSER_UA,
                "Accept-Encoding": "gzip, deflate", "Connection": "close"}
CATALOG_TTL = 3600
SIG_TTL     = 480
IPTV_ORG_CHANNELS_URL = "https://iptv-org.github.io/api/channels.json"
EPG_INDEX_TTL = 7 * 24 * 3600

DOWNLOAD_DIRS = [
    "/storage/emulated/0/Download",
    "/storage/emulated/0/Downloads",
    "/storage/self/primary/Download",
    "/sdcard/Download",
    "/sdcard/Downloads",
    "/storage/sdcard0/Download",
]

def _writable_download_dir():
    for d in DOWNLOAD_DIRS:
        test = os.path.join(d, ".vav_test")
        if _vfs_write(test, "x"):
            xbmcvfs.delete(test)
            return d
    return None

COUNTRY_LOGOS = {
    "albania":              "special://home/addons/xinhrtvliveix/resources/country/al.png",
    "arabia":               "special://home/addons/xinhrtvliveix/resources/country/ae.png",
    "azerbaijan":           "special://home/addons/xinhrtvliveix/resources/country/az.png",
    "balkans":              "special://home/addons/xinhrtvliveix/resources/country/yu.png",
    "belgium":              "special://home/addons/xinhrtvliveix/resources/country/be.png",
    "bulgaria":             "special://home/addons/xinhrtvliveix/resources/country/bg.png",
    "croatia":              "special://home/addons/xinhrtvliveix/resources/country/hr.png",
    "denmark":              "special://home/addons/xinhrtvliveix/resources/country/dk.png",
    "france":               "special://home/addons/xinhrtvliveix/resources/country/fr.png",
    "france sport":         "special://home/addons/xinhrtvliveix/resources/country/fr.png",
    "germany":              "special://home/addons/xinhrtvliveix/resources/country/de.png",
    "greece":               "special://home/addons/xinhrtvliveix/resources/country/gr.png",
    "iran":                 "special://home/addons/xinhrtvliveix/resources/country/ir.png",
    "italy":                "special://home/addons/xinhrtvliveix/resources/country/it.png",
    "netherlands":          "special://home/addons/xinhrtvliveix/resources/country/nl.png",
    "poland":               "special://home/addons/xinhrtvliveix/resources/country/pl.png",
    "portugal":             "special://home/addons/xinhrtvliveix/resources/country/pt.png",
    "romania":              "special://home/addons/xinhrtvliveix/resources/country/ro.png",
    "russia":               "special://home/addons/xinhrtvliveix/resources/country/ru.png",
    "spain":                "special://home/addons/xinhrtvliveix/resources/country/es.png",
    "sports international": "special://home/addons/xinhrtvliveix/resources/country/eu.png",
    "sweden":               "special://home/addons/xinhrtvliveix/resources/country/se.png",
    "turkey":               "special://home/addons/xinhrtvliveix/resources/country/tr.png",
    "united kingdom":       "special://home/addons/xinhrtvliveix/resources/country/gb.png",
}

DEFAULT_COUNTRY_ORDER = [
    "Turkey", "Germany", "Denmark", "Sports International",
    "United Kingdom", "France", "Italy", "Spain", "Portugal",
    "Netherlands", "Poland", "Romania", "Bulgaria", "Russia",
    "Greece", "Sweden", "Belgium", "Albania", "Arabia",
    "Azerbaijan", "Balkans", "Croatia", "Iran",
]

COUNTRY_CODES = {k: os.path.splitext(os.path.basename(v))[0].upper()
                for k, v in COUNTRY_LOGOS.items()}

_SEPARATORS     = ["=>", "->", "|"]
_SEPARATORS_UNI = ["\u27be", "\u27fe", "\u2192", "\u00bb", "\u203a"]

_sig_cache = {"sig": None, "ts": 0}
_sig_lock  = threading.Lock()
_base_idx  = [0]

def _log(msg, level=xbmc.LOGDEBUG):
    xbmc.log("[xinhrtvliveix][v7-slicefix] " + str(msg), level)

def _build_url(q):
    return base_url + "?" + urllib.parse.urlencode(q)

def _current_base():
    return BASE_SITES[_base_idx[0] % len(BASE_SITES)]

def _switch_base():
    _base_idx[0] += 1

def _decode(resp):
    raw = resp.content
    try:
        raw = gzip.decompress(raw)
    except Exception:
        pass
    return json.loads(raw.decode("utf-8", errors="replace"))

def _extract_country(group_str):
    s = (group_str or "").strip()
    for sep in _SEPARATORS_UNI + _SEPARATORS:
        if sep in s:
            s = s.split(sep)[0].strip()
            break
    s = s or "Other"
    return s.title()

def _clean_logo(url):
    if not url:
        return ""
    if "logo.huhu.to" in url:
        return ""
    return url

def _m3u_escape(s):
    return (s or "").replace('"', "'").replace("\n", " ").replace("\r", "")

def _vfs_write(path, content):
    try:
        f = xbmcvfs.File(path, 'w')
        result = f.write(content.encode("utf-8"))
        f.close()
        return result is not False
    except Exception as e:
        _log("VFS write %s: %s" % (path, e), xbmc.LOGWARNING)
        return False

_NORM_DROP = {"hd", "fhd", "uhd", "sd", "4k", "hevc", "h265", "tv"}

def _normalize_name(name):
    s = (name or "").lower()
    s = s.replace("ß", "ss").replace("ı", "i")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    words = [w for w in s.split() if w not in _NORM_DROP]
    return "".join(words)

def _load_epg_index(force=False):
    if not force:
        try:
            with open(EPG_INDEX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data.get("ts", 0) < EPG_INDEX_TTL:
                return data["by_country"], data["by_name"]
        except Exception:
            pass
    try:
        r = requests.get(IPTV_ORG_CHANNELS_URL, timeout=60, verify=False)
        r.raise_for_status()
        channels  = r.json()
        by_country, by_name = {}, {}
        for c in channels:
            cid = c.get("id")
            if not cid:
                continue
            country = (c.get("country") or "").upper()
            names = [c.get("name")] + (c.get("alt_names") or [])
            for n in names:
                norm = _normalize_name(n)
                if not norm:
                    continue
                by_country.setdefault(country + "|" + norm, cid)
                by_name.setdefault(norm, cid)
        with open(EPG_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "by_country": by_country, "by_name": by_name}, f)
        return by_country, by_name
    except Exception as e:
        _log("EPG index: " + str(e), xbmc.LOGWARNING)
        return {}, {}

def _auto_tvg_id(ch, by_country, by_name):
    norm = _normalize_name(ch["name"])
    if not norm:
        return ""
    code = COUNTRY_CODES.get(ch["country"].lower(), "")
    if code:
        tid = by_country.get(code + "|" + norm)
        if tid:
            return tid
    return by_name.get(norm, "")

def _notify(msg, error=False):
    icon = xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO
    xbmcgui.Dialog().notification("NahroTv", msg, icon, 3000)

def _refresh_container():
    xbmc.executebuiltin("Container.Refresh")

def _load_order():
    try:
        with open(ORDER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass
    return list(DEFAULT_COUNTRY_ORDER)

def _save_order(order):
    try:
        with open(ORDER_FILE, "w", encoding="utf-8") as f:
            json.dump(order, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log("Order save: " + str(e), xbmc.LOGWARNING)

def _sorted_countries(countries):
    order = _load_order()
    out, seen = [], set()
    for name in order:
        for c in countries:
            if c.lower() == name.lower() and c not in seen:
                out.append(c)
                seen.add(c)
    for c in sorted(countries):
        if c not in seen:
            out.append(c)
    return out

def _move_country(country, direction):
    channels = _get_catalog()
    all_ctry = list(set(ch["country"] for ch in channels))
    order    = _sorted_countries(all_ctry)
    if country not in order:
        order.append(country)
    idx = order.index(country)
    if direction == "up"     and idx > 0:
        order[idx], order[idx - 1] = order[idx - 1], order[idx]
    elif direction == "down" and idx < len(order) - 1:
        order[idx], order[idx + 1] = order[idx + 1], order[idx]
    elif direction == "top":
        order.insert(0, order.pop(idx))
    elif direction == "bottom":
        order.append(order.pop(idx))
    _save_order(order)
    _refresh_container()

def _reset_order():
    try:
        os.remove(ORDER_FILE)
    except Exception:
        pass
    _refresh_container()

def _load_favs():
    try:
        with open(FAV_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_favs(favs):
    try:
        with open(FAV_FILE, "w", encoding="utf-8") as f:
            json.dump(favs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log("Fav save: " + str(e), xbmc.LOGWARNING)

def _fav_exists(ch_id):
    return any(f["id"] == ch_id for f in _load_favs())

def _add_fav(ch):
    favs = _load_favs()
    if not _fav_exists(ch["id"]):
        favs.append({"id": ch["id"], "name": ch["name"],
                     "url": ch["url"], "logo": ch.get("logo", "")})
        _save_favs(favs)
        _notify('"%s" zu NahroTv Favoriten hinzugefuegt' % ch["name"])

def _remove_fav(ch_id):
    _save_favs([f for f in _load_favs() if f["id"] != ch_id])
    _notify("Aus NahroTv Favoriten entfernt")
    _refresh_container()

def _rename_fav(ch_id):
    favs  = _load_favs()
    entry = next((f for f in favs if f["id"] == ch_id), None)
    if not entry:
        return
    kb = xbmc.Keyboard(entry["name"], "Neuer Name")
    kb.doModal()
    if kb.isConfirmed():
        new_name = kb.getText().strip()
        if new_name:
            entry["name"] = new_name
            _save_favs(favs)
            _notify('Umbenannt zu "%s"' % new_name)
            _refresh_container()

def _move_fav(ch_id, direction):
    favs = _load_favs()
    idx  = next((i for i, f in enumerate(favs) if f["id"] == ch_id), None)
    if idx is None:
        return
    if direction == "up"     and idx > 0:
        favs[idx], favs[idx - 1] = favs[idx - 1], favs[idx]
    elif direction == "down" and idx < len(favs) - 1:
        favs[idx], favs[idx + 1] = favs[idx + 1], favs[idx]
    elif direction == "top":
        favs.insert(0, favs.pop(idx))
    elif direction == "bottom":
        favs.append(favs.pop(idx))
    _save_favs(favs)
    _refresh_container()

def _get_sig(force=False):
    with _sig_lock:
        now = time.time()
        if not force and _sig_cache["sig"] and (now - _sig_cache["ts"]) < SIG_TTL:
            return _sig_cache["sig"]
    uid = str(uuid.uuid4())
    ts  = int(time.time() * 1000)
    payload = {
        "reason": "app-focus", "locale": "en", "theme": "dark",
        "metadata": {
            "device":  {"type": "desktop", "uniqueId": uid},
            "os":      {"name": "win32", "version": "Windows 10 Pro",
                        "abis": ["x64"], "host": "Lenovo"},
            "app":     {"platform": "electron"},
            "version": {"package": "net.vypn.app", "binary": "3.1.0", "js": "3.1.0"},
        },
        "appFocusTime": 0, "playerActive": False, "playDuration": 0,
        "devMode": False, "hasAddon": True, "castConnected": False,
        "package": "net.vypn.app", "version": "3.1.0", "process": "app",
        "firstAppStart": ts, "lastAppStart": ts, "ipLocation": None,
        "adblockEnabled": True,
        "proxy": {"supported": ["ss"], "engine": "Mu",
                  "enabled": False, "autoServer": True},
        "iap": {"supported": False},
    }
    sig = None
    for url in PING_URLS:
        try:
            r = requests.post(url, json=payload, headers=PING_HEADERS,
                              timeout=15, verify=False)
            r.raise_for_status()
            data = _decode(r)
            sig = data.get("addonSig") or data.get("sig") or data.get("token")
            if sig:
                break
        except Exception as e:
            _log("Ping %s: %s" % (url, e), xbmc.LOGWARNING)
    if sig:
        with _sig_lock:
            _sig_cache["sig"] = sig
            _sig_cache["ts"]  = time.time()
    return sig

CACHE_VERSION = 2

def _save_catalog(channels):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "v": CACHE_VERSION, "channels": channels}, f)
    except Exception as e:
        _log("Cache write: " + str(e), xbmc.LOGWARNING)

def _load_catalog_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("v") != CACHE_VERSION:
            return None
        if time.time() - data.get("ts", 0) < CATALOG_TTL:
            return data["channels"]
    except Exception:
        pass
    return None

MAX_PAGES   = 60
MAX_WORKERS = 8

def _catalog_headers(sig):
    return {
        "content-type":       "application/json; charset=utf-8",
        "mediaurl-signature": sig or "",
        "user-agent":         MEDIAURL_UA,
        "accept":             "*/*",
        "Accept-Language":    "en",
        "Accept-Encoding":    "gzip, deflate",
        "Connection":         "close",
    }

def _fetch_one_page(base, sig, cursor):
    payload = {
        "language": "de", "region": "DE",
        "catalogId": "iptv", "id": "",
        "adult": True, "search": "", "sort": "trending-region", "filter": {},
        "cursor": cursor, "clientVersion": "3.1.0",
    }
    r = requests.post(base + "/mediaurl-catalog.json",
                      json=payload, headers=_catalog_headers(sig),
                      timeout=30, verify=False)
    r.raise_for_status()
    return _decode(r)

def _parse_items(items):
    result = []
    for item in items:
        if item.get("type") != "iptv":
            continue
        group = item.get("group", "")
        ids   = item.get("ids") or {}
        ch_id = ids.get("id") or item.get("id", "")
        result.append({
            "id":      ch_id,
            "name":    item.get("name") or item.get("title", "Unbekannt"),
            "url":     item.get("url", ""),
            "logo":    _clean_logo(item.get("logo") or item.get("artwork", "")),
            "country": _extract_country(group),
            "group":   group,
        })
    return result

def _fetch_catalog(sig, pd=None):
    base, mirror_tried = _current_base(), False
    session = requests.Session()

    def _fetch_page_s(cursor):
        payload = {
            "language": "de", "region": "DE",
            "catalogId": "iptv", "id": "",
            "adult": True, "search": "", "sort": "trending-region", "filter": {},
            "cursor": cursor, "clientVersion": "3.1.0",
        }
        r = session.post(base + "/mediaurl-catalog.json",
                         json=payload, headers=_catalog_headers(sig),
                         timeout=30, verify=False)
        r.raise_for_status()
        return _decode(r)

    try:
        data0 = _fetch_page_s(None)
    except Exception as e:
        if "451" in str(e) and not mirror_tried:
            _switch_base()
            base = _current_base()
            mirror_tried = True
            try:
                data0 = _fetch_page_s(None)
            except Exception as e2:
                _log("Catalog p1: %s" % e2, xbmc.LOGWARNING)
                return []
        else:
            _log("Catalog p1: %s" % e, xbmc.LOGWARNING)
            return []

    items0 = data0.get("items", [])
    if not items0:
        return []

    channels    = _parse_items(items0)
    cursor0     = data0.get("nextCursor")
    total_items = data0.get("totalCount") or data0.get("total") or 0
    page_size   = len(items0) or 1
    total_pages = min(MAX_PAGES, max(1, (total_items + page_size - 1) // page_size)
                      if total_items else MAX_PAGES)

    if pd:
        pd.update(max(1, int(100 / total_pages)),
                  "NahroTv Kanalliste... Seite 1  (%d Kanaele)" % len(channels))

    if not cursor0:
        return channels

    remaining = total_pages - 1
    canceled  = threading.Event()

    if isinstance(cursor0, int) and cursor0 > 0:
        step    = cursor0
        cursors = [step * (i + 1) for i in range(remaining)]

        lock = threading.Lock()
        done = [1]

        def _worker(cursor, page_num):
            if canceled.is_set():
                return []
            try:
                data = _fetch_page_s(cursor)
                return _parse_items(data.get("items", []))
            except Exception as e:
                _log("Catalog p%d: %s" % (page_num, e), xbmc.LOGWARNING)
                return []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(_worker, c, i + 2): i for i, c in enumerate(cursors)}
            for fut in as_completed(futs):
                if pd and pd.iscanceled():
                    canceled.set()
                    break
                batch = fut.result()
                with lock:
                    channels.extend(batch)
                    done[0] += 1
                    if pd:
                        pct = min(99, int(done[0] * 100 / total_pages))
                        pd.update(pct, "NahroTv Kanalliste... (%d Kanaele)" % len(channels))

    else:
        cursor   = cursor0
        page     = 1
        next_fut = None

        with ThreadPoolExecutor(max_workers=1) as ex:
            next_fut = ex.submit(_fetch_page_s, cursor)

            while page < MAX_PAGES:
                page += 1
                if pd and pd.iscanceled():
                    canceled.set()
                    break
                try:
                    data = next_fut.result(timeout=35)
                except Exception as e:
                    _log("Catalog p%d: %s" % (page, e), xbmc.LOGWARNING)
                    break

                items  = data.get("items", [])
                cursor = data.get("nextCursor")

                if cursor and not canceled.is_set():
                    next_fut = ex.submit(_fetch_page_s, cursor)

                if not items:
                    break
                channels.extend(_parse_items(items))

                if pd:
                    pct = min(99, int(page * 100 / total_pages))
                    pd.update(pct, "NahroTv Kanalliste... Seite %d  (%d Kanaele)" % (page, len(channels)))

                if not cursor:
                    break

    return channels

def _get_catalog():
    cached = _load_catalog_cache()
    if cached:
        return cached
    sig = _get_sig()
    if not sig:
        _notify("Kein Token – erneut versuchen", error=True)
        return []
    pd = xbmcgui.DialogProgress()
    pd.create("NahroTv", "NahroTv Kanalliste...")
    pd.update(0)
    channels = _fetch_catalog(sig, pd=pd)
    pd.update(100)
    pd.close()
    if channels:
        _save_catalog(channels)
    return channels

def _resolve(channel_url, sig):
    for attempt in range(2):
        headers = {
            "content-type":       "application/json; charset=utf-8",
            "mediaurl-signature": sig or "",
            "user-agent":         MEDIAURL_UA,
            "accept":             "*/*",
            "Accept-Language":    "en",
            "Accept-Encoding":    "gzip, deflate",
            "Connection":         "close",
        }
        payload = {"language": "de", "region": "DE",
                   "url": channel_url, "clientVersion": "3.1.0"}
        try:
            r = requests.post(_current_base() + "/mediaurl-resolve.json",
                              json=payload, headers=headers,
                              timeout=30, verify=False)
            if r.status_code == 451:
                _switch_base()
                continue
            r.raise_for_status()
            result = _decode(r)
            stream_url = None
            if isinstance(result, list) and result:
                stream_url = result[0].get("url")
            elif isinstance(result, dict):
                stream_url = result.get("url") or result.get("streamUrl")
            if stream_url:
                return stream_url
        except Exception as e:
            _log("Resolve %d: %s" % (attempt + 1, e), xbmc.LOGWARNING)
        if attempt == 0:
            sig = _get_sig(force=True)
            if not sig:
                break
    return None

def _make_channel_li(ch, context="channel"):
    li   = xbmcgui.ListItem(label=ch["name"])
    logo = ch.get("logo") or ""
    if logo:
        li.setArt({"thumb": logo, "icon": logo})
    li.setProperty("IsPlayable", "true")

    play_url = _build_url({"mode": "play",
                           "channel_url": ch["url"],
                           "channel_id":  ch["id"]})
    ctx = []

    if context == "fav":
        ctx += [
            ("Nach oben",
             "RunPlugin(%s)" % _build_url({"mode": "fav_move", "id": ch["id"], "dir": "up"})),
            ("Nach unten",
             "RunPlugin(%s)" % _build_url({"mode": "fav_move", "id": ch["id"], "dir": "down"})),
            ("Ganz nach oben",
             "RunPlugin(%s)" % _build_url({"mode": "fav_move", "id": ch["id"], "dir": "top"})),
            ("Ganz nach unten",
             "RunPlugin(%s)" % _build_url({"mode": "fav_move", "id": ch["id"], "dir": "bottom"})),
            ("Umbenennen",
             "RunPlugin(%s)" % _build_url({"mode": "fav_rename", "id": ch["id"]})),
            ("Aus NahroTv Favoriten entfernen",
             "RunPlugin(%s)" % _build_url({"mode": "fav_remove", "id": ch["id"]})),
        ]
    else:
        if _fav_exists(ch["id"]):
            ctx += [("Aus NahroTv Favoriten entfernen",
                     "RunPlugin(%s)" % _build_url({"mode": "fav_remove", "id": ch["id"]}))]
        else:
            ctx += [("Zu NahroTv Favoriten hinzufuegen",
                     "RunPlugin(%s)" % _build_url({"mode": "fav_add", "id": ch["id"]}))]

    ctx += [
        ("Timeshift",
         "RunPlugin(%s)" % _build_url({"mode": "timeshift_play",
                                       "channel_url": ch["url"],
                                       "channel_name": ch["name"]})),
        ("Download starten",
         "RunPlugin(%s)" % _build_url({"mode": "download_start",
                                       "channel_url": ch["url"],
                                       "channel_name": ch["name"]})),
        ("Aktive Downloads",
         "Container.Update(%s)" % _build_url({"mode": "download_list"})),
    ]

    li.addContextMenuItems(ctx)
    return li, play_url

def reload_catalog():
    try:
        os.remove(CACHE_FILE)
    except Exception:
        pass
    pd = xbmcgui.DialogProgress()
    pd.create("NahroTv", "NahroTv Kanalliste wird neu geladen...")
    sig = _get_sig(force=True)
    channels = _fetch_catalog(sig, pd=pd)
    pd.close()
    if channels:
        _save_catalog(channels)
        _notify("NahroTv Kanalliste aktualisiert: %d Kanaele" % len(channels))
    else:
        _notify("NahroaTv Kanalliste konnte nicht geladen werden.", error=True)
    _refresh_container()

def list_groups():
    channels = _get_catalog()
    if not channels:
        xbmcplugin.endOfDirectory(addon_handle)
        return

    fav_count = len(_load_favs())
    fav_label = "NahroTv Favoriten (%d)" % fav_count if fav_count else "NahroTv Favoriten"
    fav_icon  = "special://home/addons/xinhrtvliveix/resources/favourites.png"
    li_fav = xbmcgui.ListItem(label=fav_label)
    li_fav.setArt({"thumb": fav_icon, "icon": fav_icon})
    xbmcplugin.addDirectoryItem(handle=addon_handle,
                                url=_build_url({"mode": "list_favs"}),
                                listitem=li_fav, isFolder=True)

    search_icon = "special://home/addons/xinhrtvliveix/resources/search.png"
    li_search = xbmcgui.ListItem(label="Suche...")
    li_search.setArt({"thumb": search_icon, "icon": search_icon})
    xbmcplugin.addDirectoryItem(handle=addon_handle,
                                url=_build_url({"mode": "search"}),
                                listitem=li_search, isFolder=True)

    li_reload = xbmcgui.ListItem(label="[COLOR yellow]NahroTv Kanalliste neu laden[/COLOR]")
    li_reload.setArt({"thumb": "DefaultAddonSources.png", "icon": "DefaultAddonSources.png"})
    xbmcplugin.addDirectoryItem(handle=addon_handle,
                                url=_build_url({"mode": "reload_catalog"}),
                                listitem=li_reload, isFolder=False)

    settings_icon = "DefaultAddonProgram.png"
    li_settings = xbmcgui.ListItem(label="Einstellungen")
    li_settings.setArt({"thumb": settings_icon, "icon": settings_icon})

    countries = set(ch["country"] for ch in channels)
    for country in _sorted_countries(countries):
        li   = xbmcgui.ListItem(label=country)
        logo = COUNTRY_LOGOS.get(country.lower(), "")
        if logo:
            li.setArt({"thumb": logo, "icon": logo})
        ctx = [
            ("Nach oben",
             "RunPlugin(%s)" % _build_url({"mode": "ctry_move", "country": country, "dir": "up"})),
            ("Nach unten",
             "RunPlugin(%s)" % _build_url({"mode": "ctry_move", "country": country, "dir": "down"})),
            ("Ganz nach oben",
             "RunPlugin(%s)" % _build_url({"mode": "ctry_move", "country": country, "dir": "top"})),
            ("Ganz nach unten",
             "RunPlugin(%s)" % _build_url({"mode": "ctry_move", "country": country, "dir": "bottom"})),
            ("Reihenfolge zuruecksetzen",
             "RunPlugin(%s)" % _build_url({"mode": "ctry_reset"})),
        ]
        li.addContextMenuItems(ctx)
        xbmcplugin.addDirectoryItem(handle=addon_handle,
                                    url=_build_url({"mode": "list_channels", "group": country}),
                                    listitem=li, isFolder=True)

    xbmcplugin.addDirectoryItem(handle=addon_handle,
                                url=_build_url({"mode": "settings"}),
                                listitem=li_settings, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle)

def list_channels(group):
    channels = _get_catalog()
    matches = [ch for ch in channels if ch["country"].lower() == group.lower() and ch.get("url")]
    matches.sort(key=lambda ch: ch["name"].lower())
    epg_enabled = addon.getSetting("epg_enabled") != "false"
    epg_ids = {}
    programmes = {}
    if matches and epg_enabled:
        epg_ids = _load_epg_ids({group})
        programmes = _load_epg_programmes(group)
        _log("EPG list_channels %s: ids=%d progs=%d" % (group, len(epg_ids), len(programmes)), xbmc.LOGINFO)
    matched = 0
    name_matched = 0
    misses = []
    for ch in matches:
        li, url = _make_channel_li(ch, context="channel")
        entry, has_id, ch_id = _epg_plot_for_channel(ch, epg_ids, programmes)
        if has_id:
            name_matched += 1
        elif len(misses) < 15:
            misses.append(ch["name"])
        if has_id:
            try:
                plot = u""
                plotoutline = u""
                if entry:
                    matched += 1
                    start_dt = _parse_xmltv_datetime(entry["start"])
                    stop_dt  = _parse_xmltv_datetime(entry["stop"])
                    if start_dt and stop_dt:
                        start_loc = datetime.fromtimestamp(start_dt.timestamp())
                        stop_loc  = datetime.fromtimestamp(stop_dt.timestamp())
                        epg_str = u"  \u2022  [COLOR yellow]jetzt:[/COLOR] %s - %s: %s" % (
                            start_loc.strftime("%H:%M"), stop_loc.strftime("%H:%M"), entry["title"])
                        li.setLabel(ch["name"] + epg_str)
                        plot = u"[COLOR yellow]JETZT[/COLOR]\n%s - %s: %s" % (
                            start_loc.strftime("%H:%M"), stop_loc.strftime("%H:%M"), entry["title"])
                        plotoutline = entry["title"]
                upcoming = _upcoming_programmes(programmes, ch_id, count=3) if ch_id else []
                if upcoming:
                    plot += (u"\n\n" if plot else u"") + u"[COLOR cyan]Programm:[/COLOR]"
                    for nxt in upcoming:
                        ns = _parse_xmltv_datetime(nxt["start"])
                        ne = _parse_xmltv_datetime(nxt["stop"])
                        if ns and ne:
                            ns_loc = datetime.fromtimestamp(ns.timestamp())
                            ne_loc = datetime.fromtimestamp(ne.timestamp())
                            plot += u"\n%s - %s: %s" % (
                                ns_loc.strftime("%H:%M"), ne_loc.strftime("%H:%M"), nxt["title"])
                    if not plotoutline:
                        plotoutline = upcoming[0]["title"]
                if plot:
                    try:
                        tag = li.getVideoInfoTag()
                        tag.setMediaType("video")
                        tag.setTitle(ch["name"])
                        tag.setPlot(plot)
                        tag.setPlotOutline(plotoutline)
                    except Exception:
                        li.setInfo("video", {"title": ch["name"], "plot": plot, "plotoutline": plotoutline})
            except Exception:
                pass
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=url,
                                    listitem=li, isFolder=False)
    _log("EPG %s: enabled=%s names=%d programmes=%d channels=%d name_matched=%d now_matched=%d misses=%s" % (
        group, epg_enabled, len(epg_ids), len(programmes), len(matches), name_matched, matched, misses
    ), xbmc.LOGINFO)
    xbmcplugin.endOfDirectory(addon_handle)

def list_favs():
    favs = _load_favs()
    if not favs:
        xbmcgui.Dialog().ok("NahroTv Favoriten", "Noch keine NahroTv Favoriten gespeichert.")
        xbmcplugin.endOfDirectory(addon_handle)
        return
    for fav in favs:
        li, url = _make_channel_li(fav, context="fav")
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=url,
                                    listitem=li, isFolder=False)
    xbmcplugin.endOfDirectory(addon_handle)

def do_search(query=None):
    if not query:
        kb = xbmc.Keyboard("", "Kanal suchen")
        kb.doModal()
        if not kb.isConfirmed():
            xbmcplugin.endOfDirectory(addon_handle)
            return
        query = kb.getText().strip()
    if not query:
        xbmcplugin.endOfDirectory(addon_handle)
        return
    channels = _get_catalog()
    q        = query.lower()
    found    = [ch for ch in channels
                if q in ch["name"].lower() or q in ch["country"].lower()]
    if not found:
        xbmcgui.Dialog().ok("Suche", 'Keine Ergebnisse fuer "%s".' % query)
        xbmcplugin.endOfDirectory(addon_handle)
        return
    country_order = _load_order()
    order_map     = {c.lower(): i for i, c in enumerate(country_order)}

    def _sort_key(ch):
        ctry_idx = order_map.get(ch["country"].lower(), len(country_order))
        return (ctry_idx, ch["name"].lower())

    found.sort(key=_sort_key)

    xbmcplugin.setPluginCategory(addon_handle, "Suche: " + query)
    for ch in found:
        li, url = _make_channel_li(ch, context="channel")
        li.setLabel("%s  [%s]" % (ch["name"], ch["country"]))
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=url,
                                    listitem=li, isFolder=False)
    xbmcplugin.endOfDirectory(addon_handle)

_EPG_STRIP = re.compile(
    r'^\[.*?\]\s*'
    r'|\s*\|[A-Z0-9+]+$'
    r'|\s+\[.*?\]'
    r'|\s+\(.*?\)'
    r'|\s+\b(FHD|UHD|HD\+?|SD|4K|HEVC|RAW|SAT|BACKUP\s*\d*)\b',
    re.IGNORECASE
)

def _epg_name(raw):
    name = raw.strip()
    prev = None
    while name != prev:
        prev = name
        name = _EPG_STRIP.sub("", name).strip()
    return name


def browse_export_path():
    current = addon.getSetting("export_path").strip()
    if not current or current.startswith("special://"):
        start = "/storage"
    else:
        start = current
    chosen = xbmcgui.Dialog().browse(0, "Export-Ordner auswaehlen", "local", "", False, False, start)
    if chosen and chosen != start:
        addon.setSetting("export_path", chosen)
        _notify("Export-Ordner geaendert: " + chosen)

def browse_rec_dir():
    current = addon.getSetting("rec_dest_dir").strip()
    start   = current if current else "/storage/emulated/0"
    chosen  = xbmcgui.Dialog().browse(0, "Download-Ordner auswaehlen", "local", "", False, False, start)
    if chosen and chosen != start:
        addon.setSetting("rec_dest_dir", chosen)
        _notify("Download-Ordner geaendert: " + chosen)

def browse_ts_dir():
    current = addon.getSetting("timeshift_dir").strip()
    start   = current if current else "/storage/emulated/0"
    chosen  = xbmcgui.Dialog().browse(0, "Timeshift-Ordner auswaehlen", "local", "", False, False, start)
    if chosen and chosen != start:
        addon.setSetting("timeshift_dir", chosen)
        _notify("Timeshift-Ordner geaendert: " + chosen)

def _epg_base():
    url = addon.getSetting("epg_url").strip().rstrip("/")
    if url:
        return url + "/"
    return "http://epg.pw/xmltv/"

def _get_country_epg():
    b = _epg_base()
    ext = "xml.gz"
    return {
        "albania":              b + "epg_AL." + ext,
        "arabia":               "https://www.open-epg.com/files/arabic1.xml.gz",
        "azerbaijan":           None,
        "balkans":              b + "epg_RS." + ext,
        "belgium":              b + "epg_BE." + ext,
        "bulgaria":             b + "epg_BG." + ext,
        "croatia":              b + "epg_HR." + ext,
        "denmark":              b + "epg_DK." + ext,
        "france":               b + "epg_FR." + ext,
        "france sport":         b + "epg_FR." + ext,
        "germany":              b + "epg_DE." + ext,
        "greece":               b + "epg_GR." + ext,
        "iran":                 None,
        "italy":                b + "epg_IT." + ext,
        "netherlands":          b + "epg_NL." + ext,
        "poland":               b + "epg_PL." + ext,
        "portugal":             b + "epg_PT." + ext,
        "romania":              b + "epg_RO." + ext,
        "russia":               b + "epg_RU." + ext,
        "spain":                b + "epg_ES." + ext,
        "sports international": b + "epg_INT." + ext,
        "sweden":               b + "epg_SE." + ext,
        "turkey":               "https://www.open-epg.com/files/turkey1.xml.gz",
        "united kingdom":       b + "epg_UK." + ext,
    }

EPG_PROG_TTL = 6 * 3600
EPG_IDS_TTL  = 12 * 3600
EPG_PROG_VERSION = 2
EPG_IDS_VERSION  = 2

def _epg_ids_cache_file(country):
    safe = re.sub(r"[^a-z0-9]+", "_", country.lower())
    return os.path.join(ADDON_DATA, "epg_ids_%s.json" % safe)

def _epg_prog_cache_file(country):
    safe = re.sub(r"[^a-z0-9]+", "_", country.lower())
    return os.path.join(ADDON_DATA, "epg_prog_%s.json" % safe)

_epg_id_cache = {}
_epg_id_cache_lock = threading.Lock()
_epg_raw_cache = {}
_epg_raw_cache_lock = threading.Lock()

def _fetch_epg_raw(url):
    with _epg_raw_cache_lock:
        if url in _epg_raw_cache:
            return _epg_raw_cache[url]
    try:
        r = requests.get(url, timeout=120, verify=False)
        r.raise_for_status()
        try:
            raw = gzip.decompress(r.content).decode("utf-8", errors="replace")
        except Exception:
            raw = r.text
        _log("EPG fetch OK %s: %d chars" % (url, len(raw)), xbmc.LOGINFO)
        with _epg_raw_cache_lock:
            _epg_raw_cache[url] = raw
        return raw
    except Exception as e:
        _log("EPG fetch FAIL %s: %s" % (url, e), xbmc.LOGWARNING)
        return None

def _load_epg_ids(countries):
    result = {}
    for c in countries:
        url = _get_country_epg().get(c.lower())
        if not url:
            continue
        with _epg_id_cache_lock:
            cached = _epg_id_cache.get(url)
        if cached is not None:
            result.update(cached)
            continue
        cache_file = _epg_ids_cache_file(c)
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                fd = json.load(f)
            if fd.get("v") == EPG_IDS_VERSION and time.time() - fd.get("ts", 0) < EPG_IDS_TTL:
                mapping = fd["mapping"]
                if "__norm_to_ids__" not in mapping or not isinstance(mapping.get("__norm_to_ids__"), dict):
                    norm_to_ids = {}
                    for k, v in mapping.items():
                        if k != "__norm_to_ids__" and isinstance(v, str):
                            norm_to_ids[k] = v
                    mapping["__norm_to_ids__"] = norm_to_ids
                with _epg_id_cache_lock:
                    _epg_id_cache[url] = mapping
                result.update(mapping)
                _log("EPG ids cache hit %s: %d names" % (c, len(mapping)), xbmc.LOGINFO)
                continue
        except Exception:
            pass
        raw = _fetch_epg_raw(url)
        if not raw:
            continue
        mapping = {}
        norm_to_ids = {}
        for cm in re.finditer(r'<channel id="([^"]+)"[^>]*>(.*?)</channel>', raw, re.DOTALL):
            ch_id = cm.group(1)
            body  = cm.group(2)
            for nm in re.finditer(r'<display-name[^>]*>([^<]*)</display-name>', body):
                ch_name = html.unescape(nm.group(1)).strip()
                if not ch_name:
                    continue
                mapping.setdefault(ch_name.lower(), ch_id)
                norm = _normalize_name(ch_name)
                if norm:
                    mapping.setdefault(norm, ch_id)
                    norm_to_ids.setdefault(norm, ch_id)
        mapping["__norm_to_ids__"] = norm_to_ids
        _log("EPG ids mapped %s: %d names" % (url, len(mapping)), xbmc.LOGINFO)
        with _epg_id_cache_lock:
            _epg_id_cache[url] = mapping
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "v": EPG_IDS_VERSION, "mapping": mapping}, f)
        except Exception as e:
            _log("EPG ids cache write %s: %s" % (c, e), xbmc.LOGWARNING)
        result.update(mapping)
    return result


def _epg_id_prefix_match(epg_ids, norm):
    norm_map = epg_ids.get("__norm_to_ids__", {})
    for key, ch_id in norm_map.items():
        if key.startswith(norm) or norm.startswith(key):
            return ch_id
    return None


def _parse_xmltv_datetime(s):
    try:
        s = s.strip().replace("\r", "").replace("\n", "").replace("\t", "")
        digits = ""
        rest = ""
        for i, c in enumerate(s):
            if c.isdigit():
                digits += c
            else:
                rest = s[i:].strip()
                break
        if len(digits) < 14:
            return None
        digits = digits[:14]
        yr  = int(digits[0:4])
        mo  = int(digits[4:6])
        dy  = int(digits[6:8])
        hr  = int(digits[8:10])
        mn  = int(digits[10:12])
        sc  = int(digits[12:14])
        dt  = datetime(yr, mo, dy, hr, mn, sc)
        offset_str = rest if rest and rest[0] in ("+", "-") else "+0000"
        offset_str = offset_str[:5]
        sign = 1 if offset_str[0] == "+" else -1
        oh   = int(offset_str[1:3])
        om   = int(offset_str[3:5])
        offset = timezone(sign * timedelta(hours=oh, minutes=om))
        return dt.replace(tzinfo=offset)
    except Exception:
        return None

def _parse_xmltv_programmes(raw):
    programmes = {}
    for m in re.finditer(r'<programme\b([^>]+)>(.*?)</programme>', raw, re.DOTALL):
        attrs = m.group(1)
        body  = m.group(2)
        s_m   = re.search(r'start="([^"]+)"', attrs)
        st_m  = re.search(r'stop="([^"]+)"', attrs)
        ch_m  = re.search(r'channel="([^"]+)"', attrs)
        if not (s_m and st_m and ch_m):
            continue
        start  = s_m.group(1)
        stop   = st_m.group(1)
        ch_id  = ch_m.group(1)
        title_m = re.search(r'<title[^>]*>([^<]*)</title>', body)
        desc_m  = re.search(r'<desc[^>]*>([^<]*)</desc>', body)
        title = html.unescape(title_m.group(1)).strip() if title_m else ""
        if not title:
            continue
        desc = html.unescape(desc_m.group(1)).strip() if desc_m else ""
        programmes.setdefault(ch_id, []).append({
            "start": start, "stop": stop, "title": title, "desc": desc,
        })
    return programmes

EPG_PROG_MEM_TTL = 300

_epg_prog_mem_cache = {}
_epg_prog_mem_lock  = threading.Lock()

def _load_epg_programmes(country):
    url = _get_country_epg().get(country.lower())
    if not url:
        return {}
    now = time.time()
    with _epg_prog_mem_lock:
        entry = _epg_prog_mem_cache.get(country)
        if entry and now - entry["ts"] < EPG_PROG_MEM_TTL:
            _log("EPG prog mem-cache hit %s: %d channels" % (country, len(entry["progs"])), xbmc.LOGINFO)
            return entry["progs"]
    cache_file = _epg_prog_cache_file(country)
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            fd = json.load(f)
        if fd.get("v") == EPG_PROG_VERSION and now - fd.get("ts", 0) < EPG_PROG_MEM_TTL:
            progs = fd["progs"]
            with _epg_prog_mem_lock:
                _epg_prog_mem_cache[country] = {"progs": progs, "ts": fd["ts"]}
            _log("EPG prog disk-cache hit %s: %d channels" % (country, len(progs)), xbmc.LOGINFO)
            return progs
    except Exception:
        pass
    try:
        raw = _fetch_epg_raw(url)
        if not raw:
            _log("EPG prog: no raw for %s" % country, xbmc.LOGWARNING)
            return {}
        progs = _parse_xmltv_programmes(raw)
        _log("EPG prog parsed %s: %d channels, %d total entries" % (
            country, len(progs), sum(len(v) for v in progs.values())), xbmc.LOGINFO)
        with _epg_prog_mem_lock:
            _epg_prog_mem_cache[country] = {"progs": progs, "ts": now}
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"ts": now, "v": EPG_PROG_VERSION, "progs": progs}, f)
        except Exception as e:
            _log("EPG prog cache write %s: %s" % (country, e), xbmc.LOGWARNING)
        return progs
    except Exception as e:
        _log("EPG prog fetch %s: %s" % (url, e), xbmc.LOGWARNING)
        return {}

_epg_time_logged = False

def _current_programme(programmes, ch_id):
    global _epg_time_logged
    _epg_time_logged = False
    entries = programmes.get(ch_id)
    if not entries:
        return None
    now = datetime.now(timezone.utc)
    for entry in entries:
        start = _parse_xmltv_datetime(entry["start"])
        stop  = _parse_xmltv_datetime(entry["stop"])
        if start is None or stop is None:
            if not _epg_time_logged:
                _log("EPG parse fail: start=%r stop=%r" % (entry.get("start"), entry.get("stop")), xbmc.LOGWARNING)
                _epg_time_logged = True
            continue
        if not _epg_time_logged:
            _log("EPG time check: now=%s start=%s stop=%s" % (now.isoformat(), start.isoformat(), stop.isoformat()), xbmc.LOGINFO)
            _epg_time_logged = True
        if start <= now <= stop:
            return entry
    return None

def _epg_plot_for_channel(ch, epg_ids, programmes):
    if not epg_ids:
        return None, False, None
    clean = _epg_name(ch["name"])
    norm_clean = _normalize_name(clean)
    norm_raw   = _normalize_name(ch["name"])
    ch_id = (epg_ids.get(clean.lower())
             or epg_ids.get(clean.lower().replace(" ", "_"))
             or epg_ids.get(norm_clean)
             or epg_ids.get(norm_raw)
             or _epg_id_prefix_match(epg_ids, norm_clean)
             or _epg_id_prefix_match(epg_ids, norm_raw))
    if not ch_id:
        return None, False, None
    return _current_programme(programmes, ch_id), True, ch_id

def _upcoming_programmes(programmes, ch_id, count=3):
    entries = programmes.get(ch_id)
    if not entries:
        return []
    now = datetime.now(timezone.utc)
    upcoming = []
    for entry in entries:
        start = _parse_xmltv_datetime(entry["start"])
        if start and start > now:
            upcoming.append(entry)
    upcoming.sort(key=lambda e: e["start"])
    return upcoming[:count]

def export_m3u():
    channels = _get_catalog()
    if not channels:
        _notify("Keine Kanaele geladen", error=True)
        return

    all_countries = _sorted_countries(list(set(ch["country"] for ch in channels)))
    selected = xbmcgui.Dialog().multiselect("Laender auswaehlen", all_countries, preselect=[])
    if selected is None:
        return
    if not selected:
        _notify("Kein Land ausgewaehlt", error=True)
        return
    chosen_countries = set(all_countries[i] for i in selected)

    epg_enabled  = addon.getSetting("epg_enabled") != "false"
    auto_map     = addon.getSetting("auto_map") != "false"
    custom_url   = addon.getSetting("epg_url").strip()
    export_dir   = addon.getSetting("export_path").strip() or ADDON_DATA
    export_dir   = xbmcvfs.translatePath(export_dir)
    xbmcvfs.mkdirs(export_dir)
    path = os.path.join(export_dir, "NahroTv.m3u")

    epg_urls   = []
    epg_ids    = {}
    by_country = {}
    by_name    = {}

    if epg_enabled:
        pd = xbmcgui.DialogProgress()
        pd.create("NahroTv", "Lade EPG-Daten...")
        pd.update(0)

        if custom_url:
            epg_urls.append(custom_url)

        for c in chosen_countries:
            url = _get_country_epg().get(c.lower())
            if url and url not in epg_urls:
                epg_urls.append(url)

        pd.update(20, "Lade EPG-Kanalnamen...")
        epg_ids = _load_epg_ids(chosen_countries)

        if auto_map:
            pd.update(60, "Lade iptv-org Zuordnung...")
            by_country, by_name = _load_epg_index()

        pd.update(100)
        pd.close()

    if epg_urls:
        header = '#EXTM3U url-tvg="%s"' % epg_urls[0]
        if len(epg_urls) > 1:
            header += ' x-tvg-url="%s"' % ",".join(epg_urls[1:])
        lines = [header]
    else:
        lines = ["#EXTM3U"]

    matched = 0
    for ch in channels:
        if not ch.get("url"):
            continue
        if ch["country"] not in chosen_countries:
            continue
        name    = _m3u_escape(ch["name"])
        country = _m3u_escape(ch["country"])
        logo    = _m3u_escape(ch.get("logo") or "") if epg_enabled else ""
        clean   = _epg_name(ch["name"])
        tvg_id  = ""

        if epg_enabled:
            norm_clean = _normalize_name(clean)
            tvg_id = (epg_ids.get(clean.lower())
                      or epg_ids.get(clean.lower().replace(" ", "_"))
                      or epg_ids.get(norm_clean)
                      or _epg_id_prefix_match(epg_ids, norm_clean)
                      or "")
            if not tvg_id and auto_map:
                tvg_id = _auto_tvg_id(ch, by_country, by_name)
            if tvg_id:
                matched += 1
            else:
                tvg_id = clean

        tvg_id   = _m3u_escape(tvg_id)
        tvg_name = _m3u_escape(clean) if epg_enabled else name
        lines.append('#EXTINF:-1 tvg-id="%s" tvg-name="%s" tvg-logo="%s" group-title="%s",%s' %
                      (tvg_id, tvg_name, logo, country, name))
        plugin_url = "https://bynicola.manevibilgeniz.workers.dev/?url=%s&channel_id=%s" % (
            urllib.parse.quote(ch["url"], safe=""), urllib.parse.quote(ch["id"], safe=""))
        lines.append(plugin_url)

    content = "\n".join(lines) + "\n"
    written = []
    if _vfs_write(path, content):
        written.append(path)

    dl_dir = _writable_download_dir()
    if dl_dir:
        dl_path = os.path.join(dl_dir, "NahroTv.m3u")
        if os.path.normpath(dl_path) != os.path.normpath(path) and _vfs_write(dl_path, content):
            written.append(dl_path)

    if not written:
        _notify("NahroTv Export fehlgeschlagen (keine Schreibrechte)", error=True)
        return

    ch_count = (len(lines) - 1) // 2
    if epg_enabled:
        _notify("NahroTv M3U exportiert (%d Kanaele, %d EPG-Treffer): %s" % (ch_count, matched, ", ".join(written)))
    else:
        _notify("NahroTv M3U exportiert (%d Kanaele): %s" % (ch_count, ", ".join(written)))

def epg_refresh():
    by_country, by_name = _load_epg_index(force=True)
    if by_name:
        _notify("NahroTv EPG-Datenbank aktualisiert (%d Kanaele)" % len(by_name))
    else:
        _notify("NahroTv EPG-Datenbank Update fehlgeschlagen", error=True)

_REC_STATE_FILE = os.path.join(ADDON_DATA, "active_downloads.json")
_rec_lock       = threading.Lock()
_rec_threads    = {}

def _rec_sanitize(text, max_len=60):
    for s, r in [("ä","ae"),("ö","oe"),("ü","ue"),("Ä","Ae"),("Ö","Oe"),("Ü","Ue"),("ß","ss")]:
        text = text.replace(s, r)
    text = "".join(c for c in text if c.isalnum() or c in " _-()[]").strip()
    return " ".join(text.split())[:max_len].strip()

def _rec_make_path(dest_dir, channel_name, start_time):
    ts  = time.strftime("%Y%m%d_%H%M", time.localtime(start_time))
    fn  = "%s_%s.ts" % (ts, _rec_sanitize(channel_name, 40))
    return os.path.join(dest_dir, fn)

def _rec_load_state():
    try:
        with open(_REC_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _rec_save_state(data):
    try:
        with open(_REC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass

def _rec_set(rec_id, **fields):
    with _rec_lock:
        data = _rec_load_state()
        data.setdefault(rec_id, {}).update(fields)
        _rec_save_state(data)

def _rec_remove(rec_id):
    with _rec_lock:
        data = _rec_load_state()
        data.pop(rec_id, None)
        _rec_save_state(data)

def _rec_get_dir():
    d = addon.getSetting("rec_dest_dir") or ""
    if not d:
        d = _writable_download_dir() or ""
    if not d:
        _notify("NahroTv Kein Download-Ordner konfiguriert. Bitte in Einstellungen festlegen.", error=True)
        return None
    os.makedirs(d, exist_ok=True)
    return d

class _RecordingThread(threading.Thread):
    def __init__(self, rec_id, stream_url, dest_path, duration_secs, channel_name):
        super().__init__(daemon=True, name="rec_%s" % rec_id[:8])
        self.rec_id       = rec_id
        self.stream_url   = stream_url
        self.dest_path    = dest_path
        self.duration_secs = duration_secs
        self.channel_name = channel_name
        self._stop        = threading.Event()

    @staticmethod
    def _is_hls(url):
        return ".m3u8" in url.lower()

    def _record_stream(self):
        retries = 0
        append  = False
        bytes_written = 0
        while not self._stop.is_set():
            try:
                mode = "ab" if append else "wb"
                with requests.get(self.stream_url, stream=True,
                                  headers={"User-Agent": BROWSER_UA},
                                  timeout=(10, 60)) as r:
                    r.raise_for_status()
                    with open(self.dest_path, mode) as f:
                        for chunk in r.iter_content(65536):
                            if self._stop.is_set():
                                return bytes_written
                            if chunk:
                                f.write(chunk)
                                bytes_written += len(chunk)
                if self._stop.is_set():
                    return bytes_written
                append   = True
                retries += 1
                if retries > 10:
                    break
                time.sleep(min(2 * retries, 15))
            except Exception as e:
                if self._stop.is_set():
                    return bytes_written
                retries += 1
                append   = True
                if retries > 10:
                    break
                _log("Rec %s Reconnect %d/10: %s" % (self.rec_id[:8], retries, e), xbmc.LOGWARNING)
                time.sleep(min(2 * retries, 15))
        return bytes_written

    def _record_hls(self):
        from urllib.parse import urljoin
        headers      = {"User-Agent": BROWSER_UA}
        seen         = set()
        media_url    = self.stream_url
        bytes_written = 0
        deadline     = time.time() + self.duration_secs
        try:
            r = requests.get(self.stream_url, headers=headers, timeout=(10, 30))
            r.raise_for_status()
            if "#EXT-X-STREAM-INF" in r.text:
                for line in r.text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        media_url = line if line.startswith("http") else urljoin(self.stream_url, line)
                        break
        except Exception as e:
            _log("Rec HLS master: %s" % e, xbmc.LOGWARNING)
            return 0
        try:
            with open(self.dest_path, "wb") as f:
                while not self._stop.is_set() and time.time() < deadline:
                    try:
                        r = requests.get(media_url, headers=headers, timeout=(10, 30))
                        r.raise_for_status()
                        new_segs = []
                        for line in r.text.splitlines():
                            line = line.strip()
                            if line and not line.startswith("#"):
                                su = line if line.startswith("http") else urljoin(media_url, line)
                                if su not in seen:
                                    new_segs.append(su)
                        for su in new_segs:
                            if self._stop.is_set():
                                break
                            try:
                                sr = requests.get(su, headers=headers, timeout=(5, 30), stream=True)
                                sr.raise_for_status()
                                for chunk in sr.iter_content(65536):
                                    if chunk:
                                        f.write(chunk)
                                        bytes_written += len(chunk)
                                seen.add(su)
                            except Exception as se:
                                _log("Rec HLS Segment %s: %s" % (su, se), xbmc.LOGWARNING)
                        time.sleep(1 if new_segs else 2)
                    except Exception as e:
                        if self._stop.is_set():
                            break
                        _log("Rec HLS Playlist: %s" % e, xbmc.LOGWARNING)
                        time.sleep(3)
        except Exception as e:
            _log("Rec HLS Schreibfehler: %s" % e, xbmc.LOGERROR)
        return bytes_written

    def run(self):
        timer = threading.Timer(self.duration_secs, self._stop.set)
        timer.daemon = True
        timer.start()
        _rec_set(self.rec_id, status="recording", channel=self.channel_name,
                 started_at=time.time(), dest=self.dest_path, duration=self.duration_secs)
        try:
            if self._is_hls(self.stream_url):
                bw = self._record_hls()
            else:
                bw = self._record_stream()
            if bw > 0:
                _notify("NahroTv Download fertig: %s" % self.channel_name)
            else:
                _notify("NahroTv Download fehlgeschlagen: %s" % self.channel_name, error=True)
        except Exception as e:
            _log("Rec run: %s" % e, xbmc.LOGERROR)
            _notify("NahroTv Download Fehler: %s" % self.channel_name, error=True)
        finally:
            timer.cancel()
            _rec_remove(self.rec_id)
            _rec_threads.pop(self.rec_id, None)

    def cancel(self):
        self._stop.set()

def _get_active_recordings():
    data = _rec_load_state()
    now  = time.time()
    stale = [rid for rid, e in data.items() if now - e.get("started_at", now) > 12 * 3600]
    if stale:
        with _rec_lock:
            data2 = _rec_load_state()
            for rid in stale:
                data2.pop(rid, None)
            _rec_save_state(data2)
            data = data2
    return data

def start_download(ch, stream_url):
    dest_dir = _rec_get_dir()
    if not dest_dir:
        return
    kb = xbmcgui.Dialog()
    dur_str = kb.input("Aufnahmedauer in Minuten", type=xbmcgui.INPUT_NUMERIC, defaultt="60")
    if not dur_str:
        return
    try:
        duration_secs = max(60, int(dur_str) * 60)
    except ValueError:
        return
    rec_id    = uuid.uuid4().hex
    dest_path = _rec_make_path(dest_dir, ch["name"], time.time())
    t = _RecordingThread(rec_id, stream_url, dest_path, duration_secs, ch["name"])
    _rec_threads[rec_id] = t
    t.start()
    _notify("NahroTv Download gestartet: %s (%d Min)" % (ch["name"], duration_secs // 60))

def stop_download(rec_id):
    t = _rec_threads.get(rec_id)
    if t and t.is_alive():
        t.cancel()
        _notify("NahroTv Download gestoppt")
    else:
        _rec_remove(rec_id)

def list_downloads():
    data = _get_active_recordings()
    if not data:
        xbmcgui.Dialog().ok("NahroTv Downloads", "Keine aktiven Downloads.")
        xbmcplugin.endOfDirectory(addon_handle)
        return
    for rid, entry in data.items():
        ch_name  = entry.get("channel", rid)
        started  = entry.get("started_at", 0)
        elapsed  = int(time.time() - started)
        duration = int(entry.get("duration", 0))
        dest     = entry.get("dest", "")
        label    = "[COLOR yellow]%s[/COLOR]  [%d/%d Min]" % (
            ch_name, elapsed // 60, duration // 60)
        li = xbmcgui.ListItem(label=label)
        li.setProperty("IsPlayable", "false")
        li.setLabel2(dest)
        ctx = [("Download stoppen",
                "RunPlugin(%s)" % _build_url({"mode": "download_stop", "rec_id": rid}))]
        li.addContextMenuItems(ctx)
        xbmcplugin.addDirectoryItem(handle=addon_handle, url="",
                                    listitem=li, isFolder=False)
    xbmcplugin.endOfDirectory(addon_handle)


_TS_MIN_BUFFER   = 524288
_TS_MIN_WAIT     = 5.0
_ts_active       = None
_ts_lock         = threading.Lock()
_ts_monitors     = []

def _ts_dir():
    d = addon.getSetting("timeshift_dir") or ""
    if not d:
        d = os.path.join(ADDON_DATA, "timeshift")
    os.makedirs(d, exist_ok=True)
    return d

class _TsRecordThread(threading.Thread):
    def __init__(self, ts_path, stream_url):
        super().__init__(daemon=True, name="ts_rec")
        self._ts_path    = ts_path
        self._stream_url = stream_url
        self._stop       = threading.Event()
        self.bytes_written = 0

    def stop(self):
        self._stop.set()

    @staticmethod
    def _is_hls(url):
        return ".m3u8" in url.lower()

    def _record_stream(self):
        retries = 0
        append  = False
        while not self._stop.is_set():
            try:
                mode = "ab" if append else "wb"
                with requests.get(self._stream_url, stream=True,
                                  headers={"User-Agent": BROWSER_UA},
                                  timeout=(10, 60)) as r:
                    r.raise_for_status()
                    with open(self._ts_path, mode) as f:
                        for chunk in r.iter_content(65536):
                            if self._stop.is_set():
                                return
                            if chunk:
                                f.write(chunk)
                                self.bytes_written += len(chunk)
                if self._stop.is_set():
                    return
                append   = True
                retries += 1
                if retries > 20:
                    break
                time.sleep(min(2 * retries, 15))
            except Exception as e:
                if self._stop.is_set():
                    return
                retries += 1
                append   = True
                if retries > 20:
                    break
                _log("TS Reconnect %d/20: %s" % (retries, e), xbmc.LOGWARNING)
                time.sleep(min(2 * retries, 15))

    def _record_hls(self):
        from urllib.parse import urljoin
        headers   = {"User-Agent": BROWSER_UA}
        seen      = set()
        media_url = self._stream_url
        try:
            r = requests.get(self._stream_url, headers=headers, timeout=(10, 30))
            r.raise_for_status()
            if "#EXT-X-STREAM-INF" in r.text:
                for line in r.text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        media_url = line if line.startswith("http") else urljoin(self._stream_url, line)
                        break
        except Exception as e:
            _log("TS HLS master: %s" % e, xbmc.LOGWARNING)
            return
        try:
            with open(self._ts_path, "wb") as f:
                while not self._stop.is_set():
                    try:
                        r = requests.get(media_url, headers=headers, timeout=(10, 30))
                        r.raise_for_status()
                        new_segs = []
                        for line in r.text.splitlines():
                            line = line.strip()
                            if line and not line.startswith("#"):
                                su = line if line.startswith("http") else urljoin(media_url, line)
                                if su not in seen:
                                    new_segs.append(su)
                        for su in new_segs:
                            if self._stop.is_set():
                                break
                            try:
                                sr = requests.get(su, headers=headers, timeout=(5, 30), stream=True)
                                sr.raise_for_status()
                                for chunk in sr.iter_content(65536):
                                    if chunk:
                                        f.write(chunk)
                                        self.bytes_written += len(chunk)
                                seen.add(su)
                            except Exception as se:
                                _log("TS HLS Segment %s: %s" % (su, se), xbmc.LOGWARNING)
                        time.sleep(1 if new_segs else 2)
                    except Exception as e:
                        if self._stop.is_set():
                            break
                        _log("TS HLS Playlist: %s" % e, xbmc.LOGWARNING)
                        time.sleep(3)
        except Exception as e:
            _log("TS HLS Schreibfehler: %s" % e, xbmc.LOGERROR)

    def run(self):
        try:
            if self._is_hls(self._stream_url):
                self._record_hls()
            else:
                self._record_stream()
        except Exception as e:
            _log("TS Recorder: %s" % e, xbmc.LOGERROR)


class _TsStopMonitor(xbmc.Player):
    def activate(self):
        _ts_monitors.append(self)

    def onPlayBackStopped(self):
        self._end()

    def onPlayBackEnded(self):
        self._end()

    def onPlayBackError(self):
        self._end()

    def _end(self):
        _log("TS: Wiedergabe beendet → Session stoppen", xbmc.LOGDEBUG)
        _ts_stop_session()
        try:
            _ts_monitors.remove(self)
        except ValueError:
            pass


class _TsSession:
    def __init__(self):
        self.sid     = uuid.uuid4().hex
        self.ts_path = os.path.join(_ts_dir(), "ts_%s.ts" % self.sid)
        self._thread = None

    def start(self, stream_url):
        self._thread = _TsRecordThread(self.ts_path, stream_url)
        self._thread.start()
        _log("TS: Recording → %s" % self.ts_path, xbmc.LOGDEBUG)

    def wait_for_buffer(self):
        deadline = time.time() + _TS_MIN_WAIT
        while time.time() < deadline:
            try:
                if os.path.exists(self.ts_path) and os.path.getsize(self.ts_path) >= _TS_MIN_BUFFER:
                    return True
            except OSError:
                pass
            xbmc.sleep(200)
        try:
            return os.path.exists(self.ts_path) and os.path.getsize(self.ts_path) > 0
        except OSError:
            return False

    def play(self, channel_name):
        li = xbmcgui.ListItem(channel_name, path=self.ts_path)
        li.setMimeType("video/mp2t")
        li.setContentLookup(False)
        try:
            tag = li.getVideoInfoTag()
            tag.setMediaType("movie")
            tag.setTitle(channel_name)
        except Exception:
            li.setInfo("video", {"mediatype": "movie", "title": channel_name})
        xbmc.Player().play(self.ts_path, li)
        _log("TS: Wiedergabe gestartet: %s" % self.ts_path, xbmc.LOGDEBUG)

    def stop(self):
        if self._thread:
            self._thread.stop()
        rec  = self._thread
        path = self.ts_path

        def _cleanup():
            if rec:
                rec.join(timeout=5)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    _log("TS: Datei geloescht: %s" % path, xbmc.LOGDEBUG)
                except Exception as e:
                    _log("TS: Loeschfehler: %s" % e, xbmc.LOGWARNING)

        threading.Thread(target=_cleanup, daemon=True, name="ts_cleanup").start()


def play_via_timeshift(channel_name, stream_url):
    global _ts_active
    with _ts_lock:
        if _ts_active is not None:
            _ts_active.stop()
        session    = _TsSession()
        _ts_active = session

    session.start(stream_url)
    _TsStopMonitor().activate()

    _notify("\u23fa Timeshift: Puffer wird aufgebaut\u2026")
    if not session.wait_for_buffer():
        _notify("Timeshift: Kein Puffer \u2014 Abbruch", error=True)
        with _ts_lock:
            if _ts_active is session:
                _ts_active = None
        session.stop()
        return False

    session.play(channel_name)
    return True


def _ts_stop_session():
    global _ts_active
    with _ts_lock:
        s          = _ts_active
        _ts_active = None
    if s:
        s.stop()


def play_stream(channel_url, channel_id):
    sig = _get_sig()
    if not sig:
        _notify("Kein Token", error=True)
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        return
    stream_url = None
    max_attempts = 3
    for attempt in range(max_attempts):
        stream_url = _resolve(channel_url, sig)
        if stream_url:
            break
        if attempt < max_attempts - 1:
            xbmc.sleep(2000)
    if not stream_url:
        _notify("Stream konnte nicht aufgeloest werden", error=True)
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        return

    if addon.getSetting("timeshift_auto") == "true":
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        ch = next((c for c in _get_catalog() if c["id"] == channel_id), None)
        channel_name = ch["name"] if ch else channel_url
        play_via_timeshift(channel_name, stream_url)
        return

    li = xbmcgui.ListItem(path=stream_url)
    li.setMimeType("application/x-mpegURL")
    li.setContentLookup(False)
    li.setProperty("inputstream",                                "inputstream.adaptive")
    li.setProperty("inputstream.adaptive.manifest_type",         "hls")
    li.setProperty("inputstream.adaptive.stream_headers",        "verifypeer=false")
    li.setProperty("inputstream.adaptive.manifest_headers",      "verifypeer=false")
    li.setProperty("inputstream.adaptive.license_flags",         "persistent_storage")
    xbmcplugin.setResolvedUrl(addon_handle, True, listitem=li)

def _resolve_for_action(channel_url):
    sig = _get_sig()
    if not sig:
        _notify("Kein Token", error=True)
        return None
    for attempt in range(3):
        url = _resolve(channel_url, sig)
        if url:
            return url
        xbmc.sleep(2000)
    _notify("Stream konnte nicht aufgeloest werden", error=True)
    return None

def action_download_start(channel_url, channel_name):
    ch = {"name": channel_name, "url": channel_url, "id": ""}
    stream_url = _resolve_for_action(channel_url)
    if not stream_url:
        return
    start_download(ch, stream_url)

def action_timeshift_play(channel_url, channel_name):
    stream_url = _resolve_for_action(channel_url)
    if not stream_url:
        return
    play_via_timeshift(channel_name, stream_url)

params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
mode   = params.get("mode", "")

if   mode == "list_channels":   list_channels(params.get("group", ""))
elif mode == "list_favs":        list_favs()
elif mode == "search":           do_search(params.get("query"))
elif mode == "play":             play_stream(params.get("channel_url", ""), params.get("channel_id", ""))
elif mode == "fav_add":          _add_fav(next((c for c in _get_catalog() if c["id"] == params.get("id", "")), {}))
elif mode == "fav_remove":       _remove_fav(params.get("id", ""))
elif mode == "fav_rename":       _rename_fav(params.get("id", ""))
elif mode == "fav_move":         _move_fav(params.get("id", ""), params.get("dir", "up"))
elif mode == "ctry_move":        _move_country(params.get("country", ""), params.get("dir", "up"))
elif mode == "settings":
    addon.openSettings()
    xbmcplugin.endOfDirectory(addon_handle, succeeded=False, updateListing=False, cacheToDisc=False)
elif mode == "epg_refresh":      epg_refresh()
elif mode == "browse_export_path": browse_export_path()
elif mode == "export_m3u":      export_m3u()
elif mode == "ctry_reset":       _reset_order()
elif mode == "reload_catalog":   reload_catalog()
elif mode == "timeshift_play":   action_timeshift_play(params.get("channel_url", ""), params.get("channel_name", ""))
elif mode == "download_start":   action_download_start(params.get("channel_url", ""), params.get("channel_name", ""))
elif mode == "download_stop":    stop_download(params.get("rec_id", ""))
elif mode == "download_list":    list_downloads()
elif mode == "browse_rec_dir":   browse_rec_dir()
elif mode == "browse_ts_dir":    browse_ts_dir()
else:                            list_groups()
