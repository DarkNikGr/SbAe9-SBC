# SPDX-License-Identifier: GPL-2.0-only
"""PipeWire side of the card: its sink/source nodes, default device, sample
rate, per-node volume, a test tone, mic monitoring and an input level meter.

Uses the stock command-line tools (pw-dump, wpctl, pw-metadata, pw-play,
pw-loopback, pw-record), so there is nothing extra to install.
"""

import json
import math
import os
import re
import shutil
import struct
import subprocess
import wave

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from sbae9kit import ae9

from . import config

ALL_RATES = [44100, 48000, 88200, 96000, 176400, 192000, 384000]   # every rate the AE-9 driver can play
RATES = [48000, 96000, 192000, 384000]   # without 44.1/88.2 (pcm_rates=1, drivers before 0.9.4)
CD_RATES = (44100, 88200, 176400)        # stereo, Direct Mode only (pcm_rates=2; 176.4 with pcm_176k4)
OPTICAL_RATES = (44100, 48000, 88200, 96000, 176400, 192000)   # the optical PCM (stereo, up to 192 kHz)
SURROUND_RATES = (48000, 96000, 192000)  # what 5.1 can play at most
RATES_CONF = os.path.expanduser("~/.config/pipewire/pipewire.conf.d/90-sbae9-sbc-rates.conf")
# The head unit mic input's own sample rate: a WirePlumber rule on that one source
# (written only when you pick a rate; Automatic removes it).
MIC_CONF = os.path.expanduser("~/.config/wireplumber/wireplumber.conf.d/91-sbae9-sbc-mic.conf")
MIC_RATES = (48000, 96000)
# Where the driver's own PipeWire configs for optical in and What U Hear go
PW_CONF_DIR = os.path.expanduser("~/.config/pipewire/pipewire.conf.d")


def _run(*args, timeout=3):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def available():
    return shutil.which("pw-dump") is not None and shutil.which("wpctl") is not None


def dump():
    out = _run("pw-dump", timeout=5)
    try:
        return json.loads(out) if out else []
    except json.JSONDecodeError:
        return []


def _is_ae9(props):
    return ae9.is_ae9(props)


# The AE-9's extra capture devices (optical in, What U Hear): each its own
# PipeWire source, never taken for the head unit mic.
EXTRA_INPUTS = ae9.EXTRA_INPUTS
OPTICAL_IN = EXTRA_INPUTS["optical_in"][0]


def _extra_input(props):
    """"optical_in" / "what_u_hear" / "rear_rca" for those AE-9 sources, None for the mic."""
    kind = ae9.input_kind(props)
    return None if kind == "mic" else kind


