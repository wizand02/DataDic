import streamlit as st
import config
from modules.db_std_check import show_db_std_check
from modules.db_design_check import show_db_design_check
from modules.db_utils import init_global_config_db, get_recent_project, get_app_config, save_app_config
from modules.settings import show_settings, show_project_path_settings, load_project

import os
import sys

def get_asset_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.abspath(relative_path)

# 페이지 기본 설정
st.set_page_config(
    page_title="DataDic - DB 표준/설계 점검 도구",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 메인 제목 및 스타일 설정
st.markdown("""
    <style>
    .main-title {
        font-size: 3rem;
        font-weight: 800;
        background: linear-gradient(45deg, #FF4B4B, #FF8F8F);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 1rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: transparent;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
    
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] {
        gap: 0px;
        margin: 0 -1rem;
    }
    
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {
        padding: 15px 25px !important;
        margin: 0 !important;
        width: 100% !important;
        border-radius: 0px !important;
        cursor: pointer;
        transition: background-color 0.2s;
        border-right: 5px solid transparent;
    }

    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:has(div[data-checked="true"]) {
        background-color: #FF4B4B !important;
        border-right: 5px solid #bd1b1b !important;
    }
    
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:has(div[data-checked="true"]) p {
        color: white !important;
        font-weight: 700 !important;
    }
    
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover:not(:has(div[data-checked="true"])) {
        background-color: rgba(255, 75, 75, 0.1);
    }

    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label > div:first-child {
        display: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

def initialize_app():
    """앱 초기화 로직: 글로벌 DB 생성 및 최근 프로젝트 로드"""
    init_global_config_db()
    
    if 'current_project_path' not in st.session_state:
        recent_path, recent_db = get_recent_project()
        if recent_path and os.path.exists(recent_path):
            load_project(recent_path, db_path=recent_db, show_toast=False)
    
    # 지은 모드(is_expert) 설정 로드
    if 'app_mode_toggle' not in st.session_state:
        saved_mode = get_app_config('is_expert', 'False')
        st.session_state.app_mode_toggle = (saved_mode == 'True')

    # 마지막 메뉴 선택 로드
    if 'last_menu_selection' not in st.session_state:
        st.session_state.last_menu_selection = get_app_config('last_menu_selection', '🎯 DB표준점검')

def main():
    initialize_app()

    # 사이드바 메뉴 설정
    with st.sidebar:
        # 현재 활성 프로젝트 표시 (사이드바 상단)
        if 'current_project_path' in st.session_state and st.session_state.current_project_path:
            path = st.session_state.current_project_path
            db_path = st.session_state.get('current_db_path')
            db_name = os.path.basename(db_path) if db_path and os.path.exists(db_path) else "연결된 DB 없음"
            
            st.markdown(f"""
                <div style="background-color: rgba(255, 75, 75, 0.05); padding: 12px; border-radius: 8px 8px 0 0; border: 1px solid rgba(255, 75, 75, 0.2); border-bottom: none; margin-top: 10px;">
                    <div style="color: #FF4B4B; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; margin-bottom: 4px;">ACTIVE PROJECT</div>
                    <div style="font-size: 0.8rem; color: #333; word-break: break-all; font-family: monospace; line-height: 1.2; margin-bottom: 10px;">{path}</div>
                    <div style="color: #FF4B4B; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; margin-bottom: 4px;">ACTIVE DB</div>
                    <div style="font-size: 0.8rem; color: #333; word-break: break-all; font-family: monospace; line-height: 1.2;">{db_name}</div>
                </div>
            """, unsafe_allow_html=True)
            if st.button("📁 폴더 열기", key="open_explorer_sidebar", use_container_width=True):
                if os.path.exists(path):
                    os.startfile(path)
                else:
                    st.sidebar.error("⚠️ 경로를 찾을 수 없습니다.")
        
        st.divider()
        
        st.markdown(
            """
            <style>
            /* 토글 버튼 컨테이너를 약간 꾸밈 */
            div[data-testid="stSidebar"] div[data-testid="stToggle"] {
                background-color: rgba(255, 75, 75, 0.05);
                padding: 10px 15px;
                border-radius: 8px;
                border: 1px solid rgba(255, 75, 75, 0.2);
                margin-top: -10px;
            }
            div[data-testid="stSidebar"] div[data-testid="stToggle"] label p {
                font-weight: 600;
                color: #444;
                font-size: 0.95rem;
            }
            </style>
            """, unsafe_allow_html=True
        )
        
        is_expert = st.toggle(
            "🚀 지은 모드 활성화", 
            value=st.session_state.get('app_mode_toggle', False), 
            help="활성화하면 모든 고급 기능을 사용할 수 있습니다. (기본: 심플 모드)",
            key="app_mode_toggle_widget"
        )
        
        # 모드가 변경되었으면 DB에 저장
        if 'app_mode_toggle' not in st.session_state or st.session_state.app_mode_toggle != is_expert:
            st.session_state.app_mode_toggle = is_expert
            save_app_config('is_expert', str(is_expert))
            
        app_mode = "지은 모드" if is_expert else "심플 모드"
        
        # 현재 상태 표시 뱃지
        if is_expert:
            st.markdown(
                """<div style='background-color: #FF4B4B; color: white; padding: 8px 10px; border-radius: 5px; text-align: center; font-weight: bold; font-size: 0.85rem; margin-top: 5px; margin-bottom: 5px;'>
                🔥 현재 상태: 지은 모드
                </div>""", unsafe_allow_html=True
            )
        else:
            st.markdown(
                """<div style='background-color: #F0F2F6; color: #31333F; padding: 8px 10px; border-radius: 5px; text-align: center; font-weight: bold; font-size: 0.85rem; margin-top: 5px; margin-bottom: 5px; border: 1px solid #E0E2E6;'>
                🌱 현재 상태: 심플 모드
                </div>""", unsafe_allow_html=True
            )
        
        st.divider()
        
        # DB 표준점검, DB 설계점검 및 설정만 남김
        if app_mode == "심플 모드":
            menu_options = [
                "📁 프로젝트 경로 설정", 
                "🎯 DB표준점검",
                "🛠️ DB설계점검"
            ]
        else:
            menu_options = [
                "⚙️ 설정",
                "🎯 DB표준점검",
                "🛠️ DB설계점검"
            ]
        
        # 초기 인덱스 계산
        try:
            menu_index = menu_options.index(st.session_state.last_menu_selection)
        except:
            menu_index = 0

        selection = st.radio(
            "메뉴 선택",
            menu_options,
            index=menu_index,
            label_visibility="collapsed",
            key="sidebar_menu_radio_widget"
        )
        
        # 메뉴 변경 시 저장
        if selection != st.session_state.last_menu_selection:
            st.session_state.last_menu_selection = selection
            save_app_config('last_menu_selection', selection)
        
        # ── 팝업 닫기 및 스크롤 제어 로직 ──
        # 메뉴가 변경되거나 클릭될 때 팝업 상태 초기화
        if "prev_selection" not in st.session_state:
            st.session_state.prev_selection = selection
            
        if st.session_state.prev_selection != selection:
            st.session_state.prev_selection = selection
            # 모든 팝업 관련 세션 상태 초기화
            st.session_state.active_dq_rep = None
            # 화면 상단 이동 실행
            st.components.v1.html("<script>window.parent.document.querySelector('section.main').scrollTo(0,0);</script>", height=0)

        # 현재 메뉴를 다시 눌렀을 때도 상단 이동을 보장하기 위한 JS 리스너
        st.components.v1.html(
            """
            <script>
                function setupSidebarListeners() {
                    const doc = window.parent.document;
                    const labels = doc.querySelectorAll('[data-testid="stSidebar"] .stRadio label');
                    labels.forEach(label => {
                        if (!label.dataset.scrollBound) {
                            label.addEventListener('click', () => {
                                // 즉시 스크롤 상단 이동
                                const main = doc.querySelector('section.main');
                                if (main) main.scrollTo({top: 0, behavior: 'auto'});
                            });
                            label.dataset.scrollBound = 'true';
                        }
                    });
                }
                setupSidebarListeners();
                // 동적 렌더링 대응을 위해 반복 체크
                setInterval(setupSidebarListeners, 1000);
            </script>
            """,
            height=0
        )
        
        # ── 디버그/상태 정보 ──
        with st.expander("🛠️ 시스템 상태", expanded=False):
            st.markdown(f"""
                <div style="font-size: 0.8rem; line-height: 1.6;">
                    <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-bottom: 8px;">
                        <span style="font-weight: 600; color: #666;">Version</span>
                        <span style="color: #FF4B4B;">{config.APP_VERSION}</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            if os.path.exists(config.GLOBAL_CONFIG_DB_PATH):
                recent_p, recent_d = get_recent_project()
                db_name_only = os.path.basename(recent_d) if recent_d else "미지정"
                
                st.markdown(f"""
                    <div style="font-size: 0.75rem; background-color: #f8f9fa; padding: 8px; border-radius: 4px; border-left: 3px solid #FF4B4B;">
                        <div style="color: #888; font-weight: 700; margin-bottom: 2px;">RECENT PROJECT</div>
                        <div style="word-break: break-all; color: #333; margin-bottom: 8px; font-family: monospace;">{recent_p if recent_p else '없음'}</div>
                        <div style="color: #888; font-weight: 700; margin-bottom: 2px;">RECENT SQLITE DB</div>
                        <div style="word-break: break-all; color: #333; font-family: monospace;">{db_name_only}</div>
                    </div>
                """, unsafe_allow_html=True)
                st.caption("✅ 글로벌 설정 연결됨")
            else:
                st.error("❌ 글로벌 DB 연결 실패")

    # 선택된 메뉴에 따른 화면 출력
    if selection == "⚙️ 설정":
        show_settings()
    elif selection == "📁 프로젝트 경로 설정":
        show_project_path_settings()
    elif selection == "🎯 DB표준점검":
        show_db_std_check()
    elif selection == "🛠️ DB설계점검":
        show_db_design_check()

if __name__ == "__main__":
    main()
