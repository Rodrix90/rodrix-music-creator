# RODRIX MUSIC CREATOR 4.0 — AUDITORÍA TÉCNICA Y PLAN DE INTEGRACIÓN OBLIGATORIA DE ANDROID
**Arquitectura Híbrida WebView, Rediseño Táctil de las 5 Pantallas, Reproductor Global Persistente y Hoja de Ruta de Evolución Móvil**

---

> [!IMPORTANT]
> **Estado de la Tarea: Fase Exclusiva de Análisis, Diseño y Prototipado**
> En cumplimiento estricto con las directivas del usuario:
> - **NO** se modificó el código fuente de Android ni de la web.
> - **NO** se compiló ni generó ningún APK o AAB nuevo.
> - **NO** se alteraron el `applicationId`, firmas digitales ni certificados keystore.
> - **NO** se realizaron commits, push ni deploy a Render o GitHub.
> - **NO** se consumieron créditos de Udio/FAL.

---

## 1. AUDITORÍA TÉCNICA EXHAUSTIVA DE LA APLICACIÓN ANDROID EXISTENTE

Se realizó una inspección estática del repositorio local de Android ubicado en:
`F:\Mis Documentos Disco Rígido\Google Antigravity\rodrix-android`

### 1.1. Resumen de la Ficha Técnica

| Parámetro | Configuración Real Verificada en Código |
| :--- | :--- |
| **Tecnología del Cliente** | **Native Android Wrapper (Java) con WebView de Alto Rendimiento** (`android.webkit.WebView`). No utiliza Cordova, Capacitor ni Flutter. |
| **Ubicación del Código Fuente** | `F:\Mis Documentos Disco Rígido\Google Antigravity\rodrix-android\app\src\main\java\com\rodrix\musiccreator\MainActivity.java` |
| **Package Name (`applicationId`)**| `com.rodrix.musiccreator` |
| **Configuración SDK** | `compileSdk 35`, `targetSdk 35`, `minSdk 24` (Android 7.0 Nougat hasta Android 15). |
| **Versión Actual** | `versionCode 1`, `versionName "1.0.0"`. |
| **Herramienta de Compilación** | Gradle con plugin `com.android.application`, Java 17 (`JavaVersion.VERSION_17`). |
| **Dependencias Nativas** | `androidx.appcompat:appcompat:1.7.0`, `com.google.android.material:material:1.12.0`, `androidx.webkit:webkit:1.11.0`, `androidx.swiperefreshlayout:swiperefreshlayout:1.1.0`. |
| **URL Remota Vinculada** | `https://rodrix-music-creator.onrender.com` (Carga remota directa en tiempo real). |
| **APK de Producción Compilado**| Ubicado en la raíz del servidor: `F:\Mis Documentos Disco Rígido\Google Antigravity\Rodrix Music creator\Rodrix_Music_Creator.apk`, descargable vía endpoint `/download-app`. |

---

### 1.2. Permisos y Manifiesto (`AndroidManifest.xml`)

La aplicación declara 7 permisos en su manifiesto:
1. `android.permission.INTERNET`: Comunicación con la API de FastAPI en Render.
2. `android.permission.ACCESS_NETWORK_STATE`: Monitoreo de conectividad.
3. `android.permission.READ_EXTERNAL_STORAGE` (`maxSdkVersion="32"`): Compatibilidad con dispositivos legados.
4. `android.permission.READ_MEDIA_AUDIO`: Acceso a pistas de audio locales en Android 13+ (API 33+).
5. `android.permission.READ_MEDIA_VIDEO`: Carga de videos/contenidos multimedia.
6. `android.permission.RECORD_AUDIO`: Grabación en vivo para el módulo de Voz en Off / Ministración Pastoral.
7. `android.permission.MODIFY_AUDIO_SETTINGS`: Ajuste de volúmenes y rutas de hardware.

---

### 1.3. Mecanismos de Autenticación (Google OAuth) y Persistencia (Google Drive)

- **El Desafío de Google OAuth en Android WebViews:**
  Google bloquea por política de seguridad el inicio de sesión OAuth dentro de WebViews genéricos (`disallowed_useragent`).
- **Solución Implementada en `MainActivity.java` (Línea 133):**
  La app implementa una suplantación de User-Agent oficial de Chrome para Android:
  ```java
  String customUA = "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36";
  settings.setUserAgentString(customUA);
  ```
  Esto permite que el flujo de login con Google (`accounts.google.com` y `google.com/o/oauth2`) se ejecute sin trabas dentro de la propia aplicación móvil, sin expulsar al usuario al navegador externo.
- **Cookies y Sesión:**
  `CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)` garantiza la persistencia de la cookie de sesión cifrada de FastAPI, manteniendo al usuario conectado indefinidamente.
