import streamlit as st
import pandas as pd
import sqlite3
import os
import datetime
import re
import config

def safe_error(msg):
    """Streamlit 환경이면 st.error, 아니면 print 출력"""
    try:
        st.error(msg)
    except:
        print(msg)

def regexp_replace(string, pattern, replacement):
    """SQLite REGEXP_REPLACE UDF 구현 (Source, Pattern, Replacement)"""
    if string is None:
        return None
    try:
        s_val = str(string).strip()
        s_pat = str(pattern).strip()
        s_repl = str(replacement)
        
        # ── 앵커(^, $) 기반 스마트 품질 진단 로직 ──
        # 1. 앵커(^ 또는 $)가 포함되어 있고, 부정형 룩어헤드('(?!')를 포함하지 않는 경우 '검증 모드'
        # 2. 검증 모드에서는 '전체 일치'가 아니면 무조건 교체(replacement) 대상으로 판단
        is_validation_mode = (s_pat.startswith('^') or s_pat.endswith('$')) and '(?!' not in s_pat
        
        if is_validation_mode:
            # 패턴 내에 ^와 $가 명시적으로 없더라도 validation 모드라면 강제로 전체 일치 검사
            # (유저 패턴에 이미 포함되어 있을 확률이 높지만, re.fullmatch로 안전하게 검증)
            if re.fullmatch(s_pat, s_val):
                return s_val  # 정상: 원본 유지
            else:
                return s_repl # 오류: 전체가 일치하지 않음 (fault 등 반환)
        
        # 앵커가 없는 일반 교체 패턴 또는 특수한 부정형 탐지 패턴
        return re.sub(s_pat, s_repl, s_val)
    except:
        return string

def regexp_extract(string, pattern, replacement):
    """SQLite REGEXP_EXTRACT UDF 구현 (Source, Pattern, $n)"""
    if string is None:
        return None
    try:
        s_val = str(string).strip()
        s_pat = str(pattern).strip()
        s_repl = str(replacement).strip()
        
        match = re.search(s_pat, s_val)
        if match:
            # $1, $2 형식을 \1, \2로 변환하여 re.match.expand 활용
            # 이를 통해 '$1-$2' 같은 복합 추출도 가능해짐
            expand_pat = s_repl.replace('$', '\\')
            return match.expand(expand_pat)
    except:
        pass
    return "[오류]" # 추출 실패(미매칭) 시 '[오류]' 반환 -> 리포트에서 오류군으로 그룹화됨

def get_db_connection(db_path):
    """UDF가 등록된 SQLite 연결 반환"""
    conn = sqlite3.connect(db_path)
    # REGEXP_REPLACE(경로, 패턴, 바꿀문자)
    conn.create_function("REGEXP_REPLACE", 3, regexp_replace)
    # REGEXP_EXTRACT(경로, 패턴, $n)
    conn.create_function("REGEXP_EXTRACT", 3, regexp_extract)
    return conn

# --- 글로벌 설정 DB (c:\gndq\gndq.db) 관련 ---

def init_global_config_db():
    """글로벌 설정 DB 및 폴더 생성, 테이블 초기화"""
    db_path = config.GLOBAL_CONFIG_DB_PATH
    db_dir = os.path.dirname(db_path)
    
    try:
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
            
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 최근 프로젝트 및 DB 경로를 저장하는 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recent_project (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                project_path TEXT NOT NULL,
                db_path TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 하위 호환성: db_path 컬럼이 없는 경우 추가
        cursor.execute("PRAGMA table_info(recent_project)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'db_path' not in columns:
            cursor.execute("ALTER TABLE recent_project ADD COLUMN db_path TEXT")

        # 품질 점검 룰을 저장하는 테이블 생성 (글로벌 관리)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS myTool_DQ_Rule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id TEXT,
                rule_title TEXT,
                rule_sub_seq INTEGER,
                rule_detail TEXT,
                detect_pattern TEXT,
                replace_pattern TEXT,
                comment TEXT
            )
        """)
        
        # 테이블이 비어있으면 기본 데이터 삽입
        cursor.execute("SELECT COUNT(*) FROM myTool_DQ_Rule")
        if cursor.fetchone()[0] == 0:
            cursor.executemany("""
                INSERT INTO myTool_DQ_Rule 
                (rule_id, rule_title, rule_sub_seq, rule_detail, detect_pattern, replace_pattern, comment)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, config.DEFAULT_DQ_RULES)
            conn.commit()
        # 앱 설정(모드 등)을 저장하는 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                config_key TEXT PRIMARY KEY,
                config_value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    except Exception as e:
        safe_error(f"❌ 글로벌 설정 DB 초기화 실패: {e}")

