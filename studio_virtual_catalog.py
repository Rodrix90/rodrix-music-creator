"""
Catálogo centralizado y extensible de Perfiles del Estudio Virtual para Rodrix Music Creator 4.0.

Distingue explícitamente tres dimensiones técnicas por cada perfil:
1. Características del instrumento físico (`physical_instrument`)
2. Interpretación musical (`musical_performance`)
3. Procesamiento y sonido de estudio (`studio_processing`)

Reglas de diseño e integración con UdioAPI:
- Los nombres de músicos y canciones mostrados en la UI son referencias estilísticas descriptivas;
  hacia el campo `style` de UdioAPI únicamente se emiten descriptores técnicos puros (sin nombres
  de artistas ni títulos protegidos y sin modificar nunca el campo `prompt` con la letra).
- Las descripciones orientan textualmente al modelo generativo; no simulan circuitos DSP exactos ni
  clonan audios comerciales o librerías protegidas por derechos de autor.
- La opción `"auto"` ("Original / Automático") no impone instrucciones adicionales.
- Estrategia progresiva de compactación (Etapas 0 -> 1 -> 2 -> 3) para respetar el límite oficial de
  1.000 caracteres de UdioAPI sin eliminar silenciosamente selecciones del usuario.
"""

from __future__ import annotations

from typing import Optional

STUDIO_DEFAULT_ID = "auto"
STUDIO_DEFAULT_LABEL = "Original / Automático"
UDIO_STYLE_MAX_CHARS = 1000

STUDIO_PROFILE_HONESTY_NOTICE = (
    "Las selecciones del Estudio Virtual traducen atributos del instrumento, la interpretación y el "
    "procesamiento de estudio en descriptores textuales para el parámetro style de UdioAPI. Orientan la "
    "estética sonora resultante sin alterar tu letra en prompt, sin clonar audios originales y sin sustituir "
    "emulaciones DSP físicas exactas ni librerías comerciales."
)

# Orden de prioridad al compactar bajo presión extrema de caracteres
STUDIO_CATEGORY_PRIORITY_VOCAL = ("drums", "basses", "guitars", "keyboards", "microphones", "consoles")
STUDIO_CATEGORY_PRIORITY_INSTRUMENTAL = ("drums", "basses", "guitars", "keyboards", "consoles", "microphones")

