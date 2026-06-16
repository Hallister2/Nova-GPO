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
        "table_alt": "rgba(255, 255, 255, 0.035)",
        "hover": "#292A2D",
        "orange": "#FF8A1F",
        "orange_hover": "#FFA13D",
        "orange_soft": "rgba(255, 138, 31, 0.13)",
        "orange_border": "rgba(255, 138, 31, 0.30)",
        "orange_focus": "rgba(255, 138, 31, 0.42)",
        "success": "#3DDC84",
        "success_soft": "rgba(61, 220, 132, 0.13)",
        "success_border": "rgba(61, 220, 132, 0.25)",
        "danger": "#FF4D4D",
        "danger_soft": "rgba(255, 77, 77, 0.13)",
        "danger_border": "rgba(255, 77, 77, 0.30)",
        "blue": "#82B6FF",
        "blue_soft": "rgba(130, 182, 255, 0.13)",
        "blue_border": "rgba(130, 182, 255, 0.25)",
        "badge": "#252628",
        "disabled": "#1A1B1D",
        "primary_text": "#16100A",
        "scroll_handle": "#252628",
    },
    "clean_light": {
        "app": "#F4F5F7",
        "sidebar": "#E6E8EC",
        "panel": "#FFFFFF",
        "raised": "#EEF1F5",
        "field": "#FFFFFF",
        "text": "#111827",
        "secondary": "#374151",
        "muted": "#667085",
        "border": "rgba(17, 24, 39, 0.18)",
        "soft": "rgba(17, 24, 39, 0.06)",
        "table_alt": "#F7F8FA",
        "hover": "#E1E6EE",
        "orange": "#F97316",
        "orange_hover": "#EA580C",
        "orange_soft": "rgba(249, 115, 22, 0.12)",
        "orange_border": "rgba(249, 115, 22, 0.36)",
        "orange_focus": "rgba(249, 115, 22, 0.52)",
        "success": "#047857",
        "success_soft": "rgba(4, 120, 87, 0.11)",
        "success_border": "rgba(4, 120, 87, 0.28)",
        "danger": "#B42318",
        "danger_soft": "rgba(180, 35, 24, 0.11)",
        "danger_border": "rgba(180, 35, 24, 0.30)",
        "blue": "#1D4ED8",
        "blue_soft": "rgba(29, 78, 216, 0.10)",
        "blue_border": "rgba(29, 78, 216, 0.26)",
        "badge": "#EEF2F6",
        "disabled": "#E5E7EB",
        "primary_text": "#1F1307",
        "scroll_handle": "#C4CAD3",
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
    border: 1px solid {t["orange_border"]};
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
    background-color: {t["success_soft"]};
    color: {t["success"]};
    border: 1px solid {t["success_border"]};
}}

QLabel#StatusBadge[state="diff"] {{
    background-color: {t["danger_soft"]};
    color: {t["danger"]};
    border: 1px solid {t["danger_border"]};
}}

QLabel#StatusBadge[state="added"] {{
    background-color: {t["success_soft"]};
    color: {t["success"]};
    border: 1px solid {t["success_border"]};
}}

QLabel#StatusBadge[state="removed"] {{
    background-color: {t["danger_soft"]};
    color: {t["danger"]};
    border: 1px solid {t["danger_border"]};
}}

QLabel#StatusBadge[state="changed"] {{
    background-color: {t["orange_soft"]};
    color: {t["orange"]};
    border: 1px solid {t["orange_border"]};
}}

QLabel#StatusBadge[state="unchanged"] {{
    background-color: {t["badge"]};
    color: {t["secondary"]};
    border: 1px solid {t["border"]};
}}

QLabel#StatusBadge[state="valid"] {{
    background-color: {t["success_soft"]};
    color: {t["success"]};
    border: 1px solid {t["success_border"]};
}}

QLabel#StatusBadge[state="review"] {{
    background-color: {t["blue_soft"]};
    color: {t["blue"]};
    border: 1px solid {t["blue_border"]};
}}

QLabel#StatusBadge[state="enabled"] {{
    background-color: {t["success_soft"]};
    color: {t["success"]};
    border: 1px solid {t["success_border"]};
}}

QLabel#StatusBadge[state="disabled"] {{
    background-color: {t["orange_soft"]};
    color: {t["orange"]};
    border: 1px solid {t["orange_border"]};
}}

