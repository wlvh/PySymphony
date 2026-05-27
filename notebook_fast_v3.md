import re
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    log_loss,
    brier_score_loss,
    accuracy_score,
)
from sklearn.calibration import calibration_curve


# ----------------------------
# 0. Config
# ----------------------------

ANS_K = "insured_duns_number"

# Conservative: premium may be post-quote / post-underwriting. Exclude until confirmed.
DROP_PREMIUM_BAND = True

# Default: do not use hundreds of external payload columns.
# Availability flags are still used.
INCLUDE_EXTERNAL_PAYLOAD = False

# Hidden prediction: train at most one final model.
USE_SINGLE_FINAL_MODEL_FOR_HIDDEN = True
MIN_FINAL_TRAIN_ROWS = 80
MIN_SAMPLE_PER_TRANSFORMED_FEATURE = 5.0

# Validation / preprocessing.
VALID_FRACTION = 0.25
MAX_CAT_CARDINALITY = 60
NUMERIC_PARSE_THRESHOLD = 0.85
LOGISTIC_C_GRID = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0]
LOGISTIC_MAX_ITER = 1000

RECENT_WINDOWS_DAYS = [90, 180, 365]
MIN_RECENT_N = 30

# Target encoding settings.
ADD_TARGET_ENCODING = True
TARGET_ENCODING_SMOOTHING = 20.0
TARGET_ENCODE_COLS_BASE = [
    "broker_norm",
    "subline_norm",
    "insured_country_norm",
    "region_norm",
    "industry_group_norm",
]

# Diagnostics.
DO_SEGMENTED_REPORT = True
DO_CALIBRATION_TABLE = True
DO_BOOTSTRAP_CI = True
BOOTSTRAP_N = 200
BOOTSTRAP_RANDOM_SEED = 42


# ----------------------------
# 1. Utilities
# ----------------------------

def display_or_print(df, n=None):
    out = df if n is None else df.head(n)
    try:
        display(out)
    except Exception:
        print(out.to_string(index=False))


def clean_key(s):
    """Normalize DUNS-like keys, keeping digits only."""
    out = s.astype("string").str.strip().str.upper()
    out = out.replace({
        "": pd.NA,
        "NAN": pd.NA,
        "NONE": pd.NA,
        "NULL": pd.NA,
        "<NA>": pd.NA,
    })
    out = out.str.replace(r"\.0$", "", regex=True)
    out = out.str.replace(r"\D+", "", regex=True)
    out = out.replace({"": pd.NA})
    return out


def clean_cat(s):
    out = s.astype("string").str.strip().str.lower()
    out = out.replace({
        "": pd.NA,
        "nan": pd.NA,
        "none": pd.NA,
        "null": pd.NA,
        "<na>": pd.NA,
    })
    return out


def to_binary_label(s):
    """Robust conversion for bound."""
    num = pd.to_numeric(s, errors="coerce")
    txt = s.astype("string").str.strip().str.upper()
    mapped = txt.map({
        "TRUE": 1, "T": 1, "YES": 1, "Y": 1, "1": 1, "BOUND": 1,
        "FALSE": 0, "F": 0, "NO": 0, "N": 0, "0": 0,
        "NOT BOUND": 0, "UNBOUND": 0,
    })
    out = num.where(num.notna(), mapped)
    out = pd.to_numeric(out, errors="coerce")
    out = out.where(out.isin([0, 1]))
    return out.astype(float)


def parse_csad_datepll(s):
    """Parse csad DATEPLL, e.g. MAR23 -> 2023-03-01, without locale dependence."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, errors="coerce")

    raw = s.astype("string").str.strip().str.upper()
    month_map = {
        "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
        "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
        "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
    }
    mon = raw.str.extract(r"^([A-Z]{3})", expand=False).map(month_map)
    yr = raw.str.extract(r"(\d{2,4})$", expand=False)
    yr4 = yr.where(yr.str.len().eq(4), "20" + yr)
    manual = pd.to_datetime(yr4 + "-" + mon + "-01", errors="coerce")

    iso_like = raw.str.contains(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", na=False)
    fallback = pd.to_datetime(raw.where(iso_like), errors="coerce")
    return manual.combine_first(fallback)


def parse_smad_arch_dte(s):
    """Parse smad ARCH_DTE: datetime, MMDDYYYY, YYYYMMDD, or ISO-like."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, errors="coerce")

    raw = s.astype("string").str.strip()
    iso_like = raw.str.contains(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", na=False)
    direct = pd.to_datetime(raw.where(iso_like), errors="coerce")

    digits = (
        raw.str.replace(r"\.0$", "", regex=True)
           .str.replace(r"\D+", "", regex=True)
           .replace({"": pd.NA})
    )
    digits_z = digits.copy()
    short = digits_z.notna() & digits_z.str.len().lt(8)
    digits_z.loc[short] = digits_z.loc[short].str.zfill(8)
    digits8 = digits_z.where(digits_z.str.len().eq(8))

    dt_mdy = pd.to_datetime(digits8, format="%m%d%Y", errors="coerce")
    dt_ymd = pd.to_datetime(digits8, format="%Y%m%d", errors="coerce")
    parsed = dt_ymd.combine_first(dt_mdy) if dt_ymd.notna().sum() > dt_mdy.notna().sum() else dt_mdy.combine_first(dt_ymd)
    return direct.combine_first(parsed)


def choose_best_key_col(df, ref_key, preferred=None, label="table"):
    """Pick DUNS-like column with largest overlap with answer keys."""
    preferred = preferred or []
    preferred_existing = [c for c in preferred if c in df.columns]
    duns_like = [c for c in df.columns if "DUNS" in c.upper() and c not in preferred_existing]
    candidates = preferred_existing + duns_like

    if not candidates:
        raise KeyError(f"No DUNS-like columns found in {label}. Columns: {list(df.columns)[:50]}...")

    ref_set = set(ref_key.dropna().astype(str))
    rows = []
    for c in candidates:
        s = clean_key(df[c])
        vc = s.value_counts(dropna=True)
        rows.append({
            "col": c,
            "nonnull": int(s.notna().sum()),
            "nunique": int(s.nunique(dropna=True)),
            "max_rows_per_key": int(vc.iloc[0]) if len(vc) else 0,
            "overlap_unique_with_answer": len(set(s.dropna().astype(str)) & ref_set),
            "overlap_rows_with_answer": int(s.isin(ref_set).sum()),
        })

    diag = pd.DataFrame(rows).sort_values(
        ["overlap_unique_with_answer", "overlap_rows_with_answer", "nunique", "nonnull"],
        ascending=False,
    )
    print(f"\nDUNS key candidates for {label}:")
    print(diag.to_string(index=False))

    best = diag.iloc[0]["col"]
    print(f"Chosen {label} key: {best!r}")
    return best


def make_ohe():
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=True)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=True)


