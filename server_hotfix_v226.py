#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.26 / profile 1.8.8.

Adds immediate visible feedback for diagnostics/capture button actions.
Robot profile and protocol are unchanged.
"""
import server_hotfix_v225 as h

w = h.w
VERSION = "2.0.26"
PROFILE_VERSION = "1.8.8"

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.25", "v2.0.26")

# Add a persistent status strip to the existing page.
w.s.HTML = w.s.HTML.replace(
    "</body>",
    '''<div id="captureStatus" style="position:fixed;right:16px;bottom:16px;z-index:9999;padding:10px 14px;border-radius:8px;background:#202124;color:white;box-shadow:0 2px 10px #0005;display:none;font-weight:600"></div>
<script>
(function(){
  const oldOut = window.out;
  let started = 0;
  function status(msg, hide){
    const el=document.getElementById('captureStatus');
    if(!el)return;
    el.textContent=msg; el.style.display='block';
    if(hide)setTimeout(()=>{el.style.display='none'},hide);
  }
  window.out=function(v){
    if(oldOut) oldOut(v);
    const elapsed=started ? ((Date.now()-started)/1000).toFixed(1) : '0.0';
    let detail='';
    try {
      if(v && typeof v==='object'){
        if(Array.isArray(v.matching_log_fragments)) detail=' — '+v.matching_log_fragments.length+' matching log lines';
        else if(Array.isArray(v.matches)) detail=' — '+v.matches.length+' matches';
      }
    } catch(e){}
    status('Capture complete ('+elapsed+'s)'+detail,5000);
    started=0;
  };
  document.addEventListener('click',function(e){
    const b=e.target.closest('button');
    if(!b)return;
    const txt=(b.textContent||'').trim();
    if(!txt)return;
    started=Date.now();
    status('Running: '+txt+' …',0);
  },true);
  window.addEventListener('unhandledrejection',function(e){status('Capture failed: '+(e.reason&&e.reason.message?e.reason.message:e.reason),8000);started=0;});
})();
</script></body>''',
    1,
)

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; profile remains {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
