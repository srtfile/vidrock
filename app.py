#!/usr/bin/env python3
"""
Vidrock Stream Resolver — Flask web app + API
Deploy to Render: Start Command = gunicorn app:app
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests
from flask import Flask, jsonify, render_template_string, request

try:
    from Crypto.Cipher import AES
except Exception:
    AES = None

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_URL = "https://vidrock.ru/embed/movie/254"
VIDROCK_API = "https://vidrock.ru/api"
SUB_API = "https://sub.vdrk.site"
STATS_API = "https://stats.vidrock.ru"
TMDB_API = "https://api.themoviedb.org/3"
TMDB_API_KEY = "54e00466a09676df57ba51c4ca30b1a6"
VIDROCK_AES_KEY = b"x7k9mPqT2rWvY8zA5bC3nF6hJ2lK4mN9"
VIDROCK_AES_IV = VIDROCK_AES_KEY[:16]
MEDIA_RE = re.compile(
    r"https?://[^\s\"'<>\\]+?\.(?:m3u8|mpd|mp4|m4v|webm|vtt)(?:\?[^\s\"'<>\\]*)?",
    re.IGNORECASE,
)

# ── HTML Template ────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vidrock Resolver</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap');

  :root {
    --bg: #0a0a0f;
    --surface: #111118;
    --border: #1e1e2e;
    --accent: #7c6af7;
    --accent2: #a78bfa;
    --green: #22d3a0;
    --red: #f87171;
    --amber: #fbbf24;
    --text: #e2e2f0;
    --muted: #6b6b8a;
    --mono: 'Space Mono', monospace;
    --sans: 'Space Grotesk', sans-serif;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    min-height: 100vh;
    line-height: 1.6;
  }

  /* ── Header ── */
  header {
    border-bottom: 1px solid var(--border);
    padding: 18px 32px;
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--surface);
  }

  .logo-mark {
    width: 32px; height: 32px;
    background: linear-gradient(135deg, var(--accent), var(--green));
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 16px;
  }

  header h1 {
    font-size: 16px;
    font-weight: 600;
    letter-spacing: 0.02em;
  }

  header .tag {
    margin-left: auto;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    background: var(--border);
    padding: 3px 8px;
    border-radius: 4px;
  }

  /* ── Main layout ── */
  main {
    max-width: 860px;
    margin: 0 auto;
    padding: 48px 24px;
  }

  .hero {
    margin-bottom: 40px;
  }

  .hero h2 {
    font-size: 36px;
    font-weight: 700;
    line-height: 1.15;
    letter-spacing: -0.02em;
    background: linear-gradient(135deg, var(--text) 40%, var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 10px;
  }

  .hero p {
    color: var(--muted);
    font-size: 15px;
  }

  /* ── Input card ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 24px;
  }

  .input-row {
    display: flex;
    gap: 10px;
  }

  input[type="text"] {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-family: var(--mono);
    font-size: 13px;
    padding: 12px 14px;
    outline: none;
    transition: border-color 0.2s;
  }

  input[type="text"]:focus {
    border-color: var(--accent);
  }

  input[type="text"]::placeholder { color: var(--muted); }

  button {
    background: var(--accent);
    border: none;
    border-radius: 8px;
    color: #fff;
    cursor: pointer;
    font-family: var(--sans);
    font-size: 14px;
    font-weight: 600;
    padding: 12px 22px;
    transition: opacity 0.2s, transform 0.1s;
    white-space: nowrap;
  }

  button:hover { opacity: 0.88; }
  button:active { transform: scale(0.97); }
  button:disabled { opacity: 0.4; cursor: not-allowed; }

  .examples {
    margin-top: 12px;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }

  .example-chip {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--mono);
    font-size: 11px;
    padding: 4px 10px;
    transition: border-color 0.2s, color 0.2s;
  }

  .example-chip:hover {
    border-color: var(--accent);
    color: var(--accent2);
  }

  /* ── Status bar ── */
  #status-bar {
    display: none;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 20px;
    font-size: 13px;
    font-family: var(--mono);
  }

  #status-bar.loading {
    display: flex;
    background: rgba(124,106,247,0.08);
    border: 1px solid rgba(124,106,247,0.2);
    color: var(--accent2);
  }

  #status-bar.error {
    display: flex;
    background: rgba(248,113,113,0.08);
    border: 1px solid rgba(248,113,113,0.2);
    color: var(--red);
  }

  .spinner {
    width: 14px; height: 14px;
    border: 2px solid rgba(124,106,247,0.3);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    flex-shrink: 0;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Results ── */
  #results { display: none; }

  .result-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }

  .result-header h3 {
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
  }

  .result-meta {
    display: flex;
    gap: 10px;
    align-items: center;
  }

  .badge {
    font-family: var(--mono);
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 4px;
    font-weight: 700;
  }

  .badge.ok { background: rgba(34,211,160,0.12); color: var(--green); }
  .badge.error { background: rgba(248,113,113,0.12); color: var(--red); }
  .badge.partial { background: rgba(251,191,36,0.12); color: var(--amber); }

  .copy-all {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted);
    font-size: 12px;
    padding: 5px 12px;
  }

  .copy-all:hover { border-color: var(--accent); color: var(--accent2); opacity: 1; }

  /* ── URL list ── */
  .section-label {
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--muted);
    margin: 20px 0 8px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .section-label::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }

  .url-item {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 6px;
    display: flex;
    align-items: stretch;
    overflow: hidden;
    transition: border-color 0.15s;
  }

  .url-item:hover { border-color: #2e2e45; }

  .url-kind {
    background: var(--border);
    color: var(--muted);
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.08em;
    min-width: 52px;
    display: flex;
    align-items: center;
    justify-content: center;
    text-transform: uppercase;
    flex-shrink: 0;
  }

  .url-kind.hls { color: var(--accent2); background: rgba(124,106,247,0.08); }
  .url-kind.mp4 { color: var(--green); background: rgba(34,211,160,0.08); }
  .url-kind.dash { color: var(--amber); background: rgba(251,191,36,0.08); }

  .url-text {
    font-family: var(--mono);
    font-size: 12px;
    padding: 10px 12px;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text);
    line-height: 1.4;
    cursor: text;
    user-select: all;
  }

  .url-actions {
    display: flex;
    align-items: center;
    gap: 0;
    flex-shrink: 0;
  }

  .url-btn {
    background: transparent;
    border: none;
    border-left: 1px solid var(--border);
    border-radius: 0;
    color: var(--muted);
    cursor: pointer;
    font-size: 12px;
    height: 100%;
    padding: 0 14px;
    transition: background 0.15s, color 0.15s;
  }

  .url-btn:hover { background: var(--border); color: var(--text); opacity: 1; }
  .url-btn.copied { color: var(--green); }

  /* ── Subtitles ── */
  .sub-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 6px;
    font-size: 13px;
  }

  .sub-lang {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    min-width: 80px;
  }

  .sub-url {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--accent2);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* ── Errors ── */
  .err-item {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--red);
    padding: 8px 12px;
    background: rgba(248,113,113,0.06);
    border: 1px solid rgba(248,113,113,0.15);
    border-radius: 6px;
    margin-bottom: 6px;
  }

  /* ── API docs ── */
  .api-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px;
    margin-top: 40px;
  }

  .api-card h3 {
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
    margin-bottom: 14px;
  }

  .endpoint {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
    font-family: var(--mono);
    font-size: 12px;
  }

  .method {
    background: rgba(34,211,160,0.1);
    color: var(--green);
    font-size: 10px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 4px;
    flex-shrink: 0;
  }

  .endpoint-url { color: var(--text); }
  .endpoint-desc { color: var(--muted); font-size: 11px; margin-left: auto; }

  @media (max-width: 600px) {
    main { padding: 32px 16px; }
    .hero h2 { font-size: 26px; }
    .input-row { flex-direction: column; }
    .endpoint-desc { display: none; }
  }
</style>
</head>
<body>

<header>
  <div class="logo-mark">▶</div>
  <h1>Vidrock Resolver</h1>
  <span class="tag">v1.0</span>
</header>

<main>
  <div class="hero">
    <h2>Extract stream URLs<br>from any embed.</h2>
    <p>Paste a Vidrock embed URL to get direct HLS, DASH, and MP4 stream links.</p>
  </div>

  <div class="card">
    <div class="input-row">
      <input type="text" id="url-input" placeholder="https://vidrock.ru/embed/movie/254" value="">
      <button id="resolve-btn" onclick="resolve()">Resolve</button>
    </div>
    <div class="examples">
      <span style="font-size:11px;color:var(--muted);align-self:center;">Try:</span>
      <button class="example-chip" onclick="setUrl('https://vidrock.ru/embed/movie/254')">movie/254 · King Kong</button>
      <button class="example-chip" onclick="setUrl('https://vidrock.ru/embed/movie/550')">movie/550 · Fight Club</button>
      <button class="example-chip" onclick="setUrl('https://vidrock.ru/embed/tv/1399/1/1')">tv/1399 · GoT S1E1</button>
    </div>
  </div>

  <div id="status-bar">
    <div class="spinner" id="spinner"></div>
    <span id="status-text">Resolving…</span>
  </div>

  <div id="results">
    <div class="result-header">
      <h3>Stream URLs</h3>
      <div class="result-meta">
        <span id="status-badge" class="badge"></span>
        <button class="copy-all" onclick="copyAll()">Copy all</button>
      </div>
    </div>

    <div id="title-row" style="margin-bottom:16px;display:none;">
      <span style="font-size:13px;color:var(--muted);">Title: </span>
      <span id="title-text" style="font-size:13px;font-weight:600;"></span>
      <span id="imdb-text" style="font-size:12px;color:var(--muted);margin-left:8px;font-family:var(--mono);"></span>
    </div>

    <div id="hls-section" style="display:none;">
      <div class="section-label">HLS streams</div>
      <div id="hls-list"></div>
    </div>

    <div id="mp4-section" style="display:none;">
      <div class="section-label">MP4 streams</div>
      <div id="mp4-list"></div>
    </div>

    <div id="dash-section" style="display:none;">
      <div class="section-label">DASH streams</div>
      <div id="dash-list"></div>
    </div>

    <div id="sub-section" style="display:none;">
      <div class="section-label">Subtitles</div>
      <div id="sub-list"></div>
    </div>

    <div id="err-section" style="display:none;">
      <div class="section-label">Errors</div>
      <div id="err-list"></div>
    </div>
  </div>

  <div class="api-card">
    <h3>API</h3>
    <div class="endpoint">
      <span class="method">GET</span>
      <span class="endpoint-url">/api/resolve?url=EMBED_URL</span>
      <span class="endpoint-desc">JSON: stream_urls array</span>
    </div>
    <div class="endpoint">
      <span class="method">GET</span>
      <span class="endpoint-url">/api/plain?url=EMBED_URL</span>
      <span class="endpoint-desc">Plain text, one URL per line</span>
    </div>
    <div class="endpoint">
      <span class="method">GET</span>
      <span class="endpoint-url">/health</span>
      <span class="endpoint-desc">Health check</span>
    </div>
  </div>
</main>

<script>
let allUrls = [];

function setUrl(u) {
  document.getElementById('url-input').value = u;
  document.getElementById('url-input').focus();
}

async function resolve() {
  const url = document.getElementById('url-input').value.trim();
  if (!url) return;

  const btn = document.getElementById('resolve-btn');
  btn.disabled = true;

  const bar = document.getElementById('status-bar');
  bar.className = 'loading';
  document.getElementById('spinner').style.display = '';
  document.getElementById('status-text').textContent = 'Resolving…';

  document.getElementById('results').style.display = 'none';
  allUrls = [];

  try {
    const res = await fetch('/api/resolve?url=' + encodeURIComponent(url));
    const data = await res.json();
    bar.style.display = 'none';
    render(data);
  } catch(e) {
    bar.className = 'error';
    document.getElementById('spinner').style.display = 'none';
    document.getElementById('status-text').textContent = 'Request failed: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

function render(data) {
  const results = document.getElementById('results');
  results.style.display = 'block';

  // Badge
  const badge = document.getElementById('status-badge');
  badge.textContent = data.status;
  badge.className = 'badge ' + (data.status === 'ok' ? 'ok' : data.status === 'partial' ? 'partial' : 'error');

  // Title
  const titleRow = document.getElementById('title-row');
  if (data.title) {
    document.getElementById('title-text').textContent = data.title;
    document.getElementById('imdb-text').textContent = data.imdb_id ? '· ' + data.imdb_id : '';
    titleRow.style.display = 'block';
  } else {
    titleRow.style.display = 'none';
  }

  const hls = [], mp4 = [], dash = [];
  for (const entry of data.stream_urls || []) {
    allUrls.push(entry.url);
    if (entry.kind === 'hls') hls.push(entry);
    else if (entry.kind === 'mp4') mp4.push(entry);
    else if (entry.kind === 'dash') dash.push(entry);
    else hls.push(entry);
  }

  renderSection('hls', hls);
  renderSection('mp4', mp4);
  renderSection('dash', dash);

  // Subtitles
  const subList = document.getElementById('sub-list');
  const subSection = document.getElementById('sub-section');
  subList.innerHTML = '';
  if (data.subtitles && data.subtitles.length) {
    subSection.style.display = 'block';
    for (const s of data.subtitles) {
      const d = document.createElement('div');
      d.className = 'sub-item';
      d.innerHTML = `<span class="sub-lang">${esc(s.label || '?')}</span><span class="sub-url">${esc(s.url)}</span><button class="url-btn" onclick="copyUrl(this, '${esc(s.url)}')">Copy</button>`;
      subList.appendChild(d);
    }
  } else {
    subSection.style.display = 'none';
  }

  // Errors
  const errList = document.getElementById('err-list');
  const errSection = document.getElementById('err-section');
  errList.innerHTML = '';
  if (data.errors && data.errors.length) {
    errSection.style.display = 'block';
    for (const e of data.errors) {
      const d = document.createElement('div');
      d.className = 'err-item';
      d.textContent = e;
      errList.appendChild(d);
    }
  } else {
    errSection.style.display = 'none';
  }
}

function renderSection(type, items) {
  const list = document.getElementById(type + '-list');
  const section = document.getElementById(type + '-section');
  list.innerHTML = '';
  if (!items.length) { section.style.display = 'none'; return; }
  section.style.display = 'block';
  for (const entry of items) {
    const isMaster = entry.url.includes('master') || (!entry.url.includes('720') && !entry.url.includes('480') && !entry.url.includes('360') && !entry.url.includes('1080'));
    const d = document.createElement('div');
    d.className = 'url-item';
    const kindLabel = entry.kind === 'hls' ? (isMaster ? 'master' : 'hls') : entry.kind;
    d.innerHTML = `
      <span class="url-kind ${entry.kind}">${esc(kindLabel)}</span>
      <span class="url-text" title="${esc(entry.url)}">${esc(entry.url)}</span>
      <div class="url-actions">
        <button class="url-btn" onclick="copyUrl(this, '${esc(entry.url)}')">Copy</button>
        <button class="url-btn" onclick="window.open('${esc(entry.url)}','_blank')">Open</button>
      </div>`;
    list.appendChild(d);
  }
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

async function copyUrl(btn, url) {
  try {
    await navigator.clipboard.writeText(url);
    btn.textContent = '✓';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 1500);
  } catch(e) {}
}

async function copyAll() {
  if (!allUrls.length) return;
  try {
    await navigator.clipboard.writeText(allUrls.join('\\n'));
    const btn = document.querySelector('.copy-all');
    btn.textContent = '✓ Copied';
    setTimeout(() => btn.textContent = 'Copy all', 1800);
  } catch(e) {}
}

document.getElementById('url-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') resolve();
});
</script>
</body>
</html>"""

