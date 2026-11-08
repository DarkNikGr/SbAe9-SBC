# SPDX-License-Identifier: GPL-2.0-only
"""Main window: sidebar navigation, page stack and the bottom status bar."""

import os

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from sbae9kit import desktop, frame, glass

from . import card as C
from . import config, icons, pages, pipewire, profiles
from .applier import Applier, Change
from . import theme as T
from .widgets import ApplyOverlay, Throttle, VolumeRow, label


class Context(QObject):
    """Shared state handed to every page."""
    profile_changed = Signal()
    palette_requested = Signal(str)
    restart_requested = Signal()
    restyle_requested = Signal()      # same window, new style sheet (glass opacity)

    def __init__(self):
        super().__init__()
        self.settings = config.Settings()
        self.card = C.AE9(self)
        self.pw = pipewire.Watcher(self)
        self.tone = pipewire.TestTone(self)
        self.monitor = pipewire.MicMonitor(self)
        self.meter = pipewire.LevelMeter(self)
        # Keep PipeWire's rate inside what the card takes right now: Direct
        # Mode, the 5.1 profile and the driver's pcm_rates all change that.
        # stream changes go one at a time, each with a settle period
        self.applier = Applier(self.pw.refresh, self)
        self.applier.add_followup(self._recheck_rate)
        self._in_followup = False
        self.depth_pending = False
        self._rate_written = None   # (rate, quantum) the app last wrote
        self._dragons = False       # user picked experimental 96 kHz on 5.1
        self.card.changed.connect(self._on_card_rate)
        self.card.connection_changed.connect(self._on_card_rate)
        self.pw.updated.connect(self._on_pw_rate)
        # Automatic optical rate: match the graph to the stream playing there
        self._optical_followed = None       # the rate we forced for it, or None
        self.pw.updated.connect(self._follow_optical)

    def rate_set(self):
        """The rates the card plays right now (Direct Mode, 5.1, driver options)."""
        direct = bool(self.card.get(C.DIRECT, True)) if self.card.present else True
        surround = self.pw.nodes.stream_layout() == "surround"
        return pipewire.playable_rates(direct, surround, C.module_param("pcm_rates") or "1",
                                       C.surround_max(), C.dsp_96k(), C.plays_176k4())

    def rate_cap(self):
        return max(self.rate_set())

    def dragons_available(self):
        """5.1 at 96 kHz on drivers before 0.7.0: experimental, only when the
        driver's root-only surround_96k option reads 1 (Direct Mode, high rates
        on). Offered for an explicit pick only: never clamped to, restored or
        chosen automatically. From 0.7.0 it's a normal rate (see rate_cap)."""
        return (not C.surround_96k_stable() and self.rate_cap() == 48000 and self.pw.nodes.stream_layout() == "surround"
                and self.card.present and bool(self.card.get(C.DIRECT, True))
                and C.module_param("pcm_rates") != "0"
                and C.module_param("surround_96k") == "1")

    def active_rates(self):
        """The rates in force now: 48 and 96 kHz on 5.1 only while the user's
        own experimental pick is live, else rate_set()."""
        if self._dragons and not self.dragons_available():
            self._dragons = False
        return [48000, 96000] if self._dragons else self.rate_set()

    def active_cap(self):
        return max(self.active_rates())

    def apply_rate(self, user=False, startup=False):
        """Write PipeWire's rate for the app's own pick, capped to what the
        card takes. Like the profile sync, the app never fights changes made
        elsewhere (pw-metadata, other tools):

        - user: the user picked in the combo: always written.
        - startup: restore the saved pick, only if PipeWire forces nothing.
        - otherwise (Direct Mode / 5.1 / connection changed): re-cap only if
          PipeWire still holds exactly what the app last wrote.
        Automatic or nothing saved: PipeWire is left alone (except a user pick).
        """
        mode = self.settings["rate_mode"]
        if user:
            # 96 kHz on 5.1 only by an explicit pick, and only for this 5.1 run
            self._dragons = mode == 96000 and self.dragons_available()
        if not mode and not user:
            return
        eff = pipewire.effective_rate(mode or 0, self.active_rates())
        want = (eff, pipewire.quantum_for(eff, self.settings["quantum"] or 0))
        if not user:
            now = (pipewire.current_force_rate(), pipewire.current_quantum())
            if self._rate_written is None and now == want:
                self._rate_written = want   # already ours (e.g. from the last run)
                return
            if startup:
                if now != (0, 0):
                    return
            elif want == self._rate_written or now != self._rate_written:
                return
            if self.applier.busy and not self._in_followup:
                return   # re-checked when the current change has settled

        def run():
            pipewire.set_rate_mode(eff, pipewire.allowed_rates(C.module_param("pcm_rates"), C.plays_176k4()),
                                   self.settings["quantum"] or 0)
            self._rate_written = want

        def settled():
            live = pipewire.card_stream()
            return self._sink_ok() and (live is None or not eff or live[0] == eff)

        text = "Sample rate: automatic" if not eff else f"Sample rate: {eff / 1000:g} kHz"
        self.applier.submit(Change(
            "rate", text, run, 4000, settled,
            lambda: (pipewire.current_force_rate(), pipewire.current_quantum()) != want))

    def _recheck_rate(self):
        self._in_followup = True
        try:
            self.apply_rate()
        finally:
            self._in_followup = False

    # --- changes that rebuild the card's stream (paced by the applier) ---------
    def _sink_ok(self):
        sink = self.pw.nodes.sink
        return sink is None or sink.get("state") in ("running", "idle", "suspended")

    def set_direct(self, on):
        if bool(self.card.get(C.DIRECT)) == on and not self.applier.busy:
            return
        self.applier.submit(Change(
            "direct", "Direct Mode on" if on else "Direct Mode off",
            lambda: self.card.set(C.DIRECT, on), 5000,
            lambda: bool(self.card.get(C.DIRECT)) == on and self._sink_ok(),
            lambda: bool(self.card.get(C.DIRECT)) != on))

    def set_speaker_cfg(self, k):
        items = self.card.items(C.SPEAKER_CFG)
        name = items[k] if 0 <= k < len(items) else str(k)
        self.applier.submit(Change(
            "speakers", f"Speakers: {name}", lambda: self.card.set(C.SPEAKER_CFG, k), 4000,
            lambda: self.card.get(C.SPEAKER_CFG) == k and self._sink_ok(),
            lambda: self.card.get(C.SPEAKER_CFG) != k))

    def set_stream_layout(self, surround):
        """Switch the card profile to the stereo or 5.1 stream, if there's
        anything to switch. False when there isn't."""
        if not pipewire.layout_profile(self.pw.nodes, surround) and not self.applier.busy:
            return False
        want = "surround" if surround else "stereo"

        def run():
            n = self.pw.nodes
            target = pipewire.layout_profile(n, surround)
            if target:
                if self.tone.running:
                    self.tone.stop()
                pipewire.set_card_profile(n, target)

        def settled():
            n = self.pw.nodes
            live = pipewire.card_stream()
            chans = 6 if surround else 2
            return (n.stream_layout() == want and n.sink is not None and self._sink_ok()
                    and (live is None or live[1] == chans))

        self.applier.submit(Change("profile", "5.1 Stream" if surround else "Stereo Stream",
                                   run, 5000, settled,
                                   lambda: bool(pipewire.layout_profile(self.pw.nodes, surround))))
        return True

    def set_bit_depth(self, k):
        items = self.card.items(C.BIT_DEPTH)
        name = items[k] if 0 <= k < len(items) else str(k)

        def run():
            self.card.set(C.BIT_DEPTH, k)
            # the depth is taken when the card opens: reopen it now
            self.depth_pending = not pipewire.reopen_sink(self.pw.nodes)

        self.applier.submit(Change("depth", f"Bit depth: {name}", run, 4000, self._sink_ok,
                                   lambda: self.card.get(C.BIT_DEPTH) != k))

    def set_mic_rate(self, rate):
        """Record the head unit mic at `rate` (None = PipeWire decides). Goes
        through a WirePlumber restart, which re-creates the card's nodes."""
        src = self.pw.nodes.source
        if not src:
            return

        def settled():
            n = self.pw.nodes
            return n.source is not None and self._sink_ok()

        text = f"Mic sample rate: {rate / 1000:g} kHz" if rate else "Mic sample rate: automatic"
        self.applier.submit(Change(
            "mic_rate", text, lambda: pipewire.set_mic_rate(src["name"], rate), 5000, settled,
            lambda: pipewire.mic_rate_setting() != rate))

    def set_input_rate(self, key, path, rate, title):
        """Record an extra input (What U Hear) at `rate`: its PipeWire config's
        audio.rate, then a PipeWire restart, which re-creates the nodes."""

        def settled():
            n = self.pw.nodes
            return getattr(n, key) is not None and self._sink_ok()

        self.applier.submit(Change(
            key + "_rate", f"{title} sample rate: {rate / 1000:g} kHz",
            lambda: pipewire.set_input_conf_rate(path, rate), 8000, settled,
            lambda: pipewire.input_conf_rate(path) != rate))

    def set_input_format(self, key, path, fmt, title):
        """The extra node's sample format (the optical output's bit depth): its
        PipeWire config's audio.format, then a PipeWire restart."""

        def settled():
            n = self.pw.nodes
            return getattr(n, key) is not None and self._sink_ok()

        label = "16-bit" if fmt == "S16LE" else "24-bit"
        self.applier.submit(Change(
            key + "_format", f"{title} bit depth: {label}",
            lambda: pipewire.set_input_conf_format(path, fmt), 8000, settled,
            lambda: pipewire.input_conf_format(path) != fmt))

    def set_capture_depth(self, k):
        items = self.card.items(C.CAP_BIT_DEPTH)
        name = items[k] if 0 <= k < len(items) else str(k)

        def run():
            self.card.set(C.CAP_BIT_DEPTH, k)
            pipewire.reopen_source(self.pw.nodes)   # taken when the capture opens

        self.applier.submit(Change("cap_depth", f"Mic bit depth: {name}", run, 4000, self._sink_ok,
                                   lambda: self.card.get(C.CAP_BIT_DEPTH) != k))

    def restore_rate(self):
        """Restore the saved pick at start, once the first PipeWire snapshot
        is in: before it, a 5.1 profile isn't known yet and the cap would be
        too high (6 ch above 48 kHz falls apart). With "Reload last rate on
        start" off the app only shows what PipeWire is running."""
        pipewire.update_allowed_rates(pipewire.allowed_rates(C.module_param("pcm_rates"), C.plays_176k4()))
        if not self.settings["rate_mode"] or not self.settings["restore_rate_on_start"]:
            return
        if self.pw.nodes.device or self.pw.nodes.sink:
            self.apply_rate(startup=True)
        else:
            self.pw.updated.connect(self._restore_rate_once)

    def _restore_rate_once(self, *_):
        self.pw.updated.disconnect(self._restore_rate_once)
        self.apply_rate(startup=True)

    def _on_card_rate(self, name=None):
        if name in (None, True, False, C.DIRECT):
            self.apply_rate()

    def _on_pw_rate(self, *_):
        self.apply_rate()

    # -- Automatic optical rate ------------------------------------------

    def _optical_rate_is_auto(self):
        """True when the optical output's rate is Automatic (no audio.rate)."""
        path = pipewire.input_conf(4)
        return bool(path) and pipewire.input_conf_rate(path) is None

    def _follow_optical(self, *_):
        """Optical rate Automatic: the optical PCM is separate, but PipeWire
        has one clock, so follow the rate of the stream playing to it instead
        of resampling it (only while the card's own rate is Automatic too).
        When that stream stops, give the clock back."""
        if self.settings["rate_mode"] not in (0, None) or not self._optical_rate_is_auto():
            return self._hand_back_optical_rate()
        rates = set(pipewire.streams_into("alsa_output.ae9_optical"))
        if len(rates) == 1:
            rate = rates.pop()
            if rate in pipewire.OPTICAL_RATES and pipewire.current_force_rate() != rate:
                if pipewire.force_rate(rate) is not None:
                    self._optical_followed = rate
        elif not rates:
            self._hand_back_optical_rate()

    def _hand_back_optical_rate(self):
        if self._optical_followed is None:
            return
        pipewire.force_rate(self.settings["rate_mode"] or 0)
        self._optical_followed = None


