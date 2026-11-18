"""Săn lead rules: what the agent may save, dedupe, provinces after the merger, scoring, the Apify key.

Run from backend/: python -m pytest -q tests/test_lead.py
"""

import pytest

import conftest  # noqa: F401  (sets LEAD_HOME before the import below)
from cqf_openwebui.lead import config, db, service
from cqf_openwebui.lead.service import Actor, Refused

ADMIN = Actor("u1", "Quản trị", role="admin")
SALE = Actor("u2", "Sale", role="user")
AGENT = Actor("agent", "Agent", role="agent", is_agent=True)
TODAY = "2026-11-16"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    with db.tx() as conn:
        for table in ("opportunities", "people", "seen", "runs", "kv"):
            conn.execute(f"DELETE FROM {table}")
    stamp = 1794787200  # 2026-11-16 00:00 UTC
    monkeypatch.setattr(service, "now", lambda: stamp + 3 * 3600)
    yield


def opp(**extra):
    base = {
        "company": "Công ty Cổ phần Dược Hậu Giang",
        "industry": "duoc",
        "kind": "moi_thau",
        "title": "Thư mời báo giá gói Kính hiển vi phân cực",
        "province": "Cần Thơ",
        "equipment": ["Kính hiển vi phân cực"],
        "deadline": "2026-11-25",
        "published": "2026-11-12",
        "sources": [{"url": "https://dhgpharma.com.vn/vi/thong-bao/thu-moi-bao-gia-kinh-hien-vi?utm_source=x",
                     "title": "Thư mời báo giá"}],
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------- text helpers


def test_real_companies_named_after_places_are_kept():
    for name in ("Công ty CP Thủy sản Cà Mau", "Công ty Cổ phần Dược Hậu Giang", "Tập đoàn TH",
                 "Công ty TNHH CJ Foods Việt Nam", "Công ty Cổ phần Thực phẩm Sài Gòn", "Orion Food Vina"):
        assert not service.vague_company(name), name


def test_fold_and_company_key():
    assert service.fold("Cà Mau – Đồng Tháp") == "ca mau dong thap"
    assert service.company_key("CÔNG TY CỔ PHẦN DƯỢC HẬU GIANG") == service.company_key("Dược Hậu Giang JSC")
    assert service.company_key("Công ty TNHH Thủy sản Minh Phú") == "thuy san minh phu"


@pytest.mark.parametrize("text,new", [
    ("Bạc Liêu", "Cà Mau"), ("tỉnh Sóc Trăng", "Cần Thơ"), ("KCN VSIP Bình Dương", "TP. Hồ Chí Minh"),
    ("Long An", "Tây Ninh"), ("TP.HCM", "TP. Hồ Chí Minh"), ("Bà Rịa - Vũng Tàu", "TP. Hồ Chí Minh"),
    ("Can Tho", "Cần Thơ"), ("Quảng Nam", "Đà Nẵng"), ("KCN Trà Nóc, Cần Thơ", "Cần Thơ"), ("Thái Bình", "Hưng Yên"),
])
def test_old_and_new_province_names(text, new):
    assert service.province_of(text)[0] == new


def test_no_province_when_none_named():
    assert service.province_of("Nhà máy mới ở khu công nghiệp") == ("", "")


def test_url_key_ignores_tracking_and_www():
    a = service.url_key("https://www.example.vn/tin/abc/?utm_source=fb#top")
    assert a == service.url_key("http://example.vn/tin/abc")
    assert a != service.url_key("https://example.vn/tin/abd")


# ---------------------------------------------------------------- validation


def test_good_tender_is_saved_with_score_and_reasons():
    result = service.upsert_opportunities([opp()])
    assert len(result["created"]) == 1 and not result["rejected"]
    saved = service.get_opportunity(result["created"][0]["id"])
    assert saved["province"] == "Cần Thơ" and saved["state"] == "moi"
    assert saved["score"] >= 60
    assert any("còn hạn" in r for r in saved["score_reasons"])


@pytest.mark.parametrize("extra,reason", [
    ({"company": "Không rõ"}, "tên doanh nghiệp"),
    ({"company": "Chưa rõ tên doanh nghiệp"}, "tên doanh nghiệp"),
    ({"company": "Nhà đầu tư nước ngoài (chưa công bố)"}, "tên doanh nghiệp"),
    ({"company": "Chủ đầu tư dự án khu liên hợp dược phẩm"}, "tên doanh nghiệp"),
    ({"company": "Khu công nghiệp Phù Mỹ"}, "tên doanh nghiệp"),
    ({"company": "Cà Mau"}, "tên doanh nghiệp"),
    ({"company": "Tập đoàn thực phẩm Hàn Quốc"}, "tên doanh nghiệp"),
    ({"kind": "tin_hieu", "published": None, "deadline": None}, "không rõ ngày"),
    ({"industry": "y_te"}, "7 ngành"),
    ({"kind": "khac"}, "không hợp lệ"),
    ({"sources": []}, "link nguồn"),
    ({"province": "Hà Nội"}, "ngoài vùng"),
    ({"province": "Mặt Trăng"}, "không nhận ra tỉnh"),
    ({"deadline": "2026-11-01"}, "hết hạn"),
    ({"deadline": "cuối tháng"}, "không đọc được"),
    ({"title": ""}, "tên gói"),
])
def test_bad_items_are_refused_with_a_reason(extra, reason):
    result = service.upsert_opportunities([opp(**extra)])
    assert not result["created"] and reason in result["rejected"][0]["reason"]


def test_old_news_is_refused_but_open_tender_is_kept():
    old_project = opp(kind="du_an_moi", title="", deadline=None, published="2026-06-01")
    assert "tin cũ" in service.upsert_opportunities([old_project])["rejected"][0]["reason"]
    old_but_open = opp(published="2026-06-01", deadline="2026-12-01")
    assert service.upsert_opportunities([old_but_open])["created"]


def test_old_province_name_is_kept_for_search():
    result = service.upsert_opportunities([opp(kind="du_an_moi", title="", deadline=None, province="Bạc Liêu",
                                               company="Công ty TNHH Bột cá Hải Long", industry="bot_ca")])
    saved = service.get_opportunity(result["created"][0]["id"])
    assert saved["province"] == "Cà Mau" and saved["province_old"] == "Bạc Liêu"
    assert service.list_opportunities({"q": "bac lieu"})["total"] == 1


def test_province_found_in_location_when_missing():
    result = service.upsert_opportunities([opp(province="", location="KCN Sa Đéc, Đồng Tháp")])
    assert service.get_opportunity(result["created"][0]["id"])["province"] == "Đồng Tháp"


def test_settings_turn_industries_off():
    service.save_settings(ADMIN, {"industries": ["thuy_san"]})
    assert "đang tắt" in service.upsert_opportunities([opp()])["rejected"][0]["reason"]


# ---------------------------------------------------------------- dedupe


def test_same_project_from_two_sources_is_merged():
    first = opp(kind="tin_hieu", title="ĐTM nhà máy", deadline=None, company="Công ty CP Thủy sản Minh Phú", equipment=[],
                industry="thuy_san", province="Cà Mau",
                sources=[{"url": "https://camau.gov.vn/dtm/minh-phu"}])
    second = opp(kind="du_an_moi", title="", deadline=None, company="Minh Phú JSC", industry="thuy_san",
                 province="Cà Mau", equipment=["Hầm đông IQF"], sources=[{"url": "https://vasep.com.vn/minh-phu"}])
    service.upsert_opportunities([first])
    result = service.upsert_opportunities([second])
    assert result["merged"] and not result["created"]
    saved = service.get_opportunity(result["merged"][0]["id"])
    assert saved["kind"] == "du_an_moi" and len(saved["sources"]) == 2 and saved["equipment"] == ["Hầm đông IQF"]


def test_similar_names_are_not_merged_across_companies():
    base = dict(kind="du_an_moi", title="", deadline=None, province="Cần Thơ")
    service.upsert_opportunities([opp(company="Công ty CP Dược Hậu Giang", **base)])
    result = service.upsert_opportunities([opp(company="Công ty CP Thủy sản Hậu Giang", industry="thuy_san",
                                               sources=[{"url": "https://ts-haugiang.vn"}], **base)])
    assert result["created"]


def test_one_distinctive_word_is_the_same_company():
    base = dict(kind="du_an_moi", title="", deadline=None, province="Bình Định", industry="fnb")
    service.upsert_opportunities([opp(company="BAF", sources=[{"url": "https://news.google.com/rss/articles/x"}], **base)])
    result = service.upsert_opportunities([opp(company="Công ty TNHH Chế biến Thực phẩm BAF Bình Định",
                                               sources=[{"url": "https://cafeland.vn/baf"}], **base)])
    assert result["merged"]
    saved = service.get_opportunity(result["merged"][0]["id"])
    assert saved["sources"][0]["site"] == "cafeland.vn"  # the article before the Google News redirect


def test_same_name_without_common_words_and_places_is_merged():
    base = dict(kind="du_an_moi", title="", deadline=None, province="Gia Lai", industry="fnb")
    service.upsert_opportunities([opp(company="BAF Bình Định", sources=[{"url": "https://a.vn/baf"}], **base)])
    result = service.upsert_opportunities([opp(company="Công ty Cổ phần Nông nghiệp BAF Việt Nam",
                                               sources=[{"url": "https://b.vn/baf"}], **base)])
    assert result["merged"] and not result["created"]


def test_equipment_written_as_one_string_is_split():
    result = service.upsert_opportunities([opp(equipment="Tủ an toàn sinh học, nồi hấp tiệt trùng; máy ly tâm")])
    saved = service.get_opportunity(result["created"][0]["id"])
    assert saved["equipment"] == ["Tủ an toàn sinh học", "nồi hấp tiệt trùng", "máy ly tâm"]


def test_two_tenders_of_one_company_stay_apart():
    service.upsert_opportunities([opp()])
    result = service.upsert_opportunities([opp(title="Thư mời báo giá gói Máy đo độ cứng bán tự động",
                                               sources=[{"url": "https://dhgpharma.com.vn/vi/thong-bao/may-do-do-cung"}])])
    assert result["created"]
    assert service.list_opportunities({})["total"] == 2


def test_merge_keeps_the_sales_state():
    created = service.upsert_opportunities([opp()])["created"][0]["id"]
    service.patch_opportunity(SALE, created, {"state": "dang_theo", "note": "Gọi anh Nam thứ 2"})
    service.upsert_opportunities([opp(sources=[{"url": "https://bidwinner.info/dhg-kinh-hien-vi"}])])
    saved = service.get_opportunity(created)
    assert saved["state"] == "dang_theo" and saved["note"] == "Gọi anh Nam thứ 2" and len(saved["sources"]) == 2


def test_agent_cannot_change_sales_state():
    created = service.upsert_opportunities([opp()])["created"][0]["id"]
    with pytest.raises(Refused):
        service.patch_opportunity(AGENT, created, {"state": "bo_qua"})


# ---------------------------------------------------------------- people


def test_people_dedupe_by_linkedin_and_raise_the_score():
    opp_id = service.upsert_opportunities([opp()])["created"][0]["id"]
    before = service.get_opportunity(opp_id)["score"]
    person = {"name": "Nguyễn Văn A", "title": "Purchasing Manager", "company": "DHG Pharma",
              "linkedin_url": "https://vn.linkedin.com/in/nguyen-van-a-123?trk=x", "opportunity_id": opp_id,
              "location": "Can Tho, Vietnam"}
    first = service.upsert_people([person])
    again = service.upsert_people([{**person, "linkedin_url": "https://www.linkedin.com/in/nguyen-van-a-123/"}])
    assert first["created"] and again["merged"]
    saved = service.get_opportunity(opp_id)
    assert saved["people_count"] == 1 and saved["score"] == before + 10
    assert saved["people"][0]["role_group"] == "mua_sam" and saved["people"][0]["province"] == "Cần Thơ"


@pytest.mark.parametrize("title,group", [
    ("Plant Manager", "ky_thuat"), ("Factory Director", "ky_thuat"), ("Giám đốc Kỹ thuật", "ky_thuat"), ("QA Manager", "san_xuat_qa"),
    ("Trưởng phòng Mua hàng", "mua_sam"), ("Sales Executive", "khac"),
])
def test_role_groups_from_title(title, group):
    assert service.role_of(title) == group


def test_person_needs_name_title_and_profile_link():
    result = service.upsert_people([{"name": "LinkedIn Member", "title": "Manager", "company": "X"},
                                    {"name": "Bình", "title": "", "company": "X Co"},
                                    {"name": "Trần B", "title": "QA", "company": "Y Co",
                                     "linkedin_url": "https://linkedin.com/company/y"}])
    reasons = [r["reason"] for r in result["rejected"]]
    assert len(reasons) == 3 and "tên người" in reasons[0] and "chức danh" in reasons[1] and "hồ sơ" in reasons[2]


# ---------------------------------------------------------------- seen, runs, settings, key


def test_seen_links_are_skipped_next_time():
    urls = ["https://a.vn/1", "https://www.a.vn/1/", "https://a.vn/2"]
    assert service.unseen(urls) == ["https://a.vn/1", "https://a.vn/2"]
    service.mark_seen([{"url": "https://a.vn/1", "verdict": "không liên quan"}])
    assert service.unseen(urls) == ["https://a.vn/2"]


def test_runs_add_up_cost_for_the_month():
    run = service.start_run("cron")
    service.finish_run(run["id"], {"status": "ok", "cost_usd": 0.1234, "stats": {"created": 3}})
    assert service.month_cost() == 0.1234
    assert service.list_runs()[0]["stats"] == {"created": 3}


def test_only_admin_changes_settings_and_key():
    with pytest.raises(Refused):
        service.save_settings(SALE, {"lookback_days": 30})
    with pytest.raises(Refused):
        service.save_key(SALE, "apify_api_" + "x" * 30)


def test_settings_are_checked():
    with pytest.raises(Refused):
        service.save_settings(ADMIN, {"provinces": ["Atlantis"]})
    with pytest.raises(Refused):
        service.save_settings(ADMIN, {"max_usd_per_run": 99})
    saved = service.save_settings(ADMIN, {"priority_industries": ["bot_ca", "nope"], "seller": {"products": "máy ly tâm"}})
    assert saved["priority_industries"] == ["bot_ca"] and saved["seller"]["products"] == "máy ly tâm"


def test_key_is_sealed_and_never_shown(monkeypatch):
    monkeypatch.setattr(service, "check_key", lambda key=None: {"ok": True, "username": "u", "plan": "FREE"})
    key = "apify_api_" + "A1b2C3d4" * 4
    status = service.save_key(ADMIN, key)
    assert status["set"] and status["last4"] == key[-4:] and key not in str(status)
    assert key not in str(db.get_kv("apify_key"))
    assert service.apify_key() == key
    with pytest.raises(Refused):
        service.save_key(ADMIN, "not-a-key")


def test_bad_key_is_not_saved(monkeypatch):
    monkeypatch.setattr(service, "check_key", lambda key=None: {"ok": False, "error": "Key Apify không đúng."})
    with pytest.raises(Refused):
        service.save_key(ADMIN, "apify_api_" + "Z" * 30)
    assert not service.key_status()["set"]


def test_equipment_match_with_products_scores_more():
    service.save_settings(ADMIN, {"seller": {"products": "Kính hiển vi, máy đo độ cứng, tủ an toàn sinh học"}})
    matched = service.upsert_opportunities([opp()])["created"][0]["score"]
    other = service.upsert_opportunities([opp(title="Gói xe nâng", equipment=["Xe nâng điện"],
                                              sources=[{"url": "https://dhg.vn/xe-nang"}])])["created"][0]["score"]
    assert matched - other == 15


def test_csv_export_has_bom_and_vietnamese_headers():
    service.upsert_opportunities([opp()])
    text = service.export_csv("opportunities")
    assert text.startswith("﻿") and "Tên doanh nghiệp" in text and "Dược Hậu Giang" in text


def test_every_rule_has_title_and_text():
    assert all(r["title"] and r["text"] for r in config.RULES)


# ---------------------------------------------------------------- contact details


@pytest.mark.parametrize("raw,clean", [
    ("0903 123 456", "0903123456"), ("(+84) 292.3841.234", "02923841234"), ("84 903123456", "0903123456"),
    ("1800 6868", "18006868"), ("1800156801", ""), ("1900 1234 56", "1900123456"), ("028-3822 5050", "02838225050"), ("12345", ""), ("0103456789123", ""), ("", ""),
])
def test_phone_numbers_are_normalised_or_dropped(raw, clean):
    assert service.clean_phone(raw) == clean


@pytest.mark.parametrize("raw,clean", [
    ("Info@DHGPharma.com.vn", "info@dhgpharma.com.vn"), ("mailto:sales@vinhhoan.com", "sales@vinhhoan.com"),
    ("logo@2x.png", ""), ("name@example.com", ""), ("không có", ""),
])
def test_emails_are_checked(raw, clean):
    assert service.clean_email(raw) == clean


def contact(**extra):
    base = {"website": "https://www.dhgpharma.com.vn", "phones": [{"value": "0292 3891 433", "label": "Tổng đài"}, "12"],
            "emails": ["dhgpharma@dhgpharma.com.vn", "bad@"], "address": "288 Bis Nguyễn Văn Cừ, Cần Thơ",
            "tax_code": "1800156801", "linkedin_company": "https://vn.linkedin.com/company/dhg-pharma?trk=x",
            "sources": [{"url": "https://www.dhgpharma.com.vn/vi/lien-he", "title": "Liên hệ"}]}
    base.update(extra)
    return base


def test_company_contact_is_cleaned_and_needs_a_source():
    c = service.validate_company_contact(contact())
    assert [p["value"] for p in c["phones"]] == ["02923891433"] and c["phones"][0]["label"] == "Tổng đài"
    assert [e["value"] for e in c["emails"]] == ["dhgpharma@dhgpharma.com.vn"]
    assert c["linkedin_company"] == "https://www.linkedin.com/company/dhg-pharma"
    assert c["tax_code"] == "1800156801"
    with pytest.raises(Refused, match="nguồn"):
        service.validate_company_contact(contact(sources=[]))
    assert service.validate_company_contact({"phones": ["abc"], "sources": []})["phones"] == []


def test_contact_is_merged_rescored_and_filtered():
    saved = service.upsert_opportunities([opp(), opp(company="Công ty TNHH Thủy sản Minh Phú", industry="thuy_san",
                                                   province="Cà Mau", title="Mời chào giá tủ cấy vi sinh")])
    dhg, mp = saved["created"][0]["id"], saved["created"][1]["id"]
    before = service.get_opportunity(dhg)["score"]
    out = service.set_company_contact(dhg, contact())
    assert out["score"] == before + 10 and any("1 SĐT" in r for r in out["score_reasons"])
    out = service.set_company_contact(dhg, contact(phones=["0292 3891 434"], emails=[], website="https://other.vn"))
    cc = out["company_contact"]
    assert [p["value"] for p in cc["phones"]] == ["02923891433", "02923891434"]
    assert cc["website"] == "https://www.dhgpharma.com.vn" and cc["checked_at"]
    assert out["contact_counts"]["phones"] == 2 and out["contact_counts"]["emails"] == 1
    assert [o["id"] for o in service.list_opportunities({"contact": "co"})["items"]] == [dhg]
    assert [o["id"] for o in service.list_opportunities({"contact": "chua"})["items"]] == [mp]
    assert [o["id"] for o in service.list_opportunities({"contact": "can_tim"})["items"]] == [mp]
    assert service.list_opportunities({"q": "02923891433"})["total"] == 1
    with pytest.raises(Refused):
        service.set_company_contact("khong-co", contact())


def test_lead_contact_from_source_is_cleaned():
    saved = service.upsert_opportunities([opp(contact={"name": "Ông Nguyễn Văn A", "phone": "0903.123.456 - 0292 3891 433",
                                                       "email": "Mua.Hang@dhgpharma.com.vn"})])
    o = service.get_opportunity(saved["created"][0]["id"])
    assert o["contact"] == {"name": "Ông Nguyễn Văn A", "phone": "0903123456, 02923891433", "email": "mua.hang@dhgpharma.com.vn"}
    assert o["contact_counts"]["phones"] == 2 and o["contact_counts"]["emails"] == 1


def test_csv_has_contact_columns():
    saved = service.upsert_opportunities([opp()])
    service.set_company_contact(saved["created"][0]["id"], contact())
    text = service.export_csv("opportunities")
    head, row = text.splitlines()[0], text.splitlines()[1]
    assert "SĐT doanh nghiệp" in head and "LinkedIn công ty" in head
    assert "02923891433 (Tổng đài)" in row and "dhgpharma@dhgpharma.com.vn" in row


def test_old_database_gets_the_new_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE opportunities (id TEXT PRIMARY KEY, contact TEXT NOT NULL DEFAULT '{}')")
    db._migrate(conn)
    assert "company_contact" in {r[1] for r in conn.execute("PRAGMA table_info(opportunities)")}
    db._migrate(conn)  # twice is fine


# ---------------------------------------------------------------- proxy


@pytest.mark.parametrize("raw,url", [
    ("171.253.1.2:21951:user:pa55", "http://user:pa55@171.253.1.2:21951"),
    ("proxy.vn:8080", "http://proxy.vn:8080"),
    ("http://u:p@proxy.vn:3128/", "http://u:p@proxy.vn:3128"),
])
def test_proxy_formats(raw, url):
    assert service.parse_proxy(raw) == url


def test_bad_proxy_is_refused():
    for raw in ("", "abc", "socks5://u:p@h:1080", "h:port:u:p"):
        with pytest.raises(Refused):
            service.parse_proxy(raw)


def test_proxy_is_sealed_checked_and_admin_only(monkeypatch):
    monkeypatch.setattr(service, "check_proxy", lambda url=None: {"ok": True, "ip": "171.253.1.2", "checked_at": 1, "error": ""})
    with pytest.raises(Refused):
        service.save_proxy(SALE, "171.253.1.2:21951:user:pa55")
    status = service.save_proxy(ADMIN, "171.253.1.2:21951:user:pa55")
    assert status["set"] and status["host"] == "171.253.1.2:21951" and "pa55" not in str(status)
    assert "pa55" not in str(db.get_kv("proxy"))  # stored sealed
    assert service.agent_config()["proxy"] == "http://user:pa55@171.253.1.2:21951"
    service.delete_proxy(ADMIN)
    assert not service.proxy_status()["set"]


def test_failing_proxy_is_not_saved(monkeypatch):
    monkeypatch.setattr(service, "check_proxy", lambda url=None: {"ok": False, "error": "Không đi qua được proxy: timeout"})
    with pytest.raises(Refused, match="proxy"):
        service.save_proxy(ADMIN, "171.253.1.2:21951:user:pa55")
    assert not service.proxy_status()["set"]


@pytest.mark.parametrize("title,note,ok", [
    ("Kỹ sư bảo trì điện (đang tìm cơ hội mới)", "", False),
    ("Nhân viên vệ sinh công nghiệp / an toàn", "", False),
    ("QA Manager", "Đầu mối gián tiếp: từng làm tại VISSAN", False),
    ("Marketing Intern", "", False),
    ("International Business Manager", "", True),
    ("Procurement Manager", "Phụ trách mua sắm", True),
    ("Trưởng phòng An toàn - Bảo vệ môi trường", "", True),
])
def test_people_who_are_not_current_staff_are_refused(title, note, ok):
    item = {"name": "Nguyễn Văn A", "title": title, "company": "Công ty Cổ phần Dược Hậu Giang",
            "linkedin_url": "https://vn.linkedin.com/in/nguyen-van-a", "sales_note": note}
    if ok:
        assert service.validate_person(item, service.get_settings())["title"] == title
    else:
        with pytest.raises(Refused, match="không còn làm"):
            service.validate_person(item, service.get_settings())


# ---------------------------------------------------------------- freshness


def test_tender_without_deadline_must_be_recent_and_dated():
    ok = service.upsert_opportunities([opp(deadline=None, published="2026-11-10")])
    assert ok["created"]
    for extra, reason in (({"deadline": None, "published": "2026-10-20"}, "quá 14 ngày"),
                          ({"deadline": None, "published": None}, "không rõ ngày")):
        out = service.upsert_opportunities([opp(title="Gói khác " + reason, **extra)])
        assert not out["created"] and reason in out["rejected"][0]["reason"]


def test_month_in_file_link_dates_an_old_tender():
    item = opp(deadline=None, published=None,
               sources=[{"url": "https://dhgpharma.com.vn/sites/default/files/2025-09/TMCG-may.pdf"}])
    out = service.upsert_opportunities([item])
    assert "tin cũ (2025-09-30" in out["rejected"][0]["reason"]


def test_old_event_in_a_new_article_is_refused():
    project = opp(kind="mo_rong", title="Mở rộng nhà máy", deadline=None, published="2026-11-10")
    out = service.upsert_opportunities([{**project, "event_date": "2026-03"}])
    assert "việc đã diễn ra từ 2026-03-31" in out["rejected"][0]["reason"]
    assert service.upsert_opportunities([{**project, "event_date": "2026-12"}])["created"]  # a plan, not old news


def test_stale_items_are_hidden_but_kept(monkeypatch):
    saved = service.upsert_opportunities([opp(), opp(kind="du_an_moi", title="Nhà máy mới", deadline=None,
                                                    published="2026-11-01",
                                                    sources=[{"url": "https://baocantho.com.vn/nha-may-moi-dhg"}])])
    tender, project = saved["created"][0]["id"], saved["created"][1]["id"]
    later = 1794787200 + 30 * 86400  # 16/12/2026: tender deadline 25/11 passed, project news is 45 days old
    monkeypatch.setattr(service, "now", lambda: later)
    monkeypatch.setattr(service, "_today", lambda: service.date(2026, 12, 16))
    data = service.list_opportunities({"fresh": "1"})
    assert data["items"] == [] and data["stale"] == 2
    old = {o["id"]: o["stale"] for o in service.list_opportunities({"fresh": "0"})["items"]}
    assert old == {tender: "hết hạn", project: "tin cũ"}


def test_agency_contact_in_an_article_is_not_the_company_contact():
    project = opp(kind="du_an_moi", title="Tổ hợp chế biến", deadline=None, published="2026-11-15", province="Đắk Lắk",
                  company="Công ty Cổ phần Đầu tư Nông lâm Nhật Nhật An", industry="cam_hoa_chat",
                  contact={"name": "Trung tâm Xúc tiến đầu tư", "phone": "0262 3778 788", "email": "ttxtdt@khdt.daklak.gov.vn"})
    o = service.get_opportunity(service.upsert_opportunities([project])["created"][0]["id"])
    assert o["contact"] == {"name": "", "phone": "", "email": ""}
    tender = opp(company="Viện Kiểm nghiệm thuốc TP.HCM", contact={"name": "Phòng Vật tư", "phone": "028 3855 1234",
                                                                    "email": "vattu@ivdc.gov.vn"})
    t = service.get_opportunity(service.upsert_opportunities([tender])["created"][0]["id"])
    assert t["contact"]["email"] == "vattu@ivdc.gov.vn"  # a public body's own procurement contact is kept


def test_one_article_is_one_opportunity_even_if_the_province_differs():
    src = [{"url": "https://moneyf.vn/thuy-san-minh-phu-mo-rong-san-xuat", "published": "2026-11-08"}]
    a = opp(company="Công ty CP Tập đoàn Thủy sản Minh Phú", industry="thuy_san", kind="mo_rong", deadline=None,
            title="Mở rộng sản xuất", province="Cà Mau", published="2026-11-08", sources=src)
    b = {**a, "province": "Khánh Hòa", "title": "Mở rộng nhà máy Minh Phú Khánh An"}
    first = service.upsert_opportunities([a])
    second = service.upsert_opportunities([b])
    assert first["created"] and second["merged"] and not second["created"]


def test_guessed_equipment_is_only_what_the_seller_sells():
    service.save_settings(ADMIN, {"seller": {"company": "Đức Dương SCI", "products": "Máy phân tích NIR, máy phân tích đạm, tủ sấy, cân phân tích"}})
    guess = ["Máy nghiền nguyên liệu", "Máy ép viên", "Máy phân tích NIR", "Máy sấy", "Máy phân tích đạm", "Tủ sấy",
             "Cân phân tích", "Cân định lượng"]
    project = opp(kind="du_an_moi", title="Tổ hợp chế biến", deadline=None, equipment=guess, equipment_inferred=True)
    o = service.get_opportunity(service.upsert_opportunities([project])["created"][0]["id"])
    assert o["equipment"] == ["Máy phân tích NIR", "Máy phân tích đạm", "Tủ sấy", "Cân phân tích"] and o["equipment_inferred"]
    stated = opp(title="Gói máy nghiền", equipment=["Máy nghiền nguyên liệu"], equipment_inferred=False,
                 sources=[{"url": "https://dhgpharma.com.vn/vi/thong-bao/goi-may-nghien"}])
    s = service.get_opportunity(service.upsert_opportunities([stated])["created"][0]["id"])
    assert s["equipment"] == ["Máy nghiền nguyên liệu"]  # what the source says is kept as is


def test_guess_never_keeps_production_machinery():
    products = ("Thiết bị phân tích phòng Lab QA/QC. Thiết bị: tủ an toàn sinh học, tủ sấy, máy phân tích NIR "
                "(thức ăn chăn nuôi, ngũ cốc), máy phân tích đạm, cân phân tích")
    items = ["Máy trộn thức ăn chăn nuôi", "Dây chuyền chế biến thực phẩm", "Máy phân tích NIR",
             "Thiết bị kiểm nghiệm vi sinh", "Tủ an toàn sinh học", "Máy ép viên"]
    assert service._seller_items(items, products) == ["Máy phân tích NIR", "Thiết bị kiểm nghiệm vi sinh",
                                                      "Tủ an toàn sinh học"]


@pytest.mark.parametrize("name,vague", [
    ("Seafood", True), ("SEAFOOD INDUSTRY", True), ("Food Company Vietnam", True),
    ("Minh Phu Seafood Corporation", False), ("Bien Dong Seafood", False), ("Nutifood Việt Nam", False),
    ("Công ty CP Tập đoàn Thủy sản Minh Phú", False),
])
def test_company_made_of_industry_words_only_is_vague(name, vague):
    assert bool(service.vague_company(name)) == vague
