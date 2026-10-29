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

    sanghyuk_closes = sum(1 for bday in business_days if bday["day_name"] in ["월", "수"])
    sim_staff_counts = {s: {"open": 0, "close": 0} for s in staff_names}
    
    for bday in business_days:
        d_name = bday["day_name"]
        
        avail_open = [s for s in open_input.get(d_name, []) if s != "김상혁"]
        if not avail_open:
            avail_open = general_staff
        avail_open.sort(key=lambda x: sim_staff_counts[x]["open"] + sim_staff_counts[x]["close"])
        sel_o = avail_open[0]
        sim_staff_counts[sel_o]["open"] += 1
        
        if d_name in ["월", "수"]:
            sim_staff_counts["김상혁"]["close"] += 1
        else:
            avail_close = [s for s in close_input.get(d_name, []) if s != "김상혁"]
            if not avail_close:
                avail_close = general_staff
            avail_close.sort(key=lambda x: sim_staff_counts[x]["open"] + sim_staff_counts[x]["close"])
            sel_c = avail_close[0]
            sim_staff_counts[sel_c]["close"] += 1

    optimal_nov_quotas = {}
    for s in general_staff:
        optimal_nov_quotas[s] = sim_staff_counts[s]["open"] + sim_staff_counts[s]["close"]

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
    
    user_final_cumulatives = {}
    max_slider_limit = required_nov
    
    if slider_mode == "최종 누적 횟수 기준":
        current_nov_sum = 0
        temp_vals = {}
        for i, staff in enumerate(general_staff):
            prev = st.session_state.staff_prev.get(staff, 0)
            default_final = prev + optimal_dict.get(staff, 5)
            val = st.slider(f"{staff} (이전 누적: {prev}회)", min_value=prev, max_value=prev + max_slider_limit, value=default_final, key=f"cumul_slider_{staff}")
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
        for idx, bday in enumerate(business_days):
            d_name, d_date = bday["day_name"], bday["date"]
            day_label = f"{d_date.month}/{d_date.day}({d_name})"

            so = (idx, "오픈")
            slots.append(so)
            avail[so] = [s for s in open_input.get(d_name, []) if s != "김상혁"]
            slot_label[so] = f"{day_label} 오픈"

            if d_name in ["월", "수"]:
                fixed_close[idx] = "김상혁"
            else:
                sc = (idx, "마감")
                slots.append(sc)
                avail[sc] = [s for s in close_input.get(d_name, []) if s != "김상혁"]
                slot_label[sc] = f"{day_label} 마감"

        quota_sum = sum(quotas.values())
        if quota_sum != len(slots):
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
                    st.success("지정한 쿼터에 100% 오차 없이 완벽히 일치하도록 스케줄이 생성되었습니다!")
                del st.session_state["schedule_results"]
            if "staff_counts" in st.session_state:
                del st.session_state["staff_counts"]

            avail_close_staff = close_input.get(fail_day_name, [])
            status_details = []
            for s in avail_close_staff:
                if s == "김상혁" and fail_day_name in ["월", "수"]:
                    continue
                current_done = staff_counts[s]["open"] + staff_counts[s]["close"]
                target_q = target_nov_quotas.get(s, 0)
                status_details.append(f"- {s}: 현재 {current_done}회 / 목표 쿼터 {target_q}회")
            
            status_str = "\n".join(status_details) if status_details else "- 가용 인원 없음"
            
            # 정확한 가용성 매칭 기반 추천 인원 추출
            increase_candidates = [s for s in avail_close_staff if not (s == "김상혁" and fail_day_name in ["월", "수"]) and (staff_counts[s]["open"] + staff_counts[s]["close"]) >= target_nov_quotas.get(s, 0)]
            if not increase_candidates:
                increase_candidates = [s for s in avail_close_staff if not (s == "김상혁" and fail_day_name in ["월", "수"])]
                
            decrease_candidates = [s for s in general_staff if target_nov_quotas.get(s, 0) > (staff_counts[s]["open"] + staff_counts[s]["close"]) and target_nov_quotas.get(s, 0) > 1]
            if not decrease_candidates:
                decrease_candidates = [s for s in general_staff if target_nov_quotas.get(s, 0) > 1]

            suggestion_str = (
                f"제언: 현재 {fail_day_name}요일 마감 슬롯에 투입 가능한 가용 인원의 쿼터가 꽉 차서 막혔습니다.\n"
                f"- [가용성 매칭 - 늘려야 할 추천 인원]: {', '.join(increase_candidates)}\n"
                f"- [가용성 매칭 - 줄여야 할 추천 인원(여유 인원)]: {', '.join(decrease_candidates)}\n\n"
                f"팁: 위쪽 1단계 버튼을 다시 누르시면 언제든 완벽하게 성공하는 초기 모범 스케줄 상태로 슬라이더가 확실하게 초기화됩니다!"
            )

            st.error(
                f"스케줄 생성 중단 및 오류 발생!\n"
                f"(이전에 생성되었던 결과물 및 통계는 모두 초기화되었습니다.)\n\n"
                f"상세 원인:\n{fail_reason}\n\n"
                f"[참고] {fail_day_name}요일 마감 가용 인원들의 현재 쿼터 현황:\n{status_str}\n\n"
                f"해결 가이드:\n{suggestion_str}"
            )
        else:
            mismatch = False
            for staff, target in target_nov_quotas.items():
                actual = staff_counts[staff]["open"] + staff_counts[staff]["close"]
                if actual != target:
                    mismatch = True
                    break
            
            if mismatch:
                if "schedule_results" in st.session_state:
                    del st.session_state["schedule_results"]
                if "staff_counts" in st.session_state:
                    del st.session_state["staff_counts"]
                st.error("오류: 지정한 목표 쿼터와 실제 생성된 횟수 간에 불일치가 감지되었습니다. (이전 결과물 초기화됨)")
            else:
                st.session_state.schedule_results = schedule_results
                st.session_state.staff_counts = staff_counts
                st.success("지정한 쿼터에 100% 오차 없이 완벽히 일치하도록 스케줄이 생성되었습니다!")

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