def choose_schema(df, candidate_cols, train_index):
    """
    Decide numeric vs categorical using training rows only.
    Builds X_all once to avoid DataFrame fragmentation.
    """
    col_data = {}
    numeric_cols = []
    categorical_cols = []
    dropped_reason = {}
    train_index = pd.Index(train_index)

    for c in candidate_cols:
        if c not in df.columns:
            dropped_reason[c] = "missing_column"
            continue

        s = df[c]

        if pd.api.types.is_datetime64_any_dtype(s):
            dropped_reason[c] = "raw_datetime"
            continue

        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            x = pd.to_numeric(s, errors="coerce").astype(float)
            if x.loc[train_index].nunique(dropna=True) <= 1:
                dropped_reason[c] = "constant_numeric"
                continue
            col_data[c] = x
            numeric_cols.append(c)
            continue

        txt = s.astype("string").str.strip()
        txt = txt.replace({
            "": pd.NA, "NAN": pd.NA, "nan": pd.NA, "NONE": pd.NA,
            "None": pd.NA, "NULL": pd.NA, "<NA>": pd.NA,
        })
        num_txt = (
            txt.str.replace(",", "", regex=False)
               .str.replace("$", "", regex=False)
               .str.replace("%", "", regex=False)
        )
        num = pd.to_numeric(num_txt, errors="coerce")

        train_txt = txt.loc[train_index]
        train_num = num.loc[train_index]
        nonnull_train = train_txt.notna()
        parse_rate = train_num[nonnull_train].notna().mean() if nonnull_train.any() else 0.0

        if parse_rate >= NUMERIC_PARSE_THRESHOLD:
            x = num.astype(float)
            if x.loc[train_index].nunique(dropna=True) <= 1:
                dropped_reason[c] = "constant_after_numeric_parse"
                continue
            col_data[c] = x
            numeric_cols.append(c)
            continue

        card = train_txt.nunique(dropna=True)
        if card <= 1:
            dropped_reason[c] = "constant_categorical"
            continue
        if card > MAX_CAT_CARDINALITY:
            dropped_reason[c] = f"high_cardinality_{card}"
            continue

        col_data[c] = txt.astype(object).where(txt.notna(), np.nan)
        categorical_cols.append(c)

    X_all = pd.DataFrame(col_data, index=df.index).copy() if col_data else pd.DataFrame(index=df.index)
    return X_all, numeric_cols, categorical_cols, dropped_reason


def print_dropped_summary(dropped_reason, title="Dropped feature summary", max_detail=50):
    print(f"\n{title}:")
    if not dropped_reason:
        print("none")
        return pd.DataFrame()

    detail = pd.DataFrame({
        "col": list(dropped_reason.keys()),
        "reason": list(dropped_reason.values()),
    })
    print("By reason:")
    print(detail["reason"].value_counts().to_string())

    high = detail[detail["reason"].str.startswith("high_cardinality", na=False)].copy()
    if len(high):
        print("\nHigh-cardinality dropped columns:")
        print(high.to_string(index=False))

    print("\nDropped detail, first rows:")
    print(detail.sort_values(["reason", "col"]).head(max_detail).to_string(index=False))
    return detail


def make_logistic_model(numeric_cols, categorical_cols, C):
    transformers = []
    if numeric_cols:
        num_pipe = Pipeline(steps=[
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scaler", StandardScaler(with_mean=False)),
        ])
        transformers.append(("num", num_pipe, numeric_cols))

    if categorical_cols:
        cat_pipe = Pipeline(steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value="__MISSING__")),
            ("onehot", make_ohe()),
        ])
        transformers.append(("cat", cat_pipe, categorical_cols))

    if not transformers:
        raise ValueError("No usable features after preprocessing.")

    pre = ColumnTransformer(transformers=transformers, remainder="drop")
    clf = LogisticRegression(
        max_iter=LOGISTIC_MAX_ITER,
        solver="liblinear",
        C=C,
        class_weight=None,
    )
    return Pipeline(steps=[("preprocess", pre), ("model", clf)])


def transformed_feature_count(fitted_model, X_sample):
    try:
        Xt = fitted_model.named_steps["preprocess"].transform(X_sample)
        return int(Xt.shape[1])
    except Exception as e:
        print(f"WARNING: could not compute transformed feature count: {e}")
        return np.nan


def temporal_purged_split(known_df, val_fraction=VALID_FRACTION):
    """
    One train/validation split only:
    - validation = later renew_date
    - training = earlier renew_date
    - purge DUNS keys appearing in validation from training
    """
    known_df = known_df[known_df["renew_dt"].notna()].copy()
    if len(known_df) == 0:
        raise ValueError("No known rows with valid renew_dt.")

    dates = known_df["renew_dt"].sort_values()
    cut_fracs = [1 - val_fraction, 0.70, 0.65, 0.60, 0.55, 0.50]
    best = None

    for frac in cut_fracs:
        pos = int(np.floor(len(dates) * frac))
        pos = max(0, min(pos, len(dates) - 1))
        cutoff = dates.iloc[pos]

        val_mask = known_df["renew_dt"] >= cutoff
        val_keys = set(known_df.loc[val_mask, "_k"].dropna())
        train_mask = (known_df["renew_dt"] < cutoff) & (~known_df["_k"].isin(val_keys))

        train_idx = known_df.index[train_mask]
        val_idx = known_df.index[val_mask]
        train_y = known_df.loc[train_idx, "y"]
        val_y = known_df.loc[val_idx, "y"]

        candidate = {
            "cutoff": cutoff,
            "train_idx": train_idx,
            "val_idx": val_idx,
            "train_n": len(train_idx),
            "val_n": len(val_idx),
            "train_classes": train_y.nunique(dropna=True),
            "val_classes": val_y.nunique(dropna=True),
        }
        if best is None or candidate["train_n"] > best["train_n"]:
            best = candidate
        if candidate["train_n"] >= 100 and candidate["val_n"] >= 50 and candidate["train_classes"] == 2 and candidate["val_classes"] == 2:
            return train_idx, val_idx, cutoff

    print("WARNING: Could not find an ideal temporal split. Using best available split.")
    return best["train_idx"], best["val_idx"], best["cutoff"]


