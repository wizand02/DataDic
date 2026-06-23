import streamlit as st
import pandas as pd
import sqlite3
import os
import re
from modules.db_utils import execute_query, select_query, check_designed_schema, check_impl_schema, check_schema_comp, DESIGN_SQL_DICT, DESIGN_QUERY_LOOKUP, ensure_target_table_exists

# 설계점검 대상 테이블 기본 스키마
TARGET_TABLE_SCHEMAS_DSN = {
    "속성정의": ["엔터티(한글)", "테이블(영문)", "컬럼(영문)", "속성(한글)", "속성(데이터타입)", "식별자여부"],
    "컬럼정의": ["엔터티(한글)", "테이블(영문)", "컬럼(영문)", "속성(한글)", "컬럼(데이터타입)", "PK"]
}


def sorted_df(df):
    """1열(첫 번째 컬럼) 기준 오름차순 정렬. 정렬 불가한 경우 원본 반환."""
    if df.empty or len(df.columns) == 0:
        return df
    try:
        return df.sort_values(by=df.columns[0], na_position="last").reset_index(drop=True)
    except Exception:
        return df

def load_excel_to_ori_dsn(db_path, uploaded_file):
    """업로드된 엑셀 파일의 모든 시트를 ORI_ 로드 (설계점검용)"""
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

def reset_dsn_check_state():
    """파일 업로드 변경 시 매핑 상태 등 관련 세션 초기화"""
    if 'dsn_check_loaded_sheets' in st.session_state:
        del st.session_state['dsn_check_loaded_sheets']
    if 'dsn_check_mapped_status' in st.session_state:
        del st.session_state['dsn_check_mapped_status']

def drop_design_check_results(db_path):
    """새로운 데이터 매핑/적재 시 기존 점검 결과 초기화"""
    tables_to_drop = [
        "점검_설계_01_속성컬럼비교",
        "점검_설계_02_컬럼속성비교",
        "점검_설계_03_속성도메인비교",
        "점검_설계_04_컬럼도메인비교",
        "점검_구현_01_속성컬럼비교",
        "점검_구현_02_컬럼속성비교",
        "점검_구현_03_속성도메인비교",
        "점검_구현_04_컬럼도메인비교",
        "점검_설계구현비교",
        "점검_설계구현도메인비교"
    ]
    for tb in tables_to_drop:
        execute_query(db_path, f"DROP TABLE IF EXISTS {tb}")

def auto_map_and_save_dsn(db_path, loaded_sheets):
    target_options = list(TARGET_TABLE_SCHEMAS_DSN.keys())
    for sheet in loaded_sheets:
        ori_tb_name = f"ORI_{sheet}"
        if sheet in target_options:
            selected_target = sheet
        else:
            continue
        
        target_columns = TARGET_TABLE_SCHEMAS_DSN[selected_target]
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
        execute_query(db_path, f"DROP TABLE IF EXISTS {selected_target}_FULL")
        execute_query(db_path, create_sql)
        
        if mapped_targets:
            insert_sql = f"INSERT INTO {selected_target} ({', '.join(mapped_targets)}) SELECT {', '.join(mapped_sources)} FROM {ori_tb_name};"
            execute_query(db_path, insert_sql)
        
        st.session_state['dsn_check_mapped_status'][sheet] = True
        
    drop_design_check_results(db_path)

