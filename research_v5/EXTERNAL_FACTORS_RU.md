# Допуск внешних признаков в BTC-прогноз

Состояние 3 октября 2026 года: численная голова v2.9.30 в prospective epoch 5
использует закрытые свечи BTC; optional DXY, Nasdaq futures, US10Y, funding,
OI, ETF и макро имеют вес 0. В режиме v4 контекст поступает как подписанное
диагностическое объяснение, но его баллы классов не калиброваны. Статусы
`STALE`, `TRANSPORT_FAILED`, `UNKNOWN_NOT_USED_BY_FROZEN_NUMERIC_CORE` не
заменяются прошлыми или вручную придуманными значениями.

Для NFP (BLS), PCE (BEA), ISM Manufacturing/Services требуется запись
`observation_period`, `scheduled_utc`, `published_utc`, `first_seen_utc`,
`capture_utc`, `source_url`, `raw_sha256`, `revision_id`, `value_status`.
Исследовательская проверка в `availability_ledger.py` допускает только
архивированный официальный raw, увиденный и захваченный до anchor. При
отсутствии такого снимка фактор считается недоступным. Коррекции публикации
получают новый `revision_id`; исходную версию нельзя молча переписать.

Официальные календари:

- NFP: https://www.bls.gov/schedule/news_release/empsit.htm
- PCE: https://www.bea.gov/news/schedule/full
- ISM: https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/

Календарь объявляет событие заранее, но не сообщает опубликованное значение.
Время расписания не может подменить время первого получения raw. Дата/время
публикации в американском Eastern должны переводиться по IANA `America/New_York`,
учитывая летнее время. Для DXY/Nasdaq/US10Y в часы закрытого рынка статус
`MARKET_CLOSED_LAST_SESSION` или `STALE` — нормальное отсутствие свежего
значения, а не нулевой сигнал.

Следующий численный допуск возможен только после накопления фактически
доступных as-of наблюдений, сравнения на одинаковых слотах со spot-only
базовой моделью и улучшения Brier/Log Loss на нетронутом блоке и затем
prospective. Пока таких данных нет, публикация вероятности «с учётом макро»
запрещена.