def safe_metrics(y_true, pred, label):
    y_true = pd.Series(y_true).astype(int)
    pred = np.asarray(pred, dtype=float)
    pred = np.clip(pred, 1e-6, 1 - 1e-6)
    out = {
        "model": label,
        "n": len(y_true),
        "actual_rate": float(y_true.mean()),
        "pred_mean": float(np.mean(pred)),
        "LogLoss": float(log_loss(y_true, pred, labels=[0, 1])),
        "Brier": float(brier_score_loss(y_true, pred)),
        "Accuracy@0.5": float(accuracy_score(y_true, (pred >= 0.5).astype(int))),
    }
    if y_true.nunique() == 2:
        out["ROC_AUC"] = float(roc_auc_score(y_true, pred))
        out["AveragePrecision"] = float(average_precision_score(y_true, pred))
    else:
        out["ROC_AUC"] = np.nan
        out["AveragePrecision"] = np.nan
    return out


def print_metrics_table(metrics_rows):
    cols = ["model", "n", "actual_rate", "pred_mean", "ROC_AUC", "AveragePrecision", "LogLoss", "Brier", "Accuracy@0.5"]
    df = pd.DataFrame(metrics_rows)
    print(df[cols].sort_values(["LogLoss", "Brier"]).to_string(index=False))
    return df


def constant_prior_pred(p, n):
    return np.repeat(float(np.clip(p, 1e-6, 1 - 1e-6)), n)


def asof_prior_value(m, reference_idx, asof_date, window_days=None, min_n=MIN_RECENT_N, fallback=0.5):
    """One prior value as of a single date. No grouped/rolling training."""
    ref = m.loc[reference_idx]
    ref = ref[(ref["y"].notna()) & (ref["renew_dt"].notna()) & (ref["renew_dt"] < asof_date)]

    if len(ref) == 0:
        return float(fallback), 0, "neutral_prior_no_past_labels"

    if window_days is not None:
        start = asof_date - pd.Timedelta(days=int(window_days))
        recent = ref[ref["renew_dt"] >= start]
        if len(recent) >= min_n:
            return float(recent["y"].mean()), len(recent), f"recent_{window_days}d_prior"

    return float(ref["y"].mean()), len(ref), "all_past_prior"


def asof_attach_source(ans_base, src0, prefix, original_key_col, include_payload=False):
    """
    Per-answer-row as-of attach.
    For each answer row, find the source row with same _k and max dt <= renew_dt.
    This remains correct if a source table later contains multiple snapshots per DUNS.
    """
    left = ans_base[["_row_id", "_k", "renew_dt"]].copy()
    raw_keys = set(src0["_k"].dropna().astype(str))

    out = pd.DataFrame({"_row_id": ans_base["_row_id"].values})
    out[f"{prefix}_raw_match"] = ans_base["_k"].astype("string").isin(raw_keys).fillna(False).astype("int8").values

    payload_cols = []
    if include_payload:
        exclude = {"_k", "dt", "has_row", original_key_col}
        payload_cols = [c for c in src0.columns if c not in exclude]

    right_cols = ["_k", "dt"] + payload_cols
    right = src0.loc[src0["_k"].notna() & src0["dt"].notna(), right_cols].copy()
    left_valid = left.loc[left["_k"].notna() & left["renew_dt"].notna()].copy()

    if len(right) and len(left_valid):
        left_sorted = left_valid.sort_values(["renew_dt", "_k", "_row_id"])
        right_sorted = right.sort_values(["dt", "_k"])
        merged = pd.merge_asof(
            left_sorted,
            right_sorted,
            by="_k",
            left_on="renew_dt",
            right_on="dt",
            direction="backward",
            allow_exact_matches=True,
        )
        keep_cols = ["_row_id", "dt"] + payload_cols
        merged = merged[keep_cols].copy()
        rename = {"dt": f"{prefix}_dt"}
        rename.update({c: f"{prefix}_{c}" for c in payload_cols})
        merged = merged.rename(columns=rename)
        out = out.merge(merged, on="_row_id", how="left")
    else:
        out[f"{prefix}_dt"] = pd.NaT
        for c in payload_cols:
            out[f"{prefix}_{c}"] = np.nan

    out[f"{prefix}_available_at_renewal"] = out[f"{prefix}_dt"].notna().astype("int8")
    return out


def add_target_encoding_features(df, train_index, y_col, cols, smoothing=TARGET_ENCODING_SMOOTHING):
    """
    Leakage-safe target encoding:
    - fit category -> smoothed target mean on train_index only
    - apply mapping to all rows
    - unseen/missing categories get global train mean
    """
    train_index = pd.Index(train_index)
    y_train = df.loc[train_index, y_col].astype(float)
    global_mean = float(y_train.mean()) if y_train.notna().any() else 0.5

    te_df = pd.DataFrame(index=df.index)
    meta_rows = []

    for c in cols:
        if c not in df.columns:
            continue

        s_all = df[c].astype("string").str.strip().fillna("__MISSING__")
        s_train = s_all.loc[train_index]

        tmp = pd.DataFrame({"cat": s_train, "y": y_train}).dropna(subset=["y"])
        if len(tmp) == 0:
            te_df[f"te_{c}"] = global_mean
            meta_rows.append({"col": c, "n_categories_train": 0, "global_mean": global_mean})
            continue

        stats = tmp.groupby("cat")["y"].agg(["sum", "count"])
        enc = (stats["sum"] + smoothing * global_mean) / (stats["count"] + smoothing)

        te_df[f"te_{c}"] = s_all.map(enc).astype(float).fillna(global_mean)
        meta_rows.append({
            "col": c,
            "n_categories_train": int(stats.shape[0]),
            "min_count": int(stats["count"].min()),
            "max_count": int(stats["count"].max()),
            "global_mean": global_mean,
        })

    te_meta = pd.DataFrame(meta_rows)
    return te_df, te_meta


