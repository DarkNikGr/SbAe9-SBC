# SPDX-License-Identifier: GPL-2.0-only
"""The app's pages, one per sidebar entry."""

import errno
import os
import subprocess
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton,
                               QRadioButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from . import __version__
from . import card as C
from . import config, icons, pipewire, profiles
from . import theme as T
from .widgets import (TabBar, Dial, EffectControl, EqGraph, LevelBar, PaletteCard, ProfileCarousel, Segmented,
                      SpeakerDiagram, Throttle, ToggleSwitch, VolumeRow, label)


def tool(icon_name, tip, size=24):
    b = QToolButton()
    b.setIcon(icons.icon(icon_name, active=T.ACCENT, size=size))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def info_button(text):
    b = tool("info", text, 18)
    b.clicked.connect(lambda: QMessageBox.information(b.window(), "About this setting", text))
    return b


def hline():
    f = QFrame()
    f.setObjectName("sideSep")
    return f


class Banner(QFrame):
    """Inline notice with an optional action button."""

    def __init__(self, text="", action=None, warn=False):
        super().__init__()
        self.setObjectName("warnBanner" if warn else "banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("info", T.DANGER if warn else T.ACCENT_HI, 18))
        lay.addWidget(ic)
        self.text = label(text, wrap=True)
        lay.addWidget(self.text, 1)
        self.button = None
        if action:
            self.button = QPushButton(action)
            self.button.setObjectName("accentButton")
            self.button.setCursor(Qt.PointingHandCursor)
            lay.addWidget(self.button)


class TabPages(QWidget):
    """The pages behind a TabBar. Only the shown one is visible, so only it
    counts toward the height (a short tab doesn't scroll because a long one
    is behind it, as it would in a QStackedWidget)."""

    def __init__(self):
        super().__init__()
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._pages, self._current = [], -1

    def addWidget(self, w):
        self._pages.append(w)
        self._lay.addWidget(w)
        w.setVisible(False)
        return len(self._pages) - 1

    def count(self):
        return len(self._pages)

    def widget(self, i):
        return self._pages[i]

    def currentIndex(self):
        return self._current

    def currentWidget(self):
        return self._pages[self._current] if 0 <= self._current < len(self._pages) else None

    def setCurrentIndex(self, i):
        self._current = i
        for k, w in enumerate(self._pages):
            w.setVisible(k == i)


class Page(QWidget):
    title = ""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.card = ctx.card
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(26, 14, 26, 18)
        self.lay.setSpacing(12)
        self.card.changed.connect(self._changed)
        self.card.info_changed.connect(self._changed)
        self.card.connection_changed.connect(self._on_connection)

    # Slots for long-lived signals are methods (not lambdas) so Qt drops the
    # connection when the page is deleted, e.g. when the palette changes.
    def _on_connection(self, *_):
        self.refresh()

    def _on_pw(self, *_):
        if self.isVisible():
            self.refresh()

    def header(self, text, switch=None, extra=()):
        row = QHBoxLayout()
        row.setSpacing(14)
        if switch is not None:
            row.addWidget(switch)
        row.addWidget(label(text, "pageTitle"))
        for w in extra:
            row.addWidget(w) if isinstance(w, QWidget) else row.addLayout(w)
        row.addStretch()
        self.lay.addLayout(row)
        return row

    def add_tabs(self, names):
        """Tabs under the page title. Returns one layout per tab; the last
        tab picked on this page comes back next time."""
        self.tab_bar = TabBar(names)
        self.tab_stack = TabPages()
        lays = []
        for _ in names:
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(0, 6, 0, 0)
            lay.setSpacing(12)
            self.tab_stack.addWidget(w)
            lays.append(lay)
        self.lay.addWidget(self.tab_bar)
        self.lay.addWidget(self.tab_stack, 1)
        saved = (self.ctx.settings["tabs"] or {}).get(self.title, 0)
        self.show_tab(saved if isinstance(saved, int) and 0 <= saved < len(names) else 0, save=False)
        self.tab_bar.changed.connect(self.show_tab)
        return lays

    def show_tab(self, i, save=True):
        self.tab_bar.set_current(i)
        self.tab_stack.setCurrentIndex(i)
        if save:
            tabs = dict(self.ctx.settings["tabs"] or {})
            tabs[self.title] = i
            self.ctx.settings["tabs"] = tabs
            if self.isVisible():
                self.refresh()

    def _changed(self, name):
        if self.isVisible():
            self.refresh()
        else:
            self._dirty = True

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        pass


# =====================================================================================
class SbxPage(Page):
    title = "SBX Profile"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.sbx = ToggleSwitch()
        self.sbx.setToolTip("SBX on/off")
        self.sbx.toggled.connect(lambda on: self.card.set(C.SBX, on))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(360)
        self.combo.activated.connect(lambda i: self.pick(self.combo.itemText(i)))
        self.modified = label("", "muted")
        plus = tool("plus", "Save the current settings as a new profile", 28)
        plus.clicked.connect(self.save_as)
        dots = tool("dots", "More", 28)
        dots.setPopupMode(QToolButton.InstantPopup)
        self.menu = QMenu(self)
        self.act_save = self.menu.addAction("Save", self.save)
        self.menu.addAction("Save as new…", self.save_as)
        self.act_revert = self.menu.addAction("Revert", self.revert)
        self.menu.addSeparator()
        self.act_rename = self.menu.addAction("Rename…", self.rename)
        self.act_delete = self.menu.addAction("Delete", self.delete)
        dots.setMenu(self.menu)
        self.header("SBX Profile", self.sbx, [self.combo, plus, dots, self.modified])

        self.banner = Banner("", "Turn Direct Mode off", warn=True)
        self.banner.button.clicked.connect(lambda: self.ctx.set_direct(False))
        self.lay.addWidget(self.banner)

        self.carousel = ProfileCarousel()
        self.carousel.picked.connect(self.pick)
        self.lay.addWidget(self.carousel)

        cap = QHBoxLayout()
        cap.addStretch()
        cap.addWidget(label("Acoustic Engine", "subTitle"))
        cap.addStretch()
        cap.addWidget(info_button(
            "Surround widens the sound stage beyond your speakers or headphones.\n"
            "Crystalizer restores detail lost to compression (cymbals, effects).\n"
            "Bass adds low-end weight.\n"
            "Smart Volume evens out loud and quiet passages: Night keeps peaks down, "
            "Loud lifts quiet sounds.\n"
            "Dialog+ brings voices forward.\n\n"
            "All of these run on the AE-9's own DSP. They are heard when Direct Mode "
            "is off and SBX is on."))
        self.lay.addLayout(cap)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.effects = {}
        for e in C.EFFECTS:
            ec = EffectControl(C.EFFECT_LABELS[e])
            ec.levelChanged.connect(Throttle(lambda v, e=e: self.card.set(C.fx_level(e), v), 60))
            ec.toggled.connect(lambda on, e=e: self.card.set(C.fx_switch(e), on))
            self.effects[e] = ec
            row.addStretch()
            row.addWidget(ec)
        row.addStretch()
        self.svmode = Segmented(["Night", "Normal", "Loud"])
        self.svmode.selected.connect(lambda m: self.card.set(C.SV_MODE, m))
        self.effects["Smart Volume"].layout().addWidget(self.svmode, 0, Qt.AlignHCenter)
        self.lay.addLayout(row)
        self.lay.addStretch()
        self._profiles_shown = None

    # --- profiles ----------------------------------------------------------------
    def _active(self):
        return profiles.find(self.ctx.settings, self.ctx.settings["active_profile"])

    def pick(self, name):
        prof = profiles.find(self.ctx.settings, name)
        if not prof:
            return
        self.card.apply(prof)
        self.ctx.settings["active_profile"] = name
        self.ctx.profile_changed.emit()
        self.refresh()

    def _ask_name(self, title, default=""):
        name, ok = QInputDialog.getText(self, title, "Profile name:", text=default)
        name = name.strip()
        if not ok or not name:
            return None
        if any(p["name"] == name and p.get("builtin") for p in profiles.BUILTIN):
            QMessageBox.warning(self, title, f"“{name}” is a built-in profile. Pick another name.")
            return None
        return name

    def save_as(self):
        name = self._ask_name("New profile", "New Profile 1")
        if name:
            profiles.save_user(self.ctx.settings, name, self.card.snapshot())
            self.ctx.settings["active_profile"] = name
            self.ctx.profile_changed.emit()
            self.refresh(force=True)

    def save(self):
        p = self._active()
        if p and not p.get("builtin"):
            profiles.save_user(self.ctx.settings, p["name"], self.card.snapshot(), p.get("art", "custom"))
            self.refresh(force=True)
        else:
            self.save_as()

    def revert(self):
        p = self._active()
        if p:
            self.pick(p["name"])

    def rename(self):
        p = self._active()
        if not p or p.get("builtin"):
            return
        new = self._ask_name("Rename profile", p["name"])
        if new and new != p["name"]:
            profiles.rename_user(self.ctx.settings, p["name"], new)
            self.ctx.settings["active_profile"] = new
            self.ctx.profile_changed.emit()
            self.refresh(force=True)

    def delete(self):
        p = self._active()
        if not p or p.get("builtin"):
            return
        if QMessageBox.question(self, "Delete profile", f"Delete “{p['name']}”?") == QMessageBox.Yes:
            profiles.delete_user(self.ctx.settings, p["name"])
            self.ctx.settings["active_profile"] = "Default"
            self.ctx.profile_changed.emit()
            self.refresh(force=True)

    # --- state -----------------------------------------------------------------
    def refresh(self, force=False):
        s = self.ctx.settings
        all_p = profiles.all_profiles(s)
        names = [p["name"] for p in all_p]
        active = s["active_profile"] if s["active_profile"] in names else "Default"
        if force or self._profiles_shown != names:
            self._profiles_shown = names
            self.combo.blockSignals(True)
            self.combo.clear()
            self.combo.addItems(names)
            self.combo.blockSignals(False)
            self.carousel.set_profiles(all_p, active)
        self.combo.setCurrentText(active)
        if self.carousel.current != active:
            self.carousel.set_current(active)
        prof = profiles.find(s, active)
        if not self.card.present:
            return
        snap = self.card.snapshot()
        dirty = not profiles.matches(prof, snap)
        self.modified.setText("● modified" if dirty else "")
        self.act_revert.setEnabled(dirty)
        user = bool(prof and not prof.get("builtin"))
        self.act_rename.setEnabled(user)
        self.act_delete.setEnabled(user)
        self.act_save.setEnabled(user and dirty)

        direct = self.card.get(C.DIRECT, True)
        sbx = bool(self.card.get(C.SBX, False))
        self.sbx.setCheckedSilently(sbx)
        self.sbx.setEnabled(not direct)
        if direct:
            self.banner.text.setText("Direct Mode is on: audio goes straight to the DAC and the SBX "
                                     "effects are bypassed. Changes here are kept for when it's off.")
            self.banner.button.show()
        elif not sbx:
            self.banner.text.setText("SBX is off. Switch it on (top left) to hear the effects.")
            self.banner.button.hide()
        self.banner.setVisible(direct or not sbx)
        for e, ec in self.effects.items():
            on, lvl = snap["fx"][e]
            ec.set_state(on, lvl)
        self.svmode.set_value(snap["sv_mode"])


# =====================================================================================
class EqPage(Page):
    title = "Equalizer"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.sw = ToggleSwitch()
        self.sw.setToolTip("Equalizer on/off")
        self.sw.toggled.connect(lambda on: self.card.set(C.EQ_ON, on))
        self.header("Equalizer", self.sw, [info_button(
            "A 10-band graphic EQ on the AE-9's DSP, with Creative's 20 presets.\n\n"
            "Drag a point (or scroll over it) to change a band by 1 dB. Pre-gain, on the left, "
            "lowers the level going into the EQ so boosts don't clip.\n\n"
            "Save your own curves with +. The EQ is heard when Direct Mode is off and SBX is on.")])

        row = QHBoxLayout()
        row.setSpacing(10)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(320)
        self.combo.activated.connect(self._picked)
        plus = tool("plus", "Save this curve as a preset", 26)
        plus.clicked.connect(self.save_as)
        flat = tool("refresh", "Reset to flat", 24)
        flat.clicked.connect(lambda: self._apply_hw("Flat"))
        dots = tool("dots", "More", 26)
        dots.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(self)
        self.act_rename = m.addAction("Rename", self.rename)
        self.act_delete = m.addAction("Delete", self.delete)
        dots.setMenu(m)
        row.addWidget(self.combo)
        row.addWidget(plus)
        row.addWidget(flat)
        row.addWidget(dots)
        row.addStretch()
        self.lay.addLayout(row)

        self.banner = Banner("", warn=True)
        self.lay.addWidget(self.banner)

        self.graph = EqGraph(C.EQ_BAND_LABELS)
        self.graph.setMinimumHeight(300)
        self._band_set = Throttle(self._set_band, 40)
        self.graph.bandChanged.connect(self._band_set)
        self.lay.addWidget(self.graph, 1)
        self.lay.addWidget(label("Values are whole dB. Creative's presets use finer steps internally; "
                                 "editing a band rounds it.", "hint", wrap=True))
        self.user_name = None

    def _set_band(self, idx, db):
        self.card.set(C.EQ_CONTROLS[idx], int(db) + 12)
        if not self.card.get(C.EQ_ON):
            self.card.set(C.EQ_ON, True)

    def _apply_hw(self, name):
        self.card.set(C.EQ_PRESET, name, force=True)
        self.card.set(C.EQ_ON, True)
        self.refresh()

    def _picked(self, i):
        kind, name = self.combo.itemData(i) or (None, None)
        if kind == "hw":
            self._apply_hw(name)
        elif kind == "user":
            self.card.set_eq_db(self.ctx.settings["eq_presets"][name])
            self.card.set(C.EQ_ON, True)
            self.refresh()

    def save_as(self):
        name, ok = QInputDialog.getText(self, "Save EQ preset", "Preset name:", text="My EQ")
        name = name.strip()
        if ok and name:
            if name in profiles.HW_EQ_PRESETS:
                QMessageBox.warning(self, "Save EQ preset", "That name belongs to a built-in preset.")
                return
            presets = dict(self.ctx.settings["eq_presets"])
            presets[name] = self.card.eq_db()
            self.ctx.settings["eq_presets"] = presets
            self.refresh()

    def rename(self):
        if not self.user_name:
            return
        new, ok = QInputDialog.getText(self, "Rename EQ preset", "Preset name:", text=self.user_name)
        new = new.strip()
        if ok and new and new not in profiles.HW_EQ_PRESETS:
            presets = dict(self.ctx.settings["eq_presets"])
            presets[new] = presets.pop(self.user_name)
            self.ctx.settings["eq_presets"] = presets
            self.refresh()

    def delete(self):
        if not self.user_name:
            return
        presets = dict(self.ctx.settings["eq_presets"])
        presets.pop(self.user_name, None)
        self.ctx.settings["eq_presets"] = presets
        self.refresh()

    def refresh(self):
        if not self.card.present:
            return
        vals = self.card.eq_db()
        hw = self.card.get_item(C.EQ_PRESET)
        users = self.ctx.settings["eq_presets"]
        current = None
        if hw in profiles.HW_EQ_PRESETS and profiles.eq_equal(profiles.HW_EQ_PRESETS[hw], vals):
            current = ("hw", hw)
            vals = profiles.HW_EQ_PRESETS[hw]  # show the 0.1 dB curve
        else:
            for n, v in users.items():
                if profiles.eq_equal(v, vals):
                    current = ("user", n)
                    break
        self.user_name = current[1] if current and current[0] == "user" else None
        self.act_rename.setEnabled(bool(self.user_name))
        self.act_delete.setEnabled(bool(self.user_name))

        self.combo.blockSignals(True)
        self.combo.clear()
        items = self.card.items(C.EQ_PRESET)
        for k, n in enumerate(items):
            # newer drivers list the game presets last: give them a heading
            if n in profiles.GAME_EQ_PRESETS and k > 0 and items[k - 1] not in profiles.GAME_EQ_PRESETS \
                    and all(m in profiles.GAME_EQ_PRESETS for m in items[k:]):
                self.combo.insertSeparator(self.combo.count())
                self.combo.addItem("Games", ("heading", None))
                head = self.combo.model().item(self.combo.count() - 1)
                head.setEnabled(False)
                f = head.font()
                f.setBold(True)
                head.setFont(f)
            self.combo.addItem(n, ("hw", n))
        if users:
            self.combo.insertSeparator(self.combo.count())
            for n in users:
                self.combo.addItem(icons.icon("star", T.ACCENT_HI, size=16), n, ("user", n))
        if current is None:
            self.combo.insertSeparator(self.combo.count())
            self.combo.addItem("Custom (unsaved)", ("none", None))
            self.combo.setCurrentIndex(self.combo.count() - 1)
        else:
            for i in range(self.combo.count()):
                if self.combo.itemData(i) == current:
                    self.combo.setCurrentIndex(i)
        self.combo.blockSignals(False)

        on = bool(self.card.get(C.EQ_ON))
        self.sw.setCheckedSilently(on)
        self.graph.set_values(vals)
        audible = on and self.card.dsp_active
        self.graph.setActive(audible)
        if self.card.get(C.SCOUT):
            msg = "Scout Mode is on and is using the EQ. Turn it off to get your EQ back."
        elif self.card.get(C.DIRECT, True):
            msg = "Direct Mode is on, so the EQ is bypassed (Playback page)."
        elif not self.card.get(C.SBX):
            msg = "SBX is off, so the EQ is bypassed (SBX Profile page)."
        elif not on:
            msg = "The EQ is off. Moving a band switches it on."
        else:
            msg = ""
        self.banner.text.setText(msg)
        self.banner.setVisible(bool(msg))


# =====================================================================================
class PlaybackPage(Page):
    title = "Playback"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header("Playback")
        self.lay, setup, digital = self.add_tabs(["Speakers/Headphones", "Speaker Setup", "Digital"])
        self.setup = SpeakerSetup(ctx)
        setup.addWidget(self.setup)

        grid = QGridLayout()
        grid.setHorizontalSpacing(30)
        grid.setVerticalSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(10)

        dev = QHBoxLayout()
        dcol = QVBoxLayout()
        dcol.setSpacing(0)
        dcol.addWidget(label("Playback device:", "sectionTitle"))
        self.dev_name = label("—", "sectionTitle")
        dcol.addWidget(self.dev_name)
        dev.addLayout(dcol)
        dev.addStretch()
        self.set_default = QPushButton("Set Default")
        self.set_default.setMinimumWidth(150)
        self.set_default.clicked.connect(self._make_default)
        self.default_ok = QLabel()
        dev.addWidget(self.set_default)
        dev.addWidget(self.default_ok)
        left.addLayout(dev)

        left.addWidget(label("Output", "sectionTitle"))
        self.group = QButtonGroup(self)
        self.r_spk = QRadioButton()
        self.r_hp = QRadioButton()
        self.group.addButton(self.r_spk, 0)
        self.group.addButton(self.r_hp, 1)
        self.group.idClicked.connect(lambda i: self.card.set(C.OUTPUT, i))

        def out_row(radio, icon_name, title):
            w = QWidget()
            g = QGridLayout(w)
            g.setContentsMargins(0, 4, 0, 4)
            g.setHorizontalSpacing(12)
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, T.TEXT, 22))
            g.addWidget(radio, 0, 0)
            g.addWidget(ic, 0, 1)
            t = label(title)
            t.setStyleSheet("font-size:15px;")
            g.addWidget(t, 0, 2)
            sub = label("", "muted", wrap=True)
            g.addWidget(sub, 1, 2, 1, 2)
            g.setColumnStretch(3, 1)
            return w, g, sub

        w, g, self.spk_sub = out_row(self.r_spk, "speaker", "Speakers")
        self.spk_cfg = QComboBox()
        self.spk_cfg.setToolTip("Speaker setup the DSP mixes for (used when Direct Mode is off)")
        self.spk_cfg.setMinimumWidth(150)
        self.spk_cfg.activated.connect(self._speaker_cfg)
        g.addWidget(self.spk_cfg, 0, 4)
        # PipeWire profile: stereo or 5.1 stream. Offered only with the driver's
        # profile set; usable in Direct Mode too, where Speaker Config is greyed.
        self.stream = QComboBox()
        self.stream.setMinimumWidth(150)
        self.stream.addItem("Stereo Stream", False)
        self.stream.addItem("5.1 Stream", True)
        self.stream.setToolTip(STREAM_TIP)
        self.stream.activated.connect(lambda i: self._switch_stream(self.stream.itemData(i)))
        g.addWidget(self.stream, 1, 4)
        self._stream_pending = None
        left.addWidget(w)
        w, g, self.hp_sub = out_row(self.r_hp, "headphones", "Headphones")
        # auto switch on the head unit's 3.5 mm headphone jack (newer drivers)
        self.hp_auto_row = QWidget()
        ar = QHBoxLayout(self.hp_auto_row)
        ar.setContentsMargins(0, 4, 0, 0)
        ar.setSpacing(10)
        self.hp_auto = ToggleSwitch()
        self.hp_auto.toggled.connect(lambda on: self.card.set(C.HU_AUTO, on))
        ar.addWidget(self.hp_auto)
        ar.addWidget(label("Auto switch on headphone plug", "muted"))
        ar.addWidget(info_button(
            "Plug headphones into the head unit's 3.5 mm headphone jack and the card switches to "
            "headphones; unplug and it goes back to speakers, about a second and a half "
            "after the plug settles. Same switch as holding the knob, and each output keeps "
            "its own volume.\n\n"
            "It acts once per plug change: switch back yourself afterwards and it stays that "
            "way until the next plug or unplug.\n\n"
            "Only the 3.5 mm headphone jack reports plugs: the 1/4\" headphone jack can't "
            "switch outputs by itself."))
        ar.addStretch()
        g.addWidget(self.hp_auto_row, 2, 2, 1, 3)
        self.hp_auto_row.setVisible(False)
        # headphone profile: Creative's EQ curve per headphone model (newer drivers)
        self.hp_prof_row = QWidget()
        pr = QGridLayout(self.hp_prof_row)
        pr.setContentsMargins(0, 4, 0, 0)
        pr.setHorizontalSpacing(10)
        pr.addWidget(label("Headphone Profile", "muted"), 0, 0)
        self.hp_prof = QComboBox()
        self.hp_prof.setMinimumWidth(230)
        self.hp_prof.activated.connect(lambda i: self.card.set(C.HP_PROFILE, i))
        pr.addWidget(self.hp_prof, 0, 1)
        pr.addWidget(info_button(HP_PROFILE_TIP), 0, 2)
        pr.setColumnStretch(3, 1)
        self.hp_prof_note = label("", "hint", wrap=True)
        pr.addWidget(self.hp_prof_note, 1, 0, 1, 4)
        g.addWidget(self.hp_prof_row, 3, 2, 1, 3)
        self.hp_prof_row.setVisible(False)
        self.hp_sub.setText("Head unit")
        self.hp_sub.setToolTip(HEADPHONES_TIP)
        left.addWidget(w)

        left.addSpacing(6)
        dm = QHBoxLayout()
        dm.addWidget(label("Direct Mode", "sectionTitle"))
        dm.addWidget(info_button(DIRECT_TIP + ("" if C.restarts_stream_on_direct() else DIRECT_PAUSE_TIP)))
        dm.addStretch()
        left.addLayout(dm)
        dmr = QHBoxLayout()
        self.direct = ToggleSwitch()
        self.direct.toggled.connect(lambda on: self.ctx.set_direct(on))
        self.direct_lbl = label("", "bigValue")
        dmr.addWidget(self.direct)
        dmr.addWidget(self.direct_lbl)
        dmr.addStretch()
        left.addLayout(dmr)

        # optical (S/PDIF) out, on drivers that have it (Digital tab)
        self.optical_box = QWidget()
        ob = QVBoxLayout(self.optical_box)
        ob.setContentsMargins(0, 0, 0, 0)
        ob.setSpacing(8)
        oh = QHBoxLayout()
        oh.addWidget(label("Optical Out (S/PDIF)", "sectionTitle"))
        oh.addWidget(info_button(OPTICAL_TIP))
        oh.addStretch()
        ob.addLayout(oh)
        orow = QHBoxLayout()
        self.optical = ToggleSwitch()
        self.optical.toggled.connect(lambda on: self.card.set(C.OPTICAL_OUT, on))
        self.optical_lbl = label("", "bigValue")
        orow.addWidget(self.optical)
        orow.addWidget(self.optical_lbl)
        orow.addStretch()
        ob.addLayout(orow)
        self.optical_note = label("", "hint", wrap=True)
        ob.addWidget(self.optical_note)
        ob.addSpacing(6)
        ob.addWidget(label("Audio Quality", "sectionTitle"))
        self.optical_quality = label("", "bigValue")
        ob.addWidget(self.optical_quality)
        ob.addWidget(label(
            "A separate playback output: stereo, 24-bit, 44.1–192 kHz. It bypasses the DSP, "
            "so SBX and the EQ aren't on it, and the volume knob doesn't change it — app "
            "volume does. Set the level on your receiver.", "hint", wrap=True))
        ob.addSpacing(6)
        ob.addWidget(label("Playback device", "sectionTitle"))
        orow2 = QHBoxLayout()
        self.optical_dev = label("—", "bigValue")
        self.optical_default = QPushButton("Set Default")
        self.optical_default.setMinimumWidth(150)
        self.optical_default.clicked.connect(self._make_optical_default)
        orow2.addWidget(self.optical_dev)
        orow2.addStretch()
        orow2.addWidget(self.optical_default)
        ob.addLayout(orow2)
        self.optical_box.setVisible(False)
        digital.addWidget(self.optical_box)
        self.optical_missing = label("Optical out and in need driver v0.8.0 or newer.", "muted", wrap=True)
        digital.addWidget(self.optical_missing)
        digital.addStretch()

        right = QVBoxLayout()
        right.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.diagram = SpeakerDiagram()
        right.addWidget(self.diagram, 0, Qt.AlignHCenter)
        self.test = QPushButton("Test")
        self.test.setFixedWidth(120)
        self.test.clicked.connect(self._test)
        right.addWidget(self.test, 0, Qt.AlignHCenter)
        self.diagram.clicked.connect(self._test_one)
        self.test_hint = label("", "muted")
        self.test_hint.setAlignment(Qt.AlignCenter)
        right.addWidget(self.test_hint, 0, Qt.AlignHCenter)
        ctx.tone.step.connect(self._tone_step)

        grid.addLayout(left, 0, 0)
        grid.addLayout(right, 0, 1)

        # Filters / quality
        fl = QVBoxLayout()
        fh = QHBoxLayout()
        fh.addWidget(label("Filters", "sectionTitle"))
        fh.addStretch()
        fh.addWidget(info_button(
            "The ES9038 DAC's digital filter. Fast roll-off is flatter up to 20 kHz; "
            "slow roll-off rings less. Default keeps the filter Windows starts with."))
        fl.addLayout(fh)
        self.filter = QComboBox()
        self.filter.activated.connect(lambda i: self.card.set(C.DAC_FILTER, self.filter.itemData(i)))
        fl.addWidget(self.filter)
        ql = QVBoxLayout()
        qh = QHBoxLayout()
        qh.addWidget(label("Audio Quality", "sectionTitle"))
        qh.addStretch()
        qh.addWidget(info_button(
            "The sample rate PipeWire runs the card at, and the bit depth the card plays.\n\n"
            "Automatic follows what's playing. A fixed rate resamples everything to it.\n\n"
            "Direct Mode plays up to 384 kHz in stereo (44.1 and 88.2 kHz with driver "
            "0.9.4+, 176.4 kHz with 0.9.7+) and up to 192 kHz on a 5.1 stream. With "
            "Direct Mode off the DSP runs at 48 or 96 kHz (48 kHz only before driver "
            "0.9.4). A rate the card can't play right now moves to the nearest one it can, "
            "and your pick comes back when it can. 176.4 kHz and up also use a bigger "
            "buffer (PipeWire quantum), so they don't crackle.\n\n"
            "The bit depth applies when the card is opened; the app reopens it for you "
            "(a short gap).\n\n"
            "The rate is PipeWire's global clock (written to "
            "~/.config/pipewire/pipewire.conf.d/90-sbae9-sbc-rates.conf)."))
        ql.addLayout(qh)
        qrow = QHBoxLayout()
        self.quality = QComboBox()
        # the long "experimental" label shouldn't widen the column
        self.quality.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.quality.setMinimumContentsLength(15)
        self.quality.view().setMinimumWidth(300)
        self.quality.activated.connect(self._quality)
        qrow.addWidget(self.quality, 1)
        self.depth = QComboBox()
        self.depth.activated.connect(self._depth)
        self.depth.setMaximumWidth(110)
        qrow.addWidget(self.depth, 0)
        ql.addLayout(qrow)
        self.rate_note = label("", "muted", wrap=True)
        ql.addWidget(self.rate_note)
        self.now_playing = label("", "muted")
        ql.addWidget(self.now_playing)
        fl.addWidget(label("", "muted"))
        grid.addLayout(fl, 1, 0, Qt.AlignTop)
        grid.addLayout(ql, 1, 1, Qt.AlignTop)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        self.lay.addLayout(grid)
        self.lay.addStretch()
        ctx.pw.updated.connect(self._on_pw)

    def _speaker_cfg(self, i):
        """User picked a speaker layout: set it on the card, then match the stream.
        Only user picks switch the profile; driver changes to Speaker Config
        (it follows the stream itself) just refresh the view."""
        k = self.spk_cfg.itemData(i)
        if k != self.card.get(C.SPEAKER_CFG):
            self.ctx.set_speaker_cfg(k)
        items = self.card.items(C.SPEAKER_CFG)
        if 0 <= k < len(items):
            self._switch_stream(items[k] in SURROUND_CFGS)

    def _switch_stream(self, surround):
        if self.ctx.set_stream_layout(surround):
            # the dump lags behind; hold the shown choice until it catches up
            self._stream_pending = (surround, time.monotonic())

    def _make_default(self):
        n = self.ctx.pw.nodes
        if n.sink:
            pipewire.set_default(n.sink["id"])
            self.ctx.pw.refresh()

    def _make_optical_default(self):
        n = self.ctx.pw.nodes
        if n.optical_out:
            pipewire.set_default(n.optical_out["id"])
            self.ctx.pw.refresh()

    def _test(self):
        if self.ctx.tone.running:
            self.ctx.tone.stop()
            return
        self._play_test(self.test_channels())

    def _test_one(self, ch):
        self._play_test([ch])

    def _play_test(self, chans):
        n = self.ctx.pw.nodes
        self.ctx.tone.start(n.sink["name"] if n.sink else None, chans,
                            n.stream_layout() == "surround")

    def test_channels(self):
        """Speakers that can be tested on their own: all of the layout on a 5.1
        stream; left and right on a stereo one (the DSP makes the rest)."""
        if self.ctx.pw.nodes.stream_layout() == "surround" or self.diagram.mode == "headphones":
            spk = self.diagram_speakers() if self.diagram.mode != "headphones" else {"left", "right"}
            return [c for c in TONE_ORDER if c in spk]
        return ["left", "right"]

    def diagram_speakers(self):
        cfg = self.diagram.config or "2.0"
        spk = {"left", "right"}
        if cfg == "5.1":
            spk.add("center")
        if cfg in SURROUND_CFGS:
            spk |= {"rear-left", "rear-right"}
        if cfg.endswith(".1"):
            spk.add("sub")
        return spk

    def _tone_step(self, ch):
        self.diagram.set_state(playing=ch)
        self.test.setText("Stop" if ch else "Test")

    def _quality(self, i):
        self.ctx.settings["rate_mode"] = self.quality.itemData(i)
        self.ctx.apply_rate(user=True)
        self.refresh()

    def _depth(self, i):
        k = self.depth.itemData(i)
        if k is None or not self.card.has(C.BIT_DEPTH) or k == self.card.get(C.BIT_DEPTH):
            return
        self.ctx.set_bit_depth(k)

    def _refresh_quality(self, n):
        ctx = self.ctx
        rates = ctx.active_rates()
        dragons = ctx.dragons_available()
        choice = ctx.settings["rate_mode"] or 0
        # show what PipeWire is forced to now, whoever set it (0 = Automatic)
        eff = pipewire.current_force_rate()
        offered = pipewire.card_rates(C.module_param("pcm_rates") or "1", C.plays_176k4())
        if C.module_param("pcm_rates") == "0":
            offered = pipewire.RATES      # listed, greyed out: Settings can turn them on
        if [self.quality.itemData(k) for k in range(1, self.quality.count())] != offered:
            self.quality.clear()
            self.quality.addItem("", 0)
            for r in offered:
                self.quality.addItem(f"{r / 1000:g} kHz", r)
        model = self.quality.model()
        auto = ctx.rate_set()       # Automatic never reaches the experimental rate
        span = f"{min(auto) / 1000:g}" if len(auto) == 1 else f"{min(auto) / 1000:g}–{max(auto) / 1000:g}"
        self.quality.setItemText(0, f"Auto ({span} kHz)")
        for k in range(1, self.quality.count()):
            r = self.quality.itemData(k)
            exp = dragons and r == 96000
            stereo_only = r in pipewire.CD_RATES or r == 384000
            self.quality.setItemText(k, f"{r / 1000:g} kHz" + (" (experimental: here be dragons)" if exp else ""))
            model.item(k).setEnabled(r in rates or exp)
            model.item(k).setToolTip("Stereo only" if stereo_only and n.stream_layout() == "surround" else "")
        i = self.quality.findData(eff)
        self.quality.setCurrentIndex(i if i >= 0 else 0)

        direct = bool(self.card.get(C.DIRECT, True)) if self.card.present else True
        note = ""
        if C.module_param("pcm_rates") == "0":
            note = "High rates are off in the driver (pcm_rates=0; see Settings → Device)."
        elif not direct:
            note = "DSP mode runs at 48 or 96 kHz." if C.dsp_96k() else "DSP mode runs at 48 kHz."
        elif n.stream_layout() == "surround":
            note = f"5.1 plays at {'/'.join(f'{r / 1000:g}' for r in ctx.rate_set())} kHz"
            stereo = [r for r in offered if r not in ctx.rate_set()]
            note += (f"; {'/'.join(f'{r / 1000:g}' for r in stereo)} kHz are stereo only." if stereo else ".")
            if dragons:
                note += (" 96 kHz is experimental: it stutters more and more as it plays, "
                         "and needs a Windows capture to fix.")
        outside = bool(eff) and eff != pipewire.effective_rate(choice, rates)
        if choice and choice not in rates and note and not outside:
            note += f" Your {choice / 1000:g} kHz comes back when it can."
        if outside:
            note = (note + " " if note else "") + f"PipeWire is set to {eff / 1000:g} kHz outside the app."
        if self.ctx.depth_pending:
            note = (note + " " if note else "") + "New bit depth applies to the next stream."
        self.rate_note.setText(note)
        self.rate_note.setVisible(bool(note))

        # bit depth: a card control on newer drivers, else the module option
        items = self.card.items(C.BIT_DEPTH) if self.card.has(C.BIT_DEPTH) else []
        if items:
            if [self.depth.itemText(k) for k in range(self.depth.count())] != items:
                self.depth.clear()
                for k, it in enumerate(items):
                    self.depth.addItem(it, k)
            self.depth.setCurrentIndex(self.card.get(C.BIT_DEPTH, 0) or 0)
            self.depth.setEnabled(True)
            self.depth.setToolTip("Bit depth the card plays; the app reopens the card to apply it")
            bits = items[self.card.get(C.BIT_DEPTH, 0) or 0]
        else:
            bits = f"{C.module_param('pcm_bits') or '24'}-bit"
            self.depth.clear()
            self.depth.addItem(bits, None)
            self.depth.setEnabled(False)
            self.depth.setToolTip("Set by the driver's pcm_bits option; newer drivers let you "
                                  "change it here")

        live = pipewire.card_stream()
        if live:
            rate, ch = live
            chans = {1: "mono", 2: "stereo", 6: "5.1"}.get(ch, f"{ch} ch")
            self.now_playing.setText(f"Running now: {rate / 1000:g} kHz · {bits} · {chans}")
        else:
            self.now_playing.setText("Idle")

    def refresh(self):
        n = self.ctx.pw.nodes
        self.dev_name.setText("Sound Blaster AE-9" if n.sink else "AE-9 not found in PipeWire")
        self.set_default.setEnabled(bool(n.sink) and not n.sink_is_default)
        self.set_default.setText("Default device" if n.sink_is_default else "Set Default")
        self.default_ok.setPixmap(icons.pixmap("check", T.ACCENT_HI if n.sink_is_default else T.DIM, 22))
        self._refresh_quality(n)

        layout = n.stream_layout()
        if self._stream_pending:
            want, t = self._stream_pending
            if (layout == "surround") == want or time.monotonic() - t > 6:
                self._stream_pending = None
            else:
                layout = "surround" if want else "stereo"
        self.stream.setVisible(n.can_switch_layout())
        self.stream.setEnabled(layout is not None)
        self.stream.setCurrentIndex(1 if layout == "surround" else 0)
        self.stream.setToolTip(STREAM_TIP if layout or not n.card_profile() else
                               f"Card profile: {n.card_profile()} (set elsewhere; left alone)")

        if not self.card.present:
            return
        out = self.card.get(C.OUTPUT, 0)
        (self.r_hp if out == 1 else self.r_spk).setChecked(True)
        if self.card.has(C.HU_PHONES):
            self.hp_sub.setText("Plugged In" if self.card.get(C.HU_PHONES) else "Unplugged")
        else:
            self.hp_sub.setText("Head unit")
        self.hp_auto_row.setVisible(self.card.has(C.HU_AUTO))
        if self.card.has(C.HU_AUTO):
            self.hp_auto.setCheckedSilently(bool(self.card.get(C.HU_AUTO)))
        self._refresh_hp_profile(out)
        cfg = self.card.get_item(C.SPEAKER_CFG) or "2.1"
        if self.spk_cfg.count() != len(self.card.items(C.SPEAKER_CFG)):
            self.spk_cfg.clear()
            for k, it in enumerate(self.card.items(C.SPEAKER_CFG)):
                self.spk_cfg.addItem(f"{it} Speakers", k)
        self.spk_cfg.setCurrentIndex(self.card.get(C.SPEAKER_CFG, 0) or 0)
        direct = bool(self.card.get(C.DIRECT, True))
        self.spk_cfg.setEnabled(not direct)
        # In Direct Mode the DSP (and Speaker Config) is bypassed: the stream's
        # channels go straight to the outputs.
        shown = ("5.1" if layout == "surround" else "2.0") if direct else cfg
        stream_txt = "5.1 Stream" if layout == "surround" else "Stereo Stream" if layout else ""
        self.spk_sub.setText(" · ".join(x for x in (
            SPEAKER_TEXT.get(shown, shown), stream_txt) if x))
        self.spk_sub.setToolTip(SPEAKER_JACKS.get(shown, ""))
        self.diagram.set_state(mode="headphones" if out == 1 else "speakers", config=shown)
        self.diagram.clickable = set(self.test_channels())
        what = "says each speaker's name" if pipewire.voices_available() else "plays a tone on each speaker"
        hint = f"Test {what};\nclick a speaker to test just that one"
        if not pipewire.voices_available():
            hint += "\n(install alsa-utils for spoken names)"
        self.test_hint.setText(hint)
        self.direct.setCheckedSilently(direct)
        self.direct_lbl.setText("On — DSP bypassed" if direct else "Off — SBX / EQ active")
        self._refresh_optical(layout)
        self.setup.refresh()
        names = {"Default": "Default (Windows startup filter)", "Fast": "Fast Roll Off",
                 "Slow": "Slow Roll Off"}
        if self.filter.count() != len(self.card.items(C.DAC_FILTER)):
            self.filter.clear()
            for k, it in enumerate(self.card.items(C.DAC_FILTER)):
                self.filter.addItem(names.get(it, it), k)
        self.filter.setCurrentIndex(self.card.get(C.DAC_FILTER, 0) or 0)

    def _refresh_hp_profile(self, out):
        has = self.card.has(C.HP_PROFILE)
        self.hp_prof_row.setVisible(has)
        if not has:
            return
        items = self.card.items(C.HP_PROFILE)
        if [self.hp_prof.itemText(k) for k in range(self.hp_prof.count())] != items:
            self.hp_prof.clear()
            self.hp_prof.addItems(items)
        k = self.card.get(C.HP_PROFILE, 0) or 0
        self.hp_prof.setCurrentIndex(k)
        curves = C.headphone_curves()
        direct = bool(self.card.get(C.DIRECT, True)) or self.card.inactive(C.HP_PROFILE)
        self.hp_prof.setEnabled(bool(curves) and not direct)
        live = pipewire.card_stream()
        if not curves:
            note = ("Needs Creative's headphone curves: run sudo ae9-get-firmware "
                    "AECMDMasterInstaller_3.4.92.00.exe (Creative's Sound Blaster Command "
                    "installer for the AE-9).")
        elif direct:
            note = "Works with Direct Mode off."
        elif k and out != 1:
            note = "Acts when the output is Headphones."
        elif k and live and live[0] != 48000:
            note = f"Acts at 48 kHz; the card is playing at {live[0] / 1000:g} kHz now."
        else:
            note = ""
        self.hp_prof_note.setText(note)
        self.hp_prof_note.setVisible(bool(note))

    def _refresh_optical(self, layout):
        has = self.card.has(C.OPTICAL_OUT)
        self.optical_box.setVisible(has)
        self.optical_missing.setVisible(not has)
        if not has:
            return
        n = self.ctx.pw.nodes
        on = bool(self.card.get(C.OPTICAL_OUT))
        self.optical.setCheckedSilently(on)
        self.optical_lbl.setText("On" if on else "Off")
        fmt = n.optical_out_format()
        if n.optical_out and n.optical_out.get("state") == "running" and fmt:
            rate, _ = fmt
            self.optical_quality.setText(f"{rate / 1000:g} kHz · 24-bit · stereo")
        else:
            self.optical_quality.setText("Nothing playing")
        self.optical_dev.setText("Sound Blaster AE-9 Optical" if n.optical_out
                                 else "Optical output not found in PipeWire")
        self.optical_default.setEnabled(bool(n.optical_out) and not n.optical_out_is_default)
        self.optical_default.setText("Default device" if n.optical_out_is_default else "Set Default")
        if on:
            self.optical_note.setText("Separate output: stereo, 24-bit, 44.1–192 kHz. "
                                      "No SBX/EQ; app volume applies, the knob doesn't.")
        else:
            self.optical_note.setText("Off: the optical output is silent.")
        self.optical_note.setStyleSheet("")