class Nodes:
    """Snapshot of the AE-9's PipeWire nodes and the current defaults."""

    def __init__(self, objs=None):
        objs = dump() if objs is None else objs
        self.sink = self.source = self.device = None
        self.optical_in = self.what_u_hear = self.rear_rca = None
        self.optical_out = None
        self.default_sink = self.default_source = None
        for o in objs:
            info = o.get("info") or {}
            props = info.get("props") or {}
            mc = props.get("media.class")
            meta_name = (o.get("props") or {}).get("metadata.name") or props.get("metadata.name")
            if o.get("type", "").endswith("Metadata") and meta_name == "default":
                for m in o.get("metadata", []):
                    val = m.get("value")
                    name = val.get("name") if isinstance(val, dict) else None
                    if m.get("key") == "default.audio.sink":
                        self.default_sink = name
                    elif m.get("key") == "default.audio.source":
                        self.default_source = name
            # The separate optical output is its own sink (a PipeWire adapter
            # on hw:AE9,4); keep it apart from the main AE-9 sink.  is_ae9()
            # matches its name too, so handle it before the AE-9 match.
            if mc == "Audio/Sink" and props.get("node.name") == "alsa_output.ae9_optical":
                node = {"id": o["id"], "name": props.get("node.name"), "state": info.get("state"),
                        "description": props.get("node.description"), "props": props,
                        "params": info.get("params") or {}}
                self.optical_out = self.optical_out or node
                continue
            if not _is_ae9(props):
                continue
            extra = _extra_input(props) if mc == "Audio/Source" else None
            node = {"id": o["id"], "name": props.get("node.name"), "state": info.get("state"),
                    "description": props.get("node.description"), "props": props,
                    "params": info.get("params") or {}}
            if extra:
                setattr(self, extra, getattr(self, extra) or node)
            elif mc == "Audio/Sink" and not self.sink:
                self.sink = node
            elif mc == "Audio/Source" and not self.source:
                self.source = node
            elif mc == "Audio/Device":
                self.device = node

    @property
    def sink_is_default(self):
        return bool(self.sink and self.sink["name"] == self.default_sink)

    @property
    def optical_out_is_default(self):
        return bool(self.optical_out and self.optical_out["name"] == self.default_sink)

    def optical_out_format(self):
        """(rate, format) the separate optical sink is running at, or None."""
        if not self.optical_out:
            return None
        for f in self.optical_out["params"].get("Format") or []:
            return f.get("rate"), f.get("format")
        return None

    @property
    def source_is_default(self):
        return bool(self.source and self.source["name"] == self.default_source)

    @property
    def optical_in_is_default(self):
        return self.is_default_source(self.optical_in)

    def is_default_source(self, node):
        return bool(node and node["name"] == self.default_source)

    def sink_format(self):
        """(rate, format) the sink is running at, or None when idle."""
        if not self.sink:
            return None
        for f in self.sink["params"].get("Format") or []:
            return f.get("rate"), f.get("format")
        return None

    def sink_channel_volumes(self):
        if not self.sink:
            return None
        for p in self.sink["params"].get("Props") or []:
            if "channelVolumes" in p:
                return p["channelVolumes"]
        return None

    # --- card profile (stereo vs 5.1 stream) -----------------------------------
    def card_profiles(self):
        """Names of the card's PipeWire profiles."""
        if not self.device:
            return []
        return [p.get("name") for p in self.device["params"].get("EnumProfile") or [] if p.get("name")]

    def card_profile(self):
        """Name of the active card profile, e.g. "output:analog-stereo+input:analog-stereo"."""
        if not self.device:
            return None
        for p in self.device["params"].get("Profile") or []:
            if p.get("name"):
                return p["name"]
        return None

    def can_switch_layout(self):
        """True when the driver's profile set (creative-ae9.conf) offers both a
        stereo and a 5.1 output; the stock *-fallback profiles don't."""
        names = self.card_profiles()
        return (any(n.startswith(STEREO_OUT) for n in names)
                and any(n.startswith(SURROUND_OUT) for n in names))

    def stream_layout(self):
        """"surround", "stereo", or None (no output, pro-audio, unknown)."""
        prof = self.card_profile() or ""
        if "analog-surround-51" in prof:
            return "surround"
        if prof.startswith("output:analog-stereo"):
            return "stereo"
        return None

    def sink_channel_map(self):
        """Channel positions of the sink, e.g. ["FL", "FR"]."""
        if not self.sink:
            return []
        for p in self.sink["params"].get("Props") or []:
            if p.get("channelMap"):
                return list(p["channelMap"])
        cv = self.sink_channel_volumes() or []
        return ["FL", "FR"][:len(cv)] if len(cv) <= 2 else [f"CH{i + 1}" for i in range(len(cv))]


def set_default(node_id):
    return _run("wpctl", "set-default", str(node_id)) is not None


def get_volume(node_id):
    """(volume 0..1.5, muted) on the desktop slider scale."""
    out = _run("wpctl", "get-volume", str(node_id))
    if not out:
        return None, False
    m = re.search(r"Volume:\s*([\d.]+)", out)
    return (float(m.group(1)) if m else None), "MUTED" in out


def set_volume(node_id, vol):
    _run("wpctl", "set-volume", str(node_id), f"{max(0.0, vol):.3f}")