NAV = [
    ("SBX Profile", "home", pages.SbxPage),
    ("Equalizer", "equalizer", pages.EqPage),
    None,
    ("Playback", "playback", pages.PlaybackPage),
    ("Recording", "recording", pages.RecordingPage),
    ("Scout Mode", "scout", pages.ScoutPage),
    ("Mixer", "mixer", pages.MixerPage),
]
NAV_BOTTOM = [("Settings", "settings", pages.SettingsPage)]

def nav_qss():
    return f"""
QPushButton {{
    background: transparent; border: none; border-left: 3px solid transparent; border-radius: 0;
    text-align: left; padding: 11px 16px; font-size: 16px;
}}
QPushButton:hover {{ background: {T.rgba(T.OVERLAY, 0.06)}; }}
QPushButton:checked {{ color: {T.ACCENT_HI}; border-left: 3px solid {T.ACCENT}; background: {T.rgba(T.OVERLAY, 0.06)}; }}
"""


class PillSwitch(QWidget):
    """Two-way pill in the bottom bar: an icon each side, the knob on the
    one in use. `right()` says which; `toggle()` switches."""

    def __init__(self, card, control, left_icon, right_icon, tip, parent=None):
        super().__init__(parent)
        self.card, self.control = card, control
        self.icons = (left_icon, right_icon)
        self.setFixedSize(58, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        card.changed.connect(self._on_change)

    def _on_change(self, name):
        if name == self.control:
            self.update()

    def right(self):
        return False

    def toggle(self):
        pass

    def mouseReleaseEvent(self, e):
        if self.card.present and self.rect().contains(e.position().toPoint()):
            self.toggle()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        right = self.right()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T.PANEL))
        p.drawRoundedRect(self.rect(), 15, 15)
        p.setBrush(QColor(T.ACCENT))
        p.drawEllipse(30 if right else 2, 2, 26, 26)
        icons.paint(p, self.icons[0], self.rect().adjusted(6, 7, -36, -7), T.MUTED if right else T.ACCENT_TEXT)
        icons.paint(p, self.icons[1], self.rect().adjusted(35, 7, -7, -7), T.ACCENT_TEXT if right else T.MUTED)


