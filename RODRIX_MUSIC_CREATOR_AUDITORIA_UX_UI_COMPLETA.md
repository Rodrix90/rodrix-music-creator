# RODRIX MUSIC CREATOR — AUDITORÍA INTEGRAL DE INTERFAZ WEB Y EXPERIENCIA DE USUARIO (UX/UI)
**Documento Maestro de Arquitectura, Inventario de Controles, Experiencia de Creación y Hoja de Ruta de Evolución Profesional**

---

> [!NOTE]
> **Metodología y Alcance de la Auditoría**
> Este informe exhaustivo fue elaborado mediante una auditoría técnica y funcional de sólo lectura sobre el código fuente de producción de **Rodrix Music Creator** (versión 3.0):
> - **Frontend:** [`index.html`](file:///f:/Mis%20Documentos%20Disco%20R%C3%ADgido/Google%20Antigravity/Rodrix%20Music%20creator/index.html) (7.510 líneas, 399.021 caracteres).
> - **Backend Orquestador:** [`app.py`](file:///f:/Mis%20Documentos%20Disco%20R%C3%ADgido/Google%20Antigravity/Rodrix%20Music%20creator/app.py) (6.400 líneas, 338.837 caracteres).
> - **Motor de Instrumentos Gratuitos SF2:** [`free_instruments_engine.py`](file:///f:/Mis%20Documentos%20Disco%20R%C3%ADgido/Google%20Antigravity/Rodrix%20Music%20creator/free_instruments_engine.py) (2.237 líneas).
> - **Motor de DSP / Amplificadores Virtuales:** [`virtual_amp_engine.py`](file:///f:/Mis%20Documentos%20Disco%20R%C3%ADgido/Google%20Antigravity/Rodrix%20Music%20creator/virtual_amp_engine.py) (781 líneas).
> - **Entorno de Producción en Render:** `https://rodrix-music-creator.onrender.com`.
> 
> Todas las afirmaciones están categorizadas según provengan de: **[Código Frontend]**, **[Código Backend]**, **[Prueba Funcional Simulada]** o **[Inspección de API]**. No se consumieron créditos Udio/FAL ni se modificó ninguna base de datos o almacenamiento en Google Drive.

---

## 1. RESUMEN EJECUTIVO

**Rodrix Music Creator** es una plataforma SaaS web orientada a la producción, composición asistida y orquestación musical cristiana y broadcast pastoral. Integra dos paradigmas tecnológicos complementarios:
1. **Generación Generativa en la Nube (Vía UdioAPI Pro / Modelos Chirp v4.5 a v5.5):** Generación de composiciones completas con voz solista o coros a partir de prompts enriquecidos, tablatura de acordes y letras estructuradas.
2. **Estudio Virtual Gratuito Local / Servidor (FluidSynth + DSP Convolucional de Amplificadores a Válvulas):** Generación multitrack e instrumental instantánea con 21 bancos sampleados SF2 y modelado físico de 5 cabezales de amplificador y 10 gabinetes con respuestas al impulso (IR).
3. **Módulo Broadcast de Ministración Pastoral / Voz en Off:** Procesamiento broadcast de locuciones con profiles emulados de micrófonos profesionales (*Behringer TM1, Shure SM7B, Neumann U87*), channel strips (*iZotope VEA, Neve 1073, SSL 4000*) y ducking automático sobre lechos musicales.
4. **Persistencia Híbrida de Alta Disponibilidad:** Base de datos SQLite local para locks atómicos transaccionales con espejo y respaldo continuo en **Google Drive (5 TB)** mediante OAuth2 y tokens refrescables.

---

## 2. ARQUITECTURA FUNCIONAL Y MAPA DE NAVEGACIÓN

La aplicación funciona como una **Single Page Application (SPA)** responsiva estructurada en dos paneles maestros mediante CSS Grid (`.app { display: grid; grid-template-columns: 250px 1fr; }`):
- **Barra Lateral Fija Izquierda (`.sidebar` - 250px):** Navegación persistente, selector de vistas, enlaces utilitarios y sesión de usuario.
- **Área Central Dinámica (`.center`):** Contenedor con scroll vertical que renderiza exclusivamente una de las 5 vistas maestras a la vez mediante la función JavaScript `showView(viewId)`:

```
[ SIDEBAR ] ─────────────────────────────────────────┐
│ Logo Rodrix Music Creator                         │
│ Badge Estado Sistema (Online / Udio API / GDrive) │
│                                                   │
│ ├── 🎵 Crear Canción      ➔ #view-crear           │
│ ├── 🎹 Melodías & Himnos  ➔ #view-partituras      │
│ ├── 🎙️ Voz en Off        ➔ #view-vozenoff        │
│ ├── 📚 Mi Librería        ➔ #view-libreria        │
│ └── 👑 Control Usuarios   ➔ #view-usuarios        │
│                                                   │
│ [Descargar APK Android] ➔ /download-app           │
│ [Ajustes]               ➔ #profileModal           │
│ [Ayuda / Soporte]       ➔ Mailto Gmail            │
│ [Cerrar Sesión]         ➔ /api/logout             │
└───────────────────────────────────────────────────┘
```

---

## 3. INVENTARIO EXHAUSTIVO DE VISTAS Y PANTALLAS

### Vista 1: Panel de Creación Musical (`#view-crear`)
Es la pantalla neurálgica del producto. Se organiza de arriba hacia abajo en los siguientes bloques jerárquicos:

1. **Selector de Motor Musical (`#engineSelectorGrid`):**
   - **Opción A (IA Generativa Udio):** Permite generar voces humanas, coros y arreglos de banda completa con créditos.
   - **Opción B (Instrumentos Gratuitos FluidSynth):** 0 créditos, generación offline de 8, 16 o 32 compases con bancos SF2.
2. **Grilla de Presets Musicales de Estilo (Worship Cards):**
   - Tarjetas interactivas que preconfiguran estilo, tempo BPM, compás y exclusiones:
     - `pentecostal`: Alabanza Pentecostal tradicional (118 BPM, 4/4).
     - `adoracion`: Adoración Íntima y suave (68 BPM).
     - `himno`: Himno Solemne majestuoso (78 BPM).
     - `juvenil`: Alabanza Juvenil Pop/Rock (125 BPM).
     - `piano_oracion`: Solo Piano de Oración Instrumental (60 BPM, aislamiento estricto de piano solista).
     - `guitar_solo`: Solo de Guitarra Eléctrica Virtuoso (aislamiento de guitarra sola).
     - `vals_vienes`: Gran Vals Vienés en 3/4 estilo Strauss.
     - `reset`: Modo Libre / Personalizado.
3. **Selector Rápido de Compás y Métrica Rítmica (`.rhythm-pill`):**
   - `dos_pasos` (Alabanza 4/4 clásica).
   - `gospel_2step` (Ritmo 2-Step).
   - `worship_ballad` (Balada Adoración).
   - `waltz_34` (Vals 3/4).
   - `libre` (Modo Personalizado - admite 7/8, 5/4, 9/8, 11/8, 7/4 según prompt).
4. **Instrumentación de la Obra (Cajón Desplegable de 21 Instrumentos SF2):**
   - Cajón colapsable con chips visuales para activar/desactivar instrumentos y ajustar sliders de volumen individual (0% a 150%).
5. **Rack de Estudio & Equipamiento Pro (`#ampRackSection`):**
   - Pestaña Guitarra y Pestaña Bajo.
   - 5 Cabezales valvulares emulados con perillas de EQ (Gain, Bass, Middle, Treble, Presence, Master).
   - 10 Gabinetes con microfonía emulada por convolución.
   - Selector A/B (Wet con ampli vs Dry señal pura).
   - Botón de preescucha sonora con audio sintético en tiempo real.
6. **Entrada de Letra / Estructura Musical (`#lyricsInput`):**
   - Área de texto para estrofas `[Verse]`, coros `[Chorus]`, puentes `[Bridge]` y salidas `[Outro]`.
7. **Sincronización Armónica de Acordes / Tablatura (`#chordInput`):**
   - Parser automático de acordes cifrados que detecta tonalidad y progresiones armónicas.
8. **Consola y Botón de Generación Principal (`#generateBtn`):**
   - Barra de progreso porcentual, monitor de logs en tiempo real y botón de cancelación de tarea en vuelo.

---

### Vista 2: Melodías MIDI & Himnario Sacro (`#view-partituras`)
Diseñada para convertir partituras, tablaturas y archivos MIDI de himnos clásicos en orquestaciones completas:
- **Selector de Lote / Batch:** Procesamiento individual o por lote de colecciones de himnos.
- **Selector de Arreglo Orquestal Predeterminado:**
  - *Gran Orquesta Sinfónica Clásica* (Filarmónica de Viena).
  - *Órgano de Tubos de Templo & Coro Sacro*.
  - *Piano Acústico de Concierto & Cuerdas*.
  - *Banda Pentecostal en Vivo*.
- **Selector Vocal de Himno:** Coro congregacional al unísono, voz masculina, voz femenina o pista instrumental.
- **Área de Drag & Drop de Archivos MIDI / XML / PDF:** Carga de esqueletos rítmicos melódicos.

---

### Vista 3: Voz en Off & Ministración Pastoral (`#view-vozenoff`)
Estudio virtual de locución broadcast y producción de microprogramas radiales y podcasts devocionales:
- **Pestaña A: Grabación Directa desde el Micrófono (`#tabVoRecord`):**
  - Grabador HTML5 AudioContext con vúmetro visual en decibelios.
- **Pestaña B: Subida de Audio Pregrabado (`#tabVoUpload`):**
  - Admite MP3, WAV, M4A, OGG.
- **Rack de Emulación de Micrófonos:**
  - *Behringer TM1*, *Shure SM7B*, *Neumann U87*, *Micrófono Estándar*.
- **Rack de Preamplificadores / Interfaces:**
  - *Behringer U-Phoria UMC404HD (MIDAS)*, *Focusrite Scarlett 2i2*, *Entrada Directa*.
- **Cadena de Plugins Vocales (DSP):**
  - *iZotope VEA*, *Neve 1073 Channel Strip*, *SSL 4000 Vocal Strip*, *Lineal*.
- **Motor de Ducking Inteligente:** Atenúa automáticamente el volumen de la música instrumental de fondo cuando el pastor habla y la eleva en las pausas.

---

### Vista 4: Mi Librería Musical y Predicaciones (`#view-libreria`)
Centro de gestión, reproducción y exportación de todas las canciones generadas:
- **Filtro y Barra de Búsqueda de Pistas.**
- **Tarjetas de Canción (`.track`):**
  - Portada artística o thumbnail dinámico con vúmetro animado.
  - Título, estilo, duración, estado de sincronización Google Drive (Icono de Nube Verde).
  - Reproductor con Wavesurfer.js (forma de onda interactiva).
  - Menú de 3 puntos con acciones:
    - *Descargar MP3 original.*
    - *Descargar WAV HD.*
    - *Enriquecer con Instrumentos SF2 (Abre modal multipista).*
    - *Masterizar Pista (Selector de EQ y LUFS).*
    - *Eliminar Pista.*

---

### Vista 5: Control de Accesos y Usuarios (`#view-usuarios`)
Panel exclusivo para el Administrador (`rodryandy@gmail.com`):
- Tabla de usuarios autenticados con Google OAuth.
- Visualización de email, nombre, última conexión y canciones creadas.
- Acciones de gestión: Bloquear / Desbloquear acceso, otorgar rol VIP o restablecer permisos.

---

## 4. INVENTARIO COMPLETO DE CONTROLES VISIBLES

| ID del Control | Tipo | Ubicación | Valor Predeterminado | Función Conectada |
| :--- | :--- | :--- | :--- | :--- |
| `styleInput` | Textarea | Crear Canción | Estilo Worship | Prompt sonoro principal enviado al motor IA |
| `lyricsInput` | Textarea | Crear Canción | Letra estructurada | Letra con metatags `[Verse]`, `[Chorus]` |
| `chordInput` | Textarea | Crear Canción | Vacío | Parser de tablatura armónica |
| `titleInput` | Input Text | Crear Canción | Vacío | Título de la obra |
| `userBpmInput` | Input Number | Crear Canción | 120 (o según preset) | Tempo autoritativo del usuario (40 a 240) |
| `modelInput` | Select | Crear Canción | `chirp-v5` | Modelo generativo de UdioAPI |
| `weirdness` | Input Range | Opciones Avanzadas | 25 (0 a 100) | Restricción de rareza del modelo |
| `styleInfluence`| Input Range | Opciones Avanzadas | 50 (0 a 100) | Peso del estilo sobre la composición |
| `audioInfluence`| Input Range | Opciones Avanzadas | 25 (0 a 100) | Influencia de audio cargado como guía |
| `excludeInput` | Input Text | Opciones Avanzadas | Filtros anti-latin | Negative prompt / términos excluidos |
| `instrumental` | Checkbox | Crear Canción | Unchecked | Fuerza creación instrumental sin voces |
| `chkDrums` | Checkbox | Banda Activa | Checked | Inyecta batería acústica real |
| `chkBass` | Checkbox | Banda Activa | Checked | Inyecta bajo eléctrico real |
| `chkGuitar` | Checkbox | Banda Activa | Checked | Inyecta guitarra acústica / rítmica |
| `chkPiano` | Checkbox | Banda Activa | Unchecked | Inyecta piano de cola acústico |
| `chkOrgan` | Checkbox | Banda Activa | Unchecked | Inyecta órgano Hammond B3 |
| `chkNoLatin` | Checkbox | Filtros | Checked | Excluye cumbia, salsa, reggaetón |
| `chkCrashToms` | Checkbox | Articulaciones | Checked | Crashes en caídas y redobles en toms |
| `chkSplashRide`| Checkbox | Articulaciones | Unchecked | Acentos en Splash y campana de Ride |
| `chkTomGrooves`| Checkbox | Articulaciones | Unchecked | Base rítmica apoyada en Toms |
| `chkBassSlap` | Checkbox | Articulaciones | Unchecked | Técnica de bajo Slap & Pop |
| `chkBassPickup`| Checkbox | Articulaciones | Checked | Notas de paso y pick-ups en transiciones |
| `chkAutoApplyChords` | Checkbox | Armonía | Checked | Enlaza análisis armónico al prompt |
| `generateBtn` | Botón | Crear Canción | Habilitado | Despacha la solicitud a `/api/transform` |

---

## 5. CATÁLOGO DE INSTRUMENTOS SAMPLEADOS REALES (SF2)

En [`free_instruments_engine.py`](file:///f:/Mis%20Documentos%20Disco%20R%C3%ADgido/Google%20Antigravity/Rodrix%20Music%20creator/free_instruments_engine.py), el sistema incorpora 21 instrumentos sampleados libres de regalías:

```
┌────────────────────────┬────────────────────────────────────────────┬────────────────────────┐
│ ID Instrumento         │ Nombre Visible                             │ Familia Instrumental   │
├────────────────────────┼────────────────────────────────────────────┼────────────────────────┤
│ piano_cola             │ 1. Piano de Cola Acústico                  │ Teclados & Pianos      │
│ bajo_finger            │ 2. Bajo Eléctrico (Fingerstyle + Pick-up)  │ Bajos Eléctricos       │
│ bajo_slap              │ 2B. Bajo Eléctrico (Slap & Pop + Pick-up)  │ Bajos Eléctricos       │
│ bateria_acustica       │ 3. Batería Acústica (Hi-Hat, Toms, Crashes)│ Baterías & Percusión   │
│ organo                 │ 4. Órgano Tonewheel Hammond B3             │ Teclados & Pianos      │
│ piano_fm_dx            │ 5. Piano FM DX (Yamaha DX7 E.Piano 1)      │ Teclados & Pianos      │
│ piano_sintetizado      │ 6. Piano CP80 Electric Grand + Chorus      │ Teclados & Pianos      │
│ guitarra_acustica      │ 7. Guitarra Acústica Real (Cuerdas Bronce) │ Guitarras              │
│ guitarra_distorsionada │ 8. Guitarra Distorsionada (Overdrive Lead) │ Guitarras              │
│ guitarra_limpia        │ 9. Guitarra Eléctrica Limpia (Stratocaster)│ Guitarras              │
│ bateria_electronica    │ 10. Batería Electrónica TR-808 / TR-909    │ Baterías & Percusión   │
│ bongos                 │ 11. Bongós (Martillo & Repique - 31 RR)    │ Percusión Latina/Acúst.│
│ congas                 │ 12. Congas (Tumbao Marcha - 5 articulac.)  │ Percusión Latina/Acúst.│
│ cajon                  │ 13. Cajón Peruano / Flamenco (29 RR)       │ Percusión Latina/Acúst.│
│ maracas                │ 14. Maracas (Articulación Ida y Vuelta)    │ Percusión Menor        │
│ synth_bass             │ 15. Synth Bass (Yamaha TX81Z Lately Bass)  │ Sintetizadores         │
│ synth_lead             │ 16. Synth Lead (Saw Lead / Synth Fifths)   │ Sintetizadores         │
│ flautas                │ 17. Flauta Traversa & Flauta de Pan        │ Vientos & Cuerdas      │
│ synth_pad              │ 18. Synth Pad (Sweep Pad Atmosférico)      │ Sintetizadores         │
│ cuerdas                │ 19. Cuerdas Orquestales (Ensemble Violines)│ Vientos & Cuerdas      │
│ campanas               │ 20. Campanas Tubulares de Catedral         │ Baterías & Percusión   │
└────────────────────────┴────────────────────────────────────────────┴────────────────────────┘
```

---

## 6. AMPLIFICADORES VIRTUALES Y GABINETES (IR CONVOLUCIÓN)

En [`virtual_amp_engine.py`](file:///f:/Mis%20Documentos%20Disco%20R%C3%ADgido/Google%20Antigravity/Rodrix%20Music%20creator/virtual_amp_engine.py), el procesamiento de audio se realiza con filtros biquad de Robert Bristow-Johnson (RBJ) y convolución FFT mediante SciPy:

### Modelos de Amplificador:
1. **`marshall_jcm800` (Marshall JCM800 2203 - 100W Tube):** Ganancia británica crunch/lead con armónicos pares brillantes.
2. **`mesa_dual_rectifier` (Mesa/Boogie Dual Rectifier Solo Head):** Distorsión de alta ganancia estadounidense, graves profundos y medios comprimidos.
3. **`fender_twin_reverb` (Fender Twin Reverb '65 Blackface):** Sonido clean cristalino, campana aguda brillante y techo limpio ultra-amplio.
4. **`ampeg_svt` (Ampeg SVT Classic 300W All-Tube Bass):** Estándar de bajo rock/gospel con empuje valvular en graves y rugido medio.
5. **`markbass_little_mark` (Markbass Little Mark Vintage):** Preamp híbrido a válvulas con respuesta rápida, graves secos y definición moderna.

### Gabinetes y Microfonía con Respuesta al Impulso (IR):
- `cab_marshall_1960a`: 4x12 Celestion G12T-75 microfoneado con Shure SM57.
- `cab_mesa_recto_4x12`: 4x12 Celestion Vintage 30 con Shure SM57.
- `cab_fender_twin_2x12`: 2x12 Jensen C12K con Sennheiser MD421.
- `cab_vox_2x12`: 2x12 Celestion Alnico Blue con Shure SM57.
- `cab_ampeg_svt_810e`: 8x10 Custom Eminence "The Fridge" con AKG D112.
- `cab_markbass_4x10`: 4x10 Neodymium con tweeter y Neumann U47 FET.

---

## 7. EVALUACIÓN HEURÍSTICA UX/UI Y PROBLEMAS DETECTADOS

### Fortalezas Notables:
- **Respaldo Automático Robusto en la Nube:** Las canciones no quedan atrapadas en la máquina local; se sincronizan automáticamente con Google Drive con validación SHA-256.
- **Riqueza Sonora Única en el Nicho Sacro:** La inclusión de instrumentos sampleados reales de percusión menor (congas, bongós, cajón con round-robin) y pianos icónicos (Yamaha DX7, Roland MKS-20, CP80).
- **Procesamiento de Voz Broadcast:** La suite para pastores y locutores con ducking automático sobre música es una innovación sobresaliente para un software musical.

### Debilidades y Fricciones de Usabilidad:
1. **Sobrecarga Cognitiva en la Vista Principal:**
   - La pantalla `view-crear` contiene simultáneamente: selector de motor, presets, píldoras de ritmo, cajón de 21 instrumentos, rack de amplificadores con 6 perillas, entradas de letra, tablatura de acordes y opciones avanzadas. Un usuario novato puede sentirse intimidado por la densidad visual.
2. **Duplicidad Conceptual (IA vs. SF2):**
   - Aunque existe un selector de motor (`engineSelectorGrid`), los 21 instrumentos y los amplificadores virtuales están visibles tanto para el motor FluidSynth como para el motor de IA. En la IA actúan como inyectores de prompt textual; en FluidSynth actúan como pistas de audio reales. Esta distinción técnica debe explicarse con mayor claridad gráfica.
3. **Ausencia de Editor de Letras Asistido con Rimas y Silabeo:**
   - La caja de letras es un simple `<textarea>` sin conteo de sílabas métricas ni sugerencias rítmicas por compás.
4. **Reproductor de Biblioteca Básico:**
   - Si bien cuenta con Wavesurfer.js, carece de controles para hacer bucles (loops) de una sección específica (ej. practicar sólo el coro) o cambiar la velocidad de reproducción (pitch / time-stretching).

---

## 8. PLAN DE EVOLUCIÓN: LLEVANDO RODRIX MUSIC CREATOR A UN NIVEL PROFESIONAL SUPERIOR

### Nivel 1: Mejoras Rápidas de Usabilidad y Claridad Visual (Impacto Inmediato)
- **Flujo Guiado "Asistente vs. Experto":** Modalidad "Sencilla" (Preset + Letra + Crear) y Modalidad "Estudio Pro" (despliega los amplificadores, 21 pistas y parámetros de difusión).
- **Indicador Gráfico de Compás:** Badge visual animado que muestre visualmente la métrica elegida (ej. compás 7/8 iluminando círculos en patrón 2+2+3).
- **Tooltips Explicativos Interactivos:** Burbujas flotantes que aclaren qué hace cada perilla de amplificador y qué diferencia hay entre `chirp-v5` y `chirp-v4.5`.

### Nivel 2: Edición y Control Musical Intermedio
- **Editor de Letra con Métricas de Silabeo:** Resaltado de sintaxis para etiquetas `[Verse]`, `[Chorus]`, y aviso si un verso excede la longitud métrica ideal para el tempo seleccionado.
- **Preescucha Rápida de Instrumentos en el Cajón:** Botón de "Audición" (icono de parlante) en cada uno de los 21 instrumentos del cajón para escuchar una nota de muestra antes de agregarlo al arreglo.
- **Historial de Prompts y Versiones:** Posibilidad de restaurar con un clic el prompt exacto utilizado en una canción de la biblioteca.

### Nivel 3: Funcionalidades Avanzadas de Producción
- **Mini-DAW Multipista Web (Audio Worklet):**
  - Permitir mutear, solear y ajustar paneo estéreo (L/R) de las pistas instrumentales generadas con FluidSynth sobre la canción generada por Udio.
- **Stem Separation (Separación de Pistas con Demucs / Spleeter):**
  - Dividir cualquier canción generada en 4 stems independientes: Voz, Batería, Bajo y Otros instrumentos, permitiendo remezclar o hacer versiones pista/karaoke para iglesias.

### Nivel 4: Estudio Musical Integral en el Navegador
- **Editor MIDI Roll en Pantalla:** Piano roll interactivo en la pestaña de Melodías & Himnos para corregir notas o melodías antes de renderizarlas con los instrumentos SF2.
- **Exportación a Formatos Profesionales:** Exportación en paquetes ZIP organizados para importar en Pro Tools, Reaper, Cubase o Ableton Live (archivos WAV 24-bit 48kHz sincronizados con BPM).

---

## 9. CONCLUSIONES DE LA AUDITORÍA

Rodrix Music Creator es un sistema maduro, seguro y tecnológicamente ambicioso que combina exitosamente inteligencia artificial generativa de vanguardia con síntesis local determinista sin costo. 

La base de código en FastAPI y JavaScript puro es sólida, resiliente a caídas y cuenta con mecanismos de recuperación transaccional ejemplares. La oportunidad dorada del proyecto reside en **despejar la fricción visual del frontend**, transformando una interfaz densa de ingeniería en una experiencia fluida e intuitiva de estudio de grabación profesional.
