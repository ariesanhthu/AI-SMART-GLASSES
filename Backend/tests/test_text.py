from app import text


def test_normalize_removes_vietnamese_accents_and_punctuation():
    assert text.normalize("  Điện thoại ở đâu? ") == "dien thoai o dau"


def test_keyword_intents_work_without_groq(monkeypatch):
    monkeypatch.setattr(text.groq_service, "classify_intent", lambda _prompt: None)

    assert text.classify_intent("mô tả cảnh vật")[0] == "describe"
    assert text.classify_intent("đếm điện thoại")[0:2] == ("count", "dien thoai")
    assert text.classify_intent("đọc chữ trong ảnh")[0] == "ocr"
    assert text.classify_intent("có điện thoại ở phía trước không?")[0:2] == (
        "find",
        "dien thoai",
    )


def test_unknown_prompt_defaults_to_description(monkeypatch):
    monkeypatch.setattr(text.groq_service, "classify_intent", lambda _prompt: None)
    assert text.classify_intent("xin chào") == ("describe", None, True)

