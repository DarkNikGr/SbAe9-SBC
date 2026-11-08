# SPDX-License-Identifier: GPL-2.0-only
"""Optical (S/PDIF) and What U Hear: Playback → Digital, Recording → Other Input."""

import os
import unittest

import support as S
from sbcommand import card as C, pages, pipewire


class OpticalOutTest(S.AppTestCase):
    def setUp(self):
        super().setUp()
        self.mixer.add_bool(C.OPTICAL_OUT, True)

    def digital(self):
        pg = self.page(pages.PlaybackPage)
        pg.show_tab(2)
        S.process(20)
        return pg

    def test_lives_on_the_digital_tab(self):
        pg = self.page(pages.PlaybackPage)
        pg.show_tab(0)
        self.assertFalse(pg.optical_box.isVisible())
        pg.show_tab(2)
        self.assertTrue(pg.optical_box.isVisible())
        self.assertFalse(pg.optical_missing.isVisible())

    def test_older_driver_says_what_it_needs(self):
        self.mixer.remove(C.OPTICAL_OUT)
        pg = self.digital()
        self.assertFalse(pg.optical_box.isVisible())
        self.assertIn("v0.8.0", pg.optical_missing.text())
        self.assertTrue(pg.optical_missing.isVisible())

    def test_switch_drives_the_control(self):
        pg = self.digital()
        self.assertTrue(pg.optical.isChecked())
        pg.optical.setChecked(False)
        self.assertFalse(self.card(C.OPTICAL_OUT))
        self.mixer.external(C.OPTICAL_OUT, True)       # alsamixer, the driver
        S.process(20)
        pg.refresh()
        self.assertTrue(pg.optical.isChecked())

    def test_on_off_and_quality(self):
        pg = self.digital()
        self.assertEqual(pg.optical_lbl.text(), "On")
        self.assertEqual(pg.optical_quality.text(), "Nothing playing")
        self.assertIn("Separate output", pg.optical_note.text())
        self.assertEqual(pg.optical_dev.text(), "Optical output not found in PipeWire")
        S.PW.add_optical_out(running=True)
        self.snapshot()
        pg.refresh()
        self.assertEqual(pg.optical_dev.text(), "Sound Blaster AE-9 Optical")
        self.assertEqual(pg.optical_quality.text(), "48 kHz · 24-bit · stereo")
        self.mixer.external(C.OPTICAL_OUT, False)      # off
        S.process(20)
        pg.refresh()
        self.assertEqual(pg.optical_lbl.text(), "Off")
        self.assertIn("Off", pg.optical_note.text())

    def test_optical_sink_is_separate(self):
        S.PW.add_optical_out()
        n = pipewire.Nodes(S.PW.objects)
        self.assertEqual(n.optical_out["name"], "alsa_output.ae9_optical")
        self.assertNotEqual(n.sink["name"], "alsa_output.ae9_optical")


