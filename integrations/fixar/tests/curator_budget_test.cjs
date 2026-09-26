'use strict';

// Проверяет реальное выражение jsonBody узла «Передать куратору»
// (n8n/workflows/16_sberindex_graph_steward.json) на мокированных
// ссылках $('...'). Server(dialog-service) отклоняет dialog.message > 4000.

const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const WORKFLOW_PATH = path.join(__dirname, '..', '..', 'n8n', 'workflows', '16_sberindex_graph_steward.json');
const NODE_NAME = 'Передать куратору';
const BUDGET = 4000;
const RUN_KEY = 'curator-2026092609';

const workflow = JSON.parse(fs.readFileSync(WORKFLOW_PATH, 'utf8'));
const node = (workflow.nodes || []).find(candidate => candidate && candidate.name === NODE_NAME);
assert.ok(node, `узел «${NODE_NAME}» найден в workflow`);

const rawExpression = String(node.parameters.jsonBody || '');
assert.ok(rawExpression.startsWith('={{') && rawExpression.endsWith('}}'), 'jsonBody — выражение n8n вида {{ ... }}');
const expression = rawExpression.slice(3, -2).trim();
assert.ok(expression.startsWith('(() =>'), 'тело собирается IIFE');
assert.ok(!/\.slice\(/.test(expression), 'выражение не должно срезать JSON/текст (.slice запрещён)');

function evaluate(refs) {
  const dollar = name => {
    assert.ok(Object.prototype.hasOwnProperty.call(refs, name), `неожиданная ссылка на узел ${name}`);
    return { item: { json: refs[name] } };
  };
  return new Function('$', `return (${expression});`)(dollar);
}

function makeEvidence(claims) {
  return {
    schema_version: '1.0',
    run_key: RUN_KEY,
    topic: 'Муниципальный граф: департамент образования связан с районом',
    source_url: 'https://example.org/sberindex/graph-77',
    checked_at: '2026-09-26T09:15:00.000Z',
    status: 'verified',
    confidence: 0.77,
    entities: [
      { entity_id: 'municipality:123456', entity_type: 'municipality', provenance_class: 'observed' },
      { entity_id: 'organization:77', entity_type: 'organization', provenance_class: 'observed' }
    ],
    relations: [
      { source_entity_id: 'organization:77', target_entity_id: 'municipality:123456', relation_type: 'LOCATED_IN', provenance_class: 'observed', evidence_url: 'https://example.org/r/1', confidence: 0.7 }
    ],
    claims
  };
}

function refsFor(evidence, ingest) {
  return {
    'Проверить EVIDENCE_JSON': { evidence },
    'Ingest в corpus 77': ingest,
    'Подготовить атомарный проход': { run_key: RUN_KEY }
  };
}

// --- Сценарий 1: малый payload — полное исходное сообщение без сокращений ---
const smallEvidence = makeEvidence([
  { statement: 'Департамент образования числится в составе района t0zz.', provenance_class: 'observed', evidence_url: 'https://example.org/c/0', confidence: 0.9 },
  { statement: 'Район связан с муниципалитетом t1zz.', provenance_class: 'source_estimate', evidence_url: 'https://example.org/c/1', confidence: 0.6 },
  { statement: 'Проверка выполнена 26.09.2026 t2zz.', provenance_class: 'observed', evidence_url: 'https://example.org/c/2', confidence: 0.8 }
]);
const smallIngest = { document_id: 'doc_small_0001', corpus_id: 77, duplicate: false };
const smallBody = evaluate(refsFor(smallEvidence, smallIngest));
assert.doesNotThrow(() => JSON.parse(smallBody), 'small: тело запроса — валидный JSON');
const smallParsed = JSON.parse(smallBody);
assert.strictEqual(smallParsed.case_id, 'case_d058db85c48a487c', 'small: case_id сохранён');
assert.strictEqual(smallParsed.client_message_id, RUN_KEY + ':curator', 'small: client_message_id от run_key');
assert.ok(smallParsed.message.length <= BUDGET, `small: message.length=${smallParsed.message.length} <= ${BUDGET}`);
assert.ok(smallParsed.message.includes('Прими один staging-результат'), 'small: исходный текст задания сохранён');
assert.ok(smallParsed.message.includes(JSON.stringify(smallEvidence)), 'small: полное evidence сохранено целиком');
assert.ok(smallParsed.message.includes(JSON.stringify(smallIngest)), 'small: полная квитанция ingest сохранена целиком');
assert.ok(!smallParsed.message.includes('omitted_claim_indexes'), 'small: без сокращений omitted_claim_indexes не нужен');

// --- Сценарий 2: огромные evidence/receipt/unicode -> сводка <=4000, валидный JSON ---
const hugeClaims = [];
for (let i = 0; i < 40; i++) {
  hugeClaims.push({
    statement: 'Утв-' + i + ' t' + i + 'zz «ёлки» "quoted" строка\nвторая строка ' + i + ' 🚀🏙 unicode',
    provenance_class: i % 2 ? 'source_estimate' : 'observed',
    evidence_url: 'https://example.org/huge/' + i,
    confidence: 0.5
  });
}
hugeClaims.splice(10, 0, {
  statement: 'Гигант tHugezz: ' + 'я'.repeat(4000),
  provenance_class: 'model_estimate',
  evidence_url: 'https://example.org/huge/giant',
  confidence: 0.1
});
const hugeEvidence = makeEvidence(hugeClaims);
const hugeIngest = {
  id: 'doc_huge_' + 'x'.repeat(64),
  corpus_id: 77,
  duplicate: true,
  raw_response: { detail: 'лишнее поле ' + 'ж'.repeat(2000) }
};
const hugeBody = evaluate(refsFor(hugeEvidence, hugeIngest));
assert.doesNotThrow(() => JSON.parse(hugeBody), 'huge: тело запроса — валидный JSON (unicode/экранирование не рваны)');
const hugeParsed = JSON.parse(hugeBody);
const message = hugeParsed.message;

assert.ok(message.length <= BUDGET, `huge: message.length=${message.length} <= ${BUDGET}`);
assert.strictEqual(hugeParsed.case_id, 'case_d058db85c48a487c', 'huge: case_id сохранён');
assert.strictEqual(hugeParsed.client_message_id, RUN_KEY + ':curator', 'huge: client_message_id от run_key');
assert.ok(message.includes('run_key: ' + RUN_KEY), 'huge: run_key сохранён в сводке');

const compactReceipt = { document_id: hugeIngest.id, corpus_id: 77, duplicate: true };
assert.ok(message.includes(JSON.stringify(compactReceipt)), 'huge: компактная квитанция ingest {document_id/id,corpus_id,duplicate} сохранена');
assert.ok(!message.includes(hugeIngest.raw_response.detail), 'huge: лишние поля квитанции не тащим');

const countsLine = 'entities: ' + hugeEvidence.entities.length + ' | relations: ' + hugeEvidence.relations.length + ' | claims всего: ' + hugeClaims.length;
assert.ok(message.includes(countsLine), 'huge: счётчики entities/relations/claims на месте');

const omittedMatch = message.match(/omitted_claim_indexes: (\[[0-9,]*\])/);
assert.ok(omittedMatch, 'huge: явный omitted_claim_indexes обязателен');
const omitted = JSON.parse(omittedMatch[1]);

const included = [];
hugeClaims.forEach((claim, index) => {
  const wholeLine = '#' + index + ' ' + JSON.stringify(claim);
  if (message.includes(wholeLine)) {
    included.push(index);
  } else {
    assert.ok(!message.includes(JSON.stringify(claim)), `huge: claim #${index} не должен присутствовать частично (никакой срезки JSON)`);
    assert.ok(!message.includes(JSON.stringify(claim.statement)), `huge: текст claim #${index} не должен просачиваться фрагментами`);
  }
});
const claimLines = (message.match(/\n#\d+ /g) || []).length;
assert.strictEqual(claimLines, included.length, 'huge: каждая строка claim целая и ровно одна на claim');

assert.ok(included.length > 0, 'huge: часть claims должна попасть целиком');
assert.ok(omitted.length > 0, 'huge: должны быть явные пропуски');
assert.ok(included.includes(0), 'huge: первые claims сохраняются по порядку');
assert.ok(!included.includes(10), 'huge: гигантский claim #10 не может поместиться целиком');
const expectedOmitted = hugeClaims.map((_, index) => index).filter(index => !included.includes(index));
assert.deepStrictEqual(omitted, expectedOmitted, 'huge: omitted_claim_indexes — точный комплект пропущенных (identity индексов сохранена)');

assert.ok(/ЗАПРЕЩЕНО принимать/.test(message), 'huge: приём omitted-claims явно запрещён');
assert.ok(message.includes('corpus 77'), 'huge: полное evidence указано как записанное в corpus 77');
assert.ok(/duplicate=true, не отправляй повторно проверять наличие семантическим поиском\.$/.test(message), 'huge: сообщение заканчивается квитанционным правилом, а не обрезанным JSON');

const altIngest = { document_id: 'doc_alt_42', corpus_id: 77, duplicate: false };
const altMessage = JSON.parse(evaluate(refsFor(hugeEvidence, altIngest))).message;
assert.ok(altMessage.length <= BUDGET, 'huge: вариант document_id тоже <= 4000');
assert.ok(altMessage.includes(JSON.stringify({ document_id: 'doc_alt_42', corpus_id: 77, duplicate: false })), 'huge: document_id и id — оба варианта квитанции сохраняются');

// --- Сценарий 3: irreducible message>4000 обязан падать, а не срезать ---
const fatEvidence = makeEvidence([]);
fatEvidence.topic = 'Т'.repeat(6000);
assert.throws(
  () => evaluate(refsFor(fatEvidence, { document_id: 'doc_fat', corpus_id: 77, duplicate: false })),
  /irreducible message>4000/,
  'irreducible message>4000 должен падать с явной ошибкой'
);

console.log('OK: sberindex curator budget test passed (small / huge+unicode / irreducible-fail)');
