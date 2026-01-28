"""
네이버 로그인 세션 저장 스크립트
- 수동으로 로그인 후 세션 쿠키 저장
- 한 번만 실행하면 됨
"""

import asyncio
from playwright.async_api import async_playwright

STORAGE_PATH = "naver_session.json"


async def save_login_session():
    """브라우저 열고 수동 로그인 후 세션 저장"""

    async with async_playwright() as p:
        # 브라우저 열기 (headless=False로 화면 표시)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # 네이버 로그인 페이지
        await page.goto("https://nid.naver.com/nidlogin.login")

        print("=" * 50)
        print("브라우저에서 네이버 로그인을 완료해주세요.")
        print("로그인 완료 후 Enter를 누르세요...")
        print("=" * 50)

        # 사용자가 로그인 완료할 때까지 대기
        input()

        # 로그인 확인 - 스마트플레이스 접근 테스트
        await page.goto("https://partner.booking.naver.com/bizes/1575275/booking-list-view")
        await page.wait_for_timeout(3000)

        # 세션 저장
        await context.storage_state(path=STORAGE_PATH)

        print(f"세션이 {STORAGE_PATH}에 저장되었습니다!")
        print("이제 Docker 컨테이너에서 이 파일을 사용할 수 있습니다.")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(save_login_session())
