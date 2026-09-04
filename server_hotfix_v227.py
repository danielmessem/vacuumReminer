#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.27 / profile 1.8.8.

Extends Copy -> Copied feedback so it stays visible long enough to read.
Robot profile and protocol are unchanged.
"""
import server_hotfix_v226 as h

w = h.w
VERSION = "2.0.27"
PROFILE_VERSION = "1.8.8"

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.26", "v2.0.27")

# Hold any button that changes to "Copied" in that state for ~3 seconds,
# even if the older UI code tries to revert it sooner.
w.s.HTML = w.s.HTML.replace(
    "</body>",
    '''<script>
(function(){
  const holdMs = 3000;
  const held = new WeakMap();
  const observer = new MutationObserver(function(mutations){
    for(const m of mutations){
      const el = m.target.nodeType === 3 ? m.target.parentElement : m.target;
      if(!el || el.tagName !== 'BUTTON') continue;
      const txt = (el.textContent || '').trim().toLowerCase();
      const until = held.get(el) || 0;
      if(txt === 'copied'){
        if(!until){
          const end = Date.now() + holdMs;
          held.set(el, end);
          setTimeout(function(){
            if((held.get(el) || 0) === end){
              held.delete(el);
              if((el.textContent || '').trim().toLowerCase() === 'copied') el.textContent = 'Copy';
            }
          }, holdMs);
        }
      } else if(until && Date.now() < until){
        el.textContent = 'Copied';
      } else if(until){
        held.delete(el);
      }
    }
  });
  observer.observe(document.body,{subtree:true,childList:true,characterData:true});
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
