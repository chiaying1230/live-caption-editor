// Optional browser regression against a server on 8010. ASR/API are mocked;
// synthetic audio never accesses the computer's physical microphone.
const {chromium} = require('../work/node_modules/playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true,args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
  const page = await browser.newPage({viewport:{width:1440,height:900},permissions:['microphone']});
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const session = {id:'ui-fixture',title:'即時字幕示範',created_at:new Date().toISOString()};
  const rows = Array.from({length:14},(_,i)=>({id:`line-${i}`,session_id:session.id,start:i*4,end:i*4+4,text:`第 ${i+1} 句：今天的活動會持續提供即時字幕，讓每一位參與者都能輕鬆閱讀。`,status:'committed',revision:1,locked:false}));
  let socket;
  let glossary=[];
  await page.route('**/api/**',async route => {
    const request = route.request(), url = new URL(request.url()); let body;
    if (url.pathname === '/api/health') body={label:'FunASR',model:'UI fixture',device:'cpu'};
    else if (url.pathname === '/api/glossary') {
      if(request.method()==='PUT') glossary=request.postDataJSON().entries;
      body={entries:glossary};
    }
    else if (url.pathname === '/api/sessions') body=[session];
    else if (request.method() === 'PATCH') {
      const input=request.postDataJSON(), row=rows.find(r=>r.id===url.pathname.split('/').at(-1));
      assert.equal(input.revision,row.revision);
      Object.assign(row,{text:input.text,status:'human_corrected',locked:true,revision:row.revision+1}); body=row;
    } else body={session,segments:rows,recording:false};
    await route.fulfill({json:body});
  });
  await page.routeWebSocket('**/audio', route => {
    socket=route; route.send(JSON.stringify({type:'ready',threshold:.003}));
    route.onMessage(message => {
      if(typeof message==='string' && JSON.parse(message).type==='stop') route.send(JSON.stringify({type:'stopped'}));
    });
  });
  const send=row=>socket.send(JSON.stringify({type:'segment',segment:row}));
  const pinned=()=>page.waitForFunction(()=>{const v=document.getElementById('caption-viewport');return v.scrollHeight-v.clientHeight-v.scrollTop<4;});
  try {
    await page.goto(process.env.UI_BASE_URL || 'http://127.0.0.1:8010');
    await page.locator('#start:enabled').waitFor(); await pinned();
    assert.equal(await page.locator('.segment-text').first().evaluate(e=>getComputedStyle(e).color),'rgb(255, 229, 90)');
    await page.locator('#start').click();
    await page.waitForFunction(()=>document.getElementById('recording-status').textContent==='正在收音');
    await page.locator('#edit-latest').click();
    const input=page.locator('[data-id="line-13"] .segment-text');
    assert.equal(await input.getAttribute('contenteditable'),'plaintext-only');
    await input.fill('人工校正：像 Word 一樣直接修改，新的字幕仍會出現。');
    const next={id:'live-1',session_id:session.id,start:56,end:59,text:'接著這一句仍在繼續辨識，有逗號，也有句號。',status:'provisional',revision:1,locked:false};
    send(next); await page.locator('[data-id="live-1"]:visible').waitFor();
    assert.match(await input.innerText(),/^人工校正/);
    assert.equal(await page.evaluate(()=>document.activeElement.closest('article')?.dataset.id),'line-13');
    assert.equal(await page.locator('#live-peek').count(),0);
    assert.equal(await page.locator('[data-id="live-1"] .segment-text').textContent(),next.text);
    assert.equal(await page.locator('#floating-editor').count(),0);
    await page.locator('[data-id="line-13"].human_corrected').waitFor();
    assert.equal(rows[13].locked,true);
    send({...rows[13],text:'過期辨識不得覆寫',status:'committed',revision:1}); await page.waitForTimeout(100);
    assert.match(await input.innerText(),/^人工校正/);
    await input.fill('繼續修改，按 Esc 取消這次尚未儲存的內容。');
    await input.press('Escape'); assert.match(await input.innerText(),/^人工校正/);
    send({...next,status:'committed',revision:2}); await page.locator('[data-id="live-1"].committed').waitFor();
    await page.locator('[data-id="live-1"] .segment-text').click();
    await page.screenshot({path:'work/caption-inline-editor.png'});
    await page.locator('[data-id="live-1"] .segment-text').press('Escape');
    send({...next,id:'blank',text:'',status:'committed'}); await page.waitForTimeout(100);
    assert.equal(await page.locator('[data-id="blank"]').isVisible(),false);
    if(await page.locator('#follow-latest').isVisible()) await page.locator('#follow-latest').click(); await pinned();
    await page.locator('#caption-viewport').hover(); await page.mouse.wheel(0,-1000); await page.locator('#follow-latest:visible').waitFor();
    const before=await page.locator('#caption-viewport').evaluate(v=>v.scrollTop);
    send({...next,id:'live-2',start:60,end:63,text:'新增字幕時，查看前文的位置會被保留。'}); await page.waitForTimeout(100);
    assert.equal(await page.locator('#caption-viewport').evaluate(v=>v.scrollTop),before);
    await page.locator('#follow-latest').click(); await pinned();
    await page.locator('#stop').click(); await page.locator('#start:enabled').waitFor();
    await page.locator('#caption-size').fill('88'); await pinned();
    assert.equal(await page.locator('.segment').first().evaluate(e=>getComputedStyle(e).fontSize),'88px');
    await page.locator('#fullscreen').click(); assert.ok(await page.evaluate(()=>!!document.fullscreenElement));
    await page.locator('#fullscreen').click(); await page.screenshot({path:'work/caption-audience.png'});
    await page.locator('#settings-toggle').click();
    await page.locator('#glossary-text').fill('錯詞\t正詞\n錯誤詞 → 正確詞');
    await page.locator('#glossary-save').click();
    await page.waitForFunction(()=>document.getElementById('glossary-status').textContent.startsWith('已儲存 2 組'));
    assert.deepEqual(glossary,[{source:'錯詞',target:'正詞'},{source:'錯誤詞',target:'正確詞'}]);
    await page.locator('#glossary-text').fill('這行缺少正確詞'); await page.locator('#glossary-save').click();
    await page.waitForFunction(()=>document.getElementById('glossary-status').textContent.includes('第 1 行'));
    assert.equal(glossary.length,2);
    await page.locator('#settings-close').click();
    await page.setViewportSize({width:390,height:844}); await page.locator('#edit-latest').click(); await page.waitForTimeout(100);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.ok(await page.evaluate(()=>document.getElementById('caption-viewport').clientHeight>200));
    await page.screenshot({path:'work/caption-small-screen.png'}); assert.deepEqual(errors,[]);
    console.log('PASS: inline Word-style editing, auto-save, cancel, live captions during correction, focus preservation, stale lock protection, follow/history, punctuation, large font, fullscreen, narrow layout');
  } catch(error) {await page.screenshot({path:'work/caption-ui-failure.png'});throw error;}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
