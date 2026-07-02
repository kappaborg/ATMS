"""Unit tests for simulation/demo/video_source.py — the real-video pipeline.

Covers the parts that don't require YOLOv8/opencv: the IoU tracker logic,
direction-assignment heuristic, and speed estimate. The YOLOv8 loop itself
is exercised end-to-end by running the demo against a sample video — see
docs/demos/pilot-pitch.md.
"""

from __future__ import annotations

from pathlib import Path

from shared.atms_common.emissions import VehicleClass
from simulation.demo.video_source import (
    COCO_TO_VEHICLE_CLASS,
    Detection,
    IoUTracker,
    VideoConfig,
    VideoEmissionPipeline,
    _assign_direction,
    _fuse_brand_observations,
    _iou,
    normalise_brand,
)

# ---------------------------------------------------------------------------
# COCO id → VehicleClass mapping
# ---------------------------------------------------------------------------


class TestCocoMapping:
    def test_car_maps(self):
        assert COCO_TO_VEHICLE_CLASS[2] is VehicleClass.CAR

    def test_truck_maps(self):
        assert COCO_TO_VEHICLE_CLASS[7] is VehicleClass.TRUCK

    def test_bus_maps(self):
        assert COCO_TO_VEHICLE_CLASS[5] is VehicleClass.BUS

    def test_unmapped_coco_id_is_absent(self):
        # COCO id 0 is `person`, not a vehicle.
        assert 0 not in COCO_TO_VEHICLE_CLASS


# ---------------------------------------------------------------------------
# IoU
# ---------------------------------------------------------------------------


class TestIoU:
    def test_identical_bbox_is_1(self):
        b = (10.0, 10.0, 50.0, 50.0)
        assert _iou(b, b) == 1.0

    def test_disjoint_bbox_is_0(self):
        a = (0.0, 0.0, 10.0, 10.0)
        b = (100.0, 100.0, 110.0, 110.0)
        assert _iou(a, b) == 0.0

    def test_partial_overlap(self):
        # Two 20x20 boxes, 10x10 overlap. inter=100, each area=400,
        # union = 400 + 400 - 100 = 700, iou = 100/700 = 1/7.
        a = (0.0, 0.0, 20.0, 20.0)
        b = (10.0, 10.0, 30.0, 30.0)
        assert abs(_iou(a, b) - 1 / 7) < 0.001

    def test_zero_area_bbox_returns_0(self):
        a = (10.0, 10.0, 10.0, 10.0)  # zero area
        b = (5.0, 5.0, 15.0, 15.0)
        assert _iou(a, b) == 0.0


# ---------------------------------------------------------------------------
# IoUTracker
# ---------------------------------------------------------------------------


class TestIoUTracker:
    def test_new_detection_creates_track(self):
        tracker = IoUTracker()
        tracks = tracker.update([(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))], frame_idx=1)
        assert len(tracks) == 1
        assert tracks[0].vehicle_class is VehicleClass.CAR
        assert tracks[0].track_id == 1

    def test_continuing_detection_keeps_same_id(self):
        tracker = IoUTracker()
        tracker.update([(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))], frame_idx=1)
        # Slight movement — bbox stays mostly overlapping
        tracks = tracker.update([(VehicleClass.CAR, (12.0, 12.0, 32.0, 32.0))], frame_idx=2)
        assert len(tracks) == 1
        assert tracks[0].track_id == 1  # same track
        assert len(tracks[0].pixel_history) == 2

    def test_disjoint_detection_creates_new_track(self):
        tracker = IoUTracker()
        tracker.update([(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))], frame_idx=1)
        tracks = tracker.update([(VehicleClass.CAR, (100.0, 100.0, 120.0, 120.0))], frame_idx=2)
        # Original track expired? No, ttl is 5 frames. We have 2 active tracks.
        assert len(tracks) == 2
        ids = sorted(t.track_id for t in tracks)
        assert ids == [1, 2]

    def test_different_class_does_not_match_same_bbox(self):
        tracker = IoUTracker()
        tracker.update([(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))], frame_idx=1)
        tracks = tracker.update([(VehicleClass.BUS, (12.0, 12.0, 32.0, 32.0))], frame_idx=2)
        # CAR track ages but doesn't match the BUS detection.
        # Both should be alive at frame 2 (ttl=5).
        assert len(tracks) == 2
        # The BUS should be a new track (id=2).
        bus_tracks = [t for t in tracks if t.vehicle_class is VehicleClass.BUS]
        assert len(bus_tracks) == 1
        assert bus_tracks[0].track_id == 2

    def test_stale_track_expires(self):
        tracker = IoUTracker(ttl_frames=3)
        tracker.update([(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))], frame_idx=1)
        # Skip 5 frames with no detection
        for f in range(2, 10):
            tracks = tracker.update([], frame_idx=f)
        # By frame 10, the original track (last_seen=1) is way past TTL
        assert len(tracks) == 0

    def test_multiple_simultaneous_vehicles(self):
        tracker = IoUTracker()
        dets = [
            (VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0)),
            (VehicleClass.TRUCK, (200.0, 200.0, 250.0, 250.0)),
            (VehicleClass.BUS, (400.0, 400.0, 450.0, 460.0)),
        ]
        tracks = tracker.update(dets, frame_idx=1)
        assert len(tracks) == 3
        classes = {t.vehicle_class for t in tracks}
        assert classes == {VehicleClass.CAR, VehicleClass.TRUCK, VehicleClass.BUS}


