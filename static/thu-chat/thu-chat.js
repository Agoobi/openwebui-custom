/* Trang Thu chatbot (xem index.html). Chat voi bot qua /api/v1/cqf/test/stream (SSE), ben phai la "Bot da lam gi":
 * cau tra tu dong, doan tai lieu tim thay, tool bot goi, so lieu bi chan. Lich su luu tren server (/test/sessions),
 * mo may nao cung thay; trinh duyet chi nho dang mo cuoc thu nao. Moi chu dua vao trang deu escape. */
(() => {
	'use strict';
	const { api, AuthError, $, el, toast, authScreen, clock } = window.CQF;
	const KEY = 'cqf_test_chat_sid';
	const SAMPLES = ['Bên mình bán những sản phẩm gì?', 'Cho em xin báo giá', 'Giờ làm việc thế nào?', 'Tôi muốn gặp nhân viên tư vấn'];
	const TOOL = { tim_kien_thuc: 'Tra thêm tài liệu', doc_tai_lieu: 'Đọc nguyên văn tài liệu', luu_khach_hang: 'Lưu thông tin khách', chuyen_nhan_vien: 'Báo nhân viên' };

	// ------------------------------------------------------------ Markdown (giong khung chat website: escape truoc)
	const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
	const inline = (s) => esc(s)
		.replace(/`([^`]+)`/g, '<code>$1</code>')
		.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
		.replace(/(^|[^*])\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g, '$1<em>$2</em>')
		.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
	function md(text) {
		const out = []; let list = null, para = [], table = null;
		const fp = () => { if (para.length) { out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = []; } };
		const fl = () => { if (list) { out.push(`<${list.t}>${list.i.map((x) => `<li>${inline(x)}</li>`).join('')}</${list.t}>`); list = null; } };
		const ft = () => {
			if (!table) return;
			const rows = table.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r)).map((r) => r.replace(/^\s*\||\|\s*$/g, '').split('|').map((c) => inline(c.trim())));
			if (rows.length) {
				out.push(`<div class="tw"><table><thead><tr>${rows[0].map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>` +
					rows.slice(1).map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('') + '</tbody></table></div>');
			}
			table = null;
		};
		const fa = () => { fp(); fl(); ft(); };
		for (const line of String(text).replace(/\r\n/g, '\n').split('\n')) {
			const st = line.trim(); let m;
			if (!st) { fa(); continue; }
			if ((m = st.match(/^#{1,6}\s+(.*)$/))) { fa(); out.push(`<h4>${inline(m[1])}</h4>`); continue; }
			if (st[0] === '|') { fp(); fl(); (table = table || []).push(st); continue; }
			if ((m = st.match(/^([-*+•]|\d+[.)])\s+(.*)$/))) {
				fp(); ft();
				const t = /\d/.test(m[1]) ? 'ol' : 'ul';
				if (list && list.t !== t) fl();
				(list = list || { t, i: [] }).i.push(m[2]);
				continue;
			}
			if (/^(-{3,}|\*{3,})$/.test(st)) { fa(); out.push('<hr>'); continue; }
			fl(); ft(); para.push(st);
		}
		fa();
		return out.join('');
	}

	// ------------------------------------------------------------ trang thai (lich su tren server)
	const rid = () => Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, '0')).join('');
	const remembered = () => { try { return localStorage.getItem(KEY) || ''; } catch { return ''; } };
	const remember = (sid) => { try { localStorage.setItem(KEY, sid); } catch { /* bo qua */ } };
	let state = { sid: rid(), turns: [] };
	let sessions = [];
	let selected = null, busy = false;

	async function loadSessions() {
		sessions = (await api('/test/sessions')).sessions || [];
		renderHistory();
	}

	async function open(sid) {
		if (busy) return;
		try {
			const { session } = await api(`/test/session?sid=${encodeURIComponent(sid)}`);
			state = { sid: session.sid, turns: session.turns || [] };
		} catch (e) {
			if (e instanceof AuthError) return authScreen(document.querySelector('main'));
			state = { sid: rid(), turns: [] };
		}
		remember(state.sid);
		selected = null;
		renderLog();
		renderHistory();
		const last = state.turns.length - 1;
		if (last >= 0 && state.turns[last].role === 'bot') select(last, false);
		else renderTrace();
	}

	function startNew() {
		if (busy) return;
		state = { sid: rid(), turns: [] };
		remember(state.sid);
		selected = null;
		renderLog();
		renderTrace();
		renderHistory();
		$('text').focus();
	}

	// ------------------------------------------------------------ lich su thu
	function renderHistory() {
		const list = $('histList');
		list.replaceChildren();
		$('histBtn').textContent = sessions.length ? `Lịch sử (${sessions.length})` : 'Lịch sử';
		if (!sessions.length) return list.append(el('p', 'hint', 'Chưa có cuộc thử nào.'));
		for (const x of sessions) {
			const row = el('div', 'hrow' + (x.sid === state.sid ? ' on' : ''));
			const b = el('button', 'hopen');
			b.type = 'button';
			b.append(el('b', '', x.title || '(trống)'), el('span', 'hint', `${clock(x.updated_at)} · ${x.turns} câu hỏi`));
			b.addEventListener('click', () => { closeHistory(); open(x.sid); });
			const del = el('button', 'icon-btn hdel', '×');
			del.type = 'button';
			del.title = 'Xoá cuộc thử này';
			del.setAttribute('aria-label', `Xoá cuộc thử: ${x.title}`);
			del.addEventListener('click', async () => {
				if (del.dataset.arm !== '1') { del.dataset.arm = '1'; del.textContent = 'Xoá?'; return; }
				await api(`/test/session?sid=${encodeURIComponent(x.sid)}`, { method: 'DELETE' }).catch((e) => toast(e.message));
				if (x.sid === state.sid) startNew();
				loadSessions().catch(() => {});
			});
			row.append(b, del);
			list.append(row);
		}
	}
	const closeHistory = () => { $('hist').hidden = true; $('histBtn').setAttribute('aria-expanded', 'false'); };

	// ------------------------------------------------------------ khung chat
	function renderLog() {
		const box = $('logInner');
		box.replaceChildren();
		if (!state.turns.length) {
			const e = el('div', 'empty');
			e.append(el('h2', '', 'Hỏi thử như một khách hàng'), el('p', '', 'Bot tra kiến thức, trả lời và xin thông tin liên hệ y như trên website. Chọn một câu trả lời để xem bot đã làm gì.'));
			const s = el('div', 'samples');
			for (const q of SAMPLES) {
				const b = el('button', '', q);
				b.type = 'button';
				b.addEventListener('click', () => send(q));
				s.append(b);
			}
			e.append(s);
			box.append(e);
			return;
		}
		state.turns.forEach((t, i) => box.append(t.role === 'user' ? userMsg(t) : botMsg(t, i)));
		$('log').scrollTop = $('log').scrollHeight;
	}

	function userMsg(t) {
		const m = el('div', 'msg user');
		m.append(el('div', 'bubble', t.text));
		return m;
	}

	function botMsg(t, i) {
		const m = el('div', 'msg bot' + (selected === i ? ' selected' : ''));
		m.dataset.i = i;
		const b = el('div', 'bubble');
		if (t.text) b.innerHTML = md(t.text);
		else {
			const ty = el('span', 'typing');
			ty.setAttribute('aria-label', 'Bot đang trả lời');
			ty.append(el('i'), el('i'), el('i'));
			b.append(ty);
		}
		if (t.pending && t.steps.length) {
			const st = el('div', 'steps');
			for (const s of t.steps.slice(-4)) st.append(el('span', '', s));
			m.append(st);
		}
		m.append(b);
		if (!t.pending) {
			const f = el('div', 'msg-foot');
			const tr = t.trace || {};
			const n = (tr.auto?.hits?.length || 0);
			const tools = (tr.tools || []).length;
			f.append(el('span', '', `${n} đoạn tài liệu · ${tools} lần gọi công cụ`));
			if (tr.blocked) f.append(el('span', 'chip c-bad', 'Bị chặn số liệu'));
			if (tr.error) f.append(el('span', 'chip c-bad', 'Lỗi'));
			if (tr.empty) f.append(el('span', 'chip c-warn', 'Không soạn được'));
			if ((tr.tools || []).some((x) => x.name === 'luu_khach_hang' || x.name === 'chuyen_nhan_vien')) f.append(el('span', 'chip c-acc', 'Báo nhân viên'));
			const btn = el('button', 'linkish', 'Bot đã làm gì?');
			btn.type = 'button';
			btn.addEventListener('click', () => select(i, true));
			f.append(btn);
			m.append(f);
		}
		return m;
	}

	function select(i, show) {
		selected = i;
		document.querySelectorAll('.msg.bot').forEach((n) => n.classList.toggle('selected', Number(n.dataset.i) === i));
		renderTrace();
		if (show && matchMedia('(max-width: 1060px)').matches) $('lab').classList.add('show-trace');
	}

	// ------------------------------------------------------------ "Bot da lam gi"
	function hitBox(h) {
		const d = el('details', 'hit');
		const s = el('summary');
		s.append(el('b', '', h.title), el('span', 'score', `đoạn ${h.chunk} · ${h.score}`));
		d.append(s, el('pre', '', h.text));
		return d;
	}

	function section(title, ...kids) {
		const s = el('section');
		s.append(el('span', 'eyebrow', title), ...kids);
		return s;
	}

	function renderTrace() {
		const body = $('traceBody');
		const t = state.turns[selected];
		$('traceEmpty').hidden = !!t;
		body.hidden = !t;
		body.replaceChildren();
		if (!t) return;
		const tr = t.trace || {};
		const q = state.turns[selected - 1];
		const wrap = el('div');
		wrap.style.cssText = 'display:flex;flex-direction:column;gap:16px';
		wrap.append(el('h2', '', 'Bot đã làm gì'));
		if (q) wrap.append(section('Khách hỏi', el('div', '', q.text)));
		if (tr.error) {
			const a = el('div', 'alert bad', 'Lỗi gọi LLM, khách nhận câu xin để lại liên hệ: ');
			a.append(el('pre', '', tr.error));
			wrap.append(a);
		}
		if (tr.auto) {
			const ql = el('div', 'tq');
			for (const x of tr.auto.queries) ql.append(el('span', '', x));
			const hits = el('div');
			hits.style.cssText = 'display:flex;flex-direction:column;gap:6px';
			if (tr.auto.hits.length) tr.auto.hits.forEach((h) => hits.append(hitBox(h)));
			else hits.append(el('div', 'hint', 'Không tìm thấy đoạn nào.'));
			wrap.append(section(`Tra tự động (${tr.auto.queries.length} lần)`, ql), section(`Đoạn tài liệu đưa cho bot (${tr.auto.hits.length})`, hits));
		}
		if ((tr.tools || []).length) {
			const list = el('div');
			list.style.cssText = 'display:flex;flex-direction:column;gap:6px';
			for (const x of tr.tools) {
				const b = el('div', 'tool');
				b.append(el('b', '', TOOL[x.name] || x.name));
				const args = Object.entries(x.args || {}).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join(' · ');
				if (args) b.append(el('code', '', args));
				const d = el('details', 'hit');
				const s = el('summary');
				s.append(el('b', '', 'Kết quả'));
				d.append(s, el('pre', '', x.result || ''));
				b.append(d);
				list.append(b);
			}
			wrap.append(section(`Bot tự gọi thêm (${tr.tools.length})`, list));
		}
		if (tr.blocked) {
			const a = el('div', 'alert bad', `Bị chặn: câu trả lời có số liệu không có trong tài liệu (${tr.blocked.numbers.join(', ')}). Khách nhận câu xin để lại liên hệ, Hộp thư (khi chạy thật) có sự kiện "Bot không trả lời được". Bản nháp bị chặn:`);
			a.append(el('pre', '', tr.blocked.draft));
			wrap.append(a);
		}
		if (tr.empty) wrap.append(el('div', 'alert warn', `Bot không soạn được câu trả lời sau ${tr.empty} vòng gọi công cụ, khách nhận câu xin để lại liên hệ. Thường do tài liệu thiếu thông tin này: bổ sung ở trang Kiến thức.`));
		if (!tr.auto && !tr.error) wrap.append(el('div', 'hint', 'Không có dữ liệu cho câu trả lời này.'));
		body.append(wrap);
	}

	// ------------------------------------------------------------ gui tin (SSE)
	async function send(text) {
		text = String(text || '').trim();
		if (!text || busy) return;
		let token = '';
		try { token = localStorage.getItem('token') || ''; } catch { /* bo qua */ }
		if (!token) return authScreen(document.querySelector('main'));
		busy = true;
		$('send').disabled = true;
		state.turns.push({ role: 'user', text });
		const bot = { role: 'bot', text: '', steps: [], trace: { tools: [] }, pending: true };
		state.turns.push(bot);
		const i = state.turns.length - 1;
		renderLog();
		let raf = 0;
		const paint = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; renderLog(); }); };
		try {
			const res = await fetch('/api/v1/cqf/test/stream', {
				method: 'POST',
				headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
				body: JSON.stringify({ sid: state.sid, text })
			});
			if (res.status === 401 || res.status === 403) throw new AuthError('auth');
			if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Lỗi ${res.status}`);
			const reader = res.body.getReader();
			const dec = new TextDecoder();
			let buf = '';
			for (;;) {
				const { value, done } = await reader.read();
				if (done) break;
				buf += dec.decode(value, { stream: true });
				let cut;
				while ((cut = buf.indexOf('\n\n')) >= 0) {
					const chunk = buf.slice(0, cut);
					buf = buf.slice(cut + 2);
					const line = chunk.split('\n').find((l) => l.startsWith('data:'));
					if (!line) continue;
					let ev;
					try { ev = JSON.parse(line.slice(5)); } catch { continue; }
					if (ev.type === 'status') bot.steps.push(ev.text);
					else if (ev.type === 'delta') bot.text += ev.text;
					else if (ev.type === 'replace') bot.text = ev.text;
					else if (ev.type === 'trace') {
						if (ev.step === 'auto') bot.trace.auto = { queries: ev.queries, hits: ev.hits };
						else if (ev.step === 'tool') bot.trace.tools.push({ name: ev.name, args: ev.args, result: ev.result });
						else if (ev.step === 'blocked') bot.trace.blocked = { numbers: ev.numbers, draft: ev.draft };
						else if (ev.step === 'empty') bot.trace.empty = ev.rounds;
						else if (ev.step === 'error') bot.trace.error = ev.text;
					}
					paint();
				}
			}
		} catch (e) {
			if (e instanceof AuthError) return authScreen(document.querySelector('main'));
			bot.text = bot.text || '';
			bot.trace.error = e.message || String(e);
			toast(e.message || 'Không gửi được');
		} finally {
			bot.pending = false;
			if (!bot.text) bot.text = '_(không có câu trả lời)_';
			busy = false;
			$('send').disabled = false;
			remember(state.sid);
			renderLog();
			select(i, false);
			loadSessions().catch(() => {}); // server da luu luot nay
		}
	}

	// ------------------------------------------------------------ khoi dong
	const ta = $('text');
	const grow = () => { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`; };
	ta.addEventListener('input', grow);
	ta.addEventListener('keydown', (e) => {
		if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('form').requestSubmit(); }
	});
	$('form').addEventListener('submit', (e) => {
		e.preventDefault();
		const v = ta.value;
		ta.value = '';
		grow();
		send(v);
		ta.focus();
	});
	$('newChat').addEventListener('click', startNew);
	$('histBtn').addEventListener('click', () => {
		const h = $('hist');
		h.hidden = !h.hidden;
		$('histBtn').setAttribute('aria-expanded', String(!h.hidden));
	});
	document.addEventListener('click', (e) => { if (!e.target.closest('#hist, #histBtn')) closeHistory(); });
	document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeHistory(); });
	$('backToChat').addEventListener('click', () => $('lab').classList.remove('show-trace'));

	(async () => {
		try {
			const { settings: s } = await api('/settings');
			const chip = $('botState');
			if (!s.llm?.base_url || !s.llm?.model) { chip.className = 'chip c-bad'; chip.textContent = 'Chưa cấu hình LLM (trang Chatbot)'; }
			else if (s.enabled) { chip.className = 'chip c-ok'; chip.textContent = 'Đang bật trên website'; }
			else { chip.className = 'chip c-warn'; chip.textContent = 'Đang tắt trên website, vẫn thử được'; }
		} catch (e) {
			if (e instanceof AuthError) return authScreen(document.querySelector('main'));
			$('botState').hidden = true;
		}
		try { await loadSessions(); } catch (e) { if (e instanceof AuthError) return authScreen(document.querySelector('main')); }
		const want = remembered();
		if (sessions.some((x) => x.sid === want)) await open(want);
		else if (sessions.length) await open(sessions[0].sid);
		else startNew();
		ta.focus();
	})();
})();
