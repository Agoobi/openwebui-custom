/*
 * Trang Hop thu (xem index.html). Du lieu o backend cqf_openwebui chay trong Open WebUI: /api/v1/cqf/inbox/*,
 * dang nhap bang token Open WebUI (localStorage.token). Moi chu cua khach dua vao trang bang textContent.
 */
(() => {
	'use strict';

	const POLL_MS = 4000;
	const STATUS = {
		can_xu_ly: ['Cần xử lý', 'c-warn'],
		dang_chat: ['Đang chat', 'c-acc'],
		da_xong: ['Đã xong', 'c-ok']
	};
	const ACTIONS = { can_xu_ly: ['da_goi', 'xong'], dang_chat: ['xong'], da_xong: ['mo_lai'] };
	const ACTION_LABEL = { da_goi: 'Đã gọi', xong: 'Xong', mo_lai: 'Mở lại' };
	const PROFILE = [
		['ten', 'Tên'], ['sdt', 'SĐT'], ['zalo', 'Zalo'], ['email', 'Email'], ['cong_ty', 'Công ty'],
		['dia_chi', 'Địa chỉ'], ['thoi_gian', 'Giờ tiện gọi'], ['nhu_cau', 'Nhu cầu']
	];
	const EVENT = {
		lead: ['Khách để lại thông tin', ''], handoff: ['Khách cần gặp nhân viên', ''],
		guard_blocked: ['Bot không trả lời được', 'bad'], da_goi: ['Đã gọi', 'acc'], xong: ['Xong', 'acc'],
		mo_lai: ['Mở lại', 'acc'], sua_thong_tin: ['Sửa thông tin khách', 'acc']
	};
	const EDIT_FIELDS = [['ten', 'Tên'], ['sdt', 'SĐT'], ['zalo', 'Zalo'], ['email', 'Email'], ['nhu_cau', 'Nhu cầu']];

	// Markdown cua bot (danh sach, bang, dam, link): escape truoc roi moi dinh dang
	const escHtml = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
	const mdInline = (s) => escHtml(s)
		.replace(/`([^`]+)`/g, '<code>$1</code>')
		.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
		.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
	function mdBlock(text) {
		const out = [];
		let list = null, para = [], table = null;
		const fp = () => { if (para.length) { out.push(`<p>${para.map(mdInline).join('<br>')}</p>`); para = []; } };
		const fl = () => { if (list) { out.push(`<${list.t}>${list.i.map((x) => `<li>${mdInline(x)}</li>`).join('')}</${list.t}>`); list = null; } };
		const ft = () => {
			if (!table) return;
			const rows = table.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r)).map((r) => r.replace(/^\s*\||\|\s*$/g, '').split('|').map((c) => mdInline(c.trim())));
			out.push(`<div class="tw"><table><tr>${rows[0].map((c) => `<th>${c}</th>`).join('')}</tr>${rows.slice(1).map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</table></div>`);
			table = null;
		};
		for (const line of String(text).split('\n')) {
			const st = line.trim();
			let m;
			if (!st) { fp(); fl(); ft(); continue; }
			if (st.startsWith('|')) { fp(); fl(); (table ||= []).push(st); continue; }
			if ((m = st.match(/^([-*+•]|\d+[.)])\s+(.*)$/))) {
				fp(); ft();
				const t = /\d/.test(m[1]) ? 'ol' : 'ul';
				if (list && list.t !== t) fl();
				(list ||= { t, i: [] }).i.push(m[2]);
				continue;
			}
			if ((m = st.match(/^#{1,6}\s+(.*)$/))) { fp(); fl(); ft(); out.push(`<p><strong>${mdInline(m[1])}</strong></p>`); continue; }
			fl(); ft(); para.push(st);
		}
		fp(); fl(); ft();
		return out.join('');
	}
	const EVENT_FIELDS = [
		...[['ten', 'Tên'], ['sdt', 'SĐT'], ['zalo', 'Zalo'], ['email', 'Email'], ['cong_ty', 'Công ty'],
			['dia_chi', 'Địa chỉ'], ['thoi_gian', 'Giờ tiện gọi'], ['nhu_cau', 'Nhu cầu']],
		['ly_do', 'Lý do'], ['tom_tat', 'Tóm tắt'], ['lien_he', 'Liên hệ'], ['khach_hoi', 'Khách hỏi'],
		['so_lieu_khong_co_can_cu', 'Số liệu không có trong tài liệu'], ['by', 'Người bấm']
	];

	const $ = (id) => document.getElementById(id);
	const state = { index: null, tab: 'all', q: '', channel: '', sort: 'new', selected: null, chat: null, chatAt: 0 };
	const seen = load('cqf-inbox-seen', {});

	function load(key, fallback) {
		try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
	}
	function save(key, value) {
		try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* trinh duyet chan luu: bo qua */ }
	}

	// ------------------------------------------------------------ giao dien Open WebUI (sang / toi)
	const theme = localStorage.getItem('theme') || 'system';
	const dark = theme === 'dark' || theme === 'oled-dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
	document.documentElement.classList.toggle('dark', dark);

	// Nhung trong Open WebUI (loader.js mo ?embed=1 canh sidebar): nut goc trai mo sidebar cua Open WebUI (dien thoai)
	const embed = new URLSearchParams(location.search).has('embed') && window.parent !== window;
	document.documentElement.classList.toggle('embed', embed);
	const tell = (msg) => { if (embed) window.parent.postMessage(msg, location.origin); };
	if (embed) {
		const home = document.getElementById('homeBtn');
		home.title = 'Mở sidebar';
		home.setAttribute('aria-label', 'Mở sidebar');
		home.addEventListener('click', (e) => { e.preventDefault(); tell({ type: 'cqf-toggle-sidebar' }); });
	}

	// ------------------------------------------------------------ API
	async function api(path, opts = {}) {
		const token = localStorage.getItem('token');
		if (!token) throw Object.assign(new Error('auth'), { auth: true });
		const res = await fetch('/api/v1/cqf' + path, { ...opts, headers: { Authorization: `Bearer ${token}`, ...(opts.body ? { 'Content-Type': 'application/json' } : {}) } });
		if (res.status === 401 || res.status === 403) throw Object.assign(new Error('auth'), { auth: true });
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		return res.json();
	}

	async function loadIndex() {
		return api('/inbox/index');
	}

	// ------------------------------------------------------------ dinh dang
	function ago(ts) {
		if (!ts) return '';
		const s = Math.max(0, Date.now() / 1000 - ts);
		if (s < 60) return 'vừa xong';
		if (s < 3600) return `${Math.floor(s / 60)} phút`;
		const d = new Date(ts * 1000);
		const today = new Date();
		if (d.toDateString() === today.toDateString()) return d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
		return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
	}
	function clock(ts) {
		return ts ? new Date(ts * 1000).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }) : '—';
	}
	function nameOf(it) {
		return it.profile?.ten || `Khách ${String(it.conv).split(':').pop().slice(0, 4)}`;
	}
	function initial(it) {
		return (it.profile?.ten || '#').trim().charAt(0).toUpperCase();
	}
	function waitStart(it) {
		const ev = (it.events || []).filter((e) => ['lead', 'handoff', 'guard_blocked'].includes(e.kind)).pop();
		return ev?.t || it.last_user_at || it.last_at;
	}
	function el(tag, cls, text) {
		const n = document.createElement(tag);
		if (cls) n.className = cls;
		if (text != null) n.textContent = text;
		return n;
	}
	const GLOBE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/></svg>';

	function avatar(it, node) {
		node.textContent = initial(it);
		const ch = el('span', 'ch');
		ch.innerHTML = GLOBE; // icon co dinh, khong co chu cua khach
		ch.title = 'Chat website';
		node.append(ch);
		return node;
	}

	// ------------------------------------------------------------ danh sach
	function visible() {
		const items = state.index?.items || [];
		const q = state.q.trim().toLowerCase();
		// "Tat ca" = moi khach CHUA xong; khach da xong chi hien o tab "Da xong"
		let rows = items.filter((it) => (state.tab === 'all' ? it.status !== 'da_xong' : it.status === state.tab) && (!state.channel || it.kenh === state.channel));
		if (q) {
			rows = rows.filter((it) => [nameOf(it), it.title, it.last_text, it.first_q, ...Object.values(it.profile || {})]
				.some((v) => String(v || '').toLowerCase().includes(q)));
		}
		if (state.sort === 'wait') {
			rows = rows.filter((it) => it.status !== 'da_xong').sort((a, b) => (waitStart(a) || 0) - (waitStart(b) || 0));
		} else {
			rows = rows.sort((a, b) => (b.last_at || 0) - (a.last_at || 0));
		}
		return rows;
	}

	function renderList() {
		const items = state.index?.items || [];
		const todo = items.filter((it) => it.status === 'can_xu_ly').length;
		tell({ type: 'cqf-inbox-count', todo });
		const nTodo = $('nTodo');
		nTodo.textContent = todo || '';
		nTodo.className = todo ? 'n hot' : 'n';
		const rows = visible();
		$('count').textContent = rows.length ? `${rows.length} khách` : '';
		const ul = $('items');
		ul.replaceChildren();
		for (const it of rows) {
			const li = el('li', 'item');
			li.setAttribute('role', 'option');
			li.tabIndex = 0;
			li.dataset.conv = it.conv;
			li.setAttribute('aria-selected', String(it.conv === state.selected));
			const unread = it.last_role === 'user' && (seen[it.conv] || 0) < (it.last_user_at || 0) && it.conv !== state.selected;
			if (unread) li.classList.add('unread');
			const body = el('div');
			body.style.minWidth = '0';
			const row1 = el('div', 'row1');
			row1.append(el('span', 'name', nameOf(it)), el('span', 'when', ago(it.last_at)));
			const who = it.last_role === 'assistant' ? 'Bot: ' : '';
			const plain = String(it.last_text || it.first_q || 'Khách mới nhắn').replace(/\*\*|__|`|^#+\s*|\|/gm, '').replace(/\s+/g, ' ');
			const snippet = el('div', 'snippet', who + plain);
			const chips = el('div', 'chips');
			const [label, cls] = STATUS[it.status] || [it.status, 'c-muted'];
			chips.append(el('span', `chip ${cls}`, label));
			if (it.profile?.sdt || it.profile?.zalo) chips.append(el('span', 'chip c-muted', it.profile.sdt || `Zalo ${it.profile.zalo}`));
			if (it.blocked) chips.append(el('span', 'chip c-bad', `Bot bị chặn ${it.blocked}`));
			if (it.status === 'can_xu_ly') chips.append(el('span', 'chip c-muted', `chờ ${ago(waitStart(it)).replace('vừa xong', '< 1 phút')}`));
			body.append(row1, snippet, chips);
			li.append(avatar(it, el('div', 'avatar')), body);
			if (unread) li.append(el('span', 'dot'));
			li.addEventListener('click', () => select(it.conv));
			li.addEventListener('keydown', (e) => {
				if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(it.conv); }
				if (e.key === 'ArrowDown') li.nextElementSibling?.focus();
				if (e.key === 'ArrowUp') li.previousElementSibling?.focus();
			});
			ul.append(li);
		}
		const empty = !rows.length;
		$('listEmpty').hidden = !empty;
		ul.hidden = empty;
		if (empty) {
			const filtered = state.q.trim() || state.channel;
			$('listEmptyText').textContent = !items.length
				? 'Chưa có cuộc trò chuyện. Khách nhắn qua khung chat trên website sẽ hiện ở đây.'
				: filtered ? 'Không có khách nào khớp bộ lọc.'
				: state.tab === 'all' ? 'Không còn khách nào đang chờ. Khách đã xong nằm ở tab Đã xong.'
				: 'Không có khách nào ở mục này.';
		}
	}

	// ------------------------------------------------------------ chi tiet
	function current() {
		return (state.index?.items || []).find((it) => it.conv === state.selected) || null;
	}

	async function select(conv) {
		state.selected = conv;
		state.chat = null;
		state.chatAt = 0;
		$('shell').classList.add('has-detail');
		try { history.replaceState(null, '', `#${encodeURIComponent(conv)}`); } catch { /* bo qua */ }
		renderList();
		renderDetail();
		await refreshChat(true);
	}

	async function refreshChat(force) {
		const it = current();
		if (!it) return;
		const version = `${it.n}:${it.last_at}`; // n tang ca khi co su kien / nut bam (khong doi last_at)
		if (!force && state.chatAt === version) return;
		try {
			const res = await api(`/inbox/conv?c=${encodeURIComponent(it.conv)}`);
			if (state.selected !== it.conv) return;
			state.chat = res.messages || [];
			state.chatAt = version;
			seen[it.conv] = Math.max(seen[it.conv] || 0, it.last_user_at || 0);
			save('cqf-inbox-seen', seen);
			renderDetail();
			renderList();
		} catch (e) {
			if (e.auth) return authFail();
			toast('Không tải được cuộc trò chuyện. Thử lại sau.');
		}
	}

	function editForm(it, kv) {
		kv.dataset.editing = it.conv;
		kv.replaceChildren();
		const form = el('form', 'editform');
		const inputs = {};
		for (const [k, l] of EDIT_FIELDS) {
			const lab = el('label');
			lab.append(el('span', '', l));
			const inp = el(k === 'nhu_cau' ? 'textarea' : 'input');
			inp.value = (it.profile || {})[k] || '';
			inp.id = `edit-${k}`;
			if (k === 'sdt' || k === 'zalo') inp.inputMode = 'tel';
			inputs[k] = inp;
			lab.append(inp);
			form.append(lab);
		}
		const row = el('div', 'editbtns');
		const ok = el('button', 'btn primary small', 'Lưu');
		ok.type = 'submit';
		const cancel = el('button', 'btn small', 'Huỷ');
		cancel.type = 'button';
		cancel.addEventListener('click', () => { state.editing = null; renderDetail(); });
		row.append(ok, cancel);
		form.append(row);
		form.addEventListener('submit', async (e) => {
			e.preventDefault();
			ok.disabled = true;
			try {
				const profile = Object.fromEntries(EDIT_FIELDS.map(([k]) => [k, inputs[k].value.trim()]));
				await api('/inbox/profile', { method: 'POST', body: JSON.stringify({ conv: it.conv, profile }) });
				state.editing = null;
				toast('Đã lưu thông tin khách');
				await tick(true);
			} catch (err) {
				if (err.auth) return authFail();
				toast('Không lưu được. Thử lại.');
				ok.disabled = false;
			}
		});
		kv.append(form);
		inputs.ten.focus();
	}

	function noteText(note) {
		if (!note || typeof note !== 'object') return note ? String(note) : '';
		return `${ACTION_LABEL[note.action] || note.action} lúc ${clock(note.t)}${note.by ? ' · ' + note.by : ''}`;
	}

	function eventNode(m) {
		const [label, tone] = EVENT[m.kind] || [m.kind, ''];
		const ev = el('div', `event ${tone}`);
		ev.append(el('b', '', `${label} · ${new Date(m.t * 1000).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`));
		const d = m.data || {};
		const parts = EVENT_FIELDS.filter(([k]) => d[k]).map(([k, l]) => `${l}: ${Array.isArray(d[k]) ? d[k].join(', ') : d[k]}`);
		if (parts.length) ev.append(document.createTextNode(parts.join(' · ')));
		return ev;
	}

	function renderDetail() {
		const it = current();
		$('detailEmpty').hidden = !!it;
		$('detailView').hidden = !it;
		if (!it) return;
		avatar(it, $('dAvatar'));
		$('dName').textContent = nameOf(it);
		const [label] = STATUS[it.status] || [it.status];
		const note = noteText(it.note);
		$('dSub').textContent = `Chat website · ${label}${note ? ' · ' + note : ''}`;

		const acts = $('dActions');
		acts.replaceChildren();
		(ACTIONS[it.status] || []).forEach((a, i) => {
			const b = el('button', i === 0 ? 'btn primary' : 'btn', ACTION_LABEL[a]);
			b.addEventListener('click', () => act(it, a, acts));
			acts.append(b);
		});

		const kv = $('kv');
		const pr = it.profile || {};
		if (state.editing === it.conv) {
			if (kv.dataset.editing !== it.conv) editForm(it, kv); // dang sua: khong ve lai moi lan lam moi
		} else {
			kv.dataset.editing = '';
			kv.replaceChildren();
			const rows = PROFILE.filter(([k]) => pr[k]).map(([k, l]) => [l, pr[k], k]);
			if (!rows.length) rows.push(['Liên hệ', 'Khách chưa để lại thông tin']);
			for (const [l, v, k] of rows) {
				const d = el('div');
				const dd = el('dd', k === 'sdt' || k === 'zalo' ? 'num' : '', v);
				if (k === 'sdt' || k === 'zalo') {
					const c = el('button', 'copy', 'Chép');
					c.addEventListener('click', () => copy(v));
					dd.append(c);
				}
				d.append(el('dt', '', l), dd);
				kv.append(d);
			}
			const edit = el('button', 'btn small', 'Sửa thông tin');
			edit.addEventListener('click', () => { state.editing = it.conv; renderDetail(); });
			kv.append(edit);
		}
		const kv2 = $('kv2');
		kv2.replaceChildren();
		for (const [l, v, num] of [['Trang đang xem', it.page || '—'], ['Lần đầu nhắn', clock(it.first_at), 1],
			['Tin nhắn cuối', clock(it.last_at), 1], ['Số tin', it.msgs, 1], ['Bot bị chặn', it.blocked || 0, 1]]) {
			const d = el('div');
			d.append(el('dt', '', l), el('dd', num ? 'num' : '', String(v)));
			kv2.append(d);
		}

		const th = $('thread');
		const atBottom = th.scrollHeight - th.scrollTop - th.clientHeight < 40;
		th.replaceChildren();
		if (!state.chat) {
			th.append(el('p', 'hint', 'Đang tải tin nhắn…'));
			return;
		}
		let lastDay = '';
		for (const m of state.chat) {
			const ts = m.t || 0;
			const day = ts ? new Date(ts * 1000).toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit' }) : '';
			if (day && day !== lastDay) { th.append(el('span', 'day', day)); lastDay = day; }
			if (m.role === 'event') { th.append(eventNode(m)); continue; }
			const who = m.role === 'user' ? 'Khách' : 'Chatbot';
			const box = el('div', `msg ${m.role === 'user' ? 'in' : 'out'}`);
			const body = el('div', m.role === 'user' ? 'text' : 'text md');
			if (m.role === 'user') body.textContent = String(m.text || '');
			else body.innerHTML = mdBlock(m.text || ''); // escape truoc trong mdBlock
			box.append(el('span', 'meta', `${who} · ${ts ? new Date(ts * 1000).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }) : ''}`), body);
			th.append(box);
		}
		if (atBottom || th.dataset.conv !== it.conv) th.scrollTop = th.scrollHeight;
		th.dataset.conv = it.conv;
	}

	async function act(it, action, box) {
		box.querySelectorAll('button').forEach((b) => (b.disabled = true));
		try {
			await api('/inbox/action', { method: 'POST', body: JSON.stringify({ conv: it.conv, action }) });
			toast(`Đã ghi nhận: ${ACTION_LABEL[action]}`);
			await tick(true);
		} catch (e) {
			if (e.auth) return authFail();
			toast('Không gửi được tới Hermes. Thử lại.');
			box.querySelectorAll('button').forEach((b) => (b.disabled = false));
		}
	}

	// ------------------------------------------------------------ tien ich
	let toastTimer;
	function toast(text) {
		const t = $('toast');
		t.textContent = text;
		t.hidden = false;
		clearTimeout(toastTimer);
		toastTimer = setTimeout(() => (t.hidden = true), 2600);
	}
	async function copy(text) {
		try { await navigator.clipboard.writeText(text); toast('Đã chép'); } catch { toast(text); }
	}
	function live(ok, text) {
		$('live').classList.toggle('off', !ok);
		$('liveText').textContent = text;
	}
	function authFail() {
		live(false, 'Chưa đăng nhập');
		$('items').replaceChildren();
		$('listEmpty').hidden = false;
		$('listEmptyText').innerHTML = 'Cần <a href="/auth">đăng nhập Open WebUI</a> bằng tài khoản được xem Hộp thư (mặc định: quản trị viên) rồi mở lại trang này.';
	}

	function configFail() {
		live(false, 'Chưa cấu hình');
		$('items').replaceChildren();
		$('listEmpty').hidden = false;
		$('listEmptyText').textContent = 'Chưa biết địa chỉ Hermes: cài lại openwebui-custom với HERMES_INBOX_URL.';
	}

	// ------------------------------------------------------------ vong lap
	let busy = false;
	async function tick(now) {
		if (busy || (document.hidden && !now)) return;
		busy = true;
		try {
			state.index = await loadIndex();
			live(true, `Cập nhật ${new Date().toLocaleTimeString('vi-VN')}`);
			renderList();
			if (state.selected) { renderDetail(); await refreshChat(false); }
		} catch (e) {
			if (e.auth) authFail();
			else if (e.config) configFail();
			else live(false, 'Mất kết nối tới Hermes, đang thử lại…');
		} finally {
			busy = false;
		}
	}

	// ------------------------------------------------------------ su kien
	$('tabs').addEventListener('click', (e) => {
		const b = e.target.closest('[data-tab]');
		if (!b) return;
		state.tab = b.dataset.tab;
		document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-selected', String(t === b)));
		renderList();
	});
	$('q').addEventListener('input', (e) => { state.q = e.target.value; renderList(); });
	$('channel').addEventListener('change', (e) => { state.channel = e.target.value; renderList(); });
	for (const [id, sort] of [['sortNew', 'new'], ['sortWait', 'wait']]) {
		$(id).addEventListener('click', () => {
			state.sort = sort;
			$('sortNew').setAttribute('aria-pressed', String(sort === 'new'));
			$('sortWait').setAttribute('aria-pressed', String(sort === 'wait'));
			renderList();
		});
	}
	$('back').addEventListener('click', () => {
		state.selected = null;
		$('shell').classList.remove('has-detail');
		try { history.replaceState(null, '', location.pathname); } catch { /* bo qua */ }
		renderList();
		renderDetail();
	});
	document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });

	const fromHash = decodeURIComponent(location.hash.slice(1));
	tick().then(() => { if (fromHash && current() == null && (state.index?.items || []).some((it) => it.conv === fromHash)) select(fromHash); });
	setInterval(() => tick(), POLL_MS);
})();
