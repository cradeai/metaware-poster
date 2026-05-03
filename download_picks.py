#!/usr/bin/env python3
"""Download top picks from _top_picks.json via yt-dlp (anonymous, 1080p).
Saves <handle>_<shortcode>.mp4 + .txt (caption) to downloads/."""
import json
import os
import subprocess
import sys

DOWNLOAD_DIR = "/Users/predator/metaware/downloads"
HANDLE = "evolving.ai"
PICKS = f"{DOWNLOAD_DIR}/_top_picks.json"


def main():
    with open(PICKS) as f:
        d = json.load(f)
    picks = d["picks"]
    print(f"[start] downloading {len(picks)} picks from @{HANDLE}", flush=True)

    ok = 0
    failed = []
    for i, p in enumerate(picks, 1):
        sc = p["shortcode"]
        stem = f"{HANDLE}_{sc}"
        mp4 = f"{DOWNLOAD_DIR}/{stem}.mp4"
        txt = f"{DOWNLOAD_DIR}/{stem}.txt"
        if os.path.exists(mp4):
            print(f"[{i:>2}/{len(picks)}] {sc}: already downloaded, skip", flush=True)
            if not os.path.exists(txt):
                with open(txt, "w") as f:
                    f.write(p.get("caption", ""))
            ok += 1
            continue
        print(f"[{i:>2}/{len(picks)}] {sc}: downloading "
              f"({p['play_count']:,} views)...", flush=True)
        url = f"https://www.instagram.com/p/{sc}/"
        r = subprocess.run(
            ["yt-dlp", url, "-o", f"{DOWNLOAD_DIR}/{stem}.%(ext)s",
             "--no-playlist", "--quiet", "--no-warnings"],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0:
            print(f"   FAILED: {r.stderr[-200:].strip()}", flush=True)
            failed.append(sc)
            continue
        if not os.path.exists(mp4):
            print(f"   FAILED: yt-dlp ran but {mp4} not found", flush=True)
            failed.append(sc)
            continue
        with open(txt, "w") as f:
            f.write(p.get("caption", ""))
        ok += 1

    print(f"\n[done] OK={ok} failed={len(failed)}", flush=True)
    if failed:
        print(f"[failed] {failed}", flush=True)


if __name__ == "__main__":
    main()