def build_feature_frame(df, base_candidate_cols, train_index, add_te=False, target_encode_cols=None):
    work = df.copy()
    candidate_cols = list(base_candidate_cols)
    te_meta = pd.DataFrame()

    if add_te and target_encode_cols:
        te_df, te_meta = add_target_encoding_features(
            df=work,
            train_index=train_index,
            y_col="y",
            cols=target_encode_cols,
            smoothing=TARGET_ENCODING_SMOOTHING,
        )
        for c in te_df.columns:
            work[c] = te_df[c]
        candidate_cols = candidate_cols + list(te_df.columns)

    X_all, numeric_cols, categorical_cols, dropped_reason = choose_schema(
        work,
        candidate_cols=candidate_cols,
        train_index=train_index,
    )
    return X_all, numeric_cols, categorical_cols, dropped_reason, te_meta


def bootstrap_metric_ci(y_true, pred, n_boot=BOOTSTRAP_N, seed=BOOTSTRAP_RANDOM_SEED):
    y_true = np.asarray(pd.Series(y_true).astype(int))
    pred = np.asarray(pred, dtype=float)
    n = len(y_true)
    rng = np.random.default_rng(seed)

    vals = {"LogLoss": [], "Brier": [], "ROC_AUC": []}
    idx = np.arange(n)

    for _ in range(n_boot):
        b = rng.choice(idx, size=n, replace=True)
        yb = y_true[b]
        pb = np.clip(pred[b], 1e-6, 1 - 1e-6)
        vals["LogLoss"].append(log_loss(yb, pb, labels=[0, 1]))
        vals["Brier"].append(brier_score_loss(yb, pb))
        if len(np.unique(yb)) == 2:
            vals["ROC_AUC"].append(roc_auc_score(yb, pb))

    rows = []
    for metric, arr in vals.items():
        if len(arr) == 0:
            rows.append({"metric": metric, "p2.5": np.nan, "p50": np.nan, "p97.5": np.nan})
        else:
            q = np.quantile(arr, [0.025, 0.5, 0.975])
            rows.append({"metric": metric, "p2.5": q[0], "p50": q[1], "p97.5": q[2]})
    return pd.DataFrame(rows)


# ----------------------------
# 2. Prepare answer table
# ----------------------------

ans0 = ans.copy()
ans0["_row_id"] = np.arange(len(ans0))

if ANS_K not in ans0.columns:
    raise KeyError(f"answer missing {ANS_K!r}")

ans0["_k"] = clean_key(ans0[ANS_K])
ans0["renew_dt"] = pd.to_datetime(ans0["renew_date"], errors="coerce")
ans0["y"] = to_binary_label(ans0["bound"])

for c in ["broker", "subline", "insured_country", "region", "industry_group"]:
    if c in ans0.columns:
        ans0[f"{c}_norm"] = clean_cat(ans0[c])

if "premium_band" in ans0.columns:
    ans0["premium_band_norm"] = ans0["premium_band"].astype("string").str.strip()

if "in_appetite" in ans0.columns:
    ans0["in_appetite_norm"] = (
        ans0["in_appetite"].astype("string").str.strip().str.upper().map({
            "TRUE": "1", "T": "1", "YES": "1", "Y": "1", "1": "1",
            "FALSE": "0", "F": "0", "NO": "0", "N": "0", "0": "0",
        })
    )

# Categorical timing only. No linear trend / no month_index by default.
ans0["renew_year_cat"] = "year_" + ans0["renew_dt"].dt.year.astype("Int64").astype("string")
ans0["renew_month_cat"] = "month_" + ans0["renew_dt"].dt.month.astype("Int64").astype("string")
ans0["renew_quarter_cat"] = "quarter_" + ans0["renew_dt"].dt.quarter.astype("Int64").astype("string")

print("\nAnswer label distribution:")
print(ans0["y"].value_counts(dropna=False).to_string())
print(f"known labels: {ans0['y'].notna().sum()}")
print(f"hidden labels: {ans0['y'].isna().sum()}")


# ----------------------------
# 3. Auto-detect external keys
# ----------------------------

ref_key = ans0["_k"]
CSAD_K = choose_best_key_col(csad, ref_key=ref_key, preferred=["DUNS_NUMBER", "DUNS"], label="csad")
SMAD_K = choose_best_key_col(smad, ref_key=ref_key, preferred=["DUNS@", "DUNS_NUMBER", "DUNS", "DUNS0", "DUNS185"], label="smad")


# ----------------------------
# 4. Prepare csad / smad and true as-of attach
# ----------------------------

csad0 = csad.copy()
csad0["_k"] = clean_key(csad0[CSAD_K])
csad0["dt"] = parse_csad_datepll(csad0["DATEPLL"]) if "DATEPLL" in csad0.columns else pd.NaT
csad0["has_row"] = 1
csad0 = csad0[csad0["_k"].notna()].copy()

smad0 = smad.copy()
smad0["_k"] = clean_key(smad0[SMAD_K])
smad0["dt"] = parse_smad_arch_dte(smad0["ARCH_DTE"]) if "ARCH_DTE" in smad0.columns else pd.NaT
smad0["has_row"] = 1
smad0 = smad0[smad0["_k"].notna()].copy()

