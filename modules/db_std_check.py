import streamlit as st
import pandas as pd
import sqlite3
import os
import re
import datetime
from modules.db_utils import (
    execute_query, select_query,
    cleansing_data, preprocess_all, check_word, check_term, check_construct, check_compliance,
    STANDARDS_QUERY_LOOKUP, STANDARDS_SQL_DICT, UIProgress, st_tabs_persistent
)

# 표준 대상 테이블별 기본 스키마 (asset/IN_DATA_CHK_FILE.xlsx 기준)
TARGET_TABLE_SCHEMAS = {
    "단어": ["표준단어", "표준단어영문약서", "형식단어여부", "이음동의어목록"],
    "용어": ["표준용어", "표준용어영문약어", "표준도메인", "이음동의어"],
    "도메인": ["표준도메인", "데이터타입", "데이터길이", "데이터소수점"],
    "속성정의": ["엔터티(한글)", "테이블(영문)", "컬럼(영문)", "속성(한글)", "속성(데이터타입)", "식별자여부"],
    "컬럼정의": ["엔터티(한글)", "테이블(영문)", "컬럼(영문)", "속성(한글)", "컬럼(데이터타입)", "PK"],
    "기관표준단어": ["기관표준단어", "기관표준단어영문약서", "형식단어여부", "이음동의어"],
    "기관표준용어": ["기관표준용어", "기관표준용어영문약어", "표준도메인", "이음동의어"],
    "기관표준도메인": ["표준도메인", "데이터타입", "데이터길이", "데이터소수점"],
    "공통표준용어": ["번호", "제정차수", "공통표준용어명", "공통표준용어설명", "공통표준용어영문약어명", "공통표준도메인명", "허용값", "저장 형식", "표현 형식", "행정표준코드명", "소관기관명", "용어 이음동의어 목록"],
    "공통표준단어": ["번호", "제정차수", "공통표준단어명", "공통표준단어영문약어명", "공통표준단어 영문명", "공통표준단어 설명", "형식단어여부", "공통표준도메인분류명", "이음동의어 목록", "금칙어 \\n목록"],
    "공통표준도메인": ["번호", "제정차수", "공통표준도메인그룹명", "공통표준도메인분류명", "공통표준도메인명", "공통표준도메인설명", "데이터타입", "데이터길이", "데이터소수점길이", "저장\\n형식", "표현\\n형식", "단위", "허용값"]
}


def sorted_df(df):
    """1열(첫 번째 커럼) 기준 오름차순 정렬. 정렬 불가한 경우 원본 반환."""
    if df.empty or len(df.columns) == 0:
        return df
    try:
        return df.sort_values(by=df.columns[0], na_position='last').reset_index(drop=True)
    except Exception:
        return df

def load_excel_to_ori(db_path, uploaded_file):
    """업로드된 엑셀 파일의 모든 시트를 ORI_ 로드"""
    conn = sqlite3.connect(db_path)
    xl = pd.ExcelFile(uploaded_file)
    sheet_names = xl.sheet_names
    
    loaded_sheets = []
    for sheet in sheet_names:
        df = pd.read_excel(uploaded_file, sheet_name=sheet)
        ori_tb_name = f"ORI_{sheet}"
        df.to_sql(ori_tb_name, conn, if_exists="replace", index=False)
        loaded_sheets.append(sheet)
    conn.close()
    return loaded_sheets

def reset_std_check_state():
    """파일 업로드 변경 시 매핑 상태 등 관련 세션 초기화"""
    if 'std_check_loaded_sheets' in st.session_state:
        del st.session_state['std_check_loaded_sheets']
    if 'std_check_mapped_status' in st.session_state:
        del st.session_state['std_check_mapped_status']

def drop_std_check_results(db_path):
    """새로운 데이터 매핑/적재 시 기존 표준점검 결과 초기화"""
    tables_to_drop = [
        "점검_단어_01_표준단어명재정의",
        "점검_단어_02_표준단어약어재정의",
        "점검_단어_03_표준단어명중복정의",
        "점검_단어_04_표준단어약어중복정의",
        "점검_용어_01_용어명재정의",
        "점검_용어_02_용어약어재정의",
        "점검_용어_03_용어명중복정의",
        "점검_용어_04_용어약어중복정의",
        "점검_용어_05_용어도메인재정의",
        "표준용어_구성점검_RES",
        "점검_속성표준준수",
        "점검_속성표준도메인준수"
    ]
    for tb in tables_to_drop:
        execute_query(db_path, f"DROP TABLE IF EXISTS {tb}")

