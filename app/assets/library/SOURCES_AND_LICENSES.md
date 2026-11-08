# Mutopia MIDI examples

Primary sources retrieved 2026-11-08. The eight Mutopia examples below were compiled locally from the Mutopia Project's own licensed LilyPond notation using GNU LilyPond 2.24.4. The additional user-local popular MIDI collection is documented separately in `popular/SOURCES_AND_LICENSES.json`; it is not included in this open-licence claim.
The compositions and the notation/encoding licences are recorded separately below. Primary `.ly` files and the locally compiled `.source.mid` files are preserved in `sources/`; source headers contain the original licence and typesetter credits. The generated excerpts retain those licences.

Primary repository revision: `2144afd6f52d56c5b6995b8b589ef1268b3139f0`. Each source URL below is pinned to that revision. The encodings' reuse permission was checked in the primary notation headers, independently of the composition's public-domain status.

Each displayed demo is the opening 32–48 seconds, merged to MIDI type 0. Tempos, velocities and instrument events are unchanged. Für Elise is transposed down one octave to fit the motor pitch range; other excerpts keep their source pitch. All sounding notes/pedals are released at the cut. The app separately arranges the imported notes for the chosen printer. The excerpts therefore retain the encoding's original licence; the two ShareAlike excerpts remain available under their respective CC BY-SA licences.

Rebuild the excerpts offline with `python tools/build_midi_library.py` (Python + mido). To download the same pinned notation and recompile, supply `--refresh --lilypond <path-to-lilypond>`; LilyPond and convert-ly are required only for recompilation. No compiler is required to run the application.

Compilation evidence: all eight primary scores compiled successfully with LilyPond 2.24.4; generated MIDI metadata identifies that compiler and the source staff names. convert-ly updates obsolete LilyPond syntax before compilation. For Moonlight only, three obsolete `override-auto-beam-setting` calls are removed from the temporary converted file; these affect printed beam grouping, not performed notes. Original primary source files remain unchanged.

## Für Elise

Ludwig van Beethoven; LilyPond/MIDI: Stelios Samelis, Mutopia Project #931.

