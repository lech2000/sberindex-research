# A6_v2: идентичности групп — 26.09.2026

research:a6_v2_20260926

Код создан и исправлен через fixar-devops/F7b; проверено26.09.2026 на Mac, Python3.14.4, полный прогон замороженной panel_v1 и численные selfchecks. Статус PARTIAL_NOT_GATE_PASS, source act_c475e17b2a584b9a открыт. Ранние архивы A5/A6 сохранены.

1896МО ×24месяца ×6категорий →45504назначения. Доли пяти категорий относительно «Все категории»; без zero-impute и принудительного sum=1. Scaler и пороги обучены только на2023; 2023labels ретроспективны, проверки причинности относятся к2024.

Независимый KMeans каждого месяца, сеткаK2..8, silhouette на воспроизводимой подвыборке400. Выбор: K2 во всех24месяцах, это результат сетки, а не принудительныйfixedK. Геометрия: изотропныеGaussianregions, RMSрадиус и variance=r²/d. Bhattacharyyaoverlap, marginстраж и one-to-one разрешение конфликтов; dormant3пропуска, retirementпосле4.

Калибровка2023: self4800/cross4800, overlapT0.27716, margin0.71870, resemblancefloor0.17395. Bootstrapсамоперекрытие отделилось по выбранным квантилям отмежкластерного; это не доказательство качества переносимых во времени порогов.

Результат: initial2, continuing36, re-emergence3, ambiguous7, dormant7, births0, disappearances0, split0, merge0. Все6точек чувствительности containment/kappa дали0split/merge. Семь неоднозначностей остаются неразрешёнными; отсутствие рождений не означает доказанного отсутствия экономических изменений.

M3 исправлен: текущие дочерние точки должны попадать в ПРЕЖНЮЮ область родителя, а прежние родительские точки — в текущую область при merge. Дополнительный guard проверяет реальный состав участников между месяцами. Контроль с теми же участниками, но неверной геометрией, отвергается.

Все selfchecks прошли: birth1, death1, return1, split1, merge1; proximityfalsepositives0, wronggeometryfalsepositives0; ambiguoustwins не рождают подтверждённую идентичность. Эти trackerunitcontrols используют фиксированные синтетическиеT.55/M.3/Tc.25; они НЕ подтверждают качество порогов, обученных на экономических данных. Prefixappend/edit проверки сохранили360прошлых строк. Полный журнал self-check.log и SHA/версии manifest.json.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python economic-atlas/src/a6_identities.py --self-check
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python economic-atlas/src/a6_identities.py --panel economic-atlas/data/panel_v1.parquet --outdir output/a6-v2-reproduced --seed 20260926
```

Далее: проверить7неоднозначных сопоставлений, сопоставить профили2групп с прежнимK5, выполнить абляции масштаба/динамики/географии и5seedустойчивость. Экономические биографии и внешняя интерпретация пока не подтверждены. Ни case06, ни gateA6 этим архивом не закрываются.


Пять seed уже выполнены: см. [robustness](robustness/README.md). Средний ARI0.99854–0.99972; неоднозначны7сопоставлений групп, охватывающих4438строкМО×месяц, а не7МО. Это проверка численнойустойчивости, не экономическойистины.
