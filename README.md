# OS_middle_test

운영체제 중간고사 대비용 **교재 연습문제 풀이 페이지**입니다(1~6장, 250문제). 휴대폰과 노트북 브라우저에서 바로 풀 수 있습니다.

- 주소: https://lumos0107.github.io/OS_middle_test/
- 처음 열 때 기기마다 비밀번호를 한 번 입력합니다. '이 기기에서 기억하기'를 켜 두면 다음부터는 바로 열립니다.
- 교재 문제 원문이 들어 있어서 문제 데이터(`data.enc.js`)는 비밀번호로 암호화해 올렸습니다. 이 저장소에 문제 원문은 평문으로 들어 있지 않고, 검색 엔진에도 노출하지 않습니다(noindex).
- 정답과 해설은 교재 공식 정답이 아니라 강의 슬라이드를 기준으로 만든 답입니다.

## 기능

- **객관식:** 보기를 누르면 바로 채점하고 정답·해설을 보여 줍니다. 이견이 있을 수 있는 문제와 교재 표기 메모도 함께 나옵니다.
- **계산(5장 42·43번):** 평균 대기 시간을 적어 채점하고, 간트 차트 풀이를 보여 줍니다.
- **서술형:** 내 답안을 적은 뒤(기기에 저장) 모범 답안을 보고, 채점 요소를 체크하며 맞음·틀림을 스스로 매깁니다.
- **모아 보기:** 장별 진행 상황, 틀린 문제·한 번이라도 틀린 문제·별표한 문제, 섞어 풀기(장·종류·범위·개수 선택)를 지원합니다.
- **노트북 단축키:** `1`~`4`로 보기를 고르고, `←` `→`로 이전·다음 문제로 갑니다.
- **기록:** 풀이 기록은 그 기기의 브라우저에만 저장됩니다. 설정의 '기록 코드 복사'와 '붙여 넣은 기록 합치기'로 휴대폰과 노트북 사이에 옮길 수 있습니다.

## 문제를 고친 뒤 다시 올리기

원본은 이 저장소 밖의 `../운영체제 시험 도움/교재_연습문제/*.md`입니다.

```
python tools/build.py        # md → data.enc.js, index.html 버전 표시 갱신
python tools/test_app.py     # 로컬 서버로 브라우저 점검 (Chromium·WebKit × 휴대폰·노트북)
git add -A && git commit -m "…" && git push
```

- 비밀번호와 salt는 `.secret.json`(깃 제외)에 있습니다. 이 파일이 없으면 다시 만들 수 없으니 지우지 마세요.
- 비밀번호를 바꾸려면 `.secret.json`을 지우고 `OSQ_PASSWORD=새비밀번호 python tools/build.py`를 실행합니다. 그러면 모든 기기에서 새 비밀번호를 다시 입력해야 합니다.
- 화면 파일(`app.js`, `style.css`)만 고쳤다면 `python tools/build.py --stamp-only`로 버전 표시만 갱신합니다.
- 필요한 것: Python 3.10 이상, pandoc, `pip install cryptography playwright`, `playwright install chromium webkit`

## 사용한 것

- 아이콘: [Tabler Icons](https://tabler.io/icons) 3.19.0 (MIT) — `icons.js`
- 글꼴: [Pretendard](https://github.com/orioncactus/pretendard) 1.3.9 (SIL OFL 1.1), jsDelivr CDN