STUDIO_VIRTUAL_CATEGORIES = [
    {
        "key": "drums",
        "field_name": "studio_drums",
        "select_id": "selStudioDrums",
        "title": "Baterías",
        "short_title": "Batería",
        "icon": "ph-drum",
        "emoji": "🥁",
        "solo_mode": "drums",
        "items": [
            {
                "id": "bonham",
                "label": "John Bonham — Rock potente y acústico.",
                "short_label": "Rock potente acústico",
                "reference_note": "Referencia estilística descriptiva: batería rock acústica de gran tamaño y sala amplia.",
                "core_tag": "heavy oversized acoustic rock drums",
                "physical_instrument": "oversized 26-inch acoustic maple kick drum, 14-inch chrome snare, deep 15-18 inch toms, big bronze cymbals",
                "musical_performance": "heavy behind-the-beat pocket, rapid kick triplets, thunderous snare backbeats and explosive tom fills",
                "studio_processing": "distant overhead and bright wooden room microphones with warm analog tape saturation",
                "summary_es": {
                    "instrumento": "Cascos acústicos profundos (bombo 26\", caja metálica 14\", toms grandes y platillos amplios).",
                    "interpretacion": "Groove pesado ligeramente detrás del pulso, tresillos de bombo y fills contundentes.",
                    "procesamiento": "Microfonía ambiental de sala grande en madera y compresión analógica cálida."
                },
            },
            {
                "id": "peart",
                "label": "Neil Peart — Rock progresivo y precisión.",
                "short_label": "Rock progresivo técnico",
                "reference_note": "Referencia estilística descriptiva: batería progresiva multi-tom articulada y precisa.",
                "core_tag": "precise progressive rock multi-tom drums",
                "physical_instrument": "multi-tom birch and maple progressive acoustic drum kit with crisp snare and articulate bell ride",
                "musical_performance": "razor-sharp metered precision, syncopated ride patterns and intricate progressive time-signature fills",
                "studio_processing": "focused multi-mic close isolation, tight gating, sharp transient attack and wide stereo overheads",
                "summary_es": {
                    "instrumento": "Set progresivo de abedul/arce con múltiples toms afinados, caja definida y ride con campana nítida.",
                    "interpretacion": "Precisión métrica milimétrica, síncopas sobre ride y redobles complejos compuestos.",
                    "procesamiento": "Aislamiento multi-micrófono cercano, puertas dinámicas limpias y apertura estéreo definida."
                },
            },
            {
                "id": "copeland",
                "label": "Stewart Copeland — Reggae, ska y síncopas.",
                "short_label": "Reggae, ska y síncopas",
                "reference_note": "Referencia estilística descriptiva: batería sincopada con caja aguda y hi-hat ágil.",
                "core_tag": "syncopated high-cracking ska-rock drums",
                "physical_instrument": "tight high-tuned steel 14-inch snare drum, punchy compact kick, crisp splash cymbals and bright hi-hat",
                "musical_performance": "reggae and ska syncopated rimshots, agile bouncing hi-hat bark and energetic cross-beat accents",
                "studio_processing": "crisp upper-mid transient snap, dry tight room focus and subtle rhythmic tape echo ambience",
                "summary_es": {
                    "instrumento": "Caja de acero afinada aguda, bombo compacto de respuesta rápida, hi-hat brillante y splash.",
                    "interpretacion": "Síncopas reggae/ska, rimshots en contratiempo y fraseo nervioso en hi-hat.",
                    "procesamiento": "Ataque agudo cercano, sala seca focalizada y eco de cinta sutil."
                },
            },
            {
                "id": "moon",
                "label": "Keith Moon — Rock explosivo y fills expresivos.",
                "short_label": "Rock explosivo y fills",
                "reference_note": "Referencia estilística descriptiva: batería rock impetuosa guiada por toms y platillos.",
                "core_tag": "explosive fiery rock tom-driven drums",
                "physical_instrument": "twin bass drums, deep resonant coated rack and floor toms, wide dark crashing bronze cymbals",
                "musical_performance": "continuous melodic sweeping tom rolls, fiery cymbal cascades and exuberant high-energy rhythmic motion",
                "studio_processing": "open vintage studio overhead mics capturing raw live energy and natural room wash",
                "summary_es": {
                    "instrumento": "Doble bombo clásico, toms resonantes con parches rugosos y platillos crash expansivos.",
                    "interpretacion": "Fills melódicos casi continuos en toms y explosiones constantes de platillos.",
                    "procesamiento": "Overheads vintage abiertos y captura cruda de sala viva sin sobre-compresión."
                },
            },
            {
                "id": "watts",
                "label": "Charlie Watts — Rock clásico con influencia de jazz.",
                "short_label": "Rock clásico / jazz swing",
                "reference_note": "Referencia estilística descriptiva: set compacto vintage con aire jazz y bolsillo natural.",
                "core_tag": "vintage 4-piece swing-pocket classic rock drums",
                "physical_instrument": "compact vintage 4-piece maple drum kit, dry dark jazz ride cymbal and crisp wooden snare",
                "musical_performance": "relaxed understated pocket, subtle swing push-pull feel and airy micro-pauses on hi-hat backbeats",
                "studio_processing": "warm ribbon overhead and front-kit miking with woody midrange clarity and gentle tube glue",
                "summary_es": {
                    "instrumento": "Set vintage compacto de 4 cuerpos en arce, ride oscuro de jazz y caja de madera cálida.",
                    "interpretacion": "Bolsillo relajado clásico con leve balanceo jazz y espacios limpios en hi-hat.",
                    "procesamiento": "Microfonía de cinta frontal y superior con calidez tubular y foco en medios."
                },
            },
            {
                "id": "portnoy",
                "label": "Mike Portnoy — Metal progresivo y doble bombo.",
                "short_label": "Metal prog / doble bombo",
                "reference_note": "Referencia estilística descriptiva: doble bombo técnico y percusión progresiva pesada.",
                "core_tag": "technical double-kick progressive metal drums",
                "physical_instrument": "double-kick progressive acoustic kit with snappy high-cut snare, octoban accents, china and stack cymbals",
                "musical_performance": "tight double bass drum patterns, razor-precise progressive meter transitions and staccato accent fills",
                "studio_processing": "modern high-impact multi-mic compression, click-defined kick punch and tight controlled low-end",
                "summary_es": {
                    "instrumento": "Doble bombo de ataque rápido, caja cortante, toms articulados y platillos china/stack.",
                    "interpretacion": "Patrones técnicos de doble bombo, cambios de compás progresivos y fills cortantes.",
                    "procesamiento": "Compresión moderna de alto impacto, bombo definido en ataque y graves controlados."
                },
            },
            {
                "id": "smith",
                "label": "Chad Smith — Funk-rock potente.",
                "short_label": "Funk-rock potente",
                "reference_note": "Referencia estilística descriptiva: batería funk-rock de pegada firme y notas fantasma.",
                "core_tag": "hard-hitting funk-rock pocket drums",
                "physical_instrument": "heavy maple and brass-snare funk-rock acoustic kit with deep 24-inch kick and bright crisp cymbals",
                "musical_performance": "authoritative hard-hitting pocket, intricate snare ghost notes and tight syncopated funk-rock groove",
                "studio_processing": "punchy analog console bus compression, forward snare snap and solid upfront chest impact",
                "summary_es": {
                    "instrumento": "Bombo de 24\", caja de latón con gran pegada y platillos brillantes.",
                    "interpretacion": "Groove funk-rock contundente repleto de notas fantasma y acentos sincopados.",
                    "procesamiento": "Compresión de bus con punch analógico, caja al frente y pegada en graves."
                },
            },
            {
                "id": "collins",
                "label": "Phil Collins — Rock progresivo y sonido de batería ochentoso.",
                "short_label": "Prog / batería ochentosa",
                "reference_note": "Referencia estilística descriptiva: toms resonantes sin parche inferior y ambiente de los 80.",
                "core_tag": "1980s gated-reverb progressive rock drums",
                "physical_instrument": "concert single-headed tom drum kit, crisp snappy snare and deep resonant floor toms",
                "musical_performance": "booming dramatic descending tom fills, commanding progressive groove and wide spacious backbeats",
                "studio_processing": "1980s heavily compressed room listen-mic ambience and classic gated reverb snare and tom tail",
                "summary_es": {
                    "instrumento": "Toms de concierto abiertos de gran ataque y caja seca profunda.",
                    "interpretacion": "Descensos dramáticos de toms y groove progresivo amplio y contundente.",
                    "procesamiento": "Ambiente sobrecomprimido estilo micrófono de sala 80s con gated reverb clásico."
                },
            },
            {
                "id": "grohl",
                "label": "Dave Grohl — Grunge y rock contundente.",
                "short_label": "Grunge / rock pesado",
                "reference_note": "Referencia estilística descriptiva: batería rock de golpeo enérgico y cascos profundos.",
                "core_tag": "hard-slamming deep-shell grunge rock drums",
                "physical_instrument": "deep heavy-shell rock drum kit with massive 24-inch kick, deep metal snare and heavy rock crashes",
                "musical_performance": "visceral full-strength heavy strokes, relentless driving rock eighth-note feel and crashing transitions",
                "studio_processing": "aggressive analog tape saturation, loud upfront room microphones and raw weighty low-mid punch",
                "summary_es": {
                    "instrumento": "Cascos profundos de rock, bombo grande de 24\", caja metálica profunda y crash pesados.",
                    "interpretacion": "Golpeo frontal muy enérgico, empuje constante y caídas de platillos intensas.",
                    "procesamiento": "Saturación de cinta analógica, sala presente y medios-graves densos y crudos."
                },
            },
            {
                "id": "baker",
                "label": "Ginger Baker — Blues-rock, jazz y ritmos africanos.",
                "short_label": "Blues-rock / polirritmia jazz",
                "reference_note": "Referencia estilística descriptiva: independencia polirrítmica en toms y swing blues-rock.",
                "core_tag": "polyrhythmic Afro-jazz blues-rock drums",
                "physical_instrument": "vintage dual-kick jazz-rock kit with coated melodic toms, sizzle ride and warm resonant wood shells",
                "musical_performance": "polyrhythmic Afro-jazz tom independence, swirling jazz phrasing and improvisational blues-rock drive",
                "studio_processing": "organic 1960s three-mic stereo spread with lively room air and vintage tube console warmth",
                "summary_es": {
                    "instrumento": "Set vintage doble bombo con toms melódicos, parches rugosos y ride con remaches.",
                    "interpretacion": "Polirritmia independiente entre toms y bombos con impulso blues-rock y swing.",
                    "procesamiento": "Captura orgánica tipo años 60 en tres micrófonos y calidez analógica a válvulas."
                },
            },
        ],
    },
    {
        "key": "guitars",
        "field_name": "studio_guitar",
        "select_id": "selStudioGuitar",
        "title": "Guitarras eléctricas",
        "short_title": "Guitarra",
        "icon": "ph-guitar",
        "emoji": "🎸",
        "solo_mode": "guitar",
        "items": [
            {
                "id": "srv_number_one",
                "label": "Stevie Ray Vaughan — Number One Stratocaster.",
                "short_label": "Number One Stratocaster",
                "reference_note": "Referencia estilística descriptiva: Stratocaster vintage con ataque Texas blues.",
                "core_tag": "heavy-gauge vintage single-coil Texas blues guitar",
                "physical_instrument": "worn 1960s sunburst alder electric guitar with overwound single-coil pickups and heavy-gauge strings",
                "musical_performance": "fierce percussive pick rakes, wide expressive blues bends and authoritative vocal neck-pickup vibrato",
                "studio_processing": "cranked high-headroom clean tube combo pushed with mild green mid-hump overdrive and off-axis dynamic mic",
                "summary_es": {
                    "instrumento": "Cuerpo de aliso tipo Strat 60s, bobinas simples calientes y cuerdas de calibre grueso.",
                    "interpretacion": "Ataque percusivo intenso de púa, bendings amplios de blues y vibrato firme.",
                    "procesamiento": "Combo a válvulas de alto headroom empujado con overdrive cálido en medios."
                },
            },
            {
                "id": "vai_evo",
                "label": "Steve Vai — Ibanez Evo.",
                "short_label": "Ibanez Evo virtuosa",
                "reference_note": "Referencia estilística descriptiva: superstrat moderna con humbuckers y palanca flotante.",
                "core_tag": "virtuosic high-gain floating-tremolo superstrat guitar",
                "physical_instrument": "sculpted solid-body superstrat electric guitar with hot ceramic-alnico humbuckers and floating locking vibrato",
                "musical_performance": "liquid legato cascades, dramatic whammy pitch inflection, pinch harmonics and expressive vocal sustain",
                "studio_processing": "multi-stage high-gain tube head through 4x12 cabinet, stereo modulated delay and studio pitch shimmer",
                "summary_es": {
                    "instrumento": "Superstrat ergonómica con humbuckers de alta salida y puente flotante de doble bloqueo.",
                    "interpretacion": "Legato fluido, armónicos artificiales, inflexiones de palanca y fraseo melódico veloz.",
                    "procesamiento": "Cabezal high-gain a válvulas con gabinete 4x12, delay estéreo modulado y brillo."
                },
            },
            {
                "id": "frusciante_strat62",
                "label": "John Frusciante — Stratocaster 1962.",
                "short_label": "Stratocaster 1962 funk/rock",
                "reference_note": "Referencia estilística descriptiva: Stratocaster 1962 orgánica entre limpio cristalino y crunch.",
                "core_tag": "1962 vintage single-coil edge-of-breakup electric guitar",
                "physical_instrument": "1962 vintage alder Stratocaster-style guitar with rosewood fingerboard and low-output aged single-coils",
                "musical_performance": "syncopated muted funk-rock chords, sparse lyrical triads and raw emotionally bent single-note leads",
                "studio_processing": "vintage British tube plexi amp on edge of breakup with spring reverb warmth and subtle analog chorus",
                "summary_es": {
                    "instrumento": "Cuerpo de aliso y diapasón de palisandro estilo 1962 con micrófonos single-coil dulces.",
                    "interpretacion": "Rasgueos funk sincopados, tríadas minimalistas y solos melódicos muy expresivos.",
                    "procesamiento": "Amplificador británico al borde de la saturación con reverb de resortes y chorus suave."
                },
            },
            {
                "id": "summers_tele61",
                "label": "Andy Summers — Telecaster 1961.",
                "short_label": "Telecaster 1961 atmosférica",
                "reference_note": "Referencia estilística descriptiva: Telecaster limpia modulada con acordes suspendidos.",
                "core_tag": "1961 Telecaster modulated wide-chord electric guitar",
                "physical_instrument": "early-1960s ash single-cut Telecaster guitar with neck humbucker warmth and bright bridge single-coil",
                "musical_performance": "spacious add9 suspended arpeggios, crisp reggae-rock upstroke chords and clean atmospheric textures",
                "studio_processing": "chimey clean studio amp layered with swirling analog flanger-chorus modulation and rhythmic stereo echo",
                "summary_es": {
                    "instrumento": "Single-cut de fresno estilo 1961 con humbucker en mástil y single-coil claro en puente.",
                    "interpretacion": "Acordes abiertos con novenas agregadas, arpegios amplios y golpes rítmicos nítidos.",
                    "procesamiento": "Canal limpio cristalino con modulación analógica flanger/chorus y eco estéreo."
                },
            },
            {
                "id": "evh_frankenstrat",
                "label": "Eddie Van Halen — Frankenstrat.",
                "short_label": "Frankenstrat brown sound",
                "reference_note": "Referencia estilística descriptiva: superstrat de un humbucker con saturación orgánica clásica.",
                "core_tag": "classic hot-rodded humbucker hard-rock electric guitar",
                "physical_instrument": "raw ash custom superstrat guitar with direct-mounted bridge PAF-style humbucker and maple fretboard",
                "musical_performance": "two-hand tapping arpeggios, swinging palm-muted rock boogie rhythms and energetic dive-bomb vibrato",
                "studio_processing": "variac-driven brown-sound vintage tube stack saturation, pre-drive analog phaser and rich plate reverb",
                "summary_es": {
                    "instrumento": "Cuerpo de fresno con mástil de arce y un humbucker directo en puente de tono abierto.",
                    "interpretacion": "Tapping a dos manos, rítmica con swing y palm-mute, más palanca enérgica.",
                    "procesamiento": "Saturación clásica de cabezal británico a válvulas, phaser pre-distorsión y plate reverb."
                },
            },
            {
                "id": "gilmour_black_strat",
                "label": "David Gilmour — Black Strat.",
                "short_label": "Black Strat espacial",
                "reference_note": "Referencia estilística descriptiva: Stratocaster negra melódica con sustain espacioso.",
                "core_tag": "soaring lyrical single-coil ambient rock electric guitar",
                "physical_instrument": "black alder Stratocaster guitar with maple neck, fat bridge single-coil pickup and short tremolo arm",
                "musical_performance": "soaring vocal slow string bends, spacious sustained lyrical melodies and bell-like arpeggio motifs",
                "studio_processing": "high-headroom clean tube stack fed with optical compression, smooth sustain fuzz, rotary speaker and stereo tape delay",
                "summary_es": {
                    "instrumento": "Cuerpo de aliso con mástil de arce y pastilla simple robusta de agudos redondos.",
                    "interpretacion": "Estiramientos largos cantables, notas sostenidas y fraseo pausado altamente melódico.",
                    "procesamiento": "Stack limpio potente con compresor óptico, fuzz cremoso, rotary y delay de cinta."
                },
            },
            {
                "id": "may_red_special",
                "label": "Brian May — Red Special.",
                "short_label": "Red Special orquestal",
                "reference_note": "Referencia estilística descriptiva: guitarra semi-hueca en serie con armonías tipo coro.",
                "core_tag": "harmonized orchestral Class-A chime rock guitar",
                "physical_instrument": "semi-chambered oak-and-mahogany electric guitar with three series-wired phase-switchable single coils played with coin pick",
                "musical_performance": "singing violin-like midrange sustain, multi-part harmonized guitar choir layers and lyrical phrasing",
                "studio_processing": "treble booster driving cranked British Class-A EL84 combo amplifiers in warm studio room ambience",
                "summary_es": {
                    "instrumento": "Cuerpo semi-cámara roble/caoba con 3 bobinas simples cableadas en serie fuera de fase.",
                    "interpretacion": "Sustain vocal tipo violín, ataque rígido definido y armonización multicapa.",
                    "procesamiento": "Treble booster atacando amplis Clase A EL84 saturados en sala cálida."
                },
            },
            {
                "id": "green_greeny_lp",
                "label": "Peter Green — Greeny Les Paul.",
                "short_label": "Greeny Les Paul blues",
                "reference_note": "Referencia estilística descriptiva: Les Paul 1959 con bobina invertida fuera de fase.",
                "core_tag": "out-of-phase vintage mahogany blues electric guitar",
                "physical_instrument": "1959 mahogany single-cut Les Paul-style guitar with reversed out-of-phase neck PAF magnet giving hollow nasal chime",
                "musical_performance": "haunting slow minor blues bends, delicate touch sensitivity and weeping dynamic finger vibrato",
                "studio_processing": "warm vintage tube amplifier right on sweet clean-to-grit edge with natural spring reverb bloom",
                "summary_es": {
                    "instrumento": "Caoba/arce estilo 1959 con imán de pastilla mástil invertido (sonido hueco fuera de fase).",
                    "interpretacion": "Blues menor lento y delicado, sensibilidad extrema a la púa o dedos y vibrato lloroso.",
                    "procesamiento": "Amplificador valvular vintage apenas saturado con reverb de resortes natural."
                },
            },
            {
                "id": "hendrix_monterey_strat",
                "label": "Jimi Hendrix — Monterey Strat.",
                "short_label": "Monterey Strat psicodélica",
                "reference_note": "Referencia estilística descriptiva: Stratocaster 60s de doble-stops, fuzz y wah.",
                "core_tag": "fiery 1960s psychedelic fuzz single-coil guitar",
                "physical_instrument": "late-1960s reverse-strung maple-neck Stratocaster guitar with glassy bell-tone single-coil pickups",
                "musical_performance": "expressive thumb-over rhythm embellishments, double-stop bends, octave swells and fiery improvisation",
                "studio_processing": "roaring 100W vintage British stack pushed by warm germanium fuzz, expressive wah sweep and rotating speaker depth",
                "summary_es": {
                    "instrumento": "Stratocaster de arce años 60 de timbre campana, cuerdas equilibradas en tensión.",
                    "interpretacion": "Embellecimientos rítmicos con doble cuerda, ligados y fraseo psicodélico expresivo.",
                    "procesamiento": "Stack británico 100W con fuzz de germanio, filtro wah y modulación rotatoria."
                },
            },
            {
                "id": "page_number_one_lp",
                "label": "Jimmy Page — Number One Les Paul.",
                "short_label": "Number One Les Paul rock",
                "reference_note": "Referencia estilística descriptiva: Les Paul 1959 de riffs pesados y capas de estudio.",
                "core_tag": "classic slim-neck PAF humbucker hard-rock guitar",
                "physical_instrument": "1959 slim-taper mahogany and carved maple-top Les Paul guitar with warm vintage PAF humbuckers",
                "musical_performance": "swaggering blues-rock riffs, dynamic clean-to-heavy picking shifts and loose gritty rock phrasing",
                "studio_processing": "layered multi-amp studio tracking blending crisp small low-watt tube room mics with big cranked arena stack",
                "summary_es": {
                    "instrumento": "Cuerpo caoba/arce tapa tallada con humbuckers PAF vintage de respuesta orgánica.",
                    "interpretacion": "Riffs de blues-rock con empuje, contraste limpio/agresivo y fraseo suelto clásico.",
                    "procesamiento": "Doblado en capas mezclando ampli chico en sala lejana y stack valvular potente."
                },
            },
        ],
    },
    {
        "key": "basses",
        "field_name": "studio_bass",
        "select_id": "selStudioBass",
        "title": "Bajos eléctricos",
        "short_title": "Bajo",
        "icon": "ph-wave-sine",
        "emoji": "🔊",
        "solo_mode": "bass",
        "items": [
            {
                "id": "pastorius_fretless",
                "label": "Jaco Pastorius — Fretless / Come On, Come Over.",
                "short_label": "Fretless / Jazz fusion",
                "reference_note": "Referencia estilística descriptiva (no audio copiado): timbre fretless melódico y síncopa ágil.",
                "core_tag": "singing fretless electric bass guitar",
                "physical_instrument": "real physical epoxy-coated fretless Jazz Bass guitar with bridge single-coil pickup and roundwound steel strings, zero synth bass",
                "musical_performance": "lyrical singing fretless glissando mwah, crisp 16th-note fingerstyle funk grooves and natural harmonics",
                "studio_processing": "dry upfront midrange cabinet focus blended with clean solid-state direct bass track",
                "summary_es": {
                    "instrumento": "Bajo eléctrico fretless con mástil sellado en epoxi, pastilla de puente y cuerdas entorchadas.",
                    "interpretacion": "Expresividad vocal mwah en glissandos, síncopa de semicorcheas y armónicos naturales.",
                    "procesamiento": "Mezcla seca en medios definidos entre gabinete cercano y línea directa limpia."
                },
            },
            {
                "id": "jamerson_motown",
                "label": "James Jamerson — Motown / What's Going On.",
                "short_label": "Soul clásico flatwound",
                "reference_note": "Referencia estilística descriptiva (no audio copiado): P-Bass vintage cálido con cuerdas flatwound.",
                "core_tag": "warm flatwound vintage Precision electric bass guitar",
                "physical_instrument": "authentic early-1960s alder split-coil Precision electric bass guitar with heavy flatwound strings and bridge mute, zero synth bass",
                "musical_performance": "melodic syncopated hook lines, soulful chromatic passing notes and deep glued rhythm-section pocket",
                "studio_processing": "warm vacuum-tube direct console preamp blended with vintage 1x15 flip-top tube bass combo",
                "summary_es": {
                    "instrumento": "Bajo eléctrico tipo Precision con pastilla dividida, cuerdas lisas flatwound y sordina en puente.",
                    "interpretacion": "Líneas melódicas sincopadas con notas de paso cromáticas y peso sólido en la base.",
                    "procesamiento": "Previo valvular de consola directa combinado con combo valvular 1x15 clásico."
                },
            },
            {
                "id": "miller_jazz_funk",
                "label": "Marcus Miller — Funk y articulación técnica / Teen Town.",
                "short_label": "Slap & fingerstyle hi-fi",
                "reference_note": "Referencia estilística descriptiva (no audio copiado): Jazz Bass activo brillante de articulación técnica.",
                "core_tag": "active hi-fi slap-and-finger funk electric bass",
                "physical_instrument": "real physical ash-body 1970s active Jazz Bass guitar with onboard 2-band boost preamp and bright steel strings, zero synth bass",
                "musical_performance": "razor-clean thumb slap and pop articulation, double-thumb precision and melodic fast funk runs",
                "studio_processing": "scooped midrange studio hi-fi DI clarity with crisp sparkling highs and fast FET compression",
                "summary_es": {
                    "instrumento": "Bajo de fresno con previo activo 2 bandas, diapasón de arce y cuerdas de acero brillantes.",
                    "interpretacion": "Slap, pop y doble pulgar ultra precisos combinados con frases rápidas de funk.",
                    "procesamiento": "Línea directa hi-fi con medios levemente ahuecados, agudos definidos y compresión FET."
                },
            },
            {
                "id": "wooten_slap",
                "label": "Victor Wooten — Slap avanzado / Classical Thump.",
                "short_label": "Slap avanzado / doble pulgar",
                "reference_note": "Referencia estilística descriptiva (no audio copiado): bajo activo ergonómico con técnica percusiva.",
                "core_tag": "technical double-thumb slap electric bass guitar",
                "physical_instrument": "real physical active PJ-pickup modern electric bass guitar with low action and lively steel roundwound strings, zero synth bass",
                "musical_performance": "percussive double-thumb up-down thumping, rapid muted plucks, harmonic tapping and agile solo phrasing",
                "studio_processing": "wide-bandwidth studio DI capture with transparent multi-band compression highlighting percussive transients",
                "summary_es": {
                    "instrumento": "Bajo activo ergonómico P/J de acción baja y cuerdas metálicas de alta respuesta.",
                    "interpretacion": "Doble pulgar arriba/abajo, percussión mutada rápida, tapping armónico y virtuosismo.",
                    "procesamiento": "DI cristalino de rango completo con compresión multibanda para definición percusiva."
                },
            },
            {
                "id": "flea_funk_rock",
                "label": "Flea — Funk-rock / Give It Away.",
                "short_label": "Funk-rock enérgico",
                "reference_note": "Referencia estilística descriptiva (no audio copiado): bajo funk-rock explosivo en slap y dedos.",
                "core_tag": "energetic punk-funk slap electric bass guitar",
                "physical_instrument": "real physical active humbucker and jazz electric bass guitar with snappy steel roundwounds, zero synth bass",
                "musical_performance": "explosive bouncing thumb slap riffs, energetic punk-funk fingerstyle pulse and tight kick-drum lock",
                "studio_processing": "high-headroom solid-state bass stack punch blended with gritty DI edge and tight sub control",
                "summary_es": {
                    "instrumento": "Bajo sólido activo de respuesta inmediata y cuerdas entorchadas con gran rebote.",
                    "interpretacion": "Riffs explosivos de slap-and-pop y líneas enérgicas a dedos amarradas al bombo.",
                    "procesamiento": "Stack sólido de alto headroom con leve rugosidad DI y graves compactos."
                },
            },
            {
                "id": "lee_prog_jazz",
                "label": "Geddy Lee — Rock progresivo / YYZ.",
                "short_label": "Jazz Bass prog agresivo",
                "reference_note": "Referencia estilística descriptiva (no audio copiado): Jazz Bass agresivo con clank en medios.",
                "core_tag": "clanky aggressive progressive electric bass guitar",
                "physical_instrument": "authentic thin-neck 1972 ash Jazz Bass guitar with dual bright single-coils and fresh steel roundwounds, zero synth bass",
                "musical_performance": "hard-plucked driving fingerstyle triplets, complex odd-meter progressive riffs and high-energy melodic counterlines",
                "studio_processing": "dual parallel path blending tube overdrive growl with compressed crisp high-bite direct bass signal",
                "summary_es": {
                    "instrumento": "Bajo Jazz 1972 de mástil delgado con dos single-coils brillantes y entorchado metálico.",
                    "interpretacion": "Pulsación agresiva a dedos estilo púa, tresillos rápidos y métricas progresivas.",
                    "procesamiento": "Ruta paralela entre saturación valvular con mordida y señal DI comprimida."
                },
            },
            {
                "id": "burton_distorted_bass",
                "label": "Cliff Burton — Bajo distorsionado / Anesthesia.",
                "short_label": "Bajo distorsión / wah",
                "reference_note": "Referencia estilística descriptiva (no audio copiado): bajo solista con fuzz y filtro wah.",
                "core_tag": "fuzz-wah distorted heavy electric bass guitar",
                "physical_instrument": "real physical neck-through mahogany electric bass guitar with high-output pickups and heavy steel strings, zero synth bass",
                "musical_performance": "aggressive fuzz-driven solo phrasing, classical counter-melody bends and roaring high-register bass lines",
                "studio_processing": "snarling vintage fuzz overdrive and expressive wah sweep pushed through cranked bass cabinet mic",
                "summary_es": {
                    "instrumento": "Bajo neck-through de caoba con pastillas de alta ganancia y cuerdas gruesas.",
                    "interpretacion": "Fraseo solista agresivo con contramelodías, estiramientos y pasajes agudos.",
                    "procesamiento": "Distorsión fuzz analógica combinada con barrido wah hacia amplificador de bajo."
                },
            },
            {
                "id": "entwistle_aggressive",
                "label": "John Entwistle — Rock agresivo / My Generation.",
                "short_label": "Rock agresivo brillante",
                "reference_note": "Referencia estilística descriptiva (no audio copiado): bajo solista brillante con ataque percusivo.",
                "core_tag": "trebly lead-aggressive rock electric bass guitar",
                "physical_instrument": "real physical dual-pickup electric bass guitar fitted with ultra-bright Rotosound steel roundwound strings, zero synth bass",
                "musical_performance": "forceful typewriter-attack fingerstyle and pick playing, roaring solo bass fills and counter-melodic lead lines",
                "studio_processing": "bi-amped treble horn bite stacked over deep 15-inch speaker punch with wide upper-mid snap",
                "summary_es": {
                    "instrumento": "Bajo de doble pastilla con cuerdas Rotosound metálicas extremadamente brillantes.",
                    "interpretacion": "Ataque percusivo muy fuerte, fraseos solistas y contramelodías al frente.",
                    "procesamiento": "Bi-amplificación separando agudos de bocina sobre cuerpo profundo de 15 pulgadas."
                },
            },
            {
                "id": "arnedo_rock_argentino",
                "label": "Diego Arnedo — Rock argentino / El 38.",
                "short_label": "Rock argentino poderoso",
                "reference_note": "Referencia estilística descriptiva (no audio copiado): bajo rock pesado, grave y terroso.",
                "core_tag": "earthy heavy Argentine rock electric bass guitar",
                "physical_instrument": "real physical heavy-bodied split-pickup electric bass guitar with fat low-mid punch and sturdy steel strings, zero synth bass",
                "musical_performance": "thunderous driving rock eighth-note grooves, hypnotic riff anchors and heavy muscular pocket feel",
                "studio_processing": "weighty cranked tube bass head and 8x10 cabinet growl with gritty midrange rock density",
                "summary_es": {
                    "instrumento": "Bajo eléctrico robusto con pastilla dividida de gran peso en graves y medios-graves.",
                    "interpretacion": "Bases pesadas de rock en corcheas firmes, riffs hipnóticos y empuje terroso.",
                    "procesamiento": "Cabezal valvular exigido con caja 8x10 logrando rugido denso de rock."
                },
            },
            {
                "id": "squire_rickenbacker_prog",
                "label": "Chris Squire — Rickenbacker progresivo / Roundabout.",
                "short_label": "Rickenbacker prog con púa",
                "reference_note": "Referencia estilística descriptiva (no audio copiado): bajo brillante de arce tocado con púa.",
                "core_tag": "bright pick-driven progressive stereo electric bass",
                "physical_instrument": "authentic maple neck-through Rickenbacker-style stereo bass guitar with biting treble bridge pickup played with rigid pick, zero synth bass",
                "musical_performance": "sharp articulated pick propulsion, choral counter-melodic progressive runs and energetic driving octaves",
                "studio_processing": "stereo bi-amp split routing gritty treble attack into bright tube amp and deep low fundamental into clean sub stack",
                "summary_es": {
                    "instrumento": "Bajo de arce neck-through tipo Rickenbacker con salida estéreo y púa rígida.",
                    "interpretacion": "Líneas contrapuntísticas brillantes tocadas con púa, ataque nítido y propulsión prog.",
                    "procesamiento": "División estéreo bi-amp: agudos con saturación cálida + subgraves limpios."
                },
            },
        ],
    },
    {
        "key": "keyboards",
        "field_name": "studio_keyboard",
        "select_id": "selStudioKeyboard",
        "title": "Teclados",
        "short_title": "Teclado",
        "icon": "ph-piano-keys",
        "emoji": "🎹",
        "solo_mode": "piano",
        "items": [
            {
                "id": "piano_acustico",
                "label": "Piano acústico.",
                "short_label": "Piano de cola acústico",
                "reference_note": "Instrumento de cuerdas percutidas con caja armónica de abeto y arpa acústica.",
                "core_tag": "acoustic concert grand piano",
                "physical_instrument": "9-foot acoustic concert grand piano with solid spruce soundboard, cast-iron frame and felt hammers",
                "musical_performance": "expressive touch sensitivity across delicate arpeggios and commanding resonant full-range chords",
                "studio_processing": "matched stereo pair of small-diaphragm condensers inside open lid with natural concert hall ambience",
                "summary_es": {
                    "instrumento": "Piano de cola de concierto de 9 pies con tabla armónica de abeto y martillos de fieltro.",
                    "interpretacion": "Dinámica amplia desde arpegios íntimos hasta acordes orquestales resonantes.",
                    "procesamiento": "Par estéreo de condensadores de diafragma pequeño + aire natural de sala."
                },
            },
            {
                "id": "hammond_b3",
                "label": "Hammond B3.",
                "short_label": "Órgano Hammond B3 + Leslie",
                "reference_note": "Órgano electromecánico de ruedas fónicas con altavoz rotatorio.",
                "core_tag": "Hammond B3 tonewheel organ with rotary Leslie",
                "physical_instrument": "electro-mechanical tonewheel Hammond B3 organ with harmonic drawbars, key-click and dual-speed rotating Leslie 122 speaker",
                "musical_performance": "expressive volume pedal swells, soulful gospel and rock palm glissandos and sustained rich organ pads",
                "studio_processing": "stereo horn and rotor miking capturing Doppler swirl and warm vacuum-tube preamp saturation",
                "summary_es": {
                    "instrumento": "Órgano electromecánico de 9 tiradores con key-click y gabinete rotatorio Leslie 122.",
                    "interpretacion": "Crescendos de pedal de expresión, glissandos de palma y colchones armónicos densos.",
                    "procesamiento": "Microfonía estéreo en rotor agudo y grave con saturación tubular cálida."
                },
            },
            {
                "id": "fender_rhodes",
                "label": "Fender Rhodes.",
                "short_label": "Piano eléctrico Fender Rhodes",
                "reference_note": "Piano eléctrico electromecánico vintage de púas y pastillas magnéticas.",
                "core_tag": "vintage Fender Rhodes tine electric piano",
                "physical_instrument": "vintage 73-key electro-mechanical Fender Rhodes electric piano with steel tines, felt hammers and passive pickups",
                "musical_performance": "warm singing bell-like chord voicings, smooth soulful sustain and gentle dynamic bark when struck hard",
                "studio_processing": "stereo tremolo autopan into warm tube preamp DI with gentle analog stereo chorus sheen",
                "summary_es": {
                    "instrumento": "Piano eléctrico electromecánico de 73 teclas con varillas metálicas (tines) y pastillas.",
                    "interpretacion": "Acordes dulces tipo campana con leve gruñido cálido al atacar fuerte.",
                    "procesamiento": "Tremolo estéreo panorámico, previo analógico cálido y chorus suave."
                },
            },
            {
                "id": "wurlitzer",
                "label": "Wurlitzer.",
                "short_label": "Piano eléctrico Wurlitzer 200A",
                "reference_note": "Piano eléctrico de lengüetas de acero con mordida cálida en medios.",
                "core_tag": "vintage Wurlitzer reed electric piano",
                "physical_instrument": "classic 200A reed-based electric piano with steel vibrating reeds and electrostatic pickup plate",
                "musical_performance": "punchy percussive midrange bark on rhythmic accents, soulful blues-rock comping and warm vibrato",
                "studio_processing": "intimate tube console warmth, mild optical compression and built-in smooth vibrato modulation",
                "summary_es": {
                    "instrumento": "Piano eléctrico clásico de lengüetas vibrantes y placa captadora electrostática.",
                    "interpretacion": "Mordida percusiva característica en medios durante acompañamientos y acentos rítmicos.",
                    "procesamiento": "Vibrato clásico suavizado, calidez de consola valvular y compresión ligera."
                },
            },
            {
                "id": "yamaha_dx7",
                "label": "Yamaha DX7.",
                "short_label": "Sintetizador FM Yamaha DX7",
                "reference_note": "Sintetizador FM clásico de los 80 con campanas cristalinas.",
                "core_tag": "1980s FM crystalline bell Yamaha DX7 keyboard",
                "physical_instrument": "iconic 1980s 6-operator digital FM synthesizer engine generating glassy metallic tines and crisp bell transients",
                "musical_performance": "shimmering 80s pop and worship electric-piano ballads, bright velocity-sensitive chimes and layered pads",
                "studio_processing": "pristine stereo analog rack chorus and lush 1980s studio digital plate reverb width",
                "summary_es": {
                    "instrumento": "Sintetizador digital FM de 6 operadores estilo años 80 con transitorios metálicos.",
                    "interpretacion": "Baladas cristalinas con brillo de campanas FM y acordes sensibles a la velocidad.",
                    "procesamiento": "Chorus estéreo analógico de rack y reverb plate amplio estilo 80s."
                },
            },
            {
                "id": "minimoog",
                "label": "Minimoog.",
                "short_label": "Sintetizador analógico Minimoog",
                "reference_note": "Sintetizador analógico sustractivo monofónico con filtro escalera de 24dB.",
                "core_tag": "warm analog ladder-filter synthesizer lead and moog bass",
                "physical_instrument": "monophonic discrete analog subtractive synthesizer with three rich VCO oscillators and 24dB transistor ladder filter",
                "musical_performance": "creamy expressive pitch-glide leads, resonant filter sweeps and fat analog moog bass foundations",
                "studio_processing": "transformer console warmth, rich analog tape saturation and subtle spatial stereo delay",
                "is_synth_bass_capable": True,
                "summary_es": {
                    "instrumento": "Sintetizador analógico monofónico de 3 osciladores discretos y filtro escalera 24dB/oct.",
                    "interpretacion": "Solos melódicos con portamento cremoso, barridos de filtro y bajos analógicos densos.",
                    "procesamiento": "Saturación de cinta/transformador y retardo espacial sutil."
                },
            },
        ],
    },
    {
        "key": "consoles",
        "field_name": "studio_console",
        "select_id": "selStudioConsole",
        "title": "Consolas de grabación",
        "short_title": "Consola",
        "icon": "ph-faders-horizontal",
        "emoji": "🎚️",
        "solo_mode": "console",
        "items": [
            {
                "id": "ssl_4000",
                "label": "SSL 4000.",
                "short_label": "SSL 4000 E/G VCA",
                "reference_note": "Consola analógica británica VCA enfocada en pegada, nitidez y control.",
                "core_tag": "SSL 4000 VCA punchy studio console mix",
                "physical_instrument": "large-format Solid State Logic VCA analog mixing console with per-channel parametric EQ and stereo bus compressor",
                "musical_performance": "keeps dense rhythm sections, crisp snare snaps and fast instrumental transients locked forward",
                "studio_processing": "tight glued VCA bus compression, punchy forward midrange snap and polished hi-fi studio clarity",
                "summary_es": {
                    "instrumento": "Consola analógica gran formato con arquitectura VCA y compresor estéreo de bus.",
                    "interpretacion": "Mantiene transitorios rápidos y mezclas densas firmemente articuladas al frente.",
                    "procesamiento": "Pegada definida, medios incisivos y cohesión clásica de mezcla profesional."
                },
            },
            {
                "id": "neve_80",
                "label": "Neve 80 Series.",
                "short_label": "Neve 80 Series Clase A",
                "reference_note": "Consola británica discreta Clase A con transformadores y cuerpo cálido.",
                "core_tag": "Neve Class-A warm transformer analog console mix",
                "physical_instrument": "discrete Class-A British analog console (1073/80-series) built with hand-wound input and output transformers",
                "musical_performance": "supports expressive vocal intimacy, thick bass foundations and organic acoustic instrument bloom",
                "studio_processing": "creamy rich low-end weight, silky top-end air and musical harmonic transformer saturation",
                "summary_es": {
                    "instrumento": "Circuitería discreta Clase A británica acoplada con transformadores de entrada/salida.",
                    "interpretacion": "Realza profundidad orgánica en voces, bajos gruesos e instrumentos acústicos.",
                    "procesamiento": "Graves cremosos, agudos sedosos y saturación armónica cálida."
                },
            },
            {
                "id": "api_console",
                "label": "API Console.",
                "short_label": "API Console 2520",
                "reference_note": "Consola estadounidense con op-amps 2520 de respuesta rápida e impacto rock.",
                "core_tag": "API 2520 op-amp punchy American rock console mix",
                "physical_instrument": "American discrete 2520 op-amp analog mixing console with proportional-Q EQ and transformer-coupled stages",
                "musical_performance": "accents tight forward drum hits, energetic electric guitar bite and immediate rock ensemble impact",
                "studio_processing": "fast punchy transient snap, muscular low-mid authority and vibrant upfront analog rock character",
                "summary_es": {
                    "instrumento": "Consola americana con amplificadores operacionales discretos 2520 y ecualización proporcional.",
                    "interpretacion": "Resalta impacto frontal inmediato en baterías, guitarras eléctricas y bajos de rock.",
                    "procesamiento": "Transitorios veloces, medios-graves musculosos y pegada directa sin opacidad."
                },
            },
            {
                "id": "digital_transparent",
                "label": "Consola digital transparente.",
                "short_label": "Consola Digital Transparente",
                "reference_note": "Ruta digital de alta precisión sin coloración analógica añadida.",
                "core_tag": "transparent high-headroom clean digital console mix",
                "physical_instrument": "modern 32-bit ultra-clean transparent digital studio console with linear ultra-low-distortion preamps",
                "musical_performance": "faithfully translates subtle playing dynamics, delicate acoustic overtones and untouched room depth",
                "studio_processing": "noise-free pristine headroom, linear phase accuracy and uncolored modern studio definition",
                "summary_es": {
                    "instrumento": "Arquitectura digital moderna de ultra-baja distorsión y preamplificadores lineales.",
                    "interpretacion": "Preserva fielmente la dinámica original y los matices acústicos sin coloración extra.",
                    "procesamiento": "Transparencia cristalina, coherencia de fase y amplio rango dinámico limpio."
                },
            },
        ],
    },
    {
        "key": "microphones",
        "field_name": "studio_mic",
        "select_id": "selStudioMic",
        "title": "Micrófonos para cantar",
        "short_title": "Micrófono",
        "icon": "ph-microphone-stage",
        "emoji": "🎙️",
        "solo_mode": "vocals",
        "items": [
            {
                "id": "neumann_u87",
                "label": "Neumann U87.",
                "short_label": "Neumann U87 condensador",
                "reference_note": "Estándar vocal de estudio con cápsula grande FET y presencia equilibrada.",
                "core_tag": "Neumann U87 studio condenser vocal clarity",
                "physical_instrument": "classic dual-large-diaphragm FET condenser vocal microphone with transformer output and gentle presence rise",
                "musical_performance": "articulates subtle vocal breath, lyrical phrasing and clear expressive diction across dynamic ranges",
                "studio_processing": "balanced studio condenser vocal polish with gentle optical vocal leveling and airy clarity",
                "summary_es": {
                    "instrumento": "Condensador FET de gran diafragma doble con transformador y realce sutil de presencia.",
                    "interpretacion": "Capta respiración íntima, dicción clara y matices expresivos en todo rango vocal.",
                    "procesamiento": "Pulido clásico de estudio, compresión óptica suave y agudos aireados."
                },
            },
            {
                "id": "shure_sm7b",
                "label": "Shure SM7B.",
                "short_label": "Shure SM7B dinámico",
                "reference_note": "Dinámico de bobina móvil ideal para voces cercanas, firmes y modernas.",
                "core_tag": "warm punchy Shure SM7B dynamic intimate vocals",
                "physical_instrument": "broadcast-grade cardioid moving-coil dynamic vocal microphone with internal shock mount and pop shield",
                "musical_performance": "supports upfront intimate chesty delivery as well as powerful belted rock singing without harsh sibilance",
                "studio_processing": "focused midrange vocal density pushed by clean high-gain preamp and tight FET compression",
                "summary_es": {
                    "instrumento": "Micrófono dinámico cardioide de estudio con suspensión neumática y filtro antipop integrado.",
                    "interpretacion": "Ideal para voz íntima cercana o proyección intensa de rock sin sibilancia agresiva.",
                    "procesamiento": "Cuerpo sólido en medios, previo limpio de alta ganancia y compresión FET firme."
                },
            },
            {
                "id": "shure_sm58",
                "label": "Shure SM58.",
                "short_label": "Shure SM58 directo / vivo",
                "reference_note": "Micrófono dinámico clásico de escenario con corte en mezcla densa.",
                "core_tag": "upfront live-stage Shure SM58 dynamic vocals",
                "physical_instrument": "rugged cardioid dynamic vocal microphone with spherical mesh windscreen and classic 3-5 kHz presence peak",
                "musical_performance": "energetic live-stage vocal projection cutting directly through loud guitars and acoustic drums",
                "studio_processing": "raw punchy mid-forward live vocal energy with controlled low-end proximity warmth",
                "summary_es": {
                    "instrumento": "Dinámico cardioide de mano con rejilla esférica y pico natural de presencia (3–5 kHz).",
                    "interpretacion": "Proyección vocal directa y enérgica pensada para cortar sobre bandas potentes.",
                    "procesamiento": "Carácter vivo en medios frontales, calidez por proximidad y cero frialdad."
                },
            },
            {
                "id": "akg_c414",
                "label": "AKG C414.",
                "short_label": "AKG C414 abierto y aéreo",
                "reference_note": "Condensador versátil de respuesta transitoria rápida y extremo agudo brillante.",
                "core_tag": "open airy AKG C414 condenser vocal detail",
                "physical_instrument": "dual-brass-edge large-diaphragm condenser capsule with ultra-fast transient detail and extended airy highs",
                "musical_performance": "delivers shimmering acoustic intimacy, delicate head-voice extensions and crisp multi-voice vocal blends",
                "studio_processing": "open transparent top-end air, pristine studio transient detail and natural stereo room shimmer",
                "summary_es": {
                    "instrumento": "Condensador multipatrón con cápsula de latón y respuesta rápida a transitorios.",
                    "interpretacion": "Realza voz de cabeza, coros detallados e interpretaciones acústicas delicadas.",
                    "procesamiento": "Aire transparente en agudos superiores y detalle fino sin exageración en graves."
                },
            },
            {
                "id": "telefunken_u47",
                "label": "Telefunken U47.",
                "short_label": "Telefunken U47 a válvulas",
                "reference_note": "Clásico condensador de válvulas de gran cuerpo y autoridad vocal.",
                "core_tag": "vintage tube Telefunken U47 commanding warm vocals",
                "physical_instrument": "large-diaphragm vintage vacuum-tube condenser microphone with M7-style capsule and custom output transformer",
                "musical_performance": "commands rich three-dimensional vocal authority, deep baritone/tenor resonance and emotive warmth",
                "studio_processing": "lush vacuum-tube harmonic density, silky smooth upper mids and timeless vintage analog vocal depth",
                "summary_es": {
                    "instrumento": "Condensador clásico a válvulas con cápsula gran diafragma y transformador dedicado.",
                    "interpretacion": "Voz tridimensional de gran autoridad, cuerpo profundo en graves y calidez emotiva.",
                    "procesamiento": "Densidad armónica valvular, agudos sedosos y profundidad analógica clásica."
                },
            },
        ],
    },
]

