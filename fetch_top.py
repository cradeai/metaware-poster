#!/usr/bin/env python3
"""Login as @metawareai via IG web flow, fetch top-N most-viewed
@evolving.ai reels from last D days using paginated /api/v1/feed/user/."""
import datetime
import json
import os
import sys
import time

import requests

USERNAME = "metawareai"
TARGET = "evolving.ai"
DAYS = 30
N = 30
APP_ID = "936619743392459"
DOWNLOAD_DIR = "/Users/predator/metaware/downloads"
SESSION_FILE = "/Users/predator/metaware/sessions/web.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.instagram.com",
        "Referer": "https://www.instagram.com/",
        "X-IG-App-ID": APP_ID,
    })
    return s


def login(s, password):
    # 1. Hit homepage to get csrftoken cookie
    s.get("https://www.instagram.com/", timeout=30)
    csrf = s.cookies.get("csrftoken")
    if not csrf:
        raise RuntimeError("no csrftoken cookie after homepage GET")

    # 2. POST login
    ts = int(time.time())
    enc_pwd = f"#PWD_INSTAGRAM_BROWSER:0:{ts}:{password}"
    headers = {
        "X-CSRFToken": csrf,
        "X-Requested-With": "XMLHttpRequest",
        "X-Instagram-AJAX": "1",
        "Referer": "https://www.instagram.com/accounts/login/",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "username": USERNAME,
        "enc_password": enc_pwd,
        "queryParams": "{}",
        "optIntoOneTap": "false",
        "trustedDeviceRecords": "{}",
    }
    r = s.post(
        "https://www.instagram.com/api/v1/web/accounts/login/ajax/",
        headers=headers, data=data, timeout=30,
    )
    print(f"[login] http={r.status_code}", flush=True)
    try:
        j = r.json()
    except Exception:
        print(f"[login] non-json response: {r.text[:300]}", flush=True)
        raise
    if not j.get("authenticated"):
        print(f"[login] FAILED: {j}", flush=True)
        raise RuntimeError(f"login not authenticated: {j}")
    if "sessionid" not in s.cookies.get_dict():
        raise RuntimeError("login claimed authenticated but no sessionid cookie")
    print(f"[login] OK: user_id={j.get('userId')}", flush=True)
    return s


def save_cookies(s):
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    cookies = {c.name: c.value for c in s.cookies}
    with open(SESSION_FILE, "w") as f:
        json.dump(cookies, f)
    os.chmod(SESSION_FILE, 0o600)


def load_cookies(s):
    if not os.path.exists(SESSION_FILE):
        return False
    with open(SESSION_FILE) as f:
        cookies = json.load(f)
    for k, v in cookies.items():
        s.cookies.set(k, v, domain=".instagram.com")
    return "sessionid" in cookies


def get_user_id(s, handle):
    r = s.get(
        f"https://www.instagram.com/api/v1/users/web_profile_info/?username={handle}",
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"web_profile_info http={r.status_code} body={r.text[:300]}")
    return r.json()["data"]["user"]["id"]


def fetch_feed(s, user_id, max_pages=20, sleep_s=2.0):
    """Paginated user feed via private API. Returns list of items."""
    items = []
    max_id = None
    for page in range(max_pages):
        params = {"count": 12}
        if max_id:
            params["max_id"] = max_id
        r = s.get(
            f"https://www.instagram.com/api/v1/feed/user/{user_id}/",
            params=params, timeout=30,
        )
        if r.status_code != 200:
            print(f"[feed] page {page+1} http={r.status_code} body={r.text[:200]}", flush=True)
            break
        j = r.json()
        page_items = j.get("items", [])
        items.extend(page_items)
        print(f"[feed] page {page+1}: {len(page_items)} items (total={len(items)})", flush=True)
        if not j.get("more_available") or not j.get("next_max_id"):
            break
        max_id = j["next_max_id"]
        time.sleep(sleep_s)
    return items


def main():
    pwd = os.environ.get("IG_PWD")
    s = make_session()

    # Try cookie reuse first
    if load_cookies(s):
        # Test session still valid
        r = s.get("https://www.instagram.com/api/v1/accounts/edit/web_form_data/", timeout=30)
        if r.status_code == 200:
            print("[session] reusing saved cookies", flush=True)
        else:
            print(f"[session] saved cookies stale (http={r.status_code}), re-logging in", flush=True)
            s = make_session()
            if not pwd:
                print("[error] need IG_PWD env var to re-login", file=sys.stderr)
                sys.exit(1)
            login(s, pwd)
            save_cookies(s)
    else:
        if not pwd:
            print("[error] no saved session and no IG_PWD env var", file=sys.stderr)
            sys.exit(1)
        login(s, pwd)
        save_cookies(s)

    print(f"[lookup] user_id for @{TARGET}...", flush=True)
    user_id = get_user_id(s, TARGET)
    print(f"[ok] user_id={user_id}", flush=True)

    # ~30 days, ~96 posts max via 8 pages should be plenty
    items = fetch_feed(s, user_id, max_pages=12, sleep_s=2.5)
    print(f"[feed] total fetched: {len(items)}", flush=True)

    cutoff = datetime.datetime.now().timestamp() - DAYS * 86400
    videos = []
    for it in items:
        if not it.get("video_versions"):
            continue
        if it.get("taken_at", 0) < cutoff:
            continue
        videos.append({
            "shortcode": it["code"],
            "play_count": it.get("play_count", 0),
            "like_count": it.get("like_count", 0),
            "comment_count": it.get("comment_count", 0),
            "taken_at": it["taken_at"],
            "date": datetime.datetime.fromtimestamp(it["taken_at"]).date().isoformat(),
            "caption": (it.get("caption") or {}).get("text", "") if it.get("caption") else "",
        })

    print(f"[filter] {len(videos)} video posts in last {DAYS}d", flush=True)
    videos.sort(key=lambda v: -v["play_count"])
    top = videos[:N]

    print(f"\n=== TOP {len(top)} BY VIEWS ===")
    for v in top:
        print(f"  {v['shortcode']:15s}  views={v['play_count']:>10,}  "
              f"likes={v['like_count']:>7,}  {v['date']}")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    out = f"{DOWNLOAD_DIR}/_top_picks.json"
    with open(out, "w") as f:
        json.dump({
            "target": TARGET,
            "fetched_at": datetime.datetime.now().isoformat(),
            "days": DAYS,
            "n": N,
            "picks": top,
        }, f, indent=2)
    print(f"\n[saved] {out}", flush=True)


if __name__ == "__main__":
    main()
