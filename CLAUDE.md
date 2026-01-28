# 예약 알림톡 자동화 시스템

네이버 예약 메일에서 예약 정보를 추출하여 카카오 알림톡을 자동 발송하는 시스템

## 시스템 구성

```
[네이버 예약] → [Gmail] → [n8n] → [카카오 알림톡] → [예약자]
```

## 기술 스택

| 구성요소 | 서비스 | 역할 |
|---------|--------|------|
| 메일 수신 | Gmail | 네이버 예약 알림 메일 수신 |
| 자동화 엔진 | n8n (Synology) | 워크플로우 실행 |
| 알림 발송 | 카카오 비즈메시지 | 알림톡 API |

## 워크플로우

1. **Gmail Trigger**: 새 메일 감지 (발신자: `noreply@naver.com`)
2. **Filter**: 예약 관련 메일만 필터링
3. **Extract**: 예약자명, 예약일시, 연락처 추출
4. **Send**: 카카오 알림톡 발송

## 디렉토리 구조

```
message/
├── CLAUDE.md          # 프로젝트 문서
├── plan.md            # 상세 설계
├── n8n/
│   └── reservation-notification.json  # n8n 워크플로우
└── docs/
    ├── kakao-setup.md     # 카카오 비즈메시지 설정 가이드
    └── n8n-workflow.md    # n8n 워크플로우 설명
```

## 필수 설정

### 1. Gmail API
- Google Cloud Console에서 OAuth 2.0 설정
- n8n에 Gmail 자격증명 등록

### 2. 카카오 비즈메시지
- 카카오 비즈니스 채널 생성
- 알림톡 템플릿 등록 (검수 필요)
- API 키 발급

### 3. n8n
- Gmail 노드 설정
- HTTP Request 노드로 카카오 API 호출

## 참고 링크

- [카카오 비즈니스](https://business.kakao.com/)
- [카카오 알림톡 API 문서](https://developers.kakao.com/docs/latest/ko/message/rest-api)
- [n8n 문서](https://docs.n8n.io/)
