import streamlit as st
import os
import config
import sqlite3
import pandas as pd
import uuid
from modules.db_utils import save_recent_project, get_recent_project

def load_project(full_path, db_path=None, show_toast=True, update_ui=True):
    """주어진 경로의 프로젝트를 로드하고 세션 상태를 업데이트"""
    if not full_path or not os.path.exists(full_path):
        return False
    
    try:
        # 경로 정규화 (슬래시 방향 통일 등)
        full_path = os.path.normpath(full_path)
        
        # DB 파일명 계산 (프로젝트 폴더명 기준 또는 전달된 경로)
        actual_p_name = os.path.basename(full_path)
        if not db_path:
            db_filename = f"{actual_p_name}.db"
            db_path = os.path.join(full_path, db_filename)
        else:
            db_filename = os.path.basename(db_path)
        
        # 0. UI 갱신을 위해 root_path만 설정하여 하위 폴더를 따로 설정하지 않게 함
        st.session_state.root_path = full_path
        st.session_state.project_name = ""  # Project Name 입력란은 빈 값으로 초기화
        
        # 위젯 키를 삭제하여 입력란이 자동으로 초기화되도록 함 (위젯 값 동기화)
        if 'input_project_name_manual' in st.session_state:
            del st.session_state.input_project_name_manual
        
        if update_ui:
            try:
                st.session_state.input_root_path_manual = st.session_state.root_path
            except:
                pass

        # 1. DB 경로 확인 후 세션에 저장
        st.session_state.current_db_path = db_path
        st.session_state.current_project_path = full_path
        
        # 2. 실제 하위 폴더를 스캔하여 '사용자 지정 폴더' 상태 업데이트
        physical_folders = [f for f in os.listdir(full_path) if os.path.isdir(os.path.join(full_path, f)) and not f.startswith('.')]
        if physical_folders:
            st.session_state.custom_folders = sorted(physical_folders)
        else:
            # 폴더가 없으면 기본값 사용
            st.session_state.custom_folders = list(config.DEFAULT_PROJECT_FOLDERS)

        # 3. DB 파일 존재 확인 후 없으면 신규 DB 생성 (빈 빈 DB만 생성)
        if not os.path.exists(db_path):
            sqlite3.connect(db_path).close()
            if show_toast: st.toast(f"✅ 신규 DB 파일 생성 완료: {db_filename}")
        elif show_toast:
            st.toast(f"✅ 프로젝트 로드 완료: {actual_p_name}")

        # 4. 최근 프로젝트 저장 (글로벌 DB)
        save_recent_project(full_path, db_path)
        
        # 5. UI 위젯 상태 초기화
        for k in list(st.session_state.keys()):
            if k.startswith("ui_"):
                del st.session_state[k]
        
        return True
    except Exception as e:
        st.error(f"❌ 프로젝트 로드 오류: {e}")
        return False

def select_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        folder_path = filedialog.askdirectory(master=root)
        root.destroy()
        return folder_path
    except Exception as e:
        st.error("⚠️ 현재 실행 환경(예: Streamlit Cloud)에서는 폴더 선택 창을 지원하지 않습니다. 아래 경로 입력창에 직접 입력해 주세요.")
        return None

def init_settings_session():
    # 1. 근본 변수 초기화 (AttributeError 방지)
    if 'root_path' not in st.session_state:
        st.session_state.root_path = ""
    if 'project_name' not in st.session_state:
        st.session_state.project_name = ""

    # 2. 위젯 연결용 변수 초기화 (경고 방지)
    if 'input_root_path_manual' not in st.session_state:
        st.session_state.input_root_path_manual = st.session_state.root_path
    if 'input_project_name_manual' not in st.session_state:
        st.session_state.input_project_name_manual = st.session_state.project_name

