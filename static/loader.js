/*
 * Open WebUI custom loader (Agoobi). Open WebUI tu nap file nay tren moi trang (/static/loader.js).
 * Them 4 hang vao sidebar, ngay duoi hang Search: Hop thu (kem so khach can xu ly), Chatbot (cai dat), Thu chatbot, Kien thuc.
 * Bam 1 hang thi trang tuong ung mo trong vung noi dung, sidebar giu nguyen (Ctrl/Cmd + bam: tab rieng).
 * Du lieu: backend cqf_openwebui chay trong Open WebUI (/api/v1/cqf). Khong sua gi khac cua Open WebUI.
 * Bam vao cau truc sidebar cua Open WebUI 0.11.4 (#sidebar-search-button): nang ban thi kiem lai.
 */
(() => {
	const V = 10; // doi khi doi trang de khong dinh cache
	const icon = (d) =>
		`<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
	const PAGES = [
		{ hash: 'hop-thu', label: 'Hộp thư', src: '/static/hop-thu/index.html', badge: true,
			icon: icon('<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>') },
		{ hash: 'chatbot', label: 'Chatbot', src: '/static/chatbot/index.html',
			icon: icon('<path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2M20 14h2M15 13v2M9 13v2"/>') },
		{ hash: 'thu-chat', label: 'Thử chatbot', src: '/static/thu-chat/index.html',
			icon: icon('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="m10 8 4 2.5-4 2.5z"/>') },
		{ hash: 'kien-thuc', label: 'Kiến thức', src: '/static/kien-thuc/index.html',
			icon: icon('<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/><path d="M8 7h8M8 11h6"/>') }
	];
	let todo = 0;
	let frame = null;
	let openHash = null;

	const current = () => PAGES.find((p) => location.hash === `#${p.hash}`) || null;

	// ------------------------------------------------------------ hang trong sidebar
	const addRows = () => {
		const search = document.getElementById('sidebar-search-button');
		const row = search?.parentElement;
		if (!row || row.nextElementSibling?.dataset?.cqfRow != null) return;
		let after = row;
		for (const p of PAGES) {
			const wrap = document.createElement('div');
			wrap.className = row.className; // cung class voi hang New Chat / Search
			wrap.dataset.cqfRow = p.hash;
			const a = document.createElement('a');
			a.id = `sidebar-cqf-${p.hash}-button`;
			a.href = `#${p.hash}`;
			a.className = 'group grow flex items-center space-x-2 rounded-xl px-2 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-900 transition outline-none';
			a.setAttribute('aria-label', p.label);
			a.innerHTML =
				`<div class="self-center flex size-4 shrink-0 items-center justify-center">${p.icon}</div>` +
				`<div class="flex flex-1 self-center translate-y-[0.5px]"><div class=" self-center text-[0.8125rem] leading-5">${p.label}</div></div>` +
				(p.badge ? '<span class="cqf-inbox-count" hidden></span>' : '');
			a.addEventListener('click', (e) => {
				e.preventDefault();
				if (e.metaKey || e.ctrlKey || e.shiftKey) return void window.open(p.src, '_blank');
				if (location.hash !== `#${p.hash}`) history.pushState(history.state, '', `${location.pathname}${location.search}#${p.hash}`);
				sync();
			});
			wrap.append(a);
			after.after(wrap);
			after = wrap;
		}
		paintCount();
		sync();
	};

	const paintCount = () => {
		const badge = document.querySelector('#sidebar-cqf-hop-thu-button .cqf-inbox-count');
		if (!badge) return;
		badge.textContent = String(todo);
		badge.hidden = !todo;
		badge.title = `${todo} khách cần xử lý`;
	};

	// ------------------------------------------------------------ trang mo trong vung noi dung
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
		const page = current();
		if (page && openHash !== page.hash) {
			frame?.remove();
			frame = document.createElement('iframe');
			frame.id = 'cqf-inbox-frame';
			frame.title = page.label;
			frame.src = `${page.src}?embed=1&v=${V}`;
			document.body.append(frame);
			openHash = page.hash;
			place();
		} else if (!page && frame) {
			frame.remove();
			frame = null;
			openHash = null;
		}
		for (const p of PAGES) {
			const btn = document.getElementById(`sidebar-cqf-${p.hash}-button`);
			btn?.classList.toggle('cqf-active', p.hash === openHash);
			btn?.setAttribute('aria-current', p.hash === openHash ? 'page' : 'false');
		}
	};
	window.addEventListener('hashchange', sync);
	window.addEventListener('popstate', sync);
	window.addEventListener('resize', place);
	setInterval(() => { // SvelteKit doi URL bang pushState (khong co su kien)
		if (frame || current()) { sync(); place(); }
	}, 300);
	window.addEventListener('message', (e) => {
		if (e.origin !== location.origin || !frame || e.source !== frame.contentWindow) return;
		if (e.data?.type === 'cqf-inbox-count') { todo = Number(e.data.todo) || 0; paintCount(); }
		else if (e.data?.type === 'cqf-toggle-sidebar') document.getElementById('sidebar-toggle-button')?.click();
	});

	// ------------------------------------------------------------ so khach can xu ly (moi phut)
	const refreshCount = async () => {
		let token = '';
		try { token = localStorage.getItem('token') || ''; } catch { /* bo qua */ }
		if (!token || document.hidden) return;
		try {
			const res = await fetch('/api/v1/cqf/status', { headers: { Authorization: `Bearer ${token}` } });
			if (!res.ok) return; // khong phai quan tri vien: khong hien
			todo = (await res.json()).todo || 0;
			paintCount();
		} catch { /* thu lai phut sau */ }
	};

	let queued = false;
	const schedule = () => {
		if (queued) return;
		queued = true;
		requestAnimationFrame(() => { queued = false; addRows(); });
	};
	const start = () => {
		addRows();
		sync();
		new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
		refreshCount();
		setInterval(refreshCount, 60000);
		document.addEventListener('visibilitychange', refreshCount);
	};
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
	else start();
})();