def auto_map_and_save_std(db_path, loaded_sheets):
    target_options = list(TARGET_TABLE_SCHEMAS.keys())
    success = True
    for sheet in loaded_sheets:
        ori_tb_name = f"ORI_{sheet}"
        if sheet in target_options:
            selected_target = sheet
        else:
            continue
        
        target_columns = TARGET_TABLE_SCHEMAS[selected_target]
        ori_cols_df = select_query(db_path, f"PRAGMA table_info({ori_tb_name})")
        src_columns = ori_cols_df['name'].tolist() if not ori_cols_df.empty else []
        
        mapped_targets = []
        mapped_sources = []
        for src_col in src_columns:
            if src_col in target_columns:
                mapped_targets.append(f'"{src_col}"')
                mapped_sources.append(f'"{src_col}"')
        
        col_defs = [f'"{col}" VARCHAR(500)' for col in target_columns]
        create_sql = f"DROP TABLE IF EXISTS {selected_target};\nCREATE TABLE {selected_target} (\n  " + ",\n  ".join(col_defs) + "\n);"
        if not execute_query(db_path, f"DROP TABLE IF EXISTS {selected_target}_FULL"): success = False
        if not execute_query(db_path, create_sql): success = False
        
        if mapped_targets:
            insert_sql = f"INSERT INTO {selected_target} ({', '.join(mapped_targets)}) SELECT {', '.join(mapped_sources)} FROM {ori_tb_name};"
            if not execute_query(db_path, insert_sql): success = False
        
        if 'std_check_mapped_status' not in st.session_state:
            st.session_state['std_check_mapped_status'] = {}
        st.session_state['std_check_mapped_status'][sheet] = True
        
    drop_std_check_results(db_path)
    return success

