#!/usr/bin/env python3
"""Independent structural, outline, shaping, and rasterizer validation.

Usage: python tools/validate_fonts.py --source source-otf --fonts fonts

Verifies the final AFDKO-converted TrueType fonts and the eight-face TTC.
Original CFF source fonts are converted independently at the same tolerance
for outline comparisons; no comparison equates cubic and quadratic points.
Requires afdko, fonttools, freetype-py, uharfbuzz, and opentype-sanitizer.
This script is distributed with the modified font under SIL OFL 1.1.
It reads font files without rewriting them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import string
import unicodedata as ud
from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont, TTCollection
from afdko.otf2ttf import otf_to_ttf
import freetype
import ots
import uharfbuzz as hb

EXPECTED_ASCENT, EXPECTED_DESCENT = 1000, -300
EXPECTED_LINE_HEIGHT = EXPECTED_ASCENT - EXPECTED_DESCENT


def shape(font, text, features=None, language="en"):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    buf.language = language
    hb.shape(font, buf, features or {})
    return [
        (g.codepoint, p.x_advance, p.y_advance, p.x_offset, p.y_offset)
        for g, p in zip(buf.glyph_infos, buf.glyph_positions)
    ]


def coordinates(font, name):
    points, ends, flags = font["glyf"][name].getCoordinates(font["glyf"])
    return list(points), list(ends), list(flags)


def bounds(font, name):
    glyph = font["glyf"][name]
    glyph.recalcBounds(font["glyf"])
    if not glyph.numberOfContours:
        return None
    return [glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax]


def independent_conversion(path, max_error):
    font = TTFont(path, recalcTimestamp=False)
    otf_to_ttf(font, max_err=max_error, post_format=2.0, reverse_direction=True)
    data = BytesIO()
    font.save(data)
    data.seek(0)
    return TTFont(data, recalcTimestamp=False)


def normalized_table(font, tag):
    data = font.getTableData(tag)
    if tag == "head":
        # Serialization/container checksum and build timestamp are not
        # outline/layout content and may differ between equivalent builds.
        data = data[:8] + b"\x00" * 4 + data[12:28] + b"\x00" * 8 + data[36:]
    return data


def compare_payloads(a, b):
    atags, btags = set(a.reader.keys()), set(b.reader.keys())
    different = sorted(atags ^ btags)
    for tag in sorted(atags & btags):
        if normalized_table(a, tag) != normalized_table(b, tag):
            different.append(tag)
    return different


def validate(original_path, modified_path, intermediate_path, max_error):
    original = TTFont(original_path, recalcTimestamp=False)
    modified = TTFont(modified_path, recalcTimestamp=False)
    reference = independent_conversion(original_path, max_error)
    conversion_reference = independent_conversion(intermediate_path, max_error)
    source_bytes, final_bytes = original_path.read_bytes(), modified_path.read_bytes()
    ohb, mhb = hb.Font(hb.Face(source_bytes)), hb.Font(hb.Face(final_bytes))
    checks, failures = {}, []

    def check(name, result):
        checks[name] = bool(result)
        if not result:
            failures.append(name)

    try:
        ots_result = ots.sanitize(str(modified_path), check=True, capture_output=True)
        check("ots", ots_result.returncode == 0)
        ots_messages = (ots_result.stdout + ots_result.stderr).decode("utf-8", "replace").strip()
    except Exception as exc:
        check("ots", False)
        ots_messages = str(exc)

    check("final_is_TrueType_glyf_not_CFF", "glyf" in modified and "CFF " not in modified and modified.sfntVersion == "\x00\x01\x00\x00")
    conversion_differences = compare_payloads(conversion_reference, modified)
    check("final_matches_independent_AFDKO_conversion", not conversion_differences)
    glyphs = original.getGlyphOrder()
    ocmap, mcmap = original.getBestCmap(), modified.getBestCmap()
    check("glyph_order_preserved", glyphs == modified.getGlyphOrder())
    check("all_advance_widths_preserved", all(original["hmtx"][n][0] == modified["hmtx"][n][0] for n in glyphs))
    bearing_failures = []
    for n in glyphs:
        ob, mb = bounds(reference, n), bounds(modified, n)
        change = mb[0] - ob[0] if ob and mb else 0
        if modified["hmtx"][n][1] != reference["hmtx"][n][1] + change:
            bearing_failures.append(n)
    check("bearing_offsets_match_CFF_conversion_convention", not bearing_failures)
    check("all_cmap_subtables_preserved", original["cmap"].compile(original) == modified["cmap"].compile(modified))
    check("GSUB_preserved", original["GSUB"].compile(original) == modified["GSUB"].compile(modified))
    if modified_path.name.startswith("IntelOneMono-"):
        display_ids = {1, 2, 4, 6, 16, 17, 18, 21, 22, 25}
        def display_names(font):
            return sorted((n.nameID, n.platformID, n.platEncID, n.langID, n.toUnicode())
                          for n in font["name"].names if n.nameID in display_ids)
        check("original_display_family_and_style_names_preserved", display_names(original) == display_names(modified))
    check("UPM_1000", modified["head"].unitsPerEm == 1000)
    check("real_xheight_plus_45", bounds(modified, "x")[3] == bounds(reference, "x")[3] + 45 == modified["OS/2"].sxHeight)
    check("cap_height_655", modified["OS/2"].sCapHeight == original["OS/2"].sCapHeight == 655)
    check("ascender_and_dot_tops_preserved", all(bounds(modified, n)[3] == bounds(reference, n)[3] for n in "bdfhijktl"))
    check("descender_bottoms_preserved", all(bounds(modified, n)[1] == bounds(reference, n)[1] for n in "gjpqy"))
    check("plain_lowercase_body_tops_plus_45", all(bounds(modified, n)[3] == bounds(reference, n)[3] + 45 for n in "acegmnopqrsuvwxyz"))

    lower_targets = {n for cp, n in ocmap.items() if ud.category(chr(cp)) == "Ll" and cp != 0x2139}
    lower_targets |= {"i.dot", "w_w_w.liga"}
    cell_targets = {n for cp, n in ocmap.items() if 0x2500 <= cp <= 0x259F or 0xE0A0 <= cp <= 0xE0D7}
    protected = set(glyphs) - lower_targets - cell_targets
    altered_protected = [n for n in sorted(protected) if coordinates(reference, n) != coordinates(modified, n)]
    check("all_non_target_outlines_match_independently_converted_official_CFF", not altered_protected)

    hhea, os2 = modified["hhea"], modified["OS/2"]
    check("preferred_hhea_and_typo_metrics",
          (hhea.ascent, hhea.descent, hhea.lineGap) == (os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap)
          == (EXPECTED_ASCENT, EXPECTED_DESCENT, 0))
    check("USE_TYPO_METRICS_set", os2.fsSelection & (1 << 7))
    check("Win_metrics_1140_360", (os2.usWinAscent, os2.usWinDescent) == (1140, 360))
    all_bounds = {n: bounds(modified, n) for n in glyphs}
    outside_win = {n: b for n, b in all_bounds.items() if b and (b[1] < -360 or b[3] > 1140)}
    check("all_glyph_bounds_fit_Win_metrics", not outside_win)
    cell_bounds = {hex(cp): bounds(modified, mcmap[cp]) for cp in (0x2500, 0x2502, 0x2503, 0x2580, 0x2584, 0x2588, 0x258C, 0x2590, 0xE0B0, 0xE0B2)}
    check("full_block_matches_cell", cell_bounds["0x2588"] == [0, EXPECTED_DESCENT, 614, EXPECTED_ASCENT])
    def covers_cell(cp):
        _, ymin, _, ymax = cell_bounds[hex(cp)]
        return ymin <= EXPECTED_DESCENT and ymax >= EXPECTED_ASCENT
    check("box_vertical_lines_cover_cell", all(covers_cell(cp) for cp in (0x2502, 0x2503)))
    check("powerline_arrows_cover_cell", all(covers_cell(cp) for cp in (0xE0B0, 0xE0B2)))

    face = freetype.Face(str(modified_path))
    rasterizer_failures = []
    for size in (12, 16, 24, 32):
        face.set_pixel_sizes(0, size)
        for gid in range(face.num_glyphs):
            try:
                face.load_glyph(gid, freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_PEDANTIC)
            except Exception as exc:
                rasterizer_failures.append({"ppem": size, "glyph": glyphs[gid], "error": str(exc)})
    check("FreeType_every_glyph_12_16_24_32_ppem", not rasterizer_failures)
    check("FreeType_preferred_height", face.height == EXPECTED_LINE_HEIGHT)

    samples = [
        ("def choose_route(routes, forecast): return best.path", "en"),
        ("Il1| O0o aegs tfij xy []{}() +-*/_", "en"),
        ("!= !== == === => -> <- <= >= <=> <-> := www 303", "en"),
        ("á é ñ ö ü č ắ ậ ộ ǰ", "en"),
        ("İ I ı i i\u0301 j\u0301 i\u0307", "tr"),
        ("i\u0307\u0301 I\u0301 J\u0301", "lt"),
        ("a\u0306\u0301 a\u0323\u0306 o\u031b\u0301 o\u0323\u0302", "vi"),
        ("e\u0301 e\u0307 p\u0301 p\u0307 j\u0301 x\u0323", "en"),
    ]
    feature_sets = [{}, {"ss01": 1}, {"ss01": 1, "ss02": 1}, {"ss03": 1}, {"ss01": 1, "ss03": 1}, {"ss04": 1}]
    shaping_failures = []
    for text, language in samples:
        for features in feature_sets:
            before = shape(ohb, text, features, language)
            after = shape(mhb, text, features, language)
            # Glyph identities and advance widths must match. Combining-mark
            # offsets may move intentionally with the modified body height.
            if [r[:3] for r in before] != [r[:3] for r in after] or any(r[0] == 0 for r in after):
                shaping_failures.append({"text": text, "language": language, "features": features, "before": before, "after": after})
    check("sample_shaping_glyphs_and_advances_preserved", not shaping_failures)
    mark_position_probes = {}
    for text, expected_y_delta in [("p\u0303", 45), ("j\u0301", 45), ("P\u0303", 0), ("x\u0323", 0)]:
        before, after = shape(ohb, text), shape(mhb, text)
        found = (len(before) == len(after) == 2 and before[-1][1] == after[-1][1] == 0)
        delta = after[-1][4] - before[-1][4] if found else None
        mark_position_probes[text] = {"expected_y_delta": expected_y_delta, "observed_y_delta": delta}
    check("live_mark_attachment_top_moves_bottom_and_caps_stay", all(v["expected_y_delta"] == v["observed_y_delta"] for v in mark_position_probes.values()))

    canonical_count, canonical_failures, inherited_canonical_failures = 0, [], []
    for cp in ocmap:
        text = chr(cp)
        decomp = ud.normalize("NFD", text)
        if text == decomp or not all(ord(c) in ocmap for c in decomp):
            continue
        canonical_count += 1
        src_equal = shape(ohb, text) == shape(ohb, decomp)
        dst_equal = shape(mhb, text) == shape(mhb, decomp)
        if not dst_equal:
            record = {"codepoint": f"U+{cp:04X}", "text": text, "nfd": decomp}
            (inherited_canonical_failures if not src_equal else canonical_failures).append(record)
    check("no_new_canonical_equivalence_failures", not canonical_failures)

    feature_effects = {}
    for name, text, features in [
        ("ss01", "!= == -> <=", {"ss01": 1}),
        ("ss02", "<= >=", {"ss01": 1, "ss02": 1}),
        ("ss03", "www", {"ss03": 1}),
        ("ss04", "303", {"ss04": 1}),
    ]:
        feature_effects[name] = shape(mhb, text) != shape(mhb, text, features)
    check("all_requested_stylistic_sets_effective", all(feature_effects.values()))

    return {
        "file": modified_path.name,
        "sha256": hashlib.sha256(final_bytes).hexdigest(),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "checks": checks,
        "failures": failures,
        "glyph_count": len(glyphs),
        "unicode_entries": len(mcmap),
        "protected_unchanged_glyphs_checked": len(protected),
        "altered_protected_glyphs": altered_protected,
        "independent_conversion_different_tables": conversion_differences,
        "AFDKO_max_error": max_error,
        "AFDKO_post_format": 2.0,
        "AFDKO_reverse_direction": True,
        "bearing_offset_failures": bearing_failures,
        "ots_message": ots_messages,
        "rasterizer_loads": face.num_glyphs * 4,
        "rasterizer_failures": rasterizer_failures,
        "canonical_pairs_tested": canonical_count,
        "new_canonical_failures": canonical_failures,
        "inherited_canonical_failures": inherited_canonical_failures,
        "shaping_sample_configurations": len(samples) * len(feature_sets),
        "shaping_failures": shaping_failures,
        "mark_position_probes": mark_position_probes,
        "stylistic_set_effects": feature_effects,
        "cell_bounds": cell_bounds,
        "outside_Win_bounds": outside_win,
        "real_xheight": bounds(modified, "x")[3],
        "recorded_xheight": modified["OS/2"].sxHeight,
        "preferred_line_height": face.height,
        "Win_line_height": os2.usWinAscent + os2.usWinDescent,
    }


def validate_collection(collection_path, font_paths):
    """Verify the collection independently of the individual TTF tests."""
    collection = TTCollection(collection_path, lazy=False, shareTables=False)
    expected = {TTFont(p)["name"].getDebugName(6): p for p in font_paths}
    checks, failures = {}, []
    def check(name, result):
        checks[name] = bool(result)
        if not result:
            failures.append(name)
    check("TTC_signature", collection_path.read_bytes()[:4] == b"ttcf")
    check("exactly_eight_faces", len(collection.fonts) == len(font_paths) == 8)
    ps_names = [font["name"].getDebugName(6) for font in collection.fonts]
    check("unique_original_PostScript_names", len(set(ps_names)) == 8 and set(ps_names) == set(expected))
    face_results = []
    for index, font in enumerate(collection.fonts):
        ps = font["name"].getDebugName(6)
        source = TTFont(expected[ps], recalcTimestamp=False)
        differing_tables = compare_payloads(font, source)
        ft = freetype.Face(str(collection_path), index=index)
        render_failures = []
        for ppem in (12, 16, 24, 32):
            ft.set_pixel_sizes(0, ppem)
            for gid in range(ft.num_glyphs):
                try:
                    ft.load_glyph(gid, freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_PEDANTIC)
                except Exception as exc:
                    render_failures.append({"ppem": ppem, "gid": gid, "error": str(exc)})
        ft_ps = ft.postscript_name.decode("ascii")
        matching = not differing_tables
        load_ok = not render_failures and ft.num_faces == 8 and ft.num_glyphs == len(source.getGlyphOrder()) and ft_ps == ps
        check(f"face_{index}_table_payloads_match_TTF", matching)
        check(f"face_{index}_FreeType_all_glyphs_all_sizes", load_ok)
        check(f"face_{index}_FreeType_preferred_height", ft.height == EXPECTED_LINE_HEIGHT)
        face_results.append({
            "index": index, "PostScript_name": ps,
            "family": font["name"].getBestFamilyName(),
            "subfamily": font["name"].getBestSubFamilyName(),
            "source_ttf": expected[ps].name,
            "different_tables": differing_tables,
            "rasterizer_loads": ft.num_glyphs * 4,
            "rasterizer_failures": render_failures,
            "FreeType_num_faces": ft.num_faces,
            "FreeType_glyph_count": ft.num_glyphs,
            "preferred_line_height": ft.height,
        })
    try:
        result = ots.sanitize(str(collection_path), check=True, capture_output=True)
        check("OTS_collection", result.returncode == 0)
        ots_message = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
    except Exception as exc:
        check("OTS_collection", False)
        ots_message = str(exc)
    return {
        "file": collection_path.name,
        "sha256": hashlib.sha256(collection_path.read_bytes()).hexdigest(),
        "checks": checks, "failures": failures,
        "face_count": len(collection.fonts), "faces": face_results,
        "ots_message": ots_message,
        "rasterizer_loads": sum(f["rasterizer_loads"] for f in face_results),
        "comparison_note": "All table payloads compared; only head checksumAdjustment and modified timestamp are normalized.",
    }


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "source-otf")
    parser.add_argument("--fonts", "--modified", dest="fonts", type=Path, default=root / "fonts")
    parser.add_argument("--intermediate", type=Path, default=root / "intermediate-otf")
    parser.add_argument("--collection", type=Path, default=root / "collection" / "IntelOneMono.ttc")
    parser.add_argument("--max-error", type=float, default=0.1)
    parser.add_argument("--report", type=Path, default=root / "Validation.json")
    args = parser.parse_args()
    fonts = sorted(args.fonts.glob("*.ttf"))
    if len(fonts) != 8:
        raise SystemExit("Expected eight final static TTF files")
    results = []
    for path in fonts:
        source = args.source / path.with_suffix(".otf").name
        intermediate = args.intermediate / path.with_suffix(".otf").name
        result = validate(source, path, intermediate, args.max_error)
        results.append(result)
        print(path.name, "PASS" if not result["failures"] else "FAIL", result["failures"], flush=True)
    ttc_result = validate_collection(args.collection, fonts)
    print(args.collection.name, "PASS" if not ttc_result["failures"] else "FAIL", ttc_result["failures"], flush=True)
    failures = sum(len(r["failures"]) for r in results) + len(ttc_result["failures"])
    report = {
        "family": TTFont(fonts[0])["name"].getBestFamilyName(),
        "validation_date": "2026-11-23",
        "all_checks_passed": failures == 0,
        "total_failed_checks": failures,
        "total_TTF_rasterizer_loads": sum(r["rasterizer_loads"] for r in results),
        "total_TTC_rasterizer_loads": ttc_result["rasterizer_loads"],
        "limitations": [
            "No physical macOS or Windows installation was tested; application line-height overrides remain application-dependent.",
            f"Preferred hhea/typo line-height is {EXPECTED_LINE_HEIGHT / 1000:.2f} em, while legacy applications reading Win metrics may use 1.50 em.",
            "All standalone glyph bounds fit the Win clipping metrics; arbitrary stacked combining marks may exceed those bounds or overlap at compact spacing.",
            "The original font supports only selected GPOS base/mark combinations; those source limitations remain.",
            "AFDKO otf2ttf does not preserve CFF hinting as TrueType hinting; these final TTFs have converter-generated unhinted outlines.",
        ],
        "fonts": results,
        "collection": ttc_result,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Total failures:", failures, flush=True)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
