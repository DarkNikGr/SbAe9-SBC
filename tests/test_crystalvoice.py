# SPDX-License-Identifier: GPL-2.0-only
"""Recording → Microphone: CrystalVoice, the DSP's mic input effects."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support as S

from sbae9kit import mixer as alsa

from sbcommand import card as C, pages


class CrystalVoiceTest(S.AppTestCase):
    def setUp(self):
        super().setUp()
        for name, on in ((C.CRYSTALVOICE, False), (C.CV_NR, True), (C.CV_EC, False),
                         (C.CV_VF, False), (C.CV_SVM, False), (C.CV_VFX, False)):
            self.mixer.add_bool(name, on)
        for name, value in ((C.CV_NR_VOL, 50), (C.CV_SVM_VOL, 74)):
            self.mixer._add(name, value, type=alsa.TYPE_INTEGER, min=0, max=100, items=[])
        self.snapshot()

    def rec(self):
        self.snapshot()
        pg = self.page(pages.RecordingPage)
        S.process(20)
        pg.refresh()
        return pg

    def test_box_and_values(self):
        pg = self.rec()
        self.assertTrue(pg.cv_box.isVisible())
        self.assertFalse(pg.cv.isChecked())
        self.assertEqual(pg.cv_lbl.text(), "Off")
        self.assertTrue(pg.cv_switches["nr"].isChecked())
        self.assertFalse(pg.cv_switches["ec"].isChecked())
        self.assertEqual(pg.cv_sliders["nr"][1].text(), "50%")
        self.assertEqual(pg.cv_sliders["svm"][1].text(), "74%")

    def test_switches_drive_the_controls(self):
        pg = self.rec()
        S.PW.calls.clear()
        pg.cv.setChecked(True)
        self.assertTrue(self.card(C.CRYSTALVOICE))
        pg.cv_switches["ec"].setChecked(True)
        self.assertTrue(self.card(C.CV_EC))
        pg.cv_switches["nr"].setChecked(False)
        self.assertFalse(self.card(C.CV_NR))

    def test_sliders_drive_the_volumes(self):
        pg = self.rec()
        sl, val = pg.cv_sliders["nr"]
        sl.setValue(70)
        self.assertEqual(self.card(C.CV_NR_VOL), 70)
        self.assertEqual(val.text(), "70%")
        sl, _ = pg.cv_sliders["svm"]
        sl.setValue(90)
        self.assertEqual(self.card(C.CV_SVM_VOL), 90)

    def test_changes_elsewhere_show(self):
        pg = self.rec()
        self.mixer.external(C.CRYSTALVOICE, True)
        self.mixer.external(C.CV_VF, True)
        self.mixer.external(C.CV_NR_VOL, 20)
        S.process(20)
        pg.refresh()
        self.assertTrue(pg.cv.isChecked())
        self.assertEqual(pg.cv_lbl.text(), "On")
        self.assertTrue(pg.cv_switches["vf"].isChecked())
        self.assertEqual(pg.cv_sliders["nr"][1].text(), "20%")

    def test_older_driver_hides_it(self):
        for name in (C.CRYSTALVOICE, C.CV_NR, C.CV_NR_VOL, C.CV_EC, C.CV_VF,
                     C.CV_SVM, C.CV_SVM_VOL, C.CV_VFX):
            self.mixer.remove(name)
        pg = self.rec()
        self.assertFalse(pg.cv_box.isVisible())


if __name__ == "__main__":
    unittest.main()
