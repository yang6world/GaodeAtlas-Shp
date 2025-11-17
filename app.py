from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from PyQt5.QtCore import QPointF, Qt, QTimer, QUrl, QUrlQuery, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QIcon, QKeySequence, QPalette, QPen, QPolygonF, QPainter
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QShortcut,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineView

from exporters import ExportError, GeoJSONExporter, ShapefileExporter
from gaode_client import GaodeClient
from geometry_utils import normalize_to_view
from models import PlaceDetail


CAPTURE_HOOK_SCRIPT = r"""
(function () {
    if (window.__gaodeCaptureInstalled) {
        return;
    }
    window.__gaodeCaptureInstalled = true;
    window._gaodeResponses = [];
    const MAX_CACHE = 60;

    const pushEntry = (url, body) => {
        try {
            if (!url || !body) {
                return;
            }
            window._gaodeResponses.push({ url: url.toString(), body: body.toString(), ts: Date.now() });
            if (window._gaodeResponses.length > MAX_CACHE) {
                window._gaodeResponses.shift();
            }
        } catch (err) {}
    };

    const wrapFetch = () => {
        if (!window.fetch) {
            return;
        }
        const origFetch = window.fetch;
        window.fetch = function () {
            return origFetch.apply(this, arguments).then((resp) => {
                try {
                    const clone = resp.clone();
                    if (clone.url && clone.url.indexOf('detail/get/detail') !== -1) {
                        clone.text().then((text) => pushEntry(clone.url, text));
                    }
                } catch (err) {}
                return resp;
            });
        };
    };

    const wrapXHR = () => {
        const proto = XMLHttpRequest.prototype;
        const origOpen = proto.open;
        const origSend = proto.send;
        proto.open = function (method, url) {
            this.__gaodeUrl = url;
            return origOpen.apply(this, arguments);
        };
        proto.send = function () {
            if (this.__gaodeUrl && this.__gaodeUrl.indexOf('detail/get/detail') !== -1) {
                this.addEventListener('load', () => {
                    try {
                        pushEntry(this.responseURL || this.__gaodeUrl, this.responseText || '');
                    } catch (err) {}
                });
            }
            return origSend.apply(this, arguments);
        };
    };

    wrapFetch();
    wrapXHR();
})();
"""

CAPTURE_PULL_SCRIPT = r"""
(function(targetId){
    try {
        const list = window._gaodeResponses || [];
        for (let i = list.length - 1; i >= 0; i--) {
            const entry = list[i];
            if (!entry || !entry.url || !entry.body) {
                continue;
            }
            let urlObj;
            try {
                urlObj = new URL(entry.url, window.location.origin);
            } catch (err) {
                continue;
            }
            if (urlObj.pathname.indexOf('detail/get/detail') === -1) {
                continue;
            }
            if (urlObj.searchParams.get('id') === targetId) {
                return entry.body;
            }
        }
    } catch (err) {}
    return null;
})(__POI_PLACEHOLDER__);
"""


@dataclass
class BatchExportOptions:
    directory: Path
    base_name: str
    save_geojson: bool
    save_shapefile: bool

    def geojson_path(self) -> Path:
        return self.directory / f"{self.base_name}.geojson"

    def shapefile_path(self) -> Path:
        return self.directory / f"{self.base_name}.shp"


class ExportOptionsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, default_name: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量导出设置")
        self._options: BatchExportOptions | None = None
        default_dir = Path.cwd()
        default_name = default_name or datetime.now().strftime("capture_%Y%m%d_%H%M%S")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.dir_edit = QLineEdit(str(default_dir))
        self.dir_edit.setReadOnly(True)
        choose_btn = QPushButton("选择…")
        choose_btn.clicked.connect(self._choose_directory)
        dir_container = QWidget()
        dir_layout = QHBoxLayout(dir_container)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.addWidget(self.dir_edit)
        dir_layout.addWidget(choose_btn)
        form.addRow("输出目录", dir_container)

        self.name_edit = QLineEdit(default_name)
        form.addRow("文件前缀", self.name_edit)

        self.geojson_check = QCheckBox("导出 GeoJSON")
        self.geojson_check.setChecked(True)
        self.shp_check = QCheckBox("导出 Shapefile")
        self.shp_check.setChecked(True)
        form.addRow("格式选择", self.geojson_check)
        form.addRow("", self.shp_check)

        layout.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._handle_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择导出目录", self.dir_edit.text())
        if directory:
            self.dir_edit.setText(directory)

    def _handle_accept(self) -> None:
        directory_text = self.dir_edit.text().strip()
        base_name = self.name_edit.text().strip()
        if not directory_text:
            QMessageBox.warning(self, "提示", "请选择导出目录")
            return
        if not base_name:
            QMessageBox.warning(self, "提示", "请输入文件名前缀")
            return
        if not (self.geojson_check.isChecked() or self.shp_check.isChecked()):
            QMessageBox.warning(self, "提示", "至少选择一种导出格式")
            return
        self._options = BatchExportOptions(
            directory=Path(directory_text),
            base_name=base_name,
            save_geojson=self.geojson_check.isChecked(),
            save_shapefile=self.shp_check.isChecked(),
        )
        self.accept()

    def get_options(self) -> BatchExportOptions | None:
        return self._options


