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

if st.button("1단계: 날짜 설정 및 기준 계산하기"):
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
    st.success("기준 날짜와 이전 누적 데이터가 계산되었습니다. 아래 슬라이더에서 인원별 '최종 누적 횟수'를 조정하세요!")

if "business_days" in st.session_state and "staff_prev" in st.session_state:
    st.subheader("인원별 당월 기준 '최종 누적 횟수' 조정 (슬라이더)")
    
    total_business_days = len(st.session_state.business_days)
    sanghyuk_closes = sum(1 for bday in st.session_state.business_days if bday["day_name"] in ["월", "수"])
    
    # 총 오픈 슬롯 수 = 총 영업일수, 총 마감 슬롯 수 = 총 영업일수
    # 일반 인원들이 나눠 가져야 할 총 오픈/마감 횟수 계산
    general_staff = [s for s in staff_names if s != "김상혁"]
    
    st.info(f"📌 총 영업일수: {total_business_days}일 (오픈 총 {total_business_days}개, 일반 마감 총 {total_business_days - sanghyuk_closes}개)")
    
    user_final_cumulatives = {}
    
    # 슬라이더 값 입력받기 (최종 누적 횟수 기준: 이전 누적 + 당월 근무)
    current_slider_sum = 0
    for i, staff in enumerate(general_staff):
        prev = st.session_state.staff_prev.get(staff, 0)
        # 기본 권장 최종 누적값 (이현준/박라영은 15, 나머지는 16)
        default_final = 15 if staff in ["이현준", "박라영"] else 16
        
        # 슬라이더 범위: 이전 누적치 이상부터 적절한 최대치까지 설정
        val = st.slider(f"{staff} (이전 누적: {prev}회)", min_value=prev, max_value=prev+15, value=default_final, key=f"cumul_slider_{staff}")
        user_final_cumulatives[staff] = val
        current_slider_sum += (val - prev)

    # 김상혁 씨 정보 표시
    sk_prev = st.session_state.staff_prev.get("김상혁", 0)
    sk_final = sk_prev + sanghyuk_closes
    st.markdown(f"🔒 **김상혁 (월/수 마감 전담)**: 이전 누적 {sk_prev}회 + 당월 마감 {sanghyuk_closes}회 = **최종 누적 {sk_final}회** (자동 고정)")
    user_final_cumulatives["김상혁"] = sk_final

    # 총 오픈/마감 슬롯과 슬라이더로 배정된 횟수 검증
    total_open_slots = total_business_days
    total_general_close_slots = total_business_days - sanghyuk_closes
    
    total_assigned_nov = sum(user_final_cumulatives[s] - st.session_state.staff_prev.get(s, 0) for s in general_staff)
    required_nov = total_open_slots + total_general_close_slots # 오픈 총개 + 일반마감 총개

    if total_assigned_nov != required_nov:
        st.warning(f"⚠️ 현재 슬라이더로 설정된 일반 인원 총 당월 근무 횟수({total_assigned_nov}회)가 배치해야 할 총 슬롯 수({required_nov}회)와 일치하지 않습니다. (오차: {total_assigned_nov - required_nov}회). 슬라이더 조정을 통해 합계를 맞춰주세요!")
    else:
        st.success("✨ 일반 인원 총 당월 근무 횟수가 완벽하게 일치합니다!")

if st.button("2단계: 최종 스케줄 생성하기"):
        business_days = st.session_state.business_days
        staff_prev = st.session_state.staff_prev
        
        # 1단계: 슬라이더로 지정한 최종 누적 횟수로부터 '개인별 당월 목표 횟수'를 정확하게 도출
        target_nov_quotas = {staff: user_final_cumulatives[staff] - staff_prev.get(staff, 0) for staff in staff_names}
        
        # 날짜별 초기화
        schedule_results = []
        staff_counts = {staff: {"open": 0, "close": 0, "prev_total": staff_prev.get(staff, 0)} for staff in staff_names}
        
        # 날짜 순회하며 배정
        for bday in business_days:
            d_name = bday["day_name"]
            d_date = bday["date"]
            
            # --- [오픈 배정] ---
            avail_open = open_input.get(d_name, [])
            avail_open = [s for s in avail_open if s != "김상혁"]
            
            # 아직 당월 목표 횟수를 다 채우지 못한 가용 인원만 필터링
            valid_open = [s for s in avail_open if staff_counts[s]["open"] + staff_counts[s]["close"] < target_nov_quotas.get(s, 0)]
            
            if valid_open:
                # 그중에서 당월 근무(오픈+마감)가 가장 적은 사람 우선 선택
                valid_open.sort(key=lambda x: staff_counts[x]["open"] + staff_counts[x]["close"])
                selected_open = valid_open[0]
            else:
                selected_open = avail_open[0] if avail_open else ""
                
            if selected_open:
                staff_counts[selected_open]["open"] += 1
                
            # --- [마감 배정] ---
            avail_close = close_input.get(d_name, [])
            if d_name in ["월", "수"] and "김상혁" in avail_close:
                selected_close = "김상혁"
            else:
                other_avail = [s for s in avail_close if s != "김상혁"]
                valid_close = [s for s in other_avail if staff_counts[s]["open"] + staff_counts[s]["close"] < target_nov_quotas.get(s, 0)]
                
                if valid_close:
                    valid_close.sort(key=lambda x: staff_counts[x]["open"] + staff_counts[x]["close"])
                    selected_close = valid_close[0]
                else:
                    if d_name in ["월", "수"]:
                        selected_close = "김상혁"
                    else:
                        selected_close = other_avail[0] if other_avail else ""
            
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
        st.success("지정한 당월 목표 횟수에 완벽히 부합하도록 스케줄이 생성되었습니다!")

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
