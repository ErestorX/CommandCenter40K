import struct
import unittest
import zlib

import numpy as np

try:
    from command_center.ui.translucent import polygon_mask, png
    HAVE_TK = True
except ImportError:          # some Linux Pythons ship without tkinter
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "tkinter not available")
class PolygonMaskTest(unittest.TestCase):
    def test_square(self):
        mask = polygon_mask([[2, 1, 6, 1, 6, 4, 2, 4]], 8, 6)
        self.assertEqual(mask.shape, (6, 8))
        want = np.zeros((6, 8), bool)
        want[1:4, 2:6] = True
        self.assertTrue((mask == want).all())

    def test_triangle_covers_half_its_box(self):
        mask = polygon_mask([[0, 0, 100, 0, 0, 100]], 100, 100)
        self.assertAlmostEqual(mask.mean(), 0.5, delta=0.01)
        self.assertTrue(mask[10, 10])
        self.assertFalse(mask[90, 90])

    def test_overlapping_polygons_are_a_union(self):
        a, b = [0, 0, 6, 0, 6, 6, 0, 6], [4, 4, 10, 4, 10, 10, 4, 10]
        mask = polygon_mask([a, b], 10, 10)
        self.assertEqual(int(mask.sum()), 36 + 36 - 4)             # the part they share counts once
        self.assertTrue(mask[5, 5])

    def test_what_leaves_the_image_is_cut(self):
        mask = polygon_mask([[-5, -5, 3, -5, 3, 3, -5, 3], [50, 50, 60, 50, 60, 60]], 8, 8)
        self.assertEqual(int(mask.sum()), 9)
        self.assertEqual(int(polygon_mask([[1, 1, 5, 5]], 8, 8).sum()), 0)       # not a polygon


@unittest.skipUnless(HAVE_TK, "tkinter not available")
class PngTest(unittest.TestCase):
    def test_pixels_come_back(self):
        rgba = np.zeros((3, 5, 4), np.uint8)
        rgba[1, 2] = (201, 71, 75, 128)
        data = png(rgba)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">IIBB", data[16:26]), (5, 3, 8, 6))      # width, height, 8 bits, RGBA
        size = struct.unpack(">I", data[33:37])[0]
        self.assertEqual(data[37:41], b"IDAT")
        lines = np.frombuffer(zlib.decompress(data[41:41 + size]), np.uint8).reshape(3, 1 + 5 * 4)
        self.assertTrue((lines[:, 0] == 0).all())
        self.assertTrue((lines[:, 1:].reshape(3, 5, 4) == rgba).all())


if __name__ == "__main__":
    unittest.main()
