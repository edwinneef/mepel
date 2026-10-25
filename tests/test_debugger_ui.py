import json
import shutil
import subprocess
from importlib.resources import files

import pytest


def test_debugger_renders_read_only_probe_and_timing_status():
    page = files("maplebot").joinpath("static/index.html").read_text("utf-8")

    assert 'id="bindings"' in page
    assert 'id="stage-timing"' in page
    assert 'id="encoder-timing"' in page
    assert 'data-probe="skill"' in page
    assert 'data-probe="up"' in page
    assert 'data-probe="hp_potion"' in page
    assert "confirm_probe" in page
    assert "reject_probe" in page
    assert "pet_food" not in page
    assert "controls-confirm" not in page


def test_alarm_acknowledgement_is_always_visible_outside_the_stop_banner():
    page = files("maplebot").joinpath("static/index.html").read_text("utf-8")
    header = page.split("<header>", 1)[1].split("</header>", 1)[0]

    assert 'id="acknowledge"' in header
    assert "$('acknowledge').hidden" not in page


def test_restart_button_waits_for_a_new_bot_before_reloading_the_dashboard():
    page = files("maplebot").joinpath("static/index.html").read_text("utf-8")

    assert 'id="restart-bot"' in page
    assert "api('restart_bot')" in page
    assert "restart_available" in page
    assert "instance_id" in page
    assert "location.reload()" in page


def test_frozen_selection_survives_an_inflight_live_frame():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to execute the debugger JavaScript regression test")
    page = files("maplebot").joinpath("static/index.html").read_text("utf-8")
    script = page.split("<script>", 1)[1].split("</script>", 1)[0]
    script = script.rsplit("refresh().catch", 1)[0]
    harness = r"""
const assert=require('node:assert/strict'), vm=require('node:vm');
const elements=new Map(), painted=[];
function element(id) {
  if(!elements.has(id))elements.set(id,{
    getContext:()=>({drawImage:bitmap=>painted.push(bitmap.url),strokeRect:()=>{}}),
    getBoundingClientRect:()=>({left:0,top:0,width:200,height:100}),
    setPointerCapture:()=>{},
  });
  return elements.get(id);
}
let finishLive, finishFreeze, failFreeze=false, holdFreeze=false;
let staleClosed=false;
const context=vm.createContext({
  document:{getElementById:element,querySelectorAll:()=>[]},
  fetch:async url=>{
    if(url==='/api/freeze'&&holdFreeze)await new Promise(r=>finishFreeze=r);
    return {ok:!failFreeze,status:200,
      json:async()=>failFreeze?{error:'No screenshot'}:{id:'frozen',width:200,height:100},
      blob:async()=>({url})};
  },
  createImageBitmap:blob=>blob.url.includes('?t=')?
    new Promise(resolve=>finishLive=()=>resolve({url:blob.url,close:()=>staleClosed=true})):
    Promise.resolve({url:blob.url,width:200,height:100,close:()=>{}}),
});
vm.runInContext(SCRIPT,context);
const run=code=>vm.runInContext(code,context);
(async()=>{
  const live=run("draw('/frame.png?t=1')");
  await new Promise(setImmediate);
  await element('freeze').onclick();
  assert.equal(painted.at(-1),'/frame.png?id=frozen');
  finishLive(); await live;
  assert.equal(staleClosed,true);
  assert.equal(painted.at(-1),'/frame.png?id=frozen');
  assert.equal(run('frozen.id'),'frozen');
  const canvas=element('canvas');
  canvas.onpointerdown({clientX:20,clientY:10,pointerId:1});
  canvas.onpointermove({clientX:80,clientY:50}); canvas.onpointerup();
  assert.equal(run('JSON.stringify(selection())'),
    JSON.stringify({id:'frozen',x:20,y:10,width:60,height:40}));
  failFreeze=true; await element('freeze').onclick();
  assert.equal(element('freeze').disabled,false);
  assert.equal(run('freezing'),false);
  assert.equal(element('message').textContent,'No screenshot');
  failFreeze=false; holdFreeze=true;
  const pending=element('freeze').onclick();
  await new Promise(setImmediate);
  await element('live').onclick();
  finishFreeze(); await pending;
  assert.equal(run('frozen'),null);
  assert.equal(element('message').textContent,'Live view');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(
        [node, "-"], input=harness.replace("SCRIPT", json.dumps(script)),
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
