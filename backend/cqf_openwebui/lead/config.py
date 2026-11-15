"""Săn lead: lists, defaults and the rules shown to people.

Every label and rule is written once here and reused by the API, the page and the agent skill (san-lead-b2b), so
what the page says is what the code does. Data lives in <DATA_DIR of Open WebUI>/cqf/lead/ (mode 700); LEAD_HOME
overrides it (tests).
"""

import json
import os
import secrets
from pathlib import Path


def _home() -> Path:
    if os.environ.get("LEAD_HOME"):
        path = Path(os.environ["LEAD_HOME"])
    else:
        from ..store import root  # inside Open WebUI: <DATA_DIR>/cqf

        path = root() / "lead"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _private_file(path: Path, make) -> str:
    if not path.exists():
        path.write_text(make())
        os.chmod(path, 0o600)
    return path.read_text().strip()


def _fernet_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


DATA_DIR = _home()
DB_PATH = DATA_DIR / "lead.db"
SECRET_KEY = os.environ.get("LEAD_SECRET_KEY") or _private_file(DATA_DIR / "secret.key", _fernet_key)

# The agent (Hermes on the same machine) calls /agent/* with this token. agent.json: {"token": "..."}.
AGENT_FILE = DATA_DIR / "agent.json"


def agent_token() -> str:
    data = {}
    if AGENT_FILE.exists():
        try:
            data = json.loads(AGENT_FILE.read_text())
        except ValueError:
            data = {}
    if not data.get("token"):
        data["token"] = secrets.token_urlsafe(32)
        AGENT_FILE.write_text(json.dumps(data, indent=2))
        os.chmod(AGENT_FILE, 0o600)
    return data["token"]


BASE_PATH = "/#san-lead"
APIFY_API = "https://api.apify.com/v2"
HTTP_TIMEOUT_SECONDS = 25
MAX_BATCH = 200  # items per agent save call
MAX_LIST = 500  # rows per page in the lists

# ---------------------------------------------------------------- industries (the 7 groups of the brief)

INDUSTRIES = {
    "duoc": "Dược phẩm & Sinh phẩm y tế",
    "thu_y": "Thuốc thú y & Chế phẩm sinh học",
    "thuy_san": "Chế biến & Xuất khẩu thủy hải sản",
    "bot_ca": "Bột cá, mỡ cá & phụ phẩm thủy sản",
    "fnb": "Thực phẩm, đồ uống & sữa",
    "my_pham": "Mỹ phẩm & hóa mỹ phẩm",
    "cam_hoa_chat": "Thức ăn chăn nuôi, thủy sản & hóa chất",
}
INDUSTRY_SHORT = {
    "duoc": "Dược phẩm",
    "thu_y": "Thú y",
    "thuy_san": "Thủy sản XK",
    "bot_ca": "Bột cá / dầu cá",
    "fnb": "F&B",
    "my_pham": "Mỹ phẩm",
    "cam_hoa_chat": "Cám / hóa chất",
}

# What kind of opportunity it is.
KINDS = {
    "moi_thau": "Mời thầu / chào giá thiết bị",
    "du_an_moi": "Dự án nhà máy mới",
    "mo_rong": "Mở rộng / nâng cấp nhà máy",
    "tin_hieu": "Tín hiệu khác (tuyển dụng, ĐTM, cấp phép)",
}
# Plant status asked by the brief: running plant (brownfield) or new project (greenfield).
PLANT_STATUS = {"dang_chay": "Nhà máy đang chạy", "du_an_moi": "Dự án nhà máy mới", "chua_ro": "Chưa rõ"}

STATES = {
    "moi": "Mới",
    "dang_theo": "Đang theo",
    "da_lien_he": "Đã liên hệ",
    "bo_qua": "Bỏ qua",
}

# Who the person is for the sale (brief, module 1 B).
ROLE_GROUPS = {
    "ky_thuat": "Kỹ thuật, dự án, ban giám đốc nhà máy",
    "san_xuat_qa": "Sản xuất, chất lượng, R&D",
    "mua_sam": "Mua sắm, ban điều hành",
    "khac": "Khác",
}

# ---------------------------------------------------------------- provinces after the merger of 1/7/2025

