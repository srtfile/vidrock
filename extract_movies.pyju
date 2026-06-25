#!/usr/bin/env python3
"""
Vidrock embed resolver - prints only unique stream URLs.
Usage: python extract_movies.py [url]
       python extract_movies.py --serve
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests

try:
    from Crypto.Cipher import AES
except Exception:
    AES = None


DEFAULT_TEST_URL = "https://vidrock.ru/embed/movie/254"
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


def browser_headers(referer: Optional[str] = None, origin: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    return headers


def pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len]) * pad_len


def base64url_no_padding(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii").replace("+", "-").replace("/", "_").rstrip("=")


def encode_vidrock_id(tmdb_id: str, media_type: str = "movie", season: Optional[str] = None, episode: Optional[str] = None) -> str:
    if AES is None:
        raise RuntimeError("pycryptodome required: pip install pycryptodome")
    plain = f"{tmdb_id}_{season}_{episode}" if media_type == "tv" else str(tmdb_id)
    cipher = AES.new(VIDROCK_AES_KEY, AES.MODE_CBC, VIDROCK_AES_IV)
    return base64url_no_padding(cipher.encrypt(pkcs7_pad(plain.encode("utf-8"))))


def parse_input_url(input_url: str) -> Dict[str, Optional[str]]:
    parsed = urlparse(input_url)
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)
    parts = [p for p in path.split("/") if p]

    media_type = None
    tmdb_id = None
    season = None
    episode = None

    if "movie" in parts:
        media_type = "movie"
        idx = parts.index("movie")
        if len(parts) > idx + 1:
            tmdb_id = parts[idx + 1]
    elif "tv" in parts:
        media_type = "tv"
        idx = parts.index("tv")
        if len(parts) > idx + 1:
            tmdb_id = parts[idx + 1]
        if len(parts) > idx + 2:
            season = parts[idx + 2]
        if len(parts) > idx + 3:
            episode = parts[idx + 3]

    season = season or (query.get("s") or query.get("season") or [None])[0]
    episode = episode or (query.get("e") or query.get("episode") or [None])[0]

    return {
        "media_type": media_type,
        "tmdb_id": tmdb_id,
        "season": season,
        "episode": episode,
        "host": parsed.netloc,
    }


def print_stream_urls(result: Dict[str, Any]) -> None:
    """Print only unique, clean stream URLs to stdout."""
    seen = set()

    # Collect master + quality HLS, MP4, DASH — skip json_playlist duplicates if direct URLs exist
    # Priority: master m3u8 first, then quality variants, then mp4
    masters = []
    variants = []
    mp4s = []
    other = []

    for entry in result.get("final_media_urls", []):
        url = entry.get("url", "")
        kind = entry.get("kind", "")
        if not url or url in seen:
            continue
        seen.add(url)

        if kind == "json_playlist":
            continue  # skip playlist API endpoints, we already expanded them
        elif kind == "hls":
            path = urlparse(url).path.lower()
            if "master" in path or path.endswith("master.m3u8"):
                masters.append(url)
            else:
                variants.append(url)
        elif kind == "mp4":
            # prefer decoded target if available
            decoded = entry.get("decoded_target_url")
            mp4s.append(decoded if decoded else url)
        else:
            other.append(url)

    all_urls = masters + variants + mp4s + other
    # Final dedup (decoded targets may duplicate)
    final_seen = set()
    for url in all_urls:
        if url not in final_seen:
            final_seen.add(url)
            print(url)

    # Print errors to stderr only
    for err in result.get("errors", []):
        print(f"[ERROR] {err}", file=sys.stderr)


@dataclass
class Resolver:
    capture_dir: Path = field(default_factory=lambda: Path.cwd())
    timeout: float = 15.0
    use_browser_fallback: bool = False

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(browser_headers())

    def request_json(self, url, steps, referer=None, origin=None, allow_text_json=True):
        start = now_ms()
        try:
            res = self.session.get(url, headers=browser_headers(referer, origin), timeout=self.timeout, allow_redirects=True)
            steps.append({"action": "GET_JSON", "url": url, "status_code": res.status_code, "elapsed_ms": now_ms() - start})
            if res.status_code in (401, 403, 429):
                return None, f"blocked_http_{res.status_code}"
            if res.status_code >= 400:
                return None, f"http_{res.status_code}"
            try:
                return res.json(), None
            except ValueError:
                if allow_text_json:
                    decoded = self.decode_possible_base64_json(res.text.strip())
                    if decoded is not None:
                        return decoded, None
                return None, "response_not_json"
        except requests.RequestException as exc:
            steps.append({"action": "GET_JSON", "url": url, "error": str(exc), "elapsed_ms": now_ms() - start})
            return None, str(exc)

    def request_text(self, url, steps, referer=None, origin=None):
        start = now_ms()
        try:
            res = self.session.get(url, headers=browser_headers(referer, origin), timeout=self.timeout, allow_redirects=True)
            content_type = res.headers.get("content-type")
            steps.append({"action": "GET_TEXT", "url": url, "status_code": res.status_code, "elapsed_ms": now_ms() - start})
            if res.status_code in (401, 403, 429):
                return None, content_type, f"blocked_http_{res.status_code}"
            if res.status_code >= 400:
                return None, content_type, f"http_{res.status_code}"
            return res.text, content_type, None
        except requests.RequestException as exc:
            steps.append({"action": "GET_TEXT", "url": url, "error": str(exc), "elapsed_ms": now_ms() - start})
            return None, None, str(exc)

    @staticmethod
    def decode_possible_base64_json(text):
        try:
            decoded = base64.b64decode(text + "=" * (-len(text) % 4)).decode("utf-8")
            return json.loads(decoded)
        except Exception:
            return None

    def resolve(self, input_url: str, use_capture_fallback: bool = True) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []
        errors: List[str] = []
        parsed = parse_input_url(input_url)
        media_type = parsed["media_type"]
        tmdb_id = parsed["tmdb_id"]
        season = parsed["season"]
        episode = parsed["episode"]

        result: Dict[str, Any] = {
            "status": "started",
            "original_url": input_url,
            "input": parsed,
            "tokens_or_ids": {},
            "source_servers": [],
            "iframe_player_urls": [],
            "final_media_urls": [],
            "subtitles": [],
            "request_steps": steps,
            "errors": errors,
            "blocked": False,
            "notes": [],
        }

        if not media_type or not tmdb_id:
            result["status"] = "error"
            errors.append("Could not parse media type and TMDB id from input URL.")
            return result

        embed_url = input_url
        if "vidrock.ru" in (parsed["host"] or ""):
            text, _ctype, err = self.request_text(input_url, steps)
            if err:
                errors.append(f"embed_request_failed: {err}")
            else:
                for found in MEDIA_RE.findall(text or ""):
                    self.add_media(result, found, "embed_html")

        try:
            token = encode_vidrock_id(tmdb_id, media_type, season, episode)
            result["tokens_or_ids"].update({
                "tmdb_id": tmdb_id, "media_type": media_type,
                "season": season, "episode": episode,
                "vidrock_api_token": token,
            })
        except Exception as exc:
            result["status"] = "error"
            errors.append(str(exc))
            return result

        if media_type == "movie":
            stats_url = f"{STATS_API}/movie/{tmdb_id}"
            api_url = f"{VIDROCK_API}/movie/{quote(token)}"
            sub_urls = [f"{SUB_API}/v2/movie/{tmdb_id}", f"{SUB_API}/v1/movie/{tmdb_id}"]
            tmdb_urls = [f"{TMDB_API}/movie/{tmdb_id}?api_key={TMDB_API_KEY}"]
        else:
            stats_url = f"{STATS_API}/tv/{tmdb_id}/{season or 1}/{episode or 1}"
            api_url = f"{VIDROCK_API}/tv/{quote(token)}"
            sub_urls = [
                f"{SUB_API}/v2/tv/{tmdb_id}/{season or 1}/{episode or 1}",
                f"{SUB_API}/v1/tv/{tmdb_id}/{season or 1}/{episode or 1}",
            ]
            tmdb_urls = [f"{TMDB_API}/tv/{tmdb_id}?api_key={TMDB_API_KEY}"]

        result["tokens_or_ids"]["source_api_url"] = api_url

        self.request_json(stats_url, steps, referer="https://vidrock.ru/")
        for tmdb_url in tmdb_urls:
            data, err = self.request_json(tmdb_url, steps)
            if data and isinstance(data, dict) and data.get("id"):
                break

        sources, err = self.request_json(api_url, steps, referer=embed_url)
        if err:
            errors.append(f"source_api_failed: {err}")
            cached = self.capture_lookup_by_token(token) if use_capture_fallback else None
            if cached is not None:
                sources = cached

        if isinstance(sources, dict):
            for name, info in sources.items():
                if not isinstance(info, dict) or not info.get("url"):
                    continue
                source = {
                    "name": name, "url": info.get("url"),
                    "language": info.get("language"), "flag": info.get("flag"), "type": info.get("type"),
                }
                result["source_servers"].append(source)
                self.add_media(result, source["url"], f"source:{name}", source_type=info.get("type"))

                if info.get("type") == "mp4" and "hellstorm.lol/playlist/" in str(info.get("url")):
                    self.expand_json_provider(info["url"], result, referer="https://vidrock.ru/")
                elif str(info.get("url", "")).lower().endswith(".m3u8"):
                    self.probe_hls(info["url"], result, referer="https://vidrock.ru/", origin="https://vidrock.ru")

        for sub_url in sub_urls:
            data, err = self.request_json(sub_url, steps, referer="https://vidrock.ru/", origin="https://vidrock.ru")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("file"):
                        result["subtitles"].append({"label": item.get("label"), "url": item.get("file")})
                break

        result["source_servers"] = unique(result["source_servers"])
        result["final_media_urls"] = unique(result["final_media_urls"])
        result["subtitles"] = unique(result["subtitles"])

        if result["final_media_urls"]:
            result["status"] = "ok"
        elif errors:
            result["status"] = "partial" if result["source_servers"] else "error"
            result["blocked"] = any("blocked" in e or "403" in e or "429" in e for e in errors)
        else:
            result["status"] = "no_media_found"
        return result

    def add_media(self, result, url, source, source_type=None):
        if not url:
            return
        clean_url = url.strip()
        parsed = urlparse(clean_url)
        decoded_path = unquote(parsed.path)
        decoded_target_path = urlparse(decoded_path.lstrip("/")).path if decoded_path.lstrip("/").startswith("http") else decoded_path
        ext = Path(parsed.path).suffix.lower().lstrip(".")
        decoded_ext = Path(decoded_target_path).suffix.lower().lstrip(".")
        if (
            ext not in {"m3u8", "mpd", "mp4", "m4v", "webm", "vtt"}
            and decoded_ext not in {"m3u8", "mpd", "mp4", "m4v", "webm", "vtt"}
            and "playlist" not in parsed.path
        ):
            return
        kind = source_type or self.media_kind(clean_url)
        if "/playlist/" in parsed.path and not parsed.path.lower().endswith((".m3u8", ".mpd")):
            kind = "json_playlist"
        elif decoded_ext in {"mp4", "m4v", "webm"}:
            kind = "mp4"
        entry = {"url": clean_url, "kind": kind, "source": source}
        if parsed.netloc.startswith("dreadnought.") and "/" in parsed.path:
            decoded_target = unquote(parsed.path.lstrip("/"))
            if decoded_target.startswith("http"):
                entry["decoded_target_url"] = decoded_target
        result["final_media_urls"].append(entry)

    @staticmethod
    def media_kind(url):
        path = urlparse(url).path.lower()
        if path.endswith(".m3u8"):
            return "hls"
        if path.endswith(".mpd"):
            return "dash"
        if path.endswith((".mp4", ".m4v", ".webm")):
            return "mp4"
        if path.endswith(".vtt"):
            return "subtitle"
        if "/playlist/" in path:
            return "json_playlist"
        return "resource"

    def expand_json_provider(self, url, result, referer):
        data, err = self.request_json(url, result["request_steps"], referer=referer, origin="https://vidrock.ru")
        if err:
            result["errors"].append(f"json_provider_failed: {url}: {err}")
            return []
        variants = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("url"):
                    variants.append({"resolution": item.get("resolution"), "url": item["url"]})
                    self.add_media(result, item["url"], "json_provider:hellstorm", source_type="mp4")
        return variants

    def probe_hls(self, url, result, referer, origin):
        text, _ctype, err = self.request_text(url, result["request_steps"], referer=referer, origin=origin)
        if err:
            result["errors"].append(f"hls_probe_failed: {url}: {err}")
            return
        if not text:
            return
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            child_url = urljoin(url, line)
            self.add_media(result, child_url, f"hls_child:{url}", source_type="hls" if ".m3u8" in child_url.lower() else None)

    def capture_lookup_by_token(self, token):
        response_dir = self.capture_dir / "xhr_responses"
        if not response_dir.exists():
            return None
        for path in response_dir.glob(f"vidrock.ru_{token}.json"):
            try:
                return json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                return None
        return None


def serve_api(resolver: Resolver, host: str, port: int) -> None:
    try:
        from flask import Flask, jsonify, request
    except Exception as exc:
        raise RuntimeError(f"Flask required: pip install flask ({exc})")

    app = Flask(__name__)

    @app.get("/resolve")
    def resolve_endpoint():
        url = request.args.get("url") or DEFAULT_TEST_URL
        result = resolver.resolve(url)
        # Return only stream URLs as JSON array
        seen = set()
        urls = []
        for entry in result.get("final_media_urls", []):
            if entry.get("kind") == "json_playlist":
                continue
            u = entry.get("decoded_target_url") or entry.get("url", "")
            if u and u not in seen:
                seen.add(u)
                urls.append({"url": u, "kind": entry.get("kind"), "source": entry.get("source")})
        return jsonify({"status": result["status"], "stream_urls": urls, "errors": result["errors"]})

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    app.run(host=host, port=port, debug=False)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve Vidrock embed URLs, print stream URLs only.")
    parser.add_argument("url", nargs="?", default=DEFAULT_TEST_URL)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--json", action="store_true", help="Output as JSON array instead of plain URLs")
    parser.add_argument("--no-capture-fallback", action="store_true")
    parser.add_argument("--capture-dir", default=os.getcwd())
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    resolver = Resolver(Path(args.capture_dir), timeout=args.timeout)

    if args.serve:
        print(f"Starting API at http://{args.host}:{args.port}", file=sys.stderr)
        serve_api(resolver, args.host, args.port)
        return 0

    result = resolver.resolve(args.url, use_capture_fallback=not args.no_capture_fallback)

    if args.json:
        seen = set()
        urls = []
        for entry in result.get("final_media_urls", []):
            if entry.get("kind") == "json_playlist":
                continue
            u = entry.get("decoded_target_url") or entry.get("url", "")
            if u and u not in seen:
                seen.add(u)
                urls.append({"url": u, "kind": entry.get("kind"), "source": entry.get("source")})
        print(json.dumps({"status": result["status"], "stream_urls": urls, "errors": result["errors"]}, indent=2))
    else:
        print_stream_urls(result)

    return 0 if result.get("status") in {"ok", "partial", "no_media_found"} else 1


if __name__ == "__main__":
    raise SystemExit(main())