# SPDX-License-Identifier: GPL-2.0-only
"""Test harness: a fake AE-9 mixer and a fake PipeWire, so the tests never
touch the real card, the real PipeWire or the user's settings.

Importing this module:
  - points XDG_CONFIG_HOME / XDG_CACHE_HOME at a temp folder,
  - runs Qt offscreen,
  - replaces the ALSA card with the shared FakeMixer (sbae9kit.testing.mixer,
    built from a snapshot of a real AE-9's controls on driver 0.6.8),
  - replaces every PipeWire command with FakePipeWire below (built from the
    shared pw_ae9_stereo.json, a trimmed pw-dump of the same machine),
  - makes any real subprocess or QProcess start fail the test.
"""

import copy
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(ROOT, "sbae9kit", "testing", "fixtures")   # shared with SbAe9-AudioMon

_TMP = tempfile.mkdtemp(prefix="sbae9-sbc-tests-")
import atexit  # noqa: E402
atexit.register(shutil.rmtree, _TMP, True)
os.environ["XDG_CONFIG_HOME"] = os.path.join(_TMP, "config")
os.environ["XDG_CACHE_HOME"] = os.path.join(_TMP, "cache")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication, QEvent, QProcess, Qt  # noqa: E402,F401
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from sbcommand import alsa, applier, config, pipewire  # noqa: E402
from sbcommand import card as C  # noqa: E402

applier.TIME_SCALE = 0.01   # 4 s settle waits become 40 ms

STEREO = "output:analog-stereo+input:analog-stereo"
SURROUND = "output:analog-surround-51+input:analog-stereo"
NEW_EQ_ORDER = ["Acoustic", "Cinema", "Classical", "Concert", "Country", "Dance", "Flat", "Gaming",
                "Hip Hop", "Jazz", "Night", "Pop", "R&B", "Rock", "Stadium", "Vocal",
                "Project CARS", "Racing", "Rocket League", "RPG"]
OLD_EQ_ORDER = ["Flat", "Rock", "Concert", "Night", "Acoustic", "Classical", "Country", "Dance",
                "Hip Hop", "Jazz", "Pop", "R&B", "Vocal", "Gaming", "Cinema", "Project CARS",
                "Racing", "Rocket League", "RPG", "Stadium"]


def fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


# --- fake ALSA mixer ---------------------------------------------------------------
# The shared one, from sbae9kit.testing (starts from the real card's controls).
from sbae9kit.testing.mixer import FakeMixer  # noqa: E402


