# be.py
import os, time, socket, json
from dotenv import load_dotenv
import requests
from typing import Optional, Tuple, Dict
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import re
import easyocr
from deep_translator import GoogleTranslator
from groq import Groq
from side_function import (
    get_obj_json,
    get_cap_json,
    generate_image_description,
    MyFaiss,
)
from datetime import datetime

load_dotenv()  # load biến môi trường từ .env nếu có
app = FastAPI()

# CORS "thoáng" cho mọi origin (kể cả 'null' khi mở file tĩnh)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=False,  # dùng False để kết hợp với '*'
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.get("/")
def root():
    return {"ok": True}


@app.get("/ping")
def ping():
    return {"ok": True, "msg": "pong"}


# Preflight thủ công (nếu trình duyệt gửi OPTIONS trước POST)
@app.options("/analyze")
@app.options("/analyze/")
def options_analyze():
    return JSONResponse(status_code=204, content=None)


# ===== OCR helpers (EasyOCR + Groq DeepSeek) =====
def _extract_text_with_easyocr(filename: str) -> str:
    reader = easyocr.Reader(["vi", "en"])  # CPU OK; lần đầu hơi chậm do load model
    result = reader.readtext(filename)
    text_in_frame = ""
    for image_result in result:
        if isinstance(image_result, (tuple, list)) and len(image_result) == 3:
            _, text, _ = image_result
            text_in_frame += " " + text
    return text_in_frame.strip()


def _translate_to_vi(text: str) -> str:
    if not text:
        return ""
    translator = GoogleTranslator(source="auto", target="vi")
    return translator.translate(text)


def _build_deepseek_prompt_vi(text_vi: str) -> str:
    return (
        "Nhiệm vụ: Hiệu chỉnh văn bản tiếng Việt nhận từ OCR cho chính xác và tự nhiên.\n"
        "Yêu cầu: Sửa lỗi nhận diện, bổ sung ký tự/từ còn thiếu dựa vào ngữ cảnh, giữ nguyên ý, không bịa thêm.\n"
        "Định dạng: Chỉ xuất RA KẾT QUẢ CUỐI CÙNG, không giải thích.\n"
        "Ràng buộc: chỉ được thực hiện nhiệm vụ không nói thêm bất kỳ thứ gì khác.\n\n"
        f"Văn bản (VI): {text_vi}"
    )


def _init_groq() -> Groq:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Thiếu GROQ_API_KEY trong biến môi trường")
    return Groq(api_key=api_key)


