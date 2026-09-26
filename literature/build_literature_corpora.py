#!/usr/bin/env python3
"""Build and optionally ingest curated scientific literature for both projects.

The corpus stores original bibliographic passports and research notes. It does
not copy paywalled papers. Open-access papers are linked to their canonical
publisher or repository record.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
KB = "http://10.189.141.165:8300"
RETRIEVED = "2026-09-20"
PROJECTS = {
    "economic-atlas": {
        "corpus_id": 75,
        "corpus_name": "research:sberindex-2026:economic-atlas:prn_fbab9aa00cd46169",
        "case_id": "case_66cae4a89ba6473f",
        "label": "Экономический атлас муниципалитетов",
    },
    "shock-radar": {
        "corpus_id": 76,
        "corpus_name": "research:sberindex-2026:shock-radar:prn_fbab9aa00cd46169",
        "case_id": "case_008f37d03cf541e5",
        "label": "Радар потребительских сдвигов",
    },
}


PAPERS = [
    # ── Economic atlas ──────────────────────────────────────────────────
    {
        "project": "economic-atlas",
        "key": "pankova-2026-demand-structure",
        "title": "Структура потребительского спроса и расходы домашних хозяйств в России",
        "authors": "Д. А. Панькова; Д. С. Терновский; П. В. Александрова; И. Б. Воскобойников; Ю. Н. Никулина; А. И. Метляхин",
        "year": 2026,
        "language": "ru",
        "venue": "Вопросы экономики, № 6, 31–57",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.32609/0042-8736-2026-6-31-57",
        "url": "https://doi.org/10.32609/0042-8736-2026-6-31-57",
        "access": "full text linked by HSE; publisher terms apply",
        "ladder": "A3,A9",
        "summary": "Двухуровневая Almost Ideal Demand System для российских домохозяйств разделяет распределение бюджета между укрупнёнными и детальными категориями. Работа даёт российский контекст для интерпретации долей категорий и различения товаров первой необходимости и более эластичных расходов.",
        "use": "Использовать как основу экономической интерпретации профилей категорий и внешней проверки названий кластеров; не переносить оценённые эластичности на муниципалитеты без отдельной проверки.",
        "limitation": "Домохозяйственная модель спроса и муниципальная кластеризация решают разные задачи; статья не подтверждает причинность кластеров СберИндекса.",
    },
    {
        "project": "economic-atlas",
        "key": "petrykina-2017-municipal-clustering",
        "title": "Применение кластерного анализа для типологизации муниципальных образований",
        "authors": "И. Н. Петрыкина; М. И. Солосина; И. Н. Щепина",
        "year": 2017,
        "language": "ru",
        "venue": "Вестник ВГУ. Серия: Экономика и управление, № 4, 154–164",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "",
        "url": "https://cyberleninka.ru/article/n/primenenie-klasternogo-analiza-dlya-tipologizatsii-munitsipalnyh-obrazovaniy",
        "access": "open repository copy",
        "ladder": "A0,A4,A9",
        "summary": "Российская работа показывает типологизацию муниципалитетов Воронежской области по региональной и муниципальной статистике и связывает группы с будущими социально-экономическими профилями территорий.",
        "use": "Сопоставить набор показателей, правила исключения признаков и язык описания кластеров с будущими профилями Атласа.",
        "limitation": "Один регион и ограниченный период; результат нельзя считать доказательством общероссийской устойчивости кластеров.",
    },
    {
        "project": "economic-atlas",
        "key": "sobolevsky-2016-city-spending",
        "title": "Cities through the Prism of People’s Spending Behavior",
        "authors": "Stanislav Sobolevsky; Izabela Sitko; Remi Tachet des Combes; Bartosz Hawelka; Juan Murillo Arias; Carlo Ratti",
        "year": 2016,
        "language": "en",
        "venue": "PLOS ONE 11(2): e0146291",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1371/journal.pone.0146291",
        "url": "https://doi.org/10.1371/journal.pone.0146291",
        "access": "open access, CC BY",
        "ladder": "A3,A4,A8,A9",
        "summary": "На данных карточных транзакций авторы нормируют различия размера и демографии городов, строят масштабно-независимые подписи расходов и кластеризуют города. Устойчивость проверяется при разных определениях городской территории и через социально-экономическую интерпретацию.",
        "use": "Прототипировать scale-adjusted признаки, обязательную проверку зависимости от размера МО и sensitivity по определению территории.",
        "limitation": "Испанские индивидуальные транзакции богаче агрегатов СберИндекса; демографическую коррекцию нельзя воспроизвести без совместимых данных.",
    },
    {
        "project": "economic-atlas",
        "key": "carpio-pinedo-2022-urban-expenditure",
        "title": "Towards a New Urban Geography of Expenditure: Using Bank Card Transactions Data to Analyze Multi-sector Spatiotemporal Distributions",
        "authors": "José Carpio-Pinedo; Gustavo Romanillos; Daniel Aparicio; María Soledad Hernández Martín-Caro; Juan Carlos García-Palomares; Javier Gutiérrez",
        "year": 2022,
        "language": "en",
        "venue": "Cities 131, 103894",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1016/j.cities.2022.103894",
        "url": "https://doi.org/10.1016/j.cities.2022.103894",
        "access": "open access per publisher",
        "ladder": "A3,A4,A6,A10",
        "summary": "Исследование сочетает пространственную автокорреляцию, локальные hot spots, k-means и временную кластеризацию многокатегорийных карточных расходов. Оно показывает, как переходить от объёма к пространственно-временным типам расходов.",
        "use": "Взять сравнительную схему: сырые доли против пространственно контекстных признаков, статические группы против временных траекторий.",
        "limitation": "Внутригородская сетка Мадрида отличается от неоднородных муниципалитетов России; локальные Gi* статистики требуют корректной матрицы соседства.",
    },
    {
        "project": "economic-atlas",
        "key": "aladangady-2019-transactions-statistics",
        "title": "From Transactions Data to Economic Statistics: Constructing Real-time, High-frequency, Geographic Measures of Consumer Spending",
        "authors": "Aditya Aladangady; Shifrah Aron-Dine; Wendy Dunn; Laura Feiveson; Paul Lengermann; Claudia Sahm",
        "year": 2019,
        "language": "en",
        "venue": "NBER Working Paper 26253",
        "publication_type": "working_paper",
        "peer_reviewed": False,
        "doi": "10.3386/w26253",
        "url": "https://www.nber.org/papers/w26253",
        "access": "public abstract and working paper record",
        "ladder": "A2,A3,A9",
        "summary": "Работа строит высокочастотные географические показатели расходов из анонимизированных платёжных транзакций и обсуждает репрезентативность, масштабирование и сопоставление с официальной статистикой.",
        "use": "Сформировать паспорт покрытия, отделить изменение расходов от изменения охвата и калибровать агрегаты по независимым официальным показателям.",
        "limitation": "Методика основана на другой платёжной сети; коэффициенты коррекции и структура выборки не переносятся на СберИндекс.",
    },
    {
        "project": "economic-atlas",
        "key": "agarwal-2017-consumer-mobility",
        "title": "Consumer Mobility and the Local Structure of Consumption Industries",
        "authors": "Sumit Agarwal; J. Bradford Jensen; Ferdinando Monte",
        "year": 2017,
        "language": "en",
        "venue": "NBER Working Paper 23616, revised 2020",
        "publication_type": "working_paper",
        "peer_reviewed": False,
        "doi": "10.3386/w23616",
        "url": "https://www.nber.org/papers/w23616",
        "access": "public abstract and working paper record",
        "ladder": "A3,A5,A9",
        "summary": "Карточные транзакции используются для оценки того, как расходы затухают с расстоянием по отраслям и как потребительская мобильность связана с локальной занятостью и плотностью заведений.",
        "use": "Обосновать отдельные отраслевые радиусы взаимодействия и не смешивать индекс расстояния с потоком МО→МО.",
        "limitation": "Требуются места покупателя и продавца, которых в текущем агрегированном наборе нет; применимость ограничена концептуальной проверкой.",
    },
    {
        "project": "economic-atlas",
        "key": "di-clemente-2018-purchase-sequences",
        "title": "Sequences of Purchases in Credit Card Data Reveal Lifestyles in Urban Populations",
        "authors": "Riccardo Di Clemente; Miguel Luengo-Oroz; Matias Travizano; Sharon Xu; Bapu Vaitla; Marta C. González",
        "year": 2018,
        "language": "en",
        "venue": "Nature Communications 9, 3330",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1038/s41467-018-05690-8",
        "url": "https://doi.org/10.1038/s41467-018-05690-8",
        "access": "open access, full text in PMC",
        "ladder": "A3,A4,A9",
        "summary": "Последовательности категорий покупок представляются как поведенческие сигнатуры, после чего группы проверяются внешними демографическими, расходными и сетевыми характеристиками.",
        "use": "Поддерживает принцип независимой внешней валидации и показывает, что структура категорий может быть информативнее общего объёма.",
        "limitation": "Исходная единица — человек и порядок покупок; месячные агрегаты МО не позволяют повторить алгоритм последовательностей.",
    },
    {
        "project": "economic-atlas",
        "key": "sobolevsky-2015-regional-indices",
        "title": "Predicting Regional Economic Indices Using Big Data of Individual Bank Card Transactions",
        "authors": "Stanislav Sobolevsky; Emanuele Massaro; Iva Bojic; Juan Murillo Arias; Carlo Ratti",
        "year": 2015,
        "language": "en",
        "venue": "arXiv:1506.00036",
        "publication_type": "preprint",
        "peer_reviewed": False,
        "doi": "10.48550/arXiv.1506.00036",
        "url": "https://arxiv.org/abs/1506.00036",
        "access": "open repository record and PDF",
        "ladder": "A3,A9",
        "summary": "Признаки активности бизнеса, жителей и посетителей из транзакций сопоставляются с официальными региональными социально-экономическими индексами через supervised learning.",
        "use": "Сформировать внешний тест того, насколько расходные подписи восстанавливают отложенные зарплаты, занятость или другие официальные признаки.",
        "limitation": "Препринт и иная география; predictive association не является причинным объяснением.",
    },
    {
        "project": "economic-atlas",
        "key": "mucha-2010-multislice-networks",
        "title": "Community Structure in Time-dependent, Multiscale, and Multiplex Networks",
        "authors": "Peter J. Mucha; Thomas Richardson; Kevin Macon; Mason A. Porter; Jukka-Pekka Onnela",
        "year": 2010,
        "language": "en",
        "venue": "Science 328(5980), 876–878",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1126/science.1184819",
        "url": "https://doi.org/10.1126/science.1184819",
        "access": "publisher record; repository preprint available",
        "ladder": "A5,A6,A8",
        "summary": "Multislice framework couples repeated network layers through links from each node to itself across layers, allowing community detection over time and across relation types.",
        "use": "Formalize monthly layers and interlayer coupling, then compare against independent monthly clustering and test sensitivity to coupling strength.",
        "limitation": "Modularity has resolution and identifiability issues; a smooth result is not automatically an economically real transition path.",
    },
    {
        "project": "economic-atlas",
        "key": "eagle-2010-network-diversity",
        "title": "Network Diversity and Economic Development",
        "authors": "Nathan Eagle; Michael Macy; Rob Claxton",
        "year": 2010,
        "language": "en",
        "venue": "Science 328(5981), 1029–1031",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1126/science.1186605",
        "url": "https://doi.org/10.1126/science.1186605",
        "access": "publisher record",
        "ladder": "A5,A9",
        "summary": "Работа связывает разнообразие социальных сетей, построенных по цифровым следам взаимодействий, с экономическим развитием территорий и показывает ценность сетевых характеристик сверх простого объёма активности.",
        "use": "Добавить сетевые diversity/centrality признаки только там, где доступна настоящая сеть, и проверять их на независимой экономической переменной.",
        "limitation": "Связь и развитие коррелируют; работа не даёт оснований трактовать сетевую метрику как причину благосостояния.",
    },
    {
        "project": "economic-atlas",
        "key": "rousseeuw-1987-silhouette",
        "title": "Silhouettes: A Graphical Aid to the Interpretation and Validation of Cluster Analysis",
        "authors": "Peter J. Rousseeuw",
        "year": 1987,
        "language": "en",
        "venue": "Journal of Computational and Applied Mathematics 20, 53–65",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1016/0377-0427(87)90125-7",
        "url": "https://doi.org/10.1016/0377-0427(87)90125-7",
        "access": "publisher record",
        "ladder": "A7,A8",
        "summary": "Вводится silhouette width как наблюдаемый уровень согласованности объекта со своим кластером относительно ближайшей альтернативы и как средство визуальной диагностики кластерной структуры.",
        "use": "Показывать распределение silhouette по МО и кластерам, а не только среднее; использовать низкие значения для списка пограничных территорий.",
        "limitation": "Метрика зависит от расстояния и предпочитает определённые формы кластеров; она не доказывает экономическую содержательность.",
    },
    {
        "project": "economic-atlas",
        "key": "halkidi-2001-clustering-validation",
        "title": "On Clustering Validation Techniques",
        "authors": "Maria Halkidi; Yannis Batistakis; Michalis Vazirgiannis",
        "year": 2001,
        "language": "en",
        "venue": "Journal of Intelligent Information Systems 17, 107–145",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1023/A:1012801612483",
        "url": "https://doi.org/10.1023/A:1012801612483",
        "access": "publisher record",
        "ladder": "A7,A8",
        "summary": "Обзор различает внешние, внутренние и относительные критерии кластерной валидности и подчёркивает необходимость оценивать компактность, разделимость и устойчивость в соответствии с типом данных и алгоритма.",
        "use": "Задать единую маску наблюдений и набор разных по смыслу ICVI до выбора решения; не оптимизировать одну метрику постфактум.",
        "limitation": "Универсального индекса нет; несогласие метрик должно оставаться частью результата, а не устраняться подбором.",
    },
    {
        "project": "economic-atlas",
        "key": "hidalgo-hausmann-2009-economic-complexity",
        "title": "The Building Blocks of Economic Complexity",
        "authors": "César A. Hidalgo; Ricardo Hausmann",
        "year": 2009,
        "language": "en",
        "venue": "Proceedings of the National Academy of Sciences 106(26), 10570–10575",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1073/pnas.0900943106",
        "url": "https://doi.org/10.1073/pnas.0900943106",
        "access": "publisher record and open manuscript",
        "ladder": "A3,A5,A9",
        "summary": "Экономическая сложность выводится из двудольной структуры территорий и видов деятельности через разнообразие и распространённость возможностей, а не из одного объёмного показателя.",
        "use": "Рассмотреть двудольный граф МО×категория и diversity/ubiquity как дополнительное представление, сохранив расходы и занятость отдельными сущностями.",
        "limitation": "Категории потребления не равны экспортным продуктам и не наблюдают производственные capabilities; термин «сложность» требует отдельного обоснования.",
    },

    # ── Shock radar ─────────────────────────────────────────────────────
    {
        "project": "shock-radar",
        "key": "mamedli-shibitov-2021-vintages",
        "title": "Forecasting Russian CPI with Data Vintages and Machine Learning Techniques",
        "authors": "Mariam Mamedli; Denis Shibitov",
        "year": 2021,
        "language": "en",
        "venue": "Bank of Russia Working Paper Series 70",
        "publication_type": "working_paper",
        "peer_reviewed": False,
        "doi": "",
        "url": "https://www.cbr.ru/statichtml/file/120014/wp-apr21_e.pdf",
        "access": "open official PDF",
        "ladder": "R1,R2,R4,R10",
        "summary": "Псевдореальный эксперимент Банка России учитывает винтажи, даты выпуска и задержки показателей. Игнорирование доступности данных и использование пересмотренных/сглаженных рядов заметно занижает оценку ошибки.",
        "use": "Сделать first_seen_at и release lag обязательными, хранить splits и оценивать консервативные задержки там, где исторические винтажи СберИндекса недоступны.",
        "limitation": "Цель — агрегированный ИПЦ, а не короткая муниципальная панель; численные эффекты не переносятся напрямую.",
    },
    {
        "project": "shock-radar",
        "key": "grebenkina-2025-high-frequency",
        "title": "Прогнозирование инфляции с использованием высокочастотных данных в моделях временных рядов",
        "authors": "А. М. Гребенкина; Е. В. Синельникова-Мурылева",
        "year": 2025,
        "language": "ru",
        "venue": "Экономическая политика 20(2), 34–55",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "",
        "url": "https://library.cbr.ru/catalog/lib/article/1014123/",
        "access": "official bibliographic record and abstract",
        "ladder": "R3,R4,R8",
        "summary": "Статья сравнивает краткосрочное прогнозирование инфляции с высокочастотным ценовым регрессором в VAR, MFVAR и MIDAS с одномерными бенчмарками.",
        "use": "Проверить, добавляют ли более частые внешние признаки пользу месячным расходам, только в парном backtest против тех же моделей без признака.",
        "limitation": "Высокая частота сама по себе не гарантирует прирост; результат относится к инфляции и конкретным регрессорам.",
    },
    {
        "project": "shock-radar",
        "key": "taylor-letham-2018-prophet",
        "title": "Forecasting at Scale",
        "authors": "Sean J. Taylor; Benjamin Letham",
        "year": 2018,
        "language": "en",
        "venue": "The American Statistician 72(1), 37–45",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1080/00031305.2017.1380080",
        "url": "https://doi.org/10.1080/00031305.2017.1380080",
        "access": "publisher record",
        "ladder": "R3,R4,R8",
        "summary": "Prophet decomposes trend, seasonality and known events/holidays in a configurable forecasting workflow designed for many business series and analyst review.",
        "use": "Use as an organizer-required/interpretable baseline with fixed holidays and validation-only tuning, never as the sole benchmark.",
        "limitation": "Automation and interpretability do not guarantee accuracy on 24 monthly observations; short series sharply limit component estimation.",
    },
    {
        "project": "shock-radar",
        "key": "montero-manso-2021-global",
        "title": "Principles and Algorithms for Forecasting Groups of Time Series: Locality and Globality",
        "authors": "Pablo Montero-Manso; Rob J. Hyndman",
        "year": 2021,
        "language": "en",
        "venue": "International Journal of Forecasting 37(4), 1632–1653",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1016/j.ijforecast.2021.03.004",
        "url": "https://doi.org/10.1016/j.ijforecast.2021.03.004",
        "access": "publisher record and open preprint",
        "ladder": "R3,R4,R8",
        "summary": "Работа формализует локальные и глобальные модели для групп рядов и показывает, почему единая модель может обобщать лучше при большом числе коротких рядов и оставаться достаточно выразительной.",
        "use": "Обосновывает глобальную модель по МО×категориям и сравнение с отдельными local baselines на одинаковых origins.",
        "limitation": "Глобальная модель всё равно нуждается в признаках идентичности, контроле масштаба и проверке обобщения на отложенных МО.",
    },
    {
        "project": "shock-radar",
        "key": "makridakis-2022-m5",
        "title": "M5 Accuracy Competition: Results, Findings, and Conclusions",
        "authors": "Spyros Makridakis; Evangelos Spiliotis; Vassilios Assimakopoulos",
        "year": 2022,
        "language": "en",
        "venue": "International Journal of Forecasting 38(4), 1346–1364",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1016/j.ijforecast.2021.11.013",
        "url": "https://doi.org/10.1016/j.ijforecast.2021.11.013",
        "access": "open access per publisher",
        "ladder": "R3,R4,R8",
        "summary": "M5 сравнивает методы на 42 840 иерархических рядах розничных продаж. Сильные решения используют глобальные ML-модели, экзогенные признаки и оценку на нескольких уровнях агрегации против простых статистических бенчмарков.",
        "use": "Взять LightGBM/CatBoost-like global baseline, scaled error как дополнительную метрику и отчётность по уровням категория×МО.",
        "limitation": "Дневные длинные Walmart-ряды намного богаче коротких месячных рядов конкурса; сложность победителей M5 нельзя переносить без абляции.",
    },
    {
        "project": "shock-radar",
        "key": "lim-2021-tft",
        "title": "Temporal Fusion Transformers for Interpretable Multi-horizon Time Series Forecasting",
        "authors": "Bryan Lim; Sercan Ö. Arık; Nicolas Loeff; Tomas Pfister",
        "year": 2021,
        "language": "en",
        "venue": "International Journal of Forecasting 37(4), 1748–1764",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1016/j.ijforecast.2021.03.012",
        "url": "https://doi.org/10.1016/j.ijforecast.2021.03.012",
        "access": "open access per publisher",
        "ladder": "R3,R4,R8",
        "summary": "TFT объединяет статические признаки, известные будущие входы и наблюдаемые ковариаты для многогоризонтного прогноза и предоставляет variable selection и интерпретируемое внимание.",
        "use": "Рассматривать как расширение после сильного global boosting baseline, если реальная длина истории и число рядов достаточны.",
        "limitation": "Высокая модельная ёмкость создаёт риск переобучения и нестабильной интерпретации на короткой истории.",
    },
    {
        "project": "shock-radar",
        "key": "ansari-2024-chronos",
        "title": "Chronos: Learning the Language of Time Series",
        "authors": "Abdul Fatir Ansari et al.",
        "year": 2024,
        "language": "en",
        "venue": "arXiv:2403.07815",
        "publication_type": "preprint",
        "peer_reviewed": False,
        "doi": "10.48550/arXiv.2403.07815",
        "url": "https://arxiv.org/abs/2403.07815",
        "access": "open repository record and PDF",
        "ladder": "R3,R4,R8",
        "summary": "Chronos квантует масштабированные значения рядов и обучает семейство T5 как вероятностные модели; zero-shot качество оценивается на множестве доменов и новых наборов.",
        "use": "Провести зафиксированный zero-shot benchmark на представительной панели с теми же origins и маской, что у классических моделей.",
        "limitation": "Неизвестное пересечение предобучающих данных и короткий контекст затрудняют интерпретацию преимущества; препринт не заменяет собственный backtest.",
    },
    {
        "project": "shock-radar",
        "key": "das-2024-timesfm",
        "title": "A Decoder-only Foundation Model for Time-series Forecasting",
        "authors": "Abhimanyu Das; Weihao Kong; Rajat Sen; Yichen Zhou",
        "year": 2024,
        "language": "en",
        "venue": "Proceedings of ICML 2024, PMLR 235",
        "publication_type": "conference_paper",
        "peer_reviewed": True,
        "doi": "10.48550/arXiv.2310.10688",
        "url": "https://proceedings.mlr.press/v235/das24c.html",
        "access": "open proceedings paper",
        "ladder": "R3,R4,R8",
        "summary": "TimesFM — decoder-only модель с patching, предобученная на большом корпусе временных рядов и оценённая zero-shot на разных частотах и горизонтах.",
        "use": "Ограниченный дополнительный benchmark после Chronos и базовых моделей, с фиксацией версии весов, ресурсов и длины контекста.",
        "limitation": "Zero-shot результат может зависеть от состава pretraining corpus; модель не должна получать будущие ковариаты, которых архитектура/версия не поддерживает.",
    },
    {
        "project": "shock-radar",
        "key": "killick-2012-pelt",
        "title": "Optimal Detection of Changepoints With a Linear Computational Cost",
        "authors": "Rebecca Killick; Paul Fearnhead; Idris A. Eckley",
        "year": 2012,
        "language": "en",
        "venue": "Journal of the American Statistical Association 107(500), 1590–1598",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1080/01621459.2012.737745",
        "url": "https://doi.org/10.1080/01621459.2012.737745",
        "access": "publisher record and open preprint",
        "ladder": "R5,R6,R8",
        "summary": "PELT даёт точную оптимизацию penalized offline segmentation при условиях pruning и часто близкую к линейной вычислительную стоимость.",
        "use": "Использовать как ретроспективный диагностический ориентир и источник кандидатов событий, отдельно от online warning.",
        "limitation": "Алгоритм видит весь ряд; его точка изменения не является ранним предупреждением и не должна оцениваться как такое.",
    },
    {
        "project": "shock-radar",
        "key": "adams-mackay-2007-bocpd",
        "title": "Bayesian Online Changepoint Detection",
        "authors": "Ryan Prescott Adams; David J. C. MacKay",
        "year": 2007,
        "language": "en",
        "venue": "arXiv:0710.3742",
        "publication_type": "preprint",
        "peer_reviewed": False,
        "doi": "10.48550/arXiv.0710.3742",
        "url": "https://arxiv.org/abs/0710.3742",
        "access": "open repository record and PDF",
        "ladder": "R5,R6,R8",
        "summary": "BOCPD рекурсивно оценивает posterior распределение run length — времени с последней точки изменения — и обновляется при поступлении каждого нового наблюдения.",
        "use": "Реализовать один из online detectors и калибровать hazard/likelihood только на train/validation; выводить вероятность, задержку и ложные тревоги.",
        "limitation": "Результат чувствителен к likelihood и hazard; неверная стационарная модель создаёт ложные срабатывания.",
    },
    {
        "project": "shock-radar",
        "key": "page-1954-cusum",
        "title": "Continuous Inspection Schemes",
        "authors": "E. S. Page",
        "year": 1954,
        "language": "en",
        "venue": "Biometrika 41(1–2), 100–115",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1093/biomet/41.1-2.100",
        "url": "https://doi.org/10.1093/biomet/41.1-2.100",
        "access": "publisher record",
        "ladder": "R5,R6,R8",
        "summary": "Классическая работа вводит последовательные cumulative-sum схемы для быстрого обнаружения устойчивого сдвига при контроле поведения до изменения.",
        "use": "CUSUM/Page-Hinkley — прозрачный baseline online detection; порог выбирать по допустимой частоте ложных тревог на validation.",
        "limitation": "Базовая схема предполагает определённый тип сдвига и стабильное распределение; сезонность и гетероскедастичность требуют работы с остатками.",
    },
    {
        "project": "shock-radar",
        "key": "shapiro-2022-news-sentiment",
        "title": "Measuring News Sentiment",
        "authors": "Adam Hale Shapiro; Moritz Sudhof; Daniel J. Wilson",
        "year": 2022,
        "language": "en",
        "venue": "Journal of Econometrics 228(2), 221–243",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1016/j.jeconom.2020.07.053",
        "url": "https://doi.org/10.1016/j.jeconom.2020.07.053",
        "access": "publisher record and author/preprint copies",
        "ladder": "R2,R3,R7,R8",
        "summary": "Авторы строят временной индекс экономического sentiment из газетных текстов и исследуют его связь с экономической активностью, отдельно рассматривая выбор корпуса и измерение тональности.",
        "use": "Создать простые as-of признаки частоты и тональности новостей, затем оценить добавочную ценность только против прогноза без новостей.",
        "limitation": "Национальный газетный sentiment не равен муниципальному событию; публикационная дата и география должны быть проверены отдельно.",
    },
    {
        "project": "shock-radar",
        "key": "leetaru-schrodt-2013-gdelt",
        "title": "GDELT: Global Data on Events, Location and Tone, 1979–2012",
        "authors": "Kalev Leetaru; Philip A. Schrodt",
        "year": 2013,
        "language": "en",
        "venue": "ISA Annual Convention, San Francisco",
        "publication_type": "conference_paper",
        "peer_reviewed": False,
        "doi": "",
        "url": "https://blog.gdeltproject.org/gdelt-global-data-on-events-location-and-tone-1979-2012/",
        "access": "open project paper and data documentation",
        "ladder": "R2,R3,R7",
        "summary": "Методическая публикация описывает глобальное автоматизированное кодирование событий, географии и tone из новостного потока, положившее основу GDELT.",
        "use": "Использовать как источник кандидатов событий и агрегированных признаков, сохраняя первичную новостную ссылку, дату первого появления и качество геокодирования.",
        "limitation": "Автоматическое кодирование содержит дубликаты и ошибки; GDELT-событие не является подтверждённым реальным шоком без внешней проверки.",
    },
    {
        "project": "shock-radar",
        "key": "barber-2023-conformal",
        "title": "Conformal Prediction Beyond Exchangeability",
        "authors": "Rina Foygel Barber; Emmanuel J. Candès; Aaditya Ramdas; Ryan J. Tibshirani",
        "year": 2023,
        "language": "en",
        "venue": "The Annals of Statistics 51(2), 816–845",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1214/23-AOS2276",
        "url": "https://doi.org/10.1214/23-AOS2276",
        "access": "open journal PDF",
        "ladder": "R4,R6,R8",
        "summary": "Weighted conformal methods reduce coverage loss under drift and nonsymmetric fitting while recovering standard guarantees under exchangeability.",
        "use": "После point-forecast baseline оценить интервалы с временными весами и публиковать фактическое покрытие по rolling origins.",
        "limitation": "Гарантии ослабевают при зависимости и drift; заявлять номинальное покрытие без эмпирической проверки нельзя.",
    },
    {
        "project": "shock-radar",
        "key": "hyndman-2011-hierarchical",
        "title": "Optimal Combination Forecasts for Hierarchical Time Series",
        "authors": "Rob J. Hyndman; Roman A. Ahmed; George Athanasopoulos; Han Lin Shang",
        "year": 2011,
        "language": "en",
        "venue": "Computational Statistics & Data Analysis 55(9), 2579–2589",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1016/j.csda.2011.03.006",
        "url": "https://doi.org/10.1016/j.csda.2011.03.006",
        "access": "publisher record and author PDF",
        "ladder": "R3,R4,R8",
        "summary": "Forecast reconciliation combines forecasts at multiple aggregation levels so that итоговые значения согласуются по иерархии и при заданных условиях имеют меньшую дисперсию среди линейных несмещённых комбинаций.",
        "use": "Если прогнозируются категории и итоги, сравнить независимые прогнозы с reconciliation и проверять точность на каждом уровне.",
        "limitation": "Когерентность не гарантирует меньшую ошибку конкретного нижнего ряда; структура агрегации должна быть точной.",
    },
    {
        "project": "shock-radar",
        "key": "bergmeir-2018-cross-validation",
        "title": "A Note on the Validity of Cross-validation for Evaluating Autoregressive Time Series Prediction",
        "authors": "Christoph Bergmeir; Rob J. Hyndman; Bonsoo Koo",
        "year": 2018,
        "language": "en",
        "venue": "Computational Statistics & Data Analysis 120, 70–83",
        "publication_type": "journal_article",
        "peer_reviewed": True,
        "doi": "10.1016/j.csda.2017.11.003",
        "url": "https://doi.org/10.1016/j.csda.2017.11.003",
        "access": "publisher record and author PDF",
        "ladder": "R2,R4,R8",
        "summary": "Работа уточняет условия, при которых k-fold CV может быть корректна для чисто авторегрессионных моделей с некоррелированными ошибками, и сравнивает её с out-of-sample процедурами.",
        "use": "Для проекта сохранить более строгий expanding-window backtest; статью использовать для объяснения, почему обычное random CV без проверки условий недопустимо.",
        "limitation": "Результат не разрешает random CV для произвольных нестационарных рядов и экзогенных признаков.",
    },
    {
        "project": "shock-radar",
        "key": "aladangady-2019-real-time-spending",
        "title": "From Transactions Data to Economic Statistics: Constructing Real-time, High-frequency, Geographic Measures of Consumer Spending",
        "authors": "Aditya Aladangady; Shifrah Aron-Dine; Wendy Dunn; Laura Feiveson; Paul Lengermann; Claudia Sahm",
        "year": 2019,
        "language": "en",
        "venue": "NBER Working Paper 26253",
        "publication_type": "working_paper",
        "peer_reviewed": False,
        "doi": "10.3386/w26253",
        "url": "https://www.nber.org/papers/w26253",
        "access": "public abstract and working paper record",
        "ladder": "R1,R2,R3,R8",
        "summary": "Работа показывает построение оперативных географических индикаторов расходов из транзакций, аудит охвата и применение к локальным краткосрочным шокам.",
        "use": "Разделить signal, coverage и revision; предупреждение строить по нормированным остаткам, а не по необработанному падению объёма.",
        "limitation": "Платёжная выборка и калибровка иные; метод не устраняет отсутствие исторических vintage СберИндекса.",
    },
]


def request(method: str, url: str, body: dict | None = None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    headers = {"content-type": "application/json"} if body is not None else {}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=headers, method=method),
        timeout=240,
    ) as response:
        return json.loads(response.read())


def paper_text(paper: dict) -> str:
    doi_line = f"https://doi.org/{paper['doi']}" if paper["doi"] else "не присвоен/не найден"
    review = "рецензируемая публикация" if paper["peer_reviewed"] else "препринт, working paper или конференционный материал"
    return f"""# {paper['title']}

