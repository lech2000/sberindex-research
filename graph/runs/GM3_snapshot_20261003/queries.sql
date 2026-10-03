-- counts
SELECT 'municipality',COUNT(*) FROM municipality UNION ALL SELECT 'release',COUNT(*) FROM dataset_release UNION ALL SELECT 'observation',COUNT(*) FROM observation UNION ALL SELECT 'source_null',COUNT(*) FROM missing_value;

-- orphan_lineage
SELECT COUNT(*) FROM observation o LEFT JOIN dataset_release r ON o.release_id=r.id LEFT JOIN municipality m ON m.tid=o.tid LEFT JOIN indicator i ON i.id=o.indicator_id WHERE r.id IS NULL OR m.tid IS NULL OR i.id IS NULL;

-- duplicate_version_keys
SELECT COUNT(*) FROM (SELECT release_id,tid,indicator_id,period,dimensions,COUNT(*) n FROM observation GROUP BY 1,2,3,4,5 HAVING n>1);

-- asof_2024_eligible
SELECT COUNT(*) FROM asof_2024;

-- unknown_availability
SELECT COUNT(*) FROM observation WHERE available_at IS NULL;

-- spend_population_both
SELECT COUNT(*) FROM (SELECT tid FROM observation WHERE indicator_id='spending' INTERSECT SELECT tid FROM observation WHERE indicator_id='population_total_by_sex');

-- spend_population_both_2024
SELECT COUNT(*) FROM (SELECT tid FROM observation WHERE indicator_id='spending' AND period LIKE '2024-%' INTERSECT SELECT tid FROM observation WHERE indicator_id='population_total_by_sex' AND period='2024-01-01');

-- foreign_key_check
PRAGMA foreign_key_check;