Encoding licence: [Public Domain](https://creativecommons.org/licenses/publicdomain/).
Composition: public domain.
Source and licence: https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=931
Primary LilyPond source: https://raw.githubusercontent.com/MutopiaProject/MutopiaProject/2144afd6f52d56c5b6995b8b589ef1268b3139f0/ftp/BeethovenLv/WoO59/fur_Elise_WoO59/fur_Elise_WoO59.ly
Notation SHA-256: `828a7bd1b42e441fe1b0eb0389ba46f1502dab28bbe488389e635fb446ba7a67`
Locally compiled full MIDI SHA-256: `8bdb5238aa5e1ce86ca8c1ee86625ffc5ff69ea4c530a86f505b16c10bed6f46`
Excerpt: `library/fur_elise.mid` — 40.0 seconds; 276 notes. Opening 40s excerpt; merged type 0; explicit note/pedal releases at cut; transpose -12 semitones; no tempo change.

Compiled MIDI metadata: `GNU LilyPond 2.24.4`; staff names `down, up` match the primary score's Staff definitions. The generated encoding is directly traceable to the licensed notation above.

## Ay Işığı Sonatı · I

Ludwig van Beethoven; LilyPond/MIDI: Stewart Holmes, Mutopia Project #276.

Encoding licence: [CC BY-SA 2.5](https://creativecommons.org/licenses/by-sa/2.5/).
Composition: public domain.
Source and licence: https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=276
Primary LilyPond source: https://raw.githubusercontent.com/MutopiaProject/MutopiaProject/2144afd6f52d56c5b6995b8b589ef1268b3139f0/ftp/BeethovenLv/O27/moonlight/moonlight-lys/moonlight1-a4.ly
Notation SHA-256: `97f5f8f0b3cc31de38dd2c284f7e66f4f4b319fca0cdc941ee6f5f4927833ac5`
Locally compiled full MIDI SHA-256: `0b590d70a30d261fac82259d5fd94c4aaa80157e00f274891bd1409c0f74d9b1`
Excerpt: `library/moonlight.mid` — 48.0 seconds; 200 notes. Opening 48s excerpt; merged type 0; explicit note/pedal releases at cut; transpose +0 semitones; no tempo change.

Compiled MIDI metadata: `GNU LilyPond 2.24.4`; staff names `down, up` match the primary score's Staff definitions. The generated encoding is directly traceable to the licensed notation above.

## Prelude in C · BWV 846

Johann Sebastian Bach; LilyPond/MIDI: Tobias Erbsland, Mutopia Project #5.

Encoding licence: [Public Domain](https://creativecommons.org/licenses/publicdomain/).
Composition: public domain.
Source and licence: https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=5
Primary LilyPond source: https://raw.githubusercontent.com/MutopiaProject/MutopiaProject/2144afd6f52d56c5b6995b8b589ef1268b3139f0/ftp/BachJS/BWV846/wtk1-prelude1/wtk1-prelude1.ly
Notation SHA-256: `9e4540143b5c5a9884f215428837fe91d1b471b02669f3a07ce50560736078e9`
Locally compiled full MIDI SHA-256: `c65e25fee31921f4cf371ef4e4e1458fedc8a776805fc925815ee88ecb6142fd`
Excerpt: `library/bach_prelude_c.mid` — 32.0 seconds; 129 notes. Opening 32s excerpt; merged type 0; explicit note/pedal releases at cut; transpose +0 semitones; no tempo change.

Compiled MIDI metadata: `GNU LilyPond 2.24.4`; staff names `lower, upper` match the primary score's Staff definitions. The generated encoding is directly traceable to the licensed notation above.

## İki Sesli İnvensiyon No. 1

Johann Sebastian Bach; LilyPond/MIDI: jeff covey, Mutopia Project #40.

Encoding licence: [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
Composition: public domain.
Source and licence: https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=40
Primary LilyPond source: https://raw.githubusercontent.com/MutopiaProject/MutopiaProject/2144afd6f52d56c5b6995b8b589ef1268b3139f0/ftp/BachJS/BWV772/bach-invention-01/bach-invention-01.ly
Notation SHA-256: `3c01302f70efd1dd6f43becaf19b9b2aac49e25b3e89666e3e55bc576c6cd55d`
Locally compiled full MIDI SHA-256: `31e1e5b1d70d00ff5a92af3e1f58db0d4c1a735581c786db6ca9d51afebb76d5`
Excerpt: `library/bach_invention_1.mid` — 32.0 seconds; 229 notes. Opening 32s excerpt; merged type 0; explicit note/pedal releases at cut; transpose +0 semitones; no tempo change.

Compiled MIDI metadata: `GNU LilyPond 2.24.4`; staff names `one, two` match the primary score's Staff definitions. The generated encoding is directly traceable to the licensed notation above.

## Pathétique · Adagio cantabile

Ludwig van Beethoven; LilyPond/MIDI: Chris Sawer, Mutopia Project #295.

Encoding licence: [Public Domain](https://creativecommons.org/licenses/publicdomain/).
Composition: public domain.
Source and licence: https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=295
Primary LilyPond source: https://raw.githubusercontent.com/MutopiaProject/MutopiaProject/2144afd6f52d56c5b6995b8b589ef1268b3139f0/ftp/BeethovenLv/O13/pathetique-2/pathetique-2.ly
Notation SHA-256: `7d7c233230bc558d6275119b1ca9af1b4f5ebe762e29855698fc1e08032acc7a`
Locally compiled full MIDI SHA-256: `0c8ec41aeafd45cb303a265a6b262286b3b7c10a0409e11186fad0a828e78a27`
Excerpt: `library/pathetique.mid` — 40.0 seconds; 194 notes. Opening 40s excerpt; merged type 0; explicit note/pedal releases at cut; transpose +0 semitones; no tempo change.

Compiled MIDI metadata: `GNU LilyPond 2.24.4`; staff names `down, up` match the primary score's Staff definitions. The generated encoding is directly traceable to the licensed notation above.

## Prelude in E minor · Op. 28 No. 4

Frédéric Chopin; LilyPond/MIDI: Magnus Lewis-Smith, Mutopia Project #468.

Encoding licence: [Public Domain](https://creativecommons.org/licenses/publicdomain/).
Composition: public domain.
Source and licence: https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=468
Primary LilyPond source: https://raw.githubusercontent.com/MutopiaProject/MutopiaProject/2144afd6f52d56c5b6995b8b589ef1268b3139f0/ftp/ChopinFF/O28/Chop-28-4/Chop-28-4.ly
Notation SHA-256: `d4fca574bc3c3ad810ee643d42b7299e1c97b3b8b3fa379c3d7f77edb02f6192`
Locally compiled full MIDI SHA-256: `2480c04dd67b3ac10e910165af5b3d7f937911edc91696af251683fa78fdbf40`
Excerpt: `library/chopin_prelude_e.mid` — 40.0 seconds; 245 notes. Opening 40s excerpt; merged type 0; explicit note/pedal releases at cut; transpose +0 semitones; no tempo change.

Compiled MIDI metadata: `GNU LilyPond 2.24.4`; staff names `lh, rh` match the primary score's Staff definitions. The generated encoding is directly traceable to the licensed notation above.

## Clair de lune

Claude Debussy; LilyPond/MIDI: Keith OHara, Mutopia Project #1778.

Encoding licence: [Public Domain](https://creativecommons.org/licenses/publicdomain/).
Composition: public domain.
Source and licence: https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=1778
Primary LilyPond source: https://raw.githubusercontent.com/MutopiaProject/MutopiaProject/2144afd6f52d56c5b6995b8b589ef1268b3139f0/ftp/DebussyC/L75/debussy_Ste_Bergamesq_Clair/debussy_Ste_Bergamesq_Clair.ly
Notation SHA-256: `c78762a27972f0643a34b994bffa1d058b1bb51e3947c0b50029aa75359e2a49`
Locally compiled full MIDI SHA-256: `1aaec3cdbea39ec2b92de599cea275dcfdabe5090f3b5bb8e406ddc528203c8a`
Excerpt: `library/clair_de_lune.mid` — 48.0 seconds; 118 notes. Opening 48s excerpt; merged type 0; explicit note/pedal releases at cut; transpose +0 semitones; no tempo change.

Compiled MIDI metadata: `GNU LilyPond 2.24.4`; staff names `lower, upper` match the primary score's Staff definitions. The generated encoding is directly traceable to the licensed notation above.

## Arabesque No. 1

Claude Debussy; LilyPond/MIDI: Keith OHara, Mutopia Project #1777.

Encoding licence: [Public Domain](https://creativecommons.org/licenses/publicdomain/).
Composition: public domain.
Source and licence: https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=1777
Primary LilyPond source: https://raw.githubusercontent.com/MutopiaProject/MutopiaProject/2144afd6f52d56c5b6995b8b589ef1268b3139f0/ftp/DebussyC/L66/debussy_Arabesque_1/debussy_Arabesque_1.ly
Notation SHA-256: `4639d0220a0a242e2928348cdf6075a7e6cdd35a8b051d67612aa99a2d636a3a`
Locally compiled full MIDI SHA-256: `e1dfd70b61778db9af50010826dd1205280a5589f1b4f8af85a5a6d6569f2adf`
Excerpt: `library/arabesque_1.mid` — 40.0 seconds; 351 notes. Opening 40s excerpt; merged type 0; explicit note/pedal releases at cut; transpose +0 semitones; no tempo change.

Compiled MIDI metadata: `GNU LilyPond 2.24.4`; staff names `lower, upper` match the primary score's Staff definitions. The generated encoding is directly traceable to the licensed notation above.

## User-supplied Super Mario Theme

`app/assets/mario.mid` was supplied by the user for this local project. No redistribution permission was asserted. This existing file is kept separate from the openly licensed downloaded examples. A publicly distributed application package should omit this user asset unless suitable permission is obtained.