# --- fake PipeWire ---------------------------------------------------------------------
class FakePipeWire:
    """Answers the PipeWire commands the app runs and records every write."""

    def __init__(self):
        self.objects = fixture("pw_ae9_stereo.json")
        self.settings = {"clock.force-rate": "0", "clock.force-quantum": "0",
                         "clock.allowed-rates": "[ 48000 96000 192000 384000 ]"}
        self.calls = []          # every command that changes something
        self.processes = []      # QProcess starts: (program, args)
        self.stream = None       # (rate, channels) in /proc hw_params, None = closed
        self.capture = None      # same, for the mic / line-in capture

    # object lookup
    def _obj(self, cls):
        for o in self.objects:
            if (o.get("info") or {}).get("props", {}).get("media.class") == cls:
                return o
        return None

    @property
    def device(self):
        return self._obj("Audio/Device")

    @property
    def sink(self):
        return self._obj("Audio/Sink")

    def profile(self):
        return self.device["info"]["params"]["Profile"][0]["name"]

    def set_profile(self, name):
        """What WirePlumber does on a profile switch: new profile, and the sink
        comes back with the matching channel layout."""
        dev = self.device["info"]
        idx = next(p["index"] for p in dev["params"]["EnumProfile"] if p["name"] == name)
        dev["params"]["Profile"] = [{"index": idx, "name": name}]
        surround = "surround-51" in name
        chmap = ["FL", "FR", "FC", "LFE", "RL", "RR"] if surround else ["FL", "FR"]
        sink = self.sink["info"]
        old_name = sink["props"]["node.name"]
        sink["props"]["node.name"] = re.sub(
            r"\.(analog-stereo|analog-surround-51)$", ".analog-surround-51" if surround else ".analog-stereo",
            sink["props"]["node.name"])
        sink["props"]["card.profile.device"] = 2 if surround else 1
        for o in self.objects:      # the default output follows, as WirePlumber does
            for m in o.get("metadata", []):
                v = m.get("value")
                if m.get("key") == "default.audio.sink" and isinstance(v, dict) and v.get("name") == old_name:
                    v["name"] = sink["props"]["node.name"]
        for p in sink["params"].get("Props", []):
            if "channelVolumes" in p:
                level = max(p["channelVolumes"])
                p["channelVolumes"] = [level] * len(chmap)
                p["channelMap"] = list(chmap)
        routes = dev["params"].setdefault("Route", [])
        for r in routes:
            if r.get("direction") == "Output":
                r["device"] = 2 if surround else 1
                r["index"] = 2 if surround else 1

    def add_optical_out(self, node_id=997, running=False):
        """The separate optical sink node from the driver's ae9-optical-out.conf."""
        props = {"node.name": "alsa_output.ae9_optical", "node.description": "Sound Blaster AE-9 Optical",
                 "media.class": "Audio/Sink", "api.alsa.path": "hw:AE9,3", "priority.session": 2000}
        state = "running" if running else "suspended"
        params = {"Format": [{"rate": 48000, "format": "S32LE"}]} if running else {}
        o = {"id": node_id, "type": "PipeWire:Interface:Node",
             "info": {"state": state, "props": props, "params": params}}
        self.objects.insert(len(self.objects), o)
        return o

    def add_optical_in(self, first=True, alsa_props=False):
        """The source node from the driver's ae9-optical-in.conf. alsa_props:
        the card props an opened node carries (they'd match the mic's)."""
        return self.add_input("alsa_input.ae9_optical", "AE-9 Optical In", 1, 999, first, alsa_props)

    def add_what_u_hear(self, first=False, alsa_props=False):
        return self.add_input("alsa_input.ae9_what_u_hear", "AE-9 What U Hear", 2, 998, first, alsa_props)

    def add_rear_rca(self, first=False, alsa_props=False):
        return self.add_input("alsa_input.ae9_rear_rca", "AE-9 Rear RCA In", 3, 997, first, alsa_props)

    def add_input(self, name, desc, dev, node_id, first, alsa_props):
        props = {"node.name": name, "node.description": desc, "media.class": "Audio/Source",
                 "api.alsa.path": f"hw:AE9,{dev}", "priority.session": 100}
        if alsa_props:
            props.update({"alsa.id": "AE9", "alsa.card_name": "Sound Blaster AE-9"})
        o = {"id": node_id, "type": "PipeWire:Interface:Node", "info": {"state": "suspended",
                                                                  "props": props, "params": {}}}
        self.objects.insert(0 if first else len(self.objects), o)
        return o

    @property
    def source(self):
        return self._obj("Audio/Source")

    def set_mic_range(self, top):
        """The rates the driver's capture offers (48 kHz only before 0.9.1)."""
        self.source["info"]["params"]["EnumFormat"] = [
            {"format": "S32LE", "rate": {"default": 48000, "min": 48000, "max": top}, "channels": 2}]

    def channel_volumes(self):
        for p in self.sink["info"]["params"].get("Props", []):
            if "channelVolumes" in p:
                return p["channelVolumes"]
        return None

    # command dispatcher (replaces pipewire._run)
    def run(self, *args, **_):
        prog = args[0]
        if prog == "pw-dump":
            return json.dumps(self.objects)
        if prog == "pw-metadata" and len(args) == 4:
            return "".join(f"update: id:0 key:'{k}' value:'{v}' type:''\n" for k, v in self.settings.items())
        if prog == "pw-metadata" and len(args) == 6:
            self.settings[args[4]] = args[5]
            self.calls.append(args)
            return ""
        if prog == "pw-cli" and len(args) >= 5 and args[1] == "set-param":
            self.calls.append(args)
            what, body = args[3], args[4]
            if what == "Profile":
                idx = int(re.search(r"index:\s*(\d+)", body).group(1))
                name = next(p["name"] for p in self.device["info"]["params"]["EnumProfile"]
                            if p["index"] == idx)
                self.set_profile(name)
            elif what == "Route":
                vols = [float(x) for x in re.search(r"channelVolumes:\s*\[([^\]]*)\]", body).group(1).split()]
                for p in self.sink["info"]["params"].get("Props", []):
                    if "channelVolumes" in p:
                        p["channelVolumes"] = vols
            return ""
        if prog == "wpctl" and args[1:2] == ("get-volume",):
            return "Volume: 1.00\n"
        self.calls.append(args)
        return ""


# --- install the fakes -------------------------------------------------------------------
PW = FakePipeWire()
PARAMS = {}


