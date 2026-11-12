import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pstbskx import updater
from pstbskx.geometry import clamp_window_rect


class UpdateTests(unittest.TestCase):
    def release_with_common_licenses(self):
        source=Path(__file__).resolve().parents[1]
        for name in updater.COMMON_LICENSES:
            (self.release/name).write_bytes((source/Path(name).name).read_bytes())
        info=updater.create_manifest(self.release,"0.05")
        with zipfile.ZipFile(self.zip,"w") as z:
            for name in (*info['files'],updater.MANIFEST):z.write(self.release/name,name)

    def test_common_licenses_are_installed_without_changing_user_data(self):
        self.release_with_common_licenses()
        stage=updater.prepare_update(self.zip,self.root,"0.04")
        updater.apply_update(stage,self.root,"0.04")
        for name in updater.COMMON_LICENSES:
            self.assertEqual((self.root/name).read_bytes(),(self.release/name).read_bytes())
        self.assertEqual((self.root/"log/tbskx.adi").read_text(),"<CALL:6>JA1ABC<EOR>")
        self.assertEqual((self.root/"config/config.json").read_text(),'{"callsign":"JH1HST"}')

    def test_common_license_failure_removes_new_files_on_rollback(self):
        self.release_with_common_licenses()
        stage=updater.prepare_update(self.zip,self.root,"0.04")
        original=updater._atomic_copy
        def fail_manifest(src,dst):
            if src==stage/"payload"/updater.MANIFEST:raise OSError("injected failure")
            return original(src,dst)
        with patch.object(updater,"_atomic_copy",side_effect=fail_manifest):
            with self.assertRaisesRegex(RuntimeError,"旧版に復元済み"):
                updater.apply_update(stage,self.root,"0.04")
        for name in updater.COMMON_LICENSES:self.assertFalse((self.root/name).exists())
        self.assertEqual((self.root/updater.EXE).read_bytes(),b"MZ-old")
        self.assertEqual((self.root/"log/tbskx.adi").read_text(),"<CALL:6>JA1ABC<EOR>")

    def test_incomplete_common_license_pair_is_rejected(self):
        name=updater.COMMON_LICENSES[0]
        (self.release/name).write_text('incomplete pair',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,"2ファイル"):
            updater.create_manifest(self.release,"0.05")

    def test_common_license_tamper_is_rejected(self):
        self.release_with_common_licenses()
        altered=Path(self.tmp.name)/"altered.zip"
        with zipfile.ZipFile(self.zip) as src,zipfile.ZipFile(altered,"w") as dst:
            for name in src.namelist():
                dst.writestr(name,b'altered terms' if name==updater.COMMON_LICENSES[0] else src.read(name))
        with self.assertRaisesRegex(ValueError,"ハッシュ"):
            updater.inspect_zip(altered,"0.04",self.root)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"installed"; self.root.mkdir()
        for name in ("config","log","bak","licenses"): (self.root/name).mkdir()
        (self.root/updater.EXE).write_bytes(b"MZ-old")
        (self.root/updater.LICENSE).write_bytes(b"MIT license")
        updater.create_manifest(self.root,"0.04")
        (self.root/"log/tbskx.adi").write_text("<CALL:6>JA1ABC<EOR>",encoding="utf-8")
        (self.root/"config/config.json").write_text('{"callsign":"JH1HST"}',encoding="utf-8")
        self.release=Path(self.tmp.name)/"release"
        for name in ("config","log","bak","licenses"): (self.release/name).mkdir(parents=True)
        (self.release/updater.EXE).write_bytes(b"MZ-new")
        (self.release/updater.LICENSE).write_bytes(b"MIT license")
        updater.create_manifest(self.release,"0.05")
        self.zip=Path(self.tmp.name)/"PSTBSK-X_0.05_win64.zip"
        with zipfile.ZipFile(self.zip,"w") as z:
            for name in (*updater.FILES,updater.MANIFEST): z.write(self.release/name,name)
            for name in ("config/","log/","bak/","licenses/"): z.writestr(name,b"")

    def test_update_preserves_data_and_makes_snapshot(self):
        stage=updater.prepare_update(self.zip,self.root,"0.04")
        backup=updater.apply_update(stage,self.root,"0.04")
        self.assertEqual((self.root/updater.EXE).read_bytes(),b"MZ-new")
        self.assertEqual((self.root/"log/tbskx.adi").read_text(),"<CALL:6>JA1ABC<EOR>")
        self.assertEqual((self.root/"config/config.json").read_text(),'{"callsign":"JH1HST"}')
        self.assertEqual((backup/updater.EXE).read_bytes(),b"MZ-old")
        self.assertTrue((backup/"log/tbskx.adi").exists())
        with self.assertRaisesRegex(ValueError,"同じ内容"): updater.inspect_zip(self.zip,"0.05",self.root)

    def test_rejects_unsafe_and_source_zip(self):
        with zipfile.ZipFile(self.zip,"a") as z: z.writestr("../config/config.json",b"damage")
        with self.assertRaisesRegex(ValueError,"危険なZIPパス"): updater.inspect_zip(self.zip,"0.04",self.root)
        source=Path(self.tmp.name)/"source.zip"
        with zipfile.ZipFile(source,"w") as z: z.writestr("main.py",b"code")
        with self.assertRaises(ValueError): updater.inspect_zip(source,"0.04",self.root)

    def test_failure_restores_old_exe_and_keeps_log(self):
        stage=updater.prepare_update(self.zip,self.root,"0.04")
        original=updater._atomic_copy
        def fail_manifest(src,dst):
            if src==stage/"payload"/updater.MANIFEST: raise OSError("injected failure")
            return original(src,dst)
        with patch.object(updater,"_atomic_copy",side_effect=fail_manifest):
            with self.assertRaisesRegex(RuntimeError,"旧版に復元済み"): updater.apply_update(stage,self.root,"0.04")
        self.assertEqual((self.root/updater.EXE).read_bytes(),b"MZ-old")
        self.assertEqual((self.root/"log/tbskx.adi").read_text(),"<CALL:6>JA1ABC<EOR>")


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_default_layout_and_autocq_repeat_count(self):
        from pstbskx.app import MainWindow
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.show(); w.resize(1280,800); self.app.processEvents()
            self.assertEqual(w.right_scroll.verticalScrollBar().maximum(),0)
            self.assertEqual(w.autocq_count.value(),10)
            self.assertEqual(w.a_reset.text(),"ウィンドウサイズ・位置をリセット")
            w.free.setText("自由文"); w.clear_btn.click(); self.assertEqual(w.free.text(),"")
            w.autocq_count.setValue(2)
            w.allow_disconnected.setChecked(True)
            with patch.object(w,"tx",return_value=True) as queued:
                w.autocq_btn.click()
                self.assertEqual(w._autocq_sent,0)  # count only a completed output
                self.assertTrue(w.autocq_btn.isChecked())
                w._tx_auto=True; w._transmission_completed("cq",True,"",None)
                self.assertEqual(w._autocq_sent,1)
                w._autocq_tick()
                w._transmission_completed("cq",True,"",None)
                self.assertEqual(w._autocq_sent,2)
                self.assertEqual(queued.call_count,2)
            self.assertFalse(w.autocq_btn.isChecked())
            w.close()

    def test_partly_offscreen_recenters(self):
        self.assertEqual(clamp_window_rect((1800,50,1280,800),[(0,0,1920,1040)],(1280,800)),(320,120,1280,800))


if __name__=="__main__": unittest.main()
