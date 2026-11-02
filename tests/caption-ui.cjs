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
  await page.route('**/api/**',async route => {
    const request = route.request(), url = new URL(request.url()); let body;
    if (url.pathname === '/api/health') body={label:'FunASR',model:'UI fixture',device:'cpu'};
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
    const input=page.locator('#correction-text'); await input.fill('人工校正：這句在編輯時，後續字幕仍應繼續顯示。');
    const next={id:'live-1',session_id:session.id,start:56,end:59,text:'接著這一句仍在繼續辨識，字幕不會被校正視窗遮住。',status:'provisional',revision:1,locked:false};
    send(next); await page.locator('[data-id="live-1"]:visible').waitFor(); await pinned();
    assert.match(await input.inputValue(),/^人工校正/);
    assert.equal(await page.evaluate(()=>document.activeElement.id),'correction-text');
    assert.ok(await page.evaluate(()=>document.getElementById('floating-editor').getBoundingClientRect().bottom < document.getElementById('caption-viewport').getBoundingClientRect().top));
    assert.ok(await page.evaluate(()=>document.querySelector('[data-id="live-1"]').getBoundingClientRect().bottom <= document.getElementById('caption-viewport').getBoundingClientRect().bottom));
    send({...next,id:'blank',text:'',status:'committed'}); await page.waitForTimeout(100);
    assert.equal(await page.locator('[data-id="blank"]').isVisible(),false);
    await page.locator('#editor-save').click(); await page.locator('.human_corrected').waitFor(); assert.equal(rows[13].locked,true);
    send({...rows[13],text:'過期辨識不得覆寫',status:'committed',revision:1}); await page.waitForTimeout(100);
    assert.match(await page.locator('[data-id="line-13"]').textContent(),/^人工校正/);
    send({...next,status:'committed',revision:2}); await page.locator('[data-id="live-1"].committed').waitFor();
    const box=await page.locator('#editor-handle').boundingBox();
    await page.mouse.move(box.x+80,box.y+15); await page.mouse.down(); await page.mouse.move(box.x+240,box.y+55); await page.mouse.up(); await pinned();
    assert.ok((await page.locator('#floating-editor').boundingBox()).x>450);
    await page.screenshot({path:'work/caption-floating-editor.png'});
    await page.locator('#editor-close').click();
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
    await page.setViewportSize({width:390,height:844}); await page.locator('#edit-latest').click(); await page.waitForTimeout(100);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.ok(await page.evaluate(()=>{const r=document.getElementById('floating-editor').getBoundingClientRect();return r.left>=0 && r.right<=innerWidth && r.top>=0;}));
    assert.ok(await page.evaluate(()=>document.getElementById('caption-viewport').clientHeight>200));
    await page.screenshot({path:'work/caption-small-screen.png'}); assert.deepEqual(errors,[]);
    console.log('PASS: follow/history, correction during capture, focus/draft preservation, stale lock protection, empty suppression, drag, large font, fullscreen, narrow layout');
  } catch(error) {await page.screenshot({path:'work/caption-ui-failure.png'});throw error;}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
