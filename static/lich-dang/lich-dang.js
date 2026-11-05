/* Lich dang (openwebui-custom): calendar of WordPress posts. Plain JS, no build step. Backend: /api/v1/cqf/lich.
   Opened by loader.js inside Open WebUI (?embed=1, next to the sidebar). Times come from the API in UTC and are shown
   in the chosen zone. */
(function () {
  "use strict";

  var API = "/api/v1/cqf/lich";
  var PARAMS = new URLSearchParams(location.search);
  var EMBED = PARAMS.has("embed") && window.parent !== window;
  document.documentElement.classList.toggle("embed", EMBED);
  var HOUR_PX = 48;
  var EVENT_MINUTES = 50;
  var DAY_SHORT = { 1: "Thứ 2", 2: "Thứ 3", 3: "Thứ 4", 4: "Thứ 5", 5: "Thứ 6", 6: "Thứ 7", 7: "CN" };
  var DAY_TINY = { 1: "T2", 2: "T3", 3: "T4", 4: "T5", 5: "T6", 6: "T7", 7: "CN" };
  var STATE_ICON = { scheduled: "clock", sending: "send", sent: "circle-check", failed: "triangle-alert", unscheduled: "file-text" };
  var COMMON_ZONES = ["Asia/Ho_Chi_Minh", "Asia/Bangkok", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney",
    "Europe/London", "Europe/Paris", "America/New_York", "America/Los_Angeles", "UTC"];

  var S = {
    me: null, settings: null, sites: [], posts: [], zones: null,
    view: store("view") || "week", tz: null, anchor: null,
    stateFilter: store("state") || "all", siteFilter: "all",
    covers: {}, sheet: null, polling: null, drag: null
  };

  // ---------- small helpers ----------
  function store(k, v) {
    try {
      if (v === undefined) return localStorage.getItem("lich." + k);
      localStorage.setItem("lich." + k, v);
    } catch (e) { return null; }
  }
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function icon(name) {
    var inner = (window.LICH_ICONS || {})[name] || "";
    return '<svg class="lucide" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + "</svg>";
  }
  function icons() {}
  function tellParent(msg) { if (EMBED) window.parent.postMessage(msg, location.origin); }
  function setLink(postId) {
    // The address bar of Open WebUI follows the open post, so the link can be shared.
    tellParent({ type: "cqf-hash", hash: "lich-dang" + (postId ? "/post=" + postId : "") });
    if (!EMBED) history.replaceState(null, "", postId ? "#post=" + postId : location.pathname + location.search);
  }
  function $(sel, el) { return (el || document).querySelector(sel); }
  function $$(sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); }
  function toast(msg, err) {
    var t = document.createElement("div");
    t.className = "toast" + (err ? " err" : "");
    t.textContent = msg;
    $("#toasts").appendChild(t);
    setTimeout(function () { t.remove(); }, err ? 7000 : 3200);
  }
  function token() { try { return localStorage.getItem("token"); } catch (e) { return null; } }

  function api(path, opts) {
    opts = opts || {};
    var headers = { Authorization: "Bearer " + token() };
    var body = opts.body;
    if (body && !(body instanceof FormData)) { headers["Content-Type"] = "application/json"; body = JSON.stringify(body); }
    return fetch(API + path, { method: opts.method || "GET", headers: headers, body: body }).then(function (r) {
      if (r.status === 401) { showLogin(); throw new Error("Phiên đăng nhập Open WebUI đã hết."); }
      var type = r.headers.get("content-type") || "";
      if (!r.ok) {
        return (type.indexOf("json") >= 0 ? r.json() : r.text()).then(function (d) {
          var detail = d && d.detail;
          if (Array.isArray(detail)) detail = detail.map(function (x) { return x.msg; }).join("; ");
          throw new Error(detail || ("Lỗi " + r.status));
        });
      }
      if (opts.blob) return r.blob();
      return type.indexOf("json") >= 0 ? r.json() : r.text();
    });
  }

  // ---------- time zones ----------
  var fmtCache = {};
  var WD = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 };
  function partsOf(ms, tz) {
    var f = fmtCache[tz] || (fmtCache[tz] = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", weekday: "short"
    }));
    var o = {};
    f.formatToParts(new Date(ms)).forEach(function (p) { o[p.type] = p.value; });
    return { y: +o.year, m: +o.month, d: +o.day, h: (+o.hour) % 24, mi: +o.minute, s: +o.second, wd: WD[o.weekday] };
  }
  function offsetMs(ms, tz) {
    var p = partsOf(ms, tz);
    return Date.UTC(p.y, p.m - 1, p.d, p.h, p.mi, p.s) - Math.floor(ms / 1000) * 1000;
  }
  function zoned(y, m, d, h, mi, tz) {
    var guess = Date.UTC(y, m - 1, d, h, mi);
    var t = guess - offsetMs(guess, tz);
    return guess - offsetMs(t, tz);
  }
  function addDays(ymd, n) {
    var t = new Date(Date.UTC(ymd.y, ymd.m - 1, ymd.d + n));
    return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate(), wd: ((t.getUTCDay() + 6) % 7) + 1 };
  }
  function dayKey(p) { return p.y + "-" + pad(p.m) + "-" + pad(p.d); }
  function gmt(tz, ms) {
    var off = Math.round(offsetMs(ms || Date.now(), tz) / 60000);
    var sign = off >= 0 ? "+" : "-";
    off = Math.abs(off);
    return "GMT" + sign + Math.floor(off / 60) + (off % 60 ? ":" + pad(off % 60) : "");
  }
  function ms(iso) { return iso ? Date.parse(iso) : null; }
  function hm(msv, tz) { var p = partsOf(msv, tz); return pad(p.h) + ":" + pad(p.mi); }
  function longTime(msv, tz) {
    var p = partsOf(msv, tz);
    return "Lúc " + pad(p.h) + ":" + pad(p.mi) + " " + DAY_SHORT[p.wd] + ", " + p.d + " tháng " + p.m;
  }
  function shortDate(msv, tz) { var p = partsOf(msv, tz); return pad(p.h) + ":" + pad(p.mi) + " " + pad(p.d) + "/" + pad(p.m); }
  function rel(msv) {
    var diff = Math.round((msv - Date.now()) / 60000);
    var a = Math.abs(diff);
    var text = a < 1 ? "vài giây" : a < 60 ? a + " phút" : a < 60 * 48 ? Math.round(a / 60) + " giờ" : Math.round(a / 1440) + " ngày";
    return diff >= 0 ? "sau " + text + " nữa" : text + " trước";
  }
  function localInputValue(msv, tz) {
    var p = partsOf(msv, tz);
    return p.y + "-" + pad(p.m) + "-" + pad(p.d) + "T" + pad(p.h) + ":" + pad(p.mi);
  }
  function inputToMs(value, tz) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value || "");
    if (!m) return null;
    return zoned(+m[1], +m[2], +m[3], +m[4], +m[5], tz);
  }

  // ---------- data ----------
  function siteOf(id) { return S.sites.find(function (s) { return s.id === id; }); }
  function today() { return partsOf(Date.now(), S.tz); }
  function viewRange() {
    var a = S.anchor;
    if (S.view === "week") {
      var start = addDays(a, -(a.wd - 1));
      return { start: start, days: 7 };
    }
    var first = { y: a.y, m: a.m, d: 1 };
    first = addDays(first, 0);
    if (S.view === "list") {
      var next = addDays({ y: a.m === 12 ? a.y + 1 : a.y, m: a.m === 12 ? 1 : a.m + 1, d: 1 }, 0);
      return { start: first, days: Math.round((Date.UTC(next.y, next.m - 1, 1) - Date.UTC(first.y, first.m - 1, 1)) / 864e5) };
    }
    return { start: addDays(first, -(first.wd - 1)), days: 42 };
  }
  function rangeMs() {
    var r = viewRange();
    var end = addDays(r.start, r.days);
    return [zoned(r.start.y, r.start.m, r.start.d, 0, 0, S.tz), zoned(end.y, end.m, end.d, 0, 0, S.tz)];
  }
  function loadMe() {
    return api("/me").then(function (me) {
      S.me = me; S.settings = me.settings; S.sites = me.sites;
      if (!S.tz) S.tz = store("tz") || me.settings.timezone;
      if (!S.anchor) S.anchor = today();
    });
  }
  function loadPosts() {
    var r = rangeMs();
    return api("/posts?start=" + new Date(r[0]).toISOString() + "&end=" + new Date(r[1]).toISOString()).then(function (posts) {
      S.posts = posts;
    });
  }
  function refresh() {
    return Promise.all([loadMe(), loadPosts()]).then(render).catch(function (e) { toast(e.message, true); });
  }
  function matches(p) {
    if (S.siteFilter !== "all" && p.site_id !== S.siteFilter) return false;
    if (S.stateFilter === "upcoming") return p.state === "scheduled" || p.state === "sending";
    if (S.stateFilter === "sent") return p.state === "sent";
    if (S.stateFilter === "failed") return p.state === "failed" || (p.state === "sending" && p.error);
    return true;
  }
  function placed() { return S.posts.filter(function (p) { return p.publish_at && p.state !== "unscheduled" && matches(p); }); }
  function waiting() { return S.posts.filter(function (p) { return p.state === "unscheduled"; }); }

  function coverUrl(p) {
    if (!p.has_cover) return Promise.resolve(null);
    var k = p.id + "@" + p.updated_at;
    if (S.covers[k]) return Promise.resolve(S.covers[k]);
    return api("/posts/" + p.id + "/cover", { blob: true }).then(function (b) {
      S.covers[k] = URL.createObjectURL(b);
      return S.covers[k];
    }).catch(function () { return null; });
  }
  function fillCovers(root) {
    $$("img[data-cover]", root).forEach(function (img) {
      var p = S.posts.find(function (x) { return x.id === img.dataset.cover; }) || (S.sheet && S.sheet.post);
      if (p) coverUrl(p).then(function (u) { if (u) img.src = u; else img.style.visibility = "hidden"; });
    });
  }
  function wpMark(size) {
    return '<span class="mark ' + (size || "xs") + '"><img src="/static/lich-dang/wordpress.svg" alt="WordPress"></span>';
  }
  function isZalo(x) { return !!x && (x.kind === "zalo_oa" || x.channel === "zalo_oa"); }
  function markFor(site, size) {
    if (!isZalo(site)) return wpMark(size);
    return '<span class="mark ' + (size || "xs") + '"><img src="/static/lich-dang/zalo.svg" alt="Zalo"></span>';
  }
  function siteLabel(s) { return isZalo(s) ? s.name : host(s.url); }
  function modeLabels(kind) { return (S.me.modes_by_kind || {})[kind || "wordpress"] || S.me.modes; }
  function host(url) { return String(url || "").replace(/^https?:\/\//, "").replace(/\/.*$/, ""); }

  function stateBadge(p) {
    var label = p.state_label;
    if (p.state === "sent" && p.wp_status && p.wp_status !== "publish") label = "Đã vào nháp WordPress";
    if (p.state === "sending" && p.next_try_at) label = "Chờ thử lại";
    return '<span class="badge state-' + p.state + '">' + icon(STATE_ICON[p.state]) + esc(label) + "</span>";
  }

  // ---------- render: shell ----------
  function render() {
    var root = $("#root");
    var r = viewRange();
    var t = today();
    var label;
    if (S.view === "week") {
      var end = addDays(r.start, 6);
      label = r.start.m === end.m
        ? r.start.d + " – " + end.d + " thg " + end.m + ", " + end.y
        : r.start.d + " thg " + r.start.m + " – " + end.d + " thg " + end.m + ", " + end.y;
    } else {
      label = "Tháng " + S.anchor.m + ", " + S.anchor.y;
    }
    var broken = S.sites.filter(function (s) { return s.check_ok === false; });
    var counts = {};
    S.posts.forEach(function (p) { counts[p.site_id] = (counts[p.site_id] || 0) + (p.state === "unscheduled" ? 0 : 1); });
    var slotsText = (S.settings.slots || []).map(function (s) {
      return s.days.map(function (d) { return DAY_TINY[d]; }).join(", ") + " " + s.time;
    }).join(" · ") || "chưa đặt";

    root.innerHTML =
      '<header class="topbar">' +
        '<nav class="crumbs">' + (EMBED ? '<button class="btn icon ghost sb-toggle" data-act="sidebar" title="Mở sidebar">' + icon("panel-left") + "</button>" : '<a href="/#lich-dang" title="Về Open WebUI">' + icon("arrow-left") + "<span>Open WebUI</span></a><span>/</span>") + "<strong>Lịch đăng</strong></nav>" +
        '<div class="spacer"></div>' +
        '<button class="btn ghost" data-act="rules" title="Quy tắc">' + icon("book-open") + '<span class="label">Quy tắc</span></button>' +
        '<button class="btn" data-act="settings" title="Cài đặt">' + icon("settings") + '<span class="label">Cài đặt</span></button>' +
        '<button class="btn primary" data-act="new">' + icon("plus") + 'Viết bài <kbd>N</kbd></button>' +
      "</header>" +
      '<main class="main">' +
        '<div class="lede"><p>Bài WordPress và Zalo OA theo ngày. Bấm ô trống để hẹn bài, kéo bài đã hẹn để đổi giờ. Bài được giữ ở đây, đúng giờ mới gửi đi.</p></div>' +
        (broken.length ? '<div class="banner slim">' + icon("shield-alert") + "<p><strong>" +
          (broken.length === 1 ? esc(siteLabel(broken[0])) + " chưa kết nối được" : broken.length + " nơi đăng chưa kết nối được") +
          '</strong> <span class="why" title="' + esc(broken.map(function (s) { return s.name + ": " + (s.check_error || ""); }).join("\n")) + '">' +
          esc(broken.length === 1 ? broken[0].check_error || "" : broken.map(siteLabel).join(", ")) + "</span></p>" +
          '<button class="btn sm" data-act="settings" data-tab="sites">Xem và kiểm tra lại</button></div>' : "") +
        (S.sites.length ? "" : '<div class="banner">' + icon("plug") + "<p><strong>Chưa có nơi đăng nào.</strong> Thêm site WordPress (application password) hoặc Zalo OA để bài đi được.</p>" +
          '<button class="btn sm" data-act="settings" data-tab="sites">Kết nối</button></div>') +
        '<div class="toolbar">' +
          '<button class="btn" data-act="today">Hôm nay</button>' +
          '<button class="btn icon ghost" data-act="prev" title="Trước">' + icon("chevron-left") + "</button>" +
          '<button class="btn icon ghost" data-act="next" title="Sau">' + icon("chevron-right") + "</button>" +
          '<span class="range">' + esc(label) + "</span>" +
          '<div class="spacer"></div>' +
          '<label class="tz row" title="Múi giờ đang xem">' + icon("globe") + '<select data-act="tz">' + zoneOptions(S.tz) + "</select></label>" +
          '<div class="seg">' +
            ["month:calendar:Tháng", "week:calendar-range:Tuần", "list:list:Danh sách"].map(function (v) {
              var x = v.split(":");
              return '<button class="' + (S.view === x[0] ? "on" : "") + '" data-act="view" data-view="' + x[0] + '">' + icon(x[1]) + x[2] + "</button>";
            }).join("") +
          "</div>" +
        "</div>" +
        '<div class="toolbar">' +
          '<button class="chip gold" data-act="settings" data-tab="slots" title="Khung giờ đăng">' + icon("star") + "Khung giờ đăng: " + esc(slotsText) + "</button>" +
          (S.tz !== S.settings.timezone ? '<button class="chip" data-act="tz-default">' + icon("pin") + "Đặt " + esc(S.tz) + " làm mặc định</button>" : "") +
          '<div class="spacer"></div>' +
          (S.sites.length > 1 ? '<button class="chip ' + (S.siteFilter === "all" ? "on" : "") + '" data-act="site" data-id="all">Tất cả nơi đăng</button>' +
            S.sites.map(function (s) {
              return '<button class="chip ' + (S.siteFilter === s.id ? "on" : "") + '" data-act="site" data-id="' + s.id + '" title="' + esc(s.name) + '">' + markFor(s) + esc(siteLabel(s)) +
                ' <span class="count">' + (counts[s.id] || 0) + "</span></button>";
            }).join("") : "") +
          '<div class="seg">' +
            ["all:Tất cả", "upcoming:Sắp đăng", "sent:Đã đăng", "failed:Lỗi"].map(function (v) {
              var x = v.split(":");
              return '<button class="' + (S.stateFilter === x[0] ? "on" : "") + '" data-act="state" data-state="' + x[0] + '">' + x[1] + "</button>";
            }).join("") +
          "</div>" +
        "</div>" +
        '<div class="body"><section class="cal" id="cal"></section>' + sideHtml() + "</div>" +
      "</main>";

    var cal = $("#cal");
    if (S.view === "week") renderWeek(cal, r, t);
    else if (S.view === "month") renderMonth(cal, r, t);
    else renderList(cal);
    fillCovers(root);
    icons();
  }

  function zoneOptions(selected) {
    var list = (S.zones || COMMON_ZONES).slice();
    if (list.indexOf(selected) < 0) list.unshift(selected);
    if (S.settings && list.indexOf(S.settings.timezone) < 0) list.unshift(S.settings.timezone);
    return list.map(function (z) {
      return '<option value="' + esc(z) + '"' + (z === selected ? " selected" : "") + ">" + esc(z) + " (" + gmt(z) + ")</option>";
    }).join("");
  }

  function sideHtml() {
    var list = waiting();
    return '<aside class="side">' +
      '<div class="side-head"><h2>Chưa lên lịch <span class="hint">' + list.length + "</span></h2>" +
      '<p class="hint">Kéo vào lịch để hẹn giờ, hoặc bấm để chọn giờ.</p></div>' +
      '<div class="side-list" id="waiting">' +
      (list.length ? list.map(function (p) {
        return '<div class="card" draggable="true" data-post="' + p.id + '">' +
          '<div class="t">' + esc(p.title) + "</div>" +
          '<div class="sub">' + (p.source === "agent" ? icon("bot") + "Agent" : icon("user") + "Bạn") + " · " + p.words + " chữ" +
          (p.has_cover ? " · " + icon("image") : "") + "</div></div>";
      }).join("") : '<p class="empty">Mọi bài đều đã có lịch.<br>Nhờ Agent viết bài trong chat, hoặc bấm Viết bài.</p>') +
      "</div>" +
      '<div class="side-foot"><button class="btn" data-act="new">' + icon("pen-line") + "Viết bài</button>" +
      '<a class="btn" href="/" target="_top">' + icon("message-square") + "Nhờ Agent viết</a></div>" +
      "</aside>";
  }

  // ---------- week ----------
  function slotMoments(startMs, endMs) {
    var out = [];
    var tz = S.settings.timezone;
    var first = partsOf(startMs - 864e5, tz);
    for (var i = 0; i < 10; i++) {
      var day = addDays(first, i);
      (S.settings.slots || []).forEach(function (s) {
        if (s.days.indexOf(day.wd) < 0) return;
        var hmv = s.time.split(":");
        var t = zoned(day.y, day.m, day.d, +hmv[0], +hmv[1], tz);
        if (t >= startMs && t < endMs) out.push(t);
      });
    }
    return out;
  }

  function lanes(items) {
    // Side by side when two posts overlap in time.
    items.sort(function (a, b) { return a.top - b.top; });
    var groups = [], cur = null;
    items.forEach(function (it) {
      if (!cur || it.top >= cur.end) { cur = { items: [], end: 0 }; groups.push(cur); }
      cur.items.push(it);
      cur.end = Math.max(cur.end, it.top + it.h);
    });
    groups.forEach(function (g) {
      var laneEnds = [];
      g.items.forEach(function (it) {
        var lane = laneEnds.findIndex(function (e) { return e <= it.top; });
        if (lane < 0) { lane = laneEnds.length; laneEnds.push(0); }
        laneEnds[lane] = it.top + it.h;
        it.lane = lane;
      });
      g.items.forEach(function (it) { it.count = laneEnds.length; });
    });
  }

  function renderWeek(cal, r, t) {
    var days = [];
    for (var i = 0; i < 7; i++) days.push(addDays(r.start, i));
    var todayKey = dayKey(t);
    var nowMs = Date.now();
    var head = '<div class="week-head"><div></div>' + days.map(function (d) {
      return '<div class="day' + (dayKey(d) === todayKey ? " today" : "") + '">' + DAY_SHORT[d.wd] + '<br><span class="num">' + d.d + "</span></div>";
    }).join("") + "</div>";
    var hours = '<div class="hours">';
    for (var h = 0; h < 24; h++) hours += "<div>" + (h ? "<span>" + h + ":00</span>" : "") + "</div>";
    hours += "</div>";

    var byDay = {};
    placed().forEach(function (p) {
      var at = ms(p.publish_at);
      var pp = partsOf(at, S.tz);
      var k = dayKey(pp);
      (byDay[k] = byDay[k] || []).push({ p: p, top: (pp.h * 60 + pp.mi) / 60 * HOUR_PX, h: EVENT_MINUTES / 60 * HOUR_PX });
    });
    var cols = days.map(function (d) {
      var k = dayKey(d);
      var dayStart = zoned(d.y, d.m, d.d, 0, 0, S.tz);
      var dayEnd = zoned(addDays(d, 1).y, addDays(d, 1).m, addDays(d, 1).d, 0, 0, S.tz);
      var past = dayEnd <= nowMs;
      var cells = "";
      for (var c = 0; c < 48; c++) cells += '<div class="cell" data-min="' + c * 30 + '"></div>';
      var bands = slotMoments(dayStart, dayEnd).map(function (sm) {
        var sp = partsOf(sm, S.tz);
        return '<div class="slot-band" style="top:' + ((sp.h * 60 + sp.mi) / 60 * HOUR_PX) + 'px">' + icon("star") + "Khung giờ " + pad(sp.h) + ":" + pad(sp.mi) + "</div>";
      }).join("");
      var items = byDay[k] || [];
      lanes(items);
      var evs = items.map(function (it) {
        var p = it.p;
        var w = 100 / it.count;
        var movable = p.state === "scheduled" || p.state === "failed";
        return '<div class="ev state-' + p.state + (S.sheet && S.sheet.post && S.sheet.post.id === p.id ? " sel" : "") + '" data-post="' + p.id + '"' +
          (movable ? ' draggable="true"' : "") +
          ' style="top:' + it.top + "px;height:" + Math.max(it.h, 40) + "px;left:calc(" + (it.lane * w) + "% + 3px);width:calc(" + w + '% - 6px)" title="' + esc(p.title) + '">' +
          (p.has_cover ? '<img class="thumb" data-cover="' + p.id + '" alt="">' : "") +
          '<div class="txt"><span class="meta">' + icon(STATE_ICON[p.state]) + hm(ms(p.publish_at), S.tz) +
          (p.mode === "draft" ? " · nháp" : "") + '</span><span class="title">' + esc(p.title) + "</span></div></div>";
      }).join("");
      var nowLine = "";
      if (nowMs >= dayStart && nowMs < dayEnd) {
        var np = partsOf(nowMs, S.tz);
        nowLine = '<div class="now-line" style="top:' + ((np.h * 60 + np.mi) / 60 * HOUR_PX) + 'px"></div>';
      }
      return '<div class="col' + (past ? " past" : "") + '" data-day="' + k + '">' + cells + bands + evs + nowLine + "</div>";
    }).join("");

    var np2 = partsOf(nowMs, S.tz);
    var inWeek = days.some(function (d) { return dayKey(d) === todayKey; });
    cal.innerHTML = head + '<div class="week-scroll" id="wscroll"><div class="week-grid">' + hours + cols +
      (inWeek ? '<div class="now-tag" style="top:' + ((np2.h * 60 + np2.mi) / 60 * HOUR_PX) + 'px">' + pad(np2.h) + ":" + pad(np2.mi) + "</div>" : "") +
      "</div></div>";
    var scroller = $("#wscroll");
    var keep = S.weekScroll;
    scroller.scrollTop = keep != null ? keep : Math.max(0, (inWeek ? np2.h - 1 : 7) * HOUR_PX);
    scroller.addEventListener("scroll", function () { S.weekScroll = scroller.scrollTop; });
  }

  // ---------- month ----------
  function renderMonth(cal, r, t) {
    var byDay = {};
    placed().forEach(function (p) {
      var k = dayKey(partsOf(ms(p.publish_at), S.tz));
      (byDay[k] = byDay[k] || []).push(p);
    });
    var html = '<div class="month-head">' + [1, 2, 3, 4, 5, 6, 7].map(function (d) { return '<div class="dow">' + DAY_SHORT[d] + "</div>"; }).join("") +
      '</div><div class="month">';
    for (var i = 0; i < 42; i++) {
      var d = addDays(r.start, i);
      var k = dayKey(d);
      var list = (byDay[k] || []).sort(function (a, b) { return ms(a.publish_at) - ms(b.publish_at); });
      html += '<div class="mday' + (d.m !== S.anchor.m ? " other" : "") + (k === dayKey(t) ? " today" : "") + '" data-day="' + k + '">' +
        '<span class="n">' + d.d + "</span>" +
        list.slice(0, 3).map(function (p) {
          var movable = p.state === "scheduled" || p.state === "failed";
          return '<div class="mchip state-' + p.state + '" data-post="' + p.id + '"' + (movable ? ' draggable="true"' : "") + ">" +
            "<b>" + hm(ms(p.publish_at), S.tz) + "</b><span>" + esc(p.title) + "</span></div>";
        }).join("") +
        (list.length > 3 ? '<span class="mmore">+' + (list.length - 3) + " bài nữa</span>" : "") +
        "</div>";
    }
    cal.innerHTML = html + "</div>";
  }

  // ---------- list ----------
  function renderList(cal) {
    var items = placed().sort(function (a, b) { return ms(a.publish_at) - ms(b.publish_at); });
    if (!items.length) {
      cal.innerHTML = '<div class="list"><p class="empty">Tháng này chưa có bài nào' + (S.stateFilter !== "all" ? " ở trạng thái này" : "") + ".</p></div>";
      return;
    }
    var html = '<div class="list">', last = "";
    items.forEach(function (p) {
      var at = ms(p.publish_at);
      var pp = partsOf(at, S.tz);
      var k = dayKey(pp);
      if (k !== last) { html += '<div class="lday">' + DAY_SHORT[pp.wd] + ", " + pp.d + "/" + pp.m + "/" + pp.y + "</div>"; last = k; }
      var site = siteOf(p.site_id);
      html += '<div class="lrow" data-post="' + p.id + '"><span class="time">' + hm(at, S.tz) + "</span>" +
        (p.has_cover ? '<img class="thumb" data-cover="' + p.id + '" alt="">' : '<span class="thumb"></span>') +
        '<div style="min-width:0"><div class="t">' + esc(p.title) + '</div><div class="sub">' +
        (site ? esc(site.name) + " · " : "") + esc(p.mode_label) + (p.error ? ' · <span class="error-text">' + esc(p.error) + "</span>" : "") + "</div></div>" +
        stateBadge(p) + "</div>";
    });
    cal.innerHTML = html + "</div>";
  }

  // ---------- scheduling actions ----------
  function schedule(postId, msv, mode) {
    return api("/posts/" + postId + "/schedule", { method: "POST", body: { publish_at: new Date(msv).toISOString(), mode: mode || undefined } })
      .then(function (p) {
        toast("Đã hẹn " + longTime(ms(p.publish_at), S.tz).toLowerCase() + " · " + p.mode_label);
        return refresh().then(function () { if (S.sheet && S.sheet.post && S.sheet.post.id === p.id) openPost(p.id); return p; });
      })
      .catch(function (e) { toast(e.message, true); refresh(); });
  }

  function quickPick(msv) {
    var list = waiting();
    closeLayer();
    var layer = $("#layer");
    layer.innerHTML = '<div class="overlay top" data-act="close"></div><div class="modal small" role="dialog">' +
      '<div class="modal-head"><h2>Hẹn bài vào ' + esc(longTime(msv, S.tz).toLowerCase()) + "</h2>" +
      '<button class="btn icon ghost" data-act="close">' + icon("x") + "</button></div>" +
      (list.length ? '<div class="pick">' + list.map(function (p) {
        return '<button data-act="pick" data-post="' + p.id + '" data-at="' + msv + '">' + icon("file-text") +
          '<span style="flex:1">' + esc(p.title) + '</span><span class="hint">' + p.words + " chữ</span></button>";
      }).join("") + "</div>" : '<p class="empty">Chưa có bài nào chờ lên lịch.</p>') +
      '<div class="sheet-foot"><button class="btn" data-act="new" data-at="' + msv + '">' + icon("pen-line") + "Viết bài mới cho giờ này</button></div></div>";
    icons();
  }

  // ---------- layer: sheets and modals ----------
  function closeLayer() {
    $("#layer").innerHTML = "";
    if (S.sheet) { var wasPost = S.sheet.kind === "post"; S.sheet = null; if (wasPost) setLink(null); }
    $$(".ev.sel").forEach(function (e) { e.classList.remove("sel"); });
  }
  function sheet(html, wide) {
    $("#layer").innerHTML = '<div class="overlay" data-act="close"></div><aside class="sheet' + (wide ? " wide" : "") + '" role="dialog">' + html + "</aside>";
    icons();
  }

  function openPost(id) {
    return api("/posts/" + id).then(function (p) {
      S.sheet = { kind: "post", post: p };
      setLink(id);
      renderPost(p);
      api("/slots/next?count=6").then(function (slots) {
        var box = $("#slotpick");
        if (!box) return;
        box.innerHTML = slots.length ? slots.map(function (s) {
          return '<button class="chip gold" data-act="slot" data-at="' + ms(s.at) + '">' + icon("star") + esc(shortDate(ms(s.at), S.tz)) + "</button>";
        }).join("") : '<span class="hint">Chưa có khung giờ trống. Đặt khung giờ trong Cài đặt.</span>';
        icons();
      });
    }).catch(function (e) { toast(e.message, true); closeLayer(); });
  }

  function zaloIssues(p) {
    var out = [];
    if (p.title.length > 150) out.push("tiêu đề " + p.title.length + "/150 ký tự");
    if ((p.excerpt || "").length > 300) out.push("mô tả ngắn " + p.excerpt.length + "/300 ký tự");
    if (!p.has_cover) out.push("chưa có ảnh bìa");
    return out;
  }

  function renderPost(p) {
    var tz = S.tz;
    var at = ms(p.publish_at);
    var site = siteOf(p.site_id);
    var zalo = isZalo(p);
    var editable = p.state === "unscheduled" || p.state === "scheduled" || p.state === "failed" || (p.state === "sending" && p.next_try_at);
    var earliest = Date.now() + (S.me.min_lead_seconds || 120) * 1000;
    var note = "";
    if (p.state === "scheduled") {
      note = "Bài được giữ ở đây và gửi lên " + esc(site ? site.name : "WordPress") + " " + esc(longTime(at, tz).toLowerCase()) +
        " (" + esc(p.mode_label.toLowerCase()) + "). Sửa bài trước lúc đó thì bài đi nội dung mới.";
    } else if (p.state === "sending" && p.next_try_at) {
      note = "Gửi lần " + p.attempts + " chưa được, máy chủ sẽ thử lại " + esc(longTime(ms(p.next_try_at), tz).toLowerCase()) + ".";
    } else if (p.state === "sending") {
      note = "Đang gửi lên WordPress…";
    } else if (p.state === "sent" && p.wp_status === "publish") {
      note = "Đã đăng " + esc(longTime(ms(p.sent_at), tz).toLowerCase()) + ". Muốn sửa thì mở bài trong WordPress.";
    } else if (p.state === "sent") {
      note = "Đã vào WordPress dạng nháp " + esc(longTime(ms(p.sent_at), tz).toLowerCase()) + ". Mở WordPress để xem lại và bấm Đăng.";
    } else if (p.state === "failed") {
      note = "Không gửi được sau " + p.attempts + " lần. Sửa nguyên nhân rồi bấm Thử lại, hoặc hẹn giờ khác.";
    } else {
      note = "Bài chưa có giờ đăng. Chọn giờ bên dưới, hoặc kéo bài vào lịch.";
    }

    var html =
      '<div class="sheet-head"><div style="flex:1;min-width:0"><h2>' + esc(p.title) + '</h2><div class="row">' + stateBadge(p) +
        (site ? '<span class="badge neutral">' + markFor(site) + esc(site.name) + "</span>" : '<span class="badge state-failed">Chưa chọn nơi đăng</span>') +
        '<span class="badge neutral">' + icon(p.mode === "publish" ? "globe" : "file-pen") + esc(p.mode_label) + "</span></div></div>" +
        '<button class="btn icon ghost" data-act="close" title="Đóng">' + icon("x") + "</button></div>" +
      '<div class="sheet-body">' +
        '<div class="sec">' +
          (p.has_cover ? '<img class="cover" data-cover="' + p.id + '" alt="' + esc(p.cover_alt) + '">' : '<div class="cover-empty">' + icon("image") + " Chưa có ảnh bìa</div>") +
          '<div class="row"><button class="btn" data-act="preview">' + icon("eye") + (zalo ? "Xem trước như trên Zalo" : "Xem trước như trên web") + "</button>" +
          (editable ? '<label class="btn">' + icon("image-up") + (p.has_cover ? "Đổi ảnh bìa" : "Thêm ảnh bìa") +
            '<input type="file" accept="image/jpeg,image/png,image/gif,image/webp" data-act="cover-file" hidden></label>' +
            (p.has_cover ? '<button class="btn ghost" data-act="cover-remove">Bỏ ảnh</button>' : "") +
            '<button class="btn ghost" data-act="edit">' + icon("pen-line") + "Sửa nội dung</button>" : "") +
          "</div>" +
        "</div>" +
        '<dl class="facts">' +
          "<dt>Thời điểm</dt><dd>" + (at ? esc(longTime(at, tz)) + "<small>" + esc(rel(at)) + " · " + esc(tz) + " " + gmt(tz, at) + "</small>" : "Chưa có") + "</dd>" +
          "<dt>Nơi đăng</dt><dd>" + (site ? esc(site.name) + "<small>" + esc(zalo ? "Zalo OA · " + (site.options.author || site.name) : site.url) + "</small>" : "Chưa có") + "</dd>" +
          "<dt>Chế độ</dt><dd>" + esc(p.mode_label) + "</dd>" +
          (p.wp_post_id ? "<dt>WordPress</dt><dd>Bài #" + p.wp_post_id + " · " + esc(p.wp_status === "publish" ? "đã đăng" : "nháp") + "</dd>" : "") +
          (zalo && p.ext_id ? "<dt>Zalo OA</dt><dd>Bài " + esc(p.ext_id) + " · " + esc(p.wp_status === "publish" ? "đang hiện" : "đang ẩn") + "</dd>" : "") +
          "<dt>Nguồn</dt><dd>" + (p.source === "agent" ? "Agent viết" : "Viết trên trang này") + "</dd>" +
          "<dt>Độ dài</dt><dd>" + p.words + " chữ</dd>" +
          (!zalo && p.categories.length ? "<dt>Chuyên mục</dt><dd>" + esc(p.categories.join(", ")) + "</dd>" : "") +
          (!zalo && p.tags.length ? "<dt>Thẻ</dt><dd>" + esc(p.tags.join(", ")) + "</dd>" : "") +
          (zalo ? "<dt>Mô tả ngắn</dt><dd>" + esc(p.excerpt || "Chưa có") + "<small>" + (p.excerpt || "").length + "/300 ký tự</small></dd>"
            : "<dt>Đường dẫn</dt><dd>/" + esc(p.slug) + "/</dd>") +
        "</dl>" +
        '<div class="sec"><p class="hint" style="font-size:13.5px">' + note + "</p>" +
          (zalo && zaloIssues(p).length && editable ? '<p class="error-text">' + icon("triangle-alert") + " Zalo chưa nhận bài này: " + esc(zaloIssues(p).join("; ")) + ".</p>" : "") +
          (p.error ? '<p class="error-text">' + icon("triangle-alert") + " " + esc(p.error) + "</p>" : "") +
        "</div>" +
        (editable ?
          '<div class="sec"><h3>' + (p.state === "unscheduled" ? "Chọn giờ đăng" : "Đổi giờ") + "</h3>" +
            '<div class="row"><input class="input" style="flex:1;min-width:190px" type="datetime-local" id="when" value="' +
              esc(localInputValue(at && at > earliest ? at : (Math.ceil(earliest / 300000) * 300000), tz)) + '">' +
            '<button class="btn primary" data-act="save-time">' + (p.state === "unscheduled" ? "Lên lịch" : "Lưu giờ mới") + "</button></div>" +
            '<p class="hint">Giờ theo ' + esc(tz) + " (" + gmt(tz) + "). Sớm nhất " + esc(hm(earliest, tz)) + " hôm nay (cách bây giờ 2 phút).</p>" +
            '<div class="slot-pick" id="slotpick"><span class="hint">Đang tìm khung giờ trống…</span></div>' +
          "</div>" +
          '<div class="sec"><h3>Chế độ đăng</h3><div class="seg">' +
            '<button class="' + (p.mode === "publish" ? "on" : "") + '" data-act="mode" data-mode="publish">' + icon("globe") + esc(modeLabels(p.channel).publish) + "</button>" +
            '<button class="' + (p.mode === "draft" ? "on" : "") + '" data-act="mode" data-mode="draft">' + icon("file-pen") + esc(modeLabels(p.channel).draft) + "</button></div>" +
            '<p class="hint">' + esc(ruleText(zalo ? "zalo" : "mode")) + "</p>" +
            (S.sites.length > 1 && !p.wp_post_id && !p.ext_id ? '<label class="field"><span>Nơi đăng</span><select class="select" data-act="post-site">' +
              S.sites.map(function (s) { return '<option value="' + s.id + '"' + (s.id === p.site_id ? " selected" : "") + ">" + esc(s.kind_label + " · " + s.name) + "</option>"; }).join("") +
              "</select></label>" : "") +
          "</div>" : "") +
        '<div class="sec"><h3>Lịch sử</h3><ul class="history">' + (p.history || []).map(function (h) {
          return "<li><time>" + esc(shortDate(ms(h.at), tz)) + "</time><span><b>" + esc(h.actor) + ":</b> " + esc(h.text) + "</span></li>";
        }).join("") + "</ul></div>" +
      "</div>" +
      '<div class="sheet-foot">' +
        (p.state === "failed" ? '<button class="btn primary" data-act="retry">' + icon("rotate-cw") + "Thử lại (2 phút nữa)</button>" : "") +
        ((p.state === "scheduled" || p.state === "failed" || (p.state === "sending" && p.next_try_at)) ? '<button class="btn" data-act="unschedule">' + icon("calendar-x") + "Huỷ lịch</button>" : "") +
        ((p.state === "unscheduled" || p.state === "failed" || p.state === "sent") ? '<button class="btn ghost danger" data-act="archive">' + icon("archive") + "Bỏ khỏi danh sách</button>" : "") +
        (p.wp_url ? '<a class="btn" target="_blank" rel="noopener" href="' + esc(p.wp_url) + '">' + icon("external-link") + (zalo ? "Xem bài trên Zalo" : "Xem bài trên site") + "</a>" : "") +
        (p.wp_edit_url ? '<a class="btn" target="_blank" rel="noopener" href="' + esc(p.wp_edit_url) + '">' + markFor(site) + (zalo ? "Quản lý bài trên Zalo OA" : "Mở trong WordPress") + "</a>" : "") +
      "</div>";
    sheet(html);
    fillCovers($("#layer"));
    render();
  }

  function ruleText(key) {
    var r = (S.me.rules || []).find(function (x) { return x.key === key; });
    return r ? r.text : "";
  }

  function previewDoc(p, coverData) {
    var site = siteOf(p.site_id);
    var when = p.publish_at ? longTime(ms(p.publish_at), S.tz) : "Chưa có giờ đăng";
    return "<!doctype html><html lang='vi'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>" +
      "<style>body{margin:0;background:#fff;color:#1f2937;font:17px/1.75 Georgia,'Times New Roman',serif}" +
      ".bar{font:13px system-ui,sans-serif;color:#6b7280;border-bottom:1px solid #e5e7eb;padding:10px 20px;display:flex;gap:8px;justify-content:space-between}" +
      "article{max-width:740px;margin:0 auto;padding:28px 20px 60px}h1{font:700 34px/1.25 system-ui,sans-serif;color:#111827;margin:0 0 10px}" +
      ".meta{font:14px system-ui,sans-serif;color:#6b7280;margin-bottom:22px}.ex{font-style:italic;color:#4b5563;border-left:3px solid #e5e7eb;padding-left:14px}" +
      "img{max-width:100%;height:auto;border-radius:8px}.cover{width:100%;aspect-ratio:16/9;object-fit:cover;margin-bottom:22px}" +
      "h2{font:700 24px/1.35 system-ui,sans-serif;color:#111827;margin:34px 0 10px}h3{font:600 19px/1.4 system-ui,sans-serif;margin:24px 0 8px}" +
      "table{border-collapse:collapse;width:100%;font:15px system-ui,sans-serif}td,th{border:1px solid #e5e7eb;padding:8px 10px;text-align:left}" +
      "a{color:#2563eb}blockquote{border-left:3px solid #d1d5db;margin:0;padding-left:16px;color:#4b5563}</style></head><body>" +
      "<div class='bar'><span>Xem trước · " + esc(site ? site.url.replace(/^https?:\/\//, "") : "chưa chọn site") + "/" + esc(p.slug) + "/</span><span>" + esc(when) + " · " + esc(p.mode_label) + "</span></div>" +
      "<article>" + (coverData ? "<img class='cover' src='" + coverData + "' alt='" + esc(p.cover_alt) + "'>" : "") +
      "<h1>" + esc(p.title) + "</h1><div class='meta'>" + esc(p.categories.join(", ")) + (p.tags.length ? " · " + esc(p.tags.join(", ")) : "") + "</div>" +
      (p.excerpt ? "<p class='ex'>" + esc(p.excerpt) + "</p>" : "") + p.html + "</article></body></html>";
  }

  function inlineMedia(html) {
    var urls = [];
    html.replace(/\/api\/v1\/cqf\/lich\/media\/[a-z0-9]+\/[A-Za-z0-9._-]+/g, function (u) { if (urls.indexOf(u) < 0) urls.push(u); return u; });
    return Promise.all(urls.map(function (u) {
      return fetch(u, { headers: { Authorization: "Bearer " + token() } }).then(function (r) { return r.ok ? r.blob() : null; })
        .then(function (b) {
          if (!b) return [u, u];
          return new Promise(function (ok) { var fr = new FileReader(); fr.onload = function () { ok([u, fr.result]); }; fr.readAsDataURL(b); });
        }).catch(function () { return [u, u]; });
    })).then(function (pairs) {
      pairs.forEach(function (pair) { html = html.split(pair[0]).join(pair[1]); });
      return html;
    });
  }

  function zaloDoc(p, blocks, coverData) {
    var site = siteOf(p.site_id);
    var author = site && site.options && site.options.author ? site.options.author : (site ? site.name : "");
    return "<!doctype html><html lang='vi'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>" +
      "<style>body{margin:0;background:#e9ebed;font:16px/1.6 -apple-system,'Segoe UI',Roboto,Arial,sans-serif;color:#081c36}" +
      ".phone{max-width:420px;margin:16px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 6px 24px rgba(0,0,0,.12)}" +
      ".bar{display:flex;align-items:center;gap:8px;padding:10px 14px;background:#0068ff;color:#fff;font-size:14px;font-weight:600}" +
      ".cover{width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:#dfe2e7}" +
      ".in{padding:14px 16px 28px}h1{font-size:20px;line-height:1.35;margin:0 0 6px}.meta{color:#7589a3;font-size:13px;margin-bottom:12px}" +
      ".desc{color:#5a6981;font-size:15px;margin:0 0 14px}p{margin:0 0 12px;white-space:pre-wrap}img.b{width:100%;border-radius:6px;display:block}" +
      "figure{margin:0 0 12px}figcaption{color:#7589a3;font-size:13px;text-align:center;margin-top:4px}" +
      ".note{max-width:420px;margin:0 auto 16px;color:#5a6981;font:12.5px system-ui,sans-serif;padding:0 8px}</style></head><body>" +
      "<div class='phone'><div class='bar'>Zalo OA · " + esc(site ? site.name : "") + "</div>" +
      (coverData ? "<img class='cover' src='" + coverData + "' alt=''>" : "<div class='cover'></div>") +
      "<div class='in'><h1>" + esc(p.title) + "</h1><div class='meta'>" + esc(author) + "</div>" +
      (p.excerpt ? "<p class='desc'>" + esc(p.excerpt) + "</p>" : "") +
      blocks.map(function (b) {
        if (b.type === "image") return "<figure><img class='b' src='" + esc(b.url) + "' alt=''>" + (b.caption ? "<figcaption>" + esc(b.caption) + "</figcaption>" : "") + "</figure>";
        var t = document.createElement("textarea"); t.innerHTML = b.content;  // Zalo shows the decoded text
        return "<p>" + esc(t.value) + "</p>";
      }).join("") +
      "</div></div><p class='note'>Bài Zalo chỉ có chữ thường và ảnh: chữ đậm, nghiêng, link bấm được sẽ thành chữ thường.</p></body></html>";
  }

  function openPreview(p) {
    var go = function (data) {
      var layer = $("#layer");
      var holder = document.createElement("div");
      holder.innerHTML = '<div class="overlay top" data-act="close-modal"></div><div class="modal" role="dialog"><div class="modal-head"><h2>Xem trước</h2>' +
        '<span class="hint">Giao diện gần giống bài trên site; theme thật có thể khác chút.</span>' +
        '<button class="btn icon ghost" data-act="close-modal">' + icon("x") + '</button></div><iframe sandbox="" title="Xem trước"></iframe></div>';
      var frame = holder.querySelector("iframe");
      if (isZalo(p)) {
        holder.querySelector(".modal-head .hint").textContent = "Gần giống bài trên ứng dụng Zalo.";
        api("/posts/" + p.id + "/zalo").then(function (z) {
          return inlineMedia(JSON.stringify(z.blocks)).then(function (json) { frame.srcdoc = zaloDoc(p, JSON.parse(json), data); });
        }).catch(function (e) { toast(e.message, true); });
      } else {
        inlineMedia(p.html).then(function (body) { frame.srcdoc = previewDoc(Object.assign({}, p, { html: body }), data); });
      }
      holder.id = "modal";
      layer.appendChild(holder);
      icons();
    };
    if (!p.has_cover) return go(null);
    api("/posts/" + p.id + "/cover", { blob: true }).then(function (b) {
      var fr = new FileReader();
      fr.onload = function () { go(fr.result); };
      fr.readAsDataURL(b);
    }).catch(function () { go(null); });
  }

  // ---------- editor ----------
  function openEditor(p, atMs) {
    var isNew = !p;
    p = p || { title: "", excerpt: "", slug: "", categories: [], tags: [], html: "", cover_alt: "", site_id: S.settings.default_site_id };
    var locked = !isNew && (p.wp_post_id || p.ext_id);
    S.sheet = { kind: "editor", post: isNew ? null : p, at: atMs || null };
    sheet(
      '<div class="sheet-head"><h2>' + (isNew ? "Viết bài" : "Sửa nội dung") + '</h2><button class="btn icon ghost" data-act="close">' + icon("x") + "</button></div>" +
      '<form class="sheet-body" id="editor" autocomplete="off">' +
        '<div class="sec">' +
          (S.sites.length ? '<label class="field"><span>Đăng lên</span><select class="select" name="site_id"' + (locked ? " disabled" : "") + ">" +
            S.sites.map(function (s) { return '<option value="' + s.id + '"' + (s.id === p.site_id ? " selected" : "") + ">" + esc(s.kind_label + " · " + s.name) + "</option>"; }).join("") +
            "</select></label>" : "") +
          '<label class="field"><span>Tiêu đề <small class="hint" id="title-count"></small></span><input class="input" name="title" required maxlength="300" value="' + esc(p.title) + '"></label>' +
          '<label class="field"><span>Mô tả ngắn <small class="hint" id="excerpt-count"></small></span><textarea class="textarea" name="excerpt" rows="2" maxlength="1000">' + esc(p.excerpt) + "</textarea></label>" +
          '<p class="hint zalo-only">Zalo OA: bài chỉ hiện chữ thường và ảnh (không chữ đậm, không link bấm được); bắt buộc ảnh bìa.</p>' +
          '<label class="field"><span>Nội dung (HTML)</span><textarea class="textarea code" name="html" spellcheck="false">' + esc(p.html) + "</textarea>" +
            '<p class="hint">Dùng thẻ &lt;h2&gt;, &lt;p&gt;, &lt;ul&gt;, &lt;table&gt;… Không lặp lại tiêu đề trong nội dung.</p></label>' +
        "</div>" +
        '<div class="sec wp-only">' +
          '<label class="field"><span>Chuyên mục</span><input class="input" name="categories" placeholder="Cách nhau bằng dấu phẩy" value="' + esc(p.categories.join(", ")) + '"></label>' +
          '<div class="slot-pick" id="catpick"><span class="hint">Đang lấy chuyên mục của site…</span></div>' +
          '<label class="field"><span>Thẻ</span><input class="input" name="tags" placeholder="Cách nhau bằng dấu phẩy" value="' + esc(p.tags.join(", ")) + '"></label>' +
          '<label class="field"><span>Đường dẫn</span><input class="input" name="slug" placeholder="tự tạo từ tiêu đề" value="' + esc(p.slug) + '"></label>' +
          '<p class="hint">Chuyên mục chọn trong danh sách có sẵn của site (không tạo chuyên mục mới). Thẻ chưa có sẽ được tạo khi đăng.</p>' +
        "</div>" +
        (isNew ? '<div class="sec"><label class="field"><span>Ảnh bìa</span><input type="file" name="cover" accept="image/jpeg,image/png,image/gif,image/webp"></label></div>' : "") +
        '<div class="sec"><label class="field"><span>Chú thích ảnh bìa (alt)</span><input class="input" name="cover_alt" value="' + esc(p.cover_alt) + '"></label></div>' +
        (atMs ? '<p class="hint">Bài sẽ được hẹn ' + esc(longTime(atMs, S.tz).toLowerCase()) + " sau khi lưu.</p>" : "") +
      "</form>" +
      '<div class="sheet-foot"><button class="btn" data-act="close">Huỷ</button><button class="btn primary" data-act="save-editor">' + icon("check") +
        (isNew ? (atMs ? "Lưu và lên lịch" : "Lưu vào Chưa lên lịch") : "Lưu") + "</button></div>",
      true
    );
    $("#editor input[name=title]").focus();
    editorChannel();
    var siteId = p.site_id || (S.settings && S.settings.default_site_id);
    var box = $("#catpick");
    if (!siteId) { box.innerHTML = '<span class="hint">Chưa có site WordPress.</span>'; return; }
    api("/sites/" + siteId + "/categories").then(function (cats) {
      if (!$("#catpick")) return;
      $("#catpick").innerHTML = cats.length ? cats.map(function (c) {
        return '<button type="button" class="chip" data-act="add-cat" data-name="' + esc(c.name) + '">' + esc(c.name) + "</button>";
      }).join("") : '<span class="hint">Site chưa có chuyên mục nào.</span>';
    }).catch(function (e) {
      if ($("#catpick")) $("#catpick").innerHTML = '<span class="hint warn">Chưa lấy được chuyên mục: ' + esc(e.message) + "</span>";
    });
  }

  function editorChannel() {
    var f = $("#editor");
    if (!f) return;
    var site = f.site_id ? siteOf(f.site_id.value) : siteOf(S.settings.default_site_id);
    var zalo = isZalo(site);
    $$(".wp-only", f).forEach(function (x) { x.hidden = zalo; });
    $$(".zalo-only", f).forEach(function (x) { x.hidden = !zalo; });
    var count = function (input, id, max) {
      var n = input.value.length;
      $(id).textContent = zalo ? "(" + n + "/" + max + ")" : "";
      $(id).classList.toggle("warn", zalo && n > max);
    };
    count(f.title, "#title-count", 150);
    count(f.excerpt, "#excerpt-count", 300);
  }

  function saveEditor() {
    var f = $("#editor");
    if (!f.reportValidity()) return;
    var data = {
      title: f.title.value, excerpt: f.excerpt.value, html: f.html.value, slug: f.slug.value,
      categories: f.categories.value, tags: f.tags.value, cover_alt: f.cover_alt.value
    };
    if (f.site_id && !f.site_id.disabled) data.site_id = f.site_id.value;
    var ctx = S.sheet;
    var file = f.cover && f.cover.files[0];
    var req = ctx.post ? api("/posts/" + ctx.post.id, { method: "PATCH", body: data }) : api("/posts", { method: "POST", body: data });
    req.then(function (p) {
      var chain = Promise.resolve(p);
      if (file) {
        var fd = new FormData();
        fd.append("file", file);
        chain = chain.then(function () { return api("/posts/" + p.id + "/cover", { method: "POST", body: fd }); });
      }
      if (ctx.at) chain = chain.then(function () { return api("/posts/" + p.id + "/schedule", { method: "POST", body: { publish_at: new Date(ctx.at).toISOString() } }); });
      return chain.then(function () { toast(ctx.post ? "Đã lưu." : "Đã tạo bài."); return refresh(); }).then(function () { openPost(p.id); });
    }).catch(function (e) { toast(e.message, true); });
  }

  // ---------- settings ----------
  function openSettings(tab) {
    tab = tab || "sites";
    // Keep unsaved edits (slot rows, the site being edited) while switching tabs or redrawing.
    if (!(S.sheet && S.sheet.kind === "settings")) S.sheet = { kind: "settings" };
    S.sheet.tab = tab;
    var st = S.settings;
    var tabs = '<div class="tabs">' + [["sites", "Kết nối"], ["publish", "Đăng bài"], ["slots", "Khung giờ đăng"], ["status", "Trạng thái"]].map(function (t) {
      return '<button class="' + (t[0] === tab ? "on" : "") + '" data-act="settings" data-tab="' + t[0] + '">' + t[1] + "</button>";
    }).join("") + "</div>";
    var body = "";
    if (tab === "sites") {
      body = '<div class="sec"><p class="hint">' + esc(ruleText("password")) + "</p>" +
        (S.me.server_ip ? '<p class="hint">Hosting có tường lửa thì cho IP máy chủ <b>' + esc(S.me.server_ip) + "</b> vào danh sách cho phép.</p>" : "") + "</div>" +
        '<div class="sec" style="padding-top:0"><h3>WordPress</h3>' + (S.sites.filter(function (s) { return !isZalo(s); }).length ? S.sites.filter(function (s) { return !isZalo(s); }).map(function (s) {
          return '<div class="site">' + wpMark("md") + '<div class="who"><b>' + esc(s.name) + (s.id === st.default_site_id ? ' <span class="badge neutral">Mặc định</span>' : "") + "</b>" +
            "<small>" + esc(s.url) + " · " + esc(s.username) + "</small>" +
            (s.check_ok ? '<small style="color:var(--sent)">' + icon("circle-check") + " Kết nối được" + (s.unfiltered_html === false ? " · tài khoản không được dùng HTML thô, thẻ &lt;style&gt;/&lt;script&gt; sẽ bị lọc" : "") + "</small>"
              : '<small class="error-text">' + icon("circle-x") + " " + esc(s.check_error || "Chưa kiểm tra") + "</small>") +
            (s.checked_at ? "<small>Kiểm lúc " + esc(shortDate(ms(s.checked_at), S.tz)) + "</small>" : "") + "</div>" +
            '<div class="row"><button class="btn sm" data-act="check-site" data-id="' + s.id + '">Kiểm tra</button>' +
            '<button class="btn sm" data-act="edit-site" data-id="' + s.id + '">Sửa</button>' +
            '<button class="btn sm ghost danger" data-act="delete-site" data-id="' + s.id + '">Xoá</button></div></div>';
        }).join("") : '<p class="hint">Chưa có site WordPress nào.</p>') + "</div>" +
        siteForm(S.sheet.editSite ? siteOf(S.sheet.editSite) : null) +
        '<div class="sec"><h3>Zalo OA</h3><p class="hint">' + esc(ruleText("zalo")) + "</p>" +
        S.sites.filter(isZalo).map(function (s) {
          return '<div class="site">' + markFor(s, "md") + '<div class="who"><b>' + esc(s.name) + (s.id === st.default_site_id ? ' <span class="badge neutral">Mặc định</span>' : "") + "</b>" +
            "<small>OA " + esc(s.oa_id) + "</small>" +
            (s.check_ok ? '<small style="color:var(--sent)">' + icon("circle-check") + " Kết nối được</small>" : '<small class="error-text">' + icon("circle-x") + " " + esc(s.check_error || "Chưa kiểm tra") + "</small>") +
            '<div class="row" style="margin-top:8px"><input class="input" style="max-width:220px" data-zalo-author="' + s.id + '" maxlength="50" value="' + esc(s.options.author || "") + '" placeholder="Tác giả">' +
            '<select class="select" style="max-width:170px" data-zalo-comment="' + s.id + '"><option value="show"' + (s.options.comment !== "hide" ? " selected" : "") + '>Cho bình luận</option><option value="hide"' + (s.options.comment === "hide" ? " selected" : "") + ">Tắt bình luận</option></select>" +
            '<button class="btn sm" data-act="save-zalo" data-id="' + s.id + '">Lưu</button></div></div>' +
            '<div class="row"><button class="btn sm" data-act="check-site" data-id="' + s.id + '">Kiểm tra</button>' +
            '<button class="btn sm ghost danger" data-act="delete-site" data-id="' + s.id + '">Xoá</button></div></div>';
        }).join("") + '<div id="zalo-cands"><span class="hint">Đang tìm OA đã kết nối trên máy chủ…</span></div></div>';
    } else if (tab === "publish") {
      body = '<form id="pubform" class="sheet-body" style="padding:0">' +
        '<div class="sec"><label class="field"><span>Múi giờ</span><select class="select" name="timezone">' + zoneOptions(st.timezone) + "</select></label>" +
          '<p class="hint">' + esc(ruleText("time")) + "</p></div>" +
        '<div class="sec"><span style="font-weight:500">Chế độ mặc định cho bài mới</span><div class="seg" id="defmode">' +
          '<button type="button" class="' + (st.default_mode === "publish" ? "on" : "") + '" data-mode="publish">' + icon("globe") + "Đăng thật</button>" +
          '<button type="button" class="' + (st.default_mode === "draft" ? "on" : "") + '" data-mode="draft">' + icon("file-pen") + "Lưu nháp trên WordPress</button></div>" +
          '<p class="hint">' + esc(ruleText("mode")) + "</p></div>" +
        (S.sites.length ? '<div class="sec"><label class="field"><span>Site mặc định</span><select class="select" name="default_site_id">' +
          S.sites.map(function (s) { return '<option value="' + s.id + '"' + (s.id === st.default_site_id ? " selected" : "") + ">" + esc(s.name) + "</option>"; }).join("") +
          "</select></label></div>" : "") +
        "</form>";
    } else if (tab === "slots") {
      var slots = S.sheet.slots || JSON.parse(JSON.stringify(st.slots || []));
      S.sheet.slots = slots;
      body = '<div class="sec"><p class="hint">Giờ đăng quen thuộc, theo ' + esc(st.timezone) + ". Agent và nút “khung giờ trống” chọn giờ trong các khung này, hai bài cách nhau ít nhất 30 phút. Khung giờ cũng hiện trong Lịch của Open WebUI.</p></div>" +
        '<div class="sec" style="padding-top:0" id="slots">' + slots.map(function (s, i) {
          return '<div class="slotrow"><div class="days">' + [1, 2, 3, 4, 5, 6, 7].map(function (d) {
            return '<button type="button" class="' + (s.days.indexOf(d) >= 0 ? "on" : "") + '" data-act="slot-day" data-i="' + i + '" data-d="' + d + '">' + DAY_TINY[d] + "</button>";
          }).join("") + '</div><input class="input" type="time" value="' + esc(s.time) + '" data-act="slot-time" data-i="' + i + '">' +
            '<button class="btn icon ghost" data-act="slot-del" data-i="' + i + '" title="Bỏ khung giờ">' + icon("trash-2") + "</button></div>";
        }).join("") + '<button class="btn" style="margin-top:10px" data-act="slot-add">' + icon("plus") + "Thêm khung giờ</button></div>";
    } else {
      var w = S.me.worker || {};
      body = '<dl class="facts" style="margin-top:8px">' +
        "<dt>Máy gửi bài</dt><dd>" + (w.last_tick_at ? "Chạy, lần gần nhất " + esc(rel(ms(w.last_tick_at))) : "Chưa chạy") + "</dd>" +
        "<dt>Gửi gần nhất</dt><dd>" + (w.last_sent_at ? esc(longTime(ms(w.last_sent_at), S.tz)) : "Chưa có") + "</dd>" +
        "<dt>Lịch Open WebUI</dt><dd>" + (w.mirror_error ? '<span class="error-text">' + esc(w.mirror_error) + "</span>" : (w.mirror_at ? "Đồng bộ " + esc(rel(ms(w.mirror_at))) : "Chưa đồng bộ")) + "</dd>" +
        "<dt>IP máy chủ</dt><dd>" + esc(S.me.server_ip || "?") + "<small>Hosting có tường lửa thì cho IP này vào danh sách cho phép</small></dd>" +
        "<dt>Agent</dt><dd>" + (S.me.agent && S.me.agent.works_for_me ? "Đang làm việc cho bạn" : "Đang làm việc cho người khác") +
          "<small>Agent tạo bài, xem trước, hẹn giờ khi bạn đồng ý trong chat; không sửa site hay cài đặt</small>" +
          (S.me.agent && !S.me.agent.works_for_me ? '<button class="btn sm" style="margin-top:6px" data-act="claim-agent">Agent làm việc cho tôi</button>' : "") + "</dd>" +
        "<dt>Bạn</dt><dd>" + esc(S.me.user.name) + "</dd></dl>" +
        (w.last_error ? '<p class="error-text">' + esc(w.last_error) + "</p>" : "");
    }
    if (tab === "sites") {
      api("/zalo/oas").then(function (oas) {
        var box = $("#zalo-cands");
        if (!box) return;
        var left = oas.filter(function (o) { return !o.added; });
        box.innerHTML = left.length ? left.map(function (o) {
          return '<div class="site">' + markFor({ kind: "zalo_oa" }, "md") + '<div class="who"><b>' + esc(o.name) + "</b><small>OA " + esc(o.oa_id) + " · đã kết nối ở trang Chatbot</small></div>" +
            '<button class="btn sm primary" data-act="add-zalo" data-oa="' + esc(o.oa_id) + '">' + icon("plus") + "Thêm vào Lịch đăng</button></div>";
        }).join("") : (oas.length ? "" : '<p class="hint">Chưa có OA nào kết nối trên máy chủ. Nạp token OA ở trang Chatbot → Kênh Zalo OA, rồi quay lại đây.</p>');
      }).catch(function () { var box = $("#zalo-cands"); if (box) box.innerHTML = ""; });
    }
    var foot = tab === "publish" ? '<div class="sheet-foot"><button class="btn primary" data-act="save-publish">' + icon("check") + "Lưu</button></div>"
      : tab === "slots" ? '<div class="sheet-foot"><button class="btn primary" data-act="save-slots">' + icon("check") + "Lưu khung giờ</button></div>" : "";
    sheet('<div class="sheet-head"><h2>Cài đặt</h2><button class="btn icon ghost" data-act="close">' + icon("x") + "</button></div>" + tabs +
      (tab === "publish" ? body : '<div class="sheet-body">' + body + "</div>") + foot, true);
  }

  function siteForm(s) {
    return '<form class="sec" id="siteform" autocomplete="off"><h3>' + (s ? "Sửa " + esc(s.name) : "Thêm site WordPress") + "</h3>" +
      '<label class="field"><span>Địa chỉ site</span><input class="input" name="url" placeholder="https://tenmien.com" required value="' + esc(s ? s.url : "") + '"></label>' +
      '<label class="field"><span>Tên hiển thị</span><input class="input" name="name" placeholder="tự lấy theo tên miền" value="' + esc(s ? s.name : "") + '"></label>' +
      '<label class="field"><span>Tên đăng nhập WordPress</span><input class="input" name="username" required autocomplete="off" value="' + esc(s ? s.username : "") + '"></label>' +
      '<label class="field"><span>Application password</span><input class="input" name="app_password" type="password" autocomplete="new-password" ' + (s ? "" : "required ") +
        'placeholder="' + (s ? "Để trống nếu giữ nguyên" : "xxxx xxxx xxxx xxxx xxxx xxxx") + '"></label>' +
      '<p class="hint">Tạo trong WordPress: Người dùng → Hồ sơ → Application Passwords → đặt tên “Lịch đăng” → Thêm mới, rồi chép chuỗi 24 ký tự vào đây. Cần tài khoản Biên tập viên hoặc Quản trị.</p>' +
      '<div class="row"><button class="btn primary" type="submit" data-act="save-site" data-id="' + (s ? s.id : "") + '">' + icon("plug") + "Kiểm tra và lưu</button>" +
      (s ? '<button class="btn ghost" type="button" data-act="edit-site" data-id="">Thêm site khác</button>' : "") + "</div></form>";
  }

  function openRules() {
    S.sheet = { kind: "rules" };
    sheet('<div class="sheet-head"><h2>Quy tắc của Lịch đăng</h2><button class="btn icon ghost" data-act="close">' + icon("x") + "</button></div>" +
      '<div class="sheet-body"><ul class="rules">' + S.me.rules.map(function (r) {
        return "<li><b>" + esc(r.title) + "</b><p>" + esc(r.text) + "</p></li>";
      }).join("") + "</ul></div>");
  }

  // ---------- events ----------
  function move(step) {
    var a = S.anchor;
    if (S.view === "week") S.anchor = addDays(a, 7 * step);
    else {
      var m = a.m + step, y = a.y;
      if (m < 1) { m = 12; y--; } if (m > 12) { m = 1; y++; }
      S.anchor = addDays({ y: y, m: m, d: 1 }, 0);
    }
    S.weekScroll = null;
    loadPosts().then(render);
  }

  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-act]");
    var postEl = e.target.closest("[data-post]");
    if (el && el.tagName === "SELECT") return;
    if (!el && postEl && !e.target.closest("#layer")) { openPost(postEl.dataset.post); return; }
    if (!el) {
      var cell = e.target.closest(".col .cell");
      if (cell && !cell.parentElement.classList.contains("past")) {
        var d = cell.parentElement.dataset.day.split("-");
        var at = zoned(+d[0], +d[1], +d[2], 0, +cell.dataset.min, S.tz);
        if (at < Date.now() + 60000) return toast("Giờ này đã qua.", true);
        quickPick(at);
      }
      var mday = e.target.closest(".mday");
      if (mday && !e.target.closest(".mchip")) {
        var p = mday.dataset.day.split("-");
        S.view = "week"; store("view", "week");
        S.anchor = addDays({ y: +p[0], m: +p[1], d: +p[2] }, 0);
        loadPosts().then(render);
      }
      return;
    }
    var act = el.dataset.act;
    var cur = S.sheet && S.sheet.post;
    switch (act) {
      case "close": closeLayer(); break;
      case "sidebar": tellParent({ type: "cqf-toggle-sidebar" }); break;
      case "close-modal": var m = $("#modal"); if (m) m.remove(); break;
      case "today": S.anchor = today(); S.weekScroll = null; loadPosts().then(render); break;
      case "prev": move(-1); break;
      case "next": move(1); break;
      case "view": S.view = el.dataset.view; store("view", S.view); loadPosts().then(render); break;
      case "state": S.stateFilter = el.dataset.state; store("state", S.stateFilter); render(); break;
      case "site": S.siteFilter = el.dataset.id; render(); break;
      case "tz-default":
        api("/settings", { method: "PUT", body: { timezone: S.tz } }).then(function () { toast("Đã đặt " + S.tz + " làm múi giờ mặc định."); refresh(); }).catch(function (x) { toast(x.message, true); });
        break;
      case "new": closeLayer(); openEditor(null, el.dataset.at ? +el.dataset.at : null); break;
      case "rules": openRules(); break;
      case "settings": if (S.sheet && S.sheet.kind === "settings") { S.sheet.tab = el.dataset.tab; openSettings(el.dataset.tab); } else openSettings(el.dataset.tab); break;
      case "pick": schedule(el.dataset.post, +el.dataset.at).then(function () { closeLayer(); }); break;
      case "preview": openPreview(cur); break;
      case "edit": openEditor(cur); break;
      case "save-editor": saveEditor(); break;
      case "claim-agent":
        api("/agent", { method: "POST" }).then(function () { toast("Từ giờ Agent làm việc cho bạn."); return refresh().then(function () { openSettings("status"); }); })
          .catch(function (x) { toast(x.message, true); });
        break;
      case "add-cat":
        var ci = $("#editor input[name=categories]");
        var list = ci.value.split(",").map(function (x) { return x.trim(); }).filter(Boolean);
        if (list.indexOf(el.dataset.name) < 0) list.push(el.dataset.name);
        ci.value = list.join(", ");
        break;
      case "save-time":
        var t = inputToMs($("#when").value, S.tz);
        if (!t) return toast("Chọn ngày giờ trước.", true);
        schedule(cur.id, t);
        break;
      case "slot": schedule(cur.id, +el.dataset.at); break;
      case "mode":
        api("/posts/" + cur.id + "/mode", { method: "POST", body: { mode: el.dataset.mode } })
          .then(function (p) { toast("Chế độ: " + p.mode_label); return refresh().then(function () { openPost(p.id); }); })
          .catch(function (x) { toast(x.message, true); });
        break;
      case "unschedule":
        api("/posts/" + cur.id + "/unschedule", { method: "POST" }).then(function (p) { toast("Đã huỷ lịch, bài về Chưa lên lịch."); return refresh().then(function () { openPost(p.id); }); })
          .catch(function (x) { toast(x.message, true); });
        break;
      case "retry":
        api("/posts/" + cur.id + "/retry", { method: "POST" }).then(function (p) { toast("Sẽ gửi lại " + longTime(ms(p.publish_at), S.tz).toLowerCase() + "."); return refresh().then(function () { openPost(p.id); }); })
          .catch(function (x) { toast(x.message, true); });
        break;
      case "archive":
        if (!confirm("Bỏ bài “" + cur.title + "” khỏi Lịch đăng? Bài trên WordPress (nếu có) không bị đụng tới.")) return;
        api("/posts/" + cur.id + "/archive", { method: "POST" }).then(function () { toast("Đã bỏ khỏi danh sách."); closeLayer(); refresh(); })
          .catch(function (x) { toast(x.message, true); });
        break;
      case "cover-remove":
        api("/posts/" + cur.id + "/cover", { method: "DELETE" }).then(function (p) { return refresh().then(function () { openPost(p.id); }); }).catch(function (x) { toast(x.message, true); });
        break;
      case "check-site":
        el.disabled = true;
        api("/sites/" + el.dataset.id + "/check", { method: "POST" }).then(function (s) {
          toast(s.check_ok ? s.name + ": kết nối được." : s.name + ": " + s.check_error, !s.check_ok);
          return refresh().then(function () { if (S.sheet && S.sheet.kind === "settings") openSettings("sites"); });
        }).catch(function (x) { toast(x.message, true); el.disabled = false; });
        break;
      case "edit-site": S.sheet.editSite = el.dataset.id || null; openSettings("sites"); var u = $("#siteform input[name=url]"); if (u) u.focus(); break;
      case "delete-site":
        var site = siteOf(el.dataset.id);
        if (!confirm("Xoá kết nối " + site.name + " khỏi Lịch đăng? Bài trên WordPress không bị đụng tới.")) return;
        api("/sites/" + site.id, { method: "DELETE" }).then(function () { toast("Đã xoá kết nối."); return refresh().then(function () { openSettings("sites"); }); })
          .catch(function (x) { toast(x.message, true); });
        break;
      case "save-site": e.preventDefault(); saveSite(el); break;
      case "add-zalo":
        el.disabled = true;
        api("/sites/zalo", { method: "POST", body: { oa_id: el.dataset.oa } }).then(function (s) {
          toast(s.check_ok ? "Đã thêm Zalo OA " + s.name + "." : "Đã thêm " + s.name + " nhưng chưa kết nối được: " + s.check_error, !s.check_ok);
          return refresh().then(function () { openSettings("sites"); });
        }).catch(function (x) { toast(x.message, true); el.disabled = false; });
        break;
      case "save-zalo":
        api("/sites/" + el.dataset.id + "/zalo", { method: "PATCH", body: {
          author: $('[data-zalo-author="' + el.dataset.id + '"]').value, comment: $('[data-zalo-comment="' + el.dataset.id + '"]').value } })
          .then(function () { toast("Đã lưu."); return refresh().then(function () { openSettings("sites"); }); })
          .catch(function (x) { toast(x.message, true); });
        break;
      case "save-publish":
        var f = $("#pubform");
        var on = $("#defmode .on");
        api("/settings", { method: "PUT", body: { timezone: f.timezone.value, default_mode: on ? on.dataset.mode : undefined, default_site_id: f.default_site_id ? f.default_site_id.value : undefined } })
          .then(function (st) { S.tz = st.timezone; store("tz", st.timezone); toast("Đã lưu cài đặt."); return refresh().then(function () { openSettings("publish"); }); })
          .catch(function (x) { toast(x.message, true); });
        break;
      case "slot-day":
        var s1 = S.sheet.slots[+el.dataset.i]; var dd = +el.dataset.d; var ix = s1.days.indexOf(dd);
        if (ix >= 0) s1.days.splice(ix, 1); else s1.days.push(dd);
        s1.days.sort(); openSettings("slots"); break;
      case "slot-del": S.sheet.slots.splice(+el.dataset.i, 1); openSettings("slots"); break;
      case "slot-add": S.sheet.slots.push({ days: [1, 2, 3, 4, 5], time: "09:00" }); openSettings("slots"); break;
      case "save-slots":
        api("/settings", { method: "PUT", body: { slots: S.sheet.slots } }).then(function () {
          toast("Đã lưu khung giờ đăng."); S.sheet.slots = null; return refresh().then(function () { openSettings("slots"); });
        }).catch(function (x) { toast(x.message, true); });
        break;
    }
    if (el.closest("#defmode") || (el.parentElement && el.parentElement.id === "defmode")) {
      $$("#defmode button").forEach(function (b) { b.classList.toggle("on", b === el); });
    }
  });

  document.addEventListener("click", function (e) {
    var b = e.target.closest("#defmode button");
    if (b) $$("#defmode button").forEach(function (x) { x.classList.toggle("on", x === b); });
  });

  function saveSite(btn) {
    var f = $("#siteform");
    if (!f.reportValidity()) return;
    btn.disabled = true;
    btn.textContent = "Đang kiểm tra…";
    var id = btn.dataset.id;
    var body = { url: f.url.value, name: f.name.value || null, username: f.username.value, app_password: f.app_password.value || null };
    api(id ? "/sites/" + id : "/sites", { method: id ? "PATCH" : "POST", body: body }).then(function (s) {
      toast(s.check_ok ? "Đã lưu " + s.name + ", kết nối được (" + (s.account || "") + ")." : "Đã lưu " + s.name + " nhưng chưa kết nối được: " + s.check_error, !s.check_ok);
      S.sheet.editSite = null;
      return refresh().then(function () { openSettings("sites"); });
    }).catch(function (x) { toast(x.message, true); btn.disabled = false; btn.textContent = "Kiểm tra và lưu"; });
  }

  document.addEventListener("submit", function (e) { e.preventDefault(); var b = e.target.querySelector("[data-act=save-site]"); if (b) saveSite(b); });

  document.addEventListener("input", function (e) {
    if (e.target.closest("#editor")) editorChannel();
  });

  document.addEventListener("change", function (e) {
    var el = e.target;
    if (el.name === "site_id" && el.closest("#editor")) editorChannel();
    if (el.dataset.act === "tz") { S.tz = el.value; store("tz", S.tz); S.anchor = today(); loadPosts().then(render); }
    if (el.dataset.act === "slot-time") { S.sheet.slots[+el.dataset.i].time = el.value; }
    if (el.dataset.act === "post-site") {
      api("/posts/" + S.sheet.post.id, { method: "PATCH", body: { site_id: el.value } }).then(function (p) { toast("Đã đổi site."); return refresh().then(function () { openPost(p.id); }); })
        .catch(function (x) { toast(x.message, true); });
    }
    if (el.dataset.act === "cover-file" && el.files[0]) {
      var fd = new FormData();
      fd.append("file", el.files[0]);
      api("/posts/" + S.sheet.post.id + "/cover", { method: "POST", body: fd }).then(function (p) { toast("Đã cập nhật ảnh bìa."); return refresh().then(function () { openPost(p.id); }); })
        .catch(function (x) { toast(x.message, true); });
    }
  });

  // Drag and drop: unscheduled cards and scheduled events onto the week grid or a month day.
  document.addEventListener("dragstart", function (e) {
    var el = e.target.closest("[data-post][draggable=true]");
    if (!el) return;
    var rect = el.getBoundingClientRect();
    S.drag = { id: el.dataset.post, grab: el.classList.contains("ev") ? e.clientY - rect.top : 0 };
    e.dataTransfer.setData("text/plain", el.dataset.post);
    e.dataTransfer.effectAllowed = "move";
    el.classList.add("dragging");
  });
  document.addEventListener("dragend", function (e) {
    $$(".dragging").forEach(function (x) { x.classList.remove("dragging"); });
    $$(".drop").forEach(function (x) { x.classList.remove("drop"); });
  });
  document.addEventListener("dragover", function (e) {
    var target = e.target.closest(".col:not(.past), .mday");
    if (!target || !S.drag) return;
    e.preventDefault();
    $$(".drop").forEach(function (x) { if (x !== target) x.classList.remove("drop"); });
    target.classList.add("drop");
  });
  document.addEventListener("drop", function (e) {
    var target = e.target.closest(".col:not(.past), .mday");
    if (!target || !S.drag) return;
    e.preventDefault();
    var drag = S.drag; S.drag = null;
    var d = target.dataset.day.split("-");
    var post = S.posts.find(function (p) { return p.id === drag.id; });
    var at;
    if (target.classList.contains("col")) {
      var y = e.clientY - target.getBoundingClientRect().top - drag.grab;
      var minutes = Math.max(0, Math.min(1425, Math.round(y / HOUR_PX * 60 / 15) * 15));
      at = zoned(+d[0], +d[1], +d[2], Math.floor(minutes / 60), minutes % 60, S.tz);
    } else {
      var keep = post && post.publish_at ? partsOf(ms(post.publish_at), S.tz) : null;
      var first = (S.settings.slots[0] && S.settings.slots[0].time || "08:00").split(":");
      at = zoned(+d[0], +d[1], +d[2], keep ? keep.h : +first[0], keep ? keep.mi : +first[1], S.tz);
    }
    if (post && post.publish_at && ms(post.publish_at) === at) return render();
    schedule(drag.id, at);
  });

  document.addEventListener("keydown", function (e) {
    if (e.target.closest("input, textarea, select")) return;
    if (e.key === "Escape") { var m = $("#modal"); if (m) m.remove(); else closeLayer(); }
    if (e.key === "n" || e.key === "N") { e.preventDefault(); openEditor(null); }
    if (e.key === "t" || e.key === "T") { S.anchor = today(); S.weekScroll = null; loadPosts().then(render); }
    if (!$("#layer").innerHTML) {
      if (e.key === "ArrowLeft") move(-1);
      if (e.key === "ArrowRight") move(1);
    }
  });

  // ---------- start ----------
  function showLogin() {
    if (S.polling) clearInterval(S.polling);
    $("#root").innerHTML = '<div class="login"><h1>Lịch đăng</h1><p class="hint">Đăng nhập Open WebUI trước, rồi quay lại trang này.</p>' +
      '<a class="btn primary" href="/auth" target="_top">Đăng nhập Open WebUI</a></div>';
  }

  function openFromHash() {
    var m = /post=([a-z0-9]+)/.exec(location.hash) || /^([a-z0-9]+)$/.exec(PARAMS.get("post") || "");
    if (m) openPost(m[1]);
    else if (location.hash === "#settings") openSettings("sites");
    else if (location.hash === "#rules") openRules();
  }

  if (!token()) { showLogin(); return; }
  loadMe().then(loadPosts).then(function () {
    render();
    openFromHash();
    api("/timezones").then(function (z) {
      var common = COMMON_ZONES.filter(function (x) { return z.indexOf(x) >= 0 || x === "UTC"; });
      S.zones = common.concat(z.filter(function (x) { return common.indexOf(x) < 0; }));
    });
    S.polling = setInterval(function () {
      if (document.hidden) return;
      var editing = S.sheet && (S.sheet.kind === "editor" || S.sheet.kind === "settings");
      Promise.all([loadMe(), loadPosts()]).then(function () {
        render();
        if (!editing && S.sheet && S.sheet.kind === "post" && !$("#modal")) {
          var fresh = S.posts.find(function (p) { return p.id === S.sheet.post.id; });
          if (fresh && fresh.updated_at !== S.sheet.post.updated_at) openPost(fresh.id);
        }
      }).catch(function () {});
    }, 20000);
  }).catch(function (e) { if (token()) toast(e.message, true); });
  window.addEventListener("hashchange", openFromHash);
})();
