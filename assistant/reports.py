"""Dynamic reports.

A report is a YAML spec (title, sections, standing instructions). Defaults ship in
``config/reports/`` and are copied to ``<data_dir>/reports/`` on first use; the live
copies are what Mother edits when you say "for future reports, add X".
Generated reports are saved as markdown under ``<data_dir>/reports/out/``.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

import yaml

from .timeutil import fmt_ts, now_local

MAX_ROWS_PER_SECTION = 80


def reports_dir(rt) -> Path:
    d = rt.settings.data_dir / "reports"
    if not d.exists():
        d.mkdir(parents=True)
        for f in rt.settings.reports_dir.glob("*.yaml"):
            shutil.copy(f, d / f.name)
    return d


def list_reports(rt) -> list[dict]:
    out = []
    for f in sorted(reports_dir(rt).glob("*.yaml")):
        spec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        out.append({"name": f.stem, "title": spec.get("title", f.stem), "description": spec.get("description", "")})
    return out


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", name.lower()).strip("_")


def load_spec(rt, name: str) -> dict:
    f = reports_dir(rt) / f"{_slug(name)}.yaml"
    if not f.exists():
        raise FileNotFoundError(f"no report named {name!r}; have: {[r['name'] for r in list_reports(rt)]}")
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


def save_spec(rt, name: str, spec: dict) -> Path:
    f = reports_dir(rt) / f"{_slug(name)}.yaml"
    history = reports_dir(rt) / "history"
    history.mkdir(exist_ok=True)
    if f.exists():
        shutil.copy(f, history / f"{f.stem}.{int(time.time())}.yaml")
    f.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return f


def update_spec(rt, name: str, instruction: str | None = None, add_section: dict | None = None,
                remove_section: str | None = None) -> dict:
    spec = load_spec(rt, name)
    if instruction:
        spec.setdefault("instructions", []).append(instruction)
    if add_section:
        spec.setdefault("sections", []).append(add_section)
    if remove_section:
        spec["sections"] = [s for s in spec.get("sections", []) if s.get("title", "").lower() != remove_section.lower()]
    save_spec(rt, name, spec)
    return spec


def gather_section_data(rt, section: dict, since: float) -> list[dict]:
    if section.get("sql"):
        sql = section["sql"].replace(":since", str(float(since)))
        try:
            return rt.db.readonly_query(sql, limit=MAX_ROWS_PER_SECTION)
        except Exception as e:
            return [{"error": f"sql failed: {e}"}]
    if section.get("data") == "fridge":
        return rt.db.query("SELECT item, expires FROM groceries WHERE status='in_fridge' ORDER BY expires")
    if section.get("data") == "findings":
        return rt.db.query("SELECT severity, check_name, message FROM findings WHERE ts>=? ORDER BY ts DESC", (since,))
    if section.get("data") == "jarvis":
        return rt.db.query("SELECT name, status_text, updated FROM projects ORDER BY updated DESC LIMIT 10")
    sources = section.get("sources") or []
    if not sources:
        return []
    marks = ",".join("?" for _ in sources)
    rows = rt.db.query(
        f"SELECT source, kind, ts, title, substr(body,1,300) AS body FROM events "
        f"WHERE source IN ({marks}) AND ts>=? ORDER BY ts DESC LIMIT ?",
        (*sources, since, MAX_ROWS_PER_SECTION))
    for r in rows:
        r["ts"] = fmt_ts(rt.settings, r["ts"])
    return rows


async def generate(rt, name: str, model_alias: str = "heavy") -> dict[str, Any]:
    spec = load_spec(rt, name)
    hours = float(spec.get("window_hours", 24))
    since = time.time() - hours * 3600
    instructions = spec.get("instructions", [])
    parts = [f"# {spec.get('title', name)} — {now_local(rt.settings):%a %b %d %Y}"]
    model = rt.settings.model(model_alias)
    for sec in spec.get("sections", []):
        rows = gather_section_data(rt, sec, since)
        if not rows and sec.get("skip_if_empty", True):
            continue
        prompt = (
            f"Write the '{sec.get('title')}' section of a personal report.\n"
            f"Goal: {sec.get('prompt', 'Summarize the data.')}\n"
            f"Standing instructions from the user: {json.dumps(instructions)}\n"
            "Use only the data below. Be concise; markdown bullets are fine. No preamble.\n\n"
            f"DATA:\n{json.dumps(rows, default=str)[:12000]}"
        )
        msg = await rt.llm.chat(model, [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=500)
        parts.append(f"## {sec.get('title')}\n{(msg.get('content') or '').strip()}")
    body = "\n\n".join(parts)
    spoken = ""
    if spec.get("speak_summary", True):
        msg = await rt.llm.chat(model, [{"role": "user", "content":
            "Turn this report into a 2-4 sentence spoken summary, plain text, no markdown:\n\n" + body[:8000]}],
            temperature=0.3, max_tokens=200)
        spoken = (msg.get("content") or "").strip()
    out = reports_dir(rt) / "out"
    out.mkdir(exist_ok=True)
    path = out / f"{_slug(name)}-{now_local(rt.settings):%Y%m%d-%H%M}.md"
    path.write_text(body, encoding="utf-8")
    rt.db.kv_set(f"report:{_slug(name)}:latest", {"path": str(path), "spoken": spoken, "ts": time.time()})
    return {"name": name, "markdown": body, "spoken": spoken, "path": str(path)}
