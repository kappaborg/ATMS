# Reusable Trajectory Predictor

This folder is a standalone trajectory package that you can copy into another
project, including a drone trajectory project.

## What Is Improved

- Removes noisy path spikes before forecasting.
- Smooths raw trajectory history for more stable motion estimates.
- Estimates velocity and acceleration from recent motion, not one frame only.
- Supports curved motion using a simple turn-rate model.
- Uses only the Python standard library, so it is easier to reuse elsewhere.

## Files

- `models.py`: prediction data structures
- `predictor.py`: main reusable predictor
- `adapters.py`: bbox-to-center helpers
- `__init__.py`: package exports

## Quick Usage

```python
from trajectory_reuse import ReusableTrajectoryPredictor

predictor = ReusableTrajectoryPredictor(
    prediction_horizon=4.0,
    dt=0.2,
)

history = [
    (0.0, 0.0),
    (0.8, 0.2),
    (1.7, 0.6),
    (2.7, 1.1),
    (3.8, 1.8),
]

prediction = predictor.predict(
    track_id=7,
    trajectory=history,
    velocity=(0.0, 0.0),
    object_type="drone",
    context={"max_speed": 20.0},
)

print(prediction.to_dict())
```

## Using In Another Project

1. Copy the whole `trajectory_reuse` folder.
2. Put it inside your target project's source directory.
3. Import it with `from trajectory_reuse import ReusableTrajectoryPredictor`.

## Notes

- The predictor works with any 2D coordinates: pixels, meters, map units, or
  drone-local coordinates.
- `dt` should match the time gap between your trajectory samples.
- If your drone project uses 3D coordinates, extend the same logic with `z`
  using this package as the 2D base.