def save_app_config(key, value):
    """글로벌 DB에 앱 설정값 저장"""
    db_path = config.GLOBAL_CONFIG_DB_PATH
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO app_config (config_key, config_value, updated_at) 
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(config_key) DO UPDATE SET 
                config_value = excluded.config_value,
                updated_at = CURRENT_TIMESTAMP
        """, (key, str(value)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving app config: {e}")
        return False

def get_app_config(key, default=None):
    """글로벌 DB에서 앱 설정값 조회"""
    db_path = config.GLOBAL_CONFIG_DB_PATH
    if not os.path.exists(db_path):
        return default
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT config_value FROM app_config WHERE config_key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default

def save_recent_project(project_path, db_path=None):
    """최근 프로젝트 및 DB 경로 저장"""
    if not project_path:
        return
    
    project_path = os.path.normpath(project_path)
    if db_path:
        db_path = os.path.normpath(db_path)
    
    init_global_config_db()
    db_path_global = config.GLOBAL_CONFIG_DB_PATH
    
    try:
        conn = sqlite3.connect(db_path_global)
        cursor = conn.cursor()
        
        if db_path:
            cursor.execute("""
                INSERT INTO recent_project (id, project_path, db_path, updated_at)
                VALUES (1, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET 
                    project_path = excluded.project_path,
                    db_path = excluded.db_path,
                    updated_at = CURRENT_TIMESTAMP
            """, (project_path, db_path))
        else:
            # db_path가 없으면 기존 db_path 유지 (COALESCE 사용)
            cursor.execute("""
                INSERT INTO recent_project (id, project_path, updated_at)
                VALUES (1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET 
                    project_path = excluded.project_path,
                    updated_at = CURRENT_TIMESTAMP
            """, (project_path,))
            
        conn.commit()
        conn.close()
    except Exception as e:
        safe_error(f"❌ 최근 프로젝트 정보 저장 실패: {e}")

def get_recent_project():
    """최근 프로젝트 및 DB 경로 조회"""
    db_path = config.GLOBAL_CONFIG_DB_PATH
    if not os.path.exists(db_path):
        return None, None
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT project_path, db_path FROM recent_project WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0], row[1]
        return None, None
    except Exception:
        return None, None

def db_log_print(a_log_msg):
    """단후 로그 출력용 (필요시 파일 기록 추가 가능)"""
    timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    log_message = f"{timestamp} {a_log_msg}"
    if st.session_state.get('IS_DEBUG_MODE', True):
        print(log_message)

def check_project_db():
    """프로젝트 및 DB 설정 체크 공통 함수"""
    if 'current_project_path' not in st.session_state or not st.session_state.current_project_path:
        st.warning("⚠️ [설정] 탭에서 먼저 프로젝트 경로를 지정해 주세요.")
        return None, None

    db_path = st.session_state.get('current_db_path')
    if not db_path or not os.path.exists(db_path):
        st.error("⚠️ 데이터베이스 파일이 존재하지 않습니다. [설정]에서 다시 저장해 주세요.")
        return None, None
        
    return st.session_state.current_project_path, db_path

def execute_query(db_path, query):
    """쿼리 실행기"""
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.executescript(query)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        # Show verbose error for easier debugging
        st.error(f"❌ 쿼리 실행 중 오류 발생: {e}\n\n[실행된 쿼리]\n{query}\n\n[상세 에러]\n{err_msg}")
        return False

def select_query(db_path, query, params=None):
    """Select 쿼리 실행 및 DataFrame 반환"""
    try:
        conn = get_db_connection(db_path)
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df
    except Exception as e:
        # st.error(f"❌ 데이터 조회 중 오류 발생: {e}")
        return pd.DataFrame()

def show_splash(message="데이터를 처리 중입니다..."):
    """풀스크린 스플래시 오버레이 출력"""
    splash_html = f"""
    <div id="splash-container" style="
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background-color: rgba(255, 255, 255, 0.85);
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        z-index: 9999;
        backdrop-filter: blur(5px);
    ">
        <div class="spinner-box" style="
            width: 150px;
            display: flex;
            justify-content: center;
            align-items: center;
            background-color: transparent;
        ">
            <div class="circle-border" style="
                width: 80px;
                height: 80px;
                padding: 3px;
                display: flex;
                justify-content: center;
                align-items: center;
                border-radius: 50%;
                background: linear-gradient(0deg, rgba(255, 75, 75, 0.1) 33%, rgba(255, 75, 75, 1) 100%);
                animation: spin .8s linear infinite;
            ">
                <div class="circle-core" style="
                    width: 100%;
                    height: 100%;
                    background-color: #ffffff;
                    border-radius: 50%;
                "></div>
            </div>
        </div>
        <div style="
            margin-top: 20px;
            color: #FF4B4B;
            font-size: 1.5rem;
            font-weight: 700;
            font-family: 'Pretendard', sans-serif;
            text-align: center;
        ">
            {message}
        </div>
        <style>
            @keyframes spin {{
                from {{ transform: rotate(0deg); }}
                to {{ transform: rotate(360deg); }}
            }}
        </style>
    </div>
    """
    return st.markdown(splash_html, unsafe_allow_html=True)

def make_query_create_table(tb_name, df):
    """DataFrame 기반 CREATE TABLE 쿼리 생성 (모든 컬럼 TEXT 타입 고정)"""
    column_definitions = [f'"{col}" TEXT' for col in df.columns]

    create_query = f"DROP TABLE IF EXISTS \"{tb_name}\";\nCREATE TABLE \"{tb_name}\" (\n"
    create_query += ",\n".join(column_definitions)
    create_query += "\n);"
    return create_query

def bulk_insert(db_path, tb_name, df):
    """DataFrame 데이터를 테이블에 삽입 (모든 데이터 TEXT 변환)"""
    try:
        conn = get_db_connection(db_path)
        # 모든 데이터를 문자열로 변환하고 결측치 처리
        processed_df = df.fillna("").astype(str)
        processed_df = processed_df.map(lambda x: x.strip())
        
        # 테이블의 실제 컬럼 정보 가져오기
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info(\"{tb_name}\")")
        table_columns = [col[1] for col in cursor.fetchall()]
        
        # 삽입 쿼리 생성
        cols_str = ", ".join([f'"{c}"' for c in table_columns])
        placeholders = ", ".join(["?"] * len(table_columns))
        insert_query = f"INSERT INTO \"{tb_name}\" ({cols_str}) VALUES ({placeholders})"
        
        # 데이터 구성
        data = []
        for _, row in processed_df.iterrows():
            vals = []
            for col in table_columns:
                if col in processed_df.columns:
                    vals.append(row[col])
                else:
                    vals.append(None)
            data.append(tuple(vals))
            
        cursor.execute(f"DELETE FROM \"{tb_name}\"")
        cursor.executemany(insert_query, data)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"❌ 데이터 삽입 오류: {e}")
        return False

def process_ws(db_path, uploaded_file, ws_name):
    """워크시트를 읽어 DB 테이블로 생성 및 삽입 (텍스트 전용)"""
    try:
        df = pd.read_excel(uploaded_file, sheet_name=ws_name, dtype=str)
        create_query = make_query_create_table(ws_name, df)
        if execute_query(db_path, create_query):
            success = bulk_insert(db_path, ws_name, df)
            return success, create_query
    except Exception as e:
        st.error(f"❌ 워크시트 '{ws_name}' 처리 중 오류: {e}")
    return False, None

# --- 데이터 전처리 및 보정 (datadic_definitions.py 참고) ---

class UIProgress:
    def __init__(self, placeholder):
        self.placeholder = placeholder
        self.history = []
        self.current = None

    def start(self, task_name):
        self.current = task_name
        self._render()

    def done(self, task_name=None):
        if task_name is None:
            task_name = self.current
        if task_name:
            self.history.append(task_name)
        self.current = None
        self._render()

    def _render(self):
        if not self.placeholder:
            return
        lines = []
        for h in self.history:
            lines.append(f"✅ {h} <span style='color:green; font-weight:bold; float:right;'>Done</span>")
        if self.current:
            lines.append(f"⏳ <b>{self.current}</b> <span style='color:#FF4B4B; font-weight:bold; float:right;'>Processing...</span>")
        
        html = f"<div style='max-height: 250px; overflow-y: auto; font-family: Pretendard, sans-serif; background-color: #f8f9fa; padding: 15px; border-radius: 8px; border: 1px solid #e0e0e0; margin-bottom: 20px; line-height: 1.8;'>"
        html += "<br>".join(lines)
        html += "</div>"
        self.placeholder.markdown(html, unsafe_allow_html=True)

def cleansing_data(db_path, progress=None):
    if progress: progress.start("기초 데이터 클렌징 (순번 부여)")
    # 용어/속성/컬럼 순번 달기
    targets = ['용어', '속성정의', '컬럼정의']
    success = True
    for t in targets:
        # 테이블 존재 여부 확인
        check = select_query(db_path, f"SELECT name FROM sqlite_master WHERE type='table' AND name='{t}'")
        if not check.empty:
            col_check = select_query(db_path, f"PRAGMA table_info('{t}')")
            if '순번' not in col_check['name'].values:
                query = f'ALTER TABLE "{t}" ADD COLUMN 순번 INTEGER; UPDATE "{t}" SET 순번 = ROWID;'
                if not execute_query(db_path, query): success = False
    if progress: progress.done()
    return success

def make_process_tables(db_path):
    # ALL_용어, ALL_단어, ALL_도메인, 정의수준코드 테이블 생성
    queries = [
        "DROP TABLE IF EXISTS ALL_용어; CREATE TABLE ALL_용어 (용어 VARCHAR(200), 용어약어 VARCHAR(200), 도메인 VARCHAR(200), 정의수준 VARCHAR(20));",
        "DROP TABLE IF EXISTS ALL_단어; CREATE TABLE ALL_단어 (단어 VARCHAR(200), 단어약어 VARCHAR(200), 형식단어여부 VARCHAR(20), 도메인분류 VARCHAR(200), 정의수준 VARCHAR(20));",
        "DROP TABLE IF EXISTS ALL_도메인; CREATE TABLE ALL_도메인 (도메인 VARCHAR(200), 데이터타입 VARCHAR(20), 데이터길이 VARCHAR(20), 데이터소수점 VARCHAR(20), 정의수준 VARCHAR(20));",
        """
        DROP TABLE IF EXISTS 정의수준코드;
        CREATE TABLE 정의수준코드 (명칭 VARCHAR(20), 코드 VARCHAR(2));
        INSERT INTO 정의수준코드 (명칭, 코드) VALUES ('공통표준', '30'), ('공통표준동의어', '31'), ('기관표준', '20'), ('기관표준동의어', '21'), ('표준', '10'), ('표준동의어', '11');
        """
    ]
    for q in queries:
        execute_query(db_path, q)

def append_df_to_tb(db_path, tb_name, df):
    conn = get_db_connection(db_path)
    df.to_sql(tb_name, conn, if_exists='append', index=False)
    conn.close()

def make_all_term_logic(db_path, from_table, col_name, level, word_kr_alias, word_en_alias, domain_alias):
    # 이음동의어 확장 로직 (datadic_make_all_term)
    res_df = select_query(db_path, f"SELECT * FROM \"{from_table}\" LIMIT 1")
    if res_df.empty or col_name not in res_df.columns:
        return

    query = f'SELECT "{col_name}" as "{word_kr_alias}", "{word_en_alias}", "{domain_alias}", "{level}" as 정의수준 FROM "{from_table}" WHERE "{col_name}" <> "-" AND "{col_name}" IS NOT NULL'
    data_df = select_query(db_path, query)
    
    if not data_df.empty:
        # 콤마 분리 및 확장
        split_series = data_df[word_kr_alias].str.split(',').explode().str.strip()
        merged_df = pd.DataFrame({'용어': split_series.values}, index=split_series.index)
        other_cols = data_df.loc[split_series.index].drop(columns=[word_kr_alias]).reset_index(drop=True)
        merged_df = pd.concat([merged_df.reset_index(drop=True), other_cols], axis=1)
        merged_df.columns = ["용어", "용어약어", "도메인", "정의수준"]
        append_df_to_tb(db_path, "ALL_용어", merged_df)

def process_term(db_path):
    # 표준용어/기관표준용어/공통표준용어 취합
    queries = [
        "INSERT INTO ALL_용어 SELECT 표준용어, 표준용어영문약어, 표준도메인, '10' FROM 용어",
        "INSERT INTO ALL_용어 SELECT 기관표준용어, 기관표준용어영문약어, 표준도메인, '20' FROM 기관표준용어",
        "INSERT INTO ALL_용어 (용어, 용어약어, 도메인, 정의수준) SELECT 공통표준용어명, 공통표준용어영문약어명, 공통표준도메인명, '30' FROM 공통표준용어 WHERE \"제정차수(제정연월)\" NOT LIKE '%(폐기)%'"
    ]
    for q in queries:
        try: execute_query(db_path, q)
        except: pass
    
    # 이음동의어 처리
    make_all_term_logic(db_path, "용어", "이음동의어", "11", "표준용어", "표준용어영문약어", "표준도메인")
    make_all_term_logic(db_path, "기관표준용어", "이음동의어", "21", "기관표준용어", "기관표준용어영문약어", "표준도메인")
    make_all_term_logic(db_path, "공통표준용어", "용어 이음동의어 목록", "31", "공통표준용어", "공통표준용어영문약어명", "공통표준도메인명")

def make_all_word_logic(db_path, from_table, col_name, level, term_kr, term_en, term_format, domain_group='-'):
    res_df = select_query(db_path, f"SELECT * FROM \"{from_table}\" LIMIT 1")
    if res_df.empty or col_name not in res_df.columns:
        return

    query = f'SELECT "{col_name}" as "{term_kr}", "{term_en}", "{term_format}", "{domain_group}" as 도메인분류, "{level}" as 정의수준 FROM "{from_table}" WHERE "{col_name}" <> "-" AND "{col_name}" IS NOT NULL'
    data_df = select_query(db_path, query)
    
    if not data_df.empty:
        split_series = data_df[term_kr].str.split(',').explode().str.strip()
        merged_df = pd.DataFrame({'단어': split_series.values}, index=split_series.index)
        other_cols = data_df.loc[split_series.index].drop(columns=[term_kr]).reset_index(drop=True)
        merged_df = pd.concat([merged_df.reset_index(drop=True), other_cols], axis=1)
        merged_df.columns = ["단어", "단어약어", "형식단어여부", "도메인분류", "정의수준"]
        
        # 중복 체크 후 삽입
        existing = select_query(db_path, "SELECT 단어, 단어약어 FROM ALL_단어")
        if not existing.empty:
            merged_df = merged_df[~merged_df.set_index(['단어', '단어약어']).index.isin(existing.set_index(['단어', '단어약어']).index)]
        append_df_to_tb(db_path, "ALL_단어", merged_df)

def process_word(db_path):
    queries = [
        "INSERT INTO ALL_단어 SELECT 표준단어, 표준단어영문약서, 형식단어여부, '-', '10' FROM 단어",
        "INSERT INTO ALL_단어 SELECT 기관표준단어, 기관표준단어영문약서, 형식단어여부, '-', '20' FROM 기관표준단어",
        "INSERT INTO ALL_단어 (단어, 단어약어, 형식단어여부, 도메인분류, 정의수준) SELECT 공통표준단어명, 공통표준단어영문약어명, \"형식단어여부\", 공통표준도메인분류명, '30' FROM 공통표준단어 WHERE \"제정차수(제정연월)\" NOT LIKE '%(폐기)%'"
    ]
    for q in queries:
        try: execute_query(db_path, q)
        except: pass

    make_all_word_logic(db_path, "단어", "이음동의어목록", "11", "표준단어", "표준단어영문약서", "형식단어여부")
    make_all_word_logic(db_path, "기관표준단어", "이음동의어", "21", "기관표준단어", "기관표준단어영문약서", "형식단어여부")
    make_all_word_logic(db_path, "공통표준단어", "이음동의어 목록", "31", "공통표준단어명", "공통표준단어영문약어명", "형식단어\n여부", "공통표준도메인분류명")
    
    execute_query(db_path, "UPDATE ALL_단어 SET 도메인분류 = NULL WHERE 도메인분류 = '-'")

def process_domain(db_path):
    queries = [
        "INSERT INTO ALL_도메인 SELECT *, '10' FROM 도메인",
        "INSERT INTO ALL_도메인 SELECT *, '20' FROM 기관표준도메인",
        "INSERT INTO ALL_도메인 (도메인, 데이터타입, 데이터길이, 데이터소수점, 정의수준) SELECT 공통표준도메인명, 데이터타입, 데이터길이, 데이터소수점길이, '30' FROM 공통표준도메인 WHERE \"제정차수(제정연월)\" NOT LIKE '%(폐기)%'"
    ]
    for q in queries:
        try: execute_query(db_path, q)
        except: pass
    
    execute_query(db_path, "UPDATE ALL_도메인 SET 데이터소수점 = NULL WHERE 데이터소수점 = '-'")
    # 실수형 소수점 처리
    execute_query(db_path, "UPDATE ALL_도메인 SET 데이터소수점 = CAST(데이터소수점 AS INTEGER) WHERE 데이터소수점 LIKE '%.0'")

def preprocess_all(db_path, progress=None):
    if progress: progress.start("ALL_용어, 단어, 도메인 세팅")
    make_process_tables(db_path)
    if progress: progress.done()
    
    success = True
    if progress: progress.start("용어 처리 (ALL_용어)")
    process_term(db_path) # 내부적으로 execute_query를 호출하지만 try-except가 있음
    if progress: progress.done()
    
    if progress: progress.start("단어 처리 (ALL_단어)")
    process_word(db_path)
    if progress: progress.done()
    
    if progress: progress.start("도메인 처리 (ALL_도메인)")
    process_domain(db_path)
    if progress: progress.done()
    
    if progress: progress.start("통합 데이터 순번부여")
    # 마지막 순번 정리
    for t in ['ALL_용어', 'ALL_단어', 'ALL_도메인']:
        col_check = select_query(db_path, f"PRAGMA table_info('{t}')")
        if '순번' not in col_check['name'].values:
            if not execute_query(db_path, f'ALTER TABLE "{t}" ADD COLUMN 순번 INTEGER; UPDATE "{t}" SET 순번 = ROWID;'): success = False
    if progress: progress.done()
    return success

# --- 점검 쿼리 모음 (DB 표준용) ---

# --- 쿼리 조회용 스크립트 모음 ---

STANDARDS_QUERY_LOOKUP = {
    "데이터 전처리 (순번 부여)": """
-- 용어, 속성정의, 컬럼정의 등 원본 테이블에 순번(PK 대용) 부여
ALTER TABLE "{테이블명}" ADD COLUMN 순번 INTEGER;
UPDATE "{테이블명}" SET 순번 = ROWID;
""",
    "ALL_용어 (용어 통합)": """
-- 1. 통합 테이블 생성
DROP TABLE IF EXISTS ALL_용어;
CREATE TABLE ALL_용어 (
    용어 VARCHAR(200), 
    용어약어 VARCHAR(200), 
    도메인 VARCHAR(200), 
    정의수준 VARCHAR(20)
);

-- 2. 표준/기관/공통 데이터 삽입
INSERT INTO ALL_용어 SELECT 표준용어, 표준용어영문약어, 표준도메인, '10' FROM 용어;
INSERT INTO ALL_용어 SELECT 기관표준용어, 기관표준용어영문약어, 표준도메인, '20' FROM 기관표준용어;
INSERT INTO ALL_용어 (용어, 용어약어, 도메인, 정의수준) 
SELECT 공통표준용어명, 공통표준용어영문약어명, 공통표준도메인명, '30' 
FROM 공통표준용어 
WHERE "제정차수(제정연월)" NOT LIKE '%(폐기)%';

-- 3. 이음동의어 확장 (Python에서 콤마 분리 후 삽입)
-- 4. 순번 추가
ALTER TABLE "ALL_용어" ADD COLUMN 순번 INTEGER;
UPDATE "ALL_용어" SET 순번 = ROWID;
""",
    "ALL_단어 (단어 통합)": """
-- 1. 통합 테이블 생성
DROP TABLE IF EXISTS ALL_단어;
CREATE TABLE ALL_단어 (
    단어 VARCHAR(200), 
    단어약어 VARCHAR(200), 
    형식단어여부 VARCHAR(20), 
    도메인분류 VARCHAR(200), 
    정의수준 VARCHAR(20)
);

-- 2. 표준/기관/공통 데이터 삽입
INSERT INTO ALL_단어 SELECT 표준단어, 표준단어영문약서, 형식단어여부, '-', '10' FROM 단어;
INSERT INTO ALL_단어 SELECT 기관표준단어, 기관표준단어영문약서, 형식단어여부, '-', '20' FROM 기관표준단어;
INSERT INTO ALL_단어 (단어, 단어약어, 형식단어여부, 도메인분류, 정의수준) 
SELECT 공통표준단어명, 공통표준단어영문약어명, 형식단어여부, 공통표준도메인분류명, '30' 
FROM 공통표준단어 WHERE "제정차수(제정연월)" NOT LIKE '%(폐기)%';

-- 3. 이음동의어 확장 (Python에서 콤마 분리 후 중복 제거 삽입)
-- 4. 순번 추가
ALTER TABLE "ALL_단어" ADD COLUMN 순번 INTEGER;
UPDATE "ALL_단어" SET 순번 = ROWID;
""",
    "ALL_도메인 (도메인 통합)": """
-- 1. 통합 테이블 생성
DROP TABLE IF EXISTS ALL_도메인;
CREATE TABLE ALL_도메인 (
    도메인 VARCHAR(200), 
    데이터타입 VARCHAR(20), 
    데이터길이 VARCHAR(20), 
    데이터소수점 VARCHAR(20), 
    정의수준 VARCHAR(20)
);

-- 2. 표준/기관/공통 데이터 삽입
INSERT INTO ALL_도메인 SELECT *, '10' FROM 도메인;
INSERT INTO ALL_도메인 SELECT *, '20' FROM 기관표준도메인;
INSERT INTO ALL_도메인 (도메인, 데이터타입, 데이터길이, 데이터소수점, 정의수준) 
SELECT 공통표준도메인명, 데이터타입, 데이터길이, 데이터소수점길이, '30' 
FROM 공통표준도메인 WHERE "제정차수(제정연월)" NOT LIKE '%(폐기)%';

-- 3. 순번 추가
ALTER TABLE "ALL_도메인" ADD COLUMN 순번 INTEGER;
UPDATE "ALL_도메인" SET 순번 = ROWID;
""",
    "표준용어_구성점검 (단어 분리 및 검증)": """
-- 1. 분석용 임시 테이블 생성
DROP TABLE IF EXISTS 표준용어_구성점검_TEMP;
CREATE TABLE 표준용어_구성점검_TEMP AS SELECT 순번, 표준용어, 표준용어영문약어 FROM 용어;

-- 2. 분석용 컬럼 추가 및 초기화
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN LEN INTEGER;
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN S_POS INTEGER;
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN E_POS INTEGER;
UPDATE 표준용어_구성점검_TEMP SET LEN=LENGTH(표준용어영문약어), S_POS = 1, E_POS = 0;

-- 3. 언더바(_) 기준 단어 분리 (최대 9개까지 반복 실행)
-- [01회차]
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN 단어약어_01 VARCHAR(50);
UPDATE 표준용어_구성점검_TEMP SET E_POS = CASE WHEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') > 0 THEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') - 1 ELSE LEN - S_POS + 1 END WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET 단어약어_01 = SUBSTR(표준용어영문약어, S_POS, E_POS) WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET S_POS = S_POS + E_POS + 1 WHERE S_POS <= LEN;
-- [02회차]
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN 단어약어_02 VARCHAR(50);
UPDATE 표준용어_구성점검_TEMP SET E_POS = CASE WHEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') > 0 THEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') - 1 ELSE LEN - S_POS + 1 END WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET 단어약어_02 = SUBSTR(표준용어영문약어, S_POS, E_POS) WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET S_POS = S_POS + E_POS + 1 WHERE S_POS <= LEN;
-- [03회차]
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN 단어약어_03 VARCHAR(50);
UPDATE 표준용어_구성점검_TEMP SET E_POS = CASE WHEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') > 0 THEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') - 1 ELSE LEN - S_POS + 1 END WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET 단어약어_03 = SUBSTR(표준용어영문약어, S_POS, E_POS) WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET S_POS = S_POS + E_POS + 1 WHERE S_POS <= LEN;
-- [04회차]
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN 단어약어_04 VARCHAR(50);
UPDATE 표준용어_구성점검_TEMP SET E_POS = CASE WHEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') > 0 THEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') - 1 ELSE LEN - S_POS + 1 END WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET 단어약어_04 = SUBSTR(표준용어영문약어, S_POS, E_POS) WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET S_POS = S_POS + E_POS + 1 WHERE S_POS <= LEN;
-- [05회차]
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN 단어약어_05 VARCHAR(50);
UPDATE 표준용어_구성점검_TEMP SET E_POS = CASE WHEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') > 0 THEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') - 1 ELSE LEN - S_POS + 1 END WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET 단어약어_05 = SUBSTR(표준용어영문약어, S_POS, E_POS) WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET S_POS = S_POS + E_POS + 1 WHERE S_POS <= LEN;
-- [06회차]
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN 단어약어_06 VARCHAR(50);
UPDATE 표준용어_구성점검_TEMP SET E_POS = CASE WHEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') > 0 THEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') - 1 ELSE LEN - S_POS + 1 END WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET 단어약어_06 = SUBSTR(표준용어영문약어, S_POS, E_POS) WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET S_POS = S_POS + E_POS + 1 WHERE S_POS <= LEN;
-- [07회차]
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN 단어약어_07 VARCHAR(50);
UPDATE 표준용어_구성점검_TEMP SET E_POS = CASE WHEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') > 0 THEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') - 1 ELSE LEN - S_POS + 1 END WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET 단어약어_07 = SUBSTR(표준용어영문약어, S_POS, E_POS) WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET S_POS = S_POS + E_POS + 1 WHERE S_POS <= LEN;
-- [08회차]
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN 단어약어_08 VARCHAR(50);
UPDATE 표준용어_구성점검_TEMP SET E_POS = CASE WHEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') > 0 THEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') - 1 ELSE LEN - S_POS + 1 END WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET 단어약어_08 = SUBSTR(표준용어영문약어, S_POS, E_POS) WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET S_POS = S_POS + E_POS + 1 WHERE S_POS <= LEN;
-- [09회차]
ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN 단어약어_09 VARCHAR(50);
UPDATE 표준용어_구성점검_TEMP SET E_POS = CASE WHEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') > 0 THEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') - 1 ELSE LEN - S_POS + 1 END WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET 단어약어_09 = SUBSTR(표준용어영문약어, S_POS, E_POS) WHERE S_POS <= LEN;
UPDATE 표준용어_구성점검_TEMP SET S_POS = S_POS + E_POS + 1 WHERE S_POS <= LEN;

