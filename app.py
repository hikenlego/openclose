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

st.header("2. 이전 달 누적 횟수 입력")
all_staff = list(set([name for sub in open_input.values() for name in sub] + [name for sub in close_input.values() for name in sub]))
if "김상혁" not in all_staff:
    all_staff.append("김상혁")

initial_counts = {
    "김상혁": {"open": 0, "close": 16},
    "김동환": {"open": 6, "close": 4},
    "박라영": {"open": 6, "close": 4},
    "정은성": {"open": 6, "close": 4},
    "김범수": {"open": 6, "close": 4},
    "허다인": {"open": 7, "close": 3},
    "이현준": {"open": 7, "close": 4}
}

history_data = []
for staff in sorted(all_staff):
    default_open_cnt = initial_counts.get(staff, {}).get("open", 0)
    default_close_cnt = initial_counts.get(staff, {}).get("close", 0)
    history_data.append({
        "이름": staff,
        "기존 총 오픈": default_open_cnt,
        "기존 총 마감": default_close_cnt
    })

history_df = pd.DataFrame(history_data)
edited_history = st.data_editor(history_df, key="history_editor")

st.header("3. 일정 생성 및 날짜 설정")
col1, col2 = st.columns(2)
with col1:
    target_year = st.number_input("연도", min_value=2024, max_value=2030, value=2026)
with col2:
    target_month = st.number_input("월", min_value=1, max_value=12, value=11)

if st.button("스케줄 생성하기"):
    # 표준 월요일 시작 달력으로 영업일 추출 (월~금은 인덱스 0~4)
    cal = calendar.monthcalendar(target_year, target_month)
    business_days = []
    
    for week in cal:
        for i, day in enumerate(week):
            if day != 0 and i in [0, 1, 2, 3, 4]:
                date_obj = datetime.date(target_year, target_month, day)
                day_name = ["월", "화", "수", "목", "금", "토", "일"][i]
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
        
        # 총계 편차 1 이내 유지를 위한 전체 총합 기준 정렬
        avail_open = open_input.get(d_name, [])
        avail_open = [s for s in avail_open if s != "김상혁"]
        avail_open.sort(key=lambda x: (
            (staff_counts[x]["open"] + staff_counts[x]["close"]) + 
            (staff_counts[x].get("prev_open", 0) + staff_counts[x].get("prev_close", 0)),
            staff_counts[x]["open"] + staff_counts[x]["close"]
        ))
        selected_open = avail_open[0] if avail_open else ""
        
        if selected_open:
            staff_counts[selected_open]["open"] += 1
            
        avail_close = close_input.get(d_name, [])
        if d_name in ["월", "수"] and "김상혁" in avail_close:
            selected_close = "김상혁"
        else:
            other_avail = [s for s in avail_close if s != "김상혁"]
            other_avail.sort(key=lambda x: (
                (staff_counts[x]["open"] + staff_counts[x]["close"]) + 
                (staff_counts[x].get("prev_open", 0) + staff_counts[x].get("prev_close", 0)),
                staff_counts[x]["open"] + staff_counts[x]["close"]
            ))
            if other_avail:
                selected_close = other_avail[0]
            else:
                if d_name in ["월", "수"]:
                    selected_close = "김상혁"
                else:
                    selected_close = ""
        
        if selected_close:
            staff_counts[selected_close]["close"] += 1
            
        schedule_results.append({
            "날짜": d_date,
            "일": bday["day_num"],
            "요일": d_name,
            "오픈": selected_open,
            "마감": selected_close
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

    st.header("5. 월간 캘린더 출력 및 이미지 다운로드")
    
  # 일요일 시작(firstweekday=6)으로 정확하게 달력 매트릭스 생성
    month_matrix = calendar.Calendar(firstweekday=6).monthcalendar(target_year, target_month)
    
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
