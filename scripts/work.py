#!/usr/bin/env python3
"""作業表CLI（ローカル版）— サーバ不要、Python標準ライブラリのみ。

作業表の実体はリポジトリ直下の work.json。複数エージェントが同じ
作業表を読み書きし、誰が何をしているかを見える状態に保つための道具。

使い方:
  python scripts/work.py new --session claude:main "タイトル"
  python scripts/work.py claim --session codex:main <id>
  python scripts/work.py progress --session claude:main <id> "やったこと" [--next "次の一手"]
  python scripts/work.py wait    --session claude:main <id> "ユーザーに確認したいこと"
  python scripts/work.py block   --session claude:main <id> "止まっている理由"
  python scripts/work.py done    --session claude:main --result "成果" [--notes id1,id2] <id>
  python scripts/work.py cancel  --session claude:main --result "やめた理由" <id>
  python scripts/work.py list [--mine <session>] [--all]
  python scripts/work.py show <id>
"""
import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK_FILE = ROOT / "work.json"
JST = timezone(timedelta(hours=9))

STATUS_LABELS = {
    "in_progress": "進行中",
    "waiting_user": "ユーザー判断待ち",
    "blocked": "ブロック中",
    "done": "完了",
    "cancelled": "キャンセル",
}
OPEN_STATUSES = {"in_progress", "waiting_user", "blocked"}


def now_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def load() -> dict:
    if WORK_FILE.exists():
        return json.loads(WORK_FILE.read_text(encoding="utf-8"))
    return {"items": []}


def save(data: dict) -> None:
    tmp = WORK_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, WORK_FILE)


def find(data: dict, item_id: str) -> dict:
    for item in data["items"]:
        if item["id"] == item_id:
            return item
    sys.exit(f"項目が見つかりません: {item_id}")


def new_id(data: dict) -> str:
    existing = {i["id"] for i in data["items"]}
    while True:
        cand = uuid.uuid4().hex[:8]
        if cand not in existing:
            return cand


def add_progress(item: dict, session: str, text: str, nxt: str | None = None) -> None:
    entry = {"at": now_iso(), "session": session, "text": text}
    if nxt:
        entry["next"] = nxt
    item.setdefault("progress", []).append(entry)
    item["updated_at"] = now_iso()
    if session not in item.setdefault("sessions", []):
        item["sessions"].append(session)


def line(item: dict) -> str:
    label = STATUS_LABELS.get(item["status"], item["status"])
    owner = item.get("owner_session") or "-"
    return f"#{item['id']} {label} 担当={owner} {item['title']}"


def cmd_new(a) -> None:
    data = load()
    item = {
        "id": new_id(data),
        "title": a.title,
        "status": "in_progress",
        "owner_session": a.session,
        "sessions": [a.session],
        "progress": [{"at": now_iso(), "session": a.session, "text": "登録"}],
        "result": "",
        "notes": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    if a.done_when:
        item["done_when"] = a.done_when
    data["items"].append(item)
    save(data)
    print(line(item))


def cmd_claim(a) -> None:
    data = load()
    item = find(data, a.id)
    item["owner_session"] = a.session
    item["status"] = "in_progress"
    add_progress(item, a.session, "担当に入った")
    save(data)
    print(line(item))


def cmd_progress(a) -> None:
    data = load()
    item = find(data, a.id)
    add_progress(item, a.session, a.text, a.next)
    if item["status"] not in OPEN_STATUSES:
        item["status"] = "in_progress"
    save(data)
    print(line(item))


def cmd_wait_block(a, status: str) -> None:
    data = load()
    item = find(data, a.id)
    item["status"] = status
    add_progress(item, a.session, a.text)
    save(data)
    print(line(item))


def cmd_close(a, status: str) -> None:
    data = load()
    item = find(data, a.id)
    item["status"] = status
    item["result"] = a.result
    if getattr(a, "notes", None):
        item["notes"] = [n.strip() for n in a.notes.split(",") if n.strip()]
    item["closed_at"] = now_iso()
    add_progress(item, a.session, f"{STATUS_LABELS[status]}: {a.result}")
    save(data)
    print(line(item))


def cmd_list(a) -> None:
    data = load()
    items = data["items"]
    if a.mine:
        items = [i for i in items if a.mine in i.get("sessions", [])]
    if not a.all:
        items = [i for i in items if i["status"] in OPEN_STATUSES]
    for item in sorted(items, key=lambda i: i["updated_at"]):
        print(line(item))
    print(f"({len(items)}件)")


def cmd_show(a) -> None:
    data = load()
    item = find(data, a.id)
    print(json.dumps(item, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="作業表（ローカル版）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def sess(sp):
        sp.add_argument("--session", required=True, help="自分のセッション名 例: claude:main")

    sp = sub.add_parser("new"); sess(sp); sp.add_argument("title")
    sp.add_argument("--done-when", default=None, help="完了条件")
    sp.set_defaults(fn=cmd_new)

    sp = sub.add_parser("claim"); sess(sp); sp.add_argument("id")
    sp.set_defaults(fn=cmd_claim)

    sp = sub.add_parser("progress"); sess(sp); sp.add_argument("id"); sp.add_argument("text")
    sp.add_argument("--next", default=None)
    sp.set_defaults(fn=cmd_progress)

    sp = sub.add_parser("wait"); sess(sp); sp.add_argument("id"); sp.add_argument("text")
    sp.set_defaults(fn=lambda a: cmd_wait_block(a, "waiting_user"))

    sp = sub.add_parser("block"); sess(sp); sp.add_argument("id"); sp.add_argument("text")
    sp.set_defaults(fn=lambda a: cmd_wait_block(a, "blocked"))

    sp = sub.add_parser("done"); sess(sp); sp.add_argument("id")
    sp.add_argument("--result", required=True)
    sp.add_argument("--notes", default=None, help="紐づくノートid（カンマ区切り）")
    sp.set_defaults(fn=lambda a: cmd_close(a, "done"))

    sp = sub.add_parser("cancel"); sess(sp); sp.add_argument("id")
    sp.add_argument("--result", required=True)
    sp.set_defaults(fn=lambda a: cmd_close(a, "cancelled"))

    sp = sub.add_parser("list")
    sp.add_argument("--mine", default=None)
    sp.add_argument("--all", action="store_true")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("show"); sp.add_argument("id")
    sp.set_defaults(fn=cmd_show)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
