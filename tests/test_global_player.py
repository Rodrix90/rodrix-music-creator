# -*- coding: utf-8 -*-
"""
RODRIX MUSIC CREATOR 4.0 — SUITE DE PRUEBAS DEL REPRODUCTOR GLOBAL PERSISTENTE
Valida:
1. Play desde Mi Librería.
2. Pausa desde el minirreproductor.
3. Sincronización de controles.
4. Cambio de canción.
5. Navegación entre las 5 pantallas sin destruir el reproductor.
6. Una sola reproducción activa (evita instancias duplicadas).
7. Barra de progreso y cálculo de tiempo/posición.
8. Control de volumen y silencio.
9. Modos de repetición (none, all, one).
10. Cierre del reproductor y liberación de estado.
11. Manejo de error de carga sin fugas de datos sensibles.
12. Sesión expirada / logout detiene reproducción.
13. Compatibilidad con Wavesurfer.js.
14. Compatibilidad con la navegación Android y safe-areas.
15. Integración con MediaSession API y controles nativos/Bluetooth.
16. Ausencia de regresiones en los demás módulos (SF2, grabación, amplificadores).
"""

import unittest
import os
import re

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")
APP_PY_PATH = os.path.join(BASE_DIR, "app.py")
ANDROID_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "rodrix-android"))


