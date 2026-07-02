#!/usr/bin/env bash
# scripts/training_status.sh
#
# Instant status check for the running brand-detector fine-tune.
# Reads the training log and prints completed / remaining / ETA.
#
# Usage:
#   ./scripts/training_status.sh
#   ./scripts/training_status.sh 28174   # explicit PID

set -u

PID="${1:-28174}"
LOG="${ATMS_TRAIN_LOG:-/tmp/atms-train.log}"

if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "⚠ Training PID $PID not alive."
    echo "  Either it finished or it was killed. Check ${LOG}'s tail and"
    echo "  the outputs/traffic_realistic/weights/ directory for the saved"
    echo "  best.pt + last.pt to decide which."
    exit 1
fi

elapsed_hms=$(ps -p "$PID" -o etime= | tr -d ' ')
latest_batch=$(grep -oE '[[:space:]][0-9]+/100[[:space:]]' "$LOG" 2>/dev/null | tail -1 | tr -d ' ')

python3 - <<PY
import datetime, sys
elapsed_hms = "$elapsed_hms"
latest_batch = "$latest_batch"

# Parse "DD-HH:MM:SS" / "HH:MM:SS" / "MM:SS"
parts = [int(p) for p in elapsed_hms.replace('-', ':').split(':')]
while len(parts) < 4: parts = [0] + parts
d, h, m, s = parts
elapsed_s = d*86400 + h*3600 + m*60 + s

if not latest_batch:
    print(f"  elapsed: {elapsed_hms}")
    print(f"  (no epoch counter in log yet — warming up)")
    sys.exit(0)

# latest_batch e.g. "51/100" -> in-flight epoch = 51, completed = 50
in_flight = int(latest_batch.split('/')[0])
total = int(latest_batch.split('/')[1])
done = max(0, in_flight - 1)
rate_min = (elapsed_s / max(done, 1)) / 60
remaining_min = rate_min * (total - done)
finish = datetime.datetime.now() + datetime.timedelta(minutes=remaining_min)

bar_filled = int((done / total) * 30)
bar = "█" * bar_filled + "░" * (30 - bar_filled)
print()
print(f"  ┃ {bar} ┃  {done}/{total} epochs")
print()
print(f"  elapsed:    {elapsed_hms}")
print(f"  in flight:  epoch {in_flight}")
print(f"  rate:       {rate_min:.2f} min/epoch")
print(f"  remaining:  {remaining_min/60:.1f} h ({remaining_min:.0f} min)")
print(f"  ETA:        {finish.strftime('%H:%M')}  ({finish.strftime('%a %b %d')})")
print()
PY