def _no_subprocess(*a, **k):
    raise AssertionError(f"a test tried to run a real command: {a}")


def _qprocess_start(self, program, args=(), *rest):
    PW.processes.append((program, list(args)))


alsa.find_card = lambda *hints: 0
alsa.card_longname = lambda idx: "Creative Labs Sound Blaster AE-9 (fake)"
alsa.Mixer = FakeMixer
pipewire._run = lambda *a, **k: PW.run(*a, **k)
pipewire.card_stream = lambda card_id="AE9": PW.stream
pipewire.capture_stream = lambda card_id="AE9": PW.capture
pipewire.RATES_CONF = os.path.join(_TMP, "pipewire", "90-sbae9-sbc-rates.conf")
pipewire.MIC_CONF = os.path.join(_TMP, "wireplumber", "91-sbae9-sbc-mic.conf")
pipewire.PW_CONF_DIR = os.path.join(_TMP, "pipewire")
C.HP_DIRS = (os.path.join(_TMP, "firmware"),)   # headphone curves; tests add them
C.module_param = lambda name: PARAMS.get(name)
C.module_version = lambda: PARAMS.get("version")
PCMS = set()   # extra capture devices the fake driver has (1 = optical in, 2 = What U Hear)
C.has_capture_pcm = lambda device, card_id="AE9": device in PCMS
import subprocess  # noqa: E402
subprocess.run = _no_subprocess
subprocess.Popen = _no_subprocess
QProcess.start = _qprocess_start


def _sync_refresh(self):
    """Watcher.refresh, but synchronous from the fake pw-dump."""
    self.nodes = pipewire.Nodes(json.loads(PW.run("pw-dump")))
    self.updated.emit(self.nodes)


pipewire.Watcher.refresh = _sync_refresh


def reset():
    """Fresh fake PipeWire, driver options and settings for a new test."""
    global PW
    PW.__init__()
    PARAMS.clear()
    PCMS.clear()
    PARAMS.update({"pcm_rates": "1", "pcm_bits": "24", "surround": "1", "surround_96k": "0",
                   "version": "0.6.8"})
    shutil.rmtree(os.environ["XDG_CONFIG_HOME"], ignore_errors=True)
    shutil.rmtree(C.HP_DIRS[0], ignore_errors=True)
    for f in (pipewire.RATES_CONF, pipewire.MIC_CONF):
        if os.path.exists(f):
            os.remove(f)


def process(ms=0):
    """Run the Qt event loop for about `ms` milliseconds."""
    end = time.monotonic() + ms / 1000
    while True:
        app.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.002)


def wait_until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.002)
    return pred()


class AppTestCase(unittest.TestCase):
    """Fresh fakes per test, plus a Context (the app's shared state)."""

    def setUp(self):
        reset()
        from sbcommand.window import Context
        self.ctx = Context()
        self.mixer = FakeMixer.last
        process()
        self.mixer.writes.clear()
        PW.calls.clear()

    def tearDown(self):
        for w in getattr(self, "_windows", []):
            w.close()
            w.deleteLater()
        # Stop this test's app before the next one starts: its PipeWire poll
        # would otherwise keep running and re-write the shared fake's rate.
        self.ctx.pw._timer.stop()
        self.ctx.applier._poll.stop()
        self.ctx.deleteLater()
        process()
        # deleteLater only runs inside a real event loop; tests never enter one
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    # helpers
    def window(self):
        from sbcommand.window import MainWindow
        w = MainWindow(self.ctx)
        w.resize(1180, 760)
        w.show()
        process()
        self._windows = getattr(self, "_windows", []) + [w]
        return w

    def page(self, cls):
        """A page, shown (pages only fill themselves in while visible)."""
        w = self.window()
        pg = next(p for p in w.findChildren(cls))
        w.go(next(i for i in range(w.stack.count()) if pg in w.stack.widget(i).findChildren(cls)
                  or w.stack.widget(i) is pg))
        process()
        pg.refresh()
        return pg

    def snapshot(self):
        """A PipeWire poll, as the app's Watcher would do it."""
        self.ctx.pw.refresh()
        process()

    def settle(self, timeout=3.0):
        """Wait for "Applying changes…" to finish."""
        process(5)
        self.assertTrue(wait_until(lambda: not self.ctx.applier.busy, timeout), "applier never settled")

    def card(self, name):
        return self.mixer.values[name]

    def rate(self):
        return int(PW.settings["clock.force-rate"]), int(PW.settings["clock.force-quantum"])
