#!/usr/bin/env python3
"""Doc tai lieu (docx, xlsx, csv, pdf, md, txt), chia doan, tim BM25, kiem so lieu.
Chep tu skill chatbot-tu-van (Agoobi/skills-hubs); cqf_openwebui chi dung cac ham doc file, so lieu, chunk, Index.
Phan CLI / MCP ben duoi giu nguyen de doi chieu voi ban goc.

Ban goc: Kho tai lieu cho skill chatbot-tu-van. Chi dung thu vien chuan.

Lenh: ingest | list | status | verify | search | remove | mcp
- ingest: doi file khach gui (docx, xlsx, pdf, txt, md, csv) sang Markdown trong nguon/ (ban goc, bot KHONG doc).
- agent soan kien thuc theo chu de vao knowledge/<chu-de>.md, dong 2 ghi: <!-- nguon: a.md, b.md -->
- verify: moi so lieu (gia, %, SDT, so dai) trong knowledge/ phai co trong file nguon da ghi. Dat thi ghi nhan;
  bot CHI dung file knowledge da verify va chua bi sua sau do (kiem bang code, khong phu thuoc agent).
- status: nguon moi / nguon da doi / file kien thuc can soan lai hoac chua verify.
- search: tim BM25 (co dau va khong dau deu khop), in JSON.
- mcp: chay MCP server qua stdio cho Hermes (tool tim/doc tai lieu, luu khach, chuyen nhan vien).

Thu muc du lieu: --home, hoac env CHATBOT_HOME, mac dinh $HERMES_HOME/chatbot (hoac ~/.hermes/chatbot).
Module nay cung duoc plugin chatbot_guard import (setup.py chep vao plugin).
"""
import argparse, csv, hashlib, hmac, io, json, logging, math, os, re, shutil, subprocess, sys, time, unicodedata
import urllib.request, urllib.error, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger("chatbot_kb")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CHUNK_CHARS = 900
SERVER_NAME = "kb"
PROTOCOL = "2025-06-18"


def home(arg=None):
    if arg:
        return Path(arg).expanduser()
    try:  # gateway nhieu profile (multiplex): env la cua profile mac dinh, home that nam o override theo luot
        from hermes_constants import get_hermes_home_override
        override = get_hermes_home_override()
        if override:
            return Path(override).expanduser() / "chatbot"
    except ImportError:
        pass
    if os.environ.get("CHATBOT_HOME"):
        return Path(os.environ["CHATBOT_HOME"]).expanduser()
    hh = os.environ.get("HERMES_HOME")
    return (Path(hh).expanduser() if hh else Path.home() / ".hermes") / "chatbot"


def settings(h):
    f = h / "settings.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def die(msg):
    out({"ok": False, "error": msg})
    sys.exit(1)


# ---------------------------------------------------------------- chuan hoa tieng Viet

def fold(text):
    """'Bảo hành ĐỔI trả' -> 'bao hanh doi tra'"""
    t = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def tokens(text):
    words = re.findall(r"[a-z0-9]+", fold(text))
    return words + [a + "_" + b for a, b in zip(words, words[1:])]


def slug(text):
    return "-".join(re.findall(r"[a-z0-9]+", fold(text)))[:60] or "tai-lieu"


# ---------------------------------------------------------------- doc file

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _docx_text(el):
    """Chu trong 1 doan/o: <w:br/> thanh xuong dong, <w:tab/> thanh dau cach (khong de chu dinh nhau)."""
    out = []
    for n in el.iter():
        if n.tag == W + "t":
            out.append(n.text or "")
        elif n.tag in (W + "br", W + "cr"):
            out.append("\n")
        elif n.tag == W + "tab":
            out.append(" ")
    return re.sub(r"[ \t]*\n[ \t]*", "\n", "".join(out)).strip()


