// client/mouse_collector.js
(function(){
  const buffer = [];
  let sessionId = Date.now() + "-" + Math.floor(Math.random()*10000);
  function record(e){
    const t = Date.now();
    buffer.push({ x: e.clientX, y: e.clientY, t });
    if(buffer.length > 5000) buffer.shift();
  }
  window.addEventListener('mousemove', record, { passive: true });
  window.addEventListener('click', (e) => buffer.push({ x:e.clientX, y:e.clientY, t: Date.now(), event: 'click' }));
  async function sendBatch(final=false){
    if(buffer.length===0) return;
    const batch = buffer.splice(0, buffer.length);
    const payload = { session_id: sessionId, events: batch, final, meta: { user_agent: navigator.userAgent } };
    try{
      if(final && navigator.sendBeacon){
        const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
        navigator.sendBeacon('/api/collect_mouse', blob);
      } else {
        await fetch('/api/collect_mouse', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      }
    }catch(e){ console.warn('mouse send failed', e); }
  }
  setInterval(()=> sendBatch(false), 3000);
  window.addEventListener('beforeunload', () => sendBatch(true));
})();
