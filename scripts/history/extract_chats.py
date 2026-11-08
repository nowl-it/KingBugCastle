#!/usr/bin/env python3
"""Harvest every chat log the KGC project touched, across five agents.

Sources (all local, read-only):
  opencode     ~/.local/share/opencode/opencode.db   (sqlite: session_v2/message/part)
  claude       ~/.claude/history.jsonl               (user prompts only; sessions are gone)
  codex        ~/.codex/state_5.sqlite               (threads table: title + first message)
  qoder        ~/.qoder/projects/-home-nowl-Code-kgc  (jsonl, one user + one assistant blob)
  antigravity  ~/.config/Antigravity/User/globalStorage/state.vscdb (protobuf blobs -> strings)

Writes plain-markdown per-session digests plus index.json under --out (default .tmp/corpus).
Raw corpus is deliberately NOT committed: it is large and personal. The synthesis in
docs/history/ is what gets committed.

    python3 scripts/history/extract_chats.py [--out DIR] [--since YYYY-MM-DD]

ponytail: tool-call bodies are dropped, only name+first line kept. The narrative lives in
user prompts and assistant prose; 600MB of file reads adds nothing to a retrospective.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
MATCH = re.compile(r"kgc|kinggodcastle|king god castle|kingbugcastle|kgcentral|king god central", re.I)


def _iso(ms: object) -> str:
    try:
        v = int(ms)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if v > 10_000_000_000:
        v //= 1000
    return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rstrip() + " …"


def _write(out: Path, source: str, sid: str, body: str) -> None:
    d = out / source
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.md").write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- opencode
def opencode(out: Path) -> list[dict]:
    db = HOME / ".local/share/opencode/opencode.db"
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "select id,title,directory,agent,model,cost,tokens_input,tokens_output,"
        "time_created,time_updated,parent_id from session_v2 "
        "where directory like '%/kgc' or directory like '%KGC%' order by time_created"
    ).fetchall()
    index = []
    for sid, title, directory, agent, model, cost, tin, tout, t0, t1, parent in rows:
        events = _opencode_session_message(con, sid) or _opencode_legacy(con, sid)
        if not events:
            continue
        lines = [f"# {title or sid}", "", f"- source: opencode · `{sid}`",
                 f"- dir: `{directory}` · agent: {agent or '?'} · model: {model or '?'}",
                 f"- when: {_iso(t0)} → {_iso(t1)} · cost ${cost or 0:.4f} · "
                 f"tokens {tin or 0}in/{tout or 0}out", ""]
        for role, body, tools in events:
            lines.append(f"## {role}")
            if body:
                lines.append(_clip(body, 4000))
            if tools:
                lines.append("\n_tools:_ " + " · ".join(tools[:8]))
            lines.append("")
        _write(out, "opencode", sid, "\n".join(lines))
        index.append({"source": "opencode", "id": sid, "title": title, "dir": directory,
                      "start": _iso(t0), "end": _iso(t1), "turns": len(events), "cost": cost,
                      "tokens_in": tin, "tokens_out": tout, "parent": parent})
    con.close()
    return index


def _opencode_session_message(con: sqlite3.Connection, sid: str) -> list[tuple[str, str, list[str]]]:
    """Newer opencode builds flatten message+parts into session_message."""
    out: list[tuple[str, str, list[str]]] = []
    for typ, data in con.execute(
        "select type,data from session_message where session_id=? "
        "and type in ('user','assistant') order by seq", (sid,)
    ).fetchall():
        try:
            m = json.loads(data)
        except json.JSONDecodeError:
            continue
        if typ == "user":
            text = m.get("text") or ""
            if isinstance(m.get("content"), list):
                text += "\n".join(c.get("text", "") for c in m["content"] if isinstance(c, dict))
            if text.strip():
                out.append(("user", text, []))
            continue
        texts, tools = [], []
        for c in m.get("content") or []:
            if not isinstance(c, dict):
                continue
            ct = c.get("type")
            if ct == "text" and c.get("text"):
                texts.append(c["text"])
            elif ct == "tool":
                hint = (c.get("state") or {}).get("input", {})
                hint = hint.get("command") or hint.get("filePath") or hint.get("description") or ""
                tools.append(f"`{c.get('tool') or c.get('name') or '?'}` {_clip(str(hint), 100)}")
        if texts or tools:
            out.append(("assistant", "\n".join(texts), tools))
    return out


def _opencode_legacy(con: sqlite3.Connection, sid: str) -> list[tuple[str, str, list[str]]]:
    """Older opencode builds: message rows + part rows."""
    out: list[tuple[str, str, list[str]]] = []
    for mid, mdata in con.execute(
        "select id,data from message where session_id=? order by time_created", (sid,)
    ).fetchall():
        try:
            role = json.loads(mdata).get("role") or "?"
        except json.JSONDecodeError:
            continue
        texts, tools = [], []
        for (pdata,) in con.execute(
            "select data from part where message_id=? order by time_created", (mid,)
        ).fetchall():
            try:
                p = json.loads(pdata)
            except json.JSONDecodeError:
                continue
            t = p.get("type")
            if t == "text" and p.get("text"):
                texts.append(p["text"])
            elif t == "tool":
                arg = (p.get("state") or {}).get("input", {})
                hint = arg.get("command") or arg.get("filePath") or arg.get("description") or ""
                tools.append(f"`{p.get('tool') or '?'}` {_clip(str(hint), 100)}")
        if texts or tools:
            out.append((role, "\n".join(texts), tools))
    return out


# --------------------------------------------------------------------------- qoder
def qoder(out: Path) -> list[dict]:
    base = HOME / ".qoder/projects/-home-nowl-Code-kgc"
    if not base.exists():
        return []
    index = []
    for f in sorted(base.glob("*.jsonl")):
        user, assistant, when = "", [], ""
        for line in f.open(encoding="utf-8", errors="replace"):
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            typ = o.get("type")
            if typ == "user":
                when = when or (o.get("timestamp") or "")[:16]
                for c in o.get("message", {}).get("content", []):
                    if isinstance(c, dict) and c.get("text"):
                        user += c["text"] + "\n"
            elif typ == "assistant":
                msg = o.get("message", {})
                for c in msg.get("content", []) if isinstance(msg, dict) else []:
                    if isinstance(c, dict) and c.get("type") == "text":
                        assistant.append(c.get("text", ""))
                    elif isinstance(c, dict) and c.get("type") == "tool_use":
                        assistant.append(f"`{c.get('name')}` {_clip(json.dumps(c.get('input', {}))[:120], 120)}")
        if not (user.strip() or assistant):
            continue
        sid = f.stem
        body = [f"# qoder {sid}", "", f"- source: qoder · when: {when}", "",
                "## user", _clip(user, 6000), "", "## assistant", _clip("\n".join(assistant), 6000), ""]
        _write(out, "qoder", sid, "\n".join(body))
        index.append({"source": "qoder", "id": sid, "title": _clip(user, 80), "start": when,
                      "end": when, "turns": 1})
    return index


# --------------------------------------------------------------------------- claude
def claude(out: Path) -> list[dict]:
    f = HOME / ".claude/history.jsonl"
    if not f.exists():
        return []
    by_session: dict[str, list[dict]] = {}
    for raw in f.open(encoding="utf-8", errors="replace"):
        try:
            o = json.loads(raw)
        except json.JSONDecodeError:
            continue
        proj = o.get("project", "")
        if not MATCH.search(proj) and not MATCH.search(o.get("display", "")):
            continue
        by_session.setdefault(o.get("sessionId") or "unknown", []).append(o)
    index = []
    for sid, items in by_session.items():
        items.sort(key=lambda x: x.get("timestamp") or 0)
        body = [f"# claude {sid}", "", f"- source: claude-code history · project: `{items[0].get('project')}` · "
                f"prompts: {len(items)}", ""]
        for it in items:
            body += [f"### {_iso(it.get('timestamp'))}", _clip(it.get("display", ""), 1500), ""]
        _write(out, "claude", sid, "\n".join(body))
        index.append({"source": "claude", "id": sid, "title": _clip(items[0].get("display", ""), 80),
                      "dir": items[0].get("project"), "start": _iso(items[0].get("timestamp")),
                      "end": _iso(items[-1].get("timestamp")), "turns": len(items)})
    return index


# --------------------------------------------------------------------------- codex
def codex(out: Path) -> list[dict]:
    db = HOME / ".codex/state_5.sqlite"
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select id,cwd,title,first_user_message,created_at,updated_at,model_provider,"
            "tokens_used from threads where cwd like '%kgc%' order by created_at"
        ).fetchall()
    except sqlite3.DatabaseError:
        rows = []
    index = []
    for sid, cwd, title, first, t0, t1, prov, tokens in rows:
        body = [f"# {title or sid}", "", f"- source: codex · `{sid}`", f"- dir: `{cwd}` · "
                f"when: {_iso(t0)} → {_iso(t1)} · tokens {tokens or 0}", "",
                "## user", _clip(first, 4000), ""]
        _write(out, "codex", sid, "\n".join(body))
        index.append({"source": "codex", "id": sid, "title": title or _clip(first, 60), "dir": cwd,
                      "start": _iso(t0), "end": _iso(t1), "turns": 1, "tokens_in": tokens})
    con.close()
    return index


# --------------------------------------------------------------------------- antigravity
def antigravity(out: Path) -> list[dict]:
    db = HOME / ".config/Antigravity/User/globalStorage/state.vscdb"
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    blob = con.execute(
        "select value from ItemTable where key='unifiedStateSync.trajectorySummaries'"
    ).fetchone()
    con.close()
    if not blob:
        return []
    raw = blob[0]
    try:
        raw = base64.b64decode(raw)
    except Exception:  # noqa: BLE001 - blob may already be plain
        pass

    # The summaries are protobuf with base64-encoded UTF-8 payloads sprinkled in, twice
    # nested. Rather than pull in a protobuf dep for a one-off, decode every base64 run
    # and keep whatever comes back as readable prose.
    def harvest(data: bytes, depth: int) -> list[str]:
        found: list[str] = []
        for m in re.finditer(rb"[A-Za-z0-9+/]{40,}={0,2}", data):
            try:
                dec = base64.b64decode(m.group(), validate=True)
            except Exception:  # noqa: BLE001
                continue
            if depth < 2:
                found += harvest(dec, depth + 1)
            try:
                s = dec.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if sum(ch.isprintable() or ch in "\n\t" for ch in s) / max(len(s), 1) > 0.95:
                found.append(s)
        for m in re.finditer(rb"[\x20-\x7e\xc0-\xff]{12,}", data):
            try:
                found.append(m.group().decode("utf-8"))
            except UnicodeDecodeError:
                continue
        return found

    titles, seen = [], set()
    for s in harvest(raw, 0):
        for line in s.splitlines():
            line = line.strip(" \t\"',:()[]{}")
            if len(line) < 12:
                continue
            if not (MATCH.search(line) or re.match(r"^[A-Z][a-z]+ [a-z]", line)):
                continue
            if line in seen:
                continue
            seen.add(line)
            titles.append(line[:160])
    body = ["# antigravity trajectory summaries", "",
            "- source: antigravity IDE global state (protobuf, decoded to strings)",
            "- note: full transcripts were not persisted by the IDE; only task titles survive.",
            "", *[f"- {t}" for t in titles[:200]], ""]
    _write(out, "antigravity", "trajectory-summaries", "\n".join(body))
    return [{"source": "antigravity", "id": "trajectory-summaries",
             "title": f"{len(titles)} trajectory titles", "turns": len(titles)}]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".tmp/corpus")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    for fn in (opencode, claude, codex, qoder, antigravity):
        try:
            got = fn(out)
        except Exception as exc:  # noqa: BLE001 - one broken store must not kill the run
            print(f"[warn] {fn.__name__}: {exc}", file=sys.stderr)
            got = []
        print(f"{fn.__name__:12} {len(got):4} sessions")
        index += got
    (out / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    total_cost = sum(r.get("cost") or 0 for r in index)
    print(f"\n{len(index)} sessions · ${total_cost:.2f} recorded spend · {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
