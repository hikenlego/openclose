import streamlit as st
import pandas as pd
import datetime
import calendar
import os
import urllib.request

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


st.title("근무 일정 자동 생성 프로그램")

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

if st.button("1단계: 날짜 설정 및 완벽한 초기 스케줄 시뮬레이션"):
    calendar.setfirstweekday(calendar.SUNDAY)
    cal = calendar.monthcalendar(target_year, target_month)
    business_days = []

    for week in cal:
        for i, day in enumerate(week):
            if day != 0 and i in [1, 2, 3, 4, 5]:
                date_obj = datetime.date(target_year, target_month, day)
                day_name = ["일", "월", "화", "수", "목", "금", "토"][i]
                business_days.append({"date": date_obj, "day_name": day_name, "day_num": day})

    st.session_state.business_days = business_days

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
                    if rules["weekly"] or rules["balance"]:
                        if week_slack is None:
                            week_note = " (주별 상한·오픈/마감 균등 상한은 모두 완화되어 적용되지 못했습니다)"
                        else:
                            week_note = f" (주별 상한·오픈/마감 균등: 기준 비율 +{week_slack}회 이내)"
                    else:
                        week_note = ""
                    st.success("지정한 쿼터에 100% 오차 없이 완벽히 일치하도록 스케줄이 생성되었습니다!" + week_note)

if "schedule_results" in st.session_state:
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

    st.header("5. 월간 캘린더 출력 및 이미지 다운로드")

    calendar.setfirstweekday(calendar.SUNDAY)
    month_matrix = calendar.monthcalendar(target_year, target_month)

    sched_dict = {item["일"]: {"오픈": item["오픈"], "마감": item["마감"]} for item in st.session_state.schedule_results}

    if HAS_MATPLOTLIB:
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.axis('off')

        col_labels = ["일", "월", "화", "수", "목", "금", "토"]
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

        table = ax.table(cellText=cell_text, colLabels=col_labels, loc='center', cellLoc='center')
        table.scale(1, 3)

        plt.title(f"{target_year}년 {target_month}월 근무 일정표", fontsize=16, pad=20)

        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight")
        buf.seek(0)

        st.pyplot(fig)

        st.download_button(
            label="달력 이미지 다운로드",
            data=buf,
            file_name=f"{target_year}_{target_month}_schedule.png",
            mime="image/png"
        )
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
