"""Этап 2: чистим собранное и расставляем теги.

Что делает:
  1. Убирает дубли (одинаковые ссылки или заголовки).
  2. Отбрасывает новости со стоп-словами из topics.yaml.
  3. Ставит теги по ключевым словам из topics.yaml.
  4. Пишет data/filtered.json (для сводки) и reports/filtered.md (для человека).
"""

import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

REGIONAL_TAG = "Законодательство: регионы"
LAW_TAG = "Законодательство"


def compile_keyword(word: str) -> re.Pattern:
    """Ключевое слово → поиск начала слова (или регулярное выражение с «re:»)."""
    if word.startswith("re:"):
        return re.compile(word[3:], re.IGNORECASE)
    # перед словом не должно быть буквы: «закон» найдёт «законопроект», но не «беззаконие»
    return re.compile(r"(?<![a-zа-яё])" + re.escape(word.lower()), re.IGNORECASE)


def compile_list(words: list[str]) -> list[re.Pattern]:
    return [compile_keyword(str(w)) for w in words or []]


def matches(text: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


def normalize(title: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", " ", title.lower()).strip()


def dedupe(items: list[dict]) -> tuple[list[dict], int]:
    seen_links, seen_titles, result = set(), set(), []
    for item in items:
        link = item["link"].split("?")[0].rstrip("/")
        title = normalize(item["title"])
        if link in seen_links or (title and title in seen_titles):
            continue
        seen_links.add(link)
        seen_titles.add(title)
        result.append(item)
    return result, len(items) - len(result)


def main():
    config = yaml.safe_load(Path("topics.yaml").read_text(encoding="utf-8"))
    topics = {name: compile_list(words) for name, words in config["topics"].items()}
    regional = compile_list(config.get("regional"))
    exclude = compile_list(config.get("exclude"))

    items = json.loads(Path("data/items.json").read_text(encoding="utf-8"))
    items, duplicates = dedupe(items)

    kept, other, excluded = [], [], []
    for item in items:
        text = f"{item['title']} {item.get('summary', '')}".lower()
        if matches(text, exclude):
            excluded.append(item)
            continue
        tags = [name for name, patterns in topics.items() if matches(text, patterns)]
        if LAW_TAG in tags and item.get("region") == "RU" and matches(text, regional):
            tags.append(REGIONAL_TAG)
        item["tags"] = tags
        (kept if tags else other).append(item)

    Path("data").mkdir(exist_ok=True)
    Path("data/filtered.json").write_text(
        json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Кандидаты для сводки: всё без дублей и мусора, с тегами и без.
    # Окончательно решает Claude: правила могли пропустить важное.
    Path("data/candidates.json").write_text(
        json.dumps(kept + other, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---------- отчёт для человека ----------
    by_tag = defaultdict(list)
    for item in kept:
        for tag in item["tags"]:
            by_tag[tag].append(item)

    def line(i: dict) -> str:
        tags = f" `{', '.join(i['tags'])}`" if i.get("tags") else ""
        return f"- **{i['source']}**: [{i['title']}]({i['link']}){tags}"

    lines = [
        "## Фильтр новостей\n",
        f"- Всего собрано: {len(items) + duplicates}",
        f"- Дублей убрано: {duplicates}",
        f"- Отброшено стоп-словами: {len(excluded)}",
        f"- Без тегов («Прочее»): {len(other)}",
        f"- **Осталось для сводки: {len(kept)}**\n",
        "| Тег | Новостей |", "|---|---|",
        *[f"| {tag} | {len(by_tag.get(tag, []))} |" for tag in [*topics, REGIONAL_TAG]],
    ]
    for tag in [*topics, REGIONAL_TAG]:
        if by_tag.get(tag):
            lines += [f"\n### {tag}\n", *[line(i) for i in by_tag[tag]]]
    lines += ["\n### Отброшено стоп-словами\n", *[line(i) for i in excluded]]
    lines += ["\n### Прочее (без тегов, в сводку не идёт)\n", *[line(i) for i in other]]

    Path("reports").mkdir(exist_ok=True)
    Path("reports/filtered.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    main()