def read_docx(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    body = root.find(W + "body")
    for el in body:
        if el.tag == W + "p":
            text = _docx_text(el)
            style = el.find(f"{W}pPr/{W}pStyle")
            level = 0
            if style is not None:
                m = re.search(r"(\d)$", style.get(W + "val", ""))
                if "heading" in style.get(W + "val", "").lower() and m:
                    level = int(m.group(1))
            if text and level:
                lines.append("#" * min(level, 4) + " " + text.replace("\n", " "))
            elif text and el.find(f"{W}pPr/{W}numPr") is not None:  # dong danh sach
                lines.append("- " + text.replace("\n", " "))
            elif text:
                lines.append(text.replace("\n", "  \n"))
        elif el.tag == W + "tbl":
            rows = [[_docx_text(c).replace("\n", " ") for c in row.iter(W + "tc")] for row in el.iter(W + "tr")]
            rows = [r for r in rows if any(r)]
            if rows:
                lines.append(rows_to_md(rows))
    return "\n\n".join(lines)


R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DATE_FMTS = set(range(14, 23)) | {45, 46, 47}  # ma dinh dang ngay co san cua Excel
PCT_FMTS = {9, 10}


def _xlsx_formats(z):
    """style index (thuoc tinh s cua o) -> 'pct' / 'date' / None, doc tu xl/styles.xml."""
    if "xl/styles.xml" not in z.namelist():
        return []
    st = ET.fromstring(z.read("xl/styles.xml"))
    custom = {int(f.get("numFmtId")): f.get("formatCode", "") for f in st.iter(S + "numFmt")}
    kinds = []
    xfs = st.find(S + "cellXfs")
    for xf in (xfs if xfs is not None else []):
        fid = int(xf.get("numFmtId", 0))
        code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", custom.get(fid, ""))  # bo chu trong ngoac kep, [mau], \x
        if fid in PCT_FMTS or "%" in code:
            kinds.append("pct")
        elif fid in DATE_FMTS or (fid in custom and re.search(r"[dy]|m{3,}", code, re.I)):
            kinds.append("date")
        else:
            kinds.append(None)
    return kinds


def _xlsx_value(raw, kind):
    """So luu trong Excel -> chu nhu Excel hien: 0.1 + dinh dang % -> '10%', 46387 + dinh dang ngay -> '31/12/2026'."""
    try:
        v = float(raw)
    except ValueError:
        return raw
    if kind == "pct":
        return _plain(v * 100) + "%"
    if kind == "date" and 0 < v < 2958466:
        d = datetime(1899, 12, 30, tzinfo=timezone.utc) + timedelta(days=v)
        return d.strftime("%d/%m/%Y %H:%M" if v % 1 else "%d/%m/%Y")
    return _plain(v) if abs(v) < 1e15 else raw


def _plain(v):
    """1500000.0 -> '1500000', 0.15000000000000002 -> '0.15' (khong dung dang 1.5e+06)."""
    v = round(v, 6)
    return str(int(v)) if v == int(v) else f"{v:.6f}".rstrip("0")


def read_xlsx(path):
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(S + "si"):
                shared.append("".join(t.text or "" for t in si.iter(S + "t")))
        fmts = _xlsx_formats(z)
        # thu tu va ten sheet theo workbook.xml; file sheetN.xml tim qua rels (sheet doi cho thi so N khong doi)
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(PR + "Relationship")}
        parts = []
        for s in wb.iter(S + "sheet"):
            target = rels.get(s.get(R + "id"), "")
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if target not in z.namelist():
                continue
            rows = []
            for row in ET.fromstring(z.read(target)).iter(S + "row"):
                vals = []
                for c in row.iter(S + "c"):
                    col = re.match(r"[A-Z]+", c.get("r", ""))
                    if col:  # o trong bi bo qua trong XML: chen lai cho dung cot
                        idx = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(col.group(0)))) - 1
                        vals += [""] * (idx - len(vals))
                    v = c.find(S + "v")
                    if c.get("t") == "s" and v is not None:
                        vals.append(shared[int(v.text)])
                    elif c.get("t") == "inlineStr":
                        vals.append("".join(t.text or "" for t in c.iter(S + "t")))
                    elif v is not None and v.text and c.get("t") in (None, "n"):
                        s_idx = int(c.get("s", 0))
                        vals.append(_xlsx_value(v.text, fmts[s_idx] if s_idx < len(fmts) else None))
                    else:
                        vals.append(v.text if v is not None and v.text else "")
                if any(x.strip() for x in vals):
                    rows.append(vals)
            if rows:
                parts.append(f"## {s.get('name')}\n\n" + rows_to_md(rows))
    return "\n\n".join(parts)