DIRECT_TIP = ("Direct Mode sends audio straight to the ESS DAC at the stream's own sample rate "
              "(up to 384 kHz), bypassing the DSP. SBX effects and the EQ are not heard.\n\n"
              "With Direct Mode off, audio goes through the Sound Core3D DSP at 48 or 96 kHz "
              "(48 kHz only before driver 0.9.4), so SBX, the EQ and Scout Mode work.")
# drivers before 0.9.4 don't restart a playing stream when Direct Mode turns on
DIRECT_PAUSE_TIP = ("\n\nSwitching Direct Mode on during playback goes silent until the stream "
                    "restarts (pause and play), same as on Windows.")

OPTICAL_TIP = ("Optical (S/PDIF) out is a separate playback output on its own PCM. Pick it "
               "as the playback device to send audio to a receiver or another device.\n\n"
               "It carries a stereo, 24-bit stream at 44.1–192 kHz, straight from the source: "
               "no SBX or EQ, and the card's Master volume (and knob) doesn't change it — app "
               "volume does. Set the level on the receiver.")

SURROUND_CFGS = ("4.0", "4.1", "5.1")
MIC_NAME = "AE-9 Head Unit Mic / Aux"


def mic_name(node):
    """The mic's name to show: the desktop's if it's a short AE-9 one (the
    driver's naming config gives it "AE-9 Head Unit Mic / Aux"), else that
    name, not PipeWire's long default ("CA0132 Sound Core3D [...] Analog Stereo")."""
    desc = (node or {}).get("description") or ""
    return desc if desc.startswith("AE-9") and len(desc) <= 40 else MIC_NAME


