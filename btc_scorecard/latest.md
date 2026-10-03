# BTC: подписанная сравнительная таблица (теневой режим)

Обновлено: 03.10.2026 10:33 МСК.
В колонке v4 указаны некалиброванные баллы. Brier v4 — только диагностика;
события v5 и v4 используют собственные определения классов, их оценки нельзя
считать прямым сравнением качества без общей метки. Исходы появляются после due.

| Якорь МСК | v2.9.30 4ч | v4 режим | Рост >1% | Падение <−1% | Арбитр | Исходы |
|---|---|---|---|---|---|---|
| 03.10 01:00 | — | DOWN_TRANSITION | 0.045 / нет | PENDING | NO_DIRECTIONAL_TAIL_WARNING | ↑нет |
| 03.10 02:00 | — | DOWN_CONTINUATION | 0.059 / нет | PENDING | NO_DIRECTIONAL_TAIL_WARNING | ↑нет |
| 03.10 03:00 | 0.151/0.711/0.139 | DOWN_CONTINUATION | 0.057 / нет | PENDING | NO_DIRECTIONAL_TAIL_WARNING | ↑нет, v5:range |
| 03.10 04:00 | — | FALSE_BREAKOUT_DOWN | 0.064 / нет | PENDING | NO_DIRECTIONAL_TAIL_WARNING | ↑нет |
| 03.10 05:00 | — | FALSE_BREAKOUT_DOWN | 0.061 / нет | PENDING | NO_DIRECTIONAL_TAIL_WARNING | ↑нет |
| 03.10 06:00 | — | FALSE_BREAKOUT_DOWN | 0.056 / нет | PENDING | NO_DIRECTIONAL_TAIL_WARNING | ↑нет |
| 03.10 07:00 | 0.136/0.718/0.145 | FALSE_BREAKOUT_DOWN | 0.061 / нет | PENDING | NO_DIRECTIONAL_TAIL_WARNING | ожидание |
| 03.10 08:00 | — | FALSE_BREAKOUT_DOWN | 0.057 / нет | PENDING | NO_DIRECTIONAL_TAIL_WARNING | ожидание |
| 03.10 09:00 | — | FALSE_BREAKOUT_DOWN | 0.040 / нет | PENDING | NO_DIRECTIONAL_TAIL_WARNING | ожидание |
| 03.10 10:00 | — | FALSE_BREAKOUT_DOWN | 0.067 / нет | PENDING | NO_DIRECTIONAL_TAIL_WARNING | ожидание |

Численные Brier и Log Loss по каждому завершённому исходу, пропуски и задержки
доступны в `latest.json`. Вероятности класса v4 не опубликованы.