print("\nExternal date ranges:")
print(f"csad dt range: {csad0['dt'].min()} -- {csad0['dt'].max()} | parse_rate={csad0['dt'].notna().mean():.3f}")
print(f"smad dt range: {smad0['dt'].min()} -- {smad0['dt'].max()} | parse_rate={smad0['dt'].notna().mean():.3f}")
print(f"csad duplicate key count before as-of: {csad0['_k'].duplicated().sum()}")
print(f"smad duplicate key count before as-of: {smad0['_k'].duplicated().sum()}")

csad_attach = asof_attach_source(ans0, csad0, prefix="csad", original_key_col=CSAD_K, include_payload=INCLUDE_EXTERNAL_PAYLOAD)
smad_attach = asof_attach_source(ans0, smad0, prefix="smad", original_key_col=SMAD_K, include_payload=INCLUDE_EXTERNAL_PAYLOAD)

m = (
    ans0
    .merge(csad_attach, on="_row_id", how="left", validate="1:1")
    .merge(smad_attach, on="_row_id", how="left", validate="1:1")
)

print("\nMerge diagnostics:")
print(f"answer rows: {len(ans0)}")
print(f"merged rows: {len(m)}")
if len(m) != len(ans0):
    raise RuntimeError("Merge changed row count. This indicates a bug in as-of attach.")

print("\nAvailability diagnostics, true as-of:")
for src in ["csad", "smad"]:
    print(f"rows with no raw {src} match: {(m[f'{src}_raw_match'] == 0).sum()}")
    print(f"rows with {src} available at renewal: {m[f'{src}_available_at_renewal'].sum()}")
    blocked = ((m[f"{src}_raw_match"] == 1) & (m[f"{src}_available_at_renewal"] == 0)).sum()
    print(f"rows where {src} matched but no as-of row was available: {blocked}")

print(f"rows with neither available: {((m['csad_available_at_renewal'] == 0) & (m['smad_available_at_renewal'] == 0)).sum()}")


# ----------------------------
# 5. Feature sets
# ----------------------------

answer_feature_cols = [
    c for c in [
        "broker_norm",
        "subline_norm",
        "insured_country_norm",
        "region_norm",
        "industry_group_norm",
        "in_appetite_norm",
        "renew_year_cat",
        "renew_month_cat",
        "renew_quarter_cat",
        "csad_available_at_renewal",
        "smad_available_at_renewal",
    ]
    if c in m.columns
]

if not DROP_PREMIUM_BAND and "premium_band_norm" in m.columns:
    answer_feature_cols.append("premium_band_norm")

# Only existing target-encoding columns are used.
target_encode_cols = [c for c in TARGET_ENCODE_COLS_BASE if c in m.columns]
if not DROP_PREMIUM_BAND and "premium_band_norm" in m.columns:
    target_encode_cols.append("premium_band_norm")

external_feature_cols = []
if INCLUDE_EXTERNAL_PAYLOAD:
    drop_exact = {
        "_row_id", "y", "bound", ANS_K, "_k", "renew_date", "renew_dt",
        "broker", "subline", "insured_country", "region", "industry_group",
        "premium_band", "in_appetite", "quarter", "year", "insured_name_scoring",
    }
    if DROP_PREMIUM_BAND:
        drop_exact.add("premium_band_norm")

    bad_feature_pattern = re.compile(
        r"(?:^|_)(duns|filler|telephone|phone|business_name|street_address|postal_code|zip_code|ingest|file_name|timestamp|as_of_date|datepll|arch_dte)(?:_|$)",
        flags=re.IGNORECASE,
    )
    for c in m.columns:
        if c in drop_exact or c in answer_feature_cols:
            continue
        if c.endswith("_dt"):
            continue
        if bad_feature_pattern.search(c):
            continue
        if c.startswith("csad_") or c.startswith("smad_"):
            external_feature_cols.append(c)

print("\nFeature set:")
print(f"answer/availability features: {len(answer_feature_cols)}")
print(answer_feature_cols)
print(f"target-encoded columns: {target_encode_cols}")
print(f"external payload features enabled: {INCLUDE_EXTERNAL_PAYLOAD}")
print(f"external payload feature count: {len(external_feature_cols)}")
print(f"DROP_PREMIUM_BAND = {DROP_PREMIUM_BAND}")


# ----------------------------
# 6. One temporal validation split
# ----------------------------

known = m[m["y"].notna()].copy()
hidden = m[m["y"].isna()].copy()

train_idx, val_idx, cutoff = temporal_purged_split(known, val_fraction=VALID_FRACTION)
train_y = m.loc[train_idx, "y"].astype(int)
val_y = m.loc[val_idx, "y"].astype(int)

print("\nTemporal + DUNS-purged validation split:")
print(f"cutoff date: {cutoff}")
print(f"train rows: {len(train_idx)}")
print(f"valid rows: {len(val_idx)}")
print(f"train y mean: {train_y.mean():.4f}")
print(f"valid y mean: {val_y.mean():.4f}")
print(f"train date range: {m.loc[train_idx, 'renew_dt'].min()} -- {m.loc[train_idx, 'renew_dt'].max()}")
print(f"valid date range: {m.loc[val_idx, 'renew_dt'].min()} -- {m.loc[val_idx, 'renew_dt'].max()}")
overlap_keys = set(m.loc[train_idx, "_k"].dropna()) & set(m.loc[val_idx, "_k"].dropna())
print(f"overlapping DUNS keys train/valid: {len(overlap_keys)}")


# ----------------------------
# 7. Prepare feature matrices
# ----------------------------

# OHE-only answer features.
X_ohe, num_ohe, cat_ohe, drop_ohe, te_meta_ohe = build_feature_frame(
    m,
    base_candidate_cols=answer_feature_cols,
    train_index=train_idx,
    add_te=False,
    target_encode_cols=None,
)
used_ohe = num_ohe + cat_ohe
print("\nAnswer OHE schema:")
print(f"numeric cols: {len(num_ohe)}")
print(f"categorical cols: {len(cat_ohe)}")
print(f"used cols: {used_ohe}")
print_dropped_summary(drop_ohe, title="Answer OHE dropped summary")