QLabel#StatusBadge[state="unknown"] {{
    background-color: {t["soft"]};
    color: {t["muted"]};
    border: 1px solid {t["border"]};
}}

QLabel#StatusBadge[state="severity-high"] {{
    background-color: {t["danger_soft"]};
    color: {t["danger"]};
    border: 1px solid {t["danger_border"]};
}}

QLabel#StatusBadge[state="severity-medium"] {{
    background-color: {t["orange_soft"]};
    color: {t["orange"]};
    border: 1px solid {t["orange_border"]};
}}

QLabel#StatusBadge[state="severity-low"] {{
    background-color: {t["blue_soft"]};
    color: {t["blue"]};
    border: 1px solid {t["blue_border"]};
}}

QLabel#StatusBadge[state="empty"] {{
    background-color: {t["soft"]};
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
    border: 1px solid {t["orange_border"]};
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
    border: 1px solid {t["orange_focus"]};
}}

QComboBox:focus {{
    border: 1px solid {t["orange_focus"]};
}}

QLineEdit:hover {{
    border: 1px solid {t["orange_focus"]};
}}

QLineEdit:focus {{
    border: 1px solid {t["orange_focus"]};
}}

QComboBox::drop-down {{
    border: 0;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {t["raised"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    selection-background-color: {t["orange_soft"]};
}}

QSpinBox {{
    background-color: {t["field"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    border-radius: 6px;
    padding: 8px 10px;
}}

QSpinBox:hover {{
    border: 1px solid {t["orange_focus"]};
}}

QSpinBox:focus {{
    border: 1px solid {t["orange_focus"]};
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
    border: 1px solid {t["orange_border"]};
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

QLabel#DetailText {{
    background-color: {t["field"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
    padding: 10px;
}}

QTextEdit:focus {{
    border: 1px solid {t["orange_focus"]};
}}

QTableWidget {{
    background-color: {t["field"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: {t["orange_soft"]};
    alternate-background-color: {t["table_alt"]};
}}

QTableWidget::item {{
    border-bottom: 1px solid {t["soft"]};
    padding: 4px 10px;
}}

QTableWidget::item:selected {{
    background-color: {t["orange_soft"]};
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
    background-color: {t["orange_soft"]};
    color: {t["orange"]};
    border: 1px solid {t["orange_border"]};
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
    border-left: 3px solid {t["danger"]};
}}

QFrame#AccordionRow[severity="medium"] {{
    border-left: 3px solid {t["orange"]};
}}

QFrame#AccordionRow[severity="low"] {{
    border-left: 3px solid {t["blue"]};
}}

QFrame#AccordionRow[expanded="true"] {{
    background-color: {t["panel"]};
    border: 1px solid {t["orange_border"]};
}}

QFrame#AccordionRow[expanded="true"][severity="high"] {{
    border: 1px solid {t["danger_border"]};
}}

QFrame#AccordionRow[expanded="true"][severity="low"] {{
    border: 1px solid {t["blue_border"]};
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
    background: {t["scroll_handle"]};
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
    background-color: {t["orange_soft"]};
    color: {t["orange"]};
    border: 1px solid {t["orange_border"]};
}}

QPushButton#ThemeButton:hover {{
    background-color: {t["hover"]};
    color: {t["text"]};
}}

QPushButton#ThemeButton[active="true"]:hover {{
    background-color: {t["orange_soft"]};
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
    background-color: {t["success_soft"]};
    border: 1px solid {t["success_border"]};
}}

QFrame#Toast[kind="warning"] {{
    background-color: {t["orange_soft"]};
    border: 1px solid {t["orange_border"]};
}}

QFrame#Toast[kind="error"] {{
    background-color: {t["danger_soft"]};
    border: 1px solid {t["danger_border"]};
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
    border: 1px solid {t["orange_border"]};
    border-radius: 5px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
    min-width: 0;
}}

QPushButton#ToastAction:hover {{
    background-color: {t["orange_soft"]};
}}

QFrame#MetricCard {{
    background-color: {t["raised"]};
    border: 1px solid {t["border"]};
    border-radius: 8px;
}}

QFrame#MetricCard[clickable="true"]:hover {{
    border: 1px solid {t["orange_border"]};
    background-color: {t["hover"]};
}}
"""
