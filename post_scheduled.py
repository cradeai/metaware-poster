#!/usr/bin/env python3
"""Scheduled poster for @metawareai — picks next from queue/ and posts via Graph API.

Runs unattended via GitHub Actions cron. Logs every run to logs/.
Uses Instagram Login flow (graph.instagram.com) — no FB Page required.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
QUEUE = f"{BASE}/queue"
POSTED = f"{BASE}/posted"
FAILED = f"{BASE}/failed"
LOGS = f"{BASE}/logs"
ENV_FILE = f"{BASE}/.env"
BRAND = "metaware"

for d in (POSTED, FAILED, LOGS):
    os.makedirs(d, exist_ok=True)


def log(msg):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    logfile = f"{LOGS}/{datetime.date.today()}.log"
    with open(logfile, "a") as f:
        f.write(line + "\n")


def load_env():
    if not os.path.exists(ENV_FILE):
        return  # GitHub Actions injects env via secrets
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


def api(method, path, params):
    base = "https://graph.instagram.com/v21.0"
    if method == "POST":
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(f"{base}/{path}", data=data, method="POST")
    else:
        qs = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{base}/{path}?{qs}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code}: {body}")


def upload_catbox(path):
    """Upload to catbox.moe (200MB limit, persistent files)."""
    r = subprocess.run(
        ["curl", "-sS",
         "-F", "reqtype=fileupload",
         "-F", f"fileToUpload=@{path}",
         "https://catbox.moe/user/api.php"],
        capture_output=True, text=True, timeout=300,
    )
    url = r.stdout.strip()
    if not url.startswith("https://files.catbox.moe/"):
        raise RuntimeError(f"catbox upload failed: {r.stdout}")
    return url


def get_video_url(name):
    """Pick a public URL for IG to fetch from.
    - In GitHub Actions: use raw.githubusercontent.com (file already in repo,
      catbox blocks cloud IPs anyway).
    - Locally: upload to catbox.moe.
    """
    repo = os.environ.get("GITHUB_REPOSITORY")
    sha = os.environ.get("GITHUB_SHA")
    if repo and sha:
        return f"https://raw.githubusercontent.com/{repo}/{sha}/queue/{name}.mp4"
    return upload_catbox(f"{QUEUE}/{name}.mp4")


def pick_next_from_queue():
    """Pick earliest queue item by numeric N (metaware1 before metaware2 before metaware10)."""
    pattern = re.compile(rf"^{BRAND}(\d+)\.mp4$")
    def sort_key(fn):
        m = pattern.match(fn)
        return (0, int(m.group(1))) if m else (1, fn)
    items = sorted(
        (f for f in os.listdir(QUEUE) if f.endswith(".mp4")),
        key=sort_key,
    )
    if not items:
        return None
    name = items[0][:-4]
    if not os.path.exists(f"{QUEUE}/{name}.txt"):
        return None
    return name


def post_one():
    load_env()
    token = os.environ.get("METAWARE_INSTAGRAM_ACCESS_TOKEN")
    user_id = os.environ.get("METAWARE_INSTAGRAM_USER_ID")
    if not token or not user_id:
        raise RuntimeError("Missing METAWARE_INSTAGRAM_ACCESS_TOKEN or METAWARE_INSTAGRAM_USER_ID")
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    if dry_run:
        log("DRY_RUN=1 — will skip media_publish and queue→posted move")

    name = pick_next_from_queue()
    if not name:
        log("queue empty — skipping this slot")
        return

    mp4 = f"{QUEUE}/{name}.mp4"
    txt = f"{QUEUE}/{name}.txt"
    json_meta = f"{QUEUE}/{name}.json"
    with open(txt) as f:
        caption = f.read().strip()

    log(f"picked {name} ({os.path.getsize(mp4)//1024} KB)")
    video_url = get_video_url(name)
    log(f"video URL: {video_url}")

    log("creating container...")
    container = api("POST", f"{user_id}/media", {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": token,
    })
    cid = container["id"]
    log(f"container {cid} created — polling...")

    for i in range(90):
        status = api("GET", cid, {"fields": "status_code", "access_token": token})
        code = status.get("status_code", "?")
        if i % 3 == 0:
            log(f"  poll {i}: {code}")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"container error: {status}")
        time.sleep(5)
    else:
        raise RuntimeError("container did not finish in time")

    if dry_run:
        log(f"DRY_RUN: container {cid} ready — leaving {name} in queue/")
        return

    log("publishing...")
    result = api("POST", f"{user_id}/media_publish", {
        "creation_id": cid, "access_token": token,
    })
    media_id = result["id"]
    log(f"published: media_id={media_id}")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    shutil.move(mp4, f"{POSTED}/{stamp}_{name}.mp4")
    shutil.move(txt, f"{POSTED}/{stamp}_{name}.txt")
    if os.path.exists(json_meta):
        with open(json_meta) as f:
            meta = json.load(f)
        meta["media_id"] = media_id
        meta["posted_at"] = datetime.datetime.now().isoformat()
        with open(f"{POSTED}/{stamp}_{name}.json", "w") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        os.remove(json_meta)
    log(f"archived to posted/{stamp}_{name}.*")


if __name__ == "__main__":
    try:
        post_one()
    except Exception as e:
        log(f"FAILED: {e}")
        if os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"):
            log("DRY_RUN: leaving queue intact")
            sys.exit(1)
        # Move offending queue items to failed/ for inspection
        name = pick_next_from_queue()
        if name:
            try:
                stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
                for ext in (".mp4", ".txt", ".json"):
                    src = f"{QUEUE}/{name}{ext}"
                    if os.path.exists(src):
                        shutil.move(src, f"{FAILED}/{stamp}_{name}{ext}")
                log(f"moved failed item to failed/{stamp}_{name}.*")
            except Exception as e2:
                log(f"could not move failed item: {e2}")
        sys.exit(1)