_CATEGORIES_BY_KEY = {cat["key"]: cat for cat in STUDIO_VIRTUAL_CATEGORIES}
_ITEMS_BY_CAT_AND_ID = {
    cat["key"]: {item["id"]: item for item in cat["items"]}
    for cat in STUDIO_VIRTUAL_CATEGORIES
}


def get_studio_virtual_catalog_payload() -> dict:
    """Devuelve el catálogo completo serializable y extensible para UI y diagnóstico."""
    return {
        "version": "4.0-six-selectors",
        "default_option": {"id": STUDIO_DEFAULT_ID, "label": STUDIO_DEFAULT_LABEL},
        "udio_style_max_chars": UDIO_STYLE_MAX_CHARS,
        "honesty_notice": STUDIO_PROFILE_HONESTY_NOTICE,
        "compaction_strategy": [
            "1. Preservar género, métrica, BPM, tonalidad/acordes, ritmo y directivas vocales/instrumentales.",
            "2. Mantener todas las categorías seleccionadas (!= 'auto') priorizando batería > bajo > guitarra > teclado > voz/mic > consola.",
            "3. Si supera 1000 caracteres: recortar primero detalles de procesamiento de estudio de menor prioridad (Etapa 1).",
            "4. Si sigue superando 1000 caracteres: reducir interpretación/extensión a descriptor compacto core_tag (3-6 palabras) conservando TODAS las categorías elegidas (Etapa 2).",
            "5. Solo en saturación extrema de texto base del usuario registrar omisión explícita en metadatos/log, nunca silenciosa (Etapa 3)."
        ],
        "categories": STUDIO_VIRTUAL_CATEGORIES,
    }


