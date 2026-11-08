# Changelog

Sound Blaster Command for Linux: the UI for the Creative Sound Blaster AE-9
driver ([SbAe9-Drv](https://github.com/3xHelix/SbAe9-Drv)).

## Unreleased

### Added

- **Optical output sample rate** (Playback → Digital): the separate optical
  PCM can run at its own rate, `Automatic` (follows the card) or a fixed
  44.1/48/88.2/96/176.4/192 kHz, set as `audio.rate` in its PipeWire config
  (`hw:AE9,4`, `ae9-optical-out.conf`). It's independent of the main output:
  the two can play at different rates at the same time, and streams at other
  rates are resampled for the optical. Changing it restarts PipeWire, so
  audio drops for a moment.

## 0.13.0 (2026-11-07)

Panel widgets for KDE Plasma and GNOME with keyboard shortcuts, the head
unit's rear RCA input, and a subwoofer boost switch. Pairs with
[SbAe9-Drv v0.10.1](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.10.1).

### Added

- A KDE Plasma 6 panel widget, "Sound Blaster AE-9" (install.sh installs
  it): Direct Mode / DSP, SBX (two stages, as in the app: DSP first), sample
  rate, bit depth, PipeWire quantum with the latency, and phantom power
  (48V, after a warning). It runs the new `sbae9-sbc ctl`, so it follows
  the app's rules (rate cap per mode, the quantum high rates need).
- The KDE widget's settings: which sample rates and quantum values its
  lists show (any quantum from 8 to 8192), and an optional quick preset
  button (a rate and a quantum at once), as the pw widget has.
- KDE global shortcuts, no keys by default: Toggle Direct Mode / DSP,
  Toggle Speakers / Headphones and Toggle SBX (System Settings > Keyboard >
  Shortcuts > Sound Blaster Command; the widget's settings link there). Each
  shows a short notification. They're also in the app's launcher menu.
- The same as a GNOME Shell extension (GNOME 45-50), "Sound Blaster AE-9"
  in the top bar; install.sh installs it where GNOME is installed. Its
  preferences (Extensions app) have the same rate and quantum lists and
  quick preset, and three keyboard shortcuts (no keys by default) that show
  what changed in GNOME's on-screen popup.
- `sbae9-sbc ctl`: status as JSON and the same changes from the command
  line (`sbae9-sbc ctl --help`), with `toggle` and `--notify` for shortcuts.
- Recording > Other Input: the head unit's rear RCA jacks ("Head unit rear
  RCA", Creative's Aux), driver 0.10.1+. Records alongside the mic as its own
  device, with Set Default; it needs the driver's `config/ae9-rear-rca-in.conf`
  in PipeWire's config folder. No level control yet (the driver doesn't have
  one yet).
- A quantum pick is kept across rate changes, but never below what a high
  rate needs (1024 at 176.4/192 kHz, 2048 at 384 kHz).

### Changed

- Headphone profiles are also found in `/lib/firmware/updates/creative-ae9/hp`
  and `/usr/lib/firmware/updates/...` (Arch installs there, since another
  file clashes with linux-firmware's AE-5/AE-7 one). Thanks, Kaiba.
- The Headphone Profile tip says how driver 0.10.1 loads curves: a moment
  after you stop on one, and if loading fails that profile's EQ stays off.
- Settings written by the widget are read back by an open app.
- The bottom bar's mode switch reads Direct Mode / DSP (Direct on the
  left), the order you switch things on, as in the panel widgets.
- Speaker Setup: Sub Gain is now a "Subwoofer boost" on/off box. It was
  never a dB level: Creative's setting is an on/off subwoofer boost. Uses
  the driver's "Bass Redirect Sub Boost Switch" (0.10.1+); on driver 0.10.0
  it writes the old gain control (0 off, 6 on).

## 0.12.0 (2026-11-07)

Speaker Setup and headphone profiles. Pairs with
[SbAe9-Drv v0.10.0](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.10.0).

### Added

- Playback → Speaker Setup tab (driver 0.10.0+; older drivers show a
  note): Bass Redirect with a Speaker Type
  picker as on Windows (Tower 80 Hz, Desktop 120 Hz, or a custom crossover
  from 50 to 200 Hz) and Sub Gain, and Speaker Calibration: a level
  (-12 to +12 dB) and a distance (0 to 500 cm, a delay of about 0.29 ms
  per 10 cm) for each speaker in the Speaker Config. Works with Direct
  Mode off; in Direct Mode it's greyed out with a button to turn it off.
- Headphone Profile under Headphones (driver 0.10.0+): Creative's EQ
  correction for 32 headphone models, read from the driver. It acts with
  Direct Mode off, on Headphones, at 48 kHz, and says when it's resting.
  Greyed out, with how to install them, when Creative's curves are missing
  (`ae9-get-firmware`).
- A DSP / Direct Mode switch in the bottom bar, next to the
  headphones / speakers one and styled the same.

### Changed

- The stream picker on Playback reads "Stereo Stream" / "5.1 Stream".

## 0.11.2 (2026-11-06)

Voice-chat node fix. Pairs with
[SbAe9-Drv v0.9.8](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.9.8).

### Fixed

- With the driver's optional WebRTC voice config installed, the app took
  its "AE-9 Voice Chat Playback" and "AE-9 Voice (WebRTC)" nodes for the
  card's own output and mic (rates, Set Default, volume and the mic rate
  went to the wrong node). Virtual nodes named after the card are skipped
  now (kit 0.3.5).

## 0.11.1 (2026-11-06)

176.4 kHz. Pairs with
[SbAe9-Drv v0.9.7](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.9.7).

### Added

- 176.4 kHz in the sample-rate picker (driver 0.9.7+, `pcm_176k4=Y`), with
  the same rules as 44.1/88.2: stereo in Direct Mode only. On the 5.1
  stream it plays at 192 kHz, with Direct Mode off at 96 kHz (48 without
  `dsp_96k`), and it comes back in stereo / Direct Mode. It gets the bigger
  buffer 192 kHz uses, and PipeWire's allowed rates list it.
- Settings → Device lists the driver's new `pcm_176k4` and `src_reclock`
  options (and `wuh_96k`) read-only. The playback rates line comes from the
  driver's options now.

## 0.11.0 (2026-11-06)

Phantom power from the app, and What U Hear at 96 kHz. Pairs with
[SbAe9-Drv v0.9.5](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.9.5).
Older drivers still work: phantom power shows as an indicator (or not at
all) and What U Hear stays at 48 kHz.

### Added

- Phantom power (48 V on the head unit's XLR/TRS jack) on Recording →
  Microphone. With a driver that can switch it, a "Phantom Power 48V"
  button that lights red when on; with one that only reports it, its state
  ("On/Off — switched by the head unit's button"); hidden on older drivers.
  It always shows the live state and follows the head unit's own button.
  Needs SbAe9-Drv v0.9.5 ("Head Unit Phantom Power").
- Turning it on asks first: a warning that 48 V can damage some equipment
  (ribbon mics, some line-level sources), Cancel or Turn on. Settings →
  Device can switch that to "Two clicks turn on, one turns off": the first
  click arms the button (blinking red outline, "Click again to turn on",
  3 s), the second turns it on. Turning off is always one click.
- If the card just started and refuses 48 V for a few seconds, or the head
  unit hasn't reported in yet, the app says so under the button.
- What U Hear's sample rate on Recording → Other Input: 48 or 96 kHz (96
  kHz with driver 0.9.5+, `wuh_96k`). It sets `audio.rate` in your copy of
  the driver's `ae9-what-u-hear.conf` and restarts PipeWire (asks first).

### Changed

- The app never turns phantom power on by itself: it isn't saved in
  settings or profiles, and Settings → Device's control table shows it
  greyed out. Read-only driver controls there are greyed out too.

## 0.10.0 (2026-11-06)

Every rate the card plays, CD rates included. Pairs with
[SbAe9-Drv v0.9.4](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.9.4):
44.1 and 88.2 kHz as is, 5.1 at 192 kHz, and 96 kHz with SBX on. Older
drivers still work, with the shorter rate lists they had.

### Added

- 44.1 and 88.2 kHz in the sample-rate picker, for CD-family music played as
  is (driver 0.9.4+, `pcm_rates=2`). Stereo in Direct Mode only: on the 5.1
  stream they're greyed out, and a 44.1/88.2 pick plays at 48/96 kHz there.
- 5.1 at 192 kHz (driver 0.9.4+, `surround_192k=1`). Only 384 kHz is stereo
  only now.
- 96 kHz with Direct Mode off, stereo and 5.1, SBX on or off (driver 0.9.4+,
  `dsp_96k=Y`). Other picks move to 48 or 96 kHz in DSP mode (44.1 -> 48,
  88.2/192/384 -> 96) and come back with Direct Mode on.
- Settings → Device lists the driver's rate options (`pcm_rates`,
  `dac_441`, `surround_192k`, `dsp_96k`, ...) read-only, and the 5.1 and
  DSP-mode rates.