def show_project_path_settings():
    init_settings_session()
    
    st.subheader("📁 프로젝트 경로 설정")
    col1, col2 = st.columns([0.7, 0.3])
    
    with col2:
        st.write("") # 간격 맞춤
        st.write("")
        if st.button("경로 선택", key="btn_path"):
            selected_path = select_folder()
            if selected_path:
                # 세션 상태 직접 업데이트 (화면 즉시 반영)
                st.session_state.input_root_path_manual = selected_path
                st.session_state.root_path = selected_path

    with col1:
        # value 인자를 제거하여 세션 상태와 충돌 방지
        st.text_input(
            "Project Path: ", 
            key="input_root_path_manual" 
        )
        st.session_state.root_path = st.session_state.input_root_path_manual

    st.text_input(
        "Project Name (최상위 폴더 생성이 필요할 경우만 입력): ",
        key="input_project_name_manual"
    )
    st.session_state.project_name = st.session_state.input_project_name_manual

    if st.button("💾 프로젝트 경로 확정", use_container_width=True):
        if not st.session_state.root_path:
            st.error("Project Path를 먼저 선택해 주세요.")
        else:
            try:
                p_name = st.session_state.project_name.strip()
                full_path = os.path.join(st.session_state.root_path, p_name) if p_name else st.session_state.root_path
                
                if p_name and not os.path.exists(full_path):
                    os.makedirs(full_path)
                    st.info(f"✨ 신규 폴더 생성: {full_path}")
                elif p_name and os.path.exists(full_path):
                    st.info(f"ℹ️ 폴더가 이미 존재합니다: {full_path}")

                # DB 파일 설정 (프로젝트명 또는 현재 폴더명 기준)
                actual_p_name = p_name if p_name else os.path.basename(os.path.abspath(full_path))
                db_filename = f"{actual_p_name}.db"
                db_path = os.path.join(full_path, db_filename)
                
                # 1. DB 연결 확인 및 세션 저장
                st.session_state.current_db_path = db_path
                st.session_state.current_project_path = full_path
                
                # 2. 실제 폴더 구조 스캔하여 '하위 폴더 설정' 세션 업데이트
                if os.path.exists(full_path):
                    physical_folders = [f for f in os.listdir(full_path) if os.path.isdir(os.path.join(full_path, f)) and not f.startswith('.')]
                    if physical_folders:
                        st.session_state.custom_folders = sorted(physical_folders)
                    else:
                        # 폴더가 비어있으면 기본값 유지
                        st.session_state.custom_folders = list(config.DEFAULT_PROJECT_FOLDERS)

                # 3. 기존 DB 확인 및 신규 DB 파일 즉시 생성 (심플모드 등에서 DB수동생성 불가 대비)
                if os.path.exists(db_path):
                    st.toast(f"✅ 기존 프로젝트 확인: {actual_p_name} (DB 연결됨)")
                else:
                    try:
                        sqlite3.connect(db_path).close()
                        st.toast(f"✅ 새 프로젝트 설정 및 신규 DB 파일 생성 완료: {db_filename}")
                    except Exception as db_e:
                        st.error(f"❌ 신규 DB 파일 생성 실패: {db_e}")
                
                # 4. UI 입력값 초기화 (새 프로젝트 DB 정보를 다시 읽기 위해)
                for k in list(st.session_state.keys()):
                    if k.startswith("ui_"):
                        del st.session_state[k]
                
                # 5. 글로벌 DB 저장
                save_recent_project(full_path, db_path)
                
                st.rerun()
            except Exception as e:
                st.error(f"❌ 오류 발생: {e}")

