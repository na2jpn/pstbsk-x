from __future__ import annotations
import sys, threading, time, math, wave
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QRectF, QTimer, Signal, QLockFile, QPointF
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QTextCursor, QImage, QPolygonF
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QLabel, QPlainTextEdit, QLineEdit, QPushButton, QGroupBox,
    QComboBox, QStatusBar, QScrollArea, QSplitter, QListWidget, QStackedWidget,
    QFormLayout, QCheckBox, QSpinBox, QSizePolicy, QMessageBox, QFileDialog,
    QRadioButton, QButtonGroup, QProgressBar, QSlider
)

from . import APP_NAME, VERSION
from .i18n import tr
from .storage import AppPaths, ConfigStore, backup_log
from .qso import DecodeRow, QsoSession
from .adif import QsoRecord, append_adif
from .timeutil import format_clock
from .single_instance import ActivationServer, request_activation
from .radio import RIG_MODELS, create_controller, validate_radio
from .yaesu import YAESU_MODELS
from .civ import CIVController
from .updater import inspect_zip, prepare_update, launch_updater, report_startup
from .audio_io import device_choices, monitor_tone, play_samples, check_output, capture_input, SAMPLE_RATE
from .signal_view import measure_audio, meter_percent, SPECTRUM_BINS
from .tone_profiles import (normalize_profile, modulate_profile,
                            audio_occupied_bandwidth, AF_OBW_TARGET_HZ)
from .rx_decoder import BurstDecoder, ReceivedFrame
from .frame import pack_frame, TYPE_TEXT, TYPE_CQ, TYPE_REPORT, TYPE_QSL, TYPE_FINAL
from .ui_common import (
    BURGUNDY, BURGUNDY_PALE, BURGUNDY_PALE_2, AMBER, BORDER,
    common_stylesheet, apply_windows_caption_color,
    restore_window_geometry, save_window_geometry,
)



