# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 시스템 개요

네이버 스마트플레이스 예약을 크롤링하여 카카오 알림톡을 자동 발송하는 시스템

```
[n8n 스케줄 01:00] → [크롤러 API] → [네이버 스마트플레이스 크롤링] → [솔라피 알림톡 발송]
```

## 아키텍처

### 크롤러 (crawler/)
- **FastAPI** 서버 + **Playwright** 브라우저 자동화
- 네이버 로그인 세션을 `naver_session.json`에 저장하여 재사용
- Synology NAS Docker에서 실행 (포트 8080)

### n8n 워크플로우 (n8n/)
- 매일 01:00 스케줄 트리거
- 크롤러 API `/send-all-notifications` 호출

### 알림톡 발송
- **솔라피(Solapi)** API 사용 (HMAC-SHA256 인증)
- 카카오 비즈메시지 채널 연동

## 주요 API 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /bookings/today` | 오늘 확정 예약 조회 |
| `POST /send-all-notifications` | 오늘 예약 전체에 알림톡 발송 |
| `GET /test-payload` | 발송 데이터 미리보기 |
| `GET /logs/latest` | 최근 크롤링 결과 |
| `GET /logs` | 크롤링 로그 목록 |
| `POST /refresh` | 브라우저 세션 재초기화 |

## 배포 명령어

```bash
# Synology SSH 접속
ssh -p 55 tnwnrrl@tnwnrrl.synology.me

# 크롤러 재배포
cd "/volume1/Synology Driver/일산 신규 프로젝트/장치/message/crawler"
sudo docker-compose down && sudo docker-compose up -d --build

# 로그 확인
sudo docker logs naver-booking-crawler --tail 50
```

## 로컬 테스트

```bash
# 오늘 예약 조회
curl http://192.168.219.187:8080/bookings/today

# 발송 데이터 확인
curl http://192.168.219.187:8080/test-payload

# 알림톡 발송 (실제 발송)
curl -X POST http://192.168.219.187:8080/send-all-notifications
```

## 환경변수 (docker-compose.yml)

- `BIZ_ID`: 네이버 스마트플레이스 업체 ID
- `SOLAPI_API_KEY`, `SOLAPI_API_SECRET`: 솔라피 인증
- `SOLAPI_SENDER`: 발신번호
- `SOLAPI_PF_ID`: 카카오 채널 ID
- `SOLAPI_TEMPLATE_ID`: 알림톡 템플릿 ID

## 세션 관리

네이버 로그인 세션이 만료되면 `naver_session.json`을 갱신해야 함:
1. `save_session.py` 실행 또는 Playwright MCP로 로그인
2. `storage_state` 저장
3. Docker 컨테이너 재시작

## 크롤링 패턴

네이버 스마트플레이스 예약 목록 페이지에서 정규식으로 파싱:
```
확정 {이름} {전화번호} {예약번호} {시간} {상품명}
```

URL: `https://partner.booking.naver.com/bizes/{BIZ_ID}/booking-list-view?countFilter=CONFIRMED`
