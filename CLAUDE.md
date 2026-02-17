# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 시스템 개요

네이버 스마트플레이스 예약을 크롤링하여 카카오 알림톡을 자동 발송하는 시스템

```
[n8n 스케줄 01:00] → [크롤러 API] → [네이버 스마트플레이스 크롤링]
  ├→ [솔라피 알림톡 즉시 발송] (기존 템플릿 - 오늘 전체 예약자 안내)
  └→ [솔라피 알림톡 예약발송] (리마인더 템플릿 - 각 플레이타임 1분 전)
```

## 아키텍처

### 크롤러 (crawler/)
- **FastAPI** 서버 (`main.py`) + **Playwright** 브라우저 자동화
- 네이버 로그인 세션을 `naver_session.json`에 저장하여 재사용
- Synology NAS Docker에서 실행 (외부 8080 → 내부 8000)

### 핵심 흐름 (crawler/main.py)
1. **크롤링**: Playwright로 네이버 예약 페이지 접속 → 정규식으로 예약 데이터 파싱
2. **즉시 발송**: `send_alimtalk()` → `SOLAPI_TEMPLATE_ID` 템플릿으로 즉시 발송
3. **리마인더 예약발송**: `schedule_reminder_alimtalk()` → `SOLAPI_REMINDER_TEMPLATE_ID` 템플릿으로 솔라피 `scheduledDate` 파라미터를 사용해 플레이타임 1분 전 발송 예약
4. **시간 변환**: `parse_booking_time_to_datetime()` → "오후 3:15" 형식을 datetime으로 변환

### n8n 워크플로우 (n8n/)
- 매일 01:00 스케줄 트리거
- 크롤러 API `POST /send-all-notifications` 호출 (내부망 `http://192.168.219.187:8080`)

### 알림톡 발송
- **솔라피(Solapi)** API 사용 (HMAC-SHA256 인증)
- 카카오 비즈메시지 채널 연동
- 이미 지난 시간의 예약은 리마인더 자동 스킵

## 주요 API 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /bookings/today` | 오늘 확정 예약 조회 |
| `POST /send-all-notifications` | 즉시 발송 + 리마인더 예약발송 일괄 처리 |
| `GET /test-payload` | 즉시 발송 + 리마인더 페이로드 미리보기 |
| `GET /logs/latest` | 최근 크롤링 결과 |
| `GET /logs` | 크롤링 로그 목록 |
| `POST /refresh` | 브라우저 세션 재초기화 |

## 배포 명령어

> **필수 참고**: 배포 시 반드시 `ssh.md` 파일을 참조할 것. SSH 접속 정보, 비밀번호, expect를 통한 자동 배포 방법이 포함되어 있음.

### Claude Code에서 자동 배포 (expect 사용)
```bash
# docker-compose 경로: /volume2/@appstore/Docker/usr/bin/docker-compose
# sudo 실행 시 반드시 PATH에 Docker 경로 포함 필요

expect -c '
set timeout 300
spawn sshpass -p "비밀번호" ssh -p 55 -tt tnwnrrl@192.168.219.187 "sudo env PATH=/volume2/@appstore/Docker/usr/bin:/usr/local/bin:/usr/bin:\$PATH /volume2/@appstore/Docker/usr/bin/docker-compose -f \"/volume1/Synology Driver/일산 신규 프로젝트/장치/message/crawler/docker-compose.yml\" up -d --build 2>&1"
expect {
    "Password:" { send "비밀번호\r"; exp_continue }
    timeout { puts "TIMEOUT"; exit 1 }
    eof
}
'
```

### 수동 배포
```bash
# Synology SSH 접속
ssh -p 55 tnwnrrl@192.168.219.187

# 크롤러 재배포
cd "/volume1/Synology Driver/일산 신규 프로젝트/장치/message/crawler"
sudo docker-compose down && sudo docker-compose up -d --build

# 로그 확인
sudo docker logs naver-booking-crawler --tail 50
```

### 배포 주의사항
- Synology NAS의 `docker-compose` 경로: `/volume2/@appstore/Docker/usr/bin/docker-compose`
- `sudo` 환경에서 `docker` 명령어를 못 찾으므로 반드시 `env PATH=...` 로 경로 지정
- `echo | sudo -S` 파이프 방식은 Synology에서 동작하지 않음 → `expect` 사용 필수
- 비밀번호는 `ssh.md` 참조

## 로컬 테스트

```bash
# 오늘 예약 조회
curl http://192.168.219.187:8080/bookings/today

# 발송 데이터 확인 (리마인더 포함)
curl http://192.168.219.187:8080/test-payload

# 알림톡 발송 (실제 발송)
curl -X POST http://192.168.219.187:8080/send-all-notifications
```

## 환경변수 (docker-compose.yml)

- `BIZ_ID`: 네이버 스마트플레이스 업체 ID
- `SOLAPI_API_KEY`, `SOLAPI_API_SECRET`: 솔라피 인증
- `SOLAPI_SENDER`: 발신번호
- `SOLAPI_PF_ID`: 카카오 채널 ID
- `SOLAPI_TEMPLATE_ID`: 알림톡 템플릿 ID (즉시 발송용)
- `SOLAPI_REMINDER_TEMPLATE_ID`: 리마인더 알림톡 템플릿 ID (플레이타임 1분 전 예약발송)

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
정규식: `r'확정\s+(\S+)\s+(01[0-9]-\d{4}-\d{4})\s+(\d{10})\s+(오[전후]\s+\d{1,2}:\d{2})\s+(\S+)'`

URL: `https://partner.booking.naver.com/bizes/{BIZ_ID}/booking-list-view?countFilter=CONFIRMED`
