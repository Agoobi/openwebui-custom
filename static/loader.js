/*
 * Open WebUI custom loader (Agoobi). Open WebUI tu nap file nay tren moi trang (/static/loader.js).
 * Viec lam:
 * 1. The HTML cua hop thu chatbot (chat "Tong quan hop thu") chay trong iframe sandbox, khong tu chuyen trang
 *    duoc: no gui postMessage {type: "cqf-open-chat", chatId}, file nay mo chat do.
 * 2. Danh dau 3 folder cua hop thu (Can xu ly / Dang chat / Da xong) va chat Tong quan bang data-cqf
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

	const mark = () => {
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
