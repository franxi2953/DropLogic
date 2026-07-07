"""Validation helpers for AdvancedDrop planning primitives."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .common import (
    check_vital_space_conflict,
    create_droplet,
    get_droplet_positions,
)
from .merge import (
    _apply_forced_dimensions,
    _build_square_pruned_shape,
    _relax_shape_safe,
)


def validate_droplet_target_layout(
    active_droplets: Iterable[Any],
    target_updates: Dict[int, Tuple[int, int]],
    *,
    matrix_shape: Optional[Iterable[int]] = None,
) -> Dict[str, Any]:
    """Validate final active-droplet layout after applying target updates.

    New footprint/vital-space conflicts caused by proposed targets are blocking.
    Conflicts already present in the current physical layout are warnings so a
    caller can still reset targets back to current positions.
    """
    active_droplets = [
        droplet for droplet in list(active_droplets or []) if getattr(droplet, "id", None) is not None
    ]
    target_updates = {
        int(droplet_id): tuple(target)
        for droplet_id, target in (target_updates or {}).items()
    }
    requested_ids = sorted(target_updates)
    active_ids = [int(getattr(droplet, "id")) for droplet in active_droplets]
    normalized_shape = _normalize_matrix_shape(matrix_shape)

    current_corners: Dict[int, Tuple[int, int]] = {}
    final_corners: Dict[int, Tuple[int, int]] = {}
    for droplet in active_droplets:
        droplet_id = int(getattr(droplet, "id"))
        current_corners[droplet_id] = tuple(getattr(droplet, "origin_corner"))
        final_corners[droplet_id] = tuple(
            target_updates.get(
                droplet_id,
                getattr(droplet, "target_corner", getattr(droplet, "origin_corner")),
            )
        )

    pending_ids = [
        droplet_id
        for droplet_id in active_ids
        if current_corners.get(droplet_id) != final_corners.get(droplet_id)
    ]
    pending_not_requested = [
        droplet_id for droplet_id in pending_ids if droplet_id not in requested_ids
    ]

    blocking = []
    warnings = []
    for droplet in active_droplets:
        droplet_id = int(getattr(droplet, "id"))
        final_corner = final_corners[droplet_id]
        final_positions = get_droplet_positions(droplet, final_corner)
        out_of_bounds = [
            [row, col]
            for row, col in sorted(final_positions)
            if not target_cell_in_bounds(row, col, normalized_shape)
        ]
        if not out_of_bounds:
            continue
        issue = {
            "type": "out_of_bounds",
            "droplet_id": droplet_id,
            "target": final_corner,
            "matrix_shape": normalized_shape,
            "cells": out_of_bounds[:10],
            "cell_count": len(out_of_bounds),
        }
        if droplet_id in requested_ids or final_corner != current_corners[droplet_id]:
            blocking.append(issue)
        else:
            warnings.append({**issue, "warning": "preexisting_out_of_bounds"})

    final_occupied: Dict[Tuple[int, int], int] = {}
    current_occupied: Dict[Tuple[int, int], int] = {}
    for droplet in active_droplets:
        droplet_id = int(getattr(droplet, "id"))
        for cell in get_droplet_positions(droplet, current_corners[droplet_id]):
            current_occupied.setdefault(cell, droplet_id)
        for cell in get_droplet_positions(droplet, final_corners[droplet_id]):
            other_id = final_occupied.setdefault(cell, droplet_id)
            if other_id == droplet_id:
                continue
            current_same = (
                current_occupied.get(cell) in {other_id, droplet_id}
                and current_corners.get(other_id) == final_corners.get(other_id)
                and current_corners.get(droplet_id) == final_corners.get(droplet_id)
            )
            issue = {
                "type": "footprint_overlap",
                "droplet_ids": [other_id, droplet_id],
                "cell": [cell[0], cell[1]],
                "targets": {
                    str(other_id): final_corners.get(other_id),
                    str(droplet_id): final_corners.get(droplet_id),
                },
            }
            if current_same:
                warnings.append({**issue, "warning": "preexisting_overlap"})
            else:
                blocking.append(issue)

    for index, droplet_a in enumerate(active_droplets):
        id_a = int(getattr(droplet_a, "id"))
        for droplet_b in active_droplets[index + 1:]:
            id_b = int(getattr(droplet_b, "id"))
            current_conflict = check_vital_space_conflict(
                droplet_a,
                current_corners[id_a],
                droplet_b,
                current_corners[id_b],
            )
            final_conflict = check_vital_space_conflict(
                droplet_a,
                final_corners[id_a],
                droplet_b,
                final_corners[id_b],
            )
            if not final_conflict:
                continue
            issue = {
                "type": "vital_space_conflict",
                "droplet_ids": [id_a, id_b],
                "targets": {
                    str(id_a): final_corners[id_a],
                    str(id_b): final_corners[id_b],
                },
                "vital_spaces": {
                    str(id_a): int(getattr(droplet_a, "vital_space", 0) or 0),
                    str(id_b): int(getattr(droplet_b, "vital_space", 0) or 0),
                },
            }
            current_same = (
                current_conflict
                and current_corners[id_a] == final_corners[id_a]
                and current_corners[id_b] == final_corners[id_b]
            )
            if current_same:
                warnings.append({**issue, "warning": "preexisting_vital_space_conflict"})
            else:
                blocking.append(issue)

    for index, droplet_a in enumerate(active_droplets):
        id_a = int(getattr(droplet_a, "id"))
        for droplet_b in active_droplets[index + 1:]:
            id_b = int(getattr(droplet_b, "id"))
            final_conflict = check_vital_space_conflict(
                droplet_a,
                final_corners[id_a],
                droplet_b,
                final_corners[id_b],
            )
            if final_conflict:
                continue
            for mover, mover_id, blocker, blocker_id in (
                (droplet_a, id_a, droplet_b, id_b),
                (droplet_b, id_b, droplet_a, id_a),
            ):
                if final_corners[mover_id] == current_corners[mover_id]:
                    continue
                if not check_vital_space_conflict(
                    mover,
                    final_corners[mover_id],
                    blocker,
                    current_corners[blocker_id],
                ):
                    continue
                blocking.append(
                    {
                        "type": "target_uses_current_reserved_space",
                        "moving_droplet_id": mover_id,
                        "blocking_droplet_id": blocker_id,
                        "moving_target": final_corners[mover_id],
                        "blocking_current_position": current_corners[blocker_id],
                        "message": (
                            "SIPP reserves active droplets' current footprints/vital "
                            "spaces during a move. Move the blocking droplet to an "
                            "intermediate parking position and execute that segment first."
                        ),
                    }
                )

    if pending_not_requested:
        warnings.append(
            {
                "type": "pending_targets_not_in_request",
                "droplet_ids": pending_not_requested,
                "message": (
                    "plan_move moves every active droplet whose target differs from "
                    "its current position, including these droplets. Reset them to "
                    "their current positions or include them intentionally before planning."
                ),
            }
        )
    if len(pending_ids) > 10:
        warnings.append(
            {
                "type": "large_move_batch",
                "pending_target_count": len(pending_ids),
                "message": (
                    "For real hardware, split movement into executed batches of "
                    "5-10 droplets and prefer 5 in dense layouts."
                ),
            }
        )

    suggested_targets = {}
    if blocking and requested_ids:
        suggested_targets = suggest_available_droplet_targets(
            active_droplets=active_droplets,
            current_corners=current_corners,
            final_corners=final_corners,
            requested_targets=target_updates,
            blocking_issues=blocking,
            matrix_shape=normalized_shape,
        )

    return {
        "ok": not blocking,
        "requested_target_ids": requested_ids,
        "active_droplet_ids": active_ids,
        "pending_target_ids": pending_ids,
        "pending_target_ids_not_in_request": pending_not_requested,
        "blocking_issue_count": len(blocking),
        "blocking_issues": blocking[:20],
        "suggestion_count": len(suggested_targets),
        "suggested_targets": suggested_targets,
        "warning_count": len(warnings),
        "warnings": warnings[:20],
        "matrix_shape": normalized_shape,
    }


def suggest_available_droplet_targets(
    *,
    active_droplets: List[Any],
    current_corners: Dict[int, Tuple[int, int]],
    final_corners: Dict[int, Tuple[int, int]],
    requested_targets: Dict[int, Tuple[int, int]],
    blocking_issues: List[Dict[str, Any]],
    matrix_shape: Optional[List[int]],
) -> Dict[str, Dict[str, Any]]:
    requested_ids = {int(droplet_id) for droplet_id in requested_targets}
    affected_ids = target_suggestion_affected_ids(
        blocking_issues,
        requested_ids,
    )
    if not affected_ids:
        affected_ids = set(requested_ids)

    droplets_by_id = {
        int(getattr(droplet, "id")): droplet
        for droplet in active_droplets
        if getattr(droplet, "id", None) is not None
    }
    suggested = {}
    search_corners = dict(final_corners)

    for droplet_id in sorted(affected_ids):
        droplet = droplets_by_id.get(droplet_id)
        requested = requested_targets.get(droplet_id)
        if droplet is None or requested is None:
            continue

        requested = tuple(requested)
        if target_candidate_available(
            droplet_id=droplet_id,
            candidate_corner=requested,
            active_droplets=active_droplets,
            current_corners=current_corners,
            final_corners=search_corners,
            matrix_shape=matrix_shape,
        )[0]:
            search_corners[droplet_id] = requested
            continue

        candidate, reason = nearest_available_droplet_target(
            droplet_id=droplet_id,
            requested_corner=requested,
            active_droplets=active_droplets,
            current_corners=current_corners,
            final_corners=search_corners,
            matrix_shape=matrix_shape,
        )
        if candidate is None:
            suggested[str(droplet_id)] = {
                "target": None,
                "from": requested,
                "reason": "no_available_target_found",
                "message": (
                    "No nearby legal target was found within the cartridge. "
                    "Move blockers to parking positions or reduce the batch size."
                ),
            }
            continue

        search_corners[droplet_id] = candidate
        suggested[str(droplet_id)] = {
            "target": candidate,
            "from": requested,
            "manhattan_distance": (
                abs(int(candidate[0]) - int(requested[0]))
                + abs(int(candidate[1]) - int(requested[1]))
            ),
            "reason": reason or "closest_available_target",
            "message": (
                "Closest available target found while keeping the other "
                "requested targets and active droplets reserved."
            ),
        }

    return suggested


def target_suggestion_affected_ids(
    blocking_issues: List[Dict[str, Any]],
    requested_ids: Set[int],
) -> Set[int]:
    affected = set()
    for issue in blocking_issues:
        issue_type = issue.get("type")
        if issue_type == "out_of_bounds":
            droplet_id = issue.get("droplet_id")
            if droplet_id in requested_ids:
                affected.add(int(droplet_id))
        elif issue_type in {"footprint_overlap", "vital_space_conflict"}:
            for droplet_id in issue.get("droplet_ids", []) or []:
                if droplet_id in requested_ids:
                    affected.add(int(droplet_id))
        elif issue_type == "target_uses_current_reserved_space":
            droplet_id = issue.get("moving_droplet_id")
            if droplet_id in requested_ids:
                affected.add(int(droplet_id))
    return affected


def validate_merge_target_layout(
    droplets: Iterable[Any],
    droplet_ids: Iterable[int],
    target: Any,
    *,
    active_droplet_ids: Optional[Iterable[int]] = None,
    matrix_shape: Optional[Iterable[int]] = None,
    forced_width: Optional[int] = None,
    forced_height: Optional[int] = None,
) -> Dict[str, Any]:
    """Diagnose whether a merge hub is clear enough to attempt a merge.

    This is a pure planning/geometry helper. It does not mutate droplets or
    append plan frames; MCP and other interfaces can expose its result.
    """
    all_droplets = [
        droplet for droplet in list(droplets or []) if getattr(droplet, "id", None) is not None
    ]
    droplets_by_id = {int(getattr(droplet, "id")): droplet for droplet in all_droplets}
    requested_ids = [int(item) for item in (droplet_ids or [])]
    active_ids = (
        {int(item) for item in active_droplet_ids}
        if active_droplet_ids is not None
        else {int(getattr(droplet, "id")) for droplet in all_droplets}
    )
    active_droplets = [
        droplet for droplet in all_droplets if int(getattr(droplet, "id")) in active_ids
    ]
    normalized_shape = _normalize_matrix_shape(matrix_shape)

    target_is_existing = isinstance(target, int)
    target_droplet = droplets_by_id.get(int(target)) if target_is_existing else None
    if target_is_existing and int(target) in requested_ids:
        requested_ids = [droplet_id for droplet_id in requested_ids if droplet_id != int(target)]

    blocking: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    missing_ids = [
        droplet_id for droplet_id in requested_ids if droplet_id not in droplets_by_id
    ]
    if missing_ids:
        blocking.append(
            {
                "type": "merge_droplets_missing",
                "droplet_ids": missing_ids,
                "message": "The requested merge input droplet ids do not exist.",
            }
        )
    if not requested_ids:
        blocking.append(
            {
                "type": "no_merge_inputs",
                "message": "Merge needs at least one input droplet besides the target.",
            }
        )
    if target_is_existing and target_droplet is None:
        blocking.append(
            {
                "type": "target_droplet_missing",
                "target": target,
                "message": "The requested merge target droplet does not exist.",
            }
        )

    try:
        target_corner = (
            tuple(getattr(target_droplet, "origin_corner"))
            if target_is_existing and target_droplet is not None
            else _pair(target, "target")
        )
    except Exception as exc:
        return {
            "ok": False,
            "reason": "invalid_merge_target",
            "message": str(exc),
            "droplet_ids": requested_ids,
            "target": target,
            "blocking_issue_count": len(blocking) + 1,
            "blocking_issues": blocking
            + [{"type": "invalid_merge_target", "message": str(exc)}],
            "matrix_shape": normalized_shape,
        }

    merging = [
        droplets_by_id[droplet_id]
        for droplet_id in requested_ids
        if droplet_id in droplets_by_id
    ]
    inactive_merge_ids = [
        droplet_id for droplet_id in requested_ids if droplet_id not in active_ids
    ]
    if inactive_merge_ids:
        warnings.append(
            {
                "type": "merge_inputs_not_active",
                "droplet_ids": inactive_merge_ids,
                "message": (
                    "These droplets exist logically but are not active in the last "
                    "plan frame. Verify the physical droplet state before merging."
                ),
            }
        )

    total_electrodes = sum(len(getattr(droplet, "shape", []) or []) for droplet in merging)
    if target_is_existing and target_droplet is not None:
        total_electrodes += len(getattr(target_droplet, "shape", []) or [])

    merged_shape = build_merge_product_shape(
        total_electrodes,
        forced_width=forced_width,
        forced_height=forced_height,
    )
    merged_vital_space = merge_product_vital_space(
        merging,
        target_droplet=target_droplet,
    )
    virtual_product = create_droplet(
        droplet_id=-1_000_000,
        origin=target_corner,
        target=target_corner,
        shape=merged_shape,
        vital_space=merged_vital_space,
    )

    target_id = None
    routing_active_droplets = list(active_droplets)
    if target_is_existing and target_droplet is not None:
        target_id = int(getattr(target_droplet, "id"))
        if not any(
            int(getattr(droplet, "id")) == target_id
            for droplet in routing_active_droplets
        ):
            routing_active_droplets.append(target_droplet)

    merging_input_ids = set(requested_ids)
    merging_ids = set(merging_input_ids)
    if target_is_existing and target_droplet is not None:
        merging_ids.add(int(getattr(target_droplet, "id")))
    blockers = [
        droplet
        for droplet in routing_active_droplets
        if int(getattr(droplet, "id")) not in merging_ids
    ]
    start_reservation_blockers = [
        droplet
        for droplet in routing_active_droplets
        if int(getattr(droplet, "id")) not in merging_input_ids
    ]

    out_of_bounds = [
        [row, col]
        for row, col in sorted(get_droplet_positions(virtual_product, target_corner))
        if not target_cell_in_bounds(row, col, normalized_shape)
    ]
    if out_of_bounds:
        blocking.append(
            {
                "type": "merge_target_out_of_bounds",
                "target": target_corner,
                "cells": out_of_bounds[:10],
                "cell_count": len(out_of_bounds),
            }
        )

    for blocker in blockers:
        blocker_id = int(getattr(blocker, "id"))
        blocker_corner = tuple(getattr(blocker, "origin_corner"))
        blocker_positions = get_droplet_positions(blocker, blocker_corner)
        overlap = sorted(
            get_droplet_positions(virtual_product, target_corner) & blocker_positions
        )
        if overlap:
            blocking.append(
                {
                    "type": "merge_target_footprint_overlap",
                    "blocking_droplet_id": blocker_id,
                    "target": target_corner,
                    "blocking_position": blocker_corner,
                    "cells": [[row, col] for row, col in overlap[:10]],
                    "cell_count": len(overlap),
                }
            )
        if check_vital_space_conflict(
            virtual_product,
            target_corner,
            blocker,
            blocker_corner,
        ):
            blocking.append(
                {
                    "type": "merge_target_vital_space_conflict",
                    "blocking_droplet_id": blocker_id,
                    "target": target_corner,
                    "blocking_position": blocker_corner,
                    "message": (
                        "The merged product would overlap the blocker footprint "
                        "or vital space. Move the blocker or choose another hub."
                    ),
                }
            )

    start_blockers = set()
    for joiner in merging:
        joiner_id = int(getattr(joiner, "id"))
        joiner_corner = tuple(getattr(joiner, "origin_corner"))
        for blocker in start_reservation_blockers:
            blocker_id = int(getattr(blocker, "id"))
            blocker_corner = tuple(getattr(blocker, "origin_corner"))
            if not check_vital_space_conflict(
                joiner,
                joiner_corner,
                blocker,
                blocker_corner,
            ):
                continue
            start_blockers.add(blocker_id)
            blocking.append(
                {
                    "type": "merge_joiner_starts_in_blocker_vital_space",
                    "joiner_droplet_id": joiner_id,
                    "blocking_droplet_id": blocker_id,
                    "joiner_position": joiner_corner,
                    "blocking_position": blocker_corner,
                    "message": (
                        "A merge input starts inside another active droplet's "
                        "reserved footprint/vital space. Stage the blocker away "
                        "and execute that segment before retrying the merge."
                    ),
                }
            )

    target_blocked = any(
        str(issue.get("type", "")).startswith("merge_target_")
        for issue in blocking
    )
    target_candidate = None
    target_reason = None
    if target_blocked:
        target_candidate, target_reason = nearest_available_merge_target(
            requested_corner=target_corner,
            product_shape=merged_shape,
            product_vital_space=merged_vital_space,
            blockers=blockers,
            matrix_shape=normalized_shape,
            exclude={target_corner},
        )
    suggested_target = None
    if target_candidate is not None and target_candidate != target_corner:
        suggested_target = {
            "target": target_candidate,
            "from": target_corner,
            "manhattan_distance": (
                abs(int(target_candidate[0]) - int(target_corner[0]))
                + abs(int(target_candidate[1]) - int(target_corner[1]))
            ),
            "reason": target_reason or "closest_available_merge_hub",
            "message": (
                "Closest nearby hub whose merged footprint/vital space does "
                "not collide with active non-merge droplets."
            ),
        }
        if target_is_existing and target_id is not None:
            retry_droplet_ids = list(requested_ids)
            if target_id not in retry_droplet_ids:
                retry_droplet_ids.append(target_id)
            retry_arguments = {
                "droplet_ids": retry_droplet_ids,
                "target": target_candidate,
            }
            if forced_width is not None:
                retry_arguments["forced_width"] = forced_width
            if forced_height is not None:
                retry_arguments["forced_height"] = forced_height
            suggested_target["target_droplet_id"] = target_id
            suggested_target["retry_arguments"] = retry_arguments

    reserved_merge_products = [(virtual_product, target_corner)]
    if suggested_target:
        reserved_merge_products.append((virtual_product, target_candidate))

    parking_suggestions = suggest_merge_blocker_parking_targets(
        active_droplets=routing_active_droplets,
        blocker_ids=start_blockers,
        matrix_shape=normalized_shape,
        reserved_droplets=reserved_merge_products,
    )

    reason = "merge_target_valid"
    if blocking:
        issue_types = {issue.get("type") for issue in blocking}
        target_blocked_for_reason = any(
            str(issue_type).startswith("merge_target_") for issue_type in issue_types
        )
        if (
            "merge_joiner_starts_in_blocker_vital_space" in issue_types
            and target_blocked_for_reason
        ):
            reason = "stage_blockers_and_choose_different_merge_target"
        elif "merge_joiner_starts_in_blocker_vital_space" in issue_types:
            reason = "stage_blockers_before_merge"
        elif target_blocked_for_reason:
            reason = "choose_different_merge_target"
        else:
            reason = "invalid_merge_request"

    result = {
        "ok": not blocking,
        "reason": reason,
        "droplet_ids": requested_ids,
        "target": target_corner,
        "target_is_existing_droplet": target_is_existing,
        "merged_shape_size": len(merged_shape),
        "merged_vital_space": merged_vital_space,
        "active_non_merge_droplet_ids": [
            int(getattr(droplet, "id")) for droplet in blockers
        ],
        "blocking_issue_count": len(blocking),
        "blocking_issues": blocking[:12],
        "warning_count": len(warnings),
        "warnings": warnings[:12],
        "matrix_shape": normalized_shape,
    }
    if suggested_target:
        result["suggested_target"] = suggested_target
    if parking_suggestions:
        result["blocker_parking_suggestions"] = parking_suggestions
    return result


def merge_failure_recommendation(
    merge_target_validation: Dict[str, Any],
) -> Optional[str]:
    """Return a short next-action hint for a failed merge diagnostic."""
    if not isinstance(merge_target_validation, dict):
        return None
    parking_suggestions = merge_target_validation.get("blocker_parking_suggestions")
    suggested_target = merge_target_validation.get("suggested_target")
    target_blocked = any(
        str(issue.get("type", "")).startswith("merge_target_")
        for issue in merge_target_validation.get("blocking_issues", []) or []
        if isinstance(issue, dict)
    )
    suggested_retry_reference = (
        "primitive_validation.merge_target_validation.suggested_target.retry_arguments"
        if isinstance(suggested_target, dict) and suggested_target.get("retry_arguments")
        else "primitive_validation.merge_target_validation.suggested_target.target"
    )
    if suggested_target and target_blocked and parking_suggestions:
        return (
            "Stage the listed blocking droplets to blocker_parking_suggestions, "
            f"execute that move, then retry plan_merge with {suggested_retry_reference}."
        )
    if suggested_target:
        return (
            f"Retry plan_merge with {suggested_retry_reference}."
        )
    if parking_suggestions:
        return (
            "Stage the listed blocking droplets to blocker_parking_suggestions, "
            "execute that move, then retry plan_merge."
        )
    if merge_target_validation.get("ok") is True:
        return (
            "The final hub looks open, so retry via an intermediate staging move "
            "or choose a nearby open hub before executing downstream primitives."
        )
    return None


def build_merge_product_shape(
    total_electrodes: int,
    forced_width: Optional[int] = None,
    forced_height: Optional[int] = None,
) -> Set[Tuple[int, int]]:
    total = max(1, int(total_electrodes or 0))
    shape = _build_square_pruned_shape(total)
    if forced_width is not None or forced_height is not None:
        shape = _apply_forced_dimensions(
            shape,
            total,
            forced_width=forced_width,
            forced_height=forced_height,
        )
    return _relax_shape_safe(shape)


def merge_product_vital_space(
    merging: List[Any],
    *,
    target_droplet: Optional[Any] = None,
) -> int:
    if target_droplet is not None:
        vital_space = getattr(target_droplet, "vital_space", None)
        if vital_space is None:
            return 1
        return int(vital_space)
    return 1


def nearest_available_merge_target(
    *,
    requested_corner: Tuple[int, int],
    product_shape: Set[Tuple[int, int]],
    product_vital_space: int,
    blockers: List[Any],
    matrix_shape: Optional[List[int]],
    exclude: Optional[Set[Tuple[int, int]]] = None,
) -> Tuple[Optional[Tuple[int, int]], Optional[str]]:
    exclude = {tuple(item) for item in (exclude or set())}
    if matrix_shape and len(matrix_shape) >= 2:
        search_limit = max(int(matrix_shape[0]), int(matrix_shape[1]))
    else:
        search_limit = 64
    requested_row, requested_col = int(requested_corner[0]), int(requested_corner[1])
    last_reason = None
    for radius in range(search_limit + 1):
        candidates = []
        for row_delta in range(-radius, radius + 1):
            col_distance = radius - abs(row_delta)
            if col_distance == 0:
                candidates.append((requested_row + row_delta, requested_col))
            else:
                candidates.append(
                    (requested_row + row_delta, requested_col - col_distance)
                )
                candidates.append(
                    (requested_row + row_delta, requested_col + col_distance)
                )
        for candidate in sorted(
            set(candidates),
            key=lambda item: (
                abs(item[0] - requested_row) + abs(item[1] - requested_col),
                max(abs(item[0] - requested_row), abs(item[1] - requested_col)),
                item[0],
                item[1],
            ),
        ):
            if tuple(candidate) in exclude:
                continue
            ok, reason = merge_target_candidate_available(
                candidate_corner=candidate,
                product_shape=product_shape,
                product_vital_space=product_vital_space,
                blockers=blockers,
                matrix_shape=matrix_shape,
            )
            if ok:
                return (int(candidate[0]), int(candidate[1])), "closest_available_merge_hub"
            last_reason = reason
    return None, last_reason


def merge_target_candidate_available(
    *,
    candidate_corner: Tuple[int, int],
    product_shape: Set[Tuple[int, int]],
    product_vital_space: int,
    blockers: List[Any],
    matrix_shape: Optional[List[int]],
) -> Tuple[bool, Optional[str]]:
    candidate_corner = (int(candidate_corner[0]), int(candidate_corner[1]))
    virtual_product = create_droplet(
        droplet_id=-1_000_001,
        origin=candidate_corner,
        target=candidate_corner,
        shape=set(product_shape),
        vital_space=int(product_vital_space),
    )
    for row, col in get_droplet_positions(virtual_product, candidate_corner):
        if not target_cell_in_bounds(row, col, matrix_shape):
            return False, "out_of_bounds"
    product_positions = get_droplet_positions(virtual_product, candidate_corner)
    for blocker in blockers:
        blocker_corner = tuple(getattr(blocker, "origin_corner"))
        if product_positions & get_droplet_positions(blocker, blocker_corner):
            return False, "footprint_overlap"
        if check_vital_space_conflict(
            virtual_product,
            candidate_corner,
            blocker,
            blocker_corner,
        ):
            return False, "vital_space_conflict"
    return True, None


def suggest_merge_blocker_parking_targets(
    *,
    active_droplets: List[Any],
    blocker_ids: Set[int],
    matrix_shape: Optional[List[int]],
    reserved_droplets: Optional[List[Tuple[Any, Tuple[int, int]]]] = None,
) -> Dict[str, Dict[str, Any]]:
    if not blocker_ids:
        return {}
    current_corners = {
        int(getattr(droplet, "id")): tuple(getattr(droplet, "origin_corner"))
        for droplet in active_droplets
    }
    search_corners = dict(current_corners)
    suggestions = {}
    for blocker_id in sorted(int(item) for item in blocker_ids):
        requested = current_corners.get(blocker_id)
        if requested is None:
            continue
        candidate, reason = nearest_available_droplet_target(
            droplet_id=blocker_id,
            requested_corner=requested,
            active_droplets=active_droplets,
            current_corners=current_corners,
            final_corners=search_corners,
            matrix_shape=matrix_shape,
            reserved_droplets=reserved_droplets,
        )
        if candidate is None or candidate == requested:
            suggestions[str(blocker_id)] = {
                "target": None,
                "from": requested,
                "reason": reason or "no_available_parking_found",
                "message": (
                    "No nearby parking target was found. Move a larger set of "
                    "droplets away from the merge area first."
                ),
            }
            continue
        search_corners[blocker_id] = candidate
        suggestions[str(blocker_id)] = {
            "target": candidate,
            "from": requested,
            "manhattan_distance": (
                abs(int(candidate[0]) - int(requested[0]))
                + abs(int(candidate[1]) - int(requested[1]))
            ),
            "reason": reason or "closest_available_parking_target",
            "message": (
                "Move this blocker to the suggested parking target, execute "
                "that segment, then retry the merge."
            ),
        }
    return suggestions


def nearest_available_droplet_target(
    *,
    droplet_id: int,
    requested_corner: Tuple[int, int],
    active_droplets: List[Any],
    current_corners: Dict[int, Tuple[int, int]],
    final_corners: Dict[int, Tuple[int, int]],
    matrix_shape: Optional[List[int]],
    reserved_droplets: Optional[List[Tuple[Any, Tuple[int, int]]]] = None,
) -> Tuple[Optional[Tuple[int, int]], Optional[str]]:
    if matrix_shape and len(matrix_shape) >= 2:
        search_limit = max(int(matrix_shape[0]), int(matrix_shape[1]))
    else:
        search_limit = 64

    requested_row, requested_col = int(requested_corner[0]), int(requested_corner[1])
    last_reason = None
    for radius in range(search_limit + 1):
        candidates = []
        for row_delta in range(-radius, radius + 1):
            col_distance = radius - abs(row_delta)
            if col_distance == 0:
                candidates.append((requested_row + row_delta, requested_col))
            else:
                candidates.append(
                    (requested_row + row_delta, requested_col - col_distance)
                )
                candidates.append(
                    (requested_row + row_delta, requested_col + col_distance)
                )
        for candidate in sorted(
            set(candidates),
            key=lambda item: (
                abs(item[0] - requested_row) + abs(item[1] - requested_col),
                max(abs(item[0] - requested_row), abs(item[1] - requested_col)),
                abs(item[0] - requested_row),
                abs(item[1] - requested_col),
                item[0],
                item[1],
            ),
        ):
            ok, reason = target_candidate_available(
                droplet_id=droplet_id,
                candidate_corner=candidate,
                active_droplets=active_droplets,
                current_corners=current_corners,
                final_corners=final_corners,
                matrix_shape=matrix_shape,
                reserved_droplets=reserved_droplets,
            )
            if ok:
                return (int(candidate[0]), int(candidate[1])), "closest_available_target"
            last_reason = reason
    return None, last_reason


def target_candidate_available(
    *,
    droplet_id: int,
    candidate_corner: Tuple[int, int],
    active_droplets: List[Any],
    current_corners: Dict[int, Tuple[int, int]],
    final_corners: Dict[int, Tuple[int, int]],
    matrix_shape: Optional[List[int]],
    reserved_droplets: Optional[List[Tuple[Any, Tuple[int, int]]]] = None,
) -> Tuple[bool, Optional[str]]:
    candidate_corner = (int(candidate_corner[0]), int(candidate_corner[1]))
    candidate_final_corners = dict(final_corners)
    candidate_final_corners[int(droplet_id)] = candidate_corner
    droplets_by_id = {
        int(getattr(droplet, "id")): droplet
        for droplet in active_droplets
        if getattr(droplet, "id", None) is not None
    }
    droplet = droplets_by_id.get(int(droplet_id))
    if droplet is None:
        return False, "droplet_not_active"

    candidate_positions = get_droplet_positions(droplet, candidate_corner)
    for row, col in candidate_positions:
        if not target_cell_in_bounds(row, col, matrix_shape):
            return False, "out_of_bounds"

    moving = candidate_corner != tuple(current_corners.get(int(droplet_id), candidate_corner))
    for other in active_droplets:
        other_id = int(getattr(other, "id"))
        if other_id == int(droplet_id):
            continue
        other_final = tuple(candidate_final_corners.get(other_id, current_corners[other_id]))
        other_positions = get_droplet_positions(other, other_final)
        for cell in candidate_positions:
            if cell in other_positions:
                return False, "footprint_overlap"
        if check_vital_space_conflict(droplet, candidate_corner, other, other_final):
            return False, "vital_space_conflict"
        if moving and check_vital_space_conflict(
            droplet,
            candidate_corner,
            other,
            tuple(current_corners[other_id]),
        ):
            return False, "target_uses_current_reserved_space"

    for reserved_droplet, reserved_corner in reserved_droplets or []:
        reserved_corner = tuple(reserved_corner)
        reserved_positions = get_droplet_positions(reserved_droplet, reserved_corner)
        if candidate_positions & reserved_positions:
            return False, "reserved_footprint_overlap"
        if check_vital_space_conflict(
            droplet,
            candidate_corner,
            reserved_droplet,
            reserved_corner,
        ):
            return False, "reserved_vital_space_conflict"

    return True, None


def target_cell_in_bounds(
    row: int,
    col: int,
    matrix_shape: Optional[List[int]],
) -> bool:
    if not matrix_shape or len(matrix_shape) < 2:
        return True
    return 0 <= int(row) < int(matrix_shape[0]) and 0 <= int(col) < int(matrix_shape[1])


def _normalize_matrix_shape(matrix_shape: Optional[Iterable[int]]) -> Optional[List[int]]:
    if matrix_shape is None:
        return None
    try:
        values = list(matrix_shape)
        if len(values) >= 2:
            return [int(values[0]), int(values[1])]
    except Exception:
        return None
    return None


def _pair(value: Any, name: str) -> Tuple[int, int]:
    if value is None:
        raise ValueError(f"{name} is required.")
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must be a two-item [row, col] coordinate.")
    return int(value[0]), int(value[1])
