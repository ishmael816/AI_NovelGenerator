# -*- coding: utf-8 -*-
"""
Outline Reviewer — HTTP API server (stdlib only, zero dependencies).
Serves the review WebUI and REST API for outline annotation, editing, and queue management.
"""
import sys
import os
import json
import uuid
import re
import time
import threading
import mimetypes
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

OUTLINES_DIR = os.path.join(PROJECT_DIR, "output", "outlines")
REVIEW_DIR = os.path.join(PROJECT_DIR, "output", "review")
WEBUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui")

ANNOTATIONS_FILE = os.path.join(REVIEW_DIR, "annotations.json")
EDITS_FILE = os.path.join(REVIEW_DIR, "edits.json")
QUEUE_FILE = os.path.join(REVIEW_DIR, "queue.json")
GENERATE_TASK_FILE = os.path.join(REVIEW_DIR, "generate_task.json")

os.makedirs(REVIEW_DIR, exist_ok=True)

# ── Import batch generator utilities ──
try:
    from batch_outline_generator import call_llm as _bg_call_llm, SYSTEM_PROMPT, THEMES
except ImportError:
    _bg_call_llm = None
    SYSTEM_PROMPT = ""
    THEMES = []

# Section keys derived from ## headers in the outline content
SECTION_KEYS = [
    "书名字", "一句话卖点", "核心设定", "主角人设",
    "三幕结构", "前10章详细大纲", "商业卖点清单", "目标读者画像",
]


def _load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_annotations():
    return _load_json(ANNOTATIONS_FILE, [])


def _save_annotations(data):
    _save_json(ANNOTATIONS_FILE, data)


def _load_edits():
    return _load_json(EDITS_FILE, {})


def _save_edits(data):
    _save_json(EDITS_FILE, data)


def _load_queue():
    return _load_json(QUEUE_FILE, [])


def _save_queue(data):
    _save_json(QUEUE_FILE, data)

