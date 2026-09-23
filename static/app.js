/* FrameFlow — 极简 AI 图片/视频工作台（无限画布 + 节点连线）
 * 首尾帧工作流：文本 -> 图片(首帧) / 图片(尾帧) -> 视频
 */
const NS = 'http://www.w3.org/2000/svg';
const STORAGE_KEY = 'frameflow.state.v1';

/* ------------------------------------------------------------------ */
/* 节点定义                                                            */
/* ------------------------------------------------------------------ */
const NODE_DEFS = {
  prompt: {
    title: '文本', icon: '📝', accent: '#8b5cf6', width: 260,
    inputs: [],
    outputs: [{ id: 'text', label: '文本', type: 'text' }],
  },
  image: {
    title: '图片', icon: '🖼️', accent: '#10b981', width: 320,
    inputs: [{ id: 'prompt', label: '提示词', type: 'text' }],
    outputs: [{ id: 'image', label: '图片', type: 'image' }],
  },
  video: {
    title: '视频', icon: '🎬', accent: '#f59e0b', width: 360,
    inputs: [
      { id: 'prompt', label: '提示词', type: 'text' },
      { id: 'first', label: '首帧', type: 'image' },
      { id: 'last', label: '尾帧', type: 'image' },
    ],
    outputs: [{ id: 'video', label: '视频', type: 'video' }],
  },
};
const PORT_MATCH = { text: ['text'], image: ['image'], video: [] };

const state = {
  nodes: [], edges: [],
  view: { x: 60, y: 60, k: 1 },
  models: { image: [], video: [] },
};
let uid = 1;
const nid = () => 'n' + (uid++) + '_' + Math.random().toString(36).slice(2, 6);

const stage = document.getElementById('stage');
const world = document.getElementById('world');
const nodesEl = document.getElementById('nodes');
const edgeGroup = document.getElementById('edge-group');
const tempEdge = document.getElementById('tempEdge');
const statusEl = document.getElementById('api-status');
const hintEl = document.getElementById('hint');

/* ------------------------------------------------------------------ */
/* 工具                                                               */
/* ------------------------------------------------------------------ */
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

async function post(path, body) {
  const r = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || data.message || ('HTTP ' + r.status));
  return data;
}
const getNode = (id) => state.nodes.find((n) => n.id === id);
function inputSource(nodeId, portId) {
  const e = state.edges.find((x) => x.to.node === nodeId && x.to.port === portId);
  return e ? getNode(e.from.node) : null;
}
function resolvePrompt(node) {
  const src = inputSource(node.id, 'prompt');
  if (src) return (src.data.text || '').trim();
  return (node.data.prompt || '').trim();
}
function resolveFrame(node, slot) {
  const src = inputSource(node.id, slot);
  if (src) return src.data.remoteUrl || src.data.url || '';
  return node.data[slot === 'first' ? 'firstUrl' : 'lastUrl'] || '';
}
let toastTimer;
function toast(msg) {
  hintEl.textContent = msg;
  hintEl.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    hintEl.textContent = '滚轮缩放 · 拖拽空白平移 · 从右侧圆点拖到左侧圆点连线 · 点击连线可删除';
    hintEl.classList.remove('show');
  }, 2200);
}

/* ------------------------------------------------------------------ */
/* 持久化                                                             */
/* ------------------------------------------------------------------ */
let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ nodes: state.nodes, edges: state.edges, view: state.view }));
    } catch (e) { /* ignore quota */ }
  }, 300);
}
function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    const s = JSON.parse(raw);
    state.nodes = s.nodes || [];
    state.edges = s.edges || [];
    state.view = s.view || { x: 60, y: 60, k: 1 };
    uid = 1000 + state.nodes.length;
    return state.nodes.length > 0;
  } catch (e) { return false; }
}

