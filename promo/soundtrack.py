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

The music is in E minor, at the cue sheet's tempo, with one chord to a bar.
It is made in the manner of Kraftwerk's Trans Europa Express, Die
Mensch-Maschine and Computerwelt: a tonal kick without a click, a dark snare,
hi-hats on the sixteenths just off the beat, a metallic hit, a staccato bass
in sixteenths, a sequencer running through the chords, and a lead whose
filter closes on every note and which sings with a slow vibrato. Each sound,
and where in the beat each drum lands and how hard, is set so that it
measures as the medians across those three albums do. Its melody, bass line,
chords and beat are its own, and nothing of a recording is in it.

It needs numpy and scipy, and ffmpeg for reading the MP3s and writing FLAC:

    .venv/bin/pip install numpy scipy
"""

import functools
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
#: the highest true peak they may reach, in dBTP. HyperFrames lowers the
#: whole track once the encoded peak passes -1 dBTP. The film's two AAC
#: encodes overshoot the ceiling by about 0.2 dB, so it sits low enough that
#: HyperFrames never has to. A ceiling lower still would make the limiter
#: flatten every kick.
LOUDNESS_TARGET = -14.0
PEAK_CEILING = -2.0

#: What a television of the PAL era hums and whines at: the mains, and the
#: line transformer running at 625 lines 25 times a second.
MAINS = 50
LINE_FREQUENCY = 625 * 25

#: The chords, by name: the root the bass plays and the three tones the
#: sequencer runs through, as MIDI note numbers, so 64 is the E above middle
#: C. The tones lie close together from one chord to the next, so the
#: sequencer barely moves when the chord changes.
CHORDS = {
    "Em": {"root": 40, "tones": (64, 67, 71)},
    "C": {"root": 36, "tones": (60, 64, 67)},
    "D": {"root": 38, "tones": (62, 66, 69)},
    "Am": {"root": 33, "tones": (60, 64, 69)},
    "B": {"root": 35, "tones": (63, 66, 71)},
}

#: One chord per bar, for the sixteen bars of the film. The opening, the
#: merge, the headline and the install line go round E minor and close on D,
#: so the stabs land. The admin climbs from A minor to B, the dominant, which
#: the build holds, and the end card comes home to E minor.
PROGRESSION = ("Em", "Em", "C", "D", "Em", "Em", "C", "D", "Em", "Am", "C", "D", "B", "Em", "C", "Em")

#: The chords of the three stabs, one each. Their roots fall E, D, C into the
#: A minor the admin starts on.
STAB_CHORDS = ("Em", "D", "C")

#: The beat, in sixteenths of a bar. The groove is two bars that take turns:
#: the kick on one and three, with a push after three in the first bar, the
#: snare on two and four, the hi-hat on sixteenths just off the beat, and a
#: metallic hit late in the second bar. The merge plays the beat in half
#: time, and the build puts the kick on every beat. A bar that leads into a
#: new part ends on the snares of FILL as well.
SIXTEENTHS = 16
GROOVE = (
    {"kick": (0, 8, 10), "snare": (4, 12), "hat": (2, 7, 11), "metal": ()},
    {"kick": (0, 8), "snare": (4, 12), "hat": (2, 7, 11, 15), "metal": (14,)},
)
HALF_TIME = {"kick": (0, 10), "snare": (8,), "hat": (2, 7, 11, 15), "metal": ()}
BUILD = {"kick": (0, 4, 8, 12), "snare": (), "hat": (2, 6, 10, 14), "metal": ()}
FILL = (14, 15)

#: How far under its level the snare roll over the build starts, in
#: decibels. It swells to full level by the end card.
ROLL_START = -12.0

#: The drums. Each is set so that, played alone, it matches the medians
#: measured across Kraftwerk's Trans Europa Express, Die Mensch-Maschine and
#: Computerwelt: its pitch, its band and how it falls away. Each "levels"
#: lists how far the sound has fallen, in decibels, so many milliseconds
#: after its peak, and "attack" is how long the rise to the peak takes, in
#: seconds.
#:
#: The kick is a sine and nothing else. Its pitch falls from 161 Hz toward
#: 50 Hz with a time constant of 17 ms, which puts it at the pitches measured
#: at its onset and 50 ms later.
KICK = {"pitch": (161, 50, 0.0173), "attack": 0.006,
        "levels": ((0, 0), (25, -8.4), (50, -13.5), (100, -20.5), (174, -40))}

#: The snare: noise in a band around 1 kHz, a little brighter noise above it,
#: and a low tone under them, moving from 196 to 241 Hz.
SNARE = {"band": (635, 1500), "upper": (1500, 5000), "upper_gain": 0.2, "body": (196, 241), "body_gain": 0.3,
         "attack": 0.008, "levels": ((0, 0), (40, -12.6), (82, -20), (164, -40))}

#: The hi-hat: noise between 2.5 and 7 kHz with a faint metallic chord in it,
#: three partials at the lowest's frequency in Hz and at two ratios above it.
HAT = {"band": (2500, 7000), "partials": (4572, 1.37, 1.88), "metal": 0.1, "attack": 0.006,
       "levels": ((0, 0), (25, -6.7), (50, -12.5), (107, -20), (215, -40))}

#: The metallic hit: three partials that share no harmonics, over a breath of
#: high noise. It falls away as the snare does.
METAL = {"partials": (4861, 1.36, 1.82), "attack": 0.002, "levels": ((0, 0), (40, -12.6), (82, -20), (164, -40))}

#: How loud each drum peaks against the kick, in decibels. The metallic hit
#: could not be measured on its own, and sits 4 dB under the snare.
DRUM_LEVELS = {"kick": 0.0, "snare": -7.5, "hat": -16.1, "metal": -11.5}

#: The feel, for the four sixteenths of a beat: how many milliseconds each
#: drum lands late there, or early where the number is negative, and how
#: many decibels under its level it is played.
DRUM_TIMING = {"kick": (-0.9, 2.2, 0.1, 2.7), "snare": (0.6, 1.5, 1.5, 2.0), "hat": (1.8, 1.4, 1.1, 0.3),
               "metal": (0.0, 0.0, 0.0, 0.0)}
DRUM_ACCENTS = {"kick": (0.0, -8.2, -2.7, -7.7), "snare": (0.0, -6.7, -6.9, -11.1), "hat": (-1.2, -4.3, -2.7, -5.7),
                "metal": (0.0, 0.0, 0.0, 0.0)}

#: How much of each drum goes to the reverb.
DRUM_REVERB = {"kick": 0.05, "snare": 0.05, "hat": 0.05, "metal": 0.1}

#: Where the drums stand in the stereo field: the hi-hats take turns between
#: the two sides, and the metallic hit leans right.
HAT_PAN = 0.7
METAL_PAN = 0.4

#: The bass: the levels of its first eight harmonics in decibels against the
#: fundamental, and above them a fall that puts the spectrum's centroid at
#: the 4.44th harmonic. A note is held, then falls, 6 dB down after 0.71 of a
#: sixteenth and 12 dB down after 1.25. Two voices a cent apart, one in each
#: channel, beat slowly against each other.
BASS = {"harmonics": (0, -7.75, -13.7, -10.8, -20.9, -17.0, -22.5, -16.5), "centroid": 4.44,
        "off6": 0.71, "off12": 1.25, "detune": 1.0}

#: The bass line of a bar: the sixteenth a note starts on and how many
#: semitones it lies over the chord's root. Each note lasts until the next.
BASSLINE = ((0, 0), (2, 12), (3, 0), (5, 0), (6, 12), (8, 0), (10, 12), (11, 7), (13, 0), (14, 12))

#: How loud the bass is while it comes in, before the merge, as a factor.
BASS_INTRO = 0.5

#: The lead, whose voice the sequencer plays as well: the levels of its first
#: eight harmonics in decibels, a filter that closes on every note within
#: 50 ms until the spectrum's centroid has fallen to 0.81 of where it began,
#: and a vibrato of 4.5 Hz and 19 cents that sets in once a note is held. The
#: two voices of a note lie 3 cents apart, one to each side.
LEAD = {"harmonics": (0, -8.5, -18.9, -20.6, -27.1, -28.1, -31.0, -34.3), "fall": 0.81,
        "vibrato": (4.5, 19.0), "detune": 3.0, "pan": 0.5}

#: The sequencer: sixteenths through the chord's tones in ARPEGGIO's order,
#: an octave above CHORDS. Each note is held for 0.8 of a sixteenth, falls
#: 6 dB by 0.6 of one and 12 dB by a whole one, and the notes take turns
#: between the sides.
SEQUENCER = {"gate": 0.8, "off6": 0.6, "off12": 1.0, "pan": 0.4}
ARPEGGIO = (0, 2, 1, 2, 0, 1, 2, 1)

#: How the sequencer starts as the picture comes up: darker by this many
#: decibels per harmonic, and at this share of its level. It opens fully by
#: the merge.
SEQUENCER_OPENING = {"darker": 3.0, "level": 0.3}

#: The lead's melody, phrase by phrase: the bar from the start of the
#: phrase, the beat in that bar, how many beats the note lasts, and the note.
#: Its motif is the leap up and the steps down that open THEME. The merge
#: calls it on C and on D, the headline states it and answers it higher, the
#: admin answers with long notes from above, the build climbs the dominant
#: and leans on its leading note, and the end card resolves, brings the
#: motif back, and comes to rest an octave above where THEME first did.
MERGE_CALL = (
    (0, 0, 1, "G4"), (0, 1, 0.5, "C5"), (0, 1.5, 0.5, "B4"), (0, 2, 2, "G4"),
    (1, 0, 1, "A4"), (1, 1, 0.5, "D5"), (1, 1.5, 0.5, "C5"), (1, 2, 1, "A4"), (1, 3, 1, "F#4"),
)
THEME = (
    (0, 0, 1, "B4"), (0, 1, 0.5, "E5"), (0, 1.5, 0.5, "D5"), (0, 2, 1, "B4"), (0, 3, 1, "G4"),
    (1, 0, 1.5, "A4"), (1, 1.5, 0.5, "B4"), (1, 2, 2, "E4"),
    (2, 0, 1, "C5"), (2, 1, 0.5, "G5"), (2, 1.5, 0.5, "F#5"), (2, 2, 1, "E5"), (2, 3, 1, "C5"),
    (3, 0, 1.5, "D5"), (3, 1.5, 0.5, "E5"), (3, 2, 2, "F#5"),
)
CHORUS = (
    (0, 0, 2, "A5"), (0, 2, 1, "G5"), (0, 3, 1, "E5"),
    (1, 0, 2, "G5"), (1, 2, 1, "E5"), (1, 3, 1, "C5"),
    (2, 0, 1.5, "F#5"), (2, 1.5, 0.5, "G5"), (2, 2, 2, "A5"),
)
CLIMB = (
    (0, 0, 0.5, "B4"), (0, 0.5, 0.5, "D#5"), (0, 1, 0.5, "F#5"), (0, 1.5, 0.5, "A5"),
    (0, 2, 0.5, "B5"), (0, 2.5, 0.5, "A5"), (0, 3, 0.5, "F#5"), (0, 3.5, 0.5, "D#5"),
)
ENDING = (
    (0, 0, 2, "E5"), (0, 2, 1, "B4"), (0, 3, 0.5, "E5"), (0, 3.5, 0.5, "D5"),
    (1, 0, 1, "C5"), (1, 1, 1, "G4"), (1, 2, 1.5, "A4"), (1, 3.5, 0.5, "B4"),
    (2, 0, 4, "E5"),
)

#: How much of its length a lead note is held. Notes shorter than a beat
#: are cut a little shorter, so a run of them does not blur.
LEAD_GATE = {"short": 0.92, "long": 0.97}

#: How long the chords on the merge and on the stabs sound, in seconds, and
#: how loud each of their three notes is against a note of the melody.
MERGE_CHORD_SECONDS = 1.4
STAB_SECONDS = 0.45
CHORD_GAIN = 0.5

#: How loud the instruments are against the drums, in decibels.
BALANCE = {"drums": 0.0, "bass": -16.0, "sequencer": -18.8, "lead": -14.3}

#: How much louder the music is than the effects, as integrated loudness in
#: LU.
MUSIC_ABOVE_EFFECTS = 12.3

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


def decibels(level):
    """A level in decibels as a factor."""
    return 10 ** (level / 20)


def peak_normalized(sound):
    """A sound scaled so its highest peak is at one."""
    return sound / numpy.abs(sound).max()


def falling(seconds, levels, attack):
    """A gain over time that rises to a peak and falls through set levels.

    The levels are joined in straight lines in decibels, which is an
    exponential fall between them, and the last fall carries on past the last
    point. A raised cosine leads up to the peak over the attack.

    Args:
        seconds: The sound's length.
        levels: Pairs of milliseconds after the peak and the level there in
            decibels, the first at the peak itself.
        attack: How long the rise to the peak takes, in seconds.
    """
    time = clock(seconds) * 1000
    marks = numpy.array([point[0] for point in levels], dtype=float) + attack * 1000
    values = numpy.array([point[1] for point in levels], dtype=float)
    slope = (values[-1] - values[-2]) / (marks[-1] - marks[-2])
    level = numpy.interp(time, marks, values)
    beyond = time > marks[-1]
    level[beyond] = values[-1] + slope * (time[beyond] - marks[-1])
    gain = decibels(level)
    rising = time < attack * 1000
    gain[rising] = 0.5 - 0.5 * numpy.cos(numpy.pi * time[rising] / (attack * 1000))
    return gain


def held_then_falling(seconds, six, twelve):
    """A note's level: held, then falling evenly in decibels, so that it is
    6 dB down at one moment and 12 dB down at the other.

    Args:
        seconds: The note's length.
        six: When it is 6 dB down, in seconds from its start.
        twelve: When it is 12 dB down, in seconds from its start.
    """
    time = clock(seconds)
    slope = 6 / (twelve - six)
    hold = max(2 * six - twelve, 0.0)
    return ramp_in(decibels(-slope * numpy.maximum(time - hold, 0)), 0.003)


def kick():
    """The kick: a sine whose pitch falls fast, as KICK sets it, peaking at
    one."""
    start, end, time_constant = KICK["pitch"]
    seconds = 0.4
    time = clock(seconds)
    pitch = end + (start - end) * numpy.exp(-time / time_constant)
    body = numpy.sin(2 * numpy.pi * numpy.cumsum(pitch) / RATE)
    return peak_normalized(ramp_out(body * falling(seconds, KICK["levels"], KICK["attack"])))


def snare():
    """The snare, as SNARE sets it, peaking at one."""
    seconds = 0.3
    time = clock(seconds)
    band = filtered(noise(seconds), "bandpass", SNARE["band"], order=4)
    upper = filtered(noise(seconds), "bandpass", SNARE["upper"], order=4) * SNARE["upper_gain"]
    first, last = SNARE["body"]
    pitch = numpy.geomspace(first, last, len(time))
    body = numpy.sin(2 * numpy.pi * numpy.cumsum(pitch) / RATE) * SNARE["body_gain"]
    sound = (band + upper) / numpy.abs(band).max() + body
    return peak_normalized(ramp_out(sound * falling(seconds, SNARE["levels"], SNARE["attack"])))


def partials(lowest, ratios, seconds):
    """Three sines, at a frequency and at two ratios above it. They share no
    harmonics, so together they sound like struck metal rather than a note.

    Args:
        lowest: The lowest frequency, in Hz.
        ratios: The other two as multiples of the lowest.
        seconds: How long they sound.
    """
    time = clock(seconds)
    frequencies = (lowest, lowest * ratios[0], lowest * ratios[1])
    return sum(numpy.sin(2 * numpy.pi * frequency * time + phase) * weight
               for frequency, phase, weight in zip(frequencies, (0.0, 1.3, 2.1), (1.0, 0.7, 0.5), strict=True))


def hat():
    """The closed hi-hat, as HAT sets it, peaking at one."""
    seconds = 0.3
    lowest, *ratios = HAT["partials"]
    sound = peak_normalized(filtered(noise(seconds), "bandpass", HAT["band"]))
    sound += peak_normalized(partials(lowest, ratios, seconds)) * HAT["metal"]
    return peak_normalized(ramp_out(sound * falling(seconds, HAT["levels"], HAT["attack"])))


def metal():
    """The metallic hit, as METAL sets it, peaking at one."""
    seconds = 0.3
    lowest, *ratios = METAL["partials"]
    sound = partials(lowest, ratios, seconds) + filtered(noise(seconds), "highpass", 6000) * 0.1
    return peak_normalized(ramp_out(sound * falling(seconds, METAL["levels"], METAL["attack"])))


def harmonic_amplitudes(levels, centroid=None, highest=24):
    """The amplitude of each harmonic of a voice, the fundamental first.

    The first eight are the levels given. Above them the amplitudes fall
    with a power of the harmonic's number. Where a centroid is given, the
    power is the one that puts the spectrum's magnitude centroid there;
    otherwise the fall is that of a sawtooth through a 12 dB filter.

    Args:
        levels: The first eight harmonics' levels in decibels against the
            fundamental.
        centroid: The magnitude centroid wanted, as a harmonic number, or None.
        highest: How many harmonics there are.
    """
    given = decibels(numpy.array(levels, dtype=float))

    def extended(power):
        above = given[-1] * (len(given) / numpy.arange(len(given) + 1, highest + 1)) ** power
        return numpy.concatenate([given, above])

    if centroid is None:
        return extended(3.0)
    numbers = numpy.arange(1, highest + 1)
    low, high = 0.0, 8.0
    for _ in range(60):
        power = (low + high) / 2
        amplitudes = extended(power)
        if numpy.sum(numbers * amplitudes) / numpy.sum(amplitudes) > centroid:
            low = power
        else:
            high = power
    return extended((low + high) / 2)


def closing_tilt(amplitudes, fall):
    """How many decibels per harmonic a closing filter takes off a voice so
    the spectrum's magnitude centroid falls to a share of where it began.

    Args:
        amplitudes: The voice's harmonics, as harmonic_amplitudes gives them.
        fall: The share of the centroid that is left once the filter has
            closed.
    """
    numbers = numpy.arange(1, len(amplitudes) + 1)
    start = numpy.sum(numbers * amplitudes) / numpy.sum(amplitudes)
    low, high = 0.0, 12.0
    for _ in range(60):
        tilt = (low + high) / 2
        tilted = amplitudes * decibels(-tilt * (numbers - 1))
        if numpy.sum(numbers * tilted) / numpy.sum(tilted) / start > fall:
            low = tilt
        else:
            high = tilt
    return (low + high) / 2


def darkened(amplitudes, tilt):
    """A voice's harmonics with each one taken down by so many decibels more
    than the one below it."""
    return amplitudes * decibels(-tilt * numpy.arange(len(amplitudes)))


def additive(note, seconds, amplitudes, closing=0.0, vibrato=None, detune=0.0):
    """A pitched voice built harmonic by harmonic, so its spectrum is exactly
    the one given and nothing aliases.

    Args:
        note: A MIDI note.
        seconds: Its length.
        amplitudes: Its harmonics, the fundamental first.
        closing: How many decibels per harmonic a filter takes off as it
            closes over the first 50 ms, as closing_tilt works it out.
        vibrato: Its rate in Hz and its depth in cents, which sets in between
            120 and 240 ms into the note, or None.
        detune: How far it lies off the note, in cents.
    """
    time = clock(seconds)
    frequency = numpy.full(len(time), hertz(note) * 2 ** (detune / 1200))
    if vibrato:
        rate, cents = vibrato
        depth = cents * numpy.clip((time - 0.12) / 0.12, 0, 1)
        frequency = frequency * 2 ** (depth * numpy.sin(2 * numpy.pi * rate * time) / 1200)
    phase = 2 * numpy.pi * numpy.cumsum(frequency) / RATE
    tilt = closing * (1 - numpy.exp(-time / 0.05))
    sound = numpy.zeros_like(time)
    for number, amplitude in enumerate(amplitudes, start=1):
        if number * frequency.max() > RATE * 0.45:
            break
        sound += amplitude * decibels(-tilt * (number - 1)) * numpy.sin(number * phase)
    return sound


@functools.cache
def bass_spectrum():
    """The bass's harmonics, as BASS sets them."""
    return harmonic_amplitudes(BASS["harmonics"], BASS["centroid"])