# The brief lists provinces by their old names. Since 1/7/2025 Viet Nam has 34 provinces; news and gov pages now use
# the new names. Leads are filed under the new name; the old names are kept so search and matching find both.
PROVINCES = {
    "Đà Nẵng": ["Đà Nẵng", "Quảng Nam"],
    "Quảng Ngãi": ["Quảng Ngãi", "Kon Tum"],
    "Gia Lai": ["Gia Lai", "Bình Định"],
    "Đắk Lắk": ["Đắk Lắk", "Phú Yên"],
    "Khánh Hòa": ["Khánh Hòa", "Ninh Thuận"],
    "Lâm Đồng": ["Lâm Đồng", "Đắk Nông", "Bình Thuận"],
    "TP. Hồ Chí Minh": ["TP. Hồ Chí Minh", "Bình Dương", "Bà Rịa - Vũng Tàu"],
    "Đồng Nai": ["Đồng Nai", "Bình Phước"],
    "Tây Ninh": ["Tây Ninh", "Long An"],
    "Đồng Tháp": ["Đồng Tháp", "Tiền Giang"],
    "Vĩnh Long": ["Vĩnh Long", "Bến Tre", "Trà Vinh"],
    "Cần Thơ": ["Cần Thơ", "Sóc Trăng", "Hậu Giang"],
    "Cà Mau": ["Cà Mau", "Bạc Liêu"],
    "An Giang": ["An Giang", "Kiên Giang"],
}
# Provinces outside the default region (from Đà Nẵng southwards), so a lead elsewhere is filed, not lost.
OTHER_PROVINCES = {
    "Hà Nội": ["Hà Nội"], "Hải Phòng": ["Hải Phòng", "Hải Dương"], "Huế": ["Huế", "Thừa Thiên Huế"],
    "Quảng Ninh": ["Quảng Ninh"], "Bắc Ninh": ["Bắc Ninh", "Bắc Giang"], "Hưng Yên": ["Hưng Yên", "Thái Bình"],
    "Ninh Bình": ["Ninh Bình", "Nam Định", "Hà Nam"], "Thanh Hóa": ["Thanh Hóa"], "Nghệ An": ["Nghệ An"],
    "Hà Tĩnh": ["Hà Tĩnh"], "Quảng Trị": ["Quảng Trị", "Quảng Bình"], "Phú Thọ": ["Phú Thọ", "Vĩnh Phúc", "Hòa Bình"],
    "Thái Nguyên": ["Thái Nguyên", "Bắc Kạn"], "Lào Cai": ["Lào Cai", "Yên Bái"], "Tuyên Quang": ["Tuyên Quang", "Hà Giang"],
    "Lạng Sơn": ["Lạng Sơn"], "Cao Bằng": ["Cao Bằng"], "Điện Biên": ["Điện Biên"], "Lai Châu": ["Lai Châu"],
    "Sơn La": ["Sơn La"],
}
# Other spellings seen in sources -> new province.
PROVINCE_ALIASES = {
    "hồ chí minh": "TP. Hồ Chí Minh", "tp hcm": "TP. Hồ Chí Minh", "tp.hcm": "TP. Hồ Chí Minh", "hcm": "TP. Hồ Chí Minh",
    "sài gòn": "TP. Hồ Chí Minh", "thành phố hồ chí minh": "TP. Hồ Chí Minh", "ho chi minh city": "TP. Hồ Chí Minh",
    "vũng tàu": "TP. Hồ Chí Minh", "bà rịa vũng tàu": "TP. Hồ Chí Minh", "brvt": "TP. Hồ Chí Minh",
    "da nang": "Đà Nẵng", "can tho": "Cần Thơ", "ca mau": "Cà Mau", "dong thap": "Đồng Tháp", "dong nai": "Đồng Nai",
    "binh duong": "TP. Hồ Chí Minh", "long an": "Tây Ninh", "tien giang": "Đồng Tháp", "ben tre": "Vĩnh Long",
    "soc trang": "Cần Thơ", "bac lieu": "Cà Mau", "kien giang": "An Giang", "khanh hoa": "Khánh Hòa",
    "binh dinh": "Gia Lai", "phu yen": "Đắk Lắk", "ninh thuan": "Khánh Hòa", "binh thuan": "Lâm Đồng",
    "quang nam": "Đà Nẵng", "quang ngai": "Quảng Ngãi", "hau giang": "Cần Thơ", "vinh long": "Vĩnh Long",
    "tra vinh": "Vĩnh Long", "an giang": "An Giang", "tay ninh": "Tây Ninh", "binh phuoc": "Đồng Nai",
    "khánh hoà": "Khánh Hòa", "thừa thiên huế": "Huế", "phú quốc": "An Giang",
}
REGION_DEFAULT = list(PROVINCES)

# ---------------------------------------------------------------- settings

