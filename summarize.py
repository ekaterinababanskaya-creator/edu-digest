"""Этап 3: Claude отбирает важное и пишет сводку.

Что делает:
  1. Берёт data/candidates.json (новости без дублей и мусора).
  2. Отправляет их Claude вместе с описанием читателя и формата.
  3. Получает ответ строго по схеме: разделы, теги, «почему важно».
  4. Подставляет ссылки и источники сам (Claude их не переписывает,
     поэтому выдумать ссылку он не может).
  5. Пишет data/digest.json (для веб-страницы) и reports/digest.md (для чтения).

Запуск без ключа: python summarize.py --dry-run
  покажет, что именно уйдёт в Claude, и ничего не отправит.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MODEL = "claude-sonnet-5-5"
MAX_ITEMS_IN_DIGEST = 35

COMPETITORS = [
    "Онлайн-школа №1", "БИТ", "ИнтернетУрок", "100балльный репетитор", "Учи.ру",
    "Тетрика", "Умназия", "Skysmart", "Онлайн-гимназия №1", "Наши пенаты", "Феникс",
]

SECTIONS = [
    "Россия: регулирование и госполитика",
    "Конкуренты",
    "Россия: рынок и EdTech",
    "Мир: K-12 политика и практика",
    "Мир: EdTech и инвестиции",
    "Исследования и данные",
]
TAGS = [
    "ФГОС",
    "ГИА",
    "Семейное образование",
    "Законодательство",
    "Законодательство: регионы",
    "EdTech и ИИ",
    "Исследования и данные",
    "У конкурентов",
]

# Это главный «рычаг» качества. Хочешь другую сводку — правь этот текст.
SYSTEM_PROMPT = f"""Ты аналитик рынка школьного образования. Готовишь еженедельную сводку
для руководителя продукта и стратегии и её команды в Домашней школе Фоксфорда.

О читателе:
- Домашняя школа Фоксфорда — российская онлайн-школа для детей 1–11 классов
  на семейном обучении. Помогает с прикреплением к школе, промежуточной
  аттестацией и подготовкой к ГИА (ОГЭ, ЕГЭ).
- Команде важны: изменения ФГОС и федеральных программ, ГИА и ВПР,
  регулирование семейного образования и аттестации, законы и приказы
  (федеральные и региональные), рынок онлайн-образования и EdTech, ИИ в школе,
  мировые тренды K-12, которые могут прийти в Россию.

Конкуренты Домашней школы: {", ".join(COMPETITORS)}, а также все источники
с пометкой «конкурент» в колонке «найдено по запросу» (в том числе их Telegram-каналы).
По ним команде важно всё: новые продукты, тарифы и цены, изменения в прикреплении
к школам, партнёрства с регионами, события и мероприятия, рекламные кампании,
инвестиции и любые другие новости.

Правила для конкурентов:
- Новость о конкуренте попадает в раздел «Конкуренты» с тегом «У конкурентов»
  (и с другими подходящими тегами). Включай все такие новости, даже небольшие.
- Названия бывают неоднозначными («Феникс», «БИТ», «Наши пенаты»). Бери новость,
  только если она точно про эту онлайн-школу или образовательную компанию,
  а не про одноимённую фирму, клуб или ресторан.
- В «Почему важно» оцени, что это значит для Домашней школы: угроза, возможность,
  что стоит проверить у себя.
- Если про конкурента пишут несколько изданий, объедини в одну новость.
- Посты из Telegram-каналов конкурентов — это их собственные анонсы. Пересказывай
  факты (что запустили, сколько стоит, когда событие), без рекламных формулировок.
  Однотипные посты одного канала за неделю объединяй.

Правила отбора:
- Бери только то, что касается школьного образования (K-12) или рынка, на котором
  работает онлайн-школа. Пропускай: дошкольное и высшее образование (если это
  не влияет на школу), научпоп, медицину, конкурсы и награды, праздники,
  юбилеи, культурные мероприятия, местные происшествия.
- Не больше {MAX_ITEMS_IN_DIGEST} новостей. Вне раздела «Конкуренты» лучше меньше, но важнее.
- Если несколько материалов про одно событие, объедини их в одну новость
  и перечисли все id.

Правила текста:
- Пиши по-русски, коротко и по делу, без восклицаний и общих слов.
- Зарубежные новости пересказывай по-русски, термины поясняй.
- «Почему важно» пиши конкретно для Домашней школы: что это меняет для продукта,
  родителей, учеников или регуляторных рисков. Если прямой связи нет, так и
  скажи: «сигнал тренда» и чем он интересен.
