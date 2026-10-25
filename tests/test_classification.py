import unittest

try:
    from tools.classify_combinations import ruled_out
except ImportError:
    ruled_out = None


@unittest.skipIf(ruled_out is None, 'Install requirements.txt for classification tools')
class ClassificationTests(unittest.TestCase):
    def test_explicit_and_unsuppressed_fan_implications(self):
        self.assertIsNotNone(ruled_out(((8018,1),), 'opened'))
        self.assertIsNotNone(ruled_out(((8075,1),(8045,1)), 'closed'))
        self.assertIsNotNone(ruled_out(((8045,1),), 'ron'))
        self.assertIsNotNone(ruled_out(((8063,1),), 'tsumo'))
        self.assertIsNotNone(ruled_out(((8042,1),), 'closed'))
        self.assertIsNotNone(ruled_out(((8042,1),), 'tsumo'))

    def test_suppressed_fans_do_not_create_false_negatives(self):
        for fan in (8003,8005,8006,8011,8018,8019,8033,8083,8084,8085):
            self.assertIsNone(ruled_out(((fan,1),), 'closed'))
        self.assertIsNone(ruled_out(((8055,1),), 'tsumo'))
        self.assertIsNone(ruled_out(((8085,1),), 'ron'))
        self.assertIsNone(ruled_out(((8085,1),), 'tsumo'))


if __name__ == '__main__':
    unittest.main()
