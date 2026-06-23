import streamlit as st
import config
from modules.db_std_check import show_db_std_check
from modules.db_design_check import show_db_design_check
from modules.db_utils import init_global_config_db, get_recent_project, get_app_config, save_app_config
from modules.settings import load_project

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
    """앱 초기화 로직: 글로벌 DB 생성 및 기본 프로젝트 자동 로드"""
    init_global_config_db()
    
    # 지은모드/심플모드를 제거하고 항상 전체 고급 기능을 활성화
    st.session_state.app_mode_toggle = True
    
    if 'current_project_path' not in st.session_state:
        recent_path, recent_db = get_recent_project()
        if recent_path and os.path.exists(recent_path):
            load_project(recent_path, db_path=recent_db, show_toast=False)
        else:
            # 설정된 경로가 없거나 유효하지 않은 경우 현재 작업 디렉토리를 기본값으로 자동 로드
            default_project_path = os.getcwd()
            default_db_path = os.path.join(default_project_path, "DataDic.db")
            load_project(default_project_path, db_path=default_db_path, show_toast=False)
            
    if 'last_menu_selection' not in st.session_state:
        st.session_state.last_menu_selection = get_app_config('last_menu_selection', '🎯 DB표준점검')

def main():
    initialize_app()

    # 사이드바 메뉴 설정
    with st.sidebar:
        st.markdown(f"""
            <div style="text-align: center; margin-top: 15px; margin-bottom: 15px;">
                <h2 style="color: #FF4B4B; margin-bottom: 5px; font-weight: 800;">🛠️ DataDic</h2>
                <span style="color: gray; font-size: 0.85rem;">DB 표준 및 설계 점검 도구</span>
            </div>
        """, unsafe_allow_html=True)
        st.divider()
        
        menu_options = [
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
        if "prev_selection" not in st.session_state:
            st.session_state.prev_selection = selection
            
        if st.session_state.prev_selection != selection:
            st.session_state.prev_selection = selection
            st.session_state.active_dq_rep = None
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
                                const main = doc.querySelector('section.main');
                                if (main) main.scrollTo({top: 0, behavior: 'auto'});
                            });
                            label.dataset.scrollBound = 'true';
                        }
                    });
                }
                setupSidebarListeners();
                setInterval(setupSidebarListeners, 1000);
            </script>
            """,
            height=0
        )
        
        st.divider()
        st.markdown(f"""
            <div style="font-size: 0.75rem; text-align: center; color: gray; line-height: 1.6;">
                Version {config.APP_VERSION}
            </div>
        """, unsafe_allow_html=True)

    # 선택된 메뉴에 따른 화면 출력
    if selection == "🎯 DB표준점검":
        show_db_std_check()
    elif selection == "🛠️ DB설계점검":
        show_db_design_check()

if __name__ == "__main__":
    main()
