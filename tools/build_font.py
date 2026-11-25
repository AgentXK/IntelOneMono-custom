#!/usr/bin/env python3
"""Build the custom Intel One Mono with a raised x-height through Adobe AFDKO.

Pipeline: original CFF OTF -> edited CFF OTF -> afdko.otf2ttf -> final TTF
          -> afdko.otf2otc -> eight-face TTC.

No TTF outline editing or hinting pass follows otf2ttf. Original display,
style and PostScript names are retained at the user's request. Original
copyright, license and Reserved Font Name provisions remain applicable.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import subprocess
import sys
import unicodedata
from pathlib import Path

from fontTools.misc.roundTools import otRound
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen, replayRecording
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTCollection, TTFont

from cff_components import classify, splitContours

FAMILY = "Intel One Mono"
VERSION = "1.506"
BUILD_DATE = "2026-11-25"
REGULAR_XHEIGHT = 500
DELTA = REGULAR_XHEIGHT - 465  # Upstream Regular and Italic x-height
# Add the extra line space above the baseline so vertical box strokes still
# fit the existing Windows clipping descent of 360 units.
ASCENT, DESCENT = 1000, -300
LINE_HEIGHT = ASCENT - DESCENT
WIN_ASCENT, WIN_DESCENT = 1140, 360
MAX_ERROR = 0.1
STYLES = ["Regular", "Italic", "Light", "LightItalic", "Medium", "MediumItalic", "Bold", "BoldItalic"]
ASCENDERS = {
    "b", "d", "f", "h", "k", "l", "t", "dcroat", "uni1E29", "hbar",
    "lslash", "germandbls", "uni0163", "tbar", "eth", "thorn",
}
DOTTED = {"i", "j", "iogonek"}
PROTECTED_MIDDLE = {"e", "ae", "oe", "uni0259"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def body_rise(y: float, xheight: float, guard: float, middle: bool) -> float:
    low, high = guard, xheight - guard
    if y <= low:
        return 0.0
    if y >= high:
        return float(DELTA)
    if middle:
        center, half = xheight * 0.505, guard * 0.58
        a, b = max(low + 8, center - half), min(high - 8, center + half)
        if y < a:
            return 0.5 * DELTA * ease((y - low) / (a - low))
        if y <= b:
            return 0.5 * DELTA
        return 0.5 * DELTA * (1 + ease((y - b) / (high - b)))
    return DELTA * ease((y - low) / (high - low))


def glyph_rise(y: float, name: str, top: float, xheight: float, guard: float) -> float:
    if name in ASCENDERS and y > xheight + 12:
        start = xheight + 12
        end = min(top, max(top - guard, start + DELTA * 1.65))
        if y >= end:
            return 0.0
        return DELTA * (1 - ease((y - start) / (end - start)))
    return body_rise(y, xheight, guard, name in PROTECTED_MIDDLE)


def cell_y(y: float, box: bool) -> float:
    old_center, new_center = 330.0, (ASCENT + DESCENT) / 2
    if not box:
        return new_center + (y - old_center) * LINE_HEIGHT / 1380.0
    d = y - old_center
    if abs(d) <= 140:
        return new_center + d
    half = LINE_HEIGHT / 2
    return new_center + math.copysign(140 + (abs(d) - 140) * (half - 140) / (690 - 140), d)


def record_glyph(font: TTFont, name: str) -> list:
    pen = RecordingPen()
    font.getGlyphSet()[name].draw(pen)
    return pen.value


def record_bounds(record: list | tuple) -> tuple | None:
    pen = BoundsPen(None)
    replayRecording(record, pen)
    return pen.bounds


def map_contour(contour: tuple, point_map) -> list:
    return [(operation, tuple(point_map(*point) for point in points)) for operation, points in contour]


def raise_s_contour(contour: tuple, slope: float) -> list:
    """Lift both edges of the s spine together instead of stretching across it."""
    bottom, lower_turn, spine, upper_turn, top = (DELTA * i / 4 for i in range(5))
    # On-curve points in the upstream 1.5.0 s contour (also used in accented s).
    profile = (
        ("moveTo", lower_turn),
        ("curveTo", spine), ("lineTo", spine), ("curveTo", upper_turn),  # upper spine edge
        ("curveTo", top), ("curveTo", top), ("lineTo", top),
        ("curveTo", top), ("curveTo", upper_turn),  # upper terminal and bowl
        ("curveTo", spine), ("lineTo", spine), ("curveTo", lower_turn),  # lower spine edge
        ("curveTo", bottom), ("curveTo", bottom), ("lineTo", bottom),
        ("curveTo", bottom), ("curveTo", lower_turn),  # lower terminal and bowl
        ("closePath", bottom),
    )
    if tuple(op for op, _ in contour) != tuple(op for op, _ in profile):
        raise ValueError("Unexpected contour structure for the upstream lowercase s")

    updated = []
    previous_rise = lower_turn
    for (op, points), (_, rise) in zip(contour, profile, strict=True):
        # Cubic handles follow the nearer endpoint, preserving the tangent at
        # both joins. Use the same italic shear as the other lowercase glyphs.
        rises = (previous_rise, rise, rise) if op == "curveTo" else (rise,) if points else ()
        updated.append((op, tuple((x + dy * slope, y + dy)
                                  for (x, y), dy in zip(points, rises, strict=True))))
        previous_rise = rise
    return updated


def preserve_names_update_metadata(font: TTFont, style: str) -> None:
    table = font["name"]
    replacement = {
        3: f"{VERSION};XHED;IntelOneMono-{style};XH{REGULAR_XHEIGHT}LH{LINE_HEIGHT}Custom{BUILD_DATE.replace('-', '')}",
        5: f"Version {VERSION}; Custom XH{REGULAR_XHEIGHT} LH{LINE_HEIGHT}; AFDKO otf2ttf",
        10: (
            "User-requested custom edit of Intel One Mono 1.5.0. Original family, "
            f"style and PostScript names retained. Regular/Italic x-height {REGULAR_XHEIGHT}; "
            f"all weights raised {DELTA} units to preserve original weight differences. "
            "The lowercase s spine retains its original weight. "
            f"Preferred line height {LINE_HEIGHT}/1000 em. Edited CFF outlines exported by "
            "Adobe AFDKO otf2ttf, without TrueType hinting. Not an official Intel "
            "release. Original OFL and Reserved Font Name provisions still apply."
        ),
    }
    table.names = [item for item in table.names if item.nameID not in replacement]
    for name_id, value in replacement.items():
        table.setName(value, name_id, 3, 1, 0x409)
        table.setName(value, name_id, 1, 0, 0)
    original_copyright = table.getDebugName(0) or ""
    table.names = [item for item in table.names if item.nameID != 0]
    for platform, encoding, language in ((3, 1, 0x409), (1, 0, 0)):
        table.setName(original_copyright + "; Custom geometric modifications 2026.",
                      0, platform, encoding, language)
    top = font["CFF "].cff.topDictIndex[0]
    top.version = VERSION
    # Leave CFF fontNames/FullName/FamilyName and all name-table identity
    # records unchanged; description/version identify the custom edit.
    font["head"].fontRevision = float(VERSION)
    font["OS/2"].achVendID = "XHED"


def edit_cff(source: Path, ttf_reference: Path, destination: Path) -> dict:
    original = TTFont(source, recalcTimestamp=False)
    font = TTFont(source, recalcBBoxes=True, recalcTimestamp=False)
    reference = TTFont(ttf_reference)
    style = source.stem.removeprefix("IntelOneMono-")
    order, cmap = original.getGlyphOrder(), original.getBestCmap()
    assert set(order) == set(reference.getGlyphOrder())
    assert cmap == reference.getBestCmap()
    records = {name: record_glyph(original, name) for name in order}
    bounds = {name: record_bounds(record) for name, record in records.items()}
    xheight = original["OS/2"].sxHeight
    slope = math.tan(math.radians(-original["post"].italicAngle))
    lower = {name for cp, name in cmap.items() if unicodedata.category(chr(cp)) == "Ll" and cp != 0x2139}
    lower |= {"i.dot", "w_w_w.liga"}
    assert len(lower) == 227
    guard = min(y for x, y in reference["glyf"]["i"].coordinates if 0 < y < xheight / 2)
    guard = float(max(40, min(135, guard)))
    top = font["CFF "].cff.topDictIndex[0]
    private = top.Private
    changed, composite_names, cells, placement_exceptions = [], [], [], []
    protected_s_glyphs = []

    def write_charstring(name: str, record: list) -> None:
        # A CFF width operand is relative to nominalWidthX, not absolute.
        width = font["hmtx"][name][0] - private.nominalWidthX
        pen = T2CharStringPen(width, None, roundTolerance=0)
        replayRecording(record, pen)
        top.CharStrings[name] = pen.getCharString(private=private, globalSubrs=font["CFF "].cff.GlobalSubrs)
        new_bounds = record_bounds(record)
        if new_bounds:
            advance, old_lsb = original["hmtx"][name]
            font["hmtx"][name] = (advance, old_lsb + otRound(new_bounds[0]) - otRound(bounds[name][0]))

    for name in order:
        if name not in lower:
            continue
        contours = splitContours(records[name])
        is_composite = reference["glyf"][name].isComposite()
        if is_composite:
            ownership = classify(original, reference, name, records)
            base_name = reference["glyf"][name].components[0].glyphName
            composite_names.append(name)
        else:
            ownership = [dict(component_name=name, is_base=True, dx=0, dy=0,
                              actual_transform=(1, 0, 0, 1, 0, 0), translation_correction=(0, 0)) for _ in contours]
            base_name = name
        updated = []
        for contour, owner in zip(contours, ownership):
            component_name, dx, dy = owner["component_name"], owner["dx"], owner["dy"]
            assert tuple(owner["actual_transform"][:4]) == (1, 0, 0, 1)
            correction = tuple(owner["translation_correction"])
            if correction != (0, 0):
                placement_exceptions.append({"glyph": name, "component": component_name, "correction": correction})
            if owner["is_base"]:
                if component_name == "s":
                    updated.extend(raise_s_contour(contour, slope))
                    protected_s_glyphs.append(name)
                    continue
                points = [point for operation, operands in contour for point in operands]
                keep_dot = component_name in DOTTED and min(y - dy for x, y in points) > xheight + 40
                component_top = bounds[component_name][3]
                def transform(x, y):
                    rise = 0 if keep_dot else glyph_rise(y - dy, component_name, component_top, xheight, guard)
                    return x + slope * rise, y + rise
            else:
                rise = 0
                if base_name not in ASCENDERS and bounds[component_name][1] + dy > xheight:
                    rise = DELTA
                if name == "ldot" and component_name == "middotcat":
                    rise = otRound(DELTA / 2)
                shift_x = otRound(slope * rise)
                def transform(x, y):
                    return x + shift_x, y + rise
            updated.extend(map_contour(contour, transform))
        write_charstring(name, updated)
        changed.append(name)

    for cp, name in sorted(cmap.items()):
        if not (0x2500 <= cp <= 0x259F or 0xE0A0 <= cp <= 0xE0D7):
            continue
        is_box = 0x2500 <= cp <= 0x257F and cp not in {0x2571, 0x2572, 0x2573}
        updated = []
        for contour in splitContours(records[name]):
            updated.extend(map_contour(contour, lambda x, y: (x, cell_y(y, is_box))))
        write_charstring(name, updated)
        cells.append(name)

    anchors_changed = 0
    for lookup in font["GPOS"].table.LookupList.Lookup:
        assert lookup.LookupType == 4
        for subtable in lookup.SubTable:
            for name, record in zip(subtable.BaseCoverage.glyphs, subtable.BaseArray.BaseRecord):
                if name not in lower or name in ASCENDERS:
                    continue
                for anchor in record.BaseAnchor:
                    if anchor is not None and anchor.YCoordinate > xheight:
                        assert anchor.Format == 1
                        anchor.YCoordinate += DELTA
                        anchor.XCoordinate += otRound(slope * DELTA)
                        anchors_changed += 1

    # Old CFF hint zones describe the previous outlines. They are removed,
    # and otf2ttf subsequently exports its native unhinted TrueType result.
    font["CFF "].cff.remove_hints()
    top.recalcFontBBox()
    font["head"].xMin, font["head"].yMin, font["head"].xMax, font["head"].yMax = top.FontBBox
    if "DSIG" in font:
        del font["DSIG"]
    os2 = font["OS/2"]
    os2.sxHeight = xheight + DELTA
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = ASCENT, DESCENT, 0
    os2.fsSelection |= 1 << 7
    os2.usWinAscent, os2.usWinDescent = WIN_ASCENT, WIN_DESCENT
    os2.yStrikeoutPosition += otRound(DELTA / 2)
    font["hhea"].ascent, font["hhea"].descent, font["hhea"].lineGap = ASCENT, DESCENT, 0
    preserve_names_update_metadata(font, style)
    destination.parent.mkdir(parents=True, exist_ok=True)
    font.save(destination)
    intermediate = TTFont(destination)
    assert intermediate.getGlyphOrder() == order
    assert intermediate.getBestCmap() == cmap
    assert intermediate["GSUB"].compile(intermediate) == original["GSUB"].compile(original)
    assert all(intermediate["hmtx"][name][0] == original["hmtx"][name][0] for name in order)
    assert otRound(record_bounds(record_glyph(intermediate, "x"))[3]) == xheight + DELTA
    return {
        "style": style, "source_otf": source.name, "source_otf_sha256": sha256(source),
        "component_reference_ttf_sha256": sha256(ttf_reference),
        "intermediate_otf_sha256": sha256(destination),
        "xheight_before": xheight, "xheight_after": xheight + DELTA,
        "cap_height": os2.sCapHeight, "units_per_em": font["head"].unitsPerEm,
        "glyph_count": len(order), "unicode_entries": len(cmap),
        "ascii_advance": font["hmtx"]["x"][0],
        "preferred_line_height_before": 1380, "preferred_line_height_after": LINE_HEIGHT,
        "hhea_and_typo": [ASCENT, DESCENT, 0], "win_clipping_metrics": [WIN_ASCENT, WIN_DESCENT],
        "lowercase_changed": changed, "composite_lowercase_updated": composite_names,
        "s_spine_protected": protected_s_glyphs,
        "cell_glyphs_changed": cells, "mark_base_anchors_changed": anchors_changed,
        "original_cff_component_placement_exceptions_preserved": placement_exceptions,
        "horizontal_stroke_guard": guard,
    }


def run_logged(command: list[str], cwd: Path, log_path: Path) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("Command: " + " ".join(command[1:]) + "\n\n" + result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"AFDKO failed ({result.returncode}); see {log_path}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root)
    args = parser.parse_args()
    root = args.root.resolve()
    for directory in ("fonts", "intermediate-otf", "collection", "logs"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    records = []
    for style in STYLES:
        stem = f"IntelOneMono-{style}"
        record = edit_cff(root / "source-otf" / f"{stem}.otf", root / "source-ttf" / f"{stem}.ttf",
                          root / "intermediate-otf" / f"{stem}.otf")
        if style in ("Regular", "Italic"):
            assert record["xheight_after"] == REGULAR_XHEIGHT
        records.append(record)
        print(style, "CFF x-height", record["xheight_before"], "->", record["xheight_after"], flush=True)
    input_otfs = [f"intermediate-otf/IntelOneMono-{style}.otf" for style in STYLES]
    convert = [sys.executable, "-m", "afdko.otf2ttf", *input_otfs, "-e", str(MAX_ERROR), "-o", "fonts", "--overwrite"]
    run_logged(convert, root, root / "logs/otf2ttf.log")
    for record in records:
        output = root / "fonts" / f'IntelOneMono-{record["style"]}.ttf'
        final = TTFont(output)
        assert "glyf" in final and "CFF " not in final
        assert final["glyf"]["x"].yMax == record["xheight_after"]
        assert final["glyf"]["H"].yMax == 655
        assert final["head"].yMax <= WIN_ASCENT and final["head"].yMin >= -WIN_DESCENT
        assert not any(tag in final for tag in ("fpgm", "prep", "cvt "))
        record.update(file=output.name, sha256=sha256(output), global_y_bounds=[final["head"].yMin, final["head"].yMax])
    input_ttfs = [f"fonts/IntelOneMono-{style}.ttf" for style in STYLES]
    collect = [sys.executable, "-m", "afdko.otf2otc", "-o", "collection/IntelOneMono.ttc", *input_ttfs]
    run_logged(collect, root, root / "logs/otf2otc.log")
    collection = root / "collection/IntelOneMono.ttc"
    ttc = TTCollection(collection)
    assert len(ttc.fonts) == 8
    assert [font["name"].getDebugName(6) for font in ttc.fonts] == [f"IntelOneMono-{style}" for style in STYLES]
    report = {
        "family": FAMILY, "version": VERSION, "date": BUILD_DATE, "regular_xheight": REGULAR_XHEIGHT,
        "weight_policy": f"Each original style x-height +{DELTA} units; original inter-weight offsets retained.",
        "name_policy": "Original family/full/PostScript/style names retained at user request.",
        "upstream": "https://github.com/intel/intel-one-mono/releases/tag/V1.5.0",
        "license": "SIL Open Font License 1.1; original Reserved Font Name remains applicable",
        "toolchain": {"afdko": importlib.metadata.version("afdko"), "fonttools": importlib.metadata.version("fonttools"),
                      "ttf_converter": "afdko.otf2ttf", "max_error_design_units": MAX_ERROR,
                      "collection_builder": "afdko.otf2otc", "hinting": "Unhinted native otf2ttf output; no subsequent hinting or outline modification"},
        "commands": {"ttf": convert[1:], "ttc": collect[1:]}, "fonts": records,
        "collection": {"file": "collection/IntelOneMono.ttc", "sha256": sha256(collection), "face_order": STYLES, "face_count": 8},
        "limitations": [
            f"Preferred line height {LINE_HEIGHT / 1000:.2f}em; application settings may override it.",
            "Legacy software using Win metrics may use 1.50em; clipping bounds are retained for accents.",
            "This direct AFDKO conversion does not contain the original manual or previous custom automatic TrueType hinting.",
            "Install either the eight TTFs or the TTC, not both; original-name versions replace earlier installations.",
        ],
    }
    (root / "Build-info.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Exported 8 TTFs through AFDKO and built", collection.name, flush=True)


if __name__ == "__main__":
    main()
