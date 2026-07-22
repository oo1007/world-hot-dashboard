---
name: world-hot
description: Generate Chinese global news and trend briefings from public RSS/Atom sources and news hot lists. Use when the user asks for world news, global headlines, daily news briefs, current events, international热点, 世界新闻, 全球热点, 今日大事, 每日新闻推送, or wants a scheduled briefing similar to the aihot skill but focused on non-AI global events.
---

# World Hot

## Overview

Use this skill to collect same-day global news and trend signals, then synthesize them into a concise Chinese briefing. Prefer it for recurring daily briefings and ad-hoc requests like "今天世界发生了什么" or "给我一份全球热点日报".

## Workflow

1. Run `scripts/collect_world_hot.py` to collect recent items from the source list.
2. Read the generated Markdown or JSON.
3. Deduplicate related headlines across sources.
4. Write a Chinese brief with these sections when useful:
   - 今日全球 10 件大事
   - 地区热点: 中国/亚太、美国、欧洲、中东、其他
   - 财经与市场
   - 科技与平台
   - 文化/体育/社会
   - 需要继续关注
5. Cite source links for factual claims. If a story appears in only one weak source or is unclear, label it as "待核实".

## Quick Start

Generate a 24-hour Markdown source digest:

```bash
python scripts/collect_world_hot.py --hours 24 --format markdown --output work/world-hot-today.md
```

Generate JSON for further processing:

```bash
python scripts/collect_world_hot.py --hours 24 --format json --output work/world-hot-today.json
```

If running from outside the skill directory, pass the absolute script path. The script uses `references/sources.json` by default.

## Briefing Rules

- Prefer events from the last 24 hours, using Asia/Shanghai as the user's reporting timezone unless the user says otherwise.
- Rank by cross-source repetition, source reliability, geopolitical/economic impact, public safety relevance, and trend signal strength.
- Do not present RSS titles as final truth when the item is developing; state what is known and what is uncertain.
- Avoid copying long article text. Use short paraphrases and source links.
- Keep the final brief in Chinese by default, with original English proper nouns preserved when clearer.
- For automation output, keep it skimmable: one short opening, grouped bullets, and a "明天继续关注" section.

## Sources

The default source list is in `references/sources.json`. It includes broad global feeds and trend feeds such as BBC World, The Guardian World, Al Jazeera, NPR World, DW, France 24, UN News, Google News topics, Techmeme, Hacker News, and Google Trends daily feeds.

When the user asks to change coverage, edit `references/sources.json` first. Good additions are official RSS feeds, public news APIs with stable keys, or internally trusted endpoints. Avoid sources that require scraping logged-in pages unless the user explicitly asks.

## Script Notes

`scripts/collect_world_hot.py`:

- Fetches RSS/Atom feeds with timeout and per-source limits.
- Normalizes title, link, source, category, published time, and summary.
- Filters by recency when publish dates are available.
- Deduplicates similar titles using normalized title keys.
- Scores items using source repetition, recency, topic keywords, and source weight.
- Emits Markdown or JSON.
