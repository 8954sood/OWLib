import importlib.util
import pathlib
import unittest

import numpy as np


SPEC = importlib.util.spec_from_file_location('sound_clips', pathlib.Path(__file__).parents[1] / 'scripts/match-sound-clips.py')
CLIPS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIPS)


class SoundClipTests(unittest.TestCase):
    def test_two_clicks_are_detected_as_separate_occurrences(self):
        rate = 8000
        rng = np.random.default_rng(77)
        t = np.arange(1440) / rate
        click = np.sin(2 * np.pi * (300 * t + 1000 * t * t)) * np.hanning(len(t))
        recording = rng.normal(0, .0001, 11200)
        recording[1600:3040] += .2 * click
        recording[6400:7840] += .1 * click
        result = CLIPS.compare(click, recording, [], rate)
        self.assertGreater(result['waveform_score'], .999)
        self.assertGreater(result['explained_clip_energy'], .99)
        self.assertEqual(len(result['occurrences']), 2)
        times = sorted(item['clip_seconds'] for item in result['occurrences'])
        np.testing.assert_allclose(times, [.2, .8], atol=1 / rate)

    def test_weak_tiny_fragment_is_not_ranked_as_explained_audio(self):
        rate = 8000
        rng = np.random.default_rng(2)
        template = rng.normal(size=160)
        recording = rng.normal(size=8000)
        result = CLIPS.compare(template, recording, [], rate)
        self.assertLess(result['waveform_score'], .95)
        self.assertEqual(result['explained_clip_energy'], 0)

    def test_full_cut_location_survives_gain_and_noise(self):
        rng = np.random.default_rng(51)
        recording = rng.normal(size=12000)
        cut = .4 * recording[4321:7321] + rng.normal(0, .0001, 3000)
        result = CLIPS.correlations(cut, recording)
        self.assertEqual(int(np.argmax(result[0])), 4321)
        self.assertGreater(float(result[0].max()), .999)

    def test_effect_tail_cut_by_video_boundary_is_matched(self):
        rng = np.random.default_rng(80)
        source = rng.normal(size=2400)
        recording = rng.normal(0, .0001, 7920)
        recording[6640:] += .3 * source[:1280]
        result = CLIPS.compare(source, recording, [], 8000)
        self.assertGreater(result['waveform_score'], .999)
        self.assertAlmostEqual(result['resource_start_clip_seconds'], .83, places=3)
        self.assertEqual(result['method'], 'edge-clipped-resource')

    def test_cut_can_start_inside_a_long_resource(self):
        rng = np.random.default_rng(81)
        source = rng.normal(size=32000)
        recording = .2 * source[16000:21600]
        result = CLIPS.compare(source, recording, [], 8000)
        self.assertGreater(result['waveform_score'], .999)
        self.assertAlmostEqual(result['source_seconds'], 2., places=3)
        self.assertGreater(result['explained_clip_energy'], .99)

    def test_restored_context_does_not_select_an_unrelated_outside_event(self):
        rng = np.random.default_rng(82)
        source = rng.normal(size=1600)
        recording = rng.normal(0, .0001, 32000)
        recording[1600:3200] += source
        recording[17600:19200] += .1 * source
        result = CLIPS.compare(source, recording, [], 8000, (16000, 24000))
        self.assertAlmostEqual(result['clip_seconds'], 2.2, places=3)
        self.assertGreater(result['waveform_score'], .999)


if __name__ == '__main__':
    unittest.main()