# ---------------------------------------------------------------------------
# Direction assignment heuristic
# ---------------------------------------------------------------------------


class TestAssignDirection:
    def test_center_of_frame(self):
        # dx == dy: tie goes to east_west (>=)
        assert _assign_direction((500.0, 500.0), 1000, 1000) == "east_west"

    def test_far_left_is_ew(self):
        assert _assign_direction((50.0, 500.0), 1000, 1000) == "east_west"

    def test_far_right_is_ew(self):
        assert _assign_direction((950.0, 500.0), 1000, 1000) == "east_west"

    def test_top_is_ns(self):
        assert _assign_direction((500.0, 50.0), 1000, 1000) == "north_south"

    def test_bottom_is_ns(self):
        assert _assign_direction((500.0, 950.0), 1000, 1000) == "north_south"

    def test_top_left_corner_is_ew_when_more_horizontal(self):
        # (100, 200) on 1000x1000: dx=400, dy=300 → ew
        assert _assign_direction((100.0, 200.0), 1000, 1000) == "east_west"

    def test_top_left_corner_is_ns_when_more_vertical(self):
        # (400, 100) on 1000x1000: dx=100, dy=400 → ns
        assert _assign_direction((400.0, 100.0), 1000, 1000) == "north_south"


# ---------------------------------------------------------------------------
# Speed estimate
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Brand label normalisation
# ---------------------------------------------------------------------------


class TestNormaliseBrand:
    def test_known_brand_normalises(self):
        assert normalise_brand("BMW") == "bmw"
        assert normalise_brand("Toyota") == "toyota"
        assert normalise_brand("Mercedes") == "mercedes-benz"

    def test_training_set_typo_is_corrected(self):
        # The training set has "hyndai" (sic); we want "hyundai"
        assert normalise_brand("hyndai") == "hyundai"

    def test_generic_car_class_is_none(self):
        # The generic `car` class carries no brand info
        assert normalise_brand("car") is None

    def test_unknown_label_is_none(self):
        assert normalise_brand("zeppelin") is None

    def test_empty_string_is_none(self):
        assert normalise_brand("") is None

    def test_none_is_none(self):
        assert normalise_brand(None) is None

    def test_byd_underscore_variant(self):
        # The training set uses "Byd_F3" for the BYD F3 model
        assert normalise_brand("Byd_F3") == "byd"

    def test_case_insensitive(self):
        assert normalise_brand("TOYOTA") == "toyota"
        assert normalise_brand("toyota") == "toyota"
        assert normalise_brand("ToYoTa") == "toyota"


# ---------------------------------------------------------------------------
# Brand fusion (match brand-detector boxes to YOLOv8 vehicle detections)
# ---------------------------------------------------------------------------


class TestFuseBrandObservations:
    def test_no_brand_obs_returns_detections_unchanged(self):
        dets = [Detection(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))]
        fused = _fuse_brand_observations(dets, [])
        assert len(fused) == 1
        assert fused[0].brand is None

    def test_high_iou_brand_attaches(self):
        dets = [Detection(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))]
        brand_obs = [((11.0, 11.0, 31.0, 31.0), "toyota", 0.92)]
        fused = _fuse_brand_observations(dets, brand_obs)
        assert fused[0].brand == "toyota"
        assert fused[0].brand_confidence == 0.92

    def test_low_iou_brand_does_not_attach(self):
        dets = [Detection(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))]
        # Disjoint bbox — should not match
        brand_obs = [((100.0, 100.0, 130.0, 130.0), "toyota", 0.92)]
        fused = _fuse_brand_observations(dets, brand_obs)
        assert fused[0].brand is None

    def test_best_iou_wins_when_multiple_brand_obs(self):
        dets = [Detection(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))]
        # Two brand observations — the second is much closer to the detection
        brand_obs = [
            ((25.0, 25.0, 45.0, 45.0), "porsche", 0.85),  # low IoU
            ((10.0, 10.0, 30.0, 30.0), "toyota", 0.90),  # perfect IoU
        ]
        fused = _fuse_brand_observations(dets, brand_obs)
        assert fused[0].brand == "toyota"

    def test_brand_obs_not_double_counted(self):
        dets = [
            Detection(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0)),
            Detection(VehicleClass.CAR, (100.0, 10.0, 120.0, 30.0)),
        ]
        # Single brand observation — should match the closer detection only
        brand_obs = [((10.0, 10.0, 30.0, 30.0), "toyota", 0.90)]
        fused = _fuse_brand_observations(dets, brand_obs)
        brands = [d.brand for d in fused]
        assert brands.count("toyota") == 1
        assert brands.count(None) == 1