def show_db_std_check():
    # 프로젝트 설정 체크
    if 'current_project_path' not in st.session_state or not st.session_state.current_project_path:
        st.header("🎯 DB표준점검")
        st.warning("⚠️ [설정] 탭에서 먼저 프로젝트 경로를 지정해 주세요.")
        return

    db_path = st.session_state.get('current_db_path')
    if not db_path or not os.path.exists(db_path):
        st.header("🎯 DB표준점검")
        st.error("⚠️ 데이터베이스 파일이 존재하지 않습니다. [설정]에서 다시 저장해 주세요.")
        return

    col_h1, col_h2 = st.columns([0.8, 0.2])
    with col_h1:
        st.header("🎯 DB표준점검")
    with col_h2:
        st.write("") # 간격 맞춤
        template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'asset', 'IN_DATA_CHK_FILE.xlsx')
        if os.path.exists(template_path):
            with open(template_path, "rb") as f:
                st.download_button(
                    label="📥 템플릿 엑셀 다운로드",
                    data=f,
                    file_name="IN_DATA_CHK_FILE.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="btn_download_standards_template_top_std"
                )

    is_expert = st.session_state.get('app_mode_toggle', False)

    # 탭 생성
    if is_expert:
        tab_titles = ["📥 DB표준 기초데이터적재", "⚙️ 표준화대상 설정", "🚀 표준사전 점검", "🧩 표준구성 점검", "✅ 표준준수 점검"]
    else:
        tab_titles = ["📥 DB표준 기초데이터적재", "🚀 표준사전 점검", "🧩 표준구성 점검", "✅ 표준준수 점검"]
    
    tabs = st.tabs(tab_titles)
    
    # 탭 인덱스 맵핑 (동적)
    idx_load = tab_titles.index("📥 DB표준 기초데이터적재")
    idx_setting = tab_titles.index("⚙️ 표준화대상 설정") if is_expert else -1
    idx_check = tab_titles.index("🚀 표준사전 점검")
    idx_const = tab_titles.index("🧩 표준구성 점검")
    idx_comp = tab_titles.index("✅ 표준준수 점검")

    # --- 데이터 사전 & 속성 요약 정보 표시 공통 함수 ---
    def render_summary(show_overview=True, show_target=False):
        def _get_cnt(query):
            try:
                res = select_query(db_path, query)
                return int(res.iloc[0, 0]) if not res.empty else 0
            except:
                return 0
                
        if show_overview:
            cnt_word_c = _get_cnt("SELECT COUNT(*) FROM 공통표준단어")
            cnt_word_i = _get_cnt("SELECT COUNT(*) FROM 기관표준단어")
            cnt_word = _get_cnt("SELECT COUNT(*) FROM 단어")
            cnt_term_c = _get_cnt("SELECT COUNT(*) FROM 공통표준용어")
            cnt_term_i = _get_cnt("SELECT COUNT(*) FROM 기관표준용어")
            cnt_term = _get_cnt("SELECT COUNT(*) FROM 용어")
            cnt_dom_c = _get_cnt("SELECT COUNT(*) FROM 공통표준도메인")
            cnt_dom_i = _get_cnt("SELECT COUNT(*) FROM 기관표준도메인")
            cnt_dom = _get_cnt("SELECT COUNT(*) FROM 도메인")
            
            st.markdown("###### 📚 데이터사전 개요")
            st.dataframe(pd.DataFrame([
                {"구분": "단어", "공통표준": f"{cnt_word_c:,}", "기관표준": f"{cnt_word_i:,}", "표준(일반)": f"{cnt_word:,}"},
                {"구분": "용어", "공통표준": f"{cnt_term_c:,}", "기관표준": f"{cnt_term_i:,}", "표준(일반)": f"{cnt_term:,}"},
                {"구분": "도메인", "공통표준": f"{cnt_dom_c:,}", "기관표준": f"{cnt_dom_i:,}", "표준(일반)": f"{cnt_dom:,}"}
            ]), hide_index=True, use_container_width=True)
            
        if show_target:
            tot_tb = _get_cnt("SELECT COUNT(DISTINCT \"테이블(영문)\") FROM 속성정의")
            tot_attr = _get_cnt("SELECT COUNT(*) FROM 속성정의")
            chk_std_tb = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='표준화대상테이블'")
            if not chk_std_tb.empty:
                tgt_tb = _get_cnt("SELECT COUNT(DISTINCT A.\"테이블(영문)\") FROM 속성정의 A JOIN 표준화대상테이블 B ON A.\"테이블(영문)\" = B.TABLE_NAME WHERE B.STANDARD_YN='Y'")
                tgt_attr = _get_cnt("SELECT COUNT(*) FROM 속성정의 A JOIN 표준화대상테이블 B ON A.\"테이블(영문)\" = B.TABLE_NAME WHERE B.STANDARD_YN='Y'")
            else:
                tgt_tb = tot_tb
                tgt_attr = tot_attr
                
            st.markdown("###### 🎯 점검 대상 현황")
            st.dataframe(pd.DataFrame([
                {"항목": "테이블 수", "전체 적재": f"{tot_tb:,}", "점검 대상 (선택됨)": f"{tgt_tb:,}"},
                {"항목": "속성/컬럼 수", "전체 적재": f"{tot_attr:,}", "점검 대상 (선택됨)": f"{tgt_attr:,}"}
            ]), hide_index=True, use_container_width=True)

    with tabs[idx_load]:
        with st.container():
            st.markdown("##### 엑셀 데이터 업로드 및 자동 적재")

            st.markdown("""
            <style>
            .std-loading-overlay {
                position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
                background: rgba(0,0,0,0.5); z-index: 9999;
                display: flex; flex-direction: column;
                align-items: center; justify-content: center;
            }
            .std-loading-box {
                background: white; border-radius: 16px; padding: 40px 56px;
                text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            }
            .std-loading-spinner { font-size: 3rem; margin-bottom: 16px; }
            .std-loading-text { font-size: 1.1rem; font-weight: 600; color: #333; }
            .std-loading-sub  { font-size: 0.9rem; color: #666; margin-top: 6px; }
            </style>
            """, unsafe_allow_html=True)

            overlay_placeholder = st.empty()

            uploaded_file = st.file_uploader(
                "DB표준용 엑셀 파일 선택",
                type=["xlsx", "xls"],
                key="std_check_uploader",
                on_change=reset_std_check_state
            )

            if uploaded_file:
                if st.button("파일 업로드 및 자동 적재 실행", use_container_width=True, key="btn_upload_ori_std"):
                    overlay_placeholder.markdown("""
                    <div class='std-loading-overlay'>
                      <div class='std-loading-box'>
                        <div class='std-loading-spinner'>⚙️</div>
                        <div class='std-loading-text'>데이터 적재 및 자동 매핑 중...</div>
                        <div class='std-loading-sub'>잠시만 기다려 주세요. 창을 닫지 마세요.</div>
                      </div>
                    </div>""", unsafe_allow_html=True)

                    with st.spinner("파일 적재 중..."):
                        loaded = load_excel_to_ori(db_path, uploaded_file)
                    
                    st.session_state['std_check_loaded_sheets'] = loaded
                    if 'std_check_mapped_status' not in st.session_state:
                        st.session_state['std_check_mapped_status'] = {}
                    for s in loaded:
                        st.session_state['std_check_mapped_status'][s] = False

                    with st.spinner("자동 매핑 및 적재 중..."):
                        success = auto_map_and_save_std(db_path, loaded)
                    
                    overlay_placeholder.empty()
                    if success:
                        st.toast(f"✅ {len(loaded)}개 시트 자동 매핑 및 적재 완료!", icon="✅")
                        import time; time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error("⚠️ 일부 시트 처리 중 오류가 발생했습니다. 에러 메시지를 확인하세요.")

    if is_expert and idx_setting != -1:
        with tabs[idx_setting]:
            with st.container():
                st.markdown("##### ⚙️ 표준화대상 단위 테이블 설정")
    
                check_tb1 = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='속성정의'")
                check_tb2 = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='컬럼정의'")
                if check_tb1.empty and check_tb2.empty:
                    st.warning("⚠️ '속성정의' 또는 '컬럼정의' 테이블이 존재하지 않습니다.")
                else:
                    queries = []
                    if not check_tb1.empty:
                        queries.append('SELECT "엔터티(한글)" as ENTITY_NAME, "테이블(영문)" as TABLE_NAME FROM 속성정의 WHERE "테이블(영문)" IS NOT NULL')
                    if not check_tb2.empty:
                        queries.append('SELECT "엔터티(한글)" as ENTITY_NAME, "테이블(영문)" as TABLE_NAME FROM 컬럼정의 WHERE "테이블(영문)" IS NOT NULL')
                
                    union_query = " UNION ".join(queries)
                    src_df = select_query(db_path, f"SELECT MAX(ENTITY_NAME) AS ENTITY_NAME, TABLE_NAME FROM ({union_query}) GROUP BY TABLE_NAME")
            
                    if src_df.empty:
                        st.warning("⚠️ 대상 테이블에 추출할 데이터가 없습니다.")
                    else:
                        exist_tb = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='표준화대상테이블'")
                        if not exist_tb.empty:
                            exist_df = select_query(db_path, "SELECT TABLE_NAME, ENTITY_NAME, STANDARD_YN, COMMENT FROM 표준화대상테이블")
                            if not exist_df.empty:
                                exist_df = exist_df.drop_duplicates(subset=['TABLE_NAME'], keep='last')
                        else:
                            exist_df = pd.DataFrame(columns=["TABLE_NAME", "ENTITY_NAME", "STANDARD_YN", "COMMENT"])
                
                        if not exist_df.empty:
                            merged_df = pd.merge(src_df, exist_df[['TABLE_NAME', 'STANDARD_YN', 'COMMENT']], on="TABLE_NAME", how="left")
                            merged_df['표준화대상'] = merged_df['STANDARD_YN'].fillna('Y').apply(lambda x: True if x == 'Y' else False)
                            merged_df['제외사유(COMMENT)'] = merged_df['COMMENT'].fillna('')
                        else:
                            merged_df = src_df.copy()
                            merged_df['표준화대상'] = True
                            merged_df['제외사유(COMMENT)'] = ""
                
                        total_cnt = len(merged_df)
                        target_cnt = merged_df['표준화대상'].sum()
                        st.info(f"📊 전체 **{total_cnt:,}**개 ┃ ✅ 대상(Y): **{target_cnt:,}**개 ┃ ❌ 비대상(N): **{total_cnt - target_cnt:,}**개")
                
                        col_type, col_status, col_search, col_b1, col_b2 = st.columns([0.15, 0.15, 0.3, 0.2, 0.2])
                        with col_type:
                            search_col = st.selectbox("검색 기준", ["전체(엔터티+테이블)", "엔터티명", "테이블명"], key="std_target_search_type")
                        with col_status:
                            search_status = st.selectbox("대상 여부", ["전체", "대상(Y)", "비대상(N)"], key="std_target_search_status")
                        with col_search:
                            search_kw = st.text_input("🔍 검색어 (SQL LIKE: %, _ 활용)", key="std_target_search")

                        mask = pd.Series(True, index=merged_df.index)
                        if search_status == "대상(Y)": mask &= (merged_df['표준화대상'] == True)
                        elif search_status == "비대상(N)": mask &= (merged_df['표준화대상'] == False)
                    
                        if search_kw:
                            escaped_kw = re.escape(search_kw)
                            regex_pattern = "^" + escaped_kw.replace("\\%", ".*").replace("%", ".*").replace("\\_", ".").replace("_", ".") + "$"
                            if search_col == "엔터티명": kw_mask = merged_df['ENTITY_NAME'].astype(str).str.match(regex_pattern, case=False, na=False)
                            elif search_col == "테이블명": kw_mask = merged_df['TABLE_NAME'].astype(str).str.match(regex_pattern, case=False, na=False)
                            else: kw_mask = merged_df['TABLE_NAME'].astype(str).str.match(regex_pattern, case=False, na=False) | merged_df['ENTITY_NAME'].astype(str).str.match(regex_pattern, case=False, na=False)
                            mask &= kw_mask

                        with col_b1:
                            st.write(""); 
                            if st.button("✅ 선택 일괄 체크", use_container_width=True):
                                merged_df.loc[mask, '표준화대상'] = True
                                save_df = merged_df.copy()
                                save_df['STANDARD_YN'] = save_df['표준화대상'].apply(lambda x: 'Y' if x else 'N')
                                save_df['COMMENT'] = save_df['제외사유(COMMENT)']
                                final_df = save_df[['TABLE_NAME', 'ENTITY_NAME', 'STANDARD_YN', 'COMMENT']]
                                conn = sqlite3.connect(db_path); final_df.to_sql("표준화대상테이블", conn, if_exists="replace", index=False); conn.close()
                                st.rerun()

                        with col_b2:
                            st.write(""); 
                            if st.button("❌ 선택 일괄 해제", use_container_width=True):
                                merged_df.loc[mask, '표준화대상'] = False
                                save_df = merged_df.copy()
                                save_df['STANDARD_YN'] = save_df['표준화대상'].apply(lambda x: 'Y' if x else 'N')
                                save_df['COMMENT'] = save_df['제외사유(COMMENT)']
                                final_df = save_df[['TABLE_NAME', 'ENTITY_NAME', 'STANDARD_YN', 'COMMENT']]
                                conn = sqlite3.connect(db_path); final_df.to_sql("표준화대상테이블", conn, if_exists="replace", index=False); conn.close()
                                st.rerun()

                        display_df = merged_df[mask][['표준화대상', 'ENTITY_NAME', 'TABLE_NAME', '제외사유(COMMENT)']]
                        edited_df = st.data_editor(
                            display_df, hide_index=True, use_container_width=True, disabled=["ENTITY_NAME", "TABLE_NAME"],
                            column_config={
                                "표준화대상": st.column_config.CheckboxColumn("대상여부(Y/N)", width="small"),
                                "제외사유(COMMENT)": st.column_config.TextColumn("제외사유(N일 경우)", width="large")
                            },
                            key="std_check_target_editor"
                        )
                
                        col_save, col_cancel = st.columns([0.8, 0.2])
                        with col_save:
                            if st.button("💾 화면의 대상설정 저장 실행", type="primary", use_container_width=True):
                                merged_df.set_index('TABLE_NAME', inplace=True)
                                edited_df_copy = edited_df.copy().set_index('TABLE_NAME')
                                merged_df.update(edited_df_copy)
                                merged_df.reset_index(inplace=True)
                                save_df = merged_df.copy()
                                save_df['STANDARD_YN'] = save_df['표준화대상'].apply(lambda x: 'Y' if x else 'N')
                                save_df['COMMENT'] = save_df['제외사유(COMMENT)']
                                final_df = save_df[['TABLE_NAME', 'ENTITY_NAME', 'STANDARD_YN', 'COMMENT']]
                                conn = sqlite3.connect(db_path); final_df.to_sql("표준화대상테이블", conn, if_exists="replace", index=False); conn.close()
                                st.success("✅ 저장 완료!"); st.rerun()
                        with col_cancel:
                            if st.button("🔄 취소(원래대로)", use_container_width=True): st.rerun()

    with tabs[idx_check]:
        with st.container():
            st.markdown("##### 🚀 DB 표준사전 점검 실행")
            st.info("💡 적재된 데이터를 기반으로 표준단어 및 표준용어 사전의 정합성을 점검합니다.")
            render_summary(show_overview=True, show_target=False)
            
            col_btn1, col_btn2 = st.columns([0.2, 0.8])
            with col_btn1:
                if st.button("🗑️ 이전결과 초기화", key="btn_reset_dic", use_container_width=True):
                    tables_to_drop = ["점검_단어_01_표준단어명재정의", "점검_단어_02_표준단어약어재정의", "점검_단어_03_표준단어명중복정의", "점검_단어_04_표준단어약어중복정의", "점검_용어_01_용어명재정의", "점검_용어_02_용어약어재정의", "점검_용어_03_용어명중복정의", "점검_용어_04_용어약어중복정의", "점검_용어_05_용어도메인재정의"]
                    for tb in tables_to_drop: execute_query(db_path, f"DROP TABLE IF EXISTS {tb}")
                    if 'last_run_dic' in st.session_state: del st.session_state['last_run_dic']
                    st.rerun()
            with col_btn2:
                if st.button("▶️ 표준사전 점검 실행", type="primary", use_container_width=True):
                    progress = UIProgress(st.empty())
                    try:
                        s1 = cleansing_data(db_path, progress)
                        s2 = preprocess_all(db_path, progress)
                        s3 = check_word(db_path, progress)
                        s4 = check_term(db_path, progress)
                        
                        if s1 and s2 and s3 and s4:
                            st.session_state['last_run_dic'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            st.success("✅ 점검 완료!")
                            import time; time.sleep(1.0)
                            st.rerun()
                        else:
                            st.warning("⚠️ 점검 중 일부 오류가 발생했습니다. 로그를 확인하세요.")
                    except Exception as e: 
                        st.error(f"❌ 예외 발생: {e}")
            
            if 'last_run_dic' in st.session_state:
                st.markdown(f"<div style='text-align: right; color: gray; font-size: 0.85em;'>마지막 점검 일시: {st.session_state['last_run_dic']}</div>", unsafe_allow_html=True)

            has_dic_result = not select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='점검_단어_01_표준단어명재정의'").empty
            if has_dic_result:
                st.divider()
                sub_tabs = st.tabs(["표준 단어", "표준 용어", "🔍 전체 데이터(ALL)"])
                tab_word, tab_term = sub_tabs[0], sub_tabs[1]
                tab_all = sub_tabs[2]
                
                with tab_word:
                    for i, (title, tb) in enumerate([("1. 표준단어명 재정의", "점검_단어_01_표준단어명재정의"), ("2. 표준단어약어 재정의", "점검_단어_02_표준단어약어재정의"), ("3. 표준단어명 중복정의", "점검_단어_03_표준단어명중복정의"), ("4. 표준단어약어 중복정의", "점검_단어_04_표준단어약어중복정의")]):
                        st.markdown(f"##### {title}")
                        df = select_query(db_path, f"SELECT * FROM {tb}")
                        if not df.empty: st.dataframe(sorted_df(df), use_container_width=True)
                with tab_term:
                    for i, (title, tb) in enumerate([("1. 용어명 재정의", "점검_용어_01_용어명재정의"), ("2. 용어약어 재정의", "점검_용어_02_용어약어재정의"), ("3. 용어명 중복정의", "점검_용어_03_용어명중복정의"), ("4. 용어약어 중복정의", "점검_용어_04_용어약어중복정의"), ("5. 용어-도메인 재정의", "점검_용어_05_용어도메인재정의")]):
                        st.markdown(f"##### {title}")
                        df = select_query(db_path, f"SELECT * FROM {tb}")
                        if not df.empty: st.dataframe(sorted_df(df), use_container_width=True)
                with tab_all:
                    sc1, sc2, sc3 = st.columns(3)
                    if sc1.button("단어 요약", key="btn_word_sum"): st.session_state.show_all_std_chk = "word"
                    if sc2.button("용어 요약", key="btn_term_sum"): st.session_state.show_all_std_chk = "term"
                    if sc3.button("도메인 요약", key="btn_dom_sum"): st.session_state.show_all_std_chk = "domain"
                    mode = st.session_state.get('show_all_std_chk', "word")
                    skw = st.text_input(f"🔍 {mode} 검색", key="txt_search_dic")
                    df_all = pd.DataFrame()
                    try:
                        if mode == "word": df_all = select_query(db_path, "SELECT A.단어, A.단어약어, A.형식단어여부, A.도메인분류, B.명칭 as 정의수준 FROM All_단어 A join 정의수준코드 B on A.정의수준=B.코드")
                        elif mode == "term": df_all = select_query(db_path, "SELECT A.용어, A.용어약어, A.도메인, B.명칭 as 정의수준 FROM All_용어 A join 정의수준코드 B on A.정의수준=B.코드")
                        elif mode == "domain": df_all = select_query(db_path, "SELECT A.도메인, A.데이터타입, A.데이터길이, A.데이터소수점, B.명칭 as 정의수준 FROM All_도메인 A join 정의수준코드 B on A.정의수준=B.코드")
                    except: pass
                    if skw and not df_all.empty: df_all = df_all[df_all.astype(str).apply(lambda r: r.str.contains(skw, case=False).any(), axis=1)]
                    st.dataframe(df_all, use_container_width=True)

    with tabs[idx_const]:
        with st.container():
            st.markdown("##### 🧩 표준구성 점검")
            render_summary(show_overview=True, show_target=False)
            col_c1, col_c2 = st.columns([0.2, 0.8])
            with col_c1:
                if st.button("🗑️ 초기화", key="btn_reset_const"):
                    for tb in ["표준용어_구성점검_TEMP", "표준용어_구성점검", "표준용어_구성점검_RES"]: execute_query(db_path, f"DROP TABLE IF EXISTS {tb}")
                    if 'last_run_const' in st.session_state: del st.session_state['last_run_const']
                    st.rerun()
            with col_c2:
                if st.button("▶️ 수행", type="primary", use_container_width=True, key="btn_run_const"):
                    if select_query(db_path, "SELECT name FROM sqlite_master WHERE name='ALL_용어'").empty: st.error("표준사전 점검을 먼저 수행하세요.")
                    else:
                        success = check_construct(db_path, UIProgress(st.empty()))
                        if success:
                            st.session_state['last_run_const'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            st.success("✅ 점검 완료!")
                            import time; time.sleep(1.0)
                            st.rerun()
                        else:
                            st.warning("⚠️ 구성 점검 중 오류가 발생했습니다.")
            has_res = not select_query(db_path, "SELECT name FROM sqlite_master WHERE name='표준용어_구성점검_RES'").empty
            if has_res:
                st.divider()
                st.markdown("##### 결과 (비표준 항목)")
                st.dataframe(select_query(db_path, "SELECT * FROM 표준용어_구성점검_RES WHERE 구성점검결과 = '비표준' AND 표준용어영문약어 IS NOT NULL"), use_container_width=True)

    with tabs[idx_comp]:
        with st.container():
            st.markdown("##### ✅ 표준준수 점검")
            render_summary(show_overview=True, show_target=True)
            col_cp1, col_cp2 = st.columns([0.2, 0.8])
            with col_cp1:
                if st.button("🗑️ 초기화", key="btn_reset_comp"):
                    for tb in ["점검_속성표준준수", "점검_속성표준도메인준수"]: execute_query(db_path, f"DROP TABLE IF EXISTS {tb}")
                    if 'last_run_comp' in st.session_state: del st.session_state['last_run_comp']
                    st.rerun()
            with col_cp2:
                if st.button("▶️ 수행", type="primary", use_container_width=True, key="btn_run_comp"):
                    if select_query(db_path, "SELECT name FROM sqlite_master WHERE name='ALL_용어'").empty: st.error("표준사전 점검을 먼저 수행하세요.")
                    else:
                        progress = UIProgress(st.empty())
                        progress.start("전처리")
                        prep_success = True
                        for tb in ["속성정의", "컬럼정의"]:
                            if not select_query(db_path, f"SELECT name FROM sqlite_master WHERE name='{tb}'").empty:
                                if select_query(db_path, f"SELECT name FROM sqlite_master WHERE name='{tb}_FULL'").empty: 
                                    if not execute_query(db_path, f"CREATE TABLE {tb}_FULL AS SELECT * FROM {tb}"): prep_success = False
                                if not execute_query(db_path, f"DROP TABLE IF EXISTS {tb}"): prep_success = False
                                if not execute_query(db_path, f"CREATE TABLE {tb} AS SELECT * FROM {tb}_FULL"): prep_success = False
                                if is_expert and not select_query(db_path, "SELECT name FROM sqlite_master WHERE name='표준화대상테이블'").empty:
                                    if not execute_query(db_path, f"DELETE FROM {tb} WHERE \"테이블(영문)\" IN (SELECT TABLE_NAME FROM 표준화대상테이블 WHERE STANDARD_YN='N')"): prep_success = False
                        progress.done()
                        
                        comp_success = check_compliance(db_path, progress)
                        if prep_success and comp_success:
                            st.session_state['last_run_comp'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            st.success("✅ 점검 완료!")
                            import time; time.sleep(1.0)
                            st.rerun()
                        else:
                            st.warning("⚠️ 준수 점검 중 일부 오류가 발생했습니다.")
            
            has_comp_res = not select_query(db_path, "SELECT name FROM sqlite_master WHERE name='점검_속성표준준수'").empty
            if has_comp_res:
                st.divider()
                sub_titles = ["표준용어 미준수", "표준도메인 미준수", "🔍 전체 데이터"]
                sub_tabs = st.tabs(sub_titles)
                
                with sub_tabs[0]:
                    df = select_query(db_path, "SELECT * FROM 점검_속성표준준수 WHERE 점검결과 <> '일치'")
                    if not df.empty: st.dataframe(sorted_df(df), use_container_width=True)
                    else: st.success("준수!")
                with sub_tabs[1]:
                    # 엔터티/테이블 정보 제외 및 DISTINCT 처리
                    query = """
                        SELECT DISTINCT 
                            "컬럼(영문)", "속성(한글)", "속성(데이터타입)", 
                            "용어", "용어약어", "용어도메인", 
                            "도메인", "데이터타입", "데이터길이", "데이터소수점", 
                            "점검결과(도메인)"
                        FROM 점검_속성표준도메인준수 
                        WHERE "점검결과(도메인)" <> '일치'
                    """
                    df = select_query(db_path, query)
                    if not df.empty: st.dataframe(sorted_df(df), use_container_width=True)
                    else: st.success("준수!")
                with sub_tabs[2]:
                    c1, c2 = st.columns(2)
                    if c1.button("All_용어", key="btn_all_term"): st.session_state.show_all_comp = "ALL_용어"
                    if c2.button("속성정의", key="btn_attr_def"): st.session_state.show_all_comp = "속성정의"
                    m = st.session_state.get('show_all_comp', 'ALL_용어')
                    kw = st.text_input(f"🔍 {m} 검색", key="txt_search_comp")
                    df = select_query(db_path, f"SELECT * FROM {m}") if not select_query(db_path, f"SELECT name FROM sqlite_master WHERE name='{m}'").empty else pd.DataFrame()
                    if kw and not df.empty: df = df[df.astype(str).apply(lambda r: r.str.contains(kw, case=False).any(), axis=1)]
                    st.dataframe(df, use_container_width=True)