class OtherInputTest(S.AppTestCase):
    def other(self):
        self.snapshot()
        pg = self.page(pages.RecordingPage)
        pg.show_tab(1)
        S.process(20)
        return pg, {sec.key: sec for sec in pg.inputs}

    def test_never_taken_for_the_mic(self):
        S.PW.add_optical_in(first=True, alsa_props=True)
        S.PW.add_what_u_hear(first=True, alsa_props=True)
        n = pipewire.Nodes(S.PW.objects)
        self.assertEqual(n.optical_in["name"], "alsa_input.ae9_optical")
        self.assertEqual(n.what_u_hear["name"], "alsa_input.ae9_what_u_hear")
        self.assertNotIn(n.source["name"], ("alsa_input.ae9_optical", "alsa_input.ae9_what_u_hear"))

    def test_both_listed_with_set_default(self):
        S.PW.add_optical_in()
        S.PW.add_what_u_hear()
        pg, secs = self.other()
        for key, name, node_id in (("optical_in", "AE-9 Optical In", "999"),
                                   ("what_u_hear", "AE-9 What U Hear", "998")):
            sec = secs[key]
            self.assertTrue(sec.isVisible(), key)
            self.assertEqual(sec.name.text(), name)
            S.PW.calls.clear()
            sec.set_default.click()
            self.assertTrue(any(c[:2] == ("wpctl", "set-default") and c[2] == node_id
                                for c in S.PW.calls), key)
        self.assertFalse(pg.other_none.isVisible())

    def test_setup_hint_when_pipewire_lacks_it(self):
        S.PCMS.update({1, 2})
        pg, secs = self.other()
        self.assertIn("ae9-optical-in.conf", secs["optical_in"].note.text())
        self.assertIn("ae9-what-u-hear.conf", secs["what_u_hear"].note.text())
        self.assertFalse(secs["what_u_hear"].set_default.isVisible())

    def test_rear_rca_listed_with_set_default(self):
        S.PW.add_rear_rca(alsa_props=True)
        n = pipewire.Nodes(S.PW.objects)
        self.assertEqual(n.rear_rca["name"], "alsa_input.ae9_rear_rca")
        self.assertNotEqual(n.source["name"], "alsa_input.ae9_rear_rca")   # never taken for the mic
        pg, secs = self.other()
        sec = secs["rear_rca"]
        self.assertTrue(sec.isVisible())
        self.assertEqual(sec.name.text(), "AE-9 Rear RCA In")
        S.PW.calls.clear()
        sec.set_default.click()
        self.assertTrue(any(c[:2] == ("wpctl", "set-default") and c[2] == "997" for c in S.PW.calls))

    def test_rear_rca_setup_hint(self):
        S.PCMS.update({3})
        pg, secs = self.other()
        self.assertTrue(secs["rear_rca"].isVisible())
        self.assertIn("ae9-rear-rca-in.conf", secs["rear_rca"].note.text())
        self.assertFalse(secs["optical_in"].isVisible())

    def test_nothing_on_an_older_driver(self):
        pg, secs = self.other()
        self.assertFalse(any(s.isVisible() for s in secs.values()))
        self.assertTrue(pg.other_none.isVisible())


WUH_CONF = """# AE-9 What U Hear (copy of the driver's config)
# 48 or 96 kHz (driver 0.9.5+; set audio.rate = 96000 below for 96 kHz).
context.objects = [
    { factory = adapter
        args = {
            factory.name     = api.alsa.pcm.source
            node.name        = "alsa_input.ae9_what_u_hear"
            api.alsa.path    = "hw:AE9,2"
            audio.rate       = 48000
            audio.channels   = 2
        }
    }
]
"""


