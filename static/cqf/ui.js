/* Tien ich chung cho cac trang cqf (Chatbot, Kien thuc) mo trong Open WebUI: API cung origin, giao dien, thong bao. */
window.CQF = (() => {
	'use strict';

	// Giao dien sang / toi theo cai dat cua Open WebUI
	const theme = (() => { try { return localStorage.getItem('theme') || 'system'; } catch { return 'system'; } })();
	const dark = theme === 'dark' || theme === 'oled-dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
	document.documentElement.classList.toggle('dark', dark);

	// Nhung trong Open WebUI (loader.js mo ?embed=1 canh sidebar)
	const embed = new URLSearchParams(location.search).has('embed') && window.parent !== window;
	document.documentElement.classList.toggle('embed', embed);
	const tell = (msg) => { if (embed) window.parent.postMessage(msg, location.origin); };

	class AuthError extends Error {}

	async function api(path, opts = {}) {
		let token = '';
		try { token = localStorage.getItem('token') || ''; } catch { /* bo qua */ }
		if (!token) throw new AuthError('auth');
		const isForm = opts.body instanceof FormData;
		const res = await fetch('/api/v1/cqf' + path, {
			...opts,
			headers: { Authorization: `Bearer ${token}`, ...(opts.body && !isForm ? { 'Content-Type': 'application/json' } : {}) }
		});
		if (res.status === 401 || res.status === 403) throw new AuthError('auth');
		const data = await res.json().catch(() => ({}));
		if (!res.ok) throw new Error(data.detail || `Lỗi ${res.status}`);
		return data;
	}

	const $ = (id) => document.getElementById(id);
	function el(tag, cls, text) {
		const n = document.createElement(tag);
		if (cls) n.className = cls;
		if (text != null) n.textContent = text;
		return n;
	}

	let toastTimer;
	function toast(text) {
		let t = $('cqf-toast');
		if (!t) {
			t = el('div', 'toast');
			t.id = 'cqf-toast';
			t.setAttribute('role', 'status');
			document.body.append(t);
		}
		t.textContent = text;
		t.hidden = false;
		clearTimeout(toastTimer);
		toastTimer = setTimeout(() => (t.hidden = true), 2800);
	}

	function authScreen(container) {
		container.replaceChildren();
		const box = el('div', 'empty');
		box.append(el('h2', '', 'Cần đăng nhập quản trị viên'));
		const p = el('p');
		p.append('Trang này chỉ dành cho quản trị viên Open WebUI. ');
		const a = el('a', '', 'Đăng nhập');
		a.href = '/auth';
		p.append(a, ' rồi mở lại.');
		box.append(p);
		container.append(box);
	}

	// Nut goc trai (thanh tren tren dien thoai): mo sidebar cua Open WebUI khi dang nhung
	document.addEventListener('DOMContentLoaded', () => {
		const home = document.querySelector('[data-cqf-home]');
		if (embed && home) {
			home.title = 'Mở sidebar';
			home.setAttribute('aria-label', 'Mở sidebar');
			home.addEventListener('click', (e) => { e.preventDefault(); tell({ type: 'cqf-toggle-sidebar' }); });
		}
	});

	const clock = (ts) => (ts ? new Date(ts * 1000).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }) : '—');

	return { api, AuthError, $, el, toast, authScreen, embed, tell, clock };
})();