- **Google Drive (5 TB):**
  La integración con Google Drive opera a nivel de backend mediante el refresh token corporativo almacenado en el servidor Render. La app Android no manipula credenciales directas de Drive, protegiendo los secretos de la nube.

---

### 1.4. Puente JavaScript Nativo (`JavascriptInterface`) y Compartir en Redes

La aplicación expone un puente bidireccional nativo (`AndroidApp`):
- **Método:** `AndroidApp.shareAudiosJson(String jsonUrls, String jsonTitles)`.
- **Funcionamiento:** Descarga en segundo plano las pistas seleccionadas en la caché temporal del dispositivo (`cacheDir/shared_audio`), genera URIs seguras mediante `FileProvider` (`com.rodrix.musiccreator.fileprovider`) y abre el diálogo nativo de Android (`Intent.ACTION_SEND_MULTIPLE`) para compartir canciones de forma masiva directamente a **WhatsApp, Telegram, Gmail o Drive** sin que el usuario tenga que lidiar con descargas manuales.

---

### 1.5. Relación entre la App Android y el Frontend Web

> [!CAUTION]
> **Principio de Sincronización Web-App:**
> La aplicación Android es un contenedor que carga en vivo `https://rodrix-music-creator.onrender.com`.
> **Ventaja:** Cualquier mejora de responsive design, estilos CSS, nuevos instrumentos SF2 o lógica de audio implementada en `index.html` se refleja **inmediatamente** en todos los teléfonos Android instalados sin obligar a los usuarios a reinstalar el APK.
> **Limitación:** El minirreproductor actual reside dentro del DOM de `view-libreria`. Al cambiar de vista, el reproductor desaparece. Para lograr persistencia global en Android se requiere elevar el reproductor al nivel raíz del DOM y orquestar el ciclo de vida con la barra de navegación inferior.

---

## 2. REDISEÑO DE LAS CINCO PANTALLAS MÓVILES (STUDIO PRO DARK MOBILE)

La interfaz móvil debe abandonar el aspecto de "escritorio encogido" y adoptar una ergonomía táctil con **Touch Targets mínimos de 48x48 dp**, espaciado adaptado a pulgares y menús colapsables.

```
┌──────────────────────────────────────────────┐
│  RODRIX MUSIC CREATOR 4.0 (Mobile Viewport)  │
├──────────────────────────────────────────────┤
│  [Top Bar]  Logo  •  Badge Online  •  Perfil │
├──────────────────────────────────────────────┤
│                                              │
│               CONTENIDO VISTA                │
│                                              │
│  - Tarjetas con paddings amplios (16px)      │
│  - Selectores tipo Bottom Sheet              │
│  - Perillas táctiles con control vertical    │
│  - Sliders táctiles con mayor zona de agarre │
│                                              │
├──────────────────────────────────────────────┤
│  [MINIRREPRODUCTOR GLOBAL PERSISTENTE]       │
│  ▶  Canción actual (2:45)       ⏮  ⏸  ⏭   │
├──────────────────────────────────────────────┤
│  [BARRA DE NAVEGACIÓN INFERIOR (5 TABS)]     │
│    🎵       🎹        🎙️       📚       👑   │
│  Crear   Melodías   Voz/Off   Librería  Admin│
└──────────────────────────────────────────────┘
```

---

### Pantalla 1: Crear Canción (`view-crear` móvil)
- **Selector de Motor IA vs SF2:** En lugar de dos tarjetas anchas en columnas, se transforma en un **Selector Segmentado Horizontal (Toggle Tabs)** en la parte superior con iconos claros:
  `[ 🤖 IA Generativa (Udio) ] | [ 🎻 0 Créditos (FluidSynth) ]`
- **Carrusel Horizontal de Presets:** Los 8 presets de estilo (`Pentecostal`, `Adoración`, `Himno`, `Juvenil`, `Piano Oración`, `Solo Guitarra`, `Vals`) se disponen en un carrusel táctil horizontal deslizable con snap alignment.
- **Acordeones Colapsables (Accordion Panels):**
  - *Panel 1:* Letra y Estructura Musical (`[Verse]`, `[Chorus]`).
  - *Panel 2:* Tablatura y Progresión de Acordes.
  - *Panel 3:* Cajón de 21 Instrumentos Sampleados (abre como una **Bottom Sheet** deslizable desde abajo).
  - *Panel 4:* Rack de Amplificadores (Pestañas Guitarra/Bajo con perillas giratorias táctiles optimizadas).
- **Botón de Generación Flotante o Fijo (Bottom Sticky Bar):** Botón `[ ⚡ CREAR CANCIÓN ]` visible en todo momento.

---

