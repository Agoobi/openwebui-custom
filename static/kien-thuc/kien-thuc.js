/* Trang Kien thuc (xem index.html): ghi chu Markdown kieu Obsidian cho chatbot. Moi chu dua vao trang deu escape. */
(() => {
	'use strict';
	const { api, AuthError, $, el, toast, authScreen, clock } = window.CQF;
	const state = { notes: [], current: null, mode: 'view', dirty: false, filter: '' };

	// ------------------------------------------------------------ Markdown -> HTML (escape truoc, roi moi dinh dang)
	const esc = (s) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
	function inline(s) {
		const byTitle = Object.fromEntries(state.notes.map((n) => [n.title.toLowerCase(), n.name]));
		const names = new Set(state.notes.map((n) => n.name));
		return esc(s)
			.replace(/`([^`]+)`/g, '<code>$1</code>')
			.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
			.replace(/(^|[^*])\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g, '$1<em>$2</em>')
			.replace(/\[\[([^\]|#]+)(?:[#|]([^\]]*))?\]\]/g, (m, target, label) => {
				const t = target.trim();
				const name = names.has(t) ? t : byTitle[t.toLowerCase()];
				return `<a class="wl${name ? '' : ' missing'}" data-note="${name || ''}" title="${name ? 'Mở ghi chú' : 'Chưa có ghi chú này'}">${label || t}</a>`;
			})
			.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
			.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
	}
	function markdown(md) {
		const lines = md.replace(/\r\n/g, '\n').split('\n');
		const out = [];
		let list = null, para = [], code = null, table = null;
		const flushPara = () => { if (para.length) { out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = []; } };
		const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`); list = null; } };
		const flushTable = () => {
			if (!table) return;
			const rows = table.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r)).map((r) => r.replace(/^\s*\||\|\s*$/g, '').split('|').map((c) => inline(c.trim())));
			out.push(`<table><thead><tr>${rows[0].map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>${rows.slice(1).map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
			table = null;
		};
		const flush = () => { flushPara(); flushList(); flushTable(); };
		lines.forEach((line) => {
			if (code !== null) {
				if (/^```/.test(line)) { out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`); code = null; } else code.push(line);
				return;
			}
			if (/^```/.test(line)) { flush(); code = []; return; }
			const st = line.trim();
			if (!st) { flush(); return; }
			let m;
			if ((m = st.match(/^(#{1,6})\s+(.*)$/))) { flush(); const lv = Math.min(m[1].length, 4); out.push(`<h${lv} id="h-${out.length}">${inline(m[2])}</h${lv}>`); return; }
			if (/^(-{3,}|\*{3,})$/.test(st)) { flush(); out.push('<hr>'); return; }
			if (st.startsWith('|')) { flushPara(); flushList(); (table ||= []).push(st); return; }
			if ((m = st.match(/^([-*+]|\d+[.)])\s+(.*)$/))) {
				flushPara(); flushTable();
				const tag = /\d/.test(m[1]) ? 'ol' : 'ul';
				if (list && list.tag !== tag) flushList();
				(list ||= { tag, items: [] }).items.push(m[2]);
				return;
			}
			if (st.startsWith('>')) { flush(); out.push(`<blockquote>${inline(st.replace(/^>\s?/, ''))}</blockquote>`); return; }
			if (/^<!--.*-->$/.test(st)) return;
			flushList(); flushTable();
			para.push(st);
		});
		if (code !== null) out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
		flush();
		return out.join('\n');
	}

	// ------------------------------------------------------------ danh sach
	function renderTree() {
		const f = state.filter.trim().toLowerCase();
		const notes = state.notes.filter((n) => !f || n.title.toLowerCase().includes(f) || (n.file || '').toLowerCase().includes(f));
		const groups = [['Từ file tải lên', notes.filter((n) => n.source)], ['Tự viết', notes.filter((n) => !n.source)]];
		const tree = $('tree');
		tree.replaceChildren();
		if (!state.notes.length) {
			tree.append(el('p', 'hint', 'Chưa có kiến thức nào. Tải file lên hoặc tạo ghi chú.'));
			return;
		}
		for (const [label, list] of groups) {
			if (!list.length) continue;
			const g = el('div', 'group');
			const head = el('div', 'eyebrow');
			head.append(el('span', '', label), el('span', '', String(list.length)));
			g.append(head);
			for (const n of list) {
				const b = el('button', `note-row${n.enabled ? '' : ' off'}`);
				b.type = 'button';
				b.setAttribute('aria-current', String(n.name === state.current?.name));
				b.title = n.enabled ? 'Bot đang dùng ghi chú này' : 'Đang tắt: bot không tra ghi chú này';
				b.append(el('span', 'dot'), el('span', 't', n.title));
				if (n.warn?.length) b.append(el('span', 'warn-ico', '⚠'));
				b.addEventListener('click', () => open(n.name));
				g.append(b);
			}
			tree.append(g);
		}
	}

	async function loadList() {
		const res = await api('/kb');
		state.notes = res.notes;
		renderTree();
	}

	// ------------------------------------------------------------ mo / xem / sua
	async function open(name, mode = 'view') {
		if (state.dirty) await saveNote(true); // chuyen ghi chu: tu luu ban dang sua (confirm() bi chan trong iframe)
		try {
			const res = await api(`/kb/note?name=${encodeURIComponent(name)}`);
			show(res.note, mode);
			try { history.replaceState(null, '', `#${encodeURIComponent(name)}`); } catch { /* bo qua */ }
		} catch (e) {
			if (e instanceof AuthError) return authScreen($('vault'));
			toast(e.message);
		}
	}

	function show(note, mode) {
		state.current = note;
		state.dirty = false;
		$('vault').classList.add('open');
		$('toolbar').hidden = false;
		$('docEmpty').hidden = true;
		$('docInner').hidden = false;
		$('noteTitle').value = note.title;
		$('source').value = note.body;
		$('noteOn').checked = note.enabled;
		const meta = $('noteMeta');
		meta.replaceChildren(
			el('span', `chip ${note.enabled ? 'c-ok' : 'c-muted'}`, note.enabled ? 'Bot đang dùng' : 'Đang tắt'),
			el('span', 'chip c-muted', note.file ? `Từ file ${note.file}` : 'Tự viết'),
			el('span', 'hint', `Sửa lần cuối ${clock(note.updated_at)} · ${note.chars.toLocaleString('vi-VN')} ký tự`)
		);
		$('secWarn').hidden = !note.warn?.length;
		$('warnText').textContent = note.warn?.length
			? `Có số không có trong file gốc: ${note.warn.join(', ')}. Kiểm tra lại nếu không chủ ý thay đổi.` : '';
		const toc = $('toc');
		toc.replaceChildren(...(note.headings || []).map(([lv, t]) => {
			const li = el('li');
			const b = el('button', '', t);
			b.style.paddingLeft = `${6 + (lv - 1) * 12}px`;
			b.addEventListener('click', () => {
				const target = [...$('preview').querySelectorAll('h1,h2,h3,h4')].find((h) => h.textContent === t);
				if (state.mode !== 'view') setMode('view');
				target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
			});
			li.append(b);
			return li;
		}));
		$('secToc').hidden = !(note.headings || []).length;
		const back = $('backlinks');
		back.replaceChildren(...(note.backlinks || []).map((n) => {
			const li = el('li');
			const b = el('button', '', state.notes.find((x) => x.name === n)?.title || n);
			b.addEventListener('click', () => open(n));
			li.append(b);
			return li;
		}));
		$('secBack').hidden = !(note.backlinks || []).length;
		$('secSrc').hidden = !note.source;
		$('srcInfo').textContent = note.file ? `Tải lên từ ${note.file}` : '';
		$('origBox').hidden = true;
		$('toggleOrig').textContent = 'Xem bản gốc';
		$('orig').innerHTML = note.source_text ? markdown(note.source_text) : '';
		setMode(mode);
		renderTree();
		setSave('');
	}

	function setMode(mode) {
		state.mode = mode;
		$('modeView').setAttribute('aria-pressed', String(mode === 'view'));
		$('modeEdit').setAttribute('aria-pressed', String(mode === 'edit'));
		$('preview').hidden = mode !== 'view';
		$('source').hidden = mode !== 'edit';
		$('saveNote').hidden = mode !== 'edit' && !state.dirty;
		if (mode === 'view') $('preview').innerHTML = markdown($('source').value);
		else $('source').focus();
	}

	function setSave(text) { $('saveState').textContent = text; }

	async function saveNote(leaving) {
		const n = state.current;
		if (!n || !state.dirty) return;
		$('saveNote').disabled = true;
		try {
			const res = await api('/kb/note', { method: 'POST', body: JSON.stringify({ name: n.name, title: $('noteTitle').value, body: $('source').value }) });
			state.dirty = false;
			await loadList();
			if (leaving === true) return toast(`Đã lưu ${res.note.title}`);
			show(res.note, state.mode);
			setSave(res.note.warn?.length ? 'Đã lưu (có cảnh báo số liệu)' : 'Đã lưu');
		} catch (e) {
			toast(`Không lưu được: ${e.message}`);
		} finally {
			$('saveNote').disabled = false;
		}
	}

	async function newNote() {
		try {
			const res = await api('/kb/note', { method: 'POST', body: JSON.stringify({ title: 'Ghi chú mới', body: '## \n' }) });
			await loadList();
			show(res.note, 'edit');
			$('noteTitle').select();
		} catch (e) {
			if (e instanceof AuthError) return authScreen($('vault'));
			toast(e.message);
		}
	}

	let delArmed = null;
	async function deleteNote() {
		const n = state.current;
		if (!n) return;
		// xac nhan bang bam 2 lan (confirm() bi chan trong iframe)
		if (delArmed !== n.name) {
			delArmed = n.name;
			$('delNote').textContent = 'Bấm lần nữa để xoá';
			setTimeout(() => { delArmed = null; $('delNote').textContent = 'Xoá'; }, 4000);
			return;
		}
		delArmed = null;
		$('delNote').textContent = 'Xoá';
		try {
			await api(`/kb/note?name=${encodeURIComponent(n.name)}`, { method: 'DELETE' });
			toast(`Đã xoá ${n.title}`);
			state.current = null;
			state.dirty = false;
			$('toolbar').hidden = true;
			$('docInner').hidden = true;
			$('docEmpty').hidden = false;
			$('vault').classList.remove('open');
			await loadList();
		} catch (e) {
			toast(e.message);
		}
	}

	async function upload(files) {
		if (!files.length) return;
		const fd = new FormData();
		[...files].forEach((f) => fd.append('files', f));
		toast(`Đang đọc ${files.length} file…`);
		try {
			const res = await api('/kb/upload', { method: 'POST', body: fd });
			await loadList();
			if (res.errors?.length) toast(res.errors.join(' · '));
			else toast(`Đã thêm ${res.done.length} file vào kiến thức, bot dùng được ngay`);
			if (res.done?.[0]) open(res.done[0].name);
		} catch (e) {
			if (e instanceof AuthError) return authScreen($('vault'));
			toast(`Không tải lên được: ${e.message}`);
		}
	}

	async function trySearch(q) {
		const out = $('searchOut');
		out.replaceChildren(el('p', 'hint', 'Đang tìm…'));
		try {
			const res = await api(`/kb/search?q=${encodeURIComponent(q)}`);
			const ql = el('div', 'qlist');
			ql.append(el('b', 'hint', `Bot tra ${res.queries.length} lần:`), ...res.queries.map((x) => el('span', '', x)));
			const list = el('div');
			list.style.cssText = 'display:flex;flex-direction:column;gap:6px;margin-top:8px';
			if (!res.hits.length) list.append(el('p', 'hint', 'Không tìm thấy đoạn nào: bot sẽ nói chưa có thông tin và xin liên hệ khách.'));
			for (const h of res.hits) {
				const b = el('button', 'hit');
				b.type = 'button';
				b.append(el('b', '', h.title), document.createTextNode(h.text.slice(0, 160) + (h.text.length > 160 ? '…' : '')));
				b.addEventListener('click', () => open(h.source));
				list.append(b);
			}
			out.replaceChildren(ql, list);
		} catch (e) {
			out.replaceChildren(el('p', 'hint', e.message));
		}
	}

	// ------------------------------------------------------------ su kien
	$('filter').addEventListener('input', (e) => { state.filter = e.target.value; renderTree(); });
	$('modeView').addEventListener('click', () => setMode('view'));
	$('modeEdit').addEventListener('click', () => setMode('edit'));
	$('source').addEventListener('input', () => { state.dirty = true; $('saveNote').hidden = false; setSave('Chưa lưu'); });
	$('noteTitle').addEventListener('input', () => { state.dirty = true; $('saveNote').hidden = false; setSave('Chưa lưu'); });
	$('saveNote').addEventListener('click', () => saveNote());
	$('delNote').addEventListener('click', deleteNote);
	$('newBtn').addEventListener('click', newNote);
	$('uploadBtn').addEventListener('click', () => $('fileInput').click());
	$('fileInput').addEventListener('change', (e) => { upload(e.target.files); e.target.value = ''; });
	$('noteOn').addEventListener('change', async (e) => {
		const n = state.current;
		try {
			await api('/kb/toggle', { method: 'POST', body: JSON.stringify({ name: n.name, enabled: e.target.checked }) });
			await loadList();
			n.enabled = e.target.checked;
			toast(e.target.checked ? 'Bot dùng lại ghi chú này' : 'Đã tắt: bot không tra ghi chú này');
			open(n.name, state.mode);
		} catch (err) {
			toast(err.message);
			e.target.checked = !e.target.checked;
		}
	});
	$('toggleOrig').addEventListener('click', () => {
		const box = $('origBox');
		box.hidden = !box.hidden;
		$('toggleOrig').textContent = box.hidden ? 'Xem bản gốc' : 'Ẩn bản gốc';
		if (!box.hidden) box.scrollIntoView({ behavior: 'smooth' });
	});
	$('preview').addEventListener('click', (e) => {
		const a = e.target.closest('a.wl');
		if (a?.dataset.note) open(a.dataset.note);
	});
	$('back').addEventListener('click', () => { $('vault').classList.remove('open'); });
	$('searchForm').addEventListener('submit', (e) => { e.preventDefault(); const q = $('q').value.trim(); if (q) trySearch(q); });
	document.addEventListener('keydown', (e) => {
		if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); saveNote(); }
	});
	window.addEventListener('beforeunload', (e) => { if (state.dirty) e.preventDefault(); });
	['dragenter', 'dragover'].forEach((t) => document.addEventListener(t, (e) => {
		if ([...(e.dataTransfer?.types || [])].includes('Files')) { e.preventDefault(); document.body.classList.add('dragging'); }
	}));
	['dragleave', 'drop'].forEach((t) => document.addEventListener(t, (e) => {
		if (t === 'dragleave' && e.relatedTarget) return;
		document.body.classList.remove('dragging');
		if (t === 'drop' && e.dataTransfer?.files?.length) { e.preventDefault(); upload(e.dataTransfer.files); }
	}));

	(async () => {
		try {
			await loadList();
			const fromHash = decodeURIComponent(location.hash.slice(1));
			if (fromHash && state.notes.some((n) => n.name === fromHash)) open(fromHash);
		} catch (e) {
			if (e instanceof AuthError) return authScreen($('vault'));
			toast(`Không tải được kiến thức: ${e.message}`);
		}
	})();
})();
