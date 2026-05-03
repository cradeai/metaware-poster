#!/usr/bin/env python3
"""Render single metaware reel using unified standard style.

Reads queue/<stem>.json metadata (new_body_text with **bold** markers,
new_caption), source video from downloads/, applies metaware-standard
overlay (vt instagram/general/standard_style.md), outputs queue/<stem>.mp4
+ queue/<stem>.txt (caption).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

DOWNLOAD_DIR = "/Users/predator/metaware/downloads"
QUEUE_DIR = "/Users/predator/metaware/queue"
POSTED_DIR = "/Users/predator/metaware/posted"
LOGO_PATH = "/Users/predator/Downloads/metaware_logo.png"
BRAND = "metaware"

# Unified standard (1080x1920 canvas) — vt general/standard_style.md
CANVAS_W = 1080
CANVAS_H = 1920
VID_Y = 665             # body descender bottom ~y=640 + 25px standard gap
VIDEO_AREA_H = CANVAS_H - VID_Y  # = 1255
# @evolving.ai source brand block ends at y=660 in 1080x1920 source
SRC_BRAND_END = 660

LOGO_SIZE = 110
LOGO_X = 63
LOGO_Y = 395
TITLE_X = 180
TITLE_Y = 411
TITLE_FONT_SIZE = 43
HANDLE_X = 180
HANDLE_Y = 460
HANDLE_FONT_SIZE = 38

BODY_X = 59
BODY_Y1 = 534
BODY_Y2 = 587
BODY_FONT_SIZE = 43

WHITE = (255, 255, 255)
HELVETICA = "/System/Library/Fonts/Helvetica.ttc"


def load_logo_white(size):
    """Load metaware_logo.png (black bg + white M) → RGBA with alpha=brightness."""
    img = Image.open(LOGO_PATH).convert("RGB").resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    op = out.load()
    for y in range(size):
        for x in range(size):
            r, g, b = px[x, y]
            v = max(r, g, b)
            if v > 80:
                op[x, y] = (255, 255, 255, v)
    return out


def parse_bold(text):
    """Parse **bold** markers into list of (chunk, bold_bool) segments."""
    parts = re.split(r'(\*\*[^*]+\*\*)', text)
    segs = []
    for p in parts:
        if not p:
            continue
        if p.startswith('**') and p.endswith('**'):
            segs.append((p[2:-2], True))
        else:
            segs.append((p, False))
    return segs


def wrap_segments(text, max_width_px=950):
    """Word-wrap text with **bold** markers into max 2 rows of (chunk, bold)."""
    segs = parse_bold(text)
    fnt_reg = ImageFont.truetype(HELVETICA, BODY_FONT_SIZE, index=0)
    fnt_bold = ImageFont.truetype(HELVETICA, BODY_FONT_SIZE, index=1)
    tokens = []
    for txt, b in segs:
        # Capture leading whitespace too — preserves space at segment boundaries
        for m in re.finditer(r'\s*\S+\s*', txt):
            tokens.append((m.group(), b))
    rows = []
    cur = []
    cur_w = 0
    for w, b in tokens:
        f = fnt_bold if b else fnt_reg
        ww = f.getlength(w)
        if cur_w + ww <= max_width_px or not cur:
            cur.append((w, b))
            cur_w += ww
        else:
            rows.append(cur)
            cur = [(w, b)]
            cur_w = ww
    if cur:
        rows.append(cur)
    if len(rows) > 2:
        rows = [rows[0], [t for r in rows[1:] for t in r]]
    rows = [[(t.rstrip() if i == len(r) - 1 else t, b) for i, (t, b) in enumerate(r)] for r in rows]
    merged = []
    for r in rows:
        m = []
        for t, b in r:
            if m and m[-1][1] == b:
                m[-1] = (m[-1][0] + t, b)
            else:
                m.append((t, b))
        merged.append(m)
    return merged


def build_overlay(body_lines):
    canvas = Image.new("RGB", (CANVAS_W, VID_Y), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Logo ring
    draw.ellipse(
        [LOGO_X, LOGO_Y, LOGO_X + LOGO_SIZE, LOGO_Y + LOGO_SIZE],
        fill=(0, 0, 0), outline=(90, 90, 90), width=2,
    )
    # M logo at 80% (per-brand erand metaware'ile)
    m_size = int(LOGO_SIZE * 0.80)
    m_logo = load_logo_white(m_size)
    bb = m_logo.getbbox()
    if bb:
        m_logo = m_logo.crop(bb)
    mx = LOGO_X + (LOGO_SIZE - m_logo.width) // 2
    my = LOGO_Y + (LOGO_SIZE - m_logo.height) // 2
    canvas.paste(m_logo, (mx, my), m_logo)

    # Title
    fnt_title = ImageFont.truetype(
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf", TITLE_FONT_SIZE,
    )
    draw.text((TITLE_X, TITLE_Y), "Metaware", fill=WHITE, font=fnt_title)

    # Verified ✓
    title_bbox = draw.textbbox((TITLE_X, TITLE_Y), "Metaware", font=fnt_title)
    br = int(TITLE_FONT_SIZE * 0.4)
    bx = title_bbox[2] + int(TITLE_FONT_SIZE * 0.25)
    by = TITLE_Y + int((TITLE_FONT_SIZE - br * 2) / 2) + 4
    draw.ellipse([bx, by, bx + br * 2, by + br * 2], fill=(29, 155, 240))
    cx, cy = bx + br, by + br
    chk = int(br * 0.45)
    draw.line(
        [(cx - chk, cy), (cx - 1, cy + chk), (cx + chk + 1, cy - chk - 1)],
        fill=WHITE, width=max(2, int(br / 5)),
    )

    # Handle
    fnt_handle = ImageFont.truetype(HELVETICA, HANDLE_FONT_SIZE, index=0)
    draw.text((HANDLE_X, HANDLE_Y), "@metawareai", fill=(170, 170, 170), font=fnt_handle)

    # Body
    fnt_reg = ImageFont.truetype(HELVETICA, BODY_FONT_SIZE, index=0)
    fnt_bold = ImageFont.truetype(HELVETICA, BODY_FONT_SIZE, index=1)
    for row_idx, row in enumerate(body_lines[:2]):
        y = BODY_Y1 if row_idx == 0 else BODY_Y2
        cx = BODY_X
        for text, is_bold in row:
            f = fnt_bold if is_bold else fnt_reg
            draw.text((cx, y), text, fill=WHITE, font=f)
            cx += f.getlength(text)

    return canvas


def detect_content_bbox(src):
    """Run cropdetect on source after excluding source's own brand block.
    Returns (x, y, w, h) of actual video content within sub-frame
    (sub-frame = source minus brand block area). Returns None if detection fails.
    """
    sub_h = CANVAS_H - SRC_BRAND_END  # = 1260
    r = subprocess.run(
        ["ffmpeg", "-ss", "1", "-t", "1", "-i", src,
         "-vf", f"crop=1080:{sub_h}:0:{SRC_BRAND_END},cropdetect=24:2:0",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=30,
    )
    matches = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', r.stderr)
    if not matches:
        return None
    w, h, x, y = (int(v) for v in matches[-1])
    return x, y, w, h


def build_filter(crop_info):
    """Build ffmpeg filter chain that ensures video is edge-to-edge horizontally
    (full 1080 width) and placed below brand overlay. Vertical black padding
    bottom is OK if source content is short."""
    sub_h = CANVAS_H - SRC_BRAND_END
    if crop_info is None:
        # Fallback: no cropdetect → assume already edge-to-edge, just scale
        return "[0:v]scale=1080:1920:flags=lanczos[bg];[bg][1:v]overlay=0:0[out]"
    x, y, w, h = crop_info
    # Scale content to 1080 wide preserving aspect
    new_h = round(h * CANVAS_W / w)
    chain = (
        f"[0:v]crop=1080:{sub_h}:0:{SRC_BRAND_END},"   # exclude source brand
        f"crop={w}:{h}:{x}:{y},"                        # tight crop to content
        f"scale=1080:{new_h}:flags=lanczos,"            # scale to full width
    )
    if new_h > VIDEO_AREA_H:
        # Content too tall — crop top+bottom equally to fit video area
        cy = (new_h - VIDEO_AREA_H) // 2
        chain += f"crop=1080:{VIDEO_AREA_H}:0:{cy},"
    chain += f"pad=1080:{CANVAS_H}:0:{VID_Y}:black[bg];"
    chain += "[bg][1:v]overlay=0:0[out]"
    return chain


def next_queue_n():
    """Find next sequential N for this brand across queue + posted."""
    import re
    pattern = re.compile(rf"^{BRAND}(\d+)\.")
    nums = []
    for d in (QUEUE_DIR, POSTED_DIR):
        if not os.path.exists(d):
            continue
        for fn in os.listdir(d):
            m = pattern.match(fn)
            if m:
                nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def render(arg):
    """Render reel. arg can be:
    - IG shortcode (e.g. DXoe6VSk6yo) → load JSON by source_shortcode field, assign next queue N
    - Existing queue name (e.g. metaware26) → re-render that queue item
    """
    # Try queue-name match first
    direct_meta = f"{QUEUE_DIR}/{arg}.json"
    if os.path.exists(direct_meta) and arg.startswith(BRAND):
        meta_path = direct_meta
        stem = arg
    else:
        # Treat arg as shortcode → look up by source_shortcode in queue JSONs
        meta_path = None
        for fn in os.listdir(QUEUE_DIR):
            if fn.endswith(".json"):
                m = json.load(open(f"{QUEUE_DIR}/{fn}"))
                if m.get("source_shortcode") == arg:
                    meta_path = f"{QUEUE_DIR}/{fn}"
                    stem = fn[:-5]
                    break
        if meta_path is None:
            # Brand-new entry: arg is shortcode without prepared JSON
            print(f"[error] no queue JSON found with source_shortcode={arg}; "
                  f"prepare metadata first", file=sys.stderr)
            sys.exit(1)

    with open(meta_path) as f:
        meta = json.load(f)
    shortcode = meta.get("source_shortcode") or arg
    source_account = meta.get("source_account", "evolving.ai")
    src = f"{DOWNLOAD_DIR}/{source_account}_{shortcode}.mp4"
    if not os.path.exists(src):
        print(f"[error] source not found: {src}", file=sys.stderr)
        sys.exit(1)
    body_text = meta.get("new_body_text", "")
    caption = meta.get("new_caption", "")

    body_lines = wrap_segments(body_text)

    os.makedirs(QUEUE_DIR, exist_ok=True)
    overlay_path = f"{QUEUE_DIR}/{stem}_overlay.png"
    out_mp4 = f"{QUEUE_DIR}/{stem}.mp4"
    out_txt = f"{QUEUE_DIR}/{stem}.txt"

    overlay = build_overlay(body_lines)
    overlay.save(overlay_path)
    print(f"[overlay] {overlay_path}", flush=True)

    # Auto-detect content bbox and build edge-to-edge filter
    crop_info = detect_content_bbox(src)
    if crop_info:
        x, y, w, h = crop_info
        print(f"[crop] content bbox in sub-frame: x={x} y={y} w={w} h={h}", flush=True)
    else:
        print("[crop] cropdetect failed — fallback to plain scale", flush=True)
    fc = build_filter(crop_info)

    # IG Reels max duration is 90s — trim source if longer
    src_dur = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", src,
    ]).decode().strip())
    out_dur = min(src_dur, 90.0)
    trimmed = out_dur < src_dur
    # IG content publishing has undocumented ~7MB fetch limit (despite 1GB
    # officially allowed). Compute target video bitrate from out_dur to
    # produce ~5MB output regardless of clip length.
    target_kb = 5 * 1024  # ~5 MB
    audio_kbps = 96
    video_kbps = max(500, int(target_kb * 8 / out_dur) - audio_kbps)
    cmd = ["ffmpeg", "-y", "-i", src, "-i", overlay_path]
    if trimmed:
        cmd += ["-t", "90"]
    cmd += [
        "-filter_complex", fc,
        "-map", "[out]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium",
        "-b:v", f"{video_kbps}k", "-maxrate", f"{int(video_kbps*1.2)}k",
        "-bufsize", f"{video_kbps*2}k",
        "-c:a", "aac", "-b:a", f"{audio_kbps}k",
        "-movflags", "+faststart",
        out_mp4,
    ]
    trim_note = f" (trimmed from {src_dur:.0f}s)" if trimmed else ""
    print(f"[render] {out_dur:.0f}s{trim_note}, {video_kbps}k video", flush=True)
    print(f"[render] ffmpeg...", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[error] ffmpeg failed:\n{r.stderr[-800:]}", file=sys.stderr)
        sys.exit(2)
    print(f"[render] {out_mp4}", flush=True)

    with open(out_txt, "w") as f:
        f.write(caption)
    print(f"[caption] {out_txt}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("arg", help="IG shortcode (DXoe6VSk6yo) OR queue name (metaware26)")
    args = p.parse_args()
    render(args.arg)