- Опирайся только на то, что есть в материалах. Не додумывай факты.
"""

DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "Одно-два предложения: главное за неделю.",
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "id исходных материалов",
                    },
                    "title": {"type": "string", "description": "Заголовок по-русски"},
                    "summary": {"type": "string", "description": "Суть в 2–3 предложениях"},
                    "why_it_matters": {"type": "string", "description": "Почему важно для Домашней школы"},
                    "section": {"type": "string", "enum": SECTIONS},
                    "tags": {"type": "array", "items": {"type": "string", "enum": TAGS}},
                    "importance": {
                        "type": "integer",
                        "description": "3 — главное за неделю, 2 — важно, 1 — для сведения",
                    },
                },
                "required": ["ids", "title", "summary", "why_it_matters", "section", "tags", "importance"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "items"],
    "additionalProperties": False,
}


def build_user_message(candidates: list[dict]) -> str:
    lines = ["Материалы за неделю (id | источник | регион | найдено по запросу | заголовок | описание):\n"]
    for i, c in enumerate(candidates):
        summary = (c.get("summary") or "")[:300].replace("\n", " ")
        via = c.get("via", "")
        if c.get("kind") == "competitor":
            via = f"конкурент: {via}"
        lines.append(f"{i} | {c['source']} | {c.get('region', '')} | {via} | {c['title']} | {summary}")
    lines.append("\nОтбери важное и верни сводку по схеме.")
    return "\n".join(lines)


def call_claude(user_message: str) -> dict:
    import anthropic

    # strip() убирает случайные пробелы и переносы строк, попавшие при копировании ключа
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    response = client.messages.create(
        model=MODEL,
        max_tokens=12000,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": DIGEST_SCHEMA}},
        messages=[{"role": "user", "content": user_message}],
    )
    print(f"Токены: на входе {response.usage.input_tokens}, на выходе {response.usage.output_tokens}")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError(f"Claude не вернул сводку (stop_reason={response.stop_reason})")
    return json.loads(text)


def attach_sources(digest: dict, candidates: list[dict]) -> dict:
    """Ссылки и источники подставляем из исходных данных, а не из ответа модели."""
    canon = {x.lower(): x for x in SECTIONS + TAGS}
    for item in digest["items"]:
        item["section"] = canon.get(item["section"].lower(), item["section"])
        item["tags"] = [canon.get(t.lower(), t) for t in item["tags"]]
        item["importance"] = min(3, max(1, int(item["importance"])))
        valid = [i for i in item["ids"] if 0 <= i < len(candidates)]
        item["sources"] = [
            {"name": candidates[i]["source"], "title": candidates[i]["title"], "link": candidates[i]["link"]}
            for i in valid
        ]
        item.pop("ids", None)
    digest["items"] = [i for i in digest["items"] if i["sources"]]
    digest["generated_at"] = datetime.now(timezone.utc).isoformat()
    digest["candidates_count"] = len(candidates)
    return digest


def render_markdown(digest: dict) -> str:
    date = digest["generated_at"][:10]
    lines = [f"# Сводка новостей K-12 · {date}\n", f"> {digest['headline']}\n"]

    def block(item: dict) -> list[str]:
        links = ", ".join(f"[{s['name']}]({s['link']})" for s in item["sources"])
        return [
            f"**{item['title']}**  ",
            f"{item['summary']}  ",
            f"*Почему важно:* {item['why_it_matters']}  ",
            f"`{', '.join(item['tags'])}` · {links}\n",
        ]

    top = [i for i in digest["items"] if i["importance"] == 3][:5]
    if top:
        lines.append("## Главное за неделю\n")
        for item in top:
            lines += block(item)

    for section in SECTIONS:
        section_items = [i for i in digest["items"] if i["section"] == section and i not in top]
        if not section_items:
            continue
        section_items.sort(key=lambda i: -i["importance"])
        lines.append(f"## {section}\n")
        for item in section_items:
            lines += block(item)

    lines.append(f"---\nОтобрано {len(digest['items'])} из {digest['candidates_count']} материалов.")
    return "\n".join(lines)


def main():
    candidates = json.loads(Path("data/candidates.json").read_text(encoding="utf-8"))
    user_message = build_user_message(candidates)

    if "--dry-run" in sys.argv:
        print(f"Материалов: {len(candidates)}, символов в запросе: {len(user_message) + len(SYSTEM_PROMPT)}")
        print(user_message[:1500])
        return

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Нет ключа ANTHROPIC_API_KEY. Добавь его в Secrets репозитория.")

    try:
        raw = call_claude(user_message)
    except Exception as e:
        # Пишем ошибку так, чтобы её было видно на странице запуска и в репозитории
        message = f"{type(e).__name__}: {e}"[:1500]
        print(f"::error::{message}")
        Path("reports").mkdir(exist_ok=True)
        Path("reports/error.md").write_text(f"# Ошибка сводки\n\n```\n{message}\n```\n", encoding="utf-8")
        sys.exit(1)

    Path("reports/error.md").unlink(missing_ok=True)
    digest = attach_sources(raw, candidates)
    Path("data/digest.json").write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("reports").mkdir(exist_ok=True)
    Path("reports/digest.md").write_text(render_markdown(digest), encoding="utf-8")
    print(f"Готово: {len(digest['items'])} новостей в сводке → reports/digest.md")


if __name__ == "__main__":
    main()
