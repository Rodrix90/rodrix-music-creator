import json
import os
import re
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

os.environ["RODRIX_DISABLE_GDRIVE_NETWORK"] = "1"
os.environ.setdefault("UDIO_API_KEY", "test_key_redacted_0000")

import app
import studio_virtual_catalog


class TestStudioVirtualSixSelectors(unittest.IsolatedAsyncioTestCase):
    """
    Valida los 6 selectores independientes del Estudio Virtual (0 créditos, 0 Udio real, 0 Drive real):
    - Catálogos completos y arquitectura extensible centralizada
    - Desglose de 3 dimensiones (físico, interpretación, procesamiento) y nota de honestidad
    - Compactación prioritaria <= 1000 chars sin omisión silenciosa
    - Preservación de Original / Automático sin imposiciones
    - Compatibilidad Upload & Cover, MP3 y letras intactas en prompt
    - Persistencia de navegación, compatibilidad Android e integridad del micrófono
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.orig_tasks_file = app.GENERATION_TASKS_FILE
        self.orig_lib_file = app.LIBRARY_FILE
        self.orig_tracks_dir = app.TRACKS_DIR
        self.orig_db_env = os.environ.get("RODRIX_DB_PATH")

        self.tmp_db = os.path.join(self.tmpdir.name, "test_studio_selectors.db")
        self.tmp_tracks = os.path.join(self.tmpdir.name, "tracks_storage")
        os.makedirs(self.tmp_tracks, exist_ok=True)
        os.environ["RODRIX_DB_PATH"] = self.tmp_db
        app.GENERATION_TASKS_FILE = os.path.join(self.tmpdir.name, "generation_tasks.json")
        app.LIBRARY_FILE = os.path.join(self.tmpdir.name, "library.json")
        app.TRACKS_DIR = self.tmp_tracks
        with app._transactional_db():
            pass
        app.TASKS.clear()
        app.RECENT_OPERATIONS.clear()
        app.app.dependency_overrides[app.get_current_user] = lambda: "rodryandy@gmail.com"

    def tearDown(self):
        app.app.dependency_overrides.clear()
        app.TASKS.clear()
        app.RECENT_OPERATIONS.clear()
        app.GENERATION_TASKS_FILE = self.orig_tasks_file
        app.LIBRARY_FILE = self.orig_lib_file
        app.TRACKS_DIR = self.orig_tracks_dir
        if self.orig_db_env is None:
            os.environ.pop("RODRIX_DB_PATH", None)
        else:
            os.environ["RODRIX_DB_PATH"] = self.orig_db_env
        self.tmpdir.cleanup()

    async def test_01_centralized_catalog_completeness_three_layers_and_api_endpoint(self):
        payload = studio_virtual_catalog.get_studio_virtual_catalog_payload()
        cats = {c["key"]: c for c in payload["categories"]}
        self.assertEqual(set(cats.keys()), {"drums", "guitars", "basses", "keyboards", "consoles", "microphones"})

        expected_counts = {
            "drums": 10,
            "guitars": 10,
            "basses": 10,
            "keyboards": 6,
            "consoles": 4,
            "microphones": 5,
        }
        for key, count in expected_counts.items():
            self.assertEqual(len(cats[key]["items"]), count, f"Cantidad esperada en {key}")

        expected_labels_substrings = [
            ("drums", ["John Bonham", "Neil Peart", "Stewart Copeland", "Keith Moon", "Charlie Watts", "Mike Portnoy", "Chad Smith", "Phil Collins", "Dave Grohl", "Ginger Baker"]),
            ("guitars", ["Stevie Ray Vaughan", "Steve Vai", "John Frusciante", "Andy Summers", "Eddie Van Halen", "David Gilmour", "Brian May", "Peter Green", "Jimi Hendrix", "Jimmy Page"]),
            ("basses", ["Jaco Pastorius", "James Jamerson", "Marcus Miller", "Victor Wooten", "Flea", "Geddy Lee", "Cliff Burton", "John Entwistle", "Diego Arnedo", "Chris Squire"]),
            ("keyboards", ["Piano acústico", "Hammond B3", "Fender Rhodes", "Wurlitzer", "Yamaha DX7", "Minimoog"]),
            ("consoles", ["SSL 4000", "Neve 80 Series", "API Console", "Consola digital transparente"]),
            ("microphones", ["Neumann U87", "Shure SM7B", "Shure SM58", "AKG C414", "Telefunken U47"]),
        ]
        forbidden_names_in_udio_prompt = [
            "bonham", "peart", "copeland", "keith moon", "charlie watts", "portnoy", "chad smith",
            "phil collins", "grohl", "ginger baker", "vaughan", "steve vai", "frusciante",
            "andy summers", "van halen", "gilmour", "brian may", "peter green", "hendrix", "jimmy page",
            "jaco", "pastorius", "jamerson", "marcus miller", "wooten", "flea", "geddy",
            "cliff burton", "entwistle", "arnedo", "chris squire", "what's going on", "roundabout", "anesthesia",
        ]

        for key, names in expected_labels_substrings:
            joined_labels = "\n".join(it["label"] for it in cats[key]["items"])
            for name in names:
                self.assertIn(name, joined_labels, f"Falta '{name}' en catálogo '{key}'")
            for it in cats[key]["items"]:
                for field in ("physical_instrument", "musical_performance", "studio_processing", "core_tag"):
                    self.assertTrue(it[field].strip(), f"{key}.{it['id']}.{field} no puede estar vacío")
                    low_val = it[field].lower()
                    for banned in forbidden_names_in_udio_prompt:
                        self.assertNotIn(banned, low_val, f"Nombre/referencia '{banned}' no debe enviarse a Udio en {it['id']}.{field}")
                self.assertIn("instrumento", it["summary_es"])
                self.assertIn("interpretacion", it["summary_es"])
                self.assertIn("procesamiento", it["summary_es"])

        self.assertIn("sin sustituir", payload["honesty_notice"].lower())

        transport = httpx.ASGITransport(app=app.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://rodrix.example") as client:
            resp = await client.get("/api/studio-profiles/catalog")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["categories"]), 6)

    def test_02_index_html_has_six_selectors_responsive_android_css_and_catalog_parity(self):
        with open(os.path.join(REPO_DIR, "index.html"), "r", encoding="utf-8") as _f:
            html = _f.read()

        for sel_id in ("selStudioDrums", "selStudioGuitar", "selStudioBass", "selStudioKeyboard", "selStudioConsole", "selStudioMic"):
            self.assertIn(f'id="{sel_id}"', html)
            pattern = rf'<select[^>]*id="{sel_id}"[^>]*>.*?<option value="auto"[^>]*>Original / Automático</option>'
            self.assertRegex(html.replace("\n", " "), pattern)

        # Compatibilidad móvil / Android y persistencia entre vistas
        self.assertIn("@media (max-width: 600px)", html)
        self.assertIn(".studio-selectors-grid{grid-template-columns:minmax(0,1fr)", html)
        self.assertIn("rodrix_studio_virtual_selectors_v1", html)
        self.assertIn("getStudioVirtualSelections", html)
        self.assertIn("resetStudioVirtualSelectors", html)

        # Paridad exacta del catálogo JS embebido con el módulo Python centralizado
        m = re.search(r"const STUDIO_VIRTUAL_FALLBACK_CATALOG = (\{.*?\});\n", html)
        self.assertIsNotNone(m, "Debe existir STUDIO_VIRTUAL_FALLBACK_CATALOG en index.html")
        embedded = json.loads(m.group(1).replace("<\\/", "</"))
        self.assertEqual(embedded, studio_virtual_catalog.get_studio_virtual_catalog_payload())

        # Integridad de controles existentes del micrófono móvil y carga de MP3
        self.assertIn('id="voRecordPanel"', html)
        self.assertIn("createScriptProcessor(4096", html)
        self.assertIn('id="audioInput"', html)
        self.assertIn('id="lyricsInput"', html)

    def test_03_auto_selections_impose_no_instructions_and_selectors_combine_independently(self):
        # Todas en auto -> cero cláusulas adicionales
        all_auto = studio_virtual_catalog.normalize_studio_selections({})
        self.assertFalse(studio_virtual_catalog.has_active_studio_selections(all_auto))

        res_plain = app.build_prioritized_style(
            genre_anchor="Christian Rock",
            bpm_tag="120 BPM",
            user_and_enriched_style="uplifting modern Christian rock",
            priority_rhythm_clauses=["steady closed eighth-note hi-hat pattern"],
            vocal_tag="clear natural Spanish vocals",
            is_instrumental=False,
            studio_selections=None,
        )
        res_auto = app.build_prioritized_style(
            genre_anchor="Christian Rock",
            bpm_tag="120 BPM",
            user_and_enriched_style="uplifting modern Christian rock",
            priority_rhythm_clauses=["steady closed eighth-note hi-hat pattern"],
            vocal_tag="clear natural Spanish vocals",
            is_instrumental=False,
            studio_selections=all_auto,
        )
        self.assertEqual(res_plain["style"], res_auto["style"])

        # Combinación parcial (2 de 6) no impone las otras 4 categorías
        partial = {"drums": "copeland", "microphones": "shure_sm7b"}
        pack = studio_virtual_catalog.pack_studio_profiles_within_budget(partial, available_budget=900, is_instrumental=False)
        self.assertEqual(pack["active_count"], 2)
        self.assertEqual(pack["preserved_categories"], ["drums", "microphones"])
        joined_low = pack["joined_text"].lower()
        self.assertIn("reggae and ska syncopated rimshots", joined_low)
        self.assertIn("moving-coil dynamic vocal microphone", joined_low)
        self.assertNotIn("stratocaster", joined_low)
        self.assertNotIn("hammond", joined_low)
        self.assertNotIn("ssl", joined_low)

    def test_04_progressive_compaction_respects_1000_chars_without_silent_drops(self):
        all_six = {
            "drums": "peart",
            "guitars": "gilmour_black_strat",
            "basses": "miller_jazz_funk",
            "keyboards": "hammond_b3",
            "consoles": "ssl_4000",
            "microphones": "telefunken_u47",
        }
        # Caso A: Combinación completa de las 6 categorías sobre prompt estándar
        res_std = app.build_prioritized_style(
            genre_anchor="Progressive Worship Rock, 4/4 time signature",
            bpm_tag="92 BPM",
            user_and_enriched_style="emotive soaring arrangement",
            priority_rhythm_clauses=["steady closed eighth-note hi-hat pattern"],
            vocal_tag="clear natural male Spanish vocals",
            is_instrumental=False,
            max_chars=1000,
            studio_selections=all_six,
        )
        self.assertLessEqual(len(res_std["style"]), 1000)
        self.assertTrue(res_std["core_preserved"])
        sp = res_std["studio_profiles"]
        self.assertEqual(sp["active_count"], 6)
        self.assertEqual(set(sp["preserved_categories"]), {"drums", "basses", "guitars", "keyboards", "microphones", "consoles"})
        self.assertEqual(sp["omitted_categories"], [])

        # Caso B: Prompt base muy largo (~640 chars) + las 6 categorías activas -> compacta capas sin perder ninguna selección
        long_prompt = ", ".join(f"symphonic rock texture layer {i:02d} with dynamic harmonic countermelody" for i in range(10))
        res_tight = app.build_prioritized_style(
            genre_anchor="Progressive Christian Rock",
            bpm_tag="108 BPM",
            user_and_enriched_style=long_prompt,
            priority_rhythm_clauses=["steady closed eighth-note hi-hat pattern"],
            vocal_tag="clear natural female Spanish vocals",
            is_instrumental=False,
            max_chars=1000,
            raw_user_style="Progressive Christian Rock",
            studio_selections=all_six,
        )
        self.assertLessEqual(len(res_tight["style"]), 1000)
        self.assertTrue(res_tight["core_preserved"])
        self.assertEqual(len(res_tight["studio_profiles"]["preserved_categories"]), 6)
        self.assertEqual(res_tight["studio_profiles"]["omitted_categories"], [])
        self.assertTrue(res_tight["studio_profiles"]["reduced_categories"])
        self.assertIsNotNone(res_tight["compaction_notice"])

        # Confirmar que cada una de las 6 selecciones conserva presencia real en el style final
        out_low = res_tight["style"].lower()
        for expected_tok in ("drum", "bass", "guitar", "hammond", "microphone"):
            self.assertIn(expected_tok, out_low)
        self.assertTrue("solid state logic" in out_low or "ssl" in out_low)

    async def test_05_upload_cover_keeps_lyrics_prompt_intact_and_injects_studio_into_style(self):
        captured_payloads = []

        async def fake_post(url, json=None, headers=None, **kw):
            captured_payloads.append(json)
            mock_r = MagicMock()
            mock_r.status_code = 200
            mock_r.text = '{"code": 200, "data": {"workId": "upcov_mock_studio_6", "task_id": "upcov_mock_studio_6"}}'
            mock_r.json.return_value = {"code": 200, "data": {"workId": "upcov_mock_studio_6", "task_id": "upcov_mock_studio_6"}}
            return mock_r

        status_mock = MagicMock()
        status_mock.status_code = 200
        status_mock.json.return_value = {"code": 200, "data": {"type": "SUCCESS", "response_data": []}}

        mock_client = AsyncMock()
        mock_client.post.side_effect = fake_post
        mock_client.get.return_value = status_mock

        task_id = "test-studio-six-upload-cover"
        app.TASKS[task_id] = {"id": task_id, "owner_email": "rodryandy@gmail.com", "logs": "", "status": "IN_PROGRESS"}

        original_lyrics = "[Verse 1]\nEsta melodía original es mía\nLa canto con alma y verdad\n[Chorus]\nNo se altera ni una sola sílaba"
        src_wav = os.path.join(REPO_DIR, "test.wav")
        if os.path.exists(src_wav):
            with open(src_wav, "rb") as _f:
                audio_bytes = _f.read()
        else:
            audio_bytes = b"RIFF" + b"\x00" * 4096

        sel_six = {
            "drums": "bonham",
            "guitars": "gilmour_black_strat",
            "basses": "arnedo_rock_argentino",
            "keyboards": "hammond_b3",
            "consoles": "neve_80",
            "microphones": "telefunken_u47",
        }

        with patch("httpx.AsyncClient") as client_cls, \
             patch.object(app, "upload_to_uguu_async", AsyncMock(return_value="https://n.uguu.se/mock_six.mp3")), \
             patch.object(app, "verify_public_audio_url_async", AsyncMock(return_value=True)), \
             patch.object(app, "gdrive_sync_generation_tasks_to_cloud", AsyncMock(return_value={"file_id": "drv_ok"})):
            client_cls.return_value.__aenter__.return_value = mock_client

            await app.run_transform_task(
                task_id=task_id,
                style="Rock melódico argentino de autor",
                lyrics=original_lyrics,
                title="Prueba Seis Selectores",
                audio_content=audio_bytes,
                audio_filename="voz_original.wav",
                ignore_audio=False,
                include_lyrics=True,
                bypass_copyright=False,
                exclude_styles="",
                vocal_gender="male",
                weirdness=20,
                style_influence=75,
                audio_influence=65,
                model="chirp-v6",
                target_bpm=88,
                hihat_mode="8th",
                lyrics_mode="custom",
                preserve_original_audio=True,
                studio_selections=sel_six,
            )

        self.assertEqual(mock_client.post.call_count, 1)
        payload = captured_payloads[0]
        # Prompt contiene EXCLUSIVAMENTE la letra exacta del usuario (sin contaminación de estudio)
        self.assertTrue(payload["custom_mode"])
        self.assertFalse(payload["make_instrumental"])
        self.assertEqual(payload["prompt"], original_lyrics)
        self.assertNotIn("Neve", payload["prompt"])
        self.assertNotIn("Hammond", payload["prompt"])
        self.assertNotIn("Telefunken", payload["prompt"])

        # Style <= 1000 chars, contiene descriptores técnicos puros y ningún nombre de artista prohibido
        sent_style = payload["style"]
        self.assertLessEqual(len(sent_style), 1000)
        self.assertIn("88 BPM", sent_style)
        self.assertNotIn("John Bonham", sent_style)
        self.assertNotIn("David Gilmour", sent_style)
        self.assertNotIn("Diego Arnedo", sent_style)
        self.assertTrue(any(k in sent_style.lower() for k in ("26-inch acoustic maple kick", "acoustic drum kit")))
        self.assertTrue(any(k in sent_style.lower() for k in ("stratocaster", "electric guitar")))
        self.assertIn("electric bass", sent_style.lower())
        self.assertIn("hammond b3", sent_style.lower())
        self.assertIn("synth bass", payload.get("tags", "").lower())

    async def test_06_preview_parameters_and_minimoog_bass_coherence(self):
        transport = httpx.ASGITransport(app=app.app)
        original_lyrics = "[Verse]\nLetra intacta para preview sin créditos"
        async with httpx.AsyncClient(transport=transport, base_url="https://rodrix.example") as client:
            resp = await client.post(
                "/api/preview_parameters",
                data={
                    "title": "Preview Estudio Virtual",
                    "style": "Rock worship moderno",
                    "lyrics": original_lyrics,
                    "include_lyrics": "true",
                    "lyrics_mode": "custom",
                    "target_bpm": "96",
                    "studio_drums": "smith",
                    "studio_guitar": "frusciante_strat62",
                    "studio_bass": "auto",
                    "studio_keyboard": "minimoog",
                    "studio_console": "api_console",
                    "studio_mic": "neumann_u87",
                },
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["prompt_preview"], original_lyrics)
        self.assertLessEqual(data["style_length"], 1000)
        self.assertEqual(data["studio_profiles"]["active_count"], 5)
        self.assertIn("96 BPM", data["style_full_preview"])
        self.assertIn("moog bass", data["style_full_preview"].lower())

        # Verificar que Minimoog sin bajo eléctrico no queda anulado en resolve_negative_exclusions
        neg_str, tags_str, _ = app.resolve_negative_exclusions("", data["style_full_preview"])
        self.assertNotIn("moog bass", tags_str.lower())

    def test_07_all_45_profiles_produce_distinct_styles_and_warning_alert_ui_present(self):
        payload = studio_virtual_catalog.get_studio_virtual_catalog_payload()
        generated = set()
        core_tags = set()
        total = 0
        for cat in payload["categories"]:
            for it in cat["items"]:
                total += 1
                res = app.build_prioritized_style(
                    genre_anchor="Rock moderno",
                    bpm_tag="100 BPM",
                    user_and_enriched_style="",
                    priority_rhythm_clauses=["steady closed eighth-note hi-hat pattern"],
                    vocal_tag="clear natural Spanish vocals",
                    is_instrumental=False,
                    max_chars=1000,
                    studio_selections={cat["key"]: it["id"]},
                )
                generated.add(res["style"])
                core_tags.add(it["core_tag"])

        self.assertEqual(total, 45)
        self.assertEqual(len(generated), 45, "Cada uno de los 45 perfiles debe generar un style único y diferenciado")
        self.assertEqual(len(core_tags), 45)

        with open(os.path.join(REPO_DIR, "index.html"), "r", encoding="utf-8") as _f:
            html = _f.read()
        self.assertIn('id="studioCompactionWarning"', html)
        self.assertIn('Advertencia por límite de', html)
        self.assertIn('[Omitida por límite de 1000 chars]', html)

    def test_08_intelligent_style_optimization_1_3_and_6_selectors_no_padding_no_bias(self):
        """Valida 1 selector (sin relleno artificial), 3 selectores y 6 selectores simultáneos aprovechando hasta 1000 chars."""
        base_kwargs = dict(
            genre_anchor="Progressive Worship Rock, 4/4 time signature",
            bpm_tag="92 BPM",
            user_and_enriched_style="Rock melódico argentino de autor",
            priority_rhythm_clauses=["steady closed eighth-note hi-hat pattern (two strokes per beat, 1-and 2-and 3-and 4-and)"],
            vocal_tag="natural male Argentine Spanish vocals, clean expressive singing",
            is_instrumental=False,
            max_chars=1000,
            raw_user_style="Rock melódico argentino de autor",
        )

        # 1) Un solo instrumento: entra sobrado (< 750 chars), NO agrega relleno artificial y mantiene las 3 capas íntegras
        res_one = app.build_prioritized_style(**base_kwargs, studio_selections={"drums": "bonham"})
        self.assertLessEqual(res_one["final_length"], 1000)
        self.assertEqual(res_one["final_length"], studio_virtual_catalog.measure_udio_style_length(res_one["style"]))
        self.assertFalse(res_one["truncated"])
        self.assertEqual(res_one["studio_profiles"]["compaction_stage"], "full_3_layers")
        self.assertEqual(res_one["studio_profiles"]["preserved_dimensions"]["drums"], ["physical", "performance", "studio"])
        self.assertLess(res_one["final_length"], 650, "No debe inflar artificialmente un style que ya cabe completo")

        # 2) Dos selectores (~720-850 chars): reutiliza espacio libre de categorías en auto, sin relleno artificial
        res_two = app.build_prioritized_style(
            genre_anchor="Modern Rock",
            bpm_tag="104 BPM",
            user_and_enriched_style="bright studio mix",
            priority_rhythm_clauses=[],
            vocal_tag="clear natural Spanish vocals",
            is_instrumental=False,
            max_chars=1000,
            studio_selections={"guitars": "summers_tele61", "consoles": "api_console"},
        )
        self.assertLessEqual(res_two["final_length"], 1000)
        self.assertEqual(res_two["studio_profiles"]["compaction_stage"], "full_3_layers")
        self.assertFalse(res_two["truncated"])

        # 3) Tres instrumentos simultáneos: conserva 3 dimensiones en los 3 sin favorecer solo a batería
        res_three = app.build_prioritized_style(
            **base_kwargs,
            studio_selections={"drums": "peart", "guitars": "gilmour_black_strat", "basses": "miller_jazz_funk"},
        )
        self.assertLessEqual(res_three["final_length"], 1000)
        self.assertGreaterEqual(res_three["final_length"], 940, "Debe aprovechar al máximo el límite de 1000 chars útiles")
        self.assertGreater(res_three["raw_length"], 1000)
        sp3 = res_three["studio_profiles"]
        for cat_k in ("drums", "guitars", "basses"):
            self.assertEqual(sp3["preserved_dimensions"][cat_k], ["physical", "performance", "studio"], f"{cat_k} debe conservar las 3 dimensiones")
        # Equidad: ningún instrumento acapara desproporcionadamente el presupuesto frente a los otros dos
        shares3 = list(sp3["per_category_chars"].values())
        self.assertLess(max(shares3) - min(shares3), 90, f"Distribución desequilibrada en 3 selectores: {sp3['per_category_chars']}")

        # 4) Seis selectores simultáneos: conserva las 6 categorías con 3 dimensiones y aprovechamiento > 95%
        six_sel = {
            "drums": "bonham",
            "guitars": "gilmour_black_strat",
            "basses": "arnedo_rock_argentino",
            "keyboards": "hammond_b3",
            "consoles": "neve_80",
            "microphones": "telefunken_u47",
        }
        res_six = app.build_prioritized_style(**base_kwargs, studio_selections=six_sel)
        self.assertLessEqual(res_six["final_length"], 1000)
        self.assertEqual(res_six["final_length"], studio_virtual_catalog.measure_udio_style_length(res_six["style"]))
        self.assertGreaterEqual(res_six["final_length"], 950, "Con 6 selectores debe aprovechar al máximo los 1000 chars")
        self.assertGreater(res_six["raw_length"], 1800, "raw_length debe reflejar la longitud real sin compactar")
        sp6 = res_six["studio_profiles"]
        self.assertEqual(sp6["active_count"], 6)
        self.assertEqual(sp6["omitted_categories"], [])
        for cat_k in six_sel:
            self.assertEqual(
                sp6["preserved_dimensions"][cat_k],
                ["physical", "performance", "studio"],
                f"Categoría {cat_k} debe conservar físico, interpretación y producción",
            )
        # Comprobar ausencia de sesgo posicional (consola/teclado/mic reciben asignación comparable a batería/guitarra)
        shares6 = sp6["per_category_chars"]
        self.assertLess(max(shares6.values()) - min(shares6.values()), 75, f"Asignación desequilibrada en 6 selectores: {shares6}")

    def test_09_extensive_prompts_explicit_omission_and_varied_genres_meters_vocals(self):
        """Valida descripciones extensas, omisión explícita nunca silenciosa, y múltiples géneros, métricas y voces."""
        all_six = {
            "drums": "portnoy",
            "guitars": "vai_evo",
            "basses": "squire_rickenbacker_prog",
            "keyboards": "yamaha_dx7",
            "consoles": "ssl_4000",
            "microphones": "akg_c414",
        }

        # Caso A: Diferentes géneros, métricas asimétricas y configuraciones vocales / instrumentales
        configs = [
            ("Progressive Metal Worship, strictly in 7/8 time signature (grouped 2+2+3)", "132 BPM", "clear natural female Spanish vocals", False),
            ("Sacred Argentine Acoustic Ballad, 3/4 time signature", "74 BPM", "natural male Argentine Spanish solo vocals", False),
            ("Jazz-Rock Funk Fusion, 4/4 time signature", "116 BPM", "", True),
        ]
        for anchor, bpm, vtag, is_inst in configs:
            res = app.build_prioritized_style(
                genre_anchor=anchor,
                bpm_tag=bpm,
                user_and_enriched_style="",
                priority_rhythm_clauses=["syncopated accent feel"],
                vocal_tag=vtag,
                is_instrumental=is_inst,
                max_chars=1000,
                studio_selections=all_six,
            )
            self.assertLessEqual(res["final_length"], 1000)
            self.assertTrue(res["core_preserved"])
            self.assertIn(bpm, res["style"])
            if is_inst:
                self.assertIn("instrumental", res["style"].lower())
            else:
                self.assertIn("spanish", res["style"].lower())
            self.assertEqual(len(res["studio_profiles"]["preserved_categories"]), 6)
            self.assertEqual(res["studio_profiles"]["omitted_categories"], [])

        # Caso B: Saturación extrema del prompt base (~880 chars) -> nunca omite silenciosamente, reporta motivo explícito
        huge_base = ", ".join(f"symphonic melodic motif {i:02d} in D minor" for i in range(25))
        res_overflow = app.build_prioritized_style(
            genre_anchor=huge_base,
            bpm_tag="100 BPM",
            user_and_enriched_style="",
            priority_rhythm_clauses=[],
            vocal_tag="clear natural Spanish vocals",
            is_instrumental=False,
            max_chars=1000,
            studio_selections=all_six,
        )
        self.assertLessEqual(res_overflow["final_length"], 1000)
        sp_ov = res_overflow["studio_profiles"]
        self.assertTrue(sp_ov["omitted_categories"], "Bajo saturación extrema debe registrar omisiones explícitas")
        for omitted_k in sp_ov["omitted_categories"]:
            self.assertIn(omitted_k, sp_ov["omitted_reasons"])
            self.assertIn("Presupuesto insuficiente", sp_ov["omitted_reasons"][omitted_k])
        self.assertIsNotNone(res_overflow["compaction_notice"])
        self.assertIn("omitidas explícitamente", res_overflow["compaction_notice"])

    def test_10_all_45_profiles_remain_distinct_under_active_compaction_and_unmodified_originals(self):
        """Confirma que los 45 perfiles conservan descripciones originales intactas y se mantienen únicos bajo compactación."""
        # Partner fijo de 5 perfiles para forzar compactación real en cada uno de los 45 perfiles evaluados
        partners = {
            "drums": "bonham",
            "guitars": "gilmour_black_strat",
            "basses": "arnedo_rock_argentino",
            "keyboards": "hammond_b3",
            "consoles": "neve_80",
            "microphones": "telefunken_u47",
        }
        payload = studio_virtual_catalog.get_studio_virtual_catalog_payload()
        for cat in payload["categories"]:
            ck = cat["key"]
            styles_for_cat = set()
            for it in cat["items"]:
                sel = dict(partners)
                sel[ck] = it["id"]
                res = app.build_prioritized_style(
                    genre_anchor="Modern Studio Rock, 4/4 time signature",
                    bpm_tag="100 BPM",
                    user_and_enriched_style="emotive arrangement",
                    priority_rhythm_clauses=["steady closed eighth-note hi-hat pattern"],
                    vocal_tag="clear natural Spanish vocals",
                    is_instrumental=False,
                    max_chars=1000,
                    studio_selections=sel,
                )
                self.assertLessEqual(res["final_length"], 1000)
                self.assertEqual(res["studio_profiles"]["omitted_categories"], [])
                styles_for_cat.add(res["style"])
            self.assertEqual(
                len(styles_for_cat),
                len(cat["items"]),
                f"Todos los perfiles de '{ck}' deben producir estilos diferenciados incluso bajo compactación de 6 selectores",
            )

    async def test_11_backend_dispatched_payload_matches_optimized_style_and_preserves_lyrics(self):
        """Verifica sin consumir créditos que el backend envía exactamente el style optimizado y mantiene intacta la letra en prompt."""
        captured = []

        async def fake_post(url, json=None, headers=None, **kw):
            captured.append(json)
            mock_r = MagicMock()
            mock_r.status_code = 200
            mock_r.text = '{"code": 200, "data": {"workId": "gen_mock_opt_style", "task_id": "gen_mock_opt_style"}}'
            mock_r.json.return_value = {"code": 200, "data": {"workId": "gen_mock_opt_style", "task_id": "gen_mock_opt_style"}}
            return mock_r

        status_mock = MagicMock()
        status_mock.status_code = 200
        status_mock.json.return_value = {"code": 200, "data": {"status": "SUCCESS", "response_data": []}}

        mock_client = AsyncMock()
        mock_client.post.side_effect = fake_post
        mock_client.get.return_value = status_mock

        sel_six = {
            "drums": "peart",
            "guitars": "may_red_special",
            "basses": "squire_rickenbacker_prog",
            "keyboards": "hammond_b3",
            "consoles": "ssl_4000",
            "microphones": "telefunken_u47",
        }
        lyrics_exact = "[Verse 1]\nCon voz firme elevo mi canción\nEn compás perfecto de adoración\n[Chorus]\nTu luz brilla eterna en mi interior"

        # 1) Obtener vista previa sin créditos desde /api/preview_parameters
        transport = httpx.ASGITransport(app=app.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://rodrix.example") as client:
            prev_resp = await client.post(
                "/api/preview_parameters",
                data={
                    "title": "Prueba Paridad Optimización",
                    "style": "Rock progresivo sinfónico",
                    "lyrics": lyrics_exact,
                    "include_lyrics": "true",
                    "lyrics_mode": "custom",
                    "vocal_gender": "male",
                    "target_bpm": "94",
                    "hihat_mode": "8th",
                    "studio_drums": sel_six["drums"],
                    "studio_guitar": sel_six["guitars"],
                    "studio_bass": sel_six["basses"],
                    "studio_keyboard": sel_six["keyboards"],
                    "studio_console": sel_six["consoles"],
                    "studio_mic": sel_six["microphones"],
                },
            )
        self.assertEqual(prev_resp.status_code, 200)
        prev_json = prev_resp.json()

        # 2) Ejecutar run_transform_task con Udio mockeado (0 créditos, 0 red real)
        task_id = "test-opt-style-parity"
        app.TASKS[task_id] = {"id": task_id, "owner_email": "rodryandy@gmail.com", "logs": "", "status": "IN_PROGRESS"}
        with patch("httpx.AsyncClient") as client_cls, \
             patch.object(app, "gdrive_sync_generation_tasks_to_cloud", AsyncMock(return_value={"file_id": "drv_ok"})):
            client_cls.return_value.__aenter__.return_value = mock_client
            await app.run_transform_task(
                task_id=task_id,
                style="Rock progresivo sinfónico",
                lyrics=lyrics_exact,
                title="Prueba Paridad Optimización",
                audio_content=None,
                audio_filename=None,
                ignore_audio=True,
                include_lyrics=True,
                bypass_copyright=False,
                exclude_styles="",
                vocal_gender="male",
                weirdness=20,
                style_influence=75,
                audio_influence=25,
                model="chirp-v6",
                target_bpm=94,
                hihat_mode="8th",
                lyrics_mode="custom",
                studio_selections=sel_six,
            )

        self.assertEqual(len(captured), 1)
        sent_payload = captured[0]
        self.assertEqual(sent_payload["prompt"], lyrics_exact)
        self.assertEqual(sent_payload["style"], prev_json["style_full_preview"])
        self.assertLessEqual(studio_virtual_catalog.measure_udio_style_length(sent_payload["style"]), 1000)
        self.assertGreaterEqual(len(sent_payload["style"]), 940)
        self.assertGreater(prev_json["style_raw_length"], 1800)


if __name__ == "__main__":
    unittest.main()
