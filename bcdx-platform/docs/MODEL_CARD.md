# Model Card — BC-Dx Platform

Generated: 2026-10-04T11:03:46Z

## Environment

| Item | Value |
|---|---|
| Python | 3.12.4 |
| scikit-learn | 1.3.0 |
| Platform | Windows 11 |
| Random seed | 42 |
| CV folds | 5 |

## Methodology

- Every model is a `Pipeline(StandardScaler -> Classifier)`. The scaler is
  fitted **inside** each CV fold, which removes the train/test leakage that
  was present in the original implementation.
- Metrics come from 5-fold stratified cross-validation on the training split,
  plus a single held-out 20% test split used only for final reporting.
- Probabilities are calibrated (`CalibratedClassifierCV`) so that reported
  risk values are meaningful rather than raw model scores.
- Decision threshold is tuned on the held-out set via Youden's J statistic
  and stored per model in the registry.

## Label Semantics (global, must not change)

| Value | Breast | Heart |
|---|---|---|
| 0 | benign (良性) | no disease (健康) |
| 1 | malignant (恶性) | disease present (患病) |

## Module: breast — 乳腺癌 / Breast Cancer

- Samples: 569
- Features: 30
- Class balance: 357 negative / 212 positive
- Champion: `breast_xgb_v1.0`

| Model | CV AUC | CV Acc | Test AUC | Test Acc | Recall | Spec. | Brier | Thr. |
|---|---|---|---|---|---|---|---|---|
| 逻辑回归 | 0.9958 ± 0.0047 | 0.9736 ± 0.0149 | **0.9944** | 0.9825 | 0.9762 | 0.9861 | 0.0174 | 0.2443 |
| 随机森林 | 0.9878 ± 0.0072 | 0.9604 ± 0.0179 | **0.9911** | 0.9737 | 0.9286 | 1.0 | 0.0296 | 0.5166 |
| XGBoost | 0.9935 ± 0.0046 | 0.9736 ± 0.0088 | **0.9959** | 0.9912 | 0.9762 | 1.0 | 0.017 | 0.1701 |

## Module: heart — 心脏病 / Heart Disease

- Samples: 303
- Features: 13
- Class balance: 164 negative / 139 positive
- Champion: `heart_rf_v1.0`

| Model | CV AUC | CV Acc | Test AUC | Test Acc | Recall | Spec. | Brier | Thr. |
|---|---|---|---|---|---|---|---|---|
| 逻辑回归 | 0.896 ± 0.0148 | 0.8264 ± 0.0172 | **0.9556** | 0.9016 | 0.8571 | 0.9394 | 0.097 | 0.6633 |
| 随机森林 | 0.8809 ± 0.0347 | 0.8098 ± 0.0169 | **0.9589** | 0.9344 | 0.9286 | 0.9394 | 0.088 | 0.6321 |
| XGBoost | 0.854 ± 0.0295 | 0.7727 ± 0.0294 | **0.9351** | 0.9016 | 0.8929 | 0.9091 | 0.1053 | 0.6834 |

## Intended Use

Research and educational decision support. **NOT a medical device.**
Outputs must never be used as the sole basis for a clinical decision.

## Known Limitations

- Trained exclusively on small public datasets (WDBC n=569, UCI Heart n=303).
- No external validation cohort; performance on other populations is unknown.
- Single-centre data collection with demographic skew.
- Feature values must be produced by an accredited laboratory pipeline.
