"""기기 간 동기화 점검: 기기 A·B(브라우저 둘)가 흉내 낸 GitHub 저장소 하나를 같이 쓴다.

실행: python tools/test_sync.py
진짜 GitHub에는 접속하지 않는다. contents API(GET·PUT, sha 충돌)를 같은 모양으로 흉내 낸다.
"""
import base64
import hashlib
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_app import serve, check, fails  # noqa: E402
from build import open_link  # noqa: E402

TOKEN = "github_pat_TEST"
REPO_URL = "https://api.github.com/repos/lumos0107/OS_middle_test-records"
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept",
        "Access-Control-Allow-Methods": "GET, PUT, OPTIONS"}
remote = {"content": None, "sha": None, "puts": 0}


def handler(route, request):
    if request.method == "OPTIONS":
        return route.fulfill(status=204, headers=CORS)
    if request.headers.get("authorization") != f"Bearer {TOKEN}":
        return route.fulfill(status=401, headers=CORS, json={"message": "Bad credentials"})
    url = request.url.split("?")[0]
    if url == REPO_URL:
        return route.fulfill(status=200, headers=CORS, json={"full_name": "lumos0107/OS_middle_test-records"})
    if url == REPO_URL + "/contents/records.json":
        if request.method == "GET":
            if remote["content"] is None:
                return route.fulfill(status=404, headers=CORS, json={"message": "Not Found"})
            b = base64.b64encode(remote["content"]).decode()
            b = "\n".join(b[i:i + 60] for i in range(0, len(b), 60)) + "\n"   # GitHub처럼 60자마다 줄바꿈
            return route.fulfill(status=200, headers=CORS, json={"content": b, "sha": remote["sha"], "encoding": "base64"})
        if request.method == "PUT":
            body = json.loads(request.post_data)
            if remote["content"] is not None and body.get("sha") != remote["sha"]:
                return route.fulfill(status=409 if body.get("sha") else 422, headers=CORS, json={"message": "sha mismatch"})
            created = remote["content"] is None
            remote["content"] = base64.b64decode(body["content"])
            remote["sha"] = hashlib.sha1(remote["content"]).hexdigest()
            remote["puts"] += 1
            return route.fulfill(status=201 if created else 200, headers=CORS, json={"content": {"sha": remote["sha"]}})
    return route.fulfill(status=404, headers=CORS, json={"message": "Not Found"})


def rec():
    return json.loads(remote["content"].decode("utf-8")) if remote["content"] else {}


def wait_remote(page, cond, what, timeout=15):
    """흉내 낸 서버는 이 파이썬 스레드에서 돌므로 time.sleep 대신 page.wait_for_timeout으로 기다린다."""
    end = time.time() + timeout
    while time.time() < end:
        if remote["content"] and cond(rec()):
            return True
        page.wait_for_timeout(200)
    check(False, f"원격 기록에 반영 안 됨: {what}")
    return False


def device(browser, base, with_token=True):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    ctx.route("https://api.github.com/**", handler)
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept())
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(open_link(base) + (f"&t={TOKEN}" if with_token else ""))
    page.wait_for_selector(".chapters")
    if with_token:
        page.wait_for_function("(document.querySelector('#syncState')||{}).textContent?.includes('동기화됨')")
    return ctx, page, errors


def home_nums(page):
    page.goto(page.url.split("#")[0] + "#/")
    page.reload()
    page.wait_for_selector(".chapters")
    page.wait_for_function("(document.querySelector('#syncState')||{}).textContent?.includes('동기화됨')")
    page.wait_for_timeout(300)
    return page.locator(".summary .nums b").all_text_contents()


