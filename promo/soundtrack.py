#!/usr/bin/env python3
"""Composes the film's sound and writes it as two stems, the music and the
effects, each exactly as long as the film.

    .venv/bin/python promo/soundtrack.py

Nothing in the music is a recording. Every instrument is synthesized here, so
the film carries no music anybody else holds a license to. The four effects
that are recordings come from assets/sfx/, and CREDITS.md there states their
license.

Every moment a sound shares with a picture is taken from the cue sheet, the
JSON block in index.html that the scenes read as well. This reads it out of
that file, so moving a cue there moves the picture and its sound together.

The music is in A minor, at the cue sheet's tempo, with one chord to a bar. It
is made in the manner of Kraftwerk in the middle of the eighties, after "Der
Telefonanruf": dry electronic drums, a staccato sequenced bass, a lead in pure
tones over a string machine, and telephone tones dialed as part of the music.
None of it is taken from one of their recordings.

It needs numpy and scipy, and ffmpeg for reading the MP3s and writing FLAC:

    .venv/bin/pip install numpy scipy
"""

import json
import pathlib
import re
import subprocess
import tempfile

import numpy
from scipy.io import wavfile
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import butter, fftconvolve, lfilter, resample_poly, sosfilt

HERE = pathlib.Path(__file__).parent
ASSETS = HERE / "assets"

RATE = 48000

#: Any fixed number. Noise only has to be the same noise on every run, so the
#: stems come out the same and a change to them is a change somebody made.
SEED = 1993

#: How loud the two stems are together, as integrated loudness in LUFS, and
#: the highest true peak they may reach, in dBTP. The film's AAC encode
#: overshoots this by up to two and a half decibels on the drums'
#: transients, and HyperFrames lowers the whole track once the encoded peak
#: passes -1 dBTP, so the ceiling sits low enough that it never has to.
LOUDNESS_TARGET = -14.0
PEAK_CEILING = -4.0

#: What a television of the PAL era hums and whines at: the mains, and the
#: line transformer running at 625 lines 25 times a second.
MAINS = 50
LINE_FREQUENCY = 625 * 25

#: The chords, by name, as the notes of a pad voicing and the root the bass
#: plays. MIDI note numbers, so 57 is the A below middle C.
CHORDS = {
    "Am": {"pad": [57, 60, 64, 71], "root": 45},
    "F": {"pad": [53, 57, 60, 64], "root": 41},
    "C": {"pad": [55, 60, 64, 67], "root": 36},
    "G": {"pad": [55, 59, 62, 67], "root": 43},
}

#: One chord per bar, for the sixteen bars of the film: the opening, the
#: merge, the two grooves either side of the stabs, the build and the end.
PROGRESSION = ["Am", "F", "Am", "G", "Am", "F", "C", "G", "Am", "Am", "F", "C", "G", "Am", "Am", "Am"]

#: The lead's harmonics and their levels against the first: the second nearly
#: as strong, the rest well below, in the proportions measured on the lead of
#: "Der Telefonanruf".
LEAD_HARMONICS = {1: 1.0, 2: 0.65, 3: 0.18, 4: 0.27, 5: 0.19, 6: 0.19}

#: The figure the lead opens the film on and closes it with, as beats into a
#: bar and MIDI notes, one figure for each of the first two chords.
LEAD_FIGURES = {
    "Am": [(0, 76), (0.5, 81), (1, 83), (1.5, 84), (2.5, 83), (3, 79)],
    "F": [(0, 81), (0.5, 84), (1, 88), (2.5, 86), (3, 84), (3.5, 81)],
}

#: The grooves, as two bars that take turns, in sixteenths of a bar. They are
#: the backbeat of eighties pop: the kick on beats one and three, the snare on
#: two and four, and in the second bar a kick on the half beat after three
#: that pushes into the next bar. That keeps the beat plain to hear without
#: the kick on every beat that, with a hi-hat on every off-beat, is disco.
SIXTEENTHS = 16
GROOVE = (
    {"kicks": (0, 8), "snares": (4, 12)},
    {"kicks": (0, 8, 10), "snares": (4, 12)},
)

#: How loud the hi-hat is on the sixteenths of a beat: quiet, in the
#: background, a little more on the beat than between, rather than the
#: accented off-beat of disco.
HAT_ACCENTS = (0.22, 0.12, 0.17, 0.12)

#: How loud the kick and the snare are in the grooves and the build, so the
#: beat stands out of the strings, the lead and the arpeggio.
KICK_GAIN = 1.15
SNARE_GAIN = 1.05

#: The sixteenths of a bar the lead plays its short notes on over the first
#: groove, a dotted eighth apart.
LEAD_STEPS = (0, 3, 6)

#: The bass sequence of a bar, in eighths, as semitones over the chord's root:
#: the root, with the fifth and the minor seventh for its turns. Staccato and
#: machine-tight, and never an octave up, which is what makes a bass disco.
BASS_SEQUENCE = (0, 0, 7, 0, 0, 10, 7, 0)

#: How long a bass note sounds, as a share of its eighth, and how its accent
#: falls on the eighths of a beat: on the beat, and on the half beat between.
BASS_GATE = 0.4
BASS_ACCENTS = (1.0, 0.7)

#: A telephone keypad's tones, after the DTMF standard: each key sounds the
#: frequency of its row and the frequency of its column together, in Hz.
DTMF_ROWS = {"123A": 697, "456B": 770, "789C": 852, "*0#D": 941}
DTMF_COLUMNS = {"147*": 1209, "2580": 1336, "369#": 1477, "ABCD": 1633}