def set_mute(node_id, muted):
    _run("wpctl", "set-mute", str(node_id), "1" if muted else "0")


# Output profiles from the driver's profile set (config/creative-ae9.conf).
STEREO_OUT = "output:analog-stereo"
SURROUND_OUT = "output:analog-surround-51"
STEREO_IN = "input:analog-stereo"


def layout_profile(nodes, surround):
    """The card profile that plays a stereo or 5.1 stream, keeping the input
    if the current profile has one. None when there's nothing to switch: no
    profile set, already there, or the user picked off / pro-audio."""
    if not nodes.can_switch_layout():
        return None
    cur = nodes.card_profile() or ""
    if cur in ("off", "pro-audio") or cur.startswith("pro-audio"):
        return None
    name = SURROUND_OUT if surround else STEREO_OUT
    if STEREO_IN in cur:
        name += "+" + STEREO_IN
    if name == cur or name not in nodes.card_profiles():
        return None
    return name


def set_card_profile(nodes, name):
    """Switch the AE-9's card profile (the stream reopens; a short gap is normal)."""
    if not nodes.device:
        return False
    for p in nodes.device["params"].get("EnumProfile") or []:
        if p.get("name") == name and p.get("index") is not None:
            if _run("pw-cli", "set-param", str(nodes.device["id"]), "Profile",
                    f"{{ index: {p['index']}, save: true }}") is not None:
                return True
    return _run("pactl", "set-card-profile", nodes.device["name"], name) is not None


CHANNEL_NAMES = {
    "MONO": "Mono", "FL": "Front Left", "FR": "Front Right", "FC": "Front Center",
    "LFE": "Subwoofer", "RL": "Rear Left", "RR": "Rear Right", "RC": "Rear Center",
    "SL": "Side Left", "SR": "Side Right", "FLC": "Front Left Center",
    "FRC": "Front Right Center",
}


def channel_name(pos):
    return CHANNEL_NAMES.get(pos, pos)


def _output_route(nodes):
    """(route index, profile device) of the card route feeding the sink."""
    if not (nodes.sink and nodes.device):
        return None
    dev = nodes.sink["props"].get("card.profile.device")
    for r in nodes.device["params"].get("Route") or []:
        if r.get("direction") == "Output" and (dev is None or r.get("device") == dev):
            return r.get("index"), r.get("device")
    return None


def set_channel_volumes(nodes, volumes):
    """Set the AE-9 output's per-channel volumes (linear; desktop % = v ** (1/3)).

    The volume goes on the card's output route, the way the desktop mixer does
    it: PipeWire then drives the card's hardware Master with the loudest
    channel and only trims the quieter ones in software. Writing the node's
    Props instead would stack a software volume on top of the hardware one.
    """
    if not volumes or not nodes.sink:
        return
    vals = " ".join(f"{max(0.0, v):.6f}" for v in volumes)
    route = _output_route(nodes)
    if route and route[0] is not None:
        idx, dev = route
        if _run("pw-cli", "set-param", str(nodes.device["id"]), "Route",
                f"{{ index: {idx}, device: {dev}, props: {{ channelVolumes: [ {vals} ] }}, save: true }}") is not None:
            return
    # no route info: go through the PulseAudio layer like the desktop mixer
    raw = [str(int(round(max(0.0, v) ** (1 / 3) * 65536))) for v in volumes]
    _run("pactl", "set-sink-volume", nodes.sink["name"], *raw)


# --- sample rate ----------------------------------------------------------------
def clock_settings():
    out = _run("pw-metadata", "-n", "settings", "0") or ""
    s = {}
    for m in re.finditer(r"key:'([^']+)' value:'([^']*)'", out):
        s[m.group(1)] = m.group(2)
    return s


# Bigger buffers at the top rates: 384 kHz crackles with PipeWire's default
# quantum (tested by ear on the AE-9; 1024-2048 is clean, 2048 gives margin).
QUANTUM = {384000: 2048, 192000: 1024, 176400: 1024}