# driver options shown read-only on Settings → Device
DEVICE_PARAMS = ("pcm_rates", "pcm_bits", "dac_441", "surround", "surround_96k", "surround_192k",
                  "dsp_96k", "wuh_96k", "pcm_176k4", "src_reclock")

INPUT_RATES = (48000, 96000)   # What U Hear: 48, or 96 kHz with the driver's wuh_96k


def confirm_pipewire_restart(parent, what):
    return QMessageBox.question(
        parent, f"Change the {what} sample rate?",
        "This restarts PipeWire, so audio on every device drops for a moment "
        "(music, calls, everything).\n\nChange it now?") == QMessageBox.Yes


PHANTOM_TIP = ("48 V phantom power for the head unit's XLR/TRS jack, for condenser mics "
               "that need it. The head unit's own button switches it too.")
PHANTOM_ARM_MS = 3000      # two-click mode: how long the first click stays armed
PHANTOM_ERRORS = {
    errno.EBUSY: "Phantom power can't be switched on yet (card just started); "
                 "try again in a few seconds.",
    errno.EAGAIN: "The head unit hasn't reported in yet; try again in a moment.",
}


def confirm_phantom(parent):
    """The warning before phantom power goes on (the default)."""
    box = QMessageBox(QMessageBox.Warning, "Phantom power",
                      "Phantom power puts 48 V on the head unit's XLR/TRS jack. It can damage "
                      "some equipment (ribbon mics, some line-level sources). Only turn it on for "
                      "condenser mics that need it.\n\nTurn on?", QMessageBox.NoButton, parent)
    yes = box.addButton("Turn on", QMessageBox.AcceptRole)
    box.setDefaultButton(box.addButton(QMessageBox.Cancel))
    box.exec()
    return box.clickedButton() is yes


