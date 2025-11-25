export function toast(msg, type="info", ms=3200) {
  const el = document.createElement("div");
  el.className = `cf-toast cf-toast-${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  requestAnimationFrame(()=> el.classList.add("show"));
  setTimeout(()=> {
    el.classList.remove("show");
    setTimeout(()=> el.remove(), 300);
  }, ms);
}
