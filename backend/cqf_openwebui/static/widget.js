/* Khung chat website (chatbot trong Open WebUI). Nhung: <script src="https://<open-webui>/api/v1/cqf/webchat/widget.js" defer></script>
 * Shadow DOM (CSS cua website khong anh huong), tra loi dang stream, hien cac buoc tra tai lieu, hien thi Markdown. */
(function () {
  if (window.__cqfWebchat) return;
  window.__cqfWebchat = true;
  var CONF = __WEBCHAT_CONFIG__;
  var me = document.currentScript || document.querySelector('script[src*="cqf/webchat/widget.js"]');
  var API = new URL(me.src).origin + CONF.api;
  var KEY = "cqf_webchat_v2";
  var C = /^#[0-9a-f]{6}$/i.test(CONF.color || "") ? CONF.color : "#0e7466";
  var NAME = CONF.shop || CONF.title || "Tư vấn";

  function load() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
  function rid() {
    var a = new Uint8Array(12);
    (window.crypto || window.msCrypto).getRandomValues(a);
    return Array.prototype.map.call(a, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }
  var state = load();
  if (!state.vid) { state.vid = rid(); state.log = []; save(); }

  // ---------------------------------------------------------------- Markdown (escape truoc, roi moi dinh dang)
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return "&#" + c.charCodeAt(0) + ";"; }); }
  function inline(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  }
  function md(text) {
    var lines = String(text).replace(/\r\n/g, "\n").split("\n"), out = [], list = null, para = [], table = null;
    function fp() { if (para.length) { out.push("<p>" + para.map(inline).join("<br>") + "</p>"); para = []; } }
    function fl() { if (list) { out.push("<" + list.t + ">" + list.i.map(function (x) { return "<li>" + inline(x) + "</li>"; }).join("") + "</" + list.t + ">"); list = null; } }
    function ft() {
      if (!table) return;
      var rows = table.filter(function (r) { return !/^\s*\|?\s*:?-{2,}/.test(r); }).map(function (r) {
        return r.replace(/^\s*\||\|\s*$/g, "").split("|").map(function (c) { return inline(c.trim()); });
      });
      if (rows.length) {
        out.push('<div class="tw"><table><thead><tr>' + rows[0].map(function (c) { return "<th>" + c + "</th>"; }).join("") +
          "</tr></thead><tbody>" + rows.slice(1).map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + c + "</td>"; }).join("") + "</tr>"; }).join("") +
          "</tbody></table></div>");
      }
      table = null;
    }
    function fa() { fp(); fl(); ft(); }
    lines.forEach(function (line) {
      var st = line.trim(), m;
      if (!st) return fa();
      if ((m = st.match(/^#{1,6}\s+(.*)$/))) { fa(); out.push("<h4>" + inline(m[1]) + "</h4>"); return; }
      if (st.charAt(0) === "|") { fp(); fl(); (table = table || []).push(st); return; }
      if ((m = st.match(/^([-*+•]|\d+[.)])\s+(.*)$/))) {
        fp(); ft();
        var t = /\d/.test(m[1]) ? "ol" : "ul";
        if (list && list.t !== t) fl();
        (list = list || { t: t, i: [] }).i.push(m[2]);
        return;
      }
      if (/^(-{3,}|\*{3,})$/.test(st)) { fa(); out.push("<hr>"); return; }
      fl(); ft(); para.push(st);
    });
    fa();
    return out.join("");
  }

  // ---------------------------------------------------------------- giao dien (Shadow DOM)
  var host = document.createElement("div");
  host.id = "cqf-webchat";
  host.style.cssText = "position:fixed;z-index:2147483000;right:0;bottom:0;width:0;height:0";
  document.body.appendChild(host);
  var root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;

  var css =
    ":host{all:initial}*{box-sizing:border-box}[hidden]{display:none!important}" +
    ".wrap{font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:#1b2430;-webkit-font-smoothing:antialiased}" +
    ".launch{position:fixed;right:20px;bottom:20px;width:58px;height:58px;border-radius:50%;border:0;cursor:pointer;background:" + C + ";color:#fff;" +
    "box-shadow:0 6px 20px rgba(0,0,0,.22);display:grid;place-items:center;transition:transform .15s}" +
    ".launch:hover{transform:scale(1.05)}.launch svg{width:26px;height:26px}" +
    ".launch .x{display:none}.open .launch .x{display:block}.open .launch .c{display:none}" +
    ".panel{position:fixed;right:20px;bottom:92px;width:380px;max-width:calc(100vw - 32px);height:620px;max-height:calc(100vh - 116px);" +
    "background:#fff;border-radius:18px;box-shadow:0 12px 40px rgba(15,23,42,.22);display:flex;flex-direction:column;overflow:hidden;" +
    "opacity:0;transform:translateY(12px) scale(.98);pointer-events:none;transition:opacity .16s,transform .16s}" +
    ".open .panel{opacity:1;transform:none;pointer-events:auto}" +
    ".head{background:" + C + ";color:#fff;padding:14px 14px 14px 16px;display:flex;align-items:center;gap:12px}" +
    ".av{width:38px;height:38px;border-radius:50%;background:rgba(255,255,255,.2);display:grid;place-items:center;font-weight:700;position:relative;flex:none}" +
    ".av::after{content:'';position:absolute;right:0;bottom:0;width:10px;height:10px;border-radius:50%;background:#34d399;border:2px solid " + C + "}" +
    ".who{flex:1;min-width:0}.who b{display:block;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.who span{font-size:12px;opacity:.85}" +
    ".close{border:0;background:rgba(255,255,255,.14);color:#fff;width:32px;height:32px;border-radius:50%;cursor:pointer;display:grid;place-items:center}" +
    ".close:hover{background:rgba(255,255,255,.25)}.close svg{width:16px;height:16px}" +
    ".log{flex:1;overflow-y:auto;padding:16px 14px;background:#f6f7f9;display:flex;flex-direction:column;gap:10px;scroll-behavior:smooth}" +
    ".row{display:flex;gap:8px;align-items:flex-end;max-width:100%}.row.user{justify-content:flex-end}" +
    ".mini{width:26px;height:26px;border-radius:50%;background:" + C + ";color:#fff;font-size:12px;font-weight:700;display:grid;place-items:center;flex:none}" +
    ".bubble{max-width:82%;padding:9px 13px;border-radius:16px;word-wrap:break-word;overflow-wrap:anywhere;min-width:0}" +
    ".bot .bubble{background:#fff;border:1px solid #e6e9ee;border-bottom-left-radius:5px}" +
    ".user .bubble{background:" + C + ";color:#fff;border-bottom-right-radius:5px;white-space:pre-wrap}" +
    ".bubble p{margin:0 0 6px}.bubble p:last-child{margin-bottom:0}.bubble ul,.bubble ol{margin:4px 0 6px;padding-left:20px}.bubble li{margin:2px 0}" +
    ".bubble h4{margin:6px 0 4px;font-size:14px}.bubble a{color:" + C + ";text-decoration:underline}.user .bubble a{color:#fff}" +
    ".bubble code{background:#f0f2f5;border-radius:4px;padding:0 4px;font-size:12.5px}.bubble hr{border:0;border-top:1px solid #e6e9ee;margin:8px 0}" +
    ".tw{overflow-x:auto;margin:6px 0;border:1px solid #e6e9ee;border-radius:10px}.tw table{border-collapse:collapse;font-size:13px;min-width:100%}" +
    ".tw th,.tw td{padding:6px 10px;text-align:left;border-bottom:1px solid #eef0f3;white-space:nowrap}.tw th{background:#f6f7f9;font-weight:600}.tw tr:last-child td{border-bottom:0}" +
    ".caret::after{content:'';display:inline-block;width:7px;height:15px;margin-left:2px;vertical-align:-2px;background:" + C + ";animation:bl 1s steps(2) infinite}" +
    "@keyframes bl{50%{opacity:0}}" +
    ".steps{margin-left:34px;font-size:12px;color:#6b7684;max-width:82%}" +
    ".steps button{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:999px;background:#eef1f4;color:#4b5563}" +
    ".steps button:focus-visible{outline:2px solid " + C + "}" +
    ".steps ul{list-style:none;margin:6px 0 0;padding:0 0 0 4px;display:flex;flex-direction:column;gap:3px}" +
    ".steps li{display:flex;gap:6px;align-items:baseline}.steps li::before{content:'✓';color:" + C + ";font-weight:700}" +
    ".steps li.now::before{content:'';width:9px;height:9px;border:2px solid " + C + ";border-right-color:transparent;border-radius:50%;animation:sp .7s linear infinite;flex:none;align-self:center}" +
    "@keyframes sp{to{transform:rotate(360deg)}}" +
    ".dots{display:inline-flex;gap:4px;padding:4px 2px}.dots i{width:7px;height:7px;border-radius:50%;background:#9aa3ad;animation:dt 1.2s infinite}" +
    ".dots i:nth-child(2){animation-delay:.15s}.dots i:nth-child(3){animation-delay:.3s}@keyframes dt{0%,60%,100%{opacity:.3;transform:none}30%{opacity:1;transform:translateY(-3px)}}" +
    ".foot{border-top:1px solid #e6e9ee;padding:10px;background:#fff}" +
    ".box{display:flex;align-items:flex-end;gap:8px;border:1px solid #dfe3e8;border-radius:14px;padding:6px 6px 6px 12px;transition:border-color .12s}" +
    ".box:focus-within{border-color:" + C + "}" +
    "textarea{flex:1;border:0;outline:none;resize:none;font:inherit;color:inherit;max-height:120px;min-height:22px;padding:5px 0;background:transparent}" +
    ".send{border:0;width:36px;height:36px;border-radius:10px;background:" + C + ";color:#fff;cursor:pointer;display:grid;place-items:center;flex:none}" +
    ".send:disabled{opacity:.4;cursor:default}.send svg{width:17px;height:17px}" +
    ".note{text-align:center;font-size:11px;color:#9aa3ad;margin-top:6px}" +
    "@media (max-width:480px){.panel{right:0;bottom:0;width:100vw;max-width:100vw;height:100%;max-height:100%;border-radius:0}.open .launch{display:none}}" +
    "@media (prefers-reduced-motion:reduce){.panel,.launch{transition:none}.caret::after,.dots i,.steps li.now::before{animation:none}}";

  var ICON_CHAT = '<svg class="c" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  var ICON_X = '<svg class="x" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';
  var wrap = document.createElement("div");
  wrap.className = "wrap";
  wrap.innerHTML =
    "<style>" + css + "</style>" +
    '<div class="panel" role="dialog" aria-label="' + esc(CONF.title || "Tư vấn") + '">' +
    '<div class="head"><div class="av" aria-hidden="true"></div><div class="who"><b></b><span>Đang trực tuyến · thường trả lời ngay</span></div>' +
    '<button class="close" type="button" aria-label="Đóng">' + ICON_X.replace('class="x" ', "") + "</button></div>" +
    '<div class="log" role="log" aria-live="polite"></div>' +
    '<div class="foot"><div class="box"><textarea rows="1" maxlength="1000" placeholder="Nhập câu hỏi…" aria-label="Câu hỏi"></textarea>' +
    '<button class="send" type="button" aria-label="Gửi" disabled><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg></button></div>' +
    '<div class="note">Trả lời dựa trên tài liệu của ' + esc(NAME) + "</div></div></div>" +
    '<button class="launch" type="button" aria-label="' + esc(CONF.title || "Tư vấn") + '">' + ICON_CHAT + ICON_X + "</button>";
  root.appendChild(wrap);
  var $ = function (s) { return wrap.querySelector(s); };
  var logEl = $(".log"), input = $("textarea"), send = $(".send");
  $(".av").textContent = NAME.trim().charAt(0).toUpperCase() || "T";
  $(".who b").textContent = CONF.title || NAME;

  function scroll() { logEl.scrollTop = logEl.scrollHeight; }
  function row(role) {
    var r = document.createElement("div");
    r.className = "row " + (role === "user" ? "user" : "bot");
    if (role !== "user") { var m = document.createElement("div"); m.className = "mini"; m.textContent = $(".av").textContent; r.appendChild(m); }
    var b = document.createElement("div");
    b.className = "bubble";
    r.appendChild(b);
    logEl.appendChild(r);
    return b;
  }
  function add(role, text) {
    var b = row(role);
    if (role === "user") b.textContent = text; else b.innerHTML = md(text);
    scroll();
    return b;
  }
  function stepsBox(steps, live) {
    var box = document.createElement("div");
    box.className = "steps";
    var searches = steps.filter(function (s) { return s.step === "search"; }).length;
    var found = steps.filter(function (s) { return s.step === "found"; })[0];
    var btn = document.createElement("button");
    btn.type = "button";
    var list = document.createElement("ul");
    list.hidden = !live;
    function paint() {
      btn.textContent = live ? "Đang tra tài liệu…" : ("Đã tra " + searches + " lần" + (found && found.sources && found.sources.length ? " · " + found.sources.length + " tài liệu" : "") + (list.hidden ? " ▾" : " ▴"));
      list.innerHTML = "";
      steps.forEach(function (s, i) {
        var li = document.createElement("li");
        li.textContent = s.text + (s.sources && s.sources.length ? ": " + s.sources.join(", ") : "");
        if (live && i === steps.length - 1) li.className = "now";
        list.appendChild(li);
      });
    }
    btn.onclick = function () { list.hidden = !list.hidden; paint(); };
    box.appendChild(btn);
    box.appendChild(list);
    paint();
    return { el: box, update: function (st, isLive) { steps = st; live = isLive; if (!isLive) list.hidden = true; searches = steps.filter(function (s) { return s.step === "search"; }).length; found = steps.filter(function (s) { return s.step === "found"; })[0]; paint(); } };
  }

  add("bot", CONF.greeting || "Xin chào! Em có thể giúp gì cho anh/chị ạ?");
  (state.log || []).forEach(function (m) { add(m.r, m.t); });

  var busy = false;
  function toggle(open) {
    var o = open == null ? !wrap.classList.contains("open") : open;
    wrap.classList.toggle("open", o);
    if (o) { setTimeout(function () { input.focus(); }, 50); scroll(); }
  }
  $(".launch").onclick = function () { toggle(); };
  $(".close").onclick = function () { toggle(false); };
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && wrap.classList.contains("open")) toggle(false); });

  function resize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 120) + "px"; send.disabled = busy || !input.value.trim(); }
  input.addEventListener("input", resize);
  input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
  send.onclick = submit;

  function remember(role, text) { state.log.push({ r: role, t: text }); state.log = state.log.slice(-60); save(); }

  function submit() {
    var text = input.value.trim();
    if (!text || busy) return;
    busy = true; input.value = ""; resize();
    add("user", text); remember("user", text);

    var steps = [], sb = stepsBox(steps, true);
    logEl.appendChild(sb.el);
    var bubble = row("bot");
    bubble.innerHTML = '<span class="dots"><i></i><i></i><i></i></span>';
    scroll();
    var reply = "", started = false;

    function finish(finalText) {
      reply = finalText != null ? finalText : reply;
      bubble.classList.remove("caret");
      bubble.innerHTML = md(reply || "Xin lỗi, em chưa trả lời được. Anh/chị thử lại giúp em ạ.");
      sb.update(steps, false);
      if (!steps.length) sb.el.remove();
      if (reply) remember("bot", reply);
      busy = false; resize(); scroll();
    }
    function handle(ev) {
      if (ev.type === "status") { steps.push(ev); sb.update(steps, true); scroll(); }
      else if (ev.type === "delta") {
        if (!started) { started = true; sb.update(steps, false); bubble.classList.add("caret"); }
        reply += ev.text; bubble.innerHTML = md(reply); scroll();
      } else if (ev.type === "replace") { reply = ev.text; bubble.innerHTML = md(reply); }
    }

    fetch(API + "/stream", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vid: state.vid, text: text, page: location.href }) })
      .then(function (r) {
        if (r.status === 429) return finish("Anh/chị gửi hơi nhanh, vui lòng thử lại sau ít phút ạ.");
        if (!r.ok || !r.body) return finish("Xin lỗi, hệ thống đang bận. Anh/chị thử lại giúp em ạ.");
        var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
        function pump() {
          return reader.read().then(function (res) {
            if (res.done) return finish();
            buf += dec.decode(res.value, { stream: true });
            var parts = buf.split("\n\n");
            buf = parts.pop();
            parts.forEach(function (p) {
              var line = p.split("\n").filter(function (l) { return l.indexOf("data:") === 0; }).map(function (l) { return l.slice(5).trim(); }).join("");
              if (!line) return;
              try { handle(JSON.parse(line)); } catch (e) {}
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function () { finish(reply || "Không kết nối được. Anh/chị kiểm tra mạng giúp em ạ."); });
  }
})();
