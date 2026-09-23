#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把《熊酒馆 · 前30秒外部算力包 v1.0》的 6 个图生视频任务，通过本地 FrameFlow 后端
(draw.openai-next.com 中转) 跑出来，结果落到 包/renders/Jxx.mp4。

用法（在 Workbench 根目录）：
  python tools/bear_tavern.py --list
  python tools/bear_tavern.py --jobs J02                       # 单条冒烟
  python tools/bear_tavern.py --all --parallel 5               # 全部，5 条并发
  python tools/bear_tavern.py --jobs J01 J03 --model veo3-frames-fast

模型说明：
  MiniMax-H3   —— 包作者本地验证用的同款模型（hailuo 通道，原生音频，最贴包）
  veo3-frames-fast / veo3 —— 画面质量高，但可能自己加配乐
  wan2.2-i2v-flash —— 便宜快，无原生音频

断点续跑：已存在 renders/Jxx.mp4 的任务默认跳过；提交记录存 runs/bear_tavern/submitted.json。
"""
import argparse
import base64
import io
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image
except ImportError:  # 没装 Pillow 就直传原图
    Image = None

PKG = Path(
    r"D:/电脑管家迁移文件/xwechat_files/wxid_x7gcga7y4u3b22_ce72/msg/file/2026-09/BearTavern_30s_v1.0"
)
API = "http://127.0.0.1:8787"
RUN_DIR = Path(__file__).resolve().parent.parent / "runs" / "bear_tavern"
STATE = RUN_DIR / "submitted.json"

DEFAULT_MODEL = "MiniMax-H3"
POLL_EVERY = 15
DONE = {"completed", "success", "succeeded", "done", "finished"}
FAIL = {"failed", "error", "canceled", "cancelled"}

_lock = threading.Lock()


def log(msg=""):
    with _lock:
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def _req(method, url, **kw):
    """上游偶发 SSL EOF / 连接重置，自动重试。"""
    last = None
    for i in range(5):
        try:
            return requests.request(method, url, **kw)
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def load_jobs():
    data = json.loads((PKG / "jobs.json").read_text(encoding="utf-8"))
    return {j["id"]: j for j in data["jobs"]}


def needed_seconds(jid):
    """从时间线算出该任务实际需要的素材长度（如 J01 需 0–5.5s）。"""
    tl = json.loads((PKG / "时间线_00-30.json").read_text(encoding="utf-8"))
    return max((s["source_in"] + s["duration"] for s in tl["shots"] if s.get("job_id") == jid), default=0.0)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def to_data_url(path: Path, max_width: int = 0) -> str:
    raw = path.read_bytes()
    if Image is not None and max_width and max_width > 0:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        if im.width > max_width:
            im = im.resize((max_width, round(im.height * max_width / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=95)
        raw = buf.getvalue()
        mime = "image/jpeg"
    else:
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def submit(job, model, duration, resolution, max_width):
    frame = PKG / job["first_frame"]
    body = {"model": model, "prompt": job["prompt"], "images": [to_data_url(frame, max_width)]}
    if duration:
        body["duration"] = duration
    if resolution:
        body["resolution"] = resolution
    r = _req("POST", f"{API}/api/video", json=body, timeout=300)
    if r.status_code >= 400:
        raise RuntimeError(f"提交失败 HTTP {r.status_code}: {r.text[:400]}")
    return r.json()


def poll(task_id, timeout, tag=""):
    t0 = time.time()
    last = None
    while True:
        d = _req("GET", f"{API}/api/tasks/{task_id}", timeout=60).json()
        st = str(d.get("status") or "").lower()
        prog = d.get("progress")
        line = f"{st or '?'} {prog if prog is not None else ''}".rstrip()
        if line != last:
            log(f"    [{tag}] {line}   [{time.time() - t0:.0f}s]")
            last = line
        if st in DONE:
            return d
        if st in FAIL:
            raise RuntimeError(f"任务失败: {json.dumps(d, ensure_ascii=False)[:400]}")
        if time.time() - t0 > timeout:
            raise TimeoutError(f"轮询超时 {timeout}s: {task_id}")
        time.sleep(POLL_EVERY)


def download(url, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _req("GET", url, stream=True, timeout=900) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return dest.stat().st_size


def run_job(jid, job, args):
    """返回 (jid, status, info)；status ∈ ok / skipped / failed"""
    dest = PKG / args.out_dir / f"{jid}.mp4"
    dur = args.durations.get(jid, args.duration) if args.durations else args.duration
    if dest.exists() and not args.force:
        log(f"[{jid}] {job['name']} — 已存在 {dest.name} ({dest.stat().st_size // 1024}KB)，跳过")
        return jid, "skipped", str(dest)

    log(f"[{jid}] {job['name']}  ({'+'.join(job['shots'])})  首帧={Path(job['first_frame']).name}  "
        f"时长={dur}s 需≥{needed_seconds(jid):.1f}s")
    try:
        res = submit(job, args.model, dur, args.resolution, args.max_width)
        tid = res["task_id"]
        log(f"[{jid}] task_id={tid}")
        state = load_state()
        state[jid] = {
            "task_id": tid, "model": args.model, "duration": dur,
            "resolution": args.resolution, "shots": job["shots"],
            "at": time.strftime("%F %T"),
        }
        save_state(state)

        d = poll(tid, args.timeout, tag=jid)
        url = d.get("result_url") or d.get("url") or (d.get("output") or {}).get("url")
        if not url:
            raise RuntimeError(f"完成但没有 result_url: {json.dumps(d, ensure_ascii=False)[:400]}")
        size = download(url, dest)
        log(f"[{jid}] ✅ {dest.name}  {size // 1024}KB")
        return jid, "ok", str(dest)
    except Exception as e:  # noqa: BLE001
        log(f"[{jid}] ❌ {e}")
        return jid, "failed", str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", nargs="*", default=[], help="要跑的任务号，如 J01 J02")
    ap.add_argument("--all", action="store_true", help="跑全部 6 条")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--duration", type=int, default=6, help="秒；0=不传，用平台默认")
    ap.add_argument("--resolution", default="768P", help="480P / 768P / 2K；空=不传")
    ap.add_argument("--out-dir", default="renders", help="结果写到包的哪个子目录")
    ap.add_argument("--duration-options", default="", help='模型只支持固定档位时，如 "5,10,15"，按镜头自动选')
    ap.add_argument("--max-width", type=int, default=1280, help="首帧压缩到该宽度（0=原图）")
    ap.add_argument("--timeout", type=int, default=3000, help="单条最长等待秒数")
    ap.add_argument("--parallel", type=int, default=1, help="并发条数")
    ap.add_argument("--force", action="store_true", help="已有结果也重跑")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    jobs = load_jobs()
    if args.list:
        log(f"{'任务':<5}{'镜头':<10}{'首帧':<26}{'帧/秒':<18}本地已验证")
        for jid, j in jobs.items():
            log(f"{jid:<5}{'+'.join(j['shots']):<10}{Path(j['first_frame']).name:<26}"
                f"{j['frames']}f/{j['seconds']:.2f}s{'':<6}{'是' if j['tested_locally'] else '否(新)'}")
        return 0

    todo = list(jobs) if args.all else args.jobs
    if not todo:
        ap.error("用 --jobs J01 ... 或 --all 指定任务")

    args.durations = {}
    if args.duration_options:
        opts = sorted(int(x) for x in args.duration_options.split(","))
        for jid in todo:
            need = needed_seconds(jid)
            pick = next((o for o in opts if o >= need), opts[-1])
            args.durations[jid] = pick

    log(f"模型={args.model}  时长={args.durations or (args.duration or '默认')}s  "
        f"分辨率={args.resolution or '默认'}  并发={args.parallel}  首帧宽={args.max_width or '原图'}")
    log(f"输出目录: {PKG / args.out_dir}")
    log()

    t0 = time.time()
    results, failed = [], []
    if args.parallel > 1:
        with ThreadPoolExecutor(max_workers=args.parallel) as ex:
            futs = {ex.submit(run_job, jid, jobs[jid], args): jid for jid in todo if jid in jobs}
            for f in as_completed(futs):
                jid, st, info = f.result()
                (results if st != "failed" else failed).append((jid, st, info))
    else:
        for jid in todo:
            if jid not in jobs:
                log(f"[{jid}] 跳过：jobs.json 里没有这个任务")
                continue
            jid, st, info = run_job(jid, jobs[jid], args)
            (results if st != "failed" else failed).append((jid, st, info))

    log()
    log("=" * 64)
    for jid, st, info in sorted(results):
        log(f"  {jid}  {st:<8} {Path(info).name}")
    for jid, err in failed:
        log(f"  {jid}  FAILED   {err[:140]}")
    log(f"总耗时 {time.time() - t0:.0f}s | 成功 {len([r for r in results if r[1] == 'ok'])}"
        f" 跳过 {len([r for r in results if r[1] == 'skipped'])} 失败 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