@functools.cache
def lead_spectrum():
    """The lead's harmonics and how far its filter closes, as LEAD sets
    them."""
    amplitudes = harmonic_amplitudes(LEAD["harmonics"])
    return amplitudes, closing_tilt(amplitudes, LEAD["fall"])


def bass_note(note, seconds, sixteenth):
    """One note of the bass: two voices a cent apart, one in each channel,
    held and then falling as BASS sets it.

    Args:
        note: A MIDI note.
        seconds: How long it lasts.
        sixteenth: A sixteenth's length at the film's tempo, in seconds.

    Returns:
        Stereo samples, as two rows.
    """
    envelope = held_then_falling(seconds, BASS["off6"] * sixteenth, BASS["off12"] * sixteenth)
    return numpy.stack([
        ramp_out(additive(note, seconds, bass_spectrum(), detune=side * BASS["detune"] / 2) * envelope, 0.004)
        for side in (-1, 1)
    ])


def sequencer_note(note, sixteenth, darker=0.0):
    """One step of the sequencer: a short note in the lead's voice, without
    its vibrato.

    Args:
        note: A MIDI note.
        sixteenth: A sixteenth's length at the film's tempo, in seconds.
        darker: How many decibels per harmonic it is darkened by.
    """
    amplitudes, tilt = lead_spectrum()
    seconds = SEQUENCER["gate"] * sixteenth
    envelope = held_then_falling(seconds, SEQUENCER["off6"] * sixteenth, SEQUENCER["off12"] * sixteenth)
    return ramp_out(additive(note, seconds, darkened(amplitudes, darker), closing=tilt) * envelope, 0.004)


