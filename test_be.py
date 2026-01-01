import os
from pathlib import Path
from typing import Optional, Tuple

from fastapi.testclient import TestClient

from be import app


client = TestClient(app)
IMG_DIR = Path(__file__).parent / "image"


def _pick_image(prefer: Optional[str] = None) -> Path:
    if prefer:
        p = IMG_DIR / prefer
        if p.exists():
            return p
    for ext in (".jpg", ".jpeg", ".png"):
        for p in IMG_DIR.glob(f"*{ext}"):
            return p
    raise FileNotFoundError("Không tìm thấy ảnh mẫu trong thư mục image/")


def _post_analyze(
    img_path: Path, prompt: Optional[str], language: Optional[str] = None
) -> Tuple[int, dict]:
    """Post analyze request with optional language parameter.

    Args:
        img_path: Path to image file.
        prompt: User prompt/request.
        language: Language code ('en' or 'vi').

    Returns:
        Tuple of (status_code, response_body).
    """
    with open(img_path, "rb") as f:
        files = {"file": (img_path.name, f, "image/jpeg")}
        data = {"prompt": prompt or ""}
        if language:
            data["language"] = language
        r = client.post("/analyze", files=files, data=data)
    status = r.status_code
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    return status, body


def run_case(
    name: str,
    prompt: Optional[str],
    prefer_image: Optional[str] = None,
    language: Optional[str] = None,
):
    """Run a test case.

    Args:
        name: Test case name.
        prompt: User prompt/request.
        prefer_image: Preferred image filename.
        language: Language code ('en' or 'vi').
    """
    img = _pick_image(prefer_image)
    code, js = _post_analyze(img, prompt, language)
    print(f"\n== {name} ==")
    print("prompt:", prompt)
    print("language:", language or "vi (default)")
    print("file:", img.name)
    print("status:", code)
    print("response:", js)


def run_all():
    # describe
    # run_case("describe", "mô tả cảnh vật trong ảnh này")
    run_case("describe_en", "mô tả cảnh vật trong ảnh này", language="en")
    run_case("describe_vi", "mô tả cảnh vật trong ảnh này", language="vi")

    # count - no target
    # run_case("count_all", "đếm tất cả đối tượng trong ảnh")
    # run_case("count_all_en", "đếm tất cả đối tượng trong ảnh", language="en")
    # run_case("count_all_vi", "đếm tất cả đối tượng trong ảnh", language="vi")

    # count - human target (phổ biến)
    # run_case("count_target_people", "đếm bao nhiêu người trong ảnh")
    # run_case("count_target_people_en", "đếm bao nhiêu người trong ảnh", language="en")
    # run_case("count_target_people_vi", "đếm bao nhiêu người trong ảnh", language="vi")

    # find - need clarification
    # run_case("find_need_clarification", "tìm")
    # run_case("find_need_clarification_en", "tìm", language="en")
    # run_case("find_need_clarification_vi", "tìm", language="vi")

    # find - with target
    # run_case("find_target_phone", "tìm cái điện thoại trong ảnh")
    # run_case("find_target_phone_en", "tìm cái điện thoại trong ảnh", language="en")
    # run_case("find_target_phone_vi", "tìm cái điện thoại trong ảnh", language="vi")

    # ocr (ưu tiên ảnh có chữ)
    run_case("ocr", "ocr văn bản trong ảnh này", prefer_image="ocr.png")
    run_case(
        "ocr_en", "ocr văn bản trong ảnh này", prefer_image="ocr.png", language="en"
    )
    run_case(
        "ocr_vi", "ocr văn bản trong ảnh này", prefer_image="ocr.png", language="vi"
    )

    # history
    # Gửi vài yêu cầu find để tạo lịch sử
    # run_case("seed_find_glasses", "tìm cái kính trong ảnh")
    # run_case("seed_find_phone", "có điện thoại ở phía trước không?")
    # Truy vấn lịch sử: "tôi đã tìm cái kính vào ngày nào"
    # run_case("history_query_glasses", "tôi đã tìm cái kính vào ngày nào")
    # run_case("history_query_glasses_en", "tôi đã tìm cái kính vào ngày nào", language="en")
    # run_case("history_query_glasses_vi", "tôi đã tìm cái kính vào ngày nào", language="vi")


if __name__ == "__main__":
    # Khi chạy trực tiếp: in kết quả, không cần pytest
    run_all()
    print("\nDONE")
