#!/usr/bin/env python3
"""Collect recent global news and trend items from RSS/Atom feeds."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT = 15
DEFAULT_MAX_PER_SOURCE = 25
USER_AGENT = "world-hot-codex-skill/1.0 (+https://openai.com/codex)"

HIGH_IMPACT_KEYWORDS = {
    "war": 8,
    "ceasefire": 7,
    "strike": 5,
    "missile": 6,
    "earthquake": 8,
    "flood": 7,
    "wildfire": 6,
    "election": 6,
    "president": 4,
    "prime minister": 4,
    "court": 3,
    "tariff": 5,
    "inflation": 5,
    "central bank": 5,
    "fed": 4,
    "market": 3,
    "oil": 4,
    "ai": 5,
    "artificial intelligence": 5,
    "cyber": 5,
    "data breach": 6,
    "pandemic": 7,
    "vaccine": 4,
    "climate": 5,
    "nuclear": 7,
    "sanction": 5,
    "summit": 4,
}


@dataclasses.dataclass
class Source:
    name: str
    url: str
    category: str = "world"
    weight: int = 1
    language: str = "en"


@dataclasses.dataclass
class Item:
    title: str
    link: str
    source: str
    category: str
    published: str | None
    published_ts: float | None
    summary: str
    language: str
    score: float
    duplicate_count: int = 1
    duplicate_sources: list[str] = dataclasses.field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def skill_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def load_sources(path: Path) -> list[Source]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Source(**entry) for entry in data.get("sources", [])]


def fetch_url(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def text_of(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return clean_text(element.text)


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def first_child(element: ET.Element, names: list[str]) -> ET.Element | None:
    for name in names:
        found = element.find(name)
        if found is not None:
            return found
    for child in element:
        local = child.tag.rsplit("}", 1)[-1]
        if local in names:
            return child
    return None


def first_text(element: ET.Element, names: list[str]) -> str:
    return text_of(first_child(element, names))


def first_link(element: ET.Element) -> str:
    link = first_child(element, ["link"])
    if link is None:
        return ""
    href = link.attrib.get("href")
    if href:
        return href.strip()
    return text_of(link)


def parse_date(value: str) -> tuple[str | None, float | None]:
    if not value:
        return None, None
    value = clean_text(value)
    parsed: dt.datetime | None = None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        pass
    if parsed is None:
        candidates = [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in candidates:
            try:
                parsed = dt.datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return value, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    parsed_utc = parsed.astimezone(dt.timezone.utc)
    return parsed_utc.isoformat(), parsed_utc.timestamp()


def parse_feed(xml_bytes: bytes, source: Source) -> list[Item]:
    root = ET.fromstring(xml_bytes)
    local_root = root.tag.rsplit("}", 1)[-1].lower()
    nodes: list[ET.Element]
    if local_root == "rss":
        nodes = root.findall("./channel/item")
    elif local_root == "feed":
        nodes = list(root.findall("{http://www.w3.org/2005/Atom}entry")) or root.findall("entry")
    else:
        nodes = list(root.iter("item"))

    items: list[Item] = []
    for node in nodes:
        title = first_text(node, ["title"])
        link = first_link(node)
        raw_date = first_text(node, ["pubDate", "published", "updated", "dc:date"])
        if not raw_date:
            for child in node:
                if child.tag.endswith("}date"):
                    raw_date = text_of(child)
                    break
        published, published_ts = parse_date(raw_date)
        summary = first_text(node, ["description", "summary", "content"])
        if not title or not link:
            continue
        score = float(source.weight)
        score += keyword_score(title + " " + summary)
        if published_ts:
            hours_old = max(0.0, (dt.datetime.now(dt.timezone.utc).timestamp() - published_ts) / 3600.0)
            score += max(0.0, 8.0 - min(hours_old, 48.0) / 6.0)
        items.append(
            Item(
                title=title,
                link=link,
                source=source.name,
                category=source.category,
                published=published,
                published_ts=published_ts,
                summary=summary,
                language=source.language,
                score=score,
                duplicate_sources=[source.name],
            )
        )
    return items


def keyword_score(text: str) -> float:
    lowered = text.lower()
    score = 0.0
    for keyword, weight in HIGH_IMPACT_KEYWORDS.items():
        if keyword in lowered:
            score += weight
    return min(score, 18.0)


STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "as",
    "by",
    "from",
    "at",
    "after",
    "over",
    "is",
    "are",
    "be",
    "was",
    "were",
    "will",
    "says",
    "say",
    "latest",
    "live",
}


def title_key(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]", " ", title.lower())
    words = [word for word in normalized.split() if word not in STOPWORDS and len(word) > 1]
    if not words:
        return hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
    return " ".join(words[:10])


def dedupe_items(items: list[Item]) -> list[Item]:
    grouped: dict[str, Item] = {}
    for item in items:
        key = title_key(item.title)
        current = grouped.get(key)
        if current is None:
            grouped[key] = item
            continue
        current.duplicate_count += 1
        if item.source not in current.duplicate_sources:
            current.duplicate_sources.append(item.source)
        current.score = max(current.score, item.score) + 3.0
        if item.published_ts and (not current.published_ts or item.published_ts > current.published_ts):
            current.published = item.published
            current.published_ts = item.published_ts
    return sorted(grouped.values(), key=lambda item: item.score, reverse=True)


def collect(args: argparse.Namespace) -> tuple[list[Item], list[dict[str, str]]]:
    sources = load_sources(args.sources)
    now_ts = dt.datetime.now(dt.timezone.utc).timestamp()
    cutoff = now_ts - args.hours * 3600 if args.hours else None
    all_items: list[Item] = []
    errors: list[dict[str, str]] = []

    for source in sources:
        try:
            feed_bytes = fetch_url(source.url, args.timeout)
            source_items = parse_feed(feed_bytes, source)
            source_items = source_items[: args.max_per_source]
            for item in source_items:
                if cutoff and item.published_ts and item.published_ts < cutoff:
                    continue
                all_items.append(item)
        except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as exc:
            errors.append({"source": source.name, "url": source.url, "error": str(exc)})

    return dedupe_items(all_items)[: args.limit], errors


def format_dt(value: str | None) -> str:
    if not value:
        return "unknown time"
    try:
        parsed = dt.datetime.fromisoformat(value)
        local = parsed.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def markdown_report(items: list[Item], errors: list[dict[str, str]], args: argparse.Namespace) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# World Hot Source Digest",
        "",
        f"- Generated: {now}",
        f"- Window: last {args.hours} hours",
        f"- Items: {len(items)}",
        "",
    ]
    grouped: dict[str, list[Item]] = {}
    for item in items:
        grouped.setdefault(item.category, []).append(item)

    for category in sorted(grouped, key=lambda key: max(item.score for item in grouped[key]), reverse=True):
        lines.append(f"## {category}")
        lines.append("")
        for idx, item in enumerate(grouped[category], 1):
            duplicate_note = ""
            if item.duplicate_count > 1:
                duplicate_note = f" | repeated sources: {', '.join(item.duplicate_sources)}"
            lines.append(f"{idx}. [{item.title}]({item.link})")
            lines.append(
                f"   - source: {item.source} | published: {format_dt(item.published)} | score: {item.score:.1f}{duplicate_note}"
            )
            if item.summary:
                wrapped = textwrap.shorten(item.summary, width=260, placeholder="...")
                lines.append(f"   - summary: {wrapped}")
        lines.append("")

    if errors:
        lines.append("## Fetch Errors")
        lines.append("")
        for error in errors:
            lines.append(f"- {error['source']}: {error['error']}")
        lines.append("")

    return "\n".join(lines)


def prompt_report(items: list[Item], errors: list[dict[str, str]], args: argparse.Namespace) -> str:
    source_digest = markdown_report(items, errors, args)
    instruction = """你是 World Hot 新闻简报助手。请基于下面的 source digest，生成中文《今日全球热点简报》。

