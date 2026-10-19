"""브라우저 점검: 잠금 → 풀기 → 기록 → 목록 → 250문제 모두 열기. 휴대폰·노트북 크기, Chromium·WebKit.

실행: python tools/test_app.py            (로컬 서버를 띄워 점검, 화면은 _local/shots/)
      python tools/test_app.py https://lumos0107.github.io/OS_middle_test/   (배포 주소 점검)
비밀번호는 .secret.json에서 읽는다.
"""
import functools
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
SHOTS = REPO / "_local" / "shots"
PASSWORD = json.loads((REPO / ".secret.json").read_text(encoding="utf-8"))["password"]
sys.path.insert(0, str(REPO / "tools"))
from build import open_link  # noqa: E402
LINK = lambda base: open_link(base)
DEVICES = {
    "phone": dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True),
    "laptop": dict(viewport={"width": 1280, "height": 800}),
}
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("  실패:", msg)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve():
    handler = functools.partial(QuietHandler, directory=str(REPO))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


def no_hscroll(page, where):
    w = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    check(w[0] <= w[1], f"{where}: 가로로 넘침 {w}")


def run(p, browser_name, device, base):
    tag = f"{browser_name}-{device}"
    print(f"[{tag}]")
    browser = getattr(p, browser_name).launch()
    ctx = browser.new_context(**DEVICES[device], color_scheme="light")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    shot = lambda name: page.screenshot(path=str(SHOTS / f"{tag}-{name}.png"), full_page=False)

    page.goto(base)
    page.wait_for_selector("#pw")
    shot("0-lock")
    page.fill("#pw", "wrong-password")
    page.click("#go")
    page.wait_for_function("document.querySelector('#err').textContent.length > 0")
    check("맞지 않" in page.text_content("#err"), "틀린 비밀번호 안내")
    page.fill("#pw", PASSWORD)
    page.click("#go")
    page.wait_for_selector(".chapters")
    check(page.locator(".chapter").count() == 6, "장 카드 6개")
    check("250문제" in page.text_content(".hero"), "전체 250문제 표시")
    no_hscroll(page, "첫 화면")

    # 1장: 맞는 답, 틀린 답
    page.click("a.chapter[href='#/ch/1']")
    page.wait_for_selector(".grid")
    check(page.locator(".cell").count() == 45, "1장 칸 45개")
    page.click(".cell[data-id='1-01']")
    page.wait_for_selector(".choice")
    check(page.locator(".choice").count() == 4, "보기 4개")
    page.click(".choice[data-k='2']")
    check(page.locator(".result.ok").count() == 1, "1-01 정답 처리")
    check("유틸리티" in page.text_content(".answer"), "1-01 정답 글")
    shot("2-mc-ok")
    page.click("[data-next]")
    page.wait_for_selector(".where >> text=1장 02번")
    page.click(".choice[data-k='1']")
    check(page.locator(".result.no").count() == 1, "1-02 오답 처리")
    check(page.locator(".choice.correct[data-k='4']").count() == 1, "1-02 정답 보기 표시")
    no_hscroll(page, "객관식 풀이 뒤")
    shot("3-mc-no")

    # 다음 버튼은 문제 길이·풀이 여부와 상관없이 같은 자리(화면 맨 아래)
    spots = []
    for pid in ("1-21", "6-29"):
        page.goto(base + f"#/q/{pid}")
        page.wait_for_selector("[data-next]")
        spots.append(page.evaluate("Math.round(document.querySelector('[data-next]').getBoundingClientRect().bottom - innerHeight)"))
    page.goto(base + "#/q/1-20")
    page.wait_for_selector(".choice")
    page.click(".choice[data-k='4']")
    spots.append(page.evaluate("Math.round(document.querySelector('[data-next]').getBoundingClientRect().bottom - innerHeight)"))
    page.click("[data-retry]")   # 뒤 점검의 기록 숫자가 바뀌지 않게 되돌림
    check(len(set(spots)) == 1 and -40 < spots[0] <= 0, f"다음 버튼 위치가 들쭉날쭉 {spots}")

    # 새로고침해도 열쇠·기록 유지
    page.goto(base + "#/")
    page.reload()
    page.wait_for_selector(".chapters")
    nums = page.locator(".summary .nums b").all_text_contents()
    check(nums == ["2", "1", "1"], f"기록 유지 {nums}")

    # 정답이 둘인 문제, 계산, 서술형
    page.goto(base + "#/q/2-21")
    page.wait_for_selector(".choice")
    page.click(".choice[data-k='4']")
    check(page.locator(".result.ok").count() == 1, "2-21 ④도 정답")
    check(page.locator(".choice.correct").count() == 2, "2-21 정답 두 개 표시")
    page.goto(base + "#/q/5-42")
    page.wait_for_selector("#calc")
    for k, v in enumerate(["19", "12", "13"]):
        page.fill(f"#v{k}", v)
    page.click("#calc button[type=submit]")
    check(page.locator(".result.no").count() == 1, "5-42 하나 틀리면 오답")
    check(page.locator(".sub.no .key").text_content().strip() == "정답 12ms", "5-42 틀린 칸에 정답")
    no_hscroll(page, "계산 풀이")
    shot("4-calc")
    page.goto(base + "#/q/6-29")
    page.wait_for_selector("#draft")
    page.fill("#draft", "두 스레드가 모두 임계구역에 들어간다. 상호 배제 위반")
    page.click("[data-reveal]")
    page.locator(".rubric input").first.check()
    page.click("[data-self='o']")
    check(page.locator("[data-self='o'].on-ok").count() == 1, "서술형 스스로 채점")
    fs = page.evaluate("parseFloat(getComputedStyle(document.querySelector('.q pre')).fontSize)")
    check(fs >= 9, f"6-29 코드 글자 크기 {fs}")
    no_hscroll(page, "서술형 풀이")
    shot("5-essay-top")
    page.evaluate("document.querySelector('.answer').scrollIntoView()")
    shot("6-essay-model")

    # 목록·섞어 풀기·세션 결과
    page.goto(base + "#/list/wrong")
    page.wait_for_selector(".qlist")
    ids = page.locator(".qitem").evaluate_all("els => els.map(e => e.dataset.id)")
    check(ids == ["1-02", "5-42"], f"틀린 문제 목록 {ids}")
    page.click("[data-run]")
    page.wait_for_selector(".choice")
    check(page.locator(".choice.locked").count() == 0, "다시 풀기는 새로 푸는 상태")
    page.click(".choice[data-k='4']")
    page.click("[data-next]")
    page.wait_for_selector("#calc")
    page.click("[data-next]")
    page.wait_for_selector(".summary")
    nums = page.locator(".summary .nums b").all_text_contents()
    check(nums == ["1", "0", "1"], f"세션 결과 {nums}")
    shot("7-done")
    page.goto(base + "#/mix")
    page.wait_for_selector("[data-go]")
    page.click("[data-go]")
    page.wait_for_selector(".prob")
    check("섞어 풀기 20문제" in page.text_content(".where"), "섞어 풀기 세션")

    # 250문제 모두 열어 보기 (WebKit은 10초에 주소 바꾸기 100번 제한이 있어 다섯 문제마다 하나만)
    all_ids = json.loads((REPO / "_local" / "ids.json").read_text(encoding="utf-8"))
    if browser_name == "webkit":
        all_ids = all_ids[::5] + ["2-21", "5-43", "6-31"]
        page.wait_for_timeout(10_000)
    bad = []
    for pid in all_ids:
        page.evaluate(f"location.hash = '#/q/{pid}'")
        want = f"{int(pid.split('-')[0])}장 {pid.split('-')[1]}번"
        try:
            page.wait_for_function(f"(document.querySelector('.where b') || {{}}).textContent === '{want}'", timeout=5000)
        except Exception:
            now = page.evaluate("[location.hash, (document.querySelector('.where b') || {}).textContent]")
            bad.append((pid, f"안 열림 {now}"))
            break
        info = page.evaluate("""() => ({ q: document.querySelector('.q').textContent.trim().length,
            choices: document.querySelectorAll('.choice').length, essay: !!document.querySelector('#draft'),
            calc: !!document.querySelector('#calc'),
            wide: document.documentElement.scrollWidth > window.innerWidth })""")
        if not info["q"] or not (info["choices"] == 4 or info["essay"] or info["calc"]) or info["wide"]:
            bad.append((pid, info))
    check(not bad, f"문제 화면 이상 {bad[:5]}")

    # 노트북 단축키
    if device == "laptop":
        page.goto(base + "#/q/3-01")
        page.wait_for_selector(".choice")
        page.keyboard.press("2")
        check(page.locator(".result.ok").count() == 1, "단축키 2로 답하기")
        page.keyboard.press("ArrowRight")
        page.wait_for_selector(".where >> text=3장 02번")

    # 어두운 화면
    page.emulate_media(color_scheme="dark")
    page.goto(base + "#/")
    page.wait_for_selector(".chapters")
    shot("8-dark-home")
    page.goto(base + "#/q/6-07")
    page.wait_for_selector(".choice")
    page.click(".choice[data-k='3']")
    shot("9-dark-mc")
    page.emulate_media(color_scheme="light")
    page.goto(base + "#/")
    page.wait_for_selector(".chapters")
    shot("1-home")
    page.goto(base + "#/ch/5")
    page.wait_for_selector(".grid")
    shot("1b-chapter")

    check(not errors, f"콘솔 오류 {errors[:3]}")

    # 열쇠 링크로 열기: 비밀번호 화면 없이 첫 화면, 주소에서 열쇠는 지워짐, 기본은 흰 화면
    ctx2 = browser.new_context(**DEVICES[device], color_scheme="dark")
    p2 = ctx2.new_page()
    p2.goto(LINK(base))
    p2.wait_for_selector(".chapters")
    check("#k=" not in p2.url, f"열쇠가 주소에 남음 {p2.url}")
    bg = p2.evaluate("getComputedStyle(document.body).backgroundColor")
    check(bg == "rgb(255, 255, 255)", f"기본 배경이 흰색이 아님 {bg}")
    p2.reload()
    p2.wait_for_selector(".chapters")
    ctx2.close()
    browser.close()


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    data = json.loads((REPO / "_local" / "data.json").read_text(encoding="utf-8"))
    ids = [pid for c in data["chapters"] for pid in c["ids"]]
    (REPO / "_local" / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    httpd = None
    if len(sys.argv) > 1:
        base = sys.argv[1]
    else:
        httpd, base = serve()
    with sync_playwright() as p:
        for b in ("chromium", "webkit"):
            for d in DEVICES:
                run(p, b, d, base)
    if httpd:
        httpd.shutdown()
    print("결과:", "통과" if not fails else f"실패 {len(fails)}건")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
