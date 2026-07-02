# 🔍 Decision Debugging Guide

## Issues Fixed

### 1. ✅ Tkinter Warning Suppressed
- Dashboard is optional, warning removed
- Monitoring works without dashboard

### 2. ✅ Decision Debugging Added
- Added debug logs to track decision creation
- Added placeholder message when no decision
- Better error messages

## Debugging Decisions

### Check Logs For:
1. **"Making decision with X detections"** - Decision process started
2. **"✅ Decision made: GREEN (frame X)"** - Decision created successfully
3. **"📤 Decision sent to Kafka"** - Decision sent to Kafka
4. **"📊 Drawing decision: GREEN"** - Decision being drawn on screen

### Common Issues:

#### No Decisions Being Made
- Check: "decision_engine not initialized" warning
- Check: "No detections to make decision from" message
- Check: Frame count is divisible by 30 (decision_update_interval)

#### Decisions Not in Kafka
- Check: "Kafka producer not available" warning
- Check: Kafka connection errors
- Verify Kafka is running: `docker ps | grep kafka`

#### Decisions Not on Screen
- Check: "Drawing decision" messages in logs
- Check: current_decision is set (not None)
- Check: draw_decision is being called

## Quick Test

Run processor and watch for:
```
✅ Decision made: GREEN (frame 30, detections: 5)
📤 Decision sent to Kafka: GREEN (ID: xxxxxxxx, topic: decisions, partition: 0)
📊 Drawing decision: GREEN (frame 30)
```

If you don't see these, check the debug logs above.
