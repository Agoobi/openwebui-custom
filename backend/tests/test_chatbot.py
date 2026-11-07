"""Chatbot: the customer's own number, returning customers, chasing, repeated questions, Markdown on Zalo.

The LLM is a script: each test says what the model "writes" and reads back what the customer got and what the model
was told (system prompt, reminder)."""

import asyncio

import pytest

from cqf_openwebui import engine as eng
from cqf_openwebui import inbox as inbox_mod
from cqf_openwebui import zalo
from cqf_openwebui.engine import Engine
from cqf_openwebui.inbox import Inbox

SETTINGS = {
    "llm": {"base_url": "https://llm.example/v1", "model": "m"},
    "business": {"ten": "Đức Dương SCI", "hotline": "0902 920 577 – 0902 799 455"},
    "thu_thap_khach": ["ten", "sdt", "zalo", "cong_ty"],
    "tu_van": {"vai_tro": "so_bo", "do_dai": "ngan"},
    "max_tool_rounds": 0,
}
BRIEF = "[KHÁCH NÀY] (đã trao đổi trước"
CONV = "zalo:8033759480027692019"
DAY = 86400


class NoDocs:
    def search(self, query, k=6):
        return []

    def read(self, name, chunk=None):
        return ""


class Model:
    """Scripted LLM: replies in order, records the messages it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    async def __call__(self, llm, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        reply = self.replies.pop(0) if self.replies else "Dạ em chào anh ạ."
        if isinstance(reply, tuple):  # ("tool", {...}) then the text of the next round
            yield reply
            return
        for i in range(0, len(reply), 7):  # arrive in pieces, like a stream
            yield "text", reply[i:i + 7]

    def system(self, call=-1):
        return self.seen[call][0]["content"]

    def reminder(self, call=-1):
        return self.seen[call][-1]["content"]


@pytest.fixture
def bot(tmp_path, monkeypatch):
    clock = {"now": 1794019338.0}  # 07/11/2026 09:42 giờ Việt Nam
    monkeypatch.setattr(eng.time, "time", lambda: clock["now"])
    monkeypatch.setattr(inbox_mod.time, "time", lambda: clock["now"])
    box = Inbox(tmp_path, SETTINGS)
    engine = Engine(NoDocs(), box)

    def say(text, model, conv=CONV, record=True):
        monkeypatch.setattr(engine, "_llm_stream", model)
        return asyncio.run(engine.answer(SETTINGS, conv, text, record=record))

    return engine, box, clock, say


def events(box, kind, conv=CONV):
    return [m for m in box.conversation(conv)["messages"] if m.get("role") == "event" and m.get("kind") == kind]


# ---------------------------------------------------------------- the customer's own number

def test_customer_number_is_never_handed_back_as_the_company_number(bot):
    engine, box, clock, say = bot
    say("Tôi cần mua Data Logger Temperature", Model("Dạ anh cần đo nhiệt độ cho kho lạnh hay phòng thí nghiệm ạ?"))
    reply = say("Gọi lại sdt 0969103875", Model(
        "Dạ em xin lỗi, em là trợ lý ảo nên chưa gọi điện được ạ.\n\nĐể được hỗ trợ nhanh nhất, anh/chị vui lòng liên hệ "
        "trực tiếp với shop qua số **0969103875** hoặc để lại thông tin để em ghi nhận ạ."))
    assert reply == eng.phone_ack("0969103875")
    assert events(box, "lead")[-1]["data"]["sdt"] == "0969103875"
    assert box.conversation(CONV)["item"]["profile"]["sdt"] == "0969103875"
    blocked = events(box, "guard_blocked")
    assert blocked and "nhầm số" in blocked[-1]["data"]["ly_do"]


def test_confirming_the_customer_number_goes_through(bot):
    engine, box, clock, say = bot
    text = "Dạ em đã ghi nhận số 0969103875, nhân viên kinh doanh sẽ gọi lại anh trong hôm nay ạ."
    model = Model(text)
    assert say("Gọi lại sdt 0969103875", model) == text
    assert "số CỦA KHÁCH" in model.reminder()


@pytest.mark.parametrize("sentence, bad", [
    ("Anh/chị vui lòng liên hệ trực tiếp với shop qua số 0969103875 ạ.", True),
    ("Anh gọi vào số 0969 103 875 giúp em nhé.", True),
    ("Hotline bên em: 0969103875.", True),
    ("Dạ em đã ghi nhận số 0969103875 ạ.", False),
    ("Nhân viên sẽ gọi lại cho anh qua số 0969103875 sớm ạ.", False),
    ("Anh có thể gọi hotline 0902 920 577 ạ.", False),  # company number: fine
])
def test_misused_number_detection(sentence, bad):
    customer = {eng.phone_key("0969103875")}
    company = {eng.phone_key("0902 920 577")}
    assert bool(eng.misused_phones(sentence, customer, company)) is bad


# ---------------------------------------------------------------- returning customer, chasing, repeated questions

def returning_customer(say, box, clock):
    say("Tôi cần mua Data Logger Temperature", Model("Dạ anh cần loại dùng cho kho lạnh, vận chuyển hay phòng thí nghiệm ạ?"))
    say("Gọi lại sdt 0969103875", Model("Dạ em đã ghi nhận số 0969103875, nhân viên sẽ gọi lại anh sớm ạ."))
    clock["now"] += 600
    box.message(CONV, "assistant", "[Nhân viên trả lời trong Zalo] Bên e đã nhận được thông tin ạ")
    clock["now"] += DAY


def test_next_day_the_bot_knows_the_customer(bot):
    engine, box, clock, say = bot
    returning_customer(say, box, clock)
    model = Model("Dạ yêu cầu Data Logger của anh đã chuyển bộ phận kinh doanh, nhân viên sẽ gọi anh qua số 0969103875 ạ.")
    say("Có gì k ha ad", model)
    system, reminder = model.system(), model.reminder()
    assert BRIEF in system and "0969103875" in system and "Bên e đã nhận được thông tin" in system
    assert "hôm qua" in system
    assert "nhắn lại sau 1 ngày" in reminder
    assert "HỎI LẠI" in reminder and "không giới thiệu lại công ty" in reminder
    # the whole earlier talk is in the history the model reads
    sent = [m["content"] for m in model.seen[-1] if m["role"] in ("user", "assistant")]
    assert sent[0] == "Tôi cần mua Data Logger Temperature" and sent[-1] == "Có gì k ha ad"
    # staff are told again: the customer is waiting
    assert events(box, "handoff")[-1]["data"]["ly_do"].startswith("Khách nhắn hỏi lại")
    assert box.index()["items"][0]["status"] == "can_xu_ly"
    assert box.conversation(CONV)["item"]["profile"]["nhu_cau"] != "Có gì k ha ad"  # the need stays the real one


def test_a_vague_first_message_is_not_a_chase(bot):
    engine, box, clock, say = bot
    model = Model("Dạ bên em chuyên thiết bị phòng Lab ạ, anh cần tìm thiết bị nào ạ?")
    say("Có gì k ha ad", model)
    assert "HỎI LẠI" not in model.reminder() and BRIEF not in model.system()
    assert not events(box, "handoff")


def test_coming_back_to_chase_without_a_number_alerts_staff(bot):
    engine, box, clock, say = bot
    say("Báo giá cho mình nồi hấp tiệt trùng 50 lít", Model("Dạ anh cho em xin tên và số điện thoại ạ."))
    clock["now"] += 20 * 3600
    model = Model("Dạ em xin lỗi, anh cho em xin số điện thoại để nhân viên gọi báo giá ngay ạ.")
    say("sao chưa thấy ai báo giá vậy", model)
    assert "xin số điện thoại" in model.reminder()
    assert events(box, "handoff")[-1]["data"]["nhu_cau"] == "Báo giá cho mình nồi hấp tiệt trùng 50 lít"


def test_asking_what_we_sell_mid_chat_is_not_a_chase(bot):
    engine, box, clock, say = bot
    say("chào em", Model("Dạ em chào anh ạ."))
    clock["now"] += 60
    model = Model("Dạ bên em chuyên thiết bị phòng Lab ạ.")
    say("bên em có gì không", model)
    assert "HỎI LẠI" not in model.reminder() and not events(box, "handoff")


def test_questions_already_asked_are_listed(bot):
    engine, box, clock, say = bot
    say("Tôi cần mua Data Logger Temperature", Model("Dạ anh cần loại dùng cho kho lạnh hay phòng thí nghiệm ạ?"))
    model = Model("Dạ vâng ạ.")
    say("kho lạnh", model)
    assert "Dạ anh cần loại dùng cho kho lạnh hay phòng thí nghiệm ạ?" in model.reminder()
    assert "ĐÃ hỏi" in model.reminder()


def test_staff_lines_are_not_counted_as_bot_questions():
    msgs = [{"role": "assistant", "text": "[Nhân viên trả lời trong Zalo] Chị cho em xin số điện thoại nhé?"},
            {"role": "assistant", "text": "Dạ anh cần **đo** ở dải nhiệt độ nào ạ?"}]
    assert eng.asked_questions(msgs) == ["Dạ anh cần đo ở dải nhiệt độ nào ạ?"]


def test_old_questions_beyond_the_history_are_summarised(bot):
    engine, box, clock, say = bot
    say("Cho mình hỏi máy đo nhiệt độ tâm sản phẩm sau thanh trùng", Model("Dạ có ạ."))
    for i in range(eng.HISTORY // 2):
        say(f"câu hỏi phụ số {i}", Model("Dạ vâng ạ."))
    model = Model("Dạ vâng ạ.")
    say("còn gì nữa không", model)
    assert "Khách từng hỏi" in model.system() and "nhiệt độ tâm sản phẩm" in model.system()


# ---------------------------------------------------------------- what the customer reads

def test_tool_narration_never_reaches_the_customer(bot):
    engine, box, clock, say = bot
    reply = say("Tôi cần mua Data Logger Temperature", Model(
        "Dạ anh cần loại dùng cho kho lạnh hay phòng thí nghiệm ạ?\n\n*(Đang sử dụng công cụ tìm kiếm để tra cứu sản phẩm...)*"))
    assert "Đang sử dụng" not in reply and "*" not in reply
    assert reply.strip() == "Dạ anh cần loại dùng cho kho lạnh hay phòng thí nghiệm ạ?"


def test_zalo_text_has_no_markdown_or_narration():
    text = zalo.plain("Dạ để em tìm các mẫu **Data Logger Temperature** ạ.\n\n*(Đang sử dụng công cụ tìm kiếm...)*\n"
                      "- Một\n- Hai")
    assert text == "Dạ để em tìm các mẫu Data Logger Temperature ạ.\n\n• Một\n• Hai"


def test_zalo_records_what_was_actually_sent(bot):
    engine, box, clock, say = bot
    reply = say("xin chào", Model("Dạ em chào anh, anh cần **thiết bị** gì ạ?"), record=False)
    assert reply == "Dạ em chào anh, anh cần **thiết bị** gì ạ?"
    roles = [m["role"] for m in box.conversation(CONV)["messages"]]
    assert roles == ["user"]  # the router writes zalo.plain(reply) after sending


def test_shortened_reply_cannot_turn_the_customer_number_into_ours(bot, monkeypatch):
    engine, box, clock, say = bot
    say("Gọi lại sdt 0969103875", Model("Dạ em đã ghi nhận số 0969103875 ạ."))
    long = "Dạ em đã ghi nhận số 0969103875, nhân viên sẽ gọi lại anh sớm ạ. " * 10

    async def bad_short(s, text):
        return "Anh vui lòng gọi vào số 0969103875 ạ."

    monkeypatch.setattr(engine, "_shorten", bad_short)
    assert asyncio.run(engine.shorten(SETTINGS, long, CONV)) == long

    async def new_number(s, text):
        return "Dạ anh gọi hotline 0911 222 333 ạ."

    monkeypatch.setattr(engine, "_shorten", new_number)
    assert asyncio.run(engine.shorten(SETTINGS, long, CONV)) == long

    async def good(s, text):
        return "Dạ em đã ghi nhận số 0969103875, nhân viên sẽ gọi lại anh ạ."

    monkeypatch.setattr(engine, "_shorten", good)
    assert asyncio.run(engine.shorten(SETTINGS, long, CONV)) == "Dạ em đã ghi nhận số 0969103875, nhân viên sẽ gọi lại anh ạ."


def test_when_reads_like_a_person():
    now = 1794019338  # 07/11 09:42
    assert eng.when(now - 60, now) == "09:41 hôm nay"
    assert eng.when(now - DAY, now) == "09:42 hôm qua (06/11)"
    assert eng.when(now - 4 * DAY, now) == "09:42 03/11 (4 ngày trước)"
