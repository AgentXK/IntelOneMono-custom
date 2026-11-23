"""Recover component roles in decomposed Intel One Mono 1.5 CFF contours.

The official TrueType builds retain component definitions, whereas the CFF
builds reorder the decomposed contours.  Match the *existing CFF contours*
against the corresponding CFF component artwork.  The matcher permits a
rigid translation correction so it retains the few placement differences
between the official CFF and TrueType builds.

This module only identifies contour ownership; it never changes either
font.  It requires fontTools and does not depend on local workspace paths.
"""
from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from typing import Any

from fontTools.pens.recordingPen import RecordingPen, replayRecording
from fontTools.pens.transformPen import TransformPen


def split_contours(recording: Sequence) -> list[tuple]:
    """Split a RecordingPen recording without reordering its contours.

    CFF glyphs in the audited upstream consist of move/line/cubic operations
    ending in closePath.  Reject unsupported/noncontour commands instead of
    silently assigning them to the wrong component.
    """
    result = []
    contour = []
    for operation, points in recording:
        if operation not in {"moveTo", "lineTo", "curveTo", "qCurveTo", "closePath", "endPath"}:
            raise ValueError(f"Unsupported outline operation: {operation}")
        if operation == "moveTo" and contour:
            raise ValueError("New contour started before the preceding contour ended")
        contour.append((operation, tuple(points)))
        if operation in {"closePath", "endPath"}:
            result.append(tuple(contour))
            contour = []
    if contour:
        raise ValueError("Unterminated contour")
    return result


# The public alias follows the spelling requested by the parent builder.
splitContours = split_contours


def _record(font_cff, glyph_name: str, recordings_cache: MutableMapping | None):
    if recordings_cache is not None and glyph_name in recordings_cache:
        value = recordings_cache[glyph_name]
        return value.value if isinstance(value, RecordingPen) else value
    pen = RecordingPen()
    font_cff.getGlyphSet()[glyph_name].draw(pen)
    if recordings_cache is not None:
        recordings_cache[glyph_name] = pen.value
    return pen.value


def _rigid_translation(expected: tuple, actual: tuple):
    """Return actual-minus-expected translation if all commands agree."""
    if len(expected) != len(actual):
        return None
    shift = None
    for (operation, points), (actual_operation, actual_points) in zip(expected, actual):
        if operation != actual_operation or len(points) != len(actual_points):
            return None
        for point, actual_point in zip(points, actual_points):
            if point is None or actual_point is None:
                if point is not actual_point:
                    return None
                continue
            delta = (actual_point[0] - point[0], actual_point[1] - point[1])
            if shift is None:
                shift = delta
            elif delta != shift:
                return None
    return shift


def classify(font_cff, font_ttf, glyph_name: str, recordings_cache: MutableMapping | None = None) -> list[dict[str, Any]]:
    """Return one ownership record per *actual CFF contour*, in its order.

    This function is for composite glyphs from the audited official TTF.
    Each returned dict contains:

    ``component_index`` / ``component_name`` / ``role`` / ``is_base``:
        Component identity. The first TTF component is the lowercase base;
        subsequent components are marks or side symbols.
    ``actual_transform``:
        Original component affine transform with the observed CFF placement.
    ``dx`` / ``dy``:
        Its actual translation relative to the standalone CFF component.
    ``translation_correction``:
        Actual CFF placement minus the TTF component placement.
    ``component_contour_index`` / ``actual_contour_index``:
        Indices within the standalone component and the composite glyph.

    A cache of unmodified CFF RecordingPen values may be shared across calls.
    Use a distinct cache per font/style. The function does not mutate cache
    entries, contours, or either font.
    """
    glyph = font_ttf["glyf"][glyph_name]
    if not glyph.isComposite():
        raise ValueError(f"{glyph_name} is not composite in the reference TTF")
    actual_contours = split_contours(_record(font_cff, glyph_name, recordings_cache))
    remaining = set(range(len(actual_contours)))
    assigned: list[dict[str, Any] | None] = [None] * len(actual_contours)

    for component_index, component in enumerate(glyph.components):
        component_name, transform = component.getComponentInfo()
        pen = RecordingPen()
        replayRecording(
            _record(font_cff, component_name, recordings_cache),
            TransformPen(pen, transform),
        )
        for component_contour_index, expected in enumerate(split_contours(pen.value)):
            candidates = []
            for actual_index in sorted(remaining):
                correction = _rigid_translation(expected, actual_contours[actual_index])
                if correction is not None:
                    distance = correction[0] ** 2 + correction[1] ** 2
                    candidates.append((distance, actual_index, correction))
            if not candidates:
                raise ValueError(
                    f"Cannot match {glyph_name}: component {component_name}, "
                    f"contour {component_contour_index}"
                )
            candidates.sort()
            # Equal nearest alternatives would indicate genuinely ambiguous
            # ownership, not just the upstream's harmless contour reordering.
            if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
                raise ValueError(
                    f"Ambiguous component ownership in {glyph_name}/{component_name}"
                )
            _, actual_index, correction = candidates[0]
            remaining.remove(actual_index)
            actual_transform = tuple(transform[:4]) + (
                transform[4] + correction[0], transform[5] + correction[1],
            )
            assigned[actual_index] = {
                "component_index": component_index,
                "component_name": component_name,
                "role": "base" if component_index == 0 else "mark",
                "is_base": component_index == 0,
                "actual_transform": actual_transform,
                "dx": actual_transform[4],
                "dy": actual_transform[5],
                "translation_correction": correction,
                "component_contour_index": component_contour_index,
                "actual_contour_index": actual_index,
            }
    if remaining or any(item is None for item in assigned):
        raise ValueError(f"Unassigned CFF contours in {glyph_name}: {sorted(remaining)}")
    return assigned