要求：
1. 不要逐条翻译 RSS 标题，要合并相同事件、去重，并按重要性重排。
2. 优先输出 8-12 条全球大事，每条包含：一句话标题、发生了什么、为什么重要、来源链接。
3. 再输出 3-5 条趋势信号，覆盖科技/财经/社会文化中值得继续看的变化。
4. 对只来自单一弱源、Reddit、或信息不完整的内容标注“待核实”。
5. 全文使用中文，保留必要英文专名。
6. 不要编造 source digest 之外的事实；如需要额外核实，请在对应条目说明。

"""
    return instruction + "\n" + source_digest


def json_report(items: list[Item], errors: list[dict[str, str]], args: argparse.Namespace) -> str:
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "window_hours": args.hours,
        "item_count": len(items),
        "items": [item.as_dict() for item in items],
        "errors": errors,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=skill_dir() / "references" / "sources.json")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--max-per-source", type=int, default=DEFAULT_MAX_PER_SOURCE)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--format", choices=["markdown", "json", "prompt"], default="markdown")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    items, errors = collect(args)
    if args.format == "json":
        output = json_report(items, errors, args)
    elif args.format == "prompt":
        output = prompt_report(items, errors, args)
    else:
        output = markdown_report(items, errors, args)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
        if not output.endswith(os.linesep):
            sys.stdout.write(os.linesep)
    if not items:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
