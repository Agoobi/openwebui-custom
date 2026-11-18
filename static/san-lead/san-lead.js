/* San lead (Open WebUI): co hoi B2B va nguoi ra quyet dinh do agent Hermes (skill san-lead-b2b) tim.
 * Xem: Co hoi | Nguoi lien he | Lan quet | Cai dat | Quy tac. Backend /api/v1/cqf/lead (cqf_openwebui/lead/router.py).
 * Moi nguoi dung Open WebUI xem va doi trang thai; quan tri vien sua cai dat va key Apify. */
(() => {
	'use strict';
	const { el, toast, tell } = window.CQF;
	const root = document.getElementById('root');
	const PAGE = 60;

	const S = {
		me: null,
		view: 'co-hoi',
		opp: { items: [], total: 0, counts: {}, filters: { state: 'moi', industry: '', kind: '', province: '', contact: '', q: '', sort: 'score' }, limit: PAGE },
		people: { items: [], total: 0, filters: { state: '', role_group: '', q: '' }, limit: PAGE },
		runs: [],
		draft: null,
		dirty: false
	};

	// ------------------------------------------------------------ API (401 = dang nhap lai; loi khac hien chu cua server)
	class AuthError extends Error {}
	async function api(path, opts = {}) {
		let token = '';
		try { token = localStorage.getItem('token') || ''; } catch { /* bo qua */ }
		if (!token) throw new AuthError('auth');
		const res = await fetch('/api/v1/cqf/lead' + path, {
			...opts,
			headers: { Authorization: `Bearer ${token}`, ...(opts.body ? { 'Content-Type': 'application/json' } : {}) },
			body: opts.body ? JSON.stringify(opts.body) : undefined
		});
		if (res.status === 401) throw new AuthError('auth');
		const data = await res.json().catch(() => ({}));
		if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Lỗi ${res.status}`);
		return data;
	}
	const fail = (e) => {
		if (e instanceof AuthError) return authScreen();
		toast(e.message || 'Có lỗi, thử lại.');
	};
	function authScreen() {
		const box = el('div', 'empty');
		box.append(el('h2', '', 'Cần đăng nhập Open WebUI'));
		const p = el('p', '', 'Phiên đăng nhập đã hết. ');
		const a = el('a', '', 'Đăng nhập');
		a.href = '/auth';
		p.append(a, ' rồi mở lại trang này.');
		box.append(p);
		root.replaceChildren(box);
	}

	// ------------------------------------------------------------ tien ich
	const icon = (d, size = 15) => {
		const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
		s.setAttribute('viewBox', '0 0 24 24');
		s.setAttribute('width', size);
		s.setAttribute('height', size);
		s.setAttribute('fill', 'none');
		s.setAttribute('stroke', 'currentColor');
		s.setAttribute('stroke-width', '2');
		s.setAttribute('stroke-linecap', 'round');
		s.setAttribute('stroke-linejoin', 'round');
		s.setAttribute('aria-hidden', 'true');
		s.innerHTML = d;
		return s;
	};
	const I = {
		search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
		down: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
		close: '<path d="M18 6 6 18M6 6l12 12"/>',
		link: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
	};
	const day = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '');
	const ago = (ts) => {
		if (!ts) return '';
		const d = Math.floor((Date.now() / 1000 - ts) / 86400);
		return d <= 0 ? 'hôm nay' : d === 1 ? 'hôm qua' : `${d} ngày trước`;
	};
	const vnDate = (iso) => (iso ? iso.split('-').reverse().join('/') : '');
	const daysLeft = (iso) => {
		if (!iso) return null;
		const end = new Date(iso + 'T23:59:59+07:00').getTime();
		return Math.ceil((end - Date.now()) / 86400000);
	};
	const usd = (n) => `$${(Number(n) || 0).toFixed(2)}`;
	const chip = (text, cls = 'c-muted') => el('span', `chip ${cls}`, text);
	const scoreBox = (n) => {
		const b = el('div', `score ${n >= 70 ? 'hi' : n >= 50 ? 'mid' : ''}`, String(n));
		b.title = `Điểm ${n}/100`;
		return b;
	};
	const ext = (href, text) => {
		const a = el('a', '', text || href);
		a.href = href;
		a.target = '_blank';
		a.rel = 'noopener noreferrer';
		return a;
	};
	const field = (label, input, hint) => {
		const f = el('label', 'field');
		f.append(el('span', '', label), input);
		if (hint) f.append(el('small', 'hint', hint));
		return f;
	};
	const select = (options, value, onChange, label) => {
		const s = el('select', 'input');
		if (label) s.setAttribute('aria-label', label);
		for (const [v, t] of options) {
			const o = el('option', '', t);
			o.value = v;
			s.append(o);
		}
		s.value = value;
		s.addEventListener('change', () => onChange(s.value));
		return s;
	};
	const isAdmin = () => !!S.me?.user?.is_admin;

	// ------------------------------------------------------------ khung trang
	const VIEWS = [
		['co-hoi', 'Cơ hội'],
		['nguoi', 'Người liên hệ'],
		['lan-quet', 'Lần quét'],
		['cai-dat', 'Cài đặt'],
		['quy-tac', 'Quy tắc']
	];

	function render() {
		const frag = document.createDocumentFragment();
		const head = el('div', 'head');
		const left = el('div');
		left.append(el('h1', '', 'Săn lead'));
		const runs = S.me.runs || [];
		const last = runs[0];
		left.append(el('div', 'hint sub', last
			? `Lần quét gần nhất: ${day(last.started_at)} ${new Date(last.started_at * 1000).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })} · ${last.status === 'ok' ? 'xong' : last.status === 'running' ? 'đang chạy' : last.status === 'partial' ? 'xong một phần' : 'lỗi'}`
			: 'Chưa có lần quét nào. Agent Hermes quét theo lịch, hoặc nhắn Hermes "quét lead".'));
		head.append(left);
		const actions = el('div', 'actions');
		if (S.view === 'co-hoi' || S.view === 'nguoi') {
			const table = S.view === 'co-hoi' ? 'opportunities' : 'people';
			const a = el('a', 'btn');
			a.href = '#';
			a.append(icon(I.down), 'Xuất CSV');
			a.addEventListener('click', (e) => { e.preventDefault(); download(table); });
			actions.append(a);
		}
		head.append(actions);
		frag.append(head);

		const tabs = el('div', 'views');
		tabs.setAttribute('role', 'tablist');
		for (const [key, label] of VIEWS) {
			const b = el('button', '', label);
			b.setAttribute('role', 'tab');
			b.setAttribute('aria-selected', String(S.view === key));
			if (key === 'co-hoi') b.append(el('span', 'n', String(S.opp.counts.moi ?? '')));
			b.addEventListener('click', () => go(key));
			tabs.append(b);
		}
		frag.append(tabs);

		if (!S.me.apify.set && S.view !== 'cai-dat') {
			const ban = el('div', 'banner');
			const t = el('div');
			t.append(el('b', '', 'Chưa có key Apify. '), 'Không có key, agent chỉ quét được Google News và các trang theo dõi; không tìm Google và LinkedIn được.');
			ban.append(t);
			if (isAdmin()) {
				const b = el('button', 'btn', 'Nhập key');
				b.addEventListener('click', () => go('cai-dat'));
				ban.append(b);
			}
			frag.append(ban);
		}

		const body = el('div');
		body.id = 'view';
		frag.append(body);
		root.replaceChildren(frag);
		({ 'co-hoi': viewOpp, nguoi: viewPeople, 'lan-quet': viewRuns, 'cai-dat': viewSettings, 'quy-tac': viewRules })[S.view](body);
	}

	function go(view) {
		if (S.dirty && S.view === 'cai-dat' && view !== 'cai-dat' && !confirm('Cài đặt chưa lưu. Bỏ thay đổi?')) return;
		S.dirty = false;
		S.draft = null;
		S.view = view;
		tell({ type: 'cqf-hash', hash: view === 'co-hoi' ? 'san-lead' : `san-lead/${view}` });
		load();
	}

	async function download(table) {
		try {
			let token = '';
			try { token = localStorage.getItem('token') || ''; } catch { /* bo qua */ }
			const res = await fetch(`/api/v1/cqf/lead/export/${table}.csv`, { headers: { Authorization: `Bearer ${token}` } });
			if (!res.ok) throw new Error(`Lỗi ${res.status}`);
			const blob = await res.blob();
			const a = document.createElement('a');
			a.href = URL.createObjectURL(blob);
			a.download = table === 'opportunities' ? 'san-lead-co-hoi.csv' : 'san-lead-nguoi-lien-he.csv';
			a.click();
			setTimeout(() => URL.revokeObjectURL(a.href), 2000);
		} catch (e) { fail(e); }
	}

	// ------------------------------------------------------------ Co hoi
	const qs = (obj) => new URLSearchParams(Object.entries(obj).filter(([, v]) => v !== '' && v != null)).toString();

	async function fetchOpp() {
		const f = S.opp.filters;
		const data = await api(`/opportunities?${qs({ ...f, state: f.state === 'all' ? '' : f.state, limit: S.opp.limit })}`);
		Object.assign(S.opp, data);
	}

	function viewOpp(box) {
		const m = S.me;
		const f = S.opp.filters;
		const bar = el('div', 'filters');
		const search = el('div', 'search');
		const q = el('input', 'input');
		q.type = 'search';
		q.placeholder = 'Tìm công ty, thiết bị, tỉnh (cả tên tỉnh cũ)…';
		q.value = f.q;
		q.setAttribute('aria-label', 'Tìm cơ hội');
		let timer;
		q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { f.q = q.value.trim(); refreshOpp(); }, 300); });
		search.append(icon(I.search), q);
		bar.append(search);
		bar.append(select([['', 'Mọi ngành'], ...Object.entries(m.industry_short)], f.industry, (v) => { f.industry = v; refreshOpp(); }, 'Ngành'));
		bar.append(select([['', 'Mọi loại'], ...Object.entries(m.kinds)], f.kind, (v) => { f.kind = v; refreshOpp(); }, 'Loại cơ hội'));
		const provs = Object.keys({ ...m.provinces, ...m.other_provinces }).filter((p) => m.settings.provinces.includes(p));
		bar.append(select([['', 'Mọi tỉnh'], ...provs.map((p) => [p, p])], f.province, (v) => { f.province = v; refreshOpp(); }, 'Tỉnh'));
		bar.append(select([['', 'Mọi liên hệ'], ['co', 'Có SĐT / email / người'], ['chua', 'Chưa có liên hệ']], f.contact, (v) => { f.contact = v; refreshOpp(); }, 'Liên hệ'));
		bar.append(select([['score', 'Điểm cao trước'], ['new', 'Mới tìm thấy trước'], ['deadline', 'Hạn chót gần trước']], f.sort, (v) => { f.sort = v; refreshOpp(); }, 'Sắp xếp'));
		box.append(bar);

		const states = el('div', 'states');
		const counts = S.opp.counts || {};
		const all = Object.values(counts).reduce((a, b) => a + b, 0);
		for (const [key, label] of [...Object.entries(m.states), ['all', 'Tất cả']]) {
			const b = el('button', '', label);
			b.setAttribute('aria-pressed', String(f.state === key));
			b.append(el('span', 'n', String(key === 'all' ? all : counts[key] || 0)));
			b.addEventListener('click', () => { f.state = key; refreshOpp(); });
			states.append(b);
		}
		box.append(states);

		const list = el('div', 'list');
		list.id = 'opp-list';
		box.append(list);
		paintOpp(list);
	}

	function paintOpp(list) {
		list.replaceChildren();
		if (!S.opp.items.length) {
			const e = el('div', 'empty');
			const filtered = S.opp.filters.q || S.opp.filters.industry || S.opp.filters.kind || S.opp.filters.province;
			e.append(el('h2', '', filtered ? 'Không có cơ hội khớp bộ lọc' : 'Chưa có cơ hội ở mục này'));
			e.append(el('p', '', filtered ? 'Bỏ bớt bộ lọc hoặc đổi từ khoá.' : 'Agent ghi cơ hội vào đây sau mỗi lần quét. Muốn quét ngay: mở chat với Hermes và nhắn "quét lead".'));
			list.append(e);
			return;
		}
		for (const o of S.opp.items) list.append(oppRow(o));
		if (S.opp.total > S.opp.items.length) {
			const more = el('div', 'more');
			const b = el('button', 'btn', `Xem thêm (${S.opp.total - S.opp.items.length})`);
			b.addEventListener('click', async () => { S.opp.limit += PAGE; try { await fetchOpp(); paintOpp(list); } catch (e) { fail(e); } });
			more.append(b);
			list.append(more);
		}
	}

	function oppRow(o) {
		const row = el('button', 'row');
		row.type = 'button';
		row.append(scoreBox(o.score));
		const main = el('div', 'main');
		const l1 = el('div', 'line1');
		l1.append(el('span', 'company', o.company), chip(o.kind_label, o.kind === 'moi_thau' ? 'c-acc' : 'c-muted'), chip(o.industry_label));
		main.append(l1);
		if (o.title) main.append(el('div', 'title', o.title));
		if (o.summary) main.append(el('div', 'summary', o.summary));
		if (o.equipment.length) {
			const tags = el('div', 'tags');
			for (const e of o.equipment.slice(0, 6)) {
				const t = el('span', `tag${o.equipment_inferred ? ' guess' : ''}`, e);
				if (o.equipment_inferred) t.title = 'Agent gợi ý, nguồn không ghi rõ';
				tags.append(t);
			}
			main.append(tags);
		}
		const meta = el('div', 'meta');
		const place = [o.location, o.province].filter(Boolean).join(', ');
		if (place) meta.append(el('span', '', place + (o.province_old ? ` (${o.province_old} cũ)` : '')));
		meta.append(el('span', '', `${o.sources.length} nguồn`));
		const cc = o.contact_counts || {};
		const reach = [cc.phones ? `${cc.phones} SĐT` : '', cc.emails ? `${cc.emails} email` : '', o.people_count ? `${o.people_count} người liên hệ` : ''].filter(Boolean);
		meta.append(el('span', reach.length ? 'reach' : 'reach none', reach.length ? reach.join(' · ') : 'chưa có liên hệ'));
		main.append(meta);
		row.append(main);
		const side = el('div', 'side');
		const left = daysLeft(o.deadline);
		if (left != null) side.append(chip(left < 0 ? 'Hết hạn' : left === 0 ? 'Hạn hôm nay' : `Còn ${left} ngày`, left <= 3 ? 'c-bad' : left <= 10 ? 'c-warn' : 'c-ok'));
		if (o.state !== 'moi') side.append(chip(o.state_label, o.state === 'bo_qua' ? 'c-muted' : 'c-acc'));
		side.append(el('span', '', o.published_at ? `Tin ${day(o.published_at)}` : `Thấy ${ago(o.first_seen)}`));
		row.append(side);
		row.addEventListener('click', () => openOpp(o.id));
		return row;
	}

	async function refreshOpp() {
		S.opp.limit = PAGE;
		try {
			await fetchOpp();
			const list = document.getElementById('opp-list');
			if (list) { render(); } // so dem trang thai doi theo
		} catch (e) { fail(e); }
	}

	// ------------------------------------------------------------ chi tiet co hoi
	function drawer(title, sub) {
		closeDrawer();
		const scrim = el('div', 'scrim');
		scrim.id = 'scrim';
		const d = el('aside', 'drawer');
		d.id = 'drawer';
		d.setAttribute('role', 'dialog');
		d.setAttribute('aria-modal', 'true');
		d.setAttribute('aria-label', title);
		const h = el('header');
		const t = el('div');
		t.append(el('h2', '', title));
		if (sub) t.append(el('div', 'hint', sub));
		const x = el('button', 'icon-btn');
		x.setAttribute('aria-label', 'Đóng');
		x.append(icon(I.close, 18));
		x.addEventListener('click', closeDrawer);
		h.append(t, x);
		const body = el('div', 'body');
		d.append(h, body);
		scrim.addEventListener('click', closeDrawer);
		document.body.append(scrim, d);
		x.focus();
		return body;
	}
	function closeDrawer() {
		document.getElementById('drawer')?.remove();
		document.getElementById('scrim')?.remove();
	}
	document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

	function stateButtons(item, save) {
		const wrap = el('div', 'actions');
		for (const [key, label] of Object.entries(S.me.states)) {
			const b = el('button', 'btn', label);
			b.setAttribute('aria-pressed', String(item.state === key));
			b.addEventListener('click', async () => {
				try { await save({ state: key }); toast(`Đã chuyển sang ${label}`); } catch (e) { fail(e); }
			});
			wrap.append(b);
		}
		return wrap;
	}

	function noteBox(item, save) {
		const wrap = el('div', 'block');
		wrap.append(el('h3', '', 'Ghi chú của sale'));
		const t = el('textarea', 'input');
		t.rows = 3;
		t.value = item.note || '';
		t.placeholder = 'Đã gọi ai, hẹn gì, báo giá gì…';
		const b = el('button', 'btn', 'Lưu ghi chú');
		b.style.marginTop = '8px';
		b.addEventListener('click', async () => { try { await save({ note: t.value }); toast('Đã lưu ghi chú'); } catch (e) { fail(e); } });
		wrap.append(t, b);
		if (item.state_by) wrap.append(el('div', 'hint', `${item.state_label} · ${item.state_by} · ${day(item.state_at)}`));
		return wrap;
	}

	async function openOpp(id) {
		let o;
		try { o = await api(`/opportunities/${id}`); } catch (e) { return fail(e); }
		const body = drawer(o.company, `${o.kind_label} · ${o.industry_label}`);
		const save = async (patch) => {
			await api(`/opportunities/${id}`, { method: 'PATCH', body: patch });
			await fetchOpp();
			render();
			openOpp(id);
		};
		body.append(stateButtons(o, save));

		const kv = el('dl', 'kv');
		const add = (k, v) => { if (v == null || v === '' || (Array.isArray(v) && !v.length)) return; kv.append(el('dt', '', k)); const dd = el('dd'); dd.append(v instanceof Node ? v : String(v)); kv.append(dd); };
		add('Doanh nghiệp / CĐT', o.company);
		add('Ngành', S.me.industries[o.industry]);
		add('Loại thông tin', o.kind_label);
		add('Trạng thái nhà máy', S.me.plant_status[o.plant_status]);
		add('Tên gói / dự án', o.title);
		add('Địa điểm', [o.location, o.province].filter(Boolean).join(', ') + (o.province_old ? ` (tỉnh cũ: ${o.province_old})` : ''));
		if (o.equipment.length) add('Hạng mục thiết bị', o.equipment.join('; ') + (o.equipment_inferred ? ' (agent gợi ý)' : ''));
		if (o.deadline) {
			const left = daysLeft(o.deadline);
			add('Hạn chót hồ sơ', `${vnDate(o.deadline)}${left != null ? (left < 0 ? ' · đã hết hạn' : ` · còn ${left} ngày`) : ''}`);
		}
		add('Tiến độ', o.progress);
		add('Giá trị', o.value_text);
		add('Ngày tin', day(o.published_at));
		add('Agent tìm thấy', `${day(o.first_seen)}${o.last_seen !== o.first_seen ? ` · gặp lại ${day(o.last_seen)}` : ''}`);
		body.append(kv);

		body.append(contactBlock(o));
		if (o.summary) { const b = el('div', 'block'); b.append(el('h3', '', 'Tóm tắt'), el('div', '', o.summary)); body.append(b); }
		if (o.sales_note) { const b = el('div', 'block'); b.append(el('h3', '', 'Gợi ý tiếp cận (AI)'), el('div', 'note-ai', o.sales_note)); body.append(b); }

		const src = el('div', 'block');
		src.append(el('h3', '', `Nguồn (${o.sources.length})`));
		const ul = el('ul', 'sources');
		for (const s of o.sources) {
			const li = el('li');
			li.append(ext(s.url, s.title || s.url));
			li.append(el('div', 'hint', [s.site, vnDate(s.published)].filter(Boolean).join(' · ')));
			ul.append(li);
		}
		src.append(ul);
		body.append(src);

		const ppl = el('div', 'block');
		ppl.append(el('h3', '', `Người liên hệ (${o.people.length})`));
		if (!o.people.length) ppl.append(el('div', 'hint', 'Chưa có. Agent tìm người cho cơ hội từ điểm ' + S.me.settings.min_score_for_people + ' trở lên.'));
		for (const p of o.people) ppl.append(personLine(p));
		body.append(ppl);

		const why = el('div', 'block');
		why.append(el('h3', '', `Điểm ${o.score}/100`));
		const r = el('ul', 'reasons');
		for (const x of o.score_reasons) r.append(el('li', '', x));
		why.append(r);
		body.append(why);

		body.append(noteBox(o, save));
		if (isAdmin()) {
			const del = el('button', 'btn danger', 'Xoá cơ hội này');
			del.addEventListener('click', async () => {
				if (!confirm('Xoá hẳn cơ hội này? Không khôi phục được.')) return;
				try { await api(`/opportunities/${id}`, { method: 'DELETE' }); closeDrawer(); await fetchOpp(); render(); toast('Đã xoá'); } catch (e) { fail(e); }
			});
			body.append(del);
		}
	}

	const fmtPhone = (d) => (/^(1800|1900)/.test(d) ? d.replace(/^(\d{4})(\d+)$/, '$1 $2')
		: d.length === 11 ? d.replace(/^(\d{4})(\d{3})(\d{4})$/, '$1 $2 $3') : d.replace(/^(\d{4})(\d{3})(\d{3})$/, '$1 $2 $3'));
	const tel = (d, label) => { const a = el('a', '', fmtPhone(d)); a.href = `tel:${d}`; const w = el('span', 'cv'); w.append(a); if (label) w.append(el('small', '', ` ${label}`)); return w; };
	const mail = (e, label) => { const a = el('a', '', e); a.href = `mailto:${e}`; const w = el('span', 'cv'); w.append(a); if (label) w.append(el('small', '', ` ${label}`)); return w; };

	function contactBlock(o) {
		// Lien he: dau moi ghi trong nguon + lien he cong khai cua doanh nghiep (agent tim, moi muc co nguon)
		const b = el('div', 'block');
		b.append(el('h3', '', 'Liên hệ'));
		const lead = o.contact || {};
		const cc = o.company_contact || {};
		const kv = el('dl', 'kv');
		const add = (k, nodes) => { if (!nodes.length) return; kv.append(el('dt', '', k)); const dd = el('dd', 'cvs'); dd.append(...nodes); kv.append(dd); };
		const leadNodes = [];
		if (lead.name) leadNodes.push(el('b', '', lead.name));
		for (const p of String(lead.phone || '').split(',').map((x) => x.trim()).filter(Boolean)) leadNodes.push(/^\d+$/.test(p) ? tel(p) : el('span', 'cv', p));
		if (lead.email) leadNodes.push(mail(lead.email));
		add('Đầu mối (theo nguồn)', leadNodes);
		add('Điện thoại', (cc.phones || []).map((p) => tel(p.value, p.label)));
		add('Email', (cc.emails || []).map((e) => mail(e.value, e.label)));
		add('Website', cc.website ? [ext(cc.website, cc.website.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, ''))] : []);
		add('LinkedIn công ty', cc.linkedin_company ? [ext(cc.linkedin_company, 'Trang công ty')] : []);
		add('Facebook', cc.facebook ? [ext(cc.facebook, 'Fanpage')] : []);
		add('Địa chỉ', cc.address ? [el('span', '', cc.address)] : []);
		add('Mã số thuế', cc.tax_code ? [el('span', '', cc.tax_code + (cc.representative ? ` · đại diện: ${cc.representative}` : ''))] : []);
		if (kv.children.length) b.append(kv);
		else b.append(el('div', 'hint', cc.checked_at ? 'Agent đã tìm nhưng chưa thấy SĐT, email công khai. Xem mục Người liên hệ và Nguồn.' : 'Chưa có. Agent tìm website, SĐT, email, LinkedIn của doanh nghiệp ở lần quét tới.'));
		if ((cc.sources || []).length) {
			const s = el('div', 'hint');
			s.append('Nguồn liên hệ: ');
			cc.sources.forEach((x, i) => { if (i) s.append(' · '); s.append(ext(x.url, x.site || x.url)); });
			b.append(s);
		}
		return b;
	}

	function personLine(p) {
		const row = el('div', 'person');
		const l = el('div');
		const name = el('b', '', p.name);
		l.append(name, el('div', 'hint', [p.title, p.company].filter(Boolean).join(' · ')));
		if (p.sales_note) l.append(el('div', '', p.sales_note));
		row.append(l);
		const r = el('div');
		if (p.linkedin_url) { const a = ext(p.linkedin_url, 'LinkedIn'); a.className = 'li'; a.prepend(icon(I.link, 13)); r.append(a); }
		if (p.email) r.append(mail(p.email));
		if (p.phone) r.append(tel(p.phone));
		row.append(r);
		return row;
	}

	// ------------------------------------------------------------ Nguoi lien he
	async function fetchPeople() {
		const f = S.people.filters;
		Object.assign(S.people, await api(`/people?${qs({ ...f, limit: S.people.limit })}`));
	}

	function viewPeople(box) {
		const m = S.me;
		const f = S.people.filters;
		const bar = el('div', 'filters');
		const search = el('div', 'search');
		const q = el('input', 'input');
		q.type = 'search';
		q.placeholder = 'Tìm tên, chức danh, công ty…';
		q.value = f.q;
		q.setAttribute('aria-label', 'Tìm người');
		let timer;
		q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(async () => { f.q = q.value.trim(); await reloadPeople(); }, 300); });
		search.append(icon(I.search), q);
		bar.append(search);
		bar.append(select([['', 'Mọi nhóm'], ...Object.entries(m.role_groups)], f.role_group, async (v) => { f.role_group = v; await reloadPeople(); }, 'Nhóm'));
		bar.append(select([['', 'Mọi trạng thái'], ...Object.entries(m.states)], f.state, async (v) => { f.state = v; await reloadPeople(); }, 'Trạng thái'));
		box.append(bar);
		const list = el('div', 'list people');
		list.id = 'people-list';
		box.append(list);
		paintPeople(list);
	}

	async function reloadPeople() {
		S.people.limit = PAGE;
		try { await fetchPeople(); paintPeople(document.getElementById('people-list')); } catch (e) { fail(e); }
	}

	function paintPeople(list) {
		if (!list) return;
		list.replaceChildren();
		if (!S.people.items.length) {
			const e = el('div', 'empty');
			e.append(el('h2', '', 'Chưa có người liên hệ'), el('p', '', 'Agent tìm người ra quyết định ở công ty có cơ hội tốt, và tìm theo chức danh, ngành, vùng (cần key Apify).'));
			list.append(e);
			return;
		}
		for (const p of S.people.items) {
			const row = el('button', 'row');
			row.type = 'button';
			const main = el('div', 'main');
			const l1 = el('div', 'line1');
			l1.append(el('span', 'company', p.name), chip(p.role_label.split(',')[0]));
			if (p.industry_label) l1.append(chip(p.industry_label));
			main.append(l1, el('div', 'title', [p.title, p.company].filter(Boolean).join(' · ')));
			if (p.sales_note) main.append(el('div', 'summary', p.sales_note));
			const meta = el('div', 'meta');
			if (p.province || p.location) meta.append(el('span', '', p.province || p.location));
			if (p.opportunity_company) meta.append(el('span', '', `Cơ hội: ${p.opportunity_company}`));
			if (p.email) meta.append(el('span', '', p.email));
			main.append(meta);
			const side = el('div', 'side');
			if (p.state !== 'moi') side.append(chip(p.state_label, 'c-acc'));
			side.append(el('span', '', `Thấy ${ago(p.first_seen)}`));
			row.append(main, side);
			row.addEventListener('click', () => openPerson(p));
			list.append(row);
		}
		if (S.people.total > S.people.items.length) {
			const more = el('div', 'more');
			const b = el('button', 'btn', `Xem thêm (${S.people.total - S.people.items.length})`);
			b.addEventListener('click', async () => { S.people.limit += PAGE; try { await fetchPeople(); paintPeople(list); } catch (e) { fail(e); } });
			more.append(b);
			list.append(more);
		}
	}

	function openPerson(p) {
		const body = drawer(p.name, [p.title, p.company].filter(Boolean).join(' · '));
		const save = async (patch) => {
			const fresh = await api(`/people/${p.id}`, { method: 'PATCH', body: patch });
			await fetchPeople();
			paintPeople(document.getElementById('people-list'));
			openPerson({ ...fresh, opportunity_company: p.opportunity_company });
		};
		body.append(stateButtons(p, save));
		const kv = el('dl', 'kv');
		const add = (k, v) => { if (!v) return; kv.append(el('dt', '', k)); const dd = el('dd'); dd.append(v instanceof Node ? v : String(v)); kv.append(dd); };
		add('Họ & tên', p.name);
		add('Chức danh', p.title);
		add('Công ty / Nhà máy', p.company);
		add('Ngành', p.industry_label);
		add('Nhóm', p.role_label);
		add('Trạng thái nhà máy', S.me.plant_status[p.plant_status]);
		add('Địa bàn', p.province || p.location);
		if (p.linkedin_url) add('LinkedIn', ext(p.linkedin_url));
		add('Email', p.email);
		add('Điện thoại', p.phone);
		add('Nguồn', p.source);
		add('Agent tìm thấy', day(p.first_seen));
		body.append(kv);
		if (p.sales_note) { const b = el('div', 'block'); b.append(el('h3', '', 'Gợi ý tiếp cận (AI)'), el('div', 'note-ai', p.sales_note)); body.append(b); }
		if (p.opportunity_id) {
			const b = el('button', 'btn', `Mở cơ hội: ${p.opportunity_company || 'liên quan'}`);
			b.addEventListener('click', () => openOpp(p.opportunity_id));
			body.append(b);
		}
		body.append(noteBox(p, save));
		if (isAdmin()) {
			const del = el('button', 'btn danger', 'Xoá người này (khi họ yêu cầu)');
			del.addEventListener('click', async () => {
				if (!confirm(`Xoá hẳn ${p.name}? Không khôi phục được.`)) return;
				try { await api(`/people/${p.id}`, { method: 'DELETE' }); closeDrawer(); await reloadPeople(); toast('Đã xoá'); } catch (e) { fail(e); }
			});
			body.append(del);
		}
	}

	// ------------------------------------------------------------ Lan quet
	const STAT_LABELS = {
		candidates: 'tin đọc', created: 'cơ hội mới', merged: 'gộp', rejected: 'loại', people_created: 'người mới',
		people_merged: 'người gộp', google_queries: 'truy vấn Google', news_items: 'tin Google News', watch_links: 'link trang theo dõi'
	};
	function viewRuns(box) {
		if (!S.runs.length) {
			const e = el('div', 'empty');
			e.append(el('h2', '', 'Chưa có lần quét nào'), el('p', '', 'Agent ghi mỗi lần quét vào đây: tìm được gì, loại bao nhiêu, tốn bao nhiêu tiền Apify.'));
			box.append(e);
			return;
		}
		const wrap = el('div', 'scroll');
		const t = el('table', 'runs');
		t.innerHTML = '<thead><tr><th>Lúc</th><th>Kiểu</th><th>Kết quả</th><th>Số liệu</th><th>Chi phí</th></tr></thead>';
		const tb = el('tbody');
		for (const r of S.runs) {
			const tr = el('tr');
			const when = el('td', 'num', `${day(r.started_at)} ${new Date(r.started_at * 1000).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`);
			const st = el('td');
			st.append(chip({ ok: 'Xong', partial: 'Một phần', error: 'Lỗi', running: 'Đang chạy' }[r.status] || r.status,
				r.status === 'ok' ? 'c-ok' : r.status === 'error' ? 'c-bad' : 'c-warn'));
			if (r.message) st.append(el('div', 'hint', r.message));
			const stats = el('td', '', Object.entries(r.stats || {}).filter(([k]) => STAT_LABELS[k]).map(([k, v]) => `${v} ${STAT_LABELS[k]}`).join(' · '));
			tr.append(when, el('td', '', r.trigger === 'cron' ? 'Theo lịch' : r.trigger === 'chat' ? 'Từ chat' : r.trigger || ''), st, stats, el('td', 'num', usd(r.cost_usd)));
			tb.append(tr);
		}
		t.append(tb);
		wrap.append(t);
		box.append(wrap);
	}

	// ------------------------------------------------------------ Cai dat
	function card(title, hint) {
		const c = el('section', 'card');
		const h = el('header');
		h.append(el('h2', '', title));
		if (hint) h.append(el('div', 'hint', hint));
		const b = el('div', 'body');
		c.append(h, b);
		return [c, b];
	}

	function viewSettings(box) {
		const m = S.me;
		const admin = isAdmin();
		if (!S.draft) S.draft = JSON.parse(JSON.stringify(m.settings));
		const d = S.draft;
		const touch = () => { S.dirty = true; const bar = document.getElementById('savebar'); if (bar) bar.hidden = false; };
		const wrap = el('div', 'settings');
		if (!admin) wrap.append(el('div', 'readonly', 'Chỉ quản trị viên Open WebUI sửa được cài đặt. Bạn đang xem.'));

		// Key Apify
		const [kc, kb] = card('Key Apify', 'Apify chạy phần tìm Google và LinkedIn. Lấy key: console.apify.com → Settings → API & Integrations → Personal API tokens.');
		const k = m.apify;
		const status = el('div', 'wide');
		if (k.set) {
			const stat = el('div', 'stat');
			const add = (label, value) => { const s = el('span', '', `${label}: `); s.append(el('b', '', value)); stat.append(s); };
			add('Key', `••••${k.last4}`);
			if (k.username) add('Tài khoản', k.username);
			if (k.plan) add('Gói', k.plan);
			if (k.limit_usd) add('Đã dùng tháng này', `${usd(k.used_usd)} / ${usd(k.limit_usd)}`);
			if (k.cycle_end) add('Chu kỳ tới', vnDate(k.cycle_end));
			status.append(stat);
			if (k.limit_usd) {
				const meter = el('div', `meter${k.used_usd / k.limit_usd > 0.8 ? ' warn' : ''}`);
				meter.style.marginTop = '8px';
				const i = el('i');
				i.style.width = `${Math.min(100, (k.used_usd / k.limit_usd) * 100)}%`;
				meter.append(i);
				status.append(meter);
			}
			if (k.ok === false && k.error) status.append(el('div', 'hint', `Lần kiểm tra gần nhất: ${k.error}`));
			else if (k.checked_at) status.append(el('div', 'hint', `Kiểm tra lúc ${day(k.checked_at)} ${new Date(k.checked_at * 1000).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}. Agent đã tiêu ${usd(m.month_cost_usd)} trong tháng (theo các lần quét).`));
		} else {
			status.append(el('div', '', 'Chưa có key. Agent chỉ quét được Google News và các trang theo dõi.'));
		}
		kb.append(status);
		if (admin) {
			const row = el('div', 'keybox wide');
			const input = el('input', 'input');
			input.type = 'password';
			input.autocomplete = 'off';
			input.placeholder = k.set ? 'Dán key mới để thay' : 'apify_api_…';
			input.setAttribute('aria-label', 'Key Apify');
			const saveKey = el('button', 'btn primary', k.set ? 'Thay key' : 'Lưu key');
			saveKey.addEventListener('click', async () => {
				saveKey.disabled = true;
				try {
					m.apify = await api('/apify-key', { method: 'PUT', body: { key: input.value.trim() } });
					toast('Apify đã nhận key. Đã lưu (mã hoá).');
					render();
				} catch (e) { fail(e); } finally { saveKey.disabled = false; }
			});
			row.append(input, saveKey);
			if (k.set) {
				const check = el('button', 'btn', 'Kiểm tra lại');
				check.addEventListener('click', async () => { check.disabled = true; try { m.apify = await api('/apify-key/check', { method: 'POST' }); render(); } catch (e) { fail(e); } finally { check.disabled = false; } });
				const del = el('button', 'btn danger', 'Xoá key');
				del.addEventListener('click', async () => { if (!confirm('Xoá key Apify? Agent sẽ ngừng tìm Google và LinkedIn.')) return; try { m.apify = await api('/apify-key', { method: 'DELETE' }); render(); } catch (e) { fail(e); } });
				row.append(check, del);
			}
			kb.append(row);
		}
		wrap.append(kc);

		// Ben ban
		const [sc, sb] = card('Bên bán', 'Agent dùng để chấm điểm "thiết bị khớp hàng đang bán" và viết gợi ý tiếp cận.');
		const company = el('input', 'input');
		company.value = d.seller.company;
		company.addEventListener('input', () => { d.seller.company = company.value; touch(); });
		sb.append(field('Tên công ty bên bán', company));
		const avoid = el('input', 'input');
		avoid.value = d.seller.avoid;
		avoid.placeholder = 'VD: thiết bị y tế cho bệnh viện';
		avoid.addEventListener('input', () => { d.seller.avoid = avoid.value; touch(); });
		sb.append(field('Không cần tìm', avoid));
		const products = el('textarea', 'input');
		products.rows = 3;
		products.value = d.seller.products;
		products.placeholder = 'VD: máy dò kim loại, máy đóng gói chân không, máy ly tâm tách mỡ cá, thiết bị phòng lab vi sinh (tủ cấy, nồi hấp tiệt trùng, máy ELISA)…';
		products.addEventListener('input', () => { d.seller.products = products.value; touch(); });
		const pf = field('Thiết bị / hàng đang bán', products, 'Ghi càng cụ thể, điểm và gợi ý tiếp cận càng sát.');
		pf.classList.add('wide');
		sb.append(pf);
		wrap.append(sc);

		// Nganh
		const [ic, ib] = card('Ngành', 'Bỏ chọn "Theo dõi" thì agent không lưu cơ hội ngành đó. "Ưu tiên" được cộng thêm điểm.');
		const grid = el('div', 'ind wide');
		grid.append(el('span', 'h', 'Ngành'), el('span', 'h', 'Theo dõi'), el('span', 'h', 'Ưu tiên'));
		for (const [key, label] of Object.entries(m.industries)) {
			grid.append(el('span', '', label));
			for (const listName of ['industries', 'priority_industries']) {
				const c = el('input');
				c.type = 'checkbox';
				c.checked = d[listName].includes(key);
				c.setAttribute('aria-label', `${listName === 'industries' ? 'Theo dõi' : 'Ưu tiên'} ${label}`);
				c.addEventListener('change', () => {
					d[listName] = c.checked ? [...new Set([...d[listName], key])] : d[listName].filter((x) => x !== key);
					touch();
				});
				grid.append(c);
			}
		}
		ib.append(grid);
		wrap.append(ic);

		// Vung
		const [pc, pb] = card('Vùng', 'Tỉnh theo tên mới (từ 1/7/2025). Cơ hội ngoài vùng không được lưu.');
		const checks = (entries, listName) => {
			const g = el('div', 'checks wide');
			for (const [key, label, sub] of entries) {
				const l = el('label');
				const c = el('input');
				c.type = 'checkbox';
				c.checked = d[listName].includes(key);
				c.addEventListener('change', () => { d[listName] = c.checked ? [...new Set([...d[listName], key])] : d[listName].filter((x) => x !== key); touch(); });
				const t = el('span', '', label);
				if (sub) t.append(el('small', '', sub));
				l.append(c, t);
				g.append(l);
			}
			return g;
		};
		pb.append(checks(Object.entries(m.provinces).map(([n, olds]) => [n, n, olds.length > 1 ? `gồm ${olds.filter((o) => o !== n).join(', ')}` : '']), 'provinces'));
		const otherToggle = el('details', 'wide');
		otherToggle.append(el('summary', 'hint', 'Tỉnh phía Bắc và miền Trung (ngoài vùng mặc định)'));
		otherToggle.append(checks(Object.entries(m.other_provinces).map(([n, olds]) => [n, n, olds.length > 1 ? `gồm ${olds.filter((o) => o !== n).join(', ')}` : '']), 'provinces'));
		pb.append(otherToggle);
		wrap.append(pc);

		// Loai co hoi + nguon
		const [nc, nb] = card('Loại cơ hội và nguồn');
		nb.append(checks(Object.entries(m.kinds).map(([k2, l]) => [k2, l]), 'kinds'));
		const SOURCES = { news: ['Google News', 'miễn phí: báo chí về khởi công, cấp phép, mở rộng'], watch: ['Trang theo dõi', 'miễn phí: trang ĐTM của tỉnh, thông báo mời chào giá của doanh nghiệp'], google: ['Tìm Google (Apify)', 'mời chào giá, ĐTM, tuyển dụng nhà máy mới, trang đấu thầu'], linkedin: ['LinkedIn (Apify)', 'người ra quyết định ở công ty có cơ hội và theo chức danh'] };
		const sg = el('div', 'checks wide');
		for (const [key, [label, sub]] of Object.entries(SOURCES)) {
			const l = el('label');
			const c = el('input');
			c.type = 'checkbox';
			c.checked = !!d.sources[key];
			c.addEventListener('change', () => { d.sources[key] = c.checked; touch(); });
			const t = el('span', '', label);
			t.append(el('small', '', sub));
			l.append(c, t);
			sg.append(l);
		}
		nb.append(sg);
		const watch = el('textarea', 'input');
		watch.rows = 5;
		watch.value = d.watch_pages.map((p) => (p.label ? `${p.url} | ${p.label}` : p.url)).join('\n');
		watch.placeholder = 'Để trống: dùng danh sách có sẵn của agent.\nhttps://www.camau.gov.vn/danh-gia-tac-dong-moi-truong-child | ĐTM Cà Mau';
		watch.addEventListener('input', () => {
			d.watch_pages = watch.value.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => {
				const [url, ...label] = line.split('|');
				return { url: url.trim(), label: label.join('|').trim() };
			});
			touch();
		});
		const wf = field('Trang theo dõi thêm (mỗi dòng: link | tên)', watch, 'Trang danh sách tin / thông báo. Agent đọc link mới trên trang mỗi lần quét.');
		wf.classList.add('wide');
		nb.append(wf);
		const kw = el('input', 'input');
		kw.value = d.extra_keywords.join(', ');
		kw.placeholder = 'VD: máy X-ray thực phẩm, hệ thống CIP';
		kw.addEventListener('input', () => { d.extra_keywords = kw.value.split(',').map((x) => x.trim()).filter(Boolean); touch(); });
		const kf = field('Từ khoá thiết bị thêm (cách nhau dấu phẩy)', kw);
		kf.classList.add('wide');
		nb.append(kf);
		wrap.append(nc);

		// Gioi han
		const [lc, lb] = card('Giới hạn và chi phí', 'Agent dừng gọi Apify khi chạm trần. Giá tham khảo: 1 truy vấn Google khoảng $0.005, 25 hồ sơ LinkedIn khoảng $0.10.');
		const num = (key, label, step, hint) => {
			const i = el('input', 'input');
			i.type = 'number';
			i.step = step;
			i.min = '0';
			i.value = d[key];
			i.addEventListener('input', () => { d[key] = i.value === '' ? '' : Number(i.value); touch(); });
			lb.append(field(label, i, hint));
		};
		num('max_usd_per_run', 'Trần mỗi lần quét (USD)', '0.05');
		num('max_usd_per_month', 'Trần mỗi tháng (USD)', '0.5', `Gói Apify hiện tại: ${k.limit_usd ? usd(k.limit_usd) : 'chưa rõ'} / tháng.`);
		num('google_queries_per_run', 'Số truy vấn Google mỗi lần', '1');
		num('linkedin_sweep_per_run', 'Số hồ sơ LinkedIn tìm theo chức danh (mỗi tuần 1 lần)', '25', '0 = tắt. 25 hồ sơ khoảng $0.10.');
		num('people_per_opportunity', 'Số người tìm cho mỗi cơ hội', '1');
		num('min_score_for_people', 'Chỉ tìm người cho cơ hội từ điểm', '5');
		num('lookback_days', 'Bỏ tin cũ hơn (ngày)', '1');
		const model = el('input', 'input');
		model.value = d.llm_model;
		model.placeholder = 'Để trống: dùng model của Hermes';
		model.addEventListener('input', () => { d.llm_model = model.value.trim(); touch(); });
		lb.append(field('Model đọc tin', model, 'VD: deepseek/deepseek-v4-pro. Model mạnh hơn đọc tin chính xác hơn, tốn hơn.'));
		wrap.append(lc);

		const [ac, ab] = card('Agent', 'Hermes trên cùng máy dùng skill san-lead-b2b. Skill đọc token trong file dưới đây để lấy key Apify và ghi kết quả.');
		ab.append(el('code', 'wide', m.agent_file));
		wrap.append(ac);

		if (!admin) wrap.querySelectorAll('input, textarea, select').forEach((x) => { x.disabled = true; });
		box.append(wrap);

		if (admin) {
			const bar = el('div', 'savebar');
			bar.id = 'savebar';
			bar.hidden = !S.dirty;
			const inner = el('div', 'inner');
			const msg = el('span', 'msg', 'Có thay đổi chưa lưu');
			const undo = el('button', 'btn', 'Bỏ thay đổi');
			undo.addEventListener('click', () => { S.draft = null; S.dirty = false; render(); });
			const save = el('button', 'btn primary', 'Lưu cài đặt');
			save.addEventListener('click', async () => {
				save.disabled = true;
				try {
					m.settings = await api('/settings', { method: 'PUT', body: S.draft });
					S.draft = null;
					S.dirty = false;
					toast('Đã lưu cài đặt');
					render();
				} catch (e) { fail(e); } finally { save.disabled = false; }
			});
			inner.append(msg, undo, save);
			bar.append(inner);
			box.append(bar);
		}
	}

	// ------------------------------------------------------------ Quy tac
	function viewRules(box) {
		const g = el('div', 'rules');
		for (const r of S.me.rules) {
			const c = el('div', 'rule');
			c.append(el('h3', '', r.title), el('p', '', r.text));
			g.append(c);
		}
		box.append(g);
	}

	// ------------------------------------------------------------ nap
	async function load() {
		try {
			S.me = await api('/me');
			if (S.view === 'co-hoi') await fetchOpp();
			else {
				const data = await api(`/opportunities?${qs({ state: 'moi', limit: 1 })}`);
				S.opp.counts = data.counts;
			}
			if (S.view === 'nguoi') await fetchPeople();
			if (S.view === 'lan-quet') S.runs = await api('/runs?limit=60');
			render();
		} catch (e) { fail(e); }
	}

	const start = new URLSearchParams(location.search).get('view') || (/#san-lead\/([a-z-]+)/.exec(window.parent !== window ? window.parent.location.hash : location.hash) || [])[1];
	if (start && VIEWS.some(([k]) => k === start)) S.view = start;
	window.addEventListener('beforeunload', (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ''; } });
	load();
})();
