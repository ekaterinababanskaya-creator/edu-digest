"""Этап 4: архив выпусков и сборка веб-страницы.

Что делает:
  1. Если есть свежая сводка data/digest.json — кладёт её в архив
     archive/ГГГГ-ММ-ДД.json (архив хранится в репозитории).
  2. Собирает папку site/: страницу index.html и все выпуски из архива.
  3. GitHub Pages публикует site/ по постоянной ссылке.
"""

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

MOSCOW = timezone(timedelta(hours=3))


def archive_fresh_digest() -> None:
    fresh = Path("data/digest.json")
    if not fresh.exists():
        print("Свежей сводки нет — публикую архив как есть")
        return
    digest = json.loads(fresh.read_text(encoding="utf-8"))
    generated = datetime.fromisoformat(digest["generated_at"]).astimezone(MOSCOW)
    target = Path("archive") / f"{generated:%Y-%m-%d}.json"
    target.parent.mkdir(exist_ok=True)
    # Повторный запуск в тот же день заменяет выпуск этого дня
    target.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Выпуск сохранён в архив: {target}")


def build_site() -> None:
    site = Path("site")
    shutil.rmtree(site, ignore_errors=True)
    (site / "issues").mkdir(parents=True)
    shutil.copy("template/index.html", site / "index.html")

    issues = []
    for path in sorted(Path("archive").glob("*.json"), reverse=True):
        shutil.copy(path, site / "issues" / path.name)
        issues.append({"date": path.stem, "file": f"issues/{path.name}"})

    (site / "issues" / "index.json").write_text(
        json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Сайт собран: {len(issues)} выпуск(ов) в архиве")


if __name__ == "__main__":
    archive_fresh_digest()
    build_site()
