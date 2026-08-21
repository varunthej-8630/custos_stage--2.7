# utils.py — CUSTOS shared utilities
# Single source of truth. Import from here — never re-define in other modules.

def iou(box_a, box_b) -> float:
    """
    Intersection-over-Union of two [x1,y1,x2,y2] boxes.
    Returns 0.0–1.0. Used for zone overlap detection.
    """
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = (ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter
    return inter / (union + 1e-6)


def box_centre(box):
    """Return (cx, cy) of a [x1,y1,x2,y2] box."""
    x1, y1, x2, y2 = box
    return (x1 + x2) / 2, (y1 + y2) / 2


def box_foot(box):
    """Return (foot_x, foot_y) — bottom-centre of bounding box."""
    x1, _, x2, y2 = box
    return (x1 + x2) / 2, y2