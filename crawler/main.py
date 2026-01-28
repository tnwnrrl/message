"""
네이버 스마트플레이스 예약 크롤러 API
- 오늘 확정 예약 목록 조회
- 솔라피 알림톡 발송
"""

import os
import re
import hmac
import hashlib
import secrets
import httpx
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from typing import List, Optional

app = FastAPI(title="네이버 예약 크롤러")

# 환경변수
BIZ_ID = os.getenv("BIZ_ID", "1575275")
STORAGE_PATH = os.getenv("STORAGE_PATH", "/app/naver_session.json")

# 솔라피 설정
SOLAPI_API_KEY = os.getenv("SOLAPI_API_KEY", "")
SOLAPI_API_SECRET = os.getenv("SOLAPI_API_SECRET", "")
SOLAPI_SENDER = os.getenv("SOLAPI_SENDER", "")
SOLAPI_PF_ID = os.getenv("SOLAPI_PF_ID", "")
SOLAPI_TEMPLATE_ID = os.getenv("SOLAPI_TEMPLATE_ID", "")

# 오늘 확정 예약 페이지 URL
CONFIRMED_BOOKINGS_URL = f"https://partner.booking.naver.com/bizes/{BIZ_ID}/booking-list-view?countFilter=CONFIRMED"

# 브라우저 상태
browser: Browser = None
context: BrowserContext = None
page: Page = None
playwright_instance = None


class BookingItem(BaseModel):
    booking_id: str
    customer_name: str
    phone_number: str
    booking_time: str
    product_name: str


class TodayBookingsResponse(BaseModel):
    date: str
    count: int
    bookings: List[BookingItem]


class SendNotificationRequest(BaseModel):
    phone_number: str
    customer_name: str
    booking_time: str


class SendNotificationResponse(BaseModel):
    success: bool
    message: str
    detail: Optional[dict] = None


class SendAllNotificationsResponse(BaseModel):
    total: int
    success: int
    failed: int
    results: List[dict]