### Changed

- "Follow the file" (Auto) lets PipeWire open the card at 44.1 and 88.2 kHz
  too. A rates file written by an older version is brought up to date at
  start.
- Direct Mode's ⓘ drops the "pause and play" hint on driver 0.9.4+: the
  driver restarts a playing stream itself now.
- README: the head unit's plug indicators, the auto switch and the "Mic
  Gain" name now name their driver,
  [SbAe9-Drv v0.9.3](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.9.3),
  which shipped them with the exact names the app already uses.

## 0.9.1 (2026-11-06)

Easier on the eyes. Captions say what's happening, not where every jack is:
hover for the details. Same drivers as 0.9.0.

### Changed

- Shorter captions, easier on the eyes: they show the state, and the
  details moved into tooltips (hover) and the ⓘ buttons. Headphones just
  says "Plugged In" / "Unplugged"; speakers say "5.1 Surround ·
  6-ch stream" (hover for which of the card's outputs that uses); the
  Recording page says "Microphone", "3.5 mm mic: plugged in" and "Hear the
  mic live". Without the driver's naming config the mic is called "AE-9
  Head Unit Mic / Aux" instead of PipeWire's long "CA0132 Sound Core3D
  [...] Analog Stereo".

## 0.9.0 (2026-11-06)

Under the hood and on the labels. Sound Blaster Command and SbAe9-AudioMon
now stand on one shared base, every jack is called by where it actually is,
and the mic gain gets its real name. Works with
[SbAe9-Drv v0.9.2](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.9.2)
and older; the head unit's plug detection and the "Mic Gain" control name
arrive with the next driver, and until then the app uses what's there.