def rows_to_md(rows):
    """Moi dong thanh 1 cau 'Cot: gia tri' de tim kiem va trich dan chinh xac.
    Dong tieu de (vd 'BANG GIA 2026' gop o phia tren bang) giu nguyen; dong dau tien du day moi la ten cot."""
    filled = [sum(1 for v in r if v.strip()) for r in rows]
    width = max(filled)
    h = next((i for i, n in enumerate(filled) if n >= max(2, (width + 1) // 2)), 0) if width > 1 else 0
    lines = [" ".join(v.strip() for v in r if v.strip()) for r in rows[:h]]
    head = [x.strip() for x in rows[h]]
    for r in rows[h + 1:]:
        pairs = [f"{head[j] if j < len(head) and head[j] else 'Cot ' + str(j + 1)}: {v.strip()}"
                 for j, v in enumerate(r) if v.strip()]
        if pairs:
            lines.append("- " + "; ".join(pairs))
    return "\n".join(lines) if len(rows) > h + 1 else "\n".join("- " + " | ".join(r) for r in rows)


def read_csv(path):
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    return rows_to_md(list(csv.reader(io.StringIO(text))))


class KbError(Exception):
    """Loi doc / nap tai lieu, thong diep tieng Viet de hien cho chu shop."""


def read_pdf(path):
    if not shutil.which("pdftotext"):
        raise KbError("Máy chủ chưa cài pdftotext (gói poppler-utils) nên chưa đọc được PDF. Đổi sang Word hoặc cài poppler-utils.")
    res = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True)
    if res.returncode != 0:
        raise KbError(f"Không đọc được PDF: {res.stderr[:200]}")
    text = res.stdout.strip()
    if len(re.sub(r"\s", "", text)) < 50:
        raise KbError("PDF gần như không có chữ (ảnh scan). Dùng bản Word/Excel hoặc PDF có chữ.")
    return text


# ---------------------------------------------------------------- so lieu (dung chung: chatbot_guard + verify)

MONEY = re.compile(r"(\d[\d.,]*)\s*(tỷ|tỉ|triệu|tr|nghìn|ngàn|k|đồng|đ|vnđ|vnd|₫)(?:\s*(\d)(?![\d.,%]))?(?![a-zà-ỹ])", re.I)
DURATION = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ngày|tháng|năm|tuần|giờ|tiếng|phút|h)(?![a-zà-ỹ])", re.I)
PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(%|phần trăm)", re.I)
PHONE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\d)")
GROUPED = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?![\d.,]*\d)")  # 99.000 / 1.200.000: gia khong don vi
NUMBER = re.compile(r"\d[\d.,]*")
LONGNUM = re.compile(r"(?<![\d.,])\d(?:[\d.\- ]*\d)?(?![\d])")  # so tai khoan, ma don
UNITS = {"tỷ": 1e9, "tỉ": 1e9, "triệu": 1e6, "tr": 1e6, "nghìn": 1e3, "ngàn": 1e3, "k": 1e3}


def _num(raw: str):
    """'1.500.000' / '1,500,000' -> 1500000; '1,5' / '2.5' -> so thap phan; '1200000' -> 1200000."""
    raw = raw.strip(".,")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
        return float(re.sub(r"[.,]", "", raw))
    if re.fullmatch(r"\d+[.,]\d+", raw):
        return float(raw.replace(",", "."))
    digits = re.sub(r"\D", "", raw)
    return float(digits) if digits else None


def _key(v):
    return round(v, 2)


def _money(text: str):
    """[(chuoi, gia tri VND)] cho so co don vi tien va so dang 99.000 khong don vi."""
    res, spans = [], []
    for m in MONEY.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            unit = UNITS.get(m.group(2).lower(), 1)
            if m.group(3) and unit >= 1e3:  # "1tr5" = 1,5 trieu, "2 triệu 5" = 2,5 trieu
                v += int(m.group(3)) / 10
            res.append((m.group(0), _key(v * unit)))
            spans.append(m.span())
    for m in GROUPED.finditer(text):
        if not any(a <= m.start() < b for a, b in spans):
            res.append((m.group(0), _key(_num(m.group(0)))))
            spans.append(m.span())
    return res, spans


def _phones(text: str):
    return {re.sub(r"\D", "", p).removeprefix("84").lstrip("0") for p in PHONE.findall(text)}