DEFAULT_SETTINGS = {
    "seller": {
        "company": "",
        "products": "",  # what the seller sells: equipment lines, brands; used for the AI sales note and scoring
        "avoid": "",  # what not to chase (e.g. medical devices for hospitals)
    },
    "industries": list(INDUSTRIES),
    "priority_industries": [],
    "provinces": REGION_DEFAULT,
    "kinds": list(KINDS),
    "sources": {
        "news": True,  # Google News RSS (free)
        "watch": True,  # list pages watched for new links (free)
        "google": True,  # Google search through Apify
        "linkedin": True,  # people through Apify (LinkedIn)
    },
    "watch_pages": [],  # [{"url", "label"}]; empty = the built-in list in the skill
    "extra_keywords": [],  # extra equipment / signal words to search
    "google_queries_per_run": 18,
    "people_per_opportunity": 4,
    "linkedin_sweep_per_run": 25,  # profiles found by title x industry (module 1), once a week; 0 = off
    "min_score_for_people": 55,
    "max_usd_per_run": 0.6,
    "max_usd_per_month": 4.5,  # stop before the Apify plan's monthly limit
    "lookback_days": 45,
    "llm_model": "",  # empty = the model Hermes uses
}

RULES = [
    {
        "key": "flow",
        "title": "Agent tìm, bạn quyết",
        "text": "Agent (Hermes) quét nguồn, đọc tin, ghi cơ hội và người liên hệ vào đây. Agent không gửi tin, "
        "không gọi, không email cho ai. Bạn chọn Đang theo / Đã liên hệ / Bỏ qua.",
    },
    {
        "key": "signal-first",
        "title": "Tìm công ty sắp mua trước, tìm người sau",
        "text": "Agent tìm tín hiệu mua (mời chào giá, dự án mới, mở rộng, ĐTM, tuyển người cho nhà máy mới) rồi mới "
        "tìm người ra quyết định ở đúng công ty đó, cộng thêm một lượt tìm theo chức danh và ngành.",
    },
    {
        "key": "source",
        "title": "Mỗi cơ hội có link gốc",
        "text": "Không có link nguồn thì không lưu. Thông tin không có trong nguồn thì để trống, agent không đoán "
        "tên người, số điện thoại hay hạn chót. Thiết bị agent tự suy ra được đánh dấu \"gợi ý\".",
    },
    {
        "key": "dedupe",
        "title": "Không trùng",
        "text": "Cùng công ty, cùng loại cơ hội, cùng tỉnh thì gộp làm một, thêm link nguồn mới vào. Link đã đọc rồi "
        "thì lần quét sau bỏ qua. Người liên hệ gộp theo link LinkedIn.",
    },
    {
        "key": "province",
        "title": "Tỉnh theo tên mới (sau 1/7/2025)",
        "text": "Cơ hội được xếp theo tỉnh mới; tên tỉnh cũ trong nguồn vẫn được giữ và tìm được. Ví dụ: Bạc Liêu → "
        "Cà Mau, Sóc Trăng và Hậu Giang → Cần Thơ, Bình Dương → TP. Hồ Chí Minh, Long An → Tây Ninh.",
    },
    {
        "key": "score",
        "title": "Điểm 0–100",
        "text": "Điểm cộng từ: loại cơ hội (mời thầu còn hạn cao nhất), ngành ưu tiên, tỉnh trong vùng, tin còn mới, "
        "thiết bị khớp với hàng bạn bán, có người liên hệ. Lý do cộng điểm hiện cạnh từng cơ hội.",
    },
    {
        "key": "budget",
        "title": "Chi phí Apify có trần",
        "text": "Agent dừng gọi Apify khi một lần quét chạm trần mỗi lần, hoặc tài khoản Apify chạm trần tháng đặt ở "
        "đây. Google News và trang theo dõi không tốn tiền.",
    },
    {
        "key": "key",
        "title": "Key Apify",
        "text": "Chỉ quản trị viên nhập hoặc đổi key. Key được mã hoá khi lưu, không hiện lại trên trang; agent trên "
        "cùng máy lấy key qua token riêng.",
    },
    {
        "key": "privacy",
        "title": "Thông tin liên hệ",
        "text": "Chỉ lưu thông tin công việc công khai (chức danh, công ty, link LinkedIn, email / số của doanh "
        "nghiệp có trong nguồn). Ai yêu cầu xoá thì xoá. Luật Bảo vệ dữ liệu cá nhân có hiệu lực từ 1/1/2026.",
    },
]
