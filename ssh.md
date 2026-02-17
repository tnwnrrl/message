# NAS 배포 명령어

## 접속
```bash
ssh -p 55 tnwnrrl@192.168.219.187
# 비밀번호: Aksksla12!
```

## 크롤러 재배포
```bash
cd "/volume1/Synology Driver/일산 신규 프로젝트/장치/message/crawler"
sudo docker-compose down && sudo docker-compose up -d --build
```

## 수정 내용 (2026-02-02)
- `parse_booking_time_to_datetime()`: `datetime.now()` → `datetime.now(ZoneInfo("Asia/Seoul"))` KST 명시
- UTC 변환: 수동 `-9시간` → `.astimezone(ZoneInfo("UTC"))` 안전한 변환
- 원인: Docker 컨테이너 TZ=UTC → 리마인더 예약시간이 과거로 계산되어 즉시 발송됨
