const {chromium}=require(process.env.ATLAS_PLAYWRIGHT_MODULE || '/Users/sergey/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),crypto=require('crypto'),{pathToFileURL}=require('url');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1100}});
 const errors=[],external=[];
 page.on('pageerror',e=>errors.push(String(e)));
 page.on('request',r=>{if(/^https?:/.test(r.url()))external.push(r.url())});
 const dir=__dirname,assert=(v,s)=>{if(!v)throw Error(s)};
 await page.goto(pathToFileURL(path.join(dir,'index.html')).href);
 await page.waitForSelector('#map circle[data-place]');
 assert(await page.locator('#map circle[data-place]').count()===1896,'Full point coverage');
 assert(await page.locator('#place-name').innerText()==='Шалинский','Initial selected story');
 assert((await page.locator('#supported-count').innerText()).replace(/\s/g,'')==='1539','Supported count');
 assert(await page.locator('#anomaly-count').innerText()==='25','Anomaly count');
 await page.locator('#filter').selectOption('persistent');
 assert(await page.locator('#map circle[data-place]').count()===25,'Persistent filter');
 await page.locator('#cases button').filter({hasText:'Черноголовка'}).click();
 assert((await page.locator('#peer-gap').innerText()).includes('-4,14'),'Measured city gap');
 assert((await page.locator('#category-table').innerText()).includes('Общественное питание'),'Category confirmation');
 await page.locator('#zoom').click();
 assert(await page.locator('#map').getAttribute('viewBox')!=='0 0 950 370','City zoom');
 await page.locator('#category').selectOption('Продовольствие');
 await page.locator('#month').selectOption('6');
 assert((await page.locator('#story').innerText()).includes('Продовольствие'),'Category/month selection');
 await page.locator('#category').selectOption('Маркетплейсы');
 await page.locator('#month').selectOption('Q4');
 await page.locator('#horizon').selectOption('6');
 assert((await page.locator('#forecast-city-note').innerText()).includes('первых двух'),'Explicit cold starts');
 await page.locator('#horizon').selectOption('1');
 assert((await page.locator('#forecast-table').innerText()).includes('686,4'),'Aggregate actual MAE rendered');
 assert((await page.locator('#forecast-table').innerText()).includes('1'+String.fromCharCode(160)+'189,1') ||
        (await page.locator('#forecast-table').innerText()).replace(/\s/g,'').includes('1189,1'),'New method actual MAE rendered');
 await page.screenshot({path:path.join(dir,'desktop.png')});
 await page.locator('#forecast-chart').screenshot({path:path.join(dir,'forecast.png')});
 const unsupported=await page.evaluate(()=>DATA.territories.find(r=>!r.supported).territory_id);
 await page.locator('#search').fill(String(unsupported));await page.locator('#search').dispatchEvent('change');
 assert(await page.locator('#place-status').innerText()==='Нет сопоставлений','Unavailable peers explicit');
 assert((await page.locator('#forecast-result').innerText()).includes('недоступна'),'Unavailable correction explicit');
 await page.locator('#search').fill('неизвестная территория xyz');await page.locator('#search').dispatchEvent('change');
 assert((await page.locator('#search-status').innerText()).includes('не найдена'),'Unknown search feedback');
 await page.locator('#cases button').filter({hasText:'Черноголовка'}).click();
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile no horizontal overflow');
 await page.screenshot({path:path.join(dir,'mobile.png'),fullPage:true});
 assert(errors.length===0,'Browser errors '+errors.join(';'));
 assert(external.length===0,'Offline external requests');
 const receipt={status:'PASS',checked_at_utc:new Date().toISOString(),
  html_sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(dir,'index.html'))).digest('hex'),
  browser:'Playwright Chrome',desktop:[1440,1100],mobile:[390,844],
  checks:['1896 points','1539 supported','25 persistent signals','city measured gap','category and month controls',
   'zoom','h1/h6 forecasts and cold-start labels','unavailable peers','unknown search',
   'mobile no overflow','no browser errors','no external requests'],errors,external_requests:external};
 fs.writeFileSync(path.join(dir,'browser_qa.json'),JSON.stringify(receipt,null,2)+'\n');
 console.log(JSON.stringify(receipt));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