# Answer features + train-only target encodings.
if ADD_TARGET_ENCODING:
    X_te, num_te, cat_te, drop_te, te_meta = build_feature_frame(
        m,
        base_candidate_cols=answer_feature_cols,
        train_index=train_idx,
        add_te=True,
        target_encode_cols=target_encode_cols,
    )
    used_te = num_te + cat_te
    print("\nAnswer + target encoding schema:")
    print(f"numeric cols: {len(num_te)}")
    print(f"categorical cols: {len(cat_te)}")
    print(f"used cols: {used_te}")
    print("\nTarget encoding metadata:")
    display_or_print(te_meta)
    print_dropped_summary(drop_te, title="Answer + TE dropped summary")
else:
    X_te, num_te, cat_te, used_te, te_meta = None, [], [], [], pd.DataFrame()

# Optional full external payload matrix.
if INCLUDE_EXTERNAL_PAYLOAD and external_feature_cols:
    full_cols = answer_feature_cols + external_feature_cols
    X_full, num_full, cat_full, drop_full, te_meta_full = build_feature_frame(
        m,
        base_candidate_cols=full_cols,
        train_index=train_idx,
        add_te=ADD_TARGET_ENCODING,
        target_encode_cols=target_encode_cols,
    )
    used_full = num_full + cat_full
    print("\nFull external schema:")
    print(f"numeric cols: {len(num_full)}")
    print(f"categorical cols: {len(cat_full)}")
    print_dropped_summary(drop_full, title="Full external dropped summary")
else:
    X_full, num_full, cat_full, used_full = None, [], [], []


# ----------------------------
# 8. Fast model comparison
# ----------------------------

metrics_rows = []
val_predictions = {}
model_specs = {}

# A. Train prior.
train_prior = float(train_y.mean())
p_train_prior = constant_prior_pred(train_prior, len(val_y))
val_predictions["train_prior"] = p_train_prior
model_specs["train_prior"] = {"type": "prior", "kind": "train_prior"}
metrics_rows.append(safe_metrics(val_y, p_train_prior, "train_prior"))

# B. Recent priors as of validation cutoff. One constant prediction per model.
for days in RECENT_WINDOWS_DAYS:
    p_recent, n_recent, src = asof_prior_value(
        m=m,
        reference_idx=train_idx,
        asof_date=cutoff,
        window_days=days,
        min_n=MIN_RECENT_N,
        fallback=train_prior,
    )
    label = f"recent_{days}d_prior_n={n_recent}"
    p_vec = constant_prior_pred(p_recent, len(val_y))
    val_predictions[label] = p_vec
    model_specs[label] = {"type": "prior", "kind": "recent", "days": days}
    metrics_rows.append(safe_metrics(val_y, p_vec, label))

# C. OHE logistic C sweep.
for C in LOGISTIC_C_GRID:
    label = f"answer_ohe_logistic_C={C}"
    mdl = make_logistic_model(num_ohe, cat_ohe, C=C)
    mdl.fit(X_ohe.loc[train_idx, used_ohe], train_y)
    p = mdl.predict_proba(X_ohe.loc[val_idx, used_ohe])[:, 1]
    val_predictions[label] = p
    model_specs[label] = {"type": "logistic", "feature_mode": "ohe", "C": C}
    row = safe_metrics(val_y, p, label)
    row["transformed_feature_count"] = transformed_feature_count(mdl, X_ohe.loc[train_idx, used_ohe])
    metrics_rows.append(row)

# D. Target-encoded logistic C sweep.
if ADD_TARGET_ENCODING and X_te is not None and used_te:
    for C in LOGISTIC_C_GRID:
        label = f"answer_te_logistic_C={C}"
        mdl = make_logistic_model(num_te, cat_te, C=C)
        mdl.fit(X_te.loc[train_idx, used_te], train_y)
        p = mdl.predict_proba(X_te.loc[val_idx, used_te])[:, 1]
        val_predictions[label] = p
        model_specs[label] = {"type": "logistic", "feature_mode": "te", "C": C}
        row = safe_metrics(val_y, p, label)
        row["transformed_feature_count"] = transformed_feature_count(mdl, X_te.loc[train_idx, used_te])
        metrics_rows.append(row)

# E. Optional full external logistic. One fit per C only if explicitly enabled.
if INCLUDE_EXTERNAL_PAYLOAD and X_full is not None and used_full:
    for C in LOGISTIC_C_GRID:
        label = f"full_external_logistic_C={C}"
        mdl = make_logistic_model(num_full, cat_full, C=C)
        mdl.fit(X_full.loc[train_idx, used_full], train_y)
        p = mdl.predict_proba(X_full.loc[val_idx, used_full])[:, 1]
        val_predictions[label] = p
        model_specs[label] = {"type": "logistic", "feature_mode": "full", "C": C}
        row = safe_metrics(val_y, p, label)
        row["transformed_feature_count"] = transformed_feature_count(mdl, X_full.loc[train_idx, used_full])
        metrics_rows.append(row)

# F. Blend best logistic with best recent prior. No grouped training.
metrics_tmp = pd.DataFrame(metrics_rows)
recent_labels = [mname for mname in val_predictions if mname.startswith("recent_")]
logistic_labels = [mname for mname, spec in model_specs.items() if spec["type"] == "logistic"]

if recent_labels and logistic_labels:
    best_recent_label = metrics_tmp[metrics_tmp["model"].isin(recent_labels)].sort_values(["LogLoss", "Brier"]).iloc[0]["model"]
    best_logistic_label = metrics_tmp[metrics_tmp["model"].isin(logistic_labels)].sort_values(["LogLoss", "Brier"]).iloc[0]["model"]
    p_best_recent = val_predictions[best_recent_label]
    p_best_logistic = val_predictions[best_logistic_label]

    for w in [0.25, 0.50, 0.75]:
        p_blend = w * p_best_logistic + (1 - w) * p_best_recent
        label = f"blend_w{w:.2f}__{best_logistic_label}__{best_recent_label}"
        val_predictions[label] = p_blend
        model_specs[label] = {
            "type": "blend",
            "w": w,
            "logistic_label": best_logistic_label,
            "prior_label": best_recent_label,
        }
        metrics_rows.append(safe_metrics(val_y, p_blend, label))