class WhatUHearRateTest(S.AppTestCase):
    def setUp(self):
        super().setUp()
        os.makedirs(pipewire.PW_CONF_DIR, exist_ok=True)
        self.path = os.path.join(pipewire.PW_CONF_DIR, "ae9-what-u-hear.conf")
        with open(self.path, "w") as f:
            f.write(WUH_CONF)
        self.addCleanup(os.remove, self.path)
        S.PARAMS["wuh_96k"] = "Y"
        S.PW.add_what_u_hear()
        self.answer = True
        old = pages.confirm_pipewire_restart
        pages.confirm_pipewire_restart = lambda parent, what: self.answer
        self.addCleanup(setattr, pages, "confirm_pipewire_restart", old)

    def section(self):
        self.snapshot()
        pg = self.page(pages.RecordingPage)
        pg.show_tab(1)
        S.process(20)
        return {sec.key: sec for sec in pg.inputs}["what_u_hear"]

    def pick(self, sec, rate):
        sec._pick_rate(sec.rate.findData(rate))
        self.settle()

    def test_finds_the_config_and_shows_its_rate(self):
        sec = self.section()
        self.assertTrue(sec.rate_row.isVisible())
        self.assertEqual(sec.conf_path, self.path)
        self.assertEqual(sec.rate.currentData(), 48000)
        self.assertTrue(sec.rate.isEnabled())

    def test_96_rewrites_audio_rate_only_and_restarts_pipewire(self):
        sec = self.section()
        S.PW.calls.clear()
        self.pick(sec, 96000)
        with open(self.path) as f:
            text = f.read()
        self.assertIn("audio.rate       = 96000", text)
        self.assertIn("set audio.rate = 96000 below", text)      # the comment is left alone
        self.assertEqual(text.replace("= 96000\n", "= 48000\n", 1), WUH_CONF)
        self.assertIn(("systemctl", "--user", "restart", "pipewire"), S.PW.calls)

    def test_cancel_changes_nothing(self):
        self.answer = False
        sec = self.section()
        S.PW.calls.clear()
        self.pick(sec, 96000)
        self.assertEqual(pipewire.input_conf_rate(self.path), 48000)
        self.assertNotIn(("systemctl", "--user", "restart", "pipewire"), S.PW.calls)
        self.assertEqual(sec.rate.currentData(), 48000)

    def test_older_driver_offers_48_only(self):
        del S.PARAMS["wuh_96k"]
        sec = self.section()
        self.assertFalse(sec.rate.isEnabled())
        self.assertFalse(sec.rate.model().item(sec.rate.findData(96000)).isEnabled())

    def test_config_elsewhere_greys_it_out(self):
        os.remove(self.path)
        self.addCleanup(open(self.path, "w").close)               # for the cleanup's remove
        sec = self.section()
        self.assertTrue(sec.rate_row.isVisible())
        self.assertFalse(sec.rate.isEnabled())
        self.assertIn("ae9-what-u-hear.conf", sec.rate.toolTip())

    def test_optical_in_has_no_rate_row(self):
        S.PW.add_optical_in()
        self.snapshot()
        pg = self.page(pages.RecordingPage)
        pg.show_tab(1)
        S.process(20)
        self.assertFalse({s.key: s for s in pg.inputs}["optical_in"].rate_row.isVisible())


if __name__ == "__main__":
    unittest.main()


OPT_CONF = """# AE-9 optical out (copy of the driver's config)
context.objects = [
    { factory = adapter
        args = {
            factory.name     = api.alsa.pcm.sink
            node.name        = "alsa_output.ae9_optical"
            api.alsa.path    = "hw:AE9,4"
            audio.format     = "S32LE"
            audio.rate       = 96000
            audio.channels   = 2
        }
    }
]
"""


