if st.button("스케줄 생성하기"):
    calendar.setfirstweekday(calendar.SUNDAY)
    cal = calendar.monthcalendar(target_year, target_month)
    business_days = []
    
    for week in cal:
        for i, day in enumerate(week):
            if day != 0 and i in [1, 2, 3, 4, 5]:
                date_obj = datetime.date(target_year, target_month, day)
                day_name = ["일", "월", "화", "수", "목", "금", "토"][i]
                business_days.append({"date": date_obj, "day_name": day_name, "day_num": day})
    
    # 1. 10월까지의 누적 데이터 가져오기
    staff_prev = {}
    for staff in staff_names:
        if staff in edited_history.index:
            val = edited_history.loc[staff, "10월"]
            staff_prev[staff] = int(val) if pd.notna(val) else 0
        else:
            staff_prev[staff] = 0

    # 2. [핵심] 11월 목표 최종 누적횟수 및 11월 당월 할당 횟수(쿼터) 설정
    # 총 영업일수 기반 오픈/마감 슬롯과 완벽히 일치하도록 쿼터 설계
    # 이현준(11) -> 최종 15 (11월 4회)
    # 박라영(10) -> 최종 15 (11월 5회)
    # 정은성, 김동환, 김범수, 허다인(각 10) -> 최종 16 (11월 각 6회)
    target_final_cumulative = {
        "이현준": 15,
        "박라영": 15,
        "정은성": 16,
        "김동환": 16,
        "김범수": 16,
        "허다인": 16
    }
    
    target_nov_quotas = {}
    for staff, final_target in target_final_cumulative.items():
        prev = staff_prev.get(staff, 0)
        target_nov_quotas[staff] = max(0, final_target - prev)
        
    # 김상혁 씨는 월/수 마감 전담 (11월 월/수 마감 총 횟수)
    sanghyuk_closes = sum(1 for bday in business_days if bday["day_name"] in ["월", "수"])
    target_nov_quotas["김상혁"] = sanghyuk_closes

    # 초기 상태 설정 (당월 배정 횟수 추적)
    staff_counts = {staff: {"open": 0, "close": 0, "prev_total": staff_prev.get(staff, 0)} for staff in staff_names}
    schedule_results = []
    
    for bday in business_days:
        d_name = bday["day_name"]
        d_date = bday["date"]
        
        # --- [오픈 배정] ---
        avail_open = open_input.get(d_name, [])
        avail_open = [s for s in avail_open if s != "김상혁"]
        
        # 아직 11월 쿼터를 다 채우지 못한 사람 우선, 달성률이 낮은 사람 우선
        eligible_open = [s for s in avail_open if staff_counts[s]["open"] + staff_counts[s]["close"] < target_nov_quotas.get(s, 0)]
        if not eligible_open:
            eligible_open = avail_open # 예비용 전체 후보
            
        eligible_open.sort(key=lambda x: (
            (staff_counts[x]["open"] + staff_counts[x]["close"]) / target_nov_quotas.get(x, 1),
            staff_counts[x]["open"] + staff_counts[x]["close"]
        ))
        
        selected_open = eligible_open[0] if eligible_open else ""
        if selected_open:
            staff_counts[selected_open]["open"] += 1
            
        # --- [마감 배정] ---
        avail_close = close_input.get(d_name, [])
        if d_name in ["월", "수"] and "김상혁" in avail_close:
            selected_close = "김상혁"
        else:
            other_avail = [s for s in avail_close if s != "김상혁"]
            eligible_close = [s for s in other_avail if staff_counts[s]["open"] + staff_counts[s]["close"] < target_nov_quotas.get(s, 0)]
            if not eligible_close:
                eligible_close = other_avail
                
            eligible_close.sort(key=lambda x: (
                (staff_counts[x]["open"] + staff_counts[x]["close"]) / target_nov_quotas.get(x, 1),
                staff_counts[x]["open"] + staff_counts[x]["close"]
            ))
            
            if eligible_close:
                selected_close = eligible_close[0]
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
    st.success("최종 누적 쿼터제 기반 스케줄이 성공적으로 생성되었습니다!")

if "schedule_results" in st.session_state:
    st.header("4. 개인별 근무 횟수 통계 및 복사 양식")
    stats_rows = []
    copy_texts = []
    
    for staff, data in st.session_state.staff_counts.items():
        m_open = data["open"]
        m_close = data["close"]
        m_total = m_open + m_close
        
        prev_total = data.get("prev_total", 0)
        total_sum = prev_total + m_total  # 누적횟수 (이전 누적 + 당월 합계)
        
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