def normalize_studio_selections(raw: Optional[dict]) -> dict:
    """Normaliza las 6 selecciones garantizando clave estable y default `'auto'`."""
    raw = raw or {}
    out = {}
    for cat in STUDIO_VIRTUAL_CATEGORIES:
        key = cat["key"]
        field_name = cat["field_name"]
        candidate = raw.get(key)
        if candidate is None:
            candidate = raw.get(field_name)
        val = str(candidate or STUDIO_DEFAULT_ID).strip()
        if not val or val.lower() == STUDIO_DEFAULT_ID:
            out[key] = STUDIO_DEFAULT_ID
        elif val in _ITEMS_BY_CAT_AND_ID[key]:
            out[key] = val
        else:
            out[key] = STUDIO_DEFAULT_ID
    return out


def has_active_studio_selections(selections: Optional[dict]) -> bool:
    norm = normalize_studio_selections(selections)
    return any(v != STUDIO_DEFAULT_ID for v in norm.values())


def get_studio_core_tags_preview(selections: Optional[dict], solo_mode: Optional[str] = None) -> list:
    """Devuelve los tags troncales de las categorías seleccionadas (compatible con detección de bajo real y synth)."""
    norm = normalize_studio_selections(selections)
    tags = []
    for cat in STUDIO_VIRTUAL_CATEGORIES:
        key = cat["key"]
        sel_id = norm[key]
        if sel_id == STUDIO_DEFAULT_ID:
            continue
        if solo_mode and cat.get("solo_mode") not in (solo_mode, "console"):
            continue
        item = _ITEMS_BY_CAT_AND_ID[key][sel_id]
        tags.append(item["core_tag"])
    return tags


