"""교재 연습문제 md 6개 → 암호화한 문제 데이터(data.enc.js).

실행: python tools/build.py              (기본 원본: 중간고사대비/운영체제/시험 도움/교재_연습문제)
      python tools/build.py --plain _local/data.json   (점검용 평문 JSON도 함께, _local/은 깃 제외)
비밀번호와 salt는 .secret.json(깃 제외)에 둔다. 처음 한 번은 OSQ_PASSWORD 환경 변수로 만든다.
salt를 고정해 두므로 데이터를 다시 만들어도 기기에 기억된 열쇠가 그대로 통한다.
필요: pandoc, cryptography
"""
import argparse
import base64
import datetime
import hashlib
import hmac
import html
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

REPO = Path(__file__).resolve().parents[1]
# 원본 md 위치: 저장소가 중간고사대비/ 바로 아래에 있든 중간고사대비/운영체제/ 안에 있든 찾는다
_SRC_CANDIDATES = [REPO.parent / "운영체제" / "시험 도움" / "교재_연습문제",
                   REPO.parent / "시험 도움" / "교재_연습문제"]
DEFAULT_SRC = next((p for p in _SRC_CANDIDATES if p.is_dir()), _SRC_CANDIDATES[0])
SECRET = REPO / ".secret.json"
OUT = REPO / "data.enc.js"
SITE = "https://lumos0107.github.io/OS_middle_test/"
ITERATIONS = 400_000
EXPECTED = {1: 45, 2: 49, 3: 33, 4: 37, 5: 51, 6: 35}   # 장별 문제 수 (사진 점검 때 센 값)

CIRCLED = "①②③④⑤⑥⑦⑧⑨"
PROB_RE = re.compile(r"^\*\*(\d{2})\*\*(?:\s+(.*))?$")
SECTION_TYPE = {"객관식": "mc", "계산": "calc", "서술형": "essay"}


# ── md 조각 다루기 ────────────────────────────────────────────────

