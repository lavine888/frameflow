#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
《熊酒馆·断航》90秒成片拼接：25fps / 2250帧 / 90.000s。

逐镜从 renders/Bxx.mp4 取前 N 帧（N = 分镜数据.json 的镜长×25），
B24 用 分镜/片名卡.png 静帧。音频沿用 MiniMax-H3 的原生立体声，
静帧镜补静音。最后按分镜顺序 concat。

  python tools/assemble_duanhang.py --width 1920 --height 1080
  python tools/assemble_duanhang.py --output output/duanhang_90s_1080p.mp4
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PKG = Path(
    r"D:/电脑管家迁移文件/xwechat_files/wxid_x7gcga7y4u3b22_ce72/msg/file/2026-09/熊酒馆_断航_分镜与MD说明_v2.0"
)
TITLE_CARD = "分镜/片名卡.png"


def run(args, check=True):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise RuntimeError(" ".join(map(str, args)) + "\n" + r.stderr[-3000:])
    return r


def probe(p):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)]).stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--renders", default="renders")
    ap.add_argument("--output", default="output/duanhang_90s_1080p.mp4")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--work-dir", default="output/edit90")
    a = ap.parse_args()

    data = json.loads((PKG / "分镜数据.json").read_text(encoding="utf-8"))
    shots = data["shots"]
    fps, total_frames = data["fps"], data["frames"]
    W, H = a.width, a.height

    renders = PKG / a.renders
    temp = PKG / a.work_dir
    temp.mkdir(parents=True, exist_ok=True)

    print(f"《{data['title']}》 {fps}fps / {total_frames}帧 / {data['duration']}s → {W}x{H}")
    print()

    parts = []
    for s in shots:
        n = s["end_frame_exclusive"] - s["start_frame"]      # 该镜帧数（25fps）
        dest = temp / f"{s['id']}.mp4"
        src = renders / f"{s['id']}.mp4"

        if s["id"] == "B24" or not src.is_file():
            why = "片名卡" if s["id"] == "B24" else "缺片段→用首帧兜底"
            img = PKG / (TITLE_CARD if s["id"] == "B24" else s["image"])
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-loop", "1", "-framerate", str(fps), "-i", img,
                 "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                 "-t", f"{n / fps:.6f}",
                 "-vf", (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                         f"crop={W}:{H},setsar=1,format=yuv420p"),
                 "-r", str(fps), "-c:v", "libx264", "-crf", str(a.crf), "-preset", "fast",
                 "-c:a", "aac", "-b:a", "192k", "-shortest", dest])
            print(f"  {s['id']}  {n:>4}f  {s['duration']:>6.2f}s  {why}")
        else:
            meta = probe(src)
            v = next(x for x in meta["streams"] if x["codec_type"] == "video")
            have = float(v.get("duration") or meta["format"]["duration"])
            flag = "" if have + 0.05 >= s["duration"] else "  ⚠素材偏短"
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                 "-vf", (f"fps={fps},trim=start_frame=0:end_frame={n},setpts=PTS-STARTPTS,"
                         f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                         f"setsar=1,format=yuv420p"),
                 "-af", "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad",
                 "-t", f"{n / fps:.6f}", "-r", str(fps),
                 "-c:v", "libx264", "-crf", str(a.crf), "-preset", "fast",
                 "-c:a", "aac", "-b:a", "192k", dest])
            print(f"  {s['id']}  {n:>4}f  {s['duration']:>6.2f}s  源 {have:.2f}s {v['width']}x{v['height']}{flag}")
        parts.append(dest)

    listing = temp / "concat.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    out = PKG / a.output
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", listing,
         "-c:v", "libx264", "-crf", str(a.crf), "-preset", "slow",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", out])

    m = probe(out)
    v = next(x for x in m["streams"] if x["codec_type"] == "video")
    au = next((x for x in m["streams"] if x["codec_type"] == "audio"), None)
    print()
    print(json.dumps({
        "output": str(out),
        "size": f"{v['width']}x{v['height']}",
        "fps": v["r_frame_rate"],
        "frames": int(v["nb_frames"]),
        "seconds": round(float(m["format"]["duration"]), 3),
        "audio": f"{au['codec_name']} {au['channels']}ch {au['sample_rate']}Hz" if au else "无",
        "MB": round(out.stat().st_size / 1048576, 1),
    }, ensure_ascii=False, indent=1))

    assert int(v["nb_frames"]) == total_frames, f"帧数不对: {v['nb_frames']} != {total_frames}"
    assert (v["width"], v["height"]) == (W, H)
    assert abs(float(m["format"]["duration"]) - data["duration"]) < 0.05
    print("✅ 校验通过：帧数/尺寸/时长与分镜数据一致")


if __name__ == "__main__":
    main()