def _count_jsonl(path):
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def _parse_outline_sections(content):
    """Parse raw outline markdown into structured sections."""
    sections = {}
    current_key = None
    current_lines = []

    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = stripped[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()

    # Extract book title from 书名字 section (first non-empty line)
    if "书名字" in sections:
        title_text = sections["书名字"].strip()
        # The title is typically the first line
        first_line = title_text.split("\n")[0].strip()
        sections["_title"] = first_line
    else:
        sections["_title"] = ""

    return sections


def _extract_title(content):
    """Extract the book title from content."""
    sections = _parse_outline_sections(content)
    return sections.get("_title", "")


def _get_outlines():
    """Load all outline summaries."""
    outlines = []
    for fn in sorted(os.listdir(OUTLINES_DIR)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(OUTLINES_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        title = _extract_title(data.get("content", ""))
        outlines.append({
            "id": data.get("index", ""),
            "tag": data.get("tag", ""),
            "name": data.get("name", ""),
            "title": title,
            "competition": data.get("competition", ""),
            "market_share": data.get("market_share", ""),
            "references": data.get("references", ""),
        })
    return outlines


def _get_outline_detail(outline_id):
    """Load full outline with parsed sections and edits applied."""
    for fn in sorted(os.listdir(OUTLINES_DIR)):
        if not fn.endswith(".json"):
            continue
        if not fn.startswith(f"outline_{outline_id}_"):
            continue
        path = os.path.join(OUTLINES_DIR, fn)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        original_content = data.get("content", "")
        sections = _parse_outline_sections(original_content)

        # Apply edits if any
        edits = _load_edits()
        outline_edits = edits.get(outline_id, {})
        for section_key, edited_content in outline_edits.items():
            if section_key in sections:
                sections[section_key] = edited_content

        return {
            "id": data.get("index", ""),
            "tag": data.get("tag", ""),
            "name": data.get("name", ""),
            "competition": data.get("competition", ""),
            "market_share": data.get("market_share", ""),
            "references": data.get("references", ""),
            "formula": data.get("formula", ""),
            "sections": sections,
        }
    return None


def _find_outline_json(outline_id):
    """Find the JSON file path for an outline ID."""
    for fn in sorted(os.listdir(OUTLINES_DIR)):
        if fn.endswith(".json") and fn.startswith(f"outline_{outline_id}_"):
            return os.path.join(OUTLINES_DIR, fn)
    return None


# ── Novel Reader helpers ──

NOVEL_OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
IGNORE_DIRS = {"outlines", "review"}


def _get_novel_dirs():
    """List all novel directories under output/."""
    novels = []
    if not os.path.isdir(NOVEL_OUTPUT_DIR):
        return novels
    for name in sorted(os.listdir(NOVEL_OUTPUT_DIR)):
        full = os.path.join(NOVEL_OUTPUT_DIR, name)
        if not os.path.isdir(full) or name in IGNORE_DIRS:
            continue
        novels.append(name)
    return novels


def _get_chapter_files(novel_name):
    """Get sorted list of chapter filenames for a novel."""
    chapters_dir = os.path.join(NOVEL_OUTPUT_DIR, novel_name, "chapters")
    if not os.path.isdir(chapters_dir):
        return []
    files = []
    for fn in os.listdir(chapters_dir):
        m = re.match(r"^chapter_(\d+)\.txt$", fn)
        if m:
            files.append((int(m.group(1)), fn))
    files.sort(key=lambda x: x[0])
    return files


def _parse_directory_titles(novel_name):
    """Parse Novel_directory.txt to extract chapter titles."""
    path = os.path.join(NOVEL_OUTPUT_DIR, novel_name, "Novel_directory.txt")
    if not os.path.isfile(path):
        return {}
    titles = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        for m in re.finditer(r"第(\d+)章\s*[-—]\s*\[?(.+?)\]?(?:\n|$)", content):
            titles[int(m.group(1))] = m.group(2).strip()
    except (IOError, UnicodeDecodeError):
        pass
    return titles


def _read_novel_file(novel_name, filename):
    """Read a text file from a novel directory, return content or None."""
    path = os.path.join(NOVEL_OUTPUT_DIR, novel_name, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (IOError, UnicodeDecodeError):
        return None


class _GenerationTask:
    """Singleton background task manager for outline generation."""

    _current = None

    def __init__(self):
        self.task_id = uuid.uuid4().hex[:8]
        self.status = "idle"
        self.total = 0
        self.completed = 0
        self.current_theme = None
        self.progress_log = []
        self.started_at = None
        self.finished_at = None
        self.error = None
        self._cancelled = False
        self._thread = None
        self._llm_model = "gpt-5.4"
        self._temperature = 0.75
        self._max_tokens = 4096

    @classmethod
    def get_current(cls):
        return cls._current

    @classmethod
    def start_new(cls, themes, model, temperature, max_tokens):
        if cls._current and cls._current.status == "running":
            raise RuntimeError("A generation task is already running")
        task = cls()
        task.total = len(themes)
        task.status = "running"
        task.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task._llm_model = model
        task._temperature = temperature
        task._max_tokens = max_tokens
        task.progress_log = [
            {"theme_id": t.get("id", ""), "name": t.get("name", ""), "status": "pending"}
            for t in themes
        ]
        task._save()
        task._thread = threading.Thread(target=task._run, args=(themes,), daemon=True)
        task._thread.start()
        cls._current = task
        return task

    def cancel(self):
        if self.status != "running":
            return False
        self._cancelled = True
        return True

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "status": self.status,
            "total": self.total,
            "completed": self.completed,
            "current_theme": self.current_theme,
            "progress_log": self.progress_log,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }

    def _save(self):
        _save_json(GENERATE_TASK_FILE, self.to_dict())

    def _fill_defaults(self, theme):
        """Fill missing fields from preset THEMES."""
        for preset in THEMES:
            if preset["id"] == theme.get("id"):
                for key in ["tag", "name", "market_share", "competition", "formula", "references", "prompt_seed"]:
                    if key not in theme or not theme.get(key):
                        theme[key] = preset.get(key, "")
                return theme
        return theme

    def _call_llm(self, theme):
        """Call LLM with configurable model/temperature."""
        prompt = f"""请为以下番茄小说男频热门题材设计一个完整的商业小说大纲：

【题材名称】{theme.get('name', '')}
【标签】{theme.get('tag', '')}
【市场数据】{theme.get('market_share', '')}
【竞争程度】{theme.get('competition', '')}
【爆款公式】{theme.get('formula', '')}
【对标作品】{theme.get('references', '')}

【创作方向】
{theme.get('prompt_seed', '')}

请按照系统提示的格式，输出完整大纲。注意书名必须是16-22字的长句体微短剧风格。"""

        # Use the global client from batch_outline_generator
        from batch_outline_generator import client as _client

        for attempt in range(3):
            try:
                resp = _client.chat.completions.create(
                    model=self._llm_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                )
                return resp.choices[0].message.content
            except Exception as e:
                print(f"  [Retry {attempt + 1}/3] LLM error: {e}")
                time.sleep(3)
        raise RuntimeError("LLM call failed after 3 retries")

    @staticmethod
    def _save_outline(theme, content, timestamp, model):
        safe_tag = theme.get("tag", "custom")
        idx = theme.get("id", uuid.uuid4().hex[:4])

        json_path = os.path.join(OUTLINES_DIR, f"outline_{idx}_{safe_tag}.json")
        record = {
            "index": idx,
            "tag": safe_tag,
            "name": theme.get("name", ""),
            "market_share": theme.get("market_share", ""),
            "competition": theme.get("competition", ""),
            "formula": theme.get("formula", ""),
            "references": theme.get("references", ""),
            "content": content,
            "generated_at": timestamp,
            "model": model,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        txt_path = os.path.join(OUTLINES_DIR, f"outline_{idx}_{safe_tag}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"# {theme.get('name', '')} — 小说大纲\n")
            f.write(f"# 索引: {idx} | 标签: {safe_tag}\n")
            f.write(f"# 市场数据: {theme.get('market_share', '')} | 竞争: {theme.get('competition', '')}\n")
            f.write(f"# 对标: {theme.get('references', '')}\n")
            f.write(f"# 生成时间: {timestamp}\n")
            f.write("=" * 60 + "\n\n")
            f.write(content)

        return json_path, txt_path

    @staticmethod
    def _update_index():
        """Regenerate index.md from all outline JSON files."""
        idx_path = os.path.join(OUTLINES_DIR, "index.md")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        outlines = []
        for fn in sorted(os.listdir(OUTLINES_DIR)):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(OUTLINES_DIR, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    outlines.append(json.load(f))
            except (json.JSONDecodeError, IOError):
                continue

        lines = [
            "# 番茄小说男频 — 大纲索引",
            "",
            f"> 最后更新: {ts}",
            "",
            "## 大纲概览",
            "",
            "| # | 题材 | 标签 | 市场份额 | 竞争 | 爆款公式 |",
            "|---|------|------|----------|------|----------|",
        ]
        for o in outlines:
            lines.append(
                f"| {o.get('index', '')} | {o.get('name', '')} | `{o.get('tag', '')}` | "
                f"{o.get('market_share', '')} | {o.get('competition', '')} | {o.get('formula', '')} |"
            )

        lines += [
            "",
            "## 文件索引",
            "",
        ]
        for o in outlines:
            idx = o.get("index", "")
            tag = o.get("tag", "")
            lines.append(
                f"- **{idx}. {o.get('name', '')}** — "
                f"[`outline_{idx}_{tag}.txt`](outline_{idx}_{tag}.txt) | "
                f"[`outline_{idx}_{tag}.json`](outline_{idx}_{tag}.json)"
            )

        with open(idx_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _run(self, themes):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            for i, theme in enumerate(themes):
                if self._cancelled:
                    self.status = "cancelled"
                    self.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._save()
                    return

                theme = self._fill_defaults(theme)
                self.current_theme = theme.get("name", theme.get("id", ""))
                self.progress_log[i]["status"] = "generating"
                self._save()

                print(f"  [Generate] [{i+1}/{self.total}] {self.current_theme}...")
                try:
                    content = self._call_llm(theme)
                    json_path, _ = self._save_outline(theme, content, timestamp, self._llm_model)
                    self.progress_log[i]["status"] = "ok"
                    self.progress_log[i]["file"] = os.path.basename(json_path)
                    self.completed += 1
                    print(f"  [Generate]   -> OK: {os.path.basename(json_path)}")
                except Exception as e:
                    self.progress_log[i]["status"] = "failed"
                    self.progress_log[i]["error"] = str(e)
                    print(f"  [Generate]   -> FAILED: {e}")

                self._save()

                if i < len(themes) - 1 and not self._cancelled:
                    time.sleep(2)

            if not self._cancelled:
                self.status = "completed"
                self.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._update_index()
                self._save()
                print(f"  [Generate] Task completed: {self.completed}/{self.total} OK")
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            self.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save()
            print(f"  [Generate] Task failed: {e}")


class APIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the outline reviewer API."""

    def log_message(self, format, *args):
        """Suppress default logging to stderr, use print instead."""
        print(f"  [{self.command}] {args[0]}")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status, message):
        self._send_json({"error": message}, status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def _serve_static(self, path):
        """Serve a static file from webui/."""
        if path == "/" or path == "":
            path = "/index.html"

        file_path = os.path.join(WEBUI_DIR, path.lstrip("/"))
        file_path = os.path.normpath(file_path)

        # Security: ensure we stay within webui/
        if not file_path.startswith(os.path.normpath(WEBUI_DIR)):
            self._send_error(403, "Forbidden")
            return

        if not os.path.isfile(file_path):
            self._send_error(404, "Not found")
            return

        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        with open(file_path, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # API routes
        if path == "/api/outlines":
            outlines = _get_outlines()
            # Attach queue/annotation status
            queue = _load_queue()
            annotations = _load_annotations()
            queue_ids = {item["outline_id"] for item in queue}
            for o in outlines:
                oid = o["id"]
                o["in_queue"] = oid in queue_ids
                o["annotation_count"] = sum(1 for a in annotations if a["outline_id"] == oid)
            self._send_json(outlines)
            return

        m = re.match(r"^/api/outlines/(\d+)$", path)
        if m:
            outline_id = m.group(1)
            detail = _get_outline_detail(outline_id)
            if detail is None:
                self._send_error(404, f"Outline {outline_id} not found")
                return
            self._send_json(detail)
            return

        if path == "/api/annotations":
            self._send_json(_load_annotations())
            return

        if path == "/api/queue":
            queue = _load_queue()
            # Enrich with outline name/title
            for item in queue:
                detail = _get_outline_detail(item["outline_id"])
                if detail:
                    item["name"] = detail["name"]
                    item["title"] = detail["sections"].get("_title", "")
            self._send_json(queue)
            return

        if path == "/api/generate/status":
            task = _GenerationTask.get_current()
            if task:
                # If persisted state says running but we have no live task,
                # the server was restarted — treat as idle.
                data = task.to_dict()
            else:
                # Check persisted file for historical data
                persisted = _load_json(GENERATE_TASK_FILE, None)
                if persisted and persisted.get("status") in ("running",):
                    # Server restarted, reset to idle
                    data = {"status": "idle", "task_id": None, "total": 0, "completed": 0,
                            "current_theme": None, "progress_log": [], "started_at": None,
                            "finished_at": None, "error": None}
                elif persisted:
                    data = persisted
                else:
                    data = {"status": "idle", "task_id": None, "total": 0, "completed": 0,
                            "current_theme": None, "progress_log": [], "started_at": None,
                            "finished_at": None, "error": None}
            self._send_json(data)
            return

        if path == "/api/generate/presets":
            # Return preset themes (without full prompt_seed to keep response lean)
            presets = []
            for t in THEMES:
                presets.append({
                    "id": t["id"],
                    "tag": t["tag"],
                    "name": t["name"],
                    "market_share": t["market_share"],
                    "competition": t["competition"],
                    "formula": t["formula"],
                    "references": t["references"],
                    "prompt_seed": t["prompt_seed"],
                })
            self._send_json(presets)
            return

        # ── Novel reader API ──

        if path == "/api/novels":
            novels = []
            chapter_titles = {}
            for name in _get_novel_dirs():
                chapters = _get_chapter_files(name)
                has_arch = os.path.isfile(os.path.join(NOVEL_OUTPUT_DIR, name, "Novel_architecture.txt"))
                has_dir = os.path.isfile(os.path.join(NOVEL_OUTPUT_DIR, name, "Novel_directory.txt"))
                has_summary = os.path.isfile(os.path.join(NOVEL_OUTPUT_DIR, name, "global_summary.txt"))
                novels.append({
                    "name": name,
                    "chapter_count": len(chapters),
                    "has_architecture": has_arch,
                    "has_directory": has_dir,
                    "has_summary": has_summary,
                })
            self._send_json(novels)
            return

        # /api/novels/{name}/chapters/{n}
        m = re.match(r"^/api/novels/(.+)/chapters/(\d+)$", path)
        if m:
            novel_name = m.group(1)
            ch_num = int(m.group(2))
            if novel_name not in _get_novel_dirs():
                self._send_error(404, f"Novel '{novel_name}' not found")
                return
            chapter_path = os.path.join(NOVEL_OUTPUT_DIR, novel_name, "chapters", f"chapter_{ch_num}.txt")
            if not os.path.isfile(chapter_path):
                self._send_error(404, f"Chapter {ch_num} not found")
                return
            content = _read_novel_file(novel_name, f"chapters/chapter_{ch_num}.txt")
            titles = _parse_directory_titles(novel_name)
            ch_title = titles.get(ch_num, "")
            self._send_json({
                "n": ch_num,
                "title": ch_title,
                "content": content,
                "char_count": len(content) if content else 0,
            })
            return

        # /api/novels/{name}/directory
        m = re.match(r"^/api/novels/(.+)/directory$", path)
        if m:
            novel_name = m.group(1)
            if novel_name not in _get_novel_dirs():
                self._send_error(404, f"Novel '{novel_name}' not found")
                return
            content = _read_novel_file(novel_name, "Novel_directory.txt")
            self._send_json({"name": novel_name, "content": content or ""})
            return

        # /api/novels/{name}/architecture
        m = re.match(r"^/api/novels/(.+)/architecture$", path)
        if m:
            novel_name = m.group(1)
            if novel_name not in _get_novel_dirs():
                self._send_error(404, f"Novel '{novel_name}' not found")
                return
            content = _read_novel_file(novel_name, "Novel_architecture.txt")
            self._send_json({"name": novel_name, "content": content or ""})
            return

        # /api/novels/{name}/summary
        m = re.match(r"^/api/novels/(.+)/summary$", path)
        if m:
            novel_name = m.group(1)
            if novel_name not in _get_novel_dirs():
                self._send_error(404, f"Novel '{novel_name}' not found")
                return
            content = _read_novel_file(novel_name, "global_summary.txt")
            self._send_json({"name": novel_name, "content": content or ""})
            return

        # /api/novels/{name} — novel info with chapter list
        m = re.match(r"^/api/novels/(.+)$", path)
        if m:
            novel_name = m.group(1)
            if novel_name not in _get_novel_dirs():
                self._send_error(404, f"Novel '{novel_name}' not found")
                return
            chapters = _get_chapter_files(novel_name)
            titles = _parse_directory_titles(novel_name)
            has_arch = os.path.isfile(os.path.join(NOVEL_OUTPUT_DIR, novel_name, "Novel_architecture.txt"))
            has_dir = os.path.isfile(os.path.join(NOVEL_OUTPUT_DIR, novel_name, "Novel_directory.txt"))
            has_summary = os.path.isfile(os.path.join(NOVEL_OUTPUT_DIR, novel_name, "global_summary.txt"))
            self._send_json({
                "name": novel_name,
                "chapter_count": len(chapters),
                "has_architecture": has_arch,
                "has_directory": has_dir,
                "has_summary": has_summary,
                "chapters": [{"n": n, "title": titles.get(n, "")} for n, _ in chapters],
            })
            return

        # P0-3: Review constraints for outline
        m = re.match(r"^/api/outlines/(\d+)/constraints$", path)
        if m:
            outline_id = m.group(1)
            try:
                from novel_generator.review_constraints import load_review_constraints
                constraints = load_review_constraints(outline_id, PROJECT_DIR)
                self._send_json({
                    "replaced_content": constraints.replaced_content,
                    "constraints": constraints.constraints,
                })
            except Exception as e:
                self._send_error(500, f"Failed to load constraints: {e}")
            return

        # P0-3: Novel constraints
        m = re.match(r"^/api/novels/(.+)/constraints$", path)
        if m:
            novel_name = m.group(1)
            if novel_name not in _get_novel_dirs():
                self._send_error(404, f"Novel '{novel_name}' not found")
                return
            constraints_file = os.path.join(NOVEL_OUTPUT_DIR, novel_name, "review_constraints.json")
            if os.path.exists(constraints_file):
                with open(constraints_file, "r", encoding="utf-8") as f:
                    self._send_json(json.load(f))
            else:
                self._send_json({"constraints": [], "replaced_content": {}})
            return

        # P0-2: Hook detection
        m = re.match(r"^/api/novels/(.+)/chapters/(\d+)/hooks$", path)
        if m:
            novel_name = m.group(1)
            ch_num = int(m.group(2))
            if novel_name not in _get_novel_dirs():
                self._send_error(404, f"Novel '{novel_name}' not found")
                return
            content = _read_novel_file(novel_name, f"chapters/chapter_{ch_num}.txt")
            if content is None:
                self._send_error(404, f"Chapter {ch_num} not found in '{novel_name}'")
                return
            try:
                from novel_generator.hook_engine import detect_hooks
                report = detect_hooks(content)
                self._send_json(report)
            except Exception as e:
                self._send_error(500, f"Hook detection failed: {e}")
            return

        # GET /api/style-presets - return style preset list
        m = re.match(r'^/api/style-presets$', path)
        if m:
            try:
                presets_path = os.path.join(
                    PROJECT_DIR, 'novel_generator', 'style_presets.json'
                )
                with open(presets_path, 'r', encoding='utf-8') as f:
                    presets = json.load(f)
                self._send_json(presets)
            except FileNotFoundError:
                self._send_error(404, 'Style presets not found')
            except Exception as e:
                self._send_error(500, str(e))
            return

        # Static files
        self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/annotations":
            data = self._read_body()
            annotations = _load_annotations()
            entry = {
                "id": uuid.uuid4().hex[:8],
                "outline_id": data.get("outline_id", ""),
                "section_key": data.get("section_key", ""),
                "text": data.get("text", ""),
                "range": data.get("range", None),
            }
            annotations.append(entry)
            _save_annotations(annotations)
            self._send_json(entry, 201)
            return

        if path == "/api/queue":
            data = self._read_body()
            queue = _load_queue()
            outline_id = data.get("outline_id", "")
            # Check not already in queue
            if any(item["outline_id"] == outline_id for item in queue):
                self._send_error(409, "Already in queue")
                return
            entry = {
                "id": uuid.uuid4().hex[:8],
                "outline_id": outline_id,
                "added_at": data.get("added_at", ""),
            }
            queue.append(entry)
            _save_queue(queue)
            self._send_json(entry, 201)
            return

        if path == "/api/generate/start":
            data = self._read_body()
            themes = data.get("themes", [])
            if not themes:
                self._send_error(400, "themes is required")
                return

            model = data.get("model", "gpt-5.4")
            temperature = float(data.get("temperature", 0.75))
            max_tokens = int(data.get("max_tokens", 4096))

            try:
                task = _GenerationTask.start_new(themes, model, temperature, max_tokens)
                print(f"  [Generate] Task {task.task_id} started: {len(themes)} themes")
                self._send_json({"task_id": task.task_id, "status": "running"}, 201)
            except RuntimeError as e:
                self._send_error(409, str(e))
            return

        if path == "/api/generate/cancel":
            task = _GenerationTask.get_current()
            if not task:
                self._send_error(404, "No active generation task")
                return
            if task.cancel():
                print(f"  [Generate] Task {task.task_id} cancellation requested")
                self._send_json({"status": "cancelling"})
            else:
                self._send_error(409, f"Task is not running (status: {task.status})")
            return

        # P0-1: Title generation
        if re.match(r"^/api/outlines/(\d+)/generate-titles$", path):
            m2 = re.match(r"^/api/outlines/(\d+)/generate-titles$", path)
            outline_id = m2.group(1)
            detail = _get_outline_detail(outline_id)
            if detail is None:
                self._send_error(404, f"Outline {outline_id} not found")
                return
            try:
                from novel_generator.title_generator import generate_titles
                titles = generate_titles(detail)
                self._send_json({"titles": titles})
            except Exception as e:
                self._send_error(500, f"Title generation failed: {e}")
            return

        if re.match(r"^/api/outlines/(\d+)/generate-synopsis$", path):
            m2 = re.match(r"^/api/outlines/(\d+)/generate-synopsis$", path)
            outline_id = m2.group(1)
            data = self._read_body()
            selected_title = data.get("title", "")
            if not selected_title:
                self._send_error(400, "title is required")
                return
            detail = _get_outline_detail(outline_id)
            if detail is None:
                self._send_error(404, f"Outline {outline_id} not found")
                return
            try:
                from novel_generator.title_generator import generate_synopsis
                synopsis = generate_synopsis(detail, selected_title)
                self._send_json(synopsis)
            except Exception as e:
                self._send_error(500, f"Synopsis generation failed: {e}")
            return

        # P0-2: Cliffhanger generation
        m = re.match(r"^/api/novels/(.+)/chapters/(\d+)/cliffhanger$", path)
        if m:
            novel_name = m.group(1)
            ch_num = int(m.group(2))
            if novel_name not in _get_novel_dirs():
                self._send_error(404, f"Novel '{novel_name}' not found")
                return
            content = _read_novel_file(novel_name, f"chapters/chapter_{ch_num}.txt")
            if content is None:
                self._send_error(404, f"Chapter {ch_num} not found")
                return
            next_bp = _read_novel_file(novel_name, "Novel_directory.txt") or ""
            try:
                from novel_generator.hook_engine import generate_cliffhanger
                candidates = generate_cliffhanger(content, next_bp)
                self._send_json({"candidates": candidates})
            except Exception as e:
                self._send_error(500, f"Cliffhanger generation failed: {e}")
            return

        # P0-3: Start novel generation from review queue
        if path == "/api/queue/start-novel":
            data = self._read_body()
            outline_id = data.get("outline_id", "")
            if not outline_id:
                self._send_error(400, "outline_id is required")
                return
            try:
                from novel_generator.review_constraints import load_review_constraints
                constraints = load_review_constraints(outline_id, PROJECT_DIR)
            except Exception as e:
                self._send_error(500, f"Failed to load constraints: {e}")
                return
            novel_name = data.get("novel_name", f"novel_{outline_id}")
            novel_dir = os.path.join(NOVEL_OUTPUT_DIR, novel_name)
            os.makedirs(novel_dir, exist_ok=True)
            constraints_data = {
                "replaced_content": constraints.replaced_content,
                "constraints": constraints.constraints,
                "outline_id": outline_id,
            }
            _save_json(os.path.join(novel_dir, "review_constraints.json"), constraints_data)
            self._send_json({
                "status": "constraints_saved",
                "novel_name": novel_name,
                "novel_dir": novel_dir,
                "constraint_count": len(constraints.constraints),
                "replaced_sections": list(constraints.replaced_content.keys()),
            })
            return

        m = re.match(r"^/api/outlines/(\d+)/revert$", path)
        if m:
            outline_id = m.group(1)
            edits = _load_edits()
            if outline_id in edits:
                del edits[outline_id]
                _save_edits(edits)
            self._send_json({"status": "reverted"})
            return

        # POST /api/rewrite - execute text rewrite
        if path == "/api/rewrite":
            try:
                body = self._read_body()
                chapter_text = body['chapter_text']
                start_pos = body['start_pos']
                end_pos = body['end_pos']
                instruction = body['instruction']
                style_id = body.get('style_id', '')

                from novel_generator.rewrite_agent import (
                    extract_context, build_rewrite_prompt, clean_rewrite_output,
                    REWRITE_SYSTEM_PROMPT
                )

                before, selected, after = extract_context(chapter_text, start_pos, end_pos)

                style_extra = ''
                if style_id:
                    presets_path = os.path.join(
                        PROJECT_DIR, 'novel_generator', 'style_presets.json'
                    )
                    with open(presets_path, 'r', encoding='utf-8') as f:
                        presets = json.load(f)
                    for p in presets.get('presets', []):
                        if p['id'] == style_id:
                            style_extra = p.get('system_extra', '')
                            break

                user_prompt = build_rewrite_prompt(before, selected, after, instruction, style_extra)

                # Load LLM config
                config_path = os.path.join(PROJECT_DIR, 'config.json')
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                llm_name = config.get('choose_configs', {}).get('final_chapter_llm', '')
                if not llm_name:
                    llm_name = list(config.get('llm_configs', {}).keys())[0]
                llm_cfg = config['llm_configs'][llm_name]

                from llm_adapters import create_llm_adapter
                llm = create_llm_adapter(
                    interface_format=llm_cfg.get('interface_format', 'OpenAI'),
                    base_url=llm_cfg.get('base_url', ''),
                    model_name=llm_cfg.get('model_name', ''),
                    api_key=llm_cfg.get('api_key', ''),
                    temperature=llm_cfg.get('temperature', 0.7),
                    max_tokens=llm_cfg.get('max_tokens', 4096),
                    timeout=llm_cfg.get('timeout', 600),
                )

                from novel_generator.common import invoke_with_cleaning
                raw_result = invoke_with_cleaning(llm, user_prompt, system_prompt=REWRITE_SYSTEM_PROMPT)
                rewritten = clean_rewrite_output(raw_result)

                self._send_json({
                    'original': selected,
                    'rewritten': rewritten,
                    'before_context': before,
                    'after_context': after
                })
            except Exception as e:
                self._send_error(500, str(e))
            return

        # POST /api/rewrite-log - save rewrite record for data flywheel
        if path == "/api/rewrite-log":
            try:
                body = self._read_body()
                record = {
                    "timestamp": datetime.now().isoformat(),
                    "novel_name": body.get("novel_name", ""),
                    "chapter_num": body.get("chapter_num", 0),
                    "original_text": body.get("original_text", ""),
                    "instruction": body.get("instruction", ""),
                    "ai_rewritten": body.get("ai_rewritten", ""),
                    "user_edited": body.get("user_edited", ""),
                }
                log_path = os.path.join(REVIEW_DIR, "rewrite_history.jsonl")
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._send_json({"status": "logged", "total": _count_jsonl(log_path)})
            except Exception as e:
                self._send_error(500, str(e))
            return

        self._send_error(404, "Not found")

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        m = re.match(r"^/api/outlines/(\d+)$", path)
        if m:
            outline_id = m.group(1)
            data = self._read_body()
            section_key = data.get("section_key", "")
            new_content = data.get("new_content", "")

            if not section_key:
                self._send_error(400, "section_key required")
                return

            # Verify the outline exists
            if _find_outline_json(outline_id) is None:
                self._send_error(404, f"Outline {outline_id} not found")
                return

            edits = _load_edits()
            if outline_id not in edits:
                edits[outline_id] = {}
            edits[outline_id][section_key] = new_content
            _save_edits(edits)
            self._send_json({"status": "saved"})
            return

        # PUT /api/novels/{name}/chapters/{n} - update chapter content
        m = re.match(r'^/api/novels/([^/]+)/chapters/(\d+)$', path)
        if m:
            try:
                novel_name = m.group(1)
                chapter_num = int(m.group(2))
                body = self._read_body()
                new_content = body['content']

                chapter_file = os.path.join(
                    NOVEL_OUTPUT_DIR, novel_name, 'chapters', f'chapter_{chapter_num}.txt'
                )

                if not os.path.exists(chapter_file):
                    self._send_error(404, f'Chapter {chapter_num} not found')
                    return

                with open(chapter_file, 'w', encoding='utf-8') as f:
                    f.write(new_content)

                self._send_json({'status': 'ok', 'chapter': chapter_num})
            except Exception as e:
                self._send_error(500, str(e))
            return

        self._send_error(404, "Not found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        m = re.match(r"^/api/annotations/(\w+)$", path)
        if m:
            ann_id = m.group(1)
            annotations = _load_annotations()
            before = len(annotations)
            annotations = [a for a in annotations if a["id"] != ann_id]
            if len(annotations) == before:
                self._send_error(404, "Annotation not found")
                return
            _save_annotations(annotations)
            self._send_json({"status": "deleted"})
            return

        m = re.match(r"^/api/queue/(\w+)$", path)
        if m:
            queue_id = m.group(1)
            queue = _load_queue()
            before = len(queue)
            queue = [q for q in queue if q["id"] != queue_id]
            if len(queue) == before:
                self._send_error(404, "Queue item not found")
                return
            _save_queue(queue)
            self._send_json({"status": "deleted"})
            return

        self._send_error(404, "Not found")


def main():
    port = 8088
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    print(f"  Outline Reviewer server running at http://localhost:{port}")
    print(f"  Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
