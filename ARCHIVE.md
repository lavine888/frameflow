# FrameFlow 存档 · 2026-09-23

> 一句话状态：**两条片子的流水线都已闭环跑通并交付**，代码全部推送到 `lavine888/frameflow`，本地无未提交改动。

- 仓库：`https://github.com/lavine888/frameflow`（PRIVATE）
- 本地：`D:/Codex-Workspace/Evomap Hackthon/Workbench/`
- 最新提交：`639777c` feat(duanhang): 《断航》90秒舰战全流程
- 工作区状态：`## main...origin/main`（干净，已同步）
- 密钥：`.env` 被 `.gitignore` 挡住，从未进入任何提交（每次提交前都做了 grep 校验）

---

## 1. 交付物

### 1.1 《熊酒馆 · 断航》90 秒舰战（25fps / 2250 帧）

| 文件 | 规格 | 大小 | sha256 |
|---|---|---|---|
| `runs/duanhang/duanhang_90s_1080p.mp4` | 1920×1080 / 25fps / 2250帧 / 90.04s / AAC立体声 | 122 MB | `0db806ae…297d3d` |
| `runs/duanhang/duanhang_90s_720p.mp4` | 1280×720 / 25fps / 2250帧 | 43 MB | `9564772b…da5851` |
| `runs/duanhang/contact-90s.png` | 24 格全片抽帧总览 | 4.1 MB | — |
| `runs/duanhang/clips/B01–B23.mp4` | 单镜 2560×1440 / 24fps，各带原生立体声 | 23 个 | — |
| `runs/duanhang/first/B01–B24.png` | 预处理首帧 1280×720（16:9） | 24 个 | — |

同时写回了源包：
- `…/熊酒馆_断航_分镜与MD说明_v2.0/renders/B01–B23.mp4`
- `…/熊酒馆_断航_分镜与MD说明_v2.0/output/duanhang_90s_1080p.mp4`

**质检**：帧数 2250 与分镜数据完全一致；逐镜首帧保真 SSIM 均值 **0.891**、最低 0.806（B09）；音频 RMS −13.8 dB（非静音）。

### 1.2 《熊酒馆》前 30 秒外部算力包 v1.0（24fps / 720 帧）

| 文件 | 规格 | 大小 | sha256 |
|---|---|---|---|
| `runs/bear_tavern/v2/bear_tavern_00-30_720p_h3-2k.mp4` | 1280×720 / 24fps / 720帧 | 17.7 MB | `110e2e56…0b8fa3` |
| `runs/bear_tavern/v2/bear_tavern_00-30_720p_wan27.mp4` | 1280×720 / 24fps / 720帧 | 20.2 MB | `a18ac1a8…a54d630` |

另有第一版 480p（`runs/bear_tavern/bear_tavern_00-30_480p.mp4`）与 9 格对比图 `contact_h3-2k.png` / `contact_wan27.png`。

**逐镜首帧保真 SSIM 对比**

```
任务    v1 H3-768P   v2 H3-2K   v2 Wan2.7
J01     0.9345       0.9676     0.9844
J02     0.8056       0.9056     0.9231
J03     0.9130       0.9645     0.9810
J04     0.9286       0.9658     0.9837
J05     0.9126       0.9644     0.9804
J06     0.9325       0.9662     0.9834
均值    0.9045       0.9557     0.9727
```

---

## 2. 环境与启动

```
Python 3.11.0 / Node v24.15.0 / ffmpeg + ffprobe 在 PATH
pip install -r requirements.txt      # fastapi uvicorn requests python-dotenv
```

`.env`（不入库）：

```
VECTRUST_BASE_URL=https://draw.openai-next.com/v1
VECTRUST_API_KEY=sk-…
```

启动工作台（UI 在 `http://127.0.0.1:8787`）：

```bash
cd "D:/Codex-Workspace/Evomap Hackthon/Workbench" && python server.py
```