### Changed

- `install.sh` installs a copy of the app (`~/.local/share/sbae9-sbc`)
  instead of pointing the menu at the project folder, the same way
  SbAe9-AudioMon installs. The menu app is the last build you installed,
  never something half-edited; re-run `./install.sh` to update it.
- Built on **SbAe9-Kit** now, the base it shares with SbAe9-AudioMon: the
  palettes, Glass, UI scale / XWayland handling, frameless window parts,
  AE-9 detection, the ALSA binding and the icon tool live there, vendored
  into `sbae9kit/`. Nothing you'd notice: the screenshots come out
  pixel-identical. The icon tool moved to SbAe9-Kit, and the tests use the
  kit's shared fake AE-9 mixer and snapshots.
- Jacks are named the same way everywhere, after where they are. On the
  head unit: the XLR/TRS jack, the 3.5 mm mic jack, and the 3.5 mm and 1/4"
  headphone jacks. On the card: the RCA out, the 3.5 mm Rear out, the
  3.5 mm C/Sub out, and Optical out and in. So the speaker captions say
  "RCA out, 3.5 mm C/Sub out, 3.5 mm Rear out", Recording shows "Head unit
  3.5 mm mic jack: plugged in" (it's the mic jack, not a line-in), and the
  auto switch says it's the head unit's 3.5 mm headphone jack that reports
  plugs (the 1/4" doesn't).
- **XLR Gain is now "Mic Gain"** (Recording and Mixer): it boosts both of the
  head unit's mic jacks, the XLR/TRS and the 3.5 mm (they share one input;
  tested at +20 dB on both). It follows the driver's new "Mic Gain Capture
  Volume" control, and released drivers' "XLR Gain" control still works.
