---
source: документация API Директа (yandex.ru/dev/direct/doc/dg/objects/ad.html) + проверка на живом аккаунте
verified: 2026-08-18, аккаунт e-16512855, 526 объявлений
note: комбинаторные объявления в API — тип RESPONSIVE_AD и версия v501
---

# Комбинаторные объявления в API: RESPONSIVE_AD и версия v501

**Правило: если объявление комбинаторное — работать через `ResponsiveAd` и endpoint `v501`.** Путь через `TextAd` в `v5` формально отвечает, но врёт при чтении и отказывает при записи.

## Что это

Комбинаторное объявление (несколько заголовков, текстов, изображений, из которых Директ сам собирает комбинации) в API называется **`RESPONSIVE_AD`**. С июля 2026 такие объявления используются в Единых перфоманс-кампаниях вместо текстово-графических.

Полный список типов в `Type`: TEXT_AD, SMART_AD, MOBILE_APP_AD, DYNAMIC_TEXT_AD, IMAGE_AD, CPC_VIDEO_AD, CPM_BANNER_AD, CPM_VIDEO_AD, SHOPPING_AD, LISTING_AD, **RESPONSIVE_AD**.

## Версии endpoint

| Операция | v5 | v501 |
|---|---|---|
| `get` с `ResponsiveAdFieldNames` | работает | работает |
| `update` с `ResponsiveAd` | **ошибка 3500** «Объявление данного типа не поддерживается в v5, используйте v501» | работает |
| `update` с `TextAd` у комбинаторного | проходит, но с предупреждением **10252** «Комбинаторный баннер изменён через устаревший API текстовых баннеров» | — |

```
https://api.direct.yandex.com/json/v5/ads     ← только чтение комбинаторных
https://api.direct.yandex.com/json/v501/ads   ← чтение и запись
```

## Ловушка при чтении через TextAdFieldNames

Один и тот же объект отдаётся по-разному в зависимости от запрошенных полей:

- запросили `TextAdFieldNames` → `"Type": "TEXT_AD"`, объект `TextAd` с **одним** `Title` и **одним** `Text`;
- запросили `ResponsiveAdFieldNames` → `"Type": "RESPONSIVE_AD"`, объект `ResponsiveAd` с массивами `Titles[]` и `Texts[]`.

То есть через `TextAd` видно только первый заголовок и первый текст — остальная комбинаторика скрыта. Для ссылок разницы нет, для аудита текстов — критично: легко решить, что у объявления один заголовок, и затереть остальные.

## Поля ResponsiveAd

Точный перечень, который принимает `ResponsiveAdFieldNames` (выдан самим API в тексте ошибки при неверном значении):

```
AdImages, DisplayDomain, Href, FinalUrl, SitelinkSetId, Texts, Titles,
DisplayUrlPath, DutPrefix, DutSuffix, SitelinksModeration, AdExtensions,
DisplayUrlPathModeration, PriceExtension, VideoExtensions,
ButtonExtensionModeration, BusinessId, TrackingPhoneId, ButtonExtension,
ErirAdDescription, TrackingParams, Carousel
```

Обратите внимание: `Titles` и `Texts` — массивы объектов вида `{"Title": "...", "Status": "ACCEPTED"}`. Поля `Title2` у комбинаторных нет.

## Рецепт: массовая замена ссылок

```bash
# 1. Прочитать текущее состояние (v5 или v501)
curl -s -X POST https://api.direct.yandex.com/json/v501/ads \
  -H "Authorization: Bearer $TOKEN" -H "Client-Login: $LOGIN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"method":"get","params":{
        "SelectionCriteria":{"CampaignIds":[123456],"States":["ON","SUSPENDED","OFF"]},
        "FieldNames":["Id","CampaignId","AdGroupId","Type","State"],
        "ResponsiveAdFieldNames":["Href","Titles","Texts"],
        "Page":{"Limit":1000}}}'

# 2. Обновить только Href, сохранив UTM-хвост каждого объявления
curl -s -X POST https://api.direct.yandex.com/json/v501/ads \
  -H "Authorization: Bearer $TOKEN" -H "Client-Login: $LOGIN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"method":"update","params":{"Ads":[
        {"Id":16493618202,"ResponsiveAd":{"Href":"https://site.ru/page?utm..."}}]}}'
```

Передавать в `update` только изменяемые поля — остальные остаются как были. Батчи до 1000 объектов за вызов; на практике удобнее по 200.

## Лимиты, о которые ломается XLS

**В одной группе допустимо до 3 неархивных комбинаторных объявлений и до 10 с учётом архивных.**

Отсюда следствие, которое стоит знать заранее: **выгрузку кампании с комбинаторными объявлениями часто невозможно загрузить обратно через XLS**. Директ проверяет лимит на весь файл, а в старых кампаниях групп с 9–16 объявлениями сколько угодно — они создавались до введения лимита. Ошибки при загрузке:

```
Строка N: В одной группе не может быть более 3 баннеров типа комбинаторное
Строка N: В одной группе не может быть более 10 архивных баннеров типа комбинаторное
```

Правкой файла это не обходится — ни включением архивных в выгрузку, ни удалением лишних строк. **Для таких кампаний массовые правки делать только через API.**

## Проверено

18.08.2026 на аккаунте с 526 активными объявлениями: чтение через оба варианта полей, `update` в v5 (предупреждение 10252) и в v501 (чисто), лимиты подтверждены отказом XLS-загрузки.
