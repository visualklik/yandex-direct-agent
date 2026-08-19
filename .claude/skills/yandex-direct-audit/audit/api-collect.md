# Снятие слепка аккаунта через API

Проверено на живом аккаунте, август 2026. Перечни полей получены от самого API — если передать
несуществующее имя, ошибка 8000 возвращает полный список допустимых значений. Приём удобный:
вместо сверки с документацией отправить `"FieldNames":["XXX"]` и прочитать ответ.

Токен и логин — в `.env` (`chmod 600`, в `.gitignore`), в файлы скилла не попадают.

```bash
set -a && . ./.env && set +a   # DIRECT_TOKEN, DIRECT_LOGIN
```

Общие заголовки:

```
Authorization: Bearer $DIRECT_TOKEN
Client-Login: $DIRECT_LOGIN
Accept-Language: ru
Content-Type: application/json; charset=utf-8
```

## Кампании

`FieldNames` (полный список из API):

```
Id, Name, Type, Status, State, StatusPayment, StatusClarification, StartDate, EndDate,
CreateTime, Currency, Funds, DailyBudget, Statistics, TimeTargeting, TimeZone,
NegativeKeywords, ExcludedSites, BlockedIps, Notification, ClientInfo, RepresentedBy, SourceId
```

`TextCampaignFieldNames` (то, ради чего аудит и делается):

```
BiddingStrategy, Settings, CounterIds, PriorityGoals, AttributionModel, RelevantKeywords,
TrackingParams, PackageBiddingStrategy, CanBeUsedAsPackageBiddingStrategySource,
NegativeKeywordSharedSetIds, WeeklyBudgetRollover
```

Аналогично существуют `UnifiedCampaignFieldNames`, `SmartCampaignFieldNames`,
`DynamicTextCampaignFieldNames`, `MobileAppCampaignFieldNames`, `CpmBannerCampaignFieldNames` —
набор зависит от типов кампаний в аккаунте. Тип узнаётся из `Type` в первом же запросе.

```bash
curl -s -X POST https://api.direct.yandex.com/json/v5/campaigns \
  -H "Authorization: Bearer $DIRECT_TOKEN" -H "Client-Login: $DIRECT_LOGIN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"method":"get","params":{
        "SelectionCriteria":{},
        "FieldNames":["Id","Name","Type","Status","State","Funds","DailyBudget","TimeTargeting",
                      "TimeZone","NegativeKeywords","ExcludedSites","BlockedIps","Notification"],
        "TextCampaignFieldNames":["BiddingStrategy","Settings","CounterIds","PriorityGoals",
                      "AttributionModel","RelevantKeywords","WeeklyBudgetRollover"]}}'
```

### Что читать в ответе

`Settings` — массив пар `{Option, Value}`. Реальный набор опций текстовой кампании:

```
ADD_METRICA_TAG, ADD_OPENSTAT_TAG, ADD_TO_FAVORITES, ALTERNATIVE_TEXTS_ENABLED,
CAMPAIGN_EXACT_PHRASE_MATCHING_ENABLED, DAILY_BUDGET_ALLOWED, ENABLE_AREA_OF_INTEREST_TARGETING,
ENABLE_COMPANY_INFO, ENABLE_EXTENDED_AD_TITLE, ENABLE_SITE_MONITORING,
EXCLUDE_PAUSED_COMPETING_ADS, MAINTAIN_NETWORK_CPC, REQUIRE_SERVICING, SHARED_ACCOUNT_ENABLED
```

`BiddingStrategy` разделён на `Search` и `Network`, у каждого свой `BiddingStrategyType`
и блок параметров (`AverageCpc`, `WeeklySpendLimit`, `BudgetType`, `GoalId`, …).
Денежные значения — в микроединицах валюты, если не передан заголовок `returnMoneyInMicros: false`.

## Группы, ключи, объявления, корректировки

```
adgroups:     Id, CampaignId, Name, Status, Type, Subtype, ServingStatus,
              RegionIds, RestrictedRegionIds, NegativeKeywords,
              NegativeKeywordSharedSetIds, TrackingParams

keywords:     Id, Keyword, State, Status, ServingStatus, AdGroupId, CampaignId,
              Bid, ContextBid, AutotargetingSearchBidIsAuto, StrategyPriority,
              Productivity, StatisticsSearch, StatisticsNetwork,
              AutotargetingCategories, AutotargetingBrandOptions, UserParam1, UserParam2

bidmodifiers: обязателен параметр Levels — ["CAMPAIGN"] и/или ["ADGROUP"]

ads:          Id, CampaignId, AdGroupId, Type, Subtype, State, Status, StatusClarification
              + ResponsiveAdFieldNames / TextAdFieldNames — см.
                ../../yandex-direct/updates/api-responsive-ads.md
```

