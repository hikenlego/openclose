import streamlit as st
import pandas as pd
import datetime
import calendar
import os
import urllib.request
import re as _re

try:
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    import io
    HAS_MATPLOTLIB = True

    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        try:
            url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
            urllib.request.urlretrieve(url, font_path)
        except Exception:
            pass

    if os.path.exists(font_path):
        fm.fontManager.addfont(font_path)
        font_name = fm.FontProperties(fname=font_path).get_name()
        plt.rc('font', family=font_name)
    else:
        plt.rc('font', family='sans-serif')

    plt.rcParams['axes.unicode_minus'] = False
except ImportError:
    HAS_MATPLOTLIB = False


def solve_quota_matching(slots, avail, quotas):
    """슬롯을 인원별 정확 쿼터에 맞춰 배정 (증가 경로 방식).
    slots : 시간순 슬롯 키 리스트
    avail : {슬롯: [가용 인원]}
    quotas: {인원: 맡아야 할 정확한 횟수}
    반환  : (owner, fail) / 성공 시 fail=None
    실패 시 fail = {"slot": 실패 슬롯, "visited": 병목 인원 집합, "stuck_slots": 병목 슬롯 리스트}
    """
    assigned = {s: [] for s in quotas}
    owner = {}

    def try_assign(slot, visited):
        cands = [s for s in avail[slot] if s in quotas]
        free = [s for s in cands if len(assigned[s]) < quotas[s]]
        if free:
            s = min(free, key=lambda x: len(assigned[x]))
            assigned[s].append(slot)
            owner[slot] = s
            return True
        for s in cands:
            if s in visited:
                continue
            visited.add(s)
            for other in list(assigned[s]):
                if try_assign(other, visited):
                    assigned[s].remove(other)
                    assigned[s].append(slot)
                    owner[slot] = s
                    return True
        return False

    for slot in slots:
        visited = set()
        if not try_assign(slot, visited):
            stuck = [slot] + [x for s in visited for x in assigned[s]]
            return owner, {"slot": slot, "visited": visited, "stuck_slots": stuck}
    return owner, None


class SearchLimit(Exception):
    pass


def get_week_idx(d):
    """달력(일요일 시작) 기준 주차 인덱스"""
    offset = (d.replace(day=1).weekday() + 1) % 7
    return (d.day - 1 + offset) // 7


def build_conflicts(slots, slot_date, rules):
    """같은 사람이 동시에 맡을 수 없는 슬롯 쌍 구성 (선택된 규칙만 반영)"""
    conflicts = {s: set() for s in slots}
    slot_set = set(slots)

    def add(a, b):
        if a in slot_set and b in slot_set:
            conflicts[a].add(b)
            conflicts[b].add(a)

    for (idx, kind) in slots:
        if rules.get("same_day") and kind == "오픈":
            add((idx, "오픈"), (idx, "마감"))
        nxt = idx + 1
        if nxt in slot_date and (slot_date[nxt] - slot_date[idx]).days == 1:
            if rules.get("close_open") and kind == "마감":
                add((idx, "마감"), (nxt, "오픈"))
            if rules.get("consec_open") and kind == "오픈":
                add((idx, "오픈"), (nxt, "오픈"))
    return conflicts


