#!/usr/bin/env python3
"""Composes the film's sound and writes it as two stems, the music and the
effects, each exactly as long as the film.

    .venv/bin/python promo/soundtrack.py

Nothing in the music is a recording. Every instrument is synthesized here, so
the film carries no music anybody else holds a license to. The three effects
that are recordings come from assets/sfx/, and CREDITS.md there states their
license.

Every moment a sound shares with a picture is taken from the cue sheet, the
JSON block in index.html that the scenes read as well. This reads it out of
that file, so moving a cue there moves the picture and its sound together.

The music is in A minor, at the cue sheet's tempo, with one chord to a bar. It
is electro in the manner of Kraftwerk: a syncopated electronic beat with claps
and claves, a sequencer running through the chords with an echo, a staccato
bass riff, and a lead like brass. Its melody, riff and rhythm are its own,
and none of it is taken from one of their recordings. Its timbres are
modeled on measurements of their album Electric Cafe: synthesizers rich in
upper harmonics, short and crisp drums, and a wide stereo field.

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

#: The chords, by name, as the notes the sequencer runs through and the root
#: the bass plays. MIDI note numbers, so 57 is the A below middle C.
CHORDS = {
    "Am": {"tones": [57, 60, 64], "root": 45},
    "F": {"tones": [53, 57, 60], "root": 41},
    "G": {"tones": [55, 59, 62], "root": 43},
    "E": {"tones": [56, 59, 64], "root": 40},
}

#: One chord per bar, for the sixteen bars of the film: the opening, the
#: merge, the first groove, the stabs, the second groove with the build, and
#: the end. Each groove closes on E, the dominant, so the next part lands.
PROGRESSION = ["Am", "Am", "F", "G", "Am", "Am", "F", "E", "Am", "Am", "Am", "F", "E", "Am", "Am", "Am"]

#: The chords of the three stabs, one each.
STAB_CHORDS = ("Am", "F", "E")

#: The grooves, as two bars that take turns, in sixteenths of a bar: an
#: electro beat, with the kick syncopated against claps on two and four and
#: quiet claves between them.
SIXTEENTHS = 16
GROOVE = (
    {"kicks": (0, 6, 10), "claps": (4, 12), "claves": (3, 7, 13)},
    {"kicks": (0, 3, 8, 11), "claps": (4, 12), "claves": (3, 11)},
)

#: How loud the hi-hat is on the sixteenths of a beat: the beat itself, the
#: sixteenth after it, the half beat and the last. Loud enough to come through
#: the riff and the bleeps.
HAT_ACCENTS = (0.44, 0.24, 0.34, 0.24)

#: The metal in the hi-hat: six square waves at frequencies that share no
#: harmonics, in Hz.
HAT_PARTIALS = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)

#: The bass riff of a bar: the sixteenth a note starts on, how many semitones
#: it lies over the chord's root, and how many sixteenths it lasts. The notes
#: on the sixteenths in RIFF_STRONG are played harder.
RIFF = ((0, 0, 2), (3, 0, 1), (6, 7, 2), (8, 0, 1), (10, 10, 2), (13, 7, 1), (14, 0, 2))
RIFF_STRONG = (0, 6, 10)

#: Which tone of the chord the sequencer plays on each sixteenth of a beat,
#: an octave and more above the chord.
BLEEP_ORDER = (0, 2, 1, 2)

#: The zapping toms that close a phrase: the sixteenth each falls on and the
#: frequency its sweep starts from.
ZAP_FILL = ((12, 3000), (14, 2000), (15, 1300))

#: The lead's phrases, as the bar from the start of the phrase, the beat in
#: that bar, how many beats a note lasts, and the note. The theme runs over
#: Am, Am, F and E and comes back through the whole piece; its last note is
#: the A it resolves to. The call is played over F and G during the merge.
LEAD_THEME = (
    (0, 0, 1.5, "E5"), (0, 1.5, 0.5, "E5"), (0, 2, 0.5, "D5"), (0, 2.5, 0.5, "C5"), (0, 3, 1, "D5"),
    (1, 0, 2, "E5"), (1, 2, 1, "G5"), (1, 3, 1, "E5"),
    (2, 0, 1.5, "F5"), (2, 1.5, 0.5, "E5"), (2, 2, 1, "D5"), (2, 3, 1, "C5"),
    (3, 0, 2, "B4"), (3, 2, 1, "G#4"), (3, 3, 1, "B4"),
)
LEAD_RESOLUTION = ((0, 0, 4, "A4"),)
LEAD_CALL = (
    (0, 0, 1, "A4"), (0, 1, 1, "C5"), (0, 2, 2, "F5"),
    (1, 0, 1, "D5"), (1, 1, 1, "B4"), (1, 2, 2, "G4"),
)

#: The theme's notes the lead plays on the three stabs, one each.
LEAD_STABS = ("E5", "C5", "B4")

#: The two bars of the theme's opening, which open the film and return over
#: the end card.
THEME_OPENING = tuple(event for event in LEAD_THEME if event[0] < 2)

#: How long after the end card arrives the music starts to fade, in seconds.
#: It is gone when the set switches off.
FADE_AFTER_FINALE = 1.0

#: The names of the notes in an octave, for writing a melody as "G#4".
NOTE_NAMES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}

#: A telephone keypad's tones, after the DTMF standard: each key sounds the
#: frequency of its row and the frequency of its column together, in Hz.
DTMF_ROWS = {"123A": 697, "456B": 770, "789C": 852, "*0#D": 941}
DTMF_COLUMNS = {"147*": 1209, "2580": 1336, "369#": 1477, "ABCD": 1633}

#: The letters on a telephone keypad's keys, so a word can be dialed.
KEYPAD_LETTERS = {"2": "ABC", "3": "DEF", "4": "GHI", "5": "JKL", "6": "MNO", "7": "PQRS", "8": "TUV", "9": "WXYZ"}

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

#: How heavy each kind of quarter turn sounds as the cube locks: a stab
#: slams, a system flicks past, and every other turn sits between them. The
#: lock as the mark, on the merge and on the end card, is the heaviest.
TURN_WEIGHTS = {"stab": 1.3, "turn": 1.0, "system": 0.6}
LOCK_WEIGHT = 1.6

#: How loud a clack is, and how loud the air of a turn, at a weight of one.
CLACK_GAIN = 0.9
TURN_AIR_GAIN = 0.25

#: About how many faces swing past while the cube spins up to the end card,
#: which sets how often the whir flutters.
SPIN_FACES = 6.5

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


def echo(sound, delay, feedback, wet, repeats=6):
    """A ping-pong echo over a stereo sound: each repeat on the other side,
    quieter by the feedback each time.

    Args:
        sound: Stereo samples, as two rows.
        delay: The time between repeats, in seconds.
        feedback: How much of each repeat comes back in the next, as a factor.
        wet: How loud the first repeat is against the sound, as a factor.
        repeats: How many repeats there are.
    """
    out = sound.copy()
    shift = samples(delay)
    left, right = sound[0], sound[1]
    level = wet
    for _ in range(repeats):
        left, right = numpy.concatenate([numpy.zeros(shift), right[:-shift]]), numpy.concatenate([numpy.zeros(shift), left[:-shift]])
        out[0] += left * level
        out[1] += right * level
        level *= feedback
    return out


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


def midi(name):
    """A note written as "G#4" as its MIDI number, with C4 at 60."""
    return NOTE_NAMES[name[:-1]] + 12 * (int(name[-1]) + 1)


def sawtooth(note, seconds, cutoff, resonance=0.7071, glide_from=None, glide=0.04, vibrato=0.0, detune=0.0):
    """A sawtooth built from its harmonics, each one already filtered.

    Building it from harmonics keeps it free of aliasing, and filtering each
    harmonic by its own frequency lets the cutoff move over time without a
    filter that runs sample by sample. The filter is a two-pole lowpass: at
    the default resonance it has no peak, and above it the harmonics near the
    cutoff stand out, as on an analog synthesizer. Harmonics past six times
    the cutoff are left out, because the filter has taken them down by more
    than 30 dB.

    Args:
        note: A MIDI note, which may lie between two semitones.
        seconds: Its length.
        cutoff: The lowpass cutoff in Hz, as one number or one per sample.
        resonance: The filter's Q.
        glide_from: A MIDI note the pitch slides up or down from, or None.
        glide: How long the slide takes, in seconds.
        vibrato: How far the pitch swings in cents once the note is held.
        detune: How far the whole sawtooth lies off the note, in cents.
    """
    time = clock(seconds)
    shift = 2 ** (detune / 1200)
    target = hertz(note) * shift
    frequency = numpy.full(len(time), target)
    if glide_from is not None:
        start = hertz(glide_from) * shift
        frequency = start * (target / start) ** numpy.clip(time / glide, 0, 1)
    if vibrato:
        cents = vibrato * numpy.clip((time - 0.2) / 0.3, 0, 1) * numpy.sin(2 * numpy.pi * 5.2 * time)
        frequency = frequency * 2 ** (cents / 1200)
    turns = numpy.cumsum(frequency) / RATE
    cutoff = numpy.broadcast_to(numpy.asarray(cutoff, dtype=float), time.shape)
    highest = int(min(RATE * 0.45, cutoff.max() * 6) // frequency.max())
    sound = numpy.zeros_like(time)
    for harmonic in range(1, max(highest, 1) + 1):
        ratio = harmonic * frequency / cutoff
        response = 1 / numpy.sqrt((1 - ratio ** 2) ** 2 + (ratio / resonance) ** 2)
        sound += response / harmonic * numpy.sin(2 * numpy.pi * harmonic * turns)
    return sound


def spread(voice, cents, crossfeed):
    """A voice played twice, detuned apart and leaning one to each side, so
    it sounds wide and beats slowly against itself, as two oscillators of an
    analog synthesizer do.

    Args:
        voice: Makes one voice as mono samples, given how far it lies off the
            note in cents.
        cents: How far each of the two lies off the note, one below it and
            one above.
        crossfeed: How much of each also sounds on the other side, as a
            factor.

    Returns:
        Stereo samples, as two rows.
    """
    left, right = voice(-cents), voice(cents)
    return numpy.stack([left + crossfeed * right, right + crossfeed * left])


def lead(note, seconds, glide_from=None):
    """The lead: two sawtooths a few cents apart, one to each side, like
    brass. On each note its filter swells open over the first 50 ms, to
    twelve times the note's frequency, and settles at eight times it. It
    slides in from the note before when the two touch, and long notes get a
    little vibrato.

    Args:
        note: A MIDI note.
        seconds: How long it sounds.
        glide_from: The note it slides in from, or None.

    Returns:
        Stereo samples, as two rows.
    """
    time = clock(seconds)
    swell = numpy.clip(time / 0.05, 0, 1) * (0.6 + 0.4 * numpy.exp(-numpy.maximum(time - 0.05, 0) / 0.25))
    cutoff = hertz(note) * (2 + 10 * swell)
    level = numpy.where(time < 0.008, time / 0.008, 0.75 + 0.25 * numpy.exp(-(time - 0.008) / 0.12)) * 0.99

    def voice(cents):
        sound = sawtooth(note, seconds, cutoff, resonance=1.3, glide_from=glide_from, glide=0.03, vibrato=8, detune=cents)
        return ramp_out(ramp_in(sound * level), 0.04)
    return spread(voice, 7, 0.45)


def bleep(note, accent=1.0):
    """One step of the sequencer: a sawtooth through a resonant filter that
    snaps shut.

    Args:
        note: A MIDI note.
        accent: How hard it is played, which opens the filter further.
    """
    time = clock(0.18)
    cutoff = 1500 + 8000 * accent * numpy.exp(-time / 0.06)
    return ramp_out(ramp_in(sawtooth(note, 0.18, cutoff, resonance=3.0) * numpy.exp(-time / 0.08) * 0.88))


def bass_note(note, seconds, accent=1.0, gate=0.6):
    """One note of the bass: two sawtooths a few cents apart, one to each
    side, each driven a little and through a resonant filter that snaps
    shut, over a sine in the middle for weight. It is held for a share of its
    length and then let go.

    Args:
        note: A MIDI note.
        seconds: Its length.
        accent: How hard it is played, which opens the filter further.
        gate: The share of its length it is held for.

    Returns:
        Stereo samples, as two rows.
    """
    time = clock(seconds)
    cutoff = 400 + 3200 * accent * numpy.exp(-time / 0.1)

    def voice(cents):
        sound = sawtooth(note, seconds, cutoff, resonance=4.0, detune=cents)
        return ramp_out(ramp_in(numpy.tanh(sound * 1.5) / numpy.tanh(1.5)))
    sub = ramp_out(ramp_in(numpy.sin(2 * numpy.pi * hertz(note) * time) * 0.15))
    held = seconds * gate
    level = numpy.where(time < held, 1.0, numpy.exp(-(time - held) / 0.02))
    return (spread(voice, 4, 0.5) * 0.6 + sub) * level * accent


def kick():
    """A short electronic kick: a sine falling from about 134 Hz to 54 Hz
    within about 30 ms and down 20 dB within about 70 ms, with a click on
    top, driven until it clips a little."""
    time = clock(0.3)
    pitch = 54 + 80 * numpy.exp(-time / 0.01)
    body = numpy.sin(2 * numpy.pi * numpy.cumsum(pitch) / RATE) * numpy.exp(-time / 0.03)
    click = filtered(noise(0.3), "highpass", 2000) * numpy.exp(-time / 0.002) * 0.35
    return ramp_out(ramp_in(numpy.tanh((body + click) * 1.8) * 1.39))


def clap():
    """An electronic clap and snare in one: four bursts of noise a few
    milliseconds apart, as hands that do not quite meet, with a short tail,
    and under them a burst of white noise and a low knock."""
    time = clock(0.25)
    sound = numpy.zeros_like(time)
    for offset in (0.0, 0.008, 0.016, 0.026):
        start = samples(offset)
        burst = filtered(noise(0.25 - offset), "bandpass", (1000, 7000)) * numpy.exp(-clock(0.25 - offset) / 0.006)
        sound[start:] += burst[:len(sound) - start]
    sound += filtered(noise(0.25), "bandpass", (1000, 7000)) * numpy.exp(-time / 0.05) * 0.5
    sound += filtered(noise(0.25), "highpass", 1800) * numpy.exp(-time / 0.045) * 0.6
    sound += numpy.sin(2 * numpy.pi * 190 * time) * numpy.exp(-time / 0.03) * 0.5
    return ramp_out(ramp_in(sound * 0.31))


def hat():
    """A closed electronic hi-hat: metal and noise between 4.5 and 12 kHz,
    down 20 dB within about 50 ms."""
    time = clock(0.15)
    metal = sum(numpy.sign(numpy.sin(2 * numpy.pi * frequency * time)) for frequency in HAT_PARTIALS)
    sound = filtered(metal * 0.25 + noise(0.15), "bandpass", (4500, 12000))
    return ramp_out(ramp_in(sound * numpy.exp(-time / 0.02) * 1.37))


def clave():
    """An electronic clave: two high tones driven until they are nearly
    square, stopping at once."""
    time = clock(0.06)
    tone = numpy.tanh(2.5 * (numpy.sin(2 * numpy.pi * 2400 * time) + 0.6 * numpy.sin(2 * numpy.pi * 3620 * time)))
    return ramp_out(ramp_in(tone * numpy.exp(-time / 0.012) * 0.95))


def zap(start):
    """The tom of electro: a tone driven nearly square, swept down fast from
    a high start.

    Args:
        start: The frequency the sweep starts from, in Hz.
    """
    time = clock(0.2)
    pitch = 110 + (start - 110) * numpy.exp(-time / 0.03)
    tone = numpy.tanh(3 * numpy.sin(2 * numpy.pi * numpy.cumsum(pitch) / RATE)) * numpy.exp(-time / 0.07)
    return ramp_out(ramp_in(filtered(tone, "lowpass", 7000) * 0.78))


def crash():
    """A short electronic cymbal: bright noise falling away within a second."""
    time = clock(1.0)
    return ramp_out(ramp_in(filtered(noise(1.0), "bandpass", (3000, 10000)) * numpy.exp(-time / 0.3))) * 0.35


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


def clack(weight=1.0):
    """The cube locking onto a face after a turn: the hard click of a latch
    and, under it, the knock of a heavy body coming to rest.

    Args:
        weight: How heavy the turn is, which deepens and lengthens the knock,
            as TURN_WEIGHTS states it for each kind of turn.
    """
    time = clock(0.15)
    latch = filtered(noise(0.15), "bandpass", (2000, 7000)) * numpy.exp(-time / 0.003)
    pitch = 70 + 90 * numpy.exp(-time / 0.008)
    knock = numpy.sin(2 * numpy.pi * numpy.cumsum(pitch) / RATE) * numpy.exp(-time / (0.02 + 0.02 * weight))
    return ramp_out(ramp_in(latch * 0.5 + knock * weight * 0.8))


def spin(seconds):
    """The cube spinning up to the end card: air whirring faster as each face
    swings past, rising in pitch and level until the cube stops dead.

    The cube's turn quickens with the square of the time, so the faces pass
    at that pace too, and the whir flutters once for each.

    Args:
        seconds: How long the spin lasts.
    """
    time = clock(seconds)
    progress = time / seconds
    faces_passed = SPIN_FACES * progress ** 2
    flutter = 0.5 + 0.5 * numpy.abs(numpy.sin(numpy.pi * faces_passed))
    air = swept_band(noise(seconds), 300 * 10 ** progress, width=1.0)
    return ramp_in(air * flutter * progress ** 1.5, 0.05)


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


def drum_grooves(cues):
    """Where the drums play a groove: under the headline and the install
    line, under the admin, and under the end card until the set switches
    off, where the music fades away."""
    parts = cues["parts"]
    return ((parts["headline"], parts["nothing"]), (parts["admin"], parts["systems"]), (cues["finale"], cues["crtOff"]))


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
        kind: "kicks", "claps" or "claves", as GROOVE names them.
    """
    bar = 4 * 60 / cues["bpm"]
    sixteenth = bar / SIXTEENTHS
    return [moment + step * sixteenth
            for start, end in drum_grooves(cues)
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
    return list(numpy.arange(cues["parts"]["systems"], cues["finale"] - 1e-6, beat))



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
    """The music stem: an electro piece with one theme running through it.

    The theme's opening sounds from afar as the set comes on, the merge
    brings the drums and the lead's call, the whole theme runs over the first
    groove, the stabs take a note of it each, the whole theme runs again over
    the second groove and the build, and over the end card it resolves, its
    opening returns, and the music fades away until the set switches off.

    Returns:
        Stereo samples for the whole film.
    """
    length = cues["length"]
    beat = 60 / cues["bpm"]
    bar = 4 * beat
    sixteenth = bar / SIXTEENTHS
    parts = cues["parts"]
    press, finale, off = cues["press"], cues["finale"], cues["crtOff"]
    drums = Bus(length)
    sequencer = Bus(length)
    leads = Bus(length)
    bass = Bus(length)
    hits = Bus(length)

    def chord_at(moment):
        return PROGRESSION[min(int(moment // bar), len(PROGRESSION) - 1)]

    def phrase(events, start, gain=0.32):
        """Lays a lead phrase down from a bar on, sliding between notes that
        touch."""
        previous = None
        for offset, beat_in_bar, beats, name in events:
            at = start + offset * bar + beat_in_bar * beat
            note = midi(name)
            glide_from = previous[1] if previous and abs(previous[0] - at) < 1e-6 else None
            leads.add(lead(note, beats * beat + 0.05, glide_from), at, gain=gain)
            previous = (at + beats * beat, note)

    def fill(bar_start):
        for step, start in ZAP_FILL:
            drums.add(zap(start), bar_start + step * sixteenth, gain=0.55, pan=-0.54)

    # The sequencer: sixteenths through the chord, an octave and more above
    # it. It opens up from the moment the picture is up to the merge, rests
    # for the stabs, and runs on until the set switches off.
    picture_up = cues["crtOn"] + beat
    for start, end in ((picture_up, parts["nothing"]), (parts["admin"], off)):
        for moment in numpy.arange(start, end - 1e-6, sixteenth):
            step = int(round((moment % bar) / sixteenth)) % SIXTEENTHS
            tones = CHORDS[chord_at(moment)]["tones"]
            opening = min(1.0, 0.3 + 0.7 * (moment - picture_up) / (press - picture_up))
            accent = (1.0 if step in RIFF_STRONG else 0.55) * opening
            note = tones[BLEEP_ORDER[step % len(BLEEP_ORDER)]] + 24
            sequencer.add(bleep(note, accent), moment, gain=0.09 * min(opening + 0.3, 1.0), pan=0.72 if step % 2 else -0.72)

    # The bass riff, quiet and closed from the second bar of the opening,
    # through the merge and the first groove, then from the admin on until
    # the set switches off.
    for start, end in ((bar, parts["nothing"]), (parts["admin"], off)):
        for moment in numpy.arange(start, end - 1e-6, bar):
            root = CHORDS[chord_at(moment)]["root"]
            closed = 0.45 if moment < press else 1.0
            for step, interval, steps in RIFF:
                accent = (1.0 if step in RIFF_STRONG else 0.7) * closed
                bass.add(bass_note(root + interval, steps * sixteenth, accent), moment + step * sixteenth, gain=0.5)

    # The lead and its theme, through the whole piece.
    phrase(THEME_OPENING, 0.0, gain=0.12)
    phrase(LEAD_CALL, press)
    phrase(LEAD_THEME, parts["headline"])
    for at, name in zip(cues["stabs"], LEAD_STABS, strict=True):
        leads.add(lead(midi(name), 0.45), at, gain=0.32)
    phrase(LEAD_THEME, parts["admin"])
    phrase(LEAD_RESOLUTION, finale)
    phrase(THEME_OPENING, finale + bar)

    # The drums through the merge: half time, claps on the third beat of each
    # bar, the hi-hats from the second bar, and a fill into the groove.
    for at in merge_kicks(cues):
        drums.add(kick(), at, gain=1.0)
    for at in (press + 2 * beat, press + 6 * beat):
        drums.add(clap(), at, gain=0.8, pan=0.09)
    for step, moment in enumerate(numpy.arange(press + bar, parts["headline"] - 1e-6, sixteenth)):
        drums.add(hat(), moment, gain=HAT_ACCENTS[step % len(HAT_ACCENTS)] * 0.7, pan=0.54)
    fill(parts["headline"] - bar)

    # The grooves. The two that end on a scene close on a fill; the one under
    # the end card fades instead.
    for at in groove_hits(cues, "kicks"):
        drums.add(kick(), at, gain=1.0)
    for at in groove_hits(cues, "claps"):
        drums.add(clap(), at, gain=0.8, pan=0.09)
    for at in groove_hits(cues, "claves"):
        drums.add(clave(), at, gain=0.12, pan=1.0)
    grooves = drum_grooves(cues)
    for start, end in grooves:
        for step, moment in enumerate(numpy.arange(start, end - 1e-6, sixteenth)):
            drums.add(hat(), moment, gain=HAT_ACCENTS[step % len(HAT_ACCENTS)], pan=0.54)
    for _, end in grooves[:-1]:
        fill(end - bar)

    # The stabs: the chord in the sequencer's voice, two octaves of it at
    # once, on a kick and a clap.
    for at, chord in zip(cues["stabs"], STAB_CHORDS, strict=True):
        stab = sum(bleep(tone + octave, 1.0) for tone in CHORDS[chord]["tones"] for octave in (12, 24))
        sequencer.add(stab, at, gain=0.2)
        drums.add(kick(), at, gain=1.0)
        drums.add(clap(), at, gain=0.8)

    # The build into the end card: a kick on every beat, the hi-hats, and a
    # roll of claps that speeds up and swells, over a riser.
    systems = parts["systems"]
    for at in build_kicks(cues):
        drums.add(kick(), at, gain=1.0)
    for step, moment in enumerate(numpy.arange(systems, finale - 1e-6, sixteenth)):
        drums.add(hat(), moment, gain=HAT_ACCENTS[step % len(HAT_ACCENTS)], pan=0.54)
    roll = [systems + step * beat / 2 for step in range(4)]
    roll += [systems + 2 * beat + step * beat / 4 for step in range(4)]
    roll += [systems + 3 * beat + step * beat / 8 for step in range(8)]
    for index, at in enumerate(roll):
        drums.add(clap(), at, gain=0.25 + 0.55 * index / len(roll))
    hits.add(riser(finale - systems), systems, gain=0.4, reverb=0.1)

    # The two hits: the merge, with a riser into it, and the end card.
    hits.add(riser(press - cues["whooshes"][0]), cues["whooshes"][0], gain=0.35, reverb=0.1)
    for at in (press, finale):
        hits.add(impact(), at, gain=0.7, reverb=0.2)
        hits.add(crash(), at, gain=0.6, reverb=0.1)

    # The sequencer and the lead echo a dotted eighth apart, from side to
    # side, and nothing goes below what a speaker can play.
    dotted_eighth = 3 * sixteenth
    music = (drums.mix(reverb_room) + bass.mix(reverb_room) + hits.mix(reverb_room)
             + echo(sequencer.mix(reverb_room), dotted_eighth, 0.35, 0.35)
             + echo(leads.mix(reverb_room), dotted_eighth, 0.3, 0.22))
    music = highpassed(music, 28)

    # The music steps back while the line is typed, so the keys are heard.
    music *= dip(length, cues["keys"][0] - 0.1, cues["enter"] + 0.15, 0.5)

    # The music comes up with the picture, from the moment the set is
    # switched on until the picture stands. A tone at full level on the very
    # first sample is what an AAC encoder overshoots on, and the television's
    # second encode would then lower the whole track to keep that one peak
    # under -1 dBTP.
    time = clock(length)
    music *= numpy.clip((time - cues["crtOn"]) / (picture_up - cues["crtOn"]), 0, 1)

    # The music fades away over the end card along a quarter of a cosine:
    # three decibels down halfway, and gone as the set switches off.
    fade_start = finale + FADE_AFTER_FINALE
    music *= numpy.cos(numpy.pi / 2 * numpy.clip((time - fade_start) / (off - fade_start), 0, 1))

    # The set goes off with the picture: whatever is left stops as the
    # picture folds to a line, and only the tube's own sound remains.
    cut = samples(off + 0.17)
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

    # The cube steps round a notch for each key as the film's word is dialed,
    # one key after another, at the pace of a telephone dialing a stored
    # number.
    dial = cues["dial"]
    keys = dialed(dial["word"])
    for index, at in enumerate(numpy.linspace(dial["from"], dial["to"], len(keys), endpoint=False)):
        bus.add(dtmf(keys[index]), at, gain=0.3, pan=-0.54 + 1.08 * index / len(keys), reverb=0.05)

    # Each logo lands at the loudest moment of its whoosh, a little after the
    # move begins, because the move eases out and covers most of its way at
    # once.
    whoosh = recording("whoosh-short")
    for at, pan in zip(cues["whooshes"], (-0.9, 0.9), strict=True):
        bus.add(whoosh, at + 0.08 - loudest_moment(whoosh), gain=1.4, pan=pan)

    # The two logos drawn up into the cube's top as it tips onto the mark,
    # ending as it locks there under the flash.
    pull = cues["meet"] - cues["press"]
    pull_time = clock(pull)
    drawn_in = swept_band(noise(pull), 400 * 20 ** (pull_time / pull), width=0.8) * (pull_time / pull) ** 2
    bus.add(drawn_in, cues["press"], gain=0.9, reverb=0.15)
    bus.add(clack(LOCK_WEIGHT), cues["meet"], gain=CLACK_GAIN)
    for note in (69, 76, 81):
        bus.add(lead(note, 1.4), cues["meet"], gain=0.2, reverb=0.2)

    # Each quarter turn: the air moving while the cube swings round, and the
    # clack of it locking onto its face.
    for start, lock in cues["turns"]:
        kind = "stab" if lock in cues["stabs"] else "system" if lock in cues["systems"] else "turn"
        weight = TURN_WEIGHTS[kind]
        bus.add(swish(lock - start), start, gain=TURN_AIR_GAIN * weight, pan=0.2)
        bus.add(clack(weight), lock, gain=CLACK_GAIN)

    # The spin up to the end card, and the cube stopping dead as the mark.
    spin_start, spin_end = cues["spin"]
    bus.add(spin(spin_end - spin_start), spin_start, gain=0.5, reverb=0.1)
    bus.add(clack(LOCK_WEIGHT), cues["finale"], gain=CLACK_GAIN)

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
        bus.add(varied, at, gain=level, pan=0.54 * (generator.random() - 0.5))
    bus.add(key_press, cues["enter"], gain=RETURN_GAIN)
    bus.add(tick(84), cues["banner"], gain=0.5)
    for index, at in enumerate(cues["steps"]):
        bus.add(tick(88 + (index % 2) * 3), at, gain=0.6, pan=0.36)
    bus.add(tick(93, 0.2), cues["done"], gain=0.7, reverb=0.3)

    for index, at in enumerate(cues["windows"]):
        bus.add(swish(0.25), at, gain=0.3, pan=0.63 if index % 2 else -0.27)

    pop = recording("pop")
    for index, at in enumerate(cues["facts"]):
        bus.add(pop, at, gain=0.9, pan=-0.72 + 0.72 * index)

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
