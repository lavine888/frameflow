#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
《熊酒馆·断航》90秒舰战 —— 批量生成 24 个镜头。

数据源：包内 分镜数据.json（25fps / 90s / 2250帧 / B01–B24）
首帧：  分镜/单格/Kxx.png（只有 677x356 左右）→ 中心裁成 16:9 → 放大到 1280x720
模型：  MiniMax-H3（支持 4–15s 任意整数时长，24fps，带原生音频）

  python tools/duanhang.py --prep-only                 # 只做首帧预处理
  python tools/duanhang.py --only B01                  # 试一条
  python tools/duanhang.py --all --parallel 4
  python tools/duanhang.py --all --parallel 4 --force   # 重跑

产物：包内 renders/B01.mp4 … B23.mp4（B24 是片名卡，不用生成）
断点续跑：runs/duanhang/submitted.json
"""
import argparse
import base64
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image, ImageFilter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
API = os.getenv("FRAMEFLOW_API", "http://127.0.0.1:8787")

PKG = Path(
    r"D:/电脑管家迁移文件/xwechat_files/wxid_x7gcga7y4u3b22_ce72/msg/file/2026-09/熊酒馆_断航_分镜与MD说明_v2.0"
)
WORK = ROOT / "runs" / "duanhang"
STATE = WORK / "submitted.json"
FIRST_DIR = WORK / "first"

MODEL = "MiniMax-H3"
RESOLUTION = "2K"
FIRST_W, FIRST_H = 1280, 720
MIN_DUR, MAX_DUR = 4, 15

STYLE = (
    "Cinematic hard-surface 3D space combat, giant ship scale, directional hard light, "
    "controlled bloom, rich dark surfaces, subtle film grain. 熊酒馆 industrial cyberpunk material language: "
    "layered black chrome armor, pale ceramic scales on a black titanium skeleton, smoked cyan optical glass, "
    "a few warm copper repair plates, small amber habitation windows. "
    "Ships are original functional spacecraft, not bear shaped, no bear ears, no giant signage. "
    "Debris keeps floating inertia; projectiles show short jets and particle trails only, "
    "never atmospheric wing lift, rain or long white smoke columns. "
    "No text, no subtitles, no watermark, no logo, no people."
)

CONTINUITY = (
    "Friendly escort ships (black chrome, cyan lights) face and fire to the RIGHT of frame; "
    "the opposing white-ceramic capital ship (red lights) faces and fires to the LEFT. "
    "Keep the exact same ship design, materials and lighting as the first frame."
)


# --------------------------------------------------------------------------- #
def load_shots():
    d = json.loads((PKG / "分镜数据.json").read_text(encoding="utf-8"))
    return d, {s["id"]: s for s in d["shots"]}


def gen_seconds(shot):
    """向上取整到整秒，夹在模型支持的 4–15s。"""
    return max(MIN_DUR, min(MAX_DUR, math.ceil(shot["duration"])))


def build_prompt(shot):
    return (
        f"{shot['title']}。{shot['action']}\n\n"
        f"Camera: {shot['camera']}\n\n"
        f"{CONTINUITY}\n\n{STYLE}"
    )


def prep_first_frame(shot):
    """Kxx.png → 中心裁成 16:9 → 1280x720（轻微锐化，不加新内容）。"""
    out = FIRST_DIR / f"{shot['id']}.png"
    src = PKG / shot["image"]
    im = Image.open(src).convert("RGB")
    w, h = im.size
    target_ar = FIRST_W / FIRST_H
    if w / h > target_ar:                      # 太宽 → 裁两侧
        nw = round(h * target_ar)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:                                      # 太高 → 裁上下
        nh = round(w / target_ar)
        im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    im = im.resize((FIRST_W, FIRST_H), Image.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def to_data_url(p, width=FIRST_W):
    im = Image.open(p).convert("RGB")
    if width and im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    import io as _io

    buf = _io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def log(msg=""):
    print(msg, flush=True)


def _req(method, url, tries=6, **kw):
    last = None
    for i in range(tries):
        try:
            return requests.request(method, url, timeout=kw.pop("timeout", 180), **kw)
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def submit(shot, duration):
    body = {
        "model": MODEL,
        "prompt": build_prompt(shot),
        "images": [to_data_url(FIRST_DIR / f"{shot['id']}.png")],
        "duration": duration,
        "resolution": RESOLUTION,
    }
    r = _req("POST", f"{API}/api/video", json=body, timeout=300)
    if r.status_code >= 400:
        raise RuntimeError(r.text[:300])
    return r.json()["task_id"]


def poll(task_id, timeout, tag=""):
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        time.sleep(12)
        d = _req("GET", f"{API}/api/tasks/{task_id}", timeout=60).json()
        st = d.get("status")
        line = f"{st} {d.get('progress')}"
        if line != last:
            log(f"    [{tag}] {line}   [{int(time.time() - t0)}s]")
            last = line
        if st in ("completed", "succeeded"):
            return d
        if st in ("failed", "error"):
            raise RuntimeError(f"任务失败: {json.dumps(d, ensure_ascii=False)[:400]}")
    raise TimeoutError(f"轮询超时 {timeout}s")


def download(url, dest):
    r = _req("GET", url, timeout=900)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return len(r.content)


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def run_shot(sid, shot, args):
    dest = PKG / args.out_dir / f"{sid}.mp4"
    dur = gen_seconds(shot)
    if dest.exists() and not args.force:
        log(f"[{sid}] {shot['title']} — 已存在（{dest.stat().st_size // 1024}KB）跳过")
        return sid, "skipped", str(dest)
    log(f"[{sid}] {shot['title']}  镜长{shot['duration']:.2f}s → 生成{dur}s  {shot['timecode']}")
    try:
        tid = submit(shot, dur)
        log(f"[{sid}] task_id={tid}")
        st = load_state()
        st[sid] = {"task_id": tid, "model": MODEL, "duration": dur,
                   "resolution": RESOLUTION, "at": time.strftime("%F %T")}
        save_state(st)
        d = poll(tid, args.timeout, tag=sid)
        url = d.get("result_url") or (d.get("output") or {}).get("url")
        if not url:
            raise RuntimeError(f"无 result_url: {json.dumps(d, ensure_ascii=False)[:300]}")
        n = download(url, dest)
        log(f"[{sid}] ✅ {dest.name}  {n // 1024}KB")
        return sid, "ok", str(dest)
    except Exception as e:  # noqa: BLE001
        log(f"[{sid}] ❌ {e}")
        return sid, "failed", str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--out-dir", default="renders")
    ap.add_argument("--prep-only", action="store_true")
    a = ap.parse_args()

    data, shots = load_shots()
    log(f"《{data['title']}》 {data['fps']}fps / {data['duration']}s / {data['frames']}帧 / {len(shots)} 镜")

    for s in shots.values():
        prep_first_frame(s)
    log(f"首帧预处理完成 → {FIRST_DIR}（{FIRST_W}x{FIRST_H}，16:9 中心裁切）")
    if a.prep_only:
        return

    todo = [k for k in shots if k != "B24"] if a.all else a.only
    if not todo:
        ap.error("用 --only B01 ... 或 --all 指定镜头")
    log(f"模型={MODEL} 分辨率={RESOLUTION} 并发={a.parallel} 共 {len(todo)} 镜")
    log()

    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        futs = {ex.submit(run_shot, k, shots[k], a): k for k in todo}
        for f in as_completed(futs):
            rows.append(f.result())

    log()
    log("=" * 74)
    ok = [r for r in rows if r[1] == "ok"]
    sk = [r for r in rows if r[1] == "skipped"]
    bad = [r for r in rows if r[1] == "failed"]
    for sid, st, info in sorted(rows):
        log(f"  {st:<8} {sid:<5} {info}")
    log(f"成功 {len(ok)}  跳过 {len(sk)}  失败 {len(bad)}   耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
