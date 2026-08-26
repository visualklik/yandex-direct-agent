---
source: официальная документация API Метрики (yandex.ru/dev/metrika) + проверка на живом счётчике
verified: 2026-08
---

# API Метрики: проверенные факты и грабли

Токен передаётся заголовком `Authorization: OAuth <token>` — не `Bearer`, как в Директе.
**Токен Директа к Метрике доступа не даёт**: проверено, `403 access_denied`. Нужен отдельный,
выпускается там же в Яндекс OAuth.

```bash
set -a && . ./.env && set +a          # METRIKA_TOKEN, METRIKA_COUNTER
```

## Management API — настройки

Базовый адрес `https://api-metrika.yandex.net/management/v1`.

| Запрос | Что отдаёт |
|---|---|
| `/counters?per_page=200` | все счётчики токена: id, site, name, permission |
| `/counter/{id}` | настройки счётчика целиком |
| `/counter/{id}/goals` | цели: id, name, type, flag, условия |
| `/counter/{id}/filters` | фильтры трафика |
| `/counter/{id}/segments` | сегменты |
| `/counter/{id}/operations` | операции над данными |
| `/counter/{id}/grants` | выданные доступы |
| `/labels` | метки — **на уровне аккаунта, а не счётчика** |

Ответ на `/counter/{id}` содержит поля, из которых и собирается аудит:

```
status, code_status, activity_status   — живой ли счётчик и виден ли код на сайте
filter_robots                          — уровень фильтрации роботов
visit_threshold                        — таймаут визита в секундах (стандарт 1800)
time_zone_name, currency               — часовой пояс и валюта счётчика
webvisor.arch_enabled, webvisor.wv_forms — вебвизор и запись форм
code_options.ecommerce                 — включена ли электронная коммерция
code_options.clickmap, code_options.visor — карта кликов, вебвизор в коде
autogoals_enabled                      — автоцели
max_goals, max_filters, max_operations — лимиты счётчика
```

**Ловушка:** параметр `field=goals,filters,...` в запросе счётчика возвращает объект
с пустыми полями — разделы нужно запрашивать отдельными эндпоинтами, как в таблице выше.

## Reporting API — отчёты

`https://api-metrika.yandex.net/stat/v1/data`, параметры в query.

| Параметр | Смысл |
|---|---|
| `ids` | номер счётчика |
| `metrics` | до **20 метрик** на запрос |
| `dimensions` | измерения для группировки |
| `date1`, `date2` | даты или относительные `30daysAgo`, `yesterday` |
| `accuracy` | `full` — точный расчёт без выборки |
| `limit`, `offset` | постраничность |
| `sort` | поле сортировки, минус — по убыванию |

**Лимит в 20 метрик считается по всем метрикам запроса.** Для целей это значит не более
десяти целей за раз, если тянуть и достижения, и конверсию: `goal{id}reaches` плюс
`goal{id}conversionRate` — это уже две метрики на цель.

**Выборка.** Ответ содержит `sampled`, `sample_share`, `sample_size`. При `sampled: true`
цифры приблизительные. Лечится сужением периода или `accuracy=full`.

## Полезные измерения

| Измерение | Что даёт |
|---|---|
| `ym:s:lastsignTrafficSource` | источник трафика по последнему значимому переходу |
| `ym:s:lastDirectClickOrder` | **кампания Директа** — основа сверки двух систем |
| `ym:s:lastDirectBanner`, `ym:s:lastDirectPhraseOrCond` | объявление и условие показа |
| `ym:s:startURL` | страница входа — посадочные |
| `ym:s:deviceCategory`, `ym:s:browser` | устройства и браузеры |
| `ym:s:regionCity` | города |
| `ym:s:searchPhrase` | поисковые фразы (органика) |
| `ym:s:date` | динамика по дням |

Метрики визитов: `ym:s:visits`, `ym:s:users`, `ym:s:bounceRate`,
`ym:s:avgVisitDurationSeconds`, `ym:s:pageDepth`, `ym:s:goal{id}reaches`,
`ym:s:goal{id}conversionRate`.

## Logs API — сырые визиты

`/management/v1/counter/{id}/logrequests` — выгрузка на уровне отдельных визитов и хитов.
Перед заказом можно оценить объём:

```
GET /management/v1/counter/{id}/logrequests/evaluate
    ?date1=...&date2=...&fields=ym:s:visitID,ym:s:dateTime,...&source=visits
```

Ответ: `possible`, `expected_size`, `max_possible_day_quantity`. Проверено на живом
счётчике — выгрузка разрешена, недельный объём порядка десятков килобайт.

Это единственный способ сверить конверсии Директа и Метрики на уровне визитов,
а не сводных чисел. В аудит пока не входит: сначала слепок и отчёты.

## Прочие грабли

- Эндпоинта `/counter/{id}/yandexdirect/clients` **не существует** — запрос отдаёт
  HTML-страницу с 404, а не JSON. Факт связки с Директом проверяется по отчёту:
  есть ли визиты в разрезе `ym:s:lastDirectClickOrder`.
- Ошибки приходят в JSON с полями `errors`, `code`, `message` — но при неверном пути
  сервер отвечает HTML, поэтому парсер должен переживать не-JSON.
- Квоты у API есть, поэтому аудит работает по слепку: собрали один раз, дальше считаем
  локально.
