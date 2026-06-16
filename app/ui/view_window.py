from __future__ import annotations

import csv
import io
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QDialog,
)

from app.core.settings import APP_ROOT
from app.gpo.gpo_model import GpoBackup
from app.gpo.gpreport_parser import GpoReportPolicy, load_gpreport
from app.gpo.ilt_parser import GPP_COMMON_HEADER, GPP_PROPERTIES_HEADER, ILT_HEADER
from app.ui.branding import APP_LOGO_PATH, app_icon
from app.ui.widgets import badge, badge_item, configure_enterprise_table, readonly_item


ASSETS_DIR = APP_ROOT / "assets"


class ViewWindow(QDialog):
    compare_with_requested = Signal(str)

    def __init__(self, backup: GpoBackup, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint,
        )

        self.backup = backup
        self.report = load_gpreport(backup.path)
        self.nav_buttons: dict[str, QPushButton] = {}

        title = self.report.name if self.report and self.report.name else backup.name

        self.setWindowTitle(f"View GPO - {title}")
        self.setWindowIcon(app_icon())
        self.resize(1120, 720)
        self.setMinimumSize(920, 620)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_nav(), 0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_summary_page())
        self.stack.addWidget(self._build_metadata_page())
        self.stack.addWidget(self._build_policy_page("Computer Configuration"))
        self.stack.addWidget(self._build_policy_page("User Configuration"))
        self.stack.addWidget(self._build_raw_page())
        self.stack.addWidget(self._build_artifacts_page())

        root.addWidget(self.stack, 1)

        self._set_page("Summary")

    def _build_nav(self) -> QFrame:
        nav = QFrame()
        nav.setObjectName("Sidebar")
        nav.setFixedWidth(214)

        layout = QVBoxLayout(nav)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(10)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)

        logo_icon = QLabel()
        logo_icon.setObjectName("BrandIcon")
        logo_icon.setFixedSize(38, 38)
        _logo_px = QPixmap()
        if APP_LOGO_PATH.exists():
            _logo_px.load(str(APP_LOGO_PATH))
        if not _logo_px.isNull():
            logo_icon.setPixmap(
                _logo_px.scaled(
                    38, 38,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        logo_text = QVBoxLayout()
        logo_text.setSpacing(1)

        logo = QLabel("NOVA")
        logo.setObjectName("Logo")

        sub = QLabel("GPO VIEW")
        sub.setObjectName("LogoSub")

        logo_text.addWidget(logo)
        logo_text.addWidget(sub)

        logo_row.addWidget(logo_icon)
        logo_row.addLayout(logo_text, 1)
        layout.addLayout(logo_row)
        layout.addSpacing(18)

        for page_name in ["Summary", "Metadata", "Computer Configuration", "User Configuration", "Raw Settings", "Files & Artifacts"]:
            button = QPushButton(page_name)
            button.setObjectName("SidebarButton")
            button.setProperty("active", "false")
            button.setIcon(self._nav_icon(page_name, active=False))
            button.setIconSize(QSize(22, 22))
            button.clicked.connect(lambda checked=False, name=page_name: self._set_page(name))

            self.nav_buttons[page_name] = button
            layout.addWidget(button)

        layout.addStretch()

        footer = QLabel("View Mode")
        footer.setObjectName("Muted")
        layout.addWidget(footer)

        return nav

    def _build_summary_page(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(18)

        title_text = self.report.name if self.report and self.report.name else self.backup.name

        header_row = QHBoxLayout()
        title = QLabel(title_text)
        title.setObjectName("Title")

        compare_btn = QPushButton("Compare with…")
        compare_btn.setObjectName("GhostButton")
        compare_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        compare_btn.clicked.connect(
            lambda: (self.compare_with_requested.emit(self.backup.path), self.accept())
        )

        header_row.addWidget(title, 1)
        header_row.addWidget(compare_btn)
        layout.addLayout(header_row)

        meta_parts: list[str] = []
        if self.report:
            if self.report.domain:
                meta_parts.append(f"Domain: {self.report.domain}")
            if self.report.created_time:
                meta_parts.append(f"Created {_fmt_ts(self.report.created_time)}")
            if self.report.modified_time:
                meta_parts.append(f"Modified {_fmt_ts(self.report.modified_time)}")
        else:
            meta_parts.append("gpreport.xml not found — showing raw parsed settings")

        subtitle = QLabel("  ·  ".join(meta_parts) if meta_parts else "Group Policy settings report")
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addWidget(self._build_summary_cards())
        layout.addStretch()

        return page

    def _build_summary_cards(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("RaisedPanel")

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        if self.report:
            computer_state = _enabled_text(self.report.computer_enabled)
            user_state = _enabled_text(self.report.user_enabled)
            computer_count = len(self._policies_for_scope("Computer Configuration"))
            user_count = len(self._policies_for_scope("User Configuration"))
            coverage = _parser_coverage(self.backup)

            layout.addWidget(self._metric_card("Computer Configuration", computer_state,
                on_click=lambda: self._set_page("Computer Configuration")))
            layout.addWidget(self._metric_card("Computer Items", str(computer_count),
                on_click=lambda: self._set_page("Computer Configuration")))
            layout.addWidget(self._metric_card("User Configuration", user_state,
                on_click=lambda: self._set_page("User Configuration")))
            layout.addWidget(self._metric_card("User Items", str(user_count),
                on_click=lambda: self._set_page("User Configuration")))
            layout.addWidget(self._metric_card("Parsed Artifacts", str(coverage["parsed"]),
                on_click=lambda: self._set_page("Files & Artifacts")))
            layout.addWidget(self._metric_card("Raw Artifacts", str(coverage["raw"]),
                on_click=lambda: self._set_page("Files & Artifacts")))
        else:
            layout.addWidget(self._metric_card("Report", "Missing"))
            layout.addWidget(self._metric_card("Raw Settings", str(len(self.backup.settings))))

        return panel

    def _metric_card(self, label_text: str, value_text: str, on_click=None) -> QFrame:
        card = QFrame()
        card.setObjectName("MetricCard")

        if on_click:
            card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            card.mousePressEvent = lambda _event: on_click()

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        label = QLabel(label_text)
        label.setObjectName("Muted")

        value = QLabel(value_text)
        value.setObjectName("PanelTitle")

        layout.addWidget(label)
        layout.addWidget(value)

        return card


    def _build_policy_page(self, scope: str) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(18)

        title = QLabel(scope)
        title.setObjectName("Title")
        layout.addWidget(title)

        all_policies = self._policies_for_scope(scope)

        subtitle = QLabel(f"{len(all_policies)} policy items found in this section.")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        filter_panel = QFrame()
        filter_panel.setObjectName("FilterBar")

        filter_row = QHBoxLayout(filter_panel)
        filter_row.setContentsMargins(14, 12, 14, 12)
        filter_row.setSpacing(10)

        search_box = QLineEdit()
        search_box.setPlaceholderText("Search policies...")

        category_filter = QComboBox()
        category_filter.setMinimumWidth(180)
        category_filter.addItem("All Categories")

        clear_button = QPushButton("Clear Filters")
        clear_button.setObjectName("GhostButton")

        result_count = QLabel()
        result_count.setObjectName("Muted")

        export_button = QPushButton("Export CSV")
        export_button.setObjectName("GhostButton")

        categories = sorted({
            policy.category
            for policy in all_policies
            if policy.category and policy.category != "Not reported"
        })

        for category in categories:
            category_filter.addItem(category)

        filter_row.addWidget(search_box, 1)
        filter_row.addWidget(category_filter)
        filter_row.addWidget(clear_button)
        filter_row.addWidget(result_count)
        filter_row.addWidget(export_button)

        layout.addWidget(filter_panel)

        content = QSplitter(Qt.Orientation.Horizontal)
        content.setChildrenCollapsible(False)

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["State", "Type", "Policy Item", "ILT"])
        configure_enterprise_table(table, row_height=42)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        detail_panel = QFrame()
        detail_panel.setObjectName("Panel")
        detail_panel.setMinimumWidth(300)

        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(16, 16, 16, 16)
        detail_layout.setSpacing(10)

        detail_title = QLabel("Policy Details")
        detail_title.setObjectName("PanelTitle")

        detail_header = QHBoxLayout()
        detail_name = QLabel("Select a policy")
        detail_name.setObjectName("StatusLabel")
        detail_name.setWordWrap(True)

        copy_name_btn = QPushButton("Copy")
        copy_name_btn.setObjectName("TableActionButton")
        copy_name_btn.setFixedSize(52, 26)
        copy_name_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        copy_name_btn.clicked.connect(lambda: QApplication.clipboard().setText(detail_name.text()))

        detail_state_slot = QHBoxLayout()
        detail_state_slot.addStretch()

        detail_header.addWidget(detail_name, 1)
        detail_header.addLayout(detail_state_slot)
        detail_header.addWidget(copy_name_btn)

        # Empty-state hint — shown when nothing is selected
        empty_hint = QLabel("Select a policy from the list to view its details.")
        empty_hint.setObjectName("Muted")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setWordWrap(True)

        # Fields container — hidden when nothing is selected
        fields_container = QWidget()
        fields_layout = QVBoxLayout(fields_container)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(8)

        detail_text = QTextEdit()
        detail_text.setReadOnly(True)
        detail_text.setObjectName("DetailText")
        detail_text.setFrameShape(QFrame.Shape.NoFrame)
        detail_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        copy_details_btn = QPushButton("Copy Details")
        copy_details_btn.setObjectName("GhostButton")
        copy_details_btn.clicked.connect(lambda: QApplication.clipboard().setText(detail_text.toPlainText()))

        fields_layout.addWidget(detail_text, 1)
        fields_layout.addWidget(copy_details_btn)
        fields_container.setVisible(False)

        detail_layout.addWidget(detail_title)
        detail_layout.addLayout(detail_header)
        detail_layout.addWidget(empty_hint, 1)
        detail_layout.addWidget(fields_container, 1)

        def populate_table(policies: list[GpoReportPolicy]) -> None:
            table.setSortingEnabled(False)
            table.setRowCount(0)

            for policy in policies:
                row = table.rowCount()
                table.insertRow(row)

                state_item = badge_item(policy.state, policy)
                type_item = readonly_item(policy.policy_type)
                name_item = readonly_item(policy.name)
                name_item.setToolTip(policy.explain)
                has_ilt = ILT_HEADER in policy.settings

                table.setItem(row, 0, state_item)
                table.setItem(row, 1, type_item)
                table.setItem(row, 2, name_item)
                table.setItem(row, 3, readonly_item(""))
                table.setCellWidget(row, 0, badge(policy.state or "Unknown", _state_badge_state(policy.state)))
                if has_ilt:
                    table.setCellWidget(row, 3, badge("Targeted", "review", min_width=76))

            table.setSortingEnabled(True)

        def filtered_policies() -> list[GpoReportPolicy]:
            search_text = search_box.text().strip().lower()
            selected_category = category_filter.currentText()

            results = all_policies

            if selected_category != "All Categories":
                results = [
                    policy
                    for policy in results
                    if policy.category == selected_category
                ]

            if not search_text:
                return results

            return [
                policy
                for policy in results
                if search_text in policy.name.lower()
                or search_text in policy.policy_type.lower()
                or search_text in policy.state.lower()
                or search_text in policy.category.lower()
                or search_text in policy.source.lower()
                or search_text in policy.supported.lower()
                or search_text in policy.explain.lower()
                or any(search_text in setting.lower() for setting in policy.settings)
            ]

        def apply_search() -> None:
            policies = filtered_policies()
            populate_table(policies)
            subtitle.setText(
                f"{len(policies)} of {len(all_policies)} policy items shown in this section."
            )
            result_count.setText(f"{len(policies)} shown")

            if policies:
                table.selectRow(0)
            elif not all_policies and scope == "User Configuration":
                show_empty_detail("User Configuration is disabled or contains no parsed policy items.")
            elif not all_policies:
                show_empty_detail("No parsed policy items were found in this section.")
            else:
                show_empty_detail("No policies match the current search.")

        def clear_filters() -> None:
            search_box.clear()
            category_filter.setCurrentIndex(0)
            apply_search()

        def show_policy_details() -> None:
            selected_items = table.selectedItems()

            if not selected_items:
                show_empty_detail("Select a policy to view details.")
                return

            row = selected_items[0].row()
            item = table.item(row, 0)
            policy = item.data(Qt.ItemDataRole.UserRole) if item else None

            if not policy:
                show_empty_detail("No policy details available.")
                return

            detail_name.setText(policy.name or "Unknown policy")
            _replace_badge(detail_state_slot, badge(policy.state or "Unknown", _state_badge_state(policy.state)))
            detail_text.setHtml(_policy_detail_html(policy))
            empty_hint.setVisible(False)
            fields_container.setVisible(True)

        def show_empty_detail(message: str = "") -> None:
            detail_name.setText("")
            _replace_badge(detail_state_slot, QLabel())  # clear badge
            fields_container.setVisible(False)
            empty_hint.setVisible(True)

        def do_export() -> None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Policy List",
                f"nova-gpo-{scope.replace(' ', '-').lower()}.csv",
                "CSV Files (*.csv);;All Files (*)",
            )
            if not path:
                return
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["State", "Type", "Policy", "Category", "Scope",
                              "Supported On", "Source", "Settings"])
            for policy in filtered_policies():
                writer.writerow([
                    policy.state, policy.policy_type, policy.name,
                    policy.category, policy.scope, policy.supported,
                    policy.source, "; ".join(policy.settings),
                ])
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(buf.getvalue())

        table.itemSelectionChanged.connect(show_policy_details)
        search_box.textChanged.connect(apply_search)
        category_filter.currentTextChanged.connect(apply_search)
        clear_button.clicked.connect(clear_filters)
        export_button.clicked.connect(do_export)

        apply_search()

        content.addWidget(table)
        content.addWidget(detail_panel)
        content.setStretchFactor(0, 3)
        content.setStretchFactor(1, 2)
        content.setSizes([680, 360])

        layout.addWidget(content, 1)

        return page


    def _build_raw_page(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(18)

        title = QLabel("Raw Settings")
        title.setObjectName("Title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Raw parsed settings from XML, INF, INI, and Registry.pol sources."
        )
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        filter_panel = QFrame()
        filter_panel.setObjectName("FilterBar")
        filter_row = QHBoxLayout(filter_panel)
        filter_row.setContentsMargins(14, 12, 14, 12)
        filter_row.setSpacing(10)

        raw_search = QLineEdit()
        raw_search.setPlaceholderText("Filter by category, setting name, or value…")

        raw_result_count = QLabel()
        raw_result_count.setObjectName("Muted")

        raw_clear = QPushButton("Clear")
        raw_clear.setObjectName("GhostButton")

        filter_row.addWidget(raw_search, 1)
        filter_row.addWidget(raw_clear)
        filter_row.addWidget(raw_result_count)
        layout.addWidget(filter_panel)

        content = QSplitter(Qt.Orientation.Horizontal)
        content.setChildrenCollapsible(False)

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Category", "Setting", "Value", "Source"])
        configure_enterprise_table(table, row_height=40)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        detail_panel = QFrame()
        detail_panel.setObjectName("Panel")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(16, 16, 16, 16)
        detail_layout.setSpacing(10)

        raw_detail_title = QLabel("Raw Setting Details")
        raw_detail_title.setObjectName("PanelTitle")
        raw_empty_hint = QLabel("Select a raw setting to view its full value and source.")
        raw_empty_hint.setObjectName("Muted")
        raw_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        raw_empty_hint.setWordWrap(True)

        raw_fields = QWidget()
        raw_fields_layout = QVBoxLayout(raw_fields)
        raw_fields_layout.setContentsMargins(0, 0, 0, 0)
        raw_fields_layout.setSpacing(10)

        raw_category = QLabel()
        raw_name = QLabel()
        raw_source = QLabel()
        raw_value = QTextEdit()
        raw_value.setReadOnly(True)
        raw_value.setObjectName("DetailText")
        raw_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        copy_raw_btn = QPushButton("Copy Value")
        copy_raw_btn.setObjectName("GhostButton")
        copy_raw_btn.clicked.connect(lambda: QApplication.clipboard().setText(raw_value.toPlainText()))

        raw_fields_layout.addWidget(_detail_field("Category", raw_category))
        raw_fields_layout.addWidget(_detail_field("Setting", raw_name))
        raw_fields_layout.addWidget(_detail_field("Source", raw_source))
        raw_fields_layout.addWidget(_detail_section("Value", raw_value), 1)
        raw_fields_layout.addWidget(copy_raw_btn)
        raw_fields.setVisible(False)

        detail_layout.addWidget(raw_detail_title)
        detail_layout.addWidget(raw_empty_hint, 1)
        detail_layout.addWidget(raw_fields, 1)

        all_settings = self.backup.settings

        def populate_raw(query: str = "") -> None:
            table.setSortingEnabled(False)
            table.setRowCount(0)
            q = query.strip().lower()
            for setting in all_settings:
                if q and not any(q in (s or "").lower() for s in (
                    setting.category, setting.name, setting.value, setting.source_file
                )):
                    continue
                row = table.rowCount()
                table.insertRow(row)
                src_short = Path(setting.source_file).name if setting.source_file else ""
                src_item = readonly_item(src_short)
                if setting.source_file:
                    src_item.setToolTip(setting.source_file)
                category_item = readonly_item(setting.category)
                category_item.setData(Qt.ItemDataRole.UserRole, setting)
                table.setItem(row, 0, category_item)
                table.setItem(row, 1, readonly_item(setting.name))
                table.setItem(row, 2, readonly_item(setting.value))
                table.setItem(row, 3, src_item)
            table.setSortingEnabled(True)
            raw_result_count.setText(
                f"{table.rowCount()} of {len(all_settings)}" if q else f"{len(all_settings)} settings"
            )
            if table.rowCount():
                table.selectRow(0)
            else:
                show_raw_empty("No raw settings match the current filter.")

        def show_raw_empty(message: str) -> None:
            raw_empty_hint.setText(message)
            raw_empty_hint.setVisible(True)
            raw_fields.setVisible(False)

        def show_raw_detail() -> None:
            selected = table.selectedItems()
            if not selected:
                show_raw_empty("Select a raw setting to view its full value and source.")
                return
            row = selected[0].row()
            item = table.item(row, 0)
            setting = item.data(Qt.ItemDataRole.UserRole) if item else None
            if setting is None:
                show_raw_empty("No raw setting details are available.")
                return
            raw_category.setText(setting.category or "Not reported")
            raw_name.setText(setting.name or "Unknown setting")
            raw_source.setText(setting.source_file or "Unknown source")
            raw_value.setPlainText(setting.value or "")
            raw_empty_hint.setVisible(False)
            raw_fields.setVisible(True)

        table.itemSelectionChanged.connect(show_raw_detail)
        raw_search.textChanged.connect(populate_raw)
        raw_clear.clicked.connect(lambda: (raw_search.clear(), populate_raw()))

        populate_raw()
        content.addWidget(table)
        content.addWidget(detail_panel)
        content.setStretchFactor(0, 3)
        content.setStretchFactor(1, 2)
        content.setSizes([760, 360])
        layout.addWidget(content, 1)

        return page

    def _set_page(self, page_name: str) -> None:
        page_indexes = {
            "Summary": 0,
            "Metadata": 1,
            "Computer Configuration": 2,
            "User Configuration": 3,
            "Raw Settings": 4,
            "Files & Artifacts": 5,
        }

        self.stack.setCurrentIndex(page_indexes[page_name])

        for name, button in self.nav_buttons.items():
            active = name == page_name
            button.setProperty("active", "true" if active else "false")
            button.setIcon(self._nav_icon(name, active=active))
            button.style().unpolish(button)
            button.style().polish(button)

    def _nav_icon(self, page_name: str, active: bool) -> QIcon:
        icon_map = {
            "Summary": ("Nav - Meetings.png", "Nav - Meetings Active.png"),
            "Metadata": ("Nav - Templates.png", "Nav - Templates Active.png"),
            "Computer Configuration": ("Nav - Review.png", "Nav - Review Active.png"),
            "User Configuration": ("Nav - Capture.png", "Nav - Capture Active.png"),
            "Raw Settings": ("Nav - Settings.png", "Nav - Settings Active.png"),
            "Files & Artifacts": ("Nav - Logs.png", "Nav - Logs Active.png"),
        }
        default_icon, active_icon = icon_map[page_name]
        return QIcon(str(ASSETS_DIR / (active_icon if active else default_icon)))

    def _policies_for_scope(self, scope: str) -> list[GpoReportPolicy]:
        if not self.report:
            return []

        return [policy for policy in self.report.policies if policy.scope == scope]

    def _build_metadata_page(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(18)

        title = QLabel("Metadata")
        title.setObjectName("Title")
        layout.addWidget(title)

        subtitle = QLabel("Reported GPO identity and backup metadata.")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        rows = self._metadata_rows()

        # Paired card grid: two per row, last row full-width if odd count
        paired_rows = [rows[i:i + 2] for i in range(0, len(rows) - 1, 2)]
        last = rows[-1] if len(rows) % 2 == 1 else None

        for pair in paired_rows:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(12)
            for label_text, value_text in pair:
                row_layout.addWidget(self._metadata_card(label_text, value_text))
            layout.addLayout(row_layout)

        if last:
            # Full-width card for the final lone item (e.g. Backup Folder path)
            card = self._metadata_card(last[0], last[1])
            layout.addWidget(card)

        layout.addStretch()
        return page

    def _metadata_card(self, label_text: str, value_text: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(4)

        lbl = QLabel(label_text)
        lbl.setObjectName("StatusLabel")

        val = QLabel(value_text or "Not reported")
        val.setWordWrap(True)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        card_layout.addWidget(lbl)
        card_layout.addWidget(val)
        return card

    def _build_artifacts_page(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(18)

        title = QLabel("Files & Artifacts")
        title.setObjectName("Title")
        layout.addWidget(title)

        subtitle = QLabel("Backup source files, parser coverage, and raw artifacts.")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Artifact", "Path", "Parser Status", "Items", "Action"])
        configure_enterprise_table(table, row_height=40)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().resizeSection(4, 90)

        # Real item counts from parsed settings
        setting_counts: dict[str, int] = {}
        for s in self.backup.settings:
            if s.source_file:
                key = s.source_file.lower().replace("\\", "/")
                setting_counts[key] = setting_counts.get(key, 0) + 1

        table.setSortingEnabled(False)

        for artifact_type, relative_path, parser_status, _raw_count in _artifact_rows(self.backup.path):
            row = table.rowCount()
            table.insertRow(row)

            real_count = setting_counts.get(relative_path.lower(), 0)
            count_text = str(real_count) if real_count > 0 else "—"

            table.setItem(row, 0, readonly_item(artifact_type))
            table.setItem(row, 1, readonly_item(relative_path))
            table.setItem(row, 2, badge_item(parser_status))
            table.setItem(row, 3, readonly_item(count_text))
            table.setCellWidget(row, 2, badge(parser_status, _parser_badge_state(parser_status), min_width=96))

            reveal_btn = QPushButton("Reveal")
            reveal_btn.setObjectName("TableActionButton")
            reveal_btn.setFixedWidth(78)
            folder = str((Path(self.backup.path) / relative_path).parent)
            reveal_btn.clicked.connect(
                lambda checked=False, p=folder: QDesktopServices.openUrl(QUrl.fromLocalFile(p))
            )
            # Center the button in its cell
            cell_widget = QWidget()
            cell_layout = QHBoxLayout(cell_widget)
            cell_layout.setContentsMargins(6, 4, 6, 4)
            cell_layout.addWidget(reveal_btn)
            table.setCellWidget(row, 4, cell_widget)

        table.setSortingEnabled(True)
        layout.addWidget(table, 1)

        return page

    def _metadata_rows(self) -> list[tuple[str, str]]:
        if not self.report:
            return [
                ("Backup Folder", self.backup.path),
                ("GPO Name", self.backup.name),
                ("Report", "gpreport.xml was not found."),
            ]

        return [
            ("GPO Name", self.report.name),
            ("Domain", self.report.domain),
            ("Created", _fmt_ts(self.report.created_time)),
            ("Modified", _fmt_ts(self.report.modified_time)),
            ("Computer Configuration", _enabled_text(self.report.computer_enabled)),
            ("User Configuration", _enabled_text(self.report.user_enabled)),
            ("Backup Folder", self.backup.path),
        ]


def _enabled_text(value: str) -> str:
    return "Enabled" if value.lower() == "true" else "Disabled"


def _parser_coverage(backup: GpoBackup) -> dict[str, int]:
    rows = _artifact_rows(backup.path)
    parsed = sum(1 for _artifact_type, _path, status, _raw_count in rows if status == "Parsed")
    raw = sum(1 for _artifact_type, _path, status, _raw_count in rows if status == "Raw")
    missing = sum(1 for _artifact_type, _path, status, _raw_count in rows if status == "Missing")
    return {
        "parsed": parsed,
        "raw": raw,
        "missing": missing,
        "settings": len(backup.settings),
    }


def _fmt_ts(raw: str) -> str:
    """Convert an ISO 8601 timestamp to a readable date/time string."""
    if not raw:
        return raw
    clean = raw.split("+")[0].split("Z")[0].strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(clean, fmt)
            time_str = dt.strftime("%I:%M %p").lstrip("0") or "12:00 AM"
            return f"{dt.strftime('%b')} {dt.day}, {dt.year}  ·  {time_str}"
        except ValueError:
            continue
    return raw


def _split_ilt(settings: list[str]) -> tuple[list[str], list[str]]:
    """Split a settings list into (regular_settings, ilt_rules)."""
    try:
        idx = settings.index(ILT_HEADER)
        return settings[:idx], settings[idx + 1:]
    except ValueError:
        return settings, []


def _settings_text(settings: list[str]) -> str:
    if not settings:
        return "No configured value details were found for this policy."
    return "\n".join(f"• {s}" for s in settings)


def _split_policy_sections(settings: list[str]) -> dict[str, list[str]]:
    sections = {"properties": [], "common": [], "targeting": []}
    current = "properties"
    for setting in settings:
        if setting == GPP_PROPERTIES_HEADER:
            current = "properties"
            continue
        if setting == GPP_COMMON_HEADER:
            current = "common"
            continue
        if setting == ILT_HEADER:
            current = "targeting"
            continue
        sections[current].append(setting)
    return sections


def _policy_detail_html(policy: GpoReportPolicy) -> str:
    sections = _split_policy_sections(policy.settings)
    rows = [
        ("Type", policy.policy_type or "Unknown"),
        ("Category", policy.category or "Not reported"),
        ("Scope", policy.scope or "Not reported"),
        ("Supported On", policy.supported or "Not specified"),
        ("Source", policy.source or "gpreport.xml"),
    ]
    html = [
        "<div style='font-size:13px; line-height:1.45;'>",
        _detail_html_section("General", _metadata_table_html(rows)),
        _detail_html_section("Properties", _settings_table_html(sections["properties"])),
    ]
    if sections["common"]:
        html.append(_detail_html_section("Common Options", _settings_table_html(sections["common"])))
    if sections["targeting"]:
        html.append(_detail_html_section("Item-Level Targeting", _settings_table_html(sections["targeting"], targeting=True)))
    html.append(_detail_html_section("Explanation", f"<p>{escape(policy.explain or 'No explanation text was included in the report.')}</p>"))
    html.append("</div>")
    return "".join(html)


def _detail_html_section(title: str, body: str) -> str:
    return (
        "<section style='margin:0 0 14px 0;'>"
        f"<h3 style='font-size:13px; margin:0 0 7px 0; text-transform:uppercase; letter-spacing:0.4px;'>{escape(title)}</h3>"
        f"{body}"
        "</section>"
    )


def _metadata_table_html(rows: list[tuple[str, str]]) -> str:
    body = "".join(
        "<tr>"
        f"<td style='font-weight:700; padding:5px 10px 5px 0; width:32%; vertical-align:top;'>{escape(label)}</td>"
        f"<td style='padding:5px 0; vertical-align:top;'>{escape(value)}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"<table width='100%' cellspacing='0' cellpadding='0'>{body}</table>"


def _settings_table_html(settings: list[str], targeting: bool = False) -> str:
    if not settings:
        return "<p style='opacity:0.72;'>No configured value details were found for this policy.</p>"
    rows: list[str] = []
    for setting in settings:
        clean = setting.strip()
        if not clean:
            continue
        if clean.startswith("•"):
            rows.append(
                "<tr>"
                f"<td colspan='2' style='font-weight:800; padding:8px 0 4px 0;'>{escape(clean.lstrip('•').strip())}</td>"
                "</tr>"
            )
            continue
        key, value = _split_setting_pair(clean)
        if key:
            rows.append(
                "<tr>"
                f"<td style='font-weight:700; padding:4px 10px 4px 0; width:34%; vertical-align:top;'>{escape(key)}</td>"
                f"<td style='padding:4px 0; vertical-align:top;'>{escape(value)}</td>"
                "</tr>"
            )
        else:
            padding = "3px 0 3px 14px" if targeting else "3px 0"
            rows.append(
                "<tr>"
                f"<td colspan='2' style='padding:{padding}; vertical-align:top;'>{escape(clean)}</td>"
                "</tr>"
            )
    return (
        "<table width='100%' cellspacing='0' cellpadding='0' style='border-collapse:collapse;'>"
        f"{''.join(rows)}"
        "</table>"
    )


def _split_setting_pair(setting: str) -> tuple[str, str]:
    if ":" not in setting:
        return "", setting
    key, value = setting.split(":", 1)
    return key.strip(), value.strip()


def _detail_field(label_text: str, value: QLabel) -> QFrame:
    frame = QFrame()
    frame.setObjectName("MetricCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 9, 12, 9)
    layout.setSpacing(3)

    label = QLabel(label_text)
    label.setObjectName("StatusLabel")

    value.setWordWrap(True)
    value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    layout.addWidget(label)
    layout.addWidget(value)
    return frame


def _detail_section(label_text: str, value: QLabel) -> QFrame:
    frame = QFrame()
    frame.setObjectName("Panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(6)

    label = QLabel(label_text)
    label.setObjectName("PanelTitle")
    label.setStyleSheet("font-size: 14px;")

    layout.addWidget(label)
    layout.addWidget(value)
    return frame


def _replace_badge(slot: QHBoxLayout, replacement: QLabel) -> None:
    while slot.count():
        item = slot.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()

    slot.addWidget(replacement)
    slot.addStretch()


def _state_badge_state(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "enabled":
        return "enabled"
    if normalized == "disabled":
        return "disabled"
    if normalized == "not configured":
        return "unknown"
    if normalized:
        return "review"
    return "unknown"


def _artifact_rows(backup_path: str) -> list[tuple[str, str, str, int]]:
    root = Path(backup_path)
    if not root.exists():
        return []

    rows: list[tuple[str, str, str, int]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue

        relative = path.relative_to(root).as_posix()
        artifact_type = _artifact_type(path)
        parser_status = _parser_status(path)
        rows.append((artifact_type, relative, parser_status, 1))

    return rows


def _artifact_type(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()

    if name == "gpreport.xml":
        return "GPO Report"
    if name == "backup.xml":
        return "Backup Metadata"
    if name == "bkupinfo.xml":
        return "Backup Manifest"
    if name == "registry.pol":
        return "Registry Policy"
    if suffix in {".ini", ".inf"}:
        return "Policy Text"
    if suffix == ".xml":
        return "Preferences XML"
    if suffix in {".ps1", ".bat", ".cmd", ".vbs", ".js"}:
        return "Script"

    return "File"


def _parser_status(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()

    if name in {"gpreport.xml", "registry.pol"} or suffix in {".xml", ".ini", ".inf"}:
        return "Parsed"

    if suffix in {".ps1", ".bat", ".cmd", ".vbs", ".js"}:
        return "Inventory"

    return "Raw"


def _parser_badge_state(status: str) -> str:
    if status == "Parsed":
        return "valid"
    if status == "Inventory":
        return "review"
    return "unknown"
