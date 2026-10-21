/*
 * Open WebUI custom loader (Agoobi). Open WebUI tu nap file nay tren moi trang (/static/loader.js).
 * Them hang "Hop thu" ngay duoi hang Search cua sidebar, kem so khach can xu ly lay tu Hermes (dia chi trong
 * /static/hop-thu/config.json). Bam vao thi trang Hop thu mo trong vung noi dung, sidebar giu nguyen
 * (Ctrl/Cmd + bam: mo tab rieng). Khong sua gi khac cua Open WebUI.
 * Bam vao cau truc sidebar cua Open WebUI 0.11.4 (#sidebar-search-button): nang ban thi kiem lai.
 * Hop dong voi Hermes: docs/dong-bo.md.
 */
(() => {
	const INBOX_ICON =
		'<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>';
	let todo = 0;

	// Hang moi dung dung class cua hang New Chat / Search nen trong nhu muc goc; Svelte ve lai sidebar thi them lai.
	const addInboxLink = () => {
		const search = document.getElementById('sidebar-search-button');
		const row = search?.parentElement;
		if (!row || row.nextElementSibling?.dataset?.cqfInboxRow != null) return;
		const wrap = document.createElement('div');
		wrap.className = row.className;
		wrap.dataset.cqfInboxRow = '';
		const a = document.createElement('a');
		a.id = 'sidebar-cqf-inbox-button';
		a.href = `#${HASH}`;
		a.addEventListener('click', (e) => {
			if (e.metaKey || e.ctrlKey || e.shiftKey) {
				e.preventDefault();
				window.open('/static/hop-thu/index.html', '_blank'); // mo tab rieng (toan man hinh)
				return;
			}
			e.preventDefault();
			if (location.hash !== `#${HASH}`) history.pushState(history.state, '', `${location.pathname}${location.search}#${HASH}`);
			sync();
		});
		a.className = 'group grow flex items-center space-x-2 rounded-xl px-2 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-900 transition outline-none';
		a.setAttribute('aria-label', 'Hộp thư');
		a.innerHTML =
			`<div class="self-center flex size-4 shrink-0 items-center justify-center">${INBOX_ICON}</div>` +
			'<div class="flex flex-1 self-center translate-y-[0.5px]"><div class=" self-center text-[0.8125rem] leading-5">Hộp thư</div></div>' +
			'<span class="cqf-inbox-count" hidden></span>';
		wrap.append(a);
		row.after(wrap);
		paintCount();
	};

	// Hop thu mo NGAY TRONG khung Open WebUI: 1 iframe phu vung noi dung ben phai sidebar, sidebar giu nguyen.
	// Mo khi URL co #hop-thu; bam muc khac trong sidebar (Open WebUI doi URL, mat #hop-thu) thi tu dong.
	const HASH = 'hop-thu';
	let frame = null;
	const sidebarRight = () => {
		if (window.innerWidth < 768) return 0; // dien thoai: sidebar Open WebUI la lop phu
		let right = 0;
		document.querySelectorAll('[id="sidebar"]').forEach((s) => {
			const r = s.getBoundingClientRect();
			if (r.width > 0 && r.height > 0 && getComputedStyle(s).visibility !== 'hidden') right = Math.max(right, r.right);
		});
		return Math.round(right);
	};
	const place = () => {
		if (!frame) return;
		const left = sidebarRight();
		frame.style.left = `${left}px`;
		frame.style.width = `calc(100vw - ${left}px)`; // iframe khong tu gian theo left/right nhu div
	};
	const sync = () => {
		const open = location.hash === `#${HASH}`;
		if (open && !frame) {
			frame = document.createElement('iframe');
			frame.id = 'cqf-inbox-frame';
			frame.title = 'Hộp thư';
			frame.src = '/static/hop-thu/index.html?embed=1&v=3';
			document.body.append(frame);
			place();
		} else if (!open && frame) {
			frame.remove();
			frame = null;
		}
		const btn = document.getElementById('sidebar-cqf-inbox-button');
		btn?.classList.toggle('cqf-active', open);
		if (btn) btn.setAttribute('aria-current', open ? 'page' : 'false');
	};
	window.addEventListener('hashchange', sync);
	window.addEventListener('popstate', sync);
	window.addEventListener('resize', place);
	// SvelteKit doi URL bang history.pushState (khong co su kien): kiem lai moi 300 ms khi hop thu dang mo
	setInterval(() => {
		if (frame || location.hash === `#${HASH}`) {
			sync();
			place();
		}
	}, 300);
	// Trang Hop thu (iframe) bao so khach can xu ly moi: cap nhat ngay, khong cho 1 phut
	window.addEventListener('message', (e) => {
		if (e.origin !== location.origin || !frame || e.source !== frame.contentWindow) return;
		if (e.data?.type === 'cqf-inbox-count') {
			todo = Number(e.data.todo) || 0;
			paintCount();
		} else if (e.data?.type === 'cqf-toggle-sidebar') {
			// nut mo sidebar cua Open WebUI (dien thoai): bam ho nut goc
			document.getElementById('sidebar-toggle-button')?.click();
		}
	});

	const paintCount = () => {
		const badge = document.querySelector('#sidebar-cqf-inbox-button .cqf-inbox-count');
		if (!badge) return;
		badge.textContent = String(todo);
		badge.hidden = !todo;
		badge.title = `${todo} khách cần xử lý`;
	};

	// So khach "Can xu ly": hoi Hermes moi phut khi tab dang mo (dung token dang nhap Open WebUI).
	let api = null;
	const refreshCount = async () => {
		const token = localStorage.getItem('token');
		if (!token || document.hidden) return;
		try {
			if (api === null) {
				const cfg = await fetch('/static/hop-thu/config.json', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : {}));
				api = String(cfg.api || '').replace(/\/$/, '');
			}
			if (!api) return;
			const res = await fetch(`${api}/inbox/api/index`, { headers: { Authorization: `Bearer ${token}` } });
			if (!res.ok) return; // khong phai quan tri vien: khong hien so
			todo = ((await res.json()).items || []).filter((it) => it.status === 'can_xu_ly').length;
			paintCount();
		} catch {
			/* Hermes tat / mang loi: thu lai phut sau */
		}
	};

	let queued = false;
	const schedule = () => {
		if (queued) return;
		queued = true;
		requestAnimationFrame(() => {
			queued = false;
			addInboxLink();
			if (frame) sync(); // nut vua duoc ve lai: giu trang thai dang chon
		});
	};

	const start = () => {
		addInboxLink();
		new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
		sync();
		refreshCount();
		setInterval(refreshCount, 60000);
		document.addEventListener('visibilitychange', refreshCount);
	};
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
	else start();
})();
