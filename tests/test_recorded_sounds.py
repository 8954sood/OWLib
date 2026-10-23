import importlib.util
import pathlib
import unittest

import numpy as np

SPEC = importlib.util.spec_from_file_location(
    'recorded_sounds', pathlib.Path(__file__).parents[1] / 'scripts/find-recorded-sounds.py')
FINDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FINDER)


class RecordingMatchingTests(unittest.TestCase):
    def test_offset_gain_noise_and_waveform_verification(self):
        rng = np.random.default_rng(123)
        t = np.arange(24000) / FINDER.RATE
        source = ((np.sin(2 * np.pi * (220 * t + 120 * t * t))
                   + np.sin(2 * np.pi * (540 * t + 35 * t * t)))
                  * (0.4 + 0.2 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)
        delay = 8192
        reference = np.concatenate((np.zeros(delay), source * 0.25, np.zeros(8000)))
        reference += rng.normal(0, 0.001, len(reference))
        alignment = FINDER.find_alignment(FINDER.fingerprint(source), FINDER.fingerprint(reference))
        self.assertIsNotNone(alignment)
        verified = FINDER.verify_waveform(source, reference, alignment)
        self.assertGreater(verified['waveform_score'], 0.99)
        self.assertAlmostEqual(verified['reference_seconds'], delay / FINDER.RATE, places=3)

    def test_silence_does_not_match(self):
        fingerprints = FINDER.fingerprint(np.zeros(24000))
        self.assertEqual(len(fingerprints), 0)
        self.assertIsNone(FINDER.find_alignment(fingerprints, fingerprints))


if __name__ == '__main__':
    unittest.main()