#: The letters on a telephone keypad's keys, so a word can be dialed.
KEYPAD_LETTERS = {"2": "ABC", "3": "DEF", "4": "GHI", "5": "JKL", "6": "MNO", "7": "PQRS", "8": "TUV", "9": "WXYZ"}

#: What the Merge button's pixels dial as they arrive.
DIALED = "PREVIOUSLY"

#: The sixteenths of the second bar of a groove on which a quiet telephone
#: tone answers the snare, and how loud it is.
TONE_STEPS = (7, 15)
TONE_GAIN = 0.12

#: One key of the install line. Its length is how much of the key-press
#: recording it uses, in seconds: the press has died away by then, and the
#: keys are a frame apart, so none runs into the next. Its gain keeps the keys
#: clear of the music, which dips under them. Its variation is how widely pitch
#: and level spread from one key to the next, as a fraction, half of it to
#: either side.
KEY_LENGTH = 0.03
KEY_GAIN = 2.6
KEY_VARIATION = 0.15

#: Return, the whole key-press recording, a firmer stroke than the keys.
RETURN_GAIN = 3.0

generator = numpy.random.default_rng(SEED)


# --- the cue sheet -----------------------------------------------------------


def read_cues():
    """The cue sheet, read out of index.html.

    Returns:
        The JSON block with the id "cues" as a dict. Its times are seconds from
        the start of the film.

    Raises:
        SystemExit: when index.html carries no cue sheet, because every sound
            here would otherwise be placed by guess.
    """
    page = (HERE / "index.html").read_text()
    found = re.search(r'<script id="cues" type="application/json">(.*?)</script>', page, re.DOTALL)
    if not found:
        raise SystemExit("index.html has no cue sheet.")
    return json.loads(found.group(1))


# --- building blocks ---------------------------------------------------------


def samples(seconds):
    """A length or a moment in seconds as a whole number of samples."""
    return round(seconds * RATE)


def hertz(note):
    """The frequency of a MIDI note, with the A above middle C at 440 Hz."""
    return 440.0 * 2 ** ((note - 69) / 12)


def clock(seconds):
    """Sample times from zero, one per sample, for a sound this long."""
    return numpy.arange(samples(seconds)) / RATE


def ramp_in(sound, seconds=0.003):
    """Fades the first few milliseconds in, so a sound starting mid-wave does
    not click."""
    count = min(len(sound), samples(seconds))
    sound[:count] *= numpy.linspace(0, 1, count)
    return sound


def ramp_out(sound, seconds=0.01):
    """Fades the last few milliseconds out, for the same reason as ramp_in."""
    count = min(len(sound), samples(seconds))
    sound[len(sound) - count:] *= numpy.linspace(1, 0, count)
    return sound


def filtered(sound, kind, frequency, order=2):
    """A Butterworth filter over a whole sound.

    Args:
        sound: Mono samples.
        kind: "lowpass", "highpass" or "bandpass".
        frequency: The cutoff in Hz, or a pair of edges for a band.
        order: The filter's order. Each order is 6 dB per octave.
    """
    sections = butter(order, frequency, btype=kind, fs=RATE, output="sos")
    return sosfilt(sections, sound)


def noise(seconds):
    """White noise, from the seeded generator."""
    return generator.standard_normal(samples(seconds))


def swept_band(source, centers, width=0.6):
    """Noise passed through a band whose middle moves over time.

    A filter whose cutoff changes every sample needs a loop per sample, which
    is slow in Python. Here the source is filtered once into a set of fixed
    bands, and the output crossfades between the two bands either side of the
    wanted frequency at each sample, which sounds the same.

    Args:
        source: Mono samples to filter.
        centers: The middle of the band at each sample, in Hz, as long as
            source.
        width: The band's width in octaves.
    """
    edges = numpy.geomspace(80, 16000, 28)
    bands = numpy.stack([
        filtered(source, "bandpass", (middle * 2 ** (-width / 2), min(middle * 2 ** (width / 2), RATE * 0.45)))
        for middle in edges
    ])
    position = numpy.interp(numpy.log(centers), numpy.log(edges), numpy.arange(len(edges)))
    lower = numpy.floor(position).astype(int).clip(0, len(edges) - 2)
    share = position - lower
    index = numpy.arange(len(source))
    return bands[lower, index] * (1 - share) + bands[lower + 1, index] * share


def stereo(sound, pan=0.0):
    """A mono sound placed in the stereo field with an equal-power pan.

    Args:
        sound: Mono samples.
        pan: From -1, all left, to 1, all right.
    """
    angle = (pan + 1) * numpy.pi / 4
    return numpy.stack([sound * numpy.cos(angle), sound * numpy.sin(angle)])


def highpassed(sound, frequency):
    """A stereo sound with everything below a frequency taken out, at 24 dB
    per octave."""
    return numpy.stack([filtered(channel, "highpass", frequency, order=4) for channel in sound])


