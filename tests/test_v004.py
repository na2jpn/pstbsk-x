import os
import tempfile
import unittest
from pathlib import Path

from pstbskx.adif import _f
from pstbskx.geometry import clamp_window_rect
from pstbskx.storage import AppPaths, ConfigStore, backup_log


class V004CoreTests(unittest.TestCase):
    def test_narrow_screen_fits_and_removed_monitor_recenters(self):
        area = (0, 0, 800, 600)
        self.assertEqual(clamp_window_rect(None, [area], (1280,800), (320,240)), area)
        self.assertEqual(clamp_window_rect((2500,100,1280,800), [area], (1280,800), (320,240)), area)

    def test_adi_unicode_length_is_utf8_bytes(self):
        self.assertEqual(_f("COMMENT", "草加"), "<COMMENT:6>草加")

    def test_manual_and_count_backup_preserve_latest_ten(self):
        with tempfile.TemporaryDirectory() as td:
            paths=AppPaths(Path(td)); paths.ensure()
            store=ConfigStore(paths); store.load()
            store.data["backup"].update(every_enabled=True,every_count=3)
            store.save()
            self.assertEqual(ConfigStore(paths).load()["backup"]["every_count"],3)
            paths.log_file.write_text("ADIF",encoding="utf-8")
            for n in range(11):
                paths.log_file.write_text(f"ADIF {n}",encoding="utf-8")
                backup_log(paths)
            backups=list(paths.bak_dir.glob("tbskx_*.adi"))
            self.assertEqual(len(backups),10)
            self.assertFalse(list(paths.bak_dir.glob("*.tmp")))


class V004UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_main_resizes_without_qso_decode_overlap(self):
        from pstbskx.app import MainWindow
        with tempfile.TemporaryDirectory() as td:
            window=MainWindow(Path(td)); window.resize(1280,800); window.show()
            self.app.processEvents()
            left=window.decode_group.mapToGlobal(window.decode_group.rect().topLeft()).x()
            left_end=left+window.decode_group.width()
            right=window.qso_group.mapToGlobal(window.qso_group.rect().topLeft()).x()
            self.assertLessEqual(left_end,right)
            self.assertEqual(window.cq_btn.accessibleName(), window.session.cq_text())
            window.show_settings(); self.app.processEvents()
            self.assertEqual(window.settings_window.nav.count(),6)
            window.close()


if __name__=="__main__": unittest.main()