class OutputSwitch(PillSwitch):
    """Headphones / speakers (Head Unit Output)."""

    def __init__(self, card, parent=None):
        super().__init__(card, C.OUTPUT, "headphones", "speaker",
                         "Switch between speakers (the card's RCA out) and headphones "
                         "(the head unit's headphone jacks)", parent)

    def right(self):
        return self.card.get(C.OUTPUT) != 1

    def toggle(self):
        self.card.set(C.OUTPUT, 0 if self.card.get(C.OUTPUT) == 1 else 1)


class DirectSwitch(PillSwitch):
    """Direct Mode / DSP, through the app's Direct Mode change (as the
    Playback page's switch)."""

    def __init__(self, ctx, parent=None):
        super().__init__(ctx.card, C.DIRECT, "direct", "chip",
                         "Switch between the DSP (SBX, EQ, speaker setup) and Direct Mode "
                         "(straight to the DAC, up to 384 kHz)", parent)
        self.ctx = ctx

    def right(self):
        # Direct on the left, DSP on the right: the order you switch things
        # on (DSP, then SBX), as in the panel widgets
        return not self.card.get(C.DIRECT, True)

    def toggle(self):
        self.ctx.set_direct(self.right())


class StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.color = QColor(T.DIM)
        self.setFixedSize(16, 16)

    def set_color(self, c):
        self.color = QColor(c)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(2, 2, 12, 12)


APPICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "appicon")


def app_icon():
    """The app icon (appicon/sbae9-sbc-<size>.png, every size), or the wave
    symbol if the PNGs are missing."""
    return desktop.app_icon(APPICON_DIR, config.APP_ID,
                            fallback=QIcon(icons.pixmap("wave", T.ACCENT_HI, 64)))


def blur_behind(win):
    """KDE's frost behind the glass window (shared with SbAe9-AudioMon)."""
    return glass.blur_behind(win)


# the frameless window's title bar and edge grips (shared with SbAe9-AudioMon)
TitleBar, EdgeGrip = frame.TitleBar, frame.EdgeGrip


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.card = ctx.card
        self.setWindowTitle("Sound Blaster Command — AE-9")
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)
        self.setMinimumSize(1000, 660)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # title strip
        title = self.title_bar = TitleBar()
        th = QHBoxLayout(title)
        th.setContentsMargins(18, 8, 10, 6)
        th.setSpacing(4)
        tl = QVBoxLayout()
        tl.setSpacing(0)
        tl.addWidget(label("Sound Blaster Command", "appTitle"))
        tl.addWidget(label("AE-9", "deviceName"))
        th.addLayout(tl)
        th.addStretch()
        self.win_buttons = []
        for name, tip, slot in (("minimize", "Minimize", self.showMinimized), ("close", "Close", self.close)):
            b = QToolButton()
            b.setObjectName("winClose" if name == "close" else "winButton")
            b.setIcon(icons.icon(name, T.MUTED, active=T.TEXT, size=18))
            b.setIconSize(QSize(18, 18))
            b.setFixedSize(34, 28)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            th.addWidget(b, 0, Qt.AlignTop)
            self.win_buttons.append(b)
        v.addWidget(title)

        self.missing = pages.Banner("Sound Blaster AE-9 not found. Is the snd-hda-codec-creative-ae9 "
                                    "driver loaded? Waiting for the card…", warn=True)
        self.missing.layout().setContentsMargins(16, 8, 16, 8)
        v.addWidget(self.missing)

        mid = QHBoxLayout()
        mid.setSpacing(0)
        v.addLayout(mid, 1)

        side = self.sidebar = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(232)
        side.setStyleSheet(nav_qss().replace("QPushButton", "#sidebar QPushButton"))
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 10, 0, 12)
        sl.setSpacing(2)
        sl.addWidget(label("Sound Experience", "sideCaption"))
        sl.addSpacing(4)
        self.stack = QStackedWidget()
        self.stack.setObjectName("content")
        self.buttons = []

        def add(entry):
            name, ic, cls = entry
            page = cls(ctx)
            idx = self.stack.addWidget(page)
            b = QPushButton(name)
            b.setCheckable(True)
            b.setIcon(icons.icon(ic, T.TEXT, active=T.ACCENT_HI, size=22))
            b.setIconSize(QSize(22, 22))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=idx: self.go(i))
            self.buttons.append(b)
            sl.addWidget(b)

        for entry in NAV:
            if entry is None:
                sl.addWidget(pages.hline())
            else:
                add(entry)
        sl.addStretch()
        sl.addWidget(pages.hline())
        for entry in NAV_BOTTOM:
            add(entry)
        mid.addWidget(side)
        mid.addWidget(self.stack, 1)

        # bottom bar
        bottom = self.bottom_bar = QFrame()
        bottom.setObjectName("bottomBar")
        bottom.setFixedHeight(56)
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(18, 0, 22, 0)
        bl.setSpacing(16)
        self.output_switch = OutputSwitch(self.card)
        bl.addWidget(self.output_switch)
        self.direct_switch = DirectSwitch(self.ctx)
        bl.addWidget(self.direct_switch)
        self.dot = StatusDot()
        bl.addWidget(self.dot)
        self.sbx_logo = label("SBX", "sbxLogo")
        bl.addWidget(self.sbx_logo)
        sep = QFrame()
        sep.setFixedSize(2, 26)
        sep.setStyleSheet(f"background:{T.TEXT};")
        self.sep = sep
        bl.addWidget(sep)
        self.profile_lbl = label("", "profileLabel")
        bl.addWidget(self.profile_lbl)
        bl.addStretch()
        self.mic = VolumeRow("mic", "mic-off", width=140, show_value=False)
        self.mic.setToolTip("Microphone level")
        self.mic.valueChanged.connect(Throttle(lambda val: self.card.set(C.MIC, round(val * 99)), 40))
        self.mic.muteToggled.connect(self._mic_mute)
        bl.addWidget(self.mic)
        vsep = QFrame()
        vsep.setFixedSize(2, 30)
        vsep.setStyleSheet(f"background:{T.TEXT};")
        bl.addWidget(vsep)
        self.vol = VolumeRow(width=190, show_value=False)
        self.vol.setToolTip("Volume (same as the head unit knob)")
        self.vol.valueChanged.connect(Throttle(
            lambda val: self.card.set(C.MASTER, C.master_pct_to_raw(val)), 30))
        self.vol.muteToggled.connect(lambda m: self.card.set(C.MASTER_SW, not m))
        bl.addWidget(self.vol)
        v.addWidget(bottom)

        self.card.changed.connect(self._on_card)
        self.card.info_changed.connect(self._on_card)
        self.card.connection_changed.connect(self._on_card)
        ctx.profile_changed.connect(self.refresh)
        ctx.pw.updated.connect(self._refresh_mic_mute)

        start = ctx.settings["page"]
        self.go(start if isinstance(start, int) and 0 <= start < self.stack.count() else 0)
        self.refresh()

        # "Applying changes…" while a stream change settles
        self.applying = ApplyOverlay(root)
        ctx.applier.busy_changed.connect(self.applying.set_busy)
        ctx.applier.step.connect(self.applying.set_step)
        if ctx.applier.busy:
            self.applying.set_busy(True)

        if T.GLASS:
            # see-through backgrounds; must be set before the window is created
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.grips = [EdgeGrip(edges, self) for edges in EdgeGrip.CURSORS]
        self.set_frameless(bool(ctx.settings["frameless"]))

    # own title bar vs. the desktop's frame
    def frameless(self):
        return bool(self.windowFlags() & Qt.FramelessWindowHint)

    def set_frameless(self, on):
        shown, state = self.isVisible(), self.windowState()
        self.setWindowFlag(Qt.FramelessWindowHint, on)   # hides the window if it was shown
        for b in self.win_buttons:
            b.setVisible(on)
        self._place_grips()
        if shown:
            self.setWindowState(state)
            self.show()

    def _place_grips(self):
        on = self.frameless() and not (self.isMaximized() or self.isFullScreen())
        for g in self.grips:
            g.setVisible(on)
            if on:
                g.place(self.width(), self.height())

    def showEvent(self, e):
        super().showEvent(e)
        if T.GLASS:
            blur_behind(self)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_grips()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange:
            self._place_grips()

    def go(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.buttons):
            b.setChecked(i == idx)
        self.ctx.settings["page"] = idx

    def _mic_mute(self, muted):
        n = self.ctx.pw.nodes
        if n.source:
            pipewire.set_mute(n.source["id"], muted)

    def _on_card(self, *_):
        self.refresh()

    def _refresh_mic_mute(self, *_):
        n = self.ctx.pw.nodes
        if n.source and self.card.present:
            _, muted = pipewire.get_volume(n.source["id"])
            self.mic.set_state(self.card.get(C.MIC, 0) / 99, muted)

    def refresh(self):
        present = self.card.present
        self.missing.setVisible(not present)
        self.stack.setEnabled(present)
        if not present:
            self.dot.set_color(T.DIM)
            self.profile_lbl.setText("No device")
            return
        direct = self.card.get(C.DIRECT, True)
        sbx = self.card.get(C.SBX, False)
        if direct:
            self.dot.set_color(T.DOT_IDLE)
            self.dot.setToolTip("Direct Mode: audio bypasses the DSP")
            self.profile_lbl.setText("Direct Mode")
        elif sbx:
            self.dot.set_color(T.OK)
            self.dot.setToolTip("SBX on: effects active")
            name = self.ctx.settings["active_profile"]
            prof = profiles.find(self.ctx.settings, name)
            mod = "" if profiles.matches(prof, self.card.snapshot()) else " *"
            scout = "  ·  Scout Mode" if self.card.get(C.SCOUT) else ""
            self.profile_lbl.setText(f"{name}{mod}{scout}")
        else:
            self.dot.set_color(T.WARN)
            self.dot.setToolTip("DSP path, SBX off")
            self.profile_lbl.setText("Off")
        raw = self.card.get(C.MASTER, 0)
        self.vol.set_state(C.master_raw_to_pct(raw), not self.card.get(C.MASTER_SW, True))
        self.vol.setToolTip(f"Volume {C.master_raw_to_db(raw):.1f} dB (same as the head unit knob)")
        self.mic.set_state(self.card.get(C.MIC, 0) / 99, self.mic.btn.isChecked())

    def closeEvent(self, e):
        self.ctx.tone.stop()
        self.ctx.monitor.stop()
        self.ctx.meter.stop()
        super().closeEvent(e)
