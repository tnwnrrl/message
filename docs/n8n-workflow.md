# n8n 워크플로우 설정 가이드

## 워크플로우 개요

```
[Gmail Trigger] → [예약 필터] → [메일 파싱] → [검증] → [알림톡 발송]
                      ↓ No           ↓ 실패
                   [종료]        [에러 로그]
```

---

## 1. 사전 준비

### 1.1 n8n 접속
시놀로지 n8n 접속: `http://YOUR_SYNOLOGY_IP:5678`

### 1.2 필요한 자격증명
1. **Gmail OAuth2**: Google Cloud Console에서 생성
2. **Kakao Admin Key**: 카카오 개발자 콘솔에서 확인

---

## 2. 워크플로우 가져오기

### 2.1 Import 방법
1. n8n 대시보드 → Workflows
2. "Import from File" 클릭
3. `n8n/reservation-notification.json` 선택
4. Import 완료

### 2.2 Import 후 설정
1. Gmail Trigger 노드 → 자격증명 연결
2. 카카오 알림톡 노드 → 자격증명 연결
3. 환경변수 설정 (Settings → Variables)

---

## 3. 노드별 설정

### 3.1 Gmail Trigger

**설정 항목**:
- Poll Time: Every Minute (1분마다 확인)
- Filters:
  - Sender: `noreply@naver.com`
  - Subject contains: `예약`
- Options:
  - Mark as Read: Yes (처리된 메일 표시)

**자격증명 설정**:
1. n8n → Credentials → Create New
2. Type: Gmail OAuth2
3. Google Cloud Console에서:
   - OAuth 2.0 Client ID 생성
   - Redirect URI: `http://YOUR_N8N_URL/rest/oauth2-credential/callback`
4. Client ID, Client Secret 입력
5. "Sign in with Google" 클릭하여 인증

### 3.2 메일 파싱 (Code 노드)

메일 본문에서 정보 추출하는 JavaScript 코드:

```javascript
// 네이버 예약 메일 파싱
const mailBody = $input.first().json.text || '';

// 패턴 매칭
const patterns = {
  name: /예약자\s*[:\s]*([가-힣a-zA-Z]+)/,
  date: /예약\s*일시\s*[:\s]*([\d]{4}[-./][\d]{1,2}[-./][\d]{1,2})/,
  time: /예약\s*시간\s*[:\s]*([\d]{1,2}:[\d]{2})/,
  phone: /연락처\s*[:\s]*([\d-]+)/
};

// 추출 결과
return {
  reservationName: mailBody.match(patterns.name)?.[1] || '',
  reservationDate: mailBody.match(patterns.date)?.[1] || '',
  reservationTime: mailBody.match(patterns.time)?.[1] || '',
  phoneNumber: (mailBody.match(patterns.phone)?.[1] || '').replace(/-/g, '')
};
```

**주의**: 네이버 예약 메일 형식에 따라 정규식 패턴 조정 필요!

### 3.3 카카오 알림톡 발송 (HTTP Request)

**HTTP Request 설정**:
- Method: POST
- URL: `https://kapi.kakao.com/v1/api/talk/friends/message/send`
- Authentication: Header Auth
  - Header Name: `Authorization`
  - Header Value: `KakaoAK YOUR_ADMIN_KEY`

**Body Parameters**:
```
template_id: YOUR_TEMPLATE_ID
template_args: {"예약자명":"...", "예약일시":"...", "예약내용":"..."}
```

---

## 4. 환경변수 설정

n8n Settings → Variables에 추가:

| 변수명 | 값 | 설명 |
|--------|-----|------|
| KAKAO_ADMIN_KEY | xxxxxxxx | 카카오 Admin 키 |
| KAKAO_TEMPLATE_ID | 12345 | 알림톡 템플릿 ID |

워크플로우에서 사용:
```
{{ $env.KAKAO_ADMIN_KEY }}
{{ $env.KAKAO_TEMPLATE_ID }}
```

---

## 5. 테스트

### 5.1 수동 실행
1. 워크플로우 열기
2. "Execute Workflow" 클릭
3. 각 노드 출력 확인

### 5.2 Gmail Trigger 테스트
1. 테스트 메일 발송 (noreply@naver.com 형식 모방)
2. 트리거 동작 확인
3. 파싱 결과 확인

### 5.3 알림톡 발송 테스트
1. 테스트 전화번호로 발송
2. 카카오톡 수신 확인

---

## 6. 활성화

1. 워크플로우 우측 상단 토글 → Active
2. "Save" 클릭
3. 1분마다 Gmail 확인 시작

---

## 7. 모니터링

### 7.1 실행 로그
- n8n → Executions
- 성공/실패 내역 확인
- 에러 발생 시 상세 로그 확인

### 7.2 알림 설정 (선택)
실패 시 알림 받기:
1. Error Trigger 노드 추가
2. 이메일/슬랙 알림 연결

---

## 8. 트러블슈팅

### Gmail Trigger가 작동하지 않음
- OAuth 토큰 만료 → 재인증
- 필터 조건 확인
- n8n 로그 확인

### 파싱 실패
- 네이버 예약 메일 형식 확인
- 정규식 패턴 수정
- rawText 로그로 원본 확인

### 알림톡 발송 실패
- Admin 키 확인
- 템플릿 ID 확인
- 수신자 전화번호 형식 (하이픈 없이)
- 카카오 API 응답 코드 확인

---

## 9. 네이버 예약 메일 샘플 필요

정확한 파싱을 위해 실제 네이버 예약 메일 샘플이 필요합니다.
메일 본문을 제공해주시면 정규식 패턴을 최적화할 수 있습니다.
