"""Этап 1: собираем свежие материалы из всех источников в sources.yaml.

Что делает:
  1. Для каждого источника находит RSS-ленту (если она не указана явно).
  2. Забирает материалы за последние DAYS дней.
  3. Печатает отчёт: какие источники работают, сколько материалов нашлось.
  4. Сохраняет всё в data/items.json — дальше этот файл прочитает сводка.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

DAYS = 7
TIMEOUT = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (EduDigest news collector)"}
COMMON_FEED_PATHS = ["/feed/", "/rss/", "/rss.xml", "/feed.xml", "/atom.xml", "/rss"]


def looks_like_feed(text: str) -> bool:
    head = text[:500].lower()
    return "<rss" in head or "<feed" in head or "<rdf" in head


def find_feed(site_url: str) -> str | None:
    """Ищем RSS: сначала в коде страницы, потом по типичным адресам."""
    try:
        page = requests.get(site_url, headers=HEADERS, timeout=TIMEOUT)
        if looks_like_feed(page.text):
            return site_url
        soup = BeautifulSoup(page.text, "html.parser")
        for link in soup.find_all("link", rel="alternate"):
            kind = (link.get("type") or "").lower()
            if "rss" in kind or "atom" in kind:
                return urljoin(site_url, link.get("href"))
    except requests.RequestException:
        pass

    for path in COMMON_FEED_PATHS:
        candidate = urljoin(site_url, path)
        try:
            r = requests.get(candidate, headers=HEADERS, timeout=TIMEOUT)
            if r.ok and looks_like_feed(r.text):
                return candidate
        except requests.RequestException:
            continue
    return None


def entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def collect_source(source: dict, since: datetime) -> tuple[list[dict], str]:
    feed_url = source.get("rss") or find_feed(source["url"])
    if not feed_url:
        return [], "❌ RSS не найден"

    try:
        r = requests.get(feed_url, headers=HEADERS, timeout=TIMEOUT)
        feed = feedparser.parse(r.content)
    except requests.RequestException as e:
        return [], f"❌ ошибка загрузки: {type(e).__name__}"

    if not feed.entries:
        return [], f"⚠️ лента пустая ({feed_url})"

    items = []
    for e in feed.entries:
        date = entry_date(e)
        if date and date < since:
            continue
        summary = BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ", strip=True)
        items.append({
            "source": source["name"],
            "region": source.get("region", ""),
            "title": e.get("title", "").strip(),
            "link": e.get("link", ""),
            "date": date.isoformat() if date else None,
            "summary": summary[:600],
        })
    return items, f"✅ {len(items)} за {DAYS} дн. ({feed_url})"


def main():
    sources = yaml.safe_load(Path("sources.yaml").read_text(encoding="utf-8"))
    since = datetime.now(timezone.utc) - timedelta(days=DAYS)

    all_items, report = [], []
    for s in sources:
        if not s.get("enabled", True):
            report.append((s["name"], "⏸ отключён"))
            continue
        items, status = collect_source(s, since)
        all_items.extend(items)
        report.append((s["name"], status))
        print(f"{s['name']}: {status}", flush=True)

    Path("data").mkdir(exist_ok=True)
    Path("data/items.json").write_text(
        json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Отчёт в виде таблицы — GitHub покажет его на странице запуска
    lines = [
        f"## Сбор новостей: {len(all_items)} материалов за {DAYS} дней\n",
        "| Источник | Статус |", "|---|---|",
        *[f"| {name} | {status} |" for name, status in report],
        "\n### Первые 30 заголовков\n",
        *[f"- **{i['source']}**: [{i['title']}]({i['link']})" for i in all_items[:30]],
    ]
    report_text = "\n".join(lines)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/sources.md").write_text(report_text, encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(report_text, encoding="utf-8")

    print(f"\nВсего: {len(all_items)} материалов → data/items.json")


if __name__ == "__main__":
    sys.exit(main())
