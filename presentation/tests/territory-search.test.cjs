const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {normalize,createIndex,find}=require('../landing-common/territory-search.js');
const source=fs.readFileSync(path.join(__dirname,'../landing-common/territory-coverage.js'),'utf8');
const catalog=JSON.parse(source.slice(source.indexOf('=')+1).trim().replace(/;$/,''));
const index=createIndex(catalog.territories,r=>r.name,r=>r.region,r=>r.id);
test('е and ё, case and punctuation match the same territory',()=>{
  assert.equal(normalize('  ОРЁЛ,  область '),normalize('орел область'));
  assert.deepEqual(find(index,'Орёл'),find(index,'орел'));
  assert.ok(find(index,'Орёл').items.some(r=>r.name==='Орёл'));
});
test('name and region can be typed in either order',()=>{
  const a=find(index,'Шадринск Курганская'),b=find(index,'Курганская Шадринск');
  assert.equal(a.total,2);assert.deepEqual(a,b);assert.equal(a.items[0].name,'Шадринск');
  assert.ok(a.items.some(r=>r.name==='Шадринский'));
});
test('same names remain separate; truncating suggestions never changes total',()=>{
  const all=find(index,'Березовский',100),short=find(index,'Березовский',2);
  assert.ok(all.total>2);assert.equal(short.total,all.total);assert.equal(short.items.length,2);
  assert.ok(new Set(all.items.map(r=>r.region)).size>1);
});
test('region browsing includes available and excluded territories in that region only',()=>{
  const regional=index.filter(r=>r.item.region==='Курганская область');
  const found=find(regional,'',100,{allowEmpty:true});
  assert.equal(found.total,regional.length);assert.ok(found.items.every(r=>r.region==='Курганская область'));
  assert.equal(find(index,'').total,0);
});
test('unknown names do not choose another territory; IDs can disambiguate',()=>{
  assert.equal(find(index,'неттакойтерритории123456').total,0);
  const item=catalog.territories.find(r=>r.name==='Орск');
  assert.equal(find(index,String(item.id)).items[0].id,item.id);
});
test('coverage agrees exactly with the frozen public Atlas; all dictionary IDs remain searchable',()=>{
  const js=fs.readFileSync(path.join(__dirname,'../economic-atlas/demo/atlas-demo-f2098ff9a110.js'),'utf8');
  const data=JSON.parse(js.split('const DATA=')[1].split(';\n')[0]);
  assert.equal(catalog.territories.length,2660);assert.equal(new Set(catalog.territories.map(r=>r.id)).size,2660);
  const available=catalog.territories.filter(r=>r.available);
  assert.equal(available.length,1896);assert.equal(new Set(available.map(r=>r.region)).size,72);
  assert.deepEqual(available.map(r=>r.id).sort((a,b)=>a-b),data.territories.map(r=>r.id).sort((a,b)=>a-b));
  assert.equal(catalog.absent_regions.length,13);
  for(const region of catalog.absent_regions)assert.ok(!available.some(r=>r.region===region));
});
test('excluded places retain their recorded reason; historical codes retain dates',()=>{
  const city=catalog.territories.find(r=>r.name==='Северобайкальск');
  assert.equal(city.available,false);assert.ok(city.reasons.includes('incomplete_spending_history'));
  assert.ok(catalog.territories.some(r=>r.yearTo!==9999));
  assert.ok(catalog.territories.filter(r=>!r.available).every(r=>r.reasons.length));
});
