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
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from typing import List, Optional
app = FastAPI(title="네이버 예약 크롤러")

# 환경변수
BIZ_ID = os.getenv("BIZ_ID", "1575275")
STORAGE_PATH = os.getenv("STORAGE_PATH", "/app/naver_session.json")
LOG_PATH = os.getenv("LOG_PATH", "/app/logs")

# 솔라피 설정
SOLAPI_API_KEY = os.getenv("SOLAPI_API_KEY", "")
SOLAPI_API_SECRET = os.getenv("SOLAPI_API_SECRET", "")
SOLAPI_SENDER = os.getenv("SOLAPI_SENDER", "")
SOLAPI_PF_ID = os.getenv("SOLAPI_PF_ID", "")
SOLAPI_TEMPLATE_ID = os.getenv("SOLAPI_TEMPLATE_ID", "")
SOLAPI_REMINDER_TEMPLATE_ID = os.getenv("SOLAPI_REMINDER_TEMPLATE_ID", "")

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


class CrawlLogItem(BaseModel):
    timestamp: str
    date: str
    count: int
    bookings: List[dict]
    send_results: Optional[List[dict]] = None


def save_crawl_log(data: dict, send_results: Optional[List[dict]] = None):
    """크롤링 결과를 로그 파일로 저장"""
    log_dir = Path(LOG_PATH)
    log_dir.mkdir(parents=True, exist_ok=True)

    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)

    timestamp = now.strftime("%Y%m%d_%H%M%S")
    date_str = now.strftime("%Y-%m-%d")

    log_entry = {
        "timestamp": now.isoformat(),
        "date": date_str,
        "count": data.get("count", 0),
        "bookings": data.get("bookings", []),
        "send_results": send_results
    }

    # 개별 로그 파일 저장
    log_file = log_dir / f"crawl_{timestamp}.json"
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, ensure_ascii=False, indent=2)

    # 최근 로그 파일도 업데이트 (최근 결과 빠른 확인용)
    latest_file = log_dir / "latest.json"
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, ensure_ascii=False, indent=2)

    print(f"크롤링 결과 저장: {log_file}")
    return str(log_file)


def get_crawl_logs(limit: int = 10) -> List[dict]:
    """저장된 크롤링 로그 목록 조회"""
    log_dir = Path(LOG_PATH)
    if not log_dir.exists():
        return []

    log_files = sorted(log_dir.glob("crawl_*.json"), reverse=True)[:limit]
    logs = []

    for log_file in log_files:
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)
                log_data["filename"] = log_file.name
                logs.append(log_data)
        except Exception as e:
            print(f"로그 파일 읽기 실패: {log_file} - {e}")

    return logs


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


def parse_booking_time_to_datetime(booking_time: str) -> datetime:
    """'오후 3:15' 형식을 오늘 날짜 datetime(KST)으로 변환"""
    # UTC + 9시간 = KST (Docker 컨테이너가 UTC일 수 있으므로)
    from datetime import timezone
    KST = timezone(timedelta(hours=9))
    today = datetime.now(KST)
    match = re.match(r'(오전|오후)\s+(\d{1,2}):(\d{2})', booking_time)
    if not match:
        raise ValueError(f"시간 파싱 실패: {booking_time}")

    period, hour, minute = match.group(1), int(match.group(2)), int(match.group(3))

    if period == "오후" and hour != 12:
        hour += 12
    elif period == "오전" and hour == 12:
        hour = 0

    return today.replace(hour=hour, minute=minute, second=0, microsecond=0)