def card_rates(pcm_rates, k176=False):
    """Every rate the loaded driver plays, from its pcm_rates option: 0 = 48
    kHz only, 1 = 48-384 kHz, 2 = also 44.1 and 88.2 kHz (driver 0.9.4+),
    and 176.4 kHz with `k176` (the pcm_176k4 option, driver 0.9.7+)."""
    if pcm_rates == "0":
        return [48000]
    return allowed_rates(pcm_rates, k176)


def allowed_rates(pcm_rates, k176=False):
    """What PipeWire may open the card at (clock.allowed-rates): the full set,
    even with pcm_rates=0, so turning high rates back on needs no rewrite."""
    if pcm_rates != "2":
        return list(RATES)
    return [r for r in ALL_RATES if r != 176400 or k176]


DSP_RATES = (48000, 96000)   # what DSP mode (Direct Mode off) plays with dsp_96k on


def playable_rates(direct, surround, pcm_rates="1", surround_max=48000, dsp_96k=False, k176=False):
    """The rates the card takes right now. DSP mode (Direct Mode off) runs at
    48 kHz, or 48 and 96 kHz with the driver's dsp_96k option (0.9.4+), in
    stereo and 5.1. 44.1 and 88.2 kHz are stereo only. 5.1 goes up to
    `surround_max`: 48 kHz on old drivers, 96 kHz from 0.7.0, 192 kHz from
    0.9.4. Stereo in Direct Mode gets them all."""
    rates = card_rates(pcm_rates, k176)
    if not direct:
        return [r for r in rates if r in DSP_RATES] if dsp_96k else [48000]
    if surround:
        return [r for r in rates if r in SURROUND_RATES and r <= surround_max] or [48000]
    return rates


def effective_rate(mode, rates):
    """The rate applied for the user's choice (0 = automatic) given the
    `rates` the card takes now: the choice itself, else the next one up
    (88.2 -> 96 kHz on 5.1, so nothing is lost), else the highest."""
    if not mode:
        return 0
    if mode in rates:
        return mode
    up = [r for r in rates if r >= mode]
    return min(up) if up else max(rates)


QUANTA = (64, 128, 256, 512, 1024, 2048)   # quantum picks offered (0 = PipeWire decides)
QUANTUM_MIN, QUANTUM_MAX = 8, 8192         # any pick in this range (the widgets' own lists)


def quantum_for(rate, pick=0):
    """The quantum to force at `rate`: the user's pick, but never below what
    the rate needs to play without crackles (QUANTUM)."""
    need = QUANTUM.get(rate, 0)
    return max(need, pick) if pick else need


def set_quantum(q):
    _run("pw-metadata", "-n", "settings", "0", "clock.force-quantum", str(q))


def force_rate(rate):
    """Set PipeWire's graph rate (0 = automatic). One clock for the whole graph."""
    return _run("pw-metadata", "-n", "settings", "0", "clock.force-rate", str(int(rate)))


def streams_into(node_name):
    """The rates of the app streams playing to that sink, from pw-dump."""
    objs = dump()
    sink = None
    rates = {}
    for o in objs:
        if not str(o.get("type", "")).endswith("Node"):
            continue
        info = o.get("info") or {}
        props = info.get("props") or {}
        if props.get("node.name") == node_name:
            sink = o.get("id")
        elif props.get("media.class") == "Stream/Output/Audio":
            for f in (info.get("params") or {}).get("Format") or []:
                if f.get("rate"):
                    rates[o.get("id")] = int(f["rate"])
                break
    if sink is None:
        return []
    out = []
    for o in objs:
        if not str(o.get("type", "")).endswith("Link"):
            continue
        info = o.get("info") or {}
        if info.get("input-node-id") == sink and rates.get(info.get("output-node-id")):
            out.append(rates[info["output-node-id"]])
    return out


