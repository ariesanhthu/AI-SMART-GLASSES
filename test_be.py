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


def _post_analyze(img_path: Path, prompt: Optional[str]) -> Tuple[int, dict]:
    with open(img_path, "rb") as f:
        files = {"file": (img_path.name, f, "image/jpeg")}
        data = {"prompt": prompt or ""}
        r = client.post("/analyze", files=files, data=data)
    status = r.status_code
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    return status, body


def run_case(name: str, prompt: Optional[str], prefer_image: Optional[str] = None):
    img = _pick_image(prefer_image)
    code, js = _post_analyze(img, prompt)
    print(f"\n== {name} ==")
    print("prompt:", prompt)
    print("file:", img.name)
    print("status:", code)
    print("response:", js)


def run_all():
    # describe
    run_case("describe", "mô tả cảnh vật trong ảnh này")

    # count - no target
    run_case("count_all", "đếm tất cả đối tượng trong ảnh")

    # count - human target (phổ biến)
    run_case("count_target_people", "đếm bao nhiêu người trong ảnh")

    # find - need clarification
    run_case("find_need_clarification", "tìm")

    # find - with target
    run_case("find_target_phone", "tìm cái điện thoại trong ảnh")

    # ocr (ưu tiên ảnh có chữ)
    run_case("ocr", "ocr văn bản trong ảnh này", prefer_image="ocr.png")

    # history
    # Gửi vài yêu cầu find để tạo lịch sử
    run_case("seed_find_glasses", "tìm cái kính trong ảnh")
    run_case("seed_find_phone", "có điện thoại ở phía trước không?")
    # Truy vấn lịch sử: "tôi đã tìm cái kính vào ngày nào"
    run_case("history_query_glasses", "tôi đã tìm cái kính vào ngày nào")


if __name__ == "__main__":
    # Khi chạy trực tiếp: in kết quả, không cần pytest
    run_all()
    print("\nDONE")