def unsupported_numbers(response: str, evidence: str, user_text: str = ""):
    """Danh sach so lieu trong cau tra loi KHONG co can cu.
    - tien: gia tri (da quy doi don vi) phai co trong tai lieu (so co don vi, so 99.000, hoac so tron nhu o Excel)
    - %: chi so voi % trong tai lieu ("30 ngay" khong lam can cu cho "30%")
    - SDT: co trong tai lieu / lien he / cau khach vua gui (bot nhac lai SDT khach)
    - so dai >= 6 chu so (tai khoan, ma): phai co nguyen chuoi so trong tai lieu
    - thoi han (24 thang, 3 ngay): con so phai co trong tai lieu hoac cau khach vua gui (chi so so, khong so don vi)
    Gia/% khach tu noi ("giam 50% dung khong?") KHONG tinh la can cu."""
    bad = []
    ev_money = {v for _, v in _money(evidence)[0]}
    ev_money |= {_key(v) for v in (_num(m.group(0)) for m in NUMBER.finditer(evidence)) if v is not None}
    money, spans = _money(response)
    bad += [raw for raw, v in money if v not in ev_money]

    ev_pct = {_key(_num(m.group(1))) for m in PERCENT.finditer(evidence)}
    for m in PERCENT.finditer(response):
        spans.append(m.span())
        if _key(_num(m.group(1))) not in ev_pct:
            bad.append(m.group(0))

    # thoi han (bao hanh 24 thang, giao 3 ngay): so phai co trong tai lieu hoac cau khach vua hoi
    ev_nums = {_key(v) for v in (_num(m.group(0)) for m in NUMBER.finditer(evidence + "\n" + user_text)) if v is not None}
    for m in DURATION.finditer(response):
        if any(a <= m.start() < b for a, b in spans):
            continue
        spans.append(m.span())
        if _key(_num(m.group(1))) not in ev_nums:
            bad.append(m.group(0))

    ok_phones = _phones(evidence) | _phones(user_text)
    for m in PHONE.finditer(response):
        spans.append(m.span())
        if re.sub(r"\D", "", m.group(0)).removeprefix("84").lstrip("0") not in ok_phones:
            bad.append(m.group(0))

    ev_digits = {re.sub(r"\D", "", m.group(0)) for m in LONGNUM.finditer(evidence)}
    for m in LONGNUM.finditer(response):
        d = re.sub(r"\D", "", m.group(0))
        if len(d) >= 6 and not any(a <= m.start() < b for a, b in spans) and d not in ev_digits:
            bad.append(m.group(0).strip())
    return bad


LIST_MARK = re.compile(r"^\s*\d+[.)]\s", re.M)


def unsupported_plain_numbers(text: str, evidence: str):
    """Cho verify (chat hon guard): so tran nhu '24 thang', '7 ngay' cung phai co trong nguon.
    Bo qua so da xet theo tien/%/SDT (vd '1,5 trieu' = '1.500.000d') va so thu tu dau dong danh sach."""
    skip = [m.span() for r in (MONEY, PERCENT, PHONE, GROUPED, LIST_MARK, NGUON_LINE) for m in r.finditer(text)]
    ev = {_key(v) for v in (_num(m.group(0)) for m in NUMBER.finditer(evidence)) if v is not None}
    bad = []
    for m in NUMBER.finditer(text):
        if any(a <= m.start() < b for a, b in skip):
            continue
        v = _num(m.group(0))
        if v is not None and _key(v) not in ev:
            bad.append(m.group(0).strip(".,"))
    return bad


READERS = {".docx": read_docx, ".xlsx": read_xlsx, ".csv": read_csv, ".pdf": read_pdf,
           ".md": lambda p: Path(p).read_text(encoding="utf-8"), ".txt": lambda p: Path(p).read_text(encoding="utf-8")}


def kdir(h):
    d = h / "knowledge"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ndir(h):
    d = h / "nguon"
    d.mkdir(parents=True, exist_ok=True)
    return d


NGUON_LINE = re.compile(r"<!--\s*nguon:\s*(.*?)\s*-->")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def verified(h):
    """{file kien thuc: {"hash", "nguon": {ten: hash}}} cua lan verify dat gan nhat."""
    f = h / "kiem_tra.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        return {}


def sources_of(text):
    m = NGUON_LINE.search(text[:2000])
    return [s.strip() for s in m.group(1).split(",") if s.strip()] if m else []