-- 4. 표준용어 구성점검 테이블 생성 2 (표준단어와 매핑) - 중복정의 모두 조합된 결과
DROP TABLE IF EXISTS 표준용어_구성점검;
CREATE TABLE 표준용어_구성점검 AS
SELECT DISTINCT T0.순번, T0.표준용어영문약어, T0.표준용어, 
       (COALESCE(T1.단어, '') || COALESCE(T2.단어, '') || COALESCE(T3.단어, '') || COALESCE(T4.단어, '') || COALESCE(T5.단어, '') || COALESCE(T6.단어, '') || COALESCE(T7.단어, '') || COALESCE(T8.단어, '') || COALESCE(T9.단어, '')) AS 조합용어, 
       '-' as 구성점검결과
FROM 표준용어_구성점검_TEMP T0 
LEFT OUTER JOIN (SELECT DISTINCT 단어약어, 단어 FROM ALL_단어) T1 ON T0.단어약어_01 = T1.단어약어
LEFT OUTER JOIN (SELECT DISTINCT 단어약어, 단어 FROM ALL_단어) T2 ON T0.단어약어_02 = T2.단어약어
LEFT OUTER JOIN (SELECT DISTINCT 단어약어, 단어 FROM ALL_단어) T3 ON T0.단어약어_03 = T3.단어약어
LEFT OUTER JOIN (SELECT DISTINCT 단어약어, 단어 FROM ALL_단어) T4 ON T0.단어약어_04 = T4.단어약어
LEFT OUTER JOIN (SELECT DISTINCT 단어약어, 단어 FROM ALL_단어) T5 ON T0.단어약어_05 = T5.단어약어
LEFT OUTER JOIN (SELECT DISTINCT 단어약어, 단어 FROM ALL_단어) T6 ON T0.단어약어_06 = T6.단어약어
LEFT OUTER JOIN (SELECT DISTINCT 단어약어, 단어 FROM ALL_단어) T7 ON T0.단어약어_07 = T7.단어약어
LEFT OUTER JOIN (SELECT DISTINCT 단어약어, 단어 FROM ALL_단어) T8 ON T0.단어약어_08 = T8.단어약어
LEFT OUTER JOIN (SELECT DISTINCT 단어약어, 단어 FROM ALL_단어) T9 ON T0.단어약어_09 = T9.단어약어;


