/*
 * Trang Hop thu (xem index.html). Doc chi muc cqf_inbox trong chat ghim "Tong quan hop thu" (Hermes ghi),
 * tai chat cua khach khi bam, nut xu ly goi Hermes. Moi chu cua khach dua vao trang bang textContent.
 */
(() => {
	'use strict';

	const OVERVIEW_TITLE = 'Tổng quan hộp thư';
	const POLL_MS = 5000;
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
		mo_lai: ['Mở lại', 'acc']
	};

	const $ = (id) => document.getElementById(id);
	const state = { index: null, overviewId: null, tab: 'all', q: '', channel: '', sort: 'new', selected: null, chat: null, chatAt: 0 };
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

	// ------------------------------------------------------------ API
	async function api(path, opts = {}) {
		const token = localStorage.getItem('token');
		if (!token) throw Object.assign(new Error('auth'), { auth: true });
		const res = await fetch(path, { ...opts, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...(opts.headers || {}) } });
		if (res.status === 401) throw Object.assign(new Error('auth'), { auth: true });
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		return res.json();
	}

	async function loadIndex() {
		if (!state.overviewId) {
			const pinned = await api('/api/v1/chats/pinned');
			const hit = pinned.find((c) => c.title === OVERVIEW_TITLE);
			if (!hit) return null;
			state.overviewId = hit.id;
		}
		try {
			const res = await api(`/api/v1/chats/${state.overviewId}`);
			return res.chat?.cqf_inbox || null;
		} catch (e) {
			state.overviewId = null; // chat tong quan bi xoa: tim lai lan sau
			throw e;
		}
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
		let rows = items.filter((it) => (state.tab === 'all' || it.status === state.tab) && (!state.channel || it.kenh === state.channel));
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
			const snippet = el('div', 'snippet', who + (it.last_text || it.first_q || 'Khách mới nhắn'));
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
			$('listEmptyText').textContent = items.length
				? 'Không có khách nào khớp bộ lọc.'
				: 'Chưa có cuộc trò chuyện. Khách nhắn qua khung chat trên website sẽ hiện ở đây.';
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
			const res = await api(`/api/v1/chats/${it.chat_id}`);
			if (state.selected !== it.conv) return;
			state.chat = res.chat;
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

	function messages(chat) {
		const hist = chat?.history;
		if (!hist?.messages) return chat?.messages || [];
		const out = [];
		let cur = hist.currentId;
		const guard = new Set();
		while (cur && hist.messages[cur] && !guard.has(cur)) {
			guard.add(cur);
			out.push(hist.messages[cur]);
			cur = hist.messages[cur].parentId;
		}
		return out.reverse();
	}

	function renderDetail() {
		const it = current();
		$('detailEmpty').hidden = !!it;
		$('detailView').hidden = !it;
		if (!it) return;
		avatar(it, $('dAvatar'));
		$('dName').textContent = nameOf(it);
		const [label] = STATUS[it.status] || [it.status];
		$('dSub').textContent = `Chat website · ${label}${it.note ? ' · ' + it.note : ''}`;

		const acts = $('dActions');
		acts.replaceChildren();
		(ACTIONS[it.status] || []).forEach((a, i) => {
			const b = el('button', i === 0 ? 'btn primary' : 'btn', ACTION_LABEL[a]);
			b.addEventListener('click', () => act(it, a, acts));
			acts.append(b);
		});
		const open = el('a', 'btn', 'Mở trong Open WebUI');
		open.href = `/c/${encodeURIComponent(it.chat_id)}`;
		acts.append(open);

		const kv = $('kv');
		kv.replaceChildren();
		const pr = it.profile || {};
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
		messages(state.chat).forEach((m, i) => {
			const text = String(m.content || '');
			if (i === 0 && m.role === 'assistant' && text.startsWith('Thẻ khách')) return; // the khach: da co o cot phai
			const ts = m.timestamp || 0;
			const day = ts ? new Date(ts * 1000).toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit' }) : '';
			if (day && day !== lastDay) { th.append(el('span', 'day', day)); lastDay = day; }
			if (m.role === 'assistant' && (text.startsWith('🔔') || text.startsWith('Chủ shop bấm:'))) {
				const isAction = text.startsWith('Chủ shop bấm:');
				const ev = el('div', `event ${isAction ? 'acc' : text.includes('không trả lời được') ? 'bad' : ''}`);
				const [head, ...rest] = text.replace(/^🔔\s*/, '').split(' — ');
				ev.append(el('b', '', head), document.createTextNode(rest.join(' — ')));
				th.append(ev);
				return;
			}
			const who = m.role === 'user' ? 'Khách' : 'Chatbot';
			const box = el('div', `msg ${m.role === 'user' ? 'in' : 'out'}`);
			box.append(el('span', 'meta', `${who} · ${ts ? new Date(ts * 1000).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }) : ''}`), el('div', 'text', text));
			th.append(box);
		});
		if (atBottom || !th.dataset.conv || th.dataset.conv !== it.conv) th.scrollTop = th.scrollHeight;
		th.dataset.conv = it.conv;
	}

	async function act(it, action, box) {
		const url = state.index?.action_url;
		if (!url) return toast('Chưa cấu hình webchat.public_url bên Hermes nên chưa bấm được.');
		box.querySelectorAll('button').forEach((b) => (b.disabled = true));
		try {
			const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ conv: it.conv, sig: it.sig, action }) });
			if (!res.ok) throw new Error(res.status);
			toast(`Đã ghi nhận: ${ACTION_LABEL[action]}`);
			setTimeout(tick, 2500); // Hermes ghi xong chi muc sau ~2 giay
			setTimeout(tick, 5000);
		} catch {
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
		$('listEmptyText').innerHTML = 'Bạn cần <a href="/auth">đăng nhập Open WebUI</a> rồi mở lại trang này.';
	}

	// ------------------------------------------------------------ vong lap
	let busy = false;
	async function tick() {
		if (busy || document.hidden) return;
		busy = true;
		try {
			const idx = await loadIndex();
			if (!idx) {
				state.index = { items: [] };
				live(true, 'Chưa có dữ liệu từ chatbot');
			} else {
				state.index = idx;
				live(true, `Cập nhật ${new Date().toLocaleTimeString('vi-VN')}`);
			}
			renderList();
			if (state.selected) { renderDetail(); await refreshChat(false); }
		} catch (e) {
			if (e.auth) authFail();
			else live(false, 'Mất kết nối, đang thử lại…');
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
	setInterval(tick, POLL_MS);
})();
