#!/usr/bin/env python3
"""
tools/import_mcwiki.py

Modification():

- Resumable importer for the Chinese Minecraft Wiki.  The importer uses the site's MediaWiki API, rather than HTML scraping.  Each saved page includes its immutable revision URL and attribution information.
- 維護 import mcwiki 的發布版行為與驗證契約。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

API_URL = "https://zh.minecraft.wiki/api.php"
WIKI_URL = "https://zh.minecraft.wiki/"
LICENSE = "CC BY-NC-SA 3.0"
USER_AGENT = "Discord-Bot-MCWikiImporter/1.0 (local AI knowledge index)"
ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT_DIR / "data" / "ai" / "knowledge" / "mcwiki"


def safe_filename(title: str, page_id: int) -> str:
    """Return a portable, stable filename that keeps a page ID for uniqueness."""
    safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", title, flags=re.UNICODE)
    safe = safe.strip("._") or "untitled"
    return f"{safe[:120]}__{page_id}.md"


def _yaml_value(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_markdown(
    *,
    title: str,
    page_id: int,
    revision_id: int,
    fetched_at: str,
    source_url: str,
    text: str,
    revision_timestamp: str = "",
) -> str:
    """Render an imported page with the metadata needed for attribution."""
    metadata = [
        "---",
        f"title: {title}",
        f"page_id: {page_id}",
        f"revision_id: {revision_id}",
        f"source_url: {_yaml_value(source_url)}",
        f"fetched_at: {fetched_at}",
        f"license: {_yaml_value(LICENSE)}",
        'attribution: "中文 Minecraft Wiki contributors"',
    ]
    if revision_timestamp:
        metadata.append(f"revision_timestamp: {revision_timestamp}")
    metadata.extend(("---", "", f"# {title}", "", text.strip(), ""))
    return "\n".join(metadata)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"completed_page_ids": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"completed_page_ids": []}
    return data if isinstance(data, dict) else {"completed_page_ids": []}


def namespace_ids(raw_namespaces: Any) -> list[int]:
    """Normalize the list and mapping variants returned by MediaWiki."""
    values = raw_namespaces.values() if isinstance(raw_namespaces, dict) else raw_namespaces
    if not isinstance(values, (list, tuple)) and not hasattr(values, "__iter__"):
        return []
    return sorted(
        int(namespace["id"])
        for namespace in values
        if isinstance(namespace, dict) and isinstance(namespace.get("id"), int)
        and namespace["id"] >= 0
    )


def selected_namespaces(args: argparse.Namespace, client: "WikiClient") -> list[int]:
    """Use article pages by default; include every public namespace only on request."""
    if args.namespace is not None:
        return [args.namespace]
    return client.namespaces() if args.all_namespaces else [0]


class WikiClient:
    def __init__(self, *, delay: float) -> None:
        self.delay = max(0.0, delay)

    def request(self, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode({"format": "json", "formatversion": 2, **params})
        request = urllib.request.Request(
            f"{API_URL}?{query}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = json.load(response)
                if self.delay:
                    time.sleep(self.delay)
                return payload
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
                if attempt == 3:
                    raise RuntimeError(f"Wiki API request failed: {error}") from error
                time.sleep(min(20.0, 2.0 ** attempt))
        raise AssertionError("unreachable")

    def namespaces(self) -> list[int]:
        payload = self.request({"action": "query", "meta": "siteinfo", "siprop": "namespaces"})
        return namespace_ids(payload.get("query", {}).get("namespaces", []))

    def pages(self, namespace: int, *, include_redirects: bool = False) -> Iterator[dict[str, Any]]:
        continuation: dict[str, Any] = {}
        while True:
            parameters: dict[str, Any] = {
                "action": "query", "list": "allpages", "apnamespace": namespace,
                "aplimit": "max", **continuation,
            }
            if not include_redirects:
                parameters["apfilterredir"] = "nonredirects"
            payload = self.request({
                **parameters,
            })
            yield from payload.get("query", {}).get("allpages", [])
            continuation = payload.get("continue", {})
            if not continuation:
                return

    def details(self, page_ids: list[int]) -> list[dict[str, Any]]:
        payload = self.request({
            "action": "query", "pageids": "|".join(map(str, page_ids)),
            "prop": "extracts|revisions|info", "explaintext": 1,
            "exsectionformat": "plain", "inprop": "url", "rvprop": "ids|timestamp|content",
            "rvslots": "main",
        })
        pages = payload.get("query", {}).get("pages", [])
        if not isinstance(pages, list):
            return []
        return pages


def _plain_text(page: dict[str, Any]) -> str:
    extract = page.get("extract")
    if isinstance(extract, str) and extract.strip():
        return html.unescape(extract).strip()
    revisions = page.get("revisions") or []
    if not revisions:
        return ""
    slots = revisions[0].get("slots", {})
    source = slots.get("main", {}).get("content", "")
    return source.strip() if isinstance(source, str) else ""


def _index_document(database_path: Path, source: str, content: str, title: str) -> None:
    from bot.mod.ai.knowledge.service import KnowledgeDocument, KnowledgeService
    from bot.mod.ai.database import AiDatabase

    KnowledgeService(AiDatabase(database_path)).index(
        KnowledgeDocument(
            source_id=source,
            title=title,
            content=content,
            origin=WIKI_URL,
        ),
        now=int(time.time()),
    )


def _write_license(output_dir: Path) -> None:
    (output_dir / "LICENSE.md").write_text(
        "# 中文 Minecraft Wiki 資料來源\n\n"
        f"來源：{WIKI_URL}\n\n"
        f"本目錄的 Wiki 內容依 {LICENSE} 授權；使用、散布或修改時必須保留"
        "頁面內的來源連結、作者歸屬與相同授權條件。\n",
        encoding="utf-8",
    )


def import_wiki(args: argparse.Namespace) -> tuple[int, int]:
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_license(output_dir)
    state_path = output_dir / ".import-state.json"
    state = _load_state(state_path)
    completed = {int(page_id) for page_id in state.get("completed_page_ids", [])}
    client = WikiClient(delay=args.delay)
    namespaces = selected_namespaces(args, client)
    discovered = imported = 0
    pending: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal imported
        if not pending:
            return
        records = client.details([int(page["pageid"]) for page in pending])
        by_id = {int(page["pageid"]): page for page in records if "pageid" in page}
        for listed in pending:
            page_id = int(listed["pageid"])
            page = by_id.get(page_id, listed)
            title = str(page.get("title", listed["title"]))
            text = _plain_text(page)
            revisions = page.get("revisions") or []
            revision = revisions[0] if revisions else {}
            revision_id = int(revision.get("revid", 0))
            source_url = f"{WIKI_URL}w/{urllib.parse.quote(title.replace(' ', '_'))}"
            if revision_id:
                source_url += f"?oldid={revision_id}"
            relative = safe_filename(title, page_id)
            content = render_markdown(
                title=title, page_id=page_id, revision_id=revision_id,
                revision_timestamp=str(revision.get("timestamp", "")),
                fetched_at=datetime.now(UTC).isoformat(), source_url=source_url, text=text,
            )
            (output_dir / relative).write_text(content, encoding="utf-8")
            if args.index and text:
                _index_document(args.database, f"mcwiki/{relative}", content, title)
            completed.add(page_id)
            imported += 1
        state["completed_page_ids"] = sorted(completed)
        state["updated_at"] = datetime.now(UTC).isoformat()
        _atomic_json(state_path, state)
        print(f"imported={imported} completed={len(completed)}")
        pending.clear()

    for namespace in namespaces:
        print(f"listing namespace={namespace}")
        for page in client.pages(namespace):
            discovered += 1
            if int(page["pageid"]) in completed:
                continue
            pending.append(page)
            if len(pending) >= args.batch_size:
                flush()
            if args.max_pages and imported >= args.max_pages:
                flush()
                return discovered, imported
    flush()
    return discovered, imported


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Chinese Minecraft Wiki pages to local AI knowledge.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", type=Path, default=ROOT_DIR / "data" / "database" / "ai.db")
    parser.add_argument("--namespace", type=int, help="Import one MediaWiki namespace only.")
    parser.add_argument(
        "--all-namespaces",
        action="store_true",
        help="Also import discussion, template, and file-description namespaces.",
    )
    parser.add_argument("--max-pages", type=int, default=0, help="Limit pages for a smoke run; 0 means all.")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between API calls.")
    parser.add_argument("--no-index", dest="index", action="store_false", help="Only save Markdown, do not update SQLite FTS.")
    parser.set_defaults(index=True)
    args = parser.parse_args()
    discovered, imported = import_wiki(args)
    print(f"finished: discovered={discovered} imported={imported}")


if __name__ == "__main__":
    main()