-- 5. 원본 용어와 조합 용어 비교 판정
UPDATE 표준용어_구성점검 SET 구성점검결과 = CASE WHEN replace(표준용어, ' ', '') = 조합용어 THEN '표준' ELSE '비표준' END;

-- 6. 최종 결과 테이블 (표준 우선으로 정리)
DROP TABLE IF EXISTS 표준용어_구성점검_RES;
CREATE TABLE 표준용어_구성점검_RES AS 
SELECT 순번,표준용어영문약어,표준용어,조합용어,구성점검결과,단어약어_01,표준단어_01,단어약어_02,표준단어_02,단어약어_03,표준단어_03,단어약어_04,표준단어_04,단어약어_05,표준단어_05,단어약어_06,표준단어_06,단어약어_07,표준단어_07,단어약어_08,표준단어_08,단어약어_09,표준단어_09 FROM 
(SELECT  * , row_number() over (partition by 순번 order by 구성점검결과 desc) as rn
FROM 표준용어_구성점검 ORDER BY 순번, 구성점검결과 DESC) WHERE rn = 1;
""",


    "점검_속성표준준수": """
-- 속성 명칭과 컬럼 영문명이 표준용어(ALL_용어)와 일치하는지 점검
DROP TABLE IF EXISTS 점검_속성표준준수;
CREATE TABLE 점검_속성표준준수 AS
SELECT T.* FROM (
    SELECT A.*, 
           CASE WHEN REPLACE(A."속성(한글)", ' ', '')=REPLACE(B.용어, ' ', '') AND B.용어약어=A."컬럼(영문)" 
                THEN '일치' ELSE '불일치' END as 점검결과, 
           B.용어, B.용어약어, B.도메인, (SELECT 명칭 FROM 정의수준코드 WHERE 코드=B.정의수준) as 정의수준, 
           ROW_NUMBER() OVER (PARTITION BY A.순번 ORDER BY B.정의수준) as rn
    FROM 속성정의 A 
    LEFT JOIN ALL_용어 B ON REPLACE(A."속성(한글)", ' ', '')=REPLACE(B.용어, ' ', '')
    WHERE A."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 표준화대상테이블 WHERE STANDARD_YN = 'N')
) T WHERE T.rn=1;
""",
    "점검_속성표준도메인준수": """
-- 1. 속성표준도메인준수 1차 테이블 생성
DROP TABLE IF EXISTS 점검_속성표준도메인준수;
CREATE TABLE 점검_속성표준도메인준수 AS
select  A."엔터티(한글)", A."테이블(영문)", A."컬럼(영문)", A."속성(한글)", A."속성(데이터타입)"
   ,NULL as col_dt, NULL as col_dl, NULL as dl_param1, NULL as dl_param2
   , A.점검결과 as "점검결과(용어)", A.용어, A.용어약어, A.도메인 as "용어도메인", A.정의수준
   , NULL as "점검결과(도메인)", B.도메인, B.데이터타입, B.데이터길이, B.데이터소수점, B.정의수준 as "도메인정의수준"
from 점검_속성표준준수 A left join ALL_도메인 B on A.도메인 = B.도메인;

-- 2. 데이터타입, 길이 분리
update 점검_속성표준도메인준수 set col_dt = CASE 
                  WHEN INSTR("속성(데이터타입)", '(') = 0 THEN "속성(데이터타입)"
               ELSE SUBSTR("속성(데이터타입)", 1, INSTR("속성(데이터타입)", '(') - 1) END;

update 점검_속성표준도메인준수 set col_dl = CASE 
                  WHEN INSTR("속성(데이터타입)", '(')=0 THEN NULL
                  ELSE TRIM(SUBSTR("속성(데이터타입)", INSTR("속성(데이터타입)", '(') + 1, INSTR("속성(데이터타입)", ')') - INSTR("속성(데이터타입)", '(') - 1)) END;

update 점검_속성표준도메인준수 set dl_param1 = CASE 
               WHEN INSTR(col_dl, ',')=0 THEN TRIM(col_dl)
               ELSE TRIM(SUBSTR(col_dl, 1, INSTR(col_dl, ',') - 1)) END;

update 점검_속성표준도메인준수 set dl_param2 = CASE
      WHEN col_dl IS NULL OR INSTR(col_dl, ',') = 0 THEN NULL
      ELSE TRIM(SUBSTR(col_dl, INSTR(col_dl, ',') + 1)) END;

-- 3. 보정 및 일치 판별
update 점검_속성표준도메인준수 set 데이터길이 = NULL where 데이터길이 = '-';
update 점검_속성표준도메인준수 set col_dt = replace(replace(col_dt, "NUMBER", "NUMERIC"), "VARCHAR2", "VARCHAR");
update 점검_속성표준도메인준수 set 데이터타입 = replace(replace(데이터타입, "NUMBER", "NUMERIC"), "VARCHAR2", "VARCHAR");

update 점검_속성표준도메인준수 set "점검결과(도메인)" = CASE 
    WHEN col_dt=데이터타입 and CAST(dl_param1 AS NUMERIC)=CAST(데이터길이 AS NUMERIC) and CAST(dl_param2 AS NUMERIC)=CAST(데이터소수점 AS NUMERIC) THEN "일치" 
    WHEN col_dt=데이터타입 and CAST(dl_param1 AS NUMERIC)=CAST(데이터길이 AS NUMERIC) and dl_param2 IS NULL AND 데이터소수점 IS NULL THEN "일치"
    WHEN col_dt=데이터타입 and dl_param1 IS NULL AND 데이터길이 IS NULL and dl_param2 IS NULL AND 데이터소수점 IS NULL THEN "일치"
    ELSE "불일치" END;
"""
}

DESIGN_QUERY_LOOKUP = {
    "데이터 전처리 (순번 부여)": """
-- 속성정의, 컬럼정의 등 원본 테이블에 순번(PK 대용) 부여
ALTER TABLE "{테이블명}" ADD COLUMN 순번 INTEGER;
UPDATE "{테이블명}" SET 순번 = ROWID;
""",
    "점검_설계구현비교 (최종 판정)": """
-- 1. 설계(속성정의)와 구현(컬럼정의) 테이블을 조인하여 비교 테이블 생성
DROP TABLE IF EXISTS 점검_설계구현비교;
CREATE TABLE 점검_설계구현비교 AS
SELECT A."테이블(영문)" as 설계_엔터티, A."엔터티(한글)" as 설계_테이블, A."컬럼(영문)" as 설계_컬럼, A."속성(한글)" as 설계_속성, '설계/구현 비교' as 비교결과, B."테이블(영문)" as 구현_엔터티, B."엔터티(한글)" as 구현_테이블, B."컬럼(영문)" as 구현_컬럼, B."속성(한글)" as 구현_속성 
FROM 속성정의 A 
LEFT JOIN 컬럼정의 B ON A."테이블(영문)" = B."테이블(영문)" AND A."컬럼(영문)" = B."컬럼(영문)"
WHERE A."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')
UNION ALL
SELECT NULL, NULL, NULL, NULL, '설계/구현 비교', B."테이블(영문)", B."엔터티(한글)", B."컬럼(영문)", B."속성(한글)" 
FROM 컬럼정의 B 
LEFT JOIN 속성정의 A ON A."테이블(영문)" = B."테이블(영문)" AND A."컬럼(영문)" = B."컬럼(영문)" 
WHERE A."컬럼(영문)" IS NULL
AND B."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N');