Комбинаторные объявления читаются и правятся только через `v501` — при чтении через
`TextAdFieldNames` видно лишь первый заголовок и первый текст, остальное скрыто.

## Отчёт по площадкам

Асинхронный: первый ответ HTTP 201 (отчёт в очереди), повторять запрос до HTTP 200.
Заголовки: `processingMode: auto`, `returnMoneyInMicros: false`,
`skipReportHeader: true`, `skipReportSummary: true`.

```bash
curl -s -X POST https://api.direct.yandex.com/json/v5/reports \
  -H "Authorization: Bearer $DIRECT_TOKEN" -H "Client-Login: $DIRECT_LOGIN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "processingMode: auto" -H "returnMoneyInMicros: false" \
  -H "skipReportHeader: true" -H "skipReportSummary: true" \
  -d '{"params":{
        "SelectionCriteria":{"DateFrom":"2026-07-19","DateTo":"2026-08-18",
          "Filter":[{"Field":"AdNetworkType","Operator":"EQUALS","Values":["AD_NETWORK"]}]},
        "FieldNames":["Placement","AdNetworkType","Impressions","Clicks","Cost",
                      "Conversions","BounceRate","AvgPageviews"],
        "OrderBy":[{"Field":"Cost","SortOrder":"DESCENDING"}],
        "ReportName":"placements_30d","ReportType":"CUSTOM_REPORT",
        "DateRangeType":"CUSTOM_DATE","Format":"TSV","IncludeVAT":"YES"}}'
```

Тонкости:

- **`ReportName` должен быть уникальным** в пределах аккаунта. Повтор имени — ошибка;
  при отладке добавлять суффикс.
- Ошибка 8000 в reports **не перечисляет** допустимые поля, в отличие от остальных сервисов, —
  имена полей проверять запуском.
- Для конверсий по конкретной цели добавить `Goals` и `AttributionModels` в `SelectionCriteria`;
  без них `Conversions` считаются по настройкам аккаунта, и цифра не совпадёт с отчётом по цели.
- Другие полезные срезы того же отчёта: `ExternalNetworkName` (внешние сети),
  `MobilePlatform`, `Device`, `TargetingLocationName`, `Age`, `Gender`.

## Запись запрещённых площадок

`ExcludedSites` заменяется целиком, не дополняется:

```bash
# 1. прочитать текущий список, 2. объединить со своим, 3. отправить объединённый
-d '{"method":"update","params":{"Campaigns":[
      {"Id":10000000001,"ExcludedSites":{"Items":["site1.ru","com.example.app"]}}]}}'
```

Лимит — 1000 доменов для баннеров, 100 для видео. Перед правкой сохранять бэкап `get`.

## Ограничения, о которые спотыкаешься при первом прогоне

Проверено практикой, не документацией:

- **`SelectionCriteria.CampaignIds` — не более 10 значений за запрос.** Для аккаунта из 30 кампаний
  запросы к `adgroups`, `keywords`, `ads`, `bidmodifiers` резать на пачки по 10.
  Ошибка: «Превышено допустимое количество идентификаторов в массиве SelectionCriteria.CampaignIds».
- **`bidmodifiers`: `Levels` живёт внутри `SelectionCriteria`**, не рядом с ним, и принимает
  `CAMPAIGN` / `AD_GROUP` — не `ADGROUP`.
- **`v501` не принимает `TrackingParams`** ни в `ResponsiveAdFieldNames`, ни в `TextAdFieldNames`,
  хотя `v5` перечисляет это поле как допустимое. Ошибка невнятная: «Неизвестное поле
  ResponsiveAdFieldNames[7]» — номер в массиве и есть подсказка, какое поле убрать.
- **Постраничность**: ответ содержит `LimitedBy`, если данных больше лимита страницы. Читать
  до тех пор, пока `LimitedBy` возвращается, подставляя его в `Page.Offset`.
- Слепок аккаунта на ~30 кампаний / 300 групп / 3800 ключей / 500 объявлений снимается
  примерно за 30 секунд.