- The head unit's plug indicators use the driver's new control names
  ("Head Unit 3.5mm Phones Plugged", "Head Unit 3.5mm Mic Plugged"); the
  test builds' old names still work.

### Fixed

- Reopening the app (for a new UI scale or Glass) could close the window
  even when the new copy failed to start; it now stays open in that case.
- Albino: the EQ curve's points had white rings that disappeared on the
  light graph; they're coral there now (dark palettes keep white).

## 0.8.1 (2026-11-06)

GNOME polish. Two small things that only showed up off KDE. Same drivers
as 0.8.0.

### Fixed

- Through XWayland (Glass on, or a UI scale other than 100%) the window now
  calls itself `sbae9-sbc`, so docks match it to the menu entry and show
  the right icon (it said `-c`, which GNOME's dash couldn't place).
- Settings → Device → "Open alsamixer" also finds GNOME's terminals (Ptyxis
  on Fedora 41+, Console) and a few others, and says what to run if there's
  no terminal at all instead of doing nothing.

## 0.8.0 (2026-11-06)

Looks round. A new icon, and Glass: frosted see-through backgrounds on any
palette, with KDE blurring whatever's behind. Plus the app is ready for the
head unit's plug detection, which lands with the next driver. Works with
[SbAe9-Drv v0.9.2](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.9.2)
and older; anything a driver doesn't have stays hidden.

### Added

- **Glass** (Settings → Application): the window's backgrounds go
  see-through on whichever palette you're using, with an Opacity slider
  from 95% down to 30% that works live. Text, dials, sliders and the EQ
  curve stay solid. On KDE what's behind gets properly frosted: with Glass
  on, the app runs through XWayland, where KDE's blur works for it.
  Elsewhere it's clear glass.
  Switching Glass on or off reopens the window (a second).
- **New app icon**: a neon mixer tile in purple and orange, for the menu,
  taskbar and the window itself, in every size from 16 to 512 px. Re-run
  `./install.sh` to pick it up. (`tools/make_icons.py` rebuilds the sizes
  from the artwork.)
- **Auto switch on headphone plug** (Playback, under Headphones): plug
  headphones into the head unit's 3.5 mm jack and the card switches to them,
  unplug and it's back to speakers. Off unless you turn it on. Only the
  3.5 mm jack is reported, so the 6.3 mm one can't do this. Shows up with
  the next driver release (after v0.9.2).
- Plugged-in indicators: Playback shows whether something's in the head
  unit's 3.5 mm headphone jack, Recording whether the 3.5 mm line-in is in
  use. They follow the plugs live. Hidden on drivers that don't report them.

## 0.7.0 (2026-11-06)

More stuff, more tabs. Playback, Recording and Settings now have tabs across
the top like on Windows, so new things have somewhere to live instead of
piling up on one page. The app remembers which tab you were on. Goes with
[SbAe9-Drv v0.9.1](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.9.1):
What U Hear needs v0.9.0 or newer, recording at 96 kHz / 32-bit v0.9.1.
Older drivers still work; the new bits just stay hidden or greyed out.

### Added

- **Playback → Digital**: Optical Out moved here, with what the optical jack
  is getting right now (e.g. "96 kHz · 24-bit · stereo").
- **Recording → Other Input**: Optical In and **What U Hear** (records
  whatever the card plays, for streaming or capturing; needs driver v0.9.0
  or newer and its `ae9-what-u-hear.conf`). Each has its own Set Default,
  or tells you how to set it up.
- **Settings → Application / Device**: looks and start-up on one tab, the
  card's info, reset and every hardware control on the other.
- **Start Sound Blaster Command when you log in** (Settings → Application).
- **Mic sample rate and bit depth** (Recording → Microphone → Quality):
  Automatic, 48 or 96 kHz, plus what it's recording at right now. 96 kHz
  needs driver v0.9.1 or newer; older drivers offer 48 only.
  Changing the rate restarts WirePlumber, so audio on every device drops for
  a moment; the app asks first. Bit depth is 24-bit, or 24 / 32-bit (as
  Windows) with driver 0.9.1 or newer, from the next recording. 32-bit is
  full 32-bit samples from the card's DSP; it sounds the same as 24-bit,
  but it's there if your workflow wants it.
