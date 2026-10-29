import streamlit as st
import pandas as pd
import datetime
import calendar

st.title("근무 일정 자동 생성 프로그램")

# 세션 상태 초기화
if "schedule_df" not in st.session_state:
    st.session_state.schedule_df = None
if "history_df" not in st.session_state:
    st.session_state.history_df = None

st.header("1. 엑셀 파일 업로드 및 가용 인원 설정")
uploaded_file = st.file_uploader("근무표 엑셀 파일을 업로드하세요", type=["xlsx", "xls"])

# 기본 요일별 가용 인원 템플릿
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
        st.success("엑셀 파일을 성공적으로 읽어왔습니다. 아래에서 가용 인원을 확인하고 수정할 수 있습니다.")
    except Exception as e:
        st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")

st.subheader("요일별 오픈 가용 인원")
open_input = {}
days = ["월", "화", "수", "목", "금"]
for day in days:
    default_str = ", ".join(default_open.get(day, []))
    val = st.text_input(f"오픈 - {day}요일", value=default_str)
    open_input[day] = [x.strip() for x in val.split(",") if x.strip()]

st.subheader("요일별 마감 가용 인원")
close_input = {}
for day in days:
    default_str = ", ".join(default_close.get(day, []))
    val = st.text_input(f"마감 - {day}요일", value=default_str)
    close_input[day] = [x.strip() for x in val.split(",") if x.strip()]


st.header("2. 이전 달 누적 횟수 입력")
all_staff = list(set([name for sub in open_input.values() for name in sub] + [name for sub in close_input.values() for name in sub]))
if "김상혁" not in all_staff:
    all_staff.append("김상혁")

history_data = []
for staff in sorted(all_staff):
    history_data.append({"이름": staff, "기존 총 오픈": 5, "기존 총 마감": 5})

history_df = pd.DataFrame(history_data)
edited_history = st.data_editor(history_df, key="history_editor")


st.header("3. 일정 생성 및 날짜 설정")
col1, col2 = st.columns(2)
with col1:
    target_year = st.number_input("연도", min_value=2024, max_value=2030, value=2026)
with col2:
    target_month = st.number_input("월", min_value=1, max_value=12, value=11)

if st.button("스케줄 생성하기"):
    # 영업일 계산 (주말 제외, 간단한 예시로 월~금 영업일 추출)
    cal = calendar.monthcalendar(target_year, target_month)
    business_days = []
    
    for week in cal:
        for i, day in enumerate(week[:5]): # 월~금 (0~4)
            if day != 0:
                date_obj = datetime.date(target_year, target_month, day)
                day_name = ["월", "화", "수", "목", "금"][i]
                business_days.append({"date": date_obj, "day_name": day_name})
    
    # 공휴일 제외 로직 추가 가능 (여기서는 기본 주중 영업일 기준)
    
    # 스케줄 배정 알고리즘 시뮬레이션
    schedule_results = []
    staff_counts = {staff: {"open": 0, "close": 0} for staff in all_staff}
    
    # 이전 달 누적 데이터 반영
    for idx, row in edited_history.iterrows():
        s_name = row["이름"]
        if s_name in staff_counts:
            staff_counts[s_name]["prev_open"] = int(row["기존 총 오픈"])
            staff_counts[s_name]["prev_close"] = int(row["기존 총 마감"])
    
    for bday in business_days:
        d_name = bday["day_name"]
        d_date = bday["date"]
        
        # 오픈 인원 선정 (가용 인원 중 누적 횟수가 적은 사람 우선 선택, 예: 2명)
        avail_open = open_input.get(d_name, [])
        # 김상혁은 오픈 불가
        avail_open = [s for s in avail_open if s != "김상혁"]
        avail_open.sort(key=lambda x: staff_counts[x]["open"] + staff_counts.get(x, {}).get("prev_open", 0))
        selected_open = avail_open[:2] if len(avail_open) >= 2 else avail_open
        
        # 마감 인원 선정 (김상혁은 월, 수 마감 고정)
        avail_close = close_input.get(d_name, [])
        if d_name in ["월", "수"] and "김상혁" in avail_close:
            selected_close = ["김상혁"]
            other_avail = [s for s in avail_close if s != "김상혁"]
            other_avail.sort(key=lambda x: staff_counts[x]["close"] + staff_counts.get(x, {}).get("prev_close", 0))
            selected_close.extend(other_avail[:2] if len(other_avail) >= 2 else other_avail)
        else:
            other_avail = [s for s in avail_close if s != "김상혁"]
            other_avail.sort(key=lambda x: staff_counts[x]["close"] + staff_counts.get(x, {}).get("prev_close", 0))
            selected_close = other_avail[:3] if len(other_avail) >= 3 else other_avail
            if d_name in ["월", "수"] and "김상혁" in avail_close and "김상혁" not in selected_close:
                selected_close[0] = "김상혁" # 강제 포함
        
        # 횟수 누적
        for s in selected_open:
            staff_counts[s]["open"] += 1
        for s in selected_close:
            staff_counts[s]["close"] += 1
            
        schedule_results.append({
            "날짜": d_date,
            "요일": d_name,
            "오픈": ", ".join(selected_open),
            "마감": ", ".join(selected_close)
        })
        
    st.session_state.schedule_results = schedule_results
    st.session_state.staff_counts = staff_counts
    st.success("스케줄이 성공적으로 생성되었습니다!")

if "schedule_results" in st.session_state:
    st.header("4. 개인별 근무 횟수 통계 및 복사 양식")
    stats_rows = []
    copy_texts = []
    
    for staff, data in st.session_state.staff_counts.items():
        m_open = data["open"]
        m_close = data["close"]
        m_total = m_open + m_close
        p_open = data.get("prev_open", 0)
        p_close = data.get("prev_close", 0)
        total_open = m_open + p_open
        total_close = m_close + p_close
        total_sum = total_open + total_close
        
        stats_rows.append({
            "이름": staff,
            "당월 오픈": m_open,
            "당월 마감": m_close,
            "당월 합계": m_total,
            "총 오픈": total_open,
            "총 마감": total_close,
            "총계": total_sum
        })
        
        line_str = f"{staff} / 오픈 {m_open} / 마감 {m_close} / 당월 {m_total} / 총 오픈 {total_open} / 총 마감 {total_close} / 총계 {total_sum}"
        copy_texts.append(line_str)
        
    stats_df = pd.DataFrame(stats_rows)
    st.dataframe(stats_df)
    
    st.subheader("복사 텍스트 양식")
    full_copy_text = "\n".join(copy_texts)
    st.text_area("아래 내용을 복사하여 사용하세요", value=full_copy_text, height=150)

    st.header("5. 월간 캘린더 및 조건별 하이라이트")
    st.write("빨간색: 마감 직후 오픈 / 파란색: 연일 오픈 / 보라색: 둘 다 해당")
    
    # 캘린더 형태 출력 테이블 구현
    sched_df = pd.DataFrame(st.session_state.schedule_results)
    st.dataframe(sched_df)
