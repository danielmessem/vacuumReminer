#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.28 / profile 1.8.8.

Automatically copies generated diagnostics output to the clipboard.
Robot profile and protocol are unchanged.
"""
import server_hotfix_v227 as h

w = h.w
VERSION = "2.0.28"
PROFILE_VERSION = "1.8.8"

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.27", "v2.0.28")

w.s.HTML = w.s.HTML.replace(
    "</body>",
    '''<script>
(function(){
  const previousOut = window.out;

  function fallbackCopy(text){
    try{
      const ta=document.createElement('textarea');
      ta.value=text;
      ta.setAttribute('readonly','');
      ta.style.position='fixed';
      ta.style.left='-9999px';
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0,ta.value.length);
      const ok=document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    }catch(e){ return false; }
  }

  async function copyOutput(text){
    try{
      if(navigator.clipboard && window.isSecureContext){
        await navigator.clipboard.writeText(text);
        return true;
      }
    }catch(e){}
    return fallbackCopy(text);
  }

  function markCopied(ok){
    const status=document.getElementById('captureStatus');
    if(status && ok){
      const current=(status.textContent||'').replace(/\s+— copied to clipboard$/,'');
      status.textContent=current+' — copied to clipboard';
      status.style.display='block';
    }
  }

  window.out=function(v){
    if(previousOut) previousOut(v);
    let text;
    try{
      text=typeof v==='string' ? v : JSON.stringify(v,null,2);
    }catch(e){
      text=String(v);
    }
    copyOutput(text).then(markCopied);
    return v;
  };
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