- The Recording page uses the input's desktop name ("AE-9 Mic / Line In"
  with the driver's naming rule), and says the XLR / TRS jack and the head
  unit's 3.5 mm line-in share it.

### Changed

- All three start-up options (start at login, re-apply the SBX profile,
  reload the last sample rate) are off until you turn them on. Out of the
  box the app changes nothing at start; it just shows what's running.
  Already turned one on? It stays on.

### Fixed

- **Dropdowns at a UI scale other than 100%** opened way off to the side of
  their box on Wayland (a Qt bug with scaled popups). A scaled app now runs
  through XWayland, where the lists drop right where they should; at 100%
  it stays native Wayland. A `QT_QPA_PLATFORM` you set yourself still wins.
- The mic level meter kept running while you weren't looking at it; it now
  only runs on the Microphone tab.

## 0.6.0 (2026-11-05)

Optical has entered the chat. Needs
[SbAe9-Drv v0.8.0](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.8.0) or
newer; on older drivers none of this shows up.

### Added

- **Optical Out** (Playback): a switch for the card's optical (S/PDIF)
  output, which plays whatever the main output plays. It's picky: stereo,
  24-bit, up to 192 kHz. Run 32-bit, 384 kHz or 5.1 and it goes quiet, so
  the app tells you so in red instead of leaving you wondering. No SBX or
  EQ on it, and the volume knob doesn't touch it; your receiver does the
  volume.
- **Optical In** (Recording): if PipeWire lists the AE-9's optical input
  (the driver's `ae9-optical-in.conf`), it shows up with its own Set
  Default, and the app tells you how to set it up if it isn't there yet.
  It records alongside the XLR mic, and the app never mixes the two up.

### Fixed

- The test suite could fail now and then: each test's app kept running in
  the background and fiddled with the next test's sample rate. Tests clean
  up after themselves now. (Tests only; the app itself was fine.)

## 0.5.0 (2026-11-05)

Catching up with [SbAe9-Drv v0.7.0](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.7.0),
which slayed the dragons: 5.1 at 96 kHz plays clean now, so the app treats
it like any other rate. Plus a few comfort things: shrink the whole app
down, lose the window frame, and decide whether your last rate comes back
when the app starts. Older drivers still work, same as before.

### Added

- **UI scale** (Settings → Appearance): a slider from 70% to 150% that
  shrinks or grows the whole app, dials, text and all, so it sits nicely in
  a smaller window. Hit Apply and the window pops back up at the new size
  in about a second. `--scale 80` tries a size for one launch without
  saving it.
- **No more window frame.** The app wears its own title bar now: grab the
  AE-9 header to move it, double-click it to maximize, drag any edge to
  resize, and there's a little minimize and close up in the corner (close
  goes red, so you know). Like the frame back? Settings → Appearance, one
  checkbox.
- **"Reload the last sample rate when the app starts"** (Settings → App).
  On (as before): your last pick comes back at launch. Off: the app opens,
  shows whatever PipeWire is running and touches nothing until you pick a
  rate. Your last pick is still remembered for when you turn it back on.
- A test suite (`python3 -m unittest discover -s tests`): ~70 tests, a few
  seconds, no card needed. It runs against a fake AE-9 and a fake PipeWire,
  so it never touches your card, your PipeWire or your settings.
- `tools/screenshots.py` regenerates the README screenshots in any palette.

### Changed

- **5.1 at 96 kHz, for real** (driver v0.7.0 or newer, with its
  `surround_96k` option on, which is the default): the picker offers a plain
  "96 kHz" on a 5.1 stream, it comes back at start like any other pick, and
  a higher pick (192 / 384 kHz) lands on 96 kHz in 5.1 instead of dropping
  to 48. DSP mode still runs at 48 kHz. On older drivers it stays the
  "here be dragons" option it was.
- README screenshots redone in the Helix palette, on a 5.1 setup.

### Fixed

- Playback: a long speaker description (5.1) could push the bit-depth box
  off the edge of the window. It wraps now.
- Recording: the Listen switch had no gap before its text.

## 0.4.1 (2026-11-04)

