"""Deployer back end: mission data access, the army roster, base sizes, footprints and placement."""
import json
import math
import random
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from crunch.data.layouts import parse_layouts
from crunch.deploy import parse_base, unit_footprint
from crunch.deploy.arrange import arrange
from crunch.deploy.movement import parse_move, rings
from crunch.deploy.objectives import contact_length, distance_to_region, objective_regions, terrain_pieces, touching
from crunch.deploy.sight import (GO_TO_GROUND_RANGE, HIDDEN_RANGE, Obstacles, cast, piece_crossings, ray_lengths, reaching,
                                 reaching_fans,
                                 visibility)
from crunch.deploy.placement import (clamp, ellipse_polygon, extent, nearest_on_outline, offset_ellipse, overlaps,
                                     random_spot)
from crunch.deploy.roster import roster
from crunch.deploy.territory import territory_line
from crunch.data.missionbook import MissionBook
from crunch.data.missions import parse_deck
from crunch.lists import parse_list
from tests.helpers import FIXTURES, FIXTURE_LIST, fixture_wd


def build_json_dir() -> Path:
    """missions/json/ as `crunch fetch` writes it, from the test fixtures."""
    d = Path(tempfile.mkdtemp())
    deck = parse_deck((FIXTURES / "wahapedia" / "mission_deck.html").read_text(encoding="utf-8"))
    for key, rows in deck.items():
        (d / f"{key}.json").write_text(json.dumps(rows), encoding="utf-8")
    ri = FIXTURES / "rapidingress"
    data = parse_layouts((ri / "terrain-data-11e.js").read_text(encoding="utf-8"),
                         (ri / "measurements-11e.js").read_text(encoding="utf-8"))
    (d / "layouts.json").write_text(json.dumps(data), encoding="utf-8")
    return d


class MissionBookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = build_json_dir()
        cls.book = MissionBook(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_dispositions(self):
        self.assertTrue(self.book.available)
        self.assertEqual(self.book.dispositions,
                         ["Take and Hold", "Purge the Foe", "Disruption", "Reconnaissance", "Priority Assets"])
        self.assertEqual(self.book.disposition("priority ASSETS"), "Priority Assets")
        self.assertIsNone(self.book.disposition("Unknown"))
        self.assertIsNone(self.book.disposition(""))

    def test_layouts_in_either_order(self):
        self.assertEqual([l["id"] for l in self.book.layouts_for("Take and Hold", "Purge the Foe")], ["PF-TH-B"])
        self.assertEqual([l["id"] for l in self.book.layouts_for("Purge the Foe", "Take and Hold")], ["PF-TH-B"])
        self.assertEqual([l["id"] for l in self.book.layouts_for("Take and Hold", "Take and Hold")], ["TH-TH-A"])
        self.assertEqual(self.book.layouts_for("Disruption", "Disruption"), [])

    def test_primary_mission_for_each_side(self):
        self.assertEqual(self.book.primary_mission("Take and Hold", "Take and Hold")["name"], "BATTLEFIELD DOMINANCE")
        self.assertEqual(self.book.primary_mission("Purge the Foe", "Reconnaissance")["name"], "CONSECRATE")
        self.assertIsNone(self.book.primary_mission("Reconnaissance", "Purge the Foe"))    # not in the fixture

    def test_mission_named_by_a_layout_only(self):
        # the fixture has no Unstoppable Force card, but the PF-TH layout names it
        m = self.book.primary_mission("Purge the Foe", "Take and Hold")
        self.assertEqual((m["name"], m["scoring"]), ("Unstoppable Force", []))

    def test_missing_data(self):
        book = MissionBook(self.dir / "nowhere")
        self.assertFalse(book.available)
        self.assertEqual((book.layouts_for("Take and Hold", "Take and Hold"), book.dispositions), ([], []))


class RosterTest(unittest.TestCase):
    def test_leaders_and_support_merge_into_their_unit(self):
        wd = fixture_wd()
        rows = roster(parse_list(FIXTURE_LIST, wd), wd)
        # 5 Intercessors + Captain + Apothecary; 80 + 80 + 70 pts
        r = rows[0]
        self.assertEqual((r.key, r.name, r.models, r.points),
                         ("u2", "Intercessor Squad #1 + Captain + Apothecary", 7, 230))
        self.assertEqual(rows[1].name, "Intercessor Squad #2")
        self.assertEqual(sum(r.points for r in rows), 300)
        self.assertEqual(r.footprint.models, 7)
        # bolt rifles 24", and the attached characters' 18" pistol; melee weapons have no range
        self.assertEqual((r.ranges, rows[1].ranges), ([18.0, 24.0], [24.0]))


class BasesTest(unittest.TestCase):
    def test_parse_base_sizes(self):
        mm = 1 / 25.4
        self.assertEqual((parse_base("40mm").w, parse_base("40mm").h), (40 * mm, 40 * mm))
        b = parse_base("120 x 92mm flying base")
        self.assertEqual((b.w, b.h, b.estimated), (120 * mm, 92 * mm, False))
        self.assertAlmostEqual(parse_base("28.5mm").w, 28.5 * mm)
        self.assertFalse(parse_base("32mm").estimated)
        for text in ("Use model", "", "Unique", "No official base size"):
            with self.subTest(text):
                self.assertTrue(parse_base(text, wounds=12).estimated)
        self.assertLess(parse_base("Use model", 4).w, parse_base("Use model", 16).w)   # bigger for tougher

    def test_single_model_is_its_base(self):
        f = unit_footprint([(parse_base("40mm"), 1)])
        self.assertEqual((f.w, f.h, f.models), (parse_base("40mm").w, parse_base("40mm").w, 1))

    def test_unit_ellipse_grows_with_models_and_spacing(self):
        b = parse_base("32mm")
        f5, f10 = unit_footprint([(b, 5)]), unit_footprint([(b, 10)])
        self.assertAlmostEqual((f5.w + 1) / (f5.h + 1), 1.5, places=6)       # aspect before the outer margin
        self.assertGreater(f10.w * f10.h, f5.w * f5.h)
        # the ellipse holds every base with its 1" spacing: bigger than the bases alone, packed
        self.assertGreater(3.14159 * f10.w * f10.h / 4, 10 * b.area)
        self.assertEqual(f10.description, "10 models: 10x 32mm")
        mixed = unit_footprint([(b, 4), (parse_base("40mm"), 1)])
        self.assertEqual(mixed.description, "5 models: 4x 32mm, 1x 40mm")
        self.assertTrue(unit_footprint([(parse_base("Use model", 10), 2)]).estimated)


class MovementTest(unittest.TestCase):
    def test_parse_move(self):
        self.assertEqual([parse_move(t) for t in ('6"', '20+"', "-", "", '12"')], [6, 20, 0, 0, 12])

    def test_rings(self):
        self.assertEqual(rings(6, True, False, False), [('Move 6"', 6)])
        self.assertEqual(rings(6, False, True, False), [('Advance 9.5"', 9.5)])
        self.assertEqual(rings(6, False, False, True), [('Charge 7"', 7)])          # 2D6 alone, M not added
        self.assertEqual(rings(6, True, False, True), [('Move 6"', 6), ('Move + charge 13"', 13)])
        # advance and charge together: the charge ring becomes the full 10.5" + M
        self.assertEqual(rings(6, True, True, True),
                         [('Move 6"', 6), ('Advance 9.5"', 9.5), ('Advance + charge 16.5"', 16.5)])
        self.assertEqual(rings(0, True, False, False), [])                     # can't move: no ring

    def test_unit_moves_at_its_slowest_model(self):
        wd = fixture_wd()
        rows = roster(parse_list(FIXTURE_LIST, wd), wd)
        self.assertEqual(rows[0].move, 6)


def square(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


class ObjectiveTerrainTest(unittest.TestCase):
    def test_edge_contact_joins_corner_contact_does_not(self):
        a = square(0, 0, 6, 4)
        self.assertTrue(touching(a, square(6, 0, 6, 4)))                 # whole 4" side shared
        self.assertTrue(touching(a, square(6.1, 1, 2, 2)))               # 2" of side, 0.1" gap
        self.assertFalse(touching(a, square(6, 4, 3, 3)))                # corner to corner
        self.assertFalse(touching(a, square(5.7, 3.7, 3, 3)))            # corners overlapping a little
        self.assertFalse(touching(a, square(7, 0, 6, 4)))                # 1" apart
        # the 4" side, plus the 0.15" tolerance reaching onto the edges at each end
        self.assertAlmostEqual(contact_length(square(6, 0, 6, 4), a), 4 + 2 * 0.15, delta=0.05)
        self.assertLess(contact_length(square(6, 4, 3, 3), a), 0.35)    # a corner: just the tolerance

    def test_objective_covers_its_whole_terrain(self):
        lay = {"terrain": [
            {"area": "T1", "footprints": [{"los_points": square(10, 10, 6, 4)}], "objective": 1},
            {"area": "T2", "footprints": [{"los_points": square(16, 10, 4, 4)}]},          # along T1's side
            {"area": "T3", "footprints": [{"los_points": square(20, 14, 3, 3)}]},          # T2's corner only
            {"area": "T4", "footprints": [{"los_points": square(40, 10, 4, 4)},            # two pieces of one
                                          {"los_points": square(44, 10, 4, 4)}], "objective": 2}],
            "objectives": [{"number": 1, "type": "central", "owner": None, "area": "T1", "position": [13, 12]},
                           {"number": 2, "type": "expansion", "owner": None, "area": "T4", "position": [44, 12]}]}
        self.assertEqual(sorted(sorted(p) for p in terrain_pieces(lay)), [["T1", "T2"], ["T3"], ["T4"]])
        r1, r2 = objective_regions(lay)
        self.assertEqual((sorted(r1["areas"]), len(r1["polygons"])), (["T1", "T2"], 2))
        self.assertEqual((r2["areas"], len(r2["polygons"])), (["T4"], 2))

    def test_distance_to_the_objective_terrain(self):
        terrain = [square(10, 0, 4, 4), square(14, 0, 4, 4)]
        unit = ellipse_polygon(2, 2, 2, 2, n=72)                          # 1" radius at (2, 2)
        d, near, far = distance_to_region(unit, terrain)
        self.assertAlmostEqual(d, 7, delta=0.01)                          # 10 - (2 + 1)
        self.assertAlmostEqual(far[0], 10, delta=0.01)
        self.assertEqual(distance_to_region(ellipse_polygon(12, 2, 2, 2), terrain)[0], 0)   # standing on it

    def test_real_layouts(self):
        lay = next(l for l in parse_layouts(
            (FIXTURES / "rapidingress" / "terrain-data-11e.js").read_text(encoding="utf-8"),
            (FIXTURES / "rapidingress" / "measurements-11e.js").read_text(encoding="utf-8"))["layouts"]
            if l["id"] == "TH-TH-A")
        regions = {r["number"]: r for r in objective_regions(lay)}
        self.assertEqual(len(regions[2]["polygons"]), 2)                  # T03: two footprints, one objective
        self.assertEqual(regions[5]["areas"], ["TH-TH-A-T11"])           # T04 only meets T11 at a corner


class SightTest(unittest.TestCase):
    """A ruin footprint 10..20 x 10..20 with a dense wall inside it at x = 16, rays going east."""
    LAYOUT = {"terrain": [
        {"area": "T1", "footprints": [{"los_points": square(10, 10, 10, 10), "obscuring": True}],
         "features": [{"category": "DENSE", "los_points": square(16, 10, 0.5, 4)},       # wall, y 10..14
                      {"category": "LIGHT", "los_points": square(12, 16, 2, 2)}]},   # light: no effect
        {"area": "T2", "footprints": [], "features": [{"category": "DENSE", "los_points": square(40, 28, 1, 6)}]}]}

    def length(self, x, y, allowed=1, max_range=48, hidden=None, dx=1.0):
        import numpy as np
        ob = Obstacles.from_layout(self.LAYOUT)
        return float(ray_lengths(np.array([[x, y]], float), np.array([[dx, 0.0]]), np.array([allowed]),
                                 max_range, ob, hidden)[0])

    def test_hidden_entering_terrain_stops_at_15_or_12_gone_to_ground(self):
        self.assertAlmostEqual(self.length(2, 18), 18)                     # enters at 8", sees through to 18"
        self.assertAlmostEqual(self.length(2, 18, hidden=HIDDEN_RANGE), 15)
        self.assertAlmostEqual(self.length(2, 18, hidden=GO_TO_GROUND_RANGE), 12)

    def test_hidden_terrain_entered_beyond_the_limit_is_not_seen_into(self):
        self.assertAlmostEqual(self.length(40, 18, dx=-1.0), 30)           # west: through... to x=10
        self.assertAlmostEqual(self.length(40, 18, dx=-1.0, hidden=HIDDEN_RANGE), 20)   # its edge, x=20

    def test_hidden_leaves_open_ground_and_own_ruin_alone(self):
        self.assertAlmostEqual(self.length(2, 30, max_range=24, hidden=HIDDEN_RANGE), 24)
        self.assertAlmostEqual(self.length(12, 18, allowed=2, hidden=HIDDEN_RANGE), 48)

    def test_open_ground_goes_to_the_range(self):
        self.assertAlmostEqual(self.length(2, 30, max_range=24), 24)

    def test_board_edge_stops_it(self):
        self.assertAlmostEqual(self.length(50, 30), 10)                    # board is 60" wide

    def test_dense_terrain_cuts_the_ray(self):
        self.assertAlmostEqual(self.length(2, 31), 38)                     # free-standing wall at x=40

    def test_see_into_a_ruin_not_through_it(self):
        self.assertAlmostEqual(self.length(2, 18), 18)                     # enters at x=10, stops at x=20

    def test_dense_wall_inside_the_ruin(self):
        self.assertAlmostEqual(self.length(2, 12), 14)                     # enters at x=10, wall at x=16

    def test_from_inside_a_ruin_it_sees_out_and_into_another(self):
        self.assertAlmostEqual(self.length(12, 18, allowed=2), 48)         # out at x=20, no other ruin

    def test_a_two_piece_area_counts_as_one(self):
        # an L: two footprints of one area sharing the border x = 36; a ray crosses it without stopping
        lay = {"terrain": [{"area": "L", "features": [], "footprints": [
            {"los_points": square(30, 30, 6, 4)}, {"los_points": square(36, 30, 2, 8)}]}]}
        import numpy as np
        ob = Obstacles.from_layout(lay)
        length = float(ray_lengths(np.array([[20.0, 32.0]]), np.array([[1.0, 0.0]]), np.array([1]), 48, ob)[0])
        self.assertAlmostEqual(length, 18)                                 # in at x=30, out at x=38

    def test_a_seam_between_two_pieces_is_not_an_edge(self):
        # the footprints of a piece rarely meet exactly: a 0.1" gap between them is still inside it
        lay = {"terrain": [{"area": "L", "features": [], "footprints": [
            {"los_points": square(30, 30, 6, 4)}, {"los_points": square(36.1, 30, 2, 8)}]}]}
        import numpy as np
        ob = Obstacles.from_layout(lay)
        O, D = np.array([[20.0, 32.0]]), np.array([[1.0, 0.0]])
        self.assertEqual([round(t, 6) for t in piece_crossings(O, D, ob)[0]], [10, 18.1])   # in, out
        self.assertAlmostEqual(float(ray_lengths(O, D, np.array([1]), 48, ob)[0]), 18.1)
        # a real gap (1") between two separate areas: two pieces, the ray stops at the first one's far edge
        lay["terrain"].append({"area": "M", "features": [], "footprints": [{"los_points": square(39.1, 30, 2, 4)}]})
        self.assertAlmostEqual(float(ray_lengths(O, D, np.array([1]), 48, Obstacles.from_layout(lay))[0]), 18.1)

    def test_rays_reaching_a_target(self):
        # a unit at (5, 30) looking east: a target at x 20..24 in the open, another behind the free wall at x=40
        rays = cast(ellipse_polygon(5, 30, 2, 2, n=36), 48, Obstacles.from_layout(self.LAYOUT))
        open_target = square(20, 29, 4, 2)
        reach = reaching(rays, open_target)
        hits = np.isfinite(reach)
        self.assertTrue(hits.any())
        ends = rays.O[hits] + rays.D[hits] * reach[hits][:, None]
        self.assertTrue(all(abs(x - 20) < 1e-6 or abs(y - 29) < 1e-6 or abs(y - 31) < 1e-6 for x, y in ends))
        self.assertFalse(np.isfinite(reaching(rays, square(44, 29, 4, 4))).any())   # behind the wall
        self.assertFalse(np.isfinite(reaching(cast(ellipse_polygon(5, 30, 2, 2, n=36), 10,
                                                    Obstacles.from_layout(self.LAYOUT)), open_target)).any())

    def test_reaching_fans_cover_the_rays_reaching_a_target(self):
        rays = cast(ellipse_polygon(5, 30, 2, 2, n=36), 48, Obstacles.from_layout(self.LAYOUT))
        target = square(20, 29, 4, 2)
        wedges = reaching_fans(rays, target)
        n_rays = int(np.isfinite(reaching(rays, target)).sum())
        self.assertTrue(wedges)
        self.assertEqual(sum(len(w) - 1 for w in wedges), n_rays)            # every reaching ray, once
        for w in wedges:                                                     # from the base to the target
            self.assertTrue(math.dist(w[0], (5, 30)) <= 1.01)
            self.assertTrue(all(19.99 <= x <= 24.01 and 28.99 <= y <= 31.01 for x, y in w[1:]))
        self.assertEqual(reaching_fans(rays, square(44, 29, 4, 4)), [])     # behind the wall: nothing

    def test_visibility_fans_are_polygons_from_the_base(self):
        fans = visibility(ellipse_polygon(5, 30, 2, 2, n=36), 12, Obstacles.from_layout(self.LAYOUT))
        self.assertTrue(fans and all(len(f) > 3 for f in fans))
        for f in fans:
            self.assertTrue(all(math.dist(f[0], p) <= 12 + 1e-6 for p in f[1:]))


class TerritoryTest(unittest.TestCase):
    """A territory: the half of the battlefield that includes a player's deployment zone."""

    @staticmethod
    def layout(edge, zone):
        return {"attacker_edge": edge, "deployment_zones": {"attacker": [zone]}}

    def test_between_the_battlefield_edges(self):
        strip = [(0.14, 0.04), (0.14, 43.96), (18.01, 43.96), (18.01, 0.04)]
        self.assertEqual(territory_line(self.layout("left", strip)), ((30, 0), (30, 44)))
        self.assertEqual(territory_line(self.layout("bottom", [(0, 0), (0, 12), (60, 12), (60, 0)])), ((0, 22), (60, 22)))

    def test_rounded_corner_is_not_a_diagonal(self):
        zone = [(30.02, 13.02), (28.19, 13.21), (26.51, 13.73), (24.98, 14.56), (23.65, 15.65), (22.56, 16.98),
                (21.73, 18.5), (21.21, 20.19), (21.03, 22.02), (0.14, 22.02), (0.14, 0.04), (30.02, 0.04)]
        self.assertEqual(territory_line(self.layout("bottom", zone)), ((0, 22), (60, 22)))

    def test_diagonal_deployment(self):
        # the line runs through the centre, parallel to the zone's slanted edge, from edge to edge
        (x1, y1), (x2, y2) = territory_line(self.layout("left", [(30, 0), (0, 44), (0, 0)]))
        self.assertEqual(sorted([(round(x1, 2), round(y1, 2)), (round(x2, 2), round(y2, 2))]), [(15, 44), (45, 0)])

    def test_unknown(self):
        self.assertIsNone(territory_line({"deployment_zones": {}}))

    def test_every_fixture_layout_has_one(self):
        book = MissionBook(build_json_dir())
        self.assertTrue(book.layouts)
        for lay in book.layouts:
            (x1, y1), (x2, y2) = territory_line(lay)
            self.assertAlmostEqual((x1 + x2) / 2, 30)           # through the centre of the board
            self.assertAlmostEqual((y1 + y2) / 2, 22)


class ArrangeTest(unittest.TestCase):
    TALL, WIDE = (300, 440), (640, 270)                      # the info panel: stacked, side by side

    def arranged(self, n, w=990, h=880):
        return arrange(n, w, h, self.TALL, self.WIDE, chrome=(26, 70))

    def test_three_boards_keep_the_grid(self):
        a = self.arranged(3)                                  # 2 x 2, the info panel in the fourth cell
        self.assertEqual(a.boards, [(0, 0, 495, 440), (495, 0, 495, 440), (0, 440, 495, 440)])
        self.assertEqual((a.info, a.wide), ((495, 440, 495, 440), False))

    def test_two_boards_stack_beside_the_panel(self):
        a = self.arranged(2)
        self.assertEqual(a.boards, [(0, 0, 690, 440), (0, 440, 690, 440)])
        self.assertEqual((a.info, a.wide), ((690, 0, 300, 880), False))
        self.assertGreater(a.scale, self.arranged(3).scale)

    def test_one_board_above_the_panel(self):
        a = self.arranged(1)
        self.assertEqual(a.boards, [(0, 0, 990, 610)])
        self.assertEqual((a.info, a.wide), ((0, 610, 990, 270), True))
        self.assertGreater(a.scale, self.arranged(2).scale)
        tall = self.arranged(1, w=600, h=1000)                # too narrow for the wide panel: stacked, below
        self.assertEqual((tall.boards, tall.info, tall.wide), ([(0, 0, 600, 500)], (0, 500, 600, 500), False))

    def test_small_window_keeps_the_grid(self):
        a = self.arranged(3, 790, 750)                        # the panel 65 short of its height: squeezed
        self.assertEqual((a.boards[1], a.info), ((395, 0, 395, 375), (395, 375, 395, 375)))
        b = self.arranged(3, 790, 700)                        # too short for that: a strip under smaller boards
        self.assertEqual((b.info, b.wide, b.boards[2]), ((0, 430, 790, 270), True, (526, 0, 263, 430)))
        self.assertLess(b.scale, a.scale)

    def test_nothing_overlaps(self):
        for n in range(1, 4):
            for w, h in ((990, 880), (1400, 700), (700, 1000), (800, 800), (1900, 1000)):
                a = self.arranged(n, w, h)
                rects = a.boards + [a.info]
                self.assertEqual(len(a.boards), n)
                for i, (x, y, rw, rh) in enumerate(rects):
                    self.assertTrue(x >= 0 and y >= 0 and x + rw <= w and y + rh <= h, (n, w, h, rects))
                    for x2, y2, w2, h2 in rects[i + 1:]:
                        self.assertTrue(x + rw <= x2 or x2 + w2 <= x or y + rh <= y2 or y2 + h2 <= y, (n, w, h, rects))

    def test_no_board_or_no_room(self):
        self.assertEqual(self.arranged(0).info, (0, 0, 990, 880))            # the panel alone
        a = self.arranged(3, 400, 300)                        # too small for the panel: it still gets a share
        self.assertEqual((len(a.boards), a.info), (3, (200, 0, 200, 300)))


class PlacementTest(unittest.TestCase):
    ZONE = [[0, 0], [12, 0], [12, 44], [0, 44]]              # a 12" deep strip along the left edge

    def test_random_spot_keeps_the_footprint_in_the_zone(self):
        rng = random.Random(1)
        for _ in range(50):
            x, y = random_spot([self.ZONE], 6, 4, rng)
            self.assertTrue(3 <= x <= 9 and 2 <= y <= 42, (x, y))

    def test_new_units_avoid_the_ones_already_placed(self):
        rng = random.Random(3)
        placed = []
        for _ in range(8):                          # eight 3" x 3" units fit easily in the strip
            x, y = random_spot([self.ZONE], 3, 3, rng, avoid=placed)
            self.assertFalse(any(overlaps((x, y, 3, 3), b) for b in placed))
            placed.append((x, y, 3, 3))
        # no room left clear of the others: still placed in the zone
        x, y = random_spot([self.ZONE], 11, 40, rng, avoid=placed)
        self.assertTrue(5.5 <= x <= 6.5 and 20 <= y <= 24)

    def test_too_big_for_the_zone_still_lands_on_the_board(self):
        x, y = random_spot([self.ZONE], 20, 10, random.Random(2))
        self.assertTrue(10 <= x <= 50 and 5 <= y <= 39)

    def test_turned_extent(self):
        self.assertEqual(tuple(round(v, 6) for v in extent(6, 4, 0)), (6, 4))
        self.assertEqual(tuple(round(v, 6) for v in extent(6, 4, 90)), (4, 6))
        w, h = extent(6, 4, 30)
        self.assertTrue(4 < w < 6 and 4 < h < 6)
        self.assertEqual(tuple(round(v, 6) for v in extent(3, 3, 30)), (3, 3))     # a round base doesn't change

    def test_rotation_is_clockwise_seen_from_above(self):
        # the long axis's end at +x (east) turns towards -y (south) on a y-up board
        east = ellipse_polygon(0, 0, 6, 2, 0)[0]
        turned = ellipse_polygon(0, 0, 6, 2, 30)[0]
        self.assertEqual(tuple(round(v, 6) for v in east), (3, 0))
        self.assertAlmostEqual(turned[0], 3 * 0.8660254, places=6)
        self.assertAlmostEqual(turned[1], -1.5, places=6)

    def test_offset_of_a_round_base_is_a_bigger_circle(self):
        for x, y in offset_ellipse(10, 10, 2, 2, 0, 6):
            self.assertAlmostEqual(math.hypot(x - 10, y - 10), 7, places=6)     # 1" radius + 6"

    def test_offset_keeps_the_distance_from_an_ellipse(self):
        outline = ellipse_polygon(30, 22, 8, 4, 30, n=720)
        for p in offset_ellipse(30, 22, 8, 4, 30, 5, n=24):
            self.assertAlmostEqual(nearest_on_outline(p, outline)[0], 5, delta=0.01)

    def test_nearest_point_on_a_footprint(self):
        square = [(0, 0), (4, 0), (4, 4), (0, 4)]
        self.assertEqual(nearest_on_outline((10, 2), square), (6.0, (4.0, 2.0)))
        self.assertEqual(nearest_on_outline((2, 2), square), (0.0, (2, 2)))          # inside

    def test_clamp_bumps_into_the_edges(self):
        self.assertEqual(clamp(-5, 100, 4, 2), (2, 43))
        self.assertEqual(clamp(30, 20, 4, 2), (30, 20))
        self.assertEqual(clamp(70, -1, 1.5, 1.5), (59.25, 0.75))


if __name__ == "__main__":
    unittest.main()