def set_rate_mode(mode, rates=None, quantum=0):
    """mode 0 = follow the source, else force that rate (with its quantum).

    Only the forced rate is capped by the caller. allowed-rates, live and in
    the drop-in, always lists the card's full set: PipeWire treats it as the
    rates the device may open at, so a short list would make it resample.
    `rates` is that set (allowed_rates()); 48-384 kHz if not given.
    `quantum` is the user's quantum pick (0 = none), see quantum_for().
    The drop-in keeps PipeWire from falling back to 44.1/48 kHz-only after a
    restart; the forced rate is restored by the app at start.
    """
    rates = rates or RATES
    _run("pw-metadata", "-n", "settings", "0", "clock.allowed-rates", _rate_list(rates))
    _run("pw-metadata", "-n", "settings", "0", "clock.force-rate", str(mode))
    set_quantum(quantum_for(mode, quantum))
    _write_rates_conf(rates)


def _rate_list(rates):
    return "[ " + " ".join(map(str, rates)) + " ]"


def _write_rates_conf(rates):
    full = _rate_list(rates)
    resampled = ("Every listed rate is played as is." if 44100 in rates else
                 "44.1 kHz material is resampled.")
    os.makedirs(os.path.dirname(RATES_CONF), exist_ok=True)
    with open(RATES_CONF, "w") as f:
        f.write("# Written by Sound Blaster Command for Linux (sbae9-sbc).\n"
                f"# The AE-9 plays {'/'.join(f'{r / 1000:g}' for r in rates)} kHz. {resampled}\n"
                "# The app's chosen rate is applied at run time (clock.force-rate).\n"
                "context.properties = {\n"
                "    default.clock.rate          = 48000\n"
                f"    default.clock.allowed-rates = {full}\n"
                "}\n")


def update_allowed_rates(rates):
    """At start: if the app's drop-in lists other rates than the driver plays
    now (written before the driver got 44.1/88.2 kHz, say), rewrite it, and
    the live allowed-rates too while they're still the app's old list. Does
    nothing without the drop-in (the app never wrote rates) and never touches
    the forced rate."""
    try:
        with open(RATES_CONF) as f:
            text = f.read()
    except OSError:
        return False
    full = _rate_list(rates)
    if f"allowed-rates = {full}\n" in text:
        return False
    old = re.search(r"allowed-rates = (\[[^\]]*\])", text)
    _write_rates_conf(rates)
    if old and clock_settings().get("clock.allowed-rates") == old.group(1):
        _run("pw-metadata", "-n", "settings", "0", "clock.allowed-rates", full)
    return True


def current_force_rate():
    try:
        return int(clock_settings().get("clock.force-rate", "0"))
    except ValueError:
        return 0


def current_quantum():
    try:
        return int(clock_settings().get("clock.force-quantum", "0"))
    except ValueError:
        return 0


def reopen_sink(nodes):
    """Suspend and resume the AE-9 sink so the card is reopened (a new bit
    depth takes effect on the next open). False if it couldn't."""
    if not nodes.sink:
        return False
    name = nodes.sink["name"]
    return (_run("pactl", "suspend-sink", name, "1") is not None
            and _run("pactl", "suspend-sink", name, "0") is not None)


def reopen_source(nodes):
    """Suspend and resume the head unit mic source so the capture reopens
    (a new capture bit depth takes effect on the next open)."""
    if not nodes.source:
        return False
    name = nodes.source["name"]
    return (_run("pactl", "suspend-source", name, "1") is not None
            and _run("pactl", "suspend-source", name, "0") is not None)


def card_stream(card_id="AE9"):
    """(rate, channels) the card's playback PCM is open at, or None when closed."""
    return ae9.pcm_open_at("pcm0p", card_id)


def capture_stream(card_id="AE9"):
    """(rate, channels) the head unit mic capture is open at, or None."""
    return ae9.pcm_open_at("pcm0c", card_id)


def mic_rates(nodes):
    """Rates the head unit mic can record at, from what the driver offers
    (48 kHz only before driver 0.9.1, 48 and 96 kHz after)."""
    src = nodes.source
    for f in ((src or {}).get("params") or {}).get("EnumFormat", []):
        r = f.get("rate")
        if isinstance(r, dict) and "max" in r:
            return [x for x in MIC_RATES if r.get("min", 0) <= x <= r["max"]]
        if isinstance(r, int):
            return [x for x in MIC_RATES if x == r]
    return [48000]


