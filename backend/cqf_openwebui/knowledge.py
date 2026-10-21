"""Kien thuc cua chatbot: ghi chu Markdown (kieu Obsidian), chu shop quan ly tren trang "Kien thuc" cua Open WebUI.

<cqf>/knowledge/<ten>.md   noi dung ghi chu (bot chi tra ghi chu dang bat)
<cqf>/sources/<ten>.md     ban chu cua file goc da tai len (docx, xlsx, csv, pdf, md, txt), de doi chieu so lieu
<cqf>/knowledge.json       {ten: {title, enabled, file, source, created_at, updated_at, warn}}

Ghi chu sinh tu file tai len: neu chu shop sua ma co so lieu (gia, %, SDT, thoi han...) khong co trong file goc thi
hien canh bao (warn); chu shop la nguoi quyet dinh nen bot van dung. [[ten ghi chu]] la lien ket giua cac ghi chu.
"""
import json, math, os, re, threading, time
from pathlib import Path

from . import kb

LINK = re.compile(r"\[\[([^\]|#\n]+)(?:[#|][^\]\n]*)?\]\]")
NAME = re.compile(r"[a-z0-9-]{1,80}")
MAX_UPLOAD = 15 * 1024 * 1024


class Knowledge:
    def __init__(self, home: Path):
        self.home = home
        self.kdir = home / "knowledge"
        self.sdir = home / "sources"
        for d in (self.kdir, self.sdir):
            d.mkdir(parents=True, exist_ok=True)
        self.meta_file = home / "knowledge.json"
        self.lock = threading.Lock()
        self._sig = None
        self._docs, self._df, self._avg = [], {}, 1.0

    # ---------------------------------------------------------------- meta

    def _meta(self):
        try:
            return json.loads(self.meta_file.read_text(encoding="utf-8")) if self.meta_file.exists() else {}
        except ValueError:
            return {}

    def _save_meta(self, meta):
        tmp = self.meta_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.meta_file)

    def _name(self, name):
        if not NAME.fullmatch(name or ""):
            raise kb.KbError("Tên ghi chú không hợp lệ.")
        return name

    def _unique(self, meta, title):
        base = kb.slug(title) or "ghi-chu"
        name, i = base, 2
        while name in meta:
            name, i = f"{base}-{i}", i + 1
        return name

    # ---------------------------------------------------------------- doc

    def list(self):
        meta = self._meta()
        bodies = {n: self._body(n) for n in meta}
        back = {n: [] for n in meta}
        titles = {m["title"].lower(): n for n, m in meta.items()}
        for n, body in bodies.items():
            for target in {self._resolve(t, titles, meta) for t in LINK.findall(body)} - {None, n}:
                back[target].append(n)
        return [{"name": n, "title": m["title"], "enabled": m.get("enabled", True), "file": m.get("file"),
                 "source": bool(m.get("source")), "chars": len(bodies[n]), "updated_at": m.get("updated_at"),
                 "warn": m.get("warn") or [], "backlinks": sorted(back[n])}
                for n, m in sorted(meta.items(), key=lambda kv: kv[1]["title"].lower())]

    def get(self, name):
        meta = self._meta()
        m = meta.get(self._name(name))
        if not m:
            raise kb.KbError("Không có ghi chú này.")
        item = next(x for x in self.list() if x["name"] == name)
        body = self._body(name)
        return {**item, "body": body, "headings": [(len(h), t.strip()) for h, t in re.findall(r"^(#{1,4})\s+(.+)$", body, re.M)],
                "source_text": self._source(m)}

    def _body(self, name):
        f = self.kdir / f"{name}.md"
        return f.read_text(encoding="utf-8") if f.exists() else ""

    def _source(self, m):
        f = self.sdir / (m.get("source") or "-")
        return f.read_text(encoding="utf-8") if m.get("source") and f.exists() else ""

    @staticmethod
    def _resolve(target, titles, meta):
        t = target.strip()
        return t if t in meta else titles.get(t.lower()) or meta.get(kb.slug(t)) and kb.slug(t)

    # ---------------------------------------------------------------- ghi

    def upload(self, path: Path, filename: str):
        """1 file tai len -> ban chu (sources/) + 1 ghi chu cung noi dung, bat san. Tra ghi chu."""
        if path.stat().st_size > MAX_UPLOAD:
            raise kb.KbError("File quá 15 MB.")
        reader = kb.READERS.get(Path(filename).suffix.lower())
        if not reader:
            raise kb.KbError(f"Chưa hỗ trợ {Path(filename).suffix or 'loại file này'}. Dùng Word (.docx), Excel (.xlsx), CSV, PDF có chữ, .md, .txt.")
        try:
            body = reader(path).strip()
        except kb.KbError:
            raise
        except Exception as e:  # file hong / sai dinh dang
            raise kb.KbError(f"{filename}: không đọc được ({e.__class__.__name__}). File có thể bị hỏng.")
        if not body:
            raise kb.KbError(f"{filename}: không có nội dung chữ.")
        title = re.sub(r"[-_]+", " ", Path(filename).stem).strip() or "Tài liệu"
        title = title[0].upper() + title[1:]
        with self.lock:
            meta = self._meta()
            same = next((n for n, m in meta.items() if m.get("file") == filename), None)  # tai lai cung file: thay
            name = same or self._unique(meta, title)
            (self.sdir / f"{name}.md").write_text(body + "\n", encoding="utf-8")
            (self.kdir / f"{name}.md").write_text(body + "\n", encoding="utf-8")
            now = int(time.time())
            meta[name] = {**meta.get(name, {}), "title": meta.get(name, {}).get("title", title), "file": filename,
                          "source": f"{name}.md", "enabled": meta.get(name, {}).get("enabled", True),
                          "created_at": meta.get(name, {}).get("created_at", now), "updated_at": now, "warn": []}
            self._save_meta(meta)
        return {"name": name, "replaced": bool(same), "chars": len(body)}

    def save(self, name, title, body, enabled=None, known=""):
        """Luu ghi chu (moi neu name rong). Ghi chu tu file goc: kiem so lieu so voi file goc (+ known: thong tin
        shop trong cai dat, vd hotline) -> warn."""
        title = (title or "").strip() or "Ghi chú mới"
        body = (body or "").replace("\r\n", "\n").rstrip() + "\n"
        if len(body) > 400_000:
            raise kb.KbError("Ghi chú quá dài (tối đa khoảng 400.000 ký tự): tách thành nhiều ghi chú.")
        with self.lock:
            meta = self._meta()
            if name:
                self._name(name)
                if name not in meta:
                    raise kb.KbError("Không có ghi chú này.")
            else:
                name = self._unique(meta, title)
            m = meta.get(name, {"created_at": int(time.time()), "enabled": True})
            src = self._source(m)
            warn = []
            if src:
                ev = src + "\n" + known
                warn = kb.unsupported_numbers(body, ev) + kb.unsupported_plain_numbers(body, ev)
            (self.kdir / f"{name}.md").write_text(body, encoding="utf-8")
            m.update(title=title, updated_at=int(time.time()), warn=sorted(set(warn))[:30])
            if enabled is not None:
                m["enabled"] = bool(enabled)
            meta[name] = m
            self._save_meta(meta)
        return self.get(name)

    def set_enabled(self, name, enabled):
        with self.lock:
            meta = self._meta()
            if self._name(name) not in meta:
                raise kb.KbError("Không có ghi chú này.")
            meta[name]["enabled"] = bool(enabled)
            self._save_meta(meta)

    def delete(self, name):
        with self.lock:
            meta = self._meta()
            if self._name(name) not in meta:
                raise kb.KbError("Không có ghi chú này.")
            m = meta.pop(name)
            for f in (self.kdir / f"{name}.md", self.sdir / (m.get("source") or "-")):
                if f.is_file():
                    f.unlink()
            self._save_meta(meta)

    # ---------------------------------------------------------------- tim (BM25, co dau / khong dau deu khop)

    def _load_index(self):
        files = sorted(self.kdir.glob("*.md"))
        sig = tuple((f.name, f.stat().st_mtime_ns) for f in files) + (
            (self.meta_file.stat().st_mtime_ns,) if self.meta_file.exists() else ())
        if sig == self._sig:
            return
        meta = self._meta()
        docs = []
        for n, m in meta.items():
            if not m.get("enabled", True):
                continue
            body = self._body(n)
            for i, c in enumerate(kb.chunk(f"# {m['title']}\n\n{body}")):
                toks = kb.tokens(c)
                tf = {}
                for t in toks:
                    tf[t] = tf.get(t, 0) + 1
                docs.append({"source": n, "title": m["title"], "chunk": i, "text": c, "tf": tf, "len": len(toks)})
        df = {}
        for d in docs:
            for t in d["tf"]:
                df[t] = df.get(t, 0) + 1
        self._docs, self._df = docs, df
        self._avg = sum(d["len"] for d in docs) / len(docs) if docs else 1.0
        self._sig = sig

    def search(self, query, k=6):
        with self.lock:
            self._load_index()
            docs, df, avg = self._docs, self._df, self._avg
        q, n, scored = set(kb.tokens(query)), len(docs), []
        for d in docs:
            s = 0.0
            for t in q:
                f = d["tf"].get(t)
                if f:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    s += idf * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * d["len"] / avg))
            if s > 0:
                scored.append((s, d))
        scored.sort(key=lambda x: -x[0])
        return [{"source": d["source"], "title": d["title"], "chunk": d["chunk"], "score": round(s, 3), "text": d["text"]}
                for s, d in scored[:k]]

    def read(self, name, chunk=None):
        """Doan (hoac ca ghi chu) dang bat, cho tool doc_tai_lieu."""
        meta = self._meta()
        if name not in meta or not meta[name].get("enabled", True):
            return ""
        parts = kb.chunk(f"# {meta[name]['title']}\n\n{self._body(name)}")
        if chunk is not None and 0 <= int(chunk) < len(parts):
            return parts[int(chunk)]
        return "\n\n".join(parts)[:12000]