class DetailRequestInterceptor(QWebEngineUrlRequestInterceptor):
    poi_detected = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._enabled = False

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def interceptRequest(self, info) -> None:  # type: ignore[override]
        if not self._enabled:
            return
        url = info.requestUrl()
        if url.host() != "ditu.amap.com":
            return
        if "detail/get/detail" not in url.path():
            return
        query = QUrlQuery(url)
        poiid = query.queryItemValue("id")
        if poiid:
            self.poi_detected.emit(poiid)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("高德POI爬取与导出")
        self.resize(1280, 800)
        self.setMinimumSize(1080, 640)
        self._client = GaodeClient()
        self._current_place: Optional[PlaceDetail] = None
        self._geojson_exporter = GeoJSONExporter()
        self._shp_exporter = ShapefileExporter()
        self._capturing = False
        self._captured_places: List[PlaceDetail] = []
        self._capture_pending: Set[str] = set()
        self._pending_attempts: Dict[str, int] = {}
        self._capture_script_added = False
        self._is_fullscreen = False
        self._init_web_engine()
        self._setup_ui()
        self._setup_fullscreen_shortcut()

    def _init_web_engine(self) -> None:
        self._web_profile = QWebEngineProfile("GaodeProfile", self)
        self._web_profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
        self._web_profile.setPersistentCookiesPolicy(QWebEngineProfile.AllowPersistentCookies)
        self._interceptor = DetailRequestInterceptor()
        self._interceptor.poi_detected.connect(self._on_poi_from_web)
        self._web_profile.setUrlRequestInterceptor(self._interceptor)
        self._install_capture_script()
        self._web_page = QWebEnginePage(self._web_profile, self)
        self.web_view = QWebEngineView()
        self.web_view.setPage(self._web_page)
        self.web_view.load(QUrl("https://ditu.amap.com/"))
        self.web_view.setFocusPolicy(Qt.StrongFocus)
        self.web_view.setZoomFactor(0.8)  # 设置默认缩放为80%

    def _install_capture_script(self) -> None:
        if self._capture_script_added:
            return
        script = QWebEngineScript()
        script.setName("GaodeCaptureHook")
        script.setSourceCode(CAPTURE_HOOK_SCRIPT)
        script.setInjectionPoint(QWebEngineScript.DocumentReady)
        script.setRunsOnSubFrames(True)
        script.setWorldId(QWebEngineScript.MainWorld)
        self._web_profile.scripts().insert(script)
        self._capture_script_added = True

    def _setup_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)
        form_layout = QHBoxLayout()
        form_layout.setSpacing(8)

        self.poi_input = QLineEdit()
        self.poi_input.setPlaceholderText("输入POI编号，如 B0FFG4HF5W")
        self.poi_input.returnPressed.connect(self._fetch_place)

        self.fetch_button = QPushButton("获取数据")
        self.fetch_button.clicked.connect(self._fetch_place)
        self.fetch_button.setAutoDefault(False)

        self.start_capture_button = QPushButton("开始捕捉")
        self.start_capture_button.clicked.connect(self._start_capture)
        self.stop_capture_button = QPushButton("停止捕捉")
        self.stop_capture_button.clicked.connect(self._stop_capture)
        self.stop_capture_button.setEnabled(False)
        self.capture_status_label = QLabel("捕捉：未开启")
        self.capture_status_label.setStyleSheet("color:#555555;font-weight:bold;")

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(25, 200)
        self.zoom_slider.setValue(80)
        self.zoom_slider.setFixedWidth(100)
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider_change)

        self.zoom_label = QLabel("80%")
        self.zoom_label.setFixedWidth(40)
        self.zoom_label.setAlignment(Qt.AlignCenter)

        self.zoom_out_button = QPushButton("-")
        self.zoom_out_button.setToolTip("缩小")
        self.zoom_out_button.setFixedSize(28, 28)
        self.zoom_out_button.clicked.connect(self._zoom_out)

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setToolTip("放大")
        self.zoom_in_button.setFixedSize(28, 28)
        self.zoom_in_button.clicked.connect(self._zoom_in)

        form_layout.addWidget(QLabel("POI ID:"))
        form_layout.addWidget(self.poi_input)
        form_layout.addWidget(self.fetch_button)
        form_layout.addWidget(self.start_capture_button)
        form_layout.addWidget(self.stop_capture_button)
        form_layout.addStretch()
        form_layout.addWidget(self.capture_status_label)
        form_layout.addSpacing(20)
        form_layout.addWidget(QLabel("缩放:"))
        form_layout.addWidget(self.zoom_out_button)
        form_layout.addWidget(self.zoom_slider)
        form_layout.addWidget(self.zoom_in_button)
        form_layout.addWidget(self.zoom_label)
        main_layout.addLayout(form_layout)

        self.instructions_label = QLabel("提示：F11 可切换全屏；捕捉模式会记录所有点击的地物，停止后统一导出。")
        self.instructions_label.setWordWrap(True)
        self.instructions_label.setStyleSheet("color:#6b6b6b;")
        main_layout.addWidget(self.instructions_label)

        # Info group
        info_group = QGroupBox("POI基本信息")
        info_form = QFormLayout()

        self.name_field = QLineEdit()
        self.address_field = QLineEdit()
        self.telephone_field = QLineEdit()
        self.city_field = QLineEdit()
        self.tag_field = QLineEdit()

        for field in (self.name_field, self.address_field, self.telephone_field, self.city_field, self.tag_field):
            field.setReadOnly(True)

        info_form.addRow("名称", self.name_field)
        info_form.addRow("地址", self.address_field)
        info_form.addRow("电话", self.telephone_field)
        info_form.addRow("城市", self.city_field)
        info_form.addRow("标签", self.tag_field)
        info_group.setLayout(info_form)

        # Graphics view
        self.view = QGraphicsView()
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setMinimumSize(400, 320)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._set_empty_scene()

        graphics_group = QGroupBox("几何预览")
        graphics_layout = QVBoxLayout()
        graphics_layout.setContentsMargins(0, 0, 0, 0)
        graphics_layout.addWidget(self.view)
        graphics_group.setLayout(graphics_layout)

        self.raw_text = QPlainTextEdit()
        self.raw_text.setReadOnly(True)
        raw_group = QGroupBox("原始JSON")
        raw_layout = QVBoxLayout()
        raw_layout.setContentsMargins(0, 0, 0, 0)
        raw_layout.addWidget(self.raw_text)
        raw_group.setLayout(raw_layout)

        web_group = QGroupBox("高德网页")
        web_layout = QVBoxLayout()
        web_layout.setContentsMargins(0, 0, 0, 0)
        web_layout.addWidget(self.web_view)
        web_group.setLayout(web_layout)

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(info_group)
        left_splitter.addWidget(raw_group)
        left_splitter.setStretchFactor(0, 2)
        left_splitter.setStretchFactor(1, 3)
        left_splitter.setChildrenCollapsible(False)
        left_splitter.setMinimumWidth(360)

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(web_group)
        right_splitter.addWidget(graphics_group)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)
        right_splitter.setChildrenCollapsible(False)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_splitter)
        splitter.addWidget(right_splitter)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)

        self._left_splitter = left_splitter
        self._right_splitter = right_splitter
        self._main_splitter = splitter
        main_layout.addWidget(splitter)
        QTimer.singleShot(0, self._apply_splitter_defaults)

        button_layout = QHBoxLayout()
        self.export_geojson_button = QPushButton("导出 GeoJSON")
        self.export_geojson_button.clicked.connect(self._export_geojson)
        self.export_geojson_button.setEnabled(False)

        self.export_shp_button = QPushButton("导出 Shapefile")
        self.export_shp_button.clicked.connect(self._export_shapefile)
        self.export_shp_button.setEnabled(False)

        button_layout.addStretch()
        button_layout.addWidget(self.export_geojson_button)
        button_layout.addWidget(self.export_shp_button)
        main_layout.addLayout(button_layout)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._update_capture_status()

    def _setup_fullscreen_shortcut(self) -> None:
        self._fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self._fullscreen_shortcut.activated.connect(self._toggle_fullscreen)

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self._is_fullscreen = False
            self._apply_splitter_defaults()
        else:
            self.showFullScreen()
            self._is_fullscreen = True
            self._apply_fullscreen_splitter_sizes()

    def _apply_fullscreen_splitter_sizes(self) -> None:
        if not hasattr(self, "_main_splitter"):
            return
        total_width = self.width()
        total_height = self.height()
        self._main_splitter.setSizes([int(total_width * 0.3), int(total_width * 0.7)])
        self._left_splitter.setSizes([int(total_height * 0.4), int(total_height * 0.6)])
        self._right_splitter.setSizes([int(total_height * 0.6), int(total_height * 0.4)])

    def _apply_splitter_defaults(self) -> None:
        if not hasattr(self, "_main_splitter"):
            return
        total_width = max(self.width(), 800)
        self._main_splitter.setSizes([int(total_width * 0.36), int(total_width * 0.64)])
        self._left_splitter.setSizes([280, 420])
        self._right_splitter.setSizes([int(self.height() * 0.55), int(self.height() * 0.45)])

    def _set_empty_scene(self) -> None:
        scene = QGraphicsScene()
        scene.addText("暂无外形数据")
        self.view.setScene(scene)

    def _fetch_place(self) -> None:
        poiid = self.poi_input.text().strip()
        if not poiid:
            QMessageBox.warning(self, "提示", "请输入POI编号")
            return
        self.fetch_button.setEnabled(False)
        self.statusBar().showMessage("正在定位POI…", 3000)
        self._pending_attempts[poiid] = 40
        self._navigate_to_poi(poiid)
        QTimer.singleShot(800, lambda pid=poiid: self._request_place_from_web_cache(pid, mode="manual"))

    def _refresh_info(self) -> None:
        place = self._current_place
        if not place:
            for widget in (self.name_field, self.address_field, self.telephone_field, self.city_field, self.tag_field):
                widget.clear()
            return
        self.name_field.setText(place.name)
        self.address_field.setText(place.address)
        self.telephone_field.setText(place.telephone)
        self.city_field.setText(place.city_name)
        self.tag_field.setText(place.tag)

    def _refresh_geometry(self) -> None:
        place = self._current_place
        if not (place and place.mining_shape and place.mining_shape.coordinates):
            self._set_empty_scene()
            return
        coords = place.mining_shape.coordinates
        width = max(self.view.viewport().width(), 400)
        height = max(self.view.viewport().height(), 400)
        norm_coords = normalize_to_view(coords, width, height)
        if not norm_coords:
            self._set_empty_scene()
            return
        polygon = QPolygonF([QPointF(x, y) for x, y in norm_coords])
        scene = QGraphicsScene()
        pen = QPen(QColor("#0078d4"))
        pen.setWidth(2)
        brush = QBrush(QColor(0, 120, 212, 60))
        scene.addPolygon(polygon, pen, brush)
        self.view.setScene(scene)

    def _refresh_raw_json(self) -> None:
        if not self._current_place:
            self.raw_text.clear()
            return
        text = json.dumps(self._current_place.raw, ensure_ascii=False, indent=2)
        self.raw_text.setPlainText(text)

    def _update_export_buttons(self) -> None:
        ready = bool(self._current_place and self._current_place.has_geometry)
        self.export_geojson_button.setEnabled(ready)
        self.export_shp_button.setEnabled(ready)

    def _store_captured_place(self, place: PlaceDetail) -> None:
        for idx, existing in enumerate(self._captured_places):
            if existing.poiid == place.poiid:
                self._captured_places[idx] = place
                break
        else:
            self._captured_places.append(place)
        self._update_capture_status()

    def _start_capture(self) -> None:
        if self._capturing:
            return
        self._capturing = True
        self._captured_places.clear()
        self._capture_pending.clear()
        self._pending_attempts.clear()
        self._interceptor.set_enabled(True)
        self.start_capture_button.setEnabled(False)
        self.stop_capture_button.setEnabled(True)
        self._update_capture_status()
        self.statusBar().showMessage("捕捉已开启，请在右侧地图点击地物", 5000)

    def _stop_capture(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        self._interceptor.set_enabled(False)
        self._pending_attempts.clear()
        self.start_capture_button.setEnabled(True)
        self.stop_capture_button.setEnabled(False)
        self._update_capture_status()
        if not self._captured_places:
            QMessageBox.information(self, "提示", "本次未捕捉到任何POI")
            return
        self._prompt_batch_export()

    def _update_capture_status(self) -> None:
        state = "进行中" if self._capturing else "已停止"
        self.capture_status_label.setText(f"捕捉：{state} ({len(self._captured_places)})")

    def _on_poi_from_web(self, poiid: str) -> None:
        if not self._capturing:
            return
        if poiid in self._capture_pending or any(p.poiid == poiid for p in self._captured_places):
            return
        self._capture_pending.add(poiid)
        self._pending_attempts[poiid] = 5
        self.statusBar().showMessage(f"捕捉请求：{poiid}", 2000)
        self._request_place_from_web_cache(poiid, mode="capture")

    def _navigate_to_poi(self, poiid: str) -> None:
        url = QUrl(f"https://ditu.amap.com/place/{poiid}")
        self.web_view.load(url)

    def _request_place_from_web_cache(self, poiid: str, mode: str) -> None:
        script = CAPTURE_PULL_SCRIPT.replace("__POI_PLACEHOLDER__", json.dumps(poiid))
        self.web_view.page().runJavaScript(
            script,
            lambda result, pid=poiid, m=mode: self._handle_web_payload_result(pid, m, result),
        )

    def _handle_web_payload_result(self, poiid: str, mode: str, result: Optional[str]) -> None:
        if result:
            try:
                payload = json.loads(result)
                place = self._client.build_place_from_payload(payload, poiid)
            except Exception as exc:
                self.statusBar().showMessage(f"解析网页响应失败({poiid})：{exc}", 5000)
            else:
                self._pending_attempts.pop(poiid, None)
                if mode == "capture":
                    self._capture_pending.discard(poiid)
                self._handle_place_ready(place, mode, poiid)
                return
        attempts = self._pending_attempts.get(poiid, 0) - 1
        if attempts > 0:
            self._pending_attempts[poiid] = attempts
            QTimer.singleShot(200, lambda pid=poiid, m=mode: self._request_place_from_web_cache(pid, m))
            return
        self._pending_attempts.pop(poiid, None)
        if mode == "capture":
            self._capture_pending.discard(poiid)
        self._handle_payload_failure(poiid, mode, "未从网页响应中获取到数据")

    def _handle_place_ready(self, place: PlaceDetail, mode: str, poiid: str) -> None:
        if mode == "manual":
            self.fetch_button.setEnabled(True)
            self.statusBar().showMessage("数据加载完成", 3000)
        else:
            self._store_captured_place(place)
            self.statusBar().showMessage(f"捕捉成功：{place.name or place.poiid}", 4000)
        self._current_place = place
        self._refresh_info()
        self._refresh_geometry()
        self._refresh_raw_json()
        self._update_export_buttons()

    def _handle_payload_failure(self, poiid: str, mode: str, reason: str) -> None:
        if mode == "manual":
            self.fetch_button.setEnabled(True)
            self.statusBar().clearMessage()
            QMessageBox.warning(self, "获取失败", f"POI {poiid} 数据未捕捉到：{reason}")
        else:
            self.statusBar().showMessage(f"捕捉失败({poiid})：{reason}", 5000)

    def _prompt_batch_export(self) -> None:
        dialog = ExportOptionsDialog(self, default_name=f"gaode_{len(self._captured_places)}")
        if dialog.exec_() != QDialog.Accepted:
            self.statusBar().showMessage("批量导出已取消", 4000)
            return
        options = dialog.get_options()
        if not options:
            return
        self._export_capture_results(options)

    def _export_capture_results(self, options: BatchExportOptions) -> None:
        reports: List[str] = []
        skipped_ids: Set[str] = set()
        try:
            if options.save_geojson:
                path, skipped = self._geojson_exporter.export_batch(self._captured_places, str(options.geojson_path()))
                reports.append(f"GeoJSON -> {path}")
                skipped_ids.update(skipped)
            if options.save_shapefile:
                path, skipped = self._shp_exporter.export_batch(self._captured_places, str(options.shapefile_path()))
                reports.append(f"Shapefile -> {path}")
                skipped_ids.update(skipped)
        except ExportError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return

        message = "\n".join(reports)
        if skipped_ids:
            message += f"\n\n以下POI缺少多边形，已跳过：{', '.join(sorted(skipped_ids))}"
        QMessageBox.information(self, "批量导出完成", message)
        self._captured_places.clear()
        self._update_capture_status()

    def _export_geojson(self) -> None:
        if not self._current_place:
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存为 GeoJSON", f"{self._current_place.poiid}.geojson", "GeoJSON (*.geojson)")
        if not path:
            return
        try:
            saved_path = self._geojson_exporter.export(self._current_place, path)
            QMessageBox.information(self, "导出完成", f"GeoJSON 已保存到\n{saved_path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _export_shapefile(self) -> None:
        if not self._current_place:
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存为 Shapefile", f"{self._current_place.poiid}.shp", "Shapefile (*.shp)")
        if not path:
            return
        try:
            saved_path = self._shp_exporter.export(self._current_place, path)
            QMessageBox.information(self, "导出完成", f"Shapefile 已保存到\n{saved_path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _on_zoom_slider_change(self, value: int) -> None:
        factor = value / 100.0
        self.web_view.setZoomFactor(factor)
        self.zoom_label.setText(f"{value}%")

    def _zoom_in(self) -> None:
        current_value = self.zoom_slider.value()
        self.zoom_slider.setValue(min(200, current_value + 10))

    def _zoom_out(self) -> None:
        current_value = self.zoom_slider.value()
        self.zoom_slider.setValue(max(25, current_value - 10))


def main() -> None:
    def resource_path(relative: str) -> str:
        # Resolve resources when running from source or a frozen/Nuitka onefile build
        if hasattr(sys, "_MEIPASS"):
            return str(Path(sys._MEIPASS) / relative)
        if getattr(sys, "frozen", False):
            return str(Path(sys.argv[0]).resolve().parent / relative)
        return str(Path(__file__).resolve().parent / relative)

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    # Ensure a light palette for consistency across OS theme settings
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("white"))
    app.setPalette(palette)
    window = MainWindow()
    icon = QIcon(resource_path("favicon.ico"))
    app.setWindowIcon(icon)
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
