"""
FrameFlow — 极简 AI 图片 / 视频工作台后端

对接 draw.openai-next.com (Shell API / Vectrust)，已实测的接口：
  * 生图:  POST {BASE}/chat/completions        (model=gpt-4o-image 等，返回 markdown 图片链接)
           POST {BASE}/images/generations      (model=gpt-image-* 等)
  * 生视频: POST {BASE}/video/generations        body: {model, prompt, images:[首帧, 尾帧], duration, resolution}
           返回 {id, output:{task_id}}，再轮询:
           GET  {BASE}/tasks/{task_id}          -> status / progress / result_url

启动:  python server.py   然后打开 http://127.0.0.1:8787
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

BASE_URL = os.getenv("VECTRUST_BASE_URL", "https://draw.openai-next.com/v1").rstrip("/")
API_KEY = os.getenv("VECTRUST_API_KEY", "").strip()

SESSION = requests.Session()


# --------------------------------------------------------------------------- #
# 模型清单（可按需增删；前端用 datalist，可手输任意模型 id）
# --------------------------------------------------------------------------- #
IMAGE_MODELS = [
    "gpt-4o-image", "gpt-4o-image-vip",
    "gpt-image-1.5", "gpt-image-2", "gpt-image-2.5",
    "gemini-2.5-flash-image", "gemini-2.5-flash-image-hd",
    "gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview",
    "doubao-seedream-4-0-250828", "doubao-seedream-4-5-251128",
    "doubao-seedream-5-0-260128", "doubao-seedream-5-0-pro-260628",
    "seedream-4-5-251128",
    "jimeng-4.5", "jimeng-4.0", "jimeng-3.1",
    "flux-kontext-pro", "flux-kontext-max", "flux-1-dev",
    "wan2.7-image", "wan2.7-image-pro",
    "vidu-image", "midjourney",
]

VIDEO_MODELS = [
    "wan2.2-kf2v-flash",        # 首尾帧 -> 视频（推荐，便宜）
    "wanx2.1-kf2v-plus",
    "wan2.2-i2v-flash", "wan2.2-i2v-plus",
    "wan2.5-i2v-preview", "wan2.6-i2v", "wan2.7-i2v",
    "wan2.6-t2v", "wan2.7-t2v",
    "doubao-seedance-2-0-fast-260128", "doubao-seedance-2-0-260128", "doubao-seedance-2-5-260628",
    "veo3-frames-fast", "veo3-frames", "veo3-fast", "veo3", "veo3.1-fast", "veo3.1",
    "viduq3-pro", "viduq2-pro",
    "jimeng-video-3.0-fast", "jimeng-video-3.5-pro",
    "MiniMax-H3", "luma-video", "pika-1.5", "sora-2-hd",
]


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def _require_key() -> None:
    if not API_KEY:
        raise HTTPException(500, "未配置 VECTRUST_API_KEY，请检查 Workbench/.env")


def _err(data: Any, code: int) -> str:
    if isinstance(data, dict):
        e = data.get("error")
        if isinstance(e, dict) and e.get("message"):
            return f"{code}: {e['message']}"
        if data.get("message"):
            return f"{code}: {data['message']}"
    return f"HTTP {code}"


_URL_RE = re.compile(r"https?://[^\s)\"'<>]+")
_IMG_HINT = re.compile(r"\.(?:png|jpe?g|webp|gif|bmp)(?:\?|$)|filesystem\.site|oss|cdn", re.I)


def _extract_url(text: str) -> Optional[str]:
    if not text:
        return None
    md = re.search(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", text)
    if md:
        return md.group(1)
    for m in _URL_RE.finditer(text):
        u = m.group(0)
        if _IMG_HINT.search(u):
            return u
    return None


# --------------------------------------------------------------------------- #
# 请求模型
# --------------------------------------------------------------------------- #
class ImageRequest(BaseModel):
    prompt: str
    model: str = "gpt-4o-image"
    mode: str = "auto"          # auto | chat | images
    size: Optional[str] = None
    n: int = 1
    extra: Dict[str, Any] = {}


class VideoRequest(BaseModel):
    prompt: str = ""
    model: str = "wan2.2-kf2v-flash"
    images: List[str] = []      # [首帧, 尾帧]
    duration: Optional[int] = None
    resolution: Optional[str] = None
    extra: Dict[str, Any] = {}


app = FastAPI(title="FrameFlow")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {"ok": True, "base_url": BASE_URL, "has_key": bool(API_KEY)}


@app.get("/api/models")
def models():
    return {"image": IMAGE_MODELS, "video": VIDEO_MODELS, "base_url": BASE_URL}


def _image_chat(req: ImageRequest) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": req.model,
        "messages": [{"role": "user", "content": req.prompt}],
        "stream": False,
    }
    body.update(req.extra)
    r = SESSION.post(f"{BASE_URL}/chat/completions", headers=_headers(), json=body, timeout=600)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise RuntimeError(_err(data, r.status_code))
    content = ""
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except Exception:
        pass
    url = _extract_url(content) or _extract_url(str(data))
    if not url:
        raise RuntimeError(f"未找到图片链接: {content[:200]}")
    return {"url": url, "mode": "chat", "model": req.model, "raw": data}


def _image_images(req: ImageRequest) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": req.model, "prompt": req.prompt, "n": req.n}
    if req.size:
        body["size"] = req.size
    body.update(req.extra)
    r = SESSION.post(f"{BASE_URL}/images/generations", headers=_headers(), json=body, timeout=600)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise RuntimeError(_err(data, r.status_code))
    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"images/generations 未返回图片: {str(data)[:200]}")
    item = items[0]
    if item.get("url"):
        return {"url": item["url"], "mode": "images", "model": req.model, "raw": data}
    if item.get("b64_json"):
        return {"url": "data:image/png;base64," + item["b64_json"], "mode": "images", "model": req.model, "raw": data}
    raise RuntimeError("images/generations 返回中没有 url/b64_json")


@app.post("/api/image")
def generate_image(req: ImageRequest):
    _require_key()
    if not req.prompt.strip():
        raise HTTPException(400, "prompt 不能为空")
    modes = ["chat", "images"] if req.mode == "auto" else [req.mode]
    errors: List[str] = []
    for mode in modes:
        try:
            return _image_chat(req) if mode == "chat" else _image_images(req)
        except Exception as e:  # noqa: BLE001
            errors.append(f"[{mode}] {e}")
    raise HTTPException(502, "；".join(errors))


@app.post("/api/video")
def generate_video(req: VideoRequest):
    _require_key()
    if not req.prompt.strip() and not req.images:
        raise HTTPException(400, "prompt 和图片不能同时为空")
    body: Dict[str, Any] = {"model": req.model, "prompt": req.prompt}
    if req.images:
        body["images"] = req.images
    if req.duration:
        body["duration"] = req.duration
    if req.resolution:
        body["resolution"] = req.resolution
    body.update(req.extra)

    r = SESSION.post(f"{BASE_URL}/video/generations", headers=_headers(), json=body, timeout=180)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise HTTPException(502, _err(data, r.status_code))
    task_id = (
        (data.get("output") or {}).get("task_id")
        or data.get("task_id")
        or data.get("id")
    )
    if not task_id:
        raise HTTPException(502, f"未拿到 task_id: {str(data)[:300]}")
    return {"task_id": task_id, "raw": data}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    _require_key()
    r = SESSION.get(f"{BASE_URL}/tasks/{task_id}", headers=_headers(), timeout=60)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise HTTPException(502, _err(data, r.status_code))
    return data


@app.get("/api/proxy")
def proxy(url: str = Query(...)):
    """下载代理，避免浏览器跨域下载问题。"""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "invalid url")
    r = SESSION.get(url, stream=True, timeout=300)
    r.raise_for_status()
    return StreamingResponse(
        r.iter_content(chunk_size=65536),
        media_type=r.headers.get("content-type", "application/octet-stream"),
    )


# --------------------------------------------------------------------------- #
# 静态前端
# --------------------------------------------------------------------------- #
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8787)