def cmd_ingest(a):
    h = home(a.home)
    done = []
    names = [slug(a.title or Path(f).stem) for f in a.files]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:  # vd bang-gia.docx + bang-gia.pdf: cung ten nguon, file sau se de file truoc
        die(f"Nhieu file cung ten {dup}: doi ten file hoac nap tung file voi --title khac nhau.")
    for f in a.files:
        p = Path(f)
        reader = READERS.get(p.suffix.lower())
        if not reader:
            die(f"Khong ho tro {p.suffix}. Dung: {', '.join(READERS)} (doi .doc/.xls sang .docx/.xlsx).")
        body = reader(p).strip()
        if not body:
            die(f"{p.name}: khong doc duoc noi dung.")
        name = slug(a.title or p.stem) + ".md"
        title = a.title or p.stem
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dst = ndir(h) / name
        prev = dst.read_text(encoding="utf-8") if dst.exists() else None
        old = prev.split("\n", 4)[-1] if prev else None
        m = re.search(r"<!-- file goc: (.*?), nap ", prev or "")
        dst.write_text(f"# {title}\n\n<!-- file goc: {p.name}, nap {stamp} -->\n\n{body}\n", encoding="utf-8")
        done.append({"file": p.name, "saved": f"nguon/{name}", "chars": len(body),
                     "replaced": old is not None, "changed": old is not None and old.strip() != body,
                     **({"thay_file_khac": m.group(1)} if m and m.group(1) != p.name else {})})
    out({"ok": True, "nguon_dir": str(ndir(h)), "ingested": done,
         "next": "Doc file nguon, soan/cap nhat knowledge/<chu-de>.md (dong 2: <!-- nguon: ... -->), "
                 "cho user duyet, roi chay verify. Xem status de biet file kien thuc nao bi anh huong."})


def cmd_list(a):
    h = home(a.home)
    out({"nguon": [{"file": f.name, "chars": f.stat().st_size} for f in sorted(ndir(h).glob("*.md"))],
         "knowledge": [{"file": f.name, "chars": f.stat().st_size} for f in sorted(kdir(h).glob("*.md"))]})


def knowledge_state(h):
    """Tinh trang tung file kien thuc + nguon chua duoc dung. Dung cho status, check.py."""
    ver, nd = verified(h), h / "nguon"  # chi doc: khong tao thu muc (check.py dung ham nay)
    nguon = {f.name: sha(f) for f in sorted(nd.glob("*.md"))}
    files, used = [], set()
    for f in sorted((h / "knowledge").glob("*.md")):
        srcs = sources_of(f.read_text(encoding="utf-8"))
        used.update(srcs)
        v = ver.get(f.name)
        if not v or v.get("hash") != sha(f):
            state = "chua_verify"  # moi soan / da sua tay: bot chua dung
        elif any(nguon.get(s) != hv for s, hv in v.get("nguon", {}).items()):
            state = "nguon_da_doi"  # bot van dung ban cu; can soan lai theo nguon moi
        else:
            state = "ok"
        files.append({"file": f.name, "state": state, "nguon": srcs,
                      "nguon_doi": [s for s, hv in (v or {}).get("nguon", {}).items() if nguon.get(s) != hv]})
    return {"knowledge": files, "nguon_chua_dung": [n for n in nguon if n not in used]}


def cmd_status(a):
    st = knowledge_state(home(a.home))
    todo = [f for f in st["knowledge"] if f["state"] != "ok"]
    out({"ok": not todo and not st["nguon_chua_dung"], **st,
         "note": "chua_verify: bot CHUA dung file nay. nguon_da_doi: bot dang dung ban cu, soan lai theo nguon moi roi verify. "
                 "nguon_chua_dung: chua co file kien thuc nao lay tu nguon nay."})