def generate_solapi_auth():
    """솔라피 HMAC-SHA256 인증 헤더 생성"""
    date = datetime.utcnow().isoformat() + "Z"
    salt = secrets.token_hex(32)

    signature = hmac.new(
        SOLAPI_API_SECRET.encode('utf-8'),
        (date + salt).encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return f"HMAC-SHA256 apiKey={SOLAPI_API_KEY}, date={date}, salt={salt}, signature={signature}"


async def send_alimtalk(phone_number: str, customer_name: str, booking_time: str) -> dict:
    """솔라피 알림톡 발송"""
    if not all([SOLAPI_API_KEY, SOLAPI_API_SECRET, SOLAPI_SENDER, SOLAPI_PF_ID, SOLAPI_TEMPLATE_ID]):
        return {"success": False, "message": "솔라피 설정이 완료되지 않았습니다."}

    auth_header = generate_solapi_auth()

    payload = {
        "message": {
            "to": phone_number,
            "from": SOLAPI_SENDER,
            "kakaoOptions": {
                "pfId": SOLAPI_PF_ID,
                "templateId": SOLAPI_TEMPLATE_ID,
                "variables": {
                    "#{예약자명}": customer_name,
                    "#{예약일시}": booking_time
                }
            }
        }
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.solapi.com/messages/v4/send",
                json=payload,
                headers={
                    "Authorization": auth_header,
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )

            result = response.json()

            if response.status_code == 200:
                return {"success": True, "message": "발송 성공", "detail": result}
            else:
                return {"success": False, "message": f"발송 실패: {response.status_code}", "detail": result}

        except Exception as e:
            return {"success": False, "message": f"발송 오류: {str(e)}"}


async def init_browser():
    """저장된 세션으로 브라우저 초기화"""
    global browser, context, page, playwright_instance

    if not Path(STORAGE_PATH).exists():
        raise Exception(f"세션 파일이 없습니다: {STORAGE_PATH}")

    playwright_instance = await async_playwright().start()
    browser = await playwright_instance.chromium.launch(headless=True)

    # 저장된 세션으로 컨텍스트 생성
    context = await browser.new_context(storage_state=STORAGE_PATH)
    page = await context.new_page()

    # 로그인 확인
    await page.goto(CONFIRMED_BOOKINGS_URL)
    await page.wait_for_timeout(3000)

    content = await page.content()
    if "로그인" in content and "예약자관리" not in content:
        raise Exception("세션이 만료되었습니다. 세션을 다시 저장해주세요.")

    print("브라우저 초기화 완료 (세션 로드됨)")


async def get_today_bookings() -> dict:
    """오늘 확정 예약 목록 조회"""
    global page

    if page is None:
        await init_browser()

    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    # 오늘 확정 예약 페이지로 이동
    await page.goto(CONFIRMED_BOOKINGS_URL)
    await page.wait_for_timeout(3000)

    # 페이지 로딩 대기
    try:
        await page.wait_for_selector('table', timeout=10000)
    except:
        pass

    # 페이지 텍스트 가져오기
    page_text = await page.inner_text('body')

    # 디버깅용 로그
    print(f"페이지 텍스트 길이: {len(page_text)}")

    # 예약 목록 파싱
    bookings = []

    # 실제 페이지 텍스트 형식:
    # 확정 전진환 010-2446-5967 1143205010 오후 11:15 백석담 ...
    pattern = r'확정\s+(\S+)\s+(01[0-9]-\d{4}-\d{4})\s+(\d{10})\s+(오[전후]\s+\d{1,2}:\d{2})\s+(\S+)'

    matches = re.findall(pattern, page_text)

    print(f"매칭된 예약: {len(matches)}건")

    for match in matches:
        name, phone, booking_id, time_part, product = match

        bookings.append({
            "booking_id": booking_id,
            "customer_name": name,
            "phone_number": phone.replace("-", ""),
            "booking_time": time_part,
            "product_name": product
        })

    # 중복 제거 (예약번호 기준)
    seen = set()
    unique_bookings = []
    for b in bookings:
        if b["booking_id"] not in seen:
            seen.add(b["booking_id"])
            unique_bookings.append(b)

    return {
        "date": today_str,
        "count": len(unique_bookings),
        "bookings": unique_bookings
    }


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 브라우저 초기화"""
    try:
        await init_browser()
    except Exception as e:
        print(f"브라우저 초기화 실패: {e}")
        print("세션 파일을 확인하세요.")


@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료 시 브라우저 정리"""
    global browser, context, playwright_instance

    if context:
        await context.close()
    if browser:
        await browser.close()
    if playwright_instance:
        await playwright_instance.stop()


@app.get("/")
async def root():
    return {"status": "running", "service": "네이버 예약 크롤러"}


@app.get("/health")
async def health():
    global page
    if page is None:
        return {"status": "not_initialized"}
    return {"status": "ok"}


@app.get("/bookings/today", response_model=TodayBookingsResponse)
async def get_bookings_today():
    """오늘 확정 예약 목록 조회"""
    try:
        result = await get_today_bookings()
        return TodayBookingsResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/send-notification", response_model=SendNotificationResponse)
async def send_notification(request: SendNotificationRequest):
    """단일 알림톡 발송"""
    result = await send_alimtalk(
        phone_number=request.phone_number,
        customer_name=request.customer_name,
        booking_time=request.booking_time
    )
    return SendNotificationResponse(**result)


@app.post("/send-all-notifications", response_model=SendAllNotificationsResponse)
async def send_all_notifications():
    """오늘 확정 예약 전체에 알림톡 발송"""
    # 오늘 예약 조회
    bookings_data = await get_today_bookings()
    bookings = bookings_data["bookings"]

    results = []
    success_count = 0
    failed_count = 0

    for booking in bookings:
        # 오늘 날짜 + 시간으로 예약일시 포맷
        today = datetime.now()
        booking_datetime = f"{today.month}월 {today.day}일 {booking['booking_time']}"

        result = await send_alimtalk(
            phone_number=booking["phone_number"],
            customer_name=booking["customer_name"],
            booking_time=booking_datetime
        )

        results.append({
            "booking_id": booking["booking_id"],
            "customer_name": booking["customer_name"],
            "phone_number": booking["phone_number"],
            **result
        })

        if result["success"]:
            success_count += 1
        else:
            failed_count += 1

    return SendAllNotificationsResponse(
        total=len(bookings),
        success=success_count,
        failed=failed_count,
        results=results
    )


@app.get("/test-payload")
async def test_payload():
    """발송 데이터 미리보기 (실제 발송 안함)"""
    bookings_data = await get_today_bookings()
    bookings = bookings_data["bookings"]

    payloads = []
    for booking in bookings:
        today = datetime.now()
        booking_datetime = f"{today.month}월 {today.day}일 {booking['booking_time']}"

        payload = {
            "message": {
                "to": booking["phone_number"],
                "from": SOLAPI_SENDER,
                "kakaoOptions": {
                    "pfId": SOLAPI_PF_ID,
                    "templateId": SOLAPI_TEMPLATE_ID,
                    "variables": {
                        "#{예약자명}": booking["customer_name"],
                        "#{예약일시}": booking_datetime
                    }
                }
            }
        }
        payloads.append({
            "booking": booking,
            "solapi_payload": payload
        })

    return {
        "count": len(payloads),
        "payloads": payloads
    }


@app.post("/refresh")
async def refresh_browser():
    """브라우저 새로고침 및 재초기화"""
    global page, context, browser

    try:
        if context:
            await context.close()
        if browser:
            await browser.close()

        await init_browser()
        return {"status": "refreshed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
