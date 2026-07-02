"""Streamlit ground-truth labeller for vehicle brand identification.

Companion of `scripts/prepare_ground_truth.py` (extracts crops) and
`scripts/compute_field_metrics.py` (turns labels into precision/recall).

This app shows one crop at a time alongside its parent frame (so the
labeller can see vehicle-in-context), offers a searchable brand picker,
and persists every commit immediately to `data/ground_truth/labels.json`
so partial progress is never lost.

Run from repo root:

    streamlit run services/labeler/app.py

Open the URL it prints (default http://localhost:8501).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GT_DIR = REPO_ROOT / "data" / "ground_truth"
METADATA_PATH = GT_DIR / "metadata.json"
LABELS_PATH = GT_DIR / "labels.json"

# Brand options: the DVM-Car class list (current dvm_car_v2 dataset) plus a
# handful of meta-labels the labeller will need:
#  - _other_brand: a real branded vehicle whose brand isn't in our 53 classes
#    (e.g. Skoda Octavia would resolve, but Chinese brands like Geely / Chery
#    are NOT in the UK-market DVM-Car set)
#  - _not_a_car: YOLO mis-detected — actually a truck/bus/motorcycle/etc.
#  - _unsure: human can't tell the brand from this crop (blur, angle, etc.)
META_LABELS = ["_other_brand", "_not_a_car", "_unsure"]


@st.cache_data
def load_brand_list() -> list[str]:
    """Read the active DVM-Car data.yaml so we always show the same brand
    set the model is trained on."""
    yaml_path = REPO_ROOT / "data" / "car_brand_dataset_dvm" / "data.yaml"
    if not yaml_path.exists():
        return []
    with yaml_path.open() as f:
        spec = yaml.safe_load(f)
    return list(spec.get("names", []))


def load_metadata() -> list[dict]:
    if not METADATA_PATH.exists():
        return []
    return json.loads(METADATA_PATH.read_text())


def load_labels() -> dict[str, dict]:
    if not LABELS_PATH.exists():
        return {}
    return json.loads(LABELS_PATH.read_text())


def save_labels(labels: dict[str, dict]) -> None:
    LABELS_PATH.write_text(json.dumps(labels, indent=2))


def main() -> None:
    st.set_page_config(page_title="ATMS — Ground-truth labeller", layout="wide")

    st.title("ATMS — Brand ground-truth labeller")
    st.caption(
        "Label each vehicle's brand so we can measure precision/recall on the "
        "trained brand model. Labels save immediately — close the tab any time."
    )

    metadata = load_metadata()
    labels = load_labels()
    brand_list = load_brand_list()

    if not metadata:
        st.error(
            "No crops yet. Run "
            "`python3 scripts/prepare_ground_truth.py --videos videos/TEST.mp4 ...` "
            "first."
        )
        return
    if not brand_list:
        st.error("Couldn't load brand list from data/car_brand_dataset_dvm/data.yaml")
        return

    # Order: unlabelled first, then labelled (so the labeller naturally walks
    # the queue but can still revise earlier work).
    crop_ids = [m["id"] for m in metadata]
    unlabelled = [cid for cid in crop_ids if cid not in labels]
    labelled = [cid for cid in crop_ids if cid in labels]
    ordered = unlabelled + labelled

    # Sidebar — progress + navigation
    total = len(crop_ids)
    done = len(labelled)
    pct = (done / total * 100) if total else 0
    st.sidebar.metric("Progress", f"{done} / {total}", f"{pct:.1f}%")
    st.sidebar.progress(done / total if total else 0)

    filter_mode = st.sidebar.radio(
        "Show",
        ["Unlabelled first", "All in order", "Only labelled"],
        index=0,
    )
    if filter_mode == "All in order":
        ordered = crop_ids
    elif filter_mode == "Only labelled":
        ordered = labelled or []

    if not ordered:
        st.success("All crops labelled! Run `python3 scripts/compute_field_metrics.py` next.")
        return

    # Index of the currently shown crop
    if "cursor" not in st.session_state:
        st.session_state.cursor = 0
    st.session_state.cursor = max(0, min(st.session_state.cursor, len(ordered) - 1))

    current_id = ordered[st.session_state.cursor]
    current = next(m for m in metadata if m["id"] == current_id)

    # ----------------------------- Layout ----------------------------------
    # Left column: full frame (with bbox highlighted) + the crop close-up.
    # Right column: brand picker + Save/Skip/Prev/Next.

    col_img, col_form = st.columns([2, 1])

    with col_img:
        st.subheader(f"Crop {current_id}  ({st.session_state.cursor + 1}/{len(ordered)})")
        st.image(
            str(GT_DIR / "frames" / f"{current_id}.jpg"),
            caption=(
                f"{Path(current['source_video']).name}  "
                f"@ frame {current['frame_idx']} ({current['time_in_video_s']}s)  "
                f"— YOLOv8 class: {current['vehicle_class']}"
            ),
            use_container_width=True,
        )
        st.image(
            str(GT_DIR / "crops" / f"{current_id}.jpg"),
            caption=(
                f"Cropped vehicle  bbox={current['bbox']}  "
                f"{current['bbox_size_px'][0]}×{current['bbox_size_px'][1]} px  "
                f"YOLO conf {current['yolo_conf']}"
            ),
            width=400,
        )

    with col_form:
        existing = labels.get(current_id, {})
        existing_brand = existing.get("brand", "")

        st.subheader("Label")
        if existing_brand:
            st.success(f"Currently labelled: **{existing_brand}**")
        else:
            st.info("Not yet labelled")

        # Build the picker — three groups (real brands, meta-labels)
        options = ["— pick —"] + brand_list + META_LABELS
        default_idx = options.index(existing_brand) if existing_brand in options else 0
        picked = st.selectbox(
            "Brand",
            options,
            index=default_idx,
            help=(
                "Real brand: pick from the list (searchable). "
                "Brand not in list: _other_brand. "
                "Not actually a passenger car (e.g., bus/truck): _not_a_car. "
                "Can't tell from this image: _unsure."
            ),
        )
        notes = st.text_input("Notes (optional)", value=existing.get("notes", ""))

        col_save, col_skip = st.columns(2)
        with col_save:
            if st.button("Save + Next", type="primary", use_container_width=True):
                if picked == "— pick —":
                    st.warning("Pick a label or press Skip")
                else:
                    labels[current_id] = {
                        "brand": picked,
                        "notes": notes.strip(),
                        "labelled_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    save_labels(labels)
                    st.session_state.cursor = min(
                        st.session_state.cursor + 1, len(ordered) - 1
                    )
                    st.rerun()
        with col_skip:
            if st.button("Skip", use_container_width=True):
                st.session_state.cursor = min(
                    st.session_state.cursor + 1, len(ordered) - 1
                )
                st.rerun()

        col_prev, col_next = st.columns(2)
        with col_prev:
            if st.button("← Prev", use_container_width=True):
                st.session_state.cursor = max(0, st.session_state.cursor - 1)
                st.rerun()
        with col_next:
            if st.button("Next →", use_container_width=True):
                st.session_state.cursor = min(
                    st.session_state.cursor + 1, len(ordered) - 1
                )
                st.rerun()

        st.divider()
        st.caption(
            "Tip: type in the brand picker to filter the 53-brand list. "
            "Save + Next is the main flow — use Skip when you want to come "
            "back to a hard crop later."
        )


main()
