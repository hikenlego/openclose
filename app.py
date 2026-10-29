import streamlit as st
import pandas as pd
import datetime
import calendar
import matplotlib.pyplot as plt
import io

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
    cal = calendar.monthcalendar(target_year, target_month)
    business_days = []
    
    for week in cal:
        for i, day in enumerate(week[:5]):
            if day != 0:
                date_obj = datetime.date(target_year, target_month, day)
                day_name = ["월", "화", "수", "목", "금"][i]
                business_days.append({"date": date_obj, "day_name": day_name, "day_num": day})
    
    schedule_results = []
    staff_counts = {staff: {"open": 0, "close": 0} for staff in all_staff}
    
    for idx, row in edited_history.iterrows():
        s_name = row["이름"]
        if s_name in staff_counts:
            staff_counts[s_name]["prev_open"] = int(row["기존 총 오픈"])
            staff_counts[s_name]["prev_close"] = int(row["기존 총 마감"])
    
    for bday in business_days:
        d_name = bday["day_name"]
        d_date = bday["date"]
        
        avail_open = open_input.get(d_name, [])
        avail_open = [s for s in avail_open if s != "김상혁"]
        avail_open.sort(key=lambda x: staff_counts[x]["open"] + staff_counts.get(x, {}).get("prev_open", 0))
        selected_open = avail_open[0] if avail_open else ""
        
        avail_close = close_input.get(d_name, [])
        if d_name in ["월", "수"] and "김상혁" in avail_close:
            selected_close = "김상혁"
        else:
            other_avail = [s for s in avail_close if s != "김상혁"]
            other_avail.sort(key=lambda x: staff_counts[x]["close"] + staff_counts.get(x, {}).get("prev_close", 0))
            if other_avail:
                selected_close = other_avail[0]
            else:
                if d_name in ["월", "수"]:
                    selected_close = "김상혁"
                else:
                    selected_close = ""
        
        if selected_open:
            staff_counts[selected_open]["open"] += 1
        if selected_close:
            staff_counts[selected_close]["close"] += 1
            
