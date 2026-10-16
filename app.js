/* 운영체제 교재 연습문제
 * 문제 데이터(data.enc.js)는 비밀번호로 암호화되어 있고, 풀이 기록은 이 기기의 localStorage에만 둔다. */
(() => {
  'use strict';

  const ICONS = window.OSQ_ICONS || {};
  const ENC = window.OSQ_DATA;
  const app = document.getElementById('app');
  const CIRC = ['', '①', '②', '③', '④'];
  const TYPE_NAME = { mc: '객관식', calc: '계산', essay: '서술형' };
  const K = { key: 'osq:key', rec: 'osq:rec', last: 'osq:last', session: 'osq:session', theme: 'osq:theme', mix: 'osq:mix' };

  let DATA = null;   // 복호화한 문제 데이터
  let CH = {};       // 장 번호 → 장
  let ORDER = [];    // 전체 문제 id (1장 01 → 6장 35)
  let REC = null;    // 풀이 기록 { res, star, draft, check }

  // ── 작은 도구 ─────────────────────────────────────────────
  const $ = (sel, root = app) => root.querySelector(sel);
  const $$ = (sel, root = app) => Array.from(root.querySelectorAll(sel));
  const on = (sel, fn) => { const el = $(sel); if (el) el.addEventListener('click', fn); };
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pct = (a, n) => (n ? (a / n * 100).toFixed(2) : 0);
  function icon(name) {
    const body = ICONS[name] || '';
    return name.endsWith('-filled')
      ? `<svg class="ic" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${body}</svg>`
      : `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
  }
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* 저장소를 못 쓰는 환경 */ } },
  };
  const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  function toB64(u8) {
    let s = '';
    for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return btoa(s);
  }
  function plain(h) {
    const d = document.createElement('div');
    d.innerHTML = h;
    return d.textContent.replace(/\s+/g, ' ').trim();
  }
  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  // ── 복호화 ────────────────────────────────────────────────
  async function deriveRaw(pw) {
    const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveBits']);
    const bits = await crypto.subtle.deriveBits(
      { name: 'PBKDF2', hash: 'SHA-256', salt: b64(ENC.salt), iterations: ENC.iter }, base, 256);
    return new Uint8Array(bits);
  }
  async function openData(raw) {
    const key = await crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['decrypt']);
    const out = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(ENC.iv) }, key, b64(ENC.ct));
    return JSON.parse(new TextDecoder().decode(out));
  }

  // ── 기록 ──────────────────────────────────────────────────
  function loadRec() {
    const r = store.get(K.rec, null);
    REC = Object.assign({ res: {}, star: {}, draft: {}, check: {} }, r && typeof r === 'object' ? r : {});
  }
  const saveRec = () => store.set(K.rec, REC);
  const P = id => DATA.problems[id];
  const state = id => (REC.res[id] && REC.res[id].r) || '';
  const count = (ids, st) => ids.filter(id => state(id) === st).length;
  function setResult(id, r, extra) {
    const prev = REC.res[id] || {};
    REC.res[id] = Object.assign({}, extra, { r, t: Date.now(), n: (prev.n || 0) + 1, ever: !!prev.ever || r === 'x' });
    saveRec();
  }
  function clearResult(id) {
    const prev = REC.res[id];
    if (prev) REC.res[id] = { ever: !!prev.ever, n: prev.n || 0 };
    delete REC.check[id];
    saveRec();
  }

  // ── 세션: 지금 풀고 있는 문제 묶음과 순서 ─────────────────────
  function getSession(id) {
    const s = store.get(K.session, null);
    if (s && Array.isArray(s.ids) && s.ids.includes(id)) return s;
    const ch = P(id).ch;
    const fallback = { label: `${ch}장 전체`, ids: CH[ch].ids, back: `#/ch/${ch}`, fresh: false, started: 0 };
    store.set(K.session, fallback);
    return fallback;
  }
  function startSession(label, ids, back, opt) {
    opt = opt || {};
    if (!ids.length) return;
    store.set(K.session, { label, ids, back, fresh: !!opt.fresh, started: Date.now() });
    go(`#/q/${opt.at || ids[0]}`);
  }
  // 새로 푸는 세션이면 세션을 시작한 뒤에 푼 결과만 보여 준다
  function shownRes(s, id) {
    const r = REC.res[id];
    if (!r || !r.r) return null;
    if (s.fresh && (r.t || 0) < s.started) return null;
    return r;
  }

  // ── 화면 이동 ─────────────────────────────────────────────
  function go(hash, replace) {
    if (replace) { history.replaceState(null, '', hash); route(); }
    else if (location.hash === hash) route();
    else location.hash = hash;
  }
  function route() {
    if (!DATA) return;
    const [a, b] = location.hash.replace(/^#\/?/, '').split('/');
    window.scrollTo(0, 0);
    if (a === 'ch' && CH[b]) renderChapter(+b);
    else if (a === 'q' && DATA.problems[b]) renderProblem(b);
    else if (a === 'list' && LISTS[b]) renderList(b);
    else if (a === 'mix') renderMix();
    else if (a === 'done') renderDone();
    else if (a === 'settings') renderSettings();
    else renderHome();
  }
  window.addEventListener('hashchange', route);

  // ── 공통 조각 ─────────────────────────────────────────────
  function topbar(back, title, sub) {
    return `<div class="bar"><div class="wrap">
      <a class="icon-btn" href="${back}" aria-label="뒤로">${icon('arrow-left')}</a>
      <div class="where"><b>${esc(title)}</b>${sub ? `<span>${esc(sub)}</span>` : ''}</div>
      <a class="icon-btn" href="#/" aria-label="처음 화면">${icon('home')}</a>
    </div></div>`;
  }
  const meter = (ok, no, n) => `<div class="meter" role="img" aria-label="맞음 ${ok}, 틀림 ${no}, 전체 ${n}">`
    + `<i class="o" style="width:${pct(ok, n)}%"></i><i class="x" style="width:${pct(no, n)}%"></i></div>`;
  const kinds = c => [['mc', '객관식'], ['calc', '계산'], ['essay', '서술형']]
    .filter(([t]) => c.counts[t]).map(([t, name]) => `${name} ${c.counts[t]}`).join(' · ');
  function qItem(id) {
    const q = P(id);
    return `<li><button class="qitem" data-id="${id}"><span class="qno ${state(id)}">${q.ch}장 ${q.no}</span>`
      + `<span class="qtext">${esc(plain(q.q))}</span></button></li>`;
  }
  function bindItems(ids, label, back) {
    $$('.qitem').forEach(b => b.addEventListener('click', () => startSession(label, ids, back, { at: b.dataset.id })));
  }
  const LISTS = {
    wrong: { title: '틀린 문제', desc: '마지막으로 풀었을 때 틀린 문제', ids: () => ORDER.filter(id => state(id) === 'x') },
    ever: { title: '한 번이라도 틀린 문제', desc: '지금은 맞혔어도 전에 틀린 적이 있는 문제', ids: () => ORDER.filter(id => REC.res[id] && REC.res[id].ever) },
    star: { title: '별표한 문제', desc: '문제 화면에서 별표를 눌러 모은 문제', ids: () => ORDER.filter(id => REC.star[id]) },
  };

  // ── 첫 화면 ───────────────────────────────────────────────
  function renderHome() {
    const all = ORDER.length, ok = count(ORDER, 'o'), no = count(ORDER, 'x');
    const last = store.get(K.last, null);
    const lq = last && DATA.problems[last];
    app.innerHTML = `
      <header class="wrap hero">
        <p class="eyebrow">운영체제 중간고사 대비</p>
        <h1>교재 연습문제</h1>
        <p class="muted">1~6장 ${all}문제 · 정답과 해설은 강의 슬라이드 기준</p>
      </header>
      <main class="wrap stack">
        <section class="card summary">
          <div class="nums">
            <div><b>${ok + no}</b><span>푼 문제</span></div>
            <div><b class="ok">${ok}</b><span>맞음</span></div>
            <div><b class="no">${no}</b><span>틀림</span></div>
          </div>
          ${meter(ok, no, all)}
          <div class="row">
            ${lq ? `<a class="btn primary" href="#/q/${last}">${icon('player-play')}이어 풀기 <small>${lq.ch}장 ${lq.no}번</small></a>`
               : `<a class="btn primary" href="#/q/${ORDER[0]}">${icon('player-play')}1장부터 풀기</a>`}
            <a class="btn" href="#/mix">${icon('arrows-shuffle')}섞어 풀기</a>
          </div>
        </section>
        <section>
          <h2 class="sec">장별 문제</h2>
          <div class="chapters">${DATA.chapters.map(chapterCard).join('')}</div>
        </section>
        <section>
          <h2 class="sec">다시 보기</h2>
          <div class="links">${Object.keys(LISTS).map(listLink).join('')}</div>
        </section>
        <footer class="foot">
          <a href="#/settings">${icon('settings')}설정 · 기록 옮기기</a>
          <p>풀이 기록은 이 기기의 브라우저에만 저장됩니다.</p>
        </footer>
      </main>`;
  }
  function chapterCard(c) {
    const n = c.ids.length, ok = count(c.ids, 'o'), no = count(c.ids, 'x');
    return `<a class="card chapter" href="#/ch/${c.no}">
      <div class="top"><span class="name">${c.no}장 ${esc(c.title)}</span><span class="cnt">${ok + no} / ${n}</span></div>
      <div class="sub muted">${kinds(c)}</div>
      ${meter(ok, no, n)}
    </a>`;
  }
  function listLink(kind) {
    const L = LISTS[kind];
    return `<a class="link" href="#/list/${kind}"><span class="t">${L.title}</span><span class="n">${L.ids().length}</span>${icon('chevron-right')}</a>`;
  }

  // ── 장 화면 ───────────────────────────────────────────────
  function renderChapter(no) {
    const c = CH[no];
    const unsolved = c.ids.filter(id => !state(id));
    const wrong = c.ids.filter(id => state(id) === 'x');
    const started = unsolved.length < c.ids.length;
    const groups = [['mc', '객관식'], ['calc', '계산'], ['essay', '서술형']].filter(([t]) => c.counts[t]);
    app.innerHTML = `
      ${topbar('#/', `${no}장`, c.title)}
      <main class="wrap stack">
        <header>
          <h1 class="title">${no}장 ${esc(c.title)}</h1>
          <p class="muted" style="margin:4px 0 0">교재 ${esc(c.pages)} · ${kinds(c)}</p>
        </header>
        <div class="actions">
          <button class="btn primary" data-act="next">${icon('player-play')}${!started ? '풀기 시작' : unsolved.length ? '이어서 풀기' : '처음부터 보기'}</button>
          <button class="btn" data-act="fresh">${icon('refresh')}새로 풀기</button>
          <button class="btn" data-act="wrong" ${wrong.length ? '' : 'disabled'}>틀린 문제 ${wrong.length}</button>
          <button class="btn" data-act="shuffle">${icon('arrows-shuffle')}섞어서</button>
        </div>
        ${groups.map(([t, name]) => `
          <section>
            <h2 class="sec">${name}</h2>
            <div class="grid">${c.ids.filter(id => P(id).type === t).map(cell).join('')}</div>
          </section>`).join('')}
        <p class="legend"><span><i class="o"></i>맞음</span><span><i class="x"></i>틀림</span><span><i></i>안 풂</span></p>
        ${c.notes.length ? `<details class="notes"><summary>교재 표기 메모 ${c.notes.length}개</summary><ul>${c.notes.map(n => `<li>${n}</li>`).join('')}</ul></details>` : ''}
      </main>`;
    const back = `#/ch/${no}`;
    $$('[data-act]').forEach(b => b.addEventListener('click', () => {
      const act = b.dataset.act;
      if (act === 'next') startSession(`${no}장 전체`, c.ids, back, { at: unsolved[0] || c.ids[0] });
      if (act === 'fresh') startSession(`${no}장 새로 풀기`, c.ids, back, { fresh: true });
      if (act === 'wrong') startSession(`${no}장 틀린 문제`, wrong, back, { fresh: true });
      if (act === 'shuffle') startSession(`${no}장 섞어 풀기`, shuffle(c.ids.slice()), back, { fresh: true });
    }));
    $$('.cell').forEach(b => b.addEventListener('click', () => startSession(`${no}장 전체`, c.ids, back, { at: b.dataset.id })));
  }
  function cell(id) {
    const q = P(id), st = state(id), star = !!REC.star[id];
    const name = { o: '맞음', x: '틀림', '': '안 풂' }[st];
    return `<button class="cell ${st}" data-id="${id}" aria-label="${q.no}번 ${name}${star ? ', 별표' : ''}">${q.no}`
      + `${star ? `<span class="st">${icon('star-filled')}</span>` : ''}</button>`;
  }

  // ── 문제 화면 ─────────────────────────────────────────────
  function renderProblem(id) {
    const q = P(id), s = getSession(id);
    const i = s.ids.indexOf(id), n = s.ids.length;
    const starred = !!REC.star[id];
    store.set(K.last, id);
    app.innerHTML = `
      <div class="bar"><div class="wrap">
        <a class="icon-btn" href="${s.back}" aria-label="목록으로">${icon('arrow-left')}</a>
        <div class="where"><b>${q.ch}장 ${q.no}번</b><span>${esc(s.label)} · ${i + 1} / ${n}</span></div>
        <button class="icon-btn star${starred ? ' on' : ''}" data-star aria-pressed="${starred}" aria-label="별표">${icon(starred ? 'star-filled' : 'star')}</button>
      </div><div class="progress"><i style="width:${pct(i + 1, n)}%"></i></div></div>
      <main class="wrap prob">
        <div class="tags"><span class="tag">${TYPE_NAME[q.type]}</span><span class="tag">교재 ${esc(q.page)}</span>${q.adv ? '<span class="tag adv">심화</span>' : ''}</div>
        <div class="q">${q.q}</div>
        <div id="body"></div>
      </main>
      <nav class="nav"><div class="wrap">
        <button class="btn" data-prev ${i > 0 ? '' : 'disabled'}>${icon('chevron-left')}이전</button>
        <button class="btn primary" data-next>${i < n - 1 ? '다음' : '결과 보기'}${icon('chevron-right')}</button>
      </div></nav>`;
    on('[data-star]', e => {
      const btn = e.currentTarget;
      if (REC.star[id]) delete REC.star[id]; else REC.star[id] = 1;
      saveRec();
      const isOn = !!REC.star[id];
      btn.classList.toggle('on', isOn);
      btn.setAttribute('aria-pressed', String(isOn));
      btn.innerHTML = icon(isOn ? 'star-filled' : 'star');
    });
    on('[data-prev]', () => { if (i > 0) go(`#/q/${s.ids[i - 1]}`, true); });
    on('[data-next]', () => go(i < n - 1 ? `#/q/${s.ids[i + 1]}` : '#/done', true));
    const body = $('#body'), r = shownRes(s, id);
    if (q.type === 'mc') mcView(id, body, r);
    else if (q.type === 'calc') calcView(id, body, r);
    else essayView(id, body, r);
  }

  const resultBar = (ok, right) => `<div class="result ${ok ? 'ok' : 'no'}" role="status">`
    + `${icon(ok ? 'circle-check' : 'circle-x')}${ok ? '맞았습니다' : '틀렸습니다'}${right ? `<span class="ans">${right}</span>` : ''}</div>`;
  const retryBtn = () => `<div class="after-actions"><button class="btn ghost" data-retry>${icon('refresh')}다시 풀기</button></div>`;
  function bindRetry(id) {
    on('[data-retry]', () => { clearResult(id); renderProblem(id); window.scrollTo(0, 0); });
  }
  function extras(q) {
    let h = '';
    if (q.dispute) h += q.dispute.map(d => `<div class="callout">${icon('alert-triangle')}<div><b>이견 가능</b><p>${d}</p></div></div>`).join('');
    if (q.notes) h += `<div class="callout">${icon('info-circle')}<div><b>교재 표기 메모</b>${q.notes.map(x => `<p>${x}</p>`).join('')}</div></div>`;
    return h;
  }
  function revealResult() {
    const res = $('.result');
    if (res && res.getBoundingClientRect().bottom > window.innerHeight - 90) res.scrollIntoView({ block: 'center' });
  }

  // 객관식
  function mcView(id, el, r) {
    const q = P(id);
    el.innerHTML = `
      <div class="choices" role="group" aria-label="보기">
        ${q.choices.map((c, k) => `<button class="choice" data-k="${k + 1}"><span class="num">${k + 1}</span><span class="txt">${c}</span></button>`).join('')}
      </div>
      <div id="after"></div>`;
    if (r && r.pick) showMc(id, r.pick[0]);
    $$('.choice', el).forEach(b => b.addEventListener('click', () => {
      if (b.classList.contains('locked')) return;
      const k = +b.dataset.k;
      setResult(id, q.ans.includes(k) ? 'o' : 'x', { pick: [k] });
      showMc(id, k);
      revealResult();
    }));
  }
  function showMc(id, k) {
    const q = P(id), ok = q.ans.includes(k);
    $$('.choice').forEach(b => {
      const n = +b.dataset.k, right = q.ans.includes(n);
      b.classList.add('locked');
      b.setAttribute('aria-disabled', 'true');
      b.classList.toggle('correct', right);
      b.classList.toggle('wrong', n === k && !right);
      b.classList.toggle('dim', !right && n !== k);
    });
    $('#after').innerHTML = `
      ${resultBar(ok, `정답 ${q.ans.map(a => CIRC[a]).join(', ')}`)}
      <section class="answer">
        <h3>정답</h3>
        ${q.ans.map(a => `<p class="pick">${CIRC[a]} ${q.choices[a - 1]}</p>`).join('')}
        <h3>해설</h3>
        <p>${q.exp}</p>
        ${extras(q)}
      </section>
      ${retryBtn()}`;
    bindRetry(id);
  }

  // 계산 (평균 대기 시간)
  const near = (v, key) => Math.abs(parseFloat(String(v).replace(',', '.')) - key) < 0.01;
  function calcView(id, el, r) {
    const q = P(id), vals = (r && r.vals) || [];
    el.innerHTML = `
      <form class="subs" id="calc" novalidate>
        <p class="hint muted">각 알고리즘의 평균 대기 시간을 적고 채점하세요.</p>
        ${q.subs.map((s, k) => `
          <div class="sub">
            <label for="v${k}">(${k + 1}) ${esc(s)}</label>
            <input id="v${k}" inputmode="decimal" autocomplete="off" enterkeyhint="${k < q.subs.length - 1 ? 'next' : 'done'}" value="${esc(vals[k] == null ? '' : vals[k])}">
            <span class="unit">ms</span>
          </div>`).join('')}
        <div class="row" id="calcBtns">
          <button class="btn primary" type="submit">${icon('check')}채점하기</button>
          <button class="btn" type="button" data-peek>${icon('eye')}풀이만 보기</button>
        </div>
      </form>
      <div id="after"></div>`;
    if (r) { showCalc(id, vals); return; }
    $('#calc').addEventListener('submit', e => {
      e.preventDefault();
      const v = q.subs.map((_, k) => $(`#v${k}`).value.trim());
      setResult(id, v.every((x, k) => near(x, q.keys[k])) ? 'o' : 'x', { vals: v });
      showCalc(id, v);
      revealResult();
    });
    on('[data-peek]', () => {
      $('#after').innerHTML = `<section class="answer"><h3>풀이</h3>${q.intro || ''}${q.model}${extras(q)}</section>`;
    });
  }
  function showCalc(id, vals) {
    const q = P(id);
    let all = true;
    $$('.sub').forEach((row, k) => {
      const good = near(vals[k], q.keys[k]);
      all = all && good;
      row.classList.add(good ? 'ok' : 'no');
      $('input', row).readOnly = true;
      if (!good) $('label', row).insertAdjacentHTML('beforeend', `<span class="key">정답 ${q.keys[k]}ms</span>`);
    });
    const btns = $('#calcBtns');
    if (btns) btns.remove();
    $('#after').innerHTML = `${resultBar(all, '')}
      <section class="answer"><h3>풀이</h3>${q.intro || ''}${q.model}${extras(q)}</section>
      ${retryBtn()}`;
    bindRetry(id);
  }

  // 서술형
  function essayView(id, el, r) {
    el.innerHTML = `
      <label class="draft-label" for="draft">내 답안 <span class="muted">(선택 · 이 기기에 저장)</span></label>
      <textarea id="draft" placeholder="떠오르는 대로 적어 본 뒤 모범 답안과 비교해 보세요.">${esc(REC.draft[id] || '')}</textarea>
      <div id="after"></div>`;
    $('#draft').addEventListener('input', e => {
      if (e.target.value.trim()) REC.draft[id] = e.target.value; else delete REC.draft[id];
      saveRec();
    });
    if (r) { showModel(id, r); return; }
    $('#after').innerHTML = `<button class="btn primary block" data-reveal>${icon('eye')}모범 답안 보기</button>`;
    on('[data-reveal]', () => { delete REC.check[id]; saveRec(); showModel(id, null); });
  }
  function showModel(id, r) {
    const q = P(id), checks = REC.check[id] || [];
    $('#after').innerHTML = `
      <section class="answer">
        <h3>모범 답안</h3>
        ${q.model}
        <h3>채점 요소 <span class="muted">· 내 답에 들어간 것에 체크</span></h3>
        <ul class="rubric">${q.rubric.map((x, k) => `<li><label><input type="checkbox" data-c="${k}"${checks[k] ? ' checked' : ''}><span>${x}</span></label></li>`).join('')}</ul>
        ${extras(q)}
      </section>
      <div class="grade">
        <p class="muted">스스로 채점하기</p>
        <div class="row">
          <button class="btn${r && r.r === 'o' ? ' on-ok' : ''}" data-self="o">${icon('circle-check')}맞음</button>
          <button class="btn${r && r.r === 'x' ? ' on-no' : ''}" data-self="x">${icon('circle-x')}틀림</button>
        </div>
      </div>
      ${r ? retryBtn() : ''}`;
    $$('[data-c]').forEach(cb => cb.addEventListener('change', () => {
      const arr = REC.check[id] || [];
      arr[+cb.dataset.c] = cb.checked;
      REC.check[id] = arr;
      saveRec();
    }));
    $$('[data-self]').forEach(b => b.addEventListener('click', () => {
      setResult(id, b.dataset.self, {});
      $$('[data-self]').forEach(x => x.classList.remove('on-ok', 'on-no'));
      b.classList.add(b.dataset.self === 'o' ? 'on-ok' : 'on-no');
    }));
    bindRetry(id);
  }

  // ── 세션 결과 ─────────────────────────────────────────────
  function renderDone() {
    const s = store.get(K.session, null);
    if (!s || !Array.isArray(s.ids) || !s.ids.every(id => DATA.problems[id])) { renderHome(); return; }
    const st = id => { const r = shownRes(s, id); return r ? r.r : ''; };
    const ok = s.ids.filter(id => st(id) === 'o').length;
    const wrong = s.ids.filter(id => st(id) === 'x');
    const rest = s.ids.length - ok - wrong.length;
    app.innerHTML = `
      ${topbar(s.back, '결과', s.label)}
      <main class="wrap stack">
        <section class="card summary">
          <div class="nums">
            <div><b class="ok">${ok}</b><span>맞음</span></div>
            <div><b class="no">${wrong.length}</b><span>틀림</span></div>
            <div><b>${rest}</b><span>안 풂</span></div>
          </div>
          ${meter(ok, wrong.length, s.ids.length)}
        </section>
        <div class="stack0">
          ${wrong.length ? `<button class="btn primary block" data-redo>${icon('refresh')}틀린 ${wrong.length}문제 다시 풀기</button>` : ''}
          <a class="btn block" href="${s.back}">목록으로</a>
        </div>
        ${wrong.length ? `<section><h2 class="sec">틀린 문제</h2><ul class="qlist">${wrong.map(qItem).join('')}</ul></section>` : ''}
      </main>`;
    on('[data-redo]', () => startSession(`${s.label} · 틀린 문제`, wrong, s.back, { fresh: true }));
    bindItems(wrong, `${s.label} · 틀린 문제`, s.back);
  }

  // ── 다시 보기 목록 ─────────────────────────────────────────
  function renderList(kind) {
    const L = LISTS[kind], ids = L.ids(), back = `#/list/${kind}`;
    app.innerHTML = `
      ${topbar('#/', L.title)}
      <main class="wrap stack">
        <p class="muted" style="margin:0">${L.desc} · ${ids.length}문제</p>
        ${ids.length ? `<button class="btn primary block" data-run>${icon('refresh')}${ids.length}문제 다시 풀기</button>` : ''}
        <ul class="qlist">${ids.map(qItem).join('') || '<li class="empty">아직 없습니다.</li>'}</ul>
      </main>`;
    on('[data-run]', () => startSession(L.title, ids, back, { fresh: true }));
    bindItems(ids, L.title, back);
  }

  // ── 섞어 풀기 ─────────────────────────────────────────────
  function renderMix() {
    const pref = Object.assign({ chs: DATA.chapters.map(c => c.no), types: ['mc', 'essay'], scope: 'all', count: 20 },
      store.get(K.mix, {}));
    const pool = () => ORDER.filter(id => {
      const q = P(id);
      if (!pref.chs.includes(q.ch)) return false;
      if (!pref.types.includes(q.type === 'mc' ? 'mc' : 'essay')) return false;
      if (pref.scope === 'unsolved') return !state(id);
      if (pref.scope === 'wrong') return !!(REC.res[id] && REC.res[id].ever);
      return true;
    });
    const chip = (g, v, label, isOn) => `<button class="chip" data-g="${g}" data-v="${v}" aria-pressed="${isOn}">${label}</button>`;
    const render = () => {
      const all = pool();
      const take = pref.count ? Math.min(pref.count, all.length) : all.length;
      app.innerHTML = `
        ${topbar('#/', '섞어 풀기')}
        <main class="wrap stack">
          <section><h2 class="sec">장</h2><div class="chips">${DATA.chapters.map(c => chip('ch', c.no, `${c.no}장`, pref.chs.includes(c.no))).join('')}</div></section>
          <section><h2 class="sec">문제 종류</h2><div class="chips">${chip('type', 'mc', '객관식', pref.types.includes('mc'))}${chip('type', 'essay', '서술형·계산', pref.types.includes('essay'))}</div></section>
          <section><h2 class="sec">범위</h2><div class="chips">${[['all', '전체'], ['unsolved', '안 푼 문제'], ['wrong', '틀린 적 있는 문제']].map(([v, l]) => chip('scope', v, l, pref.scope === v)).join('')}</div></section>
          <section><h2 class="sec">개수</h2><div class="chips">${[10, 20, 30, 0].map(v => chip('count', v, v ? `${v}문제` : '전부', pref.count === v)).join('')}</div></section>
          <p class="muted" style="margin:0">조건에 맞는 ${all.length}문제 가운데 ${take}문제를 섞어서 풉니다.</p>
          <button class="btn primary block" data-go ${take ? '' : 'disabled'}>${icon('arrows-shuffle')}시작</button>
        </main>`;
      $$('.chip').forEach(b => b.addEventListener('click', () => {
        const g = b.dataset.g, v = b.dataset.v;
        if (g === 'ch') { const c = +v; pref.chs = pref.chs.includes(c) ? pref.chs.filter(x => x !== c) : pref.chs.concat(c).sort((a, z) => a - z); }
        if (g === 'type') pref.types = pref.types.includes(v) ? pref.types.filter(x => x !== v) : pref.types.concat(v);
        if (g === 'scope') pref.scope = v;
        if (g === 'count') pref.count = +v;
        store.set(K.mix, pref);
        render();
      }));
      on('[data-go]', () => {
        const ids = shuffle(pool()).slice(0, take);
        startSession(`섞어 풀기 ${ids.length}문제`, ids, '#/mix', { fresh: true });
      });
    };
    render();
  }

  // ── 설정 ──────────────────────────────────────────────────
  function renderSettings() {
    const theme = store.get(K.theme, 'auto');
    app.innerHTML = `
      ${topbar('#/', '설정')}
      <main class="wrap stack">
        <section class="card">
          <h2 class="sec">화면</h2>
          <div class="chips">${[['auto', '기기 설정 따름'], ['light', '밝게'], ['dark', '어둡게']].map(([v, l]) => `<button class="chip" data-theme="${v}" aria-pressed="${theme === v}">${l}</button>`).join('')}</div>
        </section>
        <section class="card">
          <h2 class="sec">기록 옮기기</h2>
          <p class="muted">휴대폰과 노트북의 기록은 따로 저장됩니다. 한쪽에서 기록 코드를 복사해 다른 쪽에 붙여 넣으면 두 기록이 합쳐집니다.</p>
          <div class="row"><button class="btn" data-export>${icon('copy')}기록 코드 복사</button></div>
          <textarea id="io" placeholder="다른 기기에서 복사한 기록 코드를 여기에 붙여 넣기" spellcheck="false" autocomplete="off"></textarea>
          <div class="row"><button class="btn" data-import>${icon('download')}붙여 넣은 기록 합치기</button></div>
          <p class="muted small" id="ioMsg" role="status" style="margin:8px 0 0"></p>
        </section>
        <section class="card">
          <h2 class="sec">기록 지우기</h2>
          <p class="muted">맞음·틀림, 별표, 서술형 답안을 모두 지웁니다.</p>
          <button class="btn danger" data-reset>${icon('trash')}모든 기록 지우기</button>
        </section>
        <section class="card">
          <h2 class="sec">잠금</h2>
          <p class="muted">이 기기에 기억한 비밀번호를 지웁니다. 풀이 기록은 남습니다.</p>
          <button class="btn" data-lock>${icon('lock')}이 기기에서 잠그기</button>
        </section>
        <p class="muted small" style="margin:0">문제 데이터 ${esc(DATA.built)} · 아이콘 Tabler Icons(MIT) · 글꼴 Pretendard(OFL)</p>
      </main>`;
    $$('[data-theme]').forEach(b => b.addEventListener('click', () => {
      store.set(K.theme, b.dataset.theme);
      applyTheme();
      renderSettings();
    }));
    const msg = t => { $('#ioMsg').textContent = t; };
    on('[data-export]', async () => {
      const code = 'OSQ1:' + toB64(new TextEncoder().encode(JSON.stringify(REC)));
      const box = $('#io');
      try {
        await navigator.clipboard.writeText(code);
        msg('기록 코드를 복사했습니다. 다른 기기의 이 화면에 붙여 넣으세요.');
      } catch (e) {
        box.value = code;
        box.select();
        msg('자동 복사가 막혀 있어 아래 칸에 코드를 넣었습니다. 길게 눌러 복사하세요.');
      }
    });
    on('[data-import]', () => {
      const raw = $('#io').value.replace(/\s+/g, '');
      try {
        if (!raw.startsWith('OSQ1:')) throw new Error('형식');
        const other = JSON.parse(new TextDecoder().decode(b64(raw.slice(5))));
        const n = merge(other);
        $('#io').value = '';
        msg(`기록을 합쳤습니다. 새로 들어온 풀이 ${n}개.`);
      } catch (e) {
        msg('기록 코드를 읽지 못했습니다. 처음부터 끝까지 그대로 붙여 넣었는지 확인하세요.');
      }
    });
    on('[data-reset]', () => {
      if (!window.confirm('모든 풀이 기록과 별표, 서술형 답안을 지울까요? 되돌릴 수 없습니다.')) return;
      REC = { res: {}, star: {}, draft: {}, check: {} };
      saveRec();
      store.del(K.last);
      store.del(K.session);
      msg('');
      go('#/');
    });
    on('[data-lock]', () => {
      store.del(K.key);
      DATA = null;
      history.replaceState(null, '', '#/');
      renderLock();
    });
  }
  function merge(o) {
    let n = 0;
    Object.entries(o.res || {}).forEach(([id, r]) => {
      if (!DATA.problems[id] || !r || typeof r !== 'object') return;
      const mine = REC.res[id];
      if (r.r && (!mine || !mine.r || (r.t || 0) > (mine.t || 0))) {
        REC.res[id] = Object.assign({}, r, { ever: !!(r.ever || (mine && mine.ever)) });
        n++;
      } else if (mine && r.ever) mine.ever = true;
      else if (!mine) REC.res[id] = r;
    });
    Object.keys(o.star || {}).forEach(id => { if (DATA.problems[id]) REC.star[id] = 1; });
    Object.entries(o.draft || {}).forEach(([id, t]) => { if (DATA.problems[id] && typeof t === 'string' && !REC.draft[id]) REC.draft[id] = t; });
    Object.entries(o.check || {}).forEach(([id, c]) => { if (DATA.problems[id] && Array.isArray(c) && !REC.check[id]) REC.check[id] = c; });
    saveRec();
    return n;
  }

  // ── 화면 색 ───────────────────────────────────────────────
  const metaColors = Array.from(document.querySelectorAll('meta[name="theme-color"]')).map(m => [m, m.content]);
  function applyTheme() {
    const t = store.get(K.theme, 'auto');
    const root = document.documentElement;
    if (t === 'light' || t === 'dark') root.setAttribute('data-theme', t); else root.removeAttribute('data-theme');
    metaColors.forEach(([m, orig]) => { m.content = t === 'light' ? '#f4f5f7' : t === 'dark' ? '#121418' : orig; });
  }

  // ── 잠금 화면과 시작 ──────────────────────────────────────
  function renderLock(note) {
    app.innerHTML = `
      <main class="lock">
        <form class="box" id="unlock">
          <div class="lock-ic">${icon('lock')}</div>
          <h1>운영체제 교재 연습문제</h1>
          <p class="muted">교재 문제 원문이 들어 있어 비밀번호로 잠가 두었습니다.</p>
          <label class="field">비밀번호<input type="password" id="pw" autocomplete="current-password" required></label>
          <label class="check"><input type="checkbox" id="remember" checked>이 기기에서 기억하기</label>
          <button class="btn primary block" id="go">열기</button>
          <p class="err" id="err" role="alert">${note ? esc(note) : ''}</p>
        </form>
      </main>`;
    const pw = $('#pw');
    $('#unlock').addEventListener('submit', async e => {
      e.preventDefault();
      if (!pw.value) return;
      const btn = $('#go'), err = $('#err');
      btn.disabled = true;
      btn.textContent = '여는 중…';
      err.textContent = '';
      try {
        const raw = await deriveRaw(pw.value);
        DATA = await openData(raw);
        if ($('#remember').checked) store.set(K.key, toB64(raw));
        ready();
      } catch (x) {
        btn.disabled = false;
        btn.textContent = '열기';
        err.textContent = '비밀번호가 맞지 않습니다.';
        pw.select();
      }
    });
  }
  function ready() {
    CH = {};
    ORDER = [];
    DATA.chapters.forEach(c => { CH[c.no] = c; ORDER.push(...c.ids); });
    loadRec();
    route();
  }

  // 노트북: 1~4로 보기 고르기, ←·→로 이전·다음
  document.addEventListener('keydown', e => {
    if (!DATA || e.altKey || e.ctrlKey || e.metaKey || !/^#\/q\//.test(location.hash)) return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (/^[1-4]$/.test(e.key)) {
      const b = $(`.choice[data-k="${e.key}"]`);
      if (b) { e.preventDefault(); b.click(); }
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      $('[data-next]').click();
    } else if (e.key === 'ArrowLeft') {
      const b = $('[data-prev]');
      if (b && !b.disabled) { e.preventDefault(); b.click(); }
    }
  });

  async function start() {
    applyTheme();
    if (!ENC) { app.innerHTML = '<p class="wrap" style="padding:40px 16px">문제 데이터를 불러오지 못했습니다. 새로고침해 보세요.</p>'; return; }
    if (!(window.crypto && crypto.subtle)) { renderLock('이 브라우저에서는 열 수 없습니다. https 주소로 열어 주세요.'); return; }
    const saved = store.get(K.key, null);
    if (saved) {
      try { DATA = await openData(b64(saved)); } catch (e) { store.del(K.key); }
    }
    if (DATA) ready(); else renderLock();
  }
  start();
})();