# ---------------------------------------------------------------------------
# Tracker brand-cache behaviour
# ---------------------------------------------------------------------------


class TestTrackerBrandCache:
    def test_brand_persists_across_frames_without_re_observation(self):
        tracker = IoUTracker()
        tracker.update(
            [
                Detection(
                    VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0), brand="toyota", brand_confidence=0.9
                )
            ],
            frame_idx=1,
        )
        # Frame 2: same vehicle, no brand observed (brand detector missed)
        tracks = tracker.update(
            [Detection(VehicleClass.CAR, (12.0, 11.0, 32.0, 31.0))], frame_idx=2
        )
        assert tracks[0].brand == "toyota"  # cached

    def test_higher_confidence_overwrites(self):
        tracker = IoUTracker()
        tracker.update(
            [
                Detection(
                    VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0), brand="toyota", brand_confidence=0.5
                )
            ],
            frame_idx=1,
        )
        # Frame 2: same vehicle, brand detector now strongly says BMW
        tracks = tracker.update(
            [
                Detection(
                    VehicleClass.CAR, (12.0, 11.0, 32.0, 31.0), brand="bmw", brand_confidence=0.85
                )
            ],
            frame_idx=2,
        )
        assert tracks[0].brand == "bmw"

    def test_marginally_higher_confidence_does_not_overwrite(self):
        tracker = IoUTracker()
        tracker.update(
            [
                Detection(
                    VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0), brand="toyota", brand_confidence=0.7
                )
            ],
            frame_idx=1,
        )
        # Just slightly more confident — within the +0.1 hysteresis band
        tracks = tracker.update(
            [
                Detection(
                    VehicleClass.CAR, (12.0, 11.0, 32.0, 31.0), brand="bmw", brand_confidence=0.75
                )
            ],
            frame_idx=2,
        )
        # Should NOT flip — guards against single-frame jitter
        assert tracks[0].brand == "toyota"

    def test_unbranded_new_track_stays_unbranded(self):
        tracker = IoUTracker()
        tracks = tracker.update(
            [Detection(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))], frame_idx=1
        )
        assert tracks[0].brand is None


def test_speed_estimate_via_tracker_history():
    """A continuing track's bbox displacement should produce the correct
    speed in km/h given a known pixels-per-meter calibration."""
    cfg = VideoConfig(
        video_path=Path("/tmp/nonexistent.mp4"),
        pixels_per_meter=10.0,
    )
    pipeline = VideoEmissionPipeline(cfg)

    # Frame 1: bbox centre (20, 20). Frame 2: bbox shifted by (+5, 0) so
    # IoU > 0.3 and the tracker keeps the same id.
    # 25x25 boxes overlapping by 20x25 → inter = 500, union = 1250 - 500 ... let me
    # use small bboxes that overlap clearly: 20x20 boxes shifted by 5px.
    # inter = 15*20 = 300, union = 400 + 400 - 300 = 500 → iou = 0.6, well above threshold.
    pipeline.tracker.update([(VehicleClass.CAR, (10.0, 10.0, 30.0, 30.0))], frame_idx=1)
    tracks = pipeline.tracker.update([(VehicleClass.CAR, (15.0, 10.0, 35.0, 30.0))], frame_idx=2)
    assert len(tracks) == 1  # continuing track
    assert tracks[0].track_id == 1
    assert len(tracks[0].pixel_history) == 2

    # 5-pixel x-displacement, 0-pixel y-displacement → 5 px per frame.
    # At 10 pixels/meter and 30 fps:
    #   meters per frame = 5/10 = 0.5 m
    #   seconds per frame = 1/30
    #   m/s = 0.5 * 30 = 15 m/s
    #   km/h = 15 * 3.6 = 54 km/h
    pipeline._update_speeds(tracks, fps=30.0)
    expected_kmh = (5.0 / 10.0) * 30.0 * 3.6
    assert abs(tracks[0].speed_kmh - expected_kmh) / expected_kmh < 0.05