重启前先杀端口：

```bash
PID=$(netstat -ano | grep LISTENING | grep ':8787' | head -1 | awk '{print $NF}'); taskkill //F //PID $PID
```

---

## 3. 工具链

| 文件 | 作用 |
|---|---|
| `server.py` | FrameFlow 后端。`/api/image`（支持 `images` 参考图多模态）、`/api/video`、`/api/tasks/{id}`、`/api/proxy` |
| `static/` | 零构建前端（节点画布，文本→图片→视频） |
| `tools/bear_tavern.py` | 30 秒包批量跑：`--out-dir` 分版本、`--duration-options` 按时间线自动选档位、断点续跑 |
| `tools/assemble_hd.py` | 30 秒包拼接（原包工具硬编码 854×480，这个按 `k=W/854` 等比放大到任意尺寸） |
| `tools/shootout.py` | 同镜头多模型并排对照，用来挑模型 |
| `tools/duanhang.py` | 90 秒包批量跑：读 `分镜数据.json`，首帧保真放大，逐镜调 MiniMax-H3 |
| `tools/assemble_duanhang.py` | 90 秒包拼接：25fps 精确切帧、B24 片名卡、沿用原生立体声、断言校验 |
| `tools/e2e.cjs` | Playwright 端到端脚本（首帧图 → 尾帧图 → 首尾帧视频） |

---

## 4. 模型可用性实测（同一中继）

| 模型 | 可用性 | 产出 | 备注 |
|---|---|---|---|
| **MiniMax-H3** | ✅ | 4–15s 任意整数时长，24fps，**原生立体声** | 480P/768P/2K；`content` 数组，`duration`+`resolution` 必填 |
| **wan2.7-i2v** | ✅ 约 1 分钟/条 | 1920×1080 / 30fps | `duration` 常规档 5/10/15；无原生音频 |
| veo3 / veo3.1 | ❌ 持续 429 拥堵 | — | **不能传 `duration`**，传 int/str 都被上游拒 |
| doubao-seedance-2-5-260628 | ❌ `quota_not_enough` | — | 形状同 wan 系 |
| sora-2-hd | ❌ | — | `GetModelFixedPrice not found` |
| jimeng-video-3.5-pro | ❌ | — | `No available channel` |
| gemini-3-pro-image-preview | ❌ | — | 上游 `do_request_failed`，纯文本也失败 |
| gpt-image-2.5 | ✅ 走 `/images/generations` | 1672×941 等 | **不能用于保构图重绘**（见下） |
| gpt-4o-image | ✅ 走 `/chat/completions` | markdown 链接 | 老牌稳定 |

**接口要点**
- 生图：`POST /v1/chat/completions`（`gpt-4o-image`）或 `POST /v1/images/generations`（`gpt-image-*`，带 `images:[dataURL]` 可传参考图）
- 生视频：`POST /v1/video/generations` → 轮询 `GET /v1/tasks/{task_id}`（`/v1/video/generations/{id}` 是 404）
- 上游偶发 SSL EOF，`server.py` 的 `_request()` 与各工具里的 `_req()` 都做了 5 次退避重试

---

## 5. 关键踩坑（复跑前必读）