/* ------------------------------------------------------------------ */
/* 节点/连线构造                                                       */
/* ------------------------------------------------------------------ */
function mkNode(type, x, y, data = {}) { return { id: nid(), type, x, y, data: { status: '', ...data } }; }
function mkEdge(fromNode, fromPort, toNode, toPort) {
  return { id: `${fromNode}:${fromPort}->${toNode}:${toPort}`, from: { node: fromNode, port: fromPort }, to: { node: toNode, port: toPort } };
}
function defaultsFor(type) {
  if (type === 'image') return { model: 'gpt-4o-image', prompt: '' };
  if (type === 'video') return { model: 'wan2.2-kf2v-flash', prompt: '', duration: 5, resolution: '720P' };
  return { text: '' };
}
function starter() {
  const p = mkNode('prompt', 80, 150, { text: '一只戴宇航头盔的柴犬，电影感打光，星空背景' });
  const i1 = mkNode('image', 420, 60, { model: 'gpt-4o-image' });
  const i2 = mkNode('image', 420, 430, { model: 'gpt-4o-image' });
  const v = mkNode('video', 800, 180, { model: 'wan2.2-kf2v-flash', prompt: '镜头缓慢推进，光影流动', duration: 5, resolution: '720P' });
  state.nodes = [p, i1, i2, v];
  state.edges = [
    mkEdge(p.id, 'text', i1.id, 'prompt'),
    mkEdge(p.id, 'text', i2.id, 'prompt'),
    mkEdge(i1.id, 'image', v.id, 'first'),
    mkEdge(i2.id, 'image', v.id, 'last'),
  ];
}

/* ------------------------------------------------------------------ */
/* 渲染：视图 / 节点 / 连线                                             */
/* ------------------------------------------------------------------ */
function applyView() {
  world.style.transform = `translate(${state.view.x}px, ${state.view.y}px) scale(${state.view.k})`;
  renderEdges();
}
function fitView() {
  if (!state.nodes.length) { state.view = { x: 60, y: 60, k: 1 }; applyView(); return; }
  const pad = 90;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of state.nodes) {
    const w = NODE_DEFS[n.type].width;
    const el = document.querySelector(`.node[data-id="${n.id}"]`);
    const h = el ? el.offsetHeight : 260;
    minX = Math.min(minX, n.x); minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x + w); maxY = Math.max(maxY, n.y + h);
  }
  const vw = stage.clientWidth, vh = stage.clientHeight;
  const k = clamp(Math.min((vw - pad * 2) / (maxX - minX), (vh - pad * 2) / (maxY - minY)), 0.2, 1.1);
  state.view = {
    k,
    x: (vw - (maxX - minX) * k) / 2 - minX * k,
    y: (vh - (maxY - minY) * k) / 2 - minY * k,
  };
  applyView();
}
function render() {
  nodesEl.innerHTML = '';
  for (const n of state.nodes) nodesEl.appendChild(createNodeEl(n));
  applyView();
  save();
}
function refreshBody(node) {
  const el = document.querySelector(`.node[data-id="${node.id}"]`);
  if (!el) return;
  const body = el.querySelector('.node-body');
  body.innerHTML = bodyHTML(node);
  bindBody(node, el);
  renderEdges();
}
function refreshBodyKeepFocus(node) {
  const el = document.querySelector(`.node[data-id="${node.id}"]`);
  const active = document.activeElement;
  const key = active && active.dataset ? active.dataset.syncKey : null;
  const pos = active && active.selectionStart;
  refreshBody(node);
  if (key) {
    const again = document.querySelector(`.node[data-id="${node.id}"] [data-sync-key="${key}"]`);
    if (again) { again.focus(); try { again.setSelectionRange(pos, pos); } catch (e) { /* noop */ } }
  }
}