HP_PROFILE_TIP = ("Creative's EQ correction for your headphone model, the same curves as "
                  "Sound Blaster Command on Windows.\n\n"
                  "It acts with Direct Mode off, on Headphones, while the card plays at 48 kHz. "
                  "On speakers it rests, and comes back when you switch to headphones.\n\n"
                  "The card loads a curve about a second after you stop on it (driver 0.10.1+). "
                  "If loading fails, that profile's EQ stays off, so audio stays clean, and the "
                  "kernel log says why.\n\n"
                  "The curves are Creative's and aren't shipped with the driver: "
                  "ae9-get-firmware installs them from Creative's installer "
                  "(AECMDMasterInstaller_3.4.92.00.exe).")
HEADPHONES_TIP = ("The head unit's headphone jacks, 3.5 mm and 1/4\". "
                  "\"Plugged In\" is the 3.5 mm jack; the 1/4\" doesn't report plugs.")
STREAM_TIP = ("Channels PipeWire sends to the card (its card profile). Picking 4.0, 4.1 or 5.1 "
              "speakers switches to the 5.1 stream, 2.0 or 2.1 back to stereo. The sound "
              "pauses for a moment while the stream reopens.")

TONE_ORDER = ["left", "center", "right", "rear-right", "rear-left", "sub"]
SPEAKER_TEXT = {
    "2.0": "2.0 Stereo",
    "2.1": "2.1 Stereo + Sub",
    "4.0": "4.0 Quad",
    "4.1": "4.1 Quad + Sub",
    "5.1": "5.1 Surround",
}
# which of the card's outputs each layout uses (shown on hover)
SPEAKER_JACKS = {
    "2.0": "The card's RCA out",
    "2.1": "The card's RCA out",
    "4.0": "The card's RCA out and 3.5 mm Rear out",
    "4.1": "The card's RCA out, 3.5 mm C/Sub out and 3.5 mm Rear out",
    "5.1": "The card's RCA out, 3.5 mm C/Sub out and 3.5 mm Rear out",
}


BASS_REDIRECT_TIP = (
    "Bass Redirect sends the low end of every speaker to the subwoofer, below the "
    "crossover frequency. It's meant for x.1 setups: on speakers without a sub it just "
    "thins the sound.\n\n"
    "Speaker Type sets the crossover as Sound Blaster Command does on Windows: Tower "
    "speakers keep their bass down to 80 Hz, Desktop speakers hand it over below 120 Hz. "
    "Custom picks any frequency from 50 to 200 Hz.\n\n"
    "Subwoofer boost turns up the redirected bass (Creative's subwoofer boost, on or off).")
CALIBRATION_TIP = (
    "Level raises or lowers one speaker, from -12 to +12 dB, to even out a setup where "
    "some speakers are louder than others.\n\n"
    "Distance delays a speaker by the time sound takes to travel that far (10 cm is about "
    "0.29 ms). Set it on the speakers that are closer to you than the farthest one, by the "
    "difference, so everything reaches you at the same time.\n\n"
    "Only the speakers in your Speaker Config can be set. The DSP does this, so it works "
    "with Direct Mode off (SBX on or off).")
# the speakers each Speaker Config plays on
CONFIG_CHANNELS = {
    "2.0": ("Front L", "Front R"),
    "2.1": ("Front L", "Front R", "Sub"),
    "4.0": ("Front L", "Front R", "Rear L", "Rear R"),
    "4.1": ("Front L", "Front R", "Sub", "Rear L", "Rear R"),
    "5.1": tuple(C.SPEAKER_CHANNELS),
}
CHANNEL_LABELS = {"Front L": "Front Left", "Front R": "Front Right", "Center": "Center",
                  "Sub": "Subwoofer", "Rear L": "Rear Left", "Rear R": "Rear Right"}


def db_text(db):
    return f"{db:+d} dB" if db else "0 dB"


