import unittest

from assistant.modern_widgets import rounded_rectangle_points


class RoundedWidgetTests(unittest.TestCase):
    def test_rounded_rectangle_has_smooth_corner_points(self):
        points = rounded_rectangle_points(0, 0, 100, 50, 12)
        self.assertEqual(len(points), 56)
        self.assertTrue(all(isinstance(value, (int, float)) for value in points))

    def test_radius_is_clamped_to_half_the_short_side(self):
        points = rounded_rectangle_points(0, 0, 40, 20, 100)
        self.assertEqual(len(points), 56)
        xs = points[0::2]
        ys = points[1::2]
        self.assertGreaterEqual(min(xs), 0)
        self.assertLessEqual(max(xs), 40)
        self.assertGreaterEqual(min(ys), 0)
        self.assertLessEqual(max(ys), 20)

    def test_zero_radius_returns_rectangle_corners(self):
        self.assertEqual(
            rounded_rectangle_points(2, 3, 12, 13, 0),
            [2, 3, 12, 3, 12, 13, 2, 13],
        )


if __name__ == "__main__":
    unittest.main()