def cmd_verify(a):
    """So lieu trong moi file kien thuc phai co trong cac file nguon no ghi (va thong tin lien he trong settings)."""
    h = home(a.home)
    ver, nd = verified(h), ndir(h)
    biz = " ".join(str(v) for v in (settings(h).get("business") or {}).values())
    files = [kdir(h) / f for f in a.files] if a.files else sorted(kdir(h).glob("*.md"))
    res, all_ok = [], True
    for f in files:
        if f.parent.resolve() != kdir(h).resolve() or f.suffix != ".md" or not f.exists():
            die(f"Khong co file kien thuc {f.name} trong knowledge/")
        text = f.read_text(encoding="utf-8")
        srcs = sources_of(text)
        missing = [s for s in srcs if not (nd / s).is_file() or (nd / s).resolve().parent != nd.resolve()]
        if not srcs or missing:
            err = "thieu dong <!-- nguon: ten-file.md --> o dau file" if not srcs else f"khong co trong nguon/: {missing}"
            res.append({"file": f.name, "ok": False, "loi": err})
            all_ok = False
            continue
        evidence = "\n".join((nd / s).read_text(encoding="utf-8") for s in srcs) + "\n" + biz
        bad = unsupported_numbers(text, evidence) + unsupported_plain_numbers(text, evidence)
        if bad:
            res.append({"file": f.name, "ok": False, "so_lieu_khong_co_trong_nguon": bad})
            all_ok = False
            continue
        ver[f.name] = {"hash": sha(f), "nguon": {s: sha(nd / s) for s in srcs},
                       "time": datetime.now(timezone.utc).isoformat()}
        res.append({"file": f.name, "ok": True, "nguon": srcs})
    for name in [n for n in ver if not (kdir(h) / n).exists()]:
        ver.pop(name)
    tmp = h / "kiem_tra.json.tmp"
    tmp.write_text(json.dumps(ver, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(h / "kiem_tra.json")
    out({"ok": all_ok, "files": res,
         "note": "File loi thi bot KHONG dung. Sua cho dung nguon (khong doan so), hoi user neu nguon mau thuan."})
    if not all_ok:
        sys.exit(1)


def cmd_remove(a):
    d = (ndir if a.nguon else kdir)(home(a.home)).resolve()
    f = (d / a.file).resolve()
    if f.parent != d or f.suffix != ".md":  # chi xoa file .md nam ngay trong knowledge/ (hoac nguon/)
        die(f"Chi xoa duoc file .md trong {d} (vd: bang-gia.md)")
    if not f.exists():
        die(f"Khong co {a.file}")
    f.unlink()
    out({"ok": True, "removed": a.file})


# ---------------------------------------------------------------- tim kiem

def chunk(text):
    """Cat theo doan, gom den ~CHUNK_CHARS, giu tieu de gan nhat lam ngu canh."""
    chunks, cur, heading = [], "", ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para or para.startswith("<!--"):
            continue
        if para.startswith("#"):
            heading = para.lstrip("# ").strip().split("\n")[0][:120]
        if cur and len(cur) + len(para) > CHUNK_CHARS:
            chunks.append(cur)
            cur = (f"[{heading}]\n" if heading and not para.startswith("#") else "")
        cur = (cur + "\n\n" + para).strip()
        head = f"[{heading}]\n" if heading else ""
        while len(cur) > CHUNK_CHARS * 2:  # doan qua dai (bang lon): cat theo dong, dong qua dai thi theo khoang trang
            # cat phai nam SAU tieu de dau doan, neu khong doan con lai y nguyen -> lap vo han
            cut = cur.rfind("\n", len(head) + 1, CHUNK_CHARS)
            if cut <= len(head):
                cut = cur.rfind(" ", len(head) + 1, CHUNK_CHARS)
            if cut <= len(head):
                cut = CHUNK_CHARS
            chunks.append(cur[:cut])
            cur = head + cur[cut:].strip()
    if cur:
        chunks.append(cur)
    return chunks


class Index:
    def __init__(self, h):
        self.dir = kdir(h)
        self.sig = None
        self.docs = []

    def _load(self):
        state = self.dir.parent / "kiem_tra.json"
        files = sorted(self.dir.glob("*.md"))
        sig = tuple((f.name, f.stat().st_mtime_ns) for f in files) + ((state.stat().st_mtime_ns,) if state.exists() else ())
        if sig == self.sig:
            return
        ver = verified(self.dir.parent)
        # chi dung file da verify va chua bi sua sau do; file khac coi nhu khong co
        files = [f for f in files if (ver.get(f.name) or {}).get("hash") == sha(f)]
        self.skipped = sorted(set(x.name for x in self.dir.glob("*.md")) - {f.name for f in files})
        if self.skipped:
            logger.warning("Bo qua file kien thuc chua verify: %s", self.skipped)
        docs = []
        for f in files:
            for i, c in enumerate(chunk(f.read_text(encoding="utf-8"))):
                toks = tokens(c)
                tf = {}
                for t in toks:
                    tf[t] = tf.get(t, 0) + 1
                docs.append({"source": f.name, "chunk": i, "text": c, "tf": tf, "len": len(toks)})
        self.df = {}
        for d in docs:
            for t in d["tf"]:
                self.df[t] = self.df.get(t, 0) + 1
        self.avg = sum(d["len"] for d in docs) / len(docs) if docs else 1
        self.docs, self.sig = docs, sig

    def search(self, query, k=5):
        self._load()
        q = set(tokens(query))
        n = len(self.docs)
        scored = []
        for d in self.docs:
            s = 0.0
            for t in q:
                f = d["tf"].get(t)
                if f:
                    idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                    s += idf * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * d["len"] / self.avg))
            if s > 0:
                scored.append((s, d))
        scored.sort(key=lambda x: -x[0])
        return [{"source": d["source"], "chunk": d["chunk"], "score": round(s, 3), "text": d["text"]} for s, d in scored[:k]]

    def get(self, source, chunk_no=None):
        self._load()
        parts = [d for d in self.docs if d["source"] == source and (chunk_no is None or d["chunk"] == chunk_no)]
        return "\n\n".join(d["text"] for d in parts)