class OpticalOutRateTest(S.AppTestCase):
    """The Digital tab's optical output has its own sample rate.

    It's a separate PCM, so it can run at a rate of its own (audio.rate in its
    PipeWire config); Automatic removes the line and follows the card."""

    def setUp(self):
        super().setUp()
        self.mixer.add_bool(C.OPTICAL_OUT, True)
        S.PW.add_optical_out(running=True)
        os.makedirs(pipewire.PW_CONF_DIR, exist_ok=True)
        self.path = os.path.join(pipewire.PW_CONF_DIR, "ae9-optical-out.conf")
        with open(self.path, "w") as f:
            f.write(OPT_CONF)
        self.addCleanup(os.remove, self.path)
        self.answer = True
        old = pages.confirm_pipewire_restart
        pages.confirm_pipewire_restart = lambda parent, what: self.answer
        self.addCleanup(setattr, pages, "confirm_pipewire_restart", old)

    def digital(self):
        pg = self.page(pages.PlaybackPage)
        pg.show_tab(2)
        S.process(20)
        pg.refresh()
        return pg

    def pick(self, pg, rate):
        pg._pick_optical_rate(pg.optical_rate.findData(rate))
        self.settle()

    def test_shows_the_configs_rate(self):
        pg = self.digital()
        self.assertEqual(pg.optical_conf, self.path)
        self.assertEqual(pg.optical_rate.itemText(0), "Automatic")
        self.assertEqual(pg.optical_rate.currentData(), 96000)
        self.assertTrue(pg.optical_rate.isEnabled())
        self.assertEqual([pg.optical_rate.itemData(i) for i in range(1, pg.optical_rate.count())],
                         list(pages.OPTICAL_RATES))

    def test_fixed_rate_rewrites_audio_rate_and_restarts_pipewire(self):
        pg = self.digital()
        S.PW.calls.clear()
        self.pick(pg, 48000)
        with open(self.path) as f:
            text = f.read()
        self.assertIn("audio.rate       = 48000", text)
        self.assertIn("copy of the driver's config", text)       # comments untouched
        self.assertEqual(text.replace("= 48000\n", "= 96000\n", 1), OPT_CONF)
        self.assertIn(("systemctl", "--user", "restart", "pipewire"), S.PW.calls)
        self.assertEqual(pg.optical_rate.currentData(), 48000)

    def test_automatic_removes_the_line(self):
        pg = self.digital()
        S.PW.calls.clear()
        self.pick(pg, 0)
        with open(self.path) as f:
            text = f.read()
        self.assertNotIn("audio.rate", text)
        self.assertIn(("systemctl", "--user", "restart", "pipewire"), S.PW.calls)
        self.assertEqual(pg.optical_rate.currentData(), 0)

    def test_cancel_changes_nothing(self):
        self.answer = False
        pg = self.digital()
        S.PW.calls.clear()
        self.pick(pg, 48000)
        self.assertEqual(pipewire.input_conf_rate(self.path), 96000)
        self.assertNotIn(("systemctl", "--user", "restart", "pipewire"), S.PW.calls)
        self.assertEqual(pg.optical_rate.currentData(), 96000)

    def test_no_config_greys_it_out(self):
        os.remove(self.path)
        self.addCleanup(open(self.path, "w").close)
        pg = self.digital()
        self.assertFalse(pg.optical_rate.isEnabled())
        self.assertIn("ae9-optical-out.conf", pg.optical_rate.toolTip())
        self.assertFalse(pg.optical_depth.isEnabled())
        self.assertIn("ae9-optical-out.conf", pg.optical_depth.toolTip())

    # -- bit depth ---------------------------------------------------------

    def depth(self, pg, fmt):
        pg._pick_optical_depth(pg.optical_depth.findData(fmt))
        self.settle()

    def test_depth_shows_the_configs_format(self):
        pg = self.digital()
        self.assertEqual(pg.optical_depth.itemText(0), "Automatic")
        self.assertEqual([pg.optical_depth.itemData(i) for i in range(pg.optical_depth.count())],
                         [None, "S32LE", "S16LE"])
        self.assertEqual(pg.optical_depth.currentData(), "S32LE")      # 24-bit
        self.assertTrue(pg.optical_depth.isEnabled())
        self.assertIn("16-bit", pg.optical_depth.toolTip())

    def test_16bit_writes_s16le(self):
        pg = self.digital()
        S.PW.calls.clear()
        self.depth(pg, "S16LE")
        with open(self.path) as f:
            text = f.read()
        self.assertIn('audio.format     = "S16LE"', text)
        self.assertEqual(text.replace("S16LE", "S32LE", 1), OPT_CONF)
        self.assertIn(("systemctl", "--user", "restart", "pipewire"), S.PW.calls)
        self.assertEqual(pg.optical_depth.currentData(), "S16LE")

    def test_automatic_depth_removes_the_line(self):
        pg = self.digital()
        self.depth(pg, None)
        with open(self.path) as f:
            text = f.read()
        self.assertNotIn("audio.format", text)
        self.assertEqual(pg.optical_depth.currentData(), None)
        self.assertIn("audio.rate       = 96000", text)                # the rate stays
