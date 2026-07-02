# Field metrics — traffic_realistic_c020

- Weights: `models/car_brand_classification/outputs/traffic_realistic/weights/best.pt`
- Conf threshold: **0.2**
- Labelled crops evaluated: **240** (skipped 56 _unsure/_other_brand)

## Overall

- **Precision: 1.8%**
- **Recall: 0.8%**
- F1: 0.011
- TP 1 / FP 55 / FN 127 / TN 1

## Per-brand

| Brand | Labelled | Predicted | Correct | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| alfa romeo | 2 | 0 | 0 | 0.00 | 0.00 |
| audi | 9 | 0 | 0 | 0.00 | 0.00 |
| bmw | 13 | 3 | 1 | 0.33 | 0.08 |
| byd | 0 | 53 | 0 | 0.00 | 0.00 |
| citroen | 13 | 0 | 0 | 0.00 | 0.00 |
| daihatsu | 11 | 0 | 0 | 0.00 | 0.00 |
| fiat | 3 | 0 | 0 | 0.00 | 0.00 |
| ford | 18 | 0 | 0 | 0.00 | 0.00 |
| honda | 2 | 0 | 0 | 0.00 | 0.00 |
| isuzu | 8 | 0 | 0 | 0.00 | 0.00 |
| mazda | 2 | 0 | 0 | 0.00 | 0.00 |
| mercedes-benz | 12 | 0 | 0 | 0.00 | 0.00 |
| mitsubishi | 4 | 0 | 0 | 0.00 | 0.00 |
| nissan | 13 | 0 | 0 | 0.00 | 0.00 |
| peugeot | 1 | 0 | 0 | 0.00 | 0.00 |
| renault | 6 | 0 | 0 | 0.00 | 0.00 |
| skoda | 3 | 0 | 0 | 0.00 | 0.00 |
| ssangyong | 1 | 0 | 0 | 0.00 | 0.00 |
| suzuki | 4 | 0 | 0 | 0.00 | 0.00 |
| toyota | 25 | 0 | 0 | 0.00 | 0.00 |
| vauxhall | 15 | 0 | 0 | 0.00 | 0.00 |
| volkswagen | 18 | 0 | 0 | 0.00 | 0.00 |

## Top confusions (mismatches)

| Label | Predicted | Count |
|---|---|---:|
| toyota | (no commit) | 17 |
| ford | (no commit) | 16 |
| vauxhall | (no commit) | 12 |
| volkswagen | (no commit) | 11 |
| mercedes-benz | (no commit) | 11 |
| daihatsu | byd | 11 |
| bmw | (no commit) | 10 |
| nissan | (no commit) | 10 |
| citroen | (no commit) | 9 |
| toyota | byd | 8 |
| audi | (no commit) | 7 |
| volkswagen | byd | 6 |
| isuzu | (no commit) | 5 |
| renault | (no commit) | 4 |
| citroen | byd | 4 |