print("\nValidation model comparison, sorted by LogLoss:")
metrics_df = print_metrics_table(metrics_rows)
BEST_MODEL_LABEL = metrics_df.sort_values(["LogLoss", "Brier"]).iloc[0]["model"]
print(f"\nSelected fast v3 baseline by validation LogLoss: {BEST_MODEL_LABEL}")

# Print feature/sample ratio for logistic candidates.
feature_ratio_rows = []
for row in metrics_rows:
    if "transformed_feature_count" in row and pd.notna(row["transformed_feature_count"]):
        n_features = row["transformed_feature_count"]
        feature_ratio_rows.append({
            "model": row["model"],
            "train_rows": len(train_idx),
            "transformed_features": int(n_features),
            "rows_per_feature": len(train_idx) / max(1, n_features),
        })
if feature_ratio_rows:
    print("\nTraining rows per transformed feature, logistic candidates:")
    ratio_df = pd.DataFrame(feature_ratio_rows).sort_values("rows_per_feature")
    print(ratio_df.to_string(index=False))
    low_ratio = ratio_df["rows_per_feature"].min()
    if low_ratio < MIN_SAMPLE_PER_TRANSFORMED_FEATURE:
        print(f"WARNING: minimum rows_per_feature={low_ratio:.2f}, below threshold {MIN_SAMPLE_PER_TRANSFORMED_FEATURE}.")


# ----------------------------
# 9. Bootstrap CI and diagnostics only
# ----------------------------

selected_val_pred = val_predictions[BEST_MODEL_LABEL]

if DO_BOOTSTRAP_CI:
    print("\nBootstrap CI for top validation models, reporting only:")
    top_labels = metrics_df.sort_values(["LogLoss", "Brier"]).head(5)["model"].tolist()
    ci_rows = []
    for label in top_labels:
        ci = bootstrap_metric_ci(val_y, val_predictions[label], n_boot=BOOTSTRAP_N, seed=BOOTSTRAP_RANDOM_SEED)
        ci["model"] = label
        ci_rows.append(ci)
    ci_df = pd.concat(ci_rows, ignore_index=True)
    print(ci_df[["model", "metric", "p2.5", "p50", "p97.5"]].to_string(index=False))

if DO_SEGMENTED_REPORT:
    val_frame = m.loc[val_idx, ["renew_year_cat", "csad_available_at_renewal", "smad_available_at_renewal"]].copy()
    val_frame["y"] = val_y.values
    val_frame["pred"] = selected_val_pred

    print("\nSelected baseline segmented AUC by external availability, reporting only:")
    for keys, g in val_frame.groupby(["csad_available_at_renewal", "smad_available_at_renewal"]):
        if len(g) < 10:
            continue
        if g["y"].nunique() < 2:
            print(f"csad={keys[0]} smad={keys[1]}: n={len(g)}, AUC=NA one-class")
        else:
            print(
                f"csad={keys[0]} smad={keys[1]}: "
                f"n={len(g)}, actual_rate={g['y'].mean():.3f}, "
                f"pred_mean={g['pred'].mean():.3f}, AUC={roc_auc_score(g['y'], g['pred']):.3f}"
            )

    print("\nSelected baseline segmented AUC by renew_year_cat, reporting only:")
    for yr, g in val_frame.groupby("renew_year_cat"):
        if pd.isna(yr) or len(g) < 10:
            continue
        if g["y"].nunique() < 2:
            print(f"{yr}: n={len(g)}, AUC=NA one-class")
        else:
            print(
                f"{yr}: n={len(g)}, actual_rate={g['y'].mean():.3f}, "
                f"pred_mean={g['pred'].mean():.3f}, AUC={roc_auc_score(g['y'], g['pred']):.3f}"
            )