def build_week_caps(slots, slot_week, quotas, slack):
    """주별 개인 상한 = ceil(쿼터 x 해당 주 슬롯 비율) + 여유분. slack=None이면 상한 없음"""
    if slack is None:
        return None
    total = len(slots)
    week_slots = {}
    for s in slots:
        week_slots[slot_week[s]] = week_slots.get(slot_week[s], 0) + 1
    return {(p, w): -(-quotas[p] * n // total) + slack for p in quotas for w, n in week_slots.items()}


def build_ratio_caps(slots, quotas, slack):
    """개인별 (오픈 상한, 마감 상한) = ceil(쿼터 x 전체 중 해당 슬롯 비율) + 여유분. slack=None이면 상한 없음"""
    if slack is None:
        return None
    total = len(slots)
    n_open = sum(1 for s in slots if s[1] == "오픈")
    n_close = total - n_open
    return {p: (-(-quotas[p] * n_open // total) + slack, -(-quotas[p] * n_close // total) + slack) for p in quotas}


def solve_with_rules(slots, avail, quotas, slot_week, conflicts, caps, ratio_caps, node_limit):
    """DFS + 가장 제약 큰 슬롯 우선 + 전방 검사. 반환 (owner, status) status: ok/infeasible/limit"""
    rem = dict(quotas)
    owner = {}
    wk = {p: {} for p in quotas}
    kc = {p: [0, 0] for p in quotas}
    unassigned = set(slots)
    order_index = {s: i for i, s in enumerate(slots)}
    nodes = [0]
    av = {s: list(dict.fromkeys(avail[s])) for s in slots}

    def cands(s):
        w = slot_week[s]
        res = []
        for p in av[s]:
            if p not in rem or rem[p] <= 0:
                continue
            if caps is not None and wk[p].get(w, 0) >= caps.get((p, w), 0):
                continue
            if ratio_caps is not None and kc[p][0 if s[1] == "오픈" else 1] >= ratio_caps[p][0 if s[1] == "오픈" else 1]:
                continue
            if any(owner.get(n) == p for n in conflicts[s]):
                continue
            res.append(p)
        return res

    def dfs():
        if not unassigned:
            return True
        nodes[0] += 1
        if nodes[0] > node_limit:
            raise SearchLimit()
        best, best_c = None, None
        cover = {p: 0 for p in rem}
        for s in unassigned:
            c = cands(s)
            if not c:
                return False
            for p in c:
                cover[p] += 1
            if best is None or len(c) < len(best_c) or (len(c) == len(best_c) and order_index[s] < order_index[best]):
                best, best_c = s, c
        for p in rem:
            if rem[p] > cover[p]:
                return False
        w = slot_week[best]
        ki = 0 if best[1] == "오픈" else 1
        best_c.sort(key=lambda p: (wk[p].get(w, 0), kc[p][ki], -rem[p], p))
        for p in best_c:
            owner[best] = p
            rem[p] -= 1
            wk[p][w] = wk[p].get(w, 0) + 1
            kc[p][ki] += 1
            unassigned.discard(best)
            if dfs():
                return True
            unassigned.add(best)
            kc[p][ki] -= 1
            wk[p][w] -= 1
            rem[p] += 1
            del owner[best]
        return False

    try:
        ok = dfs()
    except SearchLimit:
        return None, "limit"
    return (dict(owner), "ok") if ok else (None, "infeasible")


def solve_schedule(slots, avail, quotas, slot_week, slot_date, rules, node_limit=15000):
    """1) 주별/오픈·마감 상한 없이 가능한지 먼저 판정(불가능하면 즉시 종료)
    2) 가능하면 상한을 단계적으로 완화(0 -> +1 -> +2)하며 가장 균등한 해 탐색, 모두 실패하면 1)의 해 사용.
    반환 (owner, slack, week_caps, ratio_caps, status)"""
    conflicts = build_conflicts(slots, slot_date, rules)
    base_owner, status = solve_with_rules(slots, avail, quotas, slot_week, conflicts, None, None, node_limit)
    if base_owner is None:
        return None, None, None, None, status
    if rules.get("weekly") or rules.get("balance"):
        for slack in [0, 1, 2]:
            wcaps = build_week_caps(slots, slot_week, quotas, slack) if rules.get("weekly") else None
            rcaps = build_ratio_caps(slots, quotas, slack) if rules.get("balance") else None
            owner, _ = solve_with_rules(slots, avail, quotas, slot_week, conflicts, wcaps, rcaps, max(node_limit // 3, 1500))
            if owner is not None:
                return owner, slack, wcaps, rcaps, "ok"
    return base_owner, None, None, None, "ok"


def build_month_slots(business_days, open_input, close_input):
    """월 전체 슬롯/가용 인원/주차/날짜 구성 (월·수 마감은 김상혁 고정이라 제외)"""
    slots, avail, slot_week, slot_date = [], {}, {}, {}
    for idx, bday in enumerate(business_days):
        d_name, d_date = bday["day_name"], bday["date"]
        slot_date[idx] = d_date
        so = (idx, "오픈")
        slots.append(so)
        slot_week[so] = get_week_idx(d_date)
        avail[so] = [x for x in open_input.get(d_name, []) if x != "김상혁"]
        if d_name not in ["월", "수"]:
            sc = (idx, "마감")
            slots.append(sc)
            slot_week[sc] = get_week_idx(d_date)
            avail[sc] = [x for x in close_input.get(d_name, []) if x != "김상혁"]
    return slots, avail, slot_week, slot_date


def waterfill_quotas(prev, n):
    """최종 누적이 최대한 같아지도록 n개 슬롯을 배분. 반환 (기본 쿼터, 동점 그룹, 그룹에서 +1 받을 인원 수)"""
    q = {p: 0 for p in prev}
    remaining = n
    while remaining > 0:
        cur = {p: prev[p] + q[p] for p in prev}
        m = min(cur.values())
        group = sorted(p for p in prev if cur[p] == m)
        if remaining >= len(group):
            for p in group:
                q[p] += 1
            remaining -= len(group)
        else:
            return q, group, remaining
    return q, [], 0


def compute_initial_quotas(business_days, open_input, close_input, general_staff, staff_prev, rules):
    """1단계 슬라이더 초기값: 최종 누적 균등 기준 쿼터.
    1) 이전 누적이 많은 사람이 가장 적게 받음  2) 동점자 중 선택은 체크된 조건을 가장 잘 만족하는 쪽을 자동 선택
    3) 가용 인원 때문에 불가능하면 가장 가까운 가능한 쿼터로 조정. 반환 (쿼터 dict, 안내 문구 또는 None)"""
    import itertools
    slots, avail, slot_week, slot_date = build_month_slots(business_days, open_input, close_input)
    prev = {p: staff_prev.get(p, 0) for p in general_staff}
    base, tied, k = waterfill_quotas(prev, len(slots))

    cands = []
    if k > 0:
        order = sorted(tied, key=lambda p: (prev[p], p))
        v = prev[order[k - 1]]
        sure = [p for p in order if prev[p] < v]
        border = [p for p in order if prev[p] == v]
        need = k - len(sure)
        for comb in itertools.combinations(border, need):
            q = dict(base)
            for p in sure + list(comb):
                q[p] += 1
            cands.append(q)
    else:
        cands.append(dict(base))

    # 1) 체크된 조건을 가장 잘 만족하는 후보 선택
    best = None
    for q in cands:
        o, slack, _, _, _ = solve_schedule(slots, avail, q, slot_week, slot_date, rules, node_limit=4000)
        if o is not None:
            sl = 99 if slack is None else slack
            if best is None or sl < best[0]:
                best = (sl, q)
            if sl == 0:
                break
    if best:
        return best[1], None

    # 2) 조건 없이 가용 인원만 만족하는 후보
    for q in cands:
        o, f = solve_quota_matching(slots, avail, q)
        if f is None:
            labels = {"close_open": "마감 직후 오픈 피하기", "same_day": "같은 날 오픈·마감 중복 피하기",
                      "consec_open": "연일 오픈 피하기", "weekly": "주별 쏠림 방지", "balance": "오픈·마감 비중 균등"}
            hint = []
            for key, on in rules.items():
                if on:
                    trial = dict(rules)
                    trial[key] = False
                    o2, _, _, _, _ = solve_schedule(slots, avail, q, slot_week, slot_date, trial, node_limit=4000)
                    if o2 is not None:
                        hint.append(labels.get(key, key))
            msg = "체크된 배정 조건을 모두 만족하는 쿼터를 찾지 못해, 가용 인원만 만족하는 쿼터로 초기화했습니다."
            if hint:
                msg += " 다음 조건 중 하나를 해제하면 2단계에서 해가 나옵니다: " + ", ".join(hint) + "."
            else:
                msg += " 2단계에서 오류가 나면 조건을 일부 해제하세요."
            return q, msg

    # 3) 이상적 쿼터에서 가장 가까운 가능한 쿼터 탐색 (1명→1명 이동 최대 3번)
    ideal = cands[0]

    def spread(q):
        f = [prev[p] + q[p] for p in prev]
        return max(f) - min(f)

    frontier = [ideal]
    seen = {tuple(sorted(ideal.items()))}
    for depth in range(1, 4):
        nxt = []
        for q in frontier:
            for a in sorted(prev):
                if q[a] <= 0:
                    continue
                for b in sorted(prev):
                    if a == b:
                        continue
                    q2 = dict(q)
                    q2[a] -= 1
                    q2[b] += 1
                    key = tuple(sorted(q2.items()))
                    if key not in seen:
                        seen.add(key)
                        nxt.append(q2)
        nxt.sort(key=lambda q: (spread(q), tuple(sorted(q.items()))))
        for q2 in nxt[:400]:
            o, f = solve_quota_matching(slots, avail, q2)
            if f is None:
                diff = ", ".join(f"{p} {q2[p] - ideal[p]:+d}" for p in sorted(prev) if q2[p] != ideal[p])
                return q2, f"가용 인원 제약 때문에 누적 균등 쿼터에서 조정했습니다({diff})."
        frontier = nxt[:40]
    return ideal, "가용 인원 제약으로 균등 쿼터를 확정하지 못했습니다. 슬라이더를 직접 조절하세요."


def copy_button(text, label="클립보드에 복사"):
    """클릭 한 번으로 텍스트를 클립보드에 복사하는 버튼 (clipboard API, 막히면 execCommand로 대체)"""
    import json
    import streamlit.components.v1 as components
    payload = json.dumps(text).replace("</", "<\\/")
    components.html(
        """
<button id="cb" style="padding:0.45rem 1rem;border:1px solid #888;border-radius:0.5rem;background:transparent;color:inherit;cursor:pointer;font-size:14px;"></button>
<script>
const t = """ + payload + """;
const label = """ + json.dumps(label) + """;
const b = document.getElementById('cb');
b.textContent = label;
function fallbackCopy() {
  const a = document.createElement('textarea');
  a.value = t; document.body.appendChild(a); a.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) {}
  document.body.removeChild(a);
  return ok;
}
b.onclick = async () => {
  let ok = false;
  try { await navigator.clipboard.writeText(t); ok = true; } catch (e) { ok = fallbackCopy(); }
  b.textContent = ok ? '복사 완료!' : '복사 실패 - 위 텍스트 상자에서 직접 복사하세요';
  setTimeout(() => { b.textContent = label; }, 1800);
};
</script>
""",
        height=50,
    )


def copy_image_button(png_bytes, label="클립보드에 복사"):
    """PNG 이미지를 클릭 한 번으로 클립보드에 복사하는 버튼 (브라우저가 막으면 실패 안내)"""
    import base64
    import json
    import streamlit.components.v1 as components
    b64 = base64.b64encode(png_bytes).decode("ascii")
    components.html(
        """
<button id="cb" style="padding:0.45rem 1rem;border:1px solid #888;border-radius:0.5rem;background:transparent;color:inherit;cursor:pointer;font-size:14px;"></button>
<script>
const b64 = \"""" + b64 + """\";
const label = """ + json.dumps(label) + """;
const b = document.getElementById('cb');
b.textContent = label;
b.onclick = async () => {
  let ok = false;
  try {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    const blob = new Blob([arr], { type: 'image/png' });
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
    ok = true;
  } catch (e) { ok = false; }
  b.textContent = ok ? '복사 완료!' : '복사 실패 - 왼쪽 다운로드 버튼을 이용하세요';
  setTimeout(() => { b.textContent = label; }, 2200);
};
</script>
""",
        height=50,
    )


# ---------------- 공휴일 / 대체공휴일 기반 ----------------
FIXED_HOLIDAYS = [(1, 1, "신정"), (3, 1, "삼일절"), (5, 5, "어린이날"), (6, 6, "현충일"),
                  (8, 15, "광복절"), (10, 3, "개천절"), (10, 9, "한글날"), (12, 25, "성탄절")]

# 음력 기반 공휴일 (연도별 날짜는 직접 입력한 기본 데이터. 틀리면 화면의 '추가·수정 휴무일'에서 보정)
LUNAR_HOLIDAYS = {
    2024: {"설날": [(2, 9, "설 연휴"), (2, 10, "설날"), (2, 11, "설 연휴")], "부처님오신날": [(5, 15, "부처님오신날")],
           "추석": [(9, 16, "추석 연휴"), (9, 17, "추석"), (9, 18, "추석 연휴")]},
    2025: {"설날": [(1, 28, "설 연휴"), (1, 29, "설날"), (1, 30, "설 연휴")], "부처님오신날": [(5, 5, "부처님오신날")],
           "추석": [(10, 5, "추석 연휴"), (10, 6, "추석"), (10, 7, "추석 연휴")]},
    2026: {"설날": [(2, 16, "설 연휴"), (2, 17, "설날"), (2, 18, "설 연휴")], "부처님오신날": [(5, 24, "부처님오신날")],
           "추석": [(9, 24, "추석 연휴"), (9, 25, "추석"), (9, 26, "추석 연휴")]},
    2027: {"설날": [(2, 6, "설 연휴"), (2, 7, "설날"), (2, 8, "설 연휴")], "부처님오신날": [(5, 13, "부처님오신날")],
           "추석": [(9, 14, "추석 연휴"), (9, 15, "추석"), (9, 16, "추석 연휴")]},
    2028: {"설날": [(1, 26, "설 연휴"), (1, 27, "설날"), (1, 28, "설 연휴")], "부처님오신날": [(5, 2, "부처님오신날")],
           "추석": [(10, 2, "추석 연휴"), (10, 3, "추석"), (10, 4, "추석 연휴")]},
    2029: {"설날": [(2, 12, "설 연휴"), (2, 13, "설날"), (2, 14, "설 연휴")], "부처님오신날": [(5, 20, "부처님오신날")],
           "추석": [(9, 21, "추석 연휴"), (9, 22, "추석"), (9, 23, "추석 연휴")]},
    2030: {"설날": [(2, 2, "설 연휴"), (2, 3, "설날"), (2, 4, "설 연휴")], "부처님오신날": [(5, 9, "부처님오신날")],
           "추석": [(9, 11, "추석 연휴"), (9, 12, "추석"), (9, 13, "추석 연휴")]},
}

# 선거일·임시공휴일 등 (필요한 것만 기본 포함)
EXTRA_HOLIDAYS = {
    datetime.date(2024, 4, 10): "국회의원선거일",
    datetime.date(2024, 10, 1): "임시공휴일",
    datetime.date(2025, 1, 27): "임시공휴일",
    datetime.date(2025, 6, 3): "대통령선거일",
    datetime.date(2026, 6, 3): "전국동시지방선거일",
}


def get_holiday_map(year, extra_text=""):
    """{날짜: 표시 이름}. 고정 공휴일 + 음력 공휴일 + 대체공휴일 + 직접 입력.
    직접 입력: 한 줄에 'YYYY-MM-DD 이름' (추가/수정), 'YYYY-MM-DD' 앞에 '-'를 붙이면 해당 날짜 공휴일 해제"""
    td = datetime.timedelta
    hol = {}

    def add(d, n):
        hol.setdefault(d, []).append(n)

    units = []  # (종류, 날짜들, 이름)
    for m, d, n in FIXED_HOLIDAYS:
        dt = datetime.date(year, m, d)
        add(dt, n)
        if n == "어린이날":
            units.append(("kids", [dt], n))
        elif n in ("삼일절", "광복절", "개천절", "한글날", "성탄절"):
            units.append(("weekend", [dt], n))
    for name, days in LUNAR_HOLIDAYS.get(year, {}).items():
        dts = []
        for m, d, label in days:
            dt = datetime.date(year, m, d)
            add(dt, label)
            dts.append(dt)
        units.append(("group" if name in ("설날", "추석") else "weekend", dts, name))
    for dt, n in EXTRA_HOLIDAYS.items():
        if dt.year == year:
            add(dt, n)

    subs = {}

    def next_free(d):
        d += td(days=1)
        while d.weekday() >= 5 or d in hol or d in subs:
            d += td(days=1)
        return d

    for kind, dts, name in sorted(units, key=lambda u: u[1][0]):
        if kind == "group":
            need = any(d.weekday() == 6 for d in dts) or any(len(hol[d]) > 1 for d in dts)
        elif kind == "kids":
            need = dts[0].weekday() >= 5 or len(hol[dts[0]]) > 1
        else:
            need = dts[0].weekday() >= 5
        if need:
            subs[next_free(dts[-1])] = "대체공휴일"

    result = {d: "·".join(dict.fromkeys(ns)) for d, ns in hol.items()}
    result.update(subs)

    for line in (extra_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        remove = line.startswith("-")
        if remove:
            line = line[1:].strip()
        parts = line.split(None, 1)
        try:
            d = datetime.date.fromisoformat(parts[0])
        except Exception:
            continue
        if remove:
            result.pop(d, None)
        else:
            result[d] = parts[1].strip() if len(parts) > 1 else "휴무일"
    return result


APP_VERSION = "2026.10.30-r1"  # 배정 알고리즘을 바꾸면 이 값을 올려주세요 (이미지 하단에 표시됨)
FOOTER_COLS = [0.1, 1.9, 3.5, 5.1, 6.7, 8.3]


def quick_check(results, open_input, close_input, rules, staff_counts, quotas):
    """생성 직후 검증 요약 (가용 인원, 쿼터, 조건 위반 건수)"""
    avail_bad = []
    for r in results:
        d = r["요일"]
        tag = f"{r['날짜'].month}/{r['날짜'].day}"
        if r["오픈"] not in open_input.get(d, []):
            avail_bad.append(f"{tag} 오픈 {r['오픈']}")
        if d in ["월", "수"]:
            if r["마감"] != "김상혁":
                avail_bad.append(f"{tag} 마감 {r['마감']}")
        elif r["마감"] not in close_input.get(d, []):
            avail_bad.append(f"{tag} 마감 {r['마감']}")
    quota_bad = [p for p, q in quotas.items() if staff_counts[p]["open"] + staff_counts[p]["close"] != q]
    viol = {"close_open": 0, "same_day": 0, "consec_open": 0}
    for i, r in enumerate(results):
        if r["오픈"] == r["마감"]:
            viol["same_day"] += 1
        if i + 1 < len(results) and (results[i + 1]["날짜"] - r["날짜"]).days == 1:
            nx = results[i + 1]
            if r["마감"] == nx["오픈"]:
                viol["close_open"] += 1
            if r["오픈"] == nx["오픈"]:
                viol["consec_open"] += 1
    applied_viol = {k: v for k, v in viol.items() if rules.get(k) and v}
    return {"avail_bad": avail_bad, "quota_bad": quota_bad, "viol": viol, "applied_viol": applied_viol}


def build_footer_lines(gen, staff_counts):
    """이미지 하단에 넣을 생성 조건 문구. 반환: [(종류, 내용)] 종류 = h(제목) / t(문장) / rowh(표 머리) / row(표 행)"""
    import textwrap

    def wrap(text, width=88):
        return textwrap.wrap(text, width=width, subsequent_indent="   ") or [text]

    names = gen["rule_names"]
    lines = [("h", "생성 조건 (이 결과를 다시 만들거나 검증할 때의 기준)")]
    lines += [("t", t) for t in wrap(f"생성 일시 {gen['ts']} (KST) / 대상 {gen['year']}년 {gen['month']}월 / 프로그램 버전 {APP_VERSION}")]
    lines += [("t", t) for t in wrap("방식: 개인별 당월 쿼터를 정확히 맞추고 요일별 가용 인원 범위 안에서 배정 (월·수 마감은 김상혁 고정)")]

    on = [names[k] for k, v in gen["rules"].items() if v]
    off = [names[k] for k, v in gen["rules"].items() if not v]
    lines.append(("h", "배정 조건"))
    lines += [("t", t) for t in wrap("적용: " + (", ".join(on) if on else "없음"))]
    lines += [("t", t) for t in wrap("해제: " + (", ".join(off) if off else "없음"))]
    if gen["rules"].get("weekly") or gen["rules"].get("balance"):
        if gen["slack"] is None:
            lines.append(("t", "주별·오픈/마감 균등 상한: 해가 없어 완화되어 미적용"))
        else:
            lines.append(("t", f"주별·오픈/마감 균등 상한: 기준 비율 +{gen['slack']}회 이내로 충족"))

    lines.append(("h", "요일별 가용 인원 입력"))
    for label, key in [("오픈", "open_input"), ("마감", "close_input")]:
        txt = f"{label}: " + " / ".join(f"{d} {'·'.join(gen[key].get(d, [])) or '없음'}" for d in ["월", "화", "수", "목", "금"])
        lines += [("t", t) for t in wrap(txt)]

    lines.append(("h", "개인별 근무 횟수"))
    lines.append(("rowh", ["이름", "이전 누적", "당월 오픈", "당월 마감", "당월 합계", "최종 누적"]))
    for name in sorted(staff_counts):
        d = staff_counts[name]
        total = d["open"] + d["close"]
        lines.append(("row", [name, str(d["prev_total"]), str(d["open"]), str(d["close"]), str(total), str(d["prev_total"] + total)]))

    lines.append(("h", "공휴일 설정"))
    if not gen["exclude_holidays"]:
        hol_txt = "공휴일 제외: 사용 안 함"
    elif gen["holidays"]:
        hol_txt = "근무에서 제외한 공휴일: " + ", ".join(gen["holidays"])
    else:
        hol_txt = "공휴일 제외: 사용 (해당 월에 제외된 날 없음)"
    lines += [("t", t) for t in wrap(hol_txt)]
    extra = "; ".join(x.strip() for x in (gen["holiday_extra"] or "").splitlines() if x.strip())
    if extra:
        lines += [("t", t) for t in wrap("직접 입력한 휴무일 설정: " + extra)]

    chk = gen["check"]
    lines.append(("h", "생성 직후 검증 결과"))
    lines.append(("t", "가용 인원 일치: " + ("통과" if not chk["avail_bad"] else "불일치 " + ", ".join(chk["avail_bad"][:5]))))
    lines.append(("t", "개인별 쿼터 일치: " + ("통과" if not chk["quota_bad"] else "불일치 " + ", ".join(chk["quota_bad"]))))
    if chk["applied_viol"]:
        lines += [("t", t) for t in wrap("적용 조건 위반: " + ", ".join(f"{names[k]} {v}건" for k, v in chk["applied_viol"].items()))]
    else:
        lines.append(("t", "적용 조건 위반: 0건 (통과)"))
    released = [f"{names[k]} {v}건" for k, v in chk["viol"].items() if not gen["rules"].get(k) and v]
    if released:
        lines += [("t", t) for t in wrap("해제한 조건에서 발생한 건수(참고): " + ", ".join(released))]
    lines += [("t", t) for t in wrap("※ 같은 설정(가용 인원, 쿼터, 조건, 공휴일, 프로그램 버전)으로 다시 실행하면 동일한 결과가 만들어집니다.")]
    return lines


# ---------------- 스케줄 저장용 QR (이미지에 넣고, 이미지를 올리면 복원) ----------------
RULE_KEYS = ["close_open", "same_day", "consec_open", "weekly", "balance"]
RULE_NAMES = {"close_open": "마감 직후 오픈 피하기", "same_day": "같은 날 오픈·마감 중복 피하기",
              "consec_open": "연일 오픈 피하기", "weekly": "주별 쏠림 방지", "balance": "오픈·마감 비중 균등"}
WEEKDAYS5 = ["월", "화", "수", "목", "금"]


class _BitWriter:
    def __init__(self):
        self.v, self.n = 0, 0

    def put(self, val, bits):
        if not 0 <= val < (1 << bits):
            raise ValueError(f"값이 범위를 벗어났습니다({val}, {bits}비트)")
        self.v = (self.v << bits) | val
        self.n += bits

    def to_bytes(self):
        pad = (-self.n) % 8
        return (self.v << pad).to_bytes((self.n + pad) // 8, "big")


class _BitReader:
    def __init__(self, data):
        self.v, self.n, self.pos = int.from_bytes(data, "big"), len(data) * 8, 0

    def get(self, bits):
        if self.pos + bits > self.n:
            raise ValueError("QR 데이터가 짧습니다.")
        val = (self.v >> (self.n - self.pos - bits)) & ((1 << bits) - 1)
        self.pos += bits
        return val

    def prefix_bytes(self, pos):
        pad = (-pos) % 8
        return ((self.v >> (self.n - pos)) << pad).to_bytes((pos + pad) // 8, "big")


def encode_schedule_payload(gen, results, staff_counts):
    """생성 결과와 설정을 약 120바이트로 압축한 문자열 (QR용)"""
    import base64
    import re
    import zlib
    names = sorted(staff_counts)
    n = len(names)
    if n > 15:
        raise ValueError("인원이 너무 많습니다")
    idx_bits = max(1, (n - 1).bit_length())
    w = _BitWriter()
    w.put(1, 4)
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})-r(\d+)", APP_VERSION)
    yy, mm, dd, rev = (int(m.group(1)) - 2000, int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else (0, 0, 0, 0)
    w.put(yy, 7)
    w.put(mm, 4)
    w.put(dd, 5)
    w.put(rev, 6)
    ts = datetime.datetime.strptime(gen["ts"], "%Y-%m-%d %H:%M")
    w.put(int((ts - datetime.datetime(2020, 1, 1)).total_seconds() // 60), 26)
    w.put(gen["year"] - 2000, 7)
    w.put(gen["month"], 4)
    for k in RULE_KEYS:
        w.put(1 if gen["rules"].get(k) else 0, 1)
    w.put(1 if gen["exclude_holidays"] else 0, 1)
    w.put(3 if gen["slack"] is None else gen["slack"], 2)
    extra = (gen["holiday_extra"] or "").strip().encode("utf-8")
    w.put(len(extra), 8)
    for b in extra:
        w.put(b, 8)
    w.put(n, 4)
    for name in names:
        b = name.encode("utf-8")
        w.put(len(b), 6)
        for x in b:
            w.put(x, 8)
    for d in WEEKDAYS5:
        for key in ("open_input", "close_input"):
            lst = gen[key].get(d, [])
            for name in names:
                w.put(1 if name in lst else 0, 1)
    for name in names:
        w.put(min(255, staff_counts[name]["prev_total"]), 8)
    by_day = {r["일"]: r for r in results}
    mask = 0
    for day in by_day:
        mask |= 1 << (day - 1)
    w.put(mask, 31)
    for day in sorted(by_day):
        w.put(names.index(by_day[day]["오픈"]), idx_bits)
        w.put(names.index(by_day[day]["마감"]), idx_bits)
    w.put(zlib.crc32(w.to_bytes()) & 0xFFFF, 16)
    return "S1." + base64.urlsafe_b64encode(w.to_bytes()).decode().rstrip("=")


def decode_schedule_payload(text):
    import base64
    import zlib
    text = text.strip()
    if not text.startswith("S1."):
        raise ValueError("이 프로그램에서 만든 QR이 아닙니다.")
    b64 = text[3:]
    data = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
    r = _BitReader(data)
    if r.get(4) != 1:
        raise ValueError("지원하지 않는 QR 형식입니다.")
    yy, mm, dd, rev = r.get(7), r.get(4), r.get(5), r.get(6)
    app_version = f"{2000 + yy}.{mm:02d}.{dd:02d}-r{rev}"
    ts = (datetime.datetime(2020, 1, 1) + datetime.timedelta(minutes=r.get(26))).strftime("%Y-%m-%d %H:%M")
    year, month = 2000 + r.get(7), r.get(4)
    rules = {k: bool(r.get(1)) for k in RULE_KEYS}
    exclude = bool(r.get(1))
    sc = r.get(2)
    slack = None if sc == 3 else sc
    elen = r.get(8)
    extra = bytes(r.get(8) for _ in range(elen)).decode("utf-8")
    n = r.get(4)
    names = []
    for _ in range(n):
        ln = r.get(6)
        names.append(bytes(r.get(8) for _ in range(ln)).decode("utf-8"))
    avail = {"open_input": {}, "close_input": {}}
    for d in WEEKDAYS5:
        for key in ("open_input", "close_input"):
            lst = []
            for name in names:
                if r.get(1):
                    lst.append(name)
            avail[key][d] = lst
    prev = {name: r.get(8) for name in names}
    mask = r.get(31)
    idx_bits = max(1, (n - 1).bit_length())
    results = []
    for day in [i + 1 for i in range(31) if (mask >> i) & 1]:
        op = names[r.get(idx_bits)]
        cl = names[r.get(idx_bits)]
        results.append((day, op, cl))
    pos = r.pos
    if zlib.crc32(r.prefix_bytes(pos)) & 0xFFFF != r.get(16):
        raise ValueError("QR 데이터가 손상되었습니다(검증 실패).")
    return {"app_version": app_version, "ts": ts, "year": year, "month": month, "rules": rules,
            "exclude_holidays": exclude, "slack": slack, "holiday_extra": extra, "names": names,
            "open_input": avail["open_input"], "close_input": avail["close_input"], "prev": prev, "results": results}


def restore_schedule_state(d):
    """QR에서 읽은 데이터로 4~6번 섹션이 쓰는 세션 상태를 복원"""
    year, month = d["year"], d["month"]
    wnames = ["월", "화", "수", "목", "금", "토", "일"]
    results, business_days = [], []
    for day, op, cl in d["results"]:
        dt = datetime.date(year, month, day)
        dn = wnames[dt.weekday()]
        business_days.append({"date": dt, "day_name": dn, "day_num": day})
        results.append({"날짜": dt, "일": day, "요일": dn, "오픈": op, "마감": cl})
    staff_counts = {nm: {"open": 0, "close": 0, "prev_total": d["prev"][nm]} for nm in d["names"]}
    for r in results:
        staff_counts[r["오픈"]]["open"] += 1
        staff_counts[r["마감"]]["close"] += 1
    quotas = {nm: c["open"] + c["close"] for nm, c in staff_counts.items() if nm != "김상혁"}
    rules, slack = d["rules"], d["slack"]
    slots, _, slot_week, _ = build_month_slots(business_days, d["open_input"], d["close_input"])
    wcaps = build_week_caps(slots, slot_week, quotas, slack) if (rules["weekly"] and slack is not None) else None
    rcaps = build_ratio_caps(slots, quotas, slack) if (rules["balance"] and slack is not None) else None
    hm = get_holiday_map(year, d["holiday_extra"])
    gen = {
        "ts": d["ts"], "year": year, "month": month, "rules": dict(rules), "rule_names": dict(RULE_NAMES), "slack": slack,
        "open_input": d["open_input"], "close_input": d["close_input"],
        "holiday_extra": d["holiday_extra"], "exclude_holidays": d["exclude_holidays"],
        "holidays": [f"{x.month}/{x.day}({nm})" for x, nm in sorted(hm.items())
                     if x.year == year and x.month == month and x.weekday() < 5],
        "check": quick_check(results, d["open_input"], d["close_input"], rules, staff_counts, quotas),
    }
    ss = st.session_state
    for k in ["optimal_nov_quotas", "quota_note", "holiday_note"]:
        if k in ss:
            del ss[k]
    ss.business_days = business_days
    ss.staff_prev = dict(d["prev"])
    ss.schedule_results = results
    ss.staff_counts = staff_counts
    ss.applied_rules = rules
    ss.week_slack = slack
    ss.week_caps = wcaps
    ss.ratio_caps = rcaps
    ss.gen_quotas = quotas
    ss.gen_settings = gen


def make_qr_array(text):
    """OpenCV로 QR 생성 (오류 정정 M). 반환: 0/255 uint8 배열"""
    import cv2
    params = cv2.QRCodeEncoder_Params()
    params.correction_level = cv2.QRCodeEncoder_CORRECT_LEVEL_M
    params.mode = cv2.QRCodeEncoder_MODE_BYTE
    return cv2.QRCodeEncoder_create(params).encode(text)


def paste_qr(png_bytes, qr_arr, px, qr_h_in, dpi):
    """렌더링된 달력 PNG의 오른쪽 아래 칸에 QR을 정수 배율로 붙임 (모서리가 번지지 않게)"""
    import io as _io
    from PIL import Image
    base = Image.open(_io.BytesIO(png_bytes)).convert("RGB")
    n = qr_arr.shape[0]
    nearest = getattr(getattr(Image, "Resampling", Image), "NEAREST")
    qr_img = Image.fromarray(qr_arr).convert("RGB").resize((n * px, n * px), nearest)
    W, H = base.size
    x_left = W - int(0.35 * dpi) - n * px
    y_top = H - int(0.05 * dpi) - int(qr_h_in / 2 * dpi) - (n * px) // 2
    base.paste(qr_img, (x_left, y_top))
    out = _io.BytesIO()
    base.save(out, format="PNG", dpi=(dpi, dpi))
    return out.getvalue()


def decode_qr_from_image(data):
    """업로드된 이미지(PNG/JPG, 재압축·축소본 포함)에서 QR 문자열 추출"""
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("이미지를 읽을 수 없습니다.")
    h, w = img.shape
    crop = img[int(h * 0.55):, int(w * 0.45):]
    views = [img, crop,
             cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
             cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)]
    det = cv2.QRCodeDetector()
    for v in views:
        for variant in (v, cv2.adaptiveThreshold(v, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)):
            val, _, _ = det.detectAndDecode(variant)
            if val:
                return val
    raise ValueError("이미지에서 QR을 찾지 못했습니다. 원본에 가까운 이미지(전체 화면, 오른쪽 아래 QR 포함)를 올려주세요.")


st.title("근무 일정 자동 생성 프로그램")

with st.expander("저장한 스케줄 이미지 불러오기 (QR 인식)"):
    restore_file = st.file_uploader("이 프로그램이 만든 달력 이미지(PNG/JPG)를 올리면, 이미지 속 QR로 생성 당시 결과를 복원합니다",
                                    type=["png", "jpg", "jpeg"], key="restore_uploader")
    if restore_file is not None:
        _sig = (restore_file.name, restore_file.size)
        if st.session_state.get("restore_sig") != _sig:
            st.session_state.restore_sig = _sig
            try:
                _d = decode_schedule_payload(decode_qr_from_image(restore_file.getvalue()))
                restore_schedule_state(_d)
                _note = "" if _d["app_version"] == APP_VERSION else f" (현재 프로그램 버전 {APP_VERSION}과 다른 버전에서 만든 결과입니다)"
                st.session_state.restore_msg = ("ok", f"복원 완료: {_d['year']}년 {_d['month']}월 스케줄 (생성 {_d['ts']}, 프로그램 버전 {_d['app_version']}){_note}. 아래 4~6번 섹션에 표시됩니다.")
            except Exception as _e:
                st.session_state.restore_msg = ("err", f"불러오기 실패: {_e}")
    _msg = st.session_state.get("restore_msg")
    if _msg:
        (st.success if _msg[0] == "ok" else st.error)(_msg[1])

if "schedule_df" not in st.session_state:
    st.session_state.schedule_df = None

st.header("1. 엑셀 파일 업로드 및 가용 인원 설정")
uploaded_file = st.file_uploader("근무표 엑셀 파일을 업로드하세요", type=["xlsx", "xls"])

default_open = {
    "월": ["김범수", "정은성"],
    "화": ["박라영", "김동환", "허다인"],
    "수": ["김범수", "박라영", "김동환", "허다인"],
    "목": ["박라영", "이현준", "김동환"],
    "금": ["김범수", "박라영", "이현준"]
}

default_close = {
    "월": ["김상혁", "박라영", "허다인", "정은성", "김동환"],
    "화": ["박라영", "이현준", "허다인", "정은성"],
    "수": ["김범수", "김상혁", "김동환", "정은성"],
    "목": ["박라영", "이현준", "김동환", "정은성"],
    "금": ["박라영", "김범수"]
}

if uploaded_file is not None:
    try:
        df_excel = pd.read_excel(uploaded_file)
        st.write("업로드된 엑셀 파일 미리보기:")
        st.dataframe(df_excel.head())
        st.success("엑셀 파일을 성공적으로 읽어왔습니다.")
    except Exception as e:
        st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")

st.subheader("요일별 오픈 가용 인원")
open_input = {}
days = ["월", "화", "수", "목", "금"]
for day in days:
    default_str = ", ".join(default_open.get(day, []))
    val = st.text_input(f"오픈 - {day}요일", value=default_str, key=f"open_{day}")
    open_input[day] = [x.strip() for x in val.split(",") if x.strip()]

st.subheader("요일별 마감 가용 인원")
close_input = {}
for day in days:
    default_str = ", ".join(default_close.get(day, []))
    val = st.text_input(f"마감 - {day}요일", value=default_str, key=f"close_{day}")
    close_input[day] = [x.strip() for x in val.split(",") if x.strip()]

st.header("2. 이전 달 누적 횟수 입력 (월별 총계)")

staff_names = sorted(list(set([name for sub in open_input.values() for name in sub] + [name for sub in close_input.values() for name in sub])))
if "김상혁" not in staff_names:
    staff_names.append("김상혁")
staff_names = sorted(staff_names)

raw_data = {
    "김상혁": {"9월": 8, "10월": 16, "11월": None, "12월": None},
    "박라영": {"9월": 5, "10월": 10, "11월": None, "12월": None},
    "김동환": {"9월": 5, "10월": 10, "11월": None, "12월": None},
    "정은성": {"9월": 5, "10월": 10, "11월": None, "12월": None},
    "김범수": {"9월": 4, "10월": 10, "11월": None, "12월": None},
    "허다인": {"9월": 4, "10월": 10, "11월": None, "12월": None},
    "이현준": {"9월": 4, "10월": 11, "11월": None, "12월": None},
}

history_df = pd.DataFrame(raw_data).T
history_df = history_df[["9월", "10월", "11월", "12월"]]
history_df.index.name = "이름"

st.info("행은 직원 이름, 열은 월별(9~12월) 총계입니다. 11~12월은 비워둔 상태로 유지됩니다.")
edited_history = st.data_editor(history_df, key="history_editor")

st.header("3. 단계별 스케줄 설정 및 생성")

col1, col2 = st.columns(2)
with col1:
    target_year = st.number_input("연도", min_value=2024, max_value=2030, value=2026)
with col2:
    target_month = st.number_input("월", min_value=1, max_value=12, value=11)

with st.expander("공휴일 설정 (공휴일·대체공휴일 자동 반영)"):
    exclude_holidays = st.checkbox("공휴일·대체공휴일은 근무에서 제외", value=True, key="exclude_holidays")
    holiday_extra = st.text_area(
        "추가·수정 휴무일 (한 줄에 'YYYY-MM-DD 이름', 날짜 앞에 -를 붙이면 그 날짜의 공휴일을 해제)",
        value="", height=90, key="holiday_extra")

if st.button("1단계: 날짜 설정 및 완벽한 초기 스케줄 시뮬레이션"):
    calendar.setfirstweekday(calendar.SUNDAY)
    cal = calendar.monthcalendar(target_year, target_month)
    business_days = []
    holiday_map_now = get_holiday_map(target_year, holiday_extra)

    for week in cal:
        for i, day in enumerate(week):
            if day != 0 and i in [1, 2, 3, 4, 5]:
                date_obj = datetime.date(target_year, target_month, day)
                if exclude_holidays and date_obj in holiday_map_now:
                    continue
                day_name = ["일", "월", "화", "수", "목", "금", "토"][i]
                business_days.append({"date": date_obj, "day_name": day_name, "day_num": day})

    st.session_state.business_days = business_days
    excl = [f"{d.month}/{d.day}({n})" for d, n in sorted(holiday_map_now.items())
            if d.year == target_year and d.month == target_month and d.weekday() < 5]
    st.session_state.holiday_note = ("근무에서 제외된 공휴일: " + ", ".join(excl)) if (exclude_holidays and excl) else None

    staff_prev = {}
    for staff in staff_names:
        if staff in edited_history.index:
            val = edited_history.loc[staff, "10월"]
            staff_prev[staff] = int(val) if pd.notna(val) else 0
        else:
            staff_prev[staff] = 0

    st.session_state.staff_prev = staff_prev

    general_staff = [s for s in staff_names if s != "김상혁"]
    for staff in general_staff:
        if f"cumul_slider_{staff}" in st.session_state:
            del st.session_state[f"cumul_slider_{staff}"]
        if f"nov_slider_{staff}" in st.session_state:
            del st.session_state[f"nov_slider_{staff}"]

    if "schedule_results" in st.session_state:
        del st.session_state["schedule_results"]
    if "staff_counts" in st.session_state:
        del st.session_state["staff_counts"]

    quota_rules = {
        "close_open": st.session_state.get("rule_close_open", True),
        "same_day": st.session_state.get("rule_same_day", True),
        "consec_open": st.session_state.get("rule_consec_open", True),
        "weekly": st.session_state.get("rule_weekly", True),
        "balance": st.session_state.get("rule_balance", True),
    }
    optimal_nov_quotas, quota_note = compute_initial_quotas(business_days, open_input, close_input, general_staff, staff_prev, quota_rules)
    st.session_state.quota_note = quota_note

    st.session_state.optimal_nov_quotas = optimal_nov_quotas
    st.success("완벽하게 100% 성공하는 초기 모범 스케줄 시뮬레이션 및 슬라이더 초기화가 완료되었습니다!")
    st.rerun()

if "business_days" in st.session_state and "staff_prev" in st.session_state and "optimal_nov_quotas" in st.session_state:
    st.subheader("인원별 목표 횟수 후처리 조절 (슬라이더)")

    slider_mode = st.radio(
        "슬라이더 기준 방식을 선택하세요:",
        ["당월 총 횟수 기준", "최종 누적 횟수 기준"],
        horizontal=True
    )

    total_business_days = len(st.session_state.business_days)
    sanghyuk_closes = sum(1 for bday in st.session_state.business_days if bday["day_name"] in ["월", "수"])
    general_staff = [s for s in staff_names if s != "김상혁"]
    optimal_dict = st.session_state.optimal_nov_quotas

    total_open_slots = total_business_days
    total_general_close_slots = total_business_days - sanghyuk_closes
    required_nov = total_open_slots + total_general_close_slots

    st.info(f"총 영업일수: {total_business_days}일 (오픈 총 {total_open_slots}개, 일반 마감 총 {total_general_close_slots}개 | 총 배정 필요 횟수: {required_nov}회)")
    if st.session_state.get("quota_note"):
        st.info(st.session_state.quota_note)
    if st.session_state.get("holiday_note"):
        st.info(st.session_state.holiday_note)

    user_final_cumulatives = {}
    max_slider_limit = required_nov

    if slider_mode == "최종 누적 횟수 기준":
        current_nov_sum = 0
        temp_vals = {}
        slider_min = min(st.session_state.staff_prev.get(s, 0) for s in general_staff)
        for i, staff in enumerate(general_staff):
            prev = st.session_state.staff_prev.get(staff, 0)
            default_final = prev + optimal_dict.get(staff, 5)
            val = st.slider(f"{staff} (이전 누적: {prev}회)", min_value=slider_min, max_value=30, value=default_final, key=f"cumul_slider_{staff}")
            temp_vals[staff] = val
            current_nov_sum += (val - prev)

        for s in general_staff:
            user_final_cumulatives[s] = temp_vals[s]

        sk_prev = st.session_state.staff_prev.get("김상혁", 0)
        sk_final = sk_prev + sanghyuk_closes
        st.markdown(f"김상혁 (월/수 마감 전담): 이전 누적 {sk_prev}회 + 당월 마감 {sanghyuk_closes}회 = 최종 누적 {sk_final}회 (자동 고정)")
        user_final_cumulatives["김상혁"] = sk_final

        diff = current_nov_sum - required_nov
        if diff != 0:
            st.warning(f"현재 배정된 총 당월 횟수: {current_nov_sum}회 (목표치인 {required_nov}회와 차이: {diff:+d}회). 2단계를 실행하여 가용성 기반 추천 가이드를 확인하세요.")
        else:
            st.success("모든 인원의 당월 총합이 배치해야 할 슬롯 수와 완벽하게 일치합니다!")

    else:  # 당월 총 횟수 기준
        current_nov_sum = 0
        target_nov_quotas_temp = {}
        for i, staff in enumerate(general_staff):
            prev = st.session_state.staff_prev.get(staff, 0)
            default_nov = optimal_dict.get(staff, 5)
            val = st.slider(f"{staff} (당월 목표 횟수)", min_value=0, max_value=max_slider_limit, value=default_nov, key=f"nov_slider_{staff}")
            target_nov_quotas_temp[staff] = val
            current_nov_sum += val
            user_final_cumulatives[staff] = prev + val

        sk_prev = st.session_state.staff_prev.get("김상혁", 0)
        user_final_cumulatives["김상혁"] = sk_prev + sanghyuk_closes
        st.markdown(f"김상혁 (월/수 마감 전담): 당월 마감 {sanghyuk_closes}회 (자동 고정)")

        diff = current_nov_sum - required_nov
        if diff != 0:
            st.warning(f"현재 배정된 총 당월 횟수: {current_nov_sum}회 (목표치인 {required_nov}회와 차이: {diff:+d}회). 2단계를 실행하여 가용성 기반 추천 가이드를 확인하세요.")
        else:
            st.success("모든 인원의 당월 총합이 배치해야 할 슬롯 수와 완벽하게 일치합니다!")

    st.markdown("**배정 시 피할 조건** (체크하면 적용, 해가 없으면 해제해 보세요)")
    rule_close_open = st.checkbox("마감 직후 오픈 피하기", value=True, key="rule_close_open")
    rule_same_day = st.checkbox("같은 날 오픈·마감 중복 피하기", value=True, key="rule_same_day")
    rule_consec_open = st.checkbox("연일 오픈 피하기", value=True, key="rule_consec_open")
    rule_weekly = st.checkbox("주별 쏠림 방지", value=True, key="rule_weekly")
    rule_balance = st.checkbox("오픈·마감 비중 균등", value=True, key="rule_balance")

    if st.button("2단계: 최종 스케줄 생성하기"):
        business_days = st.session_state.business_days
        staff_prev = st.session_state.staff_prev

        def clear_results():
            if "schedule_results" in st.session_state:
                del st.session_state["schedule_results"]
            if "staff_counts" in st.session_state:
                del st.session_state["staff_counts"]

        target_nov_quotas = {staff: user_final_cumulatives[staff] - staff_prev.get(staff, 0) for staff in staff_names}
        quotas = {s: target_nov_quotas.get(s, 0) for s in general_staff}

        # 슬롯 구성 (월/수 마감은 김상혁 고정이라 매칭 대상에서 제외)
        slots, avail, slot_label, fixed_close = [], {}, {}, {}
        slot_week, slot_date = {}, {}
        for idx, bday in enumerate(business_days):
            d_name, d_date = bday["day_name"], bday["date"]
            day_label = f"{d_date.month}/{d_date.day}({d_name})"

            slot_date[idx] = d_date
            so = (idx, "오픈")
            slots.append(so)
            slot_week[so] = get_week_idx(d_date)
            avail[so] = [s for s in open_input.get(d_name, []) if s != "김상혁"]
            slot_label[so] = f"{day_label} 오픈"

            if d_name in ["월", "수"]:
                fixed_close[idx] = "김상혁"
            else:
                sc = (idx, "마감")
                slots.append(sc)
                slot_week[sc] = get_week_idx(d_date)
                avail[sc] = [s for s in close_input.get(d_name, []) if s != "김상혁"]
                slot_label[sc] = f"{day_label} 마감"

        neg_quota = [f"{k}({v:+d}회)" for k, v in quotas.items() if v < 0]
        quota_sum = sum(quotas.values())
        if neg_quota:
            clear_results()
            st.error(f"당월 횟수가 음수가 된 인원이 있습니다: {', '.join(neg_quota)}. 최종 누적 슬라이더를 이전 누적 이상으로 올려주세요. (이전 결과물 초기화됨)")
        elif quota_sum != len(slots):
            clear_results()
            st.error(
                f"쿼터 총합 불일치: 일반 인원 쿼터 합 {quota_sum}회 / 배정할 슬롯 {len(slots)}개 "
                f"(차이 {quota_sum - len(slots):+d}회). 슬라이더 합계를 슬롯 수에 맞춰주세요. "
                f"(이전 결과물 초기화됨)"
            )
        else:
            owner, fail = solve_quota_matching(slots, avail, quotas)

            if fail is not None:
                clear_results()
                f_slot = fail["slot"]
                f_label = slot_label[f_slot]
                visited = fail["visited"]
                stuck = fail["stuck_slots"]

                if not avail[f_slot]:
                    st.error(
                        f"스케줄 생성 중단 및 오류 발생!\n"
                        f"(이전에 생성되었던 결과물 및 통계는 모두 초기화되었습니다.)\n\n"
                        f"상세 원인:\n{f_label} 슬롯에 가용 인원이 한 명도 입력되어 있지 않습니다.\n"
                        f"해결 가이드: 위쪽 가용 인원 입력란에서 해당 요일/시간대에 인원을 추가하세요."
                    )
                else:
                    need = len(stuck)
                    cap = sum(quotas[s] for s in visited)
                    increase_candidates = sorted(visited)
                    decrease_candidates = [s for s in general_staff if s not in visited and quotas[s] > 0]
                    stuck_str = ", ".join(slot_label[x] for x in stuck)

                    st.error(
                        f"스케줄 생성 중단 및 오류 발생!\n"
                        f"(이전에 생성되었던 결과물 및 통계는 모두 초기화되었습니다.)\n\n"
                        f"상세 원인:\n{f_label} 슬롯 배정 실패. 다른 날짜 슬롯을 재배치하는 모든 경우를 시도했지만, "
                        f"현재 쿼터로는 해가 존재하지 않습니다.\n\n"
                        f"병목 진단:\n"
                        f"- 병목 슬롯 {need}개: {stuck_str}\n"
                        f"- 이 슬롯들을 맡을 수 있는 인원: {', '.join(increase_candidates)} "
                        f"(쿼터 합 {cap}회 < 필요 {need}회)\n\n"
                        f"해결 가이드:\n"
                        f"- [늘려야 할 추천 인원]: {', '.join(increase_candidates)} (합계 최소 +{need - cap}회)\n"
                        f"- [줄여야 할 추천 인원(여유 인원)]: {', '.join(decrease_candidates) if decrease_candidates else '없음'}\n"
                        f"- 총합을 유지하려면 늘린 만큼 여유 인원에서 줄이세요.\n"
                        f"- 위쪽 1단계 버튼을 다시 누르면 성공하는 초기 모범 쿼터로 슬라이더가 초기화됩니다."
                    )
            else:
                rules = {
                    "close_open": rule_close_open,
                    "same_day": rule_same_day,
                    "consec_open": rule_consec_open,
                    "weekly": rule_weekly,
                    "balance": rule_balance,
                }
                rule_names = {
                    "close_open": "마감 직후 오픈 피하기",
                    "same_day": "같은 날 오픈·마감 중복 피하기",
                    "consec_open": "연일 오픈 피하기",
                    "weekly": "주별 쏠림 방지",
                    "balance": "오픈·마감 비중 균등",
                }
                owner, week_slack, week_caps, ratio_caps, rstatus = solve_schedule(slots, avail, quotas, slot_week, slot_date, rules)

                if owner is None:
                    clear_results()
                    active = [k for k, v in rules.items() if v]
                    relax_ok = []
                    for k in active:
                        trial = dict(rules)
                        trial[k] = False
                        o2, _, _, _, st2 = solve_schedule(slots, avail, quotas, slot_week, slot_date, trial, node_limit=8000)
                        if o2 is not None:
                            relax_ok.append(rule_names[k])
                    if rstatus == "limit":
                        why = "탐색 한도 안에서 해를 찾지 못했습니다(조건이 너무 빡빡할 가능성이 큽니다)."
                    else:
                        why = "선택한 조건을 모두 만족하는 해가 존재하지 않습니다."
                    if relax_ok:
                        tip = "다음 중 하나만 해제해도 해가 나옵니다: " + ", ".join(relax_ok)
                    else:
                        tip = "한 개만 해제해서는 해가 나오지 않습니다. 2개 이상 해제하거나 슬라이더 쿼터를 조정하세요."
                    st.error(
                        f"스케줄 생성 중단! (이전 결과물 초기화됨)\n\n"
                        f"상세 원인: {why}\n"
                        f"적용 중인 조건: {', '.join(rule_names[k] for k in active) if active else '없음'}\n\n"
                        f"해결 가이드: {tip}"
                    )
                    st.stop()

                schedule_results = []
                staff_counts = {staff: {"open": 0, "close": 0, "prev_total": staff_prev.get(staff, 0)} for staff in staff_names}

                for idx, bday in enumerate(business_days):
                    selected_open = owner[(idx, "오픈")]
                    selected_close = fixed_close.get(idx) or owner[(idx, "마감")]
                    staff_counts[selected_open]["open"] += 1
                    staff_counts[selected_close]["close"] += 1
                    schedule_results.append({
                        "날짜": bday["date"],
                        "일": bday["day_num"],
                        "요일": bday["day_name"],
                        "오픈": selected_open,
                        "마감": selected_close
                    })

                mismatch = any(
                    staff_counts[s]["open"] + staff_counts[s]["close"] != t
                    for s, t in target_nov_quotas.items()
                )
                if mismatch:
                    clear_results()
                    st.error("오류: 지정한 목표 쿼터와 실제 생성된 횟수 간에 불일치가 감지되었습니다. (이전 결과물 초기화됨)")
                else:
                    st.session_state.schedule_results = schedule_results
                    st.session_state.staff_counts = staff_counts
                    st.session_state.applied_rules = rules
                    st.session_state.week_slack = week_slack
                    st.session_state.week_caps = week_caps
                    st.session_state.ratio_caps = ratio_caps
                    st.session_state.gen_quotas = dict(quotas)
                    _hm = get_holiday_map(target_year, holiday_extra)
                    st.session_state.gen_settings = {
                        "ts": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
                        "year": target_year, "month": target_month,
                        "rules": dict(rules), "rule_names": dict(rule_names), "slack": week_slack,
                        "open_input": {k: list(v) for k, v in open_input.items()},
                        "close_input": {k: list(v) for k, v in close_input.items()},
                        "holiday_extra": holiday_extra, "exclude_holidays": exclude_holidays,
                        "holidays": [f"{d.month}/{d.day}({n})" for d, n in sorted(_hm.items())
                                     if d.year == target_year and d.month == target_month and d.weekday() < 5],
                        "check": quick_check(schedule_results, open_input, close_input, rules, staff_counts, quotas),
                    }
                    if rules["weekly"] or rules["balance"]:
                        if week_slack is None:
                            week_note = " (주별 상한·오픈/마감 균등 상한은 모두 완화되어 적용되지 못했습니다)"
                        else:
                            week_note = f" (주별 상한·오픈/마감 균등: 기준 비율 +{week_slack}회 이내)"
                    else:
                        week_note = ""
                    st.success("지정한 쿼터에 100% 오차 없이 완벽히 일치하도록 스케줄이 생성되었습니다!" + week_note)

if "schedule_results" in st.session_state:
    gen = st.session_state.get("gen_settings")
    if gen:
        target_year, target_month = gen["year"], gen["month"]
        open_input, close_input = gen["open_input"], gen["close_input"]
        h_extra, h_excl = gen["holiday_extra"], gen["exclude_holidays"]
    else:
        h_extra, h_excl = st.session_state.get("holiday_extra", ""), st.session_state.get("exclude_holidays", True)

    st.header("4. 개인별 근무 횟수 통계 및 복사 양식")

    stats_rows = []
    copy_texts = []

    for staff, data in st.session_state.staff_counts.items():
        m_open = data["open"]
        m_close = data["close"]
        m_total = m_open + m_close

        prev_total = data.get("prev_total", 0)
        total_sum = prev_total + m_total

        stats_rows.append({
            "이름": staff,
            "당월 오픈": m_open,
            "당월 마감": m_close,
            "당월 합계": m_total,
            "누적횟수": total_sum
        })

        line_str = f"{staff} / 당월 오픈 {m_open} / 당월 마감 {m_close} / 당월 합계 {m_total} / 누적횟수 {total_sum}"
        copy_texts.append(line_str)

    stats_df = pd.DataFrame(stats_rows)
    st.dataframe(stats_df)

    st.subheader("복사 텍스트 양식")
    full_copy_text = "\n".join(copy_texts)
    st.text_area("아래 내용을 복사하여 사용하세요", value=full_copy_text, height=150)
    copy_button(full_copy_text, "집계표 복사하기")

    st.header("5. 월간 캘린더 출력 및 이미지 다운로드")
    show_footer = st.checkbox("이미지 하단에 생성 조건 문구도 함께 표시 (QR에는 항상 저장됩니다)", value=False, key="show_footer")

    calendar.setfirstweekday(calendar.SUNDAY)
    month_matrix = calendar.monthcalendar(target_year, target_month)

    sched_dict = {item["일"]: {"오픈": item["오픈"], "마감": item["마감"]} for item in st.session_state.schedule_results}

    if HAS_MATPLOTLIB:
        cell_text = []

        for week in month_matrix:
            row_str = []
            for day in week:
                if day == 0:
                    row_str.append("")
                else:
                    info = sched_dict.get(day, None)
                    if info:
                        text_val = f"{day}일\n오픈: {info['오픈']}\n마감: {info['마감']}"
                    else:
                        text_val = f"{day}일\n(휴무)"
                    row_str.append(text_val)
            cell_text.append(row_str)

        # --- 구글 시트 스타일 달력 이미지 (위에서 만든 cell_text를 그대로 읽어서 그림) ---
        def _short(name):
            return name

        RED, BLUE, GRID = "#d93025", "#3f51d9", "#d4d4d4"
        n_rows = len(month_matrix)
        fig_w, title_h, head_h, row_h = 10.0, 0.55, 0.45, 1.35
        footer = build_footer_lines(gen, st.session_state.staff_counts) if (gen and show_footer) else []
        footer_h = (0.25 + sum(0.36 if k == "h" else 0.23 for k, _ in footer)) if footer else 0.0

        qr_arr, qr_note = None, None
        if gen:
            try:
                qr_arr = make_qr_array(encode_schedule_payload(gen, st.session_state.schedule_results, st.session_state.staff_counts))
            except Exception as _qe:
                qr_note = f"QR을 만들지 못해 이미지에 넣지 못했습니다 ({_qe}). requirements.txt에 opencv-python-headless가 있는지 확인하세요."
        QR_PX = 4
        qr_h = (qr_arr.shape[0] * QR_PX / 150 + 0.5) if qr_arr is not None else 0.0
        bottom_h = footer_h + qr_h
        fig_h = title_h + head_h + n_rows * row_h + bottom_h
        cw = fig_w / 7

        fig = plt.figure(figsize=(fig_w + 0.2, fig_h + 0.13), facecolor="white")
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(-0.1, fig_w + 0.1)
        ax.set_ylim(-0.05, fig_h + 0.08)
        ax.axis("off")

        ax.text(0.08, fig_h - title_h / 2, f"{target_year}년 {target_month}월 근무표 (오픈 / 마감)",
                fontsize=15, fontweight="bold", va="center", ha="left")

        head_top = fig_h - title_h
        head_bottom = head_top - head_h
        for c, lab in enumerate(["일 SUN", "월 MON", "화 TUE", "수 WED", "목 THU", "금 FRI", "토 SAT"]):
            ax.text(c * cw + cw / 2, head_top - head_h / 2, lab, ha="center", va="center",
                    fontsize=12, fontweight="bold", color=RED if c == 0 else BLUE if c == 6 else "black")

        for y in [head_top, head_bottom] + [head_bottom - (r + 1) * row_h for r in range(n_rows)]:
            ax.plot([0, fig_w], [y, y], color=GRID, lw=1.0, solid_capstyle="butt")
        for k in range(8):
            ax.plot([k * cw, k * cw], [bottom_h, head_top], color=GRID, lw=1.0, solid_capstyle="butt")

        holiday_map = get_holiday_map(target_year, h_extra)

        for r, row in enumerate(month_matrix):
            y_top = head_bottom - r * row_h
            for c, day in enumerate(row):
                if day == 0:
                    continue
                x0 = c * cw
                hol_name = holiday_map.get(datetime.date(target_year, target_month, day))
                num_color = RED if (c == 0 or hol_name) else BLUE if c == 6 else "black"
                ax.text(x0 + 0.1, y_top - 0.1, str(day), ha="left", va="top", fontsize=12, color=num_color)
                mt = _re.match(r"(\d+)일\n오픈: (.+)\n마감: (.+)", cell_text[r][c])
                if mt:
                    ax.text(x0 + 0.1, y_top - row_h * 0.46, f"{_short(mt.group(2).strip())} / {_short(mt.group(3).strip())}",
                            ha="left", va="center", fontsize=11.5, color="black")
                if hol_name:
                    ax.text(x0 + 0.1, y_top - row_h * (0.66 if mt else 0.46), f"({hol_name})",
                            ha="left", va="center", fontsize=12, color=RED)

        if footer:
            cursor = bottom_h - 0.1
            for kind, payload in footer:
                if kind == "h":
                    ax.text(0.1, cursor - 0.12, payload, ha="left", va="top", fontsize=11.5, fontweight="bold", color="#111111")
                    cursor -= 0.36
                elif kind == "t":
                    ax.text(0.1, cursor, payload, ha="left", va="top", fontsize=10, color="#333333")
                    cursor -= 0.23
                else:
                    for xi, cell in zip(FOOTER_COLS, payload):
                        ax.text(xi, cursor, cell, ha="left", va="top", fontsize=10, color="#333333",
                                fontweight="bold" if kind == "rowh" else "normal")
                    cursor -= 0.23

        if qr_arr is not None:
            ax.text(0.1, qr_h / 2, "스케줄 복원용 QR (프로그램의 '이미지 불러오기'에서 사용)", ha="left", va="center", fontsize=9, color="#999999")

        raw = io.BytesIO()
        fig.savefig(raw, format="png", dpi=150, facecolor="white")
        plt.close(fig)
        final_png = raw.getvalue()
        if qr_arr is not None:
            final_png = paste_qr(final_png, qr_arr, QR_PX, qr_h, 150)
        buf = io.BytesIO(final_png)

        st.image(final_png)
        if qr_note:
            st.warning(qr_note)

        dl_col, cp_col = st.columns(2)
        with dl_col:
            st.download_button(
                label="달력 이미지 다운로드",
                data=buf,
                file_name=f"{target_year}_{target_month}_schedule.png",
                mime="image/png"
            )
        with cp_col:
            copy_image_button(buf.getvalue(), "이미지 클립보드에 복사")
    else:
        st.warning("matplotlib 라이브러리가 없어 표 형태로 대체합니다.")
        sched_df = pd.DataFrame(st.session_state.schedule_results)
        st.dataframe(sched_df)

    st.header("6. 교차 검증 (캘린더 ↔ 가용 인원)")

    # 화면에 출력된 캘린더 셀 텍스트를 그대로 다시 읽어서 검증 (matplotlib 없으면 동일 형식으로 재구성)
    if HAS_MATPLOTLIB:
        verify_cells = cell_text
    else:
        verify_cells = []
        for week in month_matrix:
            row_str = []
            for day in week:
                info = sched_dict.get(day)
                if day == 0:
                    row_str.append("")
                elif info:
                    row_str.append(f"{day}일\n오픈: {info['오픈']}\n마감: {info['마감']}")
                else:
                    row_str.append(f"{day}일\n(휴무)")
            verify_cells.append(row_str)

    import re
    weekday_names = ["일", "월", "화", "수", "목", "금", "토"]
    parsed = {}
    for w_idx, row in enumerate(verify_cells):
        for c_idx, txt in enumerate(row):
            mt = re.match(r"(\d+)일\n오픈: (.+)\n마감: (.+)", txt)
            if mt:
                parsed[int(mt.group(1))] = {"주": w_idx, "요일": weekday_names[c_idx], "오픈": mt.group(2).strip(), "마감": mt.group(3).strip()}

    expected_days = {b["day_num"]: b["day_name"] for b in st.session_state.business_days}
    v_rows = []

    for dnum in sorted(expected_days):
        d_name = expected_days[dnum]
        info = parsed.get(dnum)
        if info is None:
            v_rows.append({"날짜": f"{target_month}/{dnum}({d_name})", "요일일치": "X", "오픈 가용": "X", "마감 가용": "X", "비고": "캘린더에 근무 없음"})
            continue
        day_ok = info["요일"] == d_name
        open_ok = info["오픈"] in open_input.get(d_name, [])
        if d_name in ["월", "수"]:
            close_ok = info["마감"] == "김상혁"
            close_note = "김상혁 고정 확인"
        else:
            close_ok = info["마감"] in close_input.get(d_name, [])
            close_note = ""
        notes = []
        if not day_ok:
            notes.append(f"요일 불일치(캘린더 {info['요일']})")
        if not open_ok:
            notes.append(f"오픈 {info['오픈']} 가용 목록에 없음")
        if not close_ok:
            notes.append(f"마감 {info['마감']} " + ("김상혁 고정 위반" if d_name in ["월", "수"] else "가용 목록에 없음"))
        v_rows.append({
            "날짜": f"{target_month}/{dnum}({d_name})",
            "요일일치": "O" if day_ok else "X",
            "오픈 가용": "O" if open_ok else "X",
            "마감 가용": "O" if close_ok else "X",
            "비고": ", ".join(notes) if notes else close_note
        })

    extra_days = [d for d in parsed if d not in expected_days]
    avail_pass = all(r["요일일치"] == "O" and r["오픈 가용"] == "O" and r["마감 가용"] == "O" for r in v_rows) and not extra_days

    # 캘린더 기준 횟수 vs 통계표 횟수 vs 쿼터
    cal_counts = {}
    for dnum, info in parsed.items():
        cal_counts.setdefault(info["오픈"], {"open": 0, "close": 0})["open"] += 1
        cal_counts.setdefault(info["마감"], {"open": 0, "close": 0})["close"] += 1
    count_problems = []
    for staff, data in st.session_state.staff_counts.items():
        c = cal_counts.get(staff, {"open": 0, "close": 0})
        if c["open"] != data["open"] or c["close"] != data["close"]:
            count_problems.append(f"{staff}: 캘린더 오픈 {c['open']}/마감 {c['close']} vs 통계 오픈 {data['open']}/마감 {data['close']}")
        gq = st.session_state.get("gen_quotas", {}).get(staff)
        if gq is not None and (data["open"] + data["close"]) != gq:
            count_problems.append(f"{staff}: 당월 합계 {data['open'] + data['close']}회 vs 쿼터 {gq}회")
    count_pass = not count_problems

    # 규칙 검증 (적용 여부와 무관하게 위반 건수 집계)
    applied = st.session_state.get("applied_rules", {})
    ordered = sorted(parsed)
    same_day_v, close_open_v, consec_open_v = [], [], []
    for dnum in ordered:
        if parsed[dnum]["오픈"] == parsed[dnum]["마감"]:
            same_day_v.append(f"{target_month}/{dnum} {parsed[dnum]['오픈']}")
    date_of = {b["day_num"]: b["date"] for b in st.session_state.business_days}
    for a, b in zip(ordered, ordered[1:]):
        if (date_of[b] - date_of[a]).days != 1:
            continue
        if parsed[a]["마감"] == parsed[b]["오픈"]:
            close_open_v.append(f"{target_month}/{a}마감 -> {target_month}/{b}오픈 {parsed[a]['마감']}")
        if parsed[a]["오픈"] == parsed[b]["오픈"]:
            consec_open_v.append(f"{target_month}/{a}-{b} 연일 오픈 {parsed[a]['오픈']}")

    # 주별 분포
    week_labels = sorted({i["주"] for i in parsed.values()})
    week_table = {}
    for dnum, info in parsed.items():
        for person in (info["오픈"], info["마감"]):
            week_table.setdefault(person, {w: 0 for w in week_labels})[info["주"]] += 1
    week_rows = []
    for person in sorted(week_table):
        row = {"이름": person}
        for w in week_labels:
            row[f"{w + 1}주차"] = week_table[person][w]
        row["최대"] = max(week_table[person].values())
        week_rows.append(row)

    ratio_caps = st.session_state.get("ratio_caps")
    balance_problems = []
    if applied.get("balance") and ratio_caps:
        for person, (oc, cc) in ratio_caps.items():
            c = cal_counts.get(person, {"open": 0, "close": 0})
            if c["open"] > oc:
                balance_problems.append(f"{person} 오픈 {c['open']}회 > 상한 {oc}회")
            if c["close"] > cc:
                balance_problems.append(f"{person} 마감 {c['close']}회 > 상한 {cc}회")
    one_sided = [f"{p} 오픈 {c['open']}/마감 {c['close']}" for p, c in sorted(cal_counts.items()) if p != "김상혁" and (c["open"] == 0 or c["close"] == 0)]

    caps = st.session_state.get("week_caps")
    cap_problems = []
    if applied.get("weekly") and caps:
        for person, wk in week_table.items():
            for w, n in wk.items():
                limit = caps.get((person, w))
                if limit is not None and n > limit:
                    cap_problems.append(f"{person} {w + 1}주차 {n}회 > 상한 {limit}회")

    # 결과 요약
    summary = []
    summary.append(("가용 인원 일치 (요일·오픈·마감)", avail_pass, "전 일자 일치" if avail_pass else "불일치 있음, 아래 표 확인"))
    summary.append(("캘린더 ↔ 통계표 ↔ 쿼터 횟수 일치", count_pass, "일치" if count_pass else " / ".join(count_problems)))
    for key, label, viol in [("close_open", "마감 직후 오픈", close_open_v), ("same_day", "같은 날 오픈·마감 중복", same_day_v), ("consec_open", "연일 오픈", consec_open_v)]:
        if applied.get(key):
            summary.append((f"{label} 없음 (적용 중)", not viol, "위반 없음" if not viol else "; ".join(viol)))
        else:
            summary.append((f"{label} (해제됨, 참고)", True, "발생 0건" if not viol else f"{len(viol)}건 발생: " + "; ".join(viol)))
    if applied.get("weekly"):
        summary.append(("주별 상한 이내 (적용 중)", not cap_problems, "상한 이내" if not cap_problems else "; ".join(cap_problems)))
    else:
        summary.append(("주별 쏠림 방지 (해제됨, 참고)", True, "아래 주별 분포표 참고"))

    if applied.get("balance"):
        summary.append(("오픈·마감 비중 균등 (적용 중)", not balance_problems, "개인별 상한 이내" if not balance_problems else "; ".join(balance_problems)))
    else:
        summary.append(("오픈·마감 비중 균등 (해제됨, 참고)", True, "한쪽만 근무한 인원 없음" if not one_sided else "한쪽만 근무: " + "; ".join(one_sided)))

    hol_v = get_holiday_map(target_year, h_extra)
    hol_sched = [f"{target_month}/{d}({hol_v[datetime.date(target_year, target_month, d)]})" for d in sorted(parsed)
                 if datetime.date(target_year, target_month, d) in hol_v]
    if h_excl:
        summary.append(("공휴일·대체공휴일 근무 배정 없음 (적용 중)", not hol_sched, "배정 없음" if not hol_sched else "; ".join(hol_sched)))
    else:
        summary.append(("공휴일 근무 배정 (제외 해제됨, 참고)", True, "해당 없음" if not hol_sched else "배정됨: " + "; ".join(hol_sched)))

    all_pass = all(ok for _, ok, _ in summary)
    if all_pass:
        st.success("교차 검증 결과: 모든 항목 일치")
    else:
        st.error("교차 검증 결과: 불일치 항목이 있습니다")

    summary_df = pd.DataFrame([{"검증 항목": n, "결과": "일치" if ok else "불일치", "상세": d} for n, ok, d in summary])
    st.dataframe(summary_df, hide_index=True)

    st.subheader("일자별 가용 인원 대조")
    st.dataframe(pd.DataFrame(v_rows), hide_index=True)

    st.subheader("개인별 주차 분포")
    st.dataframe(pd.DataFrame(week_rows), hide_index=True)

    verify_text = "\n".join(f"{n}: {'일치' if ok else '불일치'} ({d})" for n, ok, d in summary)
    st.text_area("검증 결과 복사용 텍스트", value=verify_text, height=150)
    copy_button(verify_text, "검증 결과 복사하기")
