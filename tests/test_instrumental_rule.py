import unittest
import asyncio
from unittest.mock import patch, MagicMock

# Import helper functions and transform task from app
from app import run_transform_task, TASKS


class TestInstrumentalRule(unittest.TestCase):
    """
    Test suite verifying the absolute golden rule:
    'tiene que ser instrumental, si y solo si cliqueo la casilla instrumental, sinó no'
    """

    def setUp(self):
        self.pentecostal_style = (
            "full live acoustic praise drum kit, tempo 4/4, snare 2-4, kick 1-3, hi-hat, "
            "loud cutting snare drum backbeat cracking hard on beats 2 and 4, punchy snare rimshots on every 2 and 4, "
            "heavy 22-inch kick drum on beats 1 and 3, bright metallic hi-hat cymbals keeping steady eighth notes, "
            "crash cymbal downbeats, dynamic acoustic tom rolls and drum fills, loud upfront drums in the front of the mix, "
            "traditional two-step praise straight 4/4 rhythm, steady 118 bpm tempo, "
            "authentic physical electric bass guitar with roundwound strings and Ampeg SVT, root-fifth alternating bass boom-chick, "
            "driving acoustic rhythm guitar strum, passionate Argentine church choir singing in unison, natural Spanish vocals"
        )
        self.pentecostal_exclude = (
            "zero synth bass, zero 808 sub, no distant drums, no missing snare, no quiet snare, no missing cymbals, "
            "no kick drum only, no a cappella, no missing drums, no black gospel, no afro gospel, no soul, "
            "no melisma, no vocal runs, no tambourine solo, no handclaps solo, no murga, no comparsa, no carnaval, "
            "no batucada, no candombe, no bombo de murga, no marcha militar, no latin rhythm, no syncopation, "
            "no tumbao, no cumbia, no caribbean accent"
        )
        self.user_lyrics = (
            "[Verse 1]\n"
            "Cantaré al Señor por siempre\n"
            "Su diestra es todo poder\n"
            "[Chorus]\n"
            "Ha echado a la mar quien nos perseguía\n"
            "Jinete y caballo ha echado a la mar"
        )

    def test_pentecostal_with_lyrics_and_include_lyrics_true_is_never_instrumental(self):
        """
        When Pentecostal preset is selected with user lyrics and include_lyrics=True,
        make_instrumental MUST be False and lyrics MUST be preserved.
        """
        captured_payloads = []

        async def fake_post(url, headers=None, json=None, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "id": "mock_work_id",
                "status": "QUEUED",
                "title": json.get("title", "Test Song"),
                "tracks": [{"id": "mock_track_1", "audio_url": "https://example.com/audio.mp3"}]
            }
            if json:
                captured_payloads.append(dict(json))
            return mock_resp

        task_id = "test_task_pentecostal_vocal"
        TASKS[task_id] = {"logs": ""}

        with patch("httpx.AsyncClient.post", side_effect=fake_post), \
             patch("httpx.AsyncClient.get") as mock_get:
            mock_feed_resp = MagicMock()
            mock_feed_resp.status_code = 200
            mock_feed_resp.json.return_value = {
                "status": "SUCCESS",
                "data": [{"id": "mock_track_1", "audio_url": "https://example.com/audio.mp3", "title": "Test"}]
            }
            mock_feed_resp.text = '{"status":"SUCCESS"}'
            mock_get.return_value = mock_feed_resp

            asyncio.run(
                run_transform_task(
                    task_id=task_id,
                    style=self.pentecostal_style,
                    lyrics=self.user_lyrics,
                    title="Alabanza Pentecostal Viva",
                    audio_content=None,
                    audio_filename=None,
                    ignore_audio=True,
                    include_lyrics=True,  # User did NOT check instrumental!
                    bypass_copyright=False,
                    exclude_styles=self.pentecostal_exclude,
                    vocal_gender="random",
                    weirdness=20,
                    style_influence=50,
                    audio_influence=0,
                    model="chirp-v4-5",
                    pronunciation="",
                    obfuscate=False,
                    is_public_domain=False,
                    target_bpm=118,
                    hihat_mode="8th",
                    active_preset="pentecostal"
                )
            )

        self.assertTrue(len(captured_payloads) > 0, "Udio API payload should have been captured")
        payload = captured_payloads[0]

        # 1. make_instrumental must be strictly False
        self.assertFalse(payload["make_instrumental"], "make_instrumental MUST be False when include_lyrics=True")

        # 2. Lyrics must contain the user's lyrics, not [Instrumental - Solo Guitar]
        self.assertIn("Cantaré al Señor por siempre", payload["prompt"], "User lyrics must be present in prompt")
        self.assertNotIn("[Instrumental - Solo Guitar]", payload["prompt"])
        self.assertNotIn("[Instrumental - Solo Bass]", payload["prompt"])
        self.assertNotIn("[Instrumental - Solo Piano]", payload["prompt"])

        # 3. Style must include choir and Argentine vocals
        self.assertIn("choir", payload["style"].lower(), "Style prompt must include choir for Pentecostal song")

        # 4. Negative tags must not exclude vocals or choir in general (only specific regional styles like caribbean vocals are excluded)
        neg_tags_list = [t.strip().lower() for t in payload.get("negative_tags", "").split(",") if t.strip()]
        self.assertNotIn("vocals", neg_tags_list, "General vocals must not be in negative tags")
        self.assertNotIn("choir", neg_tags_list, "Choir must not be in negative tags")

    def test_pentecostal_with_include_lyrics_false_is_instrumental(self):
        """
        When the user explicitly checks the instrumental checkbox (include_lyrics=False),
        make_instrumental MUST be True.
        """
        captured_payloads = []

        async def fake_post(url, headers=None, json=None, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "id": "mock_work_id",
                "status": "QUEUED",
                "title": json.get("title", "Test Song"),
                "tracks": [{"id": "mock_track_1", "audio_url": "https://example.com/audio.mp3"}]
            }
            if json:
                captured_payloads.append(dict(json))
            return mock_resp

        task_id = "test_task_pentecostal_instr"
        TASKS[task_id] = {"logs": ""}

        with patch("httpx.AsyncClient.post", side_effect=fake_post), \
             patch("httpx.AsyncClient.get") as mock_get:
            mock_feed_resp = MagicMock()
            mock_feed_resp.status_code = 200
            mock_feed_resp.json.return_value = {
                "status": "SUCCESS",
                "data": [{"id": "mock_track_1", "audio_url": "https://example.com/audio.mp3", "title": "Test"}]
            }
            mock_feed_resp.text = '{"status":"SUCCESS"}'
            mock_get.return_value = mock_feed_resp

            asyncio.run(
                run_transform_task(
                    task_id=task_id,
                    style=self.pentecostal_style,
                    lyrics="",
                    title="Alabanza Pentecostal Instrumental",
                    audio_content=None,
                    audio_filename=None,
                    ignore_audio=True,
                    include_lyrics=False,  # User explicitly checked instrumental!
                    bypass_copyright=False,
                    exclude_styles=self.pentecostal_exclude,
                    vocal_gender="random",
                    weirdness=20,
                    style_influence=50,
                    audio_influence=0,
                    model="chirp-v4-5",
                    pronunciation="",
                    obfuscate=False,
                    is_public_domain=False,
                    target_bpm=118,
                    hihat_mode="8th",
                    active_preset="pentecostal"
                )
            )

        self.assertTrue(len(captured_payloads) > 0, "Udio API payload should have been captured")
        payload = captured_payloads[0]

        # make_instrumental must be strictly True
        self.assertTrue(payload["make_instrumental"], "make_instrumental MUST be True when include_lyrics=False")

    def test_guitar_keywords_with_lyrics_and_include_lyrics_true_is_never_instrumental(self):
        """
        Even if a style prompt includes 'guitar', 'stratocaster', 'les paul' and exclusions
        contain 'drums' or 'bass', if include_lyrics=True, it is NEVER converted to instrumental.
        """
        captured_payloads = []

        async def fake_post(url, headers=None, json=None, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "id": "mock_work_id",
                "status": "QUEUED",
                "title": json.get("title", "Test Song"),
                "tracks": [{"id": "mock_track_1", "audio_url": "https://example.com/audio.mp3"}]
            }
            if json:
                captured_payloads.append(dict(json))
            return mock_resp

        task_id = "test_task_guitar_vocal"
        TASKS[task_id] = {"logs": ""}

        with patch("httpx.AsyncClient.post", side_effect=fake_post), \
             patch("httpx.AsyncClient.get") as mock_get:
            mock_feed_resp = MagicMock()
            mock_feed_resp.status_code = 200
            mock_feed_resp.json.return_value = {
                "status": "SUCCESS",
                "data": [{"id": "mock_track_1", "audio_url": "https://example.com/audio.mp3", "title": "Test"}]
            }
            mock_feed_resp.text = '{"status":"SUCCESS"}'
            mock_get.return_value = mock_feed_resp

            asyncio.run(
                run_transform_task(
                    task_id=task_id,
                    style="Christian rock, Fender Stratocaster electric guitar, melodic solos",
                    lyrics=self.user_lyrics,
                    title="Rock Cristiano con Guitarras",
                    audio_content=None,
                    audio_filename=None,
                    ignore_audio=True,
                    include_lyrics=True,  # User did NOT check instrumental!
                    bypass_copyright=False,
                    exclude_styles="synth bass, distant drums, quiet snare",
                    vocal_gender="male",
                    weirdness=20,
                    style_influence=50,
                    audio_influence=0,
                    model="chirp-v4-5",
                    pronunciation="",
                    obfuscate=False,
                    is_public_domain=False,
                    target_bpm=120,
                    hihat_mode="8th",
                    active_preset=""
                )
            )

        self.assertTrue(len(captured_payloads) > 0)
        payload = captured_payloads[0]

        # make_instrumental must be False and lyrics preserved
        self.assertFalse(payload["make_instrumental"])
        self.assertIn("Cantaré al Señor por siempre", payload["prompt"])
        self.assertNotIn("[Instrumental - Solo Guitar]", payload["prompt"])


if __name__ == "__main__":
    unittest.main()
