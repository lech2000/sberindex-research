# Научная литература — Радар потребительских сдвигов

Кураторская выборка на 2026-09-20: 17 работ. Каждая работа индексируется в kb-forge отдельным документом.

## Приоритет чтения

1. [Forecasting Russian CPI with Data Vintages and Machine Learning Techniques](https://www.cbr.ru/statichtml/file/120014/wp-apr21_e.pdf) — Mariam Mamedli; Denis Shibitov (2021).
   Ворота: `R1,R2,R4,R10`. Сделать first_seen_at и release lag обязательными, хранить splits и оценивать консервативные задержки там, где исторические винтажи СберИндекса недоступны.

2. [Прогнозирование инфляции с использованием высокочастотных данных в моделях временных рядов](https://library.cbr.ru/catalog/lib/article/1014123/) — А. М. Гребенкина; Е. В. Синельникова-Мурылева (2025).
   Ворота: `R3,R4,R8`. Проверить, добавляют ли более частые внешние признаки пользу месячным расходам, только в парном backtest против тех же моделей без признака.

3. [Forecasting at Scale](https://doi.org/10.1080/00031305.2017.1380080) — Sean J. Taylor; Benjamin Letham (2018). DOI `10.1080/00031305.2017.1380080`.
   Ворота: `R3,R4,R8`. Use as an organizer-required/interpretable baseline with fixed holidays and validation-only tuning, never as the sole benchmark.

4. [Principles and Algorithms for Forecasting Groups of Time Series: Locality and Globality](https://doi.org/10.1016/j.ijforecast.2021.03.004) — Pablo Montero-Manso; Rob J. Hyndman (2021). DOI `10.1016/j.ijforecast.2021.03.004`.
   Ворота: `R3,R4,R8`. Обосновывает глобальную модель по МО×категориям и сравнение с отдельными local baselines на одинаковых origins.

5. [M5 Accuracy Competition: Results, Findings, and Conclusions](https://doi.org/10.1016/j.ijforecast.2021.11.013) — Spyros Makridakis; Evangelos Spiliotis; Vassilios Assimakopoulos (2022). DOI `10.1016/j.ijforecast.2021.11.013`.
   Ворота: `R3,R4,R8`. Взять LightGBM/CatBoost-like global baseline, scaled error как дополнительную метрику и отчётность по уровням категория×МО.

6. [Temporal Fusion Transformers for Interpretable Multi-horizon Time Series Forecasting](https://doi.org/10.1016/j.ijforecast.2021.03.012) — Bryan Lim; Sercan Ö. Arık; Nicolas Loeff; Tomas Pfister (2021). DOI `10.1016/j.ijforecast.2021.03.012`.
   Ворота: `R3,R4,R8`. Рассматривать как расширение после сильного global boosting baseline, если реальная длина истории и число рядов достаточны.

7. [Chronos: Learning the Language of Time Series](https://arxiv.org/abs/2403.07815) — Abdul Fatir Ansari et al. (2024). DOI `10.48550/arXiv.2403.07815`.
   Ворота: `R3,R4,R8`. Провести зафиксированный zero-shot benchmark на представительной панели с теми же origins и маской, что у классических моделей.

8. [A Decoder-only Foundation Model for Time-series Forecasting](https://proceedings.mlr.press/v235/das24c.html) — Abhimanyu Das; Weihao Kong; Rajat Sen; Yichen Zhou (2024). DOI `10.48550/arXiv.2310.10688`.
   Ворота: `R3,R4,R8`. Ограниченный дополнительный benchmark после Chronos и базовых моделей, с фиксацией версии весов, ресурсов и длины контекста.

9. [Optimal Detection of Changepoints With a Linear Computational Cost](https://doi.org/10.1080/01621459.2012.737745) — Rebecca Killick; Paul Fearnhead; Idris A. Eckley (2012). DOI `10.1080/01621459.2012.737745`.
   Ворота: `R5,R6,R8`. Использовать как ретроспективный диагностический ориентир и источник кандидатов событий, отдельно от online warning.

10. [Bayesian Online Changepoint Detection](https://arxiv.org/abs/0710.3742) — Ryan Prescott Adams; David J. C. MacKay (2007). DOI `10.48550/arXiv.0710.3742`.
   Ворота: `R5,R6,R8`. Реализовать один из online detectors и калибровать hazard/likelihood только на train/validation; выводить вероятность, задержку и ложные тревоги.

11. [Continuous Inspection Schemes](https://doi.org/10.1093/biomet/41.1-2.100) — E. S. Page (1954). DOI `10.1093/biomet/41.1-2.100`.
   Ворота: `R5,R6,R8`. CUSUM/Page-Hinkley — прозрачный baseline online detection; порог выбирать по допустимой частоте ложных тревог на validation.

12. [Measuring News Sentiment](https://doi.org/10.1016/j.jeconom.2020.07.053) — Adam Hale Shapiro; Moritz Sudhof; Daniel J. Wilson (2022). DOI `10.1016/j.jeconom.2020.07.053`.
   Ворота: `R2,R3,R7,R8`. Создать простые as-of признаки частоты и тональности новостей, затем оценить добавочную ценность только против прогноза без новостей.

13. [GDELT: Global Data on Events, Location and Tone, 1979–2012](https://blog.gdeltproject.org/gdelt-global-data-on-events-location-and-tone-1979-2012/) — Kalev Leetaru; Philip A. Schrodt (2013).
   Ворота: `R2,R3,R7`. Использовать как источник кандидатов событий и агрегированных признаков, сохраняя первичную новостную ссылку, дату первого появления и качество геокодирования.

14. [Conformal Prediction Beyond Exchangeability](https://doi.org/10.1214/23-AOS2276) — Rina Foygel Barber; Emmanuel J. Candès; Aaditya Ramdas; Ryan J. Tibshirani (2023). DOI `10.1214/23-AOS2276`.
   Ворота: `R4,R6,R8`. После point-forecast baseline оценить интервалы с временными весами и публиковать фактическое покрытие по rolling origins.

15. [Optimal Combination Forecasts for Hierarchical Time Series](https://doi.org/10.1016/j.csda.2011.03.006) — Rob J. Hyndman; Roman A. Ahmed; George Athanasopoulos; Han Lin Shang (2011). DOI `10.1016/j.csda.2011.03.006`.
   Ворота: `R3,R4,R8`. Если прогнозируются категории и итоги, сравнить независимые прогнозы с reconciliation и проверять точность на каждом уровне.

16. [A Note on the Validity of Cross-validation for Evaluating Autoregressive Time Series Prediction](https://doi.org/10.1016/j.csda.2017.11.003) — Christoph Bergmeir; Rob J. Hyndman; Bonsoo Koo (2018). DOI `10.1016/j.csda.2017.11.003`.
   Ворота: `R2,R4,R8`. Для проекта сохранить более строгий expanding-window backtest; статью использовать для объяснения, почему обычное random CV без проверки условий недопустимо.

17. [From Transactions Data to Economic Statistics: Constructing Real-time, High-frequency, Geographic Measures of Consumer Spending](https://www.nber.org/papers/w26253) — Aditya Aladangady; Shifrah Aron-Dine; Wendy Dunn; Laura Feiveson; Paul Lengermann; Claudia Sahm (2019). DOI `10.3386/w26253`.
   Ворота: `R1,R2,R3,R8`. Разделить signal, coverage и revision; предупреждение строить по нормированным остаткам, а не по необработанному падению объёма.

## Правила использования

- Первичный источник и DOI важнее пересказа; перед цитированием проверить каноническую страницу.
- Препринт/working paper помечен отдельно и не приравнивается к рецензируемой статье.
- Чужие результаты задают метод и отрицательные контроли, но не доказывают результат на данных СберИндекса.
- Закрытый полный текст не копируется; в корпусе хранится оригинальный конспект и постоянная ссылка.