def cmd_search(a):
    out({"query": a.query, "results": Index(home(a.home)).search(a.query, a.limit)})


# ---------------------------------------------------------------- lead / chuyen nhan vien

# Thong tin bot duoc xin khach (settings.json > thu_thap_khach), theo thu tu admin chon.
FIELDS = {"ten": "tên", "sdt": "số điện thoại", "email": "email", "zalo": "số Zalo",
          "dia_chi": "địa chỉ", "cong_ty": "tên công ty", "thoi_gian": "thời gian tiện liên hệ"}
DEFAULT_FIELDS = ["ten", "sdt"]


def lead_fields(s):
    v = s.get("thu_thap_khach", DEFAULT_FIELDS)
    return [f for f in (v if isinstance(v, list) else DEFAULT_FIELDS) if f in FIELDS]


def fallback_text(s):
    """Cau thay the khi khong tra loi duoc: fallback_text neu admin dat, khong thi ghep tu thu_thap_khach."""
    if s.get("fallback_text"):
        return s["fallback_text"]
    labels = [FIELDS[f] for f in lead_fields(s)]
    if labels:
        ask = ", ".join(labels[:-1]) + " và " + labels[-1] if len(labels) > 1 else labels[0]
        return f"Dạ câu này em chưa có thông tin chính xác. Anh/chị để lại {ask}, nhân viên bên em sẽ liên hệ tư vấn ngay ạ."
    hotline = (s.get("business") or {}).get("hotline")
    return ("Dạ câu này em chưa có thông tin chính xác. Anh/chị vui lòng liên hệ "
            + (f"hotline {hotline}" if hotline else "nhân viên bên em") + " để được tư vấn ạ.")