### Pantalla 2: Melodías e Himnos (`view-partituras` móvil)
- **Flujo en 3 Pasos Clave:**
  1. *Cargar Partitura / MIDI:* Área táctil amplia para seleccionar archivo desde el almacenamiento del móvil o Google Drive.
  2. *Elegir Arreglo Orquestal:* Dropdown nativo con previsualización del ensamble (ej. *Gran Filarmónica*, *Órgano de Catedral*).
  3. *Procesar:* Barra de progreso con porcentajes claros y cancelación instantánea.

---

### Pantalla 3: Voz en Off & Ministración Pastoral (`view-vozenoff` móvil)
- **Modo Grabador de Campo:**
  - Gran botón central circular de grabación `[ 🔴 GRABAR VOZ ]` con animación de pulsación.
  - Vúmetro en tiempo real optimizado para GPU mediante canvas ligero.
  - Temporizador visible en fuente monoespaciada grande (`00:45 / 05:00`).
- **Carrusel de Micrófonos:** Tarjetas táctiles tipo swipe para alternar entre *Behringer TM1*, *Shure SM7B* y *Neumann U87*.
- **Control de Música de Fondo:** Slider táctil para graduar la música ministerial con switch de ducking automático.

---

### Pantalla 4: Mi Librería (`view-libreria` móvil)
- **Lista Vertical de Tarjetas Táctiles:**
  - Thumbnail artístico a la izquierda (60x60 dp).
  - Título en negrita, estilo, duración y badge verde de Google Drive.
  - Botón Play flotante táctil sobre el thumbnail.
  - Botón de 3 puntos `[...]` que abre una **Bottom Sheet de Acciones**:
    - *Compartir en WhatsApp / Telegram (vía puente nativo `AndroidApp`).*
    - *Descargar MP3 al almacenamiento del teléfono.*
    - *Enriquecer con Instrumentos SF2.*
    - *Masterizar Pista.*
    - *Eliminar Pista.*

---

### Pantalla 5: Control de Usuarios (`view-usuarios` móvil - Sólo Admin)
- Se activa en la barra inferior exclusivamente para `rodryandy@gmail.com`.
- En lugar de una tabla HTML ancha con scroll horizontal incómodo, se presentan **Tarjetas de Usuario Individuales**:
  - Avatar, nombre y email.
  - Rol (Badge VIP / Usuario).
  - Switch de activación/bloqueo accesible con un toque.

---

## 3. ARQUITECTURA DEL REPRODUCTOR GLOBAL ANDROID

Actualmente, el reproductor `#player` está anclado en la vista de biblioteca (`#view-libreria`). Si el usuario inicia la reproducción de una alabanza y toca la pestaña "Crear" o "Voz en Off", la música se interrumpe o la interfaz del reproductor desaparece.

### 3.1. Especificación del Minirreproductor Persistente

```
┌────────────────────────────────────────────────────────┐
│ [MiniPlayer] 🎵 Canto al Señor (107 BPM)     ⏮  ⏸  ⏭  ▲ │
├────────────────────────────────────────────────────────┤
│ Barra de Progreso de 2px (Se llena con el audio)      │
├────────────────────────────────────────────────────────┤
│ [Bottom Nav]  Crear • Melodías • Voz/Off • Librería    │
└────────────────────────────────────────────────────────┘
```

1. **Ubicación en el DOM:** Debe ubicarse como hijo directo de `<body>` o `.app`, **fuera** de los contenedores `#view-*`.
2. **Posicionamiento CSS:**
   ```css
   .global-mini-player {
     position: fixed;
     bottom: 60px; /* Justo arriba de la barra de navegación móvil (bnav) */
     left: 0; right: 0;
     height: 56px;
     background: rgba(28, 28, 44, 0.95);
     backdrop-filter: blur(12px);
     border-top: 1px solid var(--border);
     display: none; /* Se activa con .show al pulsar play en cualquier tarjeta */
     z-index: 990;
   }
   ```
3. **Controles del Minirreproductor:**
   - Carátula en miniatura (40x40 px).
   - Título con scroll automático si excede el ancho (marquee).
   - Botón Play/Pausa táctil.
   - Botón de pista siguiente y anterior.
   - Botón `[▲]` para expandir a pantalla completa (Full Screen Player) con forma de onda de Wavesurfer.js y letra sincronizada.

---

### 3.2. Reproducción en Segundo Plano y Controles del Sistema Android

Para que la música no se corte al apagar la pantalla o minimizar la app, se evaluaron dos alternativas:

| Enfoque | Viabilidad | Políticas de Play Store | Complejidad |
| :--- | :--- | :--- | :--- |
| **A. HTML5 Media Session API (Frontend Web)** | **Inmediata (100% compatible)**. El estándar `navigator.mediaSession` permite que el navegador/WebView transmita título, artista, carátula y botones de control a la pantalla de bloqueo y barra de notificaciones de Android. | Permitido sin permisos especiales. | Baja (cero cambios en Gradle). |
| **B. Foreground Service Nativo con ExoPlayer (Java)** | Requiere permiso `FOREGROUND_SERVICE_MEDIA_PLAYBACK` en el manifest y un servicio nativo que reciba la URL del audio vía JavaScript. | Exige justificación rigurosa en Google Play Console. | Media-Alta. |

**Recomendación Arquitectural:**
Implementar como fase inmediata la **Media Session API** en JavaScript (proporciona control desde la pantalla de bloqueo, auriculares y Bluetooth de forma transparente). En una fase posterior, si se requiere reproducción offline sin conexión, migrar a un servicio nativo con ExoPlayer / Media3.

---

## 4. MATRIZ DE COMPATIBILIDAD WEB VS. ANDROID

| Módulo / Capacidad | Versión Web Escritorio | App Android 1.0 (Actual) | App Android 4.0 (Rediseño) |
| :--- | :---: | :---: | :---: |
| **Generación IA (Udio Chirp)** | Completa | Completa (vía WebView) | Completa con UI táctil |
| **Compases Irregulares (7/8, 9/8, 11/8)** | Completa | Completa (heredada de la API) | Completa con badges rítmicos |
| **Instrumentos SF2 (FluidSynth)** | 21 instrumentos | Funciona (genera MP3/WAV) | Cajón Bottom Sheet adaptado |
| **Amplificadores Virtuales (IR)** | 5 Amps / 10 Cabs | Funciona (audición web) | Perillas rotativas táctiles |
| **Google OAuth** | Popup / Redirect | Emulación Chrome UA nativa | Preservado intacto |
| **Google Drive (5 TB Backup)** | Automático (Backend) | Automático (Backend) | Preservado intacto |
| **Compartir Audios** | Descarga manual | Diálogo nativo WhatsApp/Telegram | Diálogo nativo optimizado |
| **Grabación de Voz en Off** | API Web AudioContext | Requiere permiso RECORD_AUDIO | Modo de campo táctil |
| **Reproductor Global Persistente** | Anclado en Librería | Anclado en Librería | **Minirreproductor flotante universal** |
| **Controles en Pantalla Bloqueada** | Soporte según navegador | No configurado | **Soporte MediaSession API** |

---

## 5. PROCEDIMIENTO DE COMPILACIÓN, FIRMA Y DISTRIBUCIÓN

1. **Entorno de Compilación:**
   - Android SDK Build-Tools 35.0.0.
   - Gradle Wrapper (`./gradlew assembleRelease` o `bundleRelease`).
2. **Firma Digital (Keystore):**
   - Mantener el alias y keystore de producción existentes para evitar conflictos de actualización en los teléfonos ya instalados.
3. **Distribución Dual:**
   - **Canal Directo (APK Oficial):** Alojado en el backend Render y descargable directamente desde la barra lateral (`/download-app`).
   - **Google Play Store (AAB):** Generación de Android App Bundle listo para subir a la consola de desarrollador de Google Play.

---

## 6. PLAN DE PRUEBAS EN DISPOSITIVOS ANDROID REALES

Para validar la experiencia táctil antes de cualquier despliegue:
1. **Prueba de Autenticación:** Verificar inicio de sesión con Google en Android 11, 13 y 15 descartando errores `disallowed_useragent`.
2. **Prueba de Minirreproductor Global:** Iniciar una pista en Librería, cambiar a Crear Canción, verificar que el audio continúa sin interrupción y que el widget responde a Play/Pausa.
3. **Prueba de Interrupciones de Audio:** Simular llamada entrante o conexión/desconexión de auriculares Bluetooth (verificar pausa automática y reanudación).
4. **Prueba de Compartir Nativo:** Seleccionar 3 canciones en la biblioteca móvil y disparar el diálogo para comprobar la entrega de los archivos MP3 en WhatsApp.
5. **Prueba de Grabación de Voz:** Comprobar captura limpia con el micrófono del móvil en la pestaña Voz en Off.

---

## 7. CONCLUSIÓN Y PRÓXIMOS PASOS

La aplicación Android actual cuenta con una base sólida gracias a su wrapper nativo con aceleración por hardware y su puente de integración para WhatsApp. La clave para elevar **Rodrix Music Creator 4.0** a un estándar profesional de clase mundial consiste en **transformar la interfaz web servida en una experiencia de usuario genuinamente móvil**, incorporando el **Minirreproductor Global Persistente** y **Bottom Sheets táctiles** para los 21 instrumentos y los amplificadores valvulares.

*Este informe se encuentra disponible para revisión. No se ha aplicado ningún cambio en código ni generado APKs hasta contar con tu autorización expresa.*