def mic_rate_setting():
    """The rate the app set for the mic (None = PipeWire decides)."""
    try:
        with open(MIC_CONF) as f:
            m = re.search(r"audio\.rate\s*=\s*(\d+)", f.read())
    except OSError:
        return None
    return int(m.group(1)) if m else None


def set_mic_rate(source_name, rate):
    """Record the head unit mic at `rate` (None = follow PipeWire): a
    WirePlumber rule for that source. Rule props only apply when a node is
    created, so WirePlumber is restarted: audio on every device drops for a
    moment."""
    if rate:
        os.makedirs(os.path.dirname(MIC_CONF), exist_ok=True)
        with open(MIC_CONF, "w") as f:
            f.write("# Written by Sound Blaster Command (sbae9-sbc): the AE-9 head unit mic's\n"
                    "# sample rate. Pick Automatic in the app, or delete this file, to undo.\n"
                    "monitor.alsa.rules = [\n"
                    "  {\n"
                    f'    matches = [ {{ node.name = "{source_name}" }} ]\n'
                    f"    actions = {{ update-props = {{ audio.rate = {int(rate)} }} }}\n"
                    "  }\n"
                    "]\n")
    else:
        try:
            os.remove(MIC_CONF)
        except FileNotFoundError:
            return
    _run("systemctl", "--user", "restart", "wireplumber", timeout=10)


# --- What U Hear (and other extra inputs) rate ------------------------------------
# These sources are defined by the driver's PipeWire configs (context.objects),
# whose audio.rate fixes the rate they record at. The driver's README says to
# change that line for 96 kHz, so the app does just that and restarts PipeWire.
_RATE_LINE = re.compile(r"^(\s*audio\.rate\s*=\s*)(\d+)", re.M)
_FORMAT_LINE = re.compile(r'^(\s*audio\.format\s*=\s*)"([^"]*)"', re.M)


def input_conf(device, card_id="AE9"):
    """The user's PipeWire config that defines hw:<card>,<device>, or None."""
    pat = re.compile(r'api\.alsa\.path\s*=\s*"hw:%s,%d"' % (re.escape(card_id), device))
    try:
        names = sorted(os.listdir(PW_CONF_DIR))
    except OSError:
        return None
    for name in names:
        path = os.path.join(PW_CONF_DIR, name)
        if not name.endswith(".conf"):
            continue
        try:
            with open(path) as f:
                if pat.search(f.read()):
                    return path
        except OSError:
            continue
    return None


def input_conf_rate(path):
    """The rate set in that config (audio.rate), or None."""
    try:
        with open(path) as f:
            m = _RATE_LINE.search(f.read())
    except (OSError, TypeError):
        return None
    return int(m.group(2)) if m else None


def input_conf_format(path):
    """The sample format set in that config (audio.format, e.g. S32LE), or None."""
    try:
        with open(path) as f:
            m = _FORMAT_LINE.search(f.read())
    except (OSError, TypeError):
        return None
    return m.group(2) if m else None


def set_input_conf_format(path, fmt):
    """Set audio.format in that config and restart PipeWire (fmt None/"" removes
    the line: PipeWire negotiates it). Audio drops for a moment."""
    with open(path) as f:
        text = f.read()
    if fmt:
        new = _FORMAT_LINE.sub(lambda m: f'{m.group(1)}"{fmt}"', text, count=1)
    else:
        new = re.sub(r'^\s*audio\.format\s*=\s*"[^"]*"[ \t]*\n', "", text, count=1, flags=re.M)
    if new == text:
        return False
    tmp = path + ".new"
    with open(tmp, "w") as f:
        f.write(new)
    os.replace(tmp, path)
    _run("systemctl", "--user", "restart", "pipewire", timeout=15)
    return True


