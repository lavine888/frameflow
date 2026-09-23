#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
同一镜头、多模型对照跑（shootout）。用来挑"更好的模型"。

  python tools/shootout.py --job J03
  python tools/shootout.py --job J03 --specs "doubao-seedance-2-5-260628|1080P|5" "wan2.7-i2v|1080P|5"

输出到 runs/bear_tavern/shootout/<JOB>__<model>__<res>.mp4
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bear_tavern import (API, PKG, _req, download, load_jobs, poll, submit, log)  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "runs" / "bear_tavern" / "shootout"

DEFAULT_SPECS = [
    ("doubao-seedance-2-5-260628", "1080P", 5),
    ("wan2.7-i2v", "1080P", 5),
    ("MiniMax-H3", "2K", 6),
]


def shoot(job_id, model, resolution, duration, max_width):
    jobs = load_jobs()
    job = jobs[job_id]
    tag = f"{job_id}__{model}__{resolution}"
    log(f"[{tag}] 提交…")
    try:
        res = submit(job, model, duration, resolution, max_width)
        tid = res["task_id"]
        log(f"[{tag}] task_id={tid}")
        d = poll(tid, 2400, tag=tag)
        url = d.get("result_url") or d.get("url") or (d.get("output") or {}).get("url")
        if not url:
            raise RuntimeError(f"无 result_url: {json.dumps(d, ensure_ascii=False)[:300]}")
        dest = OUT / f"{tag}.mp4"
        size = download(url, dest)
        log(f"[{tag}] OK {size // 1024}KB -> {dest.name}")
        return tag, "ok", tid, str(dest), size
    except Exception as e:  # noqa: BLE001
        log(f"[{tag}] FAIL {e}")
        return tag, "failed", "", str(e), 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="J03")
    ap.add_argument("--specs", nargs="*", default=[], help='"model|resolution|duration"')
    ap.add_argument("--max-width", type=int, default=1280)
    ap.add_argument("--parallel", type=int, default=3)
    a = ap.parse_args()

    specs = DEFAULT_SPECS
    if a.specs:
        specs = []
        for s in a.specs:
            parts = (s.split("|") + ["1080P", "5"])[:3]
            specs.append((parts[0], parts[1], int(parts[2])))

    OUT.mkdir(parents=True, exist_ok=True)
    log(f"镜头 {a.job} | 对照 {len(specs)} 个模型 | 并发 {a.parallel}")
    log()
    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        futs = [ex.submit(shoot, a.job, m, r, d, a.max_width) for m, r, d in specs]
        for f in as_completed(futs):
            rows.append(f.result())

    log()
    log("=" * 70)
    for tag, st, tid, info, size in sorted(rows):
        log(f"  {st:<7} {tag:<50} {size // 1024}KB  {tid}")
    log(f"耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
