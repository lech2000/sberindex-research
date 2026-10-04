-- total_observations
SELECT COUNT(*) FROM observation;

-- supplement_observations
SELECT COUNT(*) FROM budget_supplement_cell;

-- currency_cells
SELECT COUNT(*) FROM budget_supplement_cell WHERE value_kopecks IS NOT NULL;

-- noncurrency_cells
SELECT COUNT(*) FROM budget_supplement_cell WHERE value_kopecks IS NULL;

-- measure_period_counts
SELECT measure,period_kind,COUNT(*) FROM budget_supplement_cell GROUP BY 1,2 ORDER BY 1,2;

-- new_releases
SELECT COUNT(*) FROM dataset_release WHERE id LIKE 'budget-supplement-%';

-- orphans
SELECT COUNT(*) FROM budget_supplement_cell f LEFT JOIN observation o ON o.id=f.observation_id LEFT JOIN municipality m ON m.tid=o.tid LEFT JOIN dataset_release s ON s.id=o.release_id WHERE o.id IS NULL OR m.tid IS NULL OR s.id IS NULL;

-- integer_currency_mismatch
SELECT COUNT(*) FROM budget_supplement_cell f JOIN observation o ON o.id=f.observation_id WHERE f.value_kopecks IS NOT NULL AND (typeof(f.value_kopecks)<>'integer' OR f.value_kopecks<>o.value);

-- duplicate_natural_keys
SELECT COUNT(*) FROM (SELECT release_id,tid,indicator_id,period,dimensions,COUNT(*) n FROM observation GROUP BY 1,2,3,4,5 HAVING n>1);

-- supplement_asof_2024
SELECT COUNT(*) FROM budget_supplement_cell f JOIN asof_2024 o ON o.id=f.observation_id;

-- invented_availability_or_synthetic
SELECT COUNT(*) FROM budget_supplement_cell f JOIN observation o ON o.id=f.observation_id WHERE o.available_at IS NOT NULL OR o.provenance_class NOT IN ('observed','source_estimate');

-- primary_fiscal_cells
SELECT COUNT(*) FROM fiscal_cell;

-- primary_pilot_coverage
SELECT status,COUNT(*) FROM fiscal_pilot_coverage GROUP BY status ORDER BY status;

-- foreign_key_check
PRAGMA foreign_key_check;