def show_db_design_check():
    # 프로젝트 설정 체크
    if 'current_project_path' not in st.session_state or not st.session_state.current_project_path:
        st.header("🛠️ DB설계점검")
        st.warning("⚠️ [설정] 탭에서 먼저 프로젝트 경로를 지정해 주세요.")
        return

    db_path = st.session_state.get('current_db_path')
    if not db_path or not os.path.exists(db_path):
        st.header("🛠️ DB설계점검")
        st.error("⚠️ 데이터베이스 파일이 존재하지 않습니다. [설정]에서 다시 저장해 주세요.")
        return

    col_h1, col_h2 = st.columns([0.8, 0.2])
    with col_h1:
        st.header("🛠️ DB설계점검")
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
                    key="btn_download_standards_template_top_dsn"
                )

    is_expert = st.session_state.get('app_mode_toggle', False)

    # 탭 생성
    if is_expert:
        tab_titles = ["📥 DB설계 기초데이터적재", "⚙️ 점검대상 설정", "📋 설계 점검", "💻 구현 점검", "⚖️ 설계/구현 비교점검"]
    else:
        tab_titles = ["📥 DB설계 기초데이터적재", "📋 설계 점검", "💻 구현 점검", "⚖️ 설계/구현 비교점검"]
    
    tabs = st.tabs(tab_titles)
    
    # 탭 변수 설정 (동적 인덱스)
    idx_load = tab_titles.index("📥 DB설계 기초데이터적재")
    idx_setting = tab_titles.index("⚙️ 점검대상 설정") if is_expert else -1
    idx_design_check = tab_titles.index("📋 설계 점검")
    idx_impl_check = tab_titles.index("💻 구현 점검")
    idx_compare_check = tab_titles.index("⚖️ 설계/구현 비교점검")

    with tabs[idx_load]:
        with st.container():
            st.markdown("##### 엑셀 데이터 업로드 및 테이블 매핑")

            # 로딩 오버레이 CSS
            st.markdown("""
            <style>
            .dsn-loading-overlay {
                position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
                background: rgba(0,0,0,0.5); z-index: 9999;
                display: flex; flex-direction: column;
                align-items: center; justify-content: center;
            }
            .dsn-loading-box {
                background: white; border-radius: 16px; padding: 40px 56px;
                text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            }
            .dsn-loading-spinner { font-size: 3rem; margin-bottom: 16px; }
            .dsn-loading-text { font-size: 1.1rem; font-weight: 600; color: #333; }
            .dsn-loading-sub  { font-size: 0.9rem; color: #666; margin-top: 6px; }
            </style>
            """, unsafe_allow_html=True)

            overlay_placeholder = st.empty()

            uploaded_file = st.file_uploader(
                "DB설계용 엑셀 파일 선택",
                type=["xlsx", "xls"],
                key="dsn_check_uploader",
                on_change=reset_dsn_check_state
            )

            if uploaded_file:
                if st.button("파일업로드 및 원본데이터적재", use_container_width=True, key="btn_upload_ori_dsn"):
                    overlay_placeholder.markdown("""
                    <div class='dsn-loading-overlay'>
                      <div class='dsn-loading-box'>
                        <div class='dsn-loading-spinner'>⚙️</div>
                        <div class='dsn-loading-text'>데이터 적재 중...</div>
                        <div class='dsn-loading-sub'>잠시만 기다려 주세요. 창을 닫지 마세요.</div>
                      </div>
                    </div>""", unsafe_allow_html=True)

                    with st.spinner("파일 적재 중..."):
                        loaded = load_excel_to_ori_dsn(db_path, uploaded_file)
                    st.session_state['dsn_check_loaded_sheets'] = loaded
                    if 'dsn_check_mapped_status' not in st.session_state:
                        st.session_state['dsn_check_mapped_status'] = {}
                    for s in loaded:
                        st.session_state['dsn_check_mapped_status'][s] = False

                    if not is_expert:
                        with st.spinner("심플 모드: 자동 매핑 및 저장 중..."):
                            auto_map_and_save_dsn(db_path, loaded)
                        overlay_placeholder.empty()
                        import time
                        st.toast(f"✅ {len(loaded)}개 시트 자동 매핑/저장 완료!", icon="✅")
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        overlay_placeholder.empty()
                        st.toast(f"✅ {len(loaded)}개 시트 ORI 테이블 적재 완료!", icon="✅")
                        st.rerun()

                loaded_sheets = st.session_state.get('dsn_check_loaded_sheets', [])

                if loaded_sheets and is_expert:
                    if 'dsn_check_mapped_status' not in st.session_state:
                        st.session_state['dsn_check_mapped_status'] = {s: False for s in loaded_sheets}

                    st.divider()
                    st.markdown("#### 워크시트별 타겟 테이블 매핑")

                    # 타겟 테이블 옵션 ('속성정의', '컬럼정의')
                    target_options = list(TARGET_TABLE_SCHEMAS_DSN.keys())

                    # 일괄 자동 매핑 및 저장
                    if st.button("🚀 전체 워크시트 자동 매핑 및 저장", type="primary", use_container_width=True, key="btn_auto_map_all_dsn"):
                        with st.spinner("전체 워크시트를 자동 매핑하여 저장합니다..."):
                            auto_map_and_save_dsn(db_path, loaded_sheets)
                        st.toast("✅ 전체 워크시트 자동 매핑 및 저장 완료!", icon="✅")
                        import time; time.sleep(1.5)
                        st.rerun()

                    st.write("")
                    
                    # 시트별 매핑 Expander
                    for idx, sheet in enumerate(loaded_sheets):
                        ori_tb_name = f"ORI_{sheet}"
                        is_mapped = st.session_state['dsn_check_mapped_status'].get(sheet, False)
                        status_icon = "✅ 완료" if is_mapped else "⏳ 대기"
                        expander_title = f"📝 시트: {sheet} (👉 {ori_tb_name}) - {status_icon}"
                        
                        with st.expander(expander_title, expanded=False):
                            # 매핑 대상 테이블 선택
                            selected_target = st.selectbox(
                                f"어떤 테이블로 저장하시겠습니까?", 
                                options=target_options, 
                                index=target_options.index(sheet) if sheet in target_options else 0,
                                key=f"dsn_target_sel_{idx}"
                            )
                            
                            target_columns = TARGET_TABLE_SCHEMAS_DSN[selected_target]
                            
                            # ORI 테이블의 실제 컬럼들 가져오기
                            ori_cols_df = select_query(db_path, f"PRAGMA table_info({ori_tb_name})")
                            if not ori_cols_df.empty:
                                src_columns = ori_cols_df['name'].tolist()
                            else:
                                src_columns = []
                            
                            st.markdown(f"**[{ori_tb_name}] 컬럼 매핑 ➔ [{selected_target}]**")
                            
                            mapping_result = {}
                            
                            # 데이터 샘플(최상단 1개 행) 조회
                            sample_row = {}
                            if len(src_columns) > 0:
                                sample_df = select_query(db_path, f"SELECT * FROM {ori_tb_name} LIMIT 1")
                                if not sample_df.empty:
                                    sample_row = sample_df.iloc[0].to_dict()
                            
                            # 컬럼 매핑 UI
                            for i, src_col in enumerate(src_columns):
                                c1, c2, c3 = st.columns([0.4, 0.1, 0.5])
                                with c1:
                                    sample_val = sample_row.get(src_col, "NULL/없음")
                                    st.markdown(f"**{src_col}**", unsafe_allow_html=True)
                                    st.markdown(f"<span style='color:gray; font-size:0.8rem;'>예: {sample_val}</span>", unsafe_allow_html=True)
                                with c2:
                                    st.markdown("<div style='padding-top:10px;text-align:center;'>➔</div>", unsafe_allow_html=True)
                                with c3:
                                    default_idx = target_columns.index(src_col) + 1 if src_col in target_columns else 0
                                    mapped_col = st.selectbox(
                                        "타겟 컬럼 선택",
                                        options=["(매핑 안 함)"] + target_columns,
                                        index=default_idx,
                                        label_visibility="collapsed",
                                        key=f"dsn_map_{idx}_{i}"
                                    )
                                    mapping_result[src_col] = mapped_col if mapped_col != "(매핑 안 함)" else None
                                    
                            if st.button("저장 실행", key=f"dsn_btn_save_{idx}"):
                                # 개별 수동 저장 시 타겟 테이블 드롭 및 생성
                                col_defs = [f'"{col}" VARCHAR(500)' for col in target_columns]
                                create_sql = f"DROP TABLE IF EXISTS {selected_target};\nCREATE TABLE {selected_target} (\n  " + ",\n  ".join(col_defs) + "\n);"
                                
                                execute_query(db_path, f"DROP TABLE IF EXISTS {selected_target}_FULL") 
                                execute_query(db_path, create_sql)
                                
                                # 매핑 결과에 따라 INSERT 생성
                                mapped_targets = []
                                mapped_sources = []
                                for src_c, tgt_c in mapping_result.items():
                                    if tgt_c:
                                        mapped_targets.append(f'"{tgt_c}"')
                                        mapped_sources.append(f'"{src_c}"')
                                        
                                if mapped_targets:
                                    insert_sql = f"INSERT INTO {selected_target} ({', '.join(mapped_targets)}) SELECT {', '.join(mapped_sources)} FROM {ori_tb_name};"
                                    execute_query(db_path, insert_sql)
                                    st.session_state['dsn_check_mapped_status'][sheet] = True
                                    drop_design_check_results(db_path)
                                    st.toast(f"✅ `{selected_target}` 테이블에 데이터가 성공적으로 적재되었습니다.")
                                    st.rerun()
                                else:
                                    st.session_state['dsn_check_mapped_status'][sheet] = True
                                    drop_design_check_results(db_path)
                                    st.toast(f"⚠️ `{selected_target}` 매핑된 컬럼이 없어 빈 테이블만 생성되었습니다.")
                                    st.rerun()

    if is_expert and idx_setting != -1:
        with tabs[idx_setting]:
            with st.container():
                st.markdown("##### ⚙️ 설계점검 대상 테이블 설정")
        
                # Check if "속성정의" or "컬럼정의" table exists
                check_tb1 = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='속성정의'")
                check_tb2 = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='컬럼정의'")
                if check_tb1.empty and check_tb2.empty:
                    st.warning("⚠️ '속성정의' 또는 '컬럼정의' 테이블이 존재하지 않습니다. 먼저 기초데이터적재 탭에서 데이터를 업로드하고 매핑해주세요.")
                else:
                    # 1. 속성정의 및 컬럼정의에서 고유 테이블 목록 중복 제거하여 추출
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
                        # 2. 기존 모델점검대상테이블 조회
                        exist_tb = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='모델점검대상테이블'")
                        if not exist_tb.empty:
                            exist_df = select_query(db_path, "SELECT TABLE_NAME, ENTITY_NAME, STANDARD_YN, COMMENT FROM 모델점검대상테이블")
                            # 기존 모델점검대상테이블 내부에 중복이 있을 수 있으므로 제거
                            if not exist_df.empty:
                                exist_df = exist_df.drop_duplicates(subset=['TABLE_NAME'], keep='last')
                        else:
                            exist_df = pd.DataFrame(columns=["TABLE_NAME", "ENTITY_NAME", "STANDARD_YN", "COMMENT"])
                
                        # 3. 데이터 병합 (기존 설정값이 있다면 유지)
                        if not exist_df.empty:
                            merged_df = pd.merge(src_df, exist_df[['TABLE_NAME', 'STANDARD_YN', 'COMMENT']], on="TABLE_NAME", how="left")
                            merged_df['설계점검대상'] = merged_df['STANDARD_YN'].fillna('Y').apply(lambda x: True if x == 'Y' else False)
                            merged_df['제외사유(COMMENT)'] = merged_df['COMMENT'].fillna('')
                        else:
                            merged_df = src_df.copy()
                            merged_df['설계점검대상'] = True
                            merged_df['제외사유(COMMENT)'] = ""
                
                        # --- 요약 통계 표시 ---
                        total_cnt = len(merged_df)
                        target_cnt = merged_df['설계점검대상'].sum()
                        non_target_cnt = total_cnt - target_cnt
                        st.info(f"📊 **설계점검 대상 통계** : 전체 **{total_cnt:,}**개 ┃ ✅ 대상(Y): **{target_cnt:,}**개 ┃ ❌ 비대상(N): **{non_target_cnt:,}**개")
                        st.write("")
                
                        # --- 필터 및 일괄 업데이트 ---
                        col_type, col_status, col_search, col_b1, col_b2 = st.columns([0.15, 0.15, 0.3, 0.2, 0.2])
                        with col_type:
                            search_col = st.selectbox("검색 기준", ["전체(엔터티+테이블)", "엔터티명", "테이블명"], key="dsn_target_search_type")
                        with col_status:
                            search_status = st.selectbox("대상 여부", ["전체", "대상(Y)", "비대상(N)"], key="dsn_target_search_status")
                        with col_search:
                            search_kw = st.text_input("🔍 검색어 (SQL LIKE: %, _ 활용)", key="dsn_target_search")

                        mask = pd.Series(True, index=merged_df.index)
                
                        # 상태 필터 적용
                        if search_status == "대상(Y)":
                            mask = mask & (merged_df['설계점검대상'] == True)
                        elif search_status == "비대상(N)":
                            mask = mask & (merged_df['설계점검대상'] == False)
                    
                        if search_kw:
                            # SQL LIKE 패턴을 정규표현식으로 변환
                            escaped_kw = re.escape(search_kw)
                            regex_pattern = "^" + escaped_kw.replace("\\%", ".*").replace("%", ".*").replace("\\_", ".").replace("_", ".") + "$"
                    
                            if search_col == "엔터티명":
                                kw_mask = merged_df['ENTITY_NAME'].astype(str).str.match(regex_pattern, case=False, na=False)
                            elif search_col == "테이블명":
                                kw_mask = merged_df['TABLE_NAME'].astype(str).str.match(regex_pattern, case=False, na=False)
                            else:
                                kw_mask = merged_df['TABLE_NAME'].astype(str).str.match(regex_pattern, case=False, na=False) | \
                                          merged_df['ENTITY_NAME'].astype(str).str.match(regex_pattern, case=False, na=False)
                            mask = mask & kw_mask

                        with col_b1:
                            st.write("")
                            if st.button("✅ 선택 일괄 체크", use_container_width=True, key="dsn_btn_chk_all"):
                                merged_df.loc[mask, '설계점검대상'] = True
                                save_df = merged_df.copy()
                                save_df['STANDARD_YN'] = save_df['설계점검대상'].apply(lambda x: 'Y' if x else 'N')
                                save_df['COMMENT'] = save_df['제외사유(COMMENT)']
                                final_df = save_df[['TABLE_NAME', 'ENTITY_NAME', 'STANDARD_YN', 'COMMENT']]
                        
                                conn = sqlite3.connect(db_path)
                                final_df.to_sql("모델점검대상테이블", conn, if_exists="replace", index=False)
                                conn.close()
                                st.rerun()

                        with col_b2:
                            st.write("")
                            if st.button("❌ 선택 일괄 해제", use_container_width=True, key="dsn_btn_unchk_all"):
                                merged_df.loc[mask, '설계점검대상'] = False
                                save_df = merged_df.copy()
                                save_df['STANDARD_YN'] = save_df['설계점검대상'].apply(lambda x: 'Y' if x else 'N')
                                save_df['COMMENT'] = save_df['제외사유(COMMENT)']
                                final_df = save_df[['TABLE_NAME', 'ENTITY_NAME', 'STANDARD_YN', 'COMMENT']]
                        
                                conn = sqlite3.connect(db_path)
                                final_df.to_sql("모델점검대상테이블", conn, if_exists="replace", index=False)
                                conn.close()
                                st.rerun()

                        # 표시용 데이터프레임 (필터 적용된 것만)
                        display_df = merged_df[mask][['설계점검대상', 'ENTITY_NAME', 'TABLE_NAME', '제외사유(COMMENT)']]
                
                        st.markdown("**(👇 아래 조회된 대상여부를 편집 후, 반드시 아래 저장 버튼을 누르세요)**")
                
                        # 4. 데이터 에디터 표출 (대상여부, 제외사유만 편집 가능)
                        edited_df = st.data_editor(
                            display_df,
                            hide_index=True,
                            use_container_width=True,
                            disabled=["ENTITY_NAME", "TABLE_NAME"],
                            column_config={
                                "설계점검대상": st.column_config.CheckboxColumn("대상여부(Y/N)", width="small"),
                                "제외사유(COMMENT)": st.column_config.TextColumn("제외사유(N일 경우)", width="large"),
                                "ENTITY_NAME": st.column_config.TextColumn("엔터티명(한글)"),
                                "TABLE_NAME": st.column_config.TextColumn("테이블명(영문)")
                            },
                            key="dsn_check_target_editor"
                        )
                
                        # 저장/취소 버튼 레이아웃
                        col_save, col_cancel = st.columns([0.8, 0.2])
                        with col_save:
                            btn_save = st.button("💾 화면의 대상설정 저장 실행", type="primary", use_container_width=True, key="dsn_btn_save_target")
                        with col_cancel:
                            btn_cancel = st.button("🔄 취소(원래대로)", use_container_width=True, key="dsn_btn_cancel_target")
                
                        if btn_cancel:
                            if 'dsn_check_target_editor' in st.session_state:
                                del st.session_state['dsn_check_target_editor']
                            st.rerun()
                    
                        if btn_save:
                            # 편집된 항목(edited_df)을 전체 원본(merged_df)에 반영
                            merged_df.set_index('TABLE_NAME', inplace=True)
                            edited_df_copy = edited_df.copy()
                            edited_df_copy.set_index('TABLE_NAME', inplace=True)
                    
                            merged_df.update(edited_df_copy)
                            merged_df.reset_index(inplace=True)
                    
                            save_df = merged_df.copy()
                            save_df['STANDARD_YN'] = save_df['설계점검대상'].apply(lambda x: 'Y' if x else 'N')
                            save_df['COMMENT'] = save_df['제외사유(COMMENT)']
                    
                            final_df = save_df[['TABLE_NAME', 'ENTITY_NAME', 'STANDARD_YN', 'COMMENT']]
                    
                            try:
                                conn = sqlite3.connect(db_path)
                                final_df.to_sql("모델점검대상테이블", conn, if_exists="replace", index=False)
                                conn.close()
                                st.success("✅ 설계점검 대상 테이블 목록이 성공적으로 업데이트되었습니다.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 저장 중 오류 발생: {e}")

    with tabs[idx_design_check]:
        with st.container():
            st.markdown("##### 📋 설계 점검")
            st.info("💡 속성정의를 기준으로 점검하는 내용/결과를 보여줍니다.")
            
            # 기본 테이블 여부 체크
            impl_base_tb = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='속성정의'")
            if impl_base_tb.empty:
                st.warning("⚠️ '속성정의' (설계/논리) 데이터가 없습니다. 먼저 기초데이터적재를 진행해 주세요.")
            else:
                # 1. 점검 대상 개요 표 표시
                try:
                    ensure_target_table_exists(db_path, "모델점검대상테이블", ["속성정의", "컬럼정의"])
                    overview_query = """
                    SELECT '속성정의' as 구분, 
                           count(distinct "테이블(영문)") as 테이블수, 
                           count("컬럼(영문)") as 컬럼수,
                           count(distinct CASE WHEN "식별자여부" = 'Y' THEN "테이블(영문)" END) as PK테이블수,
                           count(CASE WHEN "식별자여부" = 'Y' THEN 1 END) as PK컬럼수
                    FROM 속성정의
                    UNION ALL
                    SELECT '점검대상' as 구분, 
                           count(distinct "TABLE_NAME") as 테이블수, 
                           (SELECT count(*) FROM 속성정의 A JOIN 모델점검대상테이블 B ON A."테이블(영문)" = B.TABLE_NAME WHERE B.STANDARD_YN = 'Y') as 컬럼수,
                           (SELECT count(distinct A."테이블(영문)") FROM 속성정의 A JOIN 모델점검대상테이블 B ON A."테이블(영문)" = B.TABLE_NAME WHERE B.STANDARD_YN = 'Y' AND A."식별자여부" = 'Y') as PK테이블수,
                           (SELECT count(*) FROM 속성정의 A JOIN 모델점검대상테이블 B ON A."테이블(영문)" = B.TABLE_NAME WHERE B.STANDARD_YN = 'Y' AND A."식별자여부" = 'Y') as PK컬럼수
                    FROM 모델점검대상테이블 WHERE STANDARD_YN = 'Y';
                    """
                    summary_df = select_query(db_path, overview_query)
                    if not summary_df.empty:
                        st.dataframe(summary_df, use_container_width=True)
                except Exception as e:
                    pass

                col_btn_d1, col_btn_d2 = st.columns([0.2, 0.8])
                with col_btn_d1:
                    if st.button("🗑️ 이전결과 초기화", key="btn_reset_design_chk", use_container_width=True):
                        for tb in ["점검_설계_01_속성컬럼비교", "점검_설계_02_컬럼속성비교", "점검_설계_03_속성도메인비교", "점검_설계_04_컬럼도메인비교"]:
                            execute_query(db_path, f"DROP TABLE IF EXISTS {tb}")
                        key = f"last_run_design_chk_{db_path}"
                        if key in st.session_state: del st.session_state[key]
                        st.toast("✅ [설계점검] 결과가 초기화되었습니다.")
                        st.rerun()
                with col_btn_d2:
                    if st.button("🚀 DB 모델 점검", type="primary", use_container_width=True, key="btn_run_design_chk"):
                        with st.spinner("설계 점검 실행 중..."):
                            try:
                                # 1. 대상테이블 목록(모델점검대상테이블) 필터링 반영
                                check_designed_schema(db_path)
                                st.session_state[f"last_run_design_chk_{db_path}"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                                st.success("✅ 설계 점검 완료!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 설계 점검 수행 중 오류: {e}")

                last_run = st.session_state.get(f"last_run_design_chk_{db_path}")
                if last_run:
                    st.markdown(f"<div style='text-align: right; font-size: 0.8rem; color: gray;'>최종 수행 완료 시각: {last_run}</div>", unsafe_allow_html=True)

                # 점검 결과 테이블들이 있는지 확인
                chk_design_ready = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='점검_설계_01_속성컬럼비교'")
                
                if not chk_design_ready.empty:
                    st.divider()
                    st.subheader("📝 설계 구조 점검 결과")
                    
                    sub_titles = ["속성명-컬럼명 불일치", "컬럼명-속성명 불일치", "속성명-도메인 불일치", "컬럼명-도메인 불일치"]
                    if is_expert:
                        sub_titles.append("🛠️ 쿼리 조회")
                    
                    sub_tabs = st.tabs(sub_titles)
                    
                    with sub_tabs[0]:
                        st.markdown("##### 1. 속성명-컬럼명 불일치 (설계)")
                        st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_설계_01_속성컬럼비교")), use_container_width=True)
                    with sub_tabs[1]:
                        st.markdown("##### 2. 컬럼명-속성명 불일치 (설계)")
                        st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_설계_02_컬럼속성비교")), use_container_width=True)
                    with sub_tabs[2]:
                        st.markdown("##### 3. 속성명-도메인 불일치 (설계)")
                        st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_설계_03_속성도메인비교")), use_container_width=True)
                    with sub_tabs[3]:
                        st.markdown("##### 4. 컬럼명-도메인 불일치 (설계)")
                        st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_설계_04_컬럼도메인비교")), use_container_width=True)
                    if is_expert:
                        with sub_tabs[4]:
                            st.info("💡 설계 점검과 관련된 스크립트를 조회합니다.")
                            for title, full_script in DESIGN_QUERY_LOOKUP.items():
                                if "설계" in title and "구현" not in title:
                                    with st.expander(f"📌 {title}", expanded=False):
                                        st.code(full_script.strip(), language="sql")
                            
                            st.divider()
                            st.markdown("##### ⚙️ 개별 점검용 상세 SQL (CREATE TABLE AS)")
                            for tb_name, select_sql in DESIGN_SQL_DICT.items():
                                if "설계" in tb_name and "비교" in tb_name and tb_name not in ["점검_설계구현비교", "점검_설계구현도메인비교"]:
                                    with st.expander(f"🔍 {tb_name}", expanded=False):
                                        st.code(f"CREATE TABLE {tb_name} AS\n" + select_sql.strip(), language="sql")

    with tabs[idx_impl_check]:
        with st.container():
            st.markdown("##### 💻 구현 점검")
            st.info("💡 컬럼정의를 기준으로 점검하는 내용/결과를 보여줍니다.")
            
            # 기본 테이블 여부 체크
            impl_base_tb = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='컬럼정의'")
            if impl_base_tb.empty:
                st.warning("⚠️ '컬럼정의' (구현/물리) 데이터가 없습니다. 먼저 기초데이터적재를 진행해 주세요.")
            else:
                # 1. 점검 대상 개요 표 표시
                try:
                    ensure_target_table_exists(db_path, "모델점검대상테이블", ["속성정의", "컬럼정의"])
                    overview_query = """
                    SELECT '컬럼정의' as 구분, 
                           count(distinct "테이블(영문)") as 테이블수, 
                           count("컬럼(영문)") as 컬럼수,
                           count(distinct CASE WHEN "PK" IS NOT NULL AND "PK" <> '' THEN "테이블(영문)" END) as PK테이블수,
                           count(CASE WHEN "PK" IS NOT NULL AND "PK" <> '' THEN 1 END) as PK컬럼수
                    FROM 컬럼정의
                    UNION ALL
                    SELECT '점검대상' as 구분, 
                           count(distinct "TABLE_NAME") as 테이블수, 
                           (SELECT count(*) FROM 컬럼정의 A JOIN 모델점검대상테이블 B ON A."테이블(영문)" = B.TABLE_NAME WHERE B.STANDARD_YN = 'Y') as 컬럼수,
                           (SELECT count(distinct A."테이블(영문)") FROM 컬럼정의 A JOIN 모델점검대상테이블 B ON A."테이블(영문)" = B.TABLE_NAME WHERE B.STANDARD_YN = 'Y' AND A."PK" IS NOT NULL AND A."PK" <> '') as PK테이블수,
                           (SELECT count(*) FROM 컬럼정의 A JOIN 모델점검대상테이블 B ON A."테이블(영문)" = B.TABLE_NAME WHERE B.STANDARD_YN = 'Y' AND A."PK" IS NOT NULL AND A."PK" <> '') as PK컬럼수
                    FROM 모델점검대상테이블 WHERE STANDARD_YN = 'Y';
                    """
                    summary_df = select_query(db_path, overview_query)
                    if not summary_df.empty:
                        st.dataframe(summary_df, use_container_width=True)
                except Exception as e:
                    pass

                col_btn_i1, col_btn_i2 = st.columns([0.2, 0.8])
                with col_btn_i1:
                    if st.button("🗑️ 이전결과 초기화", key="btn_reset_impl_chk", use_container_width=True):
                        for tb in ["점검_구현_01_속성컬럼비교", "점검_구현_02_컬럼속성비교", "점검_구현_03_속성도메인비교", "점검_구현_04_컬럼도메인비교"]:
                            execute_query(db_path, f"DROP TABLE IF EXISTS {tb}")
                        key = f"last_run_impl_chk_{db_path}"
                        if key in st.session_state: del st.session_state[key]
                        st.toast("✅ [구현점검] 결과가 초기화되었습니다.")
                        st.rerun()
                with col_btn_i2:
                    if st.button("🚀 DB 모델 구현 점검", type="primary", use_container_width=True, key="btn_run_impl_chk"):
                        with st.spinner("구현 점검 실행 중..."):
                            try:
                                check_impl_schema(db_path)
                                st.session_state[f"last_run_impl_chk_{db_path}"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                                st.success("✅ 구현 점검 완료!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 구현 점검 수행 중 오류: {e}")

                last_run = st.session_state.get(f"last_run_impl_chk_{db_path}")
                if last_run:
                    st.markdown(f"<div style='text-align: right; font-size: 0.8rem; color: gray;'>최종 수행 완료 시각: {last_run}</div>", unsafe_allow_html=True)

                # 점검 결과 테이블들이 있는지 확인
                chk_impl_ready = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='점검_구현_01_속성컬럼비교'")
                
                if not chk_impl_ready.empty:
                    st.divider()
                    st.subheader("📝 구현 구조 점검 결과")
                    
                    sub_titles = ["속성명-컬럼명 불일치", "컬럼명-속성명 불일치", "속성명-도메인 불일치", "컬럼명-도메인 불일치"]
                    if is_expert:
                        sub_titles.append("🛠️ 쿼리 조회")
                    
                    sub_tabs = st.tabs(sub_titles)
                    
                    with sub_tabs[0]:
                        st.markdown("##### 1. 속성명-컬럼명 불일치 (구현)")
                        st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_구현_01_속성컬럼비교")), use_container_width=True)
                    with sub_tabs[1]:
                        st.markdown("##### 2. 컬럼명-속성명 불일치 (구현)")
                        st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_구현_02_컬럼속성비교")), use_container_width=True)
                    with sub_tabs[2]:
                        st.markdown("##### 3. 속성명-도메인 불일치 (구현)")
                        st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_구현_03_속성도메인비교")), use_container_width=True)
                    with sub_tabs[3]:
                        st.markdown("##### 4. 컬럼명-도메인 불일치 (구현)")
                        st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_구현_04_컬럼도메인비교")), use_container_width=True)
                    if is_expert:
                        with sub_tabs[4]:
                            st.info("💡 구현 점검과 관련된 스크립트를 조회합니다.")
                            for title, full_script in DESIGN_QUERY_LOOKUP.items():
                                if "구현" in title:
                                    with st.expander(f"📌 {title}", expanded=False):
                                        st.code(full_script.strip(), language="sql")
                            
                            st.divider()
                            st.markdown("##### ⚙️ 개별 점검용 상세 SQL (CREATE TABLE AS)")
                            for tb_name, select_sql in DESIGN_SQL_DICT.items():
                                if "구현" in tb_name and "비교" in tb_name and tb_name not in ["점검_설계구현비교", "점검_설계구현도메인비교"]:
                                    with st.expander(f"🔍 {tb_name}", expanded=False):
                                        st.code(f"CREATE TABLE {tb_name} AS\n" + select_sql.strip(), language="sql")

    with tabs[idx_compare_check]:
        with st.container():
            st.markdown("##### ⚖️ 설계/구현 비교점검")
            st.info("💡 속성정의와 컬럼정의의 비교 점검 결과를 보여줍니다.")
            
            # 1. 점검 실행 기능
            impl_base_tb1 = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='속성정의'")
            impl_base_tb2 = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='컬럼정의'")
            
            if impl_base_tb1.empty or impl_base_tb2.empty:
                st.warning("⚠️ '속성정의' 및 '컬럼정의' 데이터가 모두 필요합니다. 먼저 기초데이터적재를 진행해 주세요.")
            else:
                # 1. 점검 대상 개요 표 표시
                try:
                    ensure_target_table_exists(db_path, "모델점검대상테이블", ["속성정의", "컬럼정의"])
                    overview_query = """
                    SELECT '속성정의' as 구분, 
                           count(distinct "테이블(영문)") as 테이블수, 
                           count("컬럼(영문)") as 컬럼수,
                           count(distinct CASE WHEN "식별자여부" = 'Y' THEN "테이블(영문)" END) as PK테이블수,
                           count(CASE WHEN "식별자여부" = 'Y' THEN 1 END) as PK컬럼수
                    FROM 속성정의
                    UNION ALL
                    SELECT '컬럼정의' as 구분, 
                           count(distinct "테이블(영문)") as 테이블수, 
                           count("컬럼(영문)") as 컬럼수,
                           count(distinct CASE WHEN "PK" IS NOT NULL AND "PK" <> '' THEN "테이블(영문)" END) as PK테이블수,
                           count(CASE WHEN "PK" IS NOT NULL AND "PK" <> '' THEN 1 END) as PK컬럼수
                    FROM 컬럼정의
                    UNION ALL
                    SELECT '점검대상' as 구분, 
                           count(distinct "TABLE_NAME") as 테이블수, 
                           (SELECT count(*) FROM 속성정의 A JOIN 모델점검대상테이블 B ON A."테이블(영문)" = B.TABLE_NAME WHERE B.STANDARD_YN = 'Y') as 컬럼수,
                           (SELECT count(distinct A."테이블(영문)") FROM 속성정의 A JOIN 모델점검대상테이블 B ON A."테이블(영문)" = B.TABLE_NAME WHERE B.STANDARD_YN = 'Y' AND A."식별자여부" = 'Y') as PK테이블수,
                           (SELECT count(*) FROM 속성정의 A JOIN 모델점검대상테이블 B ON A."테이블(영문)" = B.TABLE_NAME WHERE B.STANDARD_YN = 'Y' AND A."식별자여부" = 'Y') as PK컬럼수
                    FROM 모델점검대상테이블 WHERE STANDARD_YN = 'Y';
                    """
                    summary_df = select_query(db_path, overview_query)
                    if not summary_df.empty:
                        st.markdown("**(⚖️ 설계/구현 비교 점검대상 개요)**")
                        st.dataframe(summary_df, use_container_width=True)
                except Exception as e:
                    pass

                col_btn_cp1, col_btn_cp2 = st.columns([0.2, 0.8])
                with col_btn_cp1:
                    if st.button("🗑️ 이전결과 초기화", key="btn_reset_comp_chk", use_container_width=True):
                        for tb in ["점검_설계구현비교", "점검_설계구현도메인비교"]:
                            execute_query(db_path, f"DROP TABLE IF EXISTS {tb}")
                        key = f"last_run_comp_chk_{db_path}"
                        if key in st.session_state: del st.session_state[key]
                        st.toast("✅ [설계/구현 비교점검] 결과가 초기화되었습니다.")
                        st.rerun()
                with col_btn_cp2:
                    if st.button("🚀 설계 / 구현 비교 점검 실행", type="primary", use_container_width=True, key="btn_run_comp_chk"):
                        with st.spinner("비교 점검 실행 중..."):
                            try:
                                check_schema_comp(db_path)
                                st.session_state[f"last_run_comp_chk_{db_path}"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                                st.success("✅ 비교 점검 완료!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 비교 점검 수행 중 오류: {e}")

                last_run = st.session_state.get(f"last_run_comp_chk_{db_path}")
                if last_run:
                    st.markdown(f"<div style='text-align: right; font-size: 0.8rem; color: gray;'>최종 수행 완료 시각: {last_run}</div>", unsafe_allow_html=True)

                # 2. 결과 표시 영역
                chk_comp_ready = select_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name='점검_설계구현비교'")
                
                if not chk_comp_ready.empty:
                    st.divider()
                    st.subheader("📝 세부 점검 결과")
                    
                    sub_titles = ["설계/구현 누락 비교", "도메인 불일치 비교"]
                    if is_expert:
                        sub_titles.append("🛠️ 쿼리 조회")
                        
                    sub_tabs = st.tabs(sub_titles)
                    
                    with sub_tabs[0]:
                        st.markdown("##### 설계/구현 결과 (누락 중심)")
                        st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_설계구현비교 WHERE 비교결과 <> '일치'")), use_container_width=True)
                        if st.checkbox("전체 데이터 보기 (누락 점검)", key="chk_comp_all_dsn"):
                            st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_설계구현비교")), use_container_width=True)
                    with sub_tabs[1]:
                        st.markdown("##### 설계/구현 데이터타입(도메인) 불일치 내역")
                        st.dataframe(sorted_df(select_query(db_path, "SELECT * FROM 점검_설계구현도메인비교")), use_container_width=True)
                    if is_expert:
                        with sub_tabs[2]:
                            st.info("💡 비교 점검과 관련된 스크립트를 조회합니다.")
                            for title, full_script in DESIGN_QUERY_LOOKUP.items():
                                if "비교" in title and ("도메인" in title or "누락" in title or "설계구현" in title):
                                    with st.expander(f"📌 {title}", expanded=False):
                                        st.code(full_script.strip(), language="sql")
                            
                            st.divider()
                            st.markdown("##### ⚙️ 개별 점검용 상세 SQL (CREATE TABLE AS)")
                            for tb_name, select_sql in DESIGN_SQL_DICT.items():
                                if tb_name in ["점검_설계구현비교", "점검_설계구현도메인비교"]:
                                    with st.expander(f"🔍 {tb_name}", expanded=False):
                                        st.code(f"CREATE TABLE {tb_name} AS\n" + select_sql.strip(), language="sql")