# ── Helpers ──────────────────────────────────────────────────────────────────

def now_ms() -> int:
    return int(time.time() * 1000)


def unique(items: Iterable[Any]) -> List[Any]:
    seen = set()
    out = []
    for item in items:
        key = json.dumps(item, sort_keys=True, default=str) if isinstance(item, dict) else str(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def browser_headers(referer=None, origin=None):
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer: h["Referer"] = referer
    if origin: h["Origin"] = origin
    return h


def pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len]) * pad_len


def base64url_no_padding(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii").replace("+", "-").replace("/", "_").rstrip("=")


def encode_vidrock_id(tmdb_id, media_type="movie", season=None, episode=None):
    if AES is None:
        raise RuntimeError("pycryptodome required")
    plain = f"{tmdb_id}_{season}_{episode}" if media_type == "tv" else str(tmdb_id)
    cipher = AES.new(VIDROCK_AES_KEY, AES.MODE_CBC, VIDROCK_AES_IV)
    return base64url_no_padding(cipher.encrypt(pkcs7_pad(plain.encode())))


def parse_input_url(input_url):
    parsed = urlparse(input_url)
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)
    parts = [p for p in path.split("/") if p]
    media_type = tmdb_id = season = episode = None

    if "movie" in parts:
        media_type = "movie"
        idx = parts.index("movie")
        if len(parts) > idx + 1: tmdb_id = parts[idx + 1]
    elif "tv" in parts:
        media_type = "tv"
        idx = parts.index("tv")
        if len(parts) > idx + 1: tmdb_id = parts[idx + 1]
        if len(parts) > idx + 2: season = parts[idx + 2]
        if len(parts) > idx + 3: episode = parts[idx + 3]

    season = season or (query.get("s") or query.get("season") or [None])[0]
    episode = episode or (query.get("e") or query.get("episode") or [None])[0]
    return {"media_type": media_type, "tmdb_id": tmdb_id, "season": season, "episode": episode, "host": parsed.netloc}