class Bus:
    """Somewhere sounds are laid down at their moments, with a reverb send.

    The dry signal and what is sent to the reverb are kept apart until the end,
    because the reverb is one convolution over the whole send rather than one
    per sound.
    """

    def __init__(self, length):
        """An empty bus.

        Args:
            length: The film's length in seconds. Anything laid down past it
                is cut off.
        """
        self.dry = numpy.zeros((2, samples(length)))
        self.send = numpy.zeros((2, samples(length)))

    def add(self, sound, at, gain=1.0, pan=0.0, reverb=0.0):
        """Lays a sound down.

        Args:
            sound: Mono samples, or stereo as two rows.
            at: When it starts, in seconds from the start of the film.
            gain: Its level, as a factor.
            pan: Its place in the stereo field, for a mono sound.
            reverb: How much of it goes to the reverb, as a factor.
        """
        placed = stereo(sound, pan) if sound.ndim == 1 else sound
        start = samples(at)
        end = min(start + placed.shape[1], self.dry.shape[1])
        if end <= start:
            return
        self.dry[:, start:end] += placed[:, :end - start] * gain
        if reverb:
            self.send[:, start:end] += placed[:, :end - start] * gain * reverb

    def mix(self, room):
        """The dry signal with the send run through the room."""
        wet = numpy.stack([
            fftconvolve(self.send[channel], room[channel])[:self.dry.shape[1]]
            for channel in range(2)
        ])
        return self.dry + wet


def room(seconds=1.0):
    """The reverb's impulse response: noise falling 60 dB over its length,
    darker as it falls, different in each ear so the tail is wide. A small
    room, so what is sent to it stays close and dry."""
    time = clock(seconds)
    envelope = 10 ** (-3 * time / seconds)
    channels = []
    for _ in range(2):
        tail = noise(seconds) * envelope
        dark = filtered(tail, "lowpass", 3500)
        fade = time / seconds
        channels.append(tail * (1 - fade) * 0.5 + dark * fade)
    response = numpy.stack(channels)
    response[:, :samples(0.02)] = 0
    return response / numpy.sqrt(numpy.sum(response ** 2)) * 0.6


# --- instruments -------------------------------------------------------------


