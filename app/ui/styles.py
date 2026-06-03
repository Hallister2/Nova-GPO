from __future__ import annotations


THEME_LABELS = {
    "executive_dark": "Executive Dark",
    "clean_light": "Graphite Light",
}


THEMES = {
    "executive_dark": {
        "app": "#101112",
        "sidebar": "#141516",
        "panel": "#18191B",
        "raised": "#202123",
        "field": "#141516",
        "text": "#F4F6F8",
        "secondary": "#C0C3C7",
        "muted": "#85888E",
        "border": "rgba(255, 255, 255, 0.08)",
        "soft": "rgba(255, 255, 255, 0.04)",
        "hover": "#292A2D",
        "orange": "#FF8A1F",
        "orange_hover": "#FFA13D",
        "success": "#3DDC84",
        "danger": "#FF4D4D",
        "blue": "#82B6FF",
        "badge": "#252628",
        "disabled": "#1A1B1D",
        "primary_text": "#16100A",
    },
    "clean_light": {
        "app": "#E7E6E2",
        "sidebar": "#DAD9D4",
        "panel": "#F1F0EC",
        "raised": "#E2E1DC",
        "field": "#F8F7F3",
        "text": "#202224",
        "secondary": "#4F5358",
        "muted": "#73777D",
        "border": "rgba(32, 34, 36, 0.16)",
        "soft": "rgba(32, 34, 36, 0.055)",
        "hover": "#D4D3CE",
        "orange": "#FF7A1A",
        "orange_hover": "#FF8F33",
        "success": "#0E9F6E",
        "danger": "#E02424",
        "blue": "#2F6FB7",
        "badge": "#DFDED9",
        "disabled": "#E1E0DC",
        "primary_text": "#1C1308",
    },
}


