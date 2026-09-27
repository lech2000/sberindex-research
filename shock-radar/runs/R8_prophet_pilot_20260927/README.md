# R8: причинный пилот Prophet, 27.09.2026

Статус: **PILOT_PARTIAL_NOT_GATE_PASS**; R8/source08 открыт.
32 ряда выбраны по ключам и seed=20260927 без просмотра значений; 438 общих прогнозных точек, 189 обучений, ошибок/пропусков прогнозов нет. Это подвыборка из 171150 точек R8_v2, не итоговое сравнение всех МО и не confirmatory test.

| Модель | MAE на одних 438 точках |
|---|---:|
| Prophet, линейный тренд, без сезонности | 755.824645 |
| Последнее доступное значение | 892.436073 |
| Сезонный наивный прогноз | 1358.965753 |

Пилот даёт основание для полного причинного сравнения, но не для заявления общего превосходства Prophet. Годовая/недельная/дневная сезонность отключены, n_changepoints=3, uncertainty_samples=0. Обучение строго до origin−2, target=origin+h, настоящие календарные месяцы без сжатия пропусков. Лаг публикации два месяца — допущение, не измеренный vintage.

768 строк paired=False исходного файла исключены до выбора рядов. Совпадение raw actual и paired actual проверяется до обучения: несоответствие останавливает расчёт. На всех 438 точках расхождений нет; независимое соединение с R8_v2 и перерасчёт MAE совпали. Один прогноз отдельно повторён через прямой Prophet.fit — maxdiff=0. Повторное обучение и изменение будущих данных на +1e6: maxdiff=0 в контрольной точке; это контроль одной точки, не полный перебор origins.

Код создан и исправлен через fixar-devops/F7b MiMo Pro. Ремонт дошёл до лимита 30 ходов исполнителя; готовый файл независимо проверен и реально выполнен на Mac. SHA кода и входов в manifest/operator_review. Старые архивы не переписаны.

Воспроизведение в отдельном Python3.13 окружении с Prophet1.4.0, cmdstanpy1.3.0, pandas3.0.6, pyarrow25.0.1, numpy2.5.3:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONHASHSEED=0 python shock-radar/src/r8_prophet_pilot.py --self-check
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONHASHSEED=0 python shock-radar/src/r8_prophet_pilot.py --raw data/raw/sberindex-data-sense-2025/8_consumption.parquet --paired-run shock-radar/runs/R8_v2 --max-series 32 --seed 20260927 --outdir output/R8_prophet_pilot_repeat
```

Свежий каталог обязателен. Следующее: полный Prophet/TSFM на общей маске, подтверждённые news-vintage и 22 флага качества. Новости в этот пилот не входят.