def saw(frequency, seconds, cutoff, detune=0.0, phase=0.0, resonance=0.7071):
    """A sawtooth built from its harmonics, each one already filtered.

    Building it from harmonics keeps it free of aliasing, and filtering each
    harmonic by its own frequency lets the cutoff move over time without a
    filter that runs sample by sample. The filter is a two-pole lowpass; at
    the default resonance it has no peak, and above it the harmonics near the
    cutoff stand out, as on an analog synthesizer.

    Args:
        frequency: The pitch in Hz.
        seconds: Its length.
        cutoff: The lowpass cutoff in Hz, as one number or one per sample.
        detune: A shift in cents, for the width of several voices together.
        phase: Where each harmonic starts, as a fraction of a cycle.
        resonance: The filter's Q.
    """
    pitch = frequency * 2 ** (detune / 1200)
    time = clock(seconds)
    cutoff = numpy.broadcast_to(numpy.asarray(cutoff, dtype=float), time.shape)
    highest = int(min(RATE * 0.45, cutoff.max() * 4) // pitch)
    sound = numpy.zeros_like(time)
    for harmonic in range(1, max(highest, 1) + 1):
        ratio = harmonic * pitch / cutoff
        response = 1 / numpy.sqrt((1 - ratio ** 2) ** 2 + (ratio / resonance) ** 2)
        sound += response / harmonic * numpy.sin(2 * numpy.pi * (harmonic * pitch * time + phase * harmonic))
    return sound * 0.6


def square(frequency, seconds, cutoff):
    """A square wave from its odd harmonics, filtered as saw is."""
    time = clock(seconds)
    highest = int(min(RATE * 0.45, cutoff * 4) // frequency)
    sound = numpy.zeros_like(time)
    for harmonic in range(1, max(highest, 1) + 1, 2):
        response = 1 / numpy.sqrt(1 + (harmonic * frequency / cutoff) ** 4)
        sound += response / harmonic * numpy.sin(2 * numpy.pi * harmonic * frequency * time)
    return sound * 0.8


def lead(note, seconds=0.5):
    """The lead: six harmonics in the proportions of a sawtooth filtered soft,
    with the second nearly as strong as the first, a short attack, and a
    vibrato that sets in once the note is held.

    Args:
        note: A MIDI note.
        seconds: How long it sounds, release included.
    """
    time = clock(seconds)
    cents = 12 * numpy.clip((time - 0.15) / 0.2, 0, 1) * numpy.sin(2 * numpy.pi * 5.5 * time)
    turns = numpy.cumsum(hertz(note) * 2 ** (cents / 1200)) / RATE
    sound = sum(level * numpy.sin(2 * numpy.pi * harmonic * turns) for harmonic, level in LEAD_HARMONICS.items())
    envelope = numpy.minimum(time / 0.012, 1.0) * (0.8 + 0.2 * numpy.exp(-time / 0.1))
    return ramp_out(sound * envelope * 0.35, 0.06)


def chorus(sound, phase):
    """The ensemble of a string machine: the sound read back through a delay
    that wanders slowly between 4 and 10 ms, mixed with itself.

    Args:
        sound: Mono samples.
        phase: Where the wandering starts, so two sides can differ.
    """
    time = numpy.arange(len(sound)) / RATE
    delay = 0.007 + 0.003 * numpy.sin(2 * numpy.pi * 0.7 * time + phase)
    moved = numpy.interp(time - delay, time, sound, left=0.0)
    return (sound + moved) * 0.7


def pad(chord, seconds, cutoff, release=0.9):
    """A chord held by detuned sawtooths through a string machine's ensemble,
    in stereo, each side wandering on its own.

    Args:
        chord: A name from CHORDS.
        seconds: How long it is held before it is let go.
        cutoff: The lowpass cutoff, as one number or one per sample.
        release: How long it takes to fade once let go.
    """
    length = seconds + release
    time = clock(length)
    envelope = numpy.minimum(time / 0.3, 1.0)
    held = time > seconds
    envelope[held] *= numpy.exp(-(time[held] - seconds) / (release / 4))
    if numpy.ndim(cutoff):
        cutoff = numpy.concatenate([cutoff, numpy.full(len(time) - len(cutoff), cutoff[-1])])[:len(time)]
    sides = []
    for detunes, phase in (((-9, 0, 6), 0.0), ((-5, 3, 10), numpy.pi / 2)):
        voice = sum(
            saw(hertz(note), length, cutoff, detune, phase=generator.random())
            for note in CHORDS[chord]["pad"]
            for detune in detunes
        )
        sides.append(chorus(voice * envelope / 6, phase))
    return numpy.stack(sides)


def pluck(note, seconds, accent=1.0, gate=1.0):
    """One note of the bass: a sawtooth through a resonant filter that snaps
    shut, with a little sine under it for weight, held for a share of its
    length and then let go, as a sequencer plays it.

    Args:
        note: A MIDI note.
        seconds: Its length.
        accent: How hard it is played, which opens the filter further.
        gate: The share of its length it is held for.
    """
    time = clock(seconds)
    cutoff = 250 + 2400 * accent * numpy.exp(-time / 0.06)
    body = saw(hertz(note), seconds, cutoff, resonance=2.5)
    sub = numpy.sin(2 * numpy.pi * hertz(note) * time) * 0.12
    held = seconds * gate
    envelope = numpy.where(time < held, 1.0, numpy.exp(-(time - held) / 0.015))
    return ramp_out(ramp_in(body + sub)) * envelope * accent


def kick():
    """A short, dry electronic kick: a sine that drops from about 90 Hz to its
    low note at once and is gone within a twentieth of a second, a thud
    rather than a boom."""
    time = clock(0.16)
    pitch = 55 + 35 * numpy.exp(-time / 0.012)
    body = numpy.sin(2 * numpy.pi * numpy.cumsum(pitch) / RATE) * numpy.exp(-time / 0.02)
    click = filtered(noise(0.16), "bandpass", (1000, 4000)) * numpy.exp(-time / 0.002) * 0.15
    return ramp_out(numpy.tanh((body + click) * 1.3))


def snare():
    """An electronic snare: a burst of noise in the middle of the spectrum
    over a short tone, dry and over within a thirtieth of a second."""
    time = clock(0.14)
    tone = numpy.sin(2 * numpy.pi * 180 * time) * numpy.exp(-time / 0.02) * 0.6
    burst = filtered(noise(0.14), "bandpass", (1200, 8000)) * numpy.exp(-time / 0.013) * 1.3
    return ramp_out(ramp_in(tone + burst))


def dtmf(key, seconds=0.07):
    """A key of a telephone keypad: the frequency of its row and the
    frequency of its column, sounding together.

    Args:
        key: One of the keys in DTMF_ROWS and DTMF_COLUMNS, such as "7".
        seconds: How long the key is held.
    """
    time = clock(seconds)
    low = next(frequency for keys, frequency in DTMF_ROWS.items() if key in keys)
    high = next(frequency for keys, frequency in DTMF_COLUMNS.items() if key in keys)
    tone = numpy.sin(2 * numpy.pi * low * time) + 0.8 * numpy.sin(2 * numpy.pi * high * time)
    return ramp_out(ramp_in(tone * 0.5, 0.004), 0.006)


def dialed(word):
    """The keys a word is dialed on, letter by letter."""
    return [next(key for key, letters in KEYPAD_LETTERS.items() if letter in letters) for letter in word.upper()]


def hat():
    """A closed electronic hi-hat: a tick of noise between 3.5 and 12 kHz."""
    seconds = 0.05
    time = clock(seconds)
    sound = filtered(noise(seconds), "bandpass", (3500, 12000)) * numpy.exp(-time / 0.008)
    return ramp_in(sound) * 0.7


def crash():
    """A short electronic cymbal: bright noise falling away within a second."""
    time = clock(1.0)
    return ramp_out(ramp_in(filtered(noise(1.0), "bandpass", (3000, 10000)) * numpy.exp(-time / 0.3))) * 0.35


def impact():
    """The hit on the merge and on the end card: a sub falling under a burst
    of noise."""
    time = clock(2.2)
    pitch = 38 + 60 * numpy.exp(-time / 0.25)
    sub = numpy.sin(2 * numpy.pi * numpy.cumsum(pitch) / RATE) * numpy.exp(-time / 0.55)
    burst = filtered(noise(2.2), "lowpass", 3000) * numpy.exp(-time / 0.2) * 0.6
    return ramp_in(numpy.tanh((sub + burst) * 1.4))


def riser(seconds):
    """A rising wash of noise and a rising tone, peaking at its end."""
    time = clock(seconds)
    progress = time / seconds
    wash = swept_band(noise(seconds), 250 * (40 ** progress), width=1.0)
    tone = numpy.sin(2 * numpy.pi * numpy.cumsum(220 * 8 ** progress) / RATE) * 0.15
    return ramp_out((wash + tone) * progress ** 2.2, 0.02)


# --- effects -----------------------------------------------------------------


def power_on():
    """A CRT coming on: the relay's thunk, the tube's charge rising, and the
    whine of its line transformer fading under the picture."""
    time = clock(1.4)
    thunk = filtered(noise(1.4), "lowpass", 300) * numpy.exp(-time / 0.03) * 1.2
    thunk += numpy.sin(2 * numpy.pi * 72 * time) * numpy.exp(-time / 0.09) * 0.8
    charge = swept_band(noise(1.4), 300 * 20 ** numpy.minimum(time / 0.35, 1), width=0.5) * numpy.exp(-time / 0.25) * 0.8
    whine = numpy.sin(2 * numpy.pi * LINE_FREQUENCY * time) * numpy.exp(-time / 0.5) * 0.04
    hum = sum(numpy.sin(2 * numpy.pi * MAINS * partial * time) / partial for partial in (1, 2, 3, 5)) * numpy.exp(-time / 0.4) * 0.12
    return ramp_out(ramp_in(thunk + charge + whine + hum))


def power_off():
    """A CRT going off: a falling zap as the picture folds, then a soft tick."""
    time = clock(0.6)
    pitch = 2600 * numpy.exp(-time / 0.07) + 60
    zap = numpy.sin(2 * numpy.pi * numpy.cumsum(pitch) / RATE) * numpy.exp(-time / 0.18) * 0.5
    fizz = filtered(noise(0.6), "highpass", 3000) * numpy.exp(-time / 0.05) * 0.3
    return ramp_out(ramp_in(zap + fizz))


def tick(note, seconds=0.09):
    """A line of the installer arriving: a soft sine with a click on it."""
    time = clock(seconds)
    tone = numpy.sin(2 * numpy.pi * hertz(note) * time) * numpy.exp(-time / 0.03)
    click = filtered(noise(seconds), "highpass", 4000) * numpy.exp(-time / 0.002) * 0.3
    return ramp_out(ramp_in(tone + click))


def flap():
    """A system name rolling into place: the clack of a split-flap display."""
    time = clock(0.08)
    clack = filtered(noise(0.08), "bandpass", (1500, 6000)) * numpy.exp(-time / 0.008)
    knock = numpy.sin(2 * numpy.pi * 420 * time) * numpy.exp(-time / 0.015) * 0.5
    return ramp_in(clack + knock)


def scratch():
    """The pen striking the word out: noise drawn quickly downwards."""
    seconds = 0.22
    time = clock(seconds)
    sound = swept_band(noise(seconds), 6000 * 0.08 ** (time / seconds), width=0.8)
    return ramp_out(ramp_in(sound * numpy.sin(numpy.pi * time / seconds)), 0.02)


def swish(seconds=0.35):
    """Air moving, as a caption slides in or a window opens."""
    time = clock(seconds)
    shape = numpy.sin(numpy.pi * time / seconds) ** 2
    return swept_band(noise(seconds), 900 * 4 ** (time / seconds), width=1.2) * shape


def recording(name):
    """One of the recorded effects in assets/sfx, as mono samples at RATE,
    starting at its first audible sample.

    Starting at the onset rather than at the file's first sample is what lets
    a click land exactly on the frame it belongs to.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav") as decoded:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(ASSETS / "sfx" / f"{name}.mp3"),
             "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_f32le", decoded.name],
            check=True)
        _, sound = wavfile.read(decoded.name)
    level = numpy.abs(sound)
    onset = int(numpy.argmax(level > level.max() * 0.05))
    return sound[onset:].astype(float)


def loudest_moment(sound):
    """Where a sound is loudest, in seconds, measured over 10 ms windows."""
    window = samples(0.01)
    energy = numpy.convolve(sound ** 2, numpy.ones(window), "same")
    return int(numpy.argmax(energy)) / RATE


# --- the score ---------------------------------------------------------------


def drum_grooves(scenes):
    """Where the drums play a groove: under the headline and the install
    line, and under the admin."""
    return ((scenes["headline"], scenes["nothing"]), (scenes["admin"], scenes["systems"]))


def bars(start, end, bar):
    """Every bar between two moments, with the bar of GROOVE it plays.

    Yields:
        The bar's index from the start, its start in seconds, and its
        entry in GROOVE.
    """
    for index, moment in enumerate(numpy.arange(start, end - 1e-6, bar)):
        yield index, moment, GROOVE[index % len(GROOVE)]


def groove_hits(cues, kind):
    """Every moment one drum plays in the grooves.

    Args:
        cues: The cue sheet.
        kind: "kicks" or "snares", as GROOVE names them.
    """
    bar = 4 * 60 / cues["bpm"]
    sixteenth = bar / SIXTEENTHS
    return [moment + step * sixteenth
            for start, end in drum_grooves(cues["scenes"])
            for _, moment, pattern in bars(start, end, bar)
            for step in pattern[kind]]


def merge_kicks(cues):
    """The kicks through the merge, in half time, on the way into the first
    groove."""
    beat = 60 / cues["bpm"]
    return [cues["press"] + offset * beat for offset in (0, 2, 4, 5.5, 6)]


def build_kicks(cues):
    """A kick on every beat of the build into the end card."""
    beat = 60 / cues["bpm"]
    return list(numpy.arange(cues["scenes"]["systems"], cues["finale"] - 1e-6, beat))


def kick_times(cues):
    """Every moment the kick plays, which the pad and the bass duck under."""
    times = merge_kicks(cues) + groove_hits(cues, "kicks") + build_kicks(cues)
    times += list(cues["stabs"]) + [cues["finale"]]
    return sorted(times)


def ducking(cues, length):
    """How far the pad and the bass dip under each kick, as a gain per sample.

    Only a little: the sustained parts make room for the kick without the
    pumping of synthwave, which a machine-tight mix does not have.
    """
    gain = numpy.ones(samples(length))
    shape_time = clock(0.25)
    shape = 1 - 0.15 * numpy.minimum(shape_time / 0.004, 1) * numpy.exp(-shape_time / 0.06)
    for at in kick_times(cues):
        start = samples(at)
        end = min(start + len(shape), len(gain))
        gain[start:end] = numpy.minimum(gain[start:end], shape[:end - start])
    return gain


def dip(length, start, end, level, ramp=0.08):
    """A gain per sample that falls to a level between two moments and comes
    back, with short ramps either side.

    Args:
        length: The film's length in seconds.
        start: When the dip begins, in seconds.
        end: When it is over, in seconds.
        level: The gain at the bottom of the dip, as a factor.
        ramp: How long each side takes, in seconds.
    """
    time = clock(length)
    down = numpy.clip((time - start) / ramp, 0, 1)
    up = numpy.clip((end - time) / ramp, 0, 1)
    return 1 - (1 - level) * numpy.minimum(down, up)


def write_music(cues, reverb_room):
    """The music stem.

    Returns:
        Stereo samples for the whole film.
    """
    length = cues["length"]
    beat = 60 / cues["bpm"]
    bar = 4 * beat
    sixteenth = bar / SIXTEENTHS
    eighth = 2 * sixteenth
    scenes = cues["scenes"]
    drums = Bus(length)
    tonal = Bus(length)
    pads = Bus(length)
    bass = Bus(length)

    def chord_at(moment):
        return PROGRESSION[min(int(moment // bar), len(PROGRESSION) - 1)]

    # The strings, in every bar up to the end card but the stabs' one, dark
    # and quiet at the start and opening up as the film does. The end card
    # holds one chord until the set goes off.
    for index, chord in enumerate(PROGRESSION):
        start = index * bar
        if scenes["nothing"] <= start < scenes["admin"] or start >= cues["finale"]:
            continue
        gain = 0.5
        if start < cues["press"]:
            cutoff = numpy.linspace(700 + start * 250, 1200 + start * 250, samples(bar))
            gain = 0.22
        elif start < scenes["headline"]:
            cutoff = 3000
        elif start < scenes["admin"]:
            cutoff = 4200
        elif start < scenes["systems"]:
            cutoff = 5000
        else:
            cutoff = numpy.linspace(2500, 6000, samples(bar))
        pads.add(pad(chord, bar, cutoff), start, gain=gain, reverb=0.12)
    pads.add(pad(chord_at(cues["finale"]), cues["crtOff"] - cues["finale"], 4000, release=2.4), cues["finale"], gain=0.55, reverb=0.15)

    # The lead's figure over the opening, from the moment the picture is up,
    # and over the end card.
    picture_up = cues["crtOn"] + beat
    for index, chord in enumerate(("Am", "F")):
        for beat_offset, note in LEAD_FIGURES[chord]:
            at = picture_up + index * bar + beat_offset * beat
            tonal.add(lead(note, 0.45), at, gain=0.3, pan=-0.2 + 0.1 * (note % 3), reverb=0.1)
    for beat_offset, note in LEAD_FIGURES["Am"] + [(4.5, 81)]:
        tonal.add(lead(note, 0.9), cues["finale"] + beat + beat_offset * beat, gain=0.38, pan=0.15, reverb=0.12)

    # Short lead notes over the first groove, a dotted eighth apart, from the
    # chord.
    for index, moment, _ in bars(scenes["headline"], scenes["nothing"], bar):
        tones = CHORDS[chord_at(moment)]["pad"]
        for place, step in enumerate(LEAD_STEPS):
            note = tones[(index + place) % len(tones)] + 12
            tonal.add(lead(note, 0.18), moment + step * sixteenth, gain=0.24, pan=0.5 if place % 2 else -0.5, reverb=0.08)

    # The arpeggio over the admin, in sixteenths up and down the chord.
    pattern = [0, 1, 2, 3, 4, 3, 2, 1]
    for step, moment in enumerate(numpy.arange(scenes["admin"], scenes["systems"] - 1e-6, beat / 4)):
        tones = CHORDS[chord_at(moment)]["pad"]
        ladder = tones + [tones[0] + 12]
        note = ladder[pattern[step % len(pattern)]] + 12
        sound = square(hertz(note), 0.12, 5000) * numpy.exp(-clock(0.12) / 0.05)
        tonal.add(ramp_out(ramp_in(sound)), moment, gain=0.13, pan=0.45 * numpy.sin(step * 0.4), reverb=0.08)

    # The bass: long notes through the merge, the sequence in staccato eighths
    # in the grooves and the build, and one held note under the end card.
    for moment in (cues["press"], cues["press"] + bar):
        bass.add(pluck(CHORDS[chord_at(moment)]["root"], bar, 0.6), moment, gain=0.4)
    for start, end in ((scenes["headline"], scenes["nothing"]), (scenes["admin"], cues["finale"])):
        for step, moment in enumerate(numpy.arange(start, end - 1e-6, eighth)):
            note = CHORDS[chord_at(moment)]["root"] + BASS_SEQUENCE[step % len(BASS_SEQUENCE)]
            accent = BASS_ACCENTS[step % len(BASS_ACCENTS)]
            bass.add(pluck(note, eighth, accent, gate=BASS_GATE), moment, gain=0.34)
    bass.add(pluck(CHORDS[chord_at(cues["finale"])]["root"], cues["crtOff"] - cues["finale"], 0.8), cues["finale"], gain=0.4)

    # The drums. Half time through the merge, a roll into the first groove,
    # the backbeat in both grooves, and a roll that speeds up into the end
    # card. All of them dry.
    merge = cues["press"]
    for at in merge_kicks(cues):
        drums.add(kick(), at, gain=0.9)
    for at in (merge + 2 * beat, merge + 6 * beat):
        drums.add(snare(), at, gain=0.8, reverb=0.05)
    for step in range(8):
        drums.add(snare(), scenes["headline"] - beat + step * beat / 8, gain=0.2 + 0.08 * step, reverb=0.05)
    for moment in numpy.arange(merge + 4 * beat, scenes["headline"] - 1e-6, beat / 2):
        drums.add(hat(), moment, gain=0.45, pan=0.3)

    for at in groove_hits(cues, "kicks"):
        drums.add(kick(), at, gain=KICK_GAIN)
    for at in groove_hits(cues, "snares"):
        drums.add(snare(), at, gain=SNARE_GAIN, reverb=0.05)
    for start, end in drum_grooves(scenes):
        for step, moment in enumerate(numpy.arange(start, end - 1e-6, sixteenth)):
            drums.add(hat(), moment, gain=HAT_ACCENTS[step % len(HAT_ACCENTS)], pan=0.3)

    # Telephone tones answering the snare in every second bar of the
    # grooves, dialing the film's word one key at a time.
    keys = dialed(DIALED)
    placed = 0
    for start, end in drum_grooves(scenes):
        for index, moment, _ in bars(start, end, bar):
            if index % 2 == 0:
                continue
            for step in TONE_STEPS:
                tonal.add(dtmf(keys[placed % len(keys)], 0.06), moment + step * sixteenth, gain=TONE_GAIN, pan=-0.45 if placed % 2 else 0.45)
                placed += 1

    for index, at in enumerate(cues["stabs"]):
        chord = ("Am", "F", "G")[index]
        stab = pad(chord, 0.18, 6000, release=0.5)
        tonal.add(stab, at, gain=0.8, reverb=0.2)
        drums.add(kick(), at, gain=1.0)
        drums.add(snare(), at, gain=0.8, reverb=0.1)
    for step in range(4):
        drums.add(snare(), scenes["admin"] - beat / 2 + step * beat / 8, gain=0.3 + 0.12 * step, reverb=0.05)

    systems = scenes["systems"]
    for at in build_kicks(cues):
        drums.add(kick(), at, gain=KICK_GAIN)
    roll = [systems + step * beat / 2 for step in range(4)]
    roll += [systems + 2 * beat + step * beat / 4 for step in range(4)]
    roll += [systems + 3 * beat + step * beat / 8 for step in range(8)]
    for index, at in enumerate(roll):
        drums.add(snare(), at, gain=0.25 + 0.55 * index / len(roll), reverb=0.05)
    tonal.add(riser(cues["finale"] - systems), systems, gain=0.4, reverb=0.1)

    # The two hits: the merge, with a riser into it, and the end card.
    tonal.add(riser(cues["press"] - cues["whooshes"][0]), cues["whooshes"][0], gain=0.35, reverb=0.1)
    for at in (cues["press"], cues["finale"]):
        drums.add(impact(), at, gain=0.7, reverb=0.2)
        drums.add(crash(), at, gain=0.6, reverb=0.1)

    # The strings keep out of the bass's way, and nothing goes below what a
    # speaker can play.
    pumped = (highpassed(pads.mix(reverb_room), 160) + highpassed(bass.mix(reverb_room), 35)) * ducking(cues, length)
    music = highpassed(drums.mix(reverb_room) + tonal.mix(reverb_room) + pumped, 28)

    # The music steps back while the line is typed, so the keys are heard.
    music *= dip(length, cues["keys"][0] - 0.1, cues["enter"] + 0.15, 0.5)

    # The set goes off with the picture: the music stops as the picture folds
    # to a line, and only the tube's own sound is left.
    cut = samples(cues["crtOff"] + 0.17)
    fade = samples(0.05)
    music[:, cut:cut + fade] *= numpy.linspace(1, 0, fade)
    music[:, cut + fade:] = 0
    return music


def write_effects(cues, reverb_room):
    """The effects stem: everything that belongs to one thing on the screen
    rather than to the music.

    Returns:
        Stereo samples for the whole film.
    """
    bus = Bus(cues["length"])

    bus.add(power_on(), cues["crtOn"], gain=1.0)

    # The Merge button's pixels arrive as the film's word is dialed, one key
    # after another, at the pace of a telephone dialing a stored number.
    build_start, build_end = cues["build"]
    keys = dialed(DIALED)
    for index, at in enumerate(numpy.linspace(build_start, build_end, len(keys), endpoint=False)):
        bus.add(dtmf(keys[index]), at, gain=0.3, pan=-0.3 + 0.6 * index / len(keys), reverb=0.05)

    # Each logo lands at the loudest moment of its whoosh, a little after the
    # move begins, because the move eases out and covers most of its way at
    # once.
    whoosh = recording("whoosh-short")
    for at, pan in zip(cues["whooshes"], (-0.5, 0.5), strict=True):
        bus.add(whoosh, at + 0.08 - loudest_moment(whoosh), gain=1.4, pan=pan)

    bus.add(recording("click"), cues["press"], gain=1.8)

    # The two logos drawn into each other, ending on the flash.
    pull = cues["meet"] - cues["press"]
    pull_time = clock(pull)
    drawn_in = swept_band(noise(pull), 400 * 20 ** (pull_time / pull), width=0.8) * (pull_time / pull) ** 2
    bus.add(drawn_in, cues["press"], gain=0.9, reverb=0.15)
    for note in (81, 88, 93):
        bus.add(lead(note, 1.4), cues["meet"], gain=0.26, reverb=0.2)

    bus.add(scratch(), cues["strike"], gain=1.0)

    # One key on each character's time in the cue sheet, which is the frame
    # that character appears on. Each one strays a little in pitch and level,
    # so a run of them sounds like a hand rather than one sample repeated.
    key_press = recording("key-press")
    key = ramp_out(key_press[:samples(KEY_LENGTH)].copy())
    for at in cues["keys"]:
        speed = 1 + KEY_VARIATION * (generator.random() - 0.5)
        varied = numpy.interp(numpy.arange(0, len(key) - 1, speed), numpy.arange(len(key)), key)
        level = KEY_GAIN * (1 + KEY_VARIATION * (generator.random() - 0.5))
        bus.add(varied, at, gain=level, pan=0.3 * (generator.random() - 0.5))
    bus.add(key_press, cues["enter"], gain=RETURN_GAIN)
    bus.add(tick(84), cues["banner"], gain=0.5)
    for index, at in enumerate(cues["steps"]):
        bus.add(tick(88 + (index % 2) * 3), at, gain=0.6, pan=0.2)
    bus.add(tick(93, 0.2), cues["done"], gain=0.7, reverb=0.3)

    for at in cues["captions"]:
        bus.add(swish(), at - 0.15, gain=0.5, pan=-0.4)
    for index, at in enumerate(cues["windows"]):
        bus.add(swish(0.25), at, gain=0.3, pan=0.35 if index % 2 else -0.15)

    for index, at in enumerate(cues["systems"]):
        bus.add(flap(), at, gain=1.0, pan=0.1 * (index % 3 - 1))
    pop = recording("pop")
    for index, at in enumerate(cues["facts"]):
        bus.add(pop, at, gain=0.9, pan=-0.4 + 0.4 * index)

    bus.add(power_off(), cues["crtOff"] + 0.17, gain=1.0)
    return bus.mix(reverb_room)


# --- loudness ----------------------------------------------------------------


def integrated_loudness(sound):
    """Integrated loudness in LUFS, after ITU-R BS.1770: K-weighting, 400 ms
    blocks overlapping by three quarters, and both gates.

    The filter coefficients are the standard's own for 48 kHz.
    """
    shelf = ([1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585])
    high = ([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])
    weighted = lfilter(*high, lfilter(*shelf, sound, axis=1), axis=1)
    block, hop = samples(0.4), samples(0.1)
    powers = numpy.array([
        numpy.sum(numpy.mean(weighted[:, start:start + block] ** 2, axis=1))
        for start in range(0, weighted.shape[1] - block + 1, hop)
    ])
    loudness = -0.691 + 10 * numpy.log10(powers + 1e-12)
    kept = powers[loudness > -70]
    relative = -0.691 + 10 * numpy.log10(kept.mean()) - 10
    kept = powers[(loudness > -70) & (loudness > relative)]
    return -0.691 + 10 * numpy.log10(kept.mean())


def limiter_gain(sound, ceiling):
    """The gain, per sample, that holds a sound's true peaks under the ceiling.

    The peaks are read off the signal oversampled four times, because the
    waveform a player reconstructs swings past the samples between them, and
    that overshoot is what clips after encoding. The gain each peak needs is
    held across a window either side of it and then smoothed over the same
    window, so it is already down when the peak arrives and comes back up
    without a step.
    """
    oversampled = numpy.abs(resample_poly(sound, 4, 1, axis=1)).max(axis=0)
    peak = oversampled[:sound.shape[1] * 4].reshape(-1, 4).max(axis=1)
    needed = numpy.minimum(1.0, ceiling / numpy.maximum(peak, 1e-9))
    window = samples(0.005)
    held = minimum_filter1d(needed, size=window * 2 + 1)
    return numpy.minimum(uniform_filter1d(held, size=window * 2 + 1), needed)


def true_peak(sound):
    """The highest peak once the signal is reconstructed between samples, in
    dBFS, from four times oversampling."""
    return 20 * numpy.log10(numpy.abs(resample_poly(sound, 4, 1, axis=1)).max())


def write_flac(sound, name):
    """Writes a stem as 16 bit FLAC into assets/, dithered on the way down.

    Sixteen bits are more than the film's AAC track carries, and they keep the
    two stems at a size a repository can hold.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav") as raw:
        wavfile.write(raw.name, RATE, sound.T.astype(numpy.float32))
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", raw.name, "-af", "aresample=dither_method=triangular",
             "-c:a", "flac", "-sample_fmt", "s16", "-compression_level", "12", str(ASSETS / name)],
            check=True)


def main():
    cues = read_cues()
    reverb_room = room()
    music = write_music(cues, reverb_room)
    effects = write_effects(cues, reverb_room)

    # Both stems get the same gain, worked out on the two together, because
    # the film plays them together and the balance between them is the mix.
    together = music + effects
    gain = 10 ** ((LOUDNESS_TARGET - integrated_loudness(together)) / 20)
    ceiling = 10 ** (PEAK_CEILING / 20)
    limited = limiter_gain(together * gain, ceiling) * gain
    music *= limited
    effects *= limited
    together = music + effects

    write_flac(music, "music.flac")
    write_flac(effects, "effects.flac")
    print(f"music.flac and effects.flac, {cues['length']} s each. "
          f"Together {integrated_loudness(together):.1f} LUFS, true peak {true_peak(together):.1f} dBTP.")


if __name__ == "__main__":
    main()