def set_input_conf_rate(path, rate):
    """Set audio.rate in that config and restart PipeWire, which re-creates
    the node: audio on every device drops for a moment. rate 0 removes the
    line (Automatic): the node then follows the graph's rate."""
    with open(path) as f:
        text = f.read()
    if rate:
        new = _RATE_LINE.sub(lambda m: f"{m.group(1)}{int(rate)}", text, count=1)
    else:
        new = re.sub(r"^\s*audio\.rate\s*=\s*\d+[ \t]*\n", "", text, count=1, flags=re.M)
    if new == text:
        return False
    tmp = path + ".new"
    with open(tmp, "w") as f:
        f.write(new)
    os.replace(tmp, path)
    _run("systemctl", "--user", "restart", "pipewire", timeout=15)
    return True


# --- test tone ----------------------------------------------------------------
# test tone channels -> position in the stream
TONE_POS = {"left": "FL", "right": "FR", "center": "FC", "sub": "LFE",
            "rear-left": "RL", "rear-right": "RR"}
SURROUND_MAP = ["FL", "FR", "FC", "LFE", "RL", "RR"]

# Spoken channel names from alsa-utils (not shipped with this app). The sub
# gets the noise burst, as in speaker-test.
VOICE_DIR = "/usr/share/sounds/alsa"
VOICE_FILES = {"left": "Front_Left.wav", "right": "Front_Right.wav", "center": "Front_Center.wav",
               "sub": "Noise.wav", "rear-left": "Rear_Left.wav", "rear-right": "Rear_Right.wav"}


def voice_file(channel):
    path = os.path.join(VOICE_DIR, VOICE_FILES.get(channel, ""))
    return path if os.path.isfile(path) else None


def voices_available():
    return all(voice_file(c) for c in ("left", "right"))


def _tone_file(channel, surround=False):
    """A short tone on one channel: stereo file, or 6-channel FL FR FC LFE RL RR."""
    layout = SURROUND_MAP if surround else ["FL", "FR"]
    path = os.path.join(config.cache_dir(), f"test-{channel}{'-51' if surround else ''}.wav")
    if os.path.exists(path):
        return path
    pos = TONE_POS.get(channel)
    rate, secs = 48000, 1.2
    freq = 55.0 if pos == "LFE" else 440.0   # the sub gets a low note
    n = int(rate * secs)
    frames = bytearray()
    for i in range(n):
        env = min(1.0, i / 2400, (n - i) / 2400)  # 50 ms fades, no clicks
        # 440 Hz with a little 880 so small speakers show it too
        s = 0.25 * env * (math.sin(2 * math.pi * freq * i / rate) +
                          0.3 * math.sin(4 * math.pi * freq * i / rate))
        v = int(max(-1.0, min(1.0, s)) * 32767)
        frames += struct.pack(f"<{len(layout)}h", *[
            v if (ch == pos or pos is None) else 0 for ch in layout])
    with wave.open(path, "wb") as w:
        w.setnchannels(len(layout))
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


class TestTone(QObject):
    """Tests each speaker in turn (left, right, ... on a 5.1 stream).

    Uses the spoken channel names from alsa-utils when installed: a mono
    stream with one channel position, which PipeWire routes to that speaker
    only. Without them, a generated tone."""
    step = Signal(str)   # "left", "right", "center", ... or "" when done

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = []
        self._proc = None
        self._target = None
        self._surround = False

    @property
    def running(self):
        return self._proc is not None

    def start(self, target_name, channels=("left", "right"), surround=False):
        self.stop()
        self._target = target_name
        self._surround = surround
        self._queue = list(channels)
        self._next()

    def stop(self):
        self._queue = []
        if self._proc:
            p, self._proc = self._proc, None
            p.finished.disconnect()
            p.kill()
            p.waitForFinished(500)
        self.step.emit("")

    def _next(self, *_):
        if not self._queue:
            self._proc = None
            self.step.emit("")
            return
        ch = self._queue.pop(0)
        voice = voice_file(ch)
        if voice and ch in TONE_POS:
            args = ["--channels", "1", "--channel-map", TONE_POS[ch], voice]
        else:
            args = [_tone_file(ch, self._surround)]
            if self._surround:
                args = ["--channels", "6", "--channel-map", ",".join(SURROUND_MAP)] + args
        if self._target:
            args = ["--target", self._target] + args
        self._proc = QProcess(self)
        self._proc.finished.connect(self._next)
        self._proc.start("pw-play", args)
        self.step.emit(ch)