async def schedule_reminder_alimtalk(phone_number: str, customer_name: str, booking_time: str) -> dict:
    """플레이타임 1분 전 리마인더 알림톡 - 솔라피 그룹 예약발송"""
    if not SOLAPI_REMINDER_TEMPLATE_ID:
        return {"success": False, "message": "리마인더 템플릿 ID가 설정되지 않았습니다."}

    try:
        play_dt = parse_booking_time_to_datetime(booking_time)
    except ValueError as e:
        return {"success": False, "message": str(e)}

    scheduled_dt = play_dt - timedelta(minutes=1)
    # KST → UTC 변환 (timezone-aware)
    from datetime import timezone
    now_kst = datetime.now(timezone(timedelta(hours=9)))
    scheduled_utc = scheduled_dt.astimezone(timezone.utc)
    scheduled_iso = scheduled_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 예약 시간이 현재보다 과거이거나 2분 이내면 스킵 (솔라피가 즉시 발송하는 것 방지)
    remaining = (scheduled_dt - now_kst).total_seconds()
    print(f"[리마인더 시간 검증] now={now_kst.strftime('%H:%M:%S')} scheduled={scheduled_dt.strftime('%H:%M:%S')} remaining={remaining:.0f}s scheduledDate={scheduled_iso}")
    if remaining < 120:
        return {"success": False, "message": f"리마인더 시간이 이미 지났거나 너무 가까움 (남은시간: {remaining:.0f}초, scheduled: {scheduled_dt.strftime('%H:%M:%S')})"}

    headers = {
        "Authorization": generate_solapi_auth(),
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # 1) 그룹 생성
            r1 = await client.post("https://api.solapi.com/messages/v4/groups", headers=headers, json={})
            if r1.status_code != 200:
                return {"success": False, "message": f"그룹 생성 실패: {r1.status_code}", "detail": r1.json()}
            group_id = r1.json()["groupId"]

            # 2) 메시지 추가 (PUT)
            headers["Authorization"] = generate_solapi_auth()
            msg_payload = {
                "messages": [
                    {
                        "to": phone_number,
                        "from": SOLAPI_SENDER,
                        "text": """[신입 사원 최종 테스트 안내]
귀하의 '다해조' 입사를 환영합니다.

마지막 검증을 위해 귀하를 백석역으로 소환합니다.
이곳에서 당신의 위기 대처 능력과 정보 수집 능력을 증명하십시오.

🗝 테스트 시작 : 아래 테스트시작 버튼 클릭하여 시작 하세요.

*회사 1층 로비 비밀번호 1379* 후 세로로 긴 버튼 눌러서 입장""",
                        "kakaoOptions": {
                            "pfId": SOLAPI_PF_ID,
                            "templateId": SOLAPI_REMINDER_TEMPLATE_ID,
                            "buttons": [
                                {
                                    "buttonType": "WL",
                                    "buttonName": "테스트 시작",
                                    "linkMo": "http://mysterydam.com/play/test.php"
                                }
                            ]
                        }
                    }
                ]
            }
            r2 = await client.put(f"https://api.solapi.com/messages/v4/groups/{group_id}/messages", headers=headers, json=msg_payload)
            if r2.status_code != 200:
                return {"success": False, "message": f"메시지 추가 실패: {r2.status_code}", "detail": r2.json()}

            # 3) 예약발송 등록
            headers["Authorization"] = generate_solapi_auth()
            r3 = await client.post(f"https://api.solapi.com/messages/v4/groups/{group_id}/schedule", headers=headers, json={"scheduledDate": scheduled_iso})
            if r3.status_code != 200:
                return {"success": False, "message": f"예약발송 실패: {r3.status_code}", "detail": r3.json()}

            print(f"[리마인더 예약발송] {phone_number} {booking_time} → {scheduled_dt.strftime('%H:%M:%S')} (groupId: {group_id})")
            return {"success": True, "message": f"리마인더 예약발송 완료 ({scheduled_dt.strftime('%H:%M:%S')})", "group_id": group_id}

        except Exception as e:
            return {"success": False, "message": f"리마인더 오류: {str(e)}"}


async def send_alimtalk(phone_number: str, customer_name: str, booking_time: str) -> dict:
    """솔라피 알림톡 발송"""
    if not all([SOLAPI_API_KEY, SOLAPI_API_SECRET, SOLAPI_SENDER, SOLAPI_PF_ID, SOLAPI_TEMPLATE_ID]):
        return {"success": False, "message": "솔라피 설정이 완료되지 않았습니다."}

    auth_header = generate_solapi_auth()

    payload = {
        "message": {
            "to": phone_number,
            "from": SOLAPI_SENDER,
            "text": """안녕하세요, #{예약자명}님!
미스터리담의 첫번째 이야기 '백석담'을 예약해 주셔서 감사합니다.

 원활한 이용을 위해서 반드시 아래의 대기 장소 사진과 안내 사항을 확인해 주시기 바랍니다.
• 일시: #{예약일시}
• 대기 장소: 3호선 백석역 역사 내부 중앙
• 해당 장소에서 대기하시면 진행 방법이 알림톡으로 도착합니다.

⚠ 유의사항 (필독)
1. 원활한 진행을 위해 시작 15분 전까지 사진 속 장소에 도착해 주세요.
2. 정해진 시간에 도착하지 않으실 경우, 게임의 일부 연출이 생략된 채로 진행될 수 있습니다.
3. 시작 시간 기준 20분 이상 지각 시, 예약은 환불 없이 자동 취소되오니 시간을 엄수해 주시기 바랍니다.""",
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

    from datetime import timezone
    KST = timezone(timedelta(hours=9))
    today = datetime.now(KST)
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
        # 크롤링 결과 저장
        save_crawl_log(result)
        return TodayBookingsResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/logs")
async def get_logs(limit: int = 10):
    """크롤링 로그 목록 조회"""
    logs = get_crawl_logs(limit)
    return {"count": len(logs), "logs": logs}


@app.get("/logs/latest")
async def get_latest_log():
    """최근 크롤링 결과 조회"""
    latest_file = Path(LOG_PATH) / "latest.json"
    if not latest_file.exists():
        raise HTTPException(status_code=404, detail="로그가 없습니다.")

    with open(latest_file, "r", encoding="utf-8") as f:
        return json.load(f)


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
        # 오늘 날짜 + 시간으로 예약일시 포맷 (KST 기준)
        from datetime import timezone
        KST = timezone(timedelta(hours=9))
        today = datetime.now(KST)
        booking_datetime = f"{today.month}월 {today.day}일 {booking['booking_time']}"

        # 1) 즉시 발송 (기존 템플릿)
        result = await send_alimtalk(
            phone_number=booking["phone_number"],
            customer_name=booking["customer_name"],
            booking_time=booking_datetime
        )

        # 2) 플레이타임 1분 전 리마인더 예약발송 (새 템플릿)
        reminder_result = await schedule_reminder_alimtalk(
            phone_number=booking["phone_number"],
            customer_name=booking["customer_name"],
            booking_time=booking["booking_time"]
        )

        results.append({
            "booking_id": booking["booking_id"],
            "customer_name": booking["customer_name"],
            "phone_number": booking["phone_number"],
            **result,
            "reminder": reminder_result
        })

        if result["success"]:
            success_count += 1
        else:
            failed_count += 1

    # 발송 결과 포함하여 로그 저장
    save_crawl_log(bookings_data, send_results=results)

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
        from datetime import timezone
        KST = timezone(timedelta(hours=9))
        today = datetime.now(KST)
        booking_datetime = f"{today.month}월 {today.day}일 {booking['booking_time']}"

        payload = {
            "message": {
                "to": booking["phone_number"],
                "from": SOLAPI_SENDER,
                "text": """안녕하세요, #{예약자명}님!
미스터리담의 첫번째 이야기 '백석담'을 예약해 주셔서 감사합니다.

 원활한 이용을 위해서 반드시 아래의 대기 장소 사진과 안내 사항을 확인해 주시기 바랍니다.
• 일시: #{예약일시}
• 대기 장소: 3호선 백석역 역사 내부 중앙
• 해당 장소에서 대기하시면 진행 방법이 알림톡으로 도착합니다.

⚠ 유의사항 (필독)
1. 원활한 진행을 위해 시작 15분 전까지 사진 속 장소에 도착해 주세요.
2. 정해진 시간에 도착하지 않으실 경우, 게임의 일부 연출이 생략된 채로 진행될 수 있습니다.
3. 시작 시간 기준 20분 이상 지각 시, 예약은 환불 없이 자동 취소되오니 시간을 엄수해 주시기 바랍니다.""",
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
        # 리마인더 예약발송 페이로드
        try:
            play_dt = parse_booking_time_to_datetime(booking["booking_time"])
            scheduled_dt = play_dt - timedelta(minutes=1)
            # KST → UTC 변환 (timezone-aware)
            from datetime import timezone
            scheduled_utc = scheduled_dt.astimezone(timezone.utc)
            scheduled_date = scheduled_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            reminder_payload = {
                "message": {
                    "to": booking["phone_number"],
                    "from": SOLAPI_SENDER,
                    "text": """[신입 사원 최종 테스트 안내]
귀하의 '다해조' 입사를 환영합니다.

마지막 검증을 위해 귀하를 백석역으로 소환합니다.
이곳에서 당신의 위기 대처 능력과 정보 수집 능력을 증명하십시오.

🗝 테스트 시작 : 아래 테스트시작 버튼 클릭하여 시작 하세요.

*회사 1층 로비 비밀번호 1379* 후 세로로 긴 버튼 눌러서 입장""",
                    "kakaoOptions": {
                        "pfId": SOLAPI_PF_ID,
                        "templateId": SOLAPI_REMINDER_TEMPLATE_ID,
                        "buttons": [
                            {
                                "buttonType": "WL",
                                "buttonName": "테스트 시작",
                                "linkMo": "http://mysterydam.com/play/test.php"
                            }
                        ]
                    }
                },
                "scheduledDate": scheduled_date
            }
        except ValueError:
            reminder_payload = None

        payloads.append({
            "booking": booking,
            "solapi_payload": payload,
            "reminder_payload": reminder_payload
        })

    return {
        "count": len(payloads),
        "payloads": payloads
    }


@app.post("/reminders/register")
async def register_reminder(request: SendNotificationRequest):
    """단일 리마인더 예약발송 등록"""
    result = await schedule_reminder_alimtalk(
        phone_number=request.phone_number,
        customer_name=request.customer_name,
        booking_time=request.booking_time
    )
    return result


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