def record(h, kind, data):
    """Ghi vao leads.jsonl va day qua webhook (ky HMAC) neu co cau hinh."""
    evt = {"type": kind, "time": datetime.now(timezone.utc).isoformat(), **data}
    # SDT khach la du lieu ca nhan: file chi chu so huu doc duoc
    fd = os.open(h / "leads.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(evt, ensure_ascii=False) + "\n")
    hook = settings(h).get("lead_webhook") or {}
    if not hook.get("url"):
        return {"saved": True, "webhook": "chua cau hinh"}
    body = json.dumps(evt, ensure_ascii=False).encode()
    ts = str(int(time.time()))
    headers = {"Content-Type": "application/json", "X-Chatbot-Timestamp": ts}
    if hook.get("secret"):
        sig = hmac.new(hook["secret"].encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
        headers["X-Chatbot-Signature"] = "sha256=" + sig
    try:
        with urllib.request.urlopen(urllib.request.Request(hook["url"], body, headers, method="POST"), timeout=15) as r:
            return {"saved": True, "webhook": r.status}
    except (urllib.error.URLError, OSError, ValueError) as e:  # ValueError: URL webhook sai dinh dang
        return {"saved": True, "webhook": f"loi: {e}"}


# ---------------------------------------------------------------- MCP server (stdio, JSON-RPC 2.0)

TOOLS = [
    {"name": "tim_kien_thuc",
     "description": "Tim trong tai lieu cua doanh nghiep (san pham, gia, chinh sach, FAQ). Bat buoc goi truoc khi tra loi. "
                    "Goi lai voi cach dien dat khac neu ket qua chua du.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 5}},
                     "required": ["query"]}},
    {"name": "doc_tai_lieu",
     "description": "Doc nguyen van mot tai lieu hoac mot doan (source, chunk lay tu ket qua tim_kien_thuc).",
     "inputSchema": {"type": "object", "properties": {"source": {"type": "string"}, "chunk": {"type": "integer"}},
                     "required": ["source"]}},
    {"name": "luu_khach_hang",
     "description": "Luu thong tin lien he khach tu cung cap (SDT, email, Zalo...) de nhan vien lien he. "
                    "Chi ghi dung nhu khach viet, khong tu dien.",
     "inputSchema": {"type": "object", "properties": {**{f: {"type": "string"} for f in FIELDS},
                                                      "nhu_cau": {"type": "string"}},
                     "required": ["nhu_cau"]}},
    {"name": "chuyen_nhan_vien",
     "description": "Bao nhan vien vao ho tro: khieu nai, bao gia dac biet, cau hoi ngoai tai lieu, khach yeu cau gap nguoi.",
     "inputSchema": {"type": "object", "properties": {"ly_do": {"type": "string"}, "tom_tat": {"type": "string"},
                                                      "lien_he": {"type": "string"}},
                     "required": ["ly_do", "tom_tat"]}},
]


def call_tool(h, idx, name, args):
    if name == "tim_kien_thuc":
        res = idx.search(args.get("query", ""), int(args.get("limit") or 5))
        if not res:
            return "KHONG TIM THAY trong tai lieu. Thu cach dien dat khac; neu van khong co thi noi chua co thong tin va chuyen nhan vien."
        return "\n\n---\n\n".join(f"[{r['source']}#{r['chunk']}]\n{r['text']}" for r in res)
    if name == "doc_tai_lieu":
        text = idx.get(args.get("source", ""), args.get("chunk"))
        return text or "Khong co tai lieu/doan nay."
    if name in ("luu_khach_hang", "chuyen_nhan_vien"):
        res = record(h, "lead" if name == "luu_khach_hang" else "handoff", args)
        return json.dumps({"ok": True, **res}, ensure_ascii=False)
    raise KeyError(name)


def cmd_mcp(a):
    h = home(a.home)
    idx = Index(h)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:  # notification (initialized, cancelled...)
            continue
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                      "capabilities": {"tools": {}}, "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                text = call_tool(h, idx, params.get("name"), params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": text}], "isError": False}
            except KeyError:
                reply = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool {params.get('name')}"}}
                print(json.dumps(reply, ensure_ascii=False), flush=True)
                continue
            except Exception as e:  # loi doc file... van tra ve cho agent
                result = {"content": [{"type": "text", "text": f"Loi: {e}"}], "isError": True}
        elif method == "ping":
            result = {}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}, ensure_ascii=False), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--home", help="Thu muc du lieu chatbot (mac dinh $HERMES_HOME/chatbot)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("ingest")
    s.add_argument("files", nargs="+")
    s.add_argument("--title", help="Ten tai lieu (chi dung khi ingest 1 file)")
    s.set_defaults(f=cmd_ingest)
    sp.add_parser("list").set_defaults(f=cmd_list)
    sp.add_parser("status").set_defaults(f=cmd_status)
    s = sp.add_parser("verify")
    s.add_argument("files", nargs="*", help="Ten file trong knowledge/ (bo trong = tat ca)")
    s.set_defaults(f=cmd_verify)
    s = sp.add_parser("remove")
    s.add_argument("file")
    s.add_argument("--nguon", action="store_true", help="Xoa file trong nguon/ thay vi knowledge/")
    s.set_defaults(f=cmd_remove)
    s = sp.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(f=cmd_search)
    sp.add_parser("mcp").set_defaults(f=cmd_mcp)
    a = ap.parse_args()
    if a.cmd == "ingest" and a.title and len(a.files) > 1:
        die("--title chi dung khi ingest 1 file.")
    a.f(a)


if __name__ == "__main__":
    main()