if DO_CALIBRATION_TABLE:
    print("\nCalibration table for selected baseline, quantile bins:")
    if val_y.nunique() == 2 and len(val_y) >= 20:
        n_bins = min(10, max(2, len(val_y) // 20))
        prob_true, prob_pred_bin = calibration_curve(val_y, selected_val_pred, n_bins=n_bins, strategy="quantile")
        calib = pd.DataFrame({
            "mean_predicted_probability": prob_pred_bin,
            "actual_bound_rate": prob_true,
        })
        print(calib.to_string(index=False))
    else:
        print("Not enough validation data for calibration table.")


# ----------------------------
# 10. Hidden prediction, one final fit at most
# ----------------------------
# No per-hidden-date training. No month/quarter/date-grouped training.

hidden_pred = pd.Series(index=hidden.index, dtype=float)
hidden_pred_source = pd.Series(index=hidden.index, dtype=object)

if len(hidden) == 0:
    print("\nNo hidden rows to predict.")
else:
    hidden_min_dt = hidden["renew_dt"].min()
    hidden_max_dt = hidden["renew_dt"].max()
    known_max_dt = known["renew_dt"].max()

    print("\nHidden rows:")
    print(f"hidden n: {len(hidden)}")
    print(f"hidden date range: {hidden_min_dt} -- {hidden_max_dt}")
    print(f"known max renew_dt: {known_max_dt}")

    hidden_all_after_known = pd.notna(hidden_min_dt) and pd.notna(known_max_dt) and hidden_min_dt > known_max_dt
    print(f"hidden all after known labels: {hidden_all_after_known}")

    if pd.isna(hidden_min_dt):
        final_train_idx = known.index
        final_asof_note = "missing_hidden_min_dt_use_all_known"
    elif hidden_all_after_known:
        final_train_idx = known.index
        final_asof_note = "all_known_before_hidden"
    else:
        final_train_idx = known.index[known["renew_dt"] < hidden_min_dt]
        final_asof_note = "known_before_earliest_hidden"

    final_y = m.loc[final_train_idx, "y"].dropna().astype(int)
    print(f"final training mode: {final_asof_note}")
    print(f"final training rows: {len(final_train_idx)}")
    print(f"final training y mean: {final_y.mean() if len(final_y) else np.nan:.4f}")

    hidden_prior_fallback = float(known["y"].mean()) if known["y"].notna().any() else 0.5
    hidden_prior_asof = hidden_min_dt if pd.notna(hidden_min_dt) else (known_max_dt + pd.Timedelta(days=1))

    def hidden_prior_for_spec(spec):
        days = spec.get("days")
        p, n_used, src = asof_prior_value(
            m=m,
            reference_idx=final_train_idx,
            asof_date=hidden_prior_asof,
            window_days=days,
            min_n=MIN_RECENT_N,
            fallback=hidden_prior_fallback,
        )
        return pd.Series(constant_prior_pred(p, len(hidden)), index=hidden.index), f"{src}_n={n_used}"

    def fit_predict_hidden_logistic(spec):
        feature_mode = spec["feature_mode"]
        C = spec["C"]

        if feature_mode == "ohe":
            X_final, num_final, cat_final, drop_final, te_meta_final = build_feature_frame(
                m,
                base_candidate_cols=answer_feature_cols,
                train_index=final_train_idx,
                add_te=False,
                target_encode_cols=None,
            )
        elif feature_mode == "te":
            X_final, num_final, cat_final, drop_final, te_meta_final = build_feature_frame(
                m,
                base_candidate_cols=answer_feature_cols,
                train_index=final_train_idx,
                add_te=True,
                target_encode_cols=target_encode_cols,
            )
        elif feature_mode == "full" and INCLUDE_EXTERNAL_PAYLOAD:
            full_cols = answer_feature_cols + external_feature_cols
            X_final, num_final, cat_final, drop_final, te_meta_final = build_feature_frame(
                m,
                base_candidate_cols=full_cols,
                train_index=final_train_idx,
                add_te=ADD_TARGET_ENCODING,
                target_encode_cols=target_encode_cols,
            )
        else:
            raise ValueError(f"Unsupported final feature_mode={feature_mode}")

        used_final = num_final + cat_final
        final_model = make_logistic_model(num_final, cat_final, C=C)
        final_model.fit(X_final.loc[final_train_idx, used_final], final_y)
        n_features = transformed_feature_count(final_model, X_final.loc[final_train_idx, used_final])
        ratio = len(final_train_idx) / max(1, n_features) if pd.notna(n_features) else np.nan
        print(f"final logistic transformed features: {n_features}")
        print(f"final logistic rows_per_feature: {ratio:.2f}")
        if pd.notna(ratio) and ratio < MIN_SAMPLE_PER_TRANSFORMED_FEATURE:
            print(f"WARNING: final rows_per_feature={ratio:.2f}, below threshold {MIN_SAMPLE_PER_TRANSFORMED_FEATURE}.")

        pred = pd.Series(
            final_model.predict_proba(X_final.loc[hidden.index, used_final])[:, 1],
            index=hidden.index,
        )
        return pred, f"single_final_{feature_mode}_logistic_C={C}_{final_asof_note}_n={len(final_train_idx)}"

    spec = model_specs[BEST_MODEL_LABEL]

    if len(final_train_idx) < MIN_FINAL_TRAIN_ROWS or final_y.nunique() < 2:
        print("WARNING: insufficient final training labels. Using all-past prior only.")
        p_prior, src = hidden_prior_for_spec({"type": "prior", "kind": "train_prior", "days": None})
        hidden_pred.loc[hidden.index] = p_prior.loc[hidden.index]
        hidden_pred_source.loc[hidden.index] = src

    elif spec["type"] == "prior":
        p_prior, src = hidden_prior_for_spec(spec)
        hidden_pred.loc[hidden.index] = p_prior.loc[hidden.index]
        hidden_pred_source.loc[hidden.index] = src

    elif spec["type"] == "logistic":
        p_model, src = fit_predict_hidden_logistic(spec)
        hidden_pred.loc[hidden.index] = p_model.loc[hidden.index]
        hidden_pred_source.loc[hidden.index] = src

    elif spec["type"] == "blend":
        w = spec["w"]
        logistic_spec = model_specs[spec["logistic_label"]]
        prior_spec = model_specs[spec["prior_label"]]
        p_model, model_src = fit_predict_hidden_logistic(logistic_spec)
        p_prior, prior_src = hidden_prior_for_spec(prior_spec)
        hidden_pred.loc[hidden.index] = w * p_model.loc[hidden.index] + (1 - w) * p_prior.loc[hidden.index]
        hidden_pred_source.loc[hidden.index] = f"blend_w={w:.2f}_{model_src}_plus_{prior_src}"

    else:
        print(f"WARNING: unrecognized BEST_MODEL_LABEL={BEST_MODEL_LABEL}. Using 180d prior.")
        p_prior, src = hidden_prior_for_spec({"type": "prior", "kind": "recent", "days": 180})
        hidden_pred.loc[hidden.index] = p_prior.loc[hidden.index]
        hidden_pred_source.loc[hidden.index] = src

    output_cols = [
        "_row_id", ANS_K, "renew_date", "broker", "subline", "insured_country",
        "region", "industry_group", "premium_band", "in_appetite",
        "csad_available_at_renewal", "smad_available_at_renewal",
    ]
    output_cols = [c for c in output_cols if c in m.columns]

    bound_fast_v3_predictions = m.loc[hidden.index, output_cols].copy()
    bound_fast_v3_predictions["pred_bound_proba"] = hidden_pred.loc[hidden.index].values
    bound_fast_v3_predictions["pred_bound_label_05"] = (bound_fast_v3_predictions["pred_bound_proba"] >= 0.5).astype(int)
    bound_fast_v3_predictions["prediction_source"] = hidden_pred_source.loc[hidden.index].values
    bound_fast_v3_predictions = bound_fast_v3_predictions.sort_values("pred_bound_proba", ascending=False)

    print("\nHidden prediction probability summary:")
    print(bound_fast_v3_predictions["pred_bound_proba"].describe().to_string())

    print("\nPrediction source counts:")
    print(bound_fast_v3_predictions["prediction_source"].value_counts().to_string())

    print("\nTop hidden predictions:")
    display_or_print(bound_fast_v3_predictions.head(30))

    # Optional save path for Databricks:
    # bound_fast_v3_predictions.to_csv("/dbfs/FileStore/bound_fast_v3_predictions.csv", index=False)
