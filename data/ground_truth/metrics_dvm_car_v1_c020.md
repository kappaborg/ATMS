# Field metrics — dvm_car_v1_c020

- Weights: `models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt`
- Conf threshold: **0.2**
- Labelled crops evaluated: **240** (skipped 56 _unsure/_other_brand)

## Overall

- **Precision: 50.0%**
- **Recall: 2.2%**
- F1: 0.043
- TP 4 / FP 4 / FN 175 / TN 1

## Per-brand

| Brand | Labelled | Predicted | Correct | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| alfa romeo | 2 | 0 | 0 | 0.00 | 0.00 |
| audi | 9 | 0 | 0 | 0.00 | 0.00 |
| bmw | 13 | 3 | 3 | 1.00 | 0.23 |
| chrysler | 0 | 1 | 0 | 0.00 | 0.00 |
| citroen | 13 | 0 | 0 | 0.00 | 0.00 |
| daihatsu | 11 | 0 | 0 | 0.00 | 0.00 |
| fiat | 3 | 0 | 0 | 0.00 | 0.00 |
| ford | 18 | 0 | 0 | 0.00 | 0.00 |
| honda | 2 | 0 | 0 | 0.00 | 0.00 |
| isuzu | 8 | 0 | 0 | 0.00 | 0.00 |
| kia | 0 | 1 | 0 | 0.00 | 0.00 |
| mazda | 2 | 0 | 0 | 0.00 | 0.00 |
| mercedes-benz | 12 | 0 | 0 | 0.00 | 0.00 |
| mitsubishi | 4 | 0 | 0 | 0.00 | 0.00 |
| nissan | 13 | 1 | 1 | 1.00 | 0.08 |
| peugeot | 1 | 2 | 0 | 0.00 | 0.00 |
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
| toyota | (no commit) | 24 |
| ford | (no commit) | 18 |
| volkswagen | (no commit) | 18 |
| vauxhall | (no commit) | 13 |
| citroen | (no commit) | 13 |
| mercedes-benz | (no commit) | 12 |
| nissan | (no commit) | 12 |
| daihatsu | (no commit) | 11 |
| bmw | (no commit) | 10 |
| audi | (no commit) | 8 |
| isuzu | (no commit) | 8 |
| renault | (no commit) | 6 |
| suzuki | (no commit) | 4 |
| mitsubishi | (no commit) | 4 |
| skoda | (no commit) | 3 |