def lead_note(note, seconds):
    """One note of the lead: two voices a few cents apart, one to each side,
    whose filter closes as the note begins and which sing with vibrato once
    it is held.

    Args:
        note: A MIDI note.
        seconds: How long it sounds.

    Returns:
        Stereo samples, as two rows.
    """
    amplitudes, tilt = lead_spectrum()
    sides = []
    for side in (-1, 1):
        voice = additive(note, seconds, amplitudes, closing=tilt, vibrato=LEAD["vibrato"], detune=side * LEAD["detune"] / 2)
        sides.append(stereo(ramp_out(ramp_in(voice, 0.006), 0.03), side * LEAD["pan"]))
    return sum(sides)


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


def bar_starts(start, end, bar):
    """The start of every bar from one moment up to another, in seconds."""
    return numpy.arange(start, end - 1e-6, bar)


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
    """The music stem: a piece in the manner of Kraftwerk, with one motif
    growing through it.

    The sequencer comes up dark with the picture and opens, and the bass
    joins in the second bar. The merge brings the beat in half time, a chord
    as the logos lock, and the lead calling the motif. The headline and the
    install line run the groove under the theme. The stabs fall through three
    chords. The admin's groove carries the lead's long answer, the build
    climbs over a roll of snares that follows the systems, and the end card
    lands like a stab, resolves, brings the motif back, and fades away until
    the set switches off.

    Returns:
        Stereo samples for the whole film.
    """
    length = cues["length"]
    beat = 60 / cues["bpm"]
    bar = 4 * beat
    sixteenth = bar / SIXTEENTHS
    parts = cues["parts"]
    press, finale, off = cues["press"], cues["finale"], cues["crtOff"]
    picture_up = cues["crtOn"] + beat
    buses = {name: Bus(length) for name in BALANCE}
    drums, bass, sequencer, leads = (buses[name] for name in ("drums", "bass", "sequencer", "lead"))
    kit = {"kick": kick(), "snare": snare(), "hat": hat(), "metal": metal()}
    leading_in = {round(parts["headline"] - bar, 6), round(parts["nothing"] - bar, 6)}

    def chord_at(moment):
        return CHORDS[PROGRESSION[min(int(moment // bar), len(PROGRESSION) - 1)]]

    def drum(kind, at, level=0.0, pan=0.0):
        drums.add(kit[kind], at, gain=decibels(DRUM_LEVELS[kind] + level), pan=pan, reverb=DRUM_REVERB[kind])

    def play(pattern, start):
        """Plays a bar of a drum pattern, each drum with the timing and the
        accent of where it falls in the beat."""
        fill = FILL if round(start, 6) in leading_in else ()
        for kind, steps in pattern.items():
            for order, step in enumerate(steps + fill if kind == "snare" else steps):
                within = step % 4
                pan = HAT_PAN * (1 if order % 2 else -1) if kind == "hat" else METAL_PAN if kind == "metal" else 0.0
                drum(kind, start + step * sixteenth + DRUM_TIMING[kind][within] / 1000, DRUM_ACCENTS[kind][within], pan)

    def chord(name, at, seconds):
        for tone in CHORDS[name]["tones"]:
            leads.add(lead_note(tone + 12, seconds), at, gain=CHORD_GAIN, reverb=0.2)

    def phrase(events, start):
        for offset, beat_in_bar, beats, name in events:
            gate = LEAD_GATE["short"] if beats < 1 else LEAD_GATE["long"]
            leads.add(lead_note(midi(name), beats * beat * gate), start + offset * bar + beat_in_bar * beat, reverb=0.12)

    # The sequencer comes up dark and quiet with the picture and opens fully
    # by the merge. It rests for the stabs and runs on until the set switches
    # off.
    for start, end in ((picture_up, parts["nothing"]), (parts["admin"], off)):
        for moment in numpy.arange(start, end - 1e-6, sixteenth):
            step = round(moment / sixteenth) % SIXTEENTHS
            closed = 1 - min(1.0, (moment - picture_up) / (press - picture_up))
            note = chord_at(moment)["tones"][ARPEGGIO[step % len(ARPEGGIO)]] + 12
            level = (1.0 if step % 4 == 0 else 0.7) * (1 - (1 - SEQUENCER_OPENING["level"]) * closed)
            sequencer.add(sequencer_note(note, sixteenth, SEQUENCER_OPENING["darker"] * closed), moment, gain=level,
                          pan=SEQUENCER["pan"] * (1 if step % 2 else -1))

    # The bass comes in quietly with the second bar, is up by the merge, and
    # plays until the stabs and again from the admin on.
    for start, end, level in ((bar, press, BASS_INTRO), (press, parts["nothing"], 1.0), (parts["admin"], off, 1.0)):
        for moment in bar_starts(start, end, bar):
            root = chord_at(moment)["root"]
            for position, (step, interval) in enumerate(BASSLINE):
                following = BASSLINE[position + 1][0] if position + 1 < len(BASSLINE) else SIXTEENTHS
                accent = 1.0 if step % 4 == 0 else 0.8
                bass.add(bass_note(root + interval, (following - step) * sixteenth, sixteenth),
                         moment + step * sixteenth, gain=accent * level)

    # The beat: half time through the merge, the groove under the headline and
    # the install line, under the admin and under the end card, and the build
    # with a roll of snares that follows the systems' quarter turns and runs
    # on in sixteenths into the end card, swelling as it goes.
    for moment in bar_starts(press, parts["headline"], bar):
        play(HALF_TIME, moment)
    for start, end in ((parts["headline"], parts["nothing"]), (parts["admin"], parts["systems"]), (finale, off)):
        for index, moment in enumerate(bar_starts(start, end, bar)):
            play(GROOVE[index % len(GROOVE)], moment)
    for moment in bar_starts(parts["systems"], finale, bar):
        play(BUILD, moment)
    roll = list(cues["systems"]) + list(numpy.arange(cues["systems"][-1] + sixteenth, finale - 1e-6, sixteenth))
    for index, at in enumerate(roll):
        drum("snare", at, ROLL_START * (1 - index / (len(roll) - 1)))

    # The stabs: the kick, the snare, the bass's root and the chord at once,
    # with silence between them. The end card lands the same way, with a
    # snare beside the groove's first kick.
    for at, name in zip(cues["stabs"], STAB_CHORDS, strict=True):
        drum("kick", at)
        drum("snare", at)
        bass.add(bass_note(CHORDS[name]["root"], 2 * sixteenth, sixteenth), at)
        chord(name, at, STAB_SECONDS)
    drum("snare", finale)

    # The lead: a chord as the logos lock, and the melody through the film.
    chord(PROGRESSION[int(cues["meet"] // bar)], cues["meet"], MERGE_CHORD_SECONDS)
    phrase(MERGE_CALL, press)
    phrase(THEME, parts["headline"])
    phrase(CHORUS, parts["admin"])
    phrase(CLIMB, parts["systems"])
    phrase(ENDING, finale)

    music = sum(bus.mix(reverb_room) * decibels(BALANCE[name]) for name, bus in buses.items())
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

    # The music is set against the effects by loudness, so the balance between
    # them holds whatever the music plays.
    music *= decibels(integrated_loudness(effects) + MUSIC_ABOVE_EFFECTS - integrated_loudness(music))

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
