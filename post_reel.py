#!/usr/bin/env python3
"""Post a metaware Reel via Instagram Graph API (Instagram Login flow).

Usage:
    post_reel.py <name>     # uses queue/<name>.mp4 + queue/<name>.txt (caption)

Reads /Users/predator/metaware/.env for METAWARE_INSTAGRAM_ACCESS_TOKEN and
METAWARE_INSTAGRAM_USER_ID. Uploads video to tmpfiles.org for IG to fetch,
creates REELS container, polls until FINISHED, publishes, archives queue → posted.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "/Users/predator/metaware"
QUEUE = f"{BASE}/queue"
POSTED = f"{BASE}/posted"
LOGS = f"{BASE}/logs"
ENV_FILE = f"{BASE}/.env"

for d in (POSTED, LOGS):
    os.makedirs(d, exist_ok=True)


def log(msg):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    with open(f"{LOGS}/{datetime.date.today()}.log", "a") as f:
        f.write(line + "\n")


def load_env():
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
    """Upload to catbox.moe — returns direct download URL.
    catbox supports up to 200MB and files are permanent (good for IG fetching)."""
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


def post_one(name):
    load_env()
    token = os.environ["METAWARE_INSTAGRAM_ACCESS_TOKEN"]
    user_id = os.environ["METAWARE_INSTAGRAM_USER_ID"]

    mp4 = f"{QUEUE}/{name}.mp4"
    txt = f"{QUEUE}/{name}.txt"
    if not os.path.exists(mp4):
        raise RuntimeError(f"missing {mp4}")
    if not os.path.exists(txt):
        raise RuntimeError(f"missing {txt}")
    with open(txt) as f:
        caption = f.read().strip()

    log(f"posting {name} ({os.path.getsize(mp4)//1024} KB) — uploading...")
    video_url = upload_catbox(mp4)
    log(f"upload OK: {video_url}")

    log("creating container...")
    container = api("POST", f"{user_id}/media", {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": token,
    })
    cid = container["id"]
    log(f"container {cid} — polling...")

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

    log("publishing...")
    result = api("POST", f"{user_id}/media_publish", {
        "creation_id": cid, "access_token": token,
    })
    media_id = result["id"]
    log(f"published: media_id={media_id}")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    json_src = f"{QUEUE}/{name}.json"
    shutil.move(mp4, f"{POSTED}/{stamp}_{name}.mp4")
    shutil.move(txt, f"{POSTED}/{stamp}_{name}.txt")
    if os.path.exists(json_src):
        shutil.move(json_src, f"{POSTED}/{stamp}_{name}.json")
    log(f"archived to posted/{stamp}_{name}.*")
    return media_id


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: post_reel.py <queue_name>   (e.g. metaware1)", file=sys.stderr)
        sys.exit(1)
    try:
        post_one(sys.argv[1])
    except Exception as e:
        log(f"FAILED: {e}")
        sys.exit(1)
