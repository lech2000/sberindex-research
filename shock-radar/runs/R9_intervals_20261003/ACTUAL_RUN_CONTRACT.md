# Фактически исполненный R9: контракты окна и общей маски

Проверено 03.10.2026 по r9_prophet_batch.py, r9_prophet_feasibility.py, audit внутренний аудит и SHA predictions. Это уточнение фактического исследовательского run, не изменение задним числом preregistration.

* target: июль–декабрь 2024. h: 1,3,6,12 календарных месяцев. origin=target−h.
* baseline: actual, last в origin и seasonal в target−12 должны существовать; history до origin содержит минимум 2 наблюдения. Никакого сжатия месяцев/заполнения пропусков.
* Prophet: только непустые значения period≤origin, min_train=6; линейный тренд, 3 changepoints, дневная/недельная/годовая сезонность и uncertainty sampling отключены. Этот exploratory run использует train-through-origin без assumed release lag.
* Общая маска: 294792 baseline-строки; 294570 прогнозов; исключены 222 insufficient_train (6 при h3, 216 при h12). Других fit failures нет. Сравнение всех методов только на 294570 общих строках, отдельно по горизонтам.
* Raw SHA 9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61; predictions SHA b9726b7971c55e5c9f32cdfe439694ffc96f66d7b0c180725a7ad2dff68afe44.

Старый forecast_contract.yaml с min_train12/assumed lag2 описывает другую спецификацию. Он не может подменять фактические параметры этого запуска. Требование независимого нового holdout и проверенного historical available_at остаётся отдельной не выполненной задачей. Техническое отсутствие поздних периодов в обучении не доказывает реальную историческую доступность входов.

R8 уже завершён INCONCLUSIVE; R9 основной source OPEN до сводки критериев. Данный child-расчёт можно закрыть как completed retrospective analysis, не как научный PASS.
