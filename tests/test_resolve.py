"""Finding the engine's globals in a build we have never seen.

The cases here are the ones that decide whether a wrong address can reach the
rest of the mod. They matter more than the happy path, because a signature that
resolves correctly announces itself and a signature that resolves WRONGLY does
not -- which is exactly how the Restoration Project's eight-byte shift stayed
invisible for a session.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from fallout2_access.memory import resolve


DOC = {
    "exe_sha256": "abc123",
    "signatures": {
        "WINDOW_LIST": {
            "pattern": "FC FE FF A3 ?? ?? ?? ?? 85 C0",
            "operand_offset": 4,
            "address": 0x006ADE58,
        },
    },
    "derived": {
        "EDITOR_WINDOW": {
            "anchor": "WINDOW_LIST",
            "delta": -0xB0,
            "address": 0x006ADDA8,
        },
    },
}


class DeriveTest(unittest.TestCase):
    """Anchor-plus-distance, which is how the addresses no instruction names
    are reached."""

    def test_the_distance_is_applied_to_whatever_the_anchor_resolved_to(self):
        """The point of the scheme: the base moves with the build, the distance
        does not. RPU shifted this block by eight and the gap between the array
        and the entry inside it stayed 0xB0."""
        out, failures = resolve.derive(
            {"WINDOW_LIST": 0x006ADE50}, DOC["derived"])
        self.assertEqual(out["EDITOR_WINDOW"], 0x006ADDA0)
        self.assertEqual(failures, [])

    def test_it_reproduces_the_measured_address_on_the_measured_build(self):
        out, _ = resolve.derive({"WINDOW_LIST": 0x006ADE58}, DOC["derived"])
        self.assertEqual(out["EDITOR_WINDOW"], 0x006ADDA8)

    def test_a_failed_anchor_does_not_fall_back_to_the_recorded_value(self):
        """The whole failure mode, in one test. If the anchor could not be
        found then the neighbourhood is not where it was, which is precisely
        when a fixed distance from it is worthless -- and 0x006ADDA8 is sitting
        right there in the file looking reusable."""
        out, failures = resolve.derive({}, DOC["derived"])
        self.assertNotIn("EDITOR_WINDOW", out)
        self.assertTrue(any("anchor" in f and "EDITOR_WINDOW" in f
                            for f in failures), failures)

    def test_a_malformed_entry_is_reported_rather_than_skipped(self):
        out, failures = resolve.derive(
            {"WINDOW_LIST": 1}, {"BROKEN": {"anchor": "WINDOW_LIST"}})
        self.assertNotIn("BROKEN", out)
        self.assertTrue(failures)


class LoadTest(unittest.TestCase):
    def test_a_missing_file_is_not_an_exception(self):
        self.assertIsNone(resolve.load(
            os.path.join(tempfile.gettempdir(), "no-such-signatures.json")))

    def test_malformed_json_is_not_an_exception(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not json")
            path = fh.name
        try:
            self.assertIsNone(resolve.load(path))
        finally:
            os.unlink(path)


class ShippedFileTest(unittest.TestCase):
    """The signatures that actually ship have to be well formed, because a
    typo in them is only discovered on a build nobody has yet."""

    def setUp(self):
        self.doc = resolve.load()
        if self.doc is None:
            self.skipTest("offsets/signatures.json not present")

    def test_every_signature_has_a_pattern_and_an_operand_offset(self):
        for name, spec in self.doc.get("signatures", {}).items():
            self.assertIn("pattern", spec, name)
            self.assertIn("operand_offset", spec, name)
            self.assertIn("address", spec, name)

    def test_every_pattern_wildcards_exactly_four_operand_bytes(self):
        """An operand is a dword. A pattern that wildcards three bytes or five
        is reading the wrong field out of the match."""
        for name, spec in self.doc.get("signatures", {}).items():
            parts = spec["pattern"].split()
            off = spec["operand_offset"]
            self.assertEqual(parts[off:off + 4], ["??"] * 4, name)

    def test_every_pattern_compiles(self):
        from fallout2_access.memory import scan
        for name, spec in self.doc.get("signatures", {}).items():
            scan.compile_pattern(spec["pattern"])

    def test_derived_entries_agree_with_their_anchors(self):
        """The file records both the anchor arithmetic and the address it
        produced. If those disagree the file was hand-edited, and the version
        that is wrong is the one nobody checks."""
        entries = dict(self.doc.get("signatures", {}))
        derived = self.doc.get("derived", {})
        # An anchor may itself be derived -- the stat table is found through a
        # neighbour, and age and sex are then found through the table -- so the
        # anchor is looked for in both sections rather than only in signatures.
        entries.update(derived)
        for name, spec in derived.items():
            anchor = entries.get(spec["anchor"])
            self.assertIsNotNone(anchor, name)
            self.assertEqual(anchor["address"] + spec["delta"],
                             spec["address"], name)

    def test_no_derived_entry_anchors_to_itself_or_loops(self):
        """A cycle would spin the resolver's fixed point without progressing
        and report both names as orphans, which is a confusing way to say
        "this file is wrong"."""
        derived = self.doc.get("derived", {})
        for name in derived:
            seen = {name}
            at = derived[name]["anchor"]
            while at in derived:
                self.assertNotIn(at, seen, "cycle through {}".format(name))
                seen.add(at)
                at = derived[at]["anchor"]

    def test_every_owner_attribute_really_exists(self):
        """Binding writes module attributes, which no call site can see going
        wrong. A rename would silently stop that global being resolved and
        leave it on its hardcoded value -- the RPU failure again, self
        inflicted. This is the only place that can catch it."""
        import importlib
        for name, pairs in resolve.owners(self.doc).items():
            for module_name, attr in pairs:
                module = importlib.import_module(
                    module_name, "fallout2_access.memory")
                base = attr.split("[")[0]
                self.assertTrue(hasattr(module, base),
                                "{}: {} has no {}".format(
                                    name, module_name, base))

    def test_shared_addresses_feed_every_module_that_reads_them(self):
        """Seven of these are one address read by both the editor and the
        premade screen. Binding one and not the other is how the two would
        disagree about the same table."""
        table = resolve.owners(self.doc)
        for name in ("STAT_TABLE", "CHAR_NAME", "TAG_SKILLS", "TRAITS",
                     "MSG_STAT", "MSG_SKILL", "MSG_TRAIT"):
            self.assertIn(name, table)
            modules = {m for m, _a in table[name]}
            self.assertIn("..game.chargen", modules, name)
            self.assertIn("..game.premade", modules, name)

    def test_the_computed_chargen_addresses_are_derived_not_signatured(self):
        """AGE_ADDR and SEX_ADDR are built from the stat table at import time.
        Signaturing them independently would let the pair disagree on a build
        where the table moved, and disagreeing is worse than either answer."""
        derived = self.doc.get("derived", {})
        for name in ("STAT_AGE", "STAT_SEX"):
            self.assertIn(name, derived)
            self.assertEqual(derived[name]["anchor"], "STAT_TABLE")
        self.assertNotIn("STAT_AGE", self.doc.get("signatures", {}))



class SummaryTest(unittest.TestCase):
    """What the player is told when an address cannot be found."""

    def test_nothing_is_said_when_everything_resolved(self):
        r = resolve.Resolution({"A": 1}, [], True, "abc")
        self.assertIsNone(r.summary())

    def test_a_failure_is_reported_in_one_sentence(self):
        r = resolve.Resolution({}, ["A: no match"], True, "abc")
        said = r.summary()
        self.assertIn("1 address", said)
        self.assertIn("may not be read", said)

    def test_the_count_is_pluralised(self):
        r = resolve.Resolution({}, ["A: x", "B: y"], True, "abc")
        self.assertIn("2 addresses", r.summary())


class ApplyToTest(unittest.TestCase):
    """Writing a resolved address into the module that reads it."""

    def test_a_tuple_entry_is_rebuilt_rather_than_overwritten(self):
        """pointer.py keeps its fallback mirrors in a tuple. Assigning an int
        over the whole tuple replaces a list of candidates with one number,
        and fails later and far from here as "not iterable"."""
        from fallout2_access.game import pointer
        before = pointer.MOUSE_MIRRORS
        try:
            resolve.apply_to("..game.pointer", "MOUSE_MIRRORS[0]", 0x11223344)
            self.assertIsInstance(pointer.MOUSE_MIRRORS, tuple)
            self.assertEqual(pointer.MOUSE_MIRRORS[0], 0x11223344)
            self.assertEqual(len(pointer.MOUSE_MIRRORS), len(before))
        finally:
            pointer.MOUSE_MIRRORS = before

    def test_a_plain_constant_is_assigned(self):
        from fallout2_access.game import screens
        before = screens.MENU_FLAG
        try:
            resolve.apply_to("..game.screens", "MENU_FLAG", 0x55667788)
            self.assertEqual(screens.MENU_FLAG, 0x55667788)
        finally:
            screens.MENU_FLAG = before


class DeriveChainTest(unittest.TestCase):
    """A derived entry whose anchor is itself derived."""

    def test_a_chain_resolves_in_any_order(self):
        spec = {
            "B": {"anchor": "A", "delta": 8},
            "C": {"anchor": "B", "delta": 4},
        }
        out, failures = resolve.derive({"A": 0x1000}, spec)
        self.assertEqual(failures, [])
        self.assertEqual(out["B"], 0x1008)
        self.assertEqual(out["C"], 0x100C)

    def test_a_broken_chain_reports_every_orphan(self):
        spec = {
            "B": {"anchor": "MISSING", "delta": 8},
            "C": {"anchor": "B", "delta": 4},
        }
        out, failures = resolve.derive({}, spec)
        self.assertNotIn("B", out)
        self.assertNotIn("C", out)
        self.assertEqual(len(failures), 2)


if __name__ == "__main__":
    unittest.main()