def pack_studio_profiles_within_budget(
    selections: Optional[dict],
    available_budget: int,
    is_instrumental: bool = False,
    solo_mode: Optional[str] = None,
) -> dict:
    """
    Traduce las selecciones activas a cláusulas técnicas dentro de `available_budget` caracteres
    mediante reducción por capas (3 capas -> 2 capas -> 1 capa -> core_tag) para nunca eliminar
    silenciosamente ninguna selección del usuario salvo saturación física del texto base.
    """
    norm = normalize_studio_selections(selections)
    priority = STUDIO_CATEGORY_PRIORITY_INSTRUMENTAL if is_instrumental else STUDIO_CATEGORY_PRIORITY_VOCAL

    active_entries = []
    withheld_for_solo = []
    for key in priority:
        sel_id = norm.get(key, STUDIO_DEFAULT_ID)
        if sel_id == STUDIO_DEFAULT_ID:
            continue
        cat = _CATEGORIES_BY_KEY[key]
        item = _ITEMS_BY_CAT_AND_ID[key][sel_id]
        if solo_mode and cat.get("solo_mode") not in (solo_mode, "console"):
            withheld_for_solo.append(key)
            continue
        active_entries.append({
            "key": key,
            "id": sel_id,
            "label": item["label"],
            "short_label": item["short_label"],
            "physical": item["physical_instrument"],
            "performance": item["musical_performance"],
            "studio": item["studio_processing"],
            "core_tag": item["core_tag"],
            "is_synth_bass_capable": bool(item.get("is_synth_bass_capable", False)),
        })

    if not active_entries:
        return {
            "active_count": 0,
            "selections": norm,
            "clauses": [],
            "joined_text": "",
            "compaction_stage": "none_active",
            "reduced_categories": [],
            "preserved_categories": [],
            "omitted_categories": [],
            "withheld_for_solo": withheld_for_solo,
            "notice": None,
        }

    # Niveles por categoría:
    # 3 = [physical, performance, studio]
    # 2 = [physical, performance]
    # 1 = [physical]
    # 0 = [core_tag]
    # -1 = omitido por falta física extrema de presupuesto
    levels = {e["key"]: 3 for e in active_entries}

    def _render_clauses(lvl_map: dict) -> list:
        out = []
        for e in active_entries:
            lvl = lvl_map[e["key"]]
            if lvl == 3:
                out.extend([e["physical"], e["performance"], e["studio"]])
            elif lvl == 2:
                out.extend([e["physical"], e["performance"]])
            elif lvl == 1:
                out.append(e["physical"])
            elif lvl == 0:
                out.append(e["core_tag"])
        return out

    def _joined_len(clauses: list) -> int:
        return len(", ".join(clauses)) if clauses else 0

    budget = max(0, int(available_budget))
    clauses = _render_clauses(levels)
    stage = "full_3_layers"

    # Etapa 1: recortar capa de procesamiento de estudio (3 -> 2) empezando por menor prioridad
    if _joined_len(clauses) > budget:
        stage = "reduced_processing"
        for e in reversed(active_entries):
            if _joined_len(clauses) <= budget:
                break
            if levels[e["key"]] > 2:
                levels[e["key"]] = 2
                clauses = _render_clauses(levels)

    # Etapa 2a: recortar capa de interpretación (2 -> 1) empezando por menor prioridad
    if _joined_len(clauses) > budget:
        stage = "reduced_to_instrument_identity"
        for e in reversed(active_entries):
            if _joined_len(clauses) <= budget:
                break
            if levels[e["key"]] > 1:
                levels[e["key"]] = 1
                clauses = _render_clauses(levels)

    # Etapa 2b: compactar a core_tag (1 -> 0) empezando por menor prioridad, manteniendo TODAS las categorías
    if _joined_len(clauses) > budget:
        stage = "compact_preserves_all"
        for e in reversed(active_entries):
            if _joined_len(clauses) <= budget:
                break
            if levels[e["key"]] > 0:
                levels[e["key"]] = 0
                clauses = _render_clauses(levels)

    # Etapa 3: guardia de desbordamiento extremo con registro explícito (nunca silencioso)
    omitted = []
    if _joined_len(clauses) > budget:
        stage = "explicit_overflow"
        for e in reversed(active_entries):
            if _joined_len(clauses) <= budget:
                break
            levels[e["key"]] = -1
            omitted.append(e["key"])
            clauses = _render_clauses(levels)

    preserved = [e["key"] for e in active_entries if levels[e["key"]] >= 0]
    reduced = [e["key"] for e in active_entries if 0 <= levels[e["key"]] < 3]

    notice = None
    if withheld_for_solo:
        notice = f"Modo solo activo ({solo_mode}): categorías de banda incompatibles retenidas: {', '.join(withheld_for_solo)}."
    elif omitted:
        notice = f"Presupuesto máximo de {UDIO_STYLE_MAX_CHARS} caracteres agotado por prompt base: omitidas explícitamente {', '.join(omitted)}."
    elif reduced:
        notice = (
            f"Compactación prioritaria ({stage}): todas las categorías seleccionadas se conservaron "
            f"reduciendo detalle secundario en {', '.join(reduced)} para respetar {UDIO_STYLE_MAX_CHARS} caracteres."
        )

    joined = ", ".join(clauses)
    return {
        "active_count": len(active_entries),
        "selections": norm,
        "levels": levels,
        "clauses": clauses,
        "joined_text": joined,
        "compaction_stage": stage,
        "reduced_categories": reduced,
        "preserved_categories": preserved,
        "omitted_categories": omitted,
        "withheld_for_solo": withheld_for_solo,
        "notice": notice,
    }