class SpeakerSetup(QWidget):
    """Playback → Speaker Setup: bass redirect and per-speaker level and
    distance (driver controls; the DSP does them, so not in Direct Mode)."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.card = ctx, ctx.card
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.direct_banner = Banner("Speaker setup is done by the DSP, so it works with "
                                    "Direct Mode off. Your settings are kept for then.",
                                    "Turn Direct Mode off")
        self.direct_banner.button.clicked.connect(lambda: self.ctx.set_direct(False))
        lay.addWidget(self.direct_banner)

        self.box = QWidget()
        bl = QVBoxLayout(self.box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(10)

        # bass redirect
        h = QHBoxLayout()
        self.redirect = ToggleSwitch()
        self.redirect.toggled.connect(lambda on: self.card.set(C.BASS_REDIRECT, on))
        h.addWidget(self.redirect)
        h.addWidget(label("Bass Redirect", "sectionTitle"))
        h.addWidget(info_button(BASS_REDIRECT_TIP))
        h.addStretch()
        bl.addLayout(h)
        self.redirect_note = label("", "hint", wrap=True)
        bl.addWidget(self.redirect_note)
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(8)
        g.addWidget(label("Speaker Type", "muted"), 0, 0)
        self.spk_type = QComboBox()
        for name, hz in C.SPEAKER_TYPES.items():
            self.spk_type.addItem(f"{name} ({hz} Hz)", hz)
        self.spk_type.addItem("Custom", None)
        self.spk_type.setMinimumWidth(170)
        self.spk_type.activated.connect(self._pick_type)
        g.addWidget(self.spk_type, 0, 1)
        g.addWidget(label("Crossover", "muted"), 1, 0)
        self.xover = QSlider(Qt.Horizontal)
        self.xover.setRange(5, 20)          # in 10 Hz steps
        self.xover.setPageStep(1)
        self.xover.valueChanged.connect(self._xover_moved)
        self._xover_set = Throttle(lambda hz: self.card.set(C.BASS_XOVER, hz), 60)
        g.addWidget(self.xover, 1, 1)
        self.xover_val = label("", "muted")
        self.xover_val.setMinimumWidth(66)
        g.addWidget(self.xover_val, 1, 2)
        self.sub_boost = QCheckBox("Subwoofer boost")
        self.sub_boost.toggled.connect(self._set_sub_boost)
        g.addWidget(self.sub_boost, 2, 0, 1, 2)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        self.redirect_grid = QWidget()
        self.redirect_grid.setLayout(g)
        bl.addWidget(self.redirect_grid)

        # calibration
        bl.addSpacing(8)
        h = QHBoxLayout()
        h.addWidget(label("Speaker Calibration", "sectionTitle"))
        h.addWidget(info_button(CALIBRATION_TIP))
        h.addStretch()
        self.reset = QPushButton("Reset")
        self.reset.setToolTip("Every speaker back to 0 dB and 0 cm")
        self.reset.clicked.connect(self._reset)
        h.addWidget(self.reset)
        bl.addLayout(h)
        cg = QGridLayout()
        cg.setHorizontalSpacing(14)
        cg.setVerticalSpacing(6)
        cg.addWidget(label("Level", "muted"), 0, 1, 1, 2)
        cg.addWidget(label("Distance", "muted"), 0, 3, 1, 2)
        self.rows = {}
        for r, ch in enumerate(C.SPEAKER_CHANNELS, 1):
            name = label(CHANNEL_LABELS[ch])
            lvl = QSlider(Qt.Horizontal)
            lvl.setRange(-12, 12)
            lvl.setPageStep(1)
            lvl.setMinimumWidth(160)
            lvl_val = label("", "muted")
            lvl_val.setMinimumWidth(56)
            lvl_set = Throttle(lambda db, ch=ch: self.card.set(C.speaker_level(ch), db), 60)
            lvl.valueChanged.connect(lambda v, t=lvl_val, f=lvl_set: (t.setText(db_text(v)), f(v)))
            dist = QSpinBox()
            dist.setRange(0, 500)
            dist.setSingleStep(10)
            dist.setSuffix(" cm")
            dist.setKeyboardTracking(False)
            dist.setMinimumWidth(100)
            delay = label("", "muted")
            delay.setMinimumWidth(70)

            def dist_changed(v, ch=ch, t=delay):
                t.setText(self._delay_text(v))
                self.card.set(C.speaker_distance(ch), v)
            dist.valueChanged.connect(dist_changed)
            for c, w in enumerate((name, lvl, lvl_val, dist, delay)):
                cg.addWidget(w, r, c)
            self.rows[ch] = (name, lvl, lvl_val, dist, delay)
        cg.setColumnStretch(1, 1)
        bl.addLayout(cg)
        self.layout_note = label("", "hint", wrap=True)
        bl.addWidget(self.layout_note)
        lay.addWidget(self.box)

        self.missing = label("Speaker setup (bass redirect, speaker levels and distances) "
                             "needs a newer SbAe9-Drv.", "muted", wrap=True)
        lay.addWidget(self.missing)
        lay.addStretch()
        self.refresh()

    @staticmethod
    def _delay_text(cm):
        return f"{cm * C.CM_DELAY_MS:.2f} ms" if cm else ""

    def available(self):
        return self.card.present and self.card.has(C.BASS_REDIRECT)

    def _pick_type(self, i):
        hz = self.spk_type.itemData(i)
        if hz is not None:
            self.card.set(C.BASS_XOVER, hz)
            self.refresh()

    def _xover_moved(self, v):
        hz = v * 10
        self.xover_val.setText(f"{hz} Hz")
        k = self.spk_type.findData(hz)
        self.spk_type.setCurrentIndex(k if k >= 0 else self.spk_type.count() - 1)
        self._xover_set(hz)

    def _set_sub_boost(self, on):
        if self.card.has(C.BASS_SUB_BOOST):
            self.card.set(C.BASS_SUB_BOOST, on)
        else:
            self.card.set(C.BASS_SUB_GAIN_OLD, C.SUB_BOOST_OLD_ON if on else 0)

    def _sub_boost_on(self):
        if self.card.has(C.BASS_SUB_BOOST):
            return bool(self.card.get(C.BASS_SUB_BOOST))
        return bool(self.card.get(C.BASS_SUB_GAIN_OLD, 0))

    def _reset(self):
        for ch in C.SPEAKER_CHANNELS:
            self.card.set(C.speaker_level(ch), 0)
            self.card.set(C.speaker_distance(ch), 0)
        self.refresh()

    @staticmethod
    def _show(widget, value):
        """Set a slider or spin box without writing it back to the card (and
        leave a slider alone while it's being dragged)."""
        if isinstance(widget, QSlider) and widget.isSliderDown():
            return
        widget.blockSignals(True)
        widget.setValue(value)
        widget.blockSignals(False)

    def refresh(self):
        has = self.available()
        self.box.setVisible(has)
        self.missing.setVisible(not has)
        if not has:
            self.direct_banner.setVisible(False)
            return
        card = self.card
        # the driver greys these out in Direct Mode; go by that, and by
        # Direct Mode itself for a driver that doesn't
        live = not card.get(C.DIRECT, True) and not card.inactive(C.BASS_REDIRECT)
        self.direct_banner.setVisible(not live)
        self.box.setEnabled(live)

        cfg = card.get_item(C.SPEAKER_CFG) or "2.1"
        on = bool(card.get(C.BASS_REDIRECT))
        self.redirect.setCheckedSilently(on)
        self.redirect_grid.setEnabled(on)
        self.redirect_note.setText(
            "" if cfg.endswith(".1") else
            f"Your Speaker Config is {cfg} (no sub): Bass Redirect would just thin the sound.")
        self.redirect_note.setVisible(bool(self.redirect_note.text()))
        hz = card.get(C.BASS_XOVER, 80) or 80
        self._show(self.xover, round(hz / 10))
        self.xover_val.setText(f"{hz} Hz")
        k = self.spk_type.findData(hz)
        self.spk_type.setCurrentIndex(k if k >= 0 else self.spk_type.count() - 1)
        self.sub_boost.setVisible(card.has(C.BASS_SUB_BOOST) or card.has(C.BASS_SUB_GAIN_OLD))
        self.sub_boost.blockSignals(True)
        self.sub_boost.setChecked(self._sub_boost_on())
        self.sub_boost.blockSignals(False)

        used = CONFIG_CHANNELS.get(cfg, C.SPEAKER_CHANNELS)
        for ch, (name, lvl, lvl_val, dist, delay) in self.rows.items():
            present = card.has(C.speaker_level(ch))
            for w in (name, lvl, lvl_val, dist, delay):
                w.setVisible(present)
                w.setEnabled(ch in used)
            tip = "" if ch in used else f"Not in your {cfg} Speaker Config"
            name.setToolTip(tip)
            db = card.get(C.speaker_level(ch), 0) or 0
            self._show(lvl, db)
            lvl_val.setText(db_text(db))
            cm = card.get(C.speaker_distance(ch), 0) or 0
            self._show(dist, cm)
            delay.setText(self._delay_text(cm))
        self.layout_note.setText(f"Speakers outside your {cfg} Speaker Config are greyed out; "
                                 "change it on the Speakers/Headphones tab."
                                 if len(used) < len(C.SPEAKER_CHANNELS) else "")
        self.layout_note.setVisible(bool(self.layout_note.text()))


class InputSection(QWidget):
    """One of the AE-9's extra recording devices (Recording → Other Input):
    its PipeWire source with Set Default, or how to set it up."""

    def __init__(self, key, title, default_name, device, about, conf, rate_choice=False):
        super().__init__()
        self.key, self.default_name, self.device = key, default_name, device
        self.about, self.conf, self.title = about, conf, title
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.setSpacing(6)
        lay.addWidget(label(title, "subTitle"))
        row = QHBoxLayout()
        self.name = label("", "sectionTitle")
        row.addWidget(self.name)
        row.addStretch()
        self.set_default = QPushButton("Set Default")
        self.set_default.setMinimumWidth(150)
        self.set_default.clicked.connect(self._make_default)
        self.ok = QLabel()
        row.addWidget(self.set_default)
        row.addWidget(self.ok)
        lay.addLayout(row)
        # sample rate: set in the driver's PipeWire config for this input
        self.rate_row = QWidget()
        rr = QHBoxLayout(self.rate_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(10)
        rr.addWidget(label("Sample rate"))
        self.rate = QComboBox()
        self.rate.setMinimumWidth(130)
        for r in INPUT_RATES:
            self.rate.addItem(f"{r / 1000:g} kHz", r)
        self.rate.activated.connect(self._pick_rate)
        rr.addWidget(self.rate)
        rr.addStretch()
        lay.addWidget(self.rate_row)
        self.rate_row.setVisible(False)
        self.rate_choice = rate_choice
        self.conf_path = None
        self.note = label("", "hint", wrap=True)
        lay.addWidget(self.note)
        self.node = None
        self.setVisible(False)

    def _pick_rate(self, i):
        rate = self.rate.itemData(i)
        path = self.conf_path
        if not path or rate == pipewire.input_conf_rate(path):
            return
        ctx = getattr(self.window(), "ctx", None)
        if ctx is None or not confirm_pipewire_restart(self.window(), self.title):
            self._refresh_rate()
            return
        ctx.set_input_rate(self.key, path, rate, self.title)

    def _refresh_rate(self):
        self.conf_path = pipewire.input_conf(self.device)
        cur = pipewire.input_conf_rate(self.conf_path) if self.conf_path else None
        offered = INPUT_RATES if C.wuh_96k() else INPUT_RATES[:1]
        model = self.rate.model()
        for k in range(self.rate.count()):
            r = self.rate.itemData(k)
            model.item(k).setEnabled(r in offered)
            model.item(k).setToolTip("" if r in offered else "Needs driver 0.9.5 or newer")
        i = self.rate.findData(cur)
        self.rate.setCurrentIndex(i if i >= 0 else 0)
        self.rate.setEnabled(cur is not None and len(offered) > 1)
        if cur is None:
            self.rate.setToolTip(f"Set by a PipeWire config outside {pipewire.PW_CONF_DIR}; "
                                 f"change audio.rate in {self.conf} there")
        else:
            self.rate.setToolTip("Restarts PipeWire to apply: audio on every device drops for a "
                                 "moment" if len(offered) > 1 else "96 kHz needs driver 0.9.5 or newer")

    def _make_default(self):
        if self.node:
            pipewire.set_default(self.node["id"])
            w = self.window()
            ctx = getattr(w, "ctx", None)
            if ctx:
                ctx.pw.refresh()

    def refresh(self, n, card):
        """Show this input if PipeWire lists it or the driver has it. Returns
        whether it's shown."""
        self.node = getattr(n, self.key)
        has = bool(self.node) or C.has_capture_pcm(self.device) or (
            self.key == "optical_in" and card.has(C.OPTICAL_OUT))
        self.setVisible(has)
        if not has:
            return False
        found = bool(self.node)
        self.name.setText((self.node.get("description") or self.default_name) if found
                          else "Not set up in PipeWire")
        self.set_default.setVisible(found)
        self.ok.setVisible(found)
        self.rate_row.setVisible(found and self.rate_choice)
        if found and self.rate_choice:
            self._refresh_rate()
        if found:
            default = n.is_default_source(self.node)
            self.set_default.setEnabled(not default)
            self.set_default.setText("Default device" if default else "Set Default")
            self.ok.setPixmap(icons.pixmap("check", T.ACCENT_HI if default else T.DIM, 22))
            self.note.setText(self.about)
        else:
            self.note.setText(
                f"The driver has it, but PipeWire doesn't list it yet. Copy config/{self.conf} "
                "from the driver to ~/.config/pipewire/pipewire.conf.d/ and restart PipeWire "
                "(systemctl --user restart pipewire).")
        return True


# =====================================================================================
class RecordingPage(Page):
    title = "Recording"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header("Recording")
        self.lay, other = self.add_tabs(["Microphone", "Other Input"])
        dev = QHBoxLayout()
        dcol = QVBoxLayout()
        dcol.setSpacing(0)
        dcol.addWidget(label("Recording device:", "sectionTitle"))
        self.dev_name = label("—", "sectionTitle")
        dcol.addWidget(self.dev_name)
        dev.addLayout(dcol)
        dev.addStretch()
        self.set_default = QPushButton("Set Default")
        self.set_default.setMinimumWidth(150)
        self.set_default.clicked.connect(self._make_default)
        self.default_ok = QLabel()
        dev.addWidget(self.set_default)
        dev.addWidget(self.default_ok)
        self.lay.addLayout(dev)

        g = QGridLayout()
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(14)
        mic_title = label("Microphone", "subTitle")
        mic_title.setToolTip("The head unit's XLR/TRS jack and 3.5 mm mic jack (they share this input)")
        g.addWidget(mic_title, 0, 0, 1, 3)
        g.addWidget(label("Level"), 1, 0)
        self.mic = VolumeRow("mic", "mic-off")
        self.mic.valueChanged.connect(Throttle(lambda v: self.card.set(C.MIC, round(v * 99)), 40))
        self.mic.muteToggled.connect(self._mute)
        g.addWidget(self.mic, 1, 1, 1, 2)
        g.addWidget(label("Input"), 2, 0)
        meters = QVBoxLayout()
        meters.setSpacing(5)
        self.meter_l, self.meter_r = LevelBar(), LevelBar()
        meters.addWidget(self.meter_l)
        meters.addWidget(self.meter_r)
        g.addLayout(meters, 2, 1)
        self.peak = label("", "muted")
        self.peak.setMinimumWidth(66)
        g.addWidget(self.peak, 2, 2)
        g.addWidget(label("Mic Gain"), 3, 0)
        self.xlr = Segmented(["0", "1", "2"], labels={"0": "0 dB", "1": "+10 dB", "2": "+20 dB"})
        self.xlr.selected.connect(lambda v: self.card.set(C.MIC_GAIN, int(v)))
        xr = QHBoxLayout()
        xr.addWidget(self.xlr)
        xr.addWidget(info_button("Mic preamp boost for the head unit's XLR/TRS jack and 3.5 mm mic "
                                 "jack (they share one input). Use +20 dB for quiet "
                                 "dynamic mics, 0 dB for loud sources or condensers."))
        xr.addStretch()
        g.addLayout(xr, 3, 1)
        g.addWidget(label("Listen"), 4, 0)
        lr = QHBoxLayout()
        lr.setSpacing(12)
        self.listen = ToggleSwitch()
        self.listen.toggled.connect(self._listen)
        lr.addWidget(self.listen)
        listen_lbl = label("Hear the mic live (use headphones to avoid feedback)", "muted")
        listen_lbl.setToolTip("Plays the mic through the default output")
        lr.addWidget(listen_lbl)
        lr.addStretch()
        g.addLayout(lr, 4, 1, 1, 2)
        g.addWidget(label("Quality"), 5, 0)
        qr = QHBoxLayout()
        qr.setSpacing(10)
        self.mic_rate = QComboBox()
        self.mic_rate.setMinimumWidth(180)
        self.mic_rate.activated.connect(self._mic_rate)
        qr.addWidget(self.mic_rate)
        self.mic_depth = QComboBox()
        self.mic_depth.activated.connect(self._mic_depth)
        self.mic_depth.setMinimumWidth(110)
        qr.addWidget(self.mic_depth)
        qr.addWidget(info_button(
            "The sample rate the card records the head unit's mic input at.\n\n"
            "Automatic lets PipeWire pick (it follows the playback side, usually 48 kHz). "
            "A fixed rate makes the input open at that rate whatever else plays.\n\n"
            "96 kHz needs driver 0.9.1 or newer. Changing the rate restarts WirePlumber, so "
            "audio on every device drops for a moment, and a recording already running keeps "
            "its old rate until it starts again.\n\n"
            "Bit depth: 24-bit, or with driver 0.9.1 or newer also 32-bit, as Windows offers. "
            "32-bit gives full 32-bit samples from the card's DSP; it sounds the same as "
            "24-bit in practice. It applies from the next recording."))
        qr.addStretch()
        g.addLayout(qr, 5, 1, 1, 2)
        self.mic_now = label("", "muted")
        g.addWidget(self.mic_now, 6, 1, 1, 2)
        # Phantom power: a button on drivers that can switch it, else just its state.
        # Always the live state: the app never turns it on by itself.
        self.phantom_lbl = label("Phantom")
        g.addWidget(self.phantom_lbl, 7, 0)
        pr = QHBoxLayout()
        pr.setSpacing(12)
        self.phantom_btn = QPushButton("Phantom Power 48V")
        self.phantom_btn.setObjectName("phantomButton")
        self.phantom_btn.setMinimumWidth(190)
        self.phantom_btn.setToolTip(PHANTOM_TIP)
        self.phantom_btn.clicked.connect(self._phantom_click)
        pr.addWidget(self.phantom_btn)
        self.phantom = label("", "muted")
        self.phantom.setToolTip(PHANTOM_TIP)
        pr.addWidget(self.phantom)
        pr.addStretch()
        g.addLayout(pr, 7, 1, 1, 2)
        self.phantom_note = label("", "muted", wrap=True)
        self.phantom_note.setStyleSheet(f"color:{T.DANGER};")
        g.addWidget(self.phantom_note, 8, 1, 1, 2)
        for w in (self.phantom_lbl, self.phantom_btn, self.phantom, self.phantom_note):
            w.setVisible(False)
        self._phantom_armed = False
        self._arm_timer = QTimer(self, singleShot=True, interval=PHANTOM_ARM_MS)
        self._arm_timer.timeout.connect(self._phantom_disarm)
        self._blink = QTimer(self, interval=400)
        self._blink.timeout.connect(self._phantom_blink)
        self._blink_on = False
        self._note_timer = QTimer(self, singleShot=True, interval=8000)
        self._note_timer.timeout.connect(lambda: self._phantom_say(""))
        g.setColumnStretch(1, 1)
        self.lay.addLayout(g)
        self.lay.addSpacing(8)
        self.mic_hint = label("", "hint", wrap=True)
        self.lay.addWidget(self.mic_hint)
        self.mic_jack = label("", "muted")
        self.mic_jack.setVisible(False)
        self.lay.addWidget(self.mic_jack)

        self.lay.addStretch()

        # extra inputs: each its own device, recording alongside the mic
        self.inputs = [
            InputSection("optical_in", "Optical In (S/PDIF)", "AE-9 Optical In", 1,
                         "Records alongside the head unit mic, as its own device: pick it in your "
                         "recording app. S/PDIF can't be resampled, so it opens at the sender's "
                         "rate (44.1–192 kHz) and won't open at all without a signal.",
                         "ae9-optical-in.conf"),
            InputSection("what_u_hear", "What U Hear", "AE-9 What U Hear", 2,
                         "Records what the card plays: games, music, calls, all of it, at "
                         "48 or 96 kHz (96 kHz with driver 0.9.5+). Handy for streaming or "
                         "capturing the card's own output. With SBX on you get the effects too; "
                         "with SBX off it's the stream exactly as sent.",
                         "ae9-what-u-hear.conf", rate_choice=True),
            InputSection("rear_rca", "Head unit rear RCA", "AE-9 Rear RCA In", 3,
                         "The RCA L/R jacks on the back of the head unit (Creative calls this "
                         "input Aux). Records alongside the mic, as its own device, at 44.1 to "
                         "192 kHz. There's no level control yet, and the level is low: about "
                         "-45 dBFS for a -20 dBFS source.",
                         "ae9-rear-rca-in.conf"),
        ]
        for sec in self.inputs:
            other.addWidget(sec)
        self.other_none = label("No other inputs on this driver yet: optical in needs v0.8.0 or "
                                "newer, What U Hear v0.9.0 or newer, the head unit rear RCA "
                                "v0.10.1 or newer.", "muted", wrap=True)
        other.addWidget(self.other_none)
        other.addStretch()
        ctx.meter.levels.connect(self._levels)
        ctx.monitor.state.connect(self.listen.setCheckedSilently)
        ctx.pw.updated.connect(self._on_pw)

    def _make_default(self):
        n = self.ctx.pw.nodes
        if n.source:
            pipewire.set_default(n.source["id"])
            self.ctx.pw.refresh()

    # --- phantom power ------------------------------------------------------
    def _refresh_phantom(self):
        has = self.card.has(C.HU_PHANTOM)
        writable = has and self.card.writable(C.HU_PHANTOM)
        on = bool(self.card.get(C.HU_PHANTOM)) if has else False
        self.phantom_lbl.setVisible(has)
        self.phantom.setVisible(has)
        self.phantom_btn.setVisible(writable)
        if not writable or on:
            self._phantom_disarm(restyle=False)
        if writable:
            self.phantom.setText("On — 48 V on the XLR/TRS jack" if on else "Off")
        else:
            self.phantom.setText(("On" if on else "Off") + " — switched by the head unit's button")
        self._phantom_style(on)
        jacks = "The head unit's XLR/TRS and 3.5 mm mic jacks share this input."
        self.mic_hint.setText(jacks if writable else
                              "Phantom power (48V) is the button on the head unit. " + jacks)

    def _phantom_style(self, on):
        b = self.phantom_btn
        if self._phantom_armed:
            edge = T.DANGER if self._blink_on else "transparent"
            b.setText("Click again to turn on")
            b.setStyleSheet(f"QPushButton#phantomButton {{ background: {T.PANEL}; "
                            f"border: 2px solid {edge}; color: {T.DANGER}; font-weight: 700; }}")
        else:
            b.setText("Phantom Power 48V")
            b.setStyleSheet(f"QPushButton#phantomButton {{ background: {T.DANGER}; color: #ffffff; "
                            "font-weight: 700; }" if on else "")

    def _phantom_click(self):
        if bool(self.card.get(C.HU_PHANTOM)):
            self._phantom_disarm()
            self._phantom_write(False)           # off: always one click
        elif self.ctx.settings["phantom_confirm"] == "two_click":
            if self._phantom_armed:
                self._phantom_disarm()
                self._phantom_write(True)
            else:
                self._phantom_armed = True
                self._blink_on = True
                self._arm_timer.start()
                self._blink.start()
                self._phantom_style(False)
        elif confirm_phantom(self.window()):
            self._phantom_write(True)

    def _phantom_disarm(self, restyle=True):
        was = self._phantom_armed
        self._phantom_armed = False
        self._arm_timer.stop()
        self._blink.stop()
        if was and restyle:
            self._phantom_style(bool(self.card.get(C.HU_PHANTOM)))

    def _phantom_blink(self):
        self._blink_on = not self._blink_on
        self._phantom_style(False)

    def _phantom_write(self, on):
        # The state shown follows the head unit's report (the change event), not the write.
        err = self.card.write(C.HU_PHANTOM, on)
        if err:
            self._phantom_say(PHANTOM_ERRORS.get(err) or
                              f"Couldn't switch phantom power ({os.strerror(err)}).")
        else:
            self._phantom_say("")

    def _phantom_say(self, text):
        self.phantom_note.setText(text)
        self.phantom_note.setVisible(bool(text))
        if text:
            self._note_timer.start()

    def _mute(self, muted):
        n = self.ctx.pw.nodes
        if n.source:
            pipewire.set_mute(n.source["id"], muted)

    def _mic_rate(self, i):
        rate = self.mic_rate.itemData(i)
        if rate == pipewire.mic_rate_setting():
            return
        if not self.confirm_wireplumber_restart():
            self.refresh()
            return
        self.ctx.set_mic_rate(rate)

    def confirm_wireplumber_restart(self):
        return QMessageBox.question(
            self, "Change the mic sample rate?",
            "This restarts WirePlumber, so audio on every device drops for a moment "
            "(music, calls, everything).\n\nChange it now?") == QMessageBox.Yes

    def _mic_depth(self, i):
        k = self.mic_depth.itemData(i)
        if k is not None and self.card.has(C.CAP_BIT_DEPTH) and k != self.card.get(C.CAP_BIT_DEPTH):
            self.ctx.set_capture_depth(k)

    def _refresh_mic_quality(self, n):
        rates = pipewire.mic_rates(n)
        if self.mic_rate.count() == 0:
            self.mic_rate.addItem("Automatic", None)
            for r in pipewire.MIC_RATES:
                self.mic_rate.addItem(f"{r / 1000:g} kHz", r)
        model = self.mic_rate.model()
        for k in range(1, self.mic_rate.count()):
            model.item(k).setEnabled(self.mic_rate.itemData(k) in rates)
        self.mic_rate.setEnabled(bool(n.source))
        chosen = pipewire.mic_rate_setting()
        i = self.mic_rate.findData(chosen)
        self.mic_rate.setCurrentIndex(i if i >= 0 else 0)
        # bit depth: a card control on newer drivers, else the fixed 24-bit
        items = self.card.items(C.CAP_BIT_DEPTH) if self.card.has(C.CAP_BIT_DEPTH) else []
        if items:
            labels = [f"{it} (as Windows)" if it.startswith("32") else it for it in items]
            if [self.mic_depth.itemText(k) for k in range(self.mic_depth.count())] != labels:
                self.mic_depth.clear()
                for k, text in enumerate(labels):
                    self.mic_depth.addItem(text, k)
                    if text.startswith("32"):
                        self.mic_depth.setItemData(
                            k, "Full 32-bit samples from the card's DSP; sounds the same as "
                               "24-bit in practice.", Qt.ToolTipRole)
            self.mic_depth.setCurrentIndex(self.card.get(C.CAP_BIT_DEPTH, 0) or 0)
            self.mic_depth.setEnabled(True)
            self.mic_depth.setToolTip("Bit depth the card records at; applies from the next recording")
            bits = items[self.card.get(C.CAP_BIT_DEPTH, 0) or 0]
        else:
            if self.mic_depth.count() != 1 or self.mic_depth.itemData(0) is not None:
                self.mic_depth.clear()
                self.mic_depth.addItem("24-bit", None)
            self.mic_depth.setEnabled(False)
            self.mic_depth.setToolTip("The card records 24 bits (sent in 32-bit words). Apps asking "
                                      "for 16-bit or float get PipeWire's conversion of that.")
            bits = "24-bit"
        live = pipewire.capture_stream()
        if live:
            ch = {1: "mono", 2: "stereo"}.get(live[1], f"{live[1]} ch")
            self.mic_now.setText(f"Recording now: {live[0] / 1000:g} kHz · {bits} · {ch}")
        elif max(rates) < 96000:
            self.mic_now.setText("This driver records at 48 kHz (96 kHz needs driver 0.9.1 or newer).")
        else:
            self.mic_now.setText("Not recording right now.")

    def _refresh_inputs(self, n):
        shown = [sec.refresh(n, self.card) for sec in self.inputs]
        self.other_none.setVisible(not any(shown))

    def _listen(self, on):
        n = self.ctx.pw.nodes
        if on and n.source:
            self.ctx.monitor.start(n.source["name"])
        else:
            self.ctx.monitor.stop()

    def _levels(self, l, r):
        self.meter_l.set_db(l)
        self.meter_r.set_db(r)
        top = max(l, r)
        self.peak.setText(f"{top:.0f} dBFS" if top > -89 else "—")

    def _metering(self):
        """The mic meter runs only while the Microphone tab is on screen."""
        return self.isVisible() and self.tab_stack.currentIndex() == 0

    def _update_meter(self):
        n = self.ctx.pw.nodes
        if n.source and self._metering():
            if not self.ctx.meter._proc:
                self.ctx.meter.start(n.source["name"])
        else:
            self.ctx.meter.stop()

    def show_tab(self, i, save=True):
        super().show_tab(i, save)
        self._update_meter()

    def showEvent(self, e):
        super().showEvent(e)
        self._update_meter()

    def hideEvent(self, e):
        super().hideEvent(e)
        try:
            self.ctx.meter.stop()
        except RuntimeError:     # the app is shutting down and the meter is gone
            pass

    def refresh(self):
        n = self.ctx.pw.nodes
        self.dev_name.setText(mic_name(n.source) if n.source else "AE-9 input not found in PipeWire")
        self.set_default.setEnabled(bool(n.source) and not n.source_is_default)
        self.set_default.setText("Default device" if n.source_is_default else "Set Default")
        self.default_ok.setPixmap(icons.pixmap("check", T.ACCENT_HI if n.source_is_default else T.DIM, 22))
        self._update_meter()
        self._refresh_inputs(n)
        self._refresh_mic_quality(n)
        muted = False
        if n.source:
            _, muted = pipewire.get_volume(n.source["id"])
        if not self.card.present:
            return
        self._refresh_phantom()
        self.mic_jack.setVisible(self.card.has(C.HU_MIC))
        if self.card.has(C.HU_MIC):
            self.mic_jack.setText("3.5 mm mic: " + (
                "plugged in" if self.card.get(C.HU_MIC) else "nothing plugged in"))
        raw = self.card.get(C.MIC, 0)
        self.mic.set_state(raw / 99, muted, "muted" if raw == 0 else f"{C.mic_raw_to_db(raw):+d} dB")
        self.xlr.set_value(str(self.card.get(C.MIC_GAIN, 1)))


# =====================================================================================
class ScoutPage(Page):
    title = "Scout Mode"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header("Scout Mode")
        box = QFrame()
        box.setObjectName("card")
        bl = QHBoxLayout(box)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.setSpacing(28)
        art = QLabel()
        art.setPixmap(icons.pixmap("scout", T.ACCENT_HI, 120))
        bl.addWidget(art, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(12)
        top = QHBoxLayout()
        self.sw = ToggleSwitch(size=(52, 26))
        self.sw.toggled.connect(lambda on: self.card.set(C.SCOUT, on))
        top.addWidget(self.sw)
        self.state = label("", "pageTitle")
        top.addWidget(self.state)
        top.addStretch()
        col.addLayout(top)
        col.addWidget(label(
            "Hear your enemies before they hear you. Scout Mode brings out footsteps, reloads and "
            "distant movement in games.", wrap=True))
        col.addWidget(label(
            "While it's on, the card switches Smart Volume on at 90 and uses Creative's Scout EQ "
            "curve. Your own Smart Volume and EQ settings come back when you switch it off.",
            "muted", wrap=True))
        col.addStretch()
        bl.addLayout(col, 1)
        self.lay.addWidget(box)
        self.banner = Banner("", "Enable DSP effects", warn=True)
        self.banner.button.clicked.connect(self._enable)
        self.lay.addWidget(self.banner)
        self.lay.addStretch()

    def _enable(self):
        self.card.set(C.SBX, True)
        self.ctx.set_direct(False)

    def refresh(self):
        if not self.card.present:
            return
        on = bool(self.card.get(C.SCOUT))
        self.sw.setCheckedSilently(on)
        self.state.setText("On" if on else "Off")
        self.banner.text.setText("Scout Mode works through the DSP: it needs Direct Mode off and SBX on.")
        self.banner.setVisible(not self.card.dsp_active)


# =====================================================================================
class MixerPage(Page):
    title = "Mixer"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header("Mixer")
        g = QGridLayout()
        g.setHorizontalSpacing(22)
        g.setVerticalSpacing(14)
        r = 0
        g.addWidget(label("Playback", "sectionTitle"), r, 0)
        r += 1
        self.out_name = label("Speakers")
        g.addWidget(self.out_name, r, 0)
        self.master = VolumeRow()
        self.master.valueChanged.connect(Throttle(
            lambda v: self.card.set(C.MASTER, C.master_pct_to_raw(v)), 30))
        self.master.muteToggled.connect(lambda m: self.card.set(C.MASTER_SW, not m))
        g.addWidget(self.master, r, 1)
        r += 1
        # one slider per PipeWire channel, like the desktop's own mixer; rows are
        # built once the sink's channel map is known
        g.addWidget(label("Channels"), r, 0, Qt.AlignTop)
        chan_box = QVBoxLayout()
        chan_box.setSpacing(8)
        self.chan_rows = QGridLayout()
        self.chan_rows.setHorizontalSpacing(12)
        self.chan_rows.setVerticalSpacing(8)
        self.chan_rows.setColumnStretch(1, 1)
        chan_box.addLayout(self.chan_rows)
        self.no_chan = label("No AE-9 output in PipeWire.", "muted")
        chan_box.addWidget(self.no_chan)
        tools = QHBoxLayout()
        self.link = QPushButton(" Link channels")
        self.link.setIcon(icons.icon("link"))
        self.link.setCheckable(True)
        self.link.setToolTip("Move all channels together")
        tools.addWidget(self.link)
        even = QPushButton("Equalise")
        even.setToolTip("Set every channel to the loudest one")
        even.clicked.connect(self._equalise)
        tools.addWidget(even)
        tools.addStretch()
        chan_box.addLayout(tools)
        g.addLayout(chan_box, r, 1)
        self.chan_map = None
        self.chan_sliders = []
        self.chan_vals = []
        self._pw_edit = 0.0
        self._chan_set = Throttle(self._apply_channels, 60)
        r += 1
        g.addWidget(label("", "muted"), r, 0)
        r += 1
        g.addWidget(label("Recording", "sectionTitle"), r, 0)
        r += 1
        g.addWidget(label("Microphone"), r, 0)
        self.mic = VolumeRow("mic", "mic-off")
        self.mic.valueChanged.connect(Throttle(lambda v: self.card.set(C.MIC, round(v * 99)), 40))
        self.mic.muteToggled.connect(self._mic_mute)
        g.addWidget(self.mic, r, 1)
        r += 1
        g.addWidget(label("Mic Gain"), r, 0)
        self.xlr = Segmented(["0", "1", "2"], labels={"0": "0 dB", "1": "+10 dB", "2": "+20 dB"})
        self.xlr.selected.connect(lambda v: self.card.set(C.MIC_GAIN, int(v)))
        xr = QHBoxLayout()
        xr.addWidget(self.xlr)
        xr.addStretch()
        g.addLayout(xr, r, 1)
        g.setColumnStretch(1, 1)
        g.setColumnMinimumWidth(0, 130)
        box = QWidget()
        box.setMaximumWidth(760)
        box.setLayout(g)
        self.lay.addWidget(box)
        self.lay.addWidget(label(
            "Speakers and headphones each keep their own volume on the card. "
            "Channel levels are applied by PipeWire, the same ones the desktop's volume "
            "control shows.", "hint", wrap=True))
        self.lay.addStretch()
        ctx.pw.updated.connect(self._on_pw)

    def _build_channels(self, chmap):
        while self.chan_rows.count():
            w = self.chan_rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.chan_sliders, self.chan_vals = [], []
        for i, pos in enumerate(chmap):
            self.chan_rows.addWidget(label(f"{pipewire.channel_name(pos)}:"), i, 0)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setCursor(Qt.PointingHandCursor)
            sl.valueChanged.connect(lambda v, i=i: self._channel_moved(i, v))
            self.chan_rows.addWidget(sl, i, 1)
            val = label("", "muted")
            val.setMinimumWidth(48)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.chan_rows.addWidget(val, i, 2)
            self.chan_sliders.append(sl)
            self.chan_vals.append(val)
        self.chan_map = list(chmap)
        self.no_chan.setVisible(not chmap)

    def _channel_moved(self, i, v):
        if self.link.isChecked():
            for j, sl in enumerate(self.chan_sliders):
                if j != i:
                    sl.blockSignals(True)
                    sl.setValue(v)
                    sl.blockSignals(False)
        for sl, val in zip(self.chan_sliders, self.chan_vals):
            val.setText(f"{sl.value()}%")
        self._pw_edit = time.monotonic()
        self._chan_set()

    def _apply_channels(self):
        n = self.ctx.pw.nodes
        if n.sink and self.chan_sliders:
            # desktop % is cubic: linear volume = (pct / 100) ** 3
            pipewire.set_channel_volumes(n, [(sl.value() / 100) ** 3 for sl in self.chan_sliders])

    def _equalise(self):
        if self.chan_sliders:
            top = max(sl.value() for sl in self.chan_sliders)
            for sl in self.chan_sliders:
                sl.blockSignals(True)
                sl.setValue(top)
                sl.blockSignals(False)
            self._channel_moved(0, top)

    def _refresh_channels(self):
        n = self.ctx.pw.nodes
        chmap = n.sink_channel_map()
        if chmap != self.chan_map:
            self._build_channels(chmap)
        # PipeWire state is polled; skip a few seconds after an edit so a stale
        # dump doesn't snap the sliders back
        if time.monotonic() - self._pw_edit < 3.5:
            return
        cv = n.sink_channel_volumes() or []
        for sl, val, v in zip(self.chan_sliders, self.chan_vals, cv):
            pct = int(round(max(0.0, v) ** (1 / 3) * 100))
            if not sl.isSliderDown():
                sl.blockSignals(True)
                sl.setValue(min(100, pct))
                sl.blockSignals(False)
            val.setText(f"{pct}%")

    def _mic_mute(self, muted):
        n = self.ctx.pw.nodes
        if n.source:
            pipewire.set_mute(n.source["id"], muted)

    def refresh(self):
        n = self.ctx.pw.nodes
        self._refresh_channels()
        if not self.card.present:
            return
        self.out_name.setText("Headphones" if self.card.get(C.OUTPUT) == 1 else "Speakers")
        raw = self.card.get(C.MASTER, 0)
        muted = not self.card.get(C.MASTER_SW, True)
        self.master.set_state(C.master_raw_to_pct(raw), muted,
                              f"{C.master_raw_to_db(raw):.1f} dB" if raw else "−∞ dB")
        mraw = self.card.get(C.MIC, 0)
        mm = pipewire.get_volume(n.source["id"])[1] if n.source else False
        self.mic.set_state(mraw / 99, mm, "muted" if mraw == 0 else f"{C.mic_raw_to_db(mraw):+d} dB")
        self.xlr.set_value(str(self.card.get(C.MIC_GAIN, 1)))


# =====================================================================================
# Terminals to open alsamixer in, first one installed wins: KDE, GNOME
# (Ptyxis on Fedora 41+, Console, the older GNOME Terminal), Debian's
# alternative, then the usual others.
TERMINALS = (["konsole", "-e"], ["ptyxis", "--"], ["kgx", "--"], ["gnome-terminal", "--"],
             ["x-terminal-emulator", "-e"], ["xfce4-terminal", "-x"], ["alacritty", "-e"],
             ["kitty"], ["foot"], ["xterm", "-e"])


def alsamixer_command(card_index):
    import shutil
    for term in TERMINALS:
        if shutil.which(term[0]):
            return term + ["alsamixer", "-c", str(card_index)]
    return None


class SettingsPage(Page):
    title = "Settings"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header("Settings")
        app, device = self.add_tabs(["Application", "Device"])
        self.lay = app
        self.lay.addWidget(label("Appearance", "sectionTitle"))
        pal = QHBoxLayout()
        pal.setSpacing(12)
        self.palettes = {}
        for key in T.PALETTES:
            pc = PaletteCard(key)
            pc.set_selected(key == T.CURRENT)
            pc.clicked.connect(self._pick_palette)
            self.palettes[key] = pc
            pal.addWidget(pc)
        pal.addStretch()
        self.lay.addLayout(pal)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel("UI scale"))
        self.scale = QSlider(Qt.Horizontal)
        self.scale.setRange(*T.SCALES)
        self.scale.setSingleStep(5)
        self.scale.setPageStep(10)
        self.scale.setFixedWidth(240)
        self.scale.setValue(T.SCALE)
        self.scale.valueChanged.connect(self._scale_moved)
        row.addWidget(self.scale)
        self.scale_lbl = label("", "bigValue")
        self.scale_lbl.setMinimumWidth(50)
        row.addWidget(self.scale_lbl)
        self.scale_apply = QPushButton("Apply")
        self.scale_apply.setToolTip("Saves the scale and reopens the window at the new size")
        self.scale_apply.clicked.connect(self._apply_scale)
        row.addWidget(self.scale_apply)
        reset = QPushButton("100%")
        reset.setToolTip("Back to the normal size")
        reset.clicked.connect(lambda: self.scale.setValue(100))
        row.addWidget(reset)
        row.addStretch()
        self.lay.addLayout(row)
        self.lay.addWidget(label("Shrinks or enlarges everything, so the app fits a smaller window. "
                                 "The window reopens to apply it (about a second). On a Wayland "
                                 "desktop, sizes other than 100% run through XWayland, where Qt "
                                 "puts dropdown lists in the right place.", "hint", wrap=True))
        self._scale_moved(T.SCALE)

        self.frameless = QCheckBox("Use the app's own title bar (drag the AE-9 header to move the window)")
        self.frameless.setToolTip("Off: the desktop's usual window frame and title bar")
        self.frameless.setChecked(bool(ctx.settings["frameless"]))
        self.frameless.toggled.connect(self._frameless)
        self.lay.addWidget(self.frameless)

        # Glass: see-through backgrounds on whichever palette is active
        grow = QHBoxLayout()
        grow.setSpacing(12)
        self.glass = QCheckBox("Glass")
        self.glass.setToolTip("See-through backgrounds on any palette (the window reopens)")
        self.glass.setChecked(T.GLASS)
        self.glass.toggled.connect(self._glass)
        grow.addWidget(self.glass)
        grow.addSpacing(18)
        grow.addWidget(QLabel("Opacity"))
        self.glass_opacity = QSlider(Qt.Horizontal)
        self.glass_opacity.setRange(*T.GLASS_RANGE)
        self.glass_opacity.setSingleStep(5)
        self.glass_opacity.setPageStep(10)
        self.glass_opacity.setFixedWidth(200)
        self.glass_opacity.setValue(round(T.GLASS_OPACITY * 100))
        self.glass_opacity.setEnabled(T.GLASS)
        self.glass_opacity.valueChanged.connect(self._glass_moved)
        self.glass_opacity.sliderReleased.connect(self._glass_save)
        grow.addWidget(self.glass_opacity)
        self.glass_lbl = label("", "bigValue")
        self.glass_lbl.setMinimumWidth(50)
        grow.addWidget(self.glass_lbl)
        grow.addStretch()
        self.lay.addLayout(grow)
        self.lay.addWidget(label(
            "Makes the window's backgrounds see-through, whatever the palette; text and "
            "controls stay solid. On KDE, what's behind is frosted (the app runs through "
            "XWayland for that). Switching Glass on or off reopens the window.", "hint", wrap=True))
        self._glass_label(self.glass_opacity.value())

        self.lay.addWidget(label("Start-up", "sectionTitle"))
        self.autostart = QCheckBox("Start Sound Blaster Command when you log in")
        self.autostart.setToolTip("Adds the app to your desktop's autostart "
                                  "(~/.config/autostart/sbae9-sbc.desktop)")
        self.autostart.setChecked(config.autostart_enabled())
        self.autostart.toggled.connect(config.set_autostart)
        self.lay.addWidget(self.autostart)
        self.restore = QCheckBox("Re-apply the active SBX profile when the app starts")
        self.restore.setToolTip("Usually not needed: the driver and alsa-state keep the card's "
                                "settings across reboots.")
        self.restore.setChecked(bool(ctx.settings["restore_on_start"]))
        self.restore.toggled.connect(lambda on: ctx.settings.__setitem__("restore_on_start", on))
        self.lay.addWidget(self.restore)
        self.restore_rate = QCheckBox("Reload the last sample rate when the app starts")
        self.restore_rate.setToolTip("Off: the app opens showing whatever rate PipeWire is running "
                                     "and changes nothing until you pick one.")
        self.restore_rate.setChecked(bool(ctx.settings["restore_rate_on_start"]))
        self.restore_rate.toggled.connect(lambda on: ctx.settings.__setitem__("restore_rate_on_start", on))
        self.lay.addWidget(self.restore_rate)
        self.lay.addStretch()

        # --- Device tab ---
        self.lay = device
        self.lay.addWidget(label("Device", "sectionTitle"))
        self.info = label("", "muted", wrap=True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lay.addWidget(self.info)

        self.rates_banner = Banner("Sample rates other than 48 kHz are off in the driver "
                                   "(pcm_rates=0). Turn them on until the next reboot?",
                                   "Enable (asks for password)")
        self.rates_banner.button.clicked.connect(self._enable_rates)
        self.lay.addWidget(self.rates_banner)

        # how the Recording page's phantom power button turns on (drivers that can switch it)
        self.phantom_box = QWidget()
        pl = QVBoxLayout(self.phantom_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(label("Phantom power", "sectionTitle"))
        row = QHBoxLayout()
        self.phantom_mode = QComboBox()
        for text, key in (("Ask first (warning)", "popup"),
                          ("Two clicks turn on, one turns off", "two_click")):
            self.phantom_mode.addItem(text, key)
        self.phantom_mode.setCurrentIndex(max(0, self.phantom_mode.findData(ctx.settings["phantom_confirm"])))
        self.phantom_mode.activated.connect(
            lambda i: ctx.settings.__setitem__("phantom_confirm", self.phantom_mode.itemData(i)))
        row.addWidget(self.phantom_mode)
        row.addStretch()
        pl.addLayout(row)
        pl.addWidget(label("How Recording → Phantom Power 48V turns on. Turning it off is always "
                           "one click. The app never turns it on by itself.", "hint", wrap=True))
        self.phantom_box.setVisible(False)
        self.lay.addWidget(self.phantom_box)

        self.lay.addWidget(label("Reset to defaults", "sectionTitle"))
        self.lay.addWidget(label("Puts SBX and the EQ back to the driver's defaults. Your saved "
                                 "profiles and EQ presets stay.", "hint", wrap=True))
        row = QHBoxLayout()
        reset = QPushButton("Reset SBX and EQ to defaults")
        reset.clicked.connect(self._reset)
        row.addWidget(reset)
        mixer = QPushButton("Open alsamixer")
        mixer.clicked.connect(self._alsamixer)
        row.addWidget(mixer)
        row.addStretch()
        self.lay.addLayout(row)

        self.lay.addWidget(label("All hardware controls", "sectionTitle"))
        self.lay.addWidget(label("Every ALSA control the driver exposes, including ones that are greyed out "
                                 "(inactive) in the current mode. Changes apply right away.", "hint", wrap=True))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Control", "Value", "State"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(420)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setColumnWidth(1, 200)
        self.lay.addWidget(self.table, 1)
        self._editors = {}

    def _scale_moved(self, v):
        snapped = T.clamp_scale(v)
        if snapped != v:
            self.scale.setValue(snapped)
            return
        self.scale_lbl.setText(f"{v}%")
        self.scale_apply.setEnabled(v != T.SCALE)

    def _glass(self, on):
        self.ctx.settings["glass"] = on
        self.ctx.restart_requested.emit()

    def _glass_moved(self, v):
        snapped = T.clamp_glass(v)
        if snapped != v:
            self.glass_opacity.setValue(snapped)
            return
        self._glass_label(v)
        if not self.glass_opacity.isSliderDown():   # keyboard / wheel: apply now
            self._glass_save()

    def _glass_label(self, v):
        self.glass_lbl.setText(f"{v}%")

    def _glass_save(self):
        v = self.glass_opacity.value()
        T.GLASS_OPACITY = v / 100
        self.ctx.settings["glass_opacity"] = v
        self.ctx.restyle_requested.emit()

    def _frameless(self, on):
        self.ctx.settings["frameless"] = on
        win = self.window()
        if hasattr(win, "set_frameless"):
            win.set_frameless(on)

    def _apply_scale(self):
        self.ctx.settings["ui_scale"] = self.scale.value()
        self.ctx.restart_requested.emit()

    def _pick_palette(self, key):
        if key != T.CURRENT:
            self.ctx.palette_requested.emit(key)

    def _enable_rates(self):
        path = f"{C.MODULE_PARAMS}/pcm_rates"
        try:
            on = "2" if C.plays_cd_rates() else "1"
            subprocess.run(["pkexec", "sh", "-c", f"echo {on} > {path}"], timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.refresh()

    def _alsamixer(self):
        cmd = alsamixer_command(self.card.card_index)
        if cmd:
            try:
                subprocess.Popen(cmd)
                return
            except OSError:
                pass
        QMessageBox.information(self, "Open alsamixer",
                                "No terminal app found. Run this in a terminal:\n\n"
                                f"alsamixer -c {self.card.card_index}")

    def _reset(self):
        if QMessageBox.question(self, "Reset", "Reset all SBX effects and the EQ to the driver defaults?") \
                != QMessageBox.Yes:
            return
        self.card.set(C.SCOUT, False)
        self.card.apply(profiles.BUILTIN[0])
        self.card.set(C.EQ_ON, False)
        self.ctx.settings["active_profile"] = "Default"
        self.ctx.profile_changed.emit()

    def _editor(self, c):
        if c.type == 1:
            w = QCheckBox()
            w.toggled.connect(lambda on, n=c.name: self.card.set(n, on))
        elif c.type == 3:
            w = QComboBox()
            w.addItems(c.items)
            w.activated.connect(lambda i, n=c.name: self.card.set(n, i))
        else:
            w = QSpinBox()
            w.setRange(c.min, c.max)
            w.setKeyboardTracking(False)
            w.valueChanged.connect(lambda v, n=c.name: self.card.set(n, v))
        if c.name == C.HU_PHANTOM:
            w.setEnabled(False)          # 48 V: only through the Recording page's button
            w.setToolTip("Switch it on the Recording page" if c.writable else
                         "Switched by the head unit's button")
        elif not c.writable:
            w.setEnabled(False)          # the driver reports it; it can't be set
        return w

    def refresh(self):
        mod = C.module_version() or "not loaded"
        rates = C.module_param("pcm_rates")
        bits = C.module_param("pcm_bits")
        n = self.ctx.pw.nodes
        lines = [
            f"<b>{self.card.longname or 'Sound Blaster AE-9 not found'}</b>",
            f"ALSA card {self.card.card_index} · driver snd-hda-codec-creative-ae9 {mod}",
            "Playback rates: " + ("/".join(f"{r / 1000:g}" for r in pipewire.card_rates(
                rates, C.plays_176k4())) + " kHz" if rates in ("0", "1", "2") else "?") +
            f" · sample bits: {bits or '?'}",
            "5.1 rates: " + "/".join(f"{r / 1000:g}" for r in pipewire.playable_rates(
                True, True, rates or "1", C.surround_max())) + " kHz"
            " · DSP mode: " + "/".join(f"{r / 1000:g}" for r in pipewire.playable_rates(
                False, False, rates or "1", dsp_96k=C.dsp_96k())) + " kHz",
            "Driver options: " + " · ".join(
                f"{p}={C.module_param(p)}" for p in DEVICE_PARAMS if C.module_param(p) is not None),
            f"PipeWire sink: {n.sink['name'] if n.sink else '—'}",
            f"PipeWire source: {n.source['name'] if n.source else '—'}",
            f"Sound Blaster Command for Linux {__version__}",
        ]
        self.info.setText("<br>".join(lines))
        self.rates_banner.setVisible(rates == "0")
        self.phantom_box.setVisible(self.card.has(C.HU_PHANTOM) and self.card.writable(C.HU_PHANTOM))
        ctrls = self.card.all_controls()
        if self.table.rowCount() != len(ctrls):
            self.table.setRowCount(len(ctrls))
            self._editors = {}
            for i, c in enumerate(ctrls):
                self.table.setItem(i, 0, QTableWidgetItem(c.name))
                ed = self._editor(c)
                self._editors[c.name] = ed
                self.table.setCellWidget(i, 1, ed)
                self.table.setItem(i, 2, QTableWidgetItem())
        for i, c in enumerate(ctrls):
            ed = self._editors.get(c.name)
            v = self.card.get(c.name)
            if ed is None or v is None:
                continue
            ed.blockSignals(True)
            if isinstance(ed, QCheckBox):
                ed.setChecked(bool(v))
            elif isinstance(ed, QComboBox):
                ed.setCurrentIndex(v)
            else:
                ed.setValue(v)
            ed.blockSignals(False)
            st = self.table.item(i, 2)
            st.setText("inactive" if c.inactive else "active")
            st.setForeground(QColor(T.DIM if c.inactive else T.TEXT))