1. **AI 重绘关键帧会毁构图**。断航包 K01–K24 只有 677×356，我试过用 `gpt-image-2.5` 带参考图重绘到 1920×1080，输出与原图的构图 SSIM 只有 **0.23**（等于重新画了一张）。证据图：`runs/_evidence/ai-redraw-broke-composition.png`。最终改成：中心裁 16:9 → LANCZOS 放大 → 轻度 USM，构图保真 1.0，细节交给视频模型自己补。
2. **veo3 不能传 `duration`**。传 int 报 `Sora2GenerationRequest.duration of type string`，传 str 报 `VideoGenerationRequest.duration of type int`，**不传反而能过**（然后 429）。这个矛盾是因为中继按参数组合路由到了不同上游结构体。
3. **MiniMax-H3 的时长是 4–15 任意整数**，不是固定档位。这是选它跑断航的决定性原因——最长镜 14.88s 一次出，不用拆镜。
4. **首尾帧用 `images: [首帧, 尾帧]` 数组**，`last_frame` / `image_tail` 都不认。`wan2.2-kf2v-flash` 这类必须给满两张，只给一张报错。
5. **Windows 路径**：`ls` 能用 `/d/...`，但 Windows Python 必须 `D:/...`，否则 `FileNotFoundError`。
6. **GBK 控制台**打 emoji 会 `UnicodeEncodeError`，脚本里统一 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。
7. **API key 已在多处出现过，建议轮换一次**，轮换后只改 `Workbench/.env` 即可，代码不用动。

---

## 6. 如何续跑

### 断航 90 秒

```bash
cd "D:/Codex-Workspace/Evomap Hackthon/Workbench"

# 1) 关键帧预处理（16:9 裁切放大到 1280x720）
python tools/duanhang.py --prep-only

# 2) 逐镜生成（默认 MiniMax-H3 @2K，并发 6，已存在会跳过）
python tools/duanhang.py --all --parallel 6
python tools/duanhang.py --only B09 --force        # 单独重跑某镜

# 3) 拼接 + 校验（帧数/尺寸/时长断言）
python tools/assemble_duanhang.py --width 1920 --height 1080
```

断点续跑靠 `runs/duanhang/submitted.json`（记录每镜 task_id / 模型 / 时长）。

### 熊酒馆 30 秒

```bash
python tools/bear_tavern.py --all --parallel 6 --model MiniMax-H3 --resolution 2K --duration 6 --out-dir renders_2k
python tools/bear_tavern.py --all --parallel 6 --model wan2.7-i2v --resolution 1080P --duration-options 5,10,15 --out-dir renders_wan27
python tools/assemble_hd.py --renders renders_2k --output output/xxx_720p.mp4 --width 1280 --height 720
```

### 挑模型

```bash
python tools/shootout.py --job J03          # 同镜头多模型并排对照
python tools/shootout.py --job J03 --specs "veo3|1080P|8" "wan2.7-i2v|1080P|5"
```

---

## 7. 未完成 / 下一步

- [ ] **音乐床**：断航现在只有 H3 逐镜同期音效，没有贯穿 90 秒的配乐。包里的声音设计（工业节奏、蓄能反向吸气、80.68s 最大重拍）可以程序化合成一轨铺上去。**建议优先做这个**——有无配乐观感差一个档。
- [ ] **B09 重跑**：敌方环炮蓄能，首帧保真 0.806 是全片最低，可单独重跑。
- [ ] **换 veo3 重跑**：等拥堵缓解后可拿它和 H3 对照一版。
- [ ] **人物**：两个包都是纯舰船/纯场景，角色未出镜。断航包给了 L01–L40 的选用规则（若加人物优先从现有档案筛选，不擅自改写军籍）。
- [ ] **接回 FrameFlow**：把「导入任务包 → 一键跑完」做进工作台 UI，目前两个工具是命令行跑的。

---

## 8. 目录占用

```
runs/duanhang      365 MB   （23 单镜 1440p + 两版成片 + 抽帧图）
runs/bear_tavern   214 MB   （6 单镜 + 两版成片 + 对比图）
```

`runs/` 已在 `.gitignore` 中，不进仓库。要长期保存建议另拷到网盘或移动硬盘。

## 9. 源包位置

```
D:/电脑管家迁移文件/xwechat_files/wxid_x7gcga7y4u3b22_ce72/msg/file/2026-09/
├─ BearTavern_30s_v1.0/
└─ 熊酒馆_断航_分镜与MD说明_v2.0/
```

（微信文件目录，路径较长且可能被清理，建议一并备份。）