function portScreenPos(nodeId, portId, kind) {
  const el = document.querySelector(`.port[data-port-node="${nodeId}"][data-port-id="${portId}"][data-port-kind="${kind}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const s = stage.getBoundingClientRect();
  return { x: r.left + r.width / 2 - s.left, y: r.top + r.height / 2 - s.top };
}
function edgePath(a, b) {
  const dx = Math.max(50, Math.abs(b.x - a.x) * 0.5);
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
}
function renderEdges() {
  if (!edgeGroup) return;
  edgeGroup.innerHTML = '';
  for (const e of state.edges) {
    const a = portScreenPos(e.from.node, e.from.port, 'out');
    const b = portScreenPos(e.to.node, e.to.port, 'in');
    if (!a || !b) continue;
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('d', edgePath(a, b));
    p.setAttribute('class', 'edge');
    p.addEventListener('click', () => {
      state.edges = state.edges.filter((x) => x.id !== e.id);
      render();
    });
    edgeGroup.appendChild(p);
  }
}

/* ------------------------------------------------------------------ */
/* 节点 DOM                                                           */
/* ------------------------------------------------------------------ */
function createNodeEl(node) {
  const def = NODE_DEFS[node.type];
  const el = document.createElement('div');
  el.className = 'node';
  el.dataset.id = node.id;
  el.style.left = node.x + 'px';
  el.style.top = node.y + 'px';
  el.style.width = def.width + 'px';
  el.style.setProperty('--accent', def.accent);
  el.innerHTML = `
    <div class="node-head">
      <span class="node-icon">${def.icon}</span>
      <span class="node-title">${def.title}</span>
      <button class="node-del" title="删除">✕</button>
    </div>
    <div class="node-ports">
      <div class="ports-in">${def.inputs.map((p, i) => `
        <div class="port-row in" style="top:${44 + i * 26}px">
          <span class="port" data-port-node="${node.id}" data-port-id="${p.id}" data-port-kind="in" data-port-type="${p.type}"></span>
          <span class="port-label">${p.label}</span>
        </div>`).join('')}</div>
      <div class="ports-out">${def.outputs.map((p, i) => `
        <div class="port-row out" style="top:${44 + i * 26}px">
          <span class="port-label">${p.label}</span>
          <span class="port" data-port-node="${node.id}" data-port-id="${p.id}" data-port-kind="out" data-port-type="${p.type}"></span>
        </div>`).join('')}</div>
    </div>
    <div class="node-body">${bodyHTML(node)}</div>`;
  el.querySelector('.node-head').addEventListener('pointerdown', (e) => {
    if (e.target.closest('.node-del')) return;
    startNodeDrag(e, node, el);
  });
  el.querySelector('.node-del').addEventListener('click', () => removeNode(node.id));
  bindBody(node, el);
  return el;
}

function bodyHTML(node) {
  const d = node.data;
  if (node.type === 'prompt') {
    return `<textarea class="ta prompt-text" data-sync-key="prompt-text" placeholder="输入提示词，右侧圆点可连到图片/视频">${esc(d.text || '')}</textarea>
            <div class="status">${esc(d.status || '')}</div>`;
  }
  if (node.type === 'image') {
    const src = d.remoteUrl || d.url || '';
    return `
      <div class="field"><label>模型</label>
        <input class="model" data-sync-key="model" list="image-models" value="${esc(d.model || 'gpt-4o-image')}"/></div>
      <textarea class="ta prompt" data-sync-key="prompt" placeholder="提示词（留空则使用连线文本）">${esc(d.prompt || '')}</textarea>
      <div class="row">
        <button class="btn gen">生成图片</button>
        <button class="btn ghost upload">上传</button>
        <button class="btn ghost dl" ${src ? '' : 'hidden'}>下载</button>
      </div>
      <div class="preview">${src ? `<img src="${esc(src)}"/>` : '<span class="ph">暂无图片</span>'}</div>
      <div class="status">${esc(d.status || '')}</div>
      <input type="file" class="file" accept="image/*" hidden/>`;
  }
  if (node.type === 'video') {
    const first = resolveFrame(node, 'first');
    const last = resolveFrame(node, 'last');
    const firstConn = !!inputSource(node.id, 'first');
    const lastConn = !!inputSource(node.id, 'last');
    const vid = d.videoUrl || '';
    const prog = parseInt(d.progress) || 0;
    return `
      <div class="field"><label>模型</label>
        <input class="model" data-sync-key="model" list="video-models" value="${esc(d.model || 'wan2.2-kf2v-flash')}"/></div>
      <textarea class="ta prompt" data-sync-key="prompt" placeholder="提示词 / 运镜描述（留空则使用连线文本）">${esc(d.prompt || '')}</textarea>
      <div class="frames">
        ${frameSlot('first', '首帧', first, firstConn)}
        ${frameSlot('last', '尾帧', last, lastConn)}
      </div>
      <div class="row">
        <label class="mini">时长<input class="duration" data-sync-key="duration" type="number" min="1" max="15" value="${d.duration ?? 5}"/></label>
        <label class="mini">分辨率
          <select class="resolution" data-sync-key="resolution">
            ${['', '480P', '720P', '1080P'].map((r) => `<option value="${r}" ${((d.resolution ?? '720P') === r) ? 'selected' : ''}>${r || '自动'}</option>`).join('')}
          </select>
        </label>
      </div>
      <div class="row"><button class="btn gen">生成视频</button><button class="btn ghost dl" ${vid ? '' : 'hidden'}>下载</button></div>
      <div class="progress" ${prog > 0 ? '' : 'hidden'}><div class="bar" style="width:${prog}%"></div></div>
      <div class="preview">${vid ? `<video src="${esc(vid)}" controls></video>` : '<span class="ph">暂无视频</span>'}</div>
      <div class="status">${esc(d.status || '')}</div>
      <input type="file" class="file" accept="image/*" hidden/>`;
  }
  return '';
}
function frameSlot(slot, label, url, connected) {
  return `<div class="frame" data-slot="${slot}">
    <div class="frame-label">${label}${connected ? ' <span class="link">连线</span>' : ''}</div>
    <div class="thumb">${url ? `<img src="${esc(url)}"/>` : '<span class="ph">点击上传</span>'}</div>
  </div>`;
}

function bindBody(node, el) {
  const body = el.querySelector('.node-body');
  const sync = (sel, key, fn) => {
    const i = body.querySelector(sel);
    if (!i) return;
    i.addEventListener('input', () => { fn(i.value); save(); });
    i.addEventListener('change', () => { fn(i.value); save(); });
  };
  sync('.model', 'model', (v) => { node.data.model = v; });
  sync('.duration', 'duration', (v) => { node.data.duration = Number(v); });
  sync('.resolution', 'resolution', (v) => { node.data.resolution = v; });
  sync('.prompt-text', 'text', (v) => { node.data.text = v; });
  sync('.prompt', 'prompt', (v) => { node.data.prompt = v; });

  const gen = body.querySelector('.gen');
  if (gen) gen.addEventListener('click', () => (node.type === 'image' ? genImage(node) : genVideo(node)));

  const file = body.querySelector('.file');
  const up = body.querySelector('.upload');
  if (up && file) up.addEventListener('click', () => { file.dataset.slot = ''; file.click(); });

  body.querySelectorAll('.frame').forEach((slotEl) => {
    slotEl.addEventListener('click', () => {
      const slot = slotEl.dataset.slot;
      if (inputSource(node.id, slot)) { toast('该槽位由连线提供，先删除连线再上传'); return; }
      if (!file) return;
      file.dataset.slot = slot;
      file.click();
    });
  });

  if (file) file.addEventListener('change', async () => {
    const f = file.files[0];
    if (!f) return;
    const dataUrl = await readFile(f);
    if (node.type === 'image') {
      node.data.url = dataUrl; node.data.remoteUrl = dataUrl; node.data.status = '已上传本地图片';
    } else if (node.type === 'video') {
      const slot = file.dataset.slot === 'last' ? 'last' : 'first';
      node.data[slot === 'first' ? 'firstUrl' : 'lastUrl'] = dataUrl;
      node.data.status = '已上传' + (slot === 'first' ? '首帧' : '尾帧');
    }
    refreshBody(node); save();
  });

  const dl = body.querySelector('.dl');
  if (dl) dl.addEventListener('click', () => {
    const url = node.type === 'image' ? (node.data.remoteUrl || node.data.url) : node.data.videoUrl;
    if (url) window.open('/api/proxy?url=' + encodeURIComponent(url), '_blank');
  });
}

function readFile(file) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = rej;
    fr.readAsDataURL(file);
  });
}
function removeNode(id) {
  state.nodes = state.nodes.filter((n) => n.id !== id);
  state.edges = state.edges.filter((e) => e.from.node !== id && e.to.node !== id);
  render();
}

/* ------------------------------------------------------------------ */
/* 生成：图片                                                          */
/* ------------------------------------------------------------------ */
async function genImage(node) {
  const prompt = resolvePrompt(node);
  if (!prompt) { node.data.status = '请填写提示词或连接文本节点'; refreshBody(node); return; }
  node.data.status = '生成中…'; refreshBody(node);
  try {
    const res = await post('/api/image', { prompt, model: node.data.model || 'gpt-4o-image' });
    node.data.url = res.url; node.data.remoteUrl = res.url;
    node.data.status = '✅ 完成 (' + (res.mode || '') + ')';
  } catch (e) {
    node.data.status = '❌ ' + e.message;
  }
  refreshBody(node); save();
}

/* ------------------------------------------------------------------ */
/* 生成：视频（提交 + 轮询）                                            */
/* ------------------------------------------------------------------ */
async function genVideo(node) {
  const model = node.data.model || 'wan2.2-kf2v-flash';
  const prompt = resolvePrompt(node);
  const first = resolveFrame(node, 'first');
  const last = resolveFrame(node, 'last');
  if (/kf2v/.test(model) && (!first || !last)) {
    node.data.status = '首尾帧模型需要同时提供首帧和尾帧'; refreshBody(node); return;
  }
  if (!prompt && !first) { node.data.status = '请填写提示词或放入首帧'; refreshBody(node); return; }

  node.data.status = '提交中…'; node.data.progress = 0; node.data.videoUrl = '';
  refreshBody(node);
  try {
    const res = await post('/api/video', {
      model,
      prompt,
      images: [first, last].filter(Boolean),
      duration: node.data.duration || 5,
      resolution: node.data.resolution || '720P',
    });
    const taskId = res.task_id;
    node.data.taskId = taskId;
    node.data.status = '任务已提交，等待中… (' + taskId.slice(0, 8) + ')';
    refreshBody(node);

    for (let i = 0; i < 500; i++) {
      await sleep(3000);
      let t;
      try {
        t = await fetch('/api/tasks/' + encodeURIComponent(taskId)).then((r) => r.json());
      } catch (e) {
        node.data.status = '查询失败，重试…'; refreshBody(node); continue;
      }
      const prog = t.progress || '';
      node.data.progress = parseInt(prog) || node.data.progress || 0;
      node.data.status = `生成中… ${prog} (${t.status || ''})`;
      refreshBody(node);

      if (t.status === 'completed') {
        node.data.videoUrl = t.result_url
          || (t.result && t.result.data && t.result.data.output && t.result.data.output.url) || '';
        node.data.status = node.data.videoUrl ? '✅ 完成' : '✅ 完成，但未找到视频地址';
        refreshBody(node); save();
        return;
      }
      if (t.status === 'failed' || t.status === 'error') {
        node.data.status = '❌ 失败：' + JSON.stringify(t.result || t).slice(0, 220);
        refreshBody(node); save();
        return;
      }
    }
    node.data.status = '⏱ 轮询超时，请稍后手动刷新';
    refreshBody(node); save();
  } catch (e) {
    node.data.status = '❌ ' + e.message;
    refreshBody(node); save();
  }
}

/* ------------------------------------------------------------------ */
/* 拖拽 / 平移 / 缩放 / 连线                                            */
/* ------------------------------------------------------------------ */
function startNodeDrag(e, node, el) {
  e.preventDefault();
  const sx = e.clientX, sy = e.clientY, ox = node.x, oy = node.y;
  const move = (ev) => {
    node.x = ox + (ev.clientX - sx) / state.view.k;
    node.y = oy + (ev.clientY - sy) / state.view.k;
    el.style.left = node.x + 'px';
    el.style.top = node.y + 'px';
    renderEdges();
  };
  const up = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    save();
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

let pan = null;
stage.addEventListener('pointerdown', (e) => {
  if (e.target.closest('.node') || e.target.closest('.port')) return;
  if (e.button !== 0 && e.button !== 1) return;
  pan = { x: e.clientX, y: e.clientY, ox: state.view.x, oy: state.view.y };
  stage.classList.add('panning');
});
window.addEventListener('pointermove', (e) => {
  if (!pan) return;
  state.view.x = pan.ox + (e.clientX - pan.x);
  state.view.y = pan.oy + (e.clientY - pan.y);
  applyView();
});
window.addEventListener('pointerup', () => {
  if (pan) { pan = null; stage.classList.remove('panning'); save(); }
});

stage.addEventListener('wheel', (e) => {
  e.preventDefault();
  const s = stage.getBoundingClientRect();
  const mx = e.clientX - s.left, my = e.clientY - s.top;
  const k2 = clamp(state.view.k * Math.exp(-e.deltaY * 0.0015), 0.2, 3);
  state.view.x = mx - (mx - state.view.x) * (k2 / state.view.k);
  state.view.y = my - (my - state.view.y) * (k2 / state.view.k);
  state.view.k = k2;
  applyView(); save();
}, { passive: false });

let conn = null;
stage.addEventListener('pointerdown', (e) => {
  const port = e.target.closest('.port');
  if (!port) return;
  e.preventDefault();
  e.stopPropagation();
  conn = {
    node: port.dataset.portNode, port: port.dataset.portId,
    kind: port.dataset.portKind, type: port.dataset.portType,
  };
  drawTemp(e);
});
window.addEventListener('pointermove', (e) => { if (conn) drawTemp(e); });
window.addEventListener('pointerup', (e) => {
  if (!conn) return;
  const target = document.elementFromPoint(e.clientX, e.clientY);
  const port = target && target.closest ? target.closest('.port') : null;
  if (port) {
    tryConnect(conn, {
      node: port.dataset.portNode, port: port.dataset.portId,
      kind: port.dataset.portKind, type: port.dataset.portType,
    });
  }
  conn = null;
  tempEdge.setAttribute('d', '');
});
function drawTemp(e) {
  const a = portScreenPos(conn.node, conn.port, conn.kind);
  if (!a) return;
  const s = stage.getBoundingClientRect();
  const b = { x: e.clientX - s.left, y: e.clientY - s.top };
  tempEdge.setAttribute('d', conn.kind === 'out' ? edgePath(a, b) : edgePath(b, a));
}
function tryConnect(a, b) {
  let from, to;
  if (a.kind === 'out' && b.kind === 'in') { from = a; to = b; }
  else if (a.kind === 'in' && b.kind === 'out') { from = b; to = a; }
  else { toast('请把输出圆点连到输入圆点'); return; }
  if (from.node === to.node) return;
  if (!(PORT_MATCH[from.type] || []).includes(to.type)) { toast('端口类型不匹配'); return; }
  state.edges = state.edges.filter((e) => !(e.to.node === to.node && e.to.port === to.port));
  const id = `${from.node}:${from.port}->${to.node}:${to.port}`;
  if (!state.edges.some((e) => e.id === id)) {
    state.edges.push({ id, from: { node: from.node, port: from.port }, to: { node: to.node, port: to.port } });
  }
  render();
}

/* ------------------------------------------------------------------ */
/* 工具栏                                                             */
/* ------------------------------------------------------------------ */
function addNodeAt(type) {
  const s = stage.getBoundingClientRect();
  const w = NODE_DEFS[type].width;
  const x = (s.width / 2 - state.view.x) / state.view.k - w / 2 + (Math.random() * 60 - 30);
  const y = (s.height / 2 - state.view.y) / state.view.k - 120 + (Math.random() * 60 - 30);
  const node = mkNode(type, x, y, defaultsFor(type));
  state.nodes.push(node);
  render();
  return node;
}
document.getElementById('btn-add-prompt').onclick = () => addNodeAt('prompt');
document.getElementById('btn-add-image').onclick = () => addNodeAt('image');
document.getElementById('btn-add-video').onclick = () => addNodeAt('video');
document.getElementById('btn-fit').onclick = fitView;
document.getElementById('btn-demo').onclick = () => { starter(); render(); setTimeout(fitView, 30); };
document.getElementById('btn-clear').onclick = () => {
  if (!confirm('清空当前工作台？（本地缓存也会被清掉）')) return;
  state.nodes = []; state.edges = [];
  render(); fitView();
};

function fillDatalists() {
  document.getElementById('image-models').innerHTML = state.models.image.map((m) => `<option value="${m}"></option>`).join('');
  document.getElementById('video-models').innerHTML = state.models.video.map((m) => `<option value="${m}"></option>`).join('');
}

/* ------------------------------------------------------------------ */
/* 启动                                                               */
/* ------------------------------------------------------------------ */
async function boot() {
  try {
    const m = await fetch('/api/models').then((r) => r.json());
    state.models = m;
    statusEl.textContent = 'API: ' + String(m.base_url || '').replace('https://', '');
    statusEl.classList.add('ok');
  } catch (e) {
    statusEl.textContent = 'API 未连接';
    statusEl.classList.add('bad');
  }
  fillDatalists();
  if (!load()) starter();
  render();
  setTimeout(fitView, 60);
  window.addEventListener('resize', () => renderEdges());
}
boot();