def main():
    httpd, base = serve()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ca, a, ea = device(browser, base)
        check(remote["content"] is not None, "처음 연결하면 records.json을 만든다")

        # A에서 풀고, 별표하고, 서술형 답을 쓴다
        a.goto(base + "#/q/1-01"); a.wait_for_selector(".choice"); a.click(".choice[data-k='2']")
        a.goto(base + "#/q/1-05"); a.wait_for_selector("[data-star]"); a.click("[data-star]")
        a.goto(base + "#/q/1-40"); a.wait_for_selector("#draft"); a.fill("#draft", "A에서 쓴 답")
        wait_remote(a, lambda r: r["res"].get("1-01", {}).get("r") == "o" and r["star"].get("1-05")
                    and r["draft"].get("1-40") == "A에서 쓴 답", "A의 풀이·별표·답안")

        # B에서 열면 그대로 보인다
        cb, b, eb = device(browser, base)
        check(home_nums(b) == ["1", "1", "0"], "B 첫 화면에 A의 풀이가 보임")
        b.goto(base + "#/list/star"); b.wait_for_selector(".qlist")
        check(b.locator(".qitem[data-id='1-05']").count() == 1, "B 별표 목록에 1-05")
        b.goto(base + "#/q/1-40"); b.wait_for_selector("#draft")
        check(b.input_value("#draft") == "A에서 쓴 답", "B에서 A의 서술형 답이 보임")

        # B에서 별표를 끄고 1-01을 다시 풀기로 지우면, A에서도 사라진다 (합쳐도 되살아나지 않음)
        b.goto(base + "#/q/1-05"); b.wait_for_selector("[data-star]"); b.click("[data-star]")
        b.goto(base + "#/q/1-01"); b.wait_for_selector("[data-retry]"); b.click("[data-retry]")
        wait_remote(b, lambda r: not r["star"].get("1-05") and not r["res"].get("1-01", {}).get("r"), "B의 별표 끄기·다시 풀기")
        check(home_nums(a) == ["0", "0", "0"], "A에서도 1-01 기록이 지워짐")
        a.goto(base + "#/list/star"); a.wait_for_selector("main")
        check(a.locator(".qitem").count() == 0, "A 별표 목록도 비어 있음")

        # 두 기기에서 거의 동시에 다른 문제를 풀어도 둘 다 남는다 (sha 충돌 → 다시 받아 합침)
        a.goto(base + "#/q/1-02"); a.wait_for_selector(".choice")
        b.goto(base + "#/q/1-03"); b.wait_for_selector(".choice")
        a.click(".choice[data-k='1']"); b.click(".choice[data-k='1']")
        wait_remote(a, lambda r: r["res"].get("1-02", {}).get("r") == "x" and r["res"].get("1-03", {}).get("r") == "o",
                    "동시에 푼 두 문제")
        check(home_nums(a) == ["2", "1", "1"] and home_nums(b) == ["2", "1", "1"], "두 기기 모두 2문제")

        # A에서 모든 기록 지우기 → B도 비워짐 (B의 옛 기록이 다시 올라가지 않음)
        a.goto(base + "#/settings"); a.wait_for_selector("[data-reset]"); a.click("[data-reset]")
        wait_remote(a, lambda r: r.get("resetAt", 0) > 0 and not r["res"], "모든 기록 지우기")
        check(home_nums(b) == ["0", "0", "0"], "B 기록도 지워짐")
        check(not rec()["res"], "B가 옛 기록을 다시 올리지 않음")

        # 잘못된 토큰은 연결되지 않는다
        cc, c, ec = device(browser, base, with_token=False)
        c.goto(base + "#/settings"); c.wait_for_selector("#tok")
        c.fill("#tok", "github_pat_WRONG"); c.click("[data-syncon]")
        c.wait_for_function("document.querySelector('#syncMsg').textContent.includes('토큰')")
        check(c.locator("#tok").count() == 1, "틀린 토큰이면 연결 안 됨")

        check(not (ea or eb or ec), f"페이지 오류 {ea + eb + ec}")
        browser.close()
    httpd.shutdown()
    print(f"원격 저장 {remote['puts']}번")
    print("결과:", "통과" if not fails else f"실패 {len(fails)}건")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