def trim_blank(lines):
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def take_paren(text, start):
    """text[start]의 '('와 짝이 맞는 ')' 다음 위치를 돌려준다."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def split_dispute(md):
    """'(이견 가능: …)'을 본문에서 떼어 따로 돌려준다."""
    notes = []
    while True:
        i = md.find("(이견 가능:")
        if i < 0:
            break
        j = take_paren(md, i)
        if j < 0:
            raise ValueError(f"이견 가능 괄호가 닫히지 않음: {md[i:i + 60]}")
        notes.append(md[i + len("(이견 가능:"):j - 1].strip())
        md = (md[:i].rstrip() + " " + md[j:].lstrip()).strip()
        md = re.sub(r"\s+([.,])", r"\1", md)
    return md, notes


def split_choices(block):
    s = re.sub(r"\\[ \t]*$", "", block, flags=re.M)
    parts = re.split(r"([①②③④])", s)
    marks = parts[1::2]
    if parts[0].strip() or marks != list("①②③④"):
        raise ValueError(f"보기 4개를 못 나눔: {block[:80]!r}")
    return [p.strip() for p in parts[2::2]]


def blanks(md):
    """코드 밖의 빈칸 '(   )'을 글씨 칸으로 바꾼다(HTML은 공백을 줄이므로)."""
    parts = re.split(r"(^```.*?^```[ \t]*$|`[^`\n]*`)", md, flags=re.S | re.M)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"\(\s{2,}\)", '(<span class="blank"></span>)', parts[i])
    return "".join(parts)


# ── 장 파일 읽기 ──────────────────────────────────────────────────

def parse_chapter(path):
    lines = path.read_text(encoding="utf-8").split("\n")
    m = re.match(r"# (\d)장 (.+?) — 교재 연습문제", lines[0])
    ch_no, title = int(m.group(1)), m.group(2)
    pages = re.search(r"교재 (\d+~\d+쪽)", "\n".join(lines[:5])).group(1)

    # '## ' 절로 나누기
    sections, cur = [], None
    for ln in lines:
        if ln.startswith("## "):
            cur = [ln[3:].strip(), []]
            sections.append(cur)
        elif cur:
            cur[1].append(ln)

    problems, notes = [], []
    for name, body in sections:
        if name == "교재 표기 메모":
            notes = [ln[2:].strip() for ln in body if ln.startswith("- ")]
            continue
        ptype = SECTION_TYPE[name]
        groups, g = [], None
        for ln in body:
            if ln.startswith("### "):
                g = [ln[4:].strip(), []]
                groups.append(g)
            elif g:
                g[1].append(ln)
        for head, glines in groups:
            page = re.match(r"(\d+쪽)", head).group(1)
            d0 = next(i for i, ln in enumerate(glines) if ln.strip() == "<details>")
            d1 = next(i for i, ln in enumerate(glines) if ln.strip() == "</details>")
            summary = glines[d0 + 1]
            qlines = [ln for ln in glines[:d0] if not ln.startswith("<!--")]
            alines = glines[d0 + 2:d1]
            probs = parse_questions(qlines, ptype, ch_no, page)
            attach_answers(probs, alines, summary, ptype)
            problems += probs
    return {"no": ch_no, "title": title, "pages": pages, "problems": problems, "notes": notes}


def parse_questions(qlines, ptype, ch_no, page):
    probs, cur = [], None
    fence = False
    for ln in qlines:
        if ln.startswith("```"):
            fence = not fence
        m = None if fence else PROB_RE.match(ln)
        if m:
            cur = {"ch": ch_no, "no": m.group(1), "type": ptype, "page": page, "lines": [m.group(2) or ""]}
            probs.append(cur)
        elif cur:
            cur["lines"].append(ln)
    for p in probs:
        body = trim_blank(p.pop("lines"))
        p["adv"] = False
        if body and body[0].startswith("**[심화]** "):
            p["adv"] = True
            body[0] = body[0][len("**[심화]** "):]
        if ptype == "mc":
            # 마지막 문단(①로 시작)이 보기
            k = len(body)
            while k > 0 and body[k - 1].strip():
                k -= 1
            choice_block = "\n".join(body[k:])
            if not choice_block.lstrip().startswith("①"):
                raise ValueError(f"{ch_no}-{p['no']} 보기 문단을 못 찾음")
            p["choices_md"] = split_choices(choice_block)
            body = trim_blank(body[:k])
        elif ptype == "calc":
            subs = [re.match(r"^\((\d)\) (.+?)\\?\s*$", ln) for ln in body]
            p["subs"] = [s.group(2) for s in subs if s]
            body = trim_blank([ln for ln, s in zip(body, subs) if not s])
        p["q_md"] = blanks("\n".join(body))
    return probs


def attach_answers(probs, alines, summary, ptype):
    by_no = {p["no"]: p for p in probs}
    if "정답" in summary:
        for ln in alines:
            m = re.match(r"^\|\s*(\d{2})\s*\|(.*)\|\s*$", ln)
            if not m:
                continue
            cells = [c.strip() for c in m.group(2).split(" | ")]
            if len(cells) != 2:
                raise ValueError(f"정답 표 칸 수가 이상함: {ln[:80]}")
            p = by_no[m.group(1)]
            ans = [CIRCLED.index(c) + 1 for c in re.findall(r"[①②③④]", cells[0])]
            if not ans:
                raise ValueError(f"{p['ch']}-{p['no']} 정답 번호가 없음")
            p["ans"] = ans
            p["ans_md"] = cells[0]
            p["exp_md"], p["dispute_md"] = split_dispute(cells[1])
        return
    # 모범 답안 / 풀이: **NN** 줄로 나눈 덩어리
    blocks, intro, cur = {}, [], None
    for ln in alines:
        m = PROB_RE.match(ln)
        if m and m.group(1) in by_no:
            cur = m.group(1)
            blocks[cur] = [m.group(2) or ""]
        elif cur:
            blocks[cur].append(ln)
        else:
            intro.append(ln)
    for no, p in by_no.items():
        body = blocks[no]
        rubric = [ln for ln in body if ln.startswith("- 채점 요소:")]
        body = trim_blank([ln for ln in body if not ln.startswith("- 채점 요소:")])
        text = "\n".join(body)
        p["intro_md"] = "\n".join(trim_blank(intro))
        p["model_md"], p["dispute_md"] = split_dispute(text)
        p["rubric_md"] = []
        for r in rubric:
            items = re.split(r"[①②③④⑤⑥⑦⑧⑨]", r[len("- 채점 요소:"):])
            p["rubric_md"] += [i.strip() for i in items if i.strip()]
        if ptype == "calc":
            k = re.search(r"정리: FCFS (\d+)ms, SJF (\d+)ms, HRN (\d+)ms", text)
            p["keys"] = [int(x) for x in k.groups()]
            if p["subs"] != ["선입선출", "최단 작업 우선", "최고 응답 우선"]:
                raise ValueError(f"{p['ch']}-{no} 계산 소문항이 예상과 다름: {p['subs']}")


def note_targets(note):
    """교재 표기 메모 한 줄이 가리키는 문제 번호들."""
    def nums(s):
        out = []
        for a, b in re.findall(r"(\d{1,2})(?:~(\d{1,2}))?번", s):
            out += list(range(int(a), int(b or a) + 1))
        return out
    if "—" in note:
        found = nums(note.split("—")[0]) or nums(note)
    else:
        found = nums(note)[:1]
    return [f"{n:02d}" for n in found]


# ── HTML 만들기 ───────────────────────────────────────────────────

def pandoc_many(frags):
    """md 조각 여러 개를 pandoc 한 번으로 HTML로 바꾼다."""
    sep = "OSQSEP{:05d}"
    doc = "\n\n".join(f"{f}\n\n{sep.format(i)}" for i, f in enumerate(frags))
    res = subprocess.run(["pandoc", "-f", "gfm", "-t", "html", "--wrap=none"], input=doc.encode("utf-8"),
                         capture_output=True, check=True)
    out_html = res.stdout.decode("utf-8").replace("\r\n", "\n")
    parts = re.split(r"<p>OSQSEP(\d{5})</p>\s*", out_html)
    out = [None] * len(frags)
    for i in range(0, len(parts) - 1, 2):
        out[int(parts[i + 1])] = parts[i].strip()
    if any(o is None for o in out):
        raise RuntimeError("pandoc 결과를 조각으로 다시 나누지 못함")
    return out


def char_cols(ch):
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def fix_pre(h):
    """코드 블록: 한글 같은 넓은 글자를 2칸 고정 폭에 넣고, 가장 긴 줄의 칸 수를 --cols로 넘긴다."""
    def one(m):
        attrs, body = m.group(1), m.group(2)
        plain = html.unescape(re.sub(r"<[^>]+>", "", body))
        cols = max((sum(char_cols(c) for c in line) for line in plain.split("\n")), default=0)
        pieces = re.split(r"(<[^>]+>|&[a-zA-Z#0-9]+;)", body)

        def wrap(c):
            if ord(c) < 128:
                return c
            return f'<span class="{"w" if char_cols(c) == 2 else "n"}">{c}</span>'
        new = "".join(p if p.startswith(("<", "&")) else "".join(wrap(c) for c in p) for p in pieces)
        return f'<pre{attrs} style="--cols:{cols}">{new}</pre>'
    return re.sub(r"<pre([^>]*)>(.*?)</pre>", one, h, flags=re.S)


def soften(h):
    """(보충)·(일반 교재 기준)·(슬라이드 …) 같은 출처 표시를 흐리게."""
    h = h.replace("(보충)", '<span class="src">(보충)</span>')
    h = h.replace("(일반 교재 기준)", '<span class="src">(일반 교재 기준)</span>')
    out, i = [], 0
    pat = re.compile(r"\((?:\d장 )?슬라이드 ")
    while True:
        m = pat.search(h, i)
        if not m:
            out.append(h[i:])
            break
        j = take_paren(h, m.start())
        seg = h[m.start():j] if j > 0 else ""
        balanced = j > 0 and len(re.findall(r"<[a-z]", seg)) == len(re.findall(r"</", seg))
        if not balanced:
            out.append(h[i:m.end()])
            i = m.end()
            continue
        out.append(h[i:m.start()] + f'<span class="src">{seg}</span>')
        i = j
    return "".join(out)


def nbsp_code(h):
    """짧은 인라인 코드(24자 이하)는 줄바꿈으로 쪼개지지 않게 공백을 붙는 공백으로."""
    parts = re.split(r"(<pre.*?</pre>)", h, flags=re.S)

    def one(m):
        text = html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        return f"<code>{m.group(1).replace(' ', '&nbsp;')}</code>" if len(text) <= 24 else m.group(0)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"<code>(.*?)</code>", one, parts[i])
    return "".join(parts)


def block(h):
    h = fix_pre(h)
    h = re.sub(r"<table>", '<div class="tbl"><table>', h)
    h = h.replace("</table>", "</table></div>")
    return soften(nbsp_code(h))


def inline(h):
    h = h.strip()
    if h.startswith("<p>") and h.endswith("</p>") and h.count("<p>") == 1:
        h = h[3:-4]
    return soften(nbsp_code(h))


# ── 조립 ──────────────────────────────────────────────────────────

def build(src_dir):
    chapters = [parse_chapter(src_dir / f"{n}장_연습문제.md") for n in range(1, 7)]

    # 바꿀 md 조각을 한곳에 모은다: (문제, 필드, 종류, md)
    jobs = []
    for ch in chapters:
        for p in ch["problems"]:
            jobs.append((p, "q", "block", p["q_md"]))
            if p["type"] == "mc":
                for k, c in enumerate(p["choices_md"]):
                    jobs.append((p, ("choices", k), "inline", c))
                jobs.append((p, "ans_text", "inline", p["ans_md"]))
                jobs.append((p, "exp", "inline", p["exp_md"]))
            else:
                jobs.append((p, "model", "block", p["model_md"]))
                for k, r in enumerate(p["rubric_md"]):
                    jobs.append((p, ("rubric", k), "inline", r))
                if p["intro_md"]:
                    jobs.append((p, "intro", "block", p["intro_md"]))
            for k, d in enumerate(p["dispute_md"]):
                jobs.append((p, ("dispute", k), "inline", d))
        for k, n in enumerate(ch["notes"]):
            jobs.append((ch, ("notes", k), "inline", n))

    htmls = pandoc_many([j[3] for j in jobs])
    for (obj, field, kind, _), h in zip(jobs, htmls):
        h = block(h) if kind == "block" else inline(h)
        if "**" in re.sub(r"<pre.*?</pre>|<code>.*?</code>", "", h, flags=re.S):
            raise ValueError(f"굵게 표시가 깨짐: {h[:120]}")
        if isinstance(field, tuple):
            obj.setdefault(field[0] + "_html", {})[field[1]] = h
        else:
            obj[field + "_html"] = h

    newest = max((src_dir / f"{n}장_연습문제.md").stat().st_mtime for n in range(1, 7))
    data = {"v": 1, "built": datetime.date.fromtimestamp(newest).isoformat(), "chapters": [], "problems": {}}
    for ch in chapters:
        notes = [ch["notes_html"][k] for k in range(len(ch["notes"]))] if ch["notes"] else []
        targets = {}
        for k, n in enumerate(ch["notes"]):
            for no in note_targets(n):
                targets.setdefault(no, []).append(notes[k])
        ids, counts = [], {"mc": 0, "calc": 0, "essay": 0}
        for p in ch["problems"]:
            pid = f"{ch['no']}-{p['no']}"
            ids.append(pid)
            counts[p["type"]] += 1
            q = {"ch": ch["no"], "no": p["no"], "type": p["type"], "page": p["page"], "adv": p["adv"],
                 "q": p["q_html"]}
            if p["type"] == "mc":
                q["choices"] = [p["choices_html"][k] for k in range(4)]
                q["ans"] = p["ans"]
                q["ansText"] = p["ans_text_html"]
                q["exp"] = p["exp_html"]
            else:
                q["model"] = p["model_html"]
                q["rubric"] = [p["rubric_html"][k] for k in range(len(p["rubric_md"]))]
                if p.get("intro_html"):
                    q["intro"] = p["intro_html"]
                if p["type"] == "calc":
                    q["subs"] = p["subs"]
                    q["keys"] = p["keys"]
            if p["dispute_md"]:
                q["dispute"] = [p["dispute_html"][k] for k in range(len(p["dispute_md"]))]
            if p["no"] in targets:
                q["notes"] = targets[p["no"]]
            data["problems"][pid] = q
        if len(ids) != EXPECTED[ch["no"]]:
            raise ValueError(f"{ch['no']}장 문제 수 {len(ids)} ≠ {EXPECTED[ch['no']]}")
        data["chapters"].append({"no": ch["no"], "title": ch["title"], "pages": ch["pages"],
                                 "counts": counts, "ids": ids, "notes": notes})
    return data


def check(data):
    probs = data["problems"]
    for pid, q in probs.items():
        if q["type"] == "mc":
            assert len(q["choices"]) == 4 and all(q["choices"]), pid
            assert q["ans"] and all(1 <= a <= 4 for a in q["ans"]), pid
            assert q["exp"], pid
        elif q["type"] == "essay":
            assert q["model"], pid
            assert q["rubric"], f"{pid} 채점 요소 없음"
        else:
            assert q["model"] and len(q["keys"]) == len(q["subs"]) == 3, pid
    multi = [pid for pid, q in probs.items() if q["type"] == "mc" and len(q["ans"]) > 1]
    disputes = [pid for pid, q in probs.items() if q.get("dispute")]
    noted = [pid for pid, q in probs.items() if q.get("notes")]
    for ch in data["chapters"]:
        c = ch["counts"]
        print(f"{ch['no']}장 {ch['title']}: {len(ch['ids'])}문제 (객관식 {c['mc']} · 계산 {c['calc']} · 서술형 {c['essay']})")
    print(f"합계 {len(probs)}문제 / 정답 둘 {multi} / 이견 가능 {len(disputes)}개 / 교재 표기 메모 {noted}")


# ── 암호화 ────────────────────────────────────────────────────────

def load_secret():
    if SECRET.exists():
        s = json.loads(SECRET.read_text(encoding="utf-8"))
        return s["password"], base64.b64decode(s["salt"])
    pw = os.environ.get("OSQ_PASSWORD")
    if not pw:
        sys.exit(".secret.json이 없습니다. 처음 한 번은 OSQ_PASSWORD 환경 변수로 비밀번호를 주세요.")
    salt = os.urandom(16)
    SECRET.write_text(json.dumps({"password": pw, "salt": base64.b64encode(salt).decode()}, ensure_ascii=False),
                      encoding="utf-8")
    print(".secret.json을 만들었습니다(깃 제외).")
    return pw, salt


def derive_key(password, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode())


def open_link(base=SITE):
    """비밀번호 없이 여는 링크: 주소 뒤 #k=에 열쇠를 붙인다(# 뒤는 서버로 가지 않는다)."""
    password, salt = load_secret()
    return base + "#k=" + base64.urlsafe_b64encode(derive_key(password, salt)).decode().rstrip("=")


