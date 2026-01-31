# 네이버 예약 크롤러 + 카카오 알림톡 자동 발송

네이버 스마트플레이스 예약을 자동 크롤링하여 카카오 알림톡을 발송하는 시스템

## 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    Synology NAS (Docker)                     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         naver-booking-crawler (port 8080→8000)      │    │
│  │                                                     │    │
│  │  FastAPI + Playwright (headless Chromium)            │    │
│  │  naver_session.json (네이버 로그인 세션)               │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
         ↑                    ↓                    ↓
    n8n 스케줄           네이버 크롤링          솔라피 API
   (매일 01:00)      (스마트플레이스)      (알림톡 발송)
```

## 서비스 목적

**미스터리담** 방탈출 카페의 네이버 예약을 자동 크롤링하여 카카오 알림톡을 발송하는 시스템

## 핵심 흐름

### 1. 매일 자동 발송 (n8n → 크롤러)

```
[n8n] 매일 01:00
  └→ POST /send-all-notifications
       ├→ Playwright로 네이버 예약 페이지 접속
       │    URL: partner.booking.naver.com/bizes/{BIZ_ID}/booking-list-view
       │    저장된 세션(naver_session.json)으로 인증
       │
       ├→ 정규식으로 예약 데이터 파싱
       │    패턴: "확정 {이름} {전화번호} {예약번호} {시간} {상품명}"
       │    예: "확정 남주현 010-2244-6479 1141606057 오후 3:15 백석담"
       │
       ├→ 예약자별 즉시 알림톡 발송 (안내 템플릿)
       │    솔라피 /messages/v4/send API
       │    내용: 대기장소(백석역), 유의사항, 시간 안내
       │
       └→ 예약자별 리마인더 예약발송 (플레이타임 1분 전)
            솔라피 그룹 예약발송 API (3단계)
            ① POST /messages/v4/groups → 그룹 생성
            ② PUT  /messages/v4/groups/{id}/messages → 메시지 추가
            ③ POST /messages/v4/groups/{id}/schedule → 예약 등록
            내용: 신입사원 테스트 안내 + 테스트 시작 버튼
```

### 2. 알림톡 2종

| 구분 | 발송 시점 | 내용 |
|------|----------|------|
| **안내 알림톡** | 즉시 (01:00) | 백석역 대기장소, 15분 전 도착 안내, 지각 시 취소 안내 |
| **리마인더 알림톡** | 플레이타임 1분 전 | 신입사원 테스트 안내 + "테스트 시작" 버튼 (mysterydam.com 링크) |

### 3. 인증 방식

```
네이버: Playwright 브라우저 세션 (naver_session.json)
        → 만료 시 save_session.py로 재생성

솔라피: HMAC-SHA256
        → 매 요청마다 date + salt + signature 생성
        → 카카오 비즈메시지 채널 연동
```

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/health` | 서버 상태 확인 |
| `GET` | `/bookings/today` | 오늘 확정 예약 크롤링 |
| `POST` | `/send-all-notifications` | 전체 알림톡 + 리마인더 일괄 처리 |
| `POST` | `/send-notification` | 단일 알림톡 즉시 발송 |
| `POST` | `/reminders/register` | 단일 리마인더 예약발송 등록 |
| `GET` | `/test-payload` | 발송 페이로드 미리보기 |
| `GET` | `/logs/latest` | 최근 크롤링 결과 |
| `GET` | `/logs` | 크롤링 로그 목록 |
| `POST` | `/refresh` | 브라우저 세션 재초기화 |

## 프로젝트 구조

```
message/
├── crawler/
│   ├── main.py              # FastAPI 서버 (핵심 로직 전체)
│   ├── docker-compose.yml   # Docker 설정 + 환경변수
│   ├── Dockerfile           # Playwright Python 이미지 기반
│   ├── requirements.txt     # 의존성
│   ├── save_session.py      # 네이버 세션 저장 스크립트
│   ├── naver_session.json   # 네이버 로그인 세션 (ro 마운트)
│   └── logs/                # 크롤링 로그 (볼륨 마운트)
├── n8n/
│   └── reservation-notification.json  # n8n 워크플로우
├── docs/
│   ├── kakao-setup.md
│   └── n8n-workflow.md
├── CLAUDE.md
└── README.md
```

## 배포

```bash
# Synology SSH 접속
ssh -p 55 tnwnrrl@116.47.42.83

# 크롤러 재배포
cd "/volume1/Synology Driver/일산 신규 프로젝트/장치/message/crawler"
sudo docker-compose down && sudo docker-compose up -d --build

# 로그 확인
sudo docker logs naver-booking-crawler --tail 50
```

## 로컬 테스트

```bash
# 오늘 예약 조회
curl http://116.47.42.83:8080/bookings/today

# 발송 데이터 확인
curl http://116.47.42.83:8080/test-payload

# 알림톡 발송 (실제 발송)
curl -X POST http://116.47.42.83:8080/send-all-notifications

# 리마인더 단일 등록
curl -X POST http://116.47.42.83:8080/reminders/register \
  -H "Content-Type: application/json" \
  -d '{"phone_number":"01012345678","customer_name":"홍길동","booking_time":"오후 3:15"}'
```

## 환경변수 (docker-compose.yml)

| 변수 | 설명 |
|------|------|
| `BIZ_ID` | 네이버 스마트플레이스 업체 ID |
| `SOLAPI_API_KEY` | 솔라피 API 키 |
| `SOLAPI_API_SECRET` | 솔라피 API 시크릿 |
| `SOLAPI_SENDER` | 발신번호 |
| `SOLAPI_PF_ID` | 카카오 채널 ID |
| `SOLAPI_TEMPLATE_ID` | 안내 알림톡 템플릿 ID |
| `SOLAPI_REMINDER_TEMPLATE_ID` | 리마인더 알림톡 템플릿 ID |

## 세션 관리

네이버 로그인 세션이 만료되면 `naver_session.json`을 갱신해야 함:
1. `save_session.py` 실행 또는 Playwright MCP로 로그인
2. `storage_state` 저장
3. Docker 컨테이너 재시작