The driver caught up. [SbAe9-Drv v0.6.8](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.6.8)
is out, and it's the one 0.4.0 was waiting for: 48–384 kHz out of the box,
the "PCM Bit Depth" control (so the 24 / 32-bit picker finally does
something), 5.1 locked to a sane 48 kHz with the `surround_96k` dragons
behind a door, and the EQ presets in a sensible order. Get v0.6.8 or newer
for all of that; older drivers still work, just with less to pick from.

### Changed

- "Applying changes…" gives the card one more second per change: 5 s after
  Direct Mode or a stereo / 5.1 switch, 4 s after speakers, rate or bit
  depth (11 s at most). The card asked nicely.
- EQ presets: the list follows the driver, so with v0.6.8 it's music A-Z
  with the game presets (Project CARS, Racing, Rocket League, RPG) under
  their own "Games" heading at the bottom, like on Windows. Older drivers
  keep their old order. Presets are kept by name, so nothing gets mixed up
  when the order changes.
- README: which features need v0.6.8 (rate picker in full, bit depth,
  preset order).
- README: Helvum gets a mention as a handy companion for seeing where your
  audio actually goes.

## 0.4.0 (2026-11-04)

The "slow down, cowboy" release. Sample rate and bit depth get a proper
picker, and the app now gives the card a moment to breathe between big
changes, because tonight's testing showed it really, really wants one.

Works with [SbAe9-Drv v0.6.7](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.6.7).
The bit-depth picker and the experimental 5.1 at 96 kHz light up with the
next driver release (it adds the "PCM Bit Depth" control and the
`surround_96k` option); until then the depth shows greyed out.

### Added

- **Sample rate + bit depth picker** (Playback → Audio Quality): Automatic,
  48, 96, 192 or 384 kHz, and 24- or 32-bit. Picking a depth reopens the card
  so it kicks in right away. On older drivers the depth shows what the
  driver's `pcm_bits` option is set to, greyed out.
- **"Applying changes…"**, like Creative's own app. Direct Mode, speaker
  layout, stereo / 5.1 stream, sample rate and bit depth now go one at a
  time, each with a few seconds to settle (3-4 s, done early once the card
  is back, never more than 10 s), behind a notice that keeps you from
  clicking the next one too soon. Several at once (say 5.1 plus the rate it
  needs) go in a row inside one notice. Turns out this card doesn't do a 180
  on a dime: fast bursts of changes were behind every stuck-DSP and
  stuttering-stream moment in testing. Effects, sliders and the EQ aren't
  slowed down.
- Shows what the card is actually running right now, e.g. "384 kHz · 32-bit ·
  stereo".

### Changed

- Rates the card can't take right now are greyed out, with the reason:
  DSP mode runs at 48 kHz, and so does 5.1. Switch Direct Mode
  off while forced to 384 kHz and the app drops PipeWire to 48 kHz; switch it
  back on and your 384 kHz comes back. Same for leaving 5.1.
- 5.1 at 96 kHz is in there, but you have to go looking for it: with the
  driver's `surround_96k` option set to 1, the picker offers "96 kHz
  (experimental: here be dragons)" on a 5.1 stream. It stutters more and
  more as it plays, so the app never picks or restores it on its own. Leave
  5.1 or restart the app and you're back at a sensible 48 kHz.
- The app only touches PipeWire's rate when you pick one in it. Set a rate
  or quantum by hand (`pw-metadata`) and it stays put; the picker just shows
  "PipeWire is set to … outside the app". On Automatic the app leaves
  PipeWire completely alone.
- The PipeWire drop-in (`90-sbae9-sbc-rates.conf`) always lists all four
  rates. Caps like DSP mode's 48 kHz only go into the live forced rate, so
  PipeWire never gets stuck opening the card at 48 kHz and resampling.
- 192 and 384 kHz get a bigger PipeWire buffer (quantum 1024 / 2048), so 384
  kHz stops crackling. 48/96 kHz and Automatic leave PipeWire's own buffer
  alone.

## 0.3.0 (2026-11-04)