def encrypt(data, password, salt):
    key = derive_key(password, salt)
    plain = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # 내용이 같으면 같은 파일이 나오도록 IV를 내용에서 만든다(내용이 다르면 IV도 달라진다)
    iv = hmac.new(key, plain, hashlib.sha256).digest()[:12]
    ct = AESGCM(key).encrypt(iv, plain, None)
    b64 = lambda b: base64.b64encode(b).decode()
    blob = {"v": 1, "iter": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}
    return f"window.OSQ_DATA = {json.dumps(blob)};\n", len(plain)


STAMPED = ["style.css", "app.js", "icons.js", "data.enc.js", "favicon.svg", "apple-touch-icon.png"]


def stamp_index():
    """index.html의 파일 주소 뒤 ?v=를 파일 내용 해시로 바꿔, 바뀐 파일만 새로 받게 한다."""
    idx = REPO / "index.html"
    text = idx.read_text(encoding="utf-8")
    for name in STAMPED:
        p = REPO / name
        if p.exists():
            v = hashlib.sha1(p.read_bytes()).hexdigest()[:8]
            text = re.sub(rf"({re.escape(name)})\?v=[0-9a-z]*", rf"\g<1>?v={v}", text)
    idx.write_text(text, encoding="utf-8", newline="\n")
    print("index.html 버전 표시 갱신")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default=str(DEFAULT_SRC))
    ap.add_argument("--plain", help="점검용 평문 JSON 경로(깃 제외 폴더에)")
    ap.add_argument("--stamp-only", action="store_true", help="데이터는 그대로 두고 index.html 버전 표시만 갱신")
    ap.add_argument("--link", action="store_true", help="비밀번호 없이 여는 링크(열쇠 포함)를 출력")
    args = ap.parse_args()
    if args.link:
        print(open_link())
        return
    if args.stamp_only:
        stamp_index()
        return
    data = build(Path(args.src))
    check(data)
    if args.plain:
        Path(args.plain).parent.mkdir(parents=True, exist_ok=True)
        Path(args.plain).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    password, salt = load_secret()
    js, n = encrypt(data, password, salt)
    OUT.write_text(js, encoding="utf-8", newline="\n")
    print(f"{OUT.name}: 평문 {n // 1024}KB → {len(js) // 1024}KB")
    stamp_index()


if __name__ == "__main__":
    main()