def show_settings():
    init_settings_session()

    # 설정 메뉴를 탭으로 분리
    tab_path, tab_db, tab_folders = st.tabs([
        "📁 프로젝트 경로", 
        "💾 SQLITE.DB",
        "📂 하위 폴더 설정"
    ])

    # 1. 프로젝트 경로 설정 탭
    with tab_path:
        show_project_path_settings()

    # 2. SQLITE.DB 정보 탭
    with tab_db:
        st.subheader("💾 SQLite 데이터베이스 관리")
        db_path = st.session_state.get('current_db_path')
        project_path = st.session_state.get('current_project_path')
        
        if db_path and project_path:
            # 1. 상단: 현재 DB 경로와 초기화 버튼을 가로로 배치 (하단 정렬)
            col_db, col_init = st.columns([0.8, 0.2], vertical_alignment="bottom")
            with col_db:
                st.text_input("현재 연결된 DB 경로", value=db_path, disabled=True)
            with col_init:
                if st.button("🔄 DB 초기화", help="기존 DB 파일을 삭제하고 빈 파일로 재생성합니다.", use_container_width=True, type="secondary"):
                    try:
                        if os.path.exists(db_path):
                            os.remove(db_path)
                        sqlite3.connect(db_path).close()
                        st.toast("✅ 데이터베이스 파일이 초기화되었습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 초기화 중 오류: {e}")
            
            st.write("")
            if os.path.exists(db_path):
                file_size = os.path.getsize(db_path) / 1024
                st.success(f"✅ DB 파일 접속 가능 (물리적 크기: {file_size:.1f} KB)")
            else:
                st.warning("⚠️ 파일이 아직 물리적으로 생성되지 않았습니다.")
            
            st.divider()
            
            # 2. 중단: 기존 DB 선택
            st.markdown("##### 📂 기존 DB 파일 선택")
            if os.path.exists(project_path):
                existing_dbs = [f for f in os.listdir(project_path) if f.lower().endswith('.db')]
                if existing_dbs:
                    col_sel_db, col_sel_btn = st.columns([0.8, 0.2], vertical_alignment="bottom")
                    with col_sel_db:
                        current_idx = 0
                        current_db_name = os.path.basename(db_path)
                        if current_db_name in existing_dbs:
                            current_idx = existing_dbs.index(current_db_name)
                        
                        selected_db = st.selectbox("연결할 데이터베이스 파일을 선택하세요", options=existing_dbs, index=current_idx)
                    with col_sel_btn:
                        if st.button("🔗 DB 연결", use_container_width=True):
                            new_target_path = os.path.join(project_path, selected_db)
                            if new_target_path != db_path:
                                st.session_state.current_db_path = new_target_path
                                save_recent_project(project_path, new_target_path)
                                st.toast(f"✅ 데이터베이스 연결이 변경되었습니다: {selected_db}")
                                st.rerun()
                else:
                    st.info("📦 현재 프로젝트 폴더에 선택할 수 있는 다른 DB 파일이 없습니다.")
            
            st.divider()
            
            # 3. 하단: 새로운 DB 파일 생성/연결
            st.markdown("##### ➕ 신규 DB 파일 추가")
            st.info("현재 프로젝트 폴더 내에 새로운 DB 파일을 만들고 활성화합니다.")
            
            col_new_name, col_new_btn = st.columns([0.8, 0.2], vertical_alignment="bottom")
            with col_new_name:
                new_db_name = st.text_input("새 DB 파일명 (확장자 .db 포함/생략 가능)", placeholder="예: my_new_db", key="input_new_db_name")
            with col_new_btn:
                if st.button("🆕 DB 생성", type="primary", use_container_width=True):
                    if new_db_name.strip():
                        # 확장자 보정
                        final_filename = new_db_name.strip()
                        if not final_filename.lower().endswith(".db"):
                            final_filename += ".db"
                            
                        new_db_path = os.path.join(project_path, final_filename)
                        
                        try:
                            if not os.path.exists(new_db_path):
                                sqlite3.connect(new_db_path).close()
                                st.toast(f"✅ 새 데이터베이스 파일 생성 완료: {final_filename}")
                            else:
                                st.toast(f"ℹ️ 기존 데이터베이스로 연결 전환: {final_filename}")
                            
                            # 세션 DB 경로 변경
                            st.session_state.current_db_path = new_db_path
                            save_recent_project(project_path, new_db_path)
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ 데이터베이스 생성/연결 에러: {e}")
                    else:
                        st.error("새로 지정할 DB 파일명을 입력해주세요.")

        else:
            st.warning("⚠️ [프로젝트 경로] 탭에서 먼저 경로를 확정해 주세요.")

    # 3. 하위 폴더 설정 탭
    with tab_folders:
        st.subheader("📂 하위 폴더 구성 관리")
        
        project_path = st.session_state.get('current_project_path')
        if not project_path:
            st.warning("⚠️ 프로젝트 경로를 먼저 확정해 주세요.")
        else:
            # 1. 원본 목록(custom_folders) 및 편집용 목록(temp_folders) 초기화
            if 'custom_folders' not in st.session_state:
                if os.path.exists(project_path):
                    physical = [f for f in os.listdir(project_path) if os.path.isdir(os.path.join(project_path, f)) and not f.startswith('.')]
                    st.session_state.custom_folders = sorted(physical) if physical else []
                else:
                    st.session_state.custom_folders = []
            
            # 편집 중인 임시 목록 초기화 및 데이터 형식 마이그레이션 (TypeError 방지)
            if 'temp_folders' not in st.session_state:
                st.session_state.temp_folders = [{"id": str(uuid.uuid4()), "name": f} for f in st.session_state.custom_folders]
            elif len(st.session_state.temp_folders) > 0 and isinstance(st.session_state.temp_folders[0], str):
                # 구식 데이터(문자열 리스트)가 존재할 경우 강제로 새로운 형식(딕셔너리 리스트)으로 변환
                st.session_state.temp_folders = [{"id": str(uuid.uuid4()), "name": f} for f in st.session_state.temp_folders]

            col_info, col_reload = st.columns([0.8, 0.2])
            with col_info:
                st.info(f"📍 대상 경로: `{project_path}`")
            with col_reload:
                if st.button("🔄 폴더 리로드", help="현재 대상 경로의 실제 하위 폴더 목록을 다시 읽어옵니다.", use_container_width=True):
                    if os.path.exists(project_path):
                        physical = [f for f in os.listdir(project_path) if os.path.isdir(os.path.join(project_path, f)) and not f.startswith('.')]
                        st.session_state.custom_folders = sorted(physical) if physical else []
                    else:
                        st.session_state.custom_folders = []
                    st.session_state.temp_folders = [{"id": str(uuid.uuid4()), "name": f} for f in st.session_state.custom_folders]
                    st.rerun()
            
            # --- 1. 기본 폴더 선택 추가 구역 ---
            with st.expander("✨ 기본(DEFAULT) 폴더에서 선택하여 추가", expanded=True):
                # 현재 편집 목록에 있는 이름들을 집합으로 추출
                current_names = set(f['name'] for f in st.session_state.temp_folders)
                # 기본 목록 중 현재 목록에 없는 것들만 필터링
                available_defaults = [f for f in config.DEFAULT_PROJECT_FOLDERS if f not in current_names]

                if not available_defaults:
                    st.success("모든 기본 폴더가 이미 목록에 추가되었습니다.")
                else:
                    st.markdown("추가할 기본 폴더를 선택하세요:")
                    
                    # 체크박스들을 2열로 배치
                    cols_def = st.columns(2)
                    selected_defaults = []
                    for i, def_f in enumerate(available_defaults):
                        with cols_def[i % 2]:
                            if st.checkbox(def_f, key=f"def_chk_{def_f}"):
                                selected_defaults.append(def_f)
                    
                    st.write("") # 간격 조절
                    
                    c1, c2 = st.columns([0.5, 0.5])
                    with c1:
                        if st.button("📥 선택한 기본 폴더를 목록에 추가", use_container_width=True):
                            added_count = 0
                            for f in selected_defaults:
                                # 버튼 클릭 시점에도 한 번 더 체크 (방어적 코드)
                                if f not in set(f['name'] for f in st.session_state.temp_folders):
                                    st.session_state.temp_folders.append({"id": str(uuid.uuid4()), "name": f})
                                    added_count += 1
                            
                            if added_count > 0:
                                st.toast(f"✅ {added_count}개의 기본 폴더가 추가되었습니다.")
                                st.rerun()
                    with c2:
                        if st.button("➕ 직접 입력 폴더 추가", use_container_width=True):
                            st.session_state.temp_folders.append({"id": str(uuid.uuid4()), "name": f"새_폴더_{len(st.session_state.temp_folders)+1}"})
                            st.rerun()

            st.divider()

            # --- 2. 폴더 목록 편집 리스트 ---
            st.markdown("##### 📝 실시간 편집 목록")
            
            if not st.session_state.temp_folders:
                st.caption("목록이 비어 있습니다. 위에서 폴더를 추가해 주세요.")
            
            # 리스트를 순회하며 편집 UI 출력
            for i, item in enumerate(st.session_state.temp_folders):
                # 물리적 존재 여부 확인 (원본 custom_folders 기준으로 체크하여 상태 표시)
                full_sub_path = os.path.join(project_path, item['name'])
                is_exists = os.path.exists(full_sub_path)
                
                col_status, col_in, col_del = st.columns([0.1, 0.75, 0.15])
                
                with col_status:
                    if is_exists:
                        st.markdown("✅", help="폴더가 생성되어 있음")
                    else:
                        st.markdown("⚪", help="목록에만 존재 (미생성)")
                
                with col_in:
                    # key에 고유 ID를 사용하여 인덱스 밀림 현상 방지
                    u_name = st.text_input(f"폴더 {item['id']}", value=item['name'], key=f"folder_input_{item['id']}", label_visibility="collapsed")
                    item['name'] = u_name # 실시간 값 업데이트
                
                with col_del:
                    if st.button("🗑️", key=f"del_folder_{item['id']}", help="목록에서 제거"):
                        st.session_state.temp_folders = [x for x in st.session_state.temp_folders if x['id'] != item['id']]
                        # 위젯 상태 정리 (선택 사항)
                        if f"folder_input_{item['id']}" in st.session_state:
                            del st.session_state[f"folder_input_{item['id']}"]
                        st.rerun()

            st.divider()

            # --- 편집 제어 버튼 ---
            col_apply, col_cancel = st.columns(2)
            with col_apply:
                if st.button("💾 저장 및 폴더 생성 (동기화)", use_container_width=True, type="primary"):
                    # 1. 세션 상태 업데이트 (이름 리스트로 변환하여 저장)
                    st.session_state.custom_folders = [f['name'] for f in st.session_state.temp_folders]
                    
                    # 2. 물리적 폴더 생성 수행
                    try:
                        created_count = 0
                        for folder_name in st.session_state.custom_folders:
                            if folder_name.strip():
                                sub_path = os.path.join(project_path, folder_name.strip())
                                if not os.path.exists(sub_path):
                                    os.makedirs(sub_path)
                                    created_count += 1
                        
                        st.toast(f"✅ 저장 및 폴더 생성이 완료되었습니다. (신규: {created_count}개)")
                    except Exception as e:
                        st.error(f"❌ 폴더 생성 중 오류 발생: {e}")
                    
                    st.rerun()

            with col_cancel:
                if st.button("⏪ 취소 (물리 구조로 새로고침)", use_container_width=True):
                    # 실제 경로 스캔하여 상태 복구
                    if os.path.exists(project_path):
                        physical = [f for f in os.listdir(project_path) if os.path.isdir(os.path.join(project_path, f)) and not f.startswith('.')]
                        st.session_state.custom_folders = sorted(physical)
                        # 새로운 고유 ID와 함께 임시 목록 재생성
                        st.session_state.temp_folders = [{"id": str(uuid.uuid4()), "name": f} for f in st.session_state.custom_folders]
                    
                    # 모든 이전 위젯 키 초기화
                    for k in list(st.session_state.keys()):
                        if k.startswith("folder_input_"):
                            del st.session_state[k]
                    
                    st.toast("ℹ️ 변경사항을 취소하고 물리적 폴더 구조를 다시 불러왔습니다.")
                    st.rerun()

            st.divider()
            st.caption("※ '저장' 시 목록의 폴더가 실제 생성되며, '취소' 시 실제 폴더 상태로 목록이 초기화됩니다.")




