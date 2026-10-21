/*
 * Open WebUI custom loader (Agoobi). Open WebUI tu nap file nay tren moi trang (/static/loader.js).
 * Viec lam:
 * 1. The HTML cua hop thu chatbot (chat "Tong quan hop thu") chay trong iframe sandbox, khong tu chuyen trang
 *    duoc: no gui postMessage {type: "cqf-open-chat", chatId}, file nay mo chat do.
 * 2. Them nut "Hop thu" (trang /static/hop-thu/index.html) vao sidebar.
 * 3. Danh dau 3 folder cua hop thu (Can xu ly / Dang chat / Da xong) va chat Tong quan bang data-cqf
 *    de custom.css trinh bay theo nhom. Chi doc chu, khong sua DOM cua Open WebUI.
 * Hop dong voi Hermes: docs/dong-bo.md.
 */
(() => {
	const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
	const FOLDERS = { 'Cần xử lý': 'can-xu-ly', 'Đang chat': 'dang-chat', 'Đã xong': 'da-xong' };
	const OVERVIEW = 'Tổng quan hộp thư';

	window.addEventListener('message', (event) => {
		const data = event.data;
		if (!data || data.type !== 'cqf-open-chat' || !UUID.test(String(data.chatId || ''))) return;
		// chi nhan tu iframe nam trong trang nay (the nhung cua Open WebUI)
		const fromEmbed = [...document.querySelectorAll('iframe')].some((f) => f.contentWindow === event.source);
		if (!fromEmbed) return;
		window.location.assign(`/c/${data.chatId}`);
	});

	// Nut "Hop thu" ngay duoi nut chat moi trong sidebar (Svelte ve lai sidebar thi them lai).
	const INBOX_ICON =
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>';
	const addInboxLink = () => {
		document.querySelectorAll('#sidebar-new-chat-button').forEach((btn) => {
			const host = btn.closest('a, button')?.parentElement || btn.parentElement;
			if (!host || host.querySelector(':scope > [data-cqf-inbox]')) return;
			const a = document.createElement('a');
			a.href = '/static/hop-thu/index.html';
			a.dataset.cqfInbox = '';
			a.className = 'cqf-inbox-link';
			a.innerHTML = INBOX_ICON; // icon co dinh
			const label = document.createElement('span');
			label.textContent = 'Hộp thư';
			a.append(label);
			a.title = 'Hộp thư chatbot website';
			(btn.closest('a, button') || btn).after(a);
		});
	};

	const mark = () => {
		addInboxLink();
		document.querySelectorAll('[id^="folder-"][id$="-button"]').forEach((btn) => {
			const name = btn.querySelector('.truncate')?.textContent?.trim();
			const key = FOLDERS[name];
			if (key && btn.dataset.cqf !== key) btn.dataset.cqf = key;
		});
		document.querySelectorAll('#sidebar a, #sidebar [draggable="true"]').forEach((el) => {
			const text = el.textContent?.trim();
			if (text === OVERVIEW && el.dataset.cqf !== 'tong-quan') el.dataset.cqf = 'tong-quan';
		});
	};

	let queued = false;
	const schedule = () => {
		if (queued) return;
		queued = true;
		requestAnimationFrame(() => {
			queued = false;
			mark();
		});
	};

	const start = () => {
		mark();
		new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
	};
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
	else start();
})();