# ── Resolver ──────────────────────────────────────────────────────────────────

@dataclass
class Resolver:
    timeout: float = 20.0

    def __post_init__(self):
        self.session = requests.Session()
        self.session.headers.update(browser_headers())

    def get_json(self, url, steps, referer=None, origin=None):
        start = now_ms()
        try:
            res = self.session.get(url, headers=browser_headers(referer, origin), timeout=self.timeout, allow_redirects=True)
            steps.append({"url": url, "status": res.status_code, "ms": now_ms() - start})
            if res.status_code in (401, 403, 429): return None, f"blocked_{res.status_code}"
            if res.status_code >= 400: return None, f"http_{res.status_code}"
            try:
                return res.json(), None
            except ValueError:
                try:
                    dec = base64.b64decode(res.text.strip() + "=" * (-len(res.text.strip()) % 4)).decode()
                    return json.loads(dec), None
                except Exception:
                    return None, "not_json"
        except requests.RequestException as e:
            steps.append({"url": url, "error": str(e), "ms": now_ms() - start})
            return None, str(e)

    def get_text(self, url, steps, referer=None, origin=None):
        start = now_ms()
        try:
            res = self.session.get(url, headers=browser_headers(referer, origin), timeout=self.timeout, allow_redirects=True)
            steps.append({"url": url, "status": res.status_code, "ms": now_ms() - start})
            if res.status_code in (401, 403, 429): return None, f"blocked_{res.status_code}"
            if res.status_code >= 400: return None, f"http_{res.status_code}"
            return res.text, None
        except requests.RequestException as e:
            steps.append({"url": url, "error": str(e), "ms": now_ms() - start})
            return None, str(e)

    def add_media(self, result, url, source, source_type=None):
        if not url: return
        url = url.strip()
        parsed = urlparse(url)
        decoded_path = unquote(parsed.path)
        dec_target_path = urlparse(decoded_path.lstrip("/")).path if decoded_path.lstrip("/").startswith("http") else decoded_path
        ext = Path(parsed.path).suffix.lower().lstrip(".")
        dec_ext = Path(dec_target_path).suffix.lower().lstrip(".")
        if (ext not in {"m3u8","mpd","mp4","m4v","webm","vtt"}
                and dec_ext not in {"m3u8","mpd","mp4","m4v","webm","vtt"}
                and "playlist" not in parsed.path):
            return
        kind = source_type or self.media_kind(url)
        if "/playlist/" in parsed.path and not parsed.path.lower().endswith((".m3u8",".mpd")):
            kind = "json_playlist"
        elif dec_ext in {"mp4","m4v","webm"}:
            kind = "mp4"
        entry = {"url": url, "kind": kind, "source": source}
        if parsed.netloc.startswith("dreadnought.") and "/" in parsed.path:
            dec = unquote(parsed.path.lstrip("/"))
            if dec.startswith("http"): entry["decoded_target_url"] = dec
        result["final_media_urls"].append(entry)

    @staticmethod
    def media_kind(url):
        p = urlparse(url).path.lower()
        if p.endswith(".m3u8"): return "hls"
        if p.endswith(".mpd"): return "dash"
        if p.endswith((".mp4",".m4v",".webm")): return "mp4"
        if p.endswith(".vtt"): return "subtitle"
        if "/playlist/" in p: return "json_playlist"
        return "resource"

    def probe_hls(self, url, result, referer, origin):
        text, err = self.get_text(url, result["steps"], referer, origin)
        if err or not text: return
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            self.add_media(result, urljoin(url, line), f"hls_child:{url}",
                           source_type="hls" if ".m3u8" in line.lower() else None)

    def expand_hellstorm(self, url, result, referer):
        data, err = self.get_json(url, result["steps"], referer, "https://vidrock.ru")
        if err: result["errors"].append(f"hellstorm_failed: {err}"); return
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("url"):
                    self.add_media(result, item["url"], "hellstorm", "mp4")

    def resolve(self, input_url: str) -> Dict[str, Any]:
        steps: List[Dict] = []
        errors: List[str] = []
        parsed = parse_input_url(input_url)
        media_type, tmdb_id = parsed["media_type"], parsed["tmdb_id"]
        season, episode = parsed["season"], parsed["episode"]

        result: Dict[str, Any] = {
            "status": "started", "original_url": input_url, "input": parsed,
            "tokens": {}, "source_servers": [], "final_media_urls": [],
            "subtitles": [], "steps": steps, "errors": errors,
            "title": None, "imdb_id": None,
        }

        if not media_type or not tmdb_id:
            result["status"] = "error"; errors.append("Cannot parse media type/TMDB id from URL"); return result

        # Embed page scrape
        if "vidrock.ru" in (parsed["host"] or ""):
            text, err = self.get_text(input_url, steps)
            if not err:
                for found in MEDIA_RE.findall(text or ""):
                    self.add_media(result, found, "embed_html")

        try:
            token = encode_vidrock_id(tmdb_id, media_type, season, episode)
        except Exception as e:
            result["status"] = "error"; errors.append(str(e)); return result

        result["tokens"]["api_token"] = token

        if media_type == "movie":
            api_url = f"{VIDROCK_API}/movie/{quote(token)}"
            sub_urls = [f"{SUB_API}/v2/movie/{tmdb_id}", f"{SUB_API}/v1/movie/{tmdb_id}"]
            tmdb_url = f"{TMDB_API}/movie/{tmdb_id}?api_key={TMDB_API_KEY}"
        else:
            api_url = f"{VIDROCK_API}/tv/{quote(token)}"
            sub_urls = [f"{SUB_API}/v2/tv/{tmdb_id}/{season or 1}/{episode or 1}",
                        f"{SUB_API}/v1/tv/{tmdb_id}/{season or 1}/{episode or 1}"]
            tmdb_url = f"{TMDB_API}/tv/{tmdb_id}?api_key={TMDB_API_KEY}"

        # TMDB lookup
        tmdb_data, _ = self.get_json(tmdb_url, steps)
        if isinstance(tmdb_data, dict):
            result["title"] = tmdb_data.get("title") or tmdb_data.get("name")
            result["imdb_id"] = tmdb_data.get("imdb_id")

        # Source API
        sources, err = self.get_json(api_url, steps, referer=input_url)
        if err: errors.append(f"source_api: {err}")

        if isinstance(sources, dict):
            for name, info in sources.items():
                if not isinstance(info, dict) or not info.get("url"): continue
                result["source_servers"].append({"name": name, "url": info.get("url"), "type": info.get("type")})
                self.add_media(result, info["url"], f"source:{name}", info.get("type"))
                if info.get("type") == "mp4" and "hellstorm.lol/playlist/" in str(info.get("url")):
                    self.expand_hellstorm(info["url"], result, "https://vidrock.ru/")
                elif str(info.get("url","")).lower().endswith(".m3u8"):
                    self.probe_hls(info["url"], result, "https://vidrock.ru/", "https://vidrock.ru")

        # Subtitles
        for sub_url in sub_urls:
            data, err = self.get_json(sub_url, steps, referer="https://vidrock.ru/", origin="https://vidrock.ru")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("file"):
                        result["subtitles"].append({"label": item.get("label"), "url": item["file"]})
                break

        result["final_media_urls"] = unique(result["final_media_urls"])
        result["subtitles"] = unique(result["subtitles"])

        if result["final_media_urls"]: result["status"] = "ok"
        elif errors: result["status"] = "partial" if result["source_servers"] else "error"
        else: result["status"] = "no_media_found"
        return result


# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
resolver = Resolver()


@app.get("/")
def index():
    return render_template_string(HTML)


@app.get("/api/resolve")
def api_resolve():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url parameter required"}), 400

    result = resolver.resolve(url)

    # Build clean stream list
    seen: set = set()
    stream_urls = []
    for entry in result["final_media_urls"]:
        if entry.get("kind") == "json_playlist":
            continue
        u = entry.get("decoded_target_url") or entry.get("url", "")
        if u and u not in seen:
            seen.add(u)
            stream_urls.append({"url": u, "kind": entry["kind"], "source": entry["source"]})

    return jsonify({
        "status": result["status"],
        "title": result.get("title"),
        "imdb_id": result.get("imdb_id"),
        "stream_urls": stream_urls,
        "subtitles": result["subtitles"],
        "errors": result["errors"],
    })


@app.get("/api/plain")
def api_plain():
    url = request.args.get("url", "").strip()
    if not url:
        return "url parameter required\n", 400
    result = resolver.resolve(url)
    seen: set = set()
    lines = []
    for entry in result["final_media_urls"]:
        if entry.get("kind") == "json_playlist":
            continue
        u = entry.get("decoded_target_url") or entry.get("url", "")
        if u and u not in seen:
            seen.add(u)
            lines.append(u)
    return "\n".join(lines) + "\n", 200, {"Content-Type": "text/plain"}


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8787))
    app.run(host="0.0.0.0", port=port, debug=False)