-- 2. 비교 결과 업데이트 (일치/설계누락/구현누락)
UPDATE 점검_설계구현비교 SET 비교결과='일치' WHERE 설계_컬럼 IS NOT NULL AND 구현_컬럼 IS NOT NULL;
UPDATE 점검_설계구현비교 SET 비교결과='설계누락' WHERE 설계_컬럼 IS NULL;
UPDATE 점검_설계구현비교 SET 비교결과='구현누락' WHERE 구현_컬럼 IS NULL;
""",
    "점검_설계구현도메인비교": """
-- 1. 설계(속성정의)와 구현(컬럼정의)의 테이블/컬럼이 같은 건들에 대해 데이터타입 비교
DROP TABLE IF EXISTS 점검_설계구현도메인비교;
CREATE TABLE 점검_설계구현도메인비교 AS
SELECT A."테이블(영문)" as 설계_엔터티, A."컬럼(영문)" as 설계_컬럼, A."속성(데이터타입)" as 설계_속성_데이터타입, 
       B."테이블(영문)" as 구현_엔터티, B."컬럼(영문)" as 구현_컬럼, B."컬럼(데이터타입)" as 구현_컬럼_데이터타입 
FROM 속성정의 A 
JOIN 컬럼정의 B ON A."테이블(영문)" = B."테이블(영문)" AND A."컬럼(영문)" = B."컬럼(영문)"
WHERE IFNULL(UPPER(REPLACE(REPLACE(REPLACE(A."속성(데이터타입)", 'DATE(8)', 'DATE'), 'VARCHAR2', 'VARCHAR'), ' ', '')), '') <> IFNULL(UPPER(REPLACE(REPLACE(REPLACE(B."컬럼(데이터타입)", 'DATE(8)', 'DATE'), 'VARCHAR2', 'VARCHAR'), ' ', '')), '');
"""
}

# --- 점검 쿼리 모음 (DB 설계용) ---

STANDARDS_SQL_DICT = {
    "점검_단어_01_표준단어명재정의": """
    SELECT DISTINCT T.단어, T.단어약어, T.정의수준, T.상위표준_단어약어, T.상위표준_정의수준 FROM
    (SELECT ROW_NUMBER() OVER (PARTITION BY B.순번 ORDER BY A.단어약어<>B.단어약어, B.정의수준) as rn
       , B.단어, B.단어약어, (select 명칭 from 정의수준코드 where 코드= B.정의수준) as 정의수준
       , A.단어약어 as 상위표준_단어약어, (select 명칭 from 정의수준코드 where 코드= A.정의수준) as 상위표준_정의수준
       from ALL_단어 A join ALL_단어 B on A.단어=B.단어 and A.정의수준>=20 and B.정의수준<=20) as T
    WHERE T.rn == 1 and T.단어약어<>T.상위표준_단어약어;
    """,
    "점검_단어_02_표준단어약어재정의": """
    SELECT DISTINCT T.단어약어, T.단어, T.정의수준, T.상위표준_단어, T.상위표준_정의수준
    FROM (SELECT ROW_NUMBER() OVER (PARTITION BY B.순번 ORDER BY A.단어<>B.단어, B.정의수준) as rn
          , B.단어약어, B.단어, (select 명칭 from 정의수준코드 where 코드= B.정의수준) as 정의수준
          , A.단어 as 상위표준_단어, (select 명칭 from 정의수준코드 where 코드= A.정의수준) as 상위표준_정의수준
          from ALL_단어 A join ALL_단어 B on A.단어약어=B.단어약어 and A.정의수준>=20 and B.정의수준<=20) as T
    where T.rn ==1 and T.단어<>T.상위표준_단어;
    """,
    "점검_단어_03_표준단어명중복정의": """
    SELECT DISTINCT B.단어, B.단어약어, (select 명칭 from 정의수준코드 where 코드= B.정의수준) as 정의수준, A.단어약어 as 상위표준_단어약어, (select 명칭 from 정의수준코드 where 코드= A.정의수준) as 상위표준_정의수준
    from ALL_단어 A join ALL_단어 B on A.단어=B.단어 and A.단어약어<>B.단어약어 and A.정의수준=10 and B.정의수준=10
    and B.단어약어 = (select MIN(C.단어약어) FROM ALL_단어 C where C.단어 = B.단어 and C.정의수준 = 10);
    """,
    "점검_단어_04_표준단어약어중복정의": """
    SELECT DISTINCT B.단어약어, B.단어, (select 명칭 from 정의수준코드 where 코드= B.정의수준) as 정의수준, A.단어 as 상위표준_단어, (select 명칭 from 정의수준코드 where 코드= A.정의수준) as 상위표준_정의수준
    from ALL_단어 A join ALL_단어 B on A.단어약어=B.단어약어 and A.단어<>B.단어 and A.정의수준=10 and B.정의수준=10
    and B.단어 = (select MIN(C.단어) FROM ALL_단어 C where C.단어약어 = B.단어약어 and C.정의수준 = 10);
    """,
    "점검_용어_01_용어명재정의": """
    SELECT DISTINCT T.용어, T.용어약어, T.정의수준, T.상위표준_용어약어, T.상위표준_정의수준 FROM
    (SELECT ROW_NUMBER() OVER (PARTITION BY B.순번 ORDER BY B.용어약어<>A.용어약어, B.정의수준) as rn
     , B.용어, B.용어약어, (select 명칭 from 정의수준코드 where 코드= B.정의수준) as 정의수준
     , A.용어약어 as 상위표준_용어약어, (select 명칭 from 정의수준코드 where 코드= A.정의수준) as 상위표준_정의수준
     from ALL_용어 A join ALL_용어 B on A.용어=B.용어 and A.정의수준>B.정의수준 and B.정의수준<20) as T
    WHERE T.rn == 1 and T.용어약어<>T.상위표준_용어약어;
    """,
    "점검_용어_02_용어약어재정의": """
    SELECT DISTINCT T.용어약어, T.용어, T.정의수준, T.상위표준_용어, T.상위표준_정의수준 FROM
    (SELECT ROW_NUMBER() OVER (PARTITION BY B.순번 ORDER BY B.용어<>A.용어, B.정의수준) as rn
     , B.용어약어, B.용어, (select 명칭 from 정의수준코드 where 코드= B.정의수준) as 정의수준
     , A.용어 as 상위표준_용어, (select 명칭 from 정의수준코드 where 코드= A.정의수준) as 상위표준_정의수준
     from ALL_용어 A join ALL_용어 B on A.용어약어=B.용어약어 and A.정의수준>B.정의수준 and B.정의수준<20) as T
    WHERE T.rn == 1 and T.용어<>T.상위표준_용어;
    """,
    "점검_용어_03_용어명중복정의": """
    SELECT DISTINCT B.용어, B.용어약어, (select 명칭 from 정의수준코드 where 코드= B.정의수준) as 정의수준, A.용어약어 as 상위표준_용어약어, (select 명칭 from 정의수준코드 where 코드= A.정의수준) as 상위표준_정의수준
    from ALL_용어 A join ALL_용어 B on A.용어=B.용어 and A.용어약어<>B.용어약어 and A.정의수준=10 and B.정의수준=10
    and B.용어약어 = (select MIN(C.용어약어) FROM ALL_용어 C where C.용어 = B.용어 and C.정의수준 = 10);
    """,
    "점검_용어_04_용어약어중복정의": """
    SELECT DISTINCT B.용어약어, B.용어, (select 명칭 from 정의수준코드 where 코드= B.정의수준) as 정의수준, A.용어 as 상위표준_용어, (select 명칭 from 정의수준코드 where 코드= A.정의수준) as 상위표준_정의수준
    from ALL_용어 A join ALL_용어 B on A.용어약어=B.용어약어 and A.용어<>B.용어 and A.정의수준=10 and B.정의수준=10
    and B.용어 = (select MIN(C.용어) FROM ALL_용어 C where C.용어약어 = B.용어약어 and C.정의수준 = 10);
    """,
    "점검_용어_05_용어도메인재정의": """
    SELECT DISTINCT T.용어, T.도메인, T.정의수준, T.상위수준_도메인, T.상위표준_정의수준 FROM
    (SELECT B.용어, B.도메인, (select 명칭 from 정의수준코드 where 코드= B.정의수준) as 정의수준, A.도메인 as 상위수준_도메인, (select 명칭 from 정의수준코드 where 코드= A.정의수준) as 상위표준_정의수준, ROW_NUMBER() OVER (PARTITION BY B.순번 ORDER BY A.도메인<>B.도메인, B.정의수준) as rn
     from ALL_용어 A join ALL_용어 B on A.용어=B.용어 and B.정의수준=10 and A.정의수준 >= 20) as T
    WHERE T.rn==1 and T.도메인<>T.상위수준_도메인;
    """,
    "표준용어_구성점검_TEMP": "SELECT 순번, 표준용어, 표준용어영문약어 FROM 용어;",
    "표준용어_구성점검": "조합용어 구성 로직 (SQL 템플릿 기반 생성)", # 나중에 동적으로 채움
    "표준용어_구성점검_RES": """
        SELECT 순번,표준용어영문약어,표준용어,조합용어,구성점검결과,단어약어_01,표준단어_01,단어약어_02,표준단어_02,단어약어_03,표준단어_03,단어약어_04,표준단어_04,단어약어_05,표준단어_05,단어약어_06,표준단어_06,단어약어_07,표준단어_07,단어약어_08,표준단어_08,단어약어_09,표준단어_09 FROM 
        (SELECT  * , row_number() over (partition by 순번 order by 구성점검결과 desc) as rn
        FROM 표준용어_구성점검 ORDER BY 순번, 구성점검결과 DESC) WHERE rn = 1;
    """,
    "점검_속성표준준수": """
    SELECT A.순번, A."엔터티(한글)", A."테이블(영문)", A."컬럼(영문)", A."속성(한글)", A."속성(데이터타입)", A."식별자여부",
           CASE WHEN A.norm_속성명 = B.norm_용어명 AND B.용어약어 = A."컬럼(영문)" THEN '일치' ELSE '불일치' END as 점검결과,
           B.용어, B.용어약어, B.도메인,
           (SELECT 명칭 FROM 정의수준코드 WHERE 코드 = B.정의수준) as 정의수준,
           ROW_NUMBER() OVER (PARTITION BY A.순번 ORDER BY B.정의수준) as rn
    FROM _WORK_속성정의 A
    LEFT JOIN _WORK_ALL_용어 B ON A.norm_속성명 = B.norm_용어명
    """,
    "점검_속성표준도메인준수": """
    select  A."엔터티(한글)", A."테이블(영문)", A."컬럼(영문)", A."속성(한글)", A."속성(데이터타입)"
       ,NULL as col_dt, NULL as col_dl, NULL as dl_param1, NULL as dl_param2
       , A.점검결과 as "점검결과(용어)", A.용어, A.용어약어, A.도메인 as "용어도메인", A.정의수준
       , NULL as "점검결과(도메인)", B.도메인 as "매핑도메인", B.데이터타입, B.데이터길이, B.데이터소수점, B.정의수준 as "도메인정의수준"
       from 점검_속성표준준수 A left join ALL_도메인 B on A.도메인 = B.도메인
    """
}

def ensure_target_table_exists(db_path, target_tb_name, source_tbs):
    """
    점검대상테이블(모델점검대상테이블, 표준화대상테이블)이 존재하지 않으면 신규 생성하고,
    원본 테이블(속성정의, 컬럼정의 등)에서 존재하는 모든 테이블명을 가져와 기본값('Y')으로 적재합니다.
    """
    # 1. 테이블 생성
    chk = select_query(db_path, f"SELECT name FROM sqlite_master WHERE type='table' AND name='{target_tb_name}'")
    if chk.empty:
        execute_query(db_path, f"CREATE TABLE {target_tb_name} (TABLE_NAME TEXT, ENTITY_NAME TEXT, STANDARD_YN TEXT, COMMENT TEXT)")
        
    # 2. 누락된 대상 테이블(Y) Insert
    queries = []
    for stb in source_tbs:
        chk_src = select_query(db_path, f"SELECT name FROM sqlite_master WHERE type='table' AND name='{stb}'")
        if not chk_src.empty:
            queries.append(f"""
                SELECT DISTINCT "테이블(영문)" as TABLE_NAME, MAX("엔터티(한글)") as ENTITY_NAME 
                FROM "{stb}" 
                WHERE "테이블(영문)" IS NOT NULL 
                GROUP BY "테이블(영문)"
            """)
            
    if queries:
        union_query = " UNION ".join(queries)
        insert_sql = f"""
        INSERT INTO {target_tb_name} (TABLE_NAME, ENTITY_NAME, STANDARD_YN, COMMENT)
        SELECT A.TABLE_NAME, A.ENTITY_NAME, 'Y', ''
        FROM (SELECT TABLE_NAME, MAX(ENTITY_NAME) AS ENTITY_NAME FROM ({union_query}) GROUP BY TABLE_NAME) A
        WHERE A.TABLE_NAME NOT IN (SELECT TABLE_NAME FROM {target_tb_name})
        """
        try:
            execute_query(db_path, insert_sql)
        except:
            pass


def check_word(db_path, progress=None):
    # 단어 재정의/중복정의 점검
    success = True
    if progress: progress.start("점검_단어_01_표준단어명재정의")
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 점검_단어_01_표준단어명재정의; CREATE TABLE 점검_단어_01_표준단어명재정의 AS {STANDARDS_SQL_DICT['점검_단어_01_표준단어명재정의']}"): success = False
    if progress: progress.done()
    
    if progress: progress.start("점검_단어_02_표준단어약어재정의")
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 점검_단어_02_표준단어약어재정의; CREATE TABLE 점검_단어_02_표준단어약어재정의 AS {STANDARDS_SQL_DICT['점검_단어_02_표준단어약어재정의']}"): success = False
    if progress: progress.done()
    
    if progress: progress.start("점검_단어_03_표준단어명중복정의")
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 점검_단어_03_표준단어명중복정의; CREATE TABLE 점검_단어_03_표준단어명중복정의 AS {STANDARDS_SQL_DICT['점검_단어_03_표준단어명중복정의']}"): success = False
    if progress: progress.done()
    
    if progress: progress.start("점검_단어_04_표준단어약어중복정의")
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 점검_단어_04_표준단어약어중복정의; CREATE TABLE 점검_단어_04_표준단어약어중복정의 AS {STANDARDS_SQL_DICT['점검_단어_04_표준단어약어중복정의']}"): success = False
    if progress: progress.done()
    return success

def check_term(db_path, progress=None):
    success = True
    if progress: progress.start("점검_용어_01_용어명재정의")
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 점검_용어_01_용어명재정의; CREATE TABLE 점검_용어_01_용어명재정의 AS {STANDARDS_SQL_DICT['점검_용어_01_용어명재정의']}"): success = False
    if progress: progress.done()
    
    if progress: progress.start("점검_용어_02_용어약어재정의")
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 점검_용어_02_용어약어재정의; CREATE TABLE 점검_용어_02_용어약어재정의 AS {STANDARDS_SQL_DICT['점검_용어_02_용어약어재정의']}"): success = False
    if progress: progress.done()
    
    if progress: progress.start("점검_용어_03_용어명중복정의")
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 점검_용어_03_용어명중복정의; CREATE TABLE 점검_용어_03_용어명중복정의 AS {STANDARDS_SQL_DICT['점검_용어_03_용어명중복정의']}"): success = False
    if progress: progress.done()
    
    if progress: progress.start("점검_용어_04_용어약어중복정의")
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 점검_용어_04_용어약어중복정의; CREATE TABLE 점검_용어_04_용어약어중복정의 AS {STANDARDS_SQL_DICT['점검_용어_04_용어약어중복정의']}"): success = False
    if progress: progress.done()
    
    if progress: progress.start("점검_용어_05_용어도메인재정의")
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 점검_용어_05_용어도메인재정의; CREATE TABLE 점검_용어_05_용어도메인재정의 AS {STANDARDS_SQL_DICT['점검_용어_05_용어도메인재정의']}"): success = False
    if progress: progress.done()
    return success

def check_construct(db_path, progress=None):
    success = True
    # 필수 컬럼(순번) 보장
    for t in ['용어']:
        chk = select_query(db_path, f"SELECT name FROM sqlite_master WHERE type='table' AND name='{t}'")
        if not chk.empty:
            col_check = select_query(db_path, f"PRAGMA table_info('{t}')")
            if '순번' not in col_check['name'].values:
                execute_query(db_path, f'ALTER TABLE "{t}" ADD COLUMN 순번 INTEGER; UPDATE "{t}" SET 순번 = ROWID;')

    if progress: progress.start("표준용어_구성점검(전처리)")
    # 표준용어 구성점검 (용어약어 split 및 단어 조합 비교)
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 표준용어_구성점검_TEMP; CREATE TABLE 표준용어_구성점검_TEMP AS {STANDARDS_SQL_DICT['표준용어_구성점검_TEMP']}"): success = False
    if not execute_query(db_path, "ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN LEN INTEGER; ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN S_POS INTEGER; ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN E_POS INTEGER;"): success = False
    if not execute_query(db_path, "UPDATE 표준용어_구성점검_TEMP SET LEN=LENGTH(표준용어영문약어), S_POS = 1, E_POS = 0;"): success = False

    for i in range(1, 10):
        if not execute_query(db_path, f"ALTER TABLE 표준용어_구성점검_TEMP ADD COLUMN 단어약어_0{i} VARCHAR(50);"): success = False
        if not execute_query(db_path, f"""
            UPDATE 표준용어_구성점검_TEMP SET E_POS = CASE WHEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') > 0 THEN INSTR(SUBSTR(표준용어영문약어, S_POS), '_') - 1 ELSE LEN - S_POS + 1 END WHERE S_POS <= LEN;
            UPDATE 표준용어_구성점검_TEMP SET 단어약어_0{i} = SUBSTR(표준용어영문약어, S_POS, E_POS) WHERE S_POS <= LEN;
            UPDATE 표준용어_구성점검_TEMP SET S_POS = S_POS + E_POS + 1 WHERE S_POS <= LEN;
        """): success = False
    if progress: progress.done()

    if progress: progress.start("표준용어_구성점검(상세 비교)")
    query_cols = ", ".join([f"T0.단어약어_0{i}, T{i}.단어 AS 표준단어_0{i}" for i in range(1, 10)])
    # 동일한 단어약어가 여러 개일 경우 모든 조합 생성
    subquery = "(SELECT DISTINCT 단어약어, 단어 FROM ALL_단어)"
    joins = " ".join([f"LEFT OUTER JOIN {subquery} T{i} ON T0.단어약어_0{i} = T{i}.단어약어" for i in range(1, 10)])
    concat_logic = " || ".join([f"COALESCE(T{i}.단어, '')" for i in range(1, 10)])
    
    ctas_sql = f"""
        -- 표준용어 구성점검 테이블 생성 2 (표준단어와 매핑) - 중복정의 모두 조합된 결과
        SELECT DISTINCT T0.순번, T0.표준용어영문약어, T0.표준용어, ({concat_logic}) AS 조합용어, '-' as 구성점검결과, {query_cols}
        FROM 표준용어_구성점검_TEMP T0 {joins}
    """
    STANDARDS_SQL_DICT["표준용어_구성점검"] = ctas_sql # 동적 SQL 저장
    
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 표준용어_구성점검; CREATE TABLE 표준용어_구성점검 AS {ctas_sql}"): success = False
    if not execute_query(db_path, "UPDATE 표준용어_구성점검 SET 구성점검결과 = CASE WHEN replace(표준용어, ' ', '') = 조합용어 THEN '표준' ELSE '비표준' END"): success = False
    
    # 최종 결과 정리 (표준 우선)
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 표준용어_구성점검_RES; CREATE TABLE 표준용어_구성점검_RES AS {STANDARDS_SQL_DICT['표준용어_구성점검_RES']}"): success = False
    if progress: progress.done()
    return success

def check_compliance(db_path, progress=None):
    # 표준화대상테이블이 없으면 전체 'Y'로 자동 생성
    ensure_target_table_exists(db_path, "표준화대상테이블", ["속성정의"])
    success = True

    # 필수 컬럼(순번) 보장
    for t in ['속성정의', '컬럼정의']:
        chk = select_query(db_path, f"SELECT name FROM sqlite_master WHERE type='table' AND name='{t}'")
        if not chk.empty:
            col_check = select_query(db_path, f"PRAGMA table_info('{t}')")
            if '순번' not in col_check['name'].values:
                execute_query(db_path, f'ALTER TABLE "{t}" ADD COLUMN 순번 INTEGER; UPDATE "{t}" SET 순번 = ROWID;')
    
    # --- 임시 작업용 테이블 생성 (REPLACE 결과 물리화) ---
    if progress: progress.start("속성/용어 정규화 임시 테이블 생성")
    
    # 속성정의 테이블을 읽어와서 파이썬에서 순번 제거 후 _WORK_속성정의 생성
    try:
        df_attr = select_query(db_path, 'SELECT * FROM 속성정의 WHERE "테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 표준화대상테이블 WHERE STANDARD_YN = \'N\')')
        if not df_attr.empty:
            def remove_trailing_seq(val):
                if pd.isna(val) or not isinstance(val, str):
                    return val
                return re.sub(r'(_?[0-9]+)$', '', val.strip())
            
            df_attr['컬럼(영문)'] = df_attr['컬럼(영문)'].apply(remove_trailing_seq)
            df_attr['속성(한글)'] = df_attr['속성(한글)'].apply(remove_trailing_seq)
            df_attr['norm_속성명'] = df_attr['속성(한글)'].apply(lambda x: str(x).replace(' ', '') if pd.notna(x) else '')
            
            conn = get_db_connection(db_path)
            execute_query(db_path, "DROP TABLE IF EXISTS _WORK_속성정의")
            df_attr.to_sql('_WORK_속성정의', conn, if_exists='replace', index=False)
            conn.close()
        else:
            execute_query(db_path, "DROP TABLE IF EXISTS _WORK_속성정의")
            execute_query(db_path, 'CREATE TABLE _WORK_속성정의 AS SELECT *, \'\' as norm_속성명 FROM 속성정의 WHERE 1=0')
    except Exception as e:
        st.error(f"속성정의 정규화 임시 테이블 생성 오류: {e}")
        success = False

    # ALL_용어 → REPLACE 결과 물리화
    if not execute_query(db_path, """
        DROP TABLE IF EXISTS _WORK_ALL_용어;
        CREATE TABLE _WORK_ALL_용어 AS
        SELECT *, REPLACE(용어, ' ', '') as norm_용어명
        FROM ALL_용어;
    """): success = False
    if progress: progress.done()
    
    if progress: progress.start("점검_속성표준준수")
    # 임시 테이블 기반 준수 점검 (단순 등가 조인, 빠름)
    compliance_sql = """
        DROP TABLE IF EXISTS 점검_속성표준준수;
        CREATE TABLE 점검_속성표준준수 AS
        SELECT T.순번, T."엔터티(한글)", T."테이블(영문)", T."컬럼(영문)", T."속성(한글)", T."속성(데이터타입)", T."식별자여부",
               T.점검결과, T.용어, T.용어약어, T.도메인, T.정의수준
        FROM (
            SELECT A.순번, A."엔터티(한글)", A."테이블(영문)", A."컬럼(영문)", A."속성(한글)", A."속성(데이터타입)", A."식별자여부",
                   CASE WHEN A.norm_속성명 = B.norm_용어명 AND B.용어약어 = A."컬럼(영문)" THEN '일치' ELSE '불일치' END as 점검결과,
                   B.용어, B.용어약어, B.도메인,
                   (SELECT 명칭 FROM 정의수준코드 WHERE 코드 = B.정의수준) as 정의수준,
                   ROW_NUMBER() OVER (PARTITION BY A.순번 ORDER BY B.정의수준) as rn
            FROM _WORK_속성정의 A
            LEFT JOIN _WORK_ALL_용어 B ON A.norm_속성명 = B.norm_용어명
        ) T WHERE T.rn = 1;
    """
    if not execute_query(db_path, compliance_sql): success = False
    if progress: progress.done()
    
    # 작업용 임시 테이블 정리
    execute_query(db_path, "DROP TABLE IF EXISTS _WORK_속성정의; DROP TABLE IF EXISTS _WORK_ALL_용어;")
    
    if progress: progress.start("점검_속성표준도메인준수")
    # 도메인 일치 점검 추가 로직 실행
    if not execute_query(db_path, f"DROP TABLE IF EXISTS 점검_속성표준도메인준수; CREATE TABLE 점검_속성표준도메인준수 AS {STANDARDS_SQL_DICT['점검_속성표준도메인준수']}"): success = False
    
    domain_updates = """
    update 점검_속성표준도메인준수 set col_dt = CASE WHEN INSTR("속성(데이터타입)", '(') = 0 THEN "속성(데이터타입)" ELSE SUBSTR("속성(데이터타입)", 1, INSTR("속성(데이터타입)", '(') - 1) END;
    update 점검_속성표준도메인준수 set col_dl = CASE WHEN INSTR("속성(데이터타입)", '(')=0 THEN NULL ELSE TRIM(SUBSTR("속성(데이터타입)", INSTR("속성(데이터타입)", '(') + 1, INSTR("속성(데이터타입)", ')') - INSTR("속성(데이터타입)", '(') - 1)) END;
    update 점검_속성표준도메인준수 set dl_param1 = CASE WHEN INSTR(col_dl, ',')=0 THEN TRIM(col_dl) ELSE TRIM(SUBSTR(col_dl, 1, INSTR(col_dl, ',') - 1)) END;
    update 점검_속성표준도메인준수 set dl_param2 = CASE WHEN col_dl IS NULL OR INSTR(col_dl, ',') = 0 THEN NULL ELSE TRIM(SUBSTR(col_dl, INSTR(col_dl, ',') + 1)) END;
    update 점검_속성표준도메인준수 set 데이터길이 = NULL where 데이터길이='-';
    update 점검_속성표준도메인준수 set col_dt = replace(replace(col_dt, "NUMBER", "NUMERIC"), "VARCHAR2", "VARCHAR");
    update 점검_속성표준도메인준수 set 데이터타입 = replace(replace(데이터타입, "NUMBER", "NUMERIC"), "VARCHAR2", "VARCHAR");
    update 점검_속성표준도메인준수 set "점검결과(도메인)" = CASE 
        WHEN col_dt=데이터타입 and CAST(dl_param1 AS NUMERIC)=CAST(데이터길이 AS NUMERIC) and CAST(dl_param2 AS NUMERIC)=CAST(데이터소수점 AS NUMERIC) THEN "일치" 
        WHEN col_dt=데이터타입 and CAST(dl_param1 AS NUMERIC)=CAST(데이터길이 AS NUMERIC) and dl_param2 IS NULL AND 데이터소수점 IS NULL THEN "일치" 
        WHEN col_dt=데이터타입 and dl_param1 IS NULL AND 데이터길이 IS NULL and dl_param2 IS NULL AND 데이터소수점 IS NULL THEN "일치" 
        ELSE "불일치" END;
    """
    if not execute_query(db_path, domain_updates): success = False
    if progress: progress.done()
    return success

# --- 점검 쿼리 모음 (DB 설계용) ---

DESIGN_SQL_DICT = {
    "점검_설계_01_속성컬럼비교": """
    SELECT DISTINCT B."속성(한글)", B."컬럼(영문)" FROM 속성정의 B WHERE B."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N') AND B."속성(한글)" IN
    (SELECT "속성(한글)" FROM (SELECT DISTINCT "속성(한글)", "컬럼(영문)" FROM 속성정의 WHERE "테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')) GROUP BY "속성(한글)" HAVING COUNT(*)>1);
    """,
    "점검_설계_02_컬럼속성비교": """
    SELECT DISTINCT B."컬럼(영문)", B."속성(한글)" FROM 속성정의 B WHERE B."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N') AND B."컬럼(영문)" IN
    (SELECT "컬럼(영문)" FROM (SELECT DISTINCT "속성(한글)", "컬럼(영문)" FROM 속성정의 WHERE "테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')) GROUP BY "컬럼(영문)" HAVING COUNT(*)>1);
    """,
    "점검_설계_03_속성도메인비교": """
    SELECT DISTINCT B."속성(한글)", B."속성(데이터타입)" FROM 속성정의 B WHERE B."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N') AND B."속성(한글)" IN
    (SELECT "속성(한글)" FROM (SELECT DISTINCT "속성(한글)", "속성(데이터타입)" FROM 속성정의 WHERE "테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')) GROUP BY "속성(한글)" HAVING COUNT(*)>1);
    """,
    "점검_설계_04_컬럼도메인비교": """
    SELECT DISTINCT B."컬럼(영문)", B."속성(데이터타입)" FROM 속성정의 B WHERE B."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N') AND B."컬럼(영문)" IN
    (SELECT "컬럼(영문)" FROM (SELECT DISTINCT "컬럼(영문)", "속성(데이터타입)" FROM 속성정의 WHERE "테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')) GROUP BY "컬럼(영문)" HAVING COUNT(*)>1);
    """,
    "점검_구현_01_속성컬럼비교": """
    SELECT DISTINCT B."속성(한글)", B."컬럼(영문)" FROM 컬럼정의 B WHERE B."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N') AND B."속성(한글)" IN
    (SELECT "속성(한글)" FROM (SELECT DISTINCT "속성(한글)", "컬럼(영문)" FROM 컬럼정의 WHERE "테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')) GROUP BY "속성(한글)" HAVING COUNT(*)>1);
    """,
    "점검_구현_02_컬럼속성비교": """
    SELECT DISTINCT B."컬럼(영문)", B."속성(한글)" FROM 컬럼정의 B WHERE B."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N') AND B."컬럼(영문)" IN
    (SELECT "컬럼(영문)" FROM (SELECT DISTINCT "속성(한글)", "컬럼(영문)" FROM 컬럼정의 WHERE "테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')) GROUP BY "컬럼(영문)" HAVING COUNT(*)>1);
    """,
    "점검_구현_03_속성도메인비교": """
    SELECT DISTINCT B."속성(한글)", B."컬럼(데이터타입)" FROM 컬럼정의 B WHERE B."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N') AND B."속성(한글)" IN
    (SELECT "속성(한글)" FROM (SELECT DISTINCT "속성(한글)", "컬럼(데이터타입)" FROM 컬럼정의 WHERE "테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')) GROUP BY "속성(한글)" HAVING COUNT(*)>1);
    """,
    "점검_구현_04_컬럼도메인비교": """
    SELECT DISTINCT B."컬럼(영문)", B."컬럼(데이터타입)" FROM 컬럼정의 B WHERE B."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N') AND B."컬럼(영문)" IN
    (SELECT "컬럼(영문)" FROM (SELECT DISTINCT "컬럼(영문)", "컬럼(데이터타입)" FROM 컬럼정의 WHERE "테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')) GROUP BY "컬럼(영문)" HAVING COUNT(*)>1);
    """,
    "점검_설계구현비교": """
    SELECT A."테이블(영문)" as 설계_엔터티, A."엔터티(한글)" as 설계_테이블, A."컬럼(영문)" as 설계_컬럼, A."속성(한글)" as 설계_속성, '설계/구현 비교' as 비교결과, B."테이블(영문)" as 구현_엔터티, B."엔터티(한글)" as 구현_테이블, B."컬럼(영문)" as 구현_컬럼, B."속성(한글)" as 구현_속성 FROM 속성정의 A LEFT JOIN 컬럼정의 B ON A."테이블(영문)" = B."테이블(영문)" AND A."컬럼(영문)" = B."컬럼(영문)" WHERE A."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')
    UNION ALL
    SELECT NULL, NULL, NULL, NULL, '설계/구현 비교', B."테이블(영문)", B."엔터티(한글)", B."컬럼(영문)", B."속성(한글)" FROM 컬럼정의 B LEFT JOIN 속성정의 A ON A."테이블(영문)" = B."테이블(영문)" AND A."컬럼(영문)" = B."컬럼(영문)" WHERE A."컬럼(영문)" IS NULL AND B."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N');
    """,
    "점검_설계구현도메인비교": """
    SELECT A."테이블(영문)" as 설계_엔터티, A."컬럼(영문)" as 설계_컬럼, A."속성(데이터타입)" as 설계_속성_데이터타입, B."테이블(영문)" as 구현_엔터티, B."컬럼(영문)" as 구현_컬럼, B."컬럼(데이터타입)" as 구현_컬럼_데이터타입 FROM 속성정의 A JOIN 컬럼정의 B ON A."테이블(영문)" = B."테이블(영문)" AND A."컬럼(영문)" = B."컬럼(영문)" WHERE IFNULL(UPPER(REPLACE(REPLACE(REPLACE(A."속성(데이터타입)", 'DATE(8)', 'DATE'), 'VARCHAR2', 'VARCHAR'), ' ', '')), '') <> IFNULL(UPPER(REPLACE(REPLACE(REPLACE(B."컬럼(데이터타입)", 'DATE(8)', 'DATE'), 'VARCHAR2', 'VARCHAR'), ' ', '')), '') AND A."테이블(영문)" NOT IN (SELECT TABLE_NAME FROM 모델점검대상테이블 WHERE STANDARD_YN = 'N')
    """
}

def check_designed_schema(db_path, progress=None):
    # 모델점검대상테이블이 없으면 전체 'Y'로 자동 생성
    ensure_target_table_exists(db_path, "모델점검대상테이블", ["속성정의", "컬럼정의"])
    
    # 설계 구조 점검
    if progress: progress.start("점검_설계_01_속성컬럼비교")
    execute_query(db_path, f"DROP TABLE IF EXISTS 점검_설계_01_속성컬럼비교; CREATE TABLE 점검_설계_01_속성컬럼비교 AS {DESIGN_SQL_DICT['점검_설계_01_속성컬럼비교']}")
    if progress: progress.done()
    
    if progress: progress.start("점검_설계_02_컬럼속성비교")
    execute_query(db_path, f"DROP TABLE IF EXISTS 점검_설계_02_컬럼속성비교; CREATE TABLE 점검_설계_02_컬럼속성비교 AS {DESIGN_SQL_DICT['점검_설계_02_컬럼속성비교']}")
    if progress: progress.done()
    
    if progress: progress.start("점검_설계_03_속성도메인비교")
    execute_query(db_path, f"DROP TABLE IF EXISTS 점검_설계_03_속성도메인비교; CREATE TABLE 점검_설계_03_속성도메인비교 AS {DESIGN_SQL_DICT['점검_설계_03_속성도메인비교']}")
    if progress: progress.done()
    
    if progress: progress.start("점검_설계_04_컬럼도메인비교")
    execute_query(db_path, f"DROP TABLE IF EXISTS 점검_설계_04_컬럼도메인비교; CREATE TABLE 점검_설계_04_컬럼도메인비교 AS {DESIGN_SQL_DICT['점검_설계_04_컬럼도메인비교']}")
    if progress: progress.done()

def check_impl_schema(db_path, progress=None):
    # 모델점검대상테이블이 없으면 전체 'Y'로 자동 생성
    ensure_target_table_exists(db_path, "모델점검대상테이블", ["속성정의", "컬럼정의"])
    
    # 구현 구조 점검
    if progress: progress.start("점검_구현_01_속성컬럼비교")
    execute_query(db_path, f"DROP TABLE IF EXISTS 점검_구현_01_속성컬럼비교; CREATE TABLE 점검_구현_01_속성컬럼비교 AS {DESIGN_SQL_DICT['점검_구현_01_속성컬럼비교']}")
    if progress: progress.done()
    
    if progress: progress.start("점검_구현_02_컬럼속성비교")
    execute_query(db_path, f"DROP TABLE IF EXISTS 점검_구현_02_컬럼속성비교; CREATE TABLE 점검_구현_02_컬럼속성비교 AS {DESIGN_SQL_DICT['점검_구현_02_컬럼속성비교']}")
    if progress: progress.done()
    
    if progress: progress.start("점검_구현_03_속성도메인비교")
    execute_query(db_path, f"DROP TABLE IF EXISTS 점검_구현_03_속성도메인비교; CREATE TABLE 점검_구현_03_속성도메인비교 AS {DESIGN_SQL_DICT['점검_구현_03_속성도메인비교']}")
    if progress: progress.done()
    
    if progress: progress.start("점검_구현_04_컬럼도메인비교")
    execute_query(db_path, f"DROP TABLE IF EXISTS 점검_구현_04_컬럼도메인비교; CREATE TABLE 점검_구현_04_컬럼도메인비교 AS {DESIGN_SQL_DICT['점검_구현_04_컬럼도메인비교']}")
    if progress: progress.done()

def check_schema_comp(db_path, progress=None):
    # 모델점검대상테이블이 없으면 전체 'Y'로 자동 생성
    ensure_target_table_exists(db_path, "모델점검대상테이블", ["속성정의", "컬럼정의"])
    
    # 설계 vs 구현 비교
    if progress: progress.start("점검_설계구현비교")
    execute_query(db_path, f"DROP TABLE IF EXISTS 점검_설계구현비교; CREATE TABLE 점검_설계구현비교 AS {DESIGN_SQL_DICT['점검_설계구현비교']}")
    execute_query(db_path, "UPDATE 점검_설계구현비교 SET 비교결과='일치' WHERE 설계_컬럼 IS NOT NULL AND 구현_컬럼 IS NOT NULL;")
    execute_query(db_path, "UPDATE 점검_설계구현비교 SET 비교결과='설계누락' WHERE 설계_컬럼 IS NULL;")
    execute_query(db_path, "UPDATE 점검_설계구현비교 SET 비교결과='구현누락' WHERE 구현_컬럼 IS NULL;")
    if progress: progress.done()
    
    # 설계구현 데이터타입(도메인) 비교
    if progress: progress.start("점검_설계구현도메인비교")
    execute_query(db_path, f"DROP TABLE IF EXISTS 점검_설계구현도메인비교; CREATE TABLE 점검_설계구현도메인비교 AS {DESIGN_SQL_DICT['점검_설계구현도메인비교']}")
    if progress: progress.done()

def st_tabs_persistent(tab_list, menu_key):
    """
    글로벌 설정을 사용하여 탭 선택 상태를 유지하는 커스텀 탭 함수.
    표준 st.tabs는 인덱스 지정이 불가능하므로, 라디오 버튼을 탭처럼 스타일링하여 사용합니다.
    """
    config_key = f"tab_selection_{menu_key}"
    saved_tab = get_app_config(config_key, tab_list[0])
    
    try:
        index = tab_list.index(saved_tab)
    except:
        index = 0
        
    # 라디오 버튼을 기본 st.tabs(언더라인 스타일)처럼 보이게 하는 CSS
    st.markdown("""
        <style>
        div.tab-radio-container div[role="radiogroup"] {
            flex-direction: row;
            gap: 24px;
            background-color: transparent;
            padding: 0;
            border: none;
            border-bottom: 1px solid rgba(49, 51, 63, 0.2);
            margin-bottom: 20px;
            border-radius: 0;
        }
        div.tab-radio-container div[role="radiogroup"] > label {
            background-color: transparent !important;
            padding: 10px 4px !important;
            border-radius: 0 !important;
            border: none !important;
            border-bottom: 2px solid transparent !important;
            margin: 0 !important;
            min-width: unset;
            text-align: center;
        }
        div.tab-radio-container div[role="radiogroup"] label:has(div[data-checked="true"]) {
            background-color: transparent !important;
            box-shadow: none !important;
            color: #FF4B4B !important;
            font-weight: 600 !important;
            border-bottom: 2px solid #FF4B4B !important;
            transform: translateY(1px);
        }
        div.tab-radio-container div[role="radiogroup"] label div[data-testid="stMarkdownContainer"] p {
            font-size: 1rem;
            margin: 0;
        }
        /* 라디오 버튼 원형 숨기기 */
        div.tab-radio-container div[role="radiogroup"] [data-testid="stWidgetLabel"] {
            display: none;
        }
        div.tab-radio-container div[role="radiogroup"] label > div:first-child {
            display: none !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="tab-radio-container">', unsafe_allow_html=True)
    selection = st.radio(
        f"Tab Selection for {menu_key}",
        tab_list,
        index=index,
        horizontal=True,
        label_visibility="collapsed"
    )
    st.markdown('</div>', unsafe_allow_html=True)
    
    if selection != saved_tab:
        save_app_config(config_key, selection)
        st.rerun()
        
    return selection

