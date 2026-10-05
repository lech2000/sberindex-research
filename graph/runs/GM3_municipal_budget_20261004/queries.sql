-- total_observations
SELECT COUNT(*) FROM observation;

-- fiscal_observations
SELECT COUNT(*) FROM fiscal_cell;

-- fiscal_releases
SELECT COUNT(DISTINCT release_id) FROM observation WHERE indicator_id LIKE 'fiscal_executed_%';

-- planned_observed_missing
SELECT status,COUNT(*) FROM fiscal_pilot_coverage GROUP BY status ORDER BY status;

-- fiscal_orphans
SELECT COUNT(*) FROM fiscal_cell f LEFT JOIN observation o ON f.observation_id=o.id LEFT JOIN dataset_release r ON o.release_id=r.id LEFT JOIN municipality m ON o.tid=m.tid WHERE o.id IS NULL OR r.id IS NULL OR m.tid IS NULL;

-- duplicate_natural_keys
SELECT COUNT(*) FROM (SELECT release_id,tid,indicator_id,period,dimensions,COUNT(*) n FROM observation GROUP BY 1,2,3,4,5 HAVING n>1);

-- integer_kopeck_mismatch
SELECT COUNT(*) FROM fiscal_cell f JOIN observation o ON o.id=f.observation_id WHERE typeof(f.executed_kopecks)<>'integer' OR f.executed_kopecks<>o.value;

-- fiscal_unknown_availability
SELECT COUNT(*) FROM fiscal_cell f JOIN observation o ON o.id=f.observation_id WHERE o.available_at IS NULL;

-- fiscal_synthetic
SELECT COUNT(*) FROM fiscal_cell f JOIN observation o ON o.id=f.observation_id WHERE o.provenance_class<>'observed';

-- fiscal_asof_2024
SELECT COUNT(*) FROM fiscal_cell f JOIN asof_2024 o ON o.id=f.observation_id;

-- fiscal_spending_population_pairs
SELECT COUNT(*) FROM fiscal_pilot_coverage f WHERE f.status='observed' AND EXISTS (SELECT 1 FROM observation o WHERE o.tid=f.tid AND o.indicator_id='spending' AND o.period LIKE CAST(f.year AS TEXT)||'-%') AND EXISTS (SELECT 1 FROM observation o WHERE o.tid=f.tid AND o.indicator_id='population_total_by_sex' AND o.period=CAST(f.year AS TEXT)||'-01-01');

-- foreign_key_check
PRAGMA foreign_key_check;