def build_stylesheet(theme_name: str = "executive_dark") -> str:
    t = THEMES.get(theme_name, THEMES["executive_dark"])

    return f"""
QWidget {{
    background-color: {t["app"]};
    color: {t["text"]};
    font-family: Segoe UI;
    font-size: 13px;
}}

QFrame#Sidebar {{
    background-color: {t["sidebar"]};
    border-right: 1px solid {t["border"]};
}}

QFrame#Panel {{
    background-color: {t["panel"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
}}

QFrame#RaisedPanel {{
    background-color: {t["raised"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
}}

QFrame#HeroPanel {{
    background-color: {t["panel"]};
    border: 1px solid rgba(255, 138, 31, 0.22);
    border-radius: 8px;
}}

QLabel {{
    background-color: transparent;
}}

QLabel#BrandIcon {{
    background-color: transparent;
}}

QLabel#BrandLogo {{
    background-color: transparent;
}}

QLabel#HeroOrb {{
    background-color: transparent;
}}

QLabel#EmptyStateImage {{
    background-color: transparent;
}}

QLabel#Logo {{
    color: {t["orange"]};
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 0;
}}

QLabel#LogoSub {{
    color: {t["text"]};
    font-size: 11px;
    letter-spacing: 0;
    font-weight: 700;
}}

QLabel#Title {{
    color: {t["text"]};
    font-size: 24px;
    font-weight: 700;
}}

QLabel#PanelTitle {{
    color: {t["text"]};
    font-size: 18px;
    font-weight: 700;
}}

QLabel#Muted {{
    color: {t["muted"]};
    font-size: 12px;
}}

QLabel#SidebarFooterBrand {{
    color: {t["secondary"]};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}

QLabel#StatusLabel {{
    color: {t["secondary"]};
    font-size: 11px;
    font-weight: 800;
}}

QLabel#StatusBadge {{
    background-color: {t["badge"]};
    color: {t["secondary"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 800;
}}

QLabel#StatusBadge[state="same"] {{
    background-color: rgba(61, 220, 132, 0.13);
    color: {t["success"]};
    border: 1px solid rgba(61, 220, 132, 0.25);
}}

QLabel#StatusBadge[state="diff"] {{
    background-color: rgba(255, 77, 77, 0.13);
    color: {t["danger"]};
    border: 1px solid rgba(255, 77, 77, 0.25);
}}

QLabel#StatusBadge[state="added"] {{
    background-color: rgba(61, 220, 132, 0.13);
    color: {t["success"]};
    border: 1px solid rgba(61, 220, 132, 0.25);
}}

QLabel#StatusBadge[state="removed"] {{
    background-color: rgba(255, 77, 77, 0.13);
    color: {t["danger"]};
    border: 1px solid rgba(255, 77, 77, 0.25);
}}

QLabel#StatusBadge[state="changed"] {{
    background-color: rgba(255, 138, 31, 0.13);
    color: {t["orange"]};
    border: 1px solid rgba(255, 138, 31, 0.28);
}}

QLabel#StatusBadge[state="unchanged"] {{
    background-color: {t["badge"]};
    color: {t["secondary"]};
    border: 1px solid {t["border"]};
}}

QLabel#StatusBadge[state="valid"] {{
    background-color: rgba(61, 220, 132, 0.13);
    color: {t["success"]};
    border: 1px solid rgba(61, 220, 132, 0.25);
}}

QLabel#StatusBadge[state="review"] {{
    background-color: rgba(130, 182, 255, 0.13);
    color: {t["blue"]};
    border: 1px solid rgba(130, 182, 255, 0.25);
}}

QLabel#StatusBadge[state="enabled"] {{
    background-color: rgba(61, 220, 132, 0.13);
    color: {t["success"]};
    border: 1px solid rgba(61, 220, 132, 0.25);
}}

QLabel#StatusBadge[state="disabled"] {{
    background-color: rgba(255, 138, 31, 0.12);
    color: {t["orange"]};
    border: 1px solid rgba(255, 138, 31, 0.26);
}}

QLabel#StatusBadge[state="unknown"] {{
    background-color: rgba(255, 255, 255, 0.04);
    color: {t["muted"]};
    border: 1px solid {t["border"]};
}}

QLabel#StatusBadge[state="severity-high"] {{
    background-color: rgba(255, 77, 77, 0.14);
    color: {t["danger"]};
    border: 1px solid rgba(255, 77, 77, 0.30);
}}

QLabel#StatusBadge[state="severity-medium"] {{
    background-color: rgba(255, 138, 31, 0.13);
    color: {t["orange"]};
    border: 1px solid rgba(255, 138, 31, 0.28);
}}

QLabel#StatusBadge[state="severity-low"] {{
    background-color: rgba(130, 182, 255, 0.12);
    color: {t["blue"]};
    border: 1px solid rgba(130, 182, 255, 0.24);
}}

QLabel#StatusBadge[state="empty"] {{
    background-color: rgba(255, 255, 255, 0.035);
    color: {t["muted"]};
    border: 1px solid {t["border"]};
}}

QPushButton {{
    background-color: {t["raised"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    border-radius: 7px;
    padding: 9px 14px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: {t["hover"]};
    border: 1px solid rgba(255, 138, 31, 0.24);
}}

QPushButton#PrimaryButton {{
    background-color: {t["orange"]};
    color: {t["primary_text"]};
    border: 1px solid {t["orange_hover"]};
}}

QPushButton#PrimaryButton:hover {{
    background-color: {t["orange_hover"]};
}}

QPushButton#GhostButton {{
    background-color: transparent;
    color: {t["secondary"]};
    border: 1px solid {t["border"]};
}}

QPushButton#GhostButton:hover {{
    background-color: {t["soft"]};
    color: {t["text"]};
}}

QPushButton#SidebarButton {{
    background-color: transparent;
    color: {t["secondary"]};
    border: 0;
    border-left: 3px solid transparent;
    border-radius: 6px;
    padding: 11px 14px;
    text-align: left;
    font-weight: 500;
    icon-size: 22px;
}}

QPushButton#SidebarButton:hover {{
    background-color: {t["soft"]};
    color: {t["text"]};
}}

QPushButton#SidebarButton[active="true"] {{
    background-color: {t["raised"]};
    color: {t["text"]};
    border-left: 3px solid {t["orange"]};
}}

QLineEdit {{
    background-color: {t["field"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    border-radius: 6px;
    padding: 8px 10px;
}}

QComboBox {{
    background-color: {t["field"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    border-radius: 6px;
    padding: 8px 10px;
}}

QComboBox:hover {{
    border: 1px solid rgba(255, 138, 31, 0.24);
}}

QLineEdit:hover {{
    border: 1px solid rgba(255, 138, 31, 0.22);
}}

QComboBox::drop-down {{
    border: 0;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {t["raised"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    selection-background-color: rgba(255, 138, 31, 0.18);
}}

QSpinBox {{
    background-color: {t["field"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    border-radius: 6px;
    padding: 8px 10px;
}}

QSpinBox:hover {{
    border: 1px solid rgba(255, 138, 31, 0.24);
}}

QTabWidget::pane {{
    border: 0;
}}

QTabBar::tab {{
    background-color: {t["field"]};
    color: {t["secondary"]};
    border: 1px solid {t["border"]};
    border-radius: 6px;
    padding: 8px 14px;
    margin-right: 6px;
    font-weight: 700;
}}

QTabBar::tab:selected {{
    background-color: {t["raised"]};
    color: {t["text"]};
    border: 1px solid rgba(255, 138, 31, 0.34);
}}

QTextEdit {{
    background-color: {t["field"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
    padding: 10px;
}}

QTextEdit#DetailText {{
    background-color: {t["field"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
    padding: 12px;
}}

QTableWidget {{
    background-color: {t["field"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: rgba(255, 138, 31, 0.09);
    alternate-background-color: {t["soft"]};
}}

QTableWidget::item {{
    border-bottom: 1px solid {t["soft"]};
    padding: 4px 10px;
}}

QTableWidget::item:selected {{
    background-color: rgba(255, 138, 31, 0.13);
    color: {t["text"]};
}}

QFrame#FilterBar {{
    background-color: {t["raised"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
}}

QHeaderView::section {{
    background-color: {t["raised"]};
    color: {t["secondary"]};
    border: 0;
    border-bottom: 1px solid {t["border"]};
    padding: 8px 10px;
    font-weight: 600;
}}

QPushButton#TableActionButton {{
    background-color: rgba(255, 138, 31, 0.10);
    color: {t["orange"]};
    border: 1px solid rgba(255, 138, 31, 0.38);
    border-radius: 6px;
    padding: 5px 10px;
    font-weight: 700;
}}

QPushButton#TableActionButton:hover {{
    background-color: {t["orange"]};
    color: {t["primary_text"]};
    border: 1px solid {t["orange_hover"]};
}}

QFrame#MetricCard {{
    background-color: {t["soft"]};
    border: 1px solid {t["border"]};
    border-radius: 7px;
}}

QFrame#AccordionRow {{
    background-color: {t["field"]};
    border: 1px solid {t["border"]};
    border-left: 3px solid {t["border"]};
    border-radius: 8px;
}}

QFrame#AccordionRow[severity="high"] {{
    border-left: 3px solid rgba(255, 77, 77, 0.55);
}}

QFrame#AccordionRow[severity="medium"] {{
    border-left: 3px solid rgba(255, 138, 31, 0.55);
}}

QFrame#AccordionRow[severity="low"] {{
    border-left: 3px solid rgba(130, 182, 255, 0.45);
}}

QFrame#AccordionRow[expanded="true"] {{
    background-color: {t["panel"]};
    border: 1px solid rgba(255, 138, 31, 0.32);
}}

QFrame#AccordionRow[expanded="true"][severity="high"] {{
    border: 1px solid rgba(255, 77, 77, 0.42);
}}

QFrame#AccordionRow[expanded="true"][severity="low"] {{
    border: 1px solid rgba(130, 182, 255, 0.38);
}}

QFrame#AccordionDetail {{
    background-color: {t["soft"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
}}

QWidget#AccordionContent {{
    background-color: transparent;
}}

QScrollBar:vertical {{
    background: {t["field"]};
    width: 12px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {t["badge"]};
    border-radius: 6px;
    min-height: 28px;
}}

QScrollBar::handle:vertical:hover {{
    background: {t["hover"]};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}

QFrame#ThemeToggle {{
    background-color: {t["raised"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
}}

QFrame#SidebarUtility {{
    background-color: {t["raised"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
}}

QPushButton#SidebarUtilityButton {{
    background-color: transparent;
    color: {t["secondary"]};
    border: 1px solid {t["border"]};
    border-radius: 6px;
    padding: 7px 8px;
    font-size: 11px;
    font-weight: 700;
}}

QPushButton#SidebarUtilityButton:hover {{
    background-color: {t["hover"]};
    color: {t["text"]};
    border-color: {t["orange"]};
}}

QCheckBox#SidebarUtilityCheck {{
    color: {t["secondary"]};
    font-size: 11px;
    font-weight: 600;
    spacing: 6px;
}}

QCheckBox#SidebarUtilityCheck:hover {{
    color: {t["text"]};
}}

QPushButton#ThemeButton {{
    background-color: transparent;
    color: {t["secondary"]};
    border: 0;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 700;
    min-width: 0;
}}

QPushButton#ThemeButton[active="true"] {{
    background-color: rgba(255, 138, 31, 0.14);
    color: {t["orange"]};
    border: 1px solid rgba(255, 138, 31, 0.34);
}}

QPushButton#ThemeButton:hover {{
    background-color: {t["hover"]};
    color: {t["text"]};
}}

QPushButton#ThemeButton[active="true"]:hover {{
    background-color: rgba(255, 138, 31, 0.18);
    color: {t["orange"]};
}}

QStatusBar {{
    background-color: {t["raised"]};
    color: {t["muted"]};
    font-size: 11px;
    border-top: 1px solid {t["border"]};
    padding: 0 12px;
}}

QStatusBar::item {{
    border: none;
}}

QFrame#Toast {{
    border-radius: 8px;
    border: 1px solid {t["border"]};
    background-color: {t["raised"]};
}}

QFrame#Toast[kind="success"] {{
    background-color: rgba(61, 220, 132, 0.14);
    border: 1px solid rgba(61, 220, 132, 0.30);
}}

QFrame#Toast[kind="warning"] {{
    background-color: rgba(255, 138, 31, 0.14);
    border: 1px solid rgba(255, 138, 31, 0.30);
}}

QFrame#Toast[kind="error"] {{
    background-color: rgba(255, 77, 77, 0.14);
    border: 1px solid rgba(255, 77, 77, 0.30);
}}

QLabel#ToastIcon {{
    font-size: 12px;
    font-weight: 800;
    color: {t["blue"]};
}}

QLabel#ToastIcon[kind="success"] {{ color: {t["success"]}; }}
QLabel#ToastIcon[kind="warning"] {{ color: {t["orange"]}; }}
QLabel#ToastIcon[kind="error"] {{ color: {t["danger"]}; }}

QLabel#ToastText {{
    color: {t["text"]};
    font-size: 13px;
}}

QPushButton#ToastAction {{
    background-color: transparent;
    color: {t["orange"]};
    border: 1px solid rgba(255, 138, 31, 0.35);
    border-radius: 5px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
    min-width: 0;
}}

QPushButton#ToastAction:hover {{
    background-color: rgba(255, 138, 31, 0.14);
}}

QFrame#MetricCard {{
    background-color: {t["raised"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
}}

QFrame#MetricCard[clickable="true"]:hover {{
    border: 1px solid rgba(255, 138, 31, 0.30);
    background-color: {t["hover"]};
}}
"""