class MicMonitor(QObject):
    """'Listen to this device': loops the AE-9 input to the default output."""
    state = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None

    @property
    def running(self):
        return self._proc is not None

    def start(self, source_name):
        self.stop()
        self._proc = QProcess(self)
        self._proc.finished.connect(self._done)
        self._proc.start("pw-loopback", [
            "-n", "sbae9-mic-monitor", "-l", "20",
            "-C", source_name,
            "--capture-props", "node.description='AE-9 mic monitor' node.dont-reconnect=true",
            "--playback-props", "media.role=Communication node.description='AE-9 mic monitor'",
        ])
        self.state.emit(True)

    def stop(self):
        if self._proc:
            p, self._proc = self._proc, None
            p.finished.disconnect()
            p.terminate()
            if not p.waitForFinished(800):
                p.kill()
        self.state.emit(False)

    def _done(self, *_):
        self._proc = None
        self.state.emit(False)


class LevelMeter(QObject):
    """Peak level of a source in dBFS per channel, from raw pw-record output."""
    levels = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None
        self._buf = b""
        self._peak = [-90.0, -90.0]
        self._timer = QTimer(self, interval=50)
        self._timer.timeout.connect(self._emit)

    def start(self, source_name):
        self.stop()
        self._proc = QProcess(self)
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.start("pw-record", ["--raw", "--target", source_name, "--rate", "48000",
                                       "--channels", "2", "--format", "s16",
                                       "-P", "node.description='AE-9 level meter' node.dont-reconnect=true",
                                       "-"])
        self._timer.start()

    def stop(self):
        self._timer.stop()
        if self._proc:
            p, self._proc = self._proc, None
            p.readyReadStandardOutput.disconnect()
            p.terminate()
            if not p.waitForFinished(500):
                p.kill()
        self._peak = [-90.0, -90.0]
        self.levels.emit(-90.0, -90.0)

    def _read(self):
        if not self._proc:
            return
        data = self._buf + bytes(self._proc.readAllStandardOutput())
        usable = len(data) - len(data) % 4
        self._buf = data[usable:]
        if not usable:
            return
        samples = struct.unpack(f"<{usable // 2}h", data[:usable])
        for ch in (0, 1):
            pk = max((abs(x) for x in samples[ch::2]), default=0)
            db = 20 * math.log10(pk / 32768) if pk else -90.0
            self._peak[ch] = max(self._peak[ch], db)

    def _emit(self):
        self.levels.emit(*self._peak)
        # simple peak hold with fall-off
        self._peak = [max(-90.0, p - 3.0) for p in self._peak]


class Watcher(QObject):
    """Refreshes the PipeWire snapshot in the background (pw-dump via QProcess)."""
    updated = Signal(object)  # Nodes

    def __init__(self, parent=None, interval=2500):
        super().__init__(parent)
        self.nodes = Nodes([])
        self._proc = None
        self._timer = QTimer(self, interval=interval)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        if self._proc is not None or not available():
            return
        self._proc = QProcess(self)
        self._proc.finished.connect(self._done)
        self._proc.start("pw-dump", [])

    def _done(self, *_):
        p, self._proc = self._proc, None
        try:
            objs = json.loads(bytes(p.readAllStandardOutput()).decode() or "[]")
        except (json.JSONDecodeError, UnicodeDecodeError):
            objs = []
        p.deleteLater()
        self.nodes = Nodes(objs)
        self.updated.emit(self.nodes)
