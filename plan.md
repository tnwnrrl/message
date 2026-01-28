# 예약 알림톡 자동화 - 구현 계획

## Phase 1: 카카오 비즈메시지 설정

### 1.1 비즈니스 채널 생성
1. [카카오 비즈니스](https://business.kakao.com/) 접속
2. 비즈니스 채널 생성
3. 사업자 정보 등록 (개인/사업자)

### 1.2 알림톡 발신 프로필 등록
1. 카카오톡 채널 관리자센터 접속
2. 발신프로필 등록 신청
3. 검수 대기 (1-3일)

### 1.3 알림톡 템플릿 등록
```
[예약 확인 안내]

안녕하세요, #{예약자명}님

예약이 확인되었습니다.

■ 예약 일시: #{예약일시}
■ 예약 내용: #{예약내용}

문의사항은 연락 부탁드립니다.
감사합니다.
```

### 1.4 API 키 발급
- REST API 키
- Admin 키 (알림톡 발송용)

---

## Phase 2: Gmail API 설정

### 2.1 Google Cloud Console 설정
1. 프로젝트 생성
2. Gmail API 활성화
3. OAuth 2.0 자격증명 생성
4. 리다이렉트 URI 설정 (n8n 콜백 URL)

### 2.2 필요한 스코프
```
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/gmail.modify
```

---

## Phase 3: n8n 워크플로우 구현

### 3.1 노드 구성

```
[Gmail Trigger] → [IF: 네이버예약?] → [Code: 파싱] → [HTTP: 카카오API] → [Respond]
                         ↓ No
                    [Stop]
```

### 3.2 Gmail Trigger 설정
- **Polling Interval**: 1분
- **Filter**: `from:noreply@naver.com subject:예약`

### 3.3 메일 파싱 로직 (JavaScript)
```javascript
// 네이버 예약 메일 파싱 예시
const mailBody = $input.first().json.text;

// 정규식으로 정보 추출
const nameMatch = mailBody.match(/예약자\s*[:\s]+(.+)/);
const dateMatch = mailBody.match(/예약일시\s*[:\s]+(.+)/);
const phoneMatch = mailBody.match(/연락처\s*[:\s]+([\d-]+)/);

return {
  reservationName: nameMatch ? nameMatch[1].trim() : '',
  reservationDate: dateMatch ? dateMatch[1].trim() : '',
  phoneNumber: phoneMatch ? phoneMatch[1].replace(/-/g, '') : ''
};
```

### 3.4 카카오 알림톡 API 호출
```
POST https://kapi.kakao.com/v1/api/talk/friends/message/send

Headers:
  Authorization: Bearer {ACCESS_TOKEN}
  Content-Type: application/x-www-form-urlencoded

Body:
  template_id: {TEMPLATE_ID}
  template_args: {"예약자명": "...", "예약일시": "..."}
```

---

## Phase 4: 테스트 및 배포

### 4.1 테스트 시나리오
1. 테스트 예약 메일 발송
2. n8n 트리거 확인
3. 파싱 결과 검증
4. 알림톡 수신 확인

### 4.2 에러 처리
- 메일 파싱 실패 시 관리자 알림
- API 호출 실패 시 재시도 (3회)
- 로그 기록

---

## 필요한 정보 체크리스트

- [ ] 카카오 비즈니스 채널 ID
- [ ] 카카오 REST API 키
- [ ] 알림톡 템플릿 코드
- [ ] Gmail OAuth 자격증명
- [ ] n8n 접속 URL (시놀로지)
- [ ] 네이버 예약 메일 샘플 (파싱 패턴 확인용)

---

## 예상 소요 작업

1. 카카오 비즈니스 설정: 검수 대기 포함 3-5일
2. Gmail API 설정: 1시간
3. n8n 워크플로우: 2-3시간
4. 테스트/디버깅: 1-2시간
