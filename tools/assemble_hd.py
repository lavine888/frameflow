#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
高清版拼接：逻辑与包内 tools/assemble_30s.py 完全一致，但输出尺寸可调（默认 1280x720）。

原包成片硬编码 854x480（中间 864x480 再中心裁掉 5+5）。这里把整条链路按
k = 目标宽 / 854 等比放大：中间工作尺寸、B02 近景裁切框、PNG 叠层一起缩放，
时间轴（24fps / 720 帧 / 30.000s）保持与原包一致。

  python tools/assemble_hd.py --renders renders_2k    --output output/bear_tavern_00-30_720p_h3-2k.mp4
  python tools/assemble_hd.py --renders renders_wan27 --output output/bear_tavern_00-30_720p_wan27.mp4
  python tools/assemble_hd.py --renders renders_2k --width 1920 --height 1080 --output output/...1080p.mp4
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

PKG = Path(
    r"D:/电脑管家迁移文件/xwechat_files/wxid_x7gcga7y4u3b22_ce72/msg/file/2026-09/BearTavern_30s_v1.0"
)
BASE_W, BASE_H = 854, 480      # 原包成片尺寸（k=1 基准）
WORK_W, WORK_H = 864, 480      # 原包中间工作尺寸
OVERLAY_W, OVERLAY_H, REVIEW_BAR = 1280, 720, 38


def run(args):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(r.stderr[-4000:])
    return r.stdout


def probe(p):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)]))


def ff(*a):
    return run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, a)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--renders", required=True, help="片段目录（相对包根）")
    ap.add_argument("--output", required=True)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--work-dir", default="output/edit_hd")
    a = ap.parse_args()

    W, H = a.width, a.height
    # 854x480 与 1280x720 宽高比不完全一致，取较大比例保证工作画布能盖住目标
    k = max(W / BASE_W, H / BASE_H)
    ww, wh = round(WORK_W * k), round(WORK_H * k)
    assert ww >= W and wh >= H, f"工作画布 {ww}x{wh} 盖不住 {W}x{H}"

    m = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    shots = m["edit"]["shots"]

    renders = Path(a.renders)
    renders = renders if renders.is_absolute() else PKG / renders
    assert shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 FFmpeg 在 PATH 里"

    temp = Path(a.work_dir)
    temp = temp if temp.is_absolute() else PKG / temp
    temp.mkdir(parents=True, exist_ok=True)

    print(f"输出 {W}x{H}  中间工作尺寸 {ww}x{wh}  k={k:.4f}")
    for s in shots:
        target = temp / (s["id"] + ".mp4")
        if s["type"] == "post":
            ff("-i", PKG / s["file"], "-vf", f"scale={W}:{H},setsar=1,fps=24,setpts=N/(24*TB)",
               "-frames:v", s["frames"], "-an", "-c:v", "libx264", "-preset", "fast",
               "-crf", "17", "-pix_fmt", "yuv420p", target)
            print(f"  {s['id']}  后期卡      -> {s['frames']}f")
            continue

        src = renders / (s["job_id"] + ".mp4")
        assert src.is_file(), f"缺少 {src}"
        meta = probe(src)
        v = next(x for x in meta["streams"] if x["codec_type"] == "video")
        have = float(v.get("duration") or meta["format"]["duration"])
        assert have + 0.04 >= s["source_in"] + s["duration"], \
            f"{s['id']} 素材太短: 需 {s['source_in'] + s['duration']:.2f}s, 只有 {have:.2f}s"

        start = round(s["source_in"] * 24)
        end = start + s["frames"]
        vf = (f"fps=24,trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS,"
              f"scale={ww}:{wh}:force_original_aspect_ratio=increase,crop={ww}:{wh},setsar=1")
        if s["id"] == "B02":
            cx, cy, cw, ch = [round(x * k) for x in s["editorial_crop"]["crop_xywh"]]
            vf += f",crop={cw}:{ch}:{cx}:{cy},scale={ww}:{wh}"
        vf += f",crop={W}:{H}:{round((ww - W) / 2)}:0,format=yuv420p"

        args = ["-i", src]
        if s.get("overlay"):
            args += ["-loop", "1", "-framerate", "24", "-i", PKG / s["overlay"]]
            graph = (f"[0:v]{vf}[b];"
                     f"[1:v]format=rgba,crop={OVERLAY_W}:{OVERLAY_H - REVIEW_BAR}:0:{REVIEW_BAR},"
                     f"pad={OVERLAY_W}:{OVERLAY_H}:0:{REVIEW_BAR}:color=black@0,scale={W}:{H}[o];"
                     f"[b][o]overlay=shortest=1:format=auto,format=yuv420p[v]")
            args += ["-filter_complex", graph, "-map", "[v]"]
        else:
            args += ["-vf", vf, "-map", "0:v"]
        ff(*args, "-frames:v", s["frames"], "-an", "-c:v", "libx264", "-preset", "fast",
           "-crf", "17", "-pix_fmt", "yuv420p", target)
        print(f"  {s['id']}  {s['job_id']}  取 {s['source_in']}-{s['source_in']+s['duration']}s"
              f"  -> {s['frames']}f{'  +叠层' if s.get('overlay') else ''}")

    listing = temp / "concat.txt"
    listing.write_text("".join(f"file '{s['id']}.mp4'\n" for s in shots), encoding="utf-8")
    output = Path(a.output)
    output = output if output.is_absolute() else PKG / output
    output.parent.mkdir(parents=True, exist_ok=True)
    ff("-f", "concat", "-safe", "0", "-i", listing, "-i", PKG / "audio/storyboard_mix_00-30.wav",
       "-map", "0:v", "-map", "1:a", "-vf", "setpts=N/(24*TB)", "-frames:v", "720", "-t", "30",
       "-c:v", "libx264", "-crf", "17", "-preset", "fast", "-c:a", "aac", "-b:a", "192k",
       "-ar", "48000", "-ac", "2", "-movflags", "+faststart", output)

    meta = probe(output)
    v = next(x for x in meta["streams"] if x["codec_type"] == "video")
    assert (v["width"], v["height"], int(v["nb_frames"])) == (W, H, 720), \
        f"成片规格不对: {v['width']}x{v['height']} {v['nb_frames']}f"
    assert abs(float(meta["format"]["duration"]) - 30) < 0.001
    ff("-i", output, "-f", "null", "-")
    print(json.dumps({"output": str(output), "size": f"{W}x{H}", "frames": 720, "seconds": 30,
                      "size_mb": round(output.stat().st_size / 1048576, 1)}, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