## Библиографический паспорт

- Авторы: {paper['authors']}
- Год: {paper['year']}
- Язык: {paper['language']}
- Издание: {paper['venue']}
- Тип: {paper['publication_type']}; {review}
- DOI: {doi_line}
- Каноническая страница: {paper['url']}
- Доступ: {paper['access']}
- Проверено: {RETRIEVED}, по странице издателя, официального репозитория или институционального каталога.

## Что исследуется

{paper['summary']}

## Как использовать в проекте

{paper['use']}

Связанные ворота исследовательской лестницы: {paper['ladder']}.

## Ограничение переноса

{paper['limitation']}

## Правовой режим корпуса

В kb-forge помещён этот оригинальный библиографический паспорт и аналитический конспект. Полный текст не копировался, если источник не обозначен как открытый; ссылка ведёт к канонической записи или открытому репозиторию.
"""


def write_outputs() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {"created_on": RETRIEVED, "papers": PAPERS}
    (ROOT / "papers.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    for project, spec in PROJECTS.items():
        project_papers = [paper for paper in PAPERS if paper["project"] == project]
        lines = [
            f"# Научная литература — {spec['label']}",
            "",
            f"Кураторская выборка на {RETRIEVED}: {len(project_papers)} работ. Каждая работа индексируется в kb-forge отдельным документом.",
            "",
            "## Приоритет чтения",
            "",
        ]
        for index, paper in enumerate(project_papers, 1):
            doi = f" DOI `{paper['doi']}`." if paper["doi"] else ""
            lines.extend(
                [
                    f"{index}. [{paper['title']}]({paper['url']}) — {paper['authors']} ({paper['year']}).{doi}",
                    f"   Ворота: `{paper['ladder']}`. {paper['use']}",
                    "",
                ]
            )
        lines.extend(
            [
                "## Правила использования",
                "",
                "- Первичный источник и DOI важнее пересказа; перед цитированием проверить каноническую страницу.",
                "- Препринт/working paper помечен отдельно и не приравнивается к рецензируемой статье.",
                "- Чужие результаты задают метод и отрицательные контроли, но не доказывают результат на данных СберИндекса.",
                "- Закрытый полный текст не копируется; в корпусе хранится оригинальный конспект и постоянная ссылка.",
            ]
        )
        (ROOT / f"{project}-literature-review.md").write_text("\n".join(lines) + "\n")


def ingest() -> dict:
    corpora = request("GET", f"{KB}/api/corpora")
    receipts = []
    for paper in PAPERS:
        spec = PROJECTS[paper["project"]]
        corpus = next((item for item in corpora if int(item.get("id", -1)) == spec["corpus_id"]), None)
        if not corpus or corpus.get("name") != spec["corpus_name"]:
            raise RuntimeError(f"corpus identity mismatch: {spec['corpus_id']}")
        meta = {
            "project": paper["project"],
            "case_id": spec["case_id"],
            "kind": "scientific_literature",
            "stage": "research_setup",
            "evidence_level": "source",
            "verified_on": RETRIEVED,
            "retrieved_at": RETRIEVED,
            "source_url": paper["url"],
            "authors": paper["authors"],
            "published_at": str(paper["year"]),
            "license": paper["access"],
            "doi": paper["doi"],
            "language": paper["language"],
            "peer_reviewed": paper["peer_reviewed"],
            "research_ladder": paper["ladder"],
        }
        result = request(
            "POST",
            f"{KB}/api/corpora/{spec['corpus_id']}/documents/integrate",
            {
                "title": f"Научная работа — {paper['title']}",
                "url": paper["url"],
                "text": paper_text(paper),
                "meta": meta,
            },
        )
        receipt = {
            "project": paper["project"],
            "key": paper["key"],
            "corpus_id": spec["corpus_id"],
            "title": paper["title"],
            "result": result,
        }
        receipts.append(receipt)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)

    for project, spec in PROJECTS.items():
        review_path = ROOT / f"{project}-literature-review.md"
        result = request(
            "POST",
            f"{KB}/api/corpora/{spec['corpus_id']}/documents/integrate",
            {
                "title": f"Научная литература — обзор для проекта {spec['label']}",
                "url": "https://sber.ru/sberindex/konkurs_sberindex",
                "text": review_path.read_text(),
                "meta": {
                    "project": project,
                    "case_id": spec["case_id"],
                    "kind": "literature_review",
                    "stage": "research_setup",
                    "evidence_level": "source",
                    "verified_on": RETRIEVED,
                    "retrieved_at": RETRIEVED,
                },
            },
        )
        receipts.append(
            {
                "project": project,
                "key": "literature-review",
                "corpus_id": spec["corpus_id"],
                "title": f"Научная литература — обзор для проекта {spec['label']}",
                "result": result,
            }
        )
    output = {"ingested_on": RETRIEVED, "documents": receipts}
    (ROOT / "ingest-receipts.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()
    write_outputs()
    if args.ingest:
        output = ingest()
        print(
            json.dumps(
                {
                    "ingested": len(output["documents"]),
                    "atlas": sum(p["project"] == "economic-atlas" for p in PAPERS),
                    "radar": sum(p["project"] == "shock-radar" for p in PAPERS),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
