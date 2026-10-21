/* Khung chat website (chatbot trong Open WebUI). Nhung: <script src="https://<open-webui>/api/v1/cqf/webchat/widget.js" defer></script> */
(function () {
  if (window.__cqfWebchat) return;
  window.__cqfWebchat = true;
  var CONF = __WEBCHAT_CONFIG__;
  var me = document.currentScript || document.querySelector('script[src*="cqf/webchat/widget.js"]');
  var API = new URL(me.src).origin + CONF.api;
  var KEY = "cqf_webchat_v1";

  function load() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
  function rid() {
    var a = new Uint8Array(12);
    (window.crypto || window.msCrypto).getRandomValues(a);
    return Array.prototype.map.call(a, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }
  var state = load();
  if (!state.vid) { state.vid = rid(); state.log = []; save(); }

  function esc(s) { return s.replace(/[&<>"']/g, function (c) { return "&#" + c.charCodeAt(0) + ";"; }); }
  function fmt(s) {
    return esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
      .replace(/\n/g, "<br>");
  }

  var C = CONF.color || "#0e7466";
  var css = "#cqf-btn{position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;border:0;cursor:pointer;" +
    "background:" + C + ";color:#fff;box-shadow:0 4px 14px rgba(0,0,0,.25);z-index:2147483000;display:grid;place-items:center}" +
    "#cqf-box{position:fixed;right:20px;bottom:88px;width:360px;max-width:calc(100vw - 32px);height:500px;max-height:calc(100vh - 120px);" +
    "background:#fff;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.22);display:none;flex-direction:column;overflow:hidden;" +
    "font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;color:#1b2430;z-index:2147483000}" +
    "#cqf-box.open{display:flex}#cqf-head{background:" + C + ";color:#fff;padding:12px 14px;font-weight:600}" +
    "#cqf-log{flex:1;overflow-y:auto;padding:12px;background:#f5f7f6}" +
    ".cqf-m{max-width:85%;padding:8px 11px;border-radius:12px;margin:4px 0;word-wrap:break-word}" +
    ".cqf-bot{background:#fff;border:1px solid #e3e8e6}.cqf-user{background:" + C + ";color:#fff;margin-left:auto}" +
    ".cqf-m a{color:inherit;text-decoration:underline}#cqf-typing{display:none;color:#6b7684;font-size:12px;padding:0 12px 6px;background:#f5f7f6}" +
    "#cqf-form{display:flex;border-top:1px solid #e3e8e6}#cqf-in{flex:1;border:0;padding:12px;font:inherit;outline:none}" +
    "#cqf-send{border:0;background:none;color:" + C + ";font-weight:600;padding:0 14px;cursor:pointer}#cqf-send:disabled{opacity:.5}";
  var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  var box = document.createElement("div"); box.id = "cqf-box";
  box.setAttribute("role", "dialog"); box.setAttribute("aria-label", CONF.title);
  box.innerHTML = '<div id="cqf-head"></div><div id="cqf-log" aria-live="polite"></div><div id="cqf-typing">Đang trả lời…</div>' +
    '<form id="cqf-form"><input id="cqf-in" maxlength="1000" autocomplete="off" placeholder="Nhập câu hỏi…" aria-label="Câu hỏi"><button id="cqf-send">Gửi</button></form>';
  var btn = document.createElement("button"); btn.id = "cqf-btn"; btn.setAttribute("aria-label", CONF.title);
  btn.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  document.body.appendChild(box); document.body.appendChild(btn);
  box.querySelector("#cqf-head").textContent = CONF.title;
  var logEl = box.querySelector("#cqf-log"), typingEl = box.querySelector("#cqf-typing"),
      input = box.querySelector("#cqf-in"), send = box.querySelector("#cqf-send");

  function add(role, text, keep) {
    var d = document.createElement("div");
    d.className = "cqf-m " + (role === "user" ? "cqf-user" : "cqf-bot");
    d.innerHTML = fmt(text);
    logEl.appendChild(d); logEl.scrollTop = logEl.scrollHeight;
    if (keep) { state.log.push({ r: role, t: text }); state.log = state.log.slice(-60); save(); }
  }
  add("bot", CONF.greeting, false);
  state.log.forEach(function (m) { add(m.r, m.t, false); });

  btn.onclick = function () {
    box.classList.toggle("open");
    if (box.classList.contains("open")) input.focus();
  };
  box.querySelector("#cqf-form").onsubmit = function (e) {
    e.preventDefault();
    var text = input.value.trim(); if (!text || send.disabled) return;
    input.value = ""; add("user", text, true);
    send.disabled = true; typingEl.style.display = "block";
    fetch(API + "/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vid: state.vid, text: text, page: location.href }) })
      .then(function (r) {
        if (r.status === 429) return add("bot", "Anh/chị gửi hơi nhanh, vui lòng thử lại sau ít phút ạ.", false);
        if (!r.ok) return add("bot", "Xin lỗi, hệ thống đang bận. Anh/chị thử lại giúp em ạ.", false);
        return r.json().then(function (j) { add("bot", j.reply || "", true); });
      })
      .catch(function () { add("bot", "Không kết nối được. Anh/chị kiểm tra mạng giúp em ạ.", false); })
      .then(function () { send.disabled = false; typingEl.style.display = "none"; });
  };
})();