5.1 has entered the building. Goes hand in hand with
[SbAe9-Drv v0.6.7](https://github.com/3xHelix/SbAe9-Drv/releases/tag/v0.6.7),
which taught the card to do surround. You need that driver with its PipeWire
profile set installed
([setup step 4](https://github.com/3xHelix/SbAe9-Drv#4-pipewire-profiles-stereo-and-51))
for the 5.1 bits; on an older driver the app carries on in stereo like
nothing happened.

### Added

- **5.1 stream switching.** Pick 4.0, 4.1 or 5.1 speakers and the app flips
  PipeWire over to the 5.1 profile; pick 2.0 or 2.1 and it goes back to
  stereo. Your mic input comes along for the ride. A new **Stereo stream /
  5.1 stream** box shows which one you're on, keeps up when you change it in
  KDE's sound settings, and still works in Direct Mode. The app only
  switches when *you* pick something, so it and the driver don't argue. It
  stays hidden without the driver's profile set, and keeps its hands off
  "pro-audio" or "off" if you picked those yourself.
- **Speaker test that talks.** Test now says "Front Left", "Front Center",
  "Rear Right"… out of each speaker in turn, using the voice files from
  alsa-utils (not bundled here). The sub gets a burst of noise, because subs
  don't talk. Click a speaker in the diagram to test just that one. No
  alsa-utils? You get a tone instead.
- The speaker diagram draws 4.0, 4.1 and 5.1 layouts, and the Mixer grows a
  slider for each of the six channels on a 5.1 stream.

### Changed

- "This won't be heard because Direct Mode / SBX / Scout Mode…" notices,
  and the "card not found" bar, are now warning red with a red button. Same
  red in every palette, so a warning always looks like a warning.
- The bottom bar says "SBX | Off" instead of "SBX | SBX off". We heard you
  the first time.

## 0.2.1 (2026-11-04)

Mixer round: independent Left/Right volume, like the desktop's own mixer.
Same driver as before (0.6.x).

### Changed

- **Mixer**: the Left/Right balance slider is replaced by one slider per
  channel (Front Left, Front Right, and more on surround outputs), on the same
  percent scale as the desktop's volume control. **Link channels** moves them
  together; **Equalise** sets them all to the loudest.
- Channel levels are set on the card's output route, the way the desktop
  mixer does it: the card's hardware Master follows the loudest channel and
  only the quieter ones are trimmed in software, so one side can be quiet
  without pulling the whole output down.

## 0.2.0 (2026-11-04)

Colour round: three new palettes to go with the original, and a flag to
pick one from the command line. Same driver as before (0.6.x).

### Added

- **Palettes**, switched under Settings → Appearance (remembered between
  launches):
  - **Helix**: blue-black and violet with coral-orange and amber accents and
    a mint EQ curve.
  - **Albino**: a light theme in off-white, cream, blush and peach with a
    coral accent.
  - **Wololo**: a monk's royal-blue robe and white cloth, sun-gold controls,
    a grass-green EQ curve and a staff-brown touch.
- `--palette NAME` starts the app in a palette for one launch without
  changing the saved one; `--version` and `--help`.

### Changed

- The built-in SBX profiles are labelled "Built-in" instead of
  "The Sound Blaster Team"; they're this app's presets, not Creative's.
- README: screenshots of the main pages.

## 0.1.0 (2026-11-04)

First release. Needs driver 0.6.x (the one with SBX on the card's DSP).

- **SBX Profile:** SBX switch, Surround / Crystalizer / Bass / Smart Volume
  (Night, Normal, Loud) / Dialog+ dials, built-in profiles (Default, Gaming,
  Movie, Music, Night) and your own.
- **Equalizer:** 10 bands + pre-gain on the card's DSP, Creative's 20 presets,
  saved custom curves.
- **Playback:** speakers / headphones, 2.0 / 2.1, Direct Mode, DAC filter,
  sample rate (48-384 kHz via PipeWire), default device, L/R test tone.
- **Recording:** XLR mic level and gain, live input meter, mute, listen to mic.
- **Scout Mode**, **Mixer** (volume, mute, balance) and **Settings** (driver
  info, every ALSA control including inactive ones).
- Follows the head-unit knob, alsamixer and the desktop slider live (ALSA
  control events).