def resource_file(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "resources" / name


class DecodeView(QPlainTextEdit):
    def __init__(self, on_double_click, parent=None):
        super().__init__(parent)
        self._on_double_click = on_double_click

    def mouseDoubleClickEvent(self, event):
        self._on_double_click(event)
        super().mouseDoubleClickEvent(event)


class QsoTextButton(QPushButton):
    """A real push button whose complete transmit text wraps at narrow widths."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.label=QLabel(self)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.label.setStyleSheet("background:transparent;border:0;font-family:Consolas,monospace;")
        layout=QVBoxLayout(self); layout.setContentsMargins(7,3,7,3); layout.addWidget(self.label)
        self.setMinimumHeight(38)

    def setText(self, value):
        self.label.setText(value)
        self.setAccessibleName(value)
        self.updateGeometry()

    def set_template_pending(self, pending):
        self.label.setStyleSheet(
            "background:transparent;border:0;font-family:Consolas,monospace;"
            + ("color:#888;" if pending else "color:#202020;"))


class SpectrumWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(166)
        self.spectrum=None
        self.history=QImage(SPECTRUM_BINS, 70, QImage.Format_RGB32)
        self.history.fill(QColor("#10161c"))
        self.sensitivity=50
        self.notice=""

    def clear(self):
        self.spectrum=None
        self.history.fill(QColor("#10161c"))
        self.update()

    def set_samples(self, spectrum):
        self.spectrum=spectrum
        floor=-35-0.65*self.sensitivity
        image=QImage(self.history.width(), self.history.height(), QImage.Format_RGB32)
        image.fill(QColor("#10161c"))
        painter=QPainter(image)
        painter.drawImage(0, 0, self.history.copy(0, 1, self.history.width(), self.history.height()-1))
        painter.end()
        for i, db in enumerate(spectrum):
            v=max(0.,min(1.,(float(db)-floor)/(0.-floor)))
            image.setPixelColor(i,image.height()-1,QColor(int(15+220*v),int(28+180*v),int(38+78*v)))
        self.history=image
        self.notice=""
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(8, 8, -8, -8)
        p.fillRect(r, QColor("#10161c"))
        spectrum_height=max(25,(r.height()-18)//2)
        graph=QRectF(r.left(),r.top(),r.width(),spectrum_height)
        p.setPen(QPen(QColor("#34424c"), 1))
        for i in range(7):
            x = r.left() + r.width() * i / 6
            p.drawLine(int(x), int(graph.top()), int(x), int(graph.bottom()))
        for i in range(3):
            y = graph.top() + graph.height() * i / 2
            p.drawLine(r.left(), int(y), r.right(), int(y))

        # Display 0..3000 Hz, decode-active range 300..2700 Hz.
        x1 = r.left() + r.width() * 0.1
        x2 = r.left() + r.width() * 0.9
        p.fillRect(QRectF(x1, graph.top(), x2 - x1, graph.height()), QColor(123, 16, 32, 28))
        if self.spectrum is not None:
            floor=-35-0.65*self.sensitivity
            points=QPolygonF([QPointF(r.left()+i*r.width()/(SPECTRUM_BINS-1),
                         graph.bottom()-max(0.,min(1.,(float(db)-floor)/(0.-floor)))*graph.height())
                         for i,db in enumerate(self.spectrum)])
            p.setPen(QPen(QColor("#8de4c9"),1.4))
            p.drawPolyline(points)
        waterfall=QRectF(r.left(),graph.bottom()+3,r.width(),max(1,r.bottom()-graph.bottom()-19))
        p.drawImage(waterfall,self.history)
        p.setPen(QColor("#cbd5dc"))
        p.setFont(QFont("Consolas", 9))
        for hz in range(0, 3001, 500):
            x = r.left() + r.width() * hz / 3000
            p.drawText(int(x) - 15, r.bottom() - 4, str(hz))
        if self.notice:
            p.setPen(QColor("#d6c1c7"))
            p.drawText(r.left()+10,r.top()+18,self.notice)


class ManagedWindow(QMainWindow):
    geometry_key = "window"
    default_size = (760, 620)
    minimum_size = (360, 280)

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.setWindowIcon(main.windowIcon())
        self.setStyleSheet(common_stylesheet())
        restore_window_geometry(
            self,
            main.config,
            self.geometry_key,
            self.default_size,
            self.minimum_size,
        )

    def showEvent(self, event):
        super().showEvent(event)
        apply_windows_caption_color(self)

    def closeEvent(self, event):
        save_window_geometry(self, self.main.config, self.geometry_key)
        self.main.store.save()
        super().closeEvent(event)


class FirstRunWindow(ManagedWindow):
    geometry_key = "first_run"
    default_size = (620, 440)
    minimum_size = (360, 280)
    completed = Signal(str, str)

    def __init__(self, main):
        self.lang = main.lang
        super().__init__(main, None)
        self.setWindowFlag(Qt.Window, True)
        self._build()
        self.retranslate()

    def _build(self):
        root = QWidget(); root.setObjectName("pageRoot")
        lay = QVBoxLayout(root); lay.setContentsMargins(28, 24, 28, 24); lay.setSpacing(16)

        header = QFrame(); header.setObjectName("card")
        hl = QVBoxLayout(header); hl.setContentsMargins(20, 18, 20, 18)
        self.title = QLabel(); self.title.setStyleSheet(f"font-size:24px;font-weight:800;color:{BURGUNDY};")
        self.sub = QLabel("PS Ham-ware / AKIHABARA-GIKEN / JH1HST"); self.sub.setStyleSheet("color:#666;")
        hl.addWidget(self.title); hl.addWidget(self.sub)
        lay.addWidget(header)

        card = QFrame(); card.setObjectName("card")
        form = QFormLayout(card); form.setContentsMargins(20, 18, 20, 18); form.setSpacing(12)
        self.lang_label = QLabel()
        self.lang_combo = QComboBox(); self.lang_combo.addItems(["日本語", "English"])
        self.lang_combo.setCurrentText("English" if self.lang == "en" else "日本語")
        self.call_label = QLabel()
        self.call_edit = QLineEdit(self.main.config.get("callsign", ""))
        self.error = QLabel(); self.error.setStyleSheet("color:#a00020;font-weight:700;")
        form.addRow(self.lang_label, self.lang_combo)
        form.addRow(self.call_label, self.call_edit)
        form.addRow("", self.error)
        lay.addWidget(card)
        lay.addStretch()

        row = QHBoxLayout(); row.addStretch()
        self.go = QPushButton(); self.go.setObjectName("primary"); self.go.setMinimumWidth(150)
        row.addWidget(self.go); lay.addLayout(row)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(root); self.setCentralWidget(scroll)

        self.lang_combo.currentTextChanged.connect(self._lang_changed)
        self.go.clicked.connect(self._complete)

    def _lang_changed(self, text):
        self.lang = "en" if text == "English" else "ja"
        self.retranslate()

    def retranslate(self):
        self.setWindowTitle(tr(self.lang, "first_title"))
        self.title.setText(tr(self.lang, "first_title"))
        self.lang_label.setText(tr(self.lang, "language_select"))
        self.call_label.setText(tr(self.lang, "first_callsign"))
        self.go.setText(tr(self.lang, "continue"))
        if self.error.text():
            self.error.setText(tr(self.lang, "callsign_required"))

    def _complete(self):
        call = self.call_edit.text().strip().upper()
        if not call:
            self.error.setText(tr(self.lang, "callsign_required"))
            return
        self.completed.emit(self.lang, call)
        self.close()

    def closeEvent(self, event):
        super().closeEvent(event)
        if not self.main.config.get("callsign"):
            # Closing initial setup means the application is not usable yet.
            QTimer.singleShot(0, self.main.close)


class WarningWindow(ManagedWindow):
    geometry_key = "operating_note"
    default_size = (650, 430)
    minimum_size = (360, 280)
    acknowledged = Signal()

    def __init__(self, main):
        self.lang = main.lang
        super().__init__(main, None)
        self.setWindowFlag(Qt.Window, True)
        self._build(); self.retranslate()

    def _build(self):
        root = QWidget(); root.setObjectName("pageRoot")
        lay = QVBoxLayout(root); lay.setContentsMargins(28, 24, 28, 24); lay.setSpacing(14)
        card = QFrame(); card.setObjectName("card")
        cl = QVBoxLayout(card); cl.setContentsMargins(22, 20, 22, 20); cl.setSpacing(14)
        self.title = QLabel(); self.title.setStyleSheet(f"font-size:22px;font-weight:800;color:{BURGUNDY};")
        self.body = QLabel(); self.body.setWordWrap(True); self.body.setStyleSheet("font-size:13px;line-height:1.4;")
        cl.addWidget(self.title); cl.addWidget(self.body); cl.addStretch()
        lay.addWidget(card, 1)
        row = QHBoxLayout(); row.addStretch()
        self.ok = QPushButton(); self.ok.setObjectName("primary"); self.ok.setMinimumWidth(150)
        row.addWidget(self.ok); lay.addLayout(row)
        self.ok.clicked.connect(self._ack)
        self.setCentralWidget(root)

    def set_language(self, lang):
        self.lang = lang; self.retranslate()

    def retranslate(self):
        self.setWindowTitle(tr(self.lang, "warning_title"))
        self.title.setText(tr(self.lang, "warning_title"))
        self.body.setText(tr(self.lang, "warning"))
        self.ok.setText(tr(self.lang, "confirm"))

    def _ack(self):
        self.main.config["warning_ack"] = True
        self.main.store.save()
        self.acknowledged.emit()
        self.close()


class SettingsWindow(ManagedWindow):
    geometry_key = "settings"
    default_size = (820, 620)
    minimum_size = (420, 300)
    saved = Signal()
    test_finished = Signal(str)
    monitor_finished = Signal(str)

    def __init__(self, main):
        self.lang = main.lang
        super().__init__(main, None)
        self.setWindowFlag(Qt.Window, True)
        self._monitor_stop=threading.Event(); self._monitor_active=False
        self._build(); self.retranslate(); self.load_values()
        self.test_finished.connect(self._test_complete)
        self.monitor_finished.connect(self._monitor_complete)
        self._testing=False
        self._test_controller=None

    def _build(self):
        root = QWidget(); root.setObjectName("pageRoot")
        outer = QVBoxLayout(root); outer.setContentsMargins(18, 18, 18, 18); outer.setSpacing(12)
        top = QHBoxLayout()
        self.nav = QListWidget(); self.nav.setFixedWidth(170)
        self.stack = QStackedWidget()
        top.addWidget(self.nav); top.addWidget(self.stack, 1)
        outer.addLayout(top, 1)

        # Station page
        self.station = QWidget(); sf = QFormLayout(self.station); sf.setContentsMargins(20, 18, 20, 18)
        self.call_edit = QLineEdit(); self.call_lab = QLabel(); sf.addRow(self.call_lab, self.call_edit)
        self.stack.addWidget(self.station)

        # Rig/Audio page
        self.rig = QWidget(); rf = QFormLayout(self.rig); rf.setContentsMargins(20, 18, 20, 18); rf.setSpacing(10)
        self.maker = QComboBox(); self.maker.addItems(["ICOM", "Yaesu"])
        self.model = QComboBox(); self.com = QComboBox(); self.com.addItem("AUTO", "AUTO")
        for port, name in CIVController.port_choices(): self.com.addItem(name, port)
        self.civ = QComboBox(); self.civ.setEditable(True)
        self.baud = QComboBox(); self.baud.addItem("AUTO", "AUTO")
        for speed in (115200,57600,38400,19200,9600,4800): self.baud.addItem(str(speed),str(speed))
        self.ptt = QComboBox(); self.stopbits=QComboBox(); self.stopbits.addItems(["1","2"])
        self.ain=QComboBox(); self.aout=QComboBox()
        self._audio_choices(self.ain,"input"); self._audio_choices(self.aout,"output")
        self.maker_lab=QLabel(); self.model_lab=QLabel(); self.com_lab=QLabel(); self.ain_lab=QLabel(); self.aout_lab=QLabel()
        rf.addRow(self.maker_lab, self.maker); rf.addRow(self.model_lab, self.model); rf.addRow(self.com_lab, self.com)
        rf.addRow("CI-V", self.civ); rf.addRow("CAT / CI-V baud",self.baud); rf.addRow("PTT",self.ptt)
        rf.addRow("CAT stop bits",self.stopbits)
        tests = QHBoxLayout(); self.conn_btn=QPushButton(); self.ptt_btn=QPushButton(); self.test_note=QLabel(); self.test_note.setWordWrap(True); self.test_note.setStyleSheet("color:#666;")
        tests.addWidget(self.conn_btn); tests.addWidget(self.ptt_btn); tests.addStretch(); rf.addRow(tests); rf.addRow("", self.test_note)
        self.stack.addWidget(self.rig)

        self.audio_page=QWidget(); af=QFormLayout(self.audio_page)
        af.setContentsMargins(20,18,20,18)
        af.addRow(self.ain_lab,self.ain); af.addRow(self.aout_lab,self.aout)
        self.audio_note=QLabel(); self.audio_note.setWordWrap(True); af.addRow(self.audio_note)
        self.monitor_btn=QPushButton(); self.monitor_note=QLabel(); self.monitor_note.setWordWrap(True)
        af.addRow(self.monitor_btn); af.addRow(self.monitor_note)
        self.stack.addWidget(self.audio_page)

        # Only the measured narrowband format may be transmitted.
        self.tbsk_page=QWidget(); tf=QFormLayout(self.tbsk_page)
        tf.setContentsMargins(20,18,20,18); tf.setSpacing(12)
        self.tone_lab=QLabel(); self.tone_profile=QLabel()
        self.tone_profile.setWordWrap(True)
        self.tone_note=QLabel(); self.tone_note.setWordWrap(True)
        tf.addRow(self.tone_lab,self.tone_profile); tf.addRow(self.tone_note)
        self.stack.addWidget(self.tbsk_page)

        # Display page
        self.display = QWidget(); dv = QVBoxLayout(self.display); dv.setContentsMargins(20, 18, 20, 18); dv.setSpacing(12)
        self.show_jst = QCheckBox(); self.utc_note = QLabel(); self.window_note = QLabel(); self.utc_note.setStyleSheet("color:#666;"); self.window_note.setStyleSheet("color:#666;")
        dv.addWidget(self.show_jst); dv.addWidget(self.utc_note); dv.addWidget(self.window_note); dv.addStretch()
        self.stack.addWidget(self.display)

        # Log page
        self.log = QWidget(); lv = QVBoxLayout(self.log); lv.setContentsMargins(20, 18, 20, 18); lv.setSpacing(10)
        self.backup_head=QLabel(); self.backup_head.setStyleSheet(f"font-size:15px;font-weight:800;color:{BURGUNDY};")
        self.backup_desc=QLabel(); self.backup_desc.setWordWrap(True)
        self.backup_exit=QCheckBox("終了時にバックアップ")
        self.backup_every=QCheckBox("QSO件数ごとにバックアップ")
        self.backup_count=QSpinBox(); self.backup_count.setRange(1,1000000)
        self.backup_now=QPushButton("いますぐバックアップ")
        self.log_path_lab=QLabel(); self.log_path_value=QLineEdit(); self.log_path_value.setReadOnly(True)
        lv.addWidget(self.backup_head); lv.addWidget(self.backup_desc)
        lv.addWidget(self.backup_exit); lv.addWidget(self.backup_every); lv.addWidget(self.backup_count)
        lv.addWidget(self.backup_now); lv.addSpacing(8); lv.addWidget(self.log_path_lab); lv.addWidget(self.log_path_value); lv.addStretch()
        self.stack.addWidget(self.log)

        row = QHBoxLayout(); self.save_note=QLabel(); self.save_note.setStyleSheet("color:#12662c;font-weight:800;"); row.addWidget(self.save_note); row.addStretch(); self.save_btn=QPushButton(); self.save_btn.setObjectName("primary"); self.close_btn=QPushButton(); row.addWidget(self.save_btn); row.addWidget(self.close_btn)
        outer.addLayout(row)
        self.setCentralWidget(root)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.maker.currentTextChanged.connect(self._models)
        self.model.currentTextChanged.connect(self._model_changed)
        self.conn_btn.clicked.connect(lambda:self._test_radio(False)); self.ptt_btn.clicked.connect(lambda:self._test_radio(True))
        self.backup_now.clicked.connect(lambda:self.main.backup_now(manual=True))
        self.backup_every.toggled.connect(self.backup_count.setEnabled)
        self.save_btn.clicked.connect(self.save_values); self.close_btn.clicked.connect(self.close)
        self.monitor_btn.clicked.connect(self.toggle_monitor)
        self.nav.setCurrentRow(0)

    def _models(self):
        cur = self.model.currentText()
        self.model.blockSignals(True); self.model.clear()
        if self.maker.currentText() == "ICOM": self.model.addItems(list(RIG_MODELS))
        else: self.model.addItems(list(YAESU_MODELS))
        if cur:
            self.model.setCurrentText(cur)
        self.model.blockSignals(False)
        self._model_changed()

    def _audio_choices(self, combo, kind):
        combo.addItem("UNSET" if kind=="input" else "AUTO", "UNSET" if kind=="input" else "AUTO")
        if kind=="input": combo.addItem("AUTO", "AUTO")
        try:
            for label, key, index in device_choices(kind):
                combo.addItem(label, key)
        except Exception as exc:
            combo.setToolTip(str(exc))

    def toggle_monitor(self):
        if self._monitor_active:
            self._monitor_stop.set(); return
        if self.main._tx_busy:
            self.monitor_note.setText(tr(self.lang,"tx_busy")); return
        self._monitor_active=True; self._monitor_stop=threading.Event()
        self.monitor_btn.setText(tr(self.lang,"stop")); self.monitor_note.setText(tr(self.lang,"monitor_playing"))
        device=self.aout.currentData(); stop=self._monitor_stop
        def worker():
            try:
                played=monitor_tone(device,stop)
                result=tr(self.lang,"monitor_stopped" if not played else "monitor_done")
            except Exception as exc:
                result=f"{tr(self.lang,'audio_error')}: {exc}"
            self.monitor_finished.emit(result)
        threading.Thread(target=worker,daemon=True).start()

    def _monitor_complete(self, result):
        self._monitor_active=False; self.monitor_btn.setText(tr(self.lang,"check_monitor")); self.monitor_note.setText(result)

    @staticmethod
    def _select(combo, value):
        index=combo.findData(str(value))
        if index<0:
            combo.addItem(f"{value} (unavailable)",str(value)); index=combo.count()-1
        combo.setCurrentIndex(index)

    @staticmethod
    def _select_audio(combo, value, kind):
        if str(value).isdecimal():
            try:
                import sounddevice as sd
                device=sd.query_devices(int(value))
                name=device["name"]
                for n in range(combo.count()):
                    if str(combo.itemData(n)).split("|")[1:2]==[name]:
                        combo.setCurrentIndex(n); return
            except Exception:
                pass
        SettingsWindow._select(combo,value)

    def _model_changed(self):
        model=self.model.currentText(); yaesu=self.maker.currentText()=="Yaesu"
        if not yaesu and model in RIG_MODELS:
            self.civ.setCurrentText(f"{RIG_MODELS[model]:02X}")
        self.civ.setEnabled(not yaesu); self.stopbits.setEnabled(yaesu)
        self.ptt.clear(); self.ptt.addItems(["CAT"] if yaesu else ["CI-V","RTS","DTR"])

    def _radio_values(self):
        yaesu=self.maker.currentText()=="Yaesu"
        return {"model":self.model.currentText(),"civ_address":self.civ.currentText().strip().upper(),
                "com_port":self.com.currentData(),"civ_baud":self.baud.currentData(),
                "cat_baud":self.baud.currentData(),"ptt":self.ptt.currentText(),
                "cat_stopbits":int(self.stopbits.currentText()),"auto_data_mode":False}

    def _test_radio(self, ptt):
        if self._testing: return
        if not ptt:
            if self.main.radio_busy or self.main._tx_busy:
                self.test_note.setText(tr(self.lang,"tx_busy")); return
            if not self.save_values(): return
            if self.main.radio_busy:
                self.main._reconnect_after_settings=True
            elif self.main.radio is None:
                self.main.toggle_connection()
            self.test_note.setText(tr(self.lang,"connecting_shared"))
            return
        if self.main.radio is not None and not self.main.radio_busy:
            self.main.ptt_test(); self.test_note.setText(tr(self.lang,"ptt_shared")); return
        values=self._radio_values()
        try: ctl=create_controller(values)
        except Exception as exc: self.test_note.setText(str(exc)); return
        self._testing=True; self._test_controller=ctl
        self.conn_btn.setEnabled(False); self.ptt_btn.setEnabled(False)
        self.test_note.setText("接続確認中…" if not ptt else "PTT確認中…")
        def worker():
            try:
                st=ctl.connect(values["com_port"],values["cat_baud"] if values["ptt"]=="CAT" else values["civ_baud"])
                if not st.connected: result=st.message
                elif ptt:
                    method=getattr(ctl,{"CAT":"set_ptt","CI-V":"set_ptt","RTS":"set_rts","DTR":"set_dtr"}[values["ptt"]])
                    try:
                        success=method(True)
                        if success: time.sleep(.5)
                    finally: released=method(False)
                    result="PTTテスト成功（0.5秒）" if success and released else "PTTのON/OFF確認に失敗しました"
                else: result=f"接続成功: {st.port} / {st.baud} bps / {st.frequency_hz:,} Hz" if st.frequency_hz is not None else f"接続成功: {st.port} / {st.baud} bps"
            except Exception as exc: result=f"接続テスト失敗: {exc}"
            finally:
                ctl.disconnect()
                self.test_finished.emit(result)
        threading.Thread(target=worker,daemon=True).start()

    def _test_complete(self, result):
        self._testing=False; self._test_controller=None
        self.conn_btn.setEnabled(True); self.ptt_btn.setEnabled(True)
        self.test_note.setText(result)

    def closeEvent(self, event):
        if self._monitor_active:
            self._monitor_stop.set(); event.ignore(); return
        if self._testing:
            if self._test_controller is not None: self._test_controller.cancel.set()
            self.test_note.setText(tr(self.lang,"test_wait"))
            event.ignore(); return
        super().closeEvent(event)

    def load_values(self):
        c=self.main.config; rig=c.get("rig",{})
        self.call_edit.setText(c.get("callsign", ""))
        model=rig.get("model", "IC-7300")
        self.maker.setCurrentText("Yaesu" if model in YAESU_MODELS else "ICOM")
        self._models(); self.model.setCurrentText(model); self._model_changed()
        self.civ.setCurrentText(rig.get("civ_address") or (f"{RIG_MODELS[model]:02X}" if model in RIG_MODELS else ""))
        self._select(self.com,rig.get("com_port",rig.get("com") or "AUTO"))
        self._select(self.baud,rig.get("civ_baud", "AUTO") if model in RIG_MODELS else rig.get("cat_baud","AUTO"))
        self.ptt.setCurrentText(rig.get("ptt","CAT" if model in YAESU_MODELS else "CI-V"))
        self.stopbits.setCurrentText(str(rig.get("cat_stopbits",1 if model=="FTX-1" else 2)))
        self._select_audio(self.ain,rig.get("audio_in") or "UNSET","input")
        self._select_audio(self.aout,rig.get("audio_out") or "AUTO","output")
        self.show_jst.setChecked(bool(c.get("display",{}).get("show_jst", True)))
        backup=c.get("backup",{})
        self.backup_exit.setChecked(backup.get("on_exit",True))
        self.backup_every.setChecked(backup.get("every_enabled",False))
        self.backup_count.setValue(backup.get("every_count",30))
        self.backup_count.setEnabled(self.backup_every.isChecked())
        self.log_path_value.setText(str(self.main.paths.log_file))

    def save_values(self):
        if self._testing:
            self.test_note.setText(tr(self.lang,"test_wait")); return False
        if self.main.radio_busy or self.main._tx_busy:
            self.test_note.setText("無線機操作の終了後に保存してください / Wait for the rig operation."); return False
        call=self.call_edit.text().strip().upper()
        if not call:
            self.test_note.setText(tr(self.lang,"callsign_required")); return False
        try: validate_radio(self._radio_values())
        except ValueError as exc:
            self.nav.setCurrentRow(1); self.test_note.setText(str(exc)); return False
        self.main.config["callsign"] = call
        new_rig=dict(self._radio_values(),maker=self.maker.currentText(),
                     audio_in=self.ain.currentData(),audio_out=self.aout.currentData())
        old_rig=self.main.config.get("rig",{})
        changed=any(old_rig.get(k)!=new_rig.get(k) for k in ("model","civ_address","com_port","cat_baud","civ_baud","ptt","cat_stopbits"))
        if changed and self.main.radio is not None: self.main.toggle_connection()
        self.main.config["rig"] = new_rig
        self.main.config.setdefault("tbsk",{})["tone_profile"] = normalize_profile(None)
        self.main.config.setdefault("display",{})["show_jst"] = self.show_jst.isChecked()
        self.main.config.setdefault("backup",{}).update(on_exit=self.backup_exit.isChecked(),
            every_enabled=self.backup_every.isChecked(),every_count=self.backup_count.value())
        self.main.store.save(); self.main.apply_settings(); self.saved.emit()
        self.main.statusBar().showMessage(tr(self.lang, "save"), 3000)
        self.save_note.setText(tr(self.lang,"saved"))
        QTimer.singleShot(3500, lambda:self.save_note.setText(""))
        return True

    def set_language(self, lang):
        self.lang=lang; self.retranslate()

    def retranslate(self):
        L=self.lang; self.setWindowTitle(tr(L,"settings_title"))
        current=max(0,self.nav.currentRow()); self.nav.clear()
        self.nav.addItems([tr(L,"station_page"),tr(L,"rig_page"),tr(L,"audio_page"),tr(L,"tbsk_page"),tr(L,"display_page"),tr(L,"log_page")]); self.nav.setCurrentRow(current)
        self.tone_lab.setText(tr(L,"tone_format")); self.tone_note.setText(tr(L,"tone_note"))
        self.tone_profile.setText(tr(L,"tone_native_detail"))
        self.call_lab.setText(tr(L,"callsign")); self.maker_lab.setText(tr(L,"maker")); self.model_lab.setText(tr(L,"model")); self.com_lab.setText(tr(L,"com")); self.ain_lab.setText(tr(L,"audio_in")); self.aout_lab.setText(tr(L,"audio_out"))
        self.conn_btn.setText(tr(L,"connection_test")); self.ptt_btn.setText(tr(L,"ptt_test")); self.show_jst.setText(tr(L,"show_jst")); self.utc_note.setText(tr(L,"utc_always")); self.window_note.setText(tr(L,"window_note"))
        self.backup_head.setText(tr(L,"backup_title")); self.backup_desc.setText(tr(L,"backup_desc")); self.log_path_lab.setText(tr(L,"log_path")); self.save_btn.setText(tr(L,"save")); self.close_btn.setText(tr(L,"close"))
        self.backup_exit.setText(tr(L,"backup_exit")); self.backup_every.setText(tr(L,"backup_every")); self.backup_now.setText(tr(L,"backup_now"))
        self.audio_note.setText(tr(L,"audio_note"))
        self.monitor_btn.setText(tr(L,"stop" if self._monitor_active else "check_monitor"))


class AboutWindow(ManagedWindow):
    geometry_key = "about"
    default_size = (650, 600)
    minimum_size = (360, 280)

    def __init__(self, main):
        self.lang=main.lang
        super().__init__(main, None); self.setWindowFlag(Qt.Window, True)
        self._build(); self.retranslate()

    def _build(self):
        root=QWidget(); root.setObjectName("pageRoot")
        outer=QVBoxLayout(root); outer.setContentsMargins(18,18,18,18); outer.setSpacing(12)
        header=QFrame(); header.setStyleSheet(f"background:{BURGUNDY};border-radius:14px;")
        hl=QVBoxLayout(header); hl.setContentsMargins(22,18,22,18); hl.setSpacing(4); hl.setAlignment(Qt.AlignCenter)
        icon=QLabel(); icon.setAlignment(Qt.AlignCenter)
        p=resource_file("pstbskx.png")
        if p.exists(): icon.setPixmap(QIcon(str(p)).pixmap(82,82))
        title=QLabel(APP_NAME); title.setAlignment(Qt.AlignCenter); title.setStyleSheet("color:white;font-size:27px;font-weight:800;")
        self.version=QLabel(); self.version.setAlignment(Qt.AlignCenter); self.version.setStyleSheet("color:#f5d9de;font-weight:700;")
        self.tagline=QLabel(); self.tagline.setAlignment(Qt.AlignCenter); self.tagline.setStyleSheet("color:#f9edf0;")
        hl.addWidget(icon); hl.addWidget(title); hl.addWidget(self.version); hl.addWidget(self.tagline); outer.addWidget(header)
        self.intro_h,self.intro_b=self._card(outer); self.project_h,self.project_b=self._card(outer); self.third_h,self.third_b=self._card(outer)
        self.project_b.setText("PS Ham-ware / AKIHABARA-GIKEN / JH1HST")
        btns=QHBoxLayout(); btns.addStretch(); self.github=QPushButton(); self.license=QPushButton(); btns.addWidget(self.github); btns.addWidget(self.license); outer.addLayout(btns)
        outer.addStretch(); bottom=QHBoxLayout(); bottom.addStretch(); self.close_btn=QPushButton(); self.close_btn.setObjectName("primary"); bottom.addWidget(self.close_btn); outer.addLayout(bottom)
        self.github.clicked.connect(lambda:QDesktopServices.openUrl(QUrl("https://github.com/nyatla/TBSKmodem")))
        self.license.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.main.paths.licenses_dir/"TBSKmodem_LICENSE.txt"))))
        self.close_btn.clicked.connect(self.close); self.setCentralWidget(root)

    def _card(self, outer):
        card=QFrame(); card.setObjectName("card"); l=QVBoxLayout(card); l.setContentsMargins(16,13,16,13); l.setSpacing(6)
        h=QLabel(); h.setStyleSheet(f"color:{BURGUNDY};font-size:14px;font-weight:800;"); b=QLabel(); b.setWordWrap(True)
        l.addWidget(h); l.addWidget(b); outer.addWidget(card); return h,b

    def set_language(self,lang): self.lang=lang; self.retranslate()
    def retranslate(self):
        L=self.lang; self.setWindowTitle(tr(L,"about")); self.version.setText(f"Ver {VERSION}"); self.tagline.setText(tr(L,"about_tagline"))
        self.intro_h.setText(tr(L,"about_intro_heading")); self.intro_b.setText(tr(L,"about_intro_body")); self.project_h.setText(tr(L,"about_project_heading")); self.third_h.setText(tr(L,"about_third_heading")); self.third_b.setText(tr(L,"about_third_body")); self.github.setText(tr(L,"github")); self.license.setText(tr(L,"license")); self.close_btn.setText(tr(L,"close"))


class LogWindow(ManagedWindow):
    geometry_key="log_view"; default_size=(900,600); minimum_size=(400,300)
    def __init__(self,main):
        self.lang=main.lang; super().__init__(main,None); self.setWindowFlag(Qt.Window,True); self._build(); self.retranslate(); self.refresh()
    def _build(self):
        root=QWidget(); root.setObjectName("pageRoot"); lay=QVBoxLayout(root); lay.setContentsMargins(18,18,18,18); lay.setSpacing(10)
        self.text=QPlainTextEdit(); self.text.setReadOnly(True); self.text.setFont(QFont("Consolas",10)); lay.addWidget(self.text,1)
        row=QHBoxLayout(); self.refresh_btn=QPushButton(); self.folder_btn=QPushButton(); row.addWidget(self.refresh_btn); row.addWidget(self.folder_btn); row.addStretch(); self.close_btn=QPushButton(); self.close_btn.setObjectName("primary"); row.addWidget(self.close_btn); lay.addLayout(row)
        self.refresh_btn.clicked.connect(self.refresh); self.folder_btn.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.main.paths.log_dir)))); self.close_btn.clicked.connect(self.close); self.setCentralWidget(root)
    def refresh(self):
        p=self.main.paths.log_file; self.text.setPlainText(p.read_text(encoding="utf-8",errors="replace") if p.exists() else "")
    def set_language(self,lang): self.lang=lang; self.retranslate()
    def retranslate(self):
        L=self.lang; self.setWindowTitle(tr(L,"log_window")); self.refresh_btn.setText(tr(L,"refresh")); self.folder_btn.setText(tr(L,"open_folder")); self.close_btn.setText(tr(L,"close"))


class QsoLogWindow(ManagedWindow):
    geometry_key="qso_confirm"; default_size=(520,410); minimum_size=(380,300)
    def __init__(self, main):
        self.lang=main.lang; super().__init__(main,None); self.setWindowFlag(Qt.Window,True)
        self.record=None; self.session=None
        root=QWidget(); root.setObjectName("pageRoot"); layout=QVBoxLayout(root)
        layout.setContentsMargins(20,18,20,18); layout.setSpacing(12)
        self.heading=QLabel(); self.heading.setStyleSheet(f"color:{BURGUNDY};font-size:18px;font-weight:800;")
        layout.addWidget(self.heading)
        self.note=QLabel(); self.note.setWordWrap(True); layout.addWidget(self.note)
        self.details=QPlainTextEdit(); self.details.setReadOnly(True); self.details.setFont(QFont("Consolas",10)); layout.addWidget(self.details,1)
        row=QHBoxLayout(); row.addStretch(); self.later=QPushButton(); self.save=QPushButton(); self.save.setObjectName("primary")
        row.addWidget(self.later); row.addWidget(self.save); layout.addLayout(row)
        self.later.clicked.connect(self.close); self.save.clicked.connect(self._save)
        self.setCentralWidget(root); self.retranslate()

    def set_language(self,lang): self.lang=lang; self.retranslate()
    def retranslate(self):
        self.setWindowTitle(tr(self.lang,"qso_log_title")); self.heading.setText(tr(self.lang,"qso_log_title"))
        self.note.setText(tr(self.lang,"qso_log_note")); self.later.setText(tr(self.lang,"close")); self.save.setText(tr(self.lang,"record_qso"))
        self._render()

    def offer(self,record,session):
        self.record=record; self.session=session; self._render()
        self.show(); self.raise_(); self.activateWindow()

    def _render(self):
        if self.record is None: return
        r=self.record; when=r.qso_time_utc.astimezone(timezone.utc)
        lines=[f"UTC       {when:%Y-%m-%d %H:%M:%S}",f"CALL      {r.call}",
               f"FREQ      {r.freq_mhz:.6f} MHz" if r.freq_mhz is not None else "FREQ      --",
               f"BAND      {r.band or '--'}",f"MODE      {r.mode}",
               f"RST_SENT  {r.rst_sent or '--'}",f"RST_RCVD  {r.rst_rcvd or '--'}",
               f"RX AF     {r.af_hz} Hz",f"RX S/N    {r.rx_snr:+.1f} dB" if r.rx_snr is not None else "RX S/N    --"]
        self.details.setPlainText("\n".join(lines))

    def _save(self):
        if self.record is not None and self.main._log_session(self.record,self.session): self.close()


class JogDial(QWidget):
    steps=Signal(int)
    def __init__(self,parent=None):
        super().__init__(parent); self.setFixedSize(110,110); self.last=None; self.remainder=0.0; self.rotation=0
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.translate(self.rect().center())
        p.setPen(QPen(QColor("#1b1c1e"),2)); p.setBrush(QColor("#34363a")); p.drawEllipse(QPointF(0,0),45,45)
        p.setPen(QPen(QColor("#575a60"),2)); p.setBrush(QColor("#292b2e")); p.drawEllipse(QPointF(0,0),38,38)
        p.save(); p.rotate(self.rotation)
        p.setPen(QPen(QColor("#17191c"),1)); p.setBrush(QColor("#aeb3ba")); p.drawEllipse(QPointF(0,-29),6,6)
        p.setPen(QColor("#e0e0e0")); p.drawPoint(QPointF(-1,-30)); p.restore()
        p.setPen(QColor("#f2f2f2")); p.drawText(-25,-10,50,20,Qt.AlignCenter,"TUNE")
    def advance(self, n):
        self.rotation=(self.rotation+n*15)%360; self.update(); self.steps.emit(n)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self.isEnabled(): self.last=self._angle(event.position()); self.remainder=0
    def mouseMoveEvent(self,event):
        if self.last is None or not self.isEnabled(): return
        angle=self._angle(event.position()); delta=(angle-self.last+180)%360-180; self.last=angle; self.remainder+=delta
        n=int(self.remainder/15); self.remainder-=n*15
        if n: self.advance(n)
    def mouseReleaseEvent(self,event): self.last=None
    def wheelEvent(self,event):
        if self.isEnabled(): self.advance(-1 if event.angleDelta().y()>0 else 1); event.accept()
    def _angle(self,pos):
        d=pos-QPointF(self.rect().center()); return math.degrees(math.atan2(d.x(),-d.y()))


class ControlWindow(ManagedWindow):
    geometry_key="control"; default_size=(560,490); minimum_size=(400,300)
    BANDS=(("1.8",1908000),("3.5",3520000),("7",7040000),("10",10130000),("14",14080000),("18",18100000),("21",21000000),("24",24920000),("28",28080000),("50",50200000),("144",144100000),("430",430100000),("1.2G",1296100000))
    def __init__(self,main):
        self.lang=main.lang; super().__init__(main,None); self.setWindowFlag(Qt.Window,True)
        root=QWidget(); root.setObjectName("pageRoot"); lay=QVBoxLayout(root); lay.setContentsMargins(18,18,18,18)
        self.readout=QLabel(); self.readout.setStyleSheet(f"color:{BURGUNDY};font-size:22px;font-weight:800;"); lay.addWidget(self.readout)
        row=QHBoxLayout(); self.entry=QLineEdit(); self.entry.setPlaceholderText("MHz: 14.080000"); self.set_btn=QPushButton(); row.addWidget(self.entry,1); row.addWidget(QLabel("MHz")); row.addWidget(self.set_btn); lay.addLayout(row)
        self.band_grid=QGridLayout(); self.bands=[]
        for n,(name,hz) in enumerate(self.BANDS):
            b=QPushButton(name); b.setToolTip("周波数呼び出し（送信可否の判定ではありません） / Frequency recall only"); b.clicked.connect(lambda checked=False,v=hz:self.main.tune_radio(v)); self.band_grid.addWidget(b,n//7,n%7); self.bands.append(b)
        lay.addLayout(self.band_grid)
        row=QHBoxLayout(); self.minus=QPushButton("−"); self.plus=QPushButton("+"); self.dial=JogDial(); self.step_lab=QLabel(); self.step=QComboBox()
        for label,value in (("1 Hz",1),("10 Hz",10),("100 Hz",100),("1 kHz",1000),("10 kHz",10000)): self.step.addItem(label,value)
        self.step.setCurrentIndex(1); row.addWidget(self.minus); row.addWidget(self.dial); row.addWidget(self.plus); row.addWidget(self.step_lab); row.addWidget(self.step); lay.addLayout(row)
        controls=QHBoxLayout(); self.feature_buttons={}
        for name in ("NB","NR","AN","MN"):
            b=QPushButton(name+" —"); b.setCheckable(True); b.clicked.connect(lambda checked=False,n=name:self.main.toggle_feature(n)); controls.addWidget(b); self.feature_buttons[name]=b
        lay.addLayout(controls)
        row=QHBoxLayout(); row.addWidget(QLabel("FILTER")); self.filter=QComboBox(); self.filter.currentIndexChanged.connect(self.change_filter); row.addWidget(self.filter,1); self.narrow=QPushButton("NARROW —"); self.narrow.setCheckable(True); self.narrow.clicked.connect(self.change_narrow); row.addWidget(self.narrow); lay.addLayout(row)
        self.note=QLabel(); self.note.setWordWrap(True); lay.addWidget(self.note); lay.addStretch()
        self.ptt_btn=QPushButton(); lay.addWidget(self.ptt_btn); self.setCentralWidget(root)
        self.set_btn.clicked.connect(self.apply_frequency); self.entry.returnPressed.connect(self.apply_frequency)
        self.minus.clicked.connect(lambda:self.nudge(-1)); self.plus.clicked.connect(lambda:self.nudge(1)); self.dial.steps.connect(self.nudge); self.ptt_btn.clicked.connect(main.ptt_test)
        self.retranslate(); self.refresh()

    def set_language(self,lang): self.lang=lang; self.retranslate()
    def retranslate(self):
        self.setWindowTitle(f"PSTBSK-X {tr(self.lang,'control')}"); self.set_btn.setText(tr(self.lang,"set_frequency")); self.step_lab.setText(tr(self.lang,"step")); self.ptt_btn.setText(tr(self.lang,"ptt_test")); self.refresh()
    def refresh(self):
        hz=self.main.frequency_hz; ready=self.main.radio is not None and not self.main.radio_busy
        self.readout.setText(f"{hz/1e6:.6f} MHz" if hz is not None else tr(self.lang,"no_frequency"))
        self.note.setText(tr(self.lang,"control_wait") if self.main.radio is None else tr(self.lang,"preview_notice"))
        for w in (self.entry,self.set_btn,self.minus,self.plus,self.dial,self.step,self.ptt_btn): w.setEnabled(ready)
        model=self.main.config.get("rig",{}).get("model","")
        for n,b in enumerate(self.bands):
            allowed=(n>=10 if model in ("IC-9700","IC-905") else n<12 if model in ("IC-705","IC-7100","FT-991 / FT-991A","FTX-1") else n<10)
            if model=="IC-9700": allowed=n in (10,11,12)
            b.setEnabled(ready and allowed)
        for name,b in self.feature_buttons.items():
            value=self.main.radio_features.get(name)
            b.setText(f"{name} "+("ON" if value is True else "OFF" if value is False else "—")); b.setChecked(value is True); b.setEnabled(ready and value is not None)
        state=self.main.radio_filter
        choices=state.get("options",[]) if isinstance(state,dict) else []
        if [(self.filter.itemData(i),self.filter.itemText(i)) for i in range(self.filter.count())]!=list(choices):
            self.filter.blockSignals(True); self.filter.clear()
            for value,label in choices: self.filter.addItem(label,value)
            self.filter.blockSignals(False)
        self.filter.blockSignals(True); self.filter.setCurrentIndex(self.filter.findData(state.get("value")) if isinstance(state,dict) else -1); self.filter.blockSignals(False)
        self.filter.setEnabled(ready and bool(choices) and state.get("value") is not None)
        narrow=state.get("narrow") if isinstance(state,dict) else None
        self.narrow.setText("NARROW "+("ON" if narrow is True else "OFF" if narrow is False else "—")); self.narrow.setChecked(narrow is True); self.narrow.setEnabled(ready and narrow is not None)
    def change_filter(self,index):
        if index>=0 and self.filter.isEnabled(): self.main.set_filter(self.filter.itemData(index))
    def change_narrow(self): self.main.set_narrow()
    def apply_frequency(self):
        from decimal import Decimal, InvalidOperation
        try:
            value=Decimal(self.entry.text().strip())*1000000
            if not value.is_finite() or value!=value.to_integral_value() or not 100000<=value<=15000000000: raise ValueError()
            hz=int(value)
        except (InvalidOperation,ValueError):
            self.note.setText("MHzを数値で入力してください / Enter a valid MHz value"); return
        self.main.tune_radio(hz)
    def nudge(self,direction):
        if self.main.frequency_hz is not None: self.main.tune_radio(self.main.frequency_hz+direction*self.step.currentData())


class UpdateWindow(ManagedWindow):
    geometry_key="update"; default_size=(620,430); minimum_size=(420,320)
    def __init__(self,main):
        self.lang=main.lang; super().__init__(main,None); self.setWindowFlag(Qt.Window,True)
        root=QWidget(); root.setObjectName("pageRoot"); lay=QVBoxLayout(root); lay.setContentsMargins(22,22,22,22); lay.setSpacing(12)
        self.head=QLabel(); self.head.setStyleSheet(f"color:{BURGUNDY};font-size:20px;font-weight:800;"); lay.addWidget(self.head)
        self.body=QLabel(); self.body.setWordWrap(True); lay.addWidget(self.body)
        self.path_label=QLabel(); lay.addWidget(self.path_label)
        self.path=QLineEdit(); self.path.setReadOnly(True); lay.addWidget(self.path)
        self.result=QLabel(); self.result.setWordWrap(True); lay.addWidget(self.result); lay.addStretch()
        row=QHBoxLayout(); self.choose=QPushButton(); self.apply=QPushButton(); self.apply.setObjectName("primary"); self.cancel=QPushButton(); row.addWidget(self.choose); row.addWidget(self.apply); row.addStretch(); row.addWidget(self.cancel); lay.addLayout(row)
        self.choose.clicked.connect(self.select_zip); self.apply.clicked.connect(self.start_update); self.cancel.clicked.connect(self.close)
        self.apply.setEnabled(False); self.selected=None; self.setCentralWidget(root); self.retranslate()
    def set_language(self,lang): self.lang=lang; self.retranslate()
    def retranslate(self):
        L=self.lang; self.setWindowTitle(tr(L,"update_menu")); self.head.setText(f"PSTBSK-X Ver {VERSION}")
        self.body.setText("Windows配布用 PSTBSK-X_0.xx_win64.zip を展開せずに指定してください。更新前に実行ファイルと設定・ログ・バックアップを退避します。成功後は自動再起動します。ソースZIP・差分ZIPは使用できません。" if L=="ja" else "Select an unextracted PSTBSK-X_0.xx_win64.zip Windows release. The EXE, settings, log and backups are saved before replacement. The app restarts after success. Source and diff ZIPs cannot be used.")
        self.path_label.setText("選択した更新ZIP" if L=="ja" else "Selected release ZIP")
        self.path.setPlaceholderText("更新ZIPはまだ選択されていません" if L=="ja" else "No release ZIP selected")
        self.choose.setText("更新ZIPを選択…" if L=="ja" else "Select release ZIP…"); self.apply.setText("バージョンアップ" if L=="ja" else "Upgrade"); self.cancel.setText(tr(L,"close"))
    def select_zip(self):
        filename,_=QFileDialog.getOpenFileName(self,tr(self.lang,"update_menu"),"","ZIP (*.zip)")
        if not filename: return
        self.selected=None; self.apply.setEnabled(False); self.path.setText(filename); self.path.setToolTip(filename)
        try:
            if sys.platform!="win32" or not getattr(sys,"frozen",False): raise RuntimeError("Windows EXE版から更新してください")
            info=inspect_zip(Path(filename),VERSION,self.main.base_dir)
            if not (self.main.base_dir/"config"/"pstbskx-release.json").is_file(): raise ValueError("現在の配布物に更新用情報がありません")
        except Exception as exc: self.result.setText(str(exc)); return
        self.selected=Path(filename); self.result.setText(f"Ver {VERSION} → Ver {info['version']}"); self.apply.setEnabled(True)
    def start_update(self):
        if self.selected is None: return
        if self.main.radio_busy or (self.main.settings_window is not None and self.main.settings_window._testing):
            self.result.setText(tr(self.lang,"test_wait")); return
        try:
            stage=prepare_update(self.selected,self.main.base_dir,VERSION)
            launch_updater(stage,self.main.base_dir)
        except Exception as exc: self.result.setText(str(exc)); return
        self.apply.setEnabled(False); self.choose.setEnabled(False)
        self.main.close()


class MainWindow(QMainWindow):
    radio_done=Signal(str,object,object)
    tx_done=Signal(str,bool,str,object,object)
    rx_data=Signal(object,float,int)
    rx_error=Signal(str,int)
    tx_data=Signal(object)
    rx_frame=Signal(object,int)
    rx_diagnostic=Signal(str,int)
    rx_capture_done=Signal(str,int)
    def __init__(self, base_dir: Path):
        super().__init__()
        self.base_dir=Path(base_dir); self.paths=AppPaths(self.base_dir); self.paths.ensure(); self.store=ConfigStore(self.paths)
        self.first_launch=not self.paths.config_file.exists(); self.config=self.store.load(); self.lang=self.config.get("language","ja")
        self.session=QsoSession(self.config.get("callsign","") or "NOCALL")
        self._rows=[]; self._clock_colon=True; self._received_ids={}; self._rx_decoder=None
        self.settings_window=None; self.about_window=None; self.log_window=None; self.warning_window=None; self.first_run_window=None; self.control_window=None; self.update_window=None; self.qso_log_window=None
        self.radio=None; self.radio_busy=False; self.frequency_hz=None; self.radio_features={}; self.radio_filter=None; self._autocq_sent=0
        self._tx_busy=False; self._tx_stop=threading.Event(); self._sequence_kind="cq"; self._preview_source="sequence"; self._reconnect_after_settings=False
        self._rx_stop=threading.Event(); self._rx_device=None; self._rx_generation=0; self._rx_active=False
        self._rx_capture_path=None
        self.autocq_timer=QTimer(self); self.autocq_timer.setSingleShot(True); self.autocq_timer.timeout.connect(self._autocq_tick)
        self.radio_done.connect(self._radio_completed)
        self.tx_done.connect(self._transmission_completed)
        self.rx_data.connect(self._received_audio)
        self.rx_error.connect(self._rx_failed)
        self.rx_frame.connect(self._received_frame)
        self.rx_diagnostic.connect(self._received_diagnostic)
        self.rx_capture_done.connect(self._rx_capture_finished)
        self.tx_data.connect(self._transmitted_audio)
        self.radio_poll=QTimer(self); self.radio_poll.setInterval(2500); self.radio_poll.timeout.connect(self._poll_radio); self.radio_poll.start()
        self.clock_timer=QTimer(self); self.clock_timer.setInterval(2000); self.clock_timer.timeout.connect(self._clock_tick); self.clock_timer.start()

        self.setWindowTitle(f"{APP_NAME} Ver {VERSION}")
        png=resource_file("pstbskx.png")
        if png.exists(): self.setWindowIcon(QIcon(str(png)))
        self.setStyleSheet(common_stylesheet())
        restore_window_geometry(self,self.config,"main",(1280,800),(320,240))
        self._build_ui(); self.retranslate(); self.apply_settings(); self._render_decode()
        QTimer.singleShot(0,self.first_run_if_needed)

    def _build_ui(self):
        root=QWidget(); root.setObjectName("pageRoot"); outer=QVBoxLayout(root); outer.setContentsMargins(0,0,0,0)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        content=QWidget(); content.setMinimumWidth(930); content.setStyleSheet(f"background:{BURGUNDY_PALE};")
        lay=QVBoxLayout(content); lay.setContentsMargins(12,10,12,12); lay.setSpacing(9)

        top=QHBoxLayout()
        self.connect_btn=QPushButton(); self.connection_label=QLabel(); self.frequency_label=QLabel(); self.frequency_label.setStyleSheet(f"color:{BURGUNDY};font-weight:800;")
        self.control_btn=QPushButton(); self.tone_status=QLabel()
        self.tone_status.setStyleSheet("color:#555;font-size:11px;")
        self.clock_lbl=QLabel(); self.clock_lbl.setFont(QFont("Consolas",10)); self.clock_lbl.setStyleSheet("color:#555;font-weight:700;")
        self.call_lbl=QLabel(self.config.get("callsign","") or "NOCALL"); self.call_lbl.setStyleSheet(f"color:{BURGUNDY};font-weight:800;font-size:14px;")
        top.addWidget(self.connection_label); top.addWidget(self.connect_btn); top.addWidget(self.frequency_label); top.addWidget(self.control_btn); top.addWidget(self.tone_status); top.addStretch(); top.addWidget(self.clock_lbl); top.addSpacing(10); top.addWidget(self.call_lbl); lay.addLayout(top)

        splitter=QSplitter(Qt.Horizontal); splitter.setChildrenCollapsible(False); lay.addWidget(splitter,1)
        left=QWidget(); left_layout=QVBoxLayout(left); left_layout.setContentsMargins(0,0,3,0); left_layout.setSpacing(8)
        self.spec_group=QGroupBox(); sg=QVBoxLayout(self.spec_group); self.spectrum=SpectrumWidget(); sg.addWidget(self.spectrum); left_layout.addWidget(self.spec_group)

        levels=QHBoxLayout(); levels.setContentsMargins(5,0,5,0); levels.setSpacing(5)
        self.sq_lab=QLabel(); self.sq_value=QSpinBox(); self.sq_value.setRange(0,100); self.sq_value.setSuffix(" %"); self.sq_value.setFixedWidth(70)
        self.sq_state=QLabel("●"); self.sq_state.setFixedWidth(15)
        self.level_lab=QLabel(); self.rx_meter=QProgressBar(); self.rx_meter.setRange(0,100); self.rx_meter.setTextVisible(False); self.rx_meter.setMinimumWidth(70); self.rx_meter.setMaximumWidth(155)
        self.sensitivity_lab=QLabel(); self.sensitivity=QSlider(Qt.Horizontal); self.sensitivity.setRange(0,100); self.sensitivity.setMinimumWidth(70); self.sensitivity.setMaximumWidth(155)
        self.sensitivity_value=QLabel(); self.sensitivity_value.setFixedWidth(29)
        self.rx_reset=QPushButton(); self.rx_reset.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed)
        for widget in (self.sq_lab,self.sq_value,self.sq_state,self.level_lab,self.rx_meter,self.sensitivity_lab,self.sensitivity,self.sensitivity_value):
            levels.addWidget(widget,1 if widget in (self.rx_meter,self.sensitivity) else 0)
        levels.addStretch(); levels.addWidget(self.rx_reset)
        left_layout.addLayout(levels)

        self.decode_group=QGroupBox(); dl=QVBoxLayout(self.decode_group)
        self.decode=DecodeView(self._decode_double_click); self.decode.setReadOnly(True); self.decode.setFont(QFont("Consolas",10)); self.decode.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.decode.setStyleSheet("QPlainTextEdit{background:#fffdfd;border:1px solid #cdbcc0;}")
        self.hint=QLabel(); self.hint.setStyleSheet("color:#666;"); self.hint.setWordWrap(True); dl.addWidget(self.decode,1); dl.addWidget(self.hint)
        left_layout.addWidget(self.decode_group,1); splitter.addWidget(left)

        right=QWidget(); rv=QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(5)
        self.qso_group=QGroupBox(); qv=QVBoxLayout(self.qso_group); qv.setContentsMargins(9,15,9,7); qv.setSpacing(3)
        info=QFrame(); info.setObjectName("card"); ig=QGridLayout(info); ig.setContentsMargins(10,8,10,8)
        self.his=QLabel("--"); self.af=QLabel("-- Hz"); self.snr=QLabel("-- dB"); self.sent=QLabel("--"); self.rcvd=QLabel("--")
        self.field_labels={}; fields=[("his_call",self.his),("rx_af",self.af),("current_snr",self.snr),("sent_report",self.sent),("rcvd_report",self.rcvd)]
        for i,(k,w) in enumerate(fields):
            lab=QLabel(); lab.setStyleSheet("color:#666;"); self.field_labels[k]=lab; col=i%3; row=(i//3)*2; ig.addWidget(lab,row,col); ig.addWidget(w,row+1,col)
        qv.addWidget(info)

        self.sequence_select=QButtonGroup(self); self.sequence_select.setExclusive(True)
        self.cq_label,self.cq_radio=self._seq_heading(qv,"cq"); self.cq_btn=self._sequence_button(qv); self.cq_radio.setChecked(True)
        ar=QHBoxLayout(); self.autocq_btn=QPushButton(); self.autocq_btn.setObjectName("autoCQ"); self.autocq_btn.setCheckable(True); self.autocq_interval_lab=QLabel(); self.autocq_interval=QSpinBox(); self.autocq_interval.setRange(5,120); self.autocq_seconds=QLabel(); self.autocq_count_lab=QLabel(); self.autocq_count=QSpinBox(); self.autocq_count.setRange(1,999); self.autocq_times=QLabel(); ar.addWidget(self.autocq_btn); ar.addWidget(self.autocq_count_lab); ar.addWidget(self.autocq_count); ar.addWidget(self.autocq_times); ar.addWidget(self.autocq_interval_lab); ar.addWidget(self.autocq_interval); ar.addWidget(self.autocq_seconds); qv.addLayout(ar)

        self.report_label,self.report_radio=self._seq_heading(qv,"report"); self.report_btn=self._sequence_button(qv)
        arow=QHBoxLayout(); self.a_lab=QLabel(); self.free_a=QLineEdit(); arow.addWidget(self.a_lab); arow.addWidget(self.free_a,1); qv.addLayout(arow)

        self.qsl_label,self.qsl_radio=self._seq_heading(qv,"qsl"); self.qsl_btn=self._sequence_button(qv)
        brow=QHBoxLayout(); self.b_lab=QLabel(); self.free_b=QLineEdit(); brow.addWidget(self.b_lab); brow.addWidget(self.free_b,1); qv.addLayout(brow)

        self.final_label,self.final_radio=self._seq_heading(qv,"final"); self.final_btn=self._sequence_button(qv)
        actions=QHBoxLayout(); actions.addStretch(); self.sequence_clear=QPushButton(); self.sequence_stop=QPushButton(); self.sequence_send=QPushButton()
        actions.addWidget(self.sequence_clear); actions.addWidget(self.sequence_stop); actions.addWidget(self.sequence_send); qv.addLayout(actions)

        self.qso_group.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum); rv.addWidget(self.qso_group)
        self.free_group=QGroupBox(); fv=QVBoxLayout(self.free_group); fv.setContentsMargins(9,15,9,7); fv.setSpacing(4)
        fr=QHBoxLayout(); self.free_lab=QLabel(); self.free=QLineEdit(); self.clear_btn=QPushButton(); self.free_btn=QPushButton(); fr.addWidget(self.free_lab); fr.addWidget(self.free,1); fr.addWidget(self.clear_btn); fr.addWidget(self.free_btn); fv.addLayout(fr)
        self.free_group.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum); rv.addWidget(self.free_group)
        preview_row=QHBoxLayout(); self.preview_lab=QLabel(); self.preview=QPlainTextEdit(); self.preview.setReadOnly(True); self.preview.setMaximumHeight(44); self.preview.setStyleSheet("background:#fffdfd;")
        preview_row.addWidget(self.preview_lab); preview_row.addWidget(self.preview,1); rv.addLayout(preview_row)
        rv.addStretch()
        self.allow_disconnected=QCheckBox(); rv.addWidget(self.allow_disconnected)
        right_scroll=QScrollArea(); right_scroll.setWidgetResizable(True); right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        right.setMinimumWidth(445); right_scroll.setWidget(right); self.right_scroll=right_scroll
        splitter.addWidget(right_scroll); splitter.setStretchFactor(0,3); splitter.setStretchFactor(1,2)
        splitter.setSizes([690,520])

        scroll.setWidget(content); self.main_scroll=scroll; outer.addWidget(scroll); self.setCentralWidget(root); self.setStatusBar(QStatusBar())
        self.rx_diag_label=QLabel(); self.rx_diag_label.setStyleSheet("color:#53616c;")
        self.statusBar().addPermanentWidget(self.rx_diag_label)
        self._menus(); self._connect()

    def _seq_heading(self, parent_layout, kind):
        row=QHBoxLayout(); radio=QRadioButton(); radio.setAccessibleName(kind.upper()); radio.toggled.connect(lambda checked,k=kind: self._sequence_changed(k) if checked else None)
        self.sequence_select.addButton(radio); l=QLabel(); l.setStyleSheet(f"color:{BURGUNDY};font-weight:800;"); row.addWidget(radio); row.addWidget(l); row.addStretch(); parent_layout.addLayout(row); return l,radio

    def _sequence_button(self, parent_layout):
        b=QsoTextButton(); parent_layout.addWidget(b); return b

    def _menus(self):
        mb=self.menuBar(); self.m_file=mb.addMenu(""); self.a_open=QAction(self); self.a_folder=QAction(self); self.a_logview=QAction(self); self.a_qso_log=QAction(self); self.a_capture_rx=QAction(self); self.a_exit=QAction(self); self.m_file.addActions([self.a_open,self.a_folder,self.a_logview,self.a_qso_log]); self.m_file.addSeparator(); self.m_file.addAction(self.a_capture_rx); self.m_file.addSeparator(); self.m_file.addAction(self.a_exit)
        self.m_settings=mb.addMenu(""); self.a_settings=QAction(self); self.m_settings.addAction(self.a_settings)
        self.m_lang=mb.addMenu(""); self.a_ja=QAction("日本語",self); self.a_en=QAction("English",self); self.m_lang.addActions([self.a_ja,self.a_en])
        self.m_help=mb.addMenu(""); self.a_note=QAction(self); self.a_about=QAction(self); self.a_reset=QAction(self); self.a_update=QAction(self); self.m_help.addAction(self.a_note); self.m_help.addSeparator(); self.m_help.addActions([self.a_reset,self.a_update]); self.m_help.addSeparator(); self.m_help.addAction(self.a_about)

    def _connect(self):
        self.a_exit.triggered.connect(self.close); self.a_open.triggered.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.log_file))))
        self.a_folder.triggered.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.log_dir)))); self.a_logview.triggered.connect(self.show_log_window); self.a_settings.triggered.connect(self.show_settings)
        self.a_ja.triggered.connect(lambda:self.set_language("ja")); self.a_en.triggered.connect(lambda:self.set_language("en")); self.a_note.triggered.connect(lambda:self.show_warning(force=True)); self.a_about.triggered.connect(self.show_about)
        self.a_reset.triggered.connect(self.reset_windows); self.a_update.triggered.connect(self.show_update)
        self.a_qso_log.triggered.connect(self.offer_qso_log)
        self.a_capture_rx.triggered.connect(self._capture_rx_input)
        self.connect_btn.clicked.connect(self.toggle_connection); self.control_btn.clicked.connect(self.show_control)
        for kind,b in (("cq",self.cq_btn),("report",self.report_btn),("qsl",self.qsl_btn),("final",self.final_btn)):
            b.clicked.connect(lambda checked=False,k=kind:self._select_sequence(k))
        self.sequence_send.clicked.connect(self._send_selected_sequence)
        self.sequence_stop.clicked.connect(self.stop_transmission)
        self.sequence_clear.clicked.connect(self.clear_session)
        self.free_btn.clicked.connect(lambda:self.tx(self.session.free_text(self.free.text()),kind="free",allow_no_target=True)); self.clear_btn.clicked.connect(self.free.clear)
        self.free_a.textChanged.connect(self._refresh_sequence_buttons); self.free_b.textChanged.connect(self._refresh_sequence_buttons); self.free.textChanged.connect(self._preview_free_text); self.autocq_btn.toggled.connect(self._toggle_autocq); self.autocq_interval.valueChanged.connect(self._autocq_interval_changed); self.autocq_count.valueChanged.connect(self._autocq_count_changed)
        self.allow_disconnected.toggled.connect(self._allow_disconnected_changed)
        self.sq_value.valueChanged.connect(self._rx_control_changed)
        self.sensitivity.valueChanged.connect(self._rx_control_changed)
        self.rx_reset.clicked.connect(self._reset_rx_controls)

    def retranslate(self):
        L=self.lang; self.m_file.setTitle(tr(L,"file")); self.m_settings.setTitle(tr(L,"settings")); self.m_lang.setTitle(tr(L,"language")); self.m_help.setTitle(tr(L,"help"))
        self.connect_btn.setText(tr(L,"disconnect") if self.radio else tr(L,"connect")); self.control_btn.setText(tr(L,"control")); self._show_frequency(); self._update_connection_label()
        self.a_open.setText(tr(L,"open_log")); self.a_folder.setText(tr(L,"open_log_folder")); self.a_logview.setText(tr(L,"log_view")); self.a_qso_log.setText(tr(L,"record_qso")); self.a_capture_rx.setText(tr(L,"capture_rx")); self.a_exit.setText(tr(L,"exit")); self.a_settings.setText(tr(L,"settings_open")); self.a_note.setText(tr(L,"operating_note")); self.a_about.setText(tr(L,"about")); self.a_reset.setText(tr(L,"reset_windows")); self.a_update.setText(tr(L,"update_menu"))
        self._spectrum_title(); self.decode_group.setTitle(tr(L,"decode")); self.qso_group.setTitle(tr(L,"qso")); self.hint.setText(tr(L,"decode_hint"))
        self.rx_diag_label.setText(tr(L,"rx_diag_"+getattr(self,"_rx_diag_stage","idle")))
        self.sq_lab.setText(tr(L,"squelch")); self.level_lab.setText(tr(L,"rx_level")); self.sensitivity_lab.setText(tr(L,"sensitivity"))
        self.rx_reset.setText(tr(L,"reset_rx")); self.preview_lab.setText(tr(L,"tx_preview"))
        self.sq_value.setToolTip(tr(L,"squelch_help")); self.sensitivity.setToolTip(tr(L,"sensitivity_help"))
        for k,lab in self.field_labels.items(): lab.setText(tr(L,k))
        self.cq_label.setText(tr(L,"seq_cq")); self.report_label.setText(tr(L,"seq_report")); self.qsl_label.setText(tr(L,"seq_qsl")); self.final_label.setText(tr(L,"seq_final")); self.qso_group.setTitle(tr(L,"sequence_group")); self.free_group.setTitle(tr(L,"free_group")); self.a_lab.setText(tr(L,"free_a")); self.b_lab.setText(tr(L,"free_b")); self.free_lab.setText(tr(L,"free_text")); self.free_btn.setText(tr(L,"free_send")); self.clear_btn.setText(tr(L,"free_clear")); self.autocq_btn.setText(tr(L,"autocq")); self.autocq_interval_lab.setText(tr(L,"autocq_interval")); self.autocq_count_lab.setText(tr(L,"autocq_repeats")); self.autocq_times.setText(tr(L,"times")); self.autocq_seconds.setText(tr(L,"seconds")); self.allow_disconnected.setText(tr(L,"allow_disconnected"))
        for button in (self.cq_btn,self.report_btn,self.qsl_btn,self.final_btn):
            button.setToolTip(tr(L,"select_only"))
        self.allow_disconnected.setToolTip(tr(L,"disconnected_tip"))
        self.sequence_clear.setText(tr(L,"free_clear")); self.sequence_stop.setText(tr(L,"stop")); self.sequence_send.setText(tr(L,"free_send"))
        self.sequence_send.setToolTip(tr(L,"tx_busy") if self._tx_busy else "")
        self.statusBar().showMessage(tr(L,"mock_notice"),12000)
        for w in (self.settings_window,self.about_window,self.log_window,self.warning_window,self.control_window,self.update_window,self.qso_log_window):
            if w is not None and hasattr(w,"set_language"): w.set_language(L)
        self._refresh_sequence_buttons(); self._clock_update()

    def first_run_if_needed(self):
        if self.first_launch or not self.config.get("callsign"):
            self.first_run_window=FirstRunWindow(self); self.first_run_window.completed.connect(self._first_run_complete); self.first_run_window.show(); self.first_run_window.raise_(); self.first_run_window.activateWindow(); return
        if not self.config.get("warning_ack",False): self.show_warning(force=True)

    def _first_run_complete(self, lang, call):
        self.lang=lang; self.config["language"]=lang; self.config["callsign"]=call; self.session.my_call=call; self.call_lbl.setText(call); self.store.save(); self.retranslate(); self.show_warning(force=True)

    def set_language(self,lang):
        if lang==self.lang: return
        self.lang=lang; self.config["language"]=lang; self.store.save(); self.retranslate(); self.show_warning(force=True)

    def show_warning(self, force=False):
        if not force and self.config.get("warning_ack",False): return
        if self.warning_window is None: self.warning_window=WarningWindow(self)
        self.warning_window.set_language(self.lang); self.warning_window.show(); self.warning_window.raise_(); self.warning_window.activateWindow()

    def show_settings(self):
        if self.settings_window is None: self.settings_window=SettingsWindow(self)
        self.settings_window.set_language(self.lang); self.settings_window.load_values(); self.settings_window.show(); self.settings_window.raise_(); self.settings_window.activateWindow()

    def show_about(self):
        if self.about_window is None: self.about_window=AboutWindow(self)
        self.about_window.set_language(self.lang); self.about_window.show(); self.about_window.raise_(); self.about_window.activateWindow()

    def show_log_window(self):
        if self.log_window is None: self.log_window=LogWindow(self)
        self.log_window.set_language(self.lang); self.log_window.refresh(); self.log_window.show(); self.log_window.raise_(); self.log_window.activateWindow()

    def show_control(self):
        if self.control_window is None: self.control_window=ControlWindow(self)
        self.control_window.set_language(self.lang); self.control_window.refresh(); self.control_window.show(); self.control_window.raise_(); self.control_window.activateWindow()
        self._poll_radio()

    def show_update(self):
        if self.update_window is None: self.update_window=UpdateWindow(self)
        self.update_window.set_language(self.lang); self.update_window.show(); self.update_window.raise_(); self.update_window.activateWindow()

    def reset_windows(self):
        self.config["windows"]={}
        self.showNormal(); restore_window_geometry(self,self.config,"main",(1280,800),(320,240))
        for w in (self.first_run_window,self.settings_window,self.about_window,self.log_window,self.warning_window,self.control_window,self.update_window,self.qso_log_window):
            if w is not None and w.isVisible():
                w.showNormal(); restore_window_geometry(w,self.config,w.geometry_key,w.default_size,w.minimum_size)
        self.store.save()

    def _show_frequency(self):
        self.frequency_label.setText(f"{self.frequency_hz/1e6:.6f} MHz" if self.frequency_hz is not None else tr(self.lang,"no_frequency"))
        if self.control_window is not None: self.control_window.refresh()

    def _update_connection_label(self):
        key="connecting" if self.radio_busy and self.radio is None else "connected" if self.radio else "disconnected"
        self.connection_label.setText(tr(self.lang,key))
        self.connection_label.setStyleSheet("color:#168038;font-weight:800;" if key=="connected" else "color:#666;font-weight:700;")

    def _radio_work(self,kind,operation):
        if self.radio_busy or self._tx_busy: return
        self.radio_busy=True; self.connect_btn.setEnabled(False)
        self._update_connection_label()
        if self.control_window is not None: self.control_window.refresh()
        def worker():
            try: self.radio_done.emit(kind,operation(),None)
            except Exception as exc: self.radio_done.emit(kind,None,str(exc))
        threading.Thread(target=worker,daemon=True).start()

    def toggle_connection(self):
        if self.radio_busy or self._tx_busy: return
        if self.radio is not None:
            ctl=self.radio
            self._radio_work("disconnect",lambda:ctl.disconnect())
            return
        values=dict(self.config.get("rig",{}))
        try: ctl=create_controller(values)
        except Exception as exc: self.statusBar().showMessage(str(exc),10000); return
        def connect():
            try:
                status=ctl.connect(values.get("com_port") or values.get("com") or "AUTO", values.get("cat_baud","AUTO") if values.get("ptt")=="CAT" else values.get("civ_baud","AUTO"))
                if not status.connected: raise RuntimeError(status.message)
                return ctl,status
            except Exception:
                ctl.disconnect(); raise
        self._radio_work("connect",connect)

    def _radio_completed(self,kind,result,error):
        self.radio_busy=False; self.connect_btn.setEnabled(True)
        if error:
            self.statusBar().showMessage(error,12000)
        elif kind=="connect":
            self.radio,status=result; self.frequency_hz=status.frequency_hz
            self.statusBar().showMessage(f"{status.port} / {status.baud} bps",6000)
        elif kind=="disconnect": self.radio=None; self.frequency_hz=None; self.radio_features={}; self.radio_filter=None
        elif kind=="poll":
            hz,features,filtered=result
            if hz is not None: self.frequency_hz=hz
            if features is not None: self.radio_features=features; self.radio_filter=filtered
        elif kind=="feature":
            name,value=result; self.radio_features[name]=value
        elif kind=="filter": self.radio_filter=result
        elif kind=="tune":
            if result is not None: self.frequency_hz=result
        elif kind=="ptt": self.statusBar().showMessage("PTT ON/OFF 確認完了",6000)
        self.connect_btn.setText(tr(self.lang,"disconnect") if self.radio else tr(self.lang,"connect")); self._show_frequency(); self._update_connection_label()
        if self.settings_window is not None and self.settings_window.isVisible() and kind in ("connect","disconnect"):
            self.settings_window.test_note.setText(tr(self.lang,"connected") if self.radio else (error or tr(self.lang,"disconnected")))
        if kind=="disconnect" and self._reconnect_after_settings:
            self._reconnect_after_settings=False
            QTimer.singleShot(0,self.toggle_connection)
        if kind=="connect" and self.control_window is not None and self.control_window.isVisible(): QTimer.singleShot(0,self._poll_radio)

    def _poll_radio(self):
        if self.radio is not None and not self.radio_busy and not self._tx_busy:
            ctl=self.radio; full=self.control_window is not None and self.control_window.isVisible()
            def poll():
                hz=ctl.read_frequency()
                return hz,({name:ctl.read_feature(name) for name in ("NB","NR","AN","MN")} if full else None),(ctl.read_filter() if full else None)
            self._radio_work("poll",poll)

    def toggle_feature(self,name):
        if self.radio is None or self.radio_busy or self.radio_features.get(name) is None: return
        ctl=self.radio; on=not self.radio_features[name]
        def change():
            if not ctl.set_feature(name,on): raise RuntimeError(f"{name} の変更に失敗しました")
            return name,ctl.read_feature(name)
        self._radio_work("feature",change)

    def set_filter(self,value):
        if self.radio is None or self.radio_busy or not isinstance(self.radio_filter,dict): return
        ctl=self.radio; expected=dict(self.radio_filter)
        def change():
            if not ctl.set_filter(value,expected): raise RuntimeError("FILTER の変更に失敗しました")
            return ctl.read_filter()
        self._radio_work("filter",change)

    def set_narrow(self):
        if self.radio is None or self.radio_busy or not isinstance(self.radio_filter,dict) or self.radio_filter.get("narrow") is None: return
        ctl=self.radio; expected=dict(self.radio_filter)
        def change():
            if not ctl.set_narrow(not expected["narrow"],expected): raise RuntimeError("NARROW の変更に失敗しました")
            return ctl.read_filter()
        self._radio_work("filter",change)

    def tune_radio(self,hz):
        if self.radio is None or self.radio_busy: return
        ctl=self.radio
        def tune():
            if not ctl.set_frequency(hz): raise RuntimeError("周波数を設定できませんでした")
            return ctl.read_frequency()
        self._radio_work("tune",tune)

    def ptt_test(self):
        if self.radio is None or self.radio_busy: return
        ctl=self.radio; name={"CAT":"set_ptt","CI-V":"set_ptt","RTS":"set_rts","DTR":"set_dtr"}.get(self.config.get("rig",{}).get("ptt","CI-V"),"set_ptt"); method=getattr(ctl,name)
        def test():
            try:
                if not method(True): raise RuntimeError("PTT ON に失敗しました")
                time.sleep(.5)
            finally:
                if not method(False): raise RuntimeError("PTT OFF に失敗しました")
        self._radio_work("ptt",test)

    def backup_now(self, manual=True):
        try:
            path=backup_log(self.paths,10)
        except OSError as exc:
            QMessageBox.warning(self,tr(self.lang,"backup_title"),str(exc)); return False
        if path is None:
            if manual: self.statusBar().showMessage("バックアップするADIFがありません / No ADIF to back up",5000)
            return False
        self.config.setdefault("backup",{})["pending_qsos"]=0
        self.store.save()
        self.statusBar().showMessage(f"Backup: {path.name}",10000)
        return True

    def apply_settings(self):
        self.config.setdefault("tbsk",{})["tone_profile"] = normalize_profile(None)
        self.tone_status.setText(tr(self.lang,"tone_native"))
        self.call_lbl.setText(self.config.get("callsign","") or "NOCALL"); self.session.my_call=self.config.get("callsign","") or "NOCALL"
        ac=self.config.get("autocq",{}); sec=int(ac.get("interval_sec",10)); self.autocq_interval.blockSignals(True); self.autocq_interval.setValue(max(5,min(120,sec))); self.autocq_interval.blockSignals(False)
        self.autocq_count.blockSignals(True); self.autocq_count.setValue(max(1,min(999,int(ac.get("repeat_count",10))))); self.autocq_count.blockSignals(False)
        self.allow_disconnected.blockSignals(True); self.allow_disconnected.setChecked(bool(self.config.get("tx",{}).get("allow_disconnected",False))); self.allow_disconnected.blockSignals(False)
        controls=self.config.get("rx_display",{})
        for widget,value in ((self.sq_value,int(controls.get("sq",12))),
                             (self.sensitivity,int(controls.get("sensitivity",50)))):
            widget.blockSignals(True); widget.setValue(value); widget.blockSignals(False)
        self._rx_control_changed(save=False)
        self._start_rx_if_changed()
        self._clock_update(); self._refresh_sequence_buttons()

    def _spectrum_title(self):
        self.spec_group.setTitle(tr(self.lang,"tx_waterfall" if self._tx_busy else "waterfall"))

    def _rx_control_changed(self, value=None, save=True):
        self.spectrum.sensitivity=self.sensitivity.value()
        self.sensitivity_value.setText(str(self.sensitivity.value()))
        if save:
            self.config.setdefault("rx_display",{}).update(sq=self.sq_value.value(),sensitivity=self.sensitivity.value())
            self.store.save()
        if self._rx_decoder is not None:
            self._rx_decoder.threshold_db=-85+self.sq_value.value()*.6
        self.spectrum.update()

    def _reset_rx_controls(self):
        for widget,value in ((self.sq_value,12),(self.sensitivity,50)):
            widget.blockSignals(True); widget.setValue(value); widget.blockSignals(False)
        self._rx_control_changed()

    def _capture_rx_input(self):
        if not self._rx_active:
            self.statusBar().showMessage(tr(self.lang,"capture_no_input"),10000)
            return
        default=str(self.base_dir / "PSTBSK-X_RX_input.wav")
        filename,_=QFileDialog.getSaveFileName(self,tr(self.lang,"capture_rx"),default,
                                               "WAV (*.wav)")
        if filename:
            self._rx_capture_path=filename
            self.statusBar().showMessage(tr(self.lang,"capture_started"),12000)

    def _rx_capture_finished(self, path, generation):
        if generation!=self._rx_generation: return
        self.statusBar().showMessage(
            tr(self.lang,"capture_saved").format(path=path) if path else
            tr(self.lang,"capture_failed"),20000)

    def _start_rx_if_changed(self):
        device=self.config.get("rig",{}).get("audio_in") or "UNSET"
        if device==self._rx_device and (self._rx_active or device=="UNSET"): return
        self._rx_stop.set()
        self._rx_capture_path=None
        if self._rx_decoder is not None: self._rx_decoder.close(); self._rx_decoder=None
        self._rx_generation+=1
        generation=self._rx_generation
        self._rx_stop=threading.Event()
        self._rx_device=device
        self._rx_active=False
        self.rx_meter.setValue(0)
        self.sq_state.setStyleSheet("color:#777;")
        self.spectrum.clear()
        if device=="UNSET":
            self._received_diagnostic("idle",generation)
            self.spectrum.notice=tr(self.lang,"select_audio_in")
            self.spectrum.update()
            return
        stop=self._rx_stop
        self._rx_active=True
        decoder=BurstDecoder(lambda frame:self.rx_frame.emit(frame,generation),
                             threshold_db=-85+self.sq_value.value()*.6,
                             on_diagnostic=lambda stage:self.rx_diagnostic.emit(stage,generation))
        self._received_diagnostic("listening",generation)
        self._rx_decoder=decoder
        decoder.start()
        def worker():
            import numpy as np
            pending=np.empty(0,dtype=np.float32)
            capture_path=None; capture_chunks=[]; capture_length=0
            try:
                def receive(chunk):
                    nonlocal pending,capture_path,capture_chunks,capture_length
                    if not decoder.feed(chunk):
                        raise RuntimeError("TBSK decoder could not keep up with Audio IN")
                    if self._rx_capture_path is not None:
                        capture_path=self._rx_capture_path
                        self._rx_capture_path=None
                        capture_chunks=[]; capture_length=0
                    if capture_path:
                        capture_chunks.append(chunk.copy()); capture_length+=len(chunk)
                        if capture_length>=SAMPLE_RATE*10:
                            path=capture_path; data=np.concatenate(capture_chunks)[:SAMPLE_RATE*10]
                            capture_path=None; capture_chunks=[]; capture_length=0
                            def save_capture():
                                try:
                                    pcm=(np.clip(data,-1,1)*32767).astype("<i2")
                                    with wave.open(path,"wb") as output:
                                        output.setnchannels(1); output.setsampwidth(2)
                                        output.setframerate(SAMPLE_RATE)
                                        output.writeframes(pcm.tobytes())
                                    self.rx_capture_done.emit(path,generation)
                                except Exception:
                                    self.rx_capture_done.emit("",generation)
                            threading.Thread(target=save_capture,daemon=True,
                                             name="PSTBSK-X RX capture save").start()
                    pending=np.concatenate((pending,chunk))
                    if len(pending)>=4096:
                        spectrum,level=measure_audio(pending[-4096:],SAMPLE_RATE)
                        pending=pending[-2048:]
                        self.rx_data.emit(spectrum,level,generation)
                capture_input(device,stop,receive)
            except Exception as exc:
                if not stop.is_set(): self.rx_error.emit(str(exc),generation)
            finally: decoder.close()
        threading.Thread(target=worker,daemon=True,name="PSTBSK-X Audio IN").start()

    def _received_audio(self,spectrum,level,generation):
        if generation!=self._rx_generation or self._tx_busy or not self._rx_active: return
        amount=meter_percent(level)
        self.rx_meter.setValue(amount)
        opened=amount>=self.sq_value.value() and amount>0
        self.sq_state.setStyleSheet("color:#228048;" if opened else "color:#777;")
        self.sq_state.setToolTip(tr(self.lang,"sq_open" if opened else "sq_closed"))
        self.spectrum.set_samples(spectrum)

    def _received_diagnostic(self,stage,generation):
        if generation!=self._rx_generation: return
        if (stage not in ("decoded","idle","error") and
                time.monotonic()-getattr(self,"_rx_last_decoded",0)<8):
            return
        if stage=="decoded": self._rx_last_decoded=time.monotonic()
        self._rx_diag_stage=stage
        self.rx_diag_label.setText(tr(self.lang,"rx_diag_"+stage))

    def _rx_failed(self,error,generation):
        if generation!=self._rx_generation: return
        self._rx_active=False
        self._received_diagnostic("error",generation)
        self.rx_meter.setValue(0)
        self.spectrum.notice=tr(self.lang,"rx_audio_error")
        self.spectrum.update()
        self.statusBar().showMessage(f"{tr(self.lang,'rx_audio_error')}: {error}",12000)

    def _received_frame(self,frame:ReceivedFrame,generation):
        if generation!=self._rx_generation or not self._rx_active or self._tx_busy: return
        self._received_diagnostic("decoded",generation)
        key=(frame.source,frame.seq,frame.kind,frame.af_hz,frame.text)
        now=time.monotonic()
        self._received_ids={k:v for k,v in self._received_ids.items()
                            if now-v<(5 if k[0]=="raw" else 90)}
        if key in self._received_ids: return
        self._received_ids[key]=now
        if frame.source=="raw":
            incoming=f"[TBSK RAW] {frame.text}"
            if (self._rows and self._rows[-1].call=="--" and
                    self._rows[-1].text.startswith("[TBSK RAW] ") and
                    self._rows[-1].af_hz==frame.af_hz and
                    now-getattr(self,"_raw_last_time",0)<30 and
                    (incoming.startswith(self._rows[-1].text) or
                     self._rows[-1].text.startswith(incoming)) and
                    (incoming!=self._rows[-1].text or now-self._raw_last_time<5)):
                if len(incoming)>len(self._rows[-1].text):
                    self._rows[-1].text=incoming
            else:
                self._rows.append(DecodeRow(frame.when,frame.af_hz,frame.snr_db,"--",incoming))
            self._raw_last_time=now
            self._rows=self._rows[-300:]; self._render_decode()
            return
        self.add_decode(DecodeRow(frame.when,frame.af_hz,frame.snr_db,frame.call,frame.text))

    def _transmitted_audio(self,spectrum):
        if self._tx_busy: self.spectrum.set_samples(spectrum)

    def _clock_tick(self):
        self._clock_colon=not self._clock_colon; self._clock_update()

    def _clock_update(self):
        show_jst=bool(self.config.get("display",{}).get("show_jst",True)); self.clock_lbl.setText(format_clock(datetime.now(timezone.utc),show_jst,self._clock_colon))

    def _autocq_interval_changed(self, value):
        self.config.setdefault("autocq",{})["interval_sec"]=int(value); self.store.save()

    def _autocq_count_changed(self, value):
        self.config.setdefault("autocq",{})["repeat_count"]=int(value); self.store.save()

    def _allow_disconnected_changed(self,value):
        self.config.setdefault("tx",{})["allow_disconnected"]=bool(value); self.store.save()

    def _toggle_autocq(self, checked):
        self._style_autocq()
        if checked:
            if self._tx_busy or self.radio_busy:
                self.stop_autocq(); self.statusBar().showMessage(tr(self.lang,"tx_busy"),6000); return
            if self.radio is None and not self.allow_disconnected.isChecked():
                self.stop_autocq(); self.statusBar().showMessage(tr(self.lang,"tx_need_connection"),10000); return
            self.clear_session(keep_autocq=True); self._autocq_sent=0; self._autocq_tick()
            if self.autocq_btn.isChecked(): self.statusBar().showMessage(tr(self.lang,"autocq_started"),5000)
        else:
            self.autocq_timer.stop()
            if self._tx_busy: self._tx_stop.set()
            self.statusBar().showMessage(tr(self.lang,"autocq_stopped"),3000)

    def _style_autocq(self):
        # Qt can apply the :checked text color while leaving the native button
        # face pale. An explicit per-widget style keeps the active state visible
        # in Windows as well as in the offscreen renderer.
        if self.autocq_btn.isChecked():
            self.autocq_btn.setStyleSheet(
                "QPushButton {background-color:#c52234;color:white;"
                "border:2px solid #9b1424;border-radius:6px;font-weight:800;}"
                "QPushButton:hover {background-color:#a91629;color:white;}")
        else:
            self.autocq_btn.setStyleSheet(
                "QPushButton {background-color:#f1e5e8;color:#2b2b2b;"
                "border:1px solid #bc9fa6;border-radius:6px;}"
                "QPushButton:hover {background-color:#e7cbd2;}")

    def _autocq_tick(self):
        if not self.autocq_btn.isChecked() or self.session.his_call or self._autocq_sent>=self.autocq_count.value():
            self.stop_autocq(); return
        if not self.tx(self.session.cq_text(),kind="cq",allow_no_target=True,auto=True): self.stop_autocq()

    def stop_autocq(self, reply=False):
        if self.autocq_btn.isChecked():
            self.autocq_btn.blockSignals(True); self.autocq_btn.setChecked(False); self.autocq_btn.blockSignals(False)
        self._style_autocq()
        self.autocq_timer.stop()
        if self._tx_busy and self._tx_auto: self._tx_stop.set()
        if reply: self.statusBar().showMessage(tr(self.lang,"autocq_reply"),6000)

    def add_decode(self,row:DecodeRow):
        self._rows.append(row); self._rows=self._rows[-300:]
        reply=self.session.reply_call_to_me(row.text)
        if reply and self.autocq_btn.isChecked():
            self.stop_autocq(reply=True); self.session.select_decode(row)
        else:
            self.session.observe_decode(row)
        self._render_decode(); self._refresh_session()
        if (self.session.his_call and row.call.upper()==self.session.his_call.upper()
                and self.session.is_final_from_peer(row.text) and not self.session.logged):
            self.offer_qso_log()

    def _render_decode(self):
        lines=[]
        for r in self._rows:
            call=(r.call if len(r.call)<=12 else r.call[:9]+"...").ljust(12)
            snr="--" if r.text.startswith("[TBSK RAW] ") else f"{r.snr_db:+05.1f}"
            lines.append(f"{r.when:%H:%M:%S} | {r.af_hz:4d} Hz | S/N {snr} dB | {call} | {r.text}")
        self.decode.setPlainText("\n".join(lines)); self.decode.moveCursor(QTextCursor.End)

    def _decode_double_click(self,event):
        cursor=self.decode.cursorForPosition(event.position().toPoint()); block=cursor.blockNumber()
        if 0<=block<len(self._rows):
            row=self._rows[block]
            if row.call=="--":
                self.statusBar().showMessage(tr(self.lang,"unknown_sender"),5000); return
            self.stop_autocq(); self.session.select_decode(row); self._refresh_session(); self.statusBar().showMessage(f"{tr(self.lang,'selected')}: {row.call}",5000)

    def _refresh_session(self):
        self.his.setText(self.session.his_call or "--"); self.af.setText(f"{self.session.af_hz} Hz"); self.snr.setText("-- dB" if self.session.current_rx_snr is None else f"{self.session.current_rx_snr:+.1f} dB"); self.sent.setText(self.session.report_sent or "--"); self.rcvd.setText(self.session.report_rcvd or "--"); self._refresh_sequence_buttons()

    def _refresh_sequence_buttons(self):
        for kind,button in (("cq",self.cq_btn),("report",self.report_btn),
                            ("qsl",self.qsl_btn),("final",self.final_btn)):
            button.setText(self.session.sequence_preview(kind,self.free_a.text(),self.free_b.text()))
            button.set_template_pending(kind!="cq" and not self.session.his_call)
        self.sequence_send.setEnabled(not self._tx_busy and (self._sequence_kind=="cq" or bool(self.session.his_call)))
        if self._preview_source=="sequence":
            self.preview.setPlainText(self.session.sequence_preview(self._sequence_kind,self.free_a.text(),self.free_b.text()))

    def _sequence_changed(self,kind):
        self._sequence_kind=kind
        self._preview_source="sequence"
        if hasattr(self,"preview"):
            self._refresh_sequence_buttons()

    def _preview_free_text(self,value):
        self._preview_source="free"
        self.preview.setPlainText(self.session.free_text(value))

    def _select_sequence(self,kind):
        {"cq":self.cq_radio,"report":self.report_radio,"qsl":self.qsl_radio,"final":self.final_radio}[kind].setChecked(True)
        self._sequence_changed(kind)

    def _send_selected_sequence(self):
        kind=self._sequence_kind
        if kind=="cq": self.tx(self.session.cq_text(),kind="cq",allow_no_target=True)
        elif kind=="report": self._send_report()
        elif kind=="qsl": self.tx(self.session.qsl_text(self.free_b.text()),kind="qsl")
        elif kind=="final": self.tx(self.session.final_text(),kind="final")

    def _send_report(self):
        if not self.session.his_call:
            self.statusBar().showMessage(tr(self.lang,"no_target"),5000); return
        text=self.session.report_text(self.free_a.text()); self.tx(text,kind="report")

    def tx(self,text,kind="text",allow_no_target=False,auto=False):
        if not text: return False
        if not allow_no_target and not self.session.his_call:
            self.statusBar().showMessage(tr(self.lang,"no_target"),5000); return False
        if self._tx_busy or self.radio_busy:
            self.statusBar().showMessage(tr(self.lang,"tx_busy"),5000); return False
        if self.radio is None and not self.allow_disconnected.isChecked():
            self.statusBar().showMessage(tr(self.lang,"tx_need_connection"),8000); return False
        if self.settings_window is not None and self.settings_window._monitor_active:
            self.statusBar().showMessage(tr(self.lang,"monitor_playing"),5000); return False
        data=text.encode("utf-8")
        if len(data)>512:
            self.statusBar().showMessage(tr(self.lang,"tx_too_long"),8000); return False
        self.preview.setPlainText(text)
        self._tx_busy=True; self._tx_stop=threading.Event(); self._tx_auto=auto
        self.spectrum.clear(); self._spectrum_title()
        self.rx_meter.setValue(0); self.sq_state.setStyleSheet("color:#777;")
        self.connect_btn.setEnabled(False); self.sequence_send.setEnabled(False); self.free_btn.setEnabled(False)
        self.sequence_send.setToolTip(tr(self.lang,"tx_busy"))
        self.statusBar().showMessage(tr(self.lang,"tx_starting"),0)
        radio=self.radio; ptt=self.config.get("rig",{}).get("ptt","CI-V")
        device=self.config.get("rig",{}).get("audio_out") or "AUTO"
        stop=self._tx_stop; seq=(int(time.time()*1000)&0xffff)
        typ={"cq":TYPE_CQ,"report":TYPE_REPORT,"qsl":TYPE_QSL,"final":TYPE_FINAL}.get(kind,TYPE_TEXT)
        report_value=self.session._snr_text(self.session.current_rx_snr) if kind=="report" else None
        af_hz=1500  # Fixed TX center; RX AF tracks the received station only.
        def worker():
            keyed=False; success=False; error=""; audio_width=None
            try:
                samples=modulate_profile(self.config.get("tbsk",{}).get("tone_profile"),
                                        af_hz,pack_frame(typ,seq,text))
                audio_width,_,_=audio_occupied_bandwidth(samples)
                if audio_width > AF_OBW_TARGET_HZ:
                    raise RuntimeError(tr(self.lang,"tx_audio_bandwidth_error").format(width=audio_width))
                check_output(device)
                if stop.is_set(): return
                if radio is not None:
                    method=getattr(radio,{"CAT":"set_ptt","CI-V":"set_ptt","RTS":"set_rts","DTR":"set_dtr"}.get(ptt,"set_ptt"))
                    if not method(True): raise RuntimeError("PTT ON failed")
                    keyed=True
                    if stop.wait(.2): return
                success=play_samples(samples,device,stop,
                    on_chunk=lambda chunk:self.tx_data.emit(measure_audio(chunk,SAMPLE_RATE)[0]))
                if keyed and not stop.is_set(): stop.wait(.2)
            except Exception as exc:
                error=str(exc)
            finally:
                if keyed:
                    try:
                        if not method(False): raise RuntimeError("PTT OFF failed")
                    except Exception as exc:
                        success=False; error=f"{error}; {exc}" if error else str(exc)
                self.tx_done.emit(kind,success and not stop.is_set(),error,report_value,audio_width)
        threading.Thread(target=worker,daemon=True).start()
        return True

    def _transmission_completed(self,kind,success,error,report_value,audio_width=None):
        self._tx_busy=False; self.connect_btn.setEnabled(not self.radio_busy)
        self.spectrum.clear(); self._spectrum_title()
        if self._rx_device=="UNSET":
            self.spectrum.notice=tr(self.lang,"select_audio_in"); self.spectrum.update()
        elif not self._rx_active:
            self.spectrum.notice=tr(self.lang,"rx_audio_error"); self.spectrum.update()
        self._refresh_sequence_buttons(); self.free_btn.setEnabled(True)
        self.sequence_send.setToolTip("")
        if success and kind=="report" and report_value is not None:
            self.session.report_sent=report_value; self.sent.setText(report_value)
        message=(f"{tr(self.lang,'audio_error')}: {error}" if error else
                 tr(self.lang,"tx_complete" if success else "tx_stopped"))
        if success and audio_width is not None:
            message += "  " + tr(self.lang,"tx_audio_bandwidth").format(width=audio_width)
        self.statusBar().showMessage(message,10000)
        if self._tx_auto and self.autocq_btn.isChecked():
            if not success:
                self.stop_autocq()
            else:
                self._autocq_sent+=1
                if self._autocq_sent>=self.autocq_count.value(): self.stop_autocq()
                else: self.autocq_timer.start(self.autocq_interval.value()*1000)

    def stop_transmission(self):
        self.stop_autocq()
        if self._tx_busy: self._tx_stop.set()

    def clear_session(self, keep_autocq=False):
        if not keep_autocq: self.stop_autocq()
        self.session=QsoSession(self.config.get("callsign","") or "NOCALL"); self.free_a.clear(); self.free_b.clear(); self.free.clear(); self._preview_source="sequence"; self._refresh_session()

    @staticmethod
    def _band_for_frequency(hz):
        if hz is None: return ""
        for low,high,name in ((1800000,2000000,"160m"),(3500000,4000000,"80m"),
                              (7000000,7300000,"40m"),(10100000,10150000,"30m"),
                              (14000000,14350000,"20m"),(18068000,18168000,"17m"),
                              (21000000,21450000,"15m"),(24890000,24990000,"12m"),
                              (28000000,29700000,"10m"),(50000000,54000000,"6m"),
                              (144000000,148000000,"2m"),(430000000,440000000,"70cm"),
                              (1240000000,1300000000,"23cm")):
            if low<=hz<=high: return name
        return ""

    def offer_qso_log(self):
        session=self.session
        if not session.his_call or session.logged:
            self.statusBar().showMessage(tr(self.lang,"no_target"),6000); return
        if self.qso_log_window is None: self.qso_log_window=QsoLogWindow(self)
        rec=QsoRecord(call=session.his_call,freq_mhz=self.frequency_hz/1e6 if self.frequency_hz else None,
                      band=self._band_for_frequency(self.frequency_hz),mode="TBSK",
                      rst_sent=session.report_sent,rst_rcvd=session.report_rcvd,
                      rx_snr=session.current_rx_snr,af_hz=session.af_hz,
                      qso_time_utc=session.started_utc)
        self.qso_log_window.offer(rec,session)

    def _log_session(self,rec=None,session=None):
        session=session or self.session
        if session.logged: return False
        if rec is None:
            self.offer_qso_log(); return False
        try: append_adif(self.paths.log_file,rec)
        except OSError as exc:
            self.statusBar().showMessage(f"ADIF: {exc}",12000); return False
        session.logged=True; self.statusBar().showMessage(tr(self.lang,"log_written"),10000)
        cfg=self.config.setdefault("backup",{})
        cfg["pending_qsos"]=int(cfg.get("pending_qsos",0))+1
        self.store.save()
        if cfg.get("every_enabled") and cfg["pending_qsos"]>=max(1,int(cfg.get("every_count",30))):
            self.backup_now(manual=False)
        if self.log_window is not None: self.log_window.refresh()
        return True

    def showEvent(self,event):
        super().showEvent(event); apply_windows_caption_color(self)

    def closeEvent(self,event):
        self.radio_poll.stop()
        self._rx_stop.set()
        if self._rx_decoder is not None: self._rx_decoder.close()
        if self._tx_busy: self._tx_stop.set()
        if self.radio_busy or self._tx_busy:
            event.ignore(); QTimer.singleShot(150,self.close); return
        if self.radio is not None:
            try: self.radio.disconnect()
            finally: self.radio=None
        if self.settings_window is not None and self.settings_window._testing:
            self.settings_window.close()
            event.ignore()
            QTimer.singleShot(100,self.close)
            return
        save_window_geometry(self,self.config,"main")
        for w in (self.first_run_window,self.settings_window,self.about_window,self.log_window,self.warning_window,self.control_window,self.update_window,self.qso_log_window):
            if w is not None:
                if w.isVisible(): save_window_geometry(w,self.config,getattr(w,"geometry_key","window"))
                w.close()
        self.store.save()
        if self.config.get("backup",{}).get("on_exit",True): self.backup_now(manual=False)
        event.accept()


def run(base_dir: Path):
    app=QApplication(sys.argv); app.setStyle("Fusion")
    paths=AppPaths(base_dir); paths.ensure()
    lock=QLockFile(str(paths.config_dir / "pstbskx.lock")); lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        if request_activation(base_dir): return 0
        QMessageBox.warning(None,"PSTBSK-X","PSTBSK-Xはすでに起動しています。\nPSTBSK-X is already running from this folder.")
        return 1
    try:
        w=MainWindow(base_dir)
        activation=ActivationServer(base_dir,w)
        w.show()
        report_startup(base_dir)
        result=app.exec()
        activation.server.close()
        return result
    finally:
        lock.unlock()