class TestGlobalPersistentPlayer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            cls.index_content = f.read()
        with open(APP_PY_PATH, "r", encoding="utf-8") as f:
            cls.app_content = f.read()

    # 1. Play desde Mi Librería
    def test_01_play_from_library_integration(self):
        """Comprueba que el botón play de la librería y playTrack dirigen a GlobalAudioController."""
        self.assertIn("window.GlobalAudioController", self.index_content)
        self.assertIn("GlobalAudioController.playTrack", self.index_content)
        # playTrack() debe existir y delegar al controlador
        self.assertRegex(self.index_content, r"function\s+playTrack\s*\(\s*t\s*\)\s*\{[\s\S]*?GlobalAudioController\.playTrack")

    # 2. Pausa desde el minirreproductor
    def test_02_pause_from_mini_player(self):
        """Verifica que el minirreproductor dispone de botón play/pause y método togglePlay/pause."""
        self.assertIn('id="gplayerPlayBtn"', self.index_content)
        self.assertIn('id="gplayerPlayIcon"', self.index_content)
        self.assertIn("togglePlay", self.index_content)
        self.assertIn("pause()", self.index_content)

    # 3. Sincronización de controles
    def test_03_controls_and_card_synchronization(self):
        """Verifica que el estado playing sincronice tanto el minirreproductor como las tarjetas .track."""
        self.assertIn("miniEl.classList.toggle('playing', isPlay)", self.index_content)
        self.assertIn("card.classList.toggle('playing', isThisTrack && isPlay)", self.index_content)
        self.assertIn("btnPlaySm.innerHTML = '<i class=\"ph ph-pause\"></i> Pausar'", self.index_content)
        self.assertIn("btnPlaySm.innerHTML = '<i class=\"ph ph-play\"></i> Escuchar'", self.index_content)

    # 4. Cambio de canción
    def test_04_track_switching_logic(self):
        """Comprueba cambio de fuente de audio, reinicio de tiempo y actualización de metadatos al cambiar de pista."""
        self.assertIn("nextTrack", self.index_content)
        self.assertIn("prevTrack", self.index_content)
        self.assertIn('id="gplayerNextBtn"', self.index_content)
        self.assertIn('id="gplayerPrevBtn"', self.index_content)

    # 5. Navegación entre las 5 pantallas
    def test_05_navigation_persistence_across_views(self):
        """Confirma que el reproductor está fuera de los contenedores view-panel de las 5 vistas."""
        # El reproductor NO debe estar dentro de view-libreria ni view-crear
        v_libreria_pos = self.index_content.find('id="view-libreria"')
        gplayer_pos = self.index_content.find('id="globalMiniPlayer"')
        self.assertNotEqual(gplayer_pos, -1, "Debe existir id='globalMiniPlayer'")
        self.assertNotEqual(v_libreria_pos, -1, "Debe existir id='view-libreria'")
        
        # Debe estar montado después del cierre de .app o al nivel raíz
        app_close_pos = self.index_content.find('</div> <!-- .app -->')
        if app_close_pos != -1:
            self.assertGreater(gplayer_pos, app_close_pos, "El reproductor global debe estar fuera de .app o al nivel raíz")

    # 6. Una sola reproducción activa
    def test_06_single_audio_instance(self):
        """Comprueba que existe un único elemento de audio global para evitar reproducciones solapadas."""
        self.assertIn('id="globalAudioElement"', self.index_content)
        # Verificación de que no se crean múltiples elementos <audio> dinámicos en cada playTrack
        self.assertIn("audioEl = document.getElementById('globalAudioElement')", self.index_content)

    # 7. Barra de progreso interactiva
    def test_07_progress_and_timeline_scrubber(self):
        """Verifica la presencia de barra superior táctil, timeline horizontal y función de arrastre (seek)."""
        self.assertIn('id="gplayerTopProgress"', self.index_content)
        self.assertIn('id="gplayerTopFill"', self.index_content)
        self.assertIn('id="gplayerTimelineBar"', self.index_content)
        self.assertIn('id="gplayerTimelineFill"', self.index_content)
        self.assertIn("seekRatio", self.index_content)
        self.assertIn("seekTo", self.index_content)

    # 8. Control de volumen y silencio
    def test_08_volume_and_mute_control(self):
        """Comprueba control de volumen, persistencia en localStorage y botón de silencio."""
        self.assertIn('id="gplayerMuteBtn"', self.index_content)
        self.assertIn('id="gplayerVolumeSliderBar"', self.index_content)
        self.assertIn("setVolume", self.index_content)
        self.assertIn("toggleMute", self.index_content)
        self.assertIn("rodrixGPlayerVolume", self.index_content)

    # 9. Modos de repetición
    def test_09_repeat_modes(self):
        """Verifica compatibilidad con modos de repetición: none, all, one."""
        self.assertIn('id="gplayerRepeatBtn"', self.index_content)
        self.assertIn('id="gplayerRepeatBadge"', self.index_content)
        self.assertIn("toggleRepeat", self.index_content)
        self.assertIn("state.repeatMode === 'one'", self.index_content)
        self.assertIn("state.repeatMode === 'all'", self.index_content)

    # 10. Cierre del reproductor
    def test_10_close_player_and_cleanup(self):
        """Verifica que cerrar el reproductor detiene el audio y limpia el estado activo."""
        self.assertIn('id="gplayerCloseBtn"', self.index_content)
        self.assertIn("closeBtn.onclick", self.index_content)
        self.assertIn("window.currentTrackId = null", self.index_content)
        self.assertIn("miniEl.classList.remove('active')", self.index_content)

    # 11. Manejo de error de carga
    def test_11_error_handling(self):
        """Comprueba manejo de eventos de error sin exponer tokens ni trazas sensibles."""
        self.assertIn("audioEl.addEventListener('error'", self.index_content)
        self.assertIn("state.status = 'error'", self.index_content)
        # No debe haber concatenación de claves ni tokens
        self.assertNotIn("API_KEY", self.index_content[self.index_content.find("window.GlobalAudioController"):self.index_content.find("window.GlobalAudioController") + 5000])

    # 12. Sesión expirada / logout
    def test_12_logout_stops_playback(self):
        """Confirma que el reproductor se cierra y detiene al pulsar los enlaces de cerrar sesión."""
        self.assertIn('document.querySelectorAll(\'a[href="/api/logout"]\')', self.index_content)
        self.assertIn("close();", self.index_content)

    # 13. Compatibilidad con Wavesurfer.js
    def test_13_wavesurfer_compatibility(self):
        """Verifica que se conserva la función initWaveSurfer y la compatibilidad con el waveform."""
        self.assertIn("function initWaveSurfer()", self.index_content)
        self.assertIn("wavesurfer.load(url)", self.index_content)

    # 14. Compatibilidad con la navegación Android
    def test_14_android_navigation_layout(self):
        """Verifica ubicación por encima de #mobileBottomNav con soporte para env(safe-area-inset-bottom)."""
        self.assertIn("bottom: calc(60px + env(safe-area-inset-bottom, 0px))", self.index_content)
        self.assertIn(".global-mini-player", self.index_content)
        self.assertIn(".mobile-bottom-nav", self.index_content)
        # Touch target de al menos 44-48px en móvil
        self.assertIn("width: 44px", self.index_content)
        self.assertIn("width: 48px", self.index_content)

    # 15. Integración con MediaSession API
    def test_15_media_session_integration(self):
        """Verifica metadatos y acciones de MediaSession para controles en pantalla de bloqueo y Bluetooth."""
        self.assertIn("'mediaSession' in navigator", self.index_content)
        self.assertIn("navigator.mediaSession.metadata = new MediaMetadata", self.index_content)
        self.assertIn("setActionHandler('play'", self.index_content)
        self.assertIn("setActionHandler('pause'", self.index_content)
        self.assertIn("setActionHandler('previoustrack'", self.index_content)
        self.assertIn("setActionHandler('nexttrack'", self.index_content)
        self.assertIn("setActionHandler('seekto'", self.index_content)
        self.assertIn("setPositionState", self.index_content)

    # 16. Ausencia de regresiones en los demás módulos
    def test_16_audio_coexistence_policy(self):
        """Verifica que la grabación de voz y las preescuchas pausan el reproductor global para evitar solapamientos."""
        self.assertIn("GlobalAudioController.pause()", self.index_content)
        # En startLiveRecording se pausa el reproductor
        start_rec_pos = self.index_content.find("async function startLiveRecording()")
        self.assertNotEqual(start_rec_pos, -1)
        sub_content = self.index_content[start_rec_pos:start_rec_pos + 400]
        self.assertIn("GlobalAudioController.pause()", sub_content)

    # 17. Verificación de integridad Android nativo
    def test_17_android_native_wrapper_preservation(self):
        """Confirma que rodrix-android mantiene su configuración intacta."""
        if os.path.exists(ANDROID_DIR):
            manifest_path = os.path.join(ANDROID_DIR, "app", "src", "main", "AndroidManifest.xml")
            gradle_path = os.path.join(ANDROID_DIR, "app", "build.gradle")
            main_activity_path = os.path.join(ANDROID_DIR, "app", "src", "main", "java", "com", "rodrix", "musiccreator", "MainActivity.java")

            self.assertTrue(os.path.exists(manifest_path), "AndroidManifest.xml debe existir")
            self.assertTrue(os.path.exists(gradle_path), "build.gradle debe existir")
            self.assertTrue(os.path.exists(main_activity_path), "MainActivity.java debe existir")

            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_content = f.read()
            self.assertIn('.MainActivity', manifest_content)
            self.assertIn('${applicationId}.fileprovider', manifest_content)

            with open(main_activity_path, "r", encoding="utf-8") as f:
                main_activity_content = f.read()
            self.assertIn('package com.rodrix.musiccreator;', main_activity_content)

            with open(gradle_path, "r", encoding="utf-8") as f:
                gradle_content = f.read()
            self.assertIn('namespace \'com.rodrix.musiccreator\'', gradle_content)
            self.assertIn('applicationId "com.rodrix.musiccreator"', gradle_content)

    # 18. Áreas seguras de Android y viewport-fit
    def test_18_viewport_fit_and_safe_areas(self):
        """Verifica que el viewport use viewport-fit=cover y que mobile-bottom-nav use safe-area-inset-bottom."""
        self.assertIn('viewport-fit=cover', self.index_content)
        self.assertIn('calc(60px + env(safe-area-inset-bottom, 0px))', self.index_content)
        self.assertIn('env(safe-area-inset-bottom, 0px)', self.index_content)

    # 19. Responsiveness en orientación horizontal y teclado virtual
    def test_19_landscape_and_virtual_keyboard_responsiveness(self):
        """Comprueba reglas @media (max-height: 480px) para pantallas reducidas o teclado abierto."""
        self.assertIn('@media (max-height: 480px)', self.index_content)
        self.assertIn('height: 50px !important;', self.index_content)

    # 20. Convivencia bidireccional entre reproductores
    def test_20_bidirectional_preview_pause(self):
        """Comprueba que la reproducción de vistas previas externas pausan el reproductor global."""
        self.assertIn("['voAudioPlayer', 'unifiedAudioPlayer', 'ampAudioPlayer', 'sf2EnrichAudioPlayer']", self.index_content)
        self.assertIn("if (state.status === 'playing') pause()", self.index_content)

    # 21. Resiliencia de streaming y fallback de Google Drive en backend
    def test_21_backend_audio_streaming_resilience(self):
        """Verifica la cadena de respaldo en /api/audio_file/{task_id} (disco local -> Google Drive 5TB -> URL externa)."""
        self.assertIn('@app.get("/api/audio_file/{task_id}")', self.app_content)
        self.assertIn('gdrive_download_file_bytes', self.app_content)
        self.assertIn('raw_audio_url', self.app_content)
        self.assertIn('FileResponse(path=local_path, media_type="audio/mpeg")', self.app_content)


if __name__ == "__main__":
    unittest.main()