def _strip_deepseek_reasoning(output_text: str) -> str:
    if not output_text:
        return ""
    # Xóa các khối suy luận phổ biến
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", output_text, flags=re.IGNORECASE)
    cleaned = re.sub(r"```\s*reasoning[\s\S]*?```", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"^(?:\s*(?:Reasoning|Suy luận)\s*:\s*)+",
        "",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return cleaned.strip()


def _refine_text_with_groq_vi(text_vi: str) -> str:
    client = _init_groq()
    prompt = _build_deepseek_prompt_vi(text_vi)
    completion = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "deepseek-r1-distill-llama-70b"),
        temperature=0.2,
        top_p=0.9,
        max_tokens=512,
        messages=[
            {
                "role": "system",
                "content": "Bạn là bộ hiệu chỉnh văn bản OCR tiếng Việt. Chỉ trả về kết quả cuối.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    raw = (
        completion.choices[0].message.content
        if completion and completion.choices
        else ""
    )
    return _strip_deepseek_reasoning(raw)


def _prettify_vi_sentence(text: str) -> str:
    try:
        s = (text or "").strip()
        if not s:
            return s
        # Viết hoa ký tự đầu nếu là chữ cái
        first = s[0].upper()
        s = first + s[1:]
        # Thêm dấu chấm cuối nếu chưa có ký tự câu
        if s[-1] not in ".!?…":
            s = s + "."
        # Chuẩn hoá khoảng trắng
        s = re.sub(r"\s+", " ", s)
        return s.strip()
    except Exception:
        return text


def _prettify_target_vi(term: Optional[str]) -> str:
    t = (term or "").strip()
    if not t:
        return t
    try:
        # Dịch/chuẩn hoá về tiếng Việt có dấu nếu đầu vào là không dấu/EN
        return GoogleTranslator(source="auto", target="vi").translate(t).strip()
    except Exception:
        return t


def _summarize_scene_with_groq_vi(caption_vi: str, counts: Dict[str, int]) -> str:
    """
    Dùng Groq để hợp nhất caption (VI) + thống kê đối tượng thành 1 mô tả mượt, trung thực.
    Ràng buộc: chỉ dùng thông tin được cung cấp; không bịa.
    """
    try:
        client = _init_groq()
        system_msg = (
            "Bạn là trợ lý biên tập tiếng Việt. "
            "Nhiệm vụ: gộp mô tả cảnh vật với thống kê đếm đối tượng thành 1 đoạn ngắn, tự nhiên, trung thực. "
            "Chỉ sử dụng đúng thông tin đã cho, không thêm thắt. "
            "Ràng buộc: chỉ được thực hiện nhiệm vụ không nói thêm bất kỳ thứ gì khác."
        )
        # Đưa counts ở dạng danh sách để hạn chế bịa
        counts_lines = (
            "\n".join(f"- {k}: {v}" for k, v in sorted(counts.items()))
            if counts
            else "(không có dữ liệu)"
        )
        user_msg = (
            "Dưới đây là dữ liệu bạn được phép dùng:\n"
            f"[MÔ TẢ]: {caption_vi or ''}\n"
            f"[THỐNG KÊ]:\n{counts_lines}\n\n"
            "Hãy viết 1-2 câu mô tả cảnh vật tự nhiên, có nhắc số lượng nếu phù hợp. "
            "Chỉ trả về kết quả, không giải thích."
        )

        completion = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            temperature=0.2,
            top_p=0.9,
            max_tokens=180,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        content = (
            completion.choices[0].message.content.strip()
            if completion and completion.choices
            else ""
        )
        return _strip_deepseek_reasoning(content) or caption_vi
    except Exception:
        return caption_vi


def _extract_find_target_with_groq(
    prompt_raw: str,
) -> Tuple[Optional[str], Optional[int]]:
    """
    Dùng Groq để trích xuất mục tiêu tìm kiếm dạng: "<NUM>|<ITEM>"
    - NUM: một số (ví dụ 1)
    - ITEM: tên món đồ (tiếng Việt không dấu hoặc có dấu đều được)
    Chỉ trả về đúng định dạng, không kèm giải thích.
    """
    try:
        client = _init_groq()
        system_msg = (
            "Bạn là bộ trích xuất truy vấn tìm đồ vật. "
            "Chỉ trả về duy nhất một dòng ở định dạng '<SỐ>|<TÊN MÓN ĐỒ>'. "
            "Ràng buộc: chỉ được thực hiện nhiệm vụ không nói thêm bất kỳ thứ gì khác."
        )
        user_msg = (
            "Hãy phân tích câu sau và trả về '<SỐ>|<TÊN MÓN ĐỒ>'\n" f"Câu: {prompt_raw}"
        )
        completion = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            temperature=0,
            max_tokens=16,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        content = (
            completion.choices[0].message.content.strip()
            if completion and completion.choices
            else ""
        )
        # Kỳ vọng: "1|điện thoại" hoặc "1|dien thoai"
        m = re.match(r"^\s*(\d+)\s*\|\s*(.+?)\s*$", content)
        if m:
            num = int(m.group(1))
            item = m.group(2).strip()
            return item or None, num
    except Exception:
        pass
    return None, None


def OCR(filename: str) -> str:
    try:
        raw_text = _extract_text_with_easyocr(filename)
        if not raw_text:
            return "Đầu vào không thoả mãn. Vui lòng thử lại với ảnh có văn bản."
        text_vi = _translate_to_vi(raw_text)
        refined = _refine_text_with_groq_vi(text_vi)
        return refined or text_vi or raw_text
    except Exception as e:
        return f"Lỗi khi xử lý văn bản: {e}"


@app.post("/analyze")
async def analyze(file: UploadFile = File(...), prompt: Optional[str] = Form(None)):
    name = f"photo_{int(time.time())}.jpg"
    path = os.path.join(UPLOAD_FOLDER, name)
    with open(path, "wb") as f:
        while True:
            chunk = await file.read(1_048_576)
            if not chunk:
                break
            f.write(chunk)

    intent, target, is_unknown = _classify_intent(prompt or "")
    # Lưu lịch sử yêu cầu người dùng
    try:
        _ = saveReq(prompt or "")
    except Exception:
        pass

    try:
        if intent == "describe":
            # Caption + object → mô tả tự nhiên; sau đó Groq biên tập lại
            try:
                get_cap_json(path)
            except Exception:
                pass
            try:
                get_obj_json(path)
            except Exception:
                pass
            base_text = generate_image_description()
            counts = _read_object_counts()
            smooth_text = _summarize_scene_with_groq_vi(base_text, counts)
            if is_unknown:
                prefix = (
                    "tôi không hiểu yêu cầu tôi sẽ mặc định giúp bạn mô tả cảnh vật. "
                )
                smooth_text = (prefix + (smooth_text or "")).strip()
            return {
                "status": "success",
                "intent": intent,
                "file": name,
                "text": _prettify_vi_sentence(smooth_text or ""),
            }

        if intent == "count":
            # Đếm số lượng đối tượng; nếu không có target → trả bản tóm tắt đếm tất cả
            get_obj_json(path)
            counts = _read_object_counts()
            if target:
                pretty_t = _prettify_target_vi(target)
                c = _count_target(counts, pretty_t)
                msg = (
                    f"Có khoảng {c} {pretty_t}." if c > 0 else f"Không thấy {pretty_t}."
                )
                return {
                    "status": "success",
                    "intent": intent,
                    "file": name,
                    "text": _prettify_vi_sentence(msg),
                    "data": {"target": pretty_t, "count": c, "counts": counts},
                }
            # không có target: tổng hợp lại với caption để trả câu mượt hơn
            try:
                get_cap_json(path)
            except Exception:
                pass
            base_text = generate_image_description()
            summary = _summarize_scene_with_groq_vi(base_text, counts)
            return {
                "status": "success",
                "intent": intent,
                "file": name,
                "text": _prettify_vi_sentence(summary),
                "data": {"counts": counts},
            }

        if intent == "find":
            if not target:
                return {
                    "status": "clarify",
                    "intent": intent,
                    "file": name,
                    "text": "bạn muốn tìm gì",
                    "need_clarification": True,
                }
            # Dùng CLIP để ước lượng có/không
            clip_model = MyFaiss()
            pretty_t = _prettify_target_vi(target)
            score = clip_model.image_warning(pretty_t, path)
            decision = "Có thể có" if score >= 0.22 else "Khó thấy"
            text = f"{decision} '{pretty_t}' (độ tin cậy {score:.2f})."
            return {
                "status": "success",
                "intent": intent,
                "file": name,
                "text": _prettify_vi_sentence(text),
                "data": {"target": pretty_t, "similarity": score},
            }

        if intent == "ocr":
            text = OCR(path)
            return {
                "status": "success",
                "intent": "ocr",
                "file": name,
                "text": _prettify_vi_sentence(text or ""),
            }

        if intent == "history":
            answer = retrieveData(prompt or "")
            return {
                "status": "success",
                "intent": "history",
                "file": name,
                "text": _prettify_vi_sentence(answer or ""),
            }

        # Fallback: mô tả
        try:
            get_cap_json(path)
        except Exception:
            pass
        try:
            get_obj_json(path)
        except Exception:
            pass
        text = generate_image_description()
        if is_unknown:
            prefix = "tôi không hiểu yêu cầu tôi sẽ mặc định giúp bạn mô tả cảnh vật. "
            text = (prefix + (text or "")).strip()
        return {
            "status": "success",
            "intent": "describe",
            "file": name,
            "text": _prettify_vi_sentence(text or ""),
        }

    except Exception as e:
        return {
            "status": "error",
            "intent": intent,
            "file": name,
            "text": f"Lỗi xử lý: {str(e)}",
        }


@app.post("/analyze/")
async def analyze_slash(
    file: UploadFile = File(...), prompt: Optional[str] = Form(None)
):
    return await analyze(file, prompt)


# In routes để bạn đối chiếu khi start
def _print_routes():
    print("== Routes loaded ==")
    for r in app.router.routes:
        methods = ",".join(sorted(r.methods or []))
        print(f"{methods:10s} {getattr(r, 'path', '')}")


_print_routes()


# ===== Helpers =====
def _normalize_vn(s: str) -> str:
    try:
        import unicodedata, re

        s2 = unicodedata.normalize("NFD", s.lower())
        s2 = "".join(ch for ch in s2 if unicodedata.category(ch) != "Mn")
        s2 = re.sub(r"[^a-z0-9\s]", " ", s2)
        s2 = re.sub(r"\s+", " ", s2).strip()
        return s2
    except Exception:
        return s.lower()


def _classify_intent(prompt: str) -> Tuple[str, Optional[str], bool]:
    """
    Dùng Groq để phân loại intent theo mã 0-4.
    Mapping:
      0 -> unknown (mặc định describe, trả lời câu mở đầu theo yêu cầu)
      1 -> describe
      2 -> count
      3 -> find
      4 -> ocr
      5 -> history (truy vấn lịch sử)

    Trả về: (intent, target, is_unknown)
    """
    p = _normalize_vn(prompt)
    if not p:
        return "describe", None, True

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    def _keyword_fallback() -> Tuple[str, Optional[str], bool]:
        if any(k in p for k in ["dem", "bao nhieu", "how many", "count"]):
            target2 = _extract_target(p, ["dem", "bao nhieu", "how many", "count"])
            return "count", target2, False
        # nhận diện find: từ khóa hoặc mẫu "co ... khong"
        if any(k in p for k in ["tim", "o dau", "where", "find"]) or (
            p.startswith("co ") and (" khong" in p or " ko" in p)
        ):
            target2 = _extract_target(
                p, ["tim", "o dau", "where", "find"]
            ) or _extract_find_target(p)
            return "find", target2, False
        if any(
            k in p
            for k in [
                "lich su",
                "history",
                "da khi nao",
                "vao ngay nao",
                "trong qua khu",
            ]
        ):
            return "history", None, False
        if any(k in p for k in ["mo ta", "co gi", "describe", "caption", "nhan dang"]):
            return "describe", None, False
        return "describe", None, True

    if not api_key:
        return _keyword_fallback()

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        system_msg = (
            "Bạn là bộ phân loại lệnh. Chỉ trả lời đúng 1 chữ số từ 0 đến 4, "
            "không kèm ký tự nào khác.\n"
            "Nhãn: 0=không xác định, 1=miêu tả cảnh vật, 2=đếm số lượng, 3=tìm vật/vị trí, 4=trích xuất văn bản, 5=truy vấn lịch sử."
        )
        user_msg = (
            f"Hãy phân loại câu lệnh sau theo các nhãn 0-5.\n"
            f"Câu lệnh: {prompt}\n"
            f"Chỉ trả lời 1 ký tự số duy nhất trong [0,1,2,3,4,5]."
        )
        body = {
            "model": model,
            "temperature": 0,
            "max_tokens": 4,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        }
        resp = requests.post(url, headers=headers, json=body, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        content = (
            ((data or {}).get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        digit = "".join(ch for ch in content if ch.isdigit())[:1]
        mapping = {
            "0": "unknown",
            "1": "describe",
            "2": "count",
            "3": "find",
            "4": "ocr",
            "5": "history",
        }
        label = mapping.get(digit or "", "unknown")

        is_unknown = label == "unknown"
        if label == "count":
            target = _extract_target(p, ["dem", "bao nhieu", "how many", "count"])
            return "count", target, is_unknown
        if label == "find":
            # cố gắng bóc tách X trong các câu như "co X o phia truoc khong", "tim X", ...
            target = _extract_target(
                p, ["tim", "o dau", "where", "find"]
            ) or _extract_find_target(p)
            if not target:
                # thử Groq để lấy "<num>|<item>"
                item, _ = _extract_find_target_with_groq(prompt)
                target = item or target
            return "find", target, is_unknown
        if label == "history":
            return "history", None, is_unknown
        if label == "ocr":
            return "ocr", None, is_unknown
        if label == "describe":
            return "describe", None, is_unknown
        return "describe", None, True
    except Exception:
        return _keyword_fallback()


def _extract_target(p: str, markers) -> Optional[str]:
    # rất đơn giản: lấy cụm sau từ khóa đầu tiên
    for m in markers:
        if m in p:
            after = p.split(m, 1)[1].strip()
            if after:
                return after
    return None


def _extract_find_target(p: str) -> Optional[str]:
    """
    Bóc tách X trong câu dạng tiếng Việt không dấu như:
      - "co X o phia truoc khong"
      - "co X phia truoc ko"
      - "co thay X khong"
    Trả về X (chuỗi có thể gồm nhiều từ) hoặc None.
    """
    try:
        # mẫu "co ... khong/ko"
        if p.startswith("co ") and (" khong" in p or " ko" in p):
            core = p[3:]
            core = core.split(" khong")[0].split(" ko")[0].strip()
            # bỏ cụm "o phia truoc", "phia truoc"
            core = (
                core.replace(" o phia truoc", " ").replace(" phia truoc", " ").strip()
            )
            # bỏ "thay"
            if core.startswith("thay "):
                core = core[5:].strip()
            return core or None
        # mẫu "tim X"
        if p.startswith("tim "):
            return p[4:].strip() or None
    except Exception:
        pass
    return None


def _read_object_counts() -> Dict[str, int]:
    try:
        with open(os.path.join("json", "object.json"), "r", encoding="utf-8") as f:
            obj = json.load(f)
        counts: Dict[str, int] = {}
        if isinstance(obj, list):
            for it in obj:
                label = str(it.get("label", "")).strip()
                if not label:
                    continue
                key = _normalize_vn(label)
                counts[key] = counts.get(key, 0) + 1
        return counts
    except Exception:
        return {}


def _count_target(counts: Dict[str, int], target: str) -> int:
    if not target:
        return 0
    t = _normalize_vn(target)
    # match chính xác hoặc chứa nhau
    for k, v in counts.items():
        if k == t or t in k or k in t:
            return v
    return 0


def _format_counts_summary(counts: Dict[str, int]) -> str:
    if not counts:
        return "Không nhận diện được đối tượng."
    items = sorted(counts.items(), key=lambda x: -x[1])
    parts = [f"{c} {k}" for k, c in items]
    if len(parts) == 1:
        return f"Có {parts[0]}."
    return "Có " + ", ".join(parts[:-1]) + f" và {parts[-1]}."


# ===== History: save & retrieve =====
def saveReq(st: str) -> bool:
    """
    Save vào file data.json
    {
      datetime: ISO8601,
      content: <original string>
    }
    """
    try:
        entry = {
            "datetime": datetime.now().isoformat(timespec="seconds"),
            "content": st or "",
        }
        path = os.path.join("json", "data.json")
        os.makedirs("json", exist_ok=True)
        data = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f) or []
                    if not isinstance(data, list):
                        data = []
            except Exception:
                data = []
        data.append(entry)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def retrieveData(req: str) -> str:
    """
    req: yêu cầu của người dùng
    return: kết quả tổng hợp từ file json/data.json theo truy vấn
    Ví dụ: "tôi đã tìm cái kính vào ngày nào" → trả danh sách ngày có log chứa từ khóa "kính" (hoặc target bóc tách)
    """
    try:
        path = os.path.join("json", "data.json")
        if not os.path.exists(path):
            return _prettify_vi_sentence("Chưa có lịch sử.")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or []
        if not isinstance(data, list) or not data:
            return _prettify_vi_sentence("Chưa có lịch sử.")

        p = _normalize_vn(req)
        # Cố gắng bóc tách keyword mục tiêu bằng các hàm sẵn có
        target = _extract_find_target(p) or _extract_target(p, ["tim"]) or None
        if not target:
            # thử Groq tách từ dạng "num|item"
            item, _ = _extract_find_target_with_groq(req)
            target = item or None

        target_norm = _normalize_vn(target) if target else None

        matched_dates: Dict[str, int] = {}
        for entry in data:
            content = str(entry.get("content", ""))
            dt = str(entry.get("datetime", ""))
            c_norm = _normalize_vn(content)
            if target_norm:
                if target_norm in c_norm:
                    date_only = dt.split("T")[0] if "T" in dt else dt[:10]
                    matched_dates[date_only] = matched_dates.get(date_only, 0) + 1
            else:
                # nếu không có từ khóa, trả về những ngày có log
                date_only = dt.split("T")[0] if "T" in dt else dt[:10]
                matched_dates[date_only] = matched_dates.get(date_only, 0) + 1

        if not matched_dates:
            return _prettify_vi_sentence("Không tìm thấy lịch sử phù hợp.")

        # Format kết quả
        dates_sorted = sorted(matched_dates.items())
        if target_norm:
            pretty_target = _prettify_target_vi(target)
            parts = [f"{d} (\u00d7{c})" for d, c in dates_sorted]
            msg = f"Bạn đã nhắc về '{pretty_target}' vào: " + ", ".join(parts) + "."
        else:
            parts = [f"{d} (\u00d7{c})" for d, c in dates_sorted]
            msg = "Các ngày có hoạt động: " + ", ".join(parts) + "."
        return _prettify_vi_sentence(msg)
    except Exception as e:
        return _prettify_vi_sentence(f"Lỗi truy vấn lịch sử: {e}")


if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5000
    ip = socket.gethostbyname(socket.gethostname())
    print(f"* FastAPI: http://{ip}:{port}  (open /docs)")
    uvicorn.run("be:app", host=host, port=port, reload=